# SPDX-License-Identifier: GPL-3.0-only
"""Fixed private handoff, consumed only after the wrapper drops privileges."""
import json
import os
from pathlib import Path
import pwd
import stat

CONTEXT_KEYS = frozenset(('STUDIO_NODE', 'STUDIO_CHROME', 'STUDIO_SILEX_SOURCE',
    'STUDIO_FIXTURE_TEMP', 'STUDIO_ZIP_OUTPUT', 'STUDIO_BROWSER_RECEIPT', 'RUNNER_TEMP', 'HOME'))


def checked_context(path, values):
    temporary = Path(path).parent
    if set(values) != CONTEXT_KEYS or any(type(value) is not str for value in values.values()):
        raise ValueError('closed runtime context required')
    expected = {'STUDIO_NODE': temporary / 'node/node', 'STUDIO_SILEX_SOURCE': temporary / 'silex',
        'STUDIO_FIXTURE_TEMP': temporary, 'STUDIO_ZIP_OUTPUT': temporary / 'actual-export.zip',
        'STUDIO_BROWSER_RECEIPT': temporary / 'browser.json', 'RUNNER_TEMP': temporary.parent}
    if any(values[key] != str(value) for key, value in expected.items()):
        raise ValueError('runtime context path boundary')
    if values['HOME'] != pwd.getpwuid(os.getuid()).pw_dir:
        raise ValueError('original runner home identity mismatch')
    if values['STUDIO_CHROME'] not in ('/usr/bin/google-chrome', '/usr/bin/google-chrome-stable'):
        raise ValueError('fixed installed browser launcher required')
    return values


def write_context(path, env):
    values = checked_context(path, {key: env[key] for key in CONTEXT_KEYS})
    data = (json.dumps(values, sort_keys=True) + '\n').encode()
    if len(data) > 16384:
        raise ValueError('runtime context size bound')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(data)


def read_context(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as source:
        metadata = os.fstat(source.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_nlink != 1
                or metadata.st_size > 16384):
            raise ValueError('private owned runtime context required')
        data = source.read(16385)
    if len(data) > 16384:
        raise ValueError('runtime context size bound')
    return checked_context(path, json.loads(data))


def restored_environment(values):
    # Called after privilege drop; no context/PATH is consumed by sudo/setpriv.
    # Incoming sudo environment (including root's HOME) is not inherited.
    return dict(values, PATH='/usr/bin:/bin', CI='true', DO_NOT_TRACK='1',
                PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1')
