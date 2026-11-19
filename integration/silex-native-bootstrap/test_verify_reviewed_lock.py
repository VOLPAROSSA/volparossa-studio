#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only controls for one reviewed graph; no compiler or application execution."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('native_reviewed_lock', HERE / 'verify_reviewed_lock.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class ReviewedLockTests(unittest.TestCase):
    def test_wrong_candidate_bytes_are_rejected_before_record_or_metadata_processing(self):
        with mock.patch.object(M.SUPPORT, 'ledger') as ledger, self.assertRaises(M.SUPPORT.Rejected) as caught:
            M.check_candidate(b'a different public lock candidate')
        self.assertEqual(caught.exception.kind, 'source_rejected')
        ledger.assert_not_called()
        self.assertEqual(M.CANDIDATE, 'de04aaf5ff1acbdde421e3447ea67f3eb7a00a7d5ed118f4387a180e84590118')

    def test_exact_reviewed_record_count_is_required_even_after_matching_digest(self):
        for count in (562, 564, 607):
            with mock.patch.object(M.SUPPORT, 'digest', return_value=M.CANDIDATE), \
                    mock.patch.object(M.SUPPORT, 'ledger', return_value=(4, dict.fromkeys(range(count)))), \
                    self.assertRaises(M.SUPPORT.Rejected) as caught:
                M.check_candidate(b'public ledger fixture')
            self.assertEqual(caught.exception.kind, 'ledger_rejected')
        with mock.patch.object(M.SUPPORT, 'digest', return_value=M.CANDIDATE), \
                mock.patch.object(M.SUPPORT, 'ledger', return_value=(4, dict.fromkeys(range(563)))):
            self.assertEqual(M.check_candidate(b'public ledger fixture'), 563)

    def test_shared_metadata_requires_real_full_resolve_graph_and_exact_workspace(self):
        source = Path('/public-source')
        value = {'version': 1, 'workspace_root': str(source),
                 'resolve': {'nodes': [{'id': 'public fixture', 'dependencies': []}]}}
        M.SUPPORT.metadata(json.dumps(value).encode(), source)
        for graph in (None, {}, {'nodes': []}):
            changed = dict(value, resolve=graph)
            with self.assertRaises(M.SUPPORT.Rejected):
                M.SUPPORT.metadata(json.dumps(changed).encode(), source)
        with self.assertRaises(M.SUPPORT.Rejected):
            M.SUPPORT.metadata(json.dumps(dict(value, workspace_root='/different-source')).encode(), source)

    def test_actual_changed_root_lock_is_rejected_before_any_later_git_or_metadata_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            path = source / 'Cargo.lock'
            original = b'original public candidate bytes'
            path.write_bytes(original)
            path.chmod(0o644)
            path.write_bytes(b'mutated public candidate bytes')
            with mock.patch.object(M.SUPPORT, 'snapshot') as snapshot, \
                    mock.patch.object(M.SUPPORT, 'run') as run, self.assertRaises(M.SUPPORT.Rejected) as caught:
                M.unchanged(source, original, None, {}, 0, {'started': 0, 'joined': 0})
            self.assertEqual(caught.exception.kind, 'source_rejected')
            snapshot.assert_not_called()
            run.assert_not_called()

    def test_candidate_overrides_and_extra_modes_are_not_cli_authority(self):
        for extra in ('--candidate', '--fetch-base', '--relax-ledger'):
            with mock.patch('sys.argv', ['verify_reviewed_lock.py', '--source', '/public-source',
                                         extra, 'unapproved']), \
                    mock.patch.object(M.SUPPORT, 'run') as run, self.assertRaises(M.SUPPORT.Rejected):
                M.main()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
