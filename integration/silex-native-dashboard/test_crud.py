# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only public CRUD protocol/ownership controls. No browser or Rust run."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


P = module('crud_protocol_control', 'crud_protocol.py')
M = module('crud_control', 'crud.py')
R = module('crud_runtime_control', 'crud_runtime.py')
IDS = ['00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002']


def browser(phase='first'):
    return dict(schema=1, phase=phase, status='passed',
        steps=['empty', 'create', 'rename', 'duplicate'] if phase == 'first'
              else ['persisted_list', 'delete_duplicate', 'delete_original', 'empty'],
        sandbox_requested=True, browser_closed=True, context_closed=True, external_denied=0,
        requests=12, ids=list(IDS), metadata_before_sha256='a' * 64 if phase == 'first' else None,
        metadata_after_sha256='b' * 64 if phase == 'first' else None,
        other_bytes_preserved=phase == 'first', typed_rename_only=True, browser_version='145.0.1.2',
        failure_action=None, failure_http_status=None, **{key: False for key in P.CHROME_FLAGS})


def runtime():
    return dict(schema=1, status='passed', stage='complete', runtime_revision='a' * 40,
        isolated_net=True, isolated_pid=True, original_nonroot_uid=True, capabilities_zero=True,
        no_new_privileges=True, mount_isolation_proven=False, ipc_isolation_proven=False,
        proc_mount_isolation_proven=False, denied_egress_containment=True, no_external_attempts_proven=False,
        server_runs=2, browser_runs=2, browser_receipts=[browser(), browser('second')], http_denials=42,
        outside_unchanged=True, persistence=True, owned_groups_started=4, owned_groups_joined=True,
        descendants_gone=True, listeners_closed=True, assets_unchanged=True, public_fixture_only=True,
        first_failure=None, log_observations=[dict(case_id=label, bytes=0,
            sha256=hashlib.sha256(b'').hexdigest()) for label in
            ('server-first', 'browser-first', 'server-second', 'browser-second')])


class CrudTests(unittest.TestCase):
    def test_fixed_offline_server_example_command_has_no_desktop_sdk_or_production_cli(self):
        self.assertEqual(list(map(str, M.build_command(Path('/compiler')))),
            ['/compiler/bin/cargo', 'build', '--offline', '--locked', '-p', 'silex-server',
             '--example', 'volparossa_dashboard_crud'])

    def test_wrapper_argv_and_exact_reviewed_core_identity_are_closed(self):
        self.assertEqual(list(map(str, M.wrapper_command(Path('/core'), Path('/tmp/studio-export-crud-public')))),
            ['/core/scripts/run-isolated-test.sh', '--studio-nonroot-command', '/usr/bin/python3',
             'studio_export', 'VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS', 'loopback', '-B',
             '/tmp/studio-export-crud-public/fixture/runtime.py'])
        self.assertEqual(P.CORE, 'e58d1c9bb4412ee15ad68033f1eb051494a87725')
        self.assertEqual(P.WRAPPER_SHA, '644bbcbc869bb69eb0b1611de89a83e7ff6aa635ee993042e05ec16fb8d387e0')

    def test_outer_wrapper_reserve_outlives_fixed_work_and_kill_deadlines_without_retry(self):
        self.assertEqual(M.WRAPPER_SECONDS, 140)
        self.assertGreater(M.WRAPPER_SECONDS, 120 + 5)
        self.assertLess(M.WRAPPER_SECONDS, 1500)
        core, work = Path('/core'), Path('/tmp/studio-export-crud-public')
        groups, lifecycle, env = [], object(), {'PUBLIC': 'closed fixture'}
        native = SimpleNamespace(actor=Mock(return_value=b'owned wrapper observation'))
        self.assertEqual(M.run_wrapper(native, core, work, env, 1500, groups, lifecycle),
                         b'owned wrapper observation')
        native.actor.assert_called_once_with(M.wrapper_command(core, work), env, M.ROOT,
            1500, groups, lifecycle, log=work / 'logs/namespace.log', seconds=140)
        original = RuntimeError('original owned wrapper failure')
        native.actor = Mock(side_effect=original)
        with self.assertRaises(RuntimeError) as caught:
            M.run_wrapper(native, core, work, env, 1500, groups, lifecycle)
        self.assertIs(caught.exception, original)
        native.actor.assert_called_once()

    def test_duplicate_nonfinite_and_oversize_private_json_fail_closed(self):
        for raw in (b'{"schema":1,"schema":2}', b'{"number":NaN}', b'{"number":Infinity}',
                    b'x' * (P.MAX_JSON + 1), b'\xff'):
            with self.subTest(size=len(raw)), self.assertRaises((ValueError, UnicodeError)):
                P.decode(raw)

    def test_owned_raw_fd_survives_acquisition_restore_cancel_without_transfer_leak(self):
        first = InterruptedError('first cancellation')
        later = InterruptedError('later cancellation')
        restores = iter((first, later))
        def mask(which, _value):
            if which == signal.SIG_SETMASK:
                raise next(restores)
            return set()
        operation = Mock()
        with patch.object(P.os, 'open', return_value=123), patch.object(P.os, 'close') as close, \
                patch.object(P.signal, 'pthread_sigmask', side_effect=mask), \
                self.assertRaises(InterruptedError) as caught:
            P.with_fd('/fixed/public', os.O_RDONLY, 0o600, operation)
        self.assertIs(caught.exception, first)
        operation.assert_not_called()
        close.assert_called_once_with(123)

    def test_fd_operation_failure_wins_over_close_and_repeated_restore_failures(self):
        original = ValueError('original fixture operation')
        closed = OSError('close uncertainty')
        restored = InterruptedError('queued cancellation')
        restores = 0
        def mask(which, _value):
            nonlocal restores
            if which == signal.SIG_SETMASK:
                restores += 1
                if restores == 2:
                    raise restored
            return set()
        with patch.object(P.os, 'open', return_value=123), \
                patch.object(P.os, 'close', side_effect=closed) as close, \
                patch.object(P.signal, 'pthread_sigmask', side_effect=mask), \
                self.assertRaises(ValueError) as caught:
            P.with_fd('/fixed/public', os.O_RDONLY, 0o600, Mock(side_effect=original))
        self.assertIs(caught.exception, original)
        close.assert_called_once_with(123)
        self.assertEqual(restores, 2)

    def test_private_reader_rejects_symlinks_hardlinks_modes_and_size(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / 'public'
            path.write_bytes(b'PUBLIC'); path.chmod(0o600)
            self.assertEqual(P.read(path), b'PUBLIC')
            with self.assertRaises(ValueError): P.read(path, 5)
            link = root / 'link'; link.symlink_to(path)
            with self.assertRaises(ValueError): P.read(link)
            hardlink = root / 'hardlink'; os.link(path, hardlink)
            with self.assertRaises(ValueError): P.read(path)
            hardlink.unlink(); path.chmod(0o644)
            with self.assertRaises(ValueError): P.read(path)

    def test_private_reader_refuses_same_fd_mutation_and_writer_never_clobbers(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'public.json'
            P.write(path, {'schema': 1})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError): P.write(path, {'schema': 2})
            self.assertEqual(path.read_bytes(), before)
            first = path.stat(); path.write_bytes(b'changed public fixture'); after = path.stat()
            with patch.object(P.os, 'fstat', side_effect=(first, after)), self.assertRaises(ValueError):
                P.read(path)

    def test_context_binds_only_fixed_owned_paths_hashes_and_single_link_executables(self):
        with tempfile.TemporaryDirectory(prefix='studio-export-crud-') as name:
            root = Path(name)
            (root / 'fixture').mkdir(); (root / 'node').mkdir(); (root / 'public').mkdir()
            files = {}
            for path in ('fixture/runtime.py', 'fixture/crud_protocol.py', 'fixture/crud_browser.mjs', 'server', 'node/node'):
                target = root / path
                target.write_bytes(b'PUBLIC synthetic control')
                target.chmod(0o700 if path in ('server', 'node/node') else 0o600)
                files[path] = hashlib.sha256(target.read_bytes()).hexdigest()
            assets = {}
            for path in P.ASSETS:
                target = root / 'public' / path
                target.write_bytes(b'PUBLIC'); target.chmod(0o600)
                assets[path] = dict(bytes=6, sha256=hashlib.sha256(b'PUBLIC').hexdigest())
            value = dict(schema=1, revision='a' * 40, root=str(root), node=str(root / 'node/node'),
                chrome='/usr/bin/google-chrome', server=str(root / 'server'), parent_net='net:[123]',
                parent_pid='pid:[456]', uid=max(1, os.getuid()), gid=max(1, os.getgid()), assets=assets, files=files)
            self.assertIs(P.context(value, root), value)
            for key, changed in (('node', '/arbitrary/node'), ('chrome', '/arbitrary/chrome'),
                                  ('parent_net', 'pid:[123]'), ('schema', True)):
                bad = dict(value); bad[key] = changed
                with self.subTest(key=key), self.assertRaises(ValueError): P.context(bad, root)
            bad = copy.deepcopy(value); bad['files']['node/node'] = 'b' * 64
            with self.assertRaises(ValueError): P.context(bad, root)
            os.link(root / 'node/node', root / 'linked-node')
            with self.assertRaises(ValueError): P.context(value, root)

    def test_cargo_hardlinked_binary_is_copied_into_independent_owned_700_file(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source, target = root / 'cargo-output', root / 'owned-server'
            raw = b'\x7fELFPUBLIC independent copy control'
            source.write_bytes(raw); source.chmod(0o755)
            os.link(source, root / 'cargo-hardlink')
            original = source.stat()
            expected = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            M.copy_binary(P, SimpleNamespace(inspect_elf=Mock(return_value=expected)), source, target)
            self.assertEqual(target.read_bytes(), raw)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual(target.stat().st_nlink, 1)
            self.assertNotEqual(target.stat().st_ino, source.stat().st_ino)
            self.assertEqual((source.stat().st_ino, source.stat().st_nlink), (original.st_ino, 2))

    def test_source_snapshot_allows_only_exact_example_and_overlay_extras_with_no_schema_exemption(self):
        before = {'ordinary.rs': {'sha256': 'a' * 64}, 'generated-schema.json': None}
        native = SimpleNamespace(tracked=Mock(return_value=before),
            git=Mock(side_effect=[b'example.rs\0', b'']))
        M.source_unchanged(native, Path('/source'), before, ['example.rs'], {}, 10, [], object())
        native.tracked.return_value = dict(before, **{'generated-schema.json': {'sha256': 'b' * 64}})
        with self.assertRaises(RuntimeError):
            M.source_unchanged(native, Path('/source'), before, ['example.rs'], {}, 10, [], object())
        native.tracked.return_value = before
        native.git.side_effect = [b'example.rs\0unexpected.rs\0']
        with self.assertRaises(RuntimeError):
            M.source_unchanged(native, Path('/source'), before, ['example.rs'], {}, 10, [], object())

    def test_browser_pass_requires_real_steps_closure_sandbox_typed_rename_and_metadata_binding(self):
        self.assertEqual(P.browser_receipt(browser(), 'first')['ids'], IDS)
        self.assertEqual(P.browser_receipt(browser('second'), 'second')['ids'], IDS)
        for key, changed in (('sandbox_requested', False), ('context_closed', False),
                ('browser_closed', False), ('typed_rename_only', False), ('other_bytes_preserved', False),
                ('requests', True), ('ids', IDS[:1]), ('failure_http_status', 400), ('status', 'failed'),
                ('metadata_after_sha256', 'a' * 64)):
            value = browser(); value[key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError): P.browser_receipt(value, 'first')

    def test_browser_failure_preserves_only_fixed_first_action_status_and_finite_markers(self):
        value = browser(); value.update(status='failed', failure_action='rename', failure_http_status=400)
        projection = P.browser_failure(value, 'first')
        self.assertEqual(projection['action'], 'rename')
        self.assertEqual(projection['http_status'], 400)
        for key, bad in (('failure_action', 'PRIVATE/raw/path'), ('failure_http_status', True),
                         ('chrome_sandbox_failure', 'PRIVATE'), ('error', 'PRIVATE')):
            changed = dict(value); changed[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError): P.browser_failure(changed, 'first')
        self.assertNotIn('PRIVATE', json.dumps(projection))

    def test_runtime_pass_binds_two_server_browser_runs_restart_identity_denials_and_all_cleanup(self):
        self.assertEqual(M.check_runtime(P, runtime(), 'a' * 40)['http_denials'], 42)
        for key, changed in (('http_denials', 41), ('server_runs', True), ('persistence', False),
                ('descendants_gone', False), ('listeners_closed', False), ('owned_groups_joined', False),
                ('mount_isolation_proven', True), ('no_external_attempts_proven', True)):
            value = runtime(); value[key] = changed
            with self.subTest(key=key), self.assertRaises(RuntimeError): M.check_runtime(P, value, 'a' * 40)
        value = runtime(); value['browser_receipts'][1]['ids'] = list(reversed(IDS))
        with self.assertRaises(RuntimeError): M.check_runtime(P, value, 'a' * 40)

    def test_failed_runtime_projection_rejects_arbitrary_action_paths_statuses_and_log_content(self):
        value = runtime(); value.update(status='failed', stage='http_denials',
            first_failure=dict(stage='http_denials', browser=None, case_id=4, http_status=500))
        projected = M.runtime_failure(P, value, 'a' * 40)
        self.assertEqual(projected['first_failure']['http_status'], 500)
        for changed in (dict(stage='PRIVATE'), dict(first_failure={'raw_error': 'PRIVATE'}),
                dict(log_observations=[{'case_id': 'PRIVATE', 'bytes': 1, 'sha256': 'a' * 64}])):
            bad = dict(value, **changed)
            with self.subTest(changed=changed), self.assertRaises(RuntimeError): M.runtime_failure(P, bad, 'a' * 40)

    def test_descendant_selection_is_parent_anchored_and_never_selects_sibling_processes(self):
        rows = {10: {'PPid': '1'}, 11: {'PPid': '10'}, 12: {'PPid': '11'}, 20: {'PPid': '1'}}
        self.assertEqual(R.descendants(rows, 10), {11, 12})
        rows[12] = {'PPid': '10'}  # PID1 adoption after intermediate parent exit.
        self.assertEqual(R.descendants(rows, 10), {11, 12})
        self.assertNotIn(20, R.descendants(rows, 10))

    def test_normal_exit_keeps_group_leader_unreaped_until_term_resistant_descendant_is_killed(self):
        self.assertEqual(os.environ.get('GITHUB_ACTIONS'), 'true', 'actual toy runs only on approved hosted runner')
        self.assertEqual(os.environ.get('RUNNER_ENVIRONMENT'), 'github-hosted')
        self.assertNotEqual(os.geteuid(), 0)
        # Only these newly spawned public toy PIDs are ever signalled.
        with tempfile.TemporaryDirectory(prefix='crud-owned-toy-') as name:
            ready = Path(name) / 'PUBLIC-ready'
            descendant = "import pathlib,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); pathlib.Path(sys.argv[1]).write_text('PUBLIC ready'); time.sleep(30)"
            toy = ("import pathlib,subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-I','-B','-c'," + repr(descendant) + "," + repr(str(ready)) + "]); "
                "end=time.monotonic()+2\n"
                "while not pathlib.Path(" + repr(str(ready)) + ").exists():\n"
                " if time.monotonic()>end: sys.exit(2)\n time.sleep(0.01)\n")
            child = R.Child(P, [sys.executable, '-I', '-B', '-c', toy],
                {'PATH': '/usr/bin:/bin', 'LANG': 'C'}, Path(name), 'public', time.monotonic() + 8)
            try:
                child.wait(time.monotonic() + 3)
                self.assertIsNotNone(child.status())
                self.assertIsNone(child.process.returncode)
                self.assertTrue(child.live())
            finally:
                child.close()
            self.assertTrue(child.joined)
            self.assertTrue(child.escalated)
            self.assertFalse(child.live())

    def test_wrong_entry_or_profile_refuses_before_any_dependency_import(self):
        with patch.object(M.sys, 'argv', ['crud.py']), patch.object(M, 'load') as load, \
                self.assertRaises(RuntimeError): M.main()
        load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
