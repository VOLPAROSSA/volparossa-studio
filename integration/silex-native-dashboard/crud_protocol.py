# SPDX-License-Identifier: GPL-3.0-only
"""Closed public-fixture protocol; no process or network action on import."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat

MAX_JSON = 65536
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z')
ASSETS = frozenset(('index.html', 'dashboard.css', 'dashboard.js'))
CORE = 'e58d1c9bb4412ee15ad68033f1eb051494a87725'
WRAPPER_SHA = '644bbcbc869bb69eb0b1611de89a83e7ff6aa635ee993042e05ec16fb8d387e0'
CONTEXT_KEYS = frozenset(('schema', 'revision', 'root', 'node', 'chrome', 'server',
    'parent_net', 'parent_pid', 'uid', 'gid', 'assets', 'files'))
STAGES = frozenset(('admission', 'server_start', 'browser_first', 'http_denials',
                    'server_restart', 'browser_second', 'cleanup', 'complete'))
ACTIONS = frozenset(('browser_launch', 'page_load', 'static_assets', 'empty', 'create',
    'fixture_metadata', 'rename', 'duplicate', 'persisted_list', 'delete_duplicate',
    'delete_original', 'browser_close', 'complete'))
CHROME_FLAGS = frozenset(('chrome_sandbox_failure', 'chrome_namespace_failure',
    'chrome_library_failure', 'chrome_startup_failure', 'dom_timeout'))
BROWSER_KEYS = frozenset(('schema', 'phase', 'status', 'steps', 'sandbox_requested',
    'browser_closed', 'context_closed', 'external_denied', 'requests', 'ids',
    'metadata_before_sha256', 'metadata_after_sha256', 'other_bytes_preserved',
    'typed_rename_only', 'browser_version', 'failure_action', 'failure_http_status')) | CHROME_FLAGS


def require(value):
    if not value:
        raise ValueError('closed public CRUD fixture rejected')


def pairs(values):
    result = {}
    for key, value in values:
        require(key not in result)
        result[key] = value
    return result


def decode(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON)
    def invalid(_value):
        raise ValueError('nonfinite fixture JSON')
    return json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=pairs,
                      parse_constant=invalid)


def identity(info):
    return tuple(getattr(info, name) for name in ('st_dev', 'st_ino', 'st_uid', 'st_gid',
        'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def with_fd(path, flags, mode, operation):
    """Own the raw FD across acquisition, deferred signals and every failure."""
    descriptor = None
    primary = None
    result = None
    numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
    acquire_mask = None
    try:
        try:
            acquire_mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
            descriptor = os.open(path, flags, mode)
        except BaseException as error:
            primary = error
        finally:
            if acquire_mask is not None:
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, acquire_mask)
                except BaseException as error:
                    primary = primary or error
        if primary is None:
            try:
                result = operation(descriptor)
            except BaseException as error:
                primary = error
    finally:
        close_mask = None
        try:
            close_mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
        except BaseException as error:
            primary = primary or error
        try:
            if descriptor is not None:
                try:
                    os.close(descriptor)  # Never retry an ambiguously closed FD.
                except BaseException as error:
                    primary = primary or error
        finally:
            if close_mask is not None:
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, close_mask)
                except BaseException as error:
                    primary = primary or error
    if primary is not None:
        raise primary
    return result


def read(path, maximum=MAX_JSON, modes=(0o600,), executable=False, allow_empty=False):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path)
    def operation(descriptor):
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
                and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) in modes
                and (0 if allow_empty else 1) <= before.st_size <= maximum
                and (not executable or before.st_mode & 0o100))
        raw = os.read(descriptor, maximum + 1)
        require(len(raw) == before.st_size and identity(before) == identity(os.fstat(descriptor))
                and identity(before) == identity(path.lstat()))
        return raw
    return with_fd(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, operation)


def write(path, value):
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    require(len(raw) <= MAX_JSON)
    def operation(descriptor):
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            require(written > 0)
            offset += written
        os.fsync(descriptor)
    with_fd(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, operation)


def context(value, root):
    require(root.is_absolute() and root.resolve(strict=True) == root
        and root.is_dir() and root.stat().st_uid == os.geteuid()
        and stat.S_IMODE(root.stat().st_mode) == 0o700
        and re.fullmatch('studio-export-crud-[A-Za-z0-9_-]+', root.name))
    require(type(value) is dict and value.keys() == CONTEXT_KEYS
            and type(value['schema']) is int and value['schema'] == 1
            and type(value['revision']) is str and re.fullmatch('[0-9a-f]{40}', value['revision'])
            and value['root'] == str(root) and type(value['uid']) is int and value['uid'] > 0
            and type(value['gid']) is int and value['gid'] > 0)
    for key, expected in (('node', root / 'node/node'), ('server', root / 'server')):
        require(value[key] == str(expected))
    require(value['chrome'] in ('/usr/bin/google-chrome', '/usr/bin/google-chrome-stable'))
    for key, prefix in (('parent_net', 'net'), ('parent_pid', 'pid')):
        require(type(value[key]) is str and re.fullmatch(prefix + r':\[[0-9]{1,20}\]', value[key]))
    require(type(value['assets']) is dict and value['assets'].keys() == ASSETS)
    for item in value['assets'].values():
        require(type(item) is dict and item.keys() == {'sha256', 'bytes'}
                and type(item['bytes']) is int and 0 < item['bytes'] <= 65536
                and type(item['sha256']) is str and re.fullmatch('[0-9a-f]{64}', item['sha256']))
    require(type(value['files']) is dict and value['files'].keys() == {
        'fixture/runtime.py', 'fixture/crud_protocol.py', 'fixture/crud_browser.mjs', 'server', 'node/node'})
    for path, digest in value['files'].items():
        require(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest))
        modes = (0o700,) if path in ('server', 'node/node') else (0o600,)
        maximum = 256 * 1024 * 1024 if path in ('server', 'node/node') else 131072
        require(hashlib.sha256(read(root / path, maximum, modes)).hexdigest() == digest)
    for name, record in value['assets'].items():
        raw = read(root / 'public' / name)
        require(len(raw) == record['bytes'] and hashlib.sha256(raw).hexdigest() == record['sha256'])
    return value


def browser_receipt(value, phase):
    require(phase in ('first', 'second'))
    require(type(value) is dict and value.keys() == BROWSER_KEYS)
    require(type(value['schema']) is int and value['schema'] == 1 and value['phase'] == phase
            and value['status'] == 'passed'
            and all(value[key] is True for key in ('sandbox_requested', 'browser_closed',
                'context_closed', 'typed_rename_only')))
    require(value['failure_action'] is None and value['failure_http_status'] is None
            and all(value[key] is False for key in CHROME_FLAGS))
    require(value['steps'] == (['empty', 'create', 'rename', 'duplicate'] if phase == 'first'
                              else ['persisted_list', 'delete_duplicate', 'delete_original', 'empty']))
    require(type(value['ids']) is list and len(value['ids']) == 2
            and len(set(value['ids'])) == 2 and all(type(i) is str and UUID.fullmatch(i) for i in value['ids']))
    require(type(value['requests']) is int and 1 <= value['requests'] <= 256
            and type(value['external_denied']) is int and 0 <= value['external_denied'] <= 256
            and type(value['browser_version']) is str
            and re.fullmatch(r'[0-9]{1,4}(?:\.[0-9]{1,8}){1,3}', value['browser_version']))
    require(value['other_bytes_preserved'] is (phase == 'first'))
    for key in ('metadata_before_sha256', 'metadata_after_sha256'):
        require((type(value[key]) is str and re.fullmatch('[0-9a-f]{64}', value[key]))
                if phase == 'first' else value[key] is None)
    require(phase != 'first' or value['metadata_before_sha256'] != value['metadata_after_sha256'])
    return value


def browser_failure(value, phase):
    require(phase in ('first', 'second'))
    # Select no dynamic fields even from an adversarial failed private receipt.
    require(type(value) is dict and value.keys() == BROWSER_KEYS
            and value.get('schema') == 1 and type(value.get('schema')) is int
            and value.get('phase') == phase and value.get('status') == 'failed')
    action = value.get('failure_action')
    status = value.get('failure_http_status')
    require(type(action) is str and action in ACTIONS
        and (status is None or (type(status) is int and 100 <= status <= 599)))
    require(all(type(value.get(key)) is bool for key in CHROME_FLAGS))
    return dict(action=action, http_status=status, **{key: value[key] for key in CHROME_FLAGS})
