# SPDX-License-Identifier: GPL-3.0-only
"""Fixed hosted isolation supervisor and namespace PID1; never start a GUI.

There is no command/path API. The three internal entrypoints run only through
the source-bound controller, with a single stdin consumer at each ownership
level. Source/metadata observations are not package-byte or WebKit acceptance.
"""
from contextlib import contextmanager
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time

SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
BOOT = b'VP-ISOLATION-1\n'
MAX_JSON = 64 * 1024
MAX_SOURCE = 256 * 1024
SDK = 'c2e3e609b6dc9e204b65d173ac087be89c37e06f25e10c997dd1fd87831178a8'
LIFECYCLE = 'integration/silex-export/lifecycle.py'
LIFECYCLE_SHA = 'a3fe1d2fe7ba51c7f63a73ad505161d73e0d8f5b112a9af575f62e70f467da9e'
SOURCES = {'controller': 'integration/silex-native-runtime/isolation.py',
           'root': 'integration/silex-native-runtime/isolation_root.py',
           'actor': 'integration/silex-native-runtime/isolation_actor.py',
           'lifecycle': LIFECYCLE}
FILENAMES = {'controller': 'isolation.py', 'root': 'isolation_root.py',
             'actor': 'isolation_actor.py', 'lifecycle': 'lifecycle.py'}
HOST_KEYS = ('GITHUB_ACTIONS', 'RUNNER_ENVIRONMENT', 'RUNNER_OS', 'RUNNER_ARCH',
             'GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_WORKFLOW_SHA', 'GITHUB_REF',
             'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_WORKSPACE', 'RUNNER_TEMP')
ENV = dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LANG='C', LC_ALL='C', PYTHONDONTWRITEBYTECODE='1')
KINDS = frozenset(('admission', 'source', 'protocol', 'deadline', 'cancelled',
                   'child', 'output_limit', 'cleanup', 'namespace', 'identity',
                   'filesystem', 'network', 'observer', 'host_changed'))
SCOPES = ('application_executed', 'display_started', 'browser_started',
          'native_runtime_acceptance', 'webkit_sandbox_runtime_verified',
          'full_application_privacy', 'full_studio_acceptance',
          'volparossa_updates_verified', 'packages_installed')
NAMESPACES = ('net', 'mnt', 'pid', 'ipc')
ADMISSION = frozenset(('uid_original', 'gid_original', 'groups_cleared', 'capabilities_zero',
    'no_new_privileges', 'private_namespaces', 'private_proc', 'private_home', 'private_xdg',
    'private_tmp', 'host_workspace_hidden', 'host_bus_absent', 'host_xauthority_absent',
    'display_environment_absent', 'sandbox_disable_flags_absent', 'inherited_fds_closed',
    'root_mount_readonly', 'private_resolver_profile', 'private_shared_memory', 'private_mqueue'))
WORKER_STAGES = frozenset(('mounts', 'admission_actor', 'network_setup', 'synthetic_calibration', 'complete'))
ACTOR_PREDICATES = ADMISSION | {'shape', 'protocol', 'dns', 'ipv4_datagram', 'ipv6_datagram'}
RESOLVER = b'nameserver 127.0.0.53\noptions attempts:1 timeout:1\n'
# Nested cleanup reserves under the ORIGINAL 120s end: namespace owner gets 6s
# cooperative EOF + <=3s TERM/KILL/join; root owner gets 20s, then <=3s drain.
# No owner may renew a deadline or treat a missing closed cleanup ack as success.
COOPERATIVE_GRACE = {'namespace': 6.0, 'root': 20.0}
DNS_QUERY = bytes.fromhex('475001000001000000000000') + b'\x0bcalibration\x07invalid\0\0\x01\0\x01'
DNS_REPLY = DNS_QUERY[:2] + bytes.fromhex('81830001000000000000') + DNS_QUERY[12:]


class Rejected(RuntimeError):
    def __init__(self, kind):
        if kind not in KINDS:
            raise ValueError('closed isolation failure required')
        self.kind = kind
        super().__init__('native isolation prerequisite rejected')


def require(value, kind='admission'):
    if not value:
        raise Rejected(kind)


def pairs(rows):
    value = {}
    for key, item in rows:
        require(key not in value, 'protocol')
        value[key] = item
    return value


def parse(raw, maximum=MAX_JSON):
    require(0 < len(raw) <= maximum, 'protocol')
    try:
        return json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=pairs,
                          parse_constant=lambda _value: require(False, 'protocol'))
    except (ValueError, UnicodeError):
        raise Rejected('protocol') from None


def encoded(value):
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    require(len(raw) <= MAX_JSON, 'output_limit')
    return raw


def stable(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def masked_cleanup(primary, action):
    previous = None
    try:
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    except BaseException as error:
        primary = primary or error
    try:
        action()
    except BaseException as error:
        primary = primary or error
    finally:
        if previous is not None:
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)
            except BaseException as error:
                primary = primary or error
    return primary


@contextmanager
def descriptor(path, flags, mode=0o600):
    fd = None
    primary = None
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    try:
        try:
            fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, mode)
        except BaseException as error:
            primary = error
        finally:
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)
            except BaseException as error:
                primary = primary or error
        if primary is None:
            try:
                yield fd
            except BaseException as error:
                primary = error
    finally:
        if fd is not None:
            primary = masked_cleanup(primary, lambda: os.close(fd))
    if primary is not None:
        raise primary


def read(path, maximum, *, owner, modes=(0o400, 0o600, 0o644)):
    require(path.is_absolute() and path.resolve(strict=True) == path, 'filesystem')
    with descriptor(path, os.O_RDONLY) as fd:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) in modes and 0 <= before.st_size <= maximum, 'filesystem')
        raw = bytearray()
        while len(raw) <= maximum:
            part = os.read(fd, min(65536, maximum + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        require(len(raw) == before.st_size <= maximum and stable(before) == stable(os.fstat(fd)), 'filesystem')
    return bytes(raw)


def write_new(path, raw, *, mode=0o400):
    require(len(raw) <= MAX_SOURCE, 'filesystem')
    with descriptor(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL) as fd:
        remaining = memoryview(raw)
        while remaining:
            count = os.write(fd, remaining[:65536])
            require(0 < count <= min(len(remaining), 65536), 'filesystem')
            remaining = remaining[count:]
        os.fsync(fd)
        os.fchmod(fd, mode)


def kernel_read(path, maximum):
    # procfs reports size zero for generated content. Bound actual same-FD bytes;
    # do not invent an on-disk length/stability claim for a live kernel view.
    with descriptor(path, os.O_RDONLY) as fd:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0
                and not before.st_mode & 0o022, 'filesystem')
        raw = bytearray()
        while len(raw) <= maximum:
            part = os.read(fd, min(65536, maximum + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        after = os.fstat(fd)
        require(len(raw) <= maximum and (before.st_dev, before.st_ino, before.st_uid, before.st_mode)
                == (after.st_dev, after.st_ino, after.st_uid, after.st_mode), 'filesystem')
    return bytes(raw)


def directory(path, owner, *, private=False):
    require(path.is_absolute() and path.resolve(strict=True) == path, 'filesystem')
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == owner
            and (stat.S_IMODE(info.st_mode) == 0o700 if private else not info.st_mode & 0o022), 'filesystem')
    return info.st_dev, info.st_ino


def current_namespaces():
    result = {name: os.readlink('/proc/self/ns/' + name) for name in NAMESPACES}
    require(all(re.fullmatch(name + r':\[[0-9]+\]', value) for name, value in result.items()), 'namespace')
    return result


def deadlines():
    try:
        work, end = (int(os.environ[key]) for key in ('VP_ISOLATION_WORK_NS', 'VP_ISOLATION_END_NS'))
    except (KeyError, ValueError):
        raise Rejected('deadline') from None
    now = time.monotonic_ns()
    require(0 < work - now <= 90_000_000_000 and end - work == 30_000_000_000
            and 0 < end - now <= 120_000_000_000, 'deadline')
    return work / 1e9, end / 1e9


def check_control():
    require(not os.isatty(0), 'protocol')
    info = os.fstat(0)
    require(stat.S_ISFIFO(info.st_mode) or stat.S_ISSOCK(info.st_mode), 'protocol')
    if selectors_for(0):
        require(False, 'cancelled' if not os.read(0, 1) else 'protocol')


def selectors_for(fd):
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        return bool(selector.select(0))


def boot_read(deadline):
    require(not os.isatty(0), 'protocol')
    info = os.fstat(0)
    require(stat.S_ISFIFO(info.st_mode) or stat.S_ISSOCK(info.st_mode), 'protocol')
    raw = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(0, selectors.EVENT_READ)
        while len(raw) < len(BOOT):
            require(time.monotonic() < deadline, 'deadline')
            if selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                part = os.read(0, len(BOOT) - len(raw))
                require(part, 'protocol')
                raw.extend(part)
    require(bytes(raw) == BOOT, 'protocol')


def load_lifecycle(path, expected, owner):
    require(hashlib.sha256(read(path, MAX_SOURCE, owner=owner)).hexdigest() == expected, 'source')
    spec = importlib.util.spec_from_file_location('isolation_owned_lifecycle', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Owner:
    """Own one group at a time, retaining its unreaped identity until drainage."""
    def __init__(self, lifecycle, work, end, *, control=True):
        self.lifecycle, self.work, self.end, self.control = lifecycle, work, end, control
        self.started = self.joined = 0
        self.last_output = b''
        self.roles_started = dict.fromkeys(('tool', 'admission', 'calibration', 'namespace', 'root'), 0)
        self.roles_joined = dict(self.roles_started)

    def run(self, argv, *, environment=None, payload=None, keep_stdin=False,
            cooperative=False, service=None, maximum=MAX_JSON, seconds=8, role='tool'):
        require(time.monotonic() < self.work, 'deadline')
        require(role in self.roles_started, 'protocol')
        require(not cooperative or role in COOPERATIVE_GRACE, 'protocol')
        self.last_output = b''
        process = identity = None
        primary = None
        output = bytearray()
        total = 0
        observed = None
        try:
            # Hand ownership to this frame before delivering a pending cancel.
            previous = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
            try:
                process, identity = self.lifecycle.start_group(list(map(str, argv)),
                    env=ENV if environment is None else environment, cwd='/',
                    stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
                self.started += 1
                self.roles_started[role] += 1
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)
            deadline = min(self.work, time.monotonic() + seconds)
            with selectors.DefaultSelector() as selector:
                for stream in (process.stdout, process.stderr):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
                pending = memoryview(payload) if payload is not None else None
                if pending is not None:
                    require(len(pending) <= MAX_JSON, 'protocol')
                    os.set_blocking(process.stdin.fileno(), False)
                    selector.register(process.stdin, selectors.EVENT_WRITE)
                while selector.get_map() or observed is None:
                    require(time.monotonic() < deadline, 'deadline')
                    if self.control:
                        check_control()
                    if service is not None:
                        service()
                    for key, _event in selector.select(min(0.02, max(0, deadline - time.monotonic()))):
                        if key.fileobj is process.stdin:
                            pending = pending[os.write(process.stdin.fileno(), pending[:4096]):]
                            if not pending:
                                selector.unregister(process.stdin)
                                if not keep_stdin:
                                    process.stdin.close()
                        else:
                            chunk = os.read(key.fd, 16384)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            total += len(chunk)
                            require(total <= maximum + 65536, 'output_limit')
                            if key.fileobj is process.stdout:
                                require(len(output) + len(chunk) <= maximum, 'output_limit')
                                output.extend(chunk)
                    observed = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            require(observed.si_code == os.CLD_EXITED and observed.si_status == 0, 'child')
        except BaseException as error:
            primary = error
            if process is None and isinstance(error, self.lifecycle.GroupCaptureFailure):
                self.started += 1
                self.roles_started[role] += 1
        finally:
            def drain():
                if process is None:
                    return
                close_error = None
                if process.stdin is not None and not process.stdin.closed:
                    try:
                        process.stdin.close()  # Forward EOF; never share original fd0.
                    except BaseException as error:
                        close_error = error
                if cooperative and primary is not None:
                    stop = min(self.end - 4, time.monotonic() + COOPERATIVE_GRACE[role])
                    # Give the independently timed root/PID1 owner its own cleanup
                    # window before the unshare parent can be force terminated.
                    for stream in (process.stdout, process.stderr):
                        os.set_blocking(stream.fileno(), False)
                    while time.monotonic() < stop:
                        status = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                        for stream in (process.stdout, process.stderr):
                            try:
                                os.read(stream.fileno(), 16384)
                            except BlockingIOError:
                                pass
                        if status is not None:
                            break
                        time.sleep(0.02)
                require(time.monotonic() < self.end, 'cleanup')
                result = self.lifecycle.drain_group(process, identity, grace=1, kill_grace=1)
                require(result['leader_joined'] is True and result['live_group_drained'] is True, 'cleanup')
                self.joined += 1
                self.roles_joined[role] += 1
                if close_error is not None:
                    raise close_error
            primary = masked_cleanup(primary, drain)
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        primary = masked_cleanup(primary, stream.close)
        if primary is not None:
            self.last_output = bytes(output)
            raise primary
        self.last_output = bytes(output)
        return bytes(output)


def admission_environment():
    require(sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1
            and sys.platform == 'linux' and os.uname().machine == 'x86_64')
    for key, value in {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
        'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'GITHUB_REPOSITORY': 'VOLPAROSSA/volparossa-studio',
        'GITHUB_REF': 'refs/heads/feature/native-bootstrap-runtime-20261029'}.items():
        require(os.environ.get(key) == value)
    revision = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', revision) and os.environ.get('GITHUB_WORKFLOW_SHA') == revision)
    require(not any(key.startswith('LD_') or key in ('PYTHONPATH', 'PYTHONHOME') for key in os.environ))
    for key, maximum in (('GITHUB_RUN_ID', 20), ('GITHUB_RUN_ATTEMPT', 6)):
        require(re.fullmatch(r'[1-9][0-9]{0,' + str(maximum - 1) + '}', os.environ.get(key, '')))
    workspace = Path(os.environ.get('GITHUB_WORKSPACE', ''))
    root = workspace / 'studio'
    require(workspace.is_absolute() and workspace.resolve(strict=True) == workspace
            and root.resolve(strict=True) == root)
    return root, revision


def owner_identity(root):
    uid = root.stat().st_uid
    require(1000 <= uid < 2**31 and os.environ.get('VP_ISOLATION_UID') == str(uid), 'identity')
    account = pwd.getpwuid(uid)
    require(0 < account.pw_gid < 2**31 and os.environ.get('VP_ISOLATION_GID') == str(account.pw_gid), 'identity')
    directory(root, uid)
    return uid, account.pw_gid


def stage_path():
    return Path('/run/volparossa-native-isolation-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT'])


def git_bytes(owner, root, *args):
    environment = dict(ENV, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                       GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0')
    return owner.run(['/usr/bin/git', '--no-pager', '--literal-pathspecs',
        '-c', 'safe.directory=' + str(root), '-c', 'core.hooksPath=/dev/null',
        '-c', 'core.fsmonitor=false', '-C', str(root), *args],
        environment=environment, maximum=MAX_SOURCE, seconds=5)


def source_payloads(owner, root, revision, uid):
    require(git_bytes(owner, root, 'rev-parse', '--show-toplevel').strip().decode() == str(root)
            and git_bytes(owner, root, 'rev-parse', 'HEAD').strip().decode() == revision
            and not git_bytes(owner, root, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--ignored=matching')
            and all(r.startswith(b'H ') for r in git_bytes(owner, root, 'ls-files', '-v', '-z').split(b'\0') if r), 'source')
    payloads = {}
    for label, relative in SOURCES.items():
        raw = read(root / relative, MAX_SOURCE, owner=uid, modes=(0o644,))
        require(raw == git_bytes(owner, root, 'show', 'HEAD:' + relative), 'source')
        payloads[label] = raw
    return payloads


def clean_network_json(value):
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key == 'counter' and isinstance(child, dict):
                result[key] = {k: clean_network_json(v) for k, v in child.items() if k not in ('packets', 'bytes')}
            else:
                result[key] = clean_network_json(child)
        return result
    if isinstance(value, list):
        return [clean_network_json(v) for v in value]
    return value


def host_network(owner):
    routes = {}
    for name, dropped in (('route', (4, 5)), ('ipv6_route', (6, 7))):
        raw = kernel_read(Path('/proc/net/' + name), 65536)
        lines = raw.splitlines()[1:] if name == 'route' else raw.splitlines()
        rows = [line.split() for line in lines]
        require(all(len(row) == (11 if name == 'route' else 10) for row in rows), 'host_changed')
        routes[name] = [[token.decode('ascii') for index, token in enumerate(row) if index not in dropped] for row in rows]
    resolver = Path('/etc/resolv.conf').resolve(strict=True)
    require(str(resolver) in ('/etc/resolv.conf', '/run/systemd/resolve/resolv.conf', '/run/systemd/resolve/stub-resolv.conf'), 'host_changed')
    raw = read(resolver, 65536, owner=0)
    nft = parse(owner.run(['/usr/sbin/nft', '--json', '--numeric', 'list', 'ruleset']), maximum=MAX_JSON)
    return dict(routes_sha256=hashlib.sha256(encoded(routes)).hexdigest(),
                resolver_sha256=hashlib.sha256(raw).hexdigest(),
                firewall_configuration_sha256=hashlib.sha256(encoded(clean_network_json(nft))).hexdigest())


def namespace_command(stage):
    return ['/usr/bin/unshare', '--mount', '--net', '--pid', '--ipc', '--fork',
            '--mount-proc=/proc', '--propagation=private', '--kill-child=KILL', '--',
            '/usr/bin/python3', '-I', '-B', str(stage / 'isolation_root.py'), '--namespace-init']


def actor_environment(uid, gid, parent, canary, ipc_views, ipc_canary):
    return dict(ENV, HOME='/home/fixture', XDG_CONFIG_HOME='/home/fixture/config',
        XDG_DATA_HOME='/home/fixture/data', XDG_CACHE_HOME='/home/fixture/cache',
        XDG_RUNTIME_DIR='/run/user/' + str(uid), TMPDIR='/tmp/fixture',
        VP_ISOLATION_UID=str(uid), VP_ISOLATION_GID=str(gid),
        VP_PARENT_NAMESPACES=json.dumps(parent, sort_keys=True), VP_HOST_CANARY=str(canary),
        VP_PARENT_IPC_VIEWS=json.dumps(ipc_views, sort_keys=True), VP_HOST_IPC_CANARY=str(ipc_canary))


def actor_command(uid, gid, mode):
    require(mode in ('admission', 'calibration'), 'protocol')
    return ['/usr/bin/setpriv', '--reuid=' + str(uid), '--regid=' + str(gid),
            '--clear-groups', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all',
            '--no-new-privs', '--', '/usr/bin/python3', '-I', '-B',
            '/run/fixture/isolation_actor.py', mode]


def rules(uid):
    require(type(uid) is int and 1000 <= uid < 2**31, 'identity')
    return ('''table inet vpcal {
 counter denied4 {} counter denied6 {} counter dns {} counter dns_reply {}
 chain output { type filter hook output priority 0; policy drop;
  meta skuid %d ip daddr 127.0.0.53 udp dport 53 counter name dns accept
  meta skuid 0 ip saddr 127.0.0.53 udp sport 53 counter name dns_reply accept
  meta skuid %d meta nfproto ipv4 counter name denied4 drop
  meta skuid %d meta nfproto ipv6 counter name denied6 drop
 }
}
''' % (uid, uid, uid)).encode()


def counters(raw):
    value = parse(raw)
    require(type(value) is dict and value.keys() == {'nftables'} and type(value['nftables']) is list, 'observer')
    result = {}
    for row in value['nftables']:
        require(type(row) is dict and len(row) == 1, 'observer')
        if 'counter' not in row:
            require(next(iter(row)) in ('metainfo', 'table', 'chain', 'rule'), 'observer')
            continue
        counter = row['counter']
        require(type(counter) is dict and counter.keys() <= {'family', 'table', 'name', 'handle', 'packets', 'bytes'}
                and counter.get('family') == 'inet' and counter.get('table') == 'vpcal'
                and counter.get('name') in ('denied4', 'denied6', 'dns', 'dns_reply')
                and counter['name'] not in result, 'observer')
        require(all(type(counter.get(key)) is int and 0 <= counter[key] <= 4096 for key in ('packets', 'bytes')), 'observer')
        result[counter['name']] = dict(packets=counter['packets'], bytes=counter['bytes'])
    require(set(result) == {'denied4', 'denied6', 'dns', 'dns_reply'}, 'observer')
    return result


def namespace_init():
    require(os.getuid() == os.geteuid() == 0 and os.getpid() == 1, 'namespace')
    work, end = deadlines()
    boot_read(min(work, time.monotonic() + 5))
    stage = Path(__file__).resolve().parent
    directory(stage, 0, private=True)
    meta = parse(read(stage / 'carrier.json', MAX_JSON, owner=0))
    require(meta.keys() == {'schema', 'revision', 'uid', 'gid', 'parent_namespaces', 'sources', 'host_canary',
                           'source_groups_started', 'source_groups_joined', 'parent_ipc_views', 'host_ipc_canary'}, 'source')
    uid, gid = meta['uid'], meta['gid']
    require(type(uid) is int and uid >= 1000 and type(gid) is int and gid > 0, 'identity')
    current = current_namespaces()
    require(set(meta['parent_namespaces']) == set(NAMESPACES)
            and all(current[name] != meta['parent_namespaces'][name] for name in NAMESPACES), 'namespace')
    for label, filename in FILENAMES.items():
        require(hashlib.sha256(read(stage / filename, MAX_SOURCE, owner=0)).hexdigest() == meta['sources'][label], 'source')
    lifecycle = load_lifecycle(stage / 'lifecycle.py', meta['sources']['lifecycle'], 0)
    owner = Owner(lifecycle, work, end)
    report = dict(schema=1, operation='namespace_isolation_worker', status='failed',
                  stage='mounts', admission=None, calibration=None,
                  namespace_groups_started=0, namespace_groups_joined=0,
                  actors_started=0, actors_joined=0, owner_scope='namespace_process_groups',
                  failure_kind=None, actor_failure_predicate=None)
    primary = None
    dns = None
    try:
        # Cache every source byte before hiding the original workspace/home/run.
        actor = read(stage / 'isolation_actor.py', MAX_SOURCE, owner=0)
        os.chdir('/')
        # Recursive bind preserves the already-private proc/dev child mounts;
        # remount,bind,ro changes this mount, never the host superblock's mode.
        owner.run(['/usr/bin/mount', '--no-mtab', '--rbind', '/', '/'])
        owner.run(['/usr/bin/mount', '--no-mtab', '-o', 'remount,bind,ro', '/'])
        for path in ('/tmp', '/run', '/home'):
            owner.run(['/usr/bin/mount', '--no-mtab', '-t', 'tmpfs', '-o',
                       'mode=1777,nosuid,nodev' if path == '/tmp' else 'mode=755,nosuid,nodev', 'tmpfs', path])
        # IPC namespace creation alone does not replace inherited POSIX IPC
        # mounts. Both views must be freshly mounted inside this namespace.
        owner.run(['/usr/bin/mount', '--no-mtab', '-t', 'tmpfs', '-o',
                   'mode=1777,nosuid,nodev,noexec', 'tmpfs', '/dev/shm'])
        owner.run(['/usr/bin/mount', '--no-mtab', '-t', 'mqueue', '-o',
                   'nosuid,nodev,noexec', 'mqueue', '/dev/mqueue'])
        Path('/run/fixture').mkdir(mode=0o755)
        os.chmod('/run/fixture', 0o755)  # Original UID must traverse even with umask 077.
        write_new(Path('/run/fixture/isolation_actor.py'), actor, mode=0o444)
        home = Path('/home/fixture')
        home.mkdir(mode=0o700)
        os.chown(home, uid, gid)
        for name in ('config', 'data', 'cache'):
            path = home / name; path.mkdir(mode=0o700); os.chown(path, uid, gid)
        Path('/tmp/fixture').mkdir(mode=0o700); os.chown('/tmp/fixture', uid, gid)
        Path('/run/user').mkdir(mode=0o755)
        os.chmod('/run/user', 0o755)
        runtime = Path('/run/user') / str(uid)
        runtime.mkdir(mode=0o700); os.chown(runtime, uid, gid)
        # The fixture resolver is private. No host resolver bytes are edited.
        target = Path('/etc/resolv.conf').resolve(strict=True)
        require(str(target) == '/etc/resolv.conf', 'filesystem')
        write_new(Path('/run/fixture/resolv.conf'), RESOLVER, mode=0o444)
        owner.run(['/usr/bin/mount', '--no-mtab', '--bind', '/run/fixture/resolv.conf', '/etc/resolv.conf'])
        owner.run(['/usr/bin/mount', '--no-mtab', '-o', 'remount,bind,ro', '/etc/resolv.conf'])
        environment = actor_environment(uid, gid, meta['parent_namespaces'], meta['host_canary'],
                                        meta['parent_ipc_views'], meta['host_ipc_canary'])
        report['stage'] = 'admission_actor'
        admission = parse(owner.run(actor_command(uid, gid, 'admission'), environment=environment, role='admission'))
        require(type(admission) is dict and admission.keys() == ADMISSION | {'schema', 'operation', 'passed'}
                and type(admission['schema']) is int and admission['schema'] == 1
                and admission['operation'] == 'isolation_actor_admission'
                and admission['passed'] is True and all(admission[key] is True for key in ADMISSION), 'identity')
        report['admission'] = admission
        report['stage'] = 'network_setup'
        # No implicit kernel module loading: unavailable veth means Not ready.
        require(Path('/sys/module/veth').is_dir(), 'network')
        owner.run(['/usr/bin/ip', 'link', 'set', 'lo', 'up'])
        owner.run(['/usr/bin/ip', 'link', 'add', 'vpcal0', 'type', 'veth', 'peer', 'name', 'vpsink0'])
        for link in ('vpcal0', 'vpsink0'):
            owner.run(['/usr/bin/ip', 'link', 'set', link, 'up'])
        owner.run(['/usr/bin/ip', 'addr', 'add', '192.0.2.1/24', 'dev', 'vpcal0'])
        owner.run(['/usr/bin/ip', 'addr', 'add', '192.0.2.2/24', 'dev', 'vpsink0'])
        owner.run(['/usr/bin/ip', '-6', 'addr', 'add', '2001:db8:1::1/64', 'dev', 'vpcal0', 'nodad'])
        owner.run(['/usr/bin/ip', '-6', 'addr', 'add', '2001:db8:1::2/64', 'dev', 'vpsink0', 'nodad'])
        owner.run(['/usr/bin/ip', 'route', 'add', 'default', 'dev', 'vpcal0'])
        owner.run(['/usr/bin/ip', '-6', 'route', 'add', 'default', 'dev', 'vpcal0'])
        owner.run(['/usr/sbin/nft', '-f', '-'], payload=rules(uid))
        before = counters(owner.run(['/usr/sbin/nft', '--json', 'list', 'table', 'inet', 'vpcal']))
        require(all(r == dict(packets=0, bytes=0) for r in before.values()), 'observer')
        dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK)
        dns.bind(('127.0.0.53', 53))
        queries = replies = 0
        def service():
            nonlocal queries, replies
            try:
                packet, address = dns.recvfrom(513)
            except BlockingIOError:
                return
            require(queries == 0 and packet == DNS_QUERY and address[0] == '127.0.0.1', 'observer')
            queries += 1
            require(dns.sendto(DNS_REPLY, address) == len(DNS_REPLY), 'observer')
            replies += 1
        report['stage'] = 'synthetic_calibration'
        calibrated = parse(owner.run(actor_command(uid, gid, 'calibration'), environment=environment,
                                     service=service, role='calibration'))
        after = counters(owner.run(['/usr/sbin/nft', '--json', 'list', 'table', 'inet', 'vpcal']))
        require(calibrated == dict(schema=1, operation='isolation_actor_calibration',
                ipv4_attempts=1, ipv6_attempts=1, dns_attempts=1, dns_response_verified=True), 'observer')
        require(queries == replies == 1 and all(after[name]['packets'] == 1 and after[name]['bytes'] > 0
                for name in after), 'observer')
        report['calibration'] = dict(synthetic_actor=True, ipv4_attempts=1, ipv6_attempts=1,
            ipv4_drop_packets=after['denied4']['packets'], ipv6_drop_packets=after['denied6']['packets'],
            dns_queries=queries, dns_replies=replies,
            dns_output_packets=after['dns']['packets'], dns_reply_packets=after['dns_reply']['packets'])
        report.update(status='passed', stage='complete')
    except BaseException as error:
        primary = error
        report['failure_kind'] = error.kind if isinstance(error, Rejected) else 'namespace'
        try:
            failed = parse(owner.last_output)
            require(type(failed) is dict and failed.keys() == {'schema', 'operation', 'status', 'predicate'}
                and type(failed['schema']) is int and failed['schema'] == 1
                and failed['operation'] == 'isolation_actor_failure' and failed['status'] == 'failed'
                and failed['predicate'] in ACTOR_PREDICATES)
            report['actor_failure_predicate'] = failed['predicate']
        except BaseException:
            pass
    finally:
        def finish():
            if dns is not None:
                dns.close()
            # Namespace PID1 is also an orphan reaper. No arbitrary foreign PID.
            while True:
                try:
                    child, _status = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    break
                require(child != 0, 'cleanup')
        primary = masked_cleanup(primary, finish)
        report.update(namespace_groups_started=owner.started, namespace_groups_joined=owner.joined,
                      actors_started=owner.roles_started['admission'] + owner.roles_started['calibration'],
                      actors_joined=owner.roles_joined['admission'] + owner.roles_joined['calibration'])
        if owner.started != owner.joined or primary is not None:
            report['status'] = 'failed'
            report['failure_kind'] = report['failure_kind'] or 'cleanup'
    print(json.dumps(report, sort_keys=True))
    require(primary is None and report['status'] == 'passed', 'cleanup')


def staged_supervisor():
    require(os.getuid() == os.geteuid() == 0)
    work, end = deadlines()
    stage = Path(__file__).resolve().parent
    require(stage == stage_path(), 'source')
    directory(stage, 0, private=True)
    meta = parse(read(stage / 'carrier.json', MAX_JSON, owner=0))
    for label, filename in FILENAMES.items():
        require(hashlib.sha256(read(stage / filename, MAX_SOURCE, owner=0)).hexdigest() == meta['sources'][label], 'source')
    lifecycle = load_lifecycle(stage / 'lifecycle.py', meta['sources']['lifecycle'], 0)
    owner = Owner(lifecycle, work, end)
    primary = None
    report = dict(schema=1, operation='root_isolation_supervisor', status='failed', stage='host_before',
        studio_revision=meta['revision'], source_sha256=meta['sources'], worker=None, namespace_parent_joined=False,
        namespace_init_exit_confirmed=False, host_before_sha256=None, host_after_sha256=None,
        host_network_configuration_unchanged=False, root_carrier_removed=False,
        source_groups_started=meta['source_groups_started'], source_groups_joined=meta['source_groups_joined'],
        owned_groups_started=0, owned_groups_joined=0, failure_kind=None)
    try:
        before = host_network(owner)
        report['host_before_sha256'] = before
        report['stage'] = 'namespace_worker'
        env = {k: os.environ[k] for k in HOST_KEYS}
        env.update(ENV, VP_ISOLATION_WORK_NS=os.environ['VP_ISOLATION_WORK_NS'],
                   VP_ISOLATION_END_NS=os.environ['VP_ISOLATION_END_NS'])
        raw = owner.run(namespace_command(stage), environment=env, payload=BOOT,
                        keep_stdin=True, cooperative=True, seconds=90, role='namespace')
        worker = parse(raw)
        require(worker.get('operation') == 'namespace_isolation_worker' and worker.get('status') == 'passed'
                and worker.get('stage') == 'complete' and worker.get('namespace_groups_started', 0) > 0
                and worker['namespace_groups_started'] == worker.get('namespace_groups_joined')
                and worker.get('actors_started') == worker.get('actors_joined') == 2, 'cleanup')
        report.update(worker=worker, namespace_parent_joined=True, namespace_init_exit_confirmed=True, stage='host_after')
        after = host_network(owner)
        report['host_after_sha256'] = after
        require(after == before, 'host_changed')
        report['host_network_configuration_unchanged'] = True
    except BaseException as error:
        primary = error
        # Optional closed worker failure observations never change accepted exit.
        try:
            failed = parse(owner.last_output)
            require(failed.get('operation') == 'namespace_isolation_worker'
                    and failed.get('status') == 'failed' and failed.get('failure_kind') in KINDS
                    and failed.get('stage') in WORKER_STAGES
                    and failed.get('actor_failure_predicate') in ACTOR_PREDICATES | {None}
                    and failed.get('owner_scope') == 'namespace_process_groups'
                    and all(type(failed.get(key)) is int and 0 <= failed[key] <= 128 for key in
                        ('namespace_groups_started', 'namespace_groups_joined', 'actors_started', 'actors_joined')))
            report['worker'] = {key: failed[key] for key in
                ('schema', 'operation', 'status', 'stage', 'failure_kind', 'namespace_groups_started',
                 'namespace_groups_joined', 'actors_started', 'actors_joined', 'owner_scope', 'actor_failure_predicate')}
        except BaseException:
            pass
    finally:
        def remove():
            require(owner.started == owner.joined, 'cleanup')
            directory(stage, 0, private=True)
            require(set(p.name for p in stage.iterdir()) == set(FILENAMES.values()) | {'carrier.json'}, 'cleanup')
            shutil.rmtree(stage)
            report['root_carrier_removed'] = True
        primary = masked_cleanup(primary, remove)
        report.update(owned_groups_started=owner.started, owned_groups_joined=owner.joined)
        if primary is None:
            report.update(status='passed', stage='complete')
        else:
            report['failure_kind'] = primary.kind if isinstance(primary, Rejected) else 'cleanup'
    print(json.dumps(report, sort_keys=True))
    require(primary is None, 'cleanup')


def supervisor_entry():
    require(os.getuid() == os.geteuid() == 0)
    root, revision = admission_environment()
    require(Path(__file__).resolve() == root / SOURCES['root'], 'source')
    work, end = deadlines()
    boot_read(min(work, time.monotonic() + 5))
    uid, gid = owner_identity(root)
    stage = stage_path()
    directory(Path('/run'), 0)
    require(not stage.exists() and not stage.is_symlink(), 'filesystem')
    stage.mkdir(mode=0o700)
    primary = None
    owner = None
    try:
        # The one approved frozen lifecycle is authenticated before import, then
        # copied to the root-only carrier. All subsequent Git actors are bounded
        # and joined by that immutable copy, not subprocess.run/communicate.
        frozen = read(root / LIFECYCLE, MAX_SOURCE, owner=uid, modes=(0o644,))
        require(hashlib.sha256(frozen).hexdigest() == LIFECYCLE_SHA, 'source')
        write_new(stage / 'lifecycle.py', frozen)
        lifecycle = load_lifecycle(stage / 'lifecycle.py', LIFECYCLE_SHA, 0)
        owner = Owner(lifecycle, work, end)
        payloads = source_payloads(owner, root, revision, uid)
        hashes = {label: hashlib.sha256(raw).hexdigest() for label, raw in payloads.items()}
        for label, raw in payloads.items():
            if label != 'lifecycle':
                write_new(stage / FILENAMES[label], raw)
        require(owner.started == owner.joined, 'cleanup')
        write_new(stage / 'carrier.json', encoded(dict(schema=1, revision=revision, uid=uid, gid=gid,
            parent_namespaces=current_namespaces(), sources=hashes,
            host_canary=str(Path(os.environ['RUNNER_TEMP']) / 'silex-native-isolation-private-v1/host-canary'),
            host_ipc_canary='/dev/shm/volparossa-native-isolation-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT'],
            parent_ipc_views={name: [os.stat('/dev/' + name).st_dev, os.stat('/dev/' + name).st_ino]
                              for name in ('shm', 'mqueue')},
            source_groups_started=owner.started, source_groups_joined=owner.joined)))
        env = dict(os.environ)
        # All descriptors except stdio are opened/closed locally; exec consumes
        # only root-owned files. No user module path or bytecode is enabled.
        os.execve('/usr/bin/python3', ['/usr/bin/python3', '-I', '-B',
                  str(stage / 'isolation_root.py'), '--supervisor-staged'], env)
    except BaseException as error:
        primary = error
    def remove():
        require(owner is None or owner.started == owner.joined, 'cleanup')
        directory(stage, 0, private=True)
        shutil.rmtree(stage)
    primary = masked_cleanup(primary, remove)
    raise primary


def entry():
    require(len(sys.argv) == 2 and sys.argv[1] in
            ('--privileged-supervisor', '--supervisor-staged', '--namespace-init'))
    def cancelled(number, _frame):
        raise Rejected('deadline' if number == signal.SIGALRM else 'cancelled')
    for number in SIGNALS:
        signal.signal(number, cancelled)
    _work, end = deadlines()
    signal.setitimer(signal.ITIMER_REAL, max(0.001, end - time.monotonic()))
    {'--privileged-supervisor': supervisor_entry,
     '--supervisor-staged': staged_supervisor, '--namespace-init': namespace_init}[sys.argv[1]]()


if __name__ == '__main__':
    try:
        entry()
    except BaseException:
        raise SystemExit(1) from None
