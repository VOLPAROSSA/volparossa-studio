#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Resolve only the reviewed desktop dependency removals, offline on a hosted runner.

The original publication-bounds lock is retained. This produces a review candidate,
never dependency, SDK, native runtime, publication or update acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UPSTREAM = '672efed69dda04c0a1e968859239e042f00d9538'
BASE_LOCK = '35d0ea429b62f5cd2bc8533f75f997c05e787ad3355a40c1de0eba5fd3233536'
REGISTRY = 'registry+https://github.com/rust-lang/crates.io-index'
REMOVED = frozenset({'dirs', 'sentry', 'tauri-plugin-process', 'tauri-plugin-updater', 'uuid'})
WORKSPACE = frozenset({'silex-server', 'silex-desktop'})
MAX_BYTES = 2 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
KINDS = frozenset({'admission', 'source_rejected', 'ledger_rejected', 'metadata_rejected',
                   'command_failed', 'output_limit', 'deadline', 'cancelled', 'cleanup_unconfirmed',
                   'artifact_failed'})


class Rejected(ValueError):
    def __init__(self, kind):
        if kind not in KINDS:
            raise ValueError('closed lock resolution failure required')
        self.kind = kind
        super().__init__('native lock resolution rejected')


def require(condition, kind='admission'):
    if not condition:
        raise Rejected(kind)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def directory(path, *, private=False):
    require(path.is_absolute() and path.resolve(strict=True) == path)
    value = path.stat()
    require(stat.S_ISDIR(value.st_mode) and value.st_uid == os.geteuid()
            and (stat.S_IMODE(value.st_mode) == 0o700 if private else not value.st_mode & 0o022))


def read(path):
    require(path.is_absolute() and path.resolve(strict=True) == path, 'source_rejected')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == 0o644 and 0 < before.st_size <= MAX_BYTES,
                'source_rejected')
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_nlink', 'st_size',
                  'st_mtime_ns', 'st_ctime_ns')
        require(len(raw) == before.st_size and len(raw) <= MAX_BYTES
                and all(getattr(before, field) == getattr(after, field) for field in fields),
                'source_rejected')
    return raw


def pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, 'metadata_rejected')
        value[key] = item
    return value


def json_value(raw):
    def invalid(_value):
        raise Rejected('metadata_rejected')
    try:
        return json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=pairs,
                          parse_constant=invalid)
    except (ValueError, UnicodeError):
        raise Rejected('metadata_rejected') from None


def ledger(raw):
    require(0 < len(raw) <= MAX_BYTES, 'ledger_rejected')
    try:
        value = tomllib.loads(raw.decode('utf-8', errors='strict'))
    except (ValueError, UnicodeError):
        raise Rejected('ledger_rejected') from None
    require(value.keys() == {'version', 'package'} and type(value['version']) is int
            and value['version'] == 4 and type(value['package']) is list
            and 2 <= len(value['package']) <= 1024, 'ledger_rejected')
    records = {}
    workspace = set()
    for package in value['package']:
        require(type(package) is dict and {'name', 'version'} <= package.keys()
                and package.keys() <= {'name', 'version', 'source', 'checksum', 'dependencies'},
                'ledger_rejected')
        require(type(package['name']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', package['name'])
                and type(package['version']) is str
                and re.fullmatch(r'[0-9][0-9A-Za-z.+-]{0,127}', package['version']), 'ledger_rejected')
        if 'source' in package:
            require(package['source'] == REGISTRY and type(package.get('checksum')) is str
                    and re.fullmatch(r'[0-9a-f]{64}', package['checksum']), 'ledger_rejected')
        else:
            require(package['name'] in WORKSPACE and 'checksum' not in package, 'ledger_rejected')
            workspace.add(package['name'])
        dependencies = package.get('dependencies', [])
        require(type(dependencies) is list and len(dependencies) <= 1024
                and all(type(item) is str and 0 < len(item) <= 512 for item in dependencies)
                and len(set(dependencies)) == len(dependencies), 'ledger_rejected')
        key = (package['name'], package['version'], package.get('source'))
        require(key not in records, 'ledger_rejected')
        records[key] = package
    require(workspace == WORKSPACE and sum(key[2] is None for key in records) == 2, 'ledger_rejected')
    return value['version'], records


def compare_ledgers(before, after):
    old_version, old = ledger(before)
    new_version, new = ledger(after)
    require(old_version == new_version and new.keys() <= old.keys(), 'ledger_rejected')
    desktop = [key for key in old if key[0] == 'silex-desktop' and key[2] is None]
    require(len(desktop) == 1 and desktop[0] in new, 'ledger_rejected')
    desktop = desktop[0]
    old_dependencies = old[desktop].get('dependencies', [])
    require(REMOVED <= set(old_dependencies), 'ledger_rejected')
    expected = dict(old[desktop], dependencies=[item for item in old_dependencies if item not in REMOVED])
    require(new[desktop] == expected, 'ledger_rejected')
    for key, package in new.items():
        if key != desktop:
            require(package == old[key], 'ledger_rejected')
    removed = sorted(old.keys() - new.keys())
    require(all(key[2] == REGISTRY for key in removed), 'ledger_rejected')
    return {'old_package_records': len(old), 'new_package_records': len(new),
            'removed_package_records': [{'name': name, 'version': version, 'source': 'crates_io'}
                                        for name, version, _source in removed],
            'desktop_removed_dependencies': sorted(REMOVED),
            'only_desktop_dependency_delta': True, 'retained_pins_unchanged': True}


def environment(source, temporary, *, fetch=False):
    prefix = temporary / 'volparossa-rust-1.99.1'
    home = temporary / 'silex-native-cargo-public-v1'
    directory(prefix, private=True)
    directory(home, private=True)
    for path in (home, source, *source.parents):
        base = path if path == home else path / '.cargo'
        for name in ('config', 'config.toml', 'credentials', 'credentials.toml'):
            candidate = base / name
            require(not candidate.exists() and not candidate.is_symlink())
    if fetch:
        require(not any(home.iterdir()))
    for name in ('cargo', 'rustc', 'rustdoc'):
        path = prefix / 'bin' / name
        require(path.resolve(strict=True) == path)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1
                    and info.st_mode & 0o111 and not info.st_mode & 0o022
                    and 4 <= info.st_size <= 256 * 1024 * 1024 and stream.read(4) == b'\x7fELF')
    return {'PATH': f'{prefix}/bin:/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'HOME': str(home),
            'TMPDIR': str(temporary),
            'CARGO_HOME': str(home), 'CARGO_TARGET_DIR': str(temporary / 'silex-native-metadata-target'),
            'CARGO_REGISTRIES_CRATES_IO_PROTOCOL': 'sparse',
            'CARGO_REGISTRIES_CRATES_IO_INDEX': 'sparse+https://index.crates.io/',
            'CARGO_NET_OFFLINE': 'false' if fetch else 'true',
            'CARGO_TERM_COLOR': 'never', 'RUSTC': str(prefix / 'bin/rustc'),
            'RUSTDOC': str(prefix / 'bin/rustdoc'), 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_SYSTEM': '/dev/null', 'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_ALLOW_PROTOCOL': 'https', 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/usr/bin/false',
            'GIT_NO_LAZY_FETCH': '1', 'GIT_OPTIONAL_LOCKS': '0'}


def run(argv, env, cwd, deadline, counts, *, stdout_limit=MAX_BYTES, seconds=60):
    require(time.monotonic() < deadline, 'deadline')
    child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                             umask=0o022)
    counts['started'] += 1
    primary = None
    output = bytearray()
    errors = 0
    joined = False
    end = min(deadline, time.monotonic() + seconds)
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (child.stdout, child.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                require(time.monotonic() < end, 'deadline')
                for key, _events in selector.select(min(0.25, max(0, end - time.monotonic()))):
                    stream = key.fileobj
                    chunk = os.read(stream.fileno(), 65536)
                    if not chunk:
                        selector.unregister(stream)
                    elif stream is child.stdout:
                        require(len(output) + len(chunk) <= stdout_limit, 'output_limit')
                        output.extend(chunk)
                    else:
                        errors += len(chunk)
                        require(errors <= 65536, 'output_limit')
        remaining = end - time.monotonic()
        require(remaining > 0, 'deadline')
        code = child.wait(timeout=remaining)
        joined = True
        require(code == 0, 'command_failed')
    except BaseException as error:
        primary = error
    finally:
        numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        previous = {number: signal.getsignal(number) for number in numbers}
        try:
            for number in numbers:
                signal.signal(number, signal.SIG_IGN)
            if child.returncode is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=2)
                    joined = True
                except BaseException:
                    joined = False
            for stream in (child.stdout, child.stderr):
                stream.close()
        except BaseException:
            joined = False
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
        if joined:
            counts['joined'] += 1
        elif primary is None:
            primary = Rejected('cleanup_unconfirmed')
    if primary is not None:
        raise primary
    return bytes(output)


def git(source, env, deadline, counts, *args):
    return run(['/usr/bin/git', '--no-pager', '--literal-pathspecs', '-c', 'core.fsmonitor=false',
                '-c', 'core.hooksPath=/dev/null', '-C', str(source), *args], env, source, deadline, counts)


def snapshot(source, env, deadline, counts, *, expected_count=16):
    require(git(source, env, deadline, counts, 'rev-parse', 'HEAD').strip().decode() == UPSTREAM,
            'source_rejected')
    names = git(source, env, deadline, counts, 'diff', '--no-ext-diff', '--no-textconv',
                '--name-only', '-z', 'HEAD', '--')
    names += git(source, env, deadline, counts, 'ls-files', '--others', '-z')
    changed = frozenset(name.decode('utf-8', errors='strict') for name in names.split(b'\0') if name)
    require('Cargo.lock' in changed and len(changed) == expected_count, 'source_rejected')
    fixed = changed - {'Cargo.lock'}
    hashes = {name: digest(read(source / name)) for name in fixed}
    for name in ('server-rust/Cargo.lock', 'desktop/src-tauri/Cargo.lock'):
        hashes[name] = digest(read(source / name))
    return changed, hashes


def write_new(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        require(stream.write(raw) == len(raw), 'artifact_failed')
        stream.flush()


def metadata(raw, source):
    require(len(raw) <= MAX_METADATA_BYTES, 'metadata_rejected')
    value = json_value(raw)
    require(type(value) is dict and type(value.get('version')) is int and value.get('version') == 1
            and value.get('workspace_root') == str(source), 'metadata_rejected')
    resolve = value.get('resolve')
    require(type(resolve) is dict and type(resolve.get('nodes')) is list
            and 0 < len(resolve['nodes']) <= 1024
            and all(type(node) is dict and type(node.get('id')) is str
                    and type(node.get('dependencies')) is list for node in resolve['nodes']),
            'metadata_rejected')


def verify_source(source, temporary, deadline, counts, *, patched):
    directory(temporary)
    bootstrap = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
                 **{name: os.environ.get(name, '') for name in (
                     'GITHUB_ACTIONS', 'RUNNER_ENVIRONMENT', 'RUNNER_OS', 'RUNNER_ARCH',
                     'GITHUB_WORKSPACE', 'GITHUB_SHA', 'RUNNER_TEMP')}}
    operation = 'verify-patched' if patched else 'verify-baseline'
    proof = json_value(run(['/usr/bin/python3', '-I', '-B', str(HERE / 'prepare.py'),
                            operation, '--source', str(source)], bootstrap, ROOT, deadline, counts))
    require(type(proof) is dict and proof.get('operation') == operation and proof.get('compiled') is False
            and proof.get('native_runtime_proven') is False, 'source_rejected')


def fetch_base(source):
    """The sole online operation: fixed public locked fetch before the native overlay."""
    counts = {'started': 0, 'joined': 0}
    report = {'schema': 1, 'operation': 'native_base_fetch', 'status': 'failed', 'stage': 'admission',
              'failure_kind': 'admission', 'source_commit': UPSTREAM, 'root_lock_sha256': None,
              'package_records': None, 'public_registry_only': False, 'cargo_home_initially_empty': False,
              'fetched_locked': False, 'source_unchanged': False,
              'owned_children_started': 0, 'owned_children_joined': 0, 'owned_child_cleanup_confirmed': False,
              'native_build': False, 'native_runtime_privacy': False, 'native_gui_executed': False,
              'locked_dependency_acceptance': False, 'independently_authorized_volparossa_updates': False,
              'full_studio': False}
    artifact = None
    primary = None
    deadline = time.monotonic() + 178
    try:
        temporary = Path(os.environ.get('RUNNER_TEMP', ''))
        verify_source(source, temporary, deadline, counts, patched=False)
        old = read(source / 'Cargo.lock')
        require(digest(old) == BASE_LOCK, 'source_rejected')
        require(len(ledger(old)[1]) == 607, 'ledger_rejected')
        artifact = temporary / 'silex-native-base-fetch.json'
        require(not artifact.exists() and not artifact.is_symlink(), 'artifact_failed')
        report.update(root_lock_sha256=digest(old), package_records=607, public_registry_only=True)
        report['stage'] = 'environment'
        env = environment(source, temporary, fetch=True)
        report['cargo_home_initially_empty'] = True
        before = snapshot(source, env, deadline, counts, expected_count=11)
        cargo = str(temporary / 'volparossa-rust-1.99.1/bin/cargo')
        report['stage'] = 'fetch'
        run([cargo, 'fetch', '--locked'], env, source, deadline, counts, seconds=150)
        require(read(source / 'Cargo.lock') == old
                and snapshot(source, env, deadline, counts, expected_count=11) == before,
                'source_rejected')
        verify_source(source, temporary, deadline, counts, patched=False)
        report.update(status='passed', stage='complete', failure_kind=None,
                      fetched_locked=True, source_unchanged=True)
    except BaseException as error:
        primary = error
        report['failure_kind'] = (error.kind if isinstance(error, Rejected) else
                                  'deadline' if isinstance(error, subprocess.TimeoutExpired) else
                                  'cancelled' if isinstance(error, KeyboardInterrupt) else 'source_rejected')
    finally:
        report.update(owned_children_started=counts['started'], owned_children_joined=counts['joined'],
                      owned_child_cleanup_confirmed=counts['started'] == counts['joined'])
        if counts['started'] != counts['joined']:
            report['status'] = 'failed'
            if primary is None:
                primary = Rejected('cleanup_unconfirmed')
                report['failure_kind'] = 'cleanup_unconfirmed'
        raw = (json.dumps(report, sort_keys=True) + '\n').encode()
        if artifact is not None:
            try:
                write_new(artifact, raw)
            except BaseException:
                primary = primary or Rejected('artifact_failed')
                report.update(status='failed', failure_kind=report['failure_kind'] or 'artifact_failed')
                raw = (json.dumps(report, sort_keys=True) + '\n').encode()
        print(raw.decode().rstrip())
    if primary is not None:
        raise primary


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Rejected('admission')


def main():
    parser = Parser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--fetch-base', action='store_true',
                        help='Fetch only the original locked public graph before the native overlay.')
    args = parser.parse_args()
    if args.fetch_base:
        return fetch_base(args.source)
    counts = {'started': 0, 'joined': 0}
    report = {'schema': 1, 'status': 'failed', 'stage': 'admission', 'failure_kind': 'admission',
              'old_lock_sha256': None, 'new_lock_sha256': None, 'old_package_records': None,
              'new_package_records': None, 'removed_package_records': [], 'desktop_removed_dependencies': [],
              'only_desktop_dependency_delta': False, 'retained_pins_unchanged': False,
              'source_changes_only_root_lock': False, 'offline_metadata_passed': False,
              'offline_locked_metadata_passed': False, 'original_lock_preserved': False,
              'result_lock_preserved': False, 'owned_children_started': 0, 'owned_children_joined': 0,
              'owned_child_cleanup_confirmed': False, 'native_build': False,
              'native_runtime_privacy': False, 'native_gui_executed': False,
              'locked_dependency_acceptance': False, 'independently_authorized_volparossa_updates': False,
              'full_studio': False}
    artifact = None
    primary = None
    deadline = time.monotonic() + 178
    try:
        temporary = Path(os.environ.get('RUNNER_TEMP', ''))
        verify_source(args.source, temporary, deadline, counts, patched=True)
        old = read(args.source / 'Cargo.lock')
        require(digest(old) == BASE_LOCK, 'source_rejected')
        require(len(ledger(old)[1]) == 607, 'ledger_rejected')
        env = environment(args.source, temporary)
        before_source = snapshot(args.source, env, deadline, counts)
        artifact = temporary / 'silex-native-lock'
        artifact.mkdir(mode=0o700)
        directory(artifact, private=True)
        write_new(artifact / 'BEFORE.Cargo.lock', old)
        report.update(old_lock_sha256=digest(old), original_lock_preserved=True, old_package_records=607)
        cargo = str(temporary / 'volparossa-rust-1.99.1/bin/cargo')
        report['stage'] = 'metadata'
        metadata(run([cargo, 'metadata', '--offline', '--format-version=1'], env,
                     args.source, deadline, counts, stdout_limit=MAX_METADATA_BYTES), args.source)
        report['offline_metadata_passed'] = True
        after = read(args.source / 'Cargo.lock')
        report['new_package_records'] = len(ledger(after)[1])
        report.update(compare_ledgers(old, after))
        require(snapshot(args.source, env, deadline, counts) == before_source, 'source_rejected')
        report['source_changes_only_root_lock'] = True
        report['stage'] = 'locked_metadata'
        metadata(run([cargo, 'metadata', '--offline', '--locked', '--format-version=1'], env,
                     args.source, deadline, counts, stdout_limit=MAX_METADATA_BYTES), args.source)
        require(read(args.source / 'Cargo.lock') == after
                and snapshot(args.source, env, deadline, counts) == before_source, 'source_rejected')
        report['offline_locked_metadata_passed'] = True
        report.update(status='passed', stage='complete', failure_kind=None)
    except BaseException as error:
        primary = error
        report['failure_kind'] = (error.kind if isinstance(error, Rejected) else
                                  'deadline' if isinstance(error, subprocess.TimeoutExpired) else
                                  'cancelled' if isinstance(error, KeyboardInterrupt) else 'source_rejected')
    finally:
        if artifact is not None and report['original_lock_preserved']:
            try:
                result = read(args.source / 'Cargo.lock')
                write_new(artifact / 'RESULT.Cargo.lock', result)
                report.update(new_lock_sha256=digest(result), result_lock_preserved=True)
            except BaseException as error:
                if primary is None:
                    primary = error
                    report.update(status='failed', failure_kind='artifact_failed')
        report.update(owned_children_started=counts['started'], owned_children_joined=counts['joined'],
                      owned_child_cleanup_confirmed=counts['started'] == counts['joined'])
        if counts['started'] != counts['joined']:
            report['status'] = 'failed'
            if primary is None:
                primary = Rejected('cleanup_unconfirmed')
                report['failure_kind'] = 'cleanup_unconfirmed'
        raw = (json.dumps(report, sort_keys=True) + '\n').encode()
        if artifact is not None and report['original_lock_preserved']:
            try:
                write_new(artifact / 'receipt.json', raw)
            except BaseException:
                primary = primary or Rejected('artifact_failed')
                report.update(status='failed', failure_kind=report['failure_kind'] or 'artifact_failed')
                raw = (json.dumps(report, sort_keys=True) + '\n').encode()
        print(raw.decode().rstrip())
    if primary is not None:
        raise primary


if __name__ == '__main__':
    def cancelled(_number, _frame):
        raise Rejected('cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancelled)
    try:
        main()
    except BaseException:
        raise SystemExit(1) from None
