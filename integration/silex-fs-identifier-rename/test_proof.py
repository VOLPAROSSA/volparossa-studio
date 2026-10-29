# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only proof protocol controls; no compiler, native app or dependency run."""
import hashlib
import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('fs_proof_under_test', Path(__file__).with_name('proof.py'))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def output(names=None):
    names = sorted(M.EXPECTED) + ['existing::legacy_case'] if names is None else names
    return ('running ' + str(len(names)) + ' tests\n' +
            ''.join('test ' + name + ' ... ok\n' for name in names) +
            f'\ntest result: ok. {len(names)} passed; 0 failed; 0 ignored; 0 measured; '
            '0 filtered out; finished in 0.04s\n').encode()


def source_fixture(extra=b'', staged=b'', tracked=b'H ordinary.rs\0'):
    source = Path('/fixed/silex')
    records = {name: dict(sha256=key * 64, mode='100644') for name, key in
               [('base.rs', 'a'), ('native.rs', 'b'), ('fs.rs', 'c')]}
    base = dict(files={'base.rs': {'after': records['base.rs']}})
    native_overlay = dict(files={'native.rs': {'after': records['native.rs']}})
    fs_value = dict(files={'fs.rs': {'after': records['fs.rs']}})
    def git(arguments, *_args):
        self_args = arguments[2:]
        if self_args == ['rev-parse', '--show-toplevel']:
            return str(source).encode() + b'\n'
        if self_args == ['rev-parse', 'HEAD']:
            return b'672efed69dda04c0a1e968859239e042f00d9538\n'
        if self_args[:2] == ['diff', '--cached']:
            return staged
        if self_args[:2] == ['ls-files', '-v']:
            return tracked
        if self_args[:2] == ['diff', '--no-ext-diff']:
            return b'base.rs\0native.rs\0fs.rs\0' + extra
        if self_args[:2] == ['ls-files', '--others']:
            return b''
        if self_args[0] == 'show':
            return self_args[1].encode()
        raise AssertionError('unexpected source operation')
    def read(path):
        return b'pinned' if path.name == 'Cargo.lock' and path.parent == source else ('HEAD:' + str(path.relative_to(source))).encode()
    support = SimpleNamespace(directory=Mock(), read=Mock(side_effect=read),
                              ledger=Mock(return_value=(1, {i: None for i in range(563)})))
    native = SimpleNamespace(git=Mock(side_effect=git), SUPPORT=support)
    fs = SimpleNamespace(SUPPORT=SimpleNamespace(UPSTREAM='672efed69dda04c0a1e968859239e042f00d9538', check_file=Mock()))
    return native, fs, source, fs_value, base, native_overlay, records


class ProofTests(unittest.TestCase):
    def test_fourteen_case_names_bind_the_reviewed_source_patch(self):
        raw = (M.HERE / 'patches/fs-identifier-rename.patch').read_text()
        names = set(re.findall(r'^\+(?:async )?fn ([a-z0-9_]+)', raw, re.MULTILINE))
        self.assertEqual(len(M.EXPECTED), 14)
        self.assertTrue(set(M.METADATA_CASES + M.STORAGE_CASES) <= names)

    def test_fixed_command_runs_only_offline_locked_server_library(self):
        self.assertEqual(M.test_command(Path('/private/runner-temp')), [
            '/private/runner-temp/volparossa-rust-1.99.1/bin/cargo', 'test', '--offline', '--locked',
            '-p', 'silex-server', '--lib', '--', '--test-threads=1'])

    def test_actual_suite_rows_bind_all_reviewed_cases_without_invented_suite_total(self):
        result = M.test_result(output())
        self.assertEqual(result, dict(tests=15, passed=15, failed=0, ignored=0, filtered=0,
                         reviewed_fs_cases=14, output_sha256=hashlib.sha256(output()).hexdigest()))
        self.assertEqual(M.test_result(output(sorted(M.EXPECTED)))['tests'], 14)

    def test_missing_duplicate_ignored_failed_filtered_or_multiple_suites_are_rejected(self):
        raw = output()
        first = sorted(M.EXPECTED)[0].encode()
        variants = [output(sorted(M.EXPECTED)[1:]), output(sorted(M.EXPECTED) + [sorted(M.EXPECTED)[0]]),
                    raw.replace(b' ... ok', b' ... ignored', 1), raw.replace(b' ... ok', b' ... FAILED', 1),
                    raw.replace(b'0 filtered out', b'1 filtered out'), raw + raw,
                    raw.replace(first, b'unrelated::replacement'), raw.replace(b'15 passed', b'14 passed'),
                    raw.replace(b'running 15 tests', b'running 0 tests')]
        for changed in variants:
            with self.subTest(sha=hashlib.sha256(changed).hexdigest()), self.assertRaises(M.Rejected):
                M.test_result(changed)

    def test_output_is_bounded_and_only_a_hash_and_closed_counts_leave_parser(self):
        raw = b'private path or payload must not be retained\n' + output()
        result = M.test_result(raw)
        self.assertEqual(set(result), {'tests', 'passed', 'failed', 'ignored', 'filtered',
                                     'reviewed_fs_cases', 'output_sha256'})
        with self.assertRaises(M.Rejected):
            M.test_result(b'x' * (16 * 1024 * 1024 + 1))

    def test_source_guard_binds_exact_union_legacy_locks_and_all_owned_git_reads(self):
        native, fs, source, value, base, overlay, records = source_fixture()
        with patch.object(M, 'LOCK', hashlib.sha256(b'pinned').hexdigest()), \
                patch.object(M.Path, 'lstat', return_value=SimpleNamespace(st_mode=0o100644)):
            hashes = M.source_check(native, fs, source, value, base, overlay, {}, 100, [], object())
        self.assertEqual(hashes, {name: row['sha256'] for name, row in records.items()})
        self.assertEqual(fs.SUPPORT.check_file.call_count, 3)
        self.assertTrue(all(call.args[0][:2] == ['-C', str(source)] for call in native.git.call_args_list))

    def test_extra_changed_files_staging_or_hidden_index_flags_fail_before_file_claims(self):
        for args in (dict(extra=b'unreviewed.rs\0'), dict(staged=b'base.rs\0'), dict(tracked=b'S hidden.rs\0')):
            with self.subTest(args=args):
                native, fs, source, value, base, overlay, _ = source_fixture(**args)
                with self.assertRaises(M.Rejected):
                    M.source_check(native, fs, source, value, base, overlay, {}, 100, [], object())
                fs.SUPPORT.check_file.assert_not_called()

    def test_changed_root_lock_or_legacy_lock_is_refused(self):
        native, fs, source, value, base, overlay, _ = source_fixture()
        with patch.object(M.Path, 'lstat', return_value=SimpleNamespace(st_mode=0o100644)), self.assertRaises(M.Rejected):
            M.source_check(native, fs, source, value, base, overlay, {}, 100, [], object())
        original = native.SUPPORT.read.side_effect
        native.SUPPORT.read.side_effect = lambda path: b'mutated' if path == source / 'server-rust/Cargo.lock' else original(path)
        with patch.object(M, 'LOCK', hashlib.sha256(b'pinned').hexdigest()), \
                patch.object(M.Path, 'lstat', return_value=SimpleNamespace(st_mode=0o100644)), self.assertRaises(M.Rejected):
            M.source_check(native, fs, source, value, base, overlay, {}, 100, [], object())

    def test_exact_git_mode_is_checked_even_when_bytes_and_hash_match(self):
        native, fs, source, value, base, overlay, _ = source_fixture()
        with patch.object(M.Path, 'lstat', return_value=SimpleNamespace(st_mode=0o100755)), self.assertRaises(M.Rejected):
            M.source_check(native, fs, source, value, base, overlay, {}, 100, [], object())
        fs.SUPPORT.check_file.assert_called_once()

    def test_success_reads_the_bounded_private_combined_log_not_the_empty_actor_return(self):
        native = SimpleNamespace(actor=Mock(return_value=b''), read_file=Mock(return_value=output()),
                                 compiler_diagnostic=Mock(), Rejected=M.Rejected)
        work = Path('/private/work')
        report = dict(compiler_diagnostic=None, rust_test_binary_executed=False)
        observed = M.execute_tests(native, Path('/private'), Path('/source'), work, {}, 100, [], object(), report)
        self.assertEqual(observed['tests'], 15)
        self.assertIs(report['rust_test_binary_executed'], True)
        self.assertEqual(native.actor.call_args.kwargs['log'], work / 'logs/native-cargo.log')
        native.read_file.assert_called_once_with(work / 'logs/native-cargo.log', 16 * 1024 * 1024, modes=(0o600,))
        native.compiler_diagnostic.assert_not_called()

    def test_optional_compile_observer_keeps_original_failure_and_closed_clipping(self):
        for observer_fails in (False, True):
            with self.subTest(observer_fails=observer_fails):
                original = M.Rejected('output_limit')
                native = SimpleNamespace(actor=Mock(side_effect=original), read_file=Mock(), Rejected=M.Rejected,
                    compiler_diagnostic=Mock(**(dict(side_effect=RuntimeError('private observer failure'))
                                               if observer_fails else dict(return_value={'status': 'clipped'}))))
                report = dict(compiler_diagnostic=None, rust_test_binary_executed=False)
                with self.assertRaises(M.Rejected) as caught:
                    M.execute_tests(native, Path('/private'), Path('/source'), Path('/work'), {}, 100, [], object(), report)
                self.assertIs(caught.exception, original)
                self.assertEqual(report['compiler_diagnostic'], None if observer_fails else {'status': 'clipped'})
                self.assertIs(report['rust_test_binary_executed'], False)
                native.compiler_diagnostic.assert_called_once_with(Path('/work'), clipped=True)
                native.read_file.assert_not_called()

    def test_failure_projection_drops_unknown_messages_and_keeps_closed_classes(self):
        self.assertEqual(M.failure_kind(RuntimeError('private/path?token=not-public')), 'source_rejected')
        for kind in M.KINDS:
            self.assertEqual(M.failure_kind(M.Rejected(kind)), kind)
        self.assertEqual(M.failure_kind(KeyboardInterrupt('private')), 'cancelled')
        with self.assertRaises(ValueError):
            M.Rejected('freeform-private-error')

    def test_authored_proof_keeps_exact_reused_source_pins(self):
        for path, expected in M.PINS.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_wrong_profile_or_nonabsolute_entry_is_refused_before_any_helper_import(self):
        with patch.object(M.sys, 'argv', [str(M.HERE / 'proof.py')]), \
                patch.dict(M.os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch',
                                         'GITHUB_REF': 'refs/heads/unapproved'}), \
                patch.object(M, 'load') as load, self.assertRaises(M.Rejected):
            M.main()
        load.assert_not_called()
        with patch.object(M.sys, 'argv', ['proof.py']), patch.object(M, 'load') as load, \
                self.assertRaises(M.Rejected):
            M.main()
        load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
