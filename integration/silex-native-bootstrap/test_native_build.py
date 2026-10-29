#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only private build controls; no dependency, compiler or application execution."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('private_native_build', HERE / 'native_build.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def public_file(path, raw, mode=0o600):
    path.write_bytes(raw)
    path.chmod(mode)


class NativeBuildTests(unittest.TestCase):
    def test_dashboard_descriptor_pins_genuine_nine_files_and_keeps_license_runtime_closed(self):
        raw = (HERE / 'dashboard-source.json').read_bytes()
        rows = M.dashboard_manifest(raw)
        self.assertEqual(len(rows), 9)
        self.assertEqual(sum(row['bytes'] for row in rows), 79203)
        changed = json.loads(raw)
        for key, bad in (('redistribution_acceptance', True), ('native_runtime_acceptance', True),
                         ('commit', '0' * 40), ('public_bytes', True)):
            value = copy.deepcopy(changed)
            value[key] = bad
            with self.assertRaises(M.Rejected):
                M.dashboard_manifest(json.dumps(value).encode())
        for bad in ('../outside', '/absolute', 'public/../outside', 'public/extra'):
            value = copy.deepcopy(changed)
            value['public_assets'][0]['path'] = bad
            with self.assertRaises(M.Rejected):
                M.dashboard_manifest(json.dumps(value).encode())
        with self.assertRaises(M.Rejected):
            M.dashboard_manifest(raw + b'changed')

    def test_dashboard_gitlink_is_exact_and_never_treated_as_regular_source_file(self):
        correct = f'160000 commit {M.DASHBOARD_COMMIT}\tsilex-dashboard-2026\0'.encode()
        M.gitlink(correct)
        for changed in (correct.replace(b'160000 commit', b'100644 blob'),
                        correct.replace(M.DASHBOARD_COMMIT.encode(), b'0' * 40),
                        correct.replace(b'silex-dashboard-2026', b'other'), correct + b'extra'):
            with self.assertRaises(M.Rejected):
                M.gitlink(changed)

    def test_actual_asset_copy_is_private_no_clobber_and_refuses_aliases_or_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / 'source', root / 'output'
            raw = b'public synthetic dashboard asset'
            public_file(source, raw)
            row = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            M.copy_asset(source, output, row)
            self.assertEqual(output.read_bytes(), raw)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                M.copy_asset(source, output, row)
            before = source.stat()
            fields = ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
            changed = SimpleNamespace(**{name: getattr(before, name) for name in fields})
            changed.st_ctime_ns += 1
            with mock.patch.object(M.os, 'fstat', side_effect=[before, changed]), self.assertRaises(M.Rejected):
                M.copy_asset(source, root / 'changed-during-read', row)
            self.assertFalse((root / 'changed-during-read').exists())
            alias = root / 'alias'
            alias.symlink_to(source)
            with self.assertRaises(M.Rejected):
                M.copy_asset(alias, root / 'must-not-exist', row)
            alias.unlink()
            os.link(source, alias)
            with self.assertRaises(M.Rejected):
                M.copy_asset(source, root / 'must-not-exist', row)
            alias.unlink()
            public_file(source, b'changed synthetic bytes')
            with self.assertRaises(M.Rejected):
                M.copy_asset(source, root / 'must-not-exist', row)
            self.assertFalse((root / 'must-not-exist').exists())

    def test_only_four_generated_schema_records_may_differ_and_locked_inputs_stay_exact(self):
        before = {'Cargo.lock': {'sha256': 'pinned'}, 'src/main.rs': {'sha256': 'code'}}
        before.update({name: {'sha256': 'before'} for name in M.SCHEMAS})
        after = copy.deepcopy(before)
        selected = sorted(M.SCHEMAS)[0]
        after[selected] = {'sha256': 'generated'}
        self.assertEqual(M.compare_sources(before, after),
                         [{'path': selected, 'before': before[selected], 'after': after[selected]}])
        for path in ('Cargo.lock', 'src/main.rs'):
            changed = copy.deepcopy(after)
            changed[path] = {'sha256': 'unexpected'}
            with self.assertRaises(M.Rejected):
                M.compare_sources(before, changed)
        changed = dict(after, unreviewed={'sha256': 'extra'})
        with self.assertRaises(M.Rejected):
            M.compare_sources(before, changed)

    def test_sdk_gate_refuses_stale_revision_failed_cleanup_and_false_native_authority(self):
        installer = M.load('native_build_test_sdk', HERE / 'install_sdk.py')
        records = installer.records_from_manifest((HERE / 'ubuntu-sdk.json').read_bytes())
        hashes = installer.expected_hashes(records)
        revision = 'a' * 40
        outer = dict(schema=1, mode='native-sdk-offline-install', status='passed', stage='complete',
                     sdk_manifest_sha256=M.SDK_MANIFEST, packages_installed=True, sdk_installed=True,
                     studio_revision=revision, verified_package_count=182, archive_bytes=63772228, hashes=hashes,
                     admission_diagnostic={'substage': 'complete'},
                     cleanup={'owned_groups_joined': True, 'owned_group_count': 1, 'root_cache_retained': True,
                              'package_rollback_attempted': False}, **dict.fromkeys(M.SDK_FALSE, False))
        root = dict(schema=1, mode='native-sdk-offline-root-install', status='passed', stage='complete',
                    sdk_manifest_sha256=M.SDK_MANIFEST, packages_installed=True, sdk_installed=True,
                    studio_revision=revision, run_id='123', run_attempt='1', verified_package_count=182,
                    hashes=hashes, owned_group_count=6, planned_package_count=182, plan_sha256='c' * 64,
                    **dict.fromkeys(M.SDK_FALSE, False))
        root['admission_diagnostic'] = {'substage': 'complete'}
        root.update(dict.fromkeys(('network_namespace_isolated', 'root_archive_cache_verified',
            'post_install_exact_versions', 'dpkg_audit_clean', 'installation_attempted', 'policy_created',
            'policy_restored', 'root_cache_retained', 'owned_groups_joined'), True))
        self.assertEqual(len(root), 31)
        with mock.patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
            M.sdk_receipts(outer, root, revision, records, installer)
            M.sdk_receipts(outer, dict(root, planned_package_count=0), revision, records, installer)
            for key, bad in (('studio_revision', 'b' * 40), ('native_build', True), ('schema', True),
                             ('mode', 'native-sdk-admission'), ('sdk_installed', False),
                             ('admission_diagnostic', {'substage': 'admission'}),
                             ('private_path', '/not-a-receipt-field')):
                changed = copy.deepcopy(outer)
                changed[key] = bad
                with self.assertRaises((M.Rejected, installer.Rejected)):
                    M.sdk_receipts(changed, root, revision, records, installer)
            for key, bad in (('owned_groups_joined', False), ('policy_restored', False), ('run_id', '124'),
                             ('owned_group_count', 5),
                             ('planned_package_count', True), ('planned_package_count', -1),
                             ('planned_package_count', 183), ('planned_package_count', '182'),
                             ('plan_sha256', 'A' * 64), ('plan_sha256', 'c' * 63), ('plan_sha256', None)):
                changed = copy.deepcopy(root)
                changed[key] = bad
                with self.assertRaises((M.Rejected, installer.Rejected)):
                    M.sdk_receipts(outer, changed, revision, records, installer)

    def test_frontend_inventory_rejects_links_and_binds_actual_generated_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'js').mkdir()
            public_file(root / 'index.html', b'public generated HTML')
            public_file(root / 'js/main.js', b'public generated JavaScript')
            before = M.frontend_inventory(root)
            self.assertEqual(len(before), 2)
            public_file(root / 'index.html', b'changed generated HTML')
            self.assertNotEqual(M.frontend_inventory(root), before)
            (root / 'link.js').symlink_to(root / 'js/main.js')
            with self.assertRaises(M.Rejected):
                M.frontend_inventory(root)

    def test_release_command_is_fixed_offline_without_bundler_installer_or_application(self):
        command = M.release_command(Path('/approved-temporary'))
        self.assertEqual(command, ['/approved-temporary/volparossa-rust-1.99.1/bin/cargo',
            'build', '--offline', '--locked', '--release', '-p', 'silex-desktop', '--bin', 'silex-desktop'])
        self.assertNotIn('tauri', command)
        self.assertNotIn('install', command)

    def test_fixed_no_argument_entry_refuses_source_or_command_overrides_before_admission(self):
        for arguments in (['--source', '/unapproved'], ['--build-command', 'unapproved']):
            with mock.patch('sys.argv', [str(HERE / 'native_build.py'), *arguments]), \
                    mock.patch.object(M, 'admit') as admit, mock.patch.object(M, 'actor') as actor, \
                    mock.patch('builtins.print'), self.assertRaises(M.Rejected) as caught:
                M.main()
            self.assertEqual(caught.exception.kind, 'admission')
            admit.assert_not_called()
            actor.assert_not_called()

    def test_read_only_elf_inspection_accepts_cargo_hardlink_without_relaxing_source_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'silex-desktop'
            raw = bytearray(64)
            raw[:6] = b'\x7fELF\x02\x01'
            raw[16:18], raw[18:20] = (3).to_bytes(2, 'little'), (62).to_bytes(2, 'little')
            public_file(path, raw, 0o700)
            alias = root / 'cargo-deps-hardlink'
            os.link(path, alias)
            observed = M.inspect_elf(path)
            self.assertEqual(observed['links'], 2)
            self.assertEqual(observed['sha256'], hashlib.sha256(raw).hexdigest())
            with self.assertRaises(M.Rejected):
                M.file_hash(path, 1024)
            self.assertEqual(path.read_bytes(), raw)
            alias.unlink()
            alias.symlink_to(path)
            with self.assertRaises(M.Rejected):
                M.inspect_elf(alias)
            raw[18:20] = (183).to_bytes(2, 'little')
            public_file(path, raw, 0o700)
            with self.assertRaises(M.Rejected):
                M.inspect_elf(path)

    def test_actor_preserves_primary_and_drains_owned_group_during_repeated_cancellation(self):
        primary = M.Rejected('cancelled')
        stdout, stderr = mock.Mock(), mock.Mock()
        stdout.fileno.return_value, stderr.fileno.return_value = 10, 11
        process = SimpleNamespace(pid=12345, stdout=stdout, stderr=stderr)
        lifecycle = SimpleNamespace(start_group=mock.Mock(return_value=(process, 'owned identity')))
        numbers = (M.signal.SIGINT, M.signal.SIGTERM, M.signal.SIGHUP, M.signal.SIGALRM)
        handlers = dict.fromkeys(numbers, lambda _number, _frame: None)
        original = dict(handlers)

        def set_handler(number, handler):
            previous = handlers[number]
            handlers[number] = handler
            return previous

        def drain(child, identity, **_options):
            self.assertIs(child, process)
            self.assertEqual(identity, 'owned identity')
            for number in numbers:
                handlers[number](number, None)
            return {'leader_joined': True, 'live_group_drained': True}

        lifecycle.drain_group = mock.Mock(side_effect=drain)
        selector = mock.MagicMock()
        selector.__enter__.return_value = selector
        selector.get_map.return_value = {10: True}
        selector.select.return_value = [(SimpleNamespace(fd=10, fileobj=stdout), None)]
        groups = []
        with mock.patch.object(M.selectors, 'DefaultSelector', return_value=selector), \
                mock.patch.object(M.os, 'set_blocking'), mock.patch.object(M.os, 'read', side_effect=primary), \
                mock.patch.object(M.signal, 'getsignal', side_effect=handlers.__getitem__), \
                mock.patch.object(M.signal, 'signal', side_effect=set_handler), self.assertRaises(M.Rejected) as caught:
            M.actor(['/fixed/build-command'], {}, Path('/public-source'), M.time.monotonic() + 30,
                    groups, lifecycle)
        self.assertIs(caught.exception, primary)
        self.assertEqual(groups, [True])
        self.assertEqual(handlers, original)
        lifecycle.drain_group.assert_called_once()
        stdout.close.assert_called_once()
        stderr.close.assert_called_once()

    def test_compiler_diagnostic_projects_only_codes_counts_flags_and_log_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / 'logs').mkdir()
            raw = (b'error[E0308]: /private/customer/input.html https://private.invalid/token\n'
                   b'  --> /private/source.rs:4:2\n'
                   b'error[E0308]: repeated private message <html>not retained</html>\n'
                   b'error: linking with `cc` failed: exit status: 1\n'
                   b'  The system library `gtk+-3.0` required by crate `gdk-sys` was not found.\n'
                   b'error[E0432]: unresolved public sample\n'
                   b'private payload E9999 is not a compiler error marker\n')
            public_file(work / 'logs/native-cargo.log', raw)
            observed = M.compiler_diagnostic(work)
            self.assertEqual(observed, dict(schema=1, status='captured', rust_error_codes=['E0308', 'E0432'],
                error_lines=4, pkg_config_missing=True, linker_failed=True, compiler_error=True,
                log_sha256=hashlib.sha256(raw).hexdigest(), log_bytes=len(raw),
                raw_log_durably_retained=False, raw_log_artifact=False))
            serialized = json.dumps(observed)
            for private in ('/private/', 'https://private.invalid', '<html>', 'gtk+-3.0', 'gdk-sys', 'E9999'):
                self.assertNotIn(private, serialized)
            public_file(work / 'logs/native-cargo.log', b'')
            empty = M.compiler_diagnostic(work)
            self.assertEqual(empty['status'], 'captured')
            self.assertEqual(empty['log_bytes'], 0)
            self.assertEqual(empty['log_sha256'], hashlib.sha256(b'').hexdigest())
            self.assertEqual(empty['error_lines'], 0)

    def test_restore_phase_cancellation_restores_every_handler_and_accounts_before_unblocking(self):
        for primary in (M.Rejected('child_failed'), None):
            first_late = M.Rejected('cancelled')
            second_late = M.Rejected('deadline')
            stdout, stderr = mock.Mock(), mock.Mock()
            stdout.fileno.return_value, stderr.fileno.return_value = 10, 11
            process = SimpleNamespace(pid=12345, stdout=stdout, stderr=stderr)
            lifecycle = SimpleNamespace(start_group=mock.Mock(return_value=(process, 'owned identity')),
                drain_group=mock.Mock(return_value={'leader_joined': True, 'live_group_drained': True}))
            numbers = (M.signal.SIGINT, M.signal.SIGTERM, M.signal.SIGHUP, M.signal.SIGALRM)
            original = dict.fromkeys(numbers, lambda _number, _frame: None)
            handlers = dict(original)
            restored = []
            old_mask = {M.signal.SIGUSR1}
            blocked = set(old_mask)
            groups = []

            def set_handler(number, handler):
                previous = handlers[number]
                handlers[number] = handler
                if handler is original[number]:
                    self.assertTrue(set(numbers) <= blocked)
                    restored.append(number)
                    if len(restored) == 1:
                        raise first_late  # Also covers an already queued Python callback.
                return previous

            def mask(how, values):
                previous = set(blocked)
                if how == M.signal.SIG_BLOCK:
                    blocked.update(values)
                    return previous
                self.assertEqual(how, M.signal.SIG_SETMASK)
                self.assertEqual(groups, [True])
                self.assertEqual(restored, list(numbers))
                blocked.clear()
                blocked.update(values)
                raise second_late  # Pending OS cancellation delivered at unmask.

            selector = mock.MagicMock()
            selector.__enter__.return_value = selector
            selector.get_map.side_effect = [{10: True}, {}]
            selector.select.return_value = [(SimpleNamespace(fd=10, fileobj=stdout), None)]
            with mock.patch.object(M.selectors, 'DefaultSelector', return_value=selector), \
                    mock.patch.object(M.os, 'set_blocking'), \
                    mock.patch.object(M.os, 'read', return_value=b'', side_effect=primary), \
                    mock.patch.object(M.os, 'waitid', return_value=SimpleNamespace(
                        si_pid=process.pid, si_code=M.os.CLD_EXITED, si_status=0)), \
                    mock.patch.object(M.signal, 'getsignal', side_effect=handlers.__getitem__), \
                    mock.patch.object(M.signal, 'signal', side_effect=set_handler), \
                    mock.patch.object(M.signal, 'pthread_sigmask', side_effect=mask), \
                    self.assertRaises(M.Rejected) as caught:
                M.actor(['/fixed/build-command'], {}, Path('/public-source'), M.time.monotonic() + 30,
                        groups, lifecycle)
            self.assertIs(caught.exception, primary if primary is not None else first_late)
            self.assertEqual(handlers, original)
            self.assertEqual(blocked, old_mask)
            self.assertEqual(groups, [True])
            lifecycle.drain_group.assert_called_once()
            stdout.close.assert_called_once()
            stderr.close.assert_called_once()

    def test_compiler_diagnostic_clipping_or_unsafe_log_never_returns_partial_observations(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / 'logs').mkdir()
            path = work / 'logs/native-cargo.log'
            for raw in (b''.join(f'error[E{number:04}]: public sample\n'.encode() for number in range(16)),
                        b'error: public sample\n' * 256):
                public_file(path, raw)
                self.assertEqual(M.compiler_diagnostic(work)['status'], 'captured')
                clipped = M.compiler_diagnostic(work, clipped=True)
                self.assertEqual(clipped['status'], 'clipped')
                self.assertEqual(clipped['rust_error_codes'], [])
                self.assertIsNone(clipped['error_lines'])
            for raw in (b''.join(f'error[E{number:04}]: public sample\n'.encode() for number in range(17)),
                        b'error: public sample\n' * 257):
                public_file(path, raw)
                observed = M.compiler_diagnostic(work)
                self.assertEqual(observed['status'], 'clipped')
                self.assertEqual(observed['rust_error_codes'], [])
                self.assertIsNone(observed['error_lines'])
                self.assertFalse(observed['compiler_error'])
                self.assertFalse(observed['linker_failed'])
                self.assertFalse(observed['pkg_config_missing'])
                self.assertEqual(observed['log_sha256'], hashlib.sha256(raw).hexdigest())
            with path.open('wb') as stream:
                stream.truncate(M.MAX_NATIVE_LOG + 1)
            self.assertEqual(M.compiler_diagnostic(work)['status'], 'unavailable')
            path.unlink()
            private = work / 'private-payload'
            public_file(private, b'private data is never a log input')
            path.symlink_to(private)
            observed = M.compiler_diagnostic(work)
            self.assertEqual(observed['status'], 'unavailable')
            self.assertIsNone(observed['log_sha256'])
            self.assertIsNone(observed['log_bytes'])


if __name__ == '__main__':
    unittest.main()
