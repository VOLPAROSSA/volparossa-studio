# SPDX-License-Identifier: GPL-3.0-only
"""Inert controls for the source-to-ELF handoff and closed WebView evidence."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('webview_fixture_root', HERE / 'isolation_root.py')
root = importlib.util.module_from_spec(spec)
spec.loader.exec_module(root)


gui_spec = importlib.util.spec_from_file_location('webview_actor', HERE / 'webview.py')
gui = importlib.util.module_from_spec(gui_spec)
gui_spec.loader.exec_module(gui)


class WebViewTests(unittest.TestCase):
    def test_editor_requires_unique_exact_title_and_separates_a_dirty_project(self):
        title = gui.NAME + ' — Silex'
        for name in ('Silex', '• ' + title, 'other — Silex'):
            with patch.object(gui, 'visible_titles', return_value={51: name}):
                self.assertIsNone(gui.editor_window(15))
        with patch.object(gui, 'visible_titles', return_value={51: '• ' + title}):
            self.assertEqual(gui.editor_observation(None, 15, 'project'), 'dirty_title')
        with patch.object(gui, 'visible_titles', return_value={51: title, 52: 'Silex'}):
            self.assertEqual(gui.editor_window(15), 51)
        with patch.object(gui, 'visible_titles', return_value={51: title, 52: title}):
            with self.assertRaises(RuntimeError):
                gui.editor_window(15)

    def test_private_executable_is_copied_only_after_exact_length_and_content_check(self):
        raw = b'\x7fELF\x02\x01' + bytes(range(100))
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'compiler-output'
            source.write_bytes(raw)
            for digest, size, accepted in ((hashlib.sha256(raw).hexdigest(), len(raw), True),
                    ('0' * 64, len(raw), False), (hashlib.sha256(raw).hexdigest(), len(raw) - 1, False)):
                destination = Path(temporary) / (digest + str(size))
                with source.open('rb') as stream, patch.object(root.os, 'fchown') as change_owner:
                    if accepted:
                        root.copy_release(stream, dict(bytes=size, sha256=digest), destination, os.getgid())
                        self.assertEqual(destination.read_bytes(), raw)
                        self.assertEqual(destination.stat().st_mode & 0o777, 0o550)
                        change_owner.assert_called_once()
                    else:
                        with self.assertRaises(root.Rejected):
                            root.copy_release(stream, dict(bytes=size, sha256=digest), destination, os.getgid())
                        self.assertFalse(destination.stat().st_mode & 0o111)
                        change_owner.assert_not_called()

    def test_loopback_only_allows_fixed_server_and_preserves_both_drop_counters(self):
        lines = root.gui_policy(1001).decode().splitlines()
        permits = [row for row in lines if row.endswith(' accept')]
        self.assertEqual(len(permits), 2)
        self.assertTrue(all('oifname "lo"' in row and '6805' in row and 'tcp ' in row for row in permits))
        self.assertTrue(all(any(('name ' + name + ' drop') in row for row in lines) for name in ('denied4', 'denied6')))
        with self.assertRaises(root.Rejected):
            root.gui_policy(0)

    def test_reopen_evidence_requires_both_normal_native_closes_and_owned_groups(self):
        value = dict(status='passed', stage='complete', process_groups_started=4, process_groups_joined=4,
            desktop_launches=2, native_window_closes=2, original_project_reopened=True, project_id_sha256='0' * 64)
        root.verify_gui(value)
        for key, bad in (('native_window_closes', 1), ('process_groups_joined', 3), ('original_project_reopened', False),
                         ('project_id_sha256', 'invalid'), ('stage', 'first_editor')):
            with self.subTest(key=key), self.assertRaises(root.Rejected):
                root.verify_gui(dict(value, **{key: bad}))


if __name__ == '__main__':
    unittest.main()
