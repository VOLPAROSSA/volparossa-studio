# SPDX-License-Identifier: GPL-3.0-only
"""Bounded extraction of an actual DownloadConnector ZIP; never follows links."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

MAX_ZIP = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_FILES = 256
MAX_ENTRIES = 4096


def extract(archive, destination, inventory):
    archive, destination, inventory = map(Path, (archive, destination, inventory))
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > MAX_ZIP:
        raise ValueError('zip bound or type')
    # New private tree only; caller must clean partial output on failure.
    destination.mkdir(mode=0o700)
    files, names, total = [], set(), 0
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if not 1 <= len(entries) <= MAX_ENTRIES:
            raise ValueError('entry bound')
        for entry in entries:
            raw = entry.filename
            path = PurePosixPath(raw)
            parts = raw.rstrip('/').split('/')
            mode = entry.external_attr >> 16
            if (not raw or '\\' in raw or '\x00' in raw or path.is_absolute()
                    or any(not part or part.startswith('.') or ':' in part or '%' in part for part in parts)
                    or len(parts) > 17 or len(raw.encode('utf-8')) > 1024
                    or raw.rstrip('/') in names or entry.flag_bits & 1
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                    or (entry.is_dir() != (stat.S_IFMT(mode) == stat.S_IFDIR) and stat.S_IFMT(mode))):
                raise ValueError('unsafe zip entry')
            names.add(raw.rstrip('/'))
            output = destination.joinpath(*parts)
            if entry.is_dir():
                output.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            total += entry.file_size
            if total > MAX_TOTAL or len(files) >= MAX_FILES:
                raise ValueError('asset bound')
            output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            digest = hashlib.sha256()
            actual = 0
            with bundle.open(entry) as source, output.open('xb') as target:
                output.chmod(0o600)
                while chunk := source.read(min(65536, entry.file_size - actual + 1)):
                    actual += len(chunk)
                    if actual > entry.file_size:
                        raise ValueError('expanded size mismatch')
                    digest.update(chunk)
                    target.write(chunk)
            if actual != entry.file_size:
                raise ValueError('truncated zip entry')
            files.append({'path': '/' + '/'.join(parts), 'bytes': actual, 'sha256': digest.hexdigest()})
    if '/index.html' not in {item['path'] for item in files}:
        raise ValueError('portable index absent')
    with inventory.open('x') as output:
        json.dump({'schema': 1, 'assets': sorted(files, key=lambda item: item['path'])}, output)
        output.write('\n')
    return len(files)
