#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Fetch exact SDK archives on an approved runner; never install, extract or execute them."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# Explicit trusted sibling only, including when the caller uses Python -I.
sys.path.insert(0, str(HERE))
try:
    import check_bridge as support
finally:
    sys.path.remove(str(HERE))

MANIFEST_SHA256 = 'c2e3e609b6dc9e204b65d173ac087be89c37e06f25e10c997dd1fd87831178a8'
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
REQUIRED = {'Package', 'Version', 'Architecture', 'Filename', 'SHA256', 'Size'}
OPTIONAL = {'Source', 'Depends', 'Pre-Depends'}
REQUESTED = {'libgtk-3-dev', 'libwebkit2gtk-4.1-dev', 'libayatana-appindicator3-dev',
    'librsvg2-dev', 'libssl-dev', 'pkg-config', 'patchelf', 'xvfb', 'xauth', 'dbus-x11',
    'xdotool', 'at-spi2-core', 'libatspi2.0-dev', 'libx11-dev', 'libxtst-dev', 'fonts-dejavu-core'}
APT_OPTIONS = [
    '-o', 'APT::Get::AllowUnauthenticated=false',
    '-o', 'Acquire::AllowInsecureRepositories=false',
    '-o', 'Acquire::AllowDowngradeToInsecureRepositories=false',
    '-o', 'Dir::Etc::netrc=/dev/null', '-o', 'Dir::Etc::netrcparts=/nonexistent',
    '-o', 'Acquire::http::Proxy=DIRECT', '-o', 'Acquire::https::Proxy=DIRECT',
    '-o', 'Acquire::http::AllowRedirect=false', '-o', 'Acquire::https::AllowRedirect=false',
    '-o', 'Acquire::http::Timeout=20', '-o', 'Acquire::https::Timeout=20',
    '-o', 'Acquire::Retries=0',
]
# The verified inventory run observed this exact Ubuntu archive origin and the
# fixed system mirror-list descriptor. Unobserved fallback origins fail closed.
ARCHIVE_ORIGIN = 'http://azure.archive.ubuntu.com'
MIRRORS = Path('/etc/apt/apt-mirrors.txt')


def require(condition):
    support.require(condition, 'source_rejected')


def valid_record(name, row):
    require(type(name) is str and re.fullmatch(r'[a-z0-9][a-z0-9+.-]{1,127}', name) is not None)
    require(type(row) is dict and REQUIRED <= row.keys() <= REQUIRED | OPTIONAL)
    require(all(type(value) is str and 0 < len(value.encode()) <= 8192
                and all(char >= ' ' and char != '\x7f' for char in value) for value in row.values()))
    require(row['Package'] == name and row['Architecture'] in ('amd64', 'all'))
    require(re.fullmatch(r'[0-9][A-Za-z0-9.+:~\-]{0,255}', row['Version']) is not None)
    require(re.fullmatch(r'[0-9a-f]{64}', row['SHA256']) is not None)
    require(re.fullmatch(r'[1-9][0-9]{0,8}', row['Size']) is not None
            and int(row['Size']) <= MAX_ARCHIVE)
    filename = row['Filename']
    parts = filename.split('/')
    require(len(filename.encode()) <= 1024 and len(parts) >= 5 and parts[0] == 'pool'
            and parts[1] in ('main', 'universe', 'restricted', 'multiverse')
            and all(part not in ('', '.', '..') for part in parts)
            and re.fullmatch(r'[A-Za-z0-9._+~/\-]+\.deb', filename) is not None
            and not PurePosixPath(filename).is_absolute())


def collect_records(value):
    records = {}
    for key in ('requested', 'installation_plan'):
        require(type(value.get(key)) is dict and len(value[key]) <= 256)
        for name, row in value[key].items():
            valid_record(name, row)
            require(name not in records or records[name] == row)
            records[name] = row
    require(0 < len(records) <= 256 and sum(int(row['Size']) for row in records.values()) <= MAX_TOTAL)
    require(len({row['SHA256'] for row in records.values()}) == len(records))
    return dict(sorted(records.items()))


def validate_manifest(value):
    require(type(value) is dict and value.keys() == {'schema', 'system', 'apt_verification',
        'inventory_run', 'inventory_artifact', 'inventory_artifact_sha256', 'inventory_receipt_sha256',
        'requested', 'installation_plan', 'scope', 'signed_apt_indices'})
    require(type(value['schema']) is int and value['schema'] == 1
            and value['system'] == 'ubuntu-24.04-amd64' and value['apt_verification'] == 'system apt-get update')
    require(type(value['inventory_run']) is int and value['inventory_run'] == 40800390743
            and type(value['inventory_artifact']) is int and value['inventory_artifact'] == 12865891170)
    for key in ('inventory_artifact_sha256', 'inventory_receipt_sha256'):
        require(type(value[key]) is str and re.fullmatch('[0-9a-f]{64}', value[key]) is not None)
    scope = value['scope']
    require(type(scope) is dict and scope.keys() == {'metadata_verified', 'packages_installed',
        'native_build', 'native_runtime_acceptance', 'full_studio'}
        and scope['metadata_verified'] is True
        and all(scope[key] is False for key in scope if key != 'metadata_verified'))
    indices = value['signed_apt_indices']
    require(type(indices) is list and 1 <= len(indices) <= 16)
    names = set()
    for row in indices:
        require(type(row) is dict and row.keys() == {'name', 'sha256'}
                and type(row['name']) is str and re.fullmatch(r'[A-Za-z0-9_.+\-]{1,255}_InRelease', row['name']) is not None
                and row['name'] not in names and type(row['sha256']) is str
                and re.fullmatch('[0-9a-f]{64}', row['sha256']) is not None)
        names.add(row['name'])
    records = collect_records(value)
    require(set(value['requested']) == REQUESTED and len(value['installation_plan']) == 176
            and len(records) == 182 and sum(int(row['Size']) for row in records.values()) == 63772228)
    return records


def parse_metadata(raw, expected):
    require(0 < len(raw) <= 4 * 1024 * 1024)
    paragraphs = raw.decode('utf-8', errors='strict').strip().split('\n\n')
    found = set()
    require(len(paragraphs) <= 512)
    for paragraph in paragraphs:
        row = {}
        previous = None
        for line in paragraph.splitlines():
            if line.startswith((' ', '\t')):
                require(previous is not None)
                if previous in REQUIRED | OPTIONAL:
                    row[previous] += ' ' + line.strip()
                continue
            match = re.fullmatch(r'([A-Za-z][A-Za-z0-9-]*):\s*(.*)', line)
            require(match is not None)
            previous = match[1]
            if previous in REQUIRED | OPTIONAL:
                require(previous not in row)
                row[previous] = match[2]
        name = row.get('Package')
        require(name in expected)
        valid_record(name, row)
        require(row == expected[name])
        found.add(name)
    require(found == set(expected))


def public_mirror_list(raw):
    """Return only credential-free public Ubuntu mirror text eligible for diagnostics."""
    require(0 < len(raw) <= 4096)
    text = raw.decode('ascii', errors='strict')
    origins = []
    for line in text.splitlines():
        tokens = line.split()
        require(tokens and len(tokens) <= 4)
        uri = urlsplit(tokens[0])
        require(uri.scheme in ('http', 'https') and uri.hostname is not None
                and (uri.hostname == 'ubuntu.com' or uri.hostname.endswith('.ubuntu.com'))
                and uri.username is None and uri.password is None and uri.port is None
                and not uri.query and not uri.fragment and uri.path.rstrip('/') == '/ubuntu'
                and all(re.fullmatch(r'priority:[0-9]{1,3}', token) for token in tokens[1:]))
        origins.append(tokens[0].rstrip('/'))
    return text, all(origin == ARCHIVE_ORIGIN + '/ubuntu' for origin in origins)


def verify_uris(raw, records, mirror_raw=None):
    require(0 < len(raw) <= 256 * 1024)
    found = set()
    needs_mirrors = False
    for line in raw.decode('utf-8', errors='strict').splitlines():
        if not line.startswith("'"):
            continue
        match = re.fullmatch(r"'([^']+)' ([A-Za-z0-9._+~:%\-]+\.deb) ([0-9]+) (?:[A-Za-z0-9]+:)?[0-9a-fA-F]+", line)
        require(match is not None)
        uri = urlsplit(match[1])
        require(uri.username is None and uri.password is None and uri.port is None and not uri.query and not uri.fragment)
        decoded = unquote(uri.path, errors='strict')
        if uri.scheme == 'mirror+file':
            require(not uri.netloc and decoded.startswith(str(MIRRORS) + '/pool/'))
            filename = decoded[len(str(MIRRORS)) + 1:]
            needs_mirrors = True
        else:
            require(uri.scheme + '://' + uri.netloc == ARCHIVE_ORIGIN and decoded.startswith('/ubuntu/pool/'))
            filename = decoded[len('/ubuntu/'):]
        matches = [name for name, row in records.items() if row['Filename'] == filename and row['Size'] == match[3]]
        require(len(matches) == 1 and matches[0] not in found)
        found.add(matches[0])
    require(found == set(records))
    if needs_mirrors:
        require(mirror_raw is not None and public_mirror_list(mirror_raw)[1])


def system_read(path, maximum):
    require(path.is_absolute() and path.resolve(strict=True) == path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1
                and before.st_mode & 0o022 == 0 and before.st_size <= maximum)
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    keys = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    require(len(raw) == before.st_size and len(raw) <= maximum
            and all(getattr(before, key) == getattr(after, key) for key in keys))
    return raw


def verify_archives(directory, records):
    support.directory(directory)
    require(stat.S_IMODE(directory.lstat().st_mode) == 0o700)
    entries = []
    for path in directory.iterdir():
        require(len(entries) < len(records))
        entries.append(path)
    require(len(entries) == len(records))
    by_sha = {row['SHA256']: (name, row) for name, row in records.items()}
    seen = {}
    for path in entries:
        require(re.fullmatch(r'[A-Za-z0-9._+~:%\-]+\.deb', path.name) is not None)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC), 'rb') as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and before.st_nlink == 1
                    and before.st_mode & 0o022 == 0 and 0 < before.st_size <= MAX_ARCHIVE)
            sha = hashlib.sha256()
            count = 0
            while chunk := stream.read(65536):
                count += len(chunk)
                require(count <= before.st_size and count <= MAX_ARCHIVE)
                sha.update(chunk)
            after = os.fstat(stream.fileno())
        require(count == before.st_size and all(getattr(before, key) == getattr(after, key)
            for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')))
        digest = sha.hexdigest()
        require(digest in by_sha and digest not in seen and count == int(by_sha[digest][1]['Size']))
        seen[digest] = dict(package=by_sha[digest][0], version=by_sha[digest][1]['Version'],
                            architecture=by_sha[digest][1]['Architecture'], bytes=count, sha256=digest)
    require(set(seen) == set(by_sha) and sum(row['bytes'] for row in seen.values()) <= MAX_TOTAL)
    return sorted(seen.values(), key=lambda row: row['package'])


def admission():
    require(sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1
            and len(sys.argv) == 1 and Path(sys.argv[0]) == HERE / 'fetch_sdk.py')
    require(os.getuid() == os.geteuid() != 0 and sys.platform == 'linux' and os.uname().machine == 'x86_64')
    for key, value in {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted', 'RUNNER_OS': 'Linux',
        'RUNNER_ARCH': 'X64', 'GITHUB_REPOSITORY': 'VOLPAROSSA/volparossa-studio'}.items():
        require(os.environ.get(key) == value)
    workspace, temporary = (Path(os.environ.get(key, '')) for key in ('GITHUB_WORKSPACE', 'RUNNER_TEMP'))
    for path in (ROOT, HERE, workspace, temporary):
        support.directory(path)
    revision = os.environ.get('GITHUB_SHA', '')
    require(ROOT == workspace / 'studio' and re.fullmatch('[0-9a-f]{40}', revision) is not None
            and os.environ.get('GITHUB_WORKFLOW_SHA') == revision
            and support.git('rev-parse', 'HEAD').decode().strip() == revision
            and support.git('rev-parse', '--show-toplevel').decode().strip() == str(ROOT)
            and not support.git('status', '--porcelain=v1', '-z', '--untracked-files=all')
            and all(row.startswith(b'H ') for row in support.git('ls-files', '-v', '-z').split(b'\0') if row))
    release = Path('/etc/os-release').resolve(strict=True)
    require(str(release) in ('/etc/os-release', '/usr/lib/os-release'))
    data = system_read(release, 16384).decode('ascii')
    require(re.search(r'^ID=ubuntu$', data, re.MULTILINE) is not None
            and re.search(r'^VERSION_ID="24\.04"$', data, re.MULTILINE) is not None)
    return temporary, revision


def fetch(records, invoke, archives, mirror_note=None):
    specs = [name + '=' + row['Version'] for name, row in records.items()]
    # All exact metadata and URI checks finish before mkdir/download effects.
    parse_metadata(invoke(['/usr/bin/apt-cache', '--no-all-versions', 'show', *specs], 45), records)
    uris = invoke(['/usr/bin/apt-get', *APT_OPTIONS, '--print-uris', 'download', *specs], 30)
    mirror_raw = system_read(MIRRORS, 4096) if b'mirror+file:' in uris else None
    if mirror_raw is not None:
        # Only this tightly parsed credential-free Ubuntu text may be retained
        # as a PUBLIC diagnostic when an unobserved fallback makes us refuse.
        public_text, _approved = public_mirror_list(mirror_raw)
        if mirror_note is not None:
            mirror_note(public_text)
    verify_uris(uris, records, mirror_raw)
    archives.mkdir(mode=0o700)
    invoke(['/usr/bin/apt-get', *APT_OPTIONS, 'download', *specs], 240, cwd=archives)
    return verify_archives(archives, records)


def archive_progress(directory):
    count = total = 0
    for entry in os.scandir(directory):
        count += 1
        require(count <= 256)
        try:
            metadata = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue  # APT may atomically rename its own incomplete file.
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.geteuid()
                and metadata.st_nlink == 1 and 0 <= metadata.st_size <= MAX_ARCHIVE)
        total += metadata.st_size
        require(total <= MAX_TOTAL)


def actor(command, environment, cwd, start_group, drain_group, end, seconds, cleanups, *, download=False):
    """One owned metadata/download group, with an unreaped leader until drain."""
    child = identity = None
    primary = None
    raw = bytearray()
    try:
        options = {}
        if download:
            # Only this single-threaded runner's fixed APT child receives the
            # file limit; its transport workers inherit it. The parent is unchanged.
            options['preexec_fn'] = lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_ARCHIVE, MAX_ARCHIVE))
        child, identity = start_group(command, env=environment, cwd=cwd,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **options)
        deadline = min(end, time.monotonic() + seconds)
        with selectors.DefaultSelector() as selector:
            os.set_blocking(child.stdout.fileno(), False)
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                support.require(time.monotonic() < deadline, 'deadline')
                if download:
                    archive_progress(cwd)
                for key, _events in selector.select(min(0.25, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fd, 16384)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        support.require(len(raw) + len(chunk) <= 4 * 1024 * 1024, 'output_limit')
                        raw.extend(chunk)
            while True:
                support.require(time.monotonic() < deadline, 'deadline')
                if download:
                    archive_progress(cwd)
                observed = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if observed is not None:
                    break
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        support.require(observed.si_pid == child.pid and observed.si_code == os.CLD_EXITED
                        and observed.si_status == 0, 'child_failed')
    except BaseException as error:
        primary = error
    finally:
        joined = False
        if child is not None:
            numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
            handlers = {number: signal.getsignal(number) for number in numbers}
            pending = set()
            for number in numbers:
                signal.signal(number, lambda number, _frame: pending.add(number))
            try:
                result = drain_group(child, identity, grace=1.0, kill_grace=1.0)
                joined = result['leader_joined'] is True and result['live_group_drained'] is True
            except BaseException:
                joined = False
            finally:
                try:
                    child.stdout.close()
                except Exception:
                    joined = False
                for number, handler in handlers.items():
                    signal.signal(number, handler)
            if pending and primary is None:
                primary = support.Rejected('deadline' if signal.SIGALRM in pending else 'cancelled')
        cleanups.append(joined)
        if not joined and primary is None:
            primary = support.Rejected('cleanup_failed')
    if primary is not None:
        raise primary
    return bytes(raw)


def finish(report, cleanups, archives, receipt):
    retained = archives is not None and archives.exists()
    private = False
    if retained:
        metadata = archives.lstat()
        private = stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.geteuid() and stat.S_IMODE(metadata.st_mode) == 0o700
    report['cleanup'] = dict(owned_groups_joined=bool(cleanups) and all(cleanups),
        owned_group_count=len(cleanups), archives_retained=retained, archive_tree_private=private)
    if report['status'] == 'passed' and (len(cleanups) != 3 or not all(cleanups) or not private):
        report.update(status='failed', archives_verified=False)
        report['failure'] = dict(stage='cleanup', kind='cleanup_failed')
    if receipt is not None:
        # This independent finite receipt includes 182 archive identity rows.
        raw = (json.dumps(report, sort_keys=True) + '\n').encode()
        require(len(raw) <= 65536)
        with os.fdopen(os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600), 'wb') as stream:
            stream.write(raw)


def main():
    started = time.monotonic()
    report = dict(schema=1, mode='native-sdk-archives-fetch', status='failed', stage='admission',
        sdk_manifest_sha256=MANIFEST_SHA256, archives_verified=False, packages_installed=False,
        sdk_installed=False, native_build=False, native_runtime_acceptance=False,
        native_gui_verified=False, full_application_privacy=False, full_studio_acceptance=False,
        volparossa_updates_verified=False, archive_contents_executed=False, archive_contents_extracted=False)
    receipt = archives = None
    cleanups = []
    primary = None
    def cancel(number, _frame):
        raise support.Rejected('deadline' if number == signal.SIGALRM else 'cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(number, cancel)
    signal.setitimer(signal.ITIMER_REAL, 300)
    try:
        temporary, revision = admission()
        receipt = temporary / 'silex-native-sdk-fetch.json'
        require(not receipt.exists() and not receipt.is_symlink())
        archives = temporary / 'silex-native-sdk-archives'
        require(not archives.exists() and not archives.is_symlink())
        value = support.parse_json(support.read(HERE / 'ubuntu-sdk.json', 1024 * 1024, expected=MANIFEST_SHA256))
        records = validate_manifest(value)
        report.update(studio_revision=revision, inventory_run=value['inventory_run'],
            inventory_artifact=value['inventory_artifact'], pinned_index_provenance=value['signed_apt_indices'],
            pinned_indices_are_current_assertion=False, expected_archives=len(records), expected_bytes=63772228)
        environment = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', XDG_CONFIG_HOME='/nonexistent',
            LANG='C', LC_ALL='C', DEBIAN_FRONTEND='noninteractive')
        require(not Path('/nonexistent').exists())
        sys.path.insert(0, str(HERE.parent / 'silex-export'))
        try:
            from lifecycle import start_group, drain_group
        finally:
            sys.path.remove(str(HERE.parent / 'silex-export'))
        def invoke(command, seconds, *, cwd=None):
            report['stage'] = 'apt_download' if cwd is not None else 'apt_metadata'
            return actor(command, environment, cwd or ROOT, start_group, drain_group,
                started + 300, seconds, cleanups, download=cwd is not None)
        report['hashes'] = fetch(records, invoke, archives,
            mirror_note=lambda public_text: report.update(public_mirror_list=public_text))
        require(not support.git('status', '--porcelain=v1', '-z', '--untracked-files=all'))
        report.update(status='passed', stage='complete', archives_verified=True,
                      archive_count=len(report['hashes']), archive_bytes=sum(row['bytes'] for row in report['hashes']))
    except BaseException as error:
        primary = error
        report['failure'] = dict(stage=report['stage'], kind=error.kind if isinstance(error, support.Rejected) else 'child_failed')
    finally:
        try:
            signal.setitimer(signal.ITIMER_REAL, max(0.01, started + 305 - time.monotonic()))
            finish(report, cleanups, archives, receipt)
        except BaseException:
            # Retain every archive, including partial state after a failed join.
            # An evidence-write/cleanup error cannot replace the primary failure.
            if primary is None:
                primary = support.Rejected('cleanup_failed')
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    if primary is not None or report['status'] != 'passed':
        print('native SDK archive fetch rejected', file=sys.stderr)
        return 1
    print('SILEX_NATIVE_SDK_ARCHIVES_VERIFIED=true; SDK_INSTALLED=false')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
