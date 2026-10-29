# SPDX-License-Identifier: GPL-3.0-only
"""Original dashboard asset adapter; no command, network or application execution.

The future native build caller must admit the complete pinned Silex/FS source
before calling install(). This adapter only populates its empty gitlink directory.
It is not wired into a hosted profile until that composition is reviewed.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

HERE = Path(__file__).resolve().parent
ASSETS = ('dashboard.css', 'dashboard.js', 'index.html')
MAX_ASSET = 128 * 1024
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)


class Rejected(ValueError):
    pass


def require(value):
    if not value:
        raise Rejected('original dashboard composition rejected')


def pairs(rows):
    result = {}
    for key, value in rows:
        require(key not in result)
        result[key] = value
    return result


def identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def cleanup(primary, action):
    """Defer cancellation through fixed-size cleanup, retaining an old primary.

    This does not promise interruption of kernel-stalled filesystem work. The
    admitted hosted caller owns the outer deadline and source-tree disposal.
    """
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


class Descriptors:
    """Small local FD ownership ledger; no fdopen ownership-transfer gap."""
    def __init__(self):
        self.owned = []

    def open(self, *args, **kwargs):
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
        descriptor = None
        registered = False
        primary = None
        try:
            descriptor = os.open(*args, **kwargs)
            self.owned.append(descriptor)
            registered = True
        except BaseException as error:
            primary = error
        finally:
            if descriptor is not None and not registered:
                try:
                    os.close(descriptor)
                except BaseException as error:
                    primary = primary or error
            # Unmasking may deliver cancellation before the caller receives the
            # return value. The ledger already owns any opened descriptor.
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)
            except BaseException as error:
                primary = primary or error
        if primary is not None:
            raise primary
        return descriptor

    def close(self, descriptor):
        require(descriptor in self.owned)
        # Never retry an ambiguous close against a potentially reused FD number.
        self.owned.remove(descriptor)
        os.close(descriptor)

    def close_all(self):
        primary = None
        for descriptor in tuple(reversed(self.owned)):
            try:
                self.close(descriptor)
            except BaseException as error:
                primary = primary or error
        if primary is not None:
            raise primary


def read_descriptor(descriptor, maximum):
    raw = bytearray()
    while len(raw) <= maximum:
        part = os.read(descriptor, min(65536, maximum + 1 - len(raw)))
        if not part:
            break
        raw.extend(part)
    require(len(raw) <= maximum)
    return bytes(raw)


def close_one(owners, descriptor):
    primary = cleanup(None, lambda: owners.close(descriptor))
    if primary is not None:
        raise primary


def read(path, maximum):
    require(path.is_absolute() and path.resolve(strict=True) == path)
    owners = Descriptors()
    primary = None
    try:
        fd = owners.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
                and before.st_nlink == 1 and not before.st_mode & 0o022
                and 0 < before.st_size <= maximum)
        raw = read_descriptor(fd, maximum)
        require(identity(before) == identity(os.fstat(fd))
                and len(raw) == before.st_size <= maximum)
    except BaseException as error:
        primary = error
    finally:
        primary = cleanup(primary, owners.close_all)
    if primary is not None:
        raise primary
    return raw


def assets():
    raw = read(HERE / 'manifest.json', 65536)
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _value: require(False))
    require(type(value) is dict and value.keys() == {'schema', 'operation', 'files', 'scope', 'tests'}
            and type(value['schema']) is int and value['schema'] == 1
            and value['operation'] == 'original_local_dashboard_units'
            and type(value['files']) is dict
            and value['files'].keys() == set(ASSETS) | {'test_dashboard.mjs'}
            and value['scope'] == dict(native_gui=False, publication_authorized=False,
                                      real_server_crud=False, unit_fixture_only=True))
    result = {}
    for name, row in value['files'].items():
        require(type(row) is dict and row.keys() == {'bytes', 'sha256'}
                and type(row['bytes']) is int and 0 < row['bytes'] <= MAX_ASSET
                and type(row['sha256']) is str and len(row['sha256']) == 64
                and all(c in '0123456789abcdef' for c in row['sha256']))
        content = read(HERE / 'app' / name, MAX_ASSET)
        require(len(content) == row['bytes']
                and hashlib.sha256(content).hexdigest() == row['sha256'])
        if name in ASSETS:
            result[name] = content
    require(type(value['tests']) is list and 1 <= len(value['tests']) <= 128
            and all(type(name) is str and 0 < len(name) <= 256 for name in value['tests'])
            and len(set(value['tests'])) == len(value['tests']))
    return result, hashlib.sha256(raw).hexdigest()


def directory(fd, *, private=False):
    info = os.fstat(fd)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and not info.st_mode & 0o022
            and (not private or stat.S_IMODE(info.st_mode) == 0o700))
    return info.st_dev, info.st_ino


def visible_directory(parent_fd, name, expected):
    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and not info.st_mode & 0o022 and (info.st_dev, info.st_ino) == expected)


def names(descriptor, maximum):
    result = set()
    with os.scandir(descriptor) as entries:
        for entry in entries:
            require(len(result) < maximum)
            result.add(entry.name)
    return result


def install(source):
    """Copy exactly three authenticated original assets in a hosted private tree.

    The destination must be empty. No upstream dashboard source is fetched, and
    test files are not embedded. Failure cleanup is best effort, restricted to
    observed owned files; unknown replacements are retained. There is NO confirmed
    rollback result: the caller MUST abandon the entire disposable source tree on
    ANY exception, even if three complete assets exist. Never retry in place.

    Checks reject observed changes, not arbitrary races by another process with
    the same UID. The caller admits exact Studio and pinned Silex/FS source before
    this adapter, then verifies its expected source changes afterward.
    """
    require(os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and os.environ.get('GITHUB_REPOSITORY') == 'VOLPAROSSA/volparossa-studio'
            and os.getuid() == os.geteuid() != 0)
    workspace = Path(os.environ.get('GITHUB_WORKSPACE', ''))
    require(workspace.is_absolute() and workspace.resolve(strict=True) == workspace
            and source == workspace / 'silex' and source.resolve(strict=True) == source)
    content, manifest_sha = assets()
    source_fd = target_fd = public_fd = None
    created = {}
    source_identity = target_identity = public_identity = None
    primary = None
    owners = Descriptors()

    def rollback_and_close():
        # Some failures precede inode capture. Unknown paths remain for the
        # caller's disposable-tree abandonment, never a complete rollback claim.
        try:
            if primary is not None and public_fd is not None:
                for name, inode in created.items():
                    try:
                        current = os.stat(name, dir_fd=public_fd, follow_symlinks=False)
                        require(stat.S_ISREG(current.st_mode) and current.st_uid == os.geteuid()
                                and (current.st_dev, current.st_ino) == inode)
                        os.unlink(name, dir_fd=public_fd)
                    except BaseException:
                        # Retain observed replacements or uncertain files.
                        pass
                try:
                    current = os.stat('public', dir_fd=target_fd, follow_symlinks=False)
                    require((current.st_dev, current.st_ino) == public_identity
                            and not names(public_fd, 3))
                    os.rmdir('public', dir_fd=target_fd)
                except BaseException:
                    pass
        finally:
            owners.close_all()

    try:
        source_fd = owners.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        source_identity = directory(source_fd)
        target_fd = owners.open('silex-dashboard-2026', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=source_fd)
        target_identity = directory(target_fd)
        require(not names(target_fd, 0))
        os.mkdir('public', 0o700, dir_fd=target_fd)
        public_fd = owners.open('public', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=target_fd)
        public_identity = directory(public_fd, private=True)
        for name in ASSETS:
            fd = owners.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=public_fd)
            info = os.fstat(fd)
            created[name] = (info.st_dev, info.st_ino)
            remaining = memoryview(content[name])
            while remaining:
                count = os.write(fd, remaining[:65536])
                require(0 < count <= len(remaining[:65536]))
                remaining = remaining[count:]
            os.fsync(fd)
            close_one(owners, fd)
        os.fsync(public_fd)
        require(names(public_fd, 3) == set(ASSETS))
        for name in ASSETS:
            fd = owners.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=public_fd)
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and before.st_uid == os.geteuid() and stat.S_IMODE(before.st_mode) == 0o600
                    and (before.st_dev, before.st_ino) == created[name]
                    and before.st_size == len(content[name]))
            require(read_descriptor(fd, MAX_ASSET) == content[name]
                    and identity(before) == identity(os.fstat(fd)))
            close_one(owners, fd)
        os.fsync(target_fd)
        current_content, current_manifest = assets()
        require(current_manifest == manifest_sha and current_content == content)
        # Bind the visible tree to the FDs actually populated/verified. These are
        # observed identity checks, not cross-process CAS or same-UID immunity.
        require(source.resolve(strict=True) == source)
        visible_directory(None, source, source_identity)
        visible_directory(source_fd, 'silex-dashboard-2026', target_identity)
        visible_directory(target_fd, 'public', public_identity)
        require(directory(source_fd) == source_identity and directory(target_fd) == target_identity
                and directory(public_fd, private=True) == public_identity
                and names(target_fd, 1) == {'public'}
                and names(public_fd, 3) == set(ASSETS))
    except BaseException as error:
        primary = error
    finally:
        primary = cleanup(primary, rollback_and_close)
    if primary is not None:
        raise primary
    rows = [{'path': 'public/' + name, 'bytes': len(content[name]),
             'sha256': hashlib.sha256(content[name]).hexdigest()} for name in ASSETS]
    return dict(schema=1, operation='original_dashboard_asset_composition',
                manifest_sha256=manifest_sha, assets=rows, asset_count=3,
                embedded_assets_license='GPL-3.0-only', application_executed=False,
                native_gui_verified=False, real_server_crud=False,
                redistribution_acceptance=False, publication_authorized=False)
