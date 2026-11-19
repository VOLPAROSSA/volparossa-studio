# SPDX-License-Identifier: GPL-3.0-only
"""Restore a real saved Silex project and collect its private native File system hosting output."""
import hashlib
import io
from itertools import islice
import json
import os
from pathlib import Path
import re
import stat
import zipfile

MARKER = 'VOLPAROSSA Studio manual export 20261022'
CHART = 'studio-topology.png'
LIMIT = 3 * 1024 * 1024
FIXTURE = Path('/run/fixture')


def require(ok):
    if not ok:
        raise ValueError('native_project_export_mismatch')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def capture_project(raw):
    require(0 < len(raw) <= 65536)
    saved = json.loads(raw)
    pages = saved['pages']
    require(type(pages) is list and len(pages) == 2 and pages[1]['name'] == 'Studio export')
    frame = json.dumps(pages[1]['frames'])
    require(MARKER in frame and '37px' in raw.decode() and '/assets/' + CHART in frame)
    return saved


def expected_rows(raw):
    inventory = json.loads(raw)
    require(type(inventory) is dict and inventory.keys() == {'schema', 'assets'} and inventory['schema'] == 1)
    rows = inventory['assets']
    require(type(rows) is list and len(rows) == 5)
    patterns = [r'/assets/studio-topology\.png', r'/css/index-[a-f0-9]{64}\.css',
                r'/css/studio-export-[a-f0-9]{64}\.css', r'/index\.html', r'/studio-export\.html']
    for row, pattern in zip(rows, patterns):
        require(type(row) is dict and row.keys() == {'path', 'bytes', 'sha256'}
                and re.fullmatch(pattern, row['path']) and type(row['bytes']) is int
                and 0 < row['bytes'] <= (LIMIT if row['path'].startswith('/assets/') else 65536)
                and re.fullmatch('[a-f0-9]{64}', row['sha256']))
    return rows


def regular(path, maximum):
    require(path.resolve(strict=True) == path)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as reader:
        before = os.fstat(reader.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
                and 0 < before.st_size <= maximum)
        data = reader.read(maximum + 1)
        after = os.fstat(reader.fileno())
        require(len(data) == before.st_size == after.st_size and before.st_ctime_ns == after.st_ctime_ns)
        return data


def entries(directory, limit):
    require(directory.resolve(strict=True) == directory and directory.is_dir())
    with os.scandir(directory) as items:
        return {entry.name for entry in islice(items, limit + 1)}


def restore_chart(directory):
    source = (FIXTURE / CHART).read_bytes()
    rows = expected_rows((FIXTURE / 'native-inventory.json').read_bytes())
    require(sha(source) == rows[0]['sha256'] and len(source) == rows[0]['bytes'] and entries(directory, 0) == set())
    with (directory / CHART).open('xb') as dest:
        dest.write(source)


def archive(directory, original, output, mark):
    rows = expected_rows(original)
    mark('native_export_layout')
    require(entries(directory, 4) == {'assets', 'css', 'index.html', 'studio-export.html'}
            and entries(directory / 'assets', 1) == {CHART}
            and entries(directory / 'css', 2) == {Path(row['path']).name for row in rows[1:3]})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        for row, stage in zip(rows, ('native_chart', 'native_index_css', 'native_page_css', 'native_index_html', 'native_page_html')):
            mark(stage)
            name = row['path'][1:]
            data = regular(directory / name, row['bytes'])
            require(len(data) == row['bytes'] and sha(data) == row['sha256'])
            archive.writestr(zipfile.ZipInfo(name), data)
    raw = buffer.getvalue()
    require(len(raw) <= LIMIT)
    with os.fdopen(os.open(output, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY, 0o600), 'wb') as sink:
        sink.write(raw)
    return dict(asset_count=len(rows), archive_bytes=len(raw), archive_sha256=sha(raw))
