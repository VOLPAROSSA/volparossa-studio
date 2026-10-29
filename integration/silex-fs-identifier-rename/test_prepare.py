# SPDX-License-Identifier: GPL-3.0-only
"""Hosted source-protocol controls; no Rust, application or package execution."""
import copy
import importlib.util
from pathlib import Path
import signal
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('fs_overlay_under_test', HERE / 'prepare.py')
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)


class OverlayTests(unittest.TestCase):
    def test_actual_closed_manifest_and_text_patch_bind_all_eleven_paths(self):
        value = M.manifest()
        raw = M.patch_bytes(value)
        self.assertEqual(set(value['files']), M.PATHS)
        self.assertEqual(sum(row['before'] is None for row in value['files'].values()), 4)
        self.assertEqual(len(raw), value['patch']['bytes'])
        self.assertEqual(M.SUPPORT.digest(raw), value['patch']['sha256'])

    def test_patch_refuses_path_mode_binary_duplicate_and_incomplete_headers(self):
        value = M.manifest()
        raw = M.patch_bytes(value)
        first = sorted(M.PATHS)[0].encode()
        variants = (raw.replace(b'a/' + first, b'a/../outside', 1),
                    raw.replace(b'new file mode 100644', b'new file mode 120000', 1),
                    raw + b'GIT binary patch\n', raw + raw,
                    raw.replace(b'--- /dev/null', b'--- a/foreign', 1), raw[:-1])
        for changed in variants:
            bad = copy.deepcopy(value)
            bad['patch'].update(bytes=len(changed), sha256=M.SUPPORT.digest(changed))
            with self.subTest(length=len(changed)), patch.object(M.SUPPORT, 'read', return_value=changed):
                with self.assertRaises(Exception):
                    M.patch_bytes(bad)

    def test_patch_hash_mismatch_precedes_git_authority(self):
        value = M.manifest()
        with patch.object(M.SUPPORT, 'read', return_value=b'wrong bytes'), \
                patch.object(M.SUPPORT, 'command') as command:
            with self.assertRaises(Exception):
                M.patch_bytes(value)
            command.assert_not_called()

    def test_manifest_rejects_scope_pin_extra_path_and_executable_mode(self):
        original = M.manifest()
        variants = []
        value = copy.deepcopy(original); value['scope']['publication_authorized'] = True; variants.append(value)
        value = copy.deepcopy(original); value['root_lock_sha256'] = 'a' * 64; variants.append(value)
        value = copy.deepcopy(original); value['files']['outside'] = value['files'][next(iter(M.PATHS))]; variants.append(value)
        value = copy.deepcopy(original); value['files'][next(iter(M.PATHS))]['after']['mode'] = '100755'; variants.append(value)
        for value in variants:
            raw = M.json.dumps(value).encode()
            with self.subTest(keys=len(value['files'])), patch.object(M.SUPPORT, 'read', return_value=raw):
                with self.assertRaises(Exception):
                    M.manifest()

    def test_duplicate_manifest_keys_are_rejected(self):
        with patch.object(M.SUPPORT, 'read', return_value=b'{"schema":1,"schema":1}'):
            with self.assertRaises(Exception):
                M.manifest()

    def test_verify_patched_requires_exact_repository_root_before_file_claims(self):
        value = M.manifest()
        with patch.object(M.SUPPORT, 'hosted_guard'), \
                patch.object(M.SUPPORT, 'command', return_value=b'/different/repository\n') as command, \
                patch.object(M.SUPPORT, 'check_file') as file_check:
            with self.assertRaises(Exception):
                M.source_check(Path('/expected'), value, {'files': {}}, {'files': {}}, True)
            self.assertEqual(command.call_args.args[1:], ('rev-parse', '--show-toplevel'))
            file_check.assert_not_called()

    def test_original_failure_survives_all_handler_restore_attempts(self):
        original = M.SUPPORT.Rejected('original controlled failure')
        calls = []
        handlers = {n: signal.getsignal(n) for n in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        def install(number, handler):
            calls.append((number, handler))
            if handler is handlers[number]:
                raise KeyboardInterrupt('late synthetic cancellation')
        with patch.object(M, 'main', side_effect=original), \
                patch.object(M.signal, 'signal', side_effect=install), \
                patch.object(M.signal, 'pthread_sigmask', return_value=set()):
            with self.assertRaises(M.SUPPORT.Rejected) as caught:
                M.entry()
        self.assertIs(caught.exception, original)
        self.assertEqual([n for n, _ in calls[-3:]], list(handlers))

    def test_entry_installs_cancellation_before_main_and_restores_handlers(self):
        callbacks = {}
        handlers = {n: signal.getsignal(n) for n in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        def install(number, handler):
            callbacks[number] = handler
        def operation():
            self.assertEqual(set(callbacks), set(handlers))
            with self.assertRaises(M.SUPPORT.Rejected):
                callbacks[signal.SIGTERM](signal.SIGTERM, None)
        with patch.object(M, 'main', side_effect=operation), \
                patch.object(M.signal, 'signal', side_effect=install), \
                patch.object(M.signal, 'pthread_sigmask', return_value=set()):
            M.entry()
        self.assertEqual(callbacks, handlers)


if __name__ == '__main__':
    unittest.main()
