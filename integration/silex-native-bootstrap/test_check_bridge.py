#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Hosted caller cleanup regressions; no Node, package download, SDK or native app."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import ModuleType
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('native_bootstrap_check_bridge', HERE / 'check_bridge.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class CallerCleanupTests(unittest.TestCase):
    def test_real_exited_child_remains_unreaped_until_the_only_drain_owner(self):
        started = []
        observed = []

        def start(command, **options):
            child = subprocess.Popen(command, start_new_session=True, **options)
            started.append(child)
            return child, child.pid

        def drain(child, identity, *, grace, kill_grace):
            try:
                self.assertIs(child, started[0])
                self.assertEqual(identity, child.pid)
                self.assertIsNone(child.returncode, 'bounded must not poll/wait before its drain owner')
                exited = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                self.assertIsNotNone(exited)
                self.assertEqual((exited.si_pid, exited.si_code, exited.si_status),
                                 (child.pid, os.CLD_EXITED, 0))
                observed.append(child.pid)
            finally:
                # Only this directly owned child can be signalled. Even an
                # assertion failure must join it; no external PID/group is used.
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=1)
            return {'leader_joined': True, 'live_group_drained': True}

        cleanups = []
        output = M.bounded(
            [sys.executable, '-I', '-B', '-c', 'print("PUBLIC-SYNTHETIC-BRIDGE-CLEANUP")'],
            {'PATH': '/usr/bin:/bin', 'LANG': 'C'}, start, drain,
            time.monotonic() + 20, 2, cleanups)
        self.assertEqual(output, b'PUBLIC-SYNTHETIC-BRIDGE-CLEANUP\n')
        self.assertEqual(observed, [started[0].pid])
        self.assertEqual(cleanups, [True])
        self.assertEqual(started[0].returncode, 0)
        self.assertTrue(started[0].stdout.closed)

    def test_unconfirmed_cleanup_retains_private_tree_and_original_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp = Path(temporary)
            source = runner_temp / 'silex'
            pristine = runner_temp / 'pristine-desktop-bridge.js'
            primary = M.Rejected('deadline')
            carrier = ModuleType('run')
            carrier.prepare = mock.Mock(side_effect=AssertionError('no download or execution permitted'))
            lifecycle = ModuleType('lifecycle')
            lifecycle.start_group = mock.Mock(side_effect=AssertionError('no child permitted'))
            lifecycle.drain_group = mock.Mock(side_effect=AssertionError('no foreign signal permitted'))

            def failed_source_check(*arguments, **_options):
                # Exercise main's actual failure/finally path after private
                # state creation and before authenticating/executing any tool.
                cleanups = arguments[6]
                cleanups.append(False)
                raise primary

            with mock.patch.object(M, 'admission', return_value=(source, pristine, runner_temp,
                    runner_temp / 'workspace', 'a' * 40)), \
                    mock.patch.object(M, 'read', return_value=b'public synthetic source fixture'), \
                    mock.patch.object(M, 'bounded', side_effect=failed_source_check), \
                    mock.patch.dict(sys.modules, {'run': carrier, 'lifecycle': lifecycle}), \
                    mock.patch.object(M.signal, 'signal'), \
                    mock.patch.object(M.signal, 'setitimer'), \
                    mock.patch.object(M.shutil, 'rmtree') as remove, \
                    contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(M.main(), 1)

            remove.assert_not_called()
            carrier.prepare.assert_not_called()
            lifecycle.start_group.assert_not_called()
            lifecycle.drain_group.assert_not_called()
            self.assertEqual(error.getvalue(), 'hosted bridge check rejected\n')
            trees = list(runner_temp.glob('silex-native-bridge-*'))
            self.assertEqual(len(trees), 1)
            self.assertTrue((trees[0] / 'home').is_dir())
            receipt = json.loads((runner_temp / 'silex-native-bridge.json').read_bytes())
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(receipt['failure'], {'kind': primary.kind, 'stage': 'verify_source_before'})
            self.assertEqual(receipt['cleanup'], {
                'owned_groups_joined': False, 'owned_group_count': 1,
                'private_state_removed': False, 'private_state_retained': True})
            self.assertFalse(receipt['node_invocation_started'])
            self.assertFalse(receipt['node_vm_tests_passed'])
            self.assertFalse(receipt['dependency_installation_performed'])
            self.assertFalse(receipt['native_runtime_acceptance'])


if __name__ == '__main__':
    unittest.main()
