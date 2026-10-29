#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Hosted actual Rust-library HTTP + original dashboard DOM CRUD proof."""
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import signal
import stat
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOOTSTRAP = HERE.parent / 'silex-native-bootstrap'
FS = HERE.parent / 'silex-fs-identifier-rename'
EXAMPLE = 'server-rust/examples/volparossa_dashboard_crud.rs'
WRAPPER_SECONDS = 140  # The unchanged wrapper owns 120s work + 5s forced cleanup.
PINS = {
    BOOTSTRAP / 'native_build.py': '9d8d45fe88922ced9ee43a0465177343f7b3757f6e9a28dc30884b0e3a03f51c',
    HERE / 'local_build.py': '45e7ae0a59f6f3102931faef8b560ed86c62231bb880eed994c56413e1e4589c',
    HERE / 'check.py': '42fbd5e85d74681634c7316197202dbe71372bc6b862dca38f604c6a487f1c26',
    FS / 'proof.py': '142facde5d2d30a62db546b2ea9078f97c5dae20b4857ca31263b21ee317eed7',
    FS / 'manifest.json': 'ca7f1b9b04fb7e5be36c4ed44511ae5950185df4e4572918c7a0530302e96edc',
    FS / 'prepare.py': 'd2f1cd0d964f4d89d932ab4d26201cc9d8eae0a97408087d1f102b9331bb4f3e',
}
FALSE_FLAGS = ('native_application_executed', 'native_webview_verified', 'native_gui_verified',
    'native_runtime_acceptance', 'full_application_privacy', 'no_external_attempts_proven',
    'native_signing_consent_proven', 'publication_authorized', 'full_studio_acceptance',
    'mount_isolation_proven', 'ipc_isolation_proven', 'proc_mount_isolation_proven',
    'sdk_installed', 'browser_downloaded', 'production_server_cli_proven')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def require(value):
    if not value:
        raise RuntimeError('public CRUD proof rejected')


def build_command(prefix):
    return [prefix / 'bin/cargo', 'build', '--offline', '--locked', '-p', 'silex-server',
            '--example', 'volparossa_dashboard_crud']


def wrapper_command(core, work):
    return [core / 'scripts/run-isolated-test.sh', '--studio-nonroot-command', '/usr/bin/python3',
        'studio_export', 'VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS', 'loopback', '-B', work / 'fixture/runtime.py']


def run_wrapper(native, core, work, env, deadline, groups, lifecycle):
    return native.actor(wrapper_command(core, work), env, ROOT, deadline, groups, lifecycle,
                        log=work / 'logs/namespace.log', seconds=WRAPPER_SECONDS)


def source_unchanged(native, source, before, extras, env, deadline, groups, lifecycle):
    require(native.tracked(source, extras, env, deadline, groups, lifecycle) == before)
    raw = native.git(['-C', str(source), 'ls-files', '--others', '-z'], source, env, deadline, groups, lifecycle)
    require({name.decode('utf-8', errors='strict') for name in raw.split(b'\0') if name} == set(extras))
    require(not native.git(['-C', str(source), 'diff', '--cached', '--name-only', '-z', 'HEAD', '--'],
                           source, env, deadline, groups, lifecycle))


def copy_binary(p, native, source, target, observation=None):
    expected = native.inspect_elf(source)
    if observation is not None:
        observation.update(expected)
    require(expected['bytes'] <= 256 * 1024 * 1024)
    def copy(old):
        before = os.fstat(old)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
                and before.st_size == expected['bytes'])
        def write(new):
            os.fchmod(new, 0o700)
            total = 0
            digest = hashlib.sha256()
            while chunk := os.read(old, 65536):
                total += len(chunk)
                require(total <= expected['bytes'])
                digest.update(chunk)
                offset = 0
                while offset < len(chunk):
                    written = os.write(new, chunk[offset:]); require(written > 0); offset += written
            os.fsync(new)
            require(total == expected['bytes'] and digest.hexdigest() == expected['sha256'])
        p.with_fd(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o700, write)
        after = os.fstat(old)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                )
    p.with_fd(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, copy)
    return expected


def check_runtime(p, value, revision):
    keys = {'schema', 'status', 'stage', 'runtime_revision', 'isolated_net', 'isolated_pid',
        'original_nonroot_uid', 'capabilities_zero', 'no_new_privileges', 'mount_isolation_proven',
        'ipc_isolation_proven', 'proc_mount_isolation_proven', 'denied_egress_containment',
        'no_external_attempts_proven', 'server_runs', 'browser_runs', 'browser_receipts',
        'http_denials', 'outside_unchanged', 'persistence', 'owned_groups_started',
        'owned_groups_joined', 'descendants_gone', 'listeners_closed', 'assets_unchanged', 'public_fixture_only',
        'first_failure', 'log_observations'}
    require(type(value) is dict and value.keys() == keys
        and type(value['schema']) is int and value['schema'] == 1
        and value['status'] == 'passed' and value['stage'] == 'complete'
        and value['runtime_revision'] == revision and value['first_failure'] is None)
    for name, count in (('server_runs', 2), ('browser_runs', 2), ('http_denials', 42), ('owned_groups_started', 4)):
        require(type(value[name]) is int and value[name] == count)
    require(all(value[key] is True for key in ('isolated_net', 'isolated_pid', 'original_nonroot_uid',
        'capabilities_zero', 'no_new_privileges', 'denied_egress_containment', 'outside_unchanged',
        'persistence', 'owned_groups_joined', 'descendants_gone', 'listeners_closed', 'assets_unchanged', 'public_fixture_only')))
    require(all(value[key] is False for key in ('mount_isolation_proven', 'ipc_isolation_proven',
        'proc_mount_isolation_proven', 'no_external_attempts_proven')))
    require(type(value['browser_receipts']) is list and len(value['browser_receipts']) == 2)
    first, second = [p.browser_receipt(item, phase)
                     for item, phase in zip(value['browser_receipts'], ('first', 'second'))]
    require(first['ids'] == second['ids'])
    check_logs(value['log_observations'])
    require(len(value['log_observations']) == 4)
    return value


def check_logs(rows):
    labels = {'server-first', 'browser-first', 'server-second', 'browser-second'}
    require(type(rows) is list and len(rows) <= 4)
    seen = set()
    for row in rows:
        require(type(row) is dict and row.keys() == {'case_id', 'bytes', 'sha256'}
            and type(row['case_id']) is str and row['case_id'] in labels and row['case_id'] not in seen
            and type(row['bytes']) is int and 0 <= row['bytes'] <= 4 * 1024 * 1024
            and type(row['sha256']) is str and re.fullmatch('[0-9a-f]{64}', row['sha256']))
        seen.add(row['case_id'])
    return rows


def runtime_failure(p, value, revision):
    require(type(value) is dict and type(value.get('schema')) is int and value['schema'] == 1
        and value.get('status') == 'failed' and value.get('runtime_revision') == revision
        and type(value.get('stage')) is str and value['stage'] in p.STAGES)
    first = value.get('first_failure')
    if first is not None:
        require(type(first) is dict and first.keys() == {'stage', 'browser', 'case_id', 'http_status'}
            and type(first['stage']) is str and first['stage'] in p.STAGES)
        require(first['case_id'] is None or (type(first['case_id']) is int and 0 <= first['case_id'] < 42))
        require(first['http_status'] is None or (type(first['http_status']) is int and 100 <= first['http_status'] <= 599))
        browser = first['browser']
        if browser is not None:
            require(type(browser) is dict and browser.keys() == {'action', 'http_status'} | p.CHROME_FLAGS
                and type(browser['action']) is str and browser['action'] in p.ACTIONS
                and (browser['http_status'] is None or (type(browser['http_status']) is int and 100 <= browser['http_status'] <= 599))
                and all(type(browser[key]) is bool for key in p.CHROME_FLAGS))
    cleanup = {}
    for key in ('owned_groups_joined', 'descendants_gone', 'listeners_closed'):
        require(type(value.get(key)) is bool)
        cleanup[key] = value[key]
    return dict(stage=value['stage'], first_failure=first, cleanup=cleanup,
                log_observations=check_logs(value.get('log_observations')))


def browser_identity(p, path):
    require(path.resolve(strict=True) == path)
    def operation(descriptor):
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and not before.st_mode & 0o022
            and 4 <= before.st_size <= 512 * 1024 * 1024)
        digest = hashlib.sha256()
        count = 0
        while chunk := os.read(descriptor, 65536):
            count += len(chunk); require(count <= before.st_size); digest.update(chunk)
        after = os.fstat(descriptor)
        require(count == before.st_size and all(getattr(before, name) == getattr(after, name)
            for name in ('st_dev', 'st_ino', 'st_uid', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')))
        return digest.hexdigest()
    return p.with_fd(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, operation)


def main():
    require(sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1
        and sys.argv == [str(HERE / 'crud.py')]
        and os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
        and os.environ.get('GITHUB_REF') == 'refs/heads/feature/native-local-dashboard-20261029')
    for path, digest in PINS.items():
        require(hashlib.sha256(path.read_bytes()).hexdigest() == digest)
    p = load('crud_protocol', HERE / 'crud_protocol.py')
    native = load('crud_native', BOOTSTRAP / 'native_build.py')
    handoff = load('crud_handoff', HERE / 'local_build.py')
    terminal = load('crud_terminal', HERE / 'check.py')
    fetch = native.load('crud_host', BOOTSTRAP / 'fetch_sdk.py')
    original = sys.argv
    try:
        sys.argv = [str(BOOTSTRAP / 'fetch_sdk.py')]
        temporary, revision = fetch.admission()
    finally:
        sys.argv = original
    source = Path(os.environ['GITHUB_WORKSPACE']) / 'silex'
    core = Path(os.environ['GITHUB_WORKSPACE']) / 'core'
    compiler, prefix = native.compiler(temporary)
    env = native.SUPPORT.environment(source, temporary)
    deadline = time.monotonic() + 1500
    groups = []
    lifecycle = native.load('crud_lifecycle', native.EXPORT / 'lifecycle.py')
    require(native.git(['-C', str(core), 'rev-parse', 'HEAD'], ROOT, env, deadline, groups, lifecycle).strip().decode() == p.CORE)
    require(not native.git(['-C', str(core), 'status', '--porcelain', '--untracked-files=all'], ROOT, env, deadline, groups, lifecycle))
    require(hashlib.sha256(native.read_file(core / 'scripts/run-isolated-test.sh', 65536,
                modes=(0o644, 0o755))).hexdigest() == p.WRAPPER_SHA)
    artifact = temporary / 'silex-original-dashboard-crud.json'
    require(not artifact.exists() and not artifact.is_symlink())
    work = Path(tempfile.mkdtemp(prefix='studio-export-crud-', dir=temporary))
    report = dict(schema=1, operation='actual_rust_http_original_dashboard_dom_crud', status='failed',
        stage='source_before', failure_kind='source_rejected', studio_revision=revision,
        silex_revision=native.SUPPORT.UPSTREAM, core_revision=p.CORE, wrapper_sha256=p.WRAPPER_SHA,
        fs_manifest_sha256=PINS[FS / 'manifest.json'], root_lock_sha256=None,
        dashboard_manifest_sha256=None, dashboard_assets={}, example_sha256=None,
        example_compile_actor_passed=False, example_binary={}, example_compiled=False,
        example_removed=False, immutable_source_inputs_preserved=False,
        runtime=None, runtime_failure=None, compiler_diagnostic=None, pid_namespace_joined=False,
        owned_group_count=0, owned_groups_joined=False, private_tool_tree_removed=False,
        public_fixture_only=True, **{key: False for key in FALSE_FLAGS})
    primary = None
    example_identity = None
    example_attempted = False
    example_parent_created = False
    ready = False
    try:
        for name in ('fixture', 'public', 'state', 'outside', 'home', 'tmp', 'logs', 'target'):
            (work / name).mkdir(mode=0o700)
        (work / 'home/cache').mkdir(mode=0o700)
        with (work / 'outside/sentinel').open('xb') as output:
            os.fchmod(output.fileno(), 0o600); output.write(b'PUBLIC outside sentinel unchanged\n')
        proof = native.load('crud_fs_proof', FS / 'proof.py')
        fs = native.load('crud_fs_prepare', FS / 'prepare.py')
        descriptor = fs.manifest(); fs.patch_bytes(descriptor)
        base = fs.SUPPORT.baseline_manifest()
        overlay = fs.SUPPORT.parse_manifest(fs.SUPPORT.read(BOOTSTRAP / 'manifest.json', 65536))
        require(fs.SUPPORT.digest(fs.SUPPORT.patch_bytes(overlay)) == descriptor['base_native_patch_sha256'])
        proof.source_check(native, fs, source, descriptor, base, overlay, env, deadline, groups, lifecycle)
        report['root_lock_sha256'] = proof.LOCK
        dashboard_raw = native.read_file(HERE / 'manifest.json', 65536)
        dashboard = native.SUPPORT.json_value(dashboard_raw); terminal.validate_manifest(dashboard)
        report['dashboard_manifest_sha256'] = hashlib.sha256(dashboard_raw).hexdigest()
        for name in p.ASSETS:
            raw = native.read_file(HERE / 'app' / name, 65536)
            require(len(raw) == dashboard['files'][name]['bytes']
                and hashlib.sha256(raw).hexdigest() == dashboard['files'][name]['sha256'])
            with (work / 'public' / name).open('xb') as output:
                os.fchmod(output.fileno(), 0o600); output.write(raw)
            report['dashboard_assets'][name] = dashboard['files'][name]
        example = source / EXAMPLE
        require(not example.exists() and not example.is_symlink())
        if not example.parent.exists():
            example.parent.mkdir(mode=0o755); example_parent_created = True
        require(example.parent.resolve(strict=True) == example.parent)
        example_raw = native.read_file(HERE / 'crud_server.rs', 65536)
        example_attempted = True
        with example.open('xb') as output:
            os.fchmod(output.fileno(), 0o644); output.write(example_raw)
        example_identity = (example.lstat().st_dev, example.lstat().st_ino)
        report['example_sha256'] = hashlib.sha256(example_raw).hexdigest()
        tracked = native.tracked(source, (), env, deadline, groups, lifecycle)
        extras = sorted((set(base['files']) | set(overlay['files']) | set(descriptor['files']) | {EXAMPLE}) - tracked.keys())
        before = native.tracked(source, extras, env, deadline, groups, lifecycle)
        source_unchanged(native, source, before, extras, env, deadline, groups, lifecycle)
        report['stage'] = 'example_compile'
        env.update(CARGO_TARGET_DIR=str(work / 'target'), CARGO_BUILD_JOBS='2', TMPDIR=str(work / 'tmp'))
        native.actor(build_command(prefix), env, source, deadline, groups, lifecycle,
                     log=work / 'logs/native-cargo.log', seconds=900)
        report.update(example_compile_actor_passed=True, stage='example_verify')
        source_unchanged(native, source, before, extras, env, deadline, groups, lifecycle)
        compiler.verify_payload(prefix, compiler.pins())
        copy_binary(p, native, work / 'target/debug/examples/volparossa_dashboard_crud',
                    work / 'server', report['example_binary'])
        report['example_compiled'] = True
        report['stage'] = 'driver_prepare'
        node, pnpm, _ = native.export_carrier(work)
        for original_name, destination in (('crud_runtime.py', 'runtime.py'),
                ('crud_protocol.py', 'crud_protocol.py'), ('crud_browser.mjs', 'crud_browser.mjs')):
            with (work / 'fixture' / destination).open('xb') as output:
                os.fchmod(output.fileno(), 0o600); output.write(native.read_file(HERE / original_name, 131072))
        for name in ('package.json', 'pnpm-lock.yaml'):
            with (work / 'fixture' / name).open('xb') as output:
                os.fchmod(output.fileno(), 0o600); output.write(native.read_file(native.EXPORT / name, 65536))
        driver_env = dict(env, PATH=str(node.parent) + ':' + str(prefix / 'bin') + ':/usr/bin:/bin',
            HOME=str(work / 'home'), PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1', CI='true',
            NPM_CONFIG_USERCONFIG='/dev/null', NPM_CONFIG_GLOBALCONFIG='/dev/null',
            NPM_CONFIG_REGISTRY='https://registry.npmjs.org/', NPM_CONFIG_UPDATE_NOTIFIER='false',
            PNPM_DISABLE_SELF_UPDATE_CHECK='1', COREPACK_ENABLE_NETWORK='0')
        native.actor([node, pnpm, '--dir', work / 'fixture', 'install', '--frozen-lockfile', '--ignore-scripts',
            '--store-dir', work / 'store', '--config.manage-package-manager-versions=false',
            '--config.update-notifier=false'], driver_env, work, deadline, groups, lifecycle,
            log=work / 'logs/driver-install.log', seconds=180)
        chrome = next((path for path in ('/usr/bin/google-chrome', '/usr/bin/google-chrome-stable')
                       if Path(path).is_file()), None)
        require(chrome is not None)
        chrome_binary = Path('/opt/google/chrome/chrome')
        require(chrome_binary.resolve(strict=True) == chrome_binary and chrome_binary.is_file())
        # Installed browser identity is observed, never represented as source authentication.
        report['browser_binary_sha256'] = browser_identity(p, chrome_binary)
        value = dict(schema=1, revision=revision, root=str(work), node=str(node), chrome=chrome,
            server=str(work / 'server'), parent_net=os.readlink('/proc/self/ns/net'),
            parent_pid=os.readlink('/proc/self/ns/pid'), uid=os.getuid(), gid=os.getgid(),
            assets=report['dashboard_assets'], files={})
        for name in ('fixture/runtime.py', 'fixture/crud_protocol.py', 'fixture/crud_browser.mjs', 'server', 'node/node'):
            modes = (0o700,) if name in ('server', 'node/node') else (0o600,)
            value['files'][name] = hashlib.sha256(p.read(work / name, 256 * 1024 * 1024, modes)).hexdigest()
        p.context(value, work); p.write(work / 'runtime-context.json', value)
        report['stage'] = 'actual_http_dom'
        wrapper_env = dict(driver_env, RUNNER_TEMP=str(temporary), GITHUB_ACTIONS='true',
            RUNNER_ENVIRONMENT='github-hosted', VOLPAROSSA_TEST_ALLOW_SUDO_NETNS='1')
        run_wrapper(native, core, work, wrapper_env, deadline, groups, lifecycle)
        report['pid_namespace_joined'] = True
        report['runtime'] = check_runtime(p, p.decode(p.read(work / 'runtime-receipt.json')), revision)
        p.context(value, work)
        source_unchanged(native, source, before, extras, env, deadline, groups, lifecycle)
        require(hashlib.sha256(native.read_file(HERE / 'manifest.json', 65536)).hexdigest() == report['dashboard_manifest_sha256'])
        fs.SUPPORT.hosted_guard(source)
        report['immutable_source_inputs_preserved'] = True
        report['failure_kind'] = None
        ready = True
    except BaseException as error:
        primary = error
        report['failure_kind'] = error.kind if isinstance(error, native.Rejected) else 'source_rejected'
        try:
            if report['stage'] == 'actual_http_dom':
                report['runtime_failure'] = runtime_failure(p,
                    p.decode(p.read(work / 'runtime-receipt.json')), revision)
            elif report['stage'] == 'example_compile':
                report['compiler_diagnostic'] = native.compiler_diagnostic(work,
                    clipped=isinstance(error, native.Rejected) and error.kind == 'output_limit')
        except BaseException:
            pass
    finally:
        # Shield both example removal and the terminal handoff from repeat cancellation.
        numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
        mask = None
        try:
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
        except BaseException as error:
            primary = primary or error
        try:
            try:
                example = source / EXAMPLE
                if example_identity is not None:
                    current = example.lstat()
                    require((current.st_dev, current.st_ino) == example_identity and stat.S_ISREG(current.st_mode))
                    example.unlink()
                    if example_parent_created:
                        example.parent.rmdir()
                    report['example_removed'] = True
                else:
                    require(not example_attempted or (not example.exists() and not example.is_symlink()))
                    report['example_removed'] = True  # No owned example was created.
            except BaseException as error:
                primary = primary or error
            try:
                primary = handoff.pending_cancellation() if primary is None else primary
            except BaseException as error:
                primary = primary or error
            primary = handoff.finish_build(terminal, artifact, work, report, groups, [], primary,
                child_attempted=bool(groups), work_created=True, ready=ready and report['example_removed'])
            # No project action after terminal publication. Profile removal is
            # represented by private_tool_tree_removed in that terminal receipt.
        finally:
            if mask is not None:
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, mask)
                except BaseException as error:
                    if report['status'] != 'passed':
                        primary = primary or error
    if primary is not None:
        raise primary
    print('ACTUAL_RUST_HTTP_DOM_CRUD=true; NATIVE_WEBVIEW=false; PUBLICATION=false')


if __name__ == '__main__':
    def cancelled(_number, _frame):
        raise InterruptedError('public CRUD proof cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(number, cancelled)
    signal.setitimer(signal.ITIMER_REAL, 1520)
    try:
        main()
    except BaseException:
        raise SystemExit(1) from None
