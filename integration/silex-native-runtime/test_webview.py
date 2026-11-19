# SPDX-License-Identifier: GPL-3.0-only
"""Inert controls for the source-to-ELF handoff and closed WebView evidence."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

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
        for name in ('Silex', '• other — Silex', '• • ' + title, 'other — Silex'):
            with patch.object(gui, 'visible_titles', return_value={51: name}):
                self.assertIsNone(gui.editor_window(15))
        with patch.object(gui, 'visible_titles', return_value={51: '• ' + title}):
            self.assertEqual(gui.editor_window(15), (51, 'changed'))
            self.assertEqual(gui.editor_observation(None, 15, 'project'), 'dirty_title')
        with patch.object(gui, 'visible_titles', return_value={51: title, 52: 'Silex'}):
            self.assertEqual(gui.editor_window(15), (51, 'clean'))
        with patch.object(gui, 'visible_titles', return_value={51: title, 52: '• ' + title}):
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

    def test_dashboard_action_uses_the_exact_named_action_and_observes_the_live_application(self):
        sdk, process = Mock(), Mock()
        process.poll.return_value = None
        node = sdk.get_desktop.return_value
        node.get_name.return_value = 'Refresh'
        node.get_action_iface.return_value.get_n_actions.return_value = 1
        node.get_action_iface.return_value.do_action.return_value = True
        gui.desktop_action(sdk, 'Refresh', process)
        node.get_action_iface.return_value.do_action.assert_called_once_with(0)
        process.poll.return_value = 1
        with self.assertRaises(RuntimeError):
            gui.desktop_action(sdk, 'Refresh', process)

    def test_dashboard_creation_requires_its_named_editable_input_and_exact_ready_text(self):
        node = Mock()
        node.get_name.return_value = 'Project name'
        self.assertIs(gui.project_name_input(node), node.get_editable_text_iface.return_value)
        node.get_name.return_value = 'Other input'
        self.assertIsNone(gui.project_name_input(node))
        text = node.get_text_iface.return_value
        expected = '0 local projects.'
        text.get_character_count.return_value = len(expected)
        text.get_text.return_value = expected
        self.assertTrue(gui.has_text(node, expected))
        text.get_text.return_value = '1 local projects.'
        self.assertFalse(gui.has_text(node, expected))

    def test_quit_requires_the_original_desktop_pid_and_the_save_quit_sibling(self):
        node, save = Mock(), Mock()
        node.get_name.return_value = 'Quit'
        node.get_process_id.return_value = 1001
        save.get_name.return_value = 'Save & Quit'
        box = node.get_parent.return_value
        box.get_child_count.return_value = 2
        box.get_child_at_index.side_effect = lambda index: (node, save)[index]
        node.get_action_iface.return_value.get_n_actions.return_value = 1
        self.assertIs(gui.quit_dialog_action(node, 1001), node.get_action_iface.return_value)
        self.assertIsNone(gui.quit_dialog_action(node, 1002))
        save.get_name.return_value = 'Other'
        self.assertIsNone(gui.quit_dialog_action(node, 1001))

    def test_visible_heading_must_match_the_content_saved_for_this_project(self):
        sdk = Mock()
        project_id = 'c3218641-230e-414f-8a6a-367733abeb23'
        expected = gui.saved_page(project_id)['frames'][0]['component']['components'][0]['components'][0]['content']
        node = sdk.get_desktop.return_value
        node.get_child_count.return_value = 0
        node.get_role.return_value = sdk.Role.HEADING
        node.get_name.return_value = expected
        node.get_state_set.return_value.contains.side_effect = lambda state: state in (
            sdk.StateType.VISIBLE, sdk.StateType.SHOWING)
        self.assertTrue(gui.visible_canvas_heading(sdk, project_id))
        self.assertFalse(gui.visible_canvas_heading(sdk, 'different-project'))
        node.get_state_set.return_value.contains.side_effect = lambda state: state == sdk.StateType.VISIBLE
        self.assertFalse(gui.visible_canvas_heading(sdk, project_id))

    def test_canvas_pixels_must_show_the_saved_pair_aligned_across_six_rows(self):
        first, second = gui.canvas_colors('a')
        row = b'\0' * 6 + first * 16 + second * 32
        width = len(row) // 3
        pixels = row * 6
        self.assertTrue(gui.contains_canvas_pixels(pixels, width, 6, len(row), 3, (first, second)))
        self.assertFalse(gui.contains_canvas_pixels(pixels, width, 6, len(row), 3, gui.canvas_colors('b')))
        self.assertFalse(gui.contains_canvas_pixels(pixels, width, 5, len(row), 3, (first, second)))
        self.assertFalse(gui.contains_canvas_pixels(row * 5 + row[3:] + row[:3], width, 6, len(row), 3, (first, second)))

    def test_checkpoints_preserve_partial_progress_and_never_supply_a_terminal_receipt(self):
        mark = b'GUI first_canvas_read\n'
        self.assertEqual(root.last_gui_checkpoint(mark + b'private free text'), 'first_canvas_read')
        self.assertIsNone(root.last_gui_checkpoint(b'GUI unknown_private_value'))
        self.assertEqual(root.gui_output(mark + b'{"status":"failed"}\n'), {'status': 'failed'})
        for raw in (mark, mark + mark + b'{}', b'private\n{}', b'GUI unknown\n{}'):
            with self.subTest(raw=raw), self.assertRaises((root.Rejected, ValueError)):
                root.gui_output(raw)

    def test_reopen_evidence_requires_both_normal_native_closes_and_owned_groups(self):
        value = dict(
            status='passed', stage='complete', process_groups_started=4, process_groups_joined=4,
            desktop_launches=2, native_window_closes=2, editor_title_states=['changed', 'clean'],
            canvas_readbacks=['visible_pixels', 'accessible_text'], close_actions=['window_close', 'quit_dialog'],
            original_project_reopened=True, project_id_sha256='0' * 64,
        )
        root.verify_gui(value)
        for key, bad in (
            ('native_window_closes', 1), ('process_groups_joined', 3), ('original_project_reopened', False),
            ('editor_title_states', ['clean', 'other']), ('close_actions', ['quit_dialog', 'forced']),
            ('canvas_readbacks', ['visible_pixels']), ('canvas_readbacks', ['unknown', 'accessible_text']),
            ('project_id_sha256', 'invalid'), ('stage', 'first_editor'),
        ):
            with self.subTest(key=key), self.assertRaises(root.Rejected):
                root.verify_gui(dict(value, **{key: bad}))


if __name__ == '__main__':
    unittest.main()
