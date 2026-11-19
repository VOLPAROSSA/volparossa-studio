# SPDX-License-Identifier: GPL-3.0-only
"""Approved hosted-runner package metadata only; no installation or native execution."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

PACKAGES = (
    'libgtk-3-dev', 'libwebkit2gtk-4.1-dev', 'libayatana-appindicator3-dev',
    'librsvg2-dev', 'libssl-dev', 'pkg-config', 'patchelf',
    'xvfb', 'xauth', 'dbus-x11', 'xdotool', 'at-spi2-core',
    'libatspi2.0-dev', 'libx11-dev', 'libxtst-dev', 'fonts-dejavu-core',
)
FIELDS = ('Package', 'Version', 'Architecture', 'Source', 'Filename', 'Size',
          'SHA256', 'Depends', 'Pre-Depends')


def command(arguments, accepted=(0,)):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=45, check=False)
    if len(result.stdout.encode()) + len(result.stderr.encode()) > 2 * 1024 * 1024:
        raise RuntimeError('bounded metadata command output required')
    if result.returncode not in accepted:
        raise RuntimeError('package metadata command failed')
    return result.stdout


def record(text):
    result = {}
    current = None
    for line in text.splitlines():
        if not line:
            break
        if line[:1].isspace() and current is not None:
            result[current] += ' ' + line.strip()
        elif ':' in line:
            current, value = line.split(':', 1)
            if current in result:
                raise ValueError('duplicate package metadata field')
            result[current] = value.strip()
    return {key: result[key] for key in FIELDS if key in result}


def package(name, version):
    if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::amd64)?', name):
        raise ValueError('fixed package name required')
    if not version or any(c.isspace() for c in version) or '=' in version:
        raise ValueError('exact package version required')
    value = record(command(['/usr/bin/apt-cache', 'show', name + '=' + version]))
    if (value.get('Package') != name.split(':')[0] or value.get('Version') != version
            or value.get('Architecture') not in ('amd64', 'all')
            or not re.fullmatch(r'[0-9a-f]{64}', value.get('SHA256', ''))):
        raise ValueError('exact archive metadata and digest required')
    return value


def main():
    root = Path(__file__).resolve().parents[2]
    workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve()
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('RUNNER_OS') != 'Linux'
            or os.environ.get('RUNNER_ARCH') != 'X64'
            or os.environ.get('GITHUB_REPOSITORY') != 'VOLPAROSSA/volparossa-studio'
            or os.geteuid() == 0 or root != workspace / 'studio'
            or os.environ.get('GITHUB_WORKFLOW_SHA') != os.environ['GITHUB_SHA']
            or command(['/usr/bin/git', '-C', str(root), 'rev-parse', 'HEAD']).strip() != os.environ['GITHUB_SHA']
            or command(['/usr/bin/dpkg', '--print-architecture']).strip() != 'amd64'):
        raise RuntimeError('exact-source approved hosted Ubuntu amd64 runner required')
    release = Path('/etc/os-release').read_text()
    if 'ID=ubuntu' not in release or 'VERSION_ID="24.04"' not in release:
        raise RuntimeError('Ubuntu 24.04 required')
    selected = {}
    unavailable = []
    for name in PACKAGES:
        policy = command(['/usr/bin/apt-cache', 'policy', name])
        match = re.search(r'^\s*Candidate:\s*(\S+)\s*$', policy, re.MULTILINE)
        if not match or match[1] == '(none)':
            unavailable.append(name)
            continue
        selected[name] = package(name, match[1])
    if unavailable:
        raise RuntimeError('required native SDK metadata unavailable')
    installed_text = command(['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\n', *PACKAGES], accepted=(0, 1))
    installed = dict(line.split('\t', 1) for line in installed_text.splitlines() if '\t' in line)
    targets = [name + '=' + selected[name]['Version'] for name in PACKAGES]
    plan = command(['/usr/bin/apt-get', '--simulate', '--no-remove', '--no-install-recommends', 'install', *targets])
    installs = {}
    for line in plan.splitlines():
        if not line.startswith('Inst '):
            continue
        match = re.match(r'^Inst (\S+)(?: \[[^\]]+\])? \((\S+) ', line)
        if not match:
            raise ValueError('closed package simulation record required')
        name, version = match.groups()
        if name in installs:
            raise ValueError('duplicate installation plan entry')
        installs[name] = package(name, version)
    indices = []
    for path in sorted(Path('/var/lib/apt/lists').glob('*_InRelease')):
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            raise ValueError('bounded signed apt metadata required')
        indices.append({'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if not indices:
        raise ValueError('signed apt index metadata required')
    receipt = dict(schema=1, status='passed', proof_mode='native-package-inventory',
        studio_revision=os.environ['GITHUB_SHA'], system='ubuntu-24.04-amd64',
        requested=selected, installed_targets=installed, installation_plan=installs,
        installation_plan_sha256=hashlib.sha256(plan.encode()).hexdigest(),
        signed_apt_indices=indices, apt_verification='system apt-get update',
        packages_installed=False, compiler_or_native_build=False,
        native_runtime_acceptance=False, full_studio_acceptance=False)
    output = Path(os.environ['RUNNER_TEMP']) / 'silex-native-inventory.json'
    data = json.dumps(receipt, sort_keys=True, indent=2) + '\n'
    if len(data.encode()) > 1024 * 1024:
        raise ValueError('bounded inventory receipt required')
    with output.open('x') as stream:
        stream.write(data)
    print(json.dumps(dict(status='passed', requested=len(selected), planned=len(installs),
                         packages_installed=False, native_runtime_acceptance=False), sort_keys=True))


if __name__ == '__main__':
    main()
