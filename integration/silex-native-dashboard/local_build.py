#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Private FS + original local dashboard release compilation, never app execution."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOOTSTRAP = HERE.parent / 'silex-native-bootstrap'
FS = HERE.parent / 'silex-fs-identifier-rename'
COMPOSE_SHA256 = 'fa8bda1a443eba9e975d180b299cd38949bc2c87ef48228b35881f521f4bd8b4'
PINS = {
    BOOTSTRAP / 'native_build.py': '9d8d45fe88922ced9ee43a0465177343f7b3757f6e9a28dc30884b0e3a03f51c',
    BOOTSTRAP / 'prepare.py': 'b805e7ddfedba9bbd6f677b992765f681c05e22f174de2603c3ca817034567f6',
    HERE / 'check.py': '42fbd5e85d74681634c7316197202dbe71372bc6b862dca38f604c6a487f1c26',
    FS / 'proof.py': '6beda07a041b558130f09e7760421897598cfc05ccb17a5742ca7471ded6294c',
    FS / 'prepare.py': 'd2f1cd0d964f4d89d932ab4d26201cc9d8eae0a97408087d1f102b9331bb4f3e',
    FS / 'manifest.json': '99a5893dea431b0f0be38d97d0b0b342e0b3c7a8ad191b9e05ab158a7ce195aa',
}
ASSETS = frozenset(('public/index.html', 'public/dashboard.css', 'public/dashboard.js'))
FALSE_FLAGS = ('application_executed', 'native_gui_verified', 'native_runtime_acceptance',
               'full_application_privacy', 'full_studio_acceptance', 'publication_authorized',
               'redistribution_acceptance', 'locked_dependency_acceptance', 'volparossa_updates_verified',
               'system_packages_installed_by_this_helper', 'whole_source_tree_unchanged',
               'real_dashboard_crud_proven', 'native_signing_consent_proven')


def require(value):
    if not value:
        raise RuntimeError('original dashboard private build rejected')


class Cancelled(RuntimeError):
    def __init__(self, kind):
        if kind not in ('deadline', 'cancelled'):
            raise ValueError('closed original build cancellation required')
        self.kind = kind
        super().__init__('original dashboard build interrupted')


def check_composition(value, descriptor_sha, expected_rows):
    require(type(value) is dict and value.keys() == {'schema', 'operation', 'manifest_sha256', 'assets',
        'asset_count', 'embedded_assets_license', 'application_executed', 'native_gui_verified',
        'real_server_crud', 'redistribution_acceptance', 'publication_authorized'})
    require(type(value['schema']) is int and value['schema'] == 1
            and value['operation'] == 'original_dashboard_asset_composition'
            and value['manifest_sha256'] == descriptor_sha
            and type(value['asset_count']) is int and value['asset_count'] == 3
            and value['embedded_assets_license'] == 'GPL-3.0-only'
            and all(value[key] is False for key in ('application_executed', 'native_gui_verified',
                'real_server_crud', 'redistribution_acceptance', 'publication_authorized')))
    rows = value['assets']
    require(type(rows) is list and len(rows) == 3)
    for row in rows:
        require(type(row) is dict and row.keys() == {'path', 'bytes', 'sha256'}
                and type(row['path']) is str and row['path'] in ASSETS
                and type(row['bytes']) is int and 0 < row['bytes'] <= 128 * 1024
                and type(row['sha256']) is str and re.fullmatch('[0-9a-f]{64}', row['sha256']))
    require({row['path'] for row in rows} == ASSETS)
    require(sorted(rows, key=lambda row: row['path']) == expected_rows)
    return sorted(rows, key=lambda row: row['path'])


def full_extras(before, base, overlay, fs_value):
    return sorted((set(base['files']) | set(overlay['files']) | set(fs_value['files'])) - before.keys())


def initialize_source_hook(native, source):
    """Initialize only the shared hosted hook, never Native6-only admission."""
    path = BOOTSTRAP / 'prepare.py'
    require(hashlib.sha256(native.read_file(path, 65536)).hexdigest() == PINS[path])
    prepare = native.load('native_build_prepare', path)
    require(sys.modules.get('native_build_prepare') is prepare)
    prepare.hosted_guard(source)


def pending_cancellation():
    pending = signal.sigpending().intersection((signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM))
    return Cancelled('deadline' if signal.SIGALRM in pending else 'cancelled') if pending else None


def metadata_accounting(report, groups, primary):
    """Do not let a second cancellation erase an already owned actor failure."""
    numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
    mask = None
    try:
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
    except BaseException as error:
        primary = primary or error
    try:
        report.update(owned_group_count=len(groups), owned_groups_joined=bool(groups) and all(groups))
    except BaseException as error:
        primary = primary or error
    try:
        primary = primary or pending_cancellation()
    except BaseException as error:
        primary = primary or error
    finally:
        if mask is not None:
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            except BaseException as error:
                primary = primary or error
    if primary is not None:
        try:
            report['status'] = 'failed'
        except BaseException:
            pass
    return primary


def finish_build(terminal, artifact, work, report, groups, metadata_groups, primary, **conditions):
    """Block the accounting→terminal handoff; terminal checks queued precommit signals."""
    numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
    mask = None
    committed = False
    try:
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
    except BaseException as error:
        primary = primary or error
    try:
        try:
            report.update(main_owned_group_count=len(groups), main_owned_groups_joined=bool(groups) and all(groups))
        except BaseException as error:
            primary = primary or error
        try:
            primary = primary or pending_cancellation()
        except BaseException as error:
            primary = primary or error
        # Attempt the single cleanup/receipt owner even when accounting failed.
        try:
            result = terminal.finish(artifact, work, report, groups + metadata_groups, primary, **conditions)
            primary = primary or result
            committed = primary is None and report.get('status') == 'passed'
        except BaseException as error:
            primary = primary or error
    finally:
        if mask is not None:
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            except BaseException as error:
                # Terminal publication is irreversible; no project action follows
                # it, and late cancellation must not contradict its valid receipt.
                if not committed:
                    primary = primary or error
    return primary


def metadata(native, prefix, env, source, deadline, groups, lifecycle, lock_sha, report):
    require(not groups)
    report.update(schema=1, operation='local_dashboard_full_offline_metadata',
                  owner_scope='metadata_process_group', status='failed',
                  root_lock_sha256=lock_sha, package_records=None,
                  offline_locked_metadata_passed=False, owned_group_count=0, owned_groups_joined=False)
    primary = None
    try:
        raw = native.actor([str(prefix / 'bin/cargo'), 'metadata', '--offline', '--locked', '--format-version=1'],
                           env, source, deadline, groups, lifecycle, capture=8 * 1024 * 1024, seconds=120)
        native.SUPPORT.metadata(raw, source)
        require(len(native.SUPPORT.ledger(native.SUPPORT.read(source / 'Cargo.lock'))[1]) == 563)
        require(len(groups) == 1 and all(groups))
        report.update(status='passed', package_records=563, offline_locked_metadata_passed=True)
    except BaseException as error:
        primary = error
    finally:
        primary = metadata_accounting(report, groups, primary)
    if primary is not None:
        raise primary
    return report


def build_frontend(native, node, pnpm, work, source, env, deadline, groups, lifecycle, check_sources):
    native.actor([node, pnpm, '--dir', source, '--filter', '@silexlabs/silex', 'install', '--frozen-lockfile',
                  '--ignore-scripts', '--store-dir', work / 'store', '--config.manage-package-manager-versions=false',
                  '--config.update-notifier=false'], env, source, deadline, groups, lifecycle,
                 log=work / 'logs/frontend-install.log', seconds=600)
    check_sources()
    for name in ('client', 'public'):
        native.actor([node, pnpm, '--dir', source, 'run', 'build:' + name], env, source, deadline, groups,
                     lifecycle, log=work / ('logs/build-' + name + '.log'), seconds=600)
        check_sources()
    return native.frontend_inventory(source / 'dist/client')


def main():
    require(sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1
            and sys.argv == [str(HERE / 'local_build.py')]
            and os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and os.environ.get('GITHUB_REF') == 'refs/heads/feature/native-local-dashboard-20261029')
    for path, expected in PINS.items():
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected)
    require(hashlib.sha256((HERE / 'compose.py').read_bytes()).hexdigest() == COMPOSE_SHA256)
    # Load only the already bound native module first; its loader never runs a carrier.
    import importlib.util
    spec = importlib.util.spec_from_file_location('original_build_native', BOOTSTRAP / 'native_build.py')
    native = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = native
    spec.loader.exec_module(native)
    fetch = native.load('original_build_host', BOOTSTRAP / 'fetch_sdk.py')
    terminal = native.load('original_build_terminal', HERE / 'check.py')
    original = sys.argv
    try:
        sys.argv = [str(BOOTSTRAP / 'fetch_sdk.py')]
        temporary, revision = fetch.admission()
    finally:
        sys.argv = original
    source = Path(os.environ['GITHUB_WORKSPACE']) / 'silex'
    artifact = temporary / 'silex-original-dashboard-build.json'
    require(not artifact.exists() and not artifact.is_symlink())
    work = temporary / 'silex-original-dashboard-build-private'
    target = temporary / 'silex-original-dashboard-build-target'
    groups, metadata_groups = [], []
    primary = None
    ready = work_created = child_attempted = False
    deadline = time.monotonic() + 1790
    report = dict(schema=1, operation='private_original_dashboard_native_release', status='failed', stage='sdk_gate',
        operation_failure_kind='sdk_rejected', studio_revision=revision, source_commit=native.SUPPORT.UPSTREAM,
        fs_manifest_sha256=PINS[FS / 'manifest.json'], compose_sha256=COMPOSE_SHA256,
        sdk_manifest_sha256=native.SDK_MANIFEST, sdk_gate_verified=False,
        compiler_payload_verified=False, root_lock_sha256=None, metadata_check=None,
        original_dashboard_composition=None, dashboard_asset_count=0, dashboard_bytes=0,
        authenticated_node=False, frontend_built=False, frontend_assets=0, frontend_bytes=0,
        frontend_inventory_sha256=None, generated_schema_changes=[], immutable_source_inputs_preserved=False,
        native_build=False, binary=None, compiler_diagnostic=None, private_compile_only=True,
        compiled_target_retained=False, main_owned_group_count=0,
        main_owned_groups_joined=False, owned_group_count=0, owned_groups_joined=False,
        owner_scope='main_and_metadata_process_groups', private_tool_tree_removed=False,
        **{key: False for key in FALSE_FLAGS})
    try:
        # No source mutation, private build tree or acquisition before normal SDK admission.
        installer = native.load('original_build_sdk', BOOTSTRAP / 'install_sdk.py')
        require(installer.MANIFEST == native.SDK_MANIFEST)
        records = installer.records_from_manifest(native.read_file(BOOTSTRAP / 'ubuntu-sdk.json', 1024 * 1024))
        outer = native.SUPPORT.json_value(native.read_file(temporary / 'silex-native-sdk-install.json', 65536, modes=(0o600,)))
        root = native.SUPPORT.json_value(native.read_file(temporary / 'silex-native-sdk-install-root.json', 65536, modes=(0o600,)))
        native.sdk_receipts(outer, root, revision, records, installer)
        lifecycle = native.load('lifecycle', native.EXPORT / 'lifecycle.py')
        env = native.SUPPORT.environment(source, temporary)
        child_attempted = True
        raw = native.actor(['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\t${Status}\n',
                            '--', *records], env, ROOT, deadline, groups, lifecycle)
        installer.dpkg_rows(raw, records, complete=True)
        report['sdk_gate_verified'] = True
        report['stage'] = 'initialize_source_hook'
        initialize_source_hook(native, source)
        report['stage'] = 'compiler'
        compiler, prefix = native.compiler(temporary)
        report['compiler_payload_verified'] = True
        proof = native.load('original_build_fs_proof', FS / 'proof.py')
        fs = native.load('original_build_fs_prepare', FS / 'prepare.py')
        value = fs.manifest()
        fs.patch_bytes(value)
        base = fs.SUPPORT.baseline_manifest()
        overlay = fs.SUPPORT.parse_manifest(fs.SUPPORT.read(BOOTSTRAP / 'manifest.json', 65536))
        require(fs.SUPPORT.digest(fs.SUPPORT.patch_bytes(overlay)) == value['base_native_patch_sha256'])
        report['stage'] = 'source_before'
        admitted = proof.source_check(native, fs, source, value, base, overlay, env, deadline, groups, lifecycle)
        report['root_lock_sha256'] = proof.LOCK
        report['stage'] = 'offline_metadata'
        report['metadata_check'] = {}
        metadata(native, prefix, env, source, deadline, metadata_groups, lifecycle, proof.LOCK, report['metadata_check'])
        require(report['metadata_check']['owned_group_count'] == 1
                and report['metadata_check']['owned_groups_joined'] is True)
        require(proof.source_check(native, fs, source, value, base, overlay, env, deadline, groups, lifecycle) == admitted)
        # A real source gitlink is authenticated before any replacement assets are installed.
        native.gitlink(native.git(['-C', str(source), 'ls-tree', '-z', 'HEAD', '--', 'silex-dashboard-2026'],
                                  ROOT, env, deadline, groups, lifecycle))
        before = native.tracked(source, (), env, deadline, groups, lifecycle)
        extras = full_extras(before, base, overlay, value)
        before = native.tracked(source, extras, env, deadline, groups, lifecycle)
        require(hashlib.sha256(native.read_file(source / 'pnpm-lock.yaml', 1024 * 1024)).hexdigest() == native.PNPM_LOCK)
        report['stage'] = 'compose_original_dashboard'
        compose = native.load('original_build_compose', HERE / 'compose.py')
        descriptor_raw = native.read_file(HERE / 'manifest.json', 65536)
        descriptor_sha = hashlib.sha256(descriptor_raw).hexdigest()
        descriptor = native.SUPPORT.json_value(descriptor_raw)
        terminal.validate_manifest(descriptor)
        expected_rows = sorted([dict(path='public/' + name, **row) for name, row in descriptor['files'].items()
                                if 'public/' + name in ASSETS], key=lambda row: row['path'])
        composition = compose.install(source)
        rows = check_composition(composition, descriptor_sha, expected_rows)
        native.dashboard_unchanged(source, rows)
        report.update(original_dashboard_composition=composition, dashboard_asset_count=3,
                      dashboard_bytes=sum(row['bytes'] for row in rows))
        work.mkdir(mode=0o700)
        work_created = True
        for name in ('home', 'logs', 'store', 'tmp'):
            (work / name).mkdir(mode=0o700)
        target.mkdir(mode=0o700)
        report['compiled_target_retained'] = True
        env.update(HOME=str(work / 'home'), TMPDIR=str(work / 'tmp'), CARGO_TARGET_DIR=str(target), CARGO_BUILD_JOBS='2',
            CI='true', HUSKY='0', DO_NOT_TRACK='1', NPM_CONFIG_USERCONFIG='/dev/null', NPM_CONFIG_GLOBALCONFIG='/dev/null',
            NPM_CONFIG_REGISTRY='https://registry.npmjs.org/', NPM_CONFIG_UPDATE_NOTIFIER='false',
            PNPM_DISABLE_SELF_UPDATE_CHECK='1', COREPACK_ENABLE_NETWORK='0')
        report['stage'] = 'authenticate_node'
        node, pnpm, pins = native.export_carrier(work)
        report['authenticated_node'] = True
        env['PATH'] = str(node.parent) + ':' + str(prefix / 'bin') + ':/usr/bin:/bin'
        report['stage'] = 'frontend'
        frontend = build_frontend(native, node, pnpm, work, source, env, deadline, groups, lifecycle,
            lambda: native.source_check(source, before, extras, rows, env, deadline, groups, lifecycle))
        native.source_check(source, before, extras, rows, env, deadline, groups, lifecycle)
        report.update(frontend_built=True, frontend_assets=len(frontend),
            frontend_bytes=sum(row['bytes'] for row in frontend),
            frontend_inventory_sha256=hashlib.sha256(json.dumps(frontend, sort_keys=True).encode()).hexdigest())
        require(native.file_hash(node, pins['node']['files']['bin/node']['bytes'], executable=True)['sha256']
                == pins['node']['files']['bin/node']['sha256'])
        compiler.verify_payload(prefix, compiler.pins())
        report['stage'] = 'native_release_compile'
        native.actor(native.release_command(temporary), env, source, deadline, groups, lifecycle,
                     log=work / 'logs/native-cargo.log', seconds=1500)
        report['stage'] = 'source_after'
        report['generated_schema_changes'] = native.source_check(source, before, extras, rows, env, deadline, groups, lifecycle)
        require(native.frontend_inventory(source / 'dist/client') == frontend)
        compiler.verify_payload(prefix, compiler.pins())
        require(hashlib.sha256(native.read_file(HERE / 'manifest.json', 65536)).hexdigest() == descriptor_sha
                and hashlib.sha256(native.read_file(HERE / 'compose.py', 65536)).hexdigest() == COMPOSE_SHA256)
        report['stage'] = 'inspect_elf'
        report['binary'] = native.inspect_elf(target / 'release/silex-desktop')
        report.update(native_build=True, immutable_source_inputs_preserved=True, operation_failure_kind=None)
        ready = True
    except BaseException as error:
        primary = error
        report['operation_failure_kind'] = (error.kind if isinstance(error, (native.Rejected, Cancelled)) else 'source_rejected')
        if report['stage'] == 'native_release_compile':
            try:
                report['compiler_diagnostic'] = native.compiler_diagnostic(work,
                    clipped=isinstance(error, native.Rejected) and error.kind == 'output_limit')
            except BaseException:
                pass
    finally:
        primary = finish_build(terminal, artifact, work, report, groups, metadata_groups, primary,
                               child_attempted=child_attempted, work_created=work_created, ready=ready)
    if primary is not None:
        raise primary
    print('ORIGINAL_DASHBOARD_NATIVE_BUILD=true; APPLICATION_EXECUTED=false; NATIVE_GUI=false')


if __name__ == '__main__':
    def cancelled(number, _frame):
        raise Cancelled('deadline' if number == signal.SIGALRM else 'cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(number, cancelled)
    signal.setitimer(signal.ITIMER_REAL, 1800)
    try:
        main()
    except BaseException:
        raise SystemExit(1) from None
