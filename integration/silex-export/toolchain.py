# SPDX-License-Identifier: GPL-3.0-only
"""Acquire the exact Node and pnpm tools in a caller-owned temporary directory."""
import base64
import hashlib
from pathlib import Path
import shutil
import tarfile
import urllib.request


def download(url, output, maximum):
    if not url.startswith(('https://nodejs.org/dist/', 'https://registry.npmjs.org/pnpm/-/')):
        raise ValueError('download origin')
    with urllib.request.urlopen(url, timeout=60) as response, output.open('xb') as target:
        if response.geturl() != url:
            raise ValueError('unexpected redirect')
        total = 0
        while data := response.read(65536):
            total += len(data)
            if total > maximum:
                raise ValueError('download bound')
            target.write(data)


def prepare(temporary, pins):
    node_archive = temporary / 'node.tar.xz'
    pin = pins['node']
    download(pin['url'], node_archive, pin['bytes'])
    if node_archive.stat().st_size != pin['bytes'] or hashlib.sha256(node_archive.read_bytes()).hexdigest() != pin['sha256']:
        raise ValueError('node archive integrity')
    node_root = temporary / 'node'
    node_root.mkdir(mode=0o700)
    with tarfile.open(node_archive, 'r:xz') as bundle:
        for name, expected in pin['files'].items():
            entry = bundle.getmember('node-v' + pin['version'] + '-linux-x64/' + name)
            if not entry.isfile() or entry.size != expected['bytes']:
                raise ValueError('node member')
            with bundle.extractfile(entry) as source:
                data = source.read(expected['bytes'] + 1)
            if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise ValueError('node member integrity')
            destination = node_root / Path(name).name
            destination.write_bytes(data)
            destination.chmod(0o700 if name == 'bin/node' else 0o600)
    pnpm_archive = temporary / 'pnpm.tgz'
    pin = pins['pnpm']
    download(pin['url'], pnpm_archive, pin['maximum_download_bytes'])
    actual = 'sha512-' + base64.b64encode(hashlib.sha512(pnpm_archive.read_bytes()).digest()).decode()
    if actual != pin['integrity']:
        raise ValueError('pnpm archive integrity')
    pnpm_root = temporary / 'pnpm'
    pnpm_root.mkdir(mode=0o700)
    with tarfile.open(pnpm_archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if len(members) > 4096 or sum(entry.size for entry in members) > 64 * 1024 * 1024:
            raise ValueError('pnpm extraction bound')
        for entry in members:
            parts = entry.name.rstrip('/').split('/')
            if (parts[0] != 'package' or any(part in ('', '.', '..') for part in parts)
                    or '\\' in entry.name or not (entry.isfile() or entry.isdir())):
                raise ValueError('pnpm archive member')
            output = pnpm_root.joinpath(*parts)
            if entry.isdir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(entry) as source, output.open('xb') as target:
                    shutil.copyfileobj(source, target, 65536)
    return node_root / 'node', pnpm_root / 'package/bin/pnpm.cjs'
