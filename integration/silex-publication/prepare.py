#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Verify/apply one reviewed Silex publication patch; never compile or publish.

Apply is restricted to an explicit clean disposable hosted source checkout.
The original source pin and every non-server lock package record are preserved.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

HERE = Path(__file__).resolve().parent
UPSTREAM = '672efed69dda04c0a1e968859239e042f00d9538'
ORIGIN = 'https://github.com/silexlabs/Silex'
ROOT_LOCK = 'eb92b416e0ed0428d11068202132c95dbfb02a2e5c12fd6b315df71248c83f13'
ALLOWED = {
    'Cargo.lock', 'server-rust/Cargo.toml',
    'server-rust/src/connectors/mod.rs', 'server-rust/src/connectors/traits.rs',
    'server-rust/src/connectors/fs_storage.rs',
    'server-rust/src/connectors/fs_storage/bounded_asset.rs',
    'server-rust/src/connectors/fs_storage/bounded_asset/tests.rs',
    'server-rust/src/routes/publication.rs',
    'server-rust/src/routes/publication/preparation.rs',
    'server-rust/src/routes/publication/preparation/tests.rs',
    'server-rust/src/routes/publication/tests.rs',
}
MAX_FILE = 2 * 1024 * 1024
MAX_PATCH = 1024 * 1024
MAX_MANIFEST = 65536
SHA = re.compile(r'[0-9a-f]{64}\Z')


def require(condition):
    if not condition:
        raise ValueError('publication source preparation rejected')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(values):
    result = {}
    for key, value in values:
        require(key not in result)
        result[key] = value
    return result


def read(path, maximum):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum
                and not before.st_mode & 0o022)
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, len(raw), after.st_mtime_ns, after.st_ctime_ns))
    return raw


def manifest():
    raw = read(HERE / 'manifest.json', MAX_MANIFEST)
    value = json.loads(raw, object_pairs_hook=pairs)
    require(type(value) is dict and value.keys() == {'schema', 'origin', 'upstream_commit', 'baseline_root_lock_sha256',
        'patch', 'files', 'capability', 'acceptance'})
    require(type(value['schema']) is int and value['schema'] == 1 and value['origin'] == ORIGIN
            and value['upstream_commit'] == UPSTREAM and value['baseline_root_lock_sha256'] == ROOT_LOCK)
    patch = value['patch']
    require(type(patch) is dict and patch.keys() == {'path', 'bytes', 'sha256'}
            and patch['path'] == 'patches/publication-bounds.patch'
            and type(patch['bytes']) is int and 0 < patch['bytes'] <= MAX_PATCH
            and type(patch['sha256']) is str and SHA.fullmatch(patch['sha256']))
    require(type(value['files']) is dict and value['files'].keys() == ALLOWED)
    for name, entry in value['files'].items():
        require(type(entry) is dict and entry.keys() == {'before', 'after'})
        for side in ('before', 'after'):
            record = entry[side]
            if record is None:
                require(side == 'before')
                continue
            require(type(record) is dict and record.keys() == {'bytes', 'sha256', 'mode'}
                    and type(record['bytes']) is int and 0 < record['bytes'] <= MAX_FILE
                    and record['mode'] == '100644' and type(record['sha256']) is str and SHA.fullmatch(record['sha256']))
    require(value['capability'] == {'platform': 'linux-openat2', 'active_fs_read_jobs_per_connector': 2,
        'maximum_body_bytes': 268435456, 'maximum_assets': 256, 'maximum_path_bytes': 1024,
        'maximum_index_bytes': 262144, 'maximum_object_bytes': 268435456, 'preparation_seconds': 30,
        'default_non_fs_bounded_read': 'unsupported', 'root_workspace_lock': 'Cargo.lock',
        'selected_package': 'silex-server', 'whole_shutdown_drain_proven': False})
    require(value['capability']['whole_shutdown_drain_proven'] is False)
    require(value['acceptance'] == {'native_publication_authorization': False, 'independent_hosting': False,
        'browser_rendering': False, 'full_studio': False})
    require(all(item is False for item in value['acceptance'].values()))
    return value


def git(source, *args):
    environment = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_OPTIONAL_LOCKS='0')
    result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(source), *args],
        check=True, capture_output=True, timeout=20, env=environment)
    require(len(result.stdout) <= MAX_FILE)
    return result.stdout


def check_source(source, value, *, patched):
    require(source.is_absolute() and source.resolve(strict=True) == source and source.is_dir())
    require(git(source, 'rev-parse', 'HEAD').strip().decode() == UPSTREAM)
    changed = set(git(source, 'diff', '--name-only', 'HEAD').decode().splitlines())
    changed.update(git(source, 'ls-files', '--others', '--exclude-standard').decode().splitlines())
    require(changed == ALLOWED if patched else not changed)
    original = git(source, 'show', 'HEAD:Cargo.lock')
    require(digest(original) == ROOT_LOCK)
    for name, entry in value['files'].items():
        path = source / name
        expected = entry['after' if patched else 'before']
        if expected is None:
            require(not path.exists() and not path.is_symlink())
        else:
            require(path.resolve(strict=True) == path and stat.S_IMODE(path.stat().st_mode) == 0o644)
            raw = read(path, MAX_FILE)
            require(len(raw) == expected['bytes'] and digest(raw) == expected['sha256'])
    # Prove the approved single workspace graph edge without accepting lock drift.
    old_parts = original.split(b'[[package]]')
    new_parts = read(source / 'Cargo.lock', MAX_FILE).split(b'[[package]]')
    require(len(old_parts) == len(new_parts))
    for old, new in zip(old_parts, new_parts):
        if old.startswith(b'\nname = "silex-server"\n') and patched:
            require(b' "rustix",\n' not in old and new == old.replace(b' "mime_guess",\n', b' "mime_guess",\n "rustix",\n', 1))
        else:
            require(old == new)
    require(read(source / 'server-rust/Cargo.lock', MAX_FILE) == git(source, 'show', 'HEAD:server-rust/Cargo.lock'))


def apply(source, value):
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted')
    check_source(source, value, patched=False)
    patch = read(HERE / value['patch']['path'], MAX_PATCH)
    require(len(patch) == value['patch']['bytes'] and digest(patch) == value['patch']['sha256'])
    for arguments in (('apply', '--check', '--whitespace=error-all'), ('apply', '--whitespace=error-all')):
        subprocess.run(['git', '-C', str(source), *arguments, '-'], input=patch, check=True,
            capture_output=True, timeout=20)
    check_source(source, value, patched=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('verify-baseline', 'apply', 'verify-patched'))
    parser.add_argument('--source', type=Path, required=True)
    arguments = parser.parse_args()
    value = manifest()
    if arguments.operation == 'apply':
        apply(arguments.source, value)
    else:
        check_source(arguments.source, value, patched=arguments.operation == 'verify-patched')
    print(json.dumps({'schema': 1, 'source_commit': UPSTREAM, 'patch_sha256': value['patch']['sha256'],
        'operation': arguments.operation, 'compiled': False, 'published': False, 'full_studio_acceptance': False}, sort_keys=True))


if __name__ == '__main__':
    main()
