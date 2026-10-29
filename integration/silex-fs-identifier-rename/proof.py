#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Actual hosted server-library tests of one reviewed FS overlay; JSON only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOOTSTRAP = HERE.parent / 'silex-native-bootstrap'
PINS = {
    BOOTSTRAP / 'native_build.py': '9d8d45fe88922ced9ee43a0465177343f7b3757f6e9a28dc30884b0e3a03f51c',
    HERE.parent / 'silex-native-dashboard/check.py': '42fbd5e85d74681634c7316197202dbe71372bc6b862dca38f604c6a487f1c26',
    HERE / 'prepare.py': 'd2f1cd0d964f4d89d932ab4d26201cc9d8eae0a97408087d1f102b9331bb4f3e',
    HERE / 'manifest.json': '725ca94c0f1e182f5909a59cd79c79c11895bec8efedaf841544ff230425f224',
}
LOCK = 'de04aaf5ff1acbdde421e3447ea67f3eb7a00a7d5ed118f4387a180e84590118'
METADATA_CASES = (
    'rename_preserves_known_and_unknown_fields_and_installs_a_private_regular_file',
    'name_only_commit_preserves_exact_numeric_tokens_whitespace_and_unknown_fields',
    'lossless_name_span_handles_escaped_keys_nested_values_and_refuses_ambiguous_or_oversize_output',
    'rooted_metadata_refuses_site_root_file_symlinks_hardlinks_and_nonregular_files',
    'observed_content_or_directory_mutation_refuses_commit_and_removes_owned_temporary',
    'changed_or_replaced_temporary_is_never_committed_or_mistaken_for_owned_cleanup',
    'metadata_limits_duplicate_members_missing_targets_and_name_limits_fail_closed',
    'cancelled_caller_keeps_the_single_metadata_permit_until_blocking_work_finishes',
)
STORAGE_CASES = (
    'direct_invalid_ids_are_refused_before_any_filesystem_effect_across_all_methods',
    'http_query_ids_are_backend_checked_including_empty_absolute_and_encoded_traversal',
    'valid_legacy_ids_and_generated_ids_retain_crud_assets_and_explicit_metadata_replacement',
    'http_typed_rename_preserves_metadata_rejects_extra_fields_and_advertises_real_capability',
    'shared_metadata_admission_refuses_concurrent_waiters_then_preserves_current_fields',
    'old_connector_methods_remain_available_and_new_rename_fails_closed_without_fallback',
)
EXPECTED = frozenset('connectors::fs_storage::metadata::tests::' + name for name in METADATA_CASES) | frozenset(
    'connectors::fs_storage::tests::' + name for name in STORAGE_CASES)
KINDS = frozenset(('admission', 'source_rejected', 'compiler_rejected', 'metadata_rejected',
                   'child_failed', 'output_limit', 'deadline', 'cancelled', 'cleanup_failed',
                   'artifact_failed', 'tests_rejected'))
FALSE_FLAGS = ('sdk_installed', 'packages_installed', 'node_executed', 'native_application_executed',
               'native_gui_proven', 'native_runtime_acceptance', 'http_runtime_proven',
               'generic_asset_path_confinement_proven', 'authorization_proven', 'cross_process_cas_proven',
               'full_atomicity_proven', 'publication_authorized', 'full_studio_acceptance',
               'dependency_acceptance', 'volparossa_updates_verified')


class Rejected(RuntimeError):
    def __init__(self, kind):
        if kind not in KINDS:
            raise ValueError('closed FS proof failure required')
        self.kind = kind
        super().__init__('FS hosted unit proof rejected')


def require(value, kind='source_rejected'):
    if not value:
        raise Rejected(kind)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_command(temporary):
    return [str(temporary / 'volparossa-rust-1.99.1/bin/cargo'), 'test', '--offline', '--locked',
            '-p', 'silex-server', '--lib', '--', '--test-threads=1']


def test_result(raw):
    require(len(raw) <= 16 * 1024 * 1024, 'output_limit')
    text = raw.decode('utf-8', errors='strict')
    starts = re.findall(r'^running ([0-9]+) tests?$', text, re.MULTILINE)
    require(len(starts) == 1 and 14 <= int(starts[0]) <= 4096, 'tests_rejected')
    rows = re.findall(r'^test ([A-Za-z0-9_:]+) \.\.\. (ok|FAILED|ignored)$', text, re.MULTILINE)
    require(len(rows) == int(starts[0]) and len({name for name, _ in rows}) == len(rows)
            and all(status == 'ok' for _, status in rows)
            and EXPECTED <= {name for name, _ in rows}, 'tests_rejected')
    summaries = re.findall(r'^test result: ok\. ([0-9]+) passed; 0 failed; 0 ignored; 0 measured; '
                           r'0 filtered out; finished in [0-9.]+s$', text, re.MULTILINE)
    require(summaries == starts and not re.search(r'^test result: FAILED\.', text, re.MULTILINE), 'tests_rejected')
    return dict(tests=len(rows), passed=len(rows), failed=0, ignored=0, filtered=0,
                reviewed_fs_cases=len(EXPECTED), output_sha256=hashlib.sha256(raw).hexdigest())


def source_check(native, fs, source, value, base, overlay, env, deadline, groups, lifecycle):
    """The preparation contract, using measured owned actors for every Git read."""
    def git(*arguments):
        return native.git(['-C', str(source), *arguments], ROOT, env, deadline, groups, lifecycle)
    native.SUPPORT.directory(source)
    native.SUPPORT.directory(source / '.git')
    require(git('rev-parse', '--show-toplevel').strip().decode() == str(source)
            and git('rev-parse', 'HEAD').strip().decode() == fs.SUPPORT.UPSTREAM)
    require(not git('diff', '--cached', '--name-only', '-z', 'HEAD', '--'))
    require(all(row.startswith(b'H ') for row in git('ls-files', '-v', '-z').split(b'\0') if row))
    expected = {name: row['after'] for name, row in base['files'].items()}
    expected.update({name: row['after'] for name, row in overlay['files'].items()})
    expected.update({name: row['after'] for name, row in value['files'].items()})
    changed = git('diff', '--no-ext-diff', '--no-textconv', '--name-only', '-z', 'HEAD', '--')
    changed += git('ls-files', '--others', '-z')
    require({name.decode('utf-8', errors='strict') for name in changed.split(b'\0') if name} == expected.keys())
    for name, record in expected.items():
        fs.SUPPORT.check_file(source, name, record)
        require(stat.S_IMODE((source / name).lstat().st_mode) == stat.S_IMODE(int(record['mode'], 8)))
    for name in ('server-rust/Cargo.lock', 'desktop/src-tauri/Cargo.lock', 'Cargo.toml'):
        require(native.SUPPORT.read(source / name) == git('show', 'HEAD:' + name))
    raw = native.SUPPORT.read(source / 'Cargo.lock')
    require(hashlib.sha256(raw).hexdigest() == LOCK and len(native.SUPPORT.ledger(raw)[1]) == 563)
    return {name: row['sha256'] for name, row in sorted(expected.items())}


def failure_kind(error):
    kind = getattr(error, 'kind', None)
    if kind in KINDS:
        return kind
    return 'cancelled' if isinstance(error, (KeyboardInterrupt, InterruptedError)) else 'source_rejected'


def execute_tests(native, temporary, source, work, env, deadline, groups, lifecycle, report):
    """One actual Cargo actor; privately bounded combined output, never streamed."""
    try:
        native.actor(test_command(temporary), env, source, deadline, groups, lifecycle,
                     log=work / 'logs/native-cargo.log', seconds=900)
    except BaseException as error:
        try:
            report['compiler_diagnostic'] = native.compiler_diagnostic(
                work, clipped=isinstance(error, native.Rejected) and error.kind == 'output_limit')
        except BaseException:
            pass  # This optional observer never replaces the actual actor failure.
        raise
    report['rust_test_binary_executed'] = True
    raw = native.read_file(work / 'logs/native-cargo.log', 16 * 1024 * 1024, modes=(0o600,))
    return test_result(raw)


def main():
    require(sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1
            and sys.argv == [str(HERE / 'proof.py')], 'admission')
    require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and os.environ.get('GITHUB_REF') == 'refs/heads/feature/native-local-dashboard-20261029', 'admission')
    for path, expected in PINS.items():
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected)
    native = load('fs_proof_native', BOOTSTRAP / 'native_build.py')
    fetch = load('fs_proof_host', BOOTSTRAP / 'fetch_sdk.py')
    terminal = load('fs_proof_terminal', HERE.parent / 'silex-native-dashboard/check.py')
    original = sys.argv
    try:
        sys.argv = [str(BOOTSTRAP / 'fetch_sdk.py')]
        temporary, revision = fetch.admission()
    finally:
        sys.argv = original
    source = Path(os.environ['GITHUB_WORKSPACE']) / 'silex'
    artifact = temporary / 'silex-fs-identifier-rename-proof.json'
    require(not artifact.exists() and not artifact.is_symlink(), 'artifact_failed')
    work = temporary / 'silex-fs-proof-private'
    target = temporary / 'silex-fs-proof-target'
    groups = []
    primary = None
    ready = work_created = child_attempted = False
    deadline = time.monotonic() + 1100
    report = dict(schema=1, operation='fs_identifier_rename_server_lib_tests', status='failed',
        stage='admission', operation_failure_kind='admission', studio_revision=revision,
        source_commit=native.SUPPORT.UPSTREAM, expected_root_lock_sha256=LOCK,
        root_lock_sha256=None, package_records=None,
        fs_manifest_sha256=PINS[HERE / 'manifest.json'], fs_patch_sha256=None,
        source_files_sha256=None, source_unchanged=False, compiler_payload_verified=False,
        full_offline_locked_metadata_passed=False, server_lib_tests_passed=False,
        test_result=None, compiler_diagnostic=None, rust_test_binary_executed=False, compiled_target_retained=False,
        owned_group_count=0, owned_groups_joined=False, owner_scope='proof_process_groups',
        private_tool_tree_removed=False, **{name: False for name in FALSE_FLAGS})
    try:
        work.mkdir(mode=0o700)
        work_created = True
        (work / 'tmp').mkdir(mode=0o700)
        (work / 'logs').mkdir(mode=0o700)
        target.mkdir(mode=0o700)
        report['compiled_target_retained'] = True
        fs = load('fs_proof_preparation', HERE / 'prepare.py')
        value = fs.manifest()
        fs.patch_bytes(value)
        report['fs_patch_sha256'] = value['patch']['sha256']
        base = fs.SUPPORT.baseline_manifest()
        overlay = fs.SUPPORT.parse_manifest(fs.SUPPORT.read(BOOTSTRAP / 'manifest.json', 65536))
        require(fs.SUPPORT.digest(fs.SUPPORT.patch_bytes(overlay)) == value['base_native_patch_sha256'])
        report['stage'] = 'compiler'
        compiler, prefix = native.compiler(temporary)
        report['compiler_payload_verified'] = True
        env = native.SUPPORT.environment(source, temporary)
        env.update(CARGO_TARGET_DIR=str(target), TMPDIR=str(work / 'tmp'), CARGO_BUILD_JOBS='2')
        lifecycle = native.load('lifecycle', native.EXPORT / 'lifecycle.py')
        report['stage'] = 'source_before'
        child_attempted = True
        before = source_check(native, fs, source, value, base, overlay, env, deadline, groups, lifecycle)
        report['source_files_sha256'] = before
        report.update(root_lock_sha256=LOCK, package_records=563)
        report['stage'] = 'offline_metadata'
        raw = native.actor([str(prefix / 'bin/cargo'), 'metadata', '--offline', '--locked', '--format-version=1'],
                           env, source, deadline, groups, lifecycle, capture=8 * 1024 * 1024, seconds=120)
        native.SUPPORT.metadata(raw, source)
        report['full_offline_locked_metadata_passed'] = True
        compiler.verify_payload(prefix, compiler.pins())
        report['stage'] = 'server_lib_tests'
        report['test_result'] = execute_tests(native, temporary, source, work, env, deadline, groups, lifecycle, report)
        report['stage'] = 'source_after'
        require(source_check(native, fs, source, value, base, overlay, env, deadline, groups, lifecycle) == before)
        compiler.verify_payload(prefix, compiler.pins())
        report.update(source_unchanged=True, server_lib_tests_passed=True, operation_failure_kind=None)
        ready = True
    except BaseException as error:
        primary = error
        report['operation_failure_kind'] = failure_kind(error)
    finally:
        primary = terminal.finish(artifact, work, report, groups, primary,
                                  child_attempted=child_attempted, work_created=work_created, ready=ready)
    if primary is not None:
        raise primary
    print('FS_SERVER_LIB_TESTS=true; NATIVE_GUI=false; PRODUCT_ATOMICITY=false')


if __name__ == '__main__':
    def cancelled(number, _frame):
        raise Rejected('deadline' if number == signal.SIGALRM else 'cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(number, cancelled)
    signal.setitimer(signal.ITIMER_REAL, 1140)
    try:
        main()
    except BaseException:
        raise SystemExit(1) from None
