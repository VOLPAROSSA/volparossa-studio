# SPDX-License-Identifier: GPL-3.0-only
"""Bind Silex's local publication to the production Core pack review receipt."""
import hashlib
import json
from itertools import islice
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


CORE_SOURCE = 'c8689558544eb56f28c4de5df805e4d9bbd5d358'
CORE_LOCK = 'ef5df0f0a6a1db08908d368e085d43b93ce29db5812b283475497a1658110b00'
CSS = re.compile(r'index-(?:[0-9a-f]{64}|local)\.css')


def require(test):
    if not test:
        raise ValueError('native_site_export_rejected')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path, maximum):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                and 0 < info.st_size <= maximum)
        data = source.read(maximum + 1)
        end = os.fstat(source.fileno())
        require(len(data) == end.st_size == info.st_size and end.st_ctime_ns == info.st_ctime_ns)
        return data


def assets(directory, project_id):
    require(directory.resolve(strict=True) == directory)
    with os.scandir(directory) as entries:
        require({entry.name for entry in islice(entries, 3)} == {'css', 'index.html'})
    css_dir = directory / 'css'
    require(css_dir.resolve(strict=True) == css_dir and css_dir.is_dir())
    with os.scandir(css_dir) as entries:
        styles = [css_dir / entry.name for entry in islice(entries, 2)]
    require(len(styles) == 1 and CSS.fullmatch(styles[0].name))
    html = read_regular(directory / 'index.html', 32768)
    css = read_regular(styles[0], 32768)
    require(('Restored canvas ' + project_id).encode('ascii') in html and styles[0].name.encode('ascii') in html)
    return [{'path': '/css/' + styles[0].name, 'content_type': 'text/css', 'bytes': len(css), 'sha256': sha(css)},
            {'path': '/index.html', 'content_type': 'text/html', 'bytes': len(html), 'sha256': sha(html)}]


def pack(directory, project_id):
    original = assets(directory, project_id)
    with tempfile.TemporaryDirectory(dir=os.environ['XDG_RUNTIME_DIR']) as work:
        bundle = Path(work) / 'site.bundle'
        command = ['/run/fixture/volparossa', '--control-socket', str(Path(work) / 'unused.sock'),
            'content', 'site', 'pack', '--directory', str(directory), '--output', str(bundle), '--review-receipt']
        with tempfile.TemporaryFile(dir=work) as output:
            result = subprocess.run(command, cwd=work, env={'LANG': 'C'}, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.DEVNULL, timeout=8, check=False)
            output.seek(0)
            raw = output.read(8193)
        require(result.returncode == 0 and 0 < len(raw) <= 8192)
        review = json.loads(raw)
        packed = read_regular(bundle, 131072)
        require(review['assets'] == original == assets(directory, project_id) and review['bundle_bytes'] == len(packed)
                and review['bundle_sha256'] == sha(packed))
        return review


def build_receipt():
    root = Path(os.environ['GITHUB_WORKSPACE'])
    work = Path(os.environ['RUNNER_TEMP'])
    require(os.environ['GITHUB_ACTIONS'] == 'true' and os.environ['RUNNER_ENVIRONMENT'] == 'github-hosted'
            and os.getuid() != 0 and Path.cwd() == root / 'core')
    revision = os.environ['GITHUB_SHA']
    require(re.fullmatch('[0-9a-f]{40}', revision) and os.environ['GITHUB_WORKFLOW_SHA'] == revision)
    for directory, expected in ((root / 'studio', revision), (root / 'core', CORE_SOURCE)):
        require(subprocess.check_output(['git', '-C', directory, 'rev-parse', 'HEAD'], text=True).strip() == expected)
    require(sha((root / 'core/Cargo.lock').read_bytes()) == CORE_LOCK)
    binary = work / 'studio-native-site-core-target/debug/volparossa'
    require(binary.resolve(strict=True) == binary)
    with binary.open('rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink in (1, 2)
            and info.st_mode & 0o100 and not info.st_mode & 0o022 and 2**20 <= info.st_size <= 256 * 2**20
            and stream.read(6) == b'\x7fELF\x02\x01')
        stream.seek(0)
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    record = dict(schema=1, operation='native_site_core_build', status='passed', studio_revision=revision,
        core_revision=CORE_SOURCE, core_lock_sha256=CORE_LOCK, binary=dict(bytes=info.st_size,
            sha256=digest, links=info.st_nlink, mode=stat.S_IMODE(info.st_mode)))
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
    with os.fdopen(os.open(work / 'silex-native-site-core-build.json', flags, 0o600), 'w') as output:
        print(json.dumps(record, sort_keys=True), file=output)


if __name__ == '__main__':
    require(sys.argv[1:] == ['build-receipt'])
    build_receipt()
