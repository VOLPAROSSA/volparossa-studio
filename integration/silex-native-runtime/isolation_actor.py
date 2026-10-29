# SPDX-License-Identifier: GPL-3.0-only
"""Public synthetic admission/calibration actor; no application or display."""
import errno
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys

NAMESPACES = ('net', 'mnt', 'pid', 'ipc')
KEYS = frozenset(('uid_original', 'gid_original', 'groups_cleared', 'capabilities_zero',
    'no_new_privileges', 'private_namespaces', 'private_proc', 'private_home', 'private_xdg',
    'private_tmp', 'host_workspace_hidden', 'host_bus_absent', 'host_xauthority_absent',
    'display_environment_absent', 'sandbox_disable_flags_absent', 'inherited_fds_closed',
    'root_mount_readonly', 'private_resolver_profile', 'private_shared_memory', 'private_mqueue'))
RESOLVER = b'nameserver 127.0.0.53\noptions attempts:1 timeout:1\n'
QUERY = bytes.fromhex('475001000001000000000000') + b'\x0bcalibration\x07invalid\0\0\x01\0\x01'
REPLY = QUERY[:2] + bytes.fromhex('81830001000000000000') + QUERY[12:]
PREDICATES = KEYS | {'shape', 'protocol', 'dns', 'ipv4_datagram', 'ipv6_datagram'}


class Rejected(ValueError):
    def __init__(self, predicate):
        self.predicate = predicate if predicate in PREDICATES else 'shape'
        super().__init__('synthetic isolation actor rejected')


def require(value, predicate='shape'):
    if not value:
        raise Rejected(predicate)


def bounded_read(path, maximum):
    with open(path, 'rb') as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum)
    return raw


def status():
    rows = {}
    for line in bounded_read('/proc/self/status', 65536).decode('ascii').splitlines():
        if ':' in line:
            name, value = line.split(':', 1)
            require(name not in rows)
            rows[name] = value.strip()
    return rows


def private_directory(path, uid):
    require(path.is_absolute() and path.resolve(strict=True) == path)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == uid and stat.S_IMODE(info.st_mode) == 0o700)
    # Actual write/read/delete, limited to this deliberately private fixture dir.
    probe = path / '.isolation-write-probe'
    descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        require(os.write(descriptor, b'public fixture') == 14)
    finally:
        os.close(descriptor)
    try:
        require(bounded_read(probe, 64) == b'public fixture')
    finally:
        probe.unlink()


def private_ipc_views(parent, mounts, marker):
    """Observed mount identities + a real host-marker absence, not IPC flags alone."""
    require(type(parent) is dict and set(parent) == {'shm', 'mqueue'})
    for name, kind, predicate in (('shm', 'tmpfs', 'private_shared_memory'), ('mqueue', 'mqueue', 'private_mqueue')):
        path = '/dev/' + name
        info = os.stat(path)
        require(type(parent[name]) is list and len(parent[name]) == 2
                and all(type(v) is int and v >= 0 for v in parent[name])
                and [info.st_dev, info.st_ino] != parent[name], predicate)
        rows = [line.split() for line in mounts if len(line.split()) >= 10 and line.split()[4] == path]
        require(rows and rows[-1][rows[-1].index('-') + 1] == kind
                and {'nosuid', 'nodev', 'noexec'} <= set(rows[-1][5].split(',')), predicate)
    require(marker.parent == Path('/dev/shm') and re.fullmatch(r'volparossa-native-isolation-[0-9]+-[0-9]+', marker.name)
            and not marker.exists() and not marker.is_symlink(), 'private_shared_memory')


def admission():
    uid, gid = (int(os.environ[key]) for key in ('VP_ISOLATION_UID', 'VP_ISOLATION_GID'))
    require(1000 <= uid < 2**31 and 0 < gid < 2**31)
    require(sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1)
    values = status()
    require([int(x) for x in values['Uid'].split()] == [uid] * 4 and os.getuid() == os.geteuid() == uid, 'uid_original')
    require([int(x) for x in values['Gid'].split()] == [gid] * 4 and os.getgid() == os.getegid() == gid, 'gid_original')
    require(not values['Groups'].split() and not os.getgroups(), 'groups_cleared')
    require(all(int(values[key], 16) == 0 for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')), 'capabilities_zero')
    require(values['NoNewPrivs'] == '1', 'no_new_privileges')
    parent = json.loads(os.environ['VP_PARENT_NAMESPACES'])
    require(type(parent) is dict and set(parent) == set(NAMESPACES))
    for name in NAMESPACES:
        current = os.readlink('/proc/self/ns/' + name)
        require(re.fullmatch(name + r':\[[0-9]+\]', current) and current != parent[name], 'private_namespaces')
    # A procfs mounted for this PID namespace reports only the local NSpid view.
    require(os.getpid() > 1 and os.getppid() == 1
            and values['NSpid'].split() == [str(os.getpid())], 'private_proc')
    init = bounded_read('/proc/1/status', 65536)
    require(re.search(rb'^Pid:\s+1$', init, re.M) and re.search(rb'^Uid:\s+0\s+0\s+0\s+0$', init, re.M))
    # This asserts only the top root mount, not every inherited child mount.
    require(os.statvfs('/').f_flag & os.ST_RDONLY, 'root_mount_readonly')
    expected = {'HOME': '/home/fixture', 'XDG_CONFIG_HOME': '/home/fixture/config',
        'XDG_DATA_HOME': '/home/fixture/data', 'XDG_CACHE_HOME': '/home/fixture/cache',
        'XDG_RUNTIME_DIR': '/run/user/' + str(uid), 'TMPDIR': '/tmp/fixture'}
    for key, value in expected.items():
        require(os.environ.get(key) == value)
        private_directory(Path(value), uid)
    canary = Path(os.environ['VP_HOST_CANARY'])
    require(canary.is_absolute() and len(str(canary)) <= 1024
            and canary.name == 'host-canary' and canary.parent.name == 'silex-native-isolation-private-v1'
            and not canary.exists() and not canary.is_symlink(), 'host_workspace_hidden')
    require(all(not Path(path).exists() and not Path(path).is_symlink() for path in (
        '/run/dbus/system_bus_socket', '/var/run/dbus/system_bus_socket',
        '/run/user/' + str(uid) + '/bus', '/home/fixture/.Xauthority', '/tmp/.X11-unix')))
    require(not any(name in os.environ for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY',
        'DBUS_SESSION_BUS_ADDRESS', 'DBUS_SYSTEM_BUS_ADDRESS', 'PYTHONPATH', 'PYTHONHOME',
        'LD_PRELOAD', 'LD_LIBRARY_PATH', 'SENTRY_DSN', 'GLITCHTIP_DSN', 'NODE_OPTIONS')))
    require(not any(name.startswith(('WEBKIT_', 'GTK_', 'GDK_')) for name in os.environ), 'sandbox_disable_flags_absent')
    inherited = {}
    for name in os.listdir('/proc/self/fd'):
        try:
            inherited[name] = os.readlink('/proc/self/fd/' + name)
        except FileNotFoundError:
            pass  # The completed procfs enumeration closed its own FD.
    require(set(inherited) == {'0', '1', '2'} and inherited['0'] == '/dev/null'
            and all(inherited[name].startswith('pipe:[') for name in ('1', '2')), 'inherited_fds_closed')
    require(bounded_read('/etc/resolv.conf', 256) == RESOLVER, 'private_resolver_profile')
    ipc_parent = json.loads(os.environ['VP_PARENT_IPC_VIEWS'])
    mounts = bounded_read('/proc/self/mountinfo', 512 * 1024).decode('ascii').splitlines()
    marker = Path(os.environ['VP_HOST_IPC_CANARY'])
    private_ipc_views(ipc_parent, mounts, marker)
    return dict(schema=1, operation='isolation_actor_admission', passed=True,
                **dict.fromkeys(KEYS, True))


def denied_datagram(family, target):
    with socket.socket(family, socket.SOCK_DGRAM) as client:
        client.settimeout(1)
        try:
            require(client.sendto(b'public-calibration', target) == 18)
        except OSError as error:
            # NF_DROP may return EPERM. ENETUNREACH/EHOSTUNREACH never proves
            # observation: require the separate namespace nft counter as well.
            require(error.errno in (errno.EPERM, errno.EACCES))


def calibration():
    admission()  # Same actual UID/capability/private-view checks, no extra output.
    denied_datagram(socket.AF_INET, ('198.51.100.9', 9))
    denied_datagram(socket.AF_INET6, ('2001:db8:2::9', 9))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as dns:
        dns.settimeout(2)
        dns.bind(('127.0.0.1', 0))
        require(dns.sendto(QUERY, ('127.0.0.53', 53)) == len(QUERY))
        packet, address = dns.recvfrom(513)
        require(packet == REPLY and address == ('127.0.0.53', 53))
    return dict(schema=1, operation='isolation_actor_calibration', ipv4_attempts=1,
                ipv6_attempts=1, dns_attempts=1, dns_response_verified=True)


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 2 and sys.argv[1] in ('admission', 'calibration'))
        result = admission() if sys.argv[1] == 'admission' else calibration()
        print(json.dumps(result, sort_keys=True))
    except BaseException as error:
        print(json.dumps(dict(schema=1, operation='isolation_actor_failure', status='failed',
                              predicate=error.predicate if isinstance(error, Rejected) else 'shape'), sort_keys=True))
        raise SystemExit(1) from None
