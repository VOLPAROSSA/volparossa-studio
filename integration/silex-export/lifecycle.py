# SPDX-License-Identifier: GPL-3.0-only
"""Bounded process-group termination independent of the leader's exit status."""
import os
from dataclasses import dataclass
from pathlib import Path
import signal
import subprocess
import time


@dataclass(frozen=True)
class OwnedGroup:
    pgids: tuple
    sids: tuple

    @property
    def depth(self):
        return len(self.pgids) - 1

    @property
    def group(self):
        return self.pgids[-1]


def status_fields(status):
    return dict(line.split(':', 1) for line in status.splitlines() if ':' in line)


def member_in_namespace(status, identity):
    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
    if fields['State'].split()[0] in ('Z', 'X', 'x'):
        return None
    pid, pgid, sid = (list(map(int, fields[name].split())) for name in ('NSpid', 'NSpgid', 'NSsid'))
    depth = identity.depth
    if min(len(pid), len(pgid), len(sid)) <= depth:
        return None  # A process outside our PID namespace is not our child.
    # Full ancestor prefixes bind the actual owned group/session. A sibling PID
    # namespace can reuse the same inner IDs and depth, but not these prefixes.
    if tuple(pgid[:depth + 1]) != identity.pgids or tuple(sid[:depth + 1]) != identity.sids:
        return None
    return pid[depth]


def capture_group(process):
    """Capture the unreaped direct leader before poll/wait can erase identity."""
    own = status_fields(Path('/proc/self/status').read_text())
    own_pids = list(map(int, own['NSpid'].split()))
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = status_fields((entry / 'status').read_text())
        except (FileNotFoundError, ProcessLookupError):
            continue
        pids = list(map(int, fields['NSpid'].split()))
        # PPid is expressed in the procfs mount's namespace, like NSpid[0].
        # This direct-parent anchor excludes equal-depth sibling namespaces.
        if (int(fields['PPid']) != own_pids[0] or len(pids) != len(own_pids)
                or pids[-1] != process.pid):
            continue
        pgids, sids = (tuple(map(int, fields[key].split())) for key in ('NSpgid', 'NSsid'))
        if len(pgids) != len(own_pids) or len(sids) != len(own_pids):
            raise RuntimeError('owned group namespace vectors unavailable')
        if pgids[-1] != process.pid or sids[-1] != process.pid:
            raise RuntimeError('child is not its new session/group leader')
        return OwnedGroup(pgids, sids)
    raise RuntimeError('unreaped direct group leader identity unavailable')


class GroupCaptureFailure(RuntimeError):
    def __init__(self, exit_code):
        self.exit_code = exit_code
        super().__init__('owned group capture failed')


def start_group(command, **options):
    process = subprocess.Popen(command, start_new_session=True, **options)
    try:
        identity = capture_group(process)
    except Exception:
        # The direct child has not been reaped: its PID cannot be reused. This
        # fixed group was created by our own Popen; fail closed without claiming
        # an identity or successful drain when procfs cannot establish it.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=1)
        if process.stdout is not None:
            process.stdout.close()
        raise GroupCaptureFailure(process.returncode) from None
    return process, identity


def live_group_members(identity):
    """Linux process identities in our session/group; zombies cannot execute."""
    # Core's wrapper does not remount procfs. Its stat/PID directory names may
    # therefore refer to an ancestor namespace. The NS* vectors select IDs in
    # this interpreter's namespace, including nested browser namespaces.
    members = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            status = (entry / 'status').read_text()
        except (FileNotFoundError, ProcessLookupError):
            continue
        pid = member_in_namespace(status, identity)
        if pid is not None:
            members.append(pid)
    return members


def drain_group(process, identity, grace=1.0, kill_grace=1.0):
    """Only for Popen(start_new_session=True) children; join leader and drain group."""
    group = identity.group
    if group != process.pid:
        raise ValueError('group does not match captured owned leader')
    if group <= 1 or group == os.getpgrp():
        raise ValueError('refuse caller process group')

    def send(sig):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            pass

    def drained_until(deadline):
        while True:
            process.poll()  # Reap our direct child; orphan zombies are not live.
            if not live_group_members(identity):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    send(signal.SIGTERM)
    drained = drained_until(time.monotonic() + grace)
    escalated = not drained
    if not drained:
        # Escalate even if the leader already exited and wait() would succeed.
        send(signal.SIGKILL)
        drained = drained_until(time.monotonic() + kill_grace)
    try:
        process.wait(timeout=kill_grace)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('leader join deadline') from error
    if not drained:
        raise TimeoutError('live process group drain deadline')
    return {'leader_joined': True, 'live_group_drained': True, 'kill_escalated': escalated}
