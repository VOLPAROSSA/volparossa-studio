# SPDX-License-Identifier: GPL-3.0-only
"""Finite opt-in and private compiler-artifact handoff; never runtime authority."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat

MODE = 'signed-site-recovery'
TARGET = 'studio_signed_site_recovery'
TEST = 'studio_signed_site_recovery_native_preview_and_browser'
LEGACY_TEST = 'actual_silex_export_packs_and_decodes_without_publication'
MAX_CONTEXT = 16384


def arguments(values):
    if len(values) == 3:
        return tuple(map(Path, values)), 'viewer'
    if len(values) == 5 and values[3:] == ['--proof-mode', MODE]:
        return tuple(map(Path, values[:3])), MODE
    raise ValueError('three fixed paths and an optional explicit signed-site-recovery mode required')


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON field')
        value[key] = item
    return value


def strict_json(data):
    def invalid_constant(_value):
        raise ValueError('nonfinite JSON value')
    return json.loads(data, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def read_private(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as source:
        before = os.fstat(source.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                or not 0 <= before.st_size <= maximum):
            raise ValueError('bounded private owned regular file required')
        data = source.read(maximum + 1)
        after = os.fstat(source.fileno())
    fields = ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_nlink',
              'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if (len(data) > maximum or len(data) != before.st_size
            or any(getattr(before, key) != getattr(after, key) for key in fields)):
        raise ValueError('private file changed while reading')
    return data


def executable(path):
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o022 or not metadata.st_mode & 0o100
            or metadata.st_size == 0 or path.resolve() != path):
        raise ValueError('fixed owned Core executable required')
    return path


@dataclass(frozen=True)
class CoreContext:
    mode: str
    executable: Path
    core_root: Path | None = None


def checked_signed_context(value):
    if (type(value) is not dict or set(value) != {'schema', 'proof_mode', 'core_root', 'executable'}
            or type(value['schema']) is not int or value['schema'] != 2
            or value['proof_mode'] != MODE
            or any(type(value[key]) is not str for key in ('core_root', 'executable'))):
        raise ValueError('closed signed-site context required')
    root = Path(value['core_root'])
    binary = Path(value['executable'])
    if (not root.is_absolute() or root.resolve() != root or not root.is_dir()
            or binary.parent != root / 'target/debug/deps'
            or not re.fullmatch(TARGET + r'-[0-9a-f]+', binary.name)):
        raise ValueError('fixed signed-site compiler artifact required')
    for name in ('volparossa', 'volparossa-agent'):
        executable(root / 'target/debug' / name)
    return CoreContext(MODE, executable(binary), root)


def write_signed_context(path, core, binary):
    value = {'schema': 2, 'proof_mode': MODE, 'core_root': str(core.resolve()),
             'executable': str(binary)}
    checked_signed_context(value)
    data = (json.dumps(value, sort_keys=True) + '\n').encode()
    if len(data) > MAX_CONTEXT:
        raise ValueError('signed-site context bound')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(data)


def read_core_context(path):
    # One descriptor supplies discriminator, metadata and bytes. No catch/fallback
    # can reinterpret a rejected schema-2 invocation as the old viewer proof.
    value = strict_json(read_private(path, MAX_CONTEXT))
    if type(value) is dict and type(value.get('schema')) is int and value['schema'] == 2:
        return checked_signed_context(value)
    if (type(value) is not dict or set(value) != {'schema', 'executable'}
            or type(value['schema']) is not int or value['schema'] != 1
            or type(value['executable']) is not str):
        raise ValueError('closed Core proof context required')
    binary = Path(value['executable'])
    # Preserve the original schema-1 path contract; the exported legacy reader
    # remains unchanged for callers/tests of that original interface.
    if (not binary.is_absolute() or binary.parent.parts[-3:] != ('target', 'debug', 'deps')
            or not re.fullmatch(r'studio_site_pack-[0-9a-f]+', binary.name)
            or binary.is_symlink() or not binary.is_file()):
        raise ValueError('actual Core test executable boundary')
    return CoreContext('viewer', binary)
