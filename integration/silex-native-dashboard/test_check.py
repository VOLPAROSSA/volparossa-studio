# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only finalization controls; no Node, network or native app execution."""
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('dashboard_check', Path(__file__).with_name('check.py'))
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class Signals:
    """Controlled delivery at the cleanup/commit handoff, without OS signals."""
    def __init__(self):
        self.numbers = (CHECK.signal.SIGINT, CHECK.signal.SIGTERM, CHECK.signal.SIGHUP, CHECK.signal.SIGALRM)
        self.originals = {number: self.original for number in self.numbers}
        self.handlers = dict(self.originals)
        self.pending = set()
        self.restored = []
        self.masks = []
        self.restore_error = None
        self.unmask_error = None

    def original(self, _number, _frame):
        raise RuntimeError('original cancellation handler')

    def change(self, number, handler):
        if handler is self.originals[number]:
            self.restored.append(number)
            if self.restore_error is not None:
                raise self.restore_error
        self.handlers[number] = handler

    def mask(self, operation, _numbers):
        self.masks.append(operation)
        if operation == CHECK.signal.SIG_SETMASK and len(self.masks) == 4:
            queued = set(self.pending)
            self.pending.clear()
            for number in queued:
                self.handlers[number](number, None)
            if self.unmask_error is not None:
                raise self.unmask_error
        return set()

    def install(self, stack):
        stack.enter_context(patch.object(CHECK.signal, 'getsignal', side_effect=lambda n: self.originals[n]))
        stack.enter_context(patch.object(CHECK.signal, 'signal', side_effect=self.change))
        stack.enter_context(patch.object(CHECK.signal, 'pthread_sigmask', side_effect=self.mask))
        stack.enter_context(patch.object(CHECK.signal, 'sigpending', side_effect=lambda: set(self.pending)))


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = self.root / 'tools'
        self.work.mkdir(mode=0o700)
        (self.work / 'public-tool-placeholder').write_bytes(b'public synthetic')
        self.artifact = self.root / 'receipt.json'

    def finish(self, signals, *, primary=None, groups=None, child_attempted=True, ready=True):
        report = dict(schema=1, status='failed', stage='unit_fixture', private_tool_tree_removed=False)
        result = CHECK.finish(self.artifact, self.work, report,
                              [True] if groups is None else groups, primary,
                              child_attempted=child_attempted, work_created=True, ready=ready)
        return result, report

    def test_precommit_repeated_cancel_during_cleanup_cannot_publish_pass(self):
        signals = Signals()
        remove = CHECK.shutil.rmtree
        def interrupted_remove(path):
            for number in signals.numbers * 2:
                signals.handlers[number](number, None)
            remove(path)
        with ExitStack() as stack:
            signals.install(stack)
            stack.enter_context(patch.object(CHECK.shutil, 'rmtree', side_effect=interrupted_remove))
            primary, report = self.finish(signals)
        self.assertIsNotNone(primary)
        self.assertEqual(report['status'], 'failed')
        self.assertIs(report['private_tool_tree_removed'], True)
        self.assertFalse(self.work.exists())
        self.assertEqual(json.loads(self.artifact.read_bytes())['status'], 'failed')
        self.assertEqual(set(signals.restored), set(signals.numbers))

    def test_pending_precommit_kernel_signal_cannot_publish_pass(self):
        signals = Signals()
        signals.pending.add(CHECK.signal.SIGTERM)
        with ExitStack() as stack:
            signals.install(stack)
            primary, report = self.finish(signals)
        self.assertIsNotNone(primary)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(json.loads(self.artifact.read_bytes())['status'], 'failed')

    def test_late_queued_signals_after_commit_do_not_negate_valid_receipt(self):
        signals = Signals()
        publish = CHECK.publish_receipt
        def committed_then_cancel(path, raw):
            publish(path, raw)
            signals.pending.update(signals.numbers)
        with ExitStack() as stack:
            signals.install(stack)
            stack.enter_context(patch.object(CHECK, 'publish_receipt', side_effect=committed_then_cancel))
            primary, report = self.finish(signals)
        self.assertIsNone(primary)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['stage'], 'complete')
        self.assertEqual(json.loads(self.artifact.read_bytes())['status'], 'passed')
        self.assertFalse(signals.pending)
        self.assertEqual(set(signals.restored), set(signals.numbers))
        self.assertEqual(signals.masks, [CHECK.signal.SIG_BLOCK, CHECK.signal.SIG_SETMASK] * 2)

    def test_receipt_write_failure_preserves_primary_and_is_mandatory_without_one(self):
        for original in (None, RuntimeError('original unit failure')):
            with self.subTest(prior_primary=original is not None), ExitStack() as stack:
                signals = Signals()
                signals.install(stack)
                failure = OSError('synthetic write failure')
                stack.enter_context(patch.object(CHECK, 'publish_receipt', side_effect=failure))
                primary, _report = self.finish(signals, primary=original)
            self.assertIs(primary, original or failure)
            self.assertFalse(self.artifact.exists())
            if not self.work.exists():
                self.work.mkdir()

    def test_partial_or_flush_failed_write_never_creates_public_artifact(self):
        for operation in ('write', 'fsync'):
            with self.subTest(operation=operation):
                if operation == 'fsync':
                    context = patch.object(CHECK.os, 'fsync', side_effect=OSError('flush failure'))
                else:
                    real_fdopen = CHECK.os.fdopen
                    class Partial:
                        def __init__(self, descriptor, mode):
                            self.stream = real_fdopen(descriptor, mode)
                        def __enter__(self):
                            return self
                        def __exit__(self, *args):
                            self.stream.close()
                        def fileno(self):
                            return self.stream.fileno()
                        def write(self, raw):
                            self.stream.write(raw[:5])
                            self.stream.flush()
                            return 5
                    context = patch.object(CHECK.os, 'fdopen', side_effect=Partial)
                with context, self.assertRaises((RuntimeError, OSError)):
                    CHECK.publish_receipt(self.artifact, b'{"status":"passed"}\n')
                self.assertFalse(self.artifact.exists())
                self.assertFalse((self.root / '.receipt.json.pending').exists())

    def test_publication_never_overwrites_foreign_artifact_or_staging_file(self):
        self.artifact.write_bytes(b'foreign')
        with self.assertRaises(FileExistsError):
            CHECK.publish_receipt(self.artifact, b'{"status":"passed"}\n')
        self.assertEqual(self.artifact.read_bytes(), b'foreign')
        self.artifact.unlink()
        staging = self.root / '.receipt.json.pending'
        staging.write_bytes(b'foreign staging')
        with self.assertRaises(FileExistsError):
            CHECK.publish_receipt(self.artifact, b'{"status":"passed"}\n')
        self.assertEqual(staging.read_bytes(), b'foreign staging')
        self.assertFalse(self.artifact.exists())

    def test_zero_child_carrier_failure_removes_owned_tree_and_keeps_failure(self):
        signals = Signals()
        original = RuntimeError('carrier download failure')
        with ExitStack() as stack:
            signals.install(stack)
            primary, report = self.finish(signals, primary=original, groups=[], child_attempted=False, ready=False)
        self.assertIs(primary, original)
        self.assertEqual(report['owned_group_count'], 0)
        self.assertIs(report['owned_groups_joined'], True)
        self.assertIs(report['private_tool_tree_removed'], True)
        self.assertFalse(self.work.exists())
        self.assertEqual(json.loads(self.artifact.read_bytes())['status'], 'failed')

    def test_unconfirmed_child_ownership_retains_tools_and_cannot_pass(self):
        for groups in ([], [False], [True, False]):
            with self.subTest(groups=groups), ExitStack() as stack:
                signals = Signals()
                signals.install(stack)
                remove = stack.enter_context(patch.object(CHECK.shutil, 'rmtree'))
                primary, report = self.finish(signals, groups=groups)
                remove.assert_not_called()
            self.assertIsNotNone(primary)
            self.assertTrue(self.work.exists())
            self.assertIs(report['private_tool_tree_removed'], False)
            self.assertIs(report['owned_groups_joined'], False)
            self.assertEqual(json.loads(self.artifact.read_bytes())['status'], 'failed')
            self.artifact.unlink()

    def test_repeated_handler_restore_and_mask_errors_preserve_original_failure(self):
        signals = Signals()
        original = RuntimeError('original unit failure')
        signals.restore_error = RuntimeError('repeated restore cancellation')
        signals.unmask_error = RuntimeError('late restore cancellation')
        with ExitStack() as stack:
            signals.install(stack)
            primary, report = self.finish(signals, primary=original)
        self.assertIs(primary, original)
        self.assertEqual(signals.restored, list(signals.numbers))
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(json.loads(self.artifact.read_bytes())['status'], 'failed')
        self.assertFalse(self.work.exists())

    def test_failed_mask_entry_preserves_primary_and_still_attempts_all_restores(self):
        for operation in (CHECK.signal.SIG_BLOCK, CHECK.signal.SIG_SETMASK):
            with self.subTest(operation=operation), ExitStack() as stack:
                signals = Signals()
                signals.install(stack)
                original = RuntimeError('original unit failure')
                normal_mask = signals.mask
                def failing_mask(which, numbers):
                    if which == operation:
                        raise RuntimeError('mask operation failure')
                    return normal_mask(which, numbers)
                stack.enter_context(patch.object(CHECK.signal, 'pthread_sigmask', side_effect=failing_mask))
                primary, report = self.finish(signals, primary=original)
            self.assertIs(primary, original)
            self.assertEqual(signals.restored, list(signals.numbers))
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(json.loads(self.artifact.read_bytes())['status'], 'failed')
            self.artifact.unlink()
            self.work.mkdir()

    def test_tap_requires_exact_executed_names_counts_and_no_skip(self):
        raw = (b'TAP version 13\n# Subtest: fixed case\nok 1 - fixed case\n1..1\n'
               b'# tests 1\n# suites 0\n# pass 1\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n')
        CHECK.check_tap(raw, ['fixed case'])
        for changed in (raw.replace(b'# pass 1', b'# pass 0'), raw.replace(b'ok 1 -', b'not ok 1 -'),
                        raw.replace(b'# skipped 0', b'# skipped 1'), raw + b'# tests 1\n',
                        raw.replace(b'# Subtest: fixed case', b'# Subtest: different case'),
                        raw.replace(b'ok 1 - fixed case', b'ok 1 - fixed case # SKIP')):
            with self.subTest(raw=changed), self.assertRaises(RuntimeError):
                CHECK.check_tap(changed, ['fixed case'])


if __name__ == '__main__':
    unittest.main()
