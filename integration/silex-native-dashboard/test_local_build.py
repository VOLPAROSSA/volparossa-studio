# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only original-dashboard build admission controls; no carrier/app run."""
import copy
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('original_local_build', Path(__file__).with_name('local_build.py'))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def composition():
    rows = [dict(path=name, bytes=100, sha256='b' * 64) for name in sorted(M.ASSETS)]
    value = dict(schema=1, operation='original_dashboard_asset_composition', manifest_sha256='a' * 64,
        assets=rows, asset_count=3, embedded_assets_license='GPL-3.0-only', application_executed=False,
        native_gui_verified=False, real_server_crud=False, redistribution_acceptance=False, publication_authorized=False)
    return value, copy.deepcopy(rows)


class NativeRejected(RuntimeError):
    def __init__(self, message):
        self.kind = 'sdk_rejected'
        super().__init__(message)


def metadata_native(groups, failure=None, count=563):
    def actor(*_args, **_kwargs):
        groups.append(failure is None)
        if failure is not None:
            raise failure
        return b'full metadata'
    return SimpleNamespace(actor=Mock(side_effect=actor),
        SUPPORT=SimpleNamespace(metadata=Mock(), read=Mock(return_value=b'pinned lock'),
                                ledger=Mock(return_value=(1, {i: None for i in range(count)}))))


class LocalBuildTests(unittest.TestCase):
    def test_composition_is_exact_three_original_assets_and_all_authority_flags_false(self):
        value, rows = composition()
        self.assertEqual(M.check_composition(value, 'a' * 64, rows), rows)
        for key, changed in [('asset_count', True), ('schema', True), ('application_executed', True),
                             ('publication_authorized', 0), ('manifest_sha256', 'c' * 64),
                             ('embedded_assets_license', 'unverified')]:
            bad = copy.deepcopy(value)
            bad[key] = changed
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                M.check_composition(bad, 'a' * 64, rows)

    def test_changed_duplicate_external_or_extra_asset_never_matches_descriptor(self):
        value, expected = composition()
        variants = []
        for key, changed in [('sha256', 'c' * 64), ('bytes', 101), ('path', 'https://external.invalid/a')]:
            bad = copy.deepcopy(value)
            bad['assets'][0][key] = changed
            variants.append(bad)
        bad = copy.deepcopy(value); bad['assets'][0] = bad['assets'][1]; variants.append(bad)
        bad = copy.deepcopy(value); bad['assets'].append(copy.deepcopy(bad['assets'][0])); variants.append(bad)
        bad = copy.deepcopy(value); bad['assets'][0]['git_blob'] = 'd' * 40; variants.append(bad)
        for bad in variants:
            with self.subTest(rows=bad['assets']), self.assertRaises(RuntimeError):
                M.check_composition(bad, 'a' * 64, expected)

    def test_extras_include_all_five_old_and_four_fs_new_files(self):
        before = {'Cargo.lock': {}, 'native.rs': {}, 'old.rs': {}, 'fs.rs': {}}
        base = {'files': dict.fromkeys(['old.rs'] + ['base/new' + str(i) for i in range(5)])}
        overlay = {'files': dict.fromkeys(['Cargo.lock', 'native.rs'])}
        fs = {'files': dict.fromkeys(['fs.rs'] + ['fs/new' + str(i) for i in range(4)])}
        self.assertEqual(M.full_extras(before, base, overlay, fs),
                         sorted(['base/new' + str(i) for i in range(5)] + ['fs/new' + str(i) for i in range(4)]))

    def test_full_metadata_has_one_owned_group_and_no_no_deps_shortcut(self):
        groups = []
        native = metadata_native(groups)
        report = {}
        observed = M.metadata(native, Path('/compiler'), {}, Path('/source'), 100, groups, object(), 'a' * 64, report)
        self.assertIs(observed, report)
        self.assertEqual(report['package_records'], 563)
        self.assertEqual(report['owned_group_count'], 1)
        self.assertIs(report['owned_groups_joined'], True)
        self.assertIs(report['offline_locked_metadata_passed'], True)
        self.assertEqual(native.actor.call_args.args[0], ['/compiler/bin/cargo', 'metadata', '--offline', '--locked', '--format-version=1'])
        self.assertEqual(native.actor.call_args.kwargs['capture'], 8 * 1024 * 1024)
        native.SUPPORT.metadata.assert_called_once_with(b'full metadata', Path('/source'))

    def test_metadata_failure_preserves_original_and_retains_unconfirmed_group_observation(self):
        groups = []
        original = NativeRejected('metadata child failed')
        native = metadata_native(groups, failure=original)
        report = {}
        with self.assertRaises(NativeRejected) as caught:
            M.metadata(native, Path('/compiler'), {}, Path('/source'), 100, groups, object(), 'a' * 64, report)
        self.assertIs(caught.exception, original)
        self.assertEqual(report['owned_group_count'], 1)
        self.assertIs(report['owned_groups_joined'], False)
        self.assertEqual(report['status'], 'failed')
        self.assertIs(report['offline_locked_metadata_passed'], False)

    def test_metadata_changed_ledger_count_and_reused_group_scope_are_rejected(self):
        for preexisting, count in (([], 562), ([True], 563)):
            groups = list(preexisting)
            native = metadata_native(groups, count=count)
            with self.subTest(count=count, groups=preexisting), self.assertRaises(RuntimeError):
                M.metadata(native, Path('/compiler'), {}, Path('/source'), 100, groups, object(), 'a' * 64, {})
            if preexisting:
                native.actor.assert_not_called()

    def test_frontend_uses_only_fixed_frozen_ignore_scripts_then_client_public_with_rechecks(self):
        events = []
        def actor(argv, *_args, **_kwargs):
            events.append(('actor', argv))
        native = SimpleNamespace(actor=Mock(side_effect=actor), frontend_inventory=Mock(return_value=[{'bytes': 1}]))
        result = M.build_frontend(native, Path('/node'), Path('/pnpm'), Path('/work'), Path('/source'), {},
                                 100, [], object(), lambda: events.append(('check', None)))
        self.assertEqual(result, [{'bytes': 1}])
        self.assertEqual([kind for kind, _ in events], ['actor', 'check'] * 3)
        install = events[0][1]
        self.assertIn('--frozen-lockfile', install)
        self.assertIn('--ignore-scripts', install)
        self.assertIn('--config.manage-package-manager-versions=false', install)
        self.assertEqual(events[2][1][-1], 'build:client')
        self.assertEqual(events[4][1][-1], 'build:public')
        native.frontend_inventory.assert_called_once_with(Path('/source/dist/client'))

    def test_failed_source_recheck_after_install_prevents_any_frontend_build(self):
        native = SimpleNamespace(actor=Mock(), frontend_inventory=Mock())
        failure = RuntimeError('source changed')
        with self.assertRaises(RuntimeError) as caught:
            M.build_frontend(native, Path('/node'), Path('/pnpm'), Path('/work'), Path('/source'), {},
                             100, [], object(), Mock(side_effect=failure))
        self.assertIs(caught.exception, failure)
        native.actor.assert_called_once()
        native.frontend_inventory.assert_not_called()

    def test_pinned_helpers_are_preserved_byte_exact(self):
        for path, expected in M.PINS.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
        self.assertEqual(hashlib.sha256((M.HERE / 'compose.py').read_bytes()).hexdigest(), M.COMPOSE_SHA256)

    def test_actual_shared_source_checker_uses_initialized_verified_host_hook_without_baseline_admit(self):
        spec = importlib.util.spec_from_file_location('local_build_shared_native_test', M.BOOTSTRAP / 'native_build.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        prepare = native.load('local_build_shared_prepare_test', M.BOOTSTRAP / 'prepare.py')
        source = Path('/fixed/silex')
        extra = 'server-rust/src/connectors/fs_storage/metadata.rs'
        before = {'ordinary.rs': {'sha256': 'a' * 64}}
        def git(arguments, *_args):
            return extra.encode() + b'\0' if 'ls-files' in arguments else b''
        def lock_read(path, _maximum):
            return b'lock' if path.name == 'Cargo.lock' else b'pnpm'
        with patch.dict(M.sys.modules):
            M.sys.modules.pop('native_build_prepare', None)
            with patch.object(prepare, 'hosted_guard') as guard, patch.object(prepare, 'check_source') as old_admit:
                with patch.object(native, 'git', side_effect=git), patch.object(native, 'tracked', return_value=before), \
                        patch.object(native, 'read_file', side_effect=lock_read), patch.object(native, 'dashboard_unchanged'), \
                        patch.object(native, 'NATIVE_LOCK', hashlib.sha256(b'lock').hexdigest()), \
                        patch.object(native, 'PNPM_LOCK', hashlib.sha256(b'pnpm').hexdigest()):
                    with self.assertRaises(KeyError):
                        native.source_check(source, before, [extra], [], {}, 100, [], object())
                def install(name, path):
                    self.assertEqual(name, 'native_build_prepare')
                    self.assertEqual(path, M.BOOTSTRAP / 'prepare.py')
                    M.sys.modules[name] = prepare
                    return prepare
                with patch.object(native, 'load', side_effect=install):
                    M.initialize_source_hook(native, source)
                with patch.object(native, 'git', side_effect=git), patch.object(native, 'tracked', return_value=before), \
                        patch.object(native, 'read_file', side_effect=lock_read), patch.object(native, 'dashboard_unchanged'), \
                        patch.object(native, 'NATIVE_LOCK', hashlib.sha256(b'lock').hexdigest()), \
                        patch.object(native, 'PNPM_LOCK', hashlib.sha256(b'pnpm').hexdigest()):
                    self.assertEqual(native.source_check(source, before, [extra], [], {}, 100, [], object()), [])
                self.assertEqual(guard.call_count, 2)
                old_admit.assert_not_called()

    def test_wrong_profile_is_refused_before_source_import_or_any_sdk_work(self):
        with patch.object(M.sys, 'argv', [str(M.HERE / 'local_build.py')]), \
                patch.dict(M.os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/unapproved'}), \
                patch('importlib.util.spec_from_file_location') as loader, self.assertRaises(RuntimeError):
            M.main()
        loader.assert_not_called()

    def test_cancellation_kind_is_closed_and_has_no_raw_external_message(self):
        for kind in ('cancelled', 'deadline'):
            error = M.Cancelled(kind)
            self.assertEqual(error.kind, kind)
            self.assertEqual(str(error), 'original dashboard build interrupted')
        with self.assertRaises(ValueError):
            M.Cancelled('raw private failure')

    def test_sdk_denial_precedes_source_mutation_carrier_or_owned_build_tree(self):
        original = NativeRejected('normal SDK receipt required')
        terminal = SimpleNamespace(finish=Mock(side_effect=lambda _a, _w, _r, _g, primary, **_k: primary))
        fetch = SimpleNamespace(admission=Mock(return_value=(Path('/private'), 'a' * 40)))
        installer = SimpleNamespace(MANIFEST='a' * 64, records_from_manifest=Mock(return_value={}))
        native = SimpleNamespace(SDK_MANIFEST='a' * 64, SUPPORT=SimpleNamespace(UPSTREAM='b' * 40, json_value=Mock(return_value={})),
            read_file=Mock(return_value=b'{}'), sdk_receipts=Mock(side_effect=original),
            compiler=Mock(), export_carrier=Mock(), actor=Mock(), Rejected=NativeRejected)
        def load(_name, path):
            return {'fetch_sdk.py': fetch, 'check.py': terminal, 'install_sdk.py': installer}[path.name]
        native.load = Mock(side_effect=load)
        spec = SimpleNamespace(name='fake_sdk_gate', loader=SimpleNamespace(exec_module=Mock()))
        compose_digest = hashlib.sha256((M.HERE / 'compose.py').read_bytes()).hexdigest()
        with patch.object(M, 'COMPOSE_SHA256', compose_digest), \
                patch.object(M.sys, 'argv', [str(M.HERE / 'local_build.py')]), \
                patch.dict(M.os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch',
                    'GITHUB_REF': 'refs/heads/feature/native-local-dashboard-20261029', 'GITHUB_WORKSPACE': '/workspace'}), \
                patch('importlib.util.spec_from_file_location', return_value=spec), \
                patch('importlib.util.module_from_spec', return_value=native), \
                patch.object(M.Path, 'exists', return_value=False), \
                patch.object(M.Path, 'is_symlink', return_value=False), \
                patch.object(M.Path, 'mkdir') as mkdir, self.assertRaises(NativeRejected) as caught:
            M.main()
        self.assertIs(caught.exception, original)
        mkdir.assert_not_called()
        native.compiler.assert_not_called()
        native.export_carrier.assert_not_called()
        native.actor.assert_not_called()
        self.assertEqual([call.args[1].name for call in native.load.call_args_list], ['fetch_sdk.py', 'check.py', 'install_sdk.py'])

    def test_handoff_attempts_terminal_after_accounting_and_repeated_cancellation_preserving_first_failure(self):
        for original in (None, NativeRejected('original actor failure')):
            with self.subTest(original=original is not None):
                accounting = M.Cancelled('cancelled')
                late = M.Cancelled('deadline')
                class Report(dict):
                    def update(self, *args, **kwargs):
                        if 'main_owned_group_count' in kwargs:
                            raise accounting
                        return super().update(*args, **kwargs)
                report = Report(status='failed')
                def finish(_artifact, _work, actual, groups, primary, **_conditions):
                    self.assertEqual(groups, [True, False])
                    self.assertIs(primary, original or accounting)
                    actual['status'] = 'failed'
                    return primary
                terminal = SimpleNamespace(finish=Mock(side_effect=finish))
                old_mask = {M.signal.SIGHUP}
                def mask(which, value):
                    if which == M.signal.SIG_SETMASK:
                        self.assertEqual(value, old_mask)
                        raise late
                    return old_mask
                with patch.object(M.signal, 'pthread_sigmask', side_effect=mask) as masks, \
                        patch.object(M.signal, 'sigpending', return_value={M.signal.SIGTERM, M.signal.SIGALRM}):
                    result = M.finish_build(terminal, Path('/artifact'), Path('/work'), report,
                                            [True], [False], original, ready=False)
                self.assertIs(result, original or accounting)
                terminal.finish.assert_called_once()
                self.assertEqual([call.args[0] for call in masks.call_args_list],
                                 [M.signal.SIG_BLOCK, M.signal.SIG_SETMASK])

    def test_queued_precommit_signal_fails_but_postcommit_cancel_cannot_negate_valid_terminal_result(self):
        for queued in (True, False):
            with self.subTest(queued_before_commit=queued):
                report = {'status': 'failed'}
                def finish(_artifact, _work, actual, groups, primary, **_conditions):
                    self.assertEqual(groups, [True, True])
                    if queued:
                        self.assertIsInstance(primary, M.Cancelled)
                        self.assertEqual(primary.kind, 'deadline')
                    else:
                        self.assertIsNone(primary)
                    actual['status'] = 'failed' if primary is not None else 'passed'
                    return primary
                terminal = SimpleNamespace(finish=Mock(side_effect=finish))
                def mask(which, _value):
                    if which == M.signal.SIG_SETMASK:
                        raise M.Cancelled('cancelled')
                    return set()
                with patch.object(M.signal, 'pthread_sigmask', side_effect=mask), \
                        patch.object(M.signal, 'sigpending', return_value={M.signal.SIGALRM} if queued else set()):
                    result = M.finish_build(terminal, Path('/artifact'), Path('/work'), report,
                                            [True], [True], None, ready=True)
                if queued:
                    self.assertIsInstance(result, M.Cancelled)
                    self.assertEqual(report['status'], 'failed')
                else:
                    self.assertIsNone(result)
                    self.assertEqual(report['status'], 'passed')
                self.assertEqual(report['main_owned_group_count'], 1)
                terminal.finish.assert_called_once()

    def test_metadata_finalizer_retains_actor_failure_or_first_accounting_cancel_and_restores_mask(self):
        for original in (None, NativeRejected('original metadata actor failure')):
            with self.subTest(actor_failed=original is not None):
                accounting = M.Cancelled('cancelled')
                late = M.Cancelled('deadline')
                class Report(dict):
                    def update(self, *args, **kwargs):
                        if set(kwargs) == {'owned_group_count', 'owned_groups_joined'}:
                            raise accounting
                        return super().update(*args, **kwargs)
                report = Report()
                groups = []
                native = metadata_native(groups, failure=original)
                def mask(which, _value):
                    if which == M.signal.SIG_SETMASK:
                        raise late
                    return set()
                with patch.object(M.signal, 'pthread_sigmask', side_effect=mask) as masks, \
                        patch.object(M.signal, 'sigpending', return_value={M.signal.SIGALRM}), \
                        self.assertRaises(BaseException) as caught:
                    M.metadata(native, Path('/compiler'), {}, Path('/source'), 100, groups, object(), 'a' * 64, report)
                self.assertIs(caught.exception, original or accounting)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual([call.args[0] for call in masks.call_args_list],
                                 [M.signal.SIG_BLOCK, M.signal.SIG_SETMASK])


if __name__ == '__main__':
    unittest.main()
