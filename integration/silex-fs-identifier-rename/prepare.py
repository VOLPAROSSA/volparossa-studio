#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Admit only the fixed FS overlay after the existing reviewed Native6 source."""
import importlib.util
import json
from pathlib import Path
import re
import signal
import stat
import sys

HERE = Path(__file__).resolve().parent
BOOTSTRAP = HERE.parent / 'silex-native-bootstrap'
PATHS = frozenset(('server-rust/src/connectors/fs_storage.rs',
    'server-rust/src/connectors/traits.rs', 'server-rust/src/models/website.rs',
    'server-rust/src/models/connector.rs', 'server-rust/src/routes/website.rs',
    'desktop/src-tauri/src/mcp.rs', 'server-rust/src/connectors/fs_hosting.rs',
    'server-rust/src/connectors/fs_storage/identifier.rs',
    'server-rust/src/connectors/fs_storage/metadata.rs',
    'server-rust/src/connectors/fs_storage/tests.rs',
    'server-rust/src/connectors/fs_storage/metadata/tests.rs'))
SPEC = importlib.util.spec_from_file_location('fs_overlay_native_prepare', BOOTSTRAP / 'prepare.py')
SUPPORT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SUPPORT
SPEC.loader.exec_module(SUPPORT)


def require(value):
    SUPPORT.require(value)


def manifest():
    value = json.loads(SUPPORT.read(HERE / 'manifest.json', 65536), object_pairs_hook=SUPPORT.pairs)
    require(type(value) is dict and value.keys() == {'schema', 'operation', 'source_commit',
        'base_native_manifest_sha256', 'base_native_patch_sha256', 'root_lock_sha256', 'patch', 'files', 'scope'})
    require(type(value['schema']) is int and value['schema'] == 1
        and value['operation'] == 'fs_identifier_name_rename' and value['source_commit'] == SUPPORT.UPSTREAM
        and value['base_native_manifest_sha256'] == 'c68ffe977807e21b8f7070430f81d043bc47ea0aa148606e36e0908a5c8ab576'
        and value['base_native_patch_sha256'] == 'e927749533958b9ab3dda95b0378baa1649ec5e2b5409c7b73d5a729fbe67bd2'
        and value['root_lock_sha256'] == 'de04aaf5ff1acbdde421e3447ea67f3eb7a00a7d5ed118f4387a180e84590118')
    require(type(value['files']) is dict and value['files'].keys() == PATHS)
    for name, row in value['files'].items():
        require(type(row) is dict and row.keys() == {'before', 'after'})
        for side in ('before', 'after'):
            if side == 'before' and row[side] is None:
                require(name.startswith('server-rust/src/connectors/fs_storage/'))
            else:
                SUPPORT.record(row[side])
    require(value['scope'] == dict(source_candidate=True, hosted_tests_passed=False,
        http_runtime_proven=False, native_gui_proven=False, generic_asset_path_confinement_proven=False,
        authorization_proven=False, cross_process_cas_proven=False, publication_authorized=False))
    patch = value['patch']
    require(type(patch) is dict and patch.keys() == {'path', 'bytes', 'sha256'}
            and patch['path'] == 'patches/fs-identifier-rename.patch'
            and type(patch['bytes']) is int and 0 < patch['bytes'] <= 1024 * 1024
            and type(patch['sha256']) is str and re.fullmatch('[0-9a-f]{64}', patch['sha256']))
    return value


def patch_bytes(value):
    raw = SUPPORT.read(HERE / 'patches/fs-identifier-rename.patch', 1024 * 1024)
    require(len(raw) == value['patch']['bytes'] and SUPPORT.digest(raw) == value['patch']['sha256']
            and b'\0' not in raw and b'\r' not in raw)
    lines = raw.decode('utf-8', errors='strict').splitlines(keepends=True)
    require(all(line.endswith('\n') for line in lines))
    seen = set()
    cursor = 0
    while cursor < len(lines):
        header = re.fullmatch(r'diff --git a/(\S+) b/(\S+)\n', lines[cursor])
        require(header is not None and header[1] == header[2] and header[1] in PATHS and header[1] not in seen)
        name = header[1]
        seen.add(name)
        cursor += 1
        new = value['files'][name]['before'] is None
        if new:
            require(lines[cursor] == 'new file mode 100644\n')
            cursor += 1
        require(lines[cursor] == ('--- /dev/null\n' if new else '--- a/' + name + '\n')
                and lines[cursor + 1] == '+++ b/' + name + '\n')
        cursor += 2
        hunks = 0
        while cursor < len(lines) and not lines[cursor].startswith('diff --git '):
            hunk = re.fullmatch(r'@@ -[0-9]+(?:,([0-9]+))? \+[0-9]+(?:,([0-9]+))? @@[^\n]*\n', lines[cursor])
            require(hunk is not None)
            old, added = (int(hunk[i]) if hunk[i] is not None else 1 for i in (1, 2))
            cursor += 1
            while old or added:
                require(cursor < len(lines) and lines[cursor][:1] in (' ', '+', '-'))
                prefix = lines[cursor][0]
                old -= prefix in (' ', '-')
                added -= prefix in (' ', '+')
                require(old >= 0 and added >= 0)
                cursor += 1
            hunks += 1
        require(hunks > 0)
    require(seen == PATHS)
    return raw


def source_check(source, value, native, base, patched):
    SUPPORT.hosted_guard(source)
    if not patched:
        SUPPORT.check_source(source, native, base, patched=True)
    expected = {name: row['after'] for name, row in base['files'].items()}
    expected.update({name: row['after'] for name, row in native['files'].items()})
    for name, row in value['files'].items():
        if patched:
            expected[name] = row['after']
        elif row['before'] is None:
            require(not (source / name).exists() and not (source / name).is_symlink())
        else:
            SUPPORT.check_file(source, name, row['before'])
    require(SUPPORT.command(source, 'rev-parse', '--show-toplevel').decode().strip() == str(source)
            and SUPPORT.command(source, 'rev-parse', 'HEAD').decode().strip() == SUPPORT.UPSTREAM)
    require(not SUPPORT.command(source, 'diff', '--cached', '--name-only', '-z', 'HEAD', '--'))
    require(all(row.startswith(b'H ') for row in SUPPORT.command(source, 'ls-files', '-v', '-z').split(b'\0') if row))
    changed = SUPPORT.command(source, 'diff', '--no-ext-diff', '--no-textconv', '--name-only', '-z', 'HEAD', '--')
    changed += SUPPORT.command(source, 'ls-files', '--others', '-z')
    require({name.decode('utf-8') for name in changed.split(b'\0') if name} == expected.keys())
    for name, row in expected.items():
        SUPPORT.check_file(source, name, row)
        require(stat.S_IMODE((source / name).lstat().st_mode) == stat.S_IMODE(int(row['mode'], 8)))
    for name in ('server-rust/Cargo.lock', 'desktop/src-tauri/Cargo.lock', 'Cargo.toml'):
        require(SUPPORT.read(source / name, SUPPORT.MAX_FILE) == SUPPORT.command(source, 'show', 'HEAD:' + name))


def main():
    parser = SUPPORT.Parser(description=__doc__)
    parser.add_argument('operation', choices=('verify-baseline', 'apply', 'verify-patched'))
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    value = manifest()
    require(SUPPORT.digest(SUPPORT.read(BOOTSTRAP / 'manifest.json', 65536)) == value['base_native_manifest_sha256'])
    native = SUPPORT.parse_manifest(SUPPORT.read(BOOTSTRAP / 'manifest.json', 65536))
    require(SUPPORT.digest(SUPPORT.patch_bytes(native)) == value['base_native_patch_sha256'])
    base = SUPPORT.baseline_manifest()
    raw = patch_bytes(value)
    source_check(args.source, value, native, base, args.operation == 'verify-patched')
    if args.operation == 'apply':
        SUPPORT.command(args.source, 'apply', '--check', '--whitespace=error-all', '-', payload=raw)
        source_check(args.source, value, native, base, False)
        SUPPORT.command(args.source, 'apply', '--whitespace=error-all', '-', payload=raw)
        source_check(args.source, value, native, base, True)
    print(json.dumps(dict(schema=1, operation=args.operation, patch_sha256=value['patch']['sha256'],
                          compiled=False, hosted_tests_passed=False, publication_authorized=False), sort_keys=True))


def entry():
    def cancelled(_number, _frame):
        raise SUPPORT.Rejected('FS overlay preparation cancelled')
    numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = {number: signal.getsignal(number) for number in numbers}
    primary = None
    try:
        for number in numbers:
            signal.signal(number, cancelled)
        main()
    except BaseException as error:
        primary = error
    finally:
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
        try:
            for number, handler in previous.items():
                try:
                    signal.signal(number, handler)
                except BaseException as error:
                    primary = primary or error
        finally:
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            except BaseException as error:
                primary = primary or error
    if primary is not None:
        raise primary


if __name__ == '__main__':
    try:
        entry()
    except BaseException:
        raise SystemExit(1) from None
