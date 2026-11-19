# SPDX-License-Identifier: GPL-3.0-only
"""Public HTTP/Chrome CRUD only, inside the pinned NET+PID namespace wrapper."""
import errno
import hashlib
import importlib.util
import os
from pathlib import Path
import resource
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def protocol():
    path = Path(__file__).resolve().with_name('crud_protocol.py')
    spec = importlib.util.spec_from_file_location('crud_runtime_protocol', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fields(raw):
    return dict(line.split(':', 1) for line in raw.decode('utf-8', errors='strict').splitlines() if ':' in line)


def proc_rows(p, deadline):
    rows = {}
    with os.scandir('/proc') as entries:
        for entry in entries:
            p.require(time.monotonic() < deadline and len(rows) < 4096)
            if not entry.name.isdecimal():
                continue
            try:
                with open(Path(entry.path) / 'status', 'rb') as stream:
                    raw = stream.read(16385)
            except (FileNotFoundError, ProcessLookupError):
                continue
            p.require(len(raw) <= 16384)
            row = fields(raw)
            if all(key in row for key in ('NSpid', 'NSpgid', 'NSsid', 'PPid', 'State')):
                rows[int(entry.name)] = row
    return rows


def vector(row, name):
    return tuple(map(int, row[name].split()))


class Child:
    """Own the unreaped leader through the last group signal, including exit 0."""
    def __init__(self, p, command, env, root, label, deadline):
        self.p, self.deadline, self.joined, self.log = p, deadline, False, None
        self.escalated = False
        self.process = None
        self.pgids = self.sids = None
        self.log = open(root / (label + '.log'), 'xb')
        os.fchmod(self.log.fileno(), 0o600)
        try:
            self.process = subprocess.Popen(list(map(str, command)), env=env, cwd=root,
                stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, start_new_session=True)
            own = fields(Path('/proc/self/status').read_bytes())
            for row in proc_rows(p, deadline).values():
                pid = vector(row, 'NSpid')
                if (int(row['PPid']) == vector(own, 'NSpid')[0]
                        and len(pid) == len(vector(own, 'NSpid')) and pid[-1] == self.process.pid):
                    self.pgids, self.sids = vector(row, 'NSpgid'), vector(row, 'NSsid')
                    p.require(self.pgids[-1] == self.sids[-1] == self.process.pid)
                    break
            p.require(self.pgids is not None)
        except BaseException as primary:
            if self.process is not None:
                # The directly created child is still unreaped and cannot be reused.
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    self.process.wait(timeout=1)
                except BaseException:
                    pass
            try:
                self.log.close()
            except BaseException:
                pass
            raise primary

    def status(self):
        return os.waitid(os.P_PID, self.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)

    def wait(self, end):
        while self.status() is None:
            self.p.require(time.monotonic() < min(end, self.deadline - 6))
            time.sleep(0.02)
        status = self.status()
        self.p.require(status.si_code == os.CLD_EXITED and status.si_status == 0)

    def live(self):
        depth = len(self.pgids)
        for row in proc_rows(self.p, self.deadline).values():
            if (row['State'].split()[0] not in ('Z', 'X', 'x')
                    and vector(row, 'NSpgid')[:depth] == self.pgids
                    and vector(row, 'NSsid')[:depth] == self.sids):
                return True
        return False

    def close(self):
        if self.joined:
            return
        try:
            for number in (signal.SIGTERM, signal.SIGKILL):
                self.p.require(time.monotonic() < self.deadline - 0.5)
                self.escalated |= number == signal.SIGKILL
                try:
                    os.killpg(self.process.pid, number)
                except ProcessLookupError:
                    pass
                end = min(self.deadline - 0.5, time.monotonic() + 0.7)
                while self.live() and time.monotonic() < end:
                    time.sleep(0.02)
                if not self.live():
                    break
            self.p.require(not self.live())
            self.process.wait(timeout=max(0.01, min(0.5, self.deadline - time.monotonic())))
            self.joined = True
        finally:
            self.log.close()


def descendants(rows, anchor):
    owned = set()
    changed = True
    while changed:
        changed = False
        for pid, row in rows.items():
            if pid != anchor and pid not in owned and int(row['PPid']) in owned | {anchor}:
                owned.add(pid)
                changed = True
        if len(owned) > 256:
            raise ValueError('fixture descendant bound')
    return owned


def drain_descendants(p, deadline):
    own = vector(fields(Path('/proc/self/status').read_bytes()), 'NSpid')
    # PID1 adopts browser sessions that escaped the directly owned group.
    for number in (signal.SIGTERM, signal.SIGKILL):
        end = min(deadline, time.monotonic() + 0.7)
        while time.monotonic() < end:
            rows = proc_rows(p, deadline)
            live = []
            for host_pid in descendants(rows, own[0]):
                row = rows[host_pid]
                ids = vector(row, 'NSpid')
                p.require(len(ids) >= len(own) and ids[len(own) - 1] > 1)
                if row['State'].split()[0] not in ('Z', 'X', 'x'):
                    live.append(ids[len(own) - 1])
            for pid in live:
                try:
                    os.kill(pid, number)
                except ProcessLookupError:
                    pass
            while True:
                try:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                    if pid == 0:
                        break
                except ChildProcessError:
                    break
            if not live:
                return True
            time.sleep(0.02)
    return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def denials(p, origin, root, end, diagnostic):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    count = 0
    for identifier in ('', '..', '../outside', '/absolute', str(root / 'outside'), 'safe/../outside', '%2Foutside'):
        for method, path, body in (('GET', '/api/website/meta', None),
                ('POST', '/api/website/rename', b'{"name":"PUBLIC denied"}'),
                ('DELETE', '/api/website', None), ('GET', '/api/website', None),
                ('POST', '/api/website', b'{}'), ('POST', '/api/website/duplicate', None)):
            p.require(time.monotonic() < end)
            query = urllib.parse.urlencode(dict(websiteId=identifier, connectorId='fs-storage'))
            request = urllib.request.Request(origin + path + '?' + query, method=method,
                data=body, headers={'Content-Type': 'application/json'})
            try:
                response = opener.open(request, timeout=min(1, max(0.01, end - time.monotonic())))
            except urllib.error.HTTPError as error:
                response = error
            with response:
                diagnostic.update(case_id=count, http_status=response.status)
                p.require(response.status == 400 and len(response.read(4097)) <= 4096)
            count += 1
    return count


def pre_isolation(p):
    p.require(os.getpid() == 1 and os.getuid() == os.geteuid() != 0
              and os.getgid() == os.getegid() != 0 and not os.getgroups())
    row = fields(Path('/proc/self/status').read_bytes())
    p.require(tuple(map(int, row['Uid'].split())) == (os.getuid(),) * 4
        and tuple(map(int, row['Gid'].split())) == (os.getgid(),) * 4)
    p.require(row['NoNewPrivs'].strip() == '1' and all(int(row[k].strip(), 16) == 0
        for k in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')))
    parent = os.environ.get('VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS', '')
    p.require(parent.startswith('net:[') and os.readlink('/proc/self/ns/net') != parent)


def isolation(p, value):
    pre_isolation(p)
    p.require(os.getuid() == value['uid'] and os.getgid() == value['gid'])
    p.require(os.readlink('/proc/self/ns/net') != value['parent_net']
        and os.readlink('/proc/self/ns/pid') != value['parent_pid']
        and os.environ.get('VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS') == value['parent_net'])
    devices = Path('/proc/self/net/dev').read_bytes()
    p.require(len(devices) <= 16384 and [line.split(b':', 1)[0].strip()
        for line in devices.splitlines() if b':' in line] == [b'lo'])
    routes = Path('/proc/net/route').read_bytes()
    p.require(len(routes) <= 16384 and (routes == b'' or (len(routes.splitlines()) == 1
        and routes.split() == b'Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT'.split())))
    routes6 = Path('/proc/net/ipv6_route').read_bytes()
    p.require(len(routes6) <= 16384 and all(line.split()[-1] == b'lo' for line in routes6.splitlines() if line.strip()))


def main():
    started = time.monotonic()
    p = protocol()
    root = Path(__file__).resolve().parent.parent
    p.require(sys.argv == [str(root / 'fixture/runtime.py')] and sys.flags.dont_write_bytecode == 1)
    pre_isolation(p)  # No private handoff is read before the wrapper boundary.
    value = p.context(p.decode(p.read(root / 'runtime-context.json')), root)
    isolation(p, value)
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024,) * 2)
    deadline = started + 108
    work_end = deadline - 12
    children = []
    ports = []
    primary = None
    report = dict(schema=1, status='failed', stage='admission', runtime_revision=value['revision'],
        isolated_net=True, isolated_pid=True, original_nonroot_uid=True, capabilities_zero=True,
        no_new_privileges=True, mount_isolation_proven=False, ipc_isolation_proven=False,
        proc_mount_isolation_proven=False, denied_egress_containment=True,
        no_external_attempts_proven=False, server_runs=0, browser_runs=0,
        browser_receipts=[], http_denials=0, outside_unchanged=False, persistence=False,
        owned_groups_started=0, owned_groups_joined=False, descendants_gone=False,
        listeners_closed=False, assets_unchanged=False, public_fixture_only=True,
        first_failure=None, log_observations=[])
    denial_diagnostic = {}
    env = dict(PATH='/usr/bin:/bin', LANG='C', LC_ALL='C', HOME=str(root / 'home'),
               TMPDIR=str(root / 'tmp'), XDG_CACHE_HOME=str(root / 'home/cache'),
               PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1', DO_NOT_TRACK='1')
    cleaning = False
    pending = set()
    def cancel(number, _frame):
        if cleaning:
            pending.add(number)
        else:
            raise InterruptedError('public CRUD fixture cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(number, cancel)
    signal.setitimer(signal.ITIMER_REAL, max(0.01, started + 110 - time.monotonic()))
    try:
        for phase in ('first', 'second'):
            report['stage'] = 'server_start' if phase == 'first' else 'server_restart'
            ready = root / ('ready-' + phase + '.json')
            server = Child(p, [value['server'], root / 'state', root / 'public', ready], env, root, 'server-' + phase, deadline)
            children.append(server); report['server_runs'] += 1
            end = min(work_end, time.monotonic() + 6)
            while not ready.exists():
                p.require(time.monotonic() < end and server.status() is None)
                time.sleep(0.02)
            observed = p.decode(p.read(ready))
            p.require(type(observed) is dict and observed.keys() == {'schema', 'port'}
                and type(observed['schema']) is int and observed['schema'] == 1
                and type(observed['port']) is int and 1024 < observed['port'] <= 65535)
            ports.append(observed['port'])
            origin = 'http://127.0.0.1:' + str(observed['port'])
            report['stage'] = 'browser_' + phase
            browser = Child(p, [value['node'], root / 'fixture/crud_browser.mjs', phase, origin + '/'], env, root,
                            'browser-' + phase, deadline)
            children.append(browser); report['browser_runs'] += 1
            browser.wait(min(work_end, time.monotonic() + 35)); browser.close()
            observed = p.browser_receipt(p.decode(p.read(root / ('browser-' + phase + '.json'))), phase)
            report['browser_receipts'].append(observed)
            if phase == 'first':
                report['stage'] = 'http_denials'
                report['http_denials'] = denials(p, origin, root, work_end, denial_diagnostic)
            else:
                p.require(observed['ids'] == report['browser_receipts'][0]['ids'])
                p.require(not os.listdir(root / 'state'))
                report['persistence'] = True
            server.close()
            with socket.socket() as probe:
                probe.settimeout(0.2)
                p.require(probe.connect_ex(('127.0.0.1', ports[-1])) == errno.ECONNREFUSED)
        p.context(value, root)  # Asset and executable bindings still match.
        report['assets_unchanged'] = True
        report['outside_unchanged'] = p.read(root / 'outside/sentinel') == b'PUBLIC outside sentinel unchanged\n'
        p.require(report['outside_unchanged'] and report['http_denials'] == 42)
    except BaseException as error:
        primary = error
        report['first_failure'] = dict(stage=report['stage'], browser=None,
            case_id=denial_diagnostic.get('case_id') if report['stage'] == 'http_denials' else None,
            http_status=denial_diagnostic.get('http_status') if report['stage'] == 'http_denials' else None)
        if report['stage'] in ('browser_first', 'browser_second'):
            try:
                report['first_failure']['browser'] = p.browser_failure(
                    p.decode(p.read(root / ('browser-' + phase + '.json'))), phase)
            except BaseException:
                pass  # Optional observation cannot erase the original failure.
    finally:
        cleaning = True
        report['stage'] = 'cleanup' if primary is None else report['stage']
        for child in reversed(children):
            try:
                child.close()
            except BaseException as error:
                primary = primary or error
        try:
            report['descendants_gone'] = drain_descendants(p, deadline)
        except BaseException as error:
            primary = primary or error
        report['owned_groups_started'] = len(children)
        report['owned_groups_joined'] = bool(children) and all(child.joined for child in children)
        try:
            report['listeners_closed'] = bool(ports)
            for port in ports:
                with socket.socket() as probe:
                    probe.settimeout(0.1)
                    report['listeners_closed'] &= probe.connect_ex(('127.0.0.1', port)) == errno.ECONNREFUSED
        except BaseException as error:
            primary = primary or error
        if pending:
            primary = primary or InterruptedError('CRUD cleanup interrupted')
        if primary is not None and report['first_failure'] is None:
            report['first_failure'] = dict(stage='cleanup', browser=None, case_id=None, http_status=None)
        for label in ('server-first', 'browser-first', 'server-second', 'browser-second'):
            try:
                raw = p.read(root / (label + '.log'), 4 * 1024 * 1024, allow_empty=True)
                report['log_observations'].append(dict(case_id=label, bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest()))
            except BaseException:
                pass
        if primary is None and len(children) == 4 and len(report['log_observations']) == 4 and all(report[k] for k in ('owned_groups_joined', 'descendants_gone',
                                                       'listeners_closed', 'assets_unchanged', 'outside_unchanged', 'persistence')):
            report.update(status='passed', stage='complete')
        try:
            p.write(root / 'runtime-receipt.json', report)
        except BaseException as error:
            primary = primary or error
    if primary is not None or report['status'] != 'passed':
        raise ValueError('public CRUD runtime failed')


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        raise SystemExit(1) from None
