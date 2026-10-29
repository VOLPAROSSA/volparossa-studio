# SPDX-License-Identifier: GPL-3.0-only
"""Hosted metadata inventory only; never execute the inventoried runtime tools."""
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

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = ('dbus-daemon', 'util-linux', 'mount', 'iproute2', 'nftables',
             'xvfb', 'xauth', 'xdotool', 'bubblewrap')
TOOLS = {
    'dbus-daemon': ('dbus-daemon', ('/usr/bin/dbus-daemon', '/bin/dbus-daemon')),
    'unshare': ('util-linux', ('/usr/bin/unshare', '/bin/unshare')),
    'setpriv': ('util-linux', ('/usr/bin/setpriv', '/bin/setpriv')),
    'mount': ('mount', ('/usr/bin/mount', '/bin/mount')),
    'ip': ('iproute2', ('/usr/sbin/ip', '/sbin/ip', '/usr/bin/ip', '/bin/ip')),
    'nft': ('nftables', ('/usr/sbin/nft', '/sbin/nft')),
    'Xvfb': ('xvfb', ('/usr/bin/Xvfb',)),
    'xauth': ('xauth', ('/usr/bin/xauth',)),
    'xdotool': ('xdotool', ('/usr/bin/xdotool',)),
    'bwrap': ('bubblewrap', ('/usr/bin/bwrap', '/bin/bwrap')),
}
MAX_OUTPUT = 2 * 1024 * 1024
MAX_BINARY = 32 * 1024 * 1024
MAX_RECEIPT = 1024 * 1024
FIELDS = ('Package', 'Version', 'Architecture', 'Filename', 'Size', 'SHA256')
PHASES = frozenset(('admission', 'signed_metadata', 'packages', 'binaries', 'simulation', 'complete'))
EFFECTS = ('packages_installed', 'archives_downloaded', 'archive_contents_verified',
           'namespaces_created', 'network_configuration_changed', 'display_started',
           'inventoried_tools_executed', 'compiler_or_node_executed', 'application_executed',
           'native_runtime_acceptance', 'full_studio_acceptance')
INST_PATTERN = r'Inst ([a-z0-9][a-z0-9+.-]*)(?: \[[^\]\r\n]+\])? \(([0-9A-Za-z.+:~\-]+) [^\r\n]+\)'
# Observational markers only. A matched message never authorizes a retry or
# changes accepted exits. In particular, held_message is not proof of a hold.
REFUSAL_MARKERS = {
    'archive_fetch': (b'Unable to fetch some archives', b'Some files failed to download'),
    'no_download': (b'--no-download',),
    'unmet_dependencies': (b'unmet dependencies', b'Broken packages'),
    'held_message': (b'held broken packages', b'caused by held packages'),
    'permissions': (b'Permission denied', b'are you root?'),
    'lock': (b'Could not get lock ', b'Unable to acquire the dpkg frontend lock',
             b'Unable to lock directory '),
    'candidate': (b'has no installation candidate', b'Unable to locate package ',
                  b' was not found'),
    'internal_error': (b'Internal Error,', b'Internal error:'),
}


class Rejected(ValueError):
    pass


def require(value):
    if not value:
        raise Rejected('runtime prerequisite inventory rejected')


def identity(value):
    return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def read_file(path, maximum, owner=0):
    require(path.is_absolute() and path.resolve(strict=True) == path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner
                and not before.st_mode & 0o022 and 0 <= before.st_size <= maximum)
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        require(identity(before) == identity(after) and len(raw) == before.st_size
                and len(raw) <= maximum)
    return raw, before


def group_live(group):
    entries = []
    with os.scandir('/proc') as directory:
        for entry in directory:
            require(len(entries) < 4096)
            if entry.name.isdecimal():
                entries.append(Path(entry.path))
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            raw = (entry / 'stat').read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            continue
        require(len(raw) <= 4096 and b') ' in raw)
        fields = raw.rsplit(b') ', 1)[1].split()
        require(len(fields) >= 4)
        if int(fields[2]) == group and fields[0] not in (b'Z', b'X', b'x'):
            return True
    return False


class Commands:
    def __init__(self):
        self.deadline = time.monotonic() + 110
        self.started = 0
        self.joined = 0
        self.bytes = 0
        self.env = dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LC_ALL='C', LANG='C',
                        HOME='/nonexistent', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')

    def run(self, arguments, accepted=(0,), *, diagnostic=None):
        if diagnostic is not None:
            diagnostic.update(phase='actor', exit_class='unobserved', exit_code=0,
                              stdout_bytes=0, stderr_bytes=0, output_limit_exceeded=False,
                              cumulative_limit_exceeded=False, parser_failure='not_run')
        require(time.monotonic() < self.deadline and self.started < 384)
        require(arguments[0] in ('/usr/bin/git', '/usr/bin/dpkg', '/usr/bin/dpkg-query',
                                 '/usr/bin/apt-cache', '/usr/bin/apt-get'))
        self.started += 1
        child = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, env=self.env, cwd=ROOT,
                                 start_new_session=True)
        output = bytearray()
        error_output = bytearray() if diagnostic is not None else None
        total = 0
        primary = None
        status = None
        selector = None
        try:
            selector = selectors.DefaultSelector()
            for stream in (child.stdout, child.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            end = min(self.deadline, time.monotonic() + 12)
            while selector.get_map() or status is None:
                require(time.monotonic() < end)
                for key, _ in selector.select(min(0.05, max(0, end - time.monotonic()))):
                    chunk = os.read(key.fd, 16384)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    self.bytes += len(chunk)
                    if diagnostic is not None:
                        key_name = 'stdout_bytes' if key.fileobj is child.stdout else 'stderr_bytes'
                        diagnostic[key_name] = min(MAX_OUTPUT, diagnostic[key_name] + len(chunk))
                        diagnostic['output_limit_exceeded'] = total > MAX_OUTPUT
                        diagnostic['cumulative_limit_exceeded'] = self.bytes > 16 * MAX_OUTPUT
                    require(total <= MAX_OUTPUT and self.bytes <= 16 * MAX_OUTPUT)
                    if key.fileobj is child.stdout:
                        output.extend(chunk)
                    elif error_output is not None:
                        error_output.extend(chunk)
                # Observe, but do not reap: the directly owned PGID stays reserved.
                status = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if diagnostic is not None and status is not None:
                    diagnostic.update(exit_class='normal' if status.si_code == os.CLD_EXITED else
                        'signalled' if status.si_code in (os.CLD_KILLED, os.CLD_DUMPED) else 'other',
                        exit_code=max(0, min(255, status.si_status)))
            if diagnostic is not None:
                diagnostic.update(simulation_shape(bytes(output)))
                diagnostic.update(apt_refusal_shape(bytes(output), bytes(error_output)))
            require(status.si_code == os.CLD_EXITED and status.si_status in accepted)
        except BaseException as error:
            primary = error
        finally:
            numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
            previous = {s: signal.getsignal(s) for s in numbers}
            pending = set()
            joined = False
            install_mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
            try:
                for s in previous:
                    signal.signal(s, lambda number, _frame: pending.add(number))
            except BaseException as error:
                primary = primary or error
            finally:
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, install_mask)
                except BaseException as error:
                    primary = primary or error
            try:
                for sig, grace in ((signal.SIGTERM, 0.5), (signal.SIGKILL, 0.5)):
                    try:
                        os.killpg(child.pid, sig)
                    except ProcessLookupError:
                        pass
                    end = time.monotonic() + grace
                    while group_live(child.pid) and time.monotonic() < end:
                        time.sleep(0.01)
                require(not group_live(child.pid))
                child.wait(timeout=0.5)
                joined = True
            except BaseException as error:
                primary = primary or error
            finally:
                for stream in (child.stdout, child.stderr, selector):
                    try:
                        if stream is not None:
                            stream.close()
                    except BaseException as error:
                        primary = primary or error
                # Restoring a throwing cancellation handler must not interrupt
                # the other restores or erase the measured join. Block only
                # this handoff, then deliver any deferred cancellation as failure.
                old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
                restore_error = None
                try:
                    for s, handler in previous.items():
                        try:
                            signal.signal(s, handler)
                        except BaseException as error:
                            restore_error = restore_error or error
                    if joined:
                        self.joined += 1
                    pending.update(signal.sigpending().intersection(numbers))
                    if primary is None and pending:
                        primary = Rejected('runtime inventory deadline' if signal.SIGALRM in pending
                                           else 'runtime inventory cancelled')
                    primary = primary or restore_error
                finally:
                    try:
                        signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
                    except BaseException as error:
                        primary = primary or error
        if primary is not None:
            raise primary
        return status.si_status, bytes(output)


def installed_rows(raw):
    result = {}
    for line in raw.decode('utf-8', errors='strict').splitlines():
        fields = line.split('\t')
        require(len(fields) == 4)
        name, version, architecture, state = fields
        require(name in PROVIDERS and name not in result)
        require(state in ('install ok installed', 'unknown ok not-installed', 'deinstall ok config-files'))
        require(not version or re.fullmatch(r'[0-9A-Za-z.+:~\-]{1,160}', version))
        require(architecture in ('', 'amd64', 'all'))
        require(state != 'install ok installed' or (version and architecture))
        result[name] = dict(version=version or None, architecture=architecture or None,
                            state='installed' if state == 'install ok installed' else 'not_installed')
    return result


def candidate_version(raw):
    matches = re.findall(rb'^\s*Candidate:\s*(\S+)\s*$', raw, re.MULTILINE)
    require(len(matches) == 1)
    value = matches[0].decode('ascii', errors='strict')
    require(value == '(none)' or re.fullmatch(r'[0-9A-Za-z.+:~\-]{1,160}', value))
    return None if value == '(none)' else value


def archive_record(raw, name, version):
    found = None
    for paragraph in raw.decode('utf-8', errors='strict').strip().split('\n\n'):
        values = {}
        previous = None
        for line in paragraph.splitlines():
            if line.startswith((' ', '\t')):
                require(previous is not None)
                continue
            require(':' in line)
            key, value = line.split(':', 1)
            require(key not in values)
            values[key] = value.strip()
            previous = key
        require(all(k in values for k in FIELDS))
        row = {k: values[k] for k in FIELDS}
        require(row['Package'] == name and row['Version'] == version
                and row['Architecture'] in ('amd64', 'all')
                and re.fullmatch(r'pool/[A-Za-z0-9+._~:/\-]+\.deb', row['Filename'])
                and all(p not in ('', '.', '..') for p in row['Filename'].split('/'))
                and re.fullmatch(r'[0-9a-f]{64}', row['SHA256'])
                and re.fullmatch(r'[0-9]{1,10}', row['Size'])
                and 0 < int(row['Size']) <= 64 * 1024 * 1024)
        require(found is None or found == row)
        found = row
    require(found is not None)
    return found


def owner_matches(raw, provider, alias):
    lines = raw.decode('utf-8', errors='strict').splitlines()
    if not lines:
        return False
    require(len(lines) == 1 and ': ' in lines[0])
    owner, path = lines[0].split(': ', 1)
    return owner in (provider, provider + ':amd64') and path == alias


def binary_record(aliases):
    found = []
    for alias in aliases:
        path = Path(alias)
        if not path.exists():
            require(not path.is_symlink())
            continue
        require(path.lstat().st_uid == 0)
        target = path.resolve(strict=True)
        require(str(target) in aliases)
        found.append((alias, target))
    if not found:
        return None, []
    require(len({p for _, p in found}) == 1)
    path = found[0][1]
    raw, info = read_file(path, MAX_BINARY)
    require(info.st_mode & 0o111 and raw.startswith(b'\x7fELF'))
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                owner=info.st_uid, group=info.st_gid, mode=stat.S_IMODE(info.st_mode),
                links=info.st_nlink), [a for a, _ in found]


def apt_refusal_shape(stdout, stderr):
    """Closed projection of complete bounded streams, never their content."""
    require(type(stdout) is bytes and type(stderr) is bytes
            and len(stdout) + len(stderr) <= MAX_OUTPUT)
    result = dict(stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                  stderr_sha256=hashlib.sha256(stderr).hexdigest())
    families = set()
    for stream, raw in (('stdout', stdout), ('stderr', stderr)):
        lines = [line for line in raw.splitlines() if line.strip()]
        error_lines = [line for line in lines if line.startswith(b'E:')]
        matched_errors = 0
        for family, markers in REFUSAL_MARKERS.items():
            present = any(any(marker in line for marker in markers) for line in lines)
            result[stream + '_' + family] = present
            if present:
                families.add(family)
        for line in error_lines:
            if any(marker in line for markers in REFUSAL_MARKERS.values() for marker in markers):
                matched_errors += 1
        result.update({stream + '_error_lines': min(len(error_lines), 32),
            stream + '_error_lines_clipped': len(error_lines) > 32,
            stream + '_unknown_error_lines': min(len(error_lines) - matched_errors, 32)})
    result['refusal_family'] = ('none' if not families and not stdout.strip() and not stderr.strip()
        else 'unknown' if not families else next(iter(families)) if len(families) == 1 else 'multiple')
    result['refusal_family_count'] = len(families)
    return result


def simulation_shape(raw):
    """Finite public predicates only; no stdout line or package/version escapes."""
    try:
        text = raw.decode('utf-8', errors='strict')
        valid = True
    except UnicodeError:
        text = raw.decode('utf-8', errors='replace')
        valid = False
    lines = [line for line in text.splitlines() if line.strip()]
    installs = [line for line in lines if line.startswith('Inst ')]
    matches = sum(re.fullmatch(INST_PATTERN, line) is not None for line in installs)
    return dict(utf8_valid=valid, nonempty_lines=min(len(lines), 1024), lines_clipped=len(lines) > 1024,
        inst_lines=min(len(installs), 256), inst_lines_clipped=len(installs) > 256,
        inst_shape_matches=min(matches, 256), inst_shape_mismatches=min(len(installs) - matches, 256),
        conf_lines=min(sum(line.startswith('Conf ') for line in lines), 256),
        removal_lines=min(sum(line.startswith(('Remv ', 'Purg ')) for line in lines), 256),
        native_arch_qualified_inst=min(sum(re.match(r'^Inst [a-z0-9][a-z0-9+.-]*:amd64 ', line) is not None for line in installs), 256))


def simulation_failure(diagnostic, predicate, index=None, line=None):
    if diagnostic is None or diagnostic.get('parser_failure') not in (None, 'not_run'):
        return
    diagnostic['parser_failure'] = predicate
    if index is not None:
        diagnostic.update(failure_line=min(index, 1024), failure_line_clipped=index > 1024,
            failure_line_class='inst' if line.startswith('Inst ') else 'removal' if line.startswith(('Remv ', 'Purg ')) else 'other',
            failure_inst_native_arch=re.match(r'^Inst [a-z0-9][a-z0-9+.-]*:amd64 ', line) is not None,
            failure_has_version_parenthesis=' (' in line, failure_closing_parenthesis=line.endswith(')'))


def check_simulation_diagnostic(value):
    enums = {'phase': ('actor', 'parser', 'parsed', 'metadata', 'complete', 'unavailable'),
        'exit_class': ('unobserved', 'normal', 'signalled', 'other'),
        'refusal_family': ('none', 'unknown', 'multiple', *REFUSAL_MARKERS),
        'parser_failure': ('not_run', 'none', 'encoding', 'removal', 'inst_shape', 'duplicate', 'plan_bound', 'missing_membership'),
        'failure_line_class': ('inst', 'removal', 'other')}
    bounds = {'exit_code': 255, 'stdout_bytes': MAX_OUTPUT, 'stderr_bytes': MAX_OUTPUT,
        'nonempty_lines': 1024, 'inst_lines': 256, 'inst_shape_matches': 256,
        'inst_shape_mismatches': 256, 'conf_lines': 256, 'removal_lines': 256,
        'native_arch_qualified_inst': 256, 'failure_line': 1024, 'parsed_plan_count': 256,
        'requested_count': 9, 'requested_covered_count': 9}
    bounds.update(refusal_family_count=len(REFUSAL_MARKERS))
    for stream in ('stdout', 'stderr'):
        bounds.update({stream + '_error_lines': 32, stream + '_unknown_error_lines': 32})
    booleans = {'output_limit_exceeded', 'cumulative_limit_exceeded', 'utf8_valid', 'lines_clipped',
        'inst_lines_clipped', 'failure_line_clipped', 'failure_inst_native_arch',
        'failure_has_version_parenthesis', 'failure_closing_parenthesis'}
    for stream in ('stdout', 'stderr'):
        booleans.add(stream + '_error_lines_clipped')
        booleans.update(stream + '_' + family for family in REFUSAL_MARKERS)
    hashes = {'stdout_sha256', 'stderr_sha256'}
    require(type(value) is dict and value.keys() <= enums.keys() | bounds.keys() | booleans | hashes)
    for key, item in value.items():
        if key in enums:
            require(type(item) is str and item in enums[key])
        elif key in bounds:
            require(type(item) is int and 0 <= item <= bounds[key])
        elif key in hashes:
            require(type(item) is str and re.fullmatch('[0-9a-f]{64}', item))
        else:
            require(type(item) is bool)


def simulation_rows(raw, missing, *, diagnostic=None):
    if diagnostic is not None:
        diagnostic.update(phase='parser', **simulation_shape(raw))
    names = {}
    try:
        lines = raw.decode('utf-8', errors='strict').splitlines()
    except UnicodeError:
        simulation_failure(diagnostic, 'encoding')
        raise
    for index, line in enumerate(lines):
        if line.startswith(('Remv ', 'Purg ')):
            simulation_failure(diagnostic, 'removal', index, line)
        require(not line.startswith(('Remv ', 'Purg ')))
        if not line.startswith('Inst '):
            continue
        match = re.fullmatch(INST_PATTERN, line)
        if match is None:
            simulation_failure(diagnostic, 'inst_shape', index, line)
        elif match[1] in names:
            simulation_failure(diagnostic, 'duplicate', index, line)
        elif len(names) >= 256:
            simulation_failure(diagnostic, 'plan_bound', index, line)
        require(match is not None and match[1] not in names and len(names) < 256)
        names[match[1]] = match[2]
    if diagnostic is not None:
        diagnostic.update(parsed_plan_count=min(len(names), 256), requested_count=min(len(missing), 9),
                          requested_covered_count=min(len(set(missing).intersection(names)), 9))
    if not set(missing) <= names.keys():
        simulation_failure(diagnostic, 'missing_membership')
    require(set(missing) <= names.keys())
    if diagnostic is not None:
        diagnostic.update(phase='parsed', parser_failure='none')
    return names


def metadata(commands, name, version):
    code, raw = commands.run(['/usr/bin/apt-cache', 'show', name + '=' + version], accepted=(0, 100))
    if code != 0 or not raw.strip():
        return None
    # An installed dpkg status record may survive after its archive disappeared
    # from the current indices. That is not an archive metadata verification.
    if any(not re.search(rb'^' + field.encode() + rb':', raw, re.MULTILINE) for field in FIELDS):
        return None
    return archive_record(raw, name, version)


def admission(commands):
    revision = os.environ.get('GITHUB_SHA', '')
    require(os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and os.environ.get('RUNNER_OS') == 'Linux' and os.environ.get('RUNNER_ARCH') == 'X64'
            and os.environ.get('GITHUB_REPOSITORY') == 'VOLPAROSSA/volparossa-studio'
            and os.getuid() == os.geteuid() != 0 and re.fullmatch('[0-9a-f]{40}', revision)
            and os.environ.get('GITHUB_WORKFLOW_SHA') == revision)
    workspace = Path(os.environ['GITHUB_WORKSPACE'])
    require(workspace.is_absolute() and workspace.resolve(strict=True) == workspace
            and ROOT == workspace / 'studio' and ROOT.stat().st_uid == os.geteuid())
    require(commands.run(['/usr/bin/git', '-C', str(ROOT), 'rev-parse', 'HEAD'])[1].strip().decode() == revision)
    require(not commands.run(['/usr/bin/git', '-C', str(ROOT), 'status', '--porcelain', '--untracked-files=all'])[1])
    require(commands.run(['/usr/bin/dpkg', '--print-architecture'])[1] == b'amd64\n')
    release, _ = read_file(Path('/usr/lib/os-release'), 16384)
    fields = dict(line.split('=', 1) for line in release.decode().splitlines() if '=' in line)
    require(fields.get('ID') == 'ubuntu' and fields.get('VERSION_ID') == '"24.04"')
    temporary = Path(os.environ['RUNNER_TEMP'])
    require(temporary.is_absolute() and temporary.resolve(strict=True) == temporary
            and temporary.is_dir() and temporary.stat().st_uid == os.geteuid()
            and not temporary.stat().st_mode & 0o022)
    return revision, temporary / 'silex-native-runtime-inventory.json'


def collect(commands, report):
    report['stage'] = 'signed_metadata'
    paths = sorted(Path('/var/lib/apt/lists').glob('*_InRelease'))
    require(1 <= len(paths) <= 32)
    indices = []
    for path in paths:
        raw, _ = read_file(path, 1024 * 1024)
        require(raw.startswith(b'-----BEGIN PGP SIGNED MESSAGE-----\n')
                and b'-----BEGIN PGP SIGNATURE-----' in raw)
        indices.append(dict(name=path.name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)))
    report['signed_apt_indices'] = indices
    report['stage'] = 'packages'
    _, raw = commands.run(['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\t${Status}\n', *PROVIDERS], accepted=(0, 1))
    installed = installed_rows(raw)
    missing = []
    for name in PROVIDERS:
        state = installed.get(name, dict(version=None, architecture=None, state='unavailable'))
        _, policy = commands.run(['/usr/bin/apt-cache', 'policy', name])
        candidate = candidate_version(policy)
        row = dict(installed=state, installed_archive_metadata=None, candidate_archive_metadata=None,
                   policy_sha256=hashlib.sha256(policy).hexdigest(), archive_contents_verified=False)
        if state['state'] == 'installed':
            row['installed_archive_metadata'] = metadata(commands, name, state['version'])
            if (row['installed_archive_metadata'] is not None
                    and row['installed_archive_metadata']['Architecture'] != state['architecture']):
                row['installed_archive_metadata'] = None
        else:
            missing.append(name)
        if candidate is not None:
            row['candidate_archive_metadata'] = metadata(commands, name, candidate)
        report['packages'][name] = row
    report['missing_providers'] = missing
    report['stage'] = 'binaries'
    for name, (provider, aliases) in TOOLS.items():
        record, present = binary_record(aliases)
        owner_aliases = []
        if record is not None:
            for alias in present:
                _, raw = commands.run(['/usr/bin/dpkg-query', '-S', alias], accepted=(0, 1))
                if owner_matches(raw, provider, alias):
                    owner_aliases.append(alias)
        package = report['packages'][provider]
        verified = (record is not None and bool(owner_aliases)
                    and package['installed']['state'] == 'installed'
                    and package['installed_archive_metadata'] is not None
                    and package['candidate_archive_metadata'] is not None)
        report['tools'][name] = dict(provider=provider, binary=record, ownership_aliases=owner_aliases,
                                    installed_provenance_verified=verified)
    report['stage'] = 'simulation'
    if missing and all(report['packages'][n]['candidate_archive_metadata'] is not None for n in missing):
        targets = [n + '=' + report['packages'][n]['candidate_archive_metadata']['Version'] for n in missing]
        diagnostic = {}
        report['simulation_diagnostic'] = diagnostic
        _, raw = commands.run(['/usr/bin/apt-get', '--simulate', '--no-remove', '--no-download',
                               '--no-install-recommends', 'install', *targets], diagnostic=diagnostic)
        plan = simulation_rows(raw, missing, diagnostic=diagnostic)
        report['installation_plan_sha256'] = hashlib.sha256(raw).hexdigest()
        diagnostic['phase'] = 'metadata'
        for name, version in sorted(plan.items()):
            record = metadata(commands, name, version)
            require(record is not None)
            report['installation_plan'][name] = record
        report['simulation_performed'] = True
        diagnostic['phase'] = 'complete'
    report['readiness'] = 'ready' if all(r['installed_provenance_verified'] for r in report['tools'].values()) else 'not_ready'
    report.update(status='passed', stage='complete')


def main():
    require(len(sys.argv) == 1)
    commands = Commands()
    report = dict(schema=1, operation='native-runtime-prerequisite-inventory', status='failed',
                  stage='admission', studio_revision=None, system='ubuntu-24.04-amd64',
                  readiness='not_ready', packages={}, tools={}, missing_providers=[],
                  signed_apt_indices=[], apt_verification='workflow system signed apt-get update prerequisite',
                  candidate_archive_signatures_independently_verified=False,
                  installation_plan={}, installation_plan_sha256=None, simulation_performed=False,
                  owned_groups_started=0, owned_groups_joined=0, cleanup_confirmed=False,
                  **{name: False for name in EFFECTS})
    output = None
    primary = None
    try:
        report['studio_revision'], output = admission(commands)
        collect(commands, report)
    except BaseException as error:
        primary = error
        report.update(status='failed', readiness='not_ready')
    finally:
        report.update(owned_groups_started=commands.started, owned_groups_joined=commands.joined,
                      cleanup_confirmed=commands.started > 0 and commands.started == commands.joined)
        if not report['cleanup_confirmed']:
            report.update(status='failed', readiness='not_ready')
        if 'simulation_diagnostic' in report:
            try:
                check_simulation_diagnostic(report['simulation_diagnostic'])
            except BaseException as error:
                primary = primary or error
                report.update(status='failed', readiness='not_ready', simulation_diagnostic={'phase': 'unavailable'})
        raw = (json.dumps(report, sort_keys=True) + '\n').encode()
        require(len(raw) <= MAX_RECEIPT and report['stage'] in PHASES)
        if output is not None:
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                require(stream.write(raw) == len(raw))
                stream.flush()
        print(json.dumps(dict(schema=1, status=report['status'], stage=report['stage'],
                              readiness=report['readiness'], packages_installed=False,
                              native_runtime_acceptance=False), sort_keys=True))
    if primary is not None or report['status'] != 'passed':
        raise Rejected('runtime prerequisite inventory rejected') from None


if __name__ == '__main__':
    def cancelled(_number, _frame):
        raise Rejected('runtime prerequisite inventory interrupted')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(number, cancelled)
    signal.setitimer(signal.ITIMER_REAL, 120)
    try:
        main()
    except BaseException:
        raise SystemExit(1) from None
