# SPDX-License-Identifier: GPL-3.0-only
"""Inert Python process fixtures only: no editor/browser/build/network namespace."""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from lifecycle import OwnedGroup, live_group_members, member_in_namespace
from run import OperationFailure, run


# Close inherited output in the child so the controller sees leader EOF. This
# reproduces the old bug: leader wait succeeds while its TERM-resistant child
# keeps running. Files/log text here are synthetic and temporary.
SYNTHETIC = '''
import os,signal,sys,time
path,mode=sys.argv[1:]
pid=os.fork()
if pid == 0:
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    os.close(1)
    os.close(2)
    with open(path,'x') as out: out.write(str(os.getpid()))
    while True: time.sleep(0.1)
while not os.path.exists(path): time.sleep(0.01)
print('synthetic secret must never enter diagnostics',flush=True)
if mode == 'timeout':
    while True: time.sleep(0.1)
os._exit(int(mode))
'''


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Only this test interpreter adopts its own orphan fixtures, allowing us
        # to reap them instead of leaving synthetic zombies to PID 1.
        cls.libc = ctypes.CDLL(None, use_errno=True)
        cls.original = ctypes.c_int()
        if cls.libc.prctl(37, ctypes.byref(cls.original), 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'get test child subreaper')
        if cls.libc.prctl(36, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'set test child subreaper')

    @classmethod
    def tearDownClass(cls):
        cls.libc.prctl(36, cls.original.value, 0, 0, 0)

    def scenario(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pidfile = root / 'synthetic-child'
            child = None
            started = time.monotonic()
            failure = None
            try:
                try:
                    run([sys.executable, '-B', '-c', SYNTHETIC, str(pidfile), mode], root,
                        dict(os.environ), 'build-client', timeout=0.3 if mode == 'timeout' else 3)
                except OperationFailure as error:
                    failure = error
                self.assertTrue(pidfile.exists(), 'synthetic child became ready')
                child = int(pidfile.read_text())
                stat = Path('/proc') / str(child) / 'stat'
                if stat.exists():
                    fields = stat.read_text().rsplit(')', 1)[1].split()
                    self.assertIn(fields[0], ('Z', 'X', 'x'), 'no executable child remains')
                    group = int(fields[2])
                    self.assertEqual(live_group_members(OwnedGroup((group,), (group,))), [])
                self.assertLess(time.monotonic() - started, 5, 'bounded cleanup')
                if mode == '0':
                    self.assertIsNone(failure)
                else:
                    self.assertIsNotNone(failure)
                    diagnostic = failure.receipt()
                    self.assertEqual(set(diagnostic), {'operation', 'exit_code', 'classification'})
                    self.assertEqual(diagnostic['operation'], 'build-client')
                    self.assertIs(type(diagnostic['exit_code']), int)
                    if mode == '7':
                        self.assertEqual(diagnostic, {'operation': 'build-client', 'exit_code': 7,
                                                     'classification': 'exit_nonzero'})
                    else:
                        self.assertEqual(diagnostic['classification'], 'deadline_exceeded')
                    self.assertNotIn('secret', json.dumps(diagnostic))
                    self.assertNotIn(str(root), json.dumps(diagnostic))
            finally:
                if child is None and pidfile.exists():
                    child = int(pidfile.read_text())
                if child is not None:
                    # Test failure recovery is restricted to this exact synthetic
                    # child. Never wait on an executing TERM-resistant process.
                    try:
                        os.kill(child, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    deadline = time.monotonic() + 2
                    while True:
                        try:
                            reaped, _ = os.waitpid(child, os.WNOHANG)
                        except ChildProcessError:
                            break
                        if reaped:
                            break
                        if time.monotonic() >= deadline:
                            self.fail('synthetic child reaping exceeded deadline')
                        time.sleep(0.02)

    def test_exited_leader_resistant_child_drained(self):
        self.scenario('0')

    def test_failed_build_diagnostic_closed_and_group_drained(self):
        self.scenario('7')

    def test_timed_out_leader_resistant_child_drained(self):
        self.scenario('timeout')

    def test_diagnostic_rejects_unbounded_fields(self):
        with self.assertRaises(ValueError):
            OperationFailure('untrusted operation text', 1, 'exit_nonzero')
        with self.assertRaises(ValueError):
            OperationFailure('build-client', 1, 'raw log contents')

    def test_ancestor_proc_mount_namespace_ids_and_zombies(self):
        owned = OwnedGroup((5000, 30), (5000, 30))
        status = 'State:\tS (sleeping)\nNSpid:\t6000 40 1\nNSpgid:\t5000 30 1\nNSsid:\t5000 30 1\n'
        self.assertEqual(member_in_namespace(status, owned), 40)
        self.assertIsNone(member_in_namespace(status.replace('S (sleeping)', 'Z (zombie)'), owned))
        outside = 'State:\tS\nNSpid:\t30\nNSpgid:\t30\nNSsid:\t30\n'
        self.assertIsNone(member_in_namespace(outside, owned))

    def test_equal_depth_sibling_namespace_is_not_owned(self):
        owned = OwnedGroup((5000, 30), (5000, 30))
        actual = 'State:\tS\nNSpid:\t6000 40\nNSpgid:\t5000 30\nNSsid:\t5000 30\n'
        sibling = 'State:\tS\nNSpid:\t9000 40\nNSpgid:\t8000 30\nNSsid:\t8000 30\n'
        self.assertEqual(member_in_namespace(actual, owned), 40)
        self.assertIsNone(member_in_namespace(sibling, owned))

    def test_nested_owned_group_prefix_and_distinct_session(self):
        owned = OwnedGroup((5000, 30), (5000, 30))
        nested = 'State:\tS\nNSpid:\t6000 40 1\nNSpgid:\t5000 30 1\nNSsid:\t5000 30 1\n'
        self.assertEqual(member_in_namespace(nested, owned), 40)
        self.assertIsNone(member_in_namespace(nested.replace('NSsid:\t5000 30 1', 'NSsid:\t8000 30 1'), owned))


if __name__ == '__main__':
    unittest.main()
