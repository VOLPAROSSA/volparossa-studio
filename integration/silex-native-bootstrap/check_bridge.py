#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Hosted exact-source caller for the existing authenticated Node bridge VM tests."""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXPORT = HERE.parent / 'silex-export'
UPSTREAM = '672efed69dda04c0a1e968859239e042f00d9538'
PATCHED = 'f51c34bb965e69ba7f907b2473b4aa310faef1fa98ba20003e49e6b8c824a482'
PRISTINE = 'f91e9debbe5a67175ce93bdcd17c29b8b13ba1ae5616ffa450bea4d315d90fa3'
EXPORT_MANIFEST = '02e054803e94f8773905af43a4d7aaaaedbc382a67ee27aa5ae6349ff58ca611'
NODE_VERSION = '24.19.0'
NODE_ARCHIVE = '14b342e71204f811bde6153be8e04b62aef63c236fef92b55f9c83154b409647'
NODE_BINARY = 'bc17c508ffeed0ec622934f9b7fa72f8e78da65350e63c3eceb56fa688aa5e12'
NODE_BYTES = 125989464
OUTPUT_LIMIT = 256 * 1024
CASE_NAMES = {
    'pristine 672 bridge positively detects stale-context SDK identity error and timing paths': 'baseline_canary',
    'patched bridge remains inert outside Tauri': 'outside_tauri',
    'patched dashboard clears project without stale telemetry SDK identity or timing': 'dashboard',
    'patched project metadata dirty and all four native menu callbacks still work': 'project_callbacks',
    'patched metadata fallback and rejected listeners stay handled without SDK error reporting': 'callback_failures',
    'patched MCP component selection capability and state helpers preserve actual behavior': 'mcp_components',
    'patched MCP data-source expression and delegated state helpers remain available': 'mcp_data_source',
    'patched local and external link callbacks preserve routing without real I/O': 'link_callbacks',
    'patched editor polling and bounded VM refuse real network module access and runaway code': 'vm_bounds',
}
KINDS = frozenset(('admission', 'source_rejected', 'carrier_failed', 'deadline', 'cancelled',
                   'spawn_failed', 'output_limit', 'child_failed', 'cleanup_failed', 'tap_rejected'))


class Rejected(RuntimeError):
    def __init__(self, kind):
        if kind not in KINDS:
            raise ValueError('closed failure kind required')
        self.kind = kind
        super().__init__('hosted bridge check rejected')


def require(condition, kind='admission'):
    if not condition:
        raise Rejected(kind)


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'source_rejected')
        value[key] = item
    return value


def parse_json(raw):
    def nonfinite(_value):
        raise Rejected('source_rejected')
    try:
        return json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=unique,
                          parse_constant=nonfinite)
    except (ValueError, UnicodeError):
        raise Rejected('source_rejected') from None


def directory(path):
    require(path.is_absolute() and path.resolve(strict=True) == path)
    metadata = path.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.geteuid()
            and metadata.st_mode & 0o022 == 0)


def read(path, maximum, *, expected=None):
    require(path.is_absolute() and path.resolve(strict=True) == path, 'source_rejected')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
                and before.st_nlink == 1 and before.st_mode & 0o022 == 0
                and 0 <= before.st_size <= maximum, 'source_rejected')
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_nlink',
              'st_size', 'st_mtime_ns', 'st_ctime_ns')
    require(len(data) == before.st_size and len(data) <= maximum
            and all(getattr(before, key) == getattr(after, key) for key in fields), 'source_rejected')
    if expected is not None:
        require(hashlib.sha256(data).hexdigest() == expected, 'source_rejected')
    return data


def git(*arguments):
    # Fixed read-only Git queries precede importing any project Python. No
    # repository hook, fsmonitor, lazy fetch, shell or inherited Git config.
    environment = dict(PATH='/usr/bin:/bin', LANG='C', LC_ALL='C', GIT_CONFIG_NOSYSTEM='1',
        GIT_CONFIG_GLOBAL='/dev/null', GIT_OPTIONAL_LOCKS='0', GIT_NO_LAZY_FETCH='1',
        GIT_TERMINAL_PROMPT='0')
    child = subprocess.Popen(['/usr/bin/git', '--no-pager', '--literal-pathspecs',
        '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null', '-C', str(ROOT),
        *arguments], env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, start_new_session=True)
    output = bytearray()
    error_bytes = 0
    end = time.monotonic() + 10
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (child.stdout, child.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                require(time.monotonic() < end, 'deadline')
                for key, _event in selector.select(min(0.25, max(0, end - time.monotonic()))):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.fileobj is child.stdout:
                        require(len(output) + len(chunk) <= 65536)
                        output.extend(chunk)
                    else:
                        error_bytes += len(chunk)
                        require(error_bytes <= 4096)
            child.wait(timeout=max(0.01, end - time.monotonic()))
        require(child.returncode == 0)
        return bytes(output)
    finally:
        # On failure the leader remains unreaped until this cleanup, so its
        # group identity cannot have been recycled. These fixed Git queries
        # cannot run hooks, fsmonitor or network subprocesses.
        if child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=1)
        child.stdout.close()
        child.stderr.close()


def admission():
    require(sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1)
    require(os.getuid() == os.geteuid() != 0)
    for key, value in {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                       'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64',
                       'GITHUB_REPOSITORY': 'VOLPAROSSA/volparossa-studio'}.items():
        require(os.environ.get(key) == value)
    require(sys.platform == 'linux' and os.uname().machine == 'x86_64')
    values = sys.argv[1:]
    require(len(values) == 4 and values[0] == '--source' and values[2] == '--pristine-bridge')
    workspace = Path(os.environ.get('GITHUB_WORKSPACE', ''))
    temporary = Path(os.environ.get('RUNNER_TEMP', ''))
    for path in (workspace, temporary, ROOT, HERE, EXPORT):
        directory(path)
    require(ROOT == workspace / 'studio' and Path(sys.argv[0]) == HERE / 'check_bridge.py')
    source, pristine = Path(values[1]), Path(values[3])
    directory(source)
    require(source == workspace / 'silex' or source != temporary and source.is_relative_to(temporary))
    require(pristine.is_absolute() and pristine != temporary and pristine.is_relative_to(temporary))
    for path in (source, pristine.parent):
        cursor = path
        while cursor not in (workspace, temporary):
            directory(cursor)
            cursor = cursor.parent
    revision = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', revision) is not None
            and os.environ.get('GITHUB_WORKFLOW_SHA') == revision)
    require(git('rev-parse', '--show-toplevel').decode().strip() == str(ROOT)
            and git('rev-parse', 'HEAD').decode().strip() == revision
            and not git('status', '--porcelain=v1', '-z', '--untracked-files=all'))
    require(all(entry.startswith(b'H ') for entry in git('ls-files', '-v', '-z').split(b'\0') if entry))
    read(source / 'desktop/src-tauri/scripts/desktop-bridge.js', 65536, expected=PATCHED)
    read(pristine, 65536, expected=PRISTINE)
    pins = parse_json(read(EXPORT / 'manifest.json', 65536, expected=EXPORT_MANIFEST))
    require(pins['node']['version'] == NODE_VERSION and pins['node']['sha256'] == NODE_ARCHIVE
            and pins['node']['url'] == 'https://nodejs.org/dist/v24.19.0/node-v24.19.0-linux-x64.tar.xz'
            and pins['node']['files']['bin/node']['bytes'] == NODE_BYTES
            and pins['node']['files']['bin/node']['sha256'] == NODE_BINARY)
    return source, pristine, temporary, workspace, revision


def parse_tap(raw):
    require(0 < len(raw) <= OUTPUT_LIMIT, 'tap_rejected')
    try:
        lines = raw.decode('utf-8', errors='strict').splitlines()
    except UnicodeError:
        raise Rejected('tap_rejected') from None
    require(lines.count('TAP version 13') == 1 and lines.count('1..9') == 1, 'tap_rejected')
    seen = []
    subtests = []
    summaries = {}
    for line in lines:
        if line.startswith('# Subtest: '):
            subtests.append(line.removeprefix('# Subtest: '))
        if line.startswith(('ok ', 'not ok ')):
            match = re.fullmatch(r'ok ([1-9]) - (.{1,256})', line)
            require(match is not None and match[2] in CASE_NAMES
                    and int(match[1]) == len(seen) + 1 and match[2] not in seen, 'tap_rejected')
            seen.append(match[2])
        if line.startswith('# '):
            match = re.fullmatch(r'# (tests|suites|pass|fail|cancelled|skipped|todo) ([0-9]+)', line)
            if match is not None:
                require(match[1] not in summaries, 'tap_rejected')
                summaries[match[1]] = int(match[2])
        if line.startswith(('Bail out!', 'not ok ', '1..')) and line != '1..9':
            raise Rejected('tap_rejected')
    require(len(seen) == 9 and set(seen) == set(CASE_NAMES) and subtests == seen
            and summaries == {'tests': 9, 'suites': 0, 'pass': 9, 'fail': 0,
                              'cancelled': 0, 'skipped': 0, 'todo': 0},
            'tap_rejected')
    return dict(tests=9, passed=9, failed=0, cancelled=0, skipped=0, todo=0,
                cases=[dict(id=CASE_NAMES[name], status='passed') for name in seen])


def bounded(command, environment, start_group, drain_group, deadline, seconds, cleanups, *, captured=None, on_started=None):
    process = identity = None
    output = bytearray()
    primary = None
    try:
        try:
            process, identity = start_group(command, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT)
        except Exception:
            raise Rejected('spawn_failed') from None
        if on_started is not None:
            on_started()
        end = min(deadline - 10, time.monotonic() + seconds)
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                require(time.monotonic() < end, 'deadline')
                for key, _event in selector.select(min(0.25, max(0, end - time.monotonic()))):
                    chunk = os.read(key.fd, 16384)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        require(len(output) + len(chunk) <= OUTPUT_LIMIT, 'output_limit')
                        output.extend(chunk)
            # Observe completion without reaping. drain_group sends its first
            # signal before its own poll/wait; retaining this direct leader
            # prevents that owned PID/PGID from being recycled in the gap.
            while True:
                require(time.monotonic() < end, 'deadline')
                exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None:
                    break
                time.sleep(min(0.01, max(0, end - time.monotonic())))
        require(exited.si_pid == process.pid and exited.si_code == os.CLD_EXITED
                and exited.si_status == 0, 'child_failed')
    except BaseException as error:
        primary = Rejected('deadline') if isinstance(error, subprocess.TimeoutExpired) else error
    finally:
        if captured is not None:
            captured.extend(output)
        joined = False
        if process is not None:
            # Cancellation must not abandon the single kill/join owner. Record
            # signals during this bounded drain, then propagate the first
            # original failure (or the deferred cancellation) afterwards.
            numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
            handlers = {number: signal.getsignal(number) for number in numbers}
            pending = set()
            for number in numbers:
                signal.signal(number, lambda number, _frame: pending.add(number))
            try:
                value = drain_group(process, identity, grace=1.0, kill_grace=1.0)
                joined = value['leader_joined'] is True and value['live_group_drained'] is True
            except BaseException:
                joined = False
            finally:
                try:
                    process.stdout.close()
                except Exception:
                    joined = False
                for number, handler in handlers.items():
                    signal.signal(number, handler)
            if pending and primary is None:
                primary = Rejected('deadline' if signal.SIGALRM in pending else 'cancelled')
        cleanups.append(joined)
        if not joined and primary is None:
            primary = Rejected('cleanup_failed')
    if primary is not None:
        raise primary
    return bytes(output)


def write_json(path, value):
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    require(len(raw) <= 16384)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(raw)


def main():
    started = time.monotonic()
    deadline = started + 360
    temporary = artifact = None
    report = dict(schema=1, mode='bridge-vm', status='failed', stage='admission',
        native_runtime_acceptance=False, full_application_privacy=False, full_studio_acceptance=False,
        native_gui_executed=False, installed_sdk_verified=False, keys_used=False,
        volparossa_updates_verified=False, network_publication=False,
        dependency_installation_performed=False, pnpm_executed=False,
        node_invocation_started=False, node_vm_tests_passed=False)
    cleanups = []
    tap = bytearray()
    primary = None
    def cancelled(number, _frame):
        raise Rejected('deadline' if number == signal.SIGALRM else 'cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(number, cancelled)
    signal.setitimer(signal.ITIMER_REAL, 350)
    try:
        source, pristine, runner_temp, workspace, revision = admission()
        artifact = runner_temp / 'silex-native-bridge.json'
        require(not artifact.exists() and not artifact.is_symlink())
        temporary = Path(tempfile.mkdtemp(prefix='silex-native-bridge-', dir=runner_temp))
        home = temporary / 'home'
        home.mkdir(mode=0o700)
        report.update(studio_revision=revision, upstream_revision=UPSTREAM,
            patched_bridge_sha256=PATCHED, pristine_bridge_sha256=PRISTINE,
            export_manifest_sha256=EXPORT_MANIFEST,
            harness_sha256=hashlib.sha256(read(HERE / 'test_bridge.mjs', 65536)).hexdigest(),
            caller_sha256=hashlib.sha256(read(HERE / 'check_bridge.py', 65536)).hexdigest(),
            native_overlay_manifest_sha256=hashlib.sha256(read(HERE / 'manifest.json', 65536)).hexdigest())
        # Python -I removes the script/CWD/environment import paths. Insert only
        # the verified checkout's explicit export fixture directory; no upstream
        # source directory enters sys.path. These imports perform no native work.
        sys.path.insert(0, str(EXPORT))
        try:
            import run as carrier
            from lifecycle import start_group, drain_group
        finally:
            sys.path.remove(str(EXPORT))
        environment = dict(PATH='/usr/bin:/bin', HOME=str(home), LANG='C.UTF-8', LC_ALL='C.UTF-8',
            GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Linux', RUNNER_ARCH='X64',
            GITHUB_WORKSPACE=str(workspace), RUNNER_TEMP=str(runner_temp), GITHUB_SHA=revision,
            GITHUB_WORKFLOW_SHA=revision, GITHUB_REPOSITORY='VOLPAROSSA/volparossa-studio')
        verify = ['/usr/bin/python3', '-I', '-B', str(HERE / 'prepare.py'), 'verify-patched', '--source', str(source)]
        report['stage'] = 'verify_source_before'
        before = parse_json(bounded(verify, environment, start_group, drain_group, deadline, 60, cleanups))
        require(type(before) is dict and before.get('operation') == 'verify-patched' and before.get('source_commit') == UPSTREAM
                and before.get('compiled') is False and before.get('native_runtime_proven') is False,
                'source_rejected')
        report['stage'] = 'authenticate_node'
        try:
            node, _pnpm = carrier.prepare(temporary)
        except Rejected:
            raise
        except Exception:
            raise Rejected('carrier_failed') from None
        require(node == temporary / 'node/node', 'carrier_failed')
        # The existing carrier authenticates the archive and extracted Node bytes.
        # Verify the persisted executable again without allocating its 126 MB.
        metadata = node.lstat()
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.geteuid()
                and metadata.st_nlink == 1 and stat.S_IMODE(metadata.st_mode) == 0o700
                and metadata.st_size == NODE_BYTES, 'carrier_failed')
        digest = hashlib.sha256()
        descriptor = os.open(node, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(descriptor, 'rb') as stream:
            count = 0
            while chunk := stream.read(65536):
                count += len(chunk)
                require(count <= NODE_BYTES, 'carrier_failed')
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        require(count == NODE_BYTES and digest.hexdigest() == NODE_BINARY
                and (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                'carrier_failed')
        report['authenticated_node'] = dict(version=NODE_VERSION, archive_sha256=NODE_ARCHIVE, binary_sha256=NODE_BINARY)
        report['stage'] = 'actual_node_vm_tests'
        raw = bounded([str(node), '--test-reporter=tap', str(HERE / 'test_bridge.mjs'),
            '--source-root', str(source), '--bridge-sha256', PATCHED, '--baseline-bridge', str(pristine)],
            environment, start_group, drain_group, deadline, 60, cleanups, captured=tap,
            on_started=lambda: report.update(node_invocation_started=True))
        report['tests'] = parse_tap(raw)
        report['node_vm_tests_passed'] = True
        report['tap_sha256'] = hashlib.sha256(raw).hexdigest()
        report['stage'] = 'verify_source_after'
        after = parse_json(bounded(verify, environment, start_group, drain_group, deadline, 60, cleanups))
        require(before == after, 'source_rejected')
        require(not git('status', '--porcelain=v1', '-z', '--untracked-files=all'), 'source_rejected')
        report.update(status='passed', stage='complete')
    except BaseException as error:
        primary = error
        report['failure'] = dict(kind=error.kind if isinstance(error, Rejected) else 'child_failed', stage=report['stage'])
    finally:
        removed = temporary is None
        try:
            signal.setitimer(signal.ITIMER_REAL, max(0.01, deadline - time.monotonic()))
            if temporary is not None and all(cleanups):
                shutil.rmtree(temporary)
                removed = not temporary.exists()
        except BaseException:
            removed = False
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        report['cleanup'] = dict(owned_groups_joined=bool(cleanups) and all(cleanups),
            owned_group_count=len(cleanups), private_state_removed=removed,
            private_state_retained=temporary is not None and not removed)
        if not removed or not cleanups or not all(cleanups) or report['status'] == 'passed' and len(cleanups) != 3:
            report['status'] = 'failed'
            report.setdefault('failure', dict(kind='cleanup_failed', stage='cleanup'))
        if artifact is not None:
            # Only the known public-synthetic harness's bounded TAP is retained
            # on failure. Never project helper/download/product logs or secrets.
            if report['status'] == 'failed' and tap:
                try:
                    tap_path = artifact.with_suffix('.tap')
                    descriptor = os.open(tap_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
                    with os.fdopen(descriptor, 'wb') as output:
                        output.write(tap)
                    report['failure_tap_retained'] = True
                except Exception:
                    report['failure_tap_retained'] = False
            try:
                write_json(artifact, report)
            except Exception:
                # A failed optional artifact write cannot replace the original
                # child/timeout failure. Missing evidence still returns failure.
                if primary is None:
                    primary = Rejected('cleanup_failed')
    if primary is not None or report['status'] != 'passed':
        print('hosted bridge check rejected', file=sys.stderr)
        return 1
    print('SILEX_NATIVE_BRIDGE_VM_CHECKS=passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
