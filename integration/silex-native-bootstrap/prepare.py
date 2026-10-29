#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Apply one reviewed native bootstrap overlay to the already bounded Silex source.

This source-only tool runs on an approved disposable hosted checkout. It never
builds an SDK, launches the application, grants consent or accepts an update.
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'integration/silex-publication'
UPSTREAM = '672efed69dda04c0a1e968859239e042f00d9538'
BASE_MANIFEST = '9d7ab28754d77e681dae5adc7c19046be9f15798b05eb6f518ca2ee480ea5790'
BASE_PATCH = '30901a10f6b2d09967f553820ea642f83e087fa66a55533b1b683da26306926a'
BASE_LOCK = '35d0ea429b62f5cd2bc8533f75f997c05e787ad3355a40c1de0eba5fd3233536'
NATIVE = frozenset({
    'desktop/src-tauri/Cargo.toml', 'desktop/src-tauri/src/main.rs',
    'desktop/src-tauri/src/mcp.rs', 'desktop/src-tauri/scripts/desktop-bridge.js',
    'desktop/src-tauri/tauri.conf.json',
})
BASE_FILES = frozenset({
    'Cargo.lock', 'server-rust/Cargo.toml', 'server-rust/src/connectors/mod.rs',
    'server-rust/src/connectors/traits.rs', 'server-rust/src/connectors/fs_storage.rs',
    'server-rust/src/connectors/fs_storage/bounded_asset.rs',
    'server-rust/src/connectors/fs_storage/bounded_asset/tests.rs',
    'server-rust/src/routes/publication.rs',
    'server-rust/src/routes/publication/preparation.rs',
    'server-rust/src/routes/publication/preparation/tests.rs',
    'server-rust/src/routes/publication/tests.rs',
})
ACCEPTANCE = frozenset({
    'full_studio', 'general_editor_plugin_privacy', 'independently_authorized_volparossa_updates',
    'locked_dependency_acceptance', 'native_build', 'native_runtime_privacy',
})
MAX_FILE = 2 * 1024 * 1024
MAX_PATCH = 1024 * 1024
MAX_MANIFEST = 65536
SHA = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')
PATCH_PATH = 'patches/native-bootstrap-privacy.patch'


class Rejected(ValueError):
    pass


def require(condition):
    if not condition:
        raise Rejected('native bootstrap source preparation rejected')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(values):
    result = {}
    for key, value in values:
        require(key not in result)
        result[key] = value
    return result


def read(path, maximum):
    require(path.is_absolute() and path.resolve(strict=True) == path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
                and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o644
                and before.st_size <= maximum)
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino, before.st_uid, before.st_mode, before.st_nlink,
                 before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_uid, after.st_mode, after.st_nlink,
                 len(raw), after.st_mtime_ns, after.st_ctime_ns))
        require(len(raw) <= maximum)
    return raw


def record(value):
    require(type(value) is dict and value.keys() == {'bytes', 'mode', 'sha256'})
    require(type(value['bytes']) is int and 0 < value['bytes'] <= MAX_FILE
            and value['mode'] == '100644' and type(value['sha256']) is str
            and SHA.fullmatch(value['sha256']))


def parse_manifest(raw):
    require(len(raw) <= MAX_MANIFEST)
    value = json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=pairs)
    require(type(value) is dict and value.keys() == {
        'schema', 'upstream_commit', 'base_publication_manifest_sha256',
        'base_publication_patch_sha256', 'base_patched_root_lock_sha256', 'patch', 'files', 'acceptance',
    })
    require(type(value['schema']) is int and value['schema'] == 1
            and value['upstream_commit'] == UPSTREAM
            and value['base_publication_manifest_sha256'] == BASE_MANIFEST
            and value['base_publication_patch_sha256'] == BASE_PATCH
            and value['base_patched_root_lock_sha256'] == BASE_LOCK)
    require(type(value['acceptance']) is dict and value['acceptance'].keys() == ACCEPTANCE
            and all(flag is False for flag in value['acceptance'].values()))
    require(type(value['files']) is dict and value['files'].keys() in (NATIVE, NATIVE | {'Cargo.lock'}))
    for entry in value['files'].values():
        require(type(entry) is dict and entry.keys() == {'before', 'after'})
        record(entry['before'])
        record(entry['after'])
        require(entry['before'] != entry['after'])
    if 'Cargo.lock' in value['files']:
        require(value['files']['Cargo.lock']['before']['sha256'] == BASE_LOCK)
    patch = value['patch']
    require(type(patch) is dict and patch.keys() == {'path', 'bytes', 'sha256'}
            and patch['path'] == PATCH_PATH and type(patch['bytes']) is int
            and 0 < patch['bytes'] <= MAX_PATCH and type(patch['sha256']) is str
            and SHA.fullmatch(patch['sha256']))
    return value


def patch_bytes(value):
    raw = read(HERE / PATCH_PATH, MAX_PATCH)
    require(len(raw) == value['patch']['bytes'] and digest(raw) == value['patch']['sha256'])
    check_patch(raw, value['files'].keys())
    return raw


def check_patch(raw, files):
    """Accept only ordinary textual modifications of exactly the selected fixed files."""
    require(0 < len(raw) <= MAX_PATCH and b'\0' not in raw and b'\r' not in raw)
    lines = raw.decode('utf-8', errors='strict').splitlines(keepends=True)
    require(all(line.endswith('\n') for line in lines))
    seen = []
    cursor = 0
    while cursor < len(lines):
        header = re.fullmatch(r'diff --git a/(\S+) b/(\S+)\n', lines[cursor])
        require(header is not None and header[1] == header[2] and header[1] in files
                and header[1] not in seen)
        name = header[1]
        seen.append(name)
        cursor += 1
        require(cursor < len(lines))
        if lines[cursor].startswith('index '):
            require(re.fullmatch(r'index [0-9a-f]{7,40}\.\.[0-9a-f]{7,40} 100644\n', lines[cursor]))
            cursor += 1
        require(cursor + 2 < len(lines) and lines[cursor] == f'--- a/{name}\n'
                and lines[cursor + 1] == f'+++ b/{name}\n')
        cursor += 2
        hunks = 0
        while cursor < len(lines) and not lines[cursor].startswith('diff --git '):
            hunk = re.fullmatch(r'@@ -[0-9]+(?:,([0-9]+))? \+[0-9]+(?:,([0-9]+))? @@[^\n]*\n', lines[cursor])
            require(hunk is not None)
            old = int(hunk[1]) if hunk[1] is not None else 1
            new = int(hunk[2]) if hunk[2] is not None else 1
            cursor += 1
            while old or new:
                require(cursor < len(lines))
                line = lines[cursor]
                require(line[:1] in (' ', '+', '-'))
                old -= line[0] in (' ', '-')
                new -= line[0] in (' ', '+')
                require(old >= 0 and new >= 0)
                cursor += 1
            hunks += 1
        require(hunks > 0)
    require(set(seen) == set(files))


def command(source, *args, payload=None):
    """Run fixed Git only, with bounded pipes and a joined owned Git child."""
    environment = {
        'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
        'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1',
    }
    argv = ['/usr/bin/git', '--no-pager', '--literal-pathspecs', '-c', 'core.fsmonitor=false',
            '-c', 'core.hooksPath=/dev/null', '-C', str(source), *args]
    child = subprocess.Popen(argv, stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
                             start_new_session=True)
    output = bytearray()
    error_bytes = 0
    deadline = time.monotonic() + 20
    primary = None
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (child.stdout, child.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            pending = memoryview(payload) if payload is not None else None
            if pending is not None:
                require(len(pending) <= MAX_PATCH)
                os.set_blocking(child.stdin.fileno(), False)
                selector.register(child.stdin, selectors.EVENT_WRITE)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0)
                for key, _ in selector.select(min(remaining, 0.25)):
                    stream = key.fileobj
                    if stream is child.stdin:
                        if pending:
                            pending = pending[os.write(stream.fileno(), pending[:65536]):]
                        if not pending:
                            selector.unregister(stream)
                            stream.close()
                    else:
                        chunk = os.read(stream.fileno(), 65536)
                        if not chunk:
                            selector.unregister(stream)
                            continue
                        if stream is child.stdout:
                            require(len(output) + len(chunk) <= MAX_FILE)
                            output.extend(chunk)
                        else:
                            error_bytes += len(chunk)
                            require(error_bytes <= MAX_MANIFEST)
        remaining = deadline - time.monotonic()
        require(remaining > 0 and child.wait(timeout=remaining) == 0)
        return bytes(output)
    except BaseException as error:
        primary = error
        raise
    finally:
        numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        previous = {number: signal.getsignal(number) for number in numbers}
        cleanup_error = None
        try:
            # Repeated cancellation cannot abandon the single bounded cleanup owner.
            for number in numbers:
                signal.signal(number, signal.SIG_IGN)
            try:
                # Retain an unjoined leader's PID until signalling its own group,
                # then join it; do not poll/reap before targeting the group.
                if child.returncode is None:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=2)
            except BaseException as error:
                cleanup_error = error
            finally:
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except BaseException as error:
                            if cleanup_error is None:
                                cleanup_error = error
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
        # Unconfirmed cleanup can never return success. An already failing source
        # operation retains its original failure instead of masking it with cleanup.
        if cleanup_error is not None and primary is None:
            raise cleanup_error


def directory(path):
    require(path.is_absolute() and path.resolve(strict=True) == path)
    metadata = path.stat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.geteuid()
            and not stat.S_IMODE(metadata.st_mode) & 0o022)


def hosted_guard(source):
    require(sys.platform == 'linux' and os.uname().machine == 'x86_64'
            and os.getuid() == os.geteuid() != 0)
    for key, value in {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                       'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64'}.items():
        require(os.environ.get(key) == value)
    workspace = Path(os.environ.get('GITHUB_WORKSPACE', ''))
    temporary = Path(os.environ.get('RUNNER_TEMP', ''))
    for path in (workspace, temporary, ROOT, source):
        directory(path)
    require(ROOT == workspace / 'studio' and source != ROOT and not ROOT.is_relative_to(source)
            and '.git' not in source.parts)
    require(source == workspace / 'silex'
            or (source != temporary and source.is_relative_to(temporary)))
    prefixes = [path for path in (workspace, temporary) if source != path and source.is_relative_to(path)]
    require(prefixes)
    parent = source.parent
    while parent not in prefixes:
        directory(parent)
        parent = parent.parent
    directory(source / '.git')
    expected = os.environ.get('GITHUB_SHA', '')
    require(COMMIT.fullmatch(expected))
    require(command(ROOT, 'rev-parse', '--show-toplevel').decode().strip() == str(ROOT)
            and command(ROOT, 'rev-parse', 'HEAD').decode().strip() == expected
            and not command(ROOT, 'status', '--porcelain=v1', '-z', '--untracked-files=all'))
    require(all(entry.startswith(b'H ') for entry in command(ROOT, 'ls-files', '-v', '-z').split(b'\0')
                if entry))


def baseline_manifest():
    raw = read(BASE / 'manifest.json', MAX_MANIFEST)
    require(digest(raw) == BASE_MANIFEST)
    value = json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=pairs)
    require(value['upstream_commit'] == UPSTREAM and value['files'].keys() == BASE_FILES
            and value['patch']['path'] == 'patches/publication-bounds.patch'
            and value['patch']['sha256'] == BASE_PATCH
            and value['files']['Cargo.lock']['after']['sha256'] == BASE_LOCK)
    raw = read(BASE / 'patches/publication-bounds.patch', MAX_PATCH)
    require(digest(raw) == BASE_PATCH and len(raw) == value['patch']['bytes'])
    return value


def check_file(source, name, expected):
    raw = read(source / name, MAX_FILE)
    require(len(raw) == expected['bytes'] and digest(raw) == expected['sha256'])


def check_source(source, value, base, *, patched):
    directory(source)
    require(command(source, 'rev-parse', '--show-toplevel').decode().strip() == str(source)
            and command(source, 'rev-parse', 'HEAD').decode().strip() == UPSTREAM)
    require(not command(source, 'diff', '--cached', '--name-only', '-z', 'HEAD', '--'))
    tracked = command(source, 'ls-files', '-v', '-z').split(b'\0')
    require(all(entry.startswith(b'H ') for entry in tracked if entry))
    changed = command(source, 'diff', '--no-ext-diff', '--no-textconv', '--name-only', '-z', 'HEAD', '--')
    changed += command(source, 'ls-files', '--others', '-z')
    names = {name.decode('utf-8', errors='strict') for name in changed.split(b'\0') if name}
    require(names == BASE_FILES | NATIVE if patched else names == BASE_FILES)
    for name, entry in base['files'].items():
        if not (patched and name in value['files']):
            check_file(source, name, entry['after'])
    for name, entry in value['files'].items():
        check_file(source, name, entry['after' if patched else 'before'])
        if name in NATIVE:
            original = command(source, 'show', f'HEAD:{name}')
            require(len(original) == entry['before']['bytes'] and digest(original) == entry['before']['sha256'])
    for name in ('server-rust/Cargo.lock', 'desktop/src-tauri/Cargo.lock'):
        require(read(source / name, MAX_FILE) == command(source, 'show', f'HEAD:{name}'))


def apply(source, value, base):
    hosted_guard(source)
    check_source(source, value, base, patched=False)
    patch = patch_bytes(value)
    command(source, 'apply', '--check', '--whitespace=error-all', '-', payload=patch)
    # Recheck the complete fixed source immediately before the first write.
    check_source(source, value, base, patched=False)
    command(source, 'apply', '--whitespace=error-all', '-', payload=patch)
    check_source(source, value, base, patched=True)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Rejected('native bootstrap source preparation rejected')


def main():
    parser = Parser(description=__doc__)
    parser.add_argument('operation', choices=('verify-baseline', 'apply', 'verify-patched'))
    parser.add_argument('--source', type=Path, required=True)
    arguments = parser.parse_args()
    hosted_guard(arguments.source)
    value = parse_manifest(read(HERE / 'manifest.json', MAX_MANIFEST))
    base = baseline_manifest()
    patch_bytes(value)
    if arguments.operation == 'apply':
        apply(arguments.source, value, base)
    else:
        check_source(arguments.source, value, base, patched=arguments.operation == 'verify-patched')
    print(json.dumps({'schema': 1, 'operation': arguments.operation, 'source_commit': UPSTREAM,
                      'patch_sha256': value['patch']['sha256'], 'compiled': False,
                      'native_runtime_proven': False, 'published': False,
                      'full_studio_acceptance': False, 'volparossa_update_authority_granted': False},
                     sort_keys=True))


def entry():
    def cancelled(_number, _frame):
        raise Rejected('native bootstrap source preparation interrupted')

    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        for number in previous:
            signal.signal(number, cancelled)
        main()
    except (Exception, KeyboardInterrupt):
        print('native bootstrap source preparation rejected', file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


if __name__ == '__main__':
    entry()
