#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline exact SDK installation on a disposable hosted runner; no native build.

The sole privileged entry is this fixed helper, not an installer API. Its root
process owns and drains every APT/dpkg group, even when the caller is cancelled.
No sibling module is imported by that privileged entry.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = 'c2e3e609b6dc9e204b65d173ac087be89c37e06f25e10c997dd1fd87831178a8'
POLICY = Path('/usr/sbin/policy-rc.d')
POLICY_BYTES = b'#!/bin/sh\nexit 101\n'
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
STABLE = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
ENV = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', XDG_CONFIG_HOME='/nonexistent', LANG='C',
           LC_ALL='C', DEBIAN_FRONTEND='noninteractive', SYSTEMD_OFFLINE='1')
# Installed SDK and code execution are distinct boundaries. This script runs
# signed-distribution package maintainers, never Silex/Rust/Node/WebKit itself.
FALSE_FLAGS = ('native_build', 'native_runtime_acceptance', 'native_gui_verified',
               'full_application_privacy', 'full_studio_acceptance', 'volparossa_updates_verified')


class Rejected(RuntimeError):
    pass


def require(value):
    if not value:
        raise Rejected('sdk_install_rejected')


def pairs(rows):
    value = {}
    for key, item in rows:
        require(key not in value)
        value[key] = item
    return value


def parse(raw):
    require(0 < len(raw) <= 1024 * 1024)
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _value: (_ for _ in ()).throw(Rejected('nonfinite')))


def write_json(path, value):
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    require(len(raw) <= 65536)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600), 'wb') as output:
        output.write(raw)


def canonical_directory(path, owners, *, mode=None, diagnostic=None):
    if diagnostic is not None:
        diagnostic.update(canonical=False, owner_allowed=False, mode_safe=False, ancestor_depth=0)
    canonical = path.is_absolute() and path.resolve(strict=True) == path
    if diagnostic is not None:
        diagnostic['canonical'] = canonical
    require(canonical)
    for depth, item in enumerate((path, *path.parents)):
        if diagnostic is not None:
            diagnostic.update(ancestor_depth=min(depth, 32), owner_allowed=False, mode_safe=False)
        info = item.lstat()
        owner_allowed = stat.S_ISDIR(info.st_mode) and info.st_uid in owners
        if diagnostic is not None:
            diagnostic['owner_allowed'] = owner_allowed
        require(owner_allowed)
        # The fixed /tmp and /var/tmp parents are allowed only with their sticky
        # root-owned directory semantics. The new cache itself is always 0700.
        mode_safe = bool(info.st_mode & 0o022 == 0 or
                         item in (Path('/tmp'), Path('/var/tmp')) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX)
        if diagnostic is not None:
            diagnostic['mode_safe'] = mode_safe
        require(mode_safe)
    if mode is not None:
        require(stat.S_IMODE(path.stat().st_mode) == mode)


def read_owned(path, owner, maximum, *, expected=None):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner and before.st_nlink == 1
                and not before.st_mode & 0o022 and 0 < before.st_size <= maximum)
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) == before.st_size and all(getattr(before, key) == getattr(after, key) for key in STABLE))
    if expected is not None:
        require(hashlib.sha256(raw).hexdigest() == expected)
    return raw


def records_from_manifest(raw):
    require(hashlib.sha256(raw).hexdigest() == MANIFEST)
    value = parse(raw)
    records = dict(value['requested'])
    for name, row in value['installation_plan'].items():
        require(name not in records or records[name] == row)
        records[name] = row
    require(len(records) == 182 and sum(int(row['Size']) for row in records.values()) == 63772228)
    return dict(sorted(records.items()))


def expected_hashes(records):
    return [dict(package=name, version=row['Version'], architecture=row['Architecture'],
                 bytes=int(row['Size']), sha256=row['SHA256']) for name, row in records.items()]


def check_fetch(value, records, revision):
    require(type(value) is dict and type(value.get('schema')) is int and value.get('schema') == 1 and value.get('status') == 'passed'
            and value.get('mode') == 'native-sdk-archives-fetch' and value.get('stage') == 'complete'
            and value.get('studio_revision') == revision and value.get('sdk_manifest_sha256') == MANIFEST
            and value.get('archives_verified') is True and value.get('archive_count') == 182
            and value.get('archive_bytes') == 63772228 and value.get('hashes') == expected_hashes(records)
            and value.get('cleanup') == dict(owned_groups_joined=True, owned_group_count=3,
                                            archives_retained=True, archive_tree_private=True))
    require(all(value.get(key) is False for key in (*FALSE_FLAGS, 'packages_installed', 'sdk_installed',
                                                   'archive_contents_executed', 'archive_contents_extracted')))


def row_failure(diagnostic, predicate, index, fields, records):
    if diagnostic is None or 'failure_predicate' in diagnostic:
        return
    valid = len(fields) == 4
    name, version, architecture, state = fields if valid else ('', '', '?', '?')
    diagnostic.update(failure_predicate=predicate, row_index=min(index, 182), row_index_clipped=index > 182,
        known_package=valid and name in records, arch_class=architecture if architecture in ('amd64', 'all') else
        'empty' if architecture == '' else 'other', version_empty=valid and version == '',
        state_class={'install ok installed': 'installed', 'unknown ok not-installed': 'not_installed',
                     'deinstall ok config-files': 'config_only'}.get(state, 'other'))


def dpkg_rows(raw, records, *, complete, diagnostic=None):
    if len(raw) > 1024 * 1024:
        row_failure(diagnostic, 'exact', 0, [], records)
    require(len(raw) <= 1024 * 1024)
    found = {}
    seen = set()
    for index, line in enumerate(raw.decode('utf-8', errors='strict').splitlines()):
        fields = line.split('\t')
        if len(fields) != 4:
            row_failure(diagnostic, 'columns', index, fields, records)
        require(len(fields) == 4)
        name, version, architecture, state = fields
        if name not in records:
            row_failure(diagnostic, 'name', index, fields, records)
        elif name in seen:
            row_failure(diagnostic, 'duplicate', index, fields, records)
        require(name in records and name not in seen)
        seen.add(name)
        # Actual baseline40815773094: dpkg reports a known but absent package
        # with BOTH fields empty. This grants no installed-version evidence.
        # Names/duplicates are rejected before this sole incomplete-mode case.
        if not complete and state == 'unknown ok not-installed' and version == '' and architecture == '':
            continue
        if architecture not in ('amd64', 'all'):
            row_failure(diagnostic, 'arch', index, fields, records)
        require(name in records and name not in found and architecture in ('amd64', 'all'))
        if state == 'install ok installed':
            found[name] = (version, architecture)
        else:
            if complete or state not in ('unknown ok not-installed', 'deinstall ok config-files'):
                row_failure(diagnostic, 'state', index, fields, records)
            require(not complete and state in ('unknown ok not-installed', 'deinstall ok config-files'))
    if complete:
        if set(found) != set(records):
            row_failure(diagnostic, 'exact', len(found), [], records)
        require(set(found) == set(records))
        if not all(found[name] == (row['Version'], row['Architecture']) for name, row in records.items()):
            row_failure(diagnostic, 'exact', len(found), [], records)
        require(all(found[name] == (row['Version'], row['Architecture']) for name, row in records.items()))
    return found


def plan_rows(raw, records, installed):
    require(0 < len(raw) <= 4 * 1024 * 1024)
    installs, configures = {}, {}
    text = raw.decode('utf-8', errors='strict')
    for line in text.splitlines():
        require(not line.startswith(('Remv ', 'Purg ')))
        if line.startswith('Inst '):
            match = re.fullmatch(r'Inst ([a-z0-9+.-]+)(?::amd64)?(?: \[([^\]]+)\])? \((\S+) .+\)', line)
            require(match is not None)
            name, old, version = match.groups()
            require(name in records and name not in installs and version == records[name]['Version'])
            require(old is None or name in installed and installed[name][0] == old)
            installs[name] = version
        elif line.startswith('Conf '):
            match = re.fullmatch(r'Conf ([a-z0-9+.-]+)(?::amd64)? \((\S+) .+\)', line)
            require(match is not None)
            name, version = match.groups()
            require(name in installs and name not in configures and version == installs[name])
            configures[name] = version
        else:
            require(not re.match(r'^(?:Inst|Conf|Remv|Purg)\b', line))
    require(installs == configures)
    require(all(name in installs or installed.get(name) == (row['Version'], row['Architecture'])
                for name, row in records.items()))
    return installs


def cache_name(name, row):
    # APT pkgAcqArchive QuoteString(..., "_:") encodes epoch colons in its cache
    # basename; upstream pool basenames are not the APT cache identity.
    version = row['Version'].replace(':', '%3a')
    return name + '_' + version + '_' + row['Architecture'] + '.deb'


def copy_archive(descriptor, destination, owner, by_hash):
    before = os.fstat(descriptor)
    require(stat.S_ISREG(before.st_mode) and before.st_uid == owner and before.st_nlink == 1
            and not before.st_mode & 0o022 and 0 < before.st_size <= MAX_FILE)
    # Hash and copy from the SAME open input descriptor, then bind both the
    # original metadata and the independent root-owned copy before any install.
    sha, count = hashlib.sha256(), 0
    with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400), 'wb') as output:
        while chunk := os.read(descriptor, 65536):
            count += len(chunk)
            require(count <= before.st_size and count <= MAX_FILE)
            sha.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    after = os.fstat(descriptor)
    require(all(getattr(before, key) == getattr(after, key) for key in STABLE) and count == before.st_size)
    digest = sha.hexdigest()
    require(digest in by_hash and int(by_hash[digest][1]['Size']) == count)
    require(hashlib.sha256(read_owned(destination, os.geteuid(), MAX_FILE)).hexdigest() == digest)
    return digest


def stage_archives(source, cache, records, owner):
    canonical_directory(source, {0, owner}, mode=0o700)
    require(source.stat().st_uid == owner)
    by_hash = {row['SHA256']: (name, row) for name, row in records.items()}
    require(len(by_hash) == len(records))
    seen, total = set(), 0
    directory = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        entries = os.listdir(directory)
        require(len(entries) == len(records))
        for index, filename in enumerate(sorted(entries)):
            require(re.fullmatch(r'[A-Za-z0-9._+~:%\-]+\.deb', filename) is not None)
            descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                 dir_fd=directory)
            temporary = cache / ('stage-' + str(index))
            try:
                digest = copy_archive(descriptor, temporary, owner, by_hash)
            finally:
                os.close(descriptor)
            require(digest not in seen)
            name, row = by_hash[digest]
            target = cache / cache_name(name, row)
            require(not target.exists() and not target.is_symlink())
            temporary.rename(target)
            seen.add(digest)
            total += int(row['Size'])
            require(total <= MAX_TOTAL)
        require(seen == set(by_hash))
        # Reject a directory replacement or added/removed input while staging.
        require((os.stat(source, follow_symlinks=False).st_dev, os.stat(source, follow_symlinks=False).st_ino)
                == (os.fstat(directory).st_dev, os.fstat(directory).st_ino)
                and sorted(os.listdir(directory)) == sorted(entries))
        os.fsync(directory)
    finally:
        os.close(directory)
    descriptor = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def live_group(group):
    count = 0
    for entry in Path('/proc').iterdir():
        count += 1
        require(count <= 65536)
        if not entry.name.isdecimal():
            continue
        try:
            raw = (entry / 'stat').read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            continue
        require(len(raw) <= 16384)
        fields = raw[raw.rfind(b') ') + 2:].split()
        if len(fields) >= 4 and fields[0] not in (b'Z', b'X', b'x') and int(fields[2]) == group and int(fields[3]) == group:
            return True
    return False


def root_actor(argv, end, cleanups, *, accepted=(0,), diagnostic=None):
    child = None
    primary = None
    raw = bytearray()
    code = None
    if diagnostic is not None:
        diagnostic.update(query_exit_class='unobserved', query_exit_code=0, stdout_bytes=0,
                          stderr_bytes=0, query_output_capped=False)
    try:
        require(time.monotonic() < end - 4)
        child = subprocess.Popen(argv, env=ENV, cwd='/', stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            for pipe in (child.stdout, child.stderr):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ)
            size = 0
            while selector.get_map():
                require(time.monotonic() < end - 4)
                for key, _events in selector.select(0.1):
                    chunk = os.read(key.fd, 16384)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        size += len(chunk)
                        if diagnostic is not None:
                            key_name = 'stdout_bytes' if key.fileobj is child.stdout else 'stderr_bytes'
                            diagnostic[key_name] = min(4 * 1024 * 1024, diagnostic[key_name] + len(chunk))
                            diagnostic['query_output_capped'] = size > 4 * 1024 * 1024
                        require(size <= 4 * 1024 * 1024)
                        if key.fileobj is child.stdout:
                            raw.extend(chunk)
            while True:
                require(time.monotonic() < end - 4)
                observed = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if observed is not None:
                    break
                time.sleep(0.01)
        if diagnostic is not None:
            diagnostic.update(query_exit_class='normal' if observed.si_code == os.CLD_EXITED else
                'signalled' if observed.si_code in (os.CLD_KILLED, os.CLD_DUMPED) else 'other',
                query_exit_code=max(0, min(255, observed.si_status)))
        require(observed.si_pid == child.pid and observed.si_code == os.CLD_EXITED)
        code = observed.si_status
        require(code in accepted)
    except BaseException as error:
        primary = error
    finally:
        joined = False
        if child is not None:
            numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
            saved = {number: signal.getsignal(number) for number in numbers}
            pending = set()
            for number in numbers:
                signal.signal(number, lambda number, _frame: pending.add(number))
            try:
                # Keep the direct leader UNREAPED until all group signals are
                # sent; no signalling after wait can target a recycled PGID.
                for sig, seconds in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
                    try:
                        os.killpg(child.pid, sig)
                    except ProcessLookupError:
                        pass
                    limit = min(end, time.monotonic() + seconds)
                    while live_group(child.pid) and time.monotonic() < limit:
                        time.sleep(0.01)
                    if not live_group(child.pid):
                        break
                child.wait(timeout=max(0.01, min(1, end - time.monotonic())))
                joined = not live_group(child.pid)
            except BaseException:
                joined = False
            finally:
                try:
                    for pipe in (child.stdout, child.stderr):
                        try:
                            pipe.close()
                        except BaseException:
                            joined = False
                finally:
                    for number, handler in saved.items():
                        try:
                            signal.signal(number, handler)
                        except BaseException:
                            joined = False
            if pending and primary is None:
                primary = Rejected('cancelled')
        cleanups.append(joined)
        if not joined and primary is None:
            primary = Rejected('root_group_cleanup_unconfirmed')
    if primary is not None:
        raise primary
    return bytes(raw), code


def policy_begin():
    # Existing policy is never replaced, accepted implicitly, or removed.
    descriptor = os.open(POLICY, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    info = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(POLICY_BYTES)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), 0o755)
            os.fsync(output.fileno())
    except BaseException:
        # The caller shields signals across creation/identity assignment. An I/O
        # failure still removes only the file this invocation actually created.
        try:
            current = POLICY.lstat()
            if (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino):
                POLICY.unlink()
        except BaseException:
            pass
        raise
    return info.st_dev, info.st_ino


def policy_end(identity, *, owner=0):
    info = POLICY.lstat()
    require((info.st_dev, info.st_ino) == identity
            and read_owned(POLICY, owner, 256) == POLICY_BYTES)
    POLICY.unlink()
    require(not POLICY.exists() and not POLICY.is_symlink())


def finish_policy(identity, cleanups):
    if identity is None:
        return not POLICY.exists() and not POLICY.is_symlink()
    if not cleanups or not all(cleanups):
        return False
    policy_end(identity)
    return True


def install_options(cache):
    return ['-o', 'APT::Get::AllowUnauthenticated=false', '-o', 'Acquire::AllowInsecureRepositories=false',
            '-o', 'Acquire::AllowDowngradeToInsecureRepositories=false',
            '-o', 'Acquire::http::AllowRedirect=false', '-o', 'Acquire::https::AllowRedirect=false',
            '-o', 'Acquire::http::Proxy=DIRECT', '-o', 'Acquire::https::Proxy=DIRECT',
            '-o', 'Dir::Etc::netrc=/dev/null', '-o', 'Dir::Etc::netrcparts=/nonexistent',
            '-o', 'Dir::Cache::archives=' + str(cache), '-o', 'APT::Get::AutomaticRemove=false',
            '-o', 'DPkg::Lock::Timeout=10', '--no-remove', '--no-download', '--no-install-recommends']


def install_plan(records, installed, invoke, cache):
    targets = [name + '=' + row['Version'] for name, row in records.items()]
    argv = ['/usr/bin/apt-get', *install_options(cache)]
    raw, _code = invoke([*argv, '--simulate', 'install', *targets])
    planned = plan_rows(raw, records, installed)
    # dpkg, rather than lexical version ordering, rejects every downgrade before
    # any policy/cache installation effects. No --allow-downgrades option exists.
    for name in sorted(planned):
        if name in installed:
            invoke(['/usr/bin/dpkg', '--compare-versions', installed[name][0], 'le', records[name]['Version']])
    return argv, targets, planned


ADMISSION_STAGES = ('python_identity', 'hosted_identity', 'source_identity_values', 'checkout_layout',
    'directory_runner', 'directory_studio', 'directory_helper', 'helper_owner', 'release_path',
    'release_file', 'release_identity', 'namespace_identity', 'network_read', 'network_state',
    'baseline_absence', 'manifest', 'complete')
IPV4_ROUTE_HEADER = (b'Iface', b'Destination', b'Gateway', b'Flags', b'RefCnt', b'Use',
                     b'Metric', b'Mask', b'MTU', b'Window', b'IRTT')


def admission_stage(report, stage):
    require(stage in ADMISSION_STAGES)
    report['admission_diagnostic'] = {'substage': stage}
    return report['admission_diagnostic']


def ipv4_routes_absent(raw):
    """Accept the observed empty new-netns file or one exact legacy header."""
    if type(raw) is not bytes or len(raw) > 16384:
        return False
    if raw == b'':
        return True
    lines = raw.splitlines()
    return len(lines) == 1 and tuple(lines[0].split()) == IPV4_ROUTE_HEADER


def ipv4_shape(raw):
    """Public shape ONLY; this diagnostic never grants route acceptance."""
    require(type(raw) is bytes)
    bytes_clipped = len(raw) > 16384
    nonempty = [line for line in raw[:16384].splitlines() if line.strip()]
    lines_clipped = len(nonempty) > 32
    header = IPV4_ROUTE_HEADER
    complete = not bytes_clipped and not lines_clipped
    return dict(ipv4_bytes=min(len(raw), 16384), ipv4_bytes_clipped=bytes_clipped,
                ipv4_line_count=min(len(nonempty), 32), ipv4_lines_clipped=lines_clipped,
                ipv4_header_only=complete and len(nonempty) == 1 and tuple(nonempty[0].split()) == header,
                ipv4_no_nonheader_entries=complete and all(tuple(line.split()) == header for line in nonempty))


def root_admission(report, privileged_argument):
    """The SAME read-only guards for installation and explicit admission proof."""
    admission_stage(report, 'python_identity')
    require(privileged_argument in ('--privileged-install', '--privileged-admission', '--privileged-baseline')
            and sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1 and os.getuid() == os.geteuid() == 0
            and sys.argv == [str(HERE / 'install_sdk.py'), privileged_argument])
    admission_stage(report, 'hosted_identity')
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and os.environ.get('RUNNER_OS') == 'Linux' and os.environ.get('RUNNER_ARCH') == 'X64'
            and os.environ.get('GITHUB_REPOSITORY') == 'VOLPAROSSA/volparossa-studio')
    admission_stage(report, 'source_identity_values')
    owner = os.environ.get('SILEX_SDK_OWNER', '')
    run, attempt = (os.environ.get(key, '') for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'))
    revision = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch(r'[1-9][0-9]{2,9}', owner) and int(owner) >= 1000
            and re.fullmatch(r'[1-9][0-9]{0,19}', run) and re.fullmatch(r'[1-9][0-9]{0,5}', attempt)
            and re.fullmatch('[0-9a-f]{40}', revision) and os.environ.get('GITHUB_WORKFLOW_SHA') == revision)
    owner = int(owner)
    temporary, workspace = (Path(os.environ.get(key, '')) for key in ('RUNNER_TEMP', 'GITHUB_WORKSPACE'))
    admission_stage(report, 'checkout_layout')
    require(ROOT == workspace / 'studio')
    for stage, path in (('directory_runner', temporary), ('directory_studio', ROOT), ('directory_helper', HERE)):
        canonical_directory(path, {0, owner}, diagnostic=admission_stage(report, stage))
    admission_stage(report, 'helper_owner')
    require(Path(__file__).resolve() == HERE / 'install_sdk.py'
            and (HERE / 'install_sdk.py').stat().st_uid == owner)
    admission_stage(report, 'release_path')
    release = Path('/etc/os-release').resolve(strict=True)
    require(str(release) in ('/etc/os-release', '/usr/lib/os-release'))
    admission_stage(report, 'release_file')
    os_release = read_owned(release, 0, 16384).decode('ascii')
    admission_stage(report, 'release_identity')
    require(re.search(r'^ID=ubuntu$', os_release, re.MULTILINE)
            and re.search(r'^VERSION_ID="24\.04"$', os_release, re.MULTILINE))
    admission_stage(report, 'namespace_identity')
    parent_net = os.environ.get('SILEX_SDK_PARENT_NETNS', '')
    require(re.fullmatch(r'net:\[[0-9]+\]', parent_net)
            and os.readlink('/proc/self/ns/net') != parent_net)
    admission_stage(report, 'network_read')
    # New unshare --net has only an inactive loopback and no routes; do not
    # modify any interface, route, resolver or firewall in either namespace.
    interfaces = Path('/proc/net/dev').read_bytes()
    routes4 = Path('/proc/net/route').read_bytes()
    routes6 = Path('/proc/net/ipv6_route').read_bytes()
    admission_stage(report, 'network_state')
    report['admission_diagnostic'].update(ipv4_shape(routes4))
    report['admission_diagnostic'].update(kernel_bytes_bounded=max(len(interfaces), len(routes4), len(routes6)) <= 16384,
        loopback_only={line.split(b':', 1)[0].strip() for line in interfaces.splitlines() if b':' in line} == {b'lo'},
        ipv4_routes_absent=ipv4_routes_absent(routes4),
        ipv6_routes_loopback_only=all(line.split()[-1] == b'lo' for line in routes6.splitlines()))
    require(max(len(interfaces), len(routes4), len(routes6)) <= 16384
            and {line.split(b':', 1)[0].strip() for line in interfaces.splitlines() if b':' in line} == {b'lo'}
            and ipv4_routes_absent(routes4)
            and all(line.split()[-1] == b'lo' for line in routes6.splitlines()))
    admission_stage(report, 'baseline_absence')
    require(not Path('/nonexistent').exists() and not POLICY.exists() and not POLICY.is_symlink())
    report.update(studio_revision=revision, run_id=run, run_attempt=attempt, network_namespace_isolated=True)
    admission_stage(report, 'manifest')
    records = records_from_manifest(read_owned(HERE / 'ubuntu-sdk.json', owner, 1024 * 1024))
    admission_stage(report, 'complete')
    return temporary, revision, owner, run, attempt, records


def root_main(*, admission_only=False, baseline_only=False):
    report = dict(schema=1, mode='native-sdk-offline-root-install', status='failed', stage='admission',
        sdk_manifest_sha256=MANIFEST, packages_installed=False, sdk_installed=False,
        network_namespace_isolated=False, root_archive_cache_verified=False,
        post_install_exact_versions=False, dpkg_audit_clean=False, installation_attempted=False, policy_created=False,
        policy_restored=False, root_cache_retained=False, owned_groups_joined=False,
        owned_group_count=0, **dict.fromkeys(FALSE_FLAGS, False))
    if admission_only:
        report.update(mode='native-sdk-root-admission', admission_passed=False)
    if baseline_only:
        report.update(mode='native-sdk-root-baseline', baseline_passed=False)
    cleanups, policy, cache, cache_created = [], None, None, False
    primary = None
    end = time.monotonic() + 240
    try:
        require(not (admission_only and baseline_only))
        temporary, revision, owner, run, attempt, records = root_admission(
            report, '--privileged-admission' if admission_only else '--privileged-baseline' if baseline_only else '--privileged-install')
        if admission_only:
            report['stage'] = 'admission_complete'
        elif baseline_only:
            report['stage'] = 'baseline_packages'
            diagnostic = {}
            report['baseline_diagnostic'] = diagnostic
            query = ['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\t${Status}\n', *records]
            raw, _code = root_actor(query, end, cleanups, accepted=(0, 1), diagnostic=diagnostic)
            installed = dpkg_rows(raw, records, complete=False, diagnostic=diagnostic)
            diagnostic['parsed_installed_count'] = len(installed)
            report['stage'] = 'baseline_complete'
        else:
            check_fetch(parse(read_owned(temporary / 'silex-native-sdk-fetch.json', owner, 65536)), records, revision)
            cache = Path('/var/tmp') / ('silex-native-sdk-' + run + '-' + attempt)
            canonical_directory(cache.parent, {0})
            cache.mkdir(mode=0o700)
            cache_created = True
            report['root_cache_retained'] = True
            report['stage'] = 'root_archive_staging'
            stage_archives(temporary / 'silex-native-sdk-archives', cache, records, owner)
            report['root_archive_cache_verified'] = True
            def invoke(argv, *, accepted=(0,)):
                return root_actor(argv, end, cleanups, accepted=accepted)
            report['stage'] = 'baseline_packages'
            query = ['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\t${Status}\n', *records]
            diagnostic = {}
            try:
                raw, _code = root_actor(query, end, cleanups, accepted=(0, 1), diagnostic=diagnostic)
                installed = dpkg_rows(raw, records, complete=False, diagnostic=diagnostic)
            except BaseException:
                report['baseline_diagnostic'] = diagnostic
                raise
            audit, _code = invoke(['/usr/bin/dpkg', '--audit'])
            require(not audit.strip())
            report['stage'] = 'simulation'
            argv, targets, planned = install_plan(records, installed, invoke, cache)
            report['planned_package_count'] = len(planned)
            report['plan_sha256'] = hashlib.sha256(json.dumps(planned, sort_keys=True).encode()).hexdigest()
            numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
            handlers = {number: signal.getsignal(number) for number in numbers}
            pending = set()
            for number in numbers:
                signal.signal(number, lambda number, _frame: pending.add(number))
            try:
                policy = policy_begin()
            finally:
                for number, handler in handlers.items():
                    signal.signal(number, handler)
            if pending:
                raise Rejected('cancelled')
            report.update(policy_created=True, stage='offline_install')
            # The private root cache cannot be changed by the original nonroot user.
            # All 182 exact versions remain explicit, even when already installed.
            report['installation_attempted'] = True
            invoke([*argv, '--yes', 'install', *targets])
            report.update(packages_installed=True, stage='post_install')
            raw, _code = invoke(query)
            dpkg_rows(raw, records, complete=True)
            report['post_install_exact_versions'] = True
            audit, _code = invoke(['/usr/bin/dpkg', '--audit'])
            require(not audit.strip())
            report.update(dpkg_audit_clean=True, verified_package_count=182, hashes=expected_hashes(records))
    except BaseException as error:
        primary = error
        report['failure_stage'] = report['stage']
    finally:
        numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
        handlers = {number: signal.getsignal(number) for number in numbers}
        pending = set()
        for number in numbers:
            signal.signal(number, lambda number, _frame: pending.add(number))
        try:
            joined = bool(cleanups) and all(cleanups)
            report.update(owned_groups_joined=joined, owned_group_count=len(cleanups))
            try:
                report['policy_restored'] = finish_policy(policy, cleanups)
            except BaseException as error:
                # A restoration failure remains visible without replacing the
                # original installation/cancellation failure or its stage.
                if primary is None:
                    report['failure_stage'] = 'policy_cleanup'
                primary = primary or error
            if pending and primary is None:
                primary = Rejected('cancelled')
            if admission_only:
                if primary is None and report['policy_restored'] is True and not cleanups and policy is None and not cache_created:
                    report.update(status='passed', stage='complete', admission_passed=True)
                else:
                    report.update(status='failed', admission_passed=False)
                    report.setdefault('failure_stage', 'cleanup')
            elif baseline_only:
                if primary is None and joined and report['policy_restored'] is True and policy is None and not cache_created:
                    report.update(status='passed', stage='complete', baseline_passed=True)
                else:
                    report.update(status='failed', baseline_passed=False)
                    report.setdefault('failure_stage', 'cleanup')
            elif primary is None and joined and report['policy_restored'] and report['post_install_exact_versions'] and report['dpkg_audit_clean']:
                report.update(status='passed', stage='complete', sdk_installed=True)
            elif primary is None:
                report['failure_stage'] = 'cleanup'
            raw = (json.dumps(report, sort_keys=True) + '\n').encode()
            require(len(raw) <= 65536)
            if cache_created:
                with os.fdopen(os.open(cache / 'result.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
            # Exit zero is the closed protocol transport only. The outer caller
            # requires status=passed and every postcondition, not this exit code.
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()
        finally:
            for number, handler in handlers.items():
                signal.signal(number, handler)
    return 1 if pending else 0


def check_root(value, revision, records):
    require(type(value) is dict and type(value.get('schema')) is int and value.get('schema') == 1
            and value.get('mode') == 'native-sdk-offline-root-install'
            and value.get('status') == 'passed' and value.get('stage') == 'complete'
            and value.get('studio_revision') == revision and value.get('sdk_manifest_sha256') == MANIFEST
            and all(value.get(key) is True for key in ('packages_installed', 'sdk_installed',
                'network_namespace_isolated', 'root_archive_cache_verified', 'post_install_exact_versions',
                'dpkg_audit_clean', 'installation_attempted', 'policy_created', 'policy_restored', 'root_cache_retained', 'owned_groups_joined'))
            and type(value.get('owned_group_count')) is int and 6 <= value['owned_group_count'] <= 188
            and type(value.get('verified_package_count')) is int and value.get('verified_package_count') == 182
            and value.get('hashes') == expected_hashes(records)
            and all(value.get(key) is False for key in FALSE_FLAGS))


def check_admission_diagnostic(value):
    require(type(value) is dict and value.keys() <= {'substage', 'canonical', 'owner_allowed', 'mode_safe',
        'ancestor_depth', 'kernel_bytes_bounded', 'loopback_only', 'ipv4_routes_absent', 'ipv6_routes_loopback_only',
        'ipv4_bytes', 'ipv4_bytes_clipped', 'ipv4_line_count', 'ipv4_lines_clipped',
        'ipv4_header_only', 'ipv4_no_nonheader_entries'}
        and value.get('substage') in ADMISSION_STAGES)
    for key, item in value.items():
        if key == 'ancestor_depth':
            require(type(item) is int and 0 <= item <= 32)
        elif key in ('ipv4_bytes', 'ipv4_line_count'):
            require(type(item) is int and 0 <= item <= (16384 if key == 'ipv4_bytes' else 32))
        elif key != 'substage':
            require(type(item) is bool)


def check_root_admission(value, revision):
    require(type(value) is dict and type(value.get('schema')) is int and value.get('schema') == 1
        and value.get('mode') == 'native-sdk-root-admission' and value.get('status') == 'passed'
        and value.get('stage') == 'complete' and value.get('studio_revision') == revision
        and value.get('sdk_manifest_sha256') == MANIFEST and value.get('admission_passed') is True
        and value.get('network_namespace_isolated') is True and value.get('policy_restored') is True
        and type(value.get('owned_group_count')) is int and value['owned_group_count'] == 0
        and all(value.get(key) is False for key in (*FALSE_FLAGS, 'packages_installed', 'sdk_installed',
            'root_archive_cache_verified', 'post_install_exact_versions', 'dpkg_audit_clean',
            'installation_attempted', 'policy_created', 'root_cache_retained', 'owned_groups_joined')))
    check_admission_diagnostic(value.get('admission_diagnostic'))
    require(value['admission_diagnostic'] == {'substage': 'complete'})


def check_baseline_diagnostic(value):
    require(type(value) is dict and value.keys() <= {'query_exit_class', 'query_exit_code', 'stdout_bytes',
        'stderr_bytes', 'query_output_capped', 'failure_predicate', 'row_index', 'row_index_clipped',
        'known_package', 'arch_class', 'version_empty', 'state_class', 'parsed_installed_count'})
    enums = {'query_exit_class': ('unobserved', 'normal', 'signalled', 'other'),
        'failure_predicate': ('columns', 'name', 'duplicate', 'arch', 'state', 'exact'),
        'arch_class': ('empty', 'amd64', 'all', 'other'),
        'state_class': ('installed', 'not_installed', 'config_only', 'other')}
    bounds = {'query_exit_code': 255, 'stdout_bytes': 4 * 1024 * 1024, 'stderr_bytes': 4 * 1024 * 1024,
              'row_index': 182, 'parsed_installed_count': 182}
    for key, item in value.items():
        if key in enums:
            require(type(item) is str and item in enums[key])
        elif key in bounds:
            require(type(item) is int and 0 <= item <= bounds[key])
        else:
            require(type(item) is bool)


def check_root_baseline(value, revision):
    require(type(value) is dict and type(value.get('schema')) is int and value.get('schema') == 1
        and value.get('mode') == 'native-sdk-root-baseline' and value.get('status') == 'passed'
        and value.get('stage') == 'complete' and value.get('studio_revision') == revision
        and value.get('sdk_manifest_sha256') == MANIFEST and value.get('baseline_passed') is True
        and value.get('network_namespace_isolated') is True and value.get('policy_restored') is True
        and type(value.get('owned_group_count')) is int and value['owned_group_count'] == 1
        and value.get('owned_groups_joined') is True
        and all(value.get(key) is False for key in (*FALSE_FLAGS, 'packages_installed', 'sdk_installed',
            'root_archive_cache_verified', 'post_install_exact_versions', 'dpkg_audit_clean',
            'installation_attempted', 'policy_created', 'root_cache_retained')))
    check_baseline_diagnostic(value.get('baseline_diagnostic'))
    diagnostic = value['baseline_diagnostic']
    require(diagnostic.get('query_exit_class') == 'normal' and diagnostic.get('query_exit_code') in (0, 1)
            and diagnostic.get('query_output_capped') is False and 'failure_predicate' not in diagnostic
            and type(diagnostic.get('parsed_installed_count')) is int)
    require(value.get('admission_diagnostic') == {'substage': 'complete'})


def drain_install_owner(drain_group, process, identity, *, grace=1.0, kill_grace=1.0):
    # The root owner must finish its independent APT group TERM/KILL/join and
    # restore policy before its own outer group can be force-killed. The outer
    # 265s work limit reserves 15+3+3s drain and receipt time under 300s. Generic
    # fetch/lifecycle timing stays unchanged. A missing closed root response is
    # never a successful nested cleanup acknowledgement.
    return drain_group(process, identity, grace=15.0, kill_grace=3.0)


def main(*, admission_only=False, baseline_only=False):
    # Only this unprivileged path imports previously reviewed sibling helpers.
    sys.path.insert(0, str(HERE))
    try:
        import fetch_sdk as fetch
    finally:
        sys.path.remove(str(HERE))
    report = dict(schema=1, mode='native-sdk-offline-install', status='failed', stage='admission',
                  sdk_manifest_sha256=MANIFEST, packages_installed=False, sdk_installed=False,
                  **dict.fromkeys(FALSE_FLAGS, False))
    if admission_only:
        report.update(mode='native-sdk-admission', admission_passed=False)
    if baseline_only:
        report.update(mode='native-sdk-baseline', baseline_passed=False)
    primary, artifact, root_artifact, root_value = None, None, None, None
    cleanups = []
    started = time.monotonic()
    try:
        require(not (admission_only and baseline_only))
        require(sys.argv == [str(HERE / 'install_sdk.py'),
                *(['--admission-only'] if admission_only else ['--baseline-only'] if baseline_only else [])])
        # Reuse the fetcher's exact source/host admission with only its fixed
        # entrypoint adapter after independently enforcing our own no-arg path.
        original = sys.argv
        try:
            sys.argv = [str(HERE / 'fetch_sdk.py')]
            temporary, revision = fetch.admission()
        finally:
            sys.argv = original
        run, attempt = (os.environ.get(key, '') for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'))
        require(re.fullmatch(r'[1-9][0-9]{0,19}', run) and re.fullmatch(r'[1-9][0-9]{0,5}', attempt))
        artifact = temporary / ('silex-native-sdk-admission.json' if admission_only else
                                'silex-native-sdk-baseline.json' if baseline_only else 'silex-native-sdk-install.json')
        root_artifact = temporary / ('silex-native-sdk-admission-root.json' if admission_only else
                                     'silex-native-sdk-baseline-root.json' if baseline_only else 'silex-native-sdk-install-root.json')
        require(all(not path.exists() and not path.is_symlink() for path in (artifact, root_artifact)))
        records = records_from_manifest(fetch.support.read(HERE / 'ubuntu-sdk.json', 1024 * 1024, expected=MANIFEST))
        if not admission_only and not baseline_only:
            check_fetch(parse(fetch.support.read(temporary / 'silex-native-sdk-fetch.json', 65536)), records, revision)
            require(fetch.verify_archives(temporary / 'silex-native-sdk-archives', records) == expected_hashes(records))
            require(not POLICY.exists() and not POLICY.is_symlink())
        environment = {key: os.environ[key] for key in ('GITHUB_ACTIONS', 'RUNNER_ENVIRONMENT', 'RUNNER_OS',
            'RUNNER_ARCH', 'GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_WORKFLOW_SHA', 'GITHUB_RUN_ID',
            'GITHUB_RUN_ATTEMPT', 'GITHUB_WORKSPACE', 'RUNNER_TEMP')}
        environment.update(ENV, SILEX_SDK_OWNER=str(os.geteuid()),
                           SILEX_SDK_PARENT_NETNS=os.readlink('/proc/self/ns/net'))
        argv = ['/usr/bin/sudo', '-n', '/usr/bin/unshare', '--net', '--', '/usr/bin/env', '-i',
                *[key + '=' + value for key, value in sorted(environment.items())],
                '/usr/bin/python3', '-I', '-B', str(HERE / 'install_sdk.py'),
                '--privileged-admission' if admission_only else '--privileged-baseline' if baseline_only else '--privileged-install']
        sys.path.insert(0, str(HERE.parent / 'silex-export'))
        try:
            from lifecycle import start_group, drain_group
        finally:
            sys.path.remove(str(HERE.parent / 'silex-export'))
        report.update(studio_revision=revision, stage='privileged_admission' if admission_only else
                      'privileged_baseline' if baseline_only else 'privileged_offline_install')
        def owner_drain(process, identity, **options):
            return drain_install_owner(drain_group, process, identity, **options)
        seconds = 60 if admission_only or baseline_only else 265
        raw = fetch.actor(argv, ENV, ROOT, start_group, owner_drain, started + seconds, seconds, cleanups)
        # Retain the actual bounded closed root response before validating its
        # success claim. It contains only package identities and cleanup flags.
        root_value = parse(raw)
        write_json(root_artifact, root_value)
        if type(root_value) is dict and 'admission_diagnostic' in root_value:
            check_admission_diagnostic(root_value['admission_diagnostic'])
            report['admission_diagnostic'] = root_value['admission_diagnostic']
        if type(root_value) is dict and 'baseline_diagnostic' in root_value:
            check_baseline_diagnostic(root_value['baseline_diagnostic'])
            report['baseline_diagnostic'] = root_value['baseline_diagnostic']
        if admission_only:
            check_root_admission(root_value, revision)
        elif baseline_only:
            check_root_baseline(root_value, revision)
        else:
            check_root(root_value, revision, records)
        require(root_value.get('run_id') == run and root_value.get('run_attempt') == attempt)
        require(not fetch.support.git('status', '--porcelain=v1', '-z', '--untracked-files=all'))
        require(len(cleanups) == 1 and all(cleanups))
        report.update(status='passed', stage='complete')
        if admission_only:
            report['admission_passed'] = True
        elif baseline_only:
            report['baseline_passed'] = True
        else:
            report.update(packages_installed=True, sdk_installed=True,
                          verified_package_count=182, archive_bytes=63772228, hashes=expected_hashes(records))
    except BaseException as error:
        primary = error
        report['failure_stage'] = report['stage']
    finally:
        root_joined = (type(root_value) is dict and root_value.get('owned_groups_joined') is True
                       and root_value.get('policy_restored') is True)
        if admission_only:
            root_joined = report.get('admission_passed') is True
        report['cleanup'] = dict(owned_groups_joined=len(cleanups) == 1 and all(cleanups) and root_joined,
                                 owned_group_count=len(cleanups),
                                 root_cache_retained=root_value.get('root_cache_retained') if type(root_value) is dict else None,
                                 package_rollback_attempted=False)
        if artifact is not None:
            try:
                write_json(artifact, report)
            except BaseException as error:
                primary = primary or error
    if primary is not None or report['status'] != 'passed':
        print('native SDK offline installation rejected', file=sys.stderr)
        return 1
    print('SILEX_NATIVE_SDK_ADMISSION=true; SDK_INSTALLED=false' if admission_only else
          'SILEX_NATIVE_SDK_BASELINE=true; SDK_INSTALLED=false' if baseline_only else
          'SILEX_NATIVE_SDK_INSTALLED=true; NATIVE_BUILD=false; NATIVE_RUNTIME=false')
    return 0


if __name__ == '__main__':
    def cancel(_number, _frame):
        raise Rejected('cancelled_or_deadline')
    for _number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(_number, cancel)
    _mode = sys.argv[1:]
    _seconds = 50 if _mode in (['--privileged-admission'], ['--privileged-baseline']) else 90 if _mode in (['--admission-only'], ['--baseline-only']) else 245 if _mode == ['--privileged-install'] else 300
    signal.setitimer(signal.ITIMER_REAL, _seconds)
    raise SystemExit(root_main(admission_only=_mode == ['--privileged-admission'], baseline_only=_mode == ['--privileged-baseline'])
                     if _mode in (['--privileged-install'], ['--privileged-admission'], ['--privileged-baseline'])
                     else main(admission_only=_mode == ['--admission-only'], baseline_only=_mode == ['--baseline-only']))
