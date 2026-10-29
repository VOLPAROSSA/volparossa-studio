#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Private hosted native release compilation; no application or installer execution.

The genuine dashboard's license is not verified. No ELF, dashboard, generated
frontend or raw build log is an upload artifact; only the closed receipt is.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import selectors
import shutil
import signal
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXPORT = HERE.parent / 'silex-export'
DASHBOARD_COMMIT = 'cb36b01a609915facfb1c134f96a98eabcdd3374'
DASHBOARD_ORIGIN = 'https://gitlab.com/silexlabs/silex_silex-dashboard-2026.git'
DASHBOARD_MANIFEST = 'b5c534f85d883b837a64dae853012a47bc0ededf38602e40e5964f8064a46d49'
SDK_MANIFEST = 'c2e3e609b6dc9e204b65d173ac087be89c37e06f25e10c997dd1fd87831178a8'
EXPORT_MANIFEST = '02e054803e94f8773905af43a4d7aaaaedbc382a67ee27aa5ae6349ff58ca611'
PNPM_LOCK = '02bb3b4a2db54b4a708b73c37318161163eaf160d610ae37c25db8f9b0dc64c1'
NATIVE_LOCK = 'de04aaf5ff1acbdde421e3447ea67f3eb7a00a7d5ed118f4387a180e84590118'
SCHEMAS = frozenset('desktop/src-tauri/gen/schemas/' + name + '.json'
                    for name in ('acl-manifests', 'capabilities', 'desktop-schema', 'linux-schema'))
SDK_FALSE = frozenset(('native_build', 'native_runtime_acceptance', 'native_gui_verified',
                       'full_application_privacy', 'full_studio_acceptance', 'volparossa_updates_verified'))
KINDS = frozenset(('admission', 'sdk_rejected', 'source_rejected', 'dashboard_rejected',
                   'compiler_rejected', 'carrier_rejected', 'child_failed', 'output_limit',
                   'deadline', 'cancelled', 'cleanup_failed', 'artifact_failed'))
MAX_NATIVE_LOG = 16 * 1024 * 1024
MAX_ERROR_CODES = 16
MAX_ERROR_LINES = 256


class Rejected(RuntimeError):
    def __init__(self, kind):
        if kind not in KINDS:
            raise ValueError('closed build failure required')
        self.kind = kind
        super().__init__('native private build rejected')


def require(condition, kind='source_rejected'):
    if not condition:
        raise Rejected(kind)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SUPPORT = load('native_build_lock_support', HERE / 'resolve_lock.py')


def read_file(path, maximum, *, modes=(0o600, 0o644), allow_empty=False):
    require(path.is_absolute() and path.resolve(strict=True) == path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) in modes
                and (0 if allow_empty else 1) <= before.st_size <= maximum)
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        require(len(raw) == before.st_size and len(raw) <= maximum
                and all(getattr(before, key) == getattr(after, key) for key in fields))
    return raw


def file_hash(path, maximum, *, executable=False, cargo_output=False):
    require(path.resolve(strict=True) == path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
                and (before.st_nlink >= 1 if cargo_output else before.st_nlink == 1)
                and not before.st_mode & 0o022 and 0 <= before.st_size <= maximum
                and (not executable or before.st_mode & 0o100))
        digest = hashlib.sha256()
        count = 0
        header = b''
        while chunk := stream.read(65536):
            if count == 0:
                header = chunk[:20]
            count += len(chunk)
            require(count <= maximum)
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        require(count == before.st_size and all(getattr(before, key) == getattr(after, key) for key in fields))
        if cargo_output:
            require(len(header) == 20 and header[:6] == b'\x7fELF\x02\x01'
                    and int.from_bytes(header[16:18], 'little') in (2, 3)
                    and int.from_bytes(header[18:20], 'little') == 62)
    current = path.lstat()
    require(all(getattr(current, key) == getattr(after, key) for key in fields))
    record = dict(bytes=count, sha256=digest.hexdigest(), mode=stat.S_IMODE(after.st_mode))
    if cargo_output:
        record['links'] = after.st_nlink
    return record


def dashboard_manifest(raw):
    require(hashlib.sha256(raw).hexdigest() == DASHBOARD_MANIFEST, 'dashboard_rejected')
    value = SUPPORT.json_value(raw)
    require(type(value) is dict and value.keys() == {'binding', 'commit', 'external_module', 'license',
        'local_execution', 'native_runtime_acceptance', 'public_assets', 'public_bytes',
        'redistribution_acceptance', 'schema', 'silex_parent_commit', 'source'}, 'dashboard_rejected')
    require(type(value['schema']) is int and value['schema'] == 1
            and value['commit'] == DASHBOARD_COMMIT and value['source'] == DASHBOARD_ORIGIN
            and value['binding'] == 'existing parent gitlink' and value['silex_parent_commit'] == SUPPORT.UPSTREAM
            and value['license'] == 'Not verified: no license file or explicit declaration observed at this commit'
            and value['external_module'] == 'https://unpkg.com/petite-vue@0.4.1/dist/petite-vue.es.js'
            and all(value[key] is False for key in ('local_execution', 'native_runtime_acceptance',
                                                   'redistribution_acceptance')), 'dashboard_rejected')
    rows = value['public_assets']
    require(type(rows) is list and len(rows) == 9, 'dashboard_rejected')
    previous = None
    for row in rows:
        require(type(row) is dict and row.keys() == {'path', 'git_blob', 'bytes', 'sha256'}, 'dashboard_rejected')
        name = row['path']
        require(type(name) is str and re.fullmatch(r'public/[A-Za-z0-9_./-]{1,200}', name)
                and all(part not in ('', '.', '..') and not part.startswith('.') for part in name.split('/')),
                'dashboard_rejected')
        require(previous is None or previous < name, 'dashboard_rejected')
        previous = name
        require(type(row['bytes']) is int and 0 < row['bytes'] <= 65536
                and type(row['sha256']) is str and re.fullmatch('[0-9a-f]{64}', row['sha256'])
                and type(row['git_blob']) is str and re.fullmatch('[0-9a-f]{40}', row['git_blob']), 'dashboard_rejected')
    require(type(value['public_bytes']) is int and value['public_bytes'] == 79203
            and sum(row['bytes'] for row in rows) == 79203, 'dashboard_rejected')
    return rows


def sdk_receipts(outer, root, revision, records, installer):
    require(re.fullmatch(r'[1-9][0-9]{0,19}', os.environ.get('GITHUB_RUN_ID', ''))
            and re.fullmatch(r'[1-9][0-9]{0,5}', os.environ.get('GITHUB_RUN_ATTEMPT', '')), 'sdk_rejected')
    outer_keys = {'schema', 'mode', 'status', 'stage', 'sdk_manifest_sha256', 'packages_installed',
                  'sdk_installed', 'studio_revision', 'verified_package_count', 'archive_bytes', 'hashes', 'cleanup',
                  'admission_diagnostic'} | SDK_FALSE
    require(type(outer) is dict and outer.keys() == outer_keys and type(outer['schema']) is int
            and outer['schema'] == 1 and outer['mode'] == 'native-sdk-offline-install'
            and outer['status'] == 'passed' and outer['stage'] == 'complete'
            and outer['studio_revision'] == revision and outer['sdk_manifest_sha256'] == SDK_MANIFEST
            and outer['packages_installed'] is True and outer['sdk_installed'] is True
            and type(outer['verified_package_count']) is int and outer['verified_package_count'] == 182
            and type(outer['archive_bytes']) is int and outer['archive_bytes'] == 63772228
            and outer['hashes'] == installer.expected_hashes(records)
            and outer['admission_diagnostic'] == {'substage': 'complete'}
            and all(outer[key] is False for key in SDK_FALSE), 'sdk_rejected')
    require(outer['cleanup'] == {'owned_groups_joined': True, 'owned_group_count': 1,
                                'root_cache_retained': True, 'package_rollback_attempted': False}
            and type(outer['cleanup']['owned_group_count']) is int
            and outer['cleanup']['owned_groups_joined'] is True
            and outer['cleanup']['root_cache_retained'] is True
            and outer['cleanup']['package_rollback_attempted'] is False, 'sdk_rejected')
    root_keys = {'schema', 'mode', 'status', 'stage', 'sdk_manifest_sha256', 'packages_installed',
                 'sdk_installed', 'network_namespace_isolated', 'root_archive_cache_verified',
                 'post_install_exact_versions', 'dpkg_audit_clean', 'installation_attempted',
                 'policy_created', 'policy_restored', 'root_cache_retained', 'owned_groups_joined',
                 'owned_group_count', 'studio_revision', 'run_id', 'run_attempt', 'verified_package_count', 'hashes',
                 'admission_diagnostic', 'planned_package_count', 'plan_sha256'} | SDK_FALSE
    require(type(root) is dict and root.keys() == root_keys and type(root['schema']) is int
            and root['installation_attempted'] is True
            and root['admission_diagnostic'] == {'substage': 'complete'}
            and type(root['planned_package_count']) is int and 0 <= root['planned_package_count'] <= 182
            and type(root['plan_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', root['plan_sha256'])
            and root['run_id'] == os.environ.get('GITHUB_RUN_ID')
            and root['run_attempt'] == os.environ.get('GITHUB_RUN_ATTEMPT'), 'sdk_rejected')
    installer.check_root(root, revision, records)


def actor(argv, env, cwd, deadline, groups, lifecycle, *, capture=2 * 1024 * 1024, log=None, seconds=600, git_limit=False):
    require(time.monotonic() < deadline - 10, 'deadline')
    options = dict(env=env, cwd=cwd, stdin=SUPPORT.subprocess.DEVNULL,
                   stdout=SUPPORT.subprocess.PIPE, stderr=SUPPORT.subprocess.PIPE, umask=0o022)
    if git_limit:
        options['preexec_fn'] = lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024,) * 2)
    process = identity = None
    primary = None
    output = bytearray()
    written = 0
    log_stream = None
    end = min(deadline - 10, time.monotonic() + seconds)
    try:
        process, identity = lifecycle.start_group(list(map(str, argv)), **options)
        if log is not None:
            descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            log_stream = os.fdopen(descriptor, 'wb')
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                require(time.monotonic() < end, 'deadline')
                for key, _events in selector.select(min(0.25, max(0, end - time.monotonic()))):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        written += len(chunk)
                        require(written <= (16 * 1024 * 1024 if log_stream else capture + 65536), 'output_limit')
                        if log_stream:
                            log_stream.write(chunk)
                        elif key.fileobj is process.stdout:
                            require(len(output) + len(chunk) <= capture, 'output_limit')
                            output.extend(chunk)
        # Preserve the unreaped leader until the drain owner targets its group.
        while True:
            require(time.monotonic() < end, 'deadline')
            observed = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if observed is not None:
                break
            time.sleep(min(0.01, max(0, end - time.monotonic())))
        require(observed.si_pid == process.pid and observed.si_code == os.CLD_EXITED and observed.si_status == 0,
                'child_failed')
    except BaseException as error:
        primary = error
        capture_failure = getattr(lifecycle, 'GroupCaptureFailure', None)
        if process is None and capture_failure is not None and isinstance(error, capture_failure):
            groups.append(False)  # A child started, but its group identity/drain was not confirmed.
    finally:
        numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
        previous = {number: signal.getsignal(number) for number in numbers}
        pending = set()
        for number in numbers:
            signal.signal(number, lambda number, _frame: pending.add(number))
        joined = process is None
        try:
            if process is not None:
                result = lifecycle.drain_group(process, identity, grace=1, kill_grace=1)
                joined = result['leader_joined'] is True and result['live_group_drained'] is True
        except BaseException:
            joined = False
        finally:
            for stream in ((process.stdout, process.stderr, log_stream) if process is not None else (log_stream,)):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        joined = False
            def late_failure(error):
                if isinstance(error, Rejected) and error.kind in ('cancelled', 'deadline'):
                    return error
                return Rejected('cancelled' if isinstance(error, (KeyboardInterrupt, InterruptedError))
                                else 'cleanup_failed')

            # Keep the ownership handoff atomic with respect to these signals:
            # restoring the first original handler must not interrupt the other
            # restores or skip the measured group result. Preserve any old mask.
            old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
            restore_error = None
            try:
                for number, handler in previous.items():
                    try:
                        signal.signal(number, handler)
                    except BaseException as error:
                        restore_error = restore_error or error
                if process is not None:
                    groups.append(joined)
                if primary is None and (pending or not joined):
                    primary = Rejected('deadline' if signal.SIGALRM in pending else 'cancelled' if pending else 'cleanup_failed')
                if primary is None and restore_error is not None:
                    primary = late_failure(restore_error)
            finally:
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
                except BaseException as error:
                    # A queued late cancellation can be delivered while the
                    # mask is restored. All cleanup accounting is already done.
                    if primary is None:
                        primary = late_failure(error)
    if primary is not None:
        raise primary
    return bytes(output)


def git(argv, cwd, env, deadline, groups, lifecycle, **options):
    return actor(['/usr/bin/git', '--no-pager', '--literal-pathspecs', '-c', 'core.fsmonitor=false',
                  '-c', 'core.hooksPath=/dev/null', '-c', 'http.followRedirects=false',
                  '-c', 'credential.helper=', *argv], env, cwd, deadline, groups, lifecycle, **options)


def gitlink(raw):
    require(raw == f'160000 commit {DASHBOARD_COMMIT}\tsilex-dashboard-2026\0'.encode(), 'dashboard_rejected')


def copy_asset(source, destination, row):
    raw = read_file(source, row['bytes'])
    require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], 'dashboard_rejected')
    SUPPORT.write_new(destination, raw)


def acquire_dashboard(source, work, rows, env, deadline, groups, lifecycle):
    gitlink(git(['-C', str(source), 'ls-tree', '-z', 'HEAD', '--', 'silex-dashboard-2026'],
                source, env, deadline, groups, lifecycle))
    repository = work / 'dashboard.git'
    git(['init', '--bare', str(repository)], work, env, deadline, groups, lifecycle)
    git(['--git-dir', str(repository), '-c', 'protocol.allow=never', '-c', 'protocol.https.allow=always',
         'fetch', '--no-tags', '--depth=1', DASHBOARD_ORIGIN, DASHBOARD_COMMIT], work, env, deadline, groups,
        lifecycle, seconds=120, git_limit=True)
    commit = git(['--git-dir', str(repository), 'rev-parse', 'FETCH_HEAD'], work, env, deadline, groups, lifecycle)
    require(commit.strip().decode() == DASHBOARD_COMMIT, 'dashboard_rejected')
    tree = git(['--git-dir', str(repository), 'ls-tree', '-r', '-z', DASHBOARD_COMMIT, '--', 'public'],
               work, env, deadline, groups, lifecycle)
    expected = b''.join(f"100644 blob {row['git_blob']}\t{row['path']}\0".encode() for row in rows)
    require(tree == expected, 'dashboard_rejected')
    staging = work / 'dashboard-source'
    staging.mkdir(mode=0o700)
    target = source / 'silex-dashboard-2026'
    if target.exists():
        SUPPORT.directory(target)
        require(not any(target.iterdir()), 'dashboard_rejected')
        target.chmod(0o700)
    else:
        target.mkdir(mode=0o700)
    for row in rows:
        raw = git(['--git-dir', str(repository), 'cat-file', 'blob', row['git_blob']],
                  work, env, deadline, groups, lifecycle, capture=row['bytes'] + 1)
        require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], 'dashboard_rejected')
        original, destination = staging / row['path'], target / row['path']
        original.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        SUPPORT.write_new(original, raw)
        copy_asset(original, destination, row)


def dashboard_unchanged(source, rows):
    root = source / 'silex-dashboard-2026'
    actual = set()
    for parent, directories, files in os.walk(root, followlinks=False):
        require(all(not (Path(parent) / name).is_symlink() for name in directories), 'dashboard_rejected')
        actual.update(str((Path(parent) / name).relative_to(root)) for name in files)
    require(actual == {row['path'] for row in rows}, 'dashboard_rejected')
    for row in rows:
        raw = read_file(root / row['path'], row['bytes'])
        require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], 'dashboard_rejected')


def tracked(source, extras, env, deadline, groups, lifecycle):
    raw = git(['-C', str(source), 'ls-files', '--stage', '-z'], source, env, deadline, groups, lifecycle)
    result = {}
    total = 0
    for entry in raw.split(b'\0'):
        if not entry:
            continue
        header, name = entry.decode('utf-8', errors='strict').split('\t', 1)
        mode, blob, stage = header.split()
        require(stage == '0' and not PurePosixPath(name).is_absolute()
                and all(part not in ('', '.', '..') for part in name.split('/')) and name not in result)
        path = source / name
        if mode == '160000':
            result[name] = dict(gitlink=blob)
        elif mode == '120000':
            require(path.is_symlink() and path.lstat().st_uid == os.geteuid())
            result[name] = dict(symlink=os.readlink(path), index_blob=blob)
        else:
            require(mode in ('100644', '100755'))
            if name in SCHEMAS and not path.exists() and not path.is_symlink():
                result[name] = None
                continue
            record = file_hash(path, 16 * 1024 * 1024)
            total += record['bytes']
            result[name] = dict(record, index_blob=blob)
        require(len(result) <= 10000 and total <= 128 * 1024 * 1024)
    for name in extras:
        result[name] = file_hash(source / name, 2 * 1024 * 1024)
    return result


def compare_sources(before, after):
    require(before.keys() == after.keys())
    require(all(before[name] == after[name] for name in before.keys() - SCHEMAS))
    return [dict(path=name, before=before[name], after=after[name]) for name in sorted(SCHEMAS)
            if before.get(name) != after.get(name)]


def source_check(source, before, extras, rows, env, deadline, groups, lifecycle):
    require(not git(['-C', str(source), 'diff', '--cached', '--name-only', '-z', 'HEAD', '--'],
                    source, env, deadline, groups, lifecycle))
    after = tracked(source, extras, env, deadline, groups, lifecycle)
    changes = compare_sources(before, after)
    other = git(['-C', str(source), 'ls-files', '--others', '-z', '--exclude=node_modules/**',
                 '--exclude=**/node_modules/**', '--exclude=dist/**', '--exclude=silex-dashboard-2026/**'],
                source, env, deadline, groups, lifecycle)
    require({name.decode() for name in other.split(b'\0') if name} == set(extras))
    require(hashlib.sha256(read_file(source / 'Cargo.lock', 2 * 1024 * 1024)).hexdigest() == NATIVE_LOCK
            and hashlib.sha256(read_file(source / 'pnpm-lock.yaml', 1024 * 1024)).hexdigest() == PNPM_LOCK)
    dashboard_unchanged(source, rows)
    # Studio is a separate sibling checkout: generated Silex outputs never
    # justify changed carrier, SDK, descriptor or caller source in Studio.
    prepare = sys.modules['native_build_prepare']
    prepare.hosted_guard(source)
    return changes


def frontend_inventory(root):
    require(root.resolve(strict=True) == root and root.is_dir())
    result = []
    total = 0
    for parent, directories, files in os.walk(root, followlinks=False):
        require(all(not (Path(parent) / name).is_symlink() for name in directories))
        for name in files:
            path = Path(parent) / name
            record = file_hash(path, 32 * 1024 * 1024)
            total += record['bytes']
            result.append(dict(path=str(path.relative_to(root)), **record))
            require(len(result) <= 4096 and total <= 128 * 1024 * 1024)
    result.sort(key=lambda row: row['path'])
    paths = {row['path']: row['bytes'] for row in result}
    require(paths.get('index.html', 0) > 0 and paths.get('js/main.js', 0) > 0)
    return result


def compiler(temporary):
    path = ROOT / 'integration/silex-publication/toolchain/provision-rust199.py'
    require(hashlib.sha256(read_file(path, 65536)).hexdigest()
            == '73183c57744925c962cfb2bd7414ac2c20df8848ddad20e6240ba3257a2f8fcd', 'compiler_rejected')
    module = load('native_build_compiler', path)
    prefix = temporary / 'volparossa-rust-1.99.1'
    SUPPORT.directory(prefix, private=True)  # Never invoke provision() or download an absent compiler.
    receipt = SUPPORT.json_value(read_file(prefix / 'receipt.json', 32768))
    module.validate_receipt(receipt)
    module.verify_payload(prefix, module.pins())
    return module, prefix


def export_carrier(work):
    raw = read_file(EXPORT / 'manifest.json', 65536)
    require(hashlib.sha256(raw).hexdigest() == EXPORT_MANIFEST, 'carrier_rejected')
    pins = SUPPORT.json_value(raw)
    require(pins['node']['version'] == '24.19.0' and pins['pnpm']['version'] == '10.34.4'
            and pins['silex']['lock_sha256'] == PNPM_LOCK, 'carrier_rejected')
    for name in ('extract', 'lifecycle', 'runtime_context'):
        load(name, EXPORT / (name + '.py'))
    carrier = load('native_build_carrier', EXPORT / 'run.py')
    node, pnpm = carrier.prepare(work)
    require(node == work / 'node/node' and pnpm == work / 'pnpm/package/bin/pnpm.cjs', 'carrier_rejected')
    require(file_hash(node, pins['node']['files']['bin/node']['bytes'], executable=True)['sha256']
            == pins['node']['files']['bin/node']['sha256'], 'carrier_rejected')
    return node, pnpm, pins


def release_command(temporary):
    return [str(temporary / 'volparossa-rust-1.99.1/bin/cargo'), 'build', '--offline', '--locked',
            '--release', '-p', 'silex-desktop', '--bin', 'silex-desktop']


def inspect_elf(path):
    # Cargo may hardlink its release/deps output. This is read-only inspection in
    # the fixed private target, not an independently owned distributable package.
    return file_hash(path, 512 * 1024 * 1024, executable=True, cargo_output=True)


def compiler_diagnostic(work, *, clipped=False):
    """Nonfatal marker observations, not a causal proof or a retained raw log.

    Only our own bounded Cargo-phase log is read. Any clipping or uncertainty
    discards content-derived fields; arbitrary messages never enter the receipt.
    """
    result = dict(schema=1, status='unavailable', rust_error_codes=[], error_lines=None,
                  pkg_config_missing=False, linker_failed=False, compiler_error=False,
                  log_sha256=None, log_bytes=None, raw_log_durably_retained=False, raw_log_artifact=False)
    try:
        raw = read_file(work / 'logs/native-cargo.log', MAX_NATIVE_LOG, modes=(0o600,), allow_empty=True)
        result.update(log_sha256=hashlib.sha256(raw).hexdigest(), log_bytes=len(raw))
        if clipped:
            result['status'] = 'clipped'
            return result
        codes = set()
        lines = 0
        errors = re.finditer(rb'^[ \t]{0,32}error(?:\[(E[0-9]{4})\])?:', raw, re.MULTILINE)
        for error in errors:
            lines += 1
            if error[1] is not None:
                codes.add(error[1].decode('ascii'))
            if len(codes) > MAX_ERROR_CODES or lines > MAX_ERROR_LINES:
                result['status'] = 'clipped'
                return result
        missing_library = re.search(
            rb'^[ \t]{0,32}The system library `[^`\r\n]{1,128}` required by crate `[^`\r\n]{1,128}` was not found\.[ \t]*$',
            raw, re.MULTILINE)
        missing_package = re.search(
            rb'^[ \t]{0,32}Package [^\r\n]{1,128} was not found in the pkg-config search path\.[ \t]*$',
            raw, re.MULTILINE)
        linker = re.search(
            rb'^[ \t]{0,32}error: linking with `[^`\r\n]{1,256}` failed: exit status: [0-9]{1,3}[ \t]*$',
            raw, re.MULTILINE)
        result.update(status='captured', rust_error_codes=sorted(codes), error_lines=lines,
                      pkg_config_missing=missing_library is not None or missing_package is not None,
                      linker_failed=linker is not None, compiler_error=lines > 0)
    except BaseException:
        # This observer cannot replace the original compiler/cancellation failure.
        pass
    return result


def admit(source):
    prepare = load('native_build_prepare', HERE / 'prepare.py')
    prepare.hosted_guard(source)
    value = prepare.parse_manifest(prepare.read(HERE / 'manifest.json', prepare.MAX_MANIFEST))
    base = prepare.baseline_manifest()
    prepare.patch_bytes(value)
    prepare.check_source(source, value, base, patched=True)
    return prepare, value, base


def reviewed_metadata(source, temporary, env, deadline, lifecycle, prepare, value, base):
    reviewed = load('native_build_reviewed', HERE / 'verify_reviewed_lock.py')
    original = SUPPORT.read(source / 'Cargo.lock')
    reviewed.check_candidate(original)
    groups = []
    report = dict(schema=1, operation='native_build_reviewed_metadata', owner_scope='metadata_process_group',
        status='failed', stage='locked_metadata', source_commit=SUPPORT.UPSTREAM,
        base_lock_sha256=SUPPORT.BASE_LOCK, root_lock_sha256=NATIVE_LOCK, package_records=563,
        only_desktop_dependency_delta=False, reviewed_transitive_feature_reductions=True,
        offline_locked_metadata_passed=False, source_unchanged=False, owned_group_count=0,
        owned_groups_joined=False, native_build=False, native_runtime_acceptance=False,
        sdk_installed_by_this_check=False, full_studio_acceptance=False, volparossa_updates_verified=False)
    primary = None
    try:
        path = temporary / 'silex-native-reviewed-lock.json'
        require(not path.exists() and not path.is_symlink(), 'artifact_failed')
        raw = actor([str(temporary / 'volparossa-rust-1.99.1/bin/cargo'), 'metadata', '--offline', '--locked',
                     '--format-version=1'], env, source, deadline, groups, lifecycle, capture=8 * 1024 * 1024,
                    seconds=120)
        SUPPORT.metadata(raw, source)
        require(SUPPORT.read(source / 'Cargo.lock') == original)
        prepare.check_source(source, value, base, patched=True)
        report.update(status='passed', stage='complete', offline_locked_metadata_passed=True, source_unchanged=True)
    except BaseException as error:
        primary = error
    finally:
        report.update(owned_group_count=len(groups), owned_groups_joined=len(groups) == 1 and all(groups))
        if not report['owned_groups_joined']:
            report['status'] = 'failed'
            primary = primary or Rejected('cleanup_failed')
        try:
            SUPPORT.write_new(temporary / 'silex-native-reviewed-lock.json',
                              (json.dumps(report, sort_keys=True) + '\n').encode())
        except BaseException as error:
            primary = primary or error
    if primary is not None:
        raise primary
    return report


def main():
    started = time.monotonic()
    deadline = started + 1800
    groups = []
    report = dict(schema=1, operation='private_native_release_build', status='failed', stage='admission',
        failure_kind='admission', source_commit=SUPPORT.UPSTREAM, studio_revision=os.environ.get('GITHUB_SHA'),
        sdk_gate_verified=False, sdk_manifest_sha256=SDK_MANIFEST, compiler_payload_verified=False,
        authenticated_node=False, metadata_check=None, dashboard_manifest_sha256=DASHBOARD_MANIFEST,
        dashboard_commit=DASHBOARD_COMMIT, dashboard_assets_verified=False, dashboard_asset_count=0,
        dashboard_bytes=0, frontend_dependencies_installed=False, frontend_built=False,
        frontend_assets=0, frontend_bytes=0,
        frontend_inventory_sha256=None, native_build=False, binary=None, compiler_diagnostic=None,
        immutable_source_inputs_preserved=False, generated_schema_changes=[], whole_source_tree_unchanged=False,
        root_lock_sha256=NATIVE_LOCK, pnpm_lock_sha256=PNPM_LOCK, owned_group_count=0, owned_groups_joined=False,
        application_executed=False, native_runtime_acceptance=False, native_gui_verified=False,
        full_application_privacy=False, full_studio_acceptance=False, volparossa_updates_verified=False,
        dashboard_license_verified=False, redistribution_acceptance=False, publication_authorized=False,
        system_packages_installed_by_this_helper=False, locked_dependency_acceptance=False, private_compile_only=True)
    artifact = work = None
    primary = None
    try:
        temporary = Path(os.environ.get('RUNNER_TEMP', ''))
        require(sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1
                and sys.argv == [str(HERE / 'native_build.py')], 'admission')
        source = Path(os.environ.get('GITHUB_WORKSPACE', '')) / 'silex'
        prepare, value, base = admit(source)
        revision = os.environ['GITHUB_SHA']
        require(os.environ.get('GITHUB_WORKFLOW_SHA') == revision
                and os.environ.get('GITHUB_REPOSITORY') == 'VOLPAROSSA/volparossa-studio', 'admission')
        artifact = temporary / 'silex-native-build.json'
        require(not artifact.exists() and not artifact.is_symlink(), 'artifact_failed')
        report['stage'] = 'sdk_gate'
        installer = load('native_build_sdk', HERE / 'install_sdk.py')
        require(installer.MANIFEST == SDK_MANIFEST, 'sdk_rejected')
        records = installer.records_from_manifest(read_file(HERE / 'ubuntu-sdk.json', 1024 * 1024))
        outer = SUPPORT.json_value(read_file(temporary / 'silex-native-sdk-install.json', 65536, modes=(0o600,)))
        root = SUPPORT.json_value(read_file(temporary / 'silex-native-sdk-install-root.json', 65536, modes=(0o600,)))
        sdk_receipts(outer, root, revision, records, installer)
        lifecycle = load('lifecycle', EXPORT / 'lifecycle.py')
        env = SUPPORT.environment(source, temporary)
        report['stage'] = 'verify_installed_versions'
        query = ['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\t${Status}\n', '--', *records]
        installer.dpkg_rows(actor(query, env, ROOT, deadline, groups, lifecycle), records, complete=True)
        report['sdk_gate_verified'] = True
        report['stage'] = 'verify_compiler'
        module, prefix = compiler(temporary)
        report['compiler_payload_verified'] = True
        report['stage'] = 'reviewed_locked_metadata'
        report['metadata_check'] = reviewed_metadata(source, temporary, env, deadline, lifecycle, prepare, value, base)
        report['stage'] = 'verify_source_inputs'
        rows = dashboard_manifest(read_file(HERE / 'dashboard-source.json', 65536))
        before = tracked(source, (), env, deadline, groups, lifecycle)
        changed = set(value['files']) | set(base['files'])
        extras = sorted(changed - before.keys())
        before = tracked(source, extras, env, deadline, groups, lifecycle)
        require(hashlib.sha256(read_file(source / 'pnpm-lock.yaml', 1024 * 1024)).hexdigest() == PNPM_LOCK)
        report['stage'] = 'prepare_build_workspace'
        work = temporary / 'silex-native-build-private'
        work.mkdir(mode=0o700)
        for name in ('home', 'logs', 'store'):
            (work / name).mkdir(mode=0o700)
        target = temporary / 'silex-native-build-target'
        target.mkdir(mode=0o700)
        env.update(HOME=str(work / 'home'), TMPDIR=str(work), CARGO_TARGET_DIR=str(target), CARGO_BUILD_JOBS='2',
                   CI='true', HUSKY='0', DO_NOT_TRACK='1', NPM_CONFIG_USERCONFIG='/dev/null',
                   NPM_CONFIG_GLOBALCONFIG='/dev/null', NPM_CONFIG_REGISTRY='https://registry.npmjs.org/',
                   NPM_CONFIG_UPDATE_NOTIFIER='false', PNPM_DISABLE_SELF_UPDATE_CHECK='1', COREPACK_ENABLE_NETWORK='0')
        report['stage'] = 'dashboard_source'
        acquire_dashboard(source, work, rows, env, deadline, groups, lifecycle)
        dashboard_unchanged(source, rows)
        report.update(dashboard_assets_verified=True, dashboard_asset_count=9, dashboard_bytes=79203)
        report['stage'] = 'authenticate_node'
        node, pnpm, pins = export_carrier(work)
        report['authenticated_node'] = True
        env['PATH'] = str(node.parent) + ':' + str(prefix / 'bin') + ':/usr/bin:/bin'
        report['stage'] = 'frozen_frontend_install'
        actor([node, pnpm, '--dir', source, '--filter', '@silexlabs/silex', 'install', '--frozen-lockfile',
               '--ignore-scripts', '--store-dir', work / 'store', '--config.manage-package-manager-versions=false',
               '--config.update-notifier=false'], env, source, deadline, groups, lifecycle,
              log=work / 'logs/frontend-install.log', seconds=600)
        source_check(source, before, extras, rows, env, deadline, groups, lifecycle)
        report['frontend_dependencies_installed'] = True
        for name in ('client', 'public'):
            report['stage'] = 'build_' + name
            actor([node, pnpm, '--dir', source, 'run', 'build:' + name], env, source,
                  deadline, groups, lifecycle, log=work / ('logs/build-' + name + '.log'), seconds=600)
        report['stage'] = 'verify_frontend_inputs'
        frontend = frontend_inventory(source / 'dist/client')
        report.update(frontend_built=True, frontend_assets=len(frontend),
                      frontend_bytes=sum(row['bytes'] for row in frontend),
                      frontend_inventory_sha256=hashlib.sha256(json.dumps(frontend, sort_keys=True).encode()).hexdigest())
        source_check(source, before, extras, rows, env, deadline, groups, lifecycle)
        require(file_hash(node, pins['node']['files']['bin/node']['bytes'], executable=True)['sha256']
                == pins['node']['files']['bin/node']['sha256'], 'carrier_rejected')
        report['stage'] = 'verify_compiler_before_native'
        module.verify_payload(prefix, module.pins())
        report['stage'] = 'native_release_compile'
        actor(release_command(temporary), env, source, deadline, groups, lifecycle,
              log=work / 'logs/native-cargo.log', seconds=1500)
        report['stage'] = 'verify_source_after_native'
        report['generated_schema_changes'] = source_check(source, before, extras, rows, env, deadline, groups, lifecycle)
        require(frontend_inventory(source / 'dist/client') == frontend)
        report['stage'] = 'verify_compiler_after_native'
        module.verify_payload(prefix, module.pins())
        report['stage'] = 'inspect_native_elf'
        report['binary'] = inspect_elf(target / 'release/silex-desktop')
        require(all(groups), 'cleanup_failed')
        report.update(status='passed', stage='complete', failure_kind=None, native_build=True,
                      immutable_source_inputs_preserved=True)
    except BaseException as error:
        primary = error
        report['failure_kind'] = error.kind if isinstance(error, Rejected) else 'source_rejected'
        if report['stage'] == 'native_release_compile' and work is not None:
            # The phase's child is already drained/closed by actor(). Never
            # inspect project files or allow diagnostic failure to mask it.
            try:
                report['compiler_diagnostic'] = compiler_diagnostic(
                    work, clipped=isinstance(error, Rejected) and error.kind == 'output_limit')
            except BaseException:
                pass
    finally:
        report.update(owned_group_count=len(groups), owned_groups_joined=bool(groups) and all(groups))
        if report['status'] == 'passed' and work is not None:
            try:
                shutil.rmtree(work / 'logs')  # Only our joined, successful phase logs; never an artifact.
            except BaseException as error:
                primary = primary or error
                report.update(status='failed', failure_kind='cleanup_failed')
        raw = (json.dumps(report, sort_keys=True) + '\n').encode()
        if artifact is not None:
            try:
                SUPPORT.write_new(artifact, raw)
            except BaseException as error:
                primary = primary or error
                report.update(status='failed', failure_kind='artifact_failed')
                raw = (json.dumps(report, sort_keys=True) + '\n').encode()
        print(raw.decode().rstrip())
    if primary is not None:
        raise primary


if __name__ == '__main__':
    def cancelled(number, _frame):
        raise Rejected('deadline' if number == signal.SIGALRM else 'cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(number, cancelled)
    signal.setitimer(signal.ITIMER_REAL, 1790)
    try:
        main()
    except BaseException:
        raise SystemExit(1) from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
