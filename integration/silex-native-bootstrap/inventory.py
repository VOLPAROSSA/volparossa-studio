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


def pinned_simulation():
    """Compare this runner's read-only APT plan with the exact reviewed installer."""
    import install_sdk

    records = install_sdk.records_from_manifest(Path(__file__).with_name('ubuntu-sdk.json').read_bytes())
    query = ['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\t${Status}\n', *records]
    installed = install_sdk.dpkg_rows(command(query, accepted=(0, 1)).encode(), records, complete=False)
    targets = [name + '=' + row['Version'] for name, row in records.items()]
    options = install_sdk.install_options(Path('/var/cache/apt/archives'))
    result = subprocess.run(['/usr/bin/apt-get', *options, '--simulate', 'install', *targets],
        env=install_sdk.ENV, capture_output=True, timeout=45, check=False)
    if len(result.stdout) + len(result.stderr) > 2 * 1024 * 1024:
        raise ValueError('bounded simulation output required')
    observation = dict(exit_code=result.returncode, input_count=len(records), installed_count=len(installed),
        stdout_sha256=hashlib.sha256(result.stdout).hexdigest(), unchanged_installer_accepted=False)
    if result.returncode != 0:
        output = result.stdout.decode('utf-8', errors='strict')
        error = result.stderr.decode('utf-8', errors='strict')
        markers = ('unmet dependencies', 'held broken packages', 'not installable',
            'not going to be installed', 'unable to fetch', 'essential packages',
            'could not open', 'permission denied', 'archives directory', 'no such file',
            'requested an impossible situation', 'no-download', 'packages need to be removed',
            'packages were downgraded', 'unable to locate', 'is not available',
            'cannot download', 'no installation candidate')
        combined = (output + '\n' + error).lower()
        observation['failure_markers'] = [marker for marker in markers if marker in combined]
        observation['stderr_sha256'] = hashlib.sha256(result.stderr).hexdigest()
        # apt-cache must authenticate the terminal public package name before it is recorded.
        dependencies = []
        for line in output.splitlines():
            match = re.fullmatch(r'\s*([a-z0-9+.-]+)(?::amd64)? : (Depends|PreDepends|Breaks|Conflicts): ([a-z0-9+.-]+)(?::amd64)?(?: |$).*', line)
            if match and len(dependencies) < 16:
                subject, relation, dependency = match.groups()
                for name in (subject, dependency):
                    if name not in records:
                        candidate = record(command(['/usr/bin/apt-cache', 'show', name]))
                        package(name, candidate['Version'])
                dependencies.append(dict(package=subject, relation=relation, dependency=dependency))
        observation['dependency_constraints'] = dependencies
        return observation
    try:
        planned = install_sdk.plan_rows(result.stdout, records, installed)
    except install_sdk.Rejected:
        # Report only typed observations about publicly authenticated package records.
        shapes, extra, seen_inst, seen_conf = [], set(), set(), set()
        for line in result.stdout.decode('utf-8', errors='strict').splitlines():
            match = re.match(r'^(Inst|Conf|Purg|Remv) ([a-z0-9+.-]+)(?::amd64)?(?: \[([^\]]+)\])? \((\S+) ', line)
            if match is None:
                continue
            operation, name, old, version = match.groups()
            # package() authenticates the public candidate before its name may leave the runner.
            if name not in records:
                package(name, version)
                extra.add(name)
            else:
                expected = records[name]
                tail = line.rpartition(')')[2]
                if (operation in ('Purg', 'Remv') or tail or version != expected['Version']
                        or old is not None and installed.get(name, (None,))[0] != old):
                    if len(shapes) < 8:
                        shapes.append(dict(operation=operation, package=name,
                            version_matches=version == expected['Version'],
                            old_matches=old is None or installed.get(name, (None,))[0] == old,
                            has_tail=bool(tail), tail_empty_brackets=tail.strip() == '[]',
                            tail_package_brackets=re.fullmatch(r' \[(?:[a-z0-9+.:_-]+ *)+\]', tail) is not None))
            if operation == 'Inst':
                seen_inst.add(name)
            elif operation == 'Conf':
                seen_conf.add(name)
        observation.update(first_unmatched_shapes=shapes, extra_packages=sorted(extra),
            missing_packages=[name for name, row in records.items() if name not in seen_inst
                and installed.get(name) != (row['Version'], row['Architecture'])],
            configured_set_matches=seen_conf == seen_inst)
    else:
        observation.update(unchanged_installer_accepted=True, planned_count=len(planned))
    return observation


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
        pinned_plan=pinned_simulation(),
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
