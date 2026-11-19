#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only source-overlay controls; no SDK, application or network execution."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('native_bootstrap_prepare', HERE / 'prepare.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def descriptor():
    return json.loads((HERE / 'manifest.json').read_bytes())


def recorded(raw):
    return {'bytes': len(raw), 'mode': '100644', 'sha256': M.digest(raw)}


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o644)


class PreparationTests(unittest.TestCase):
    def reject_descriptor(self, value):
        with self.assertRaises(ValueError):
            M.parse_manifest(json.dumps(value).encode())

    def test_exact_descriptor_and_only_optional_pinned_root_lock_membership(self):
        value = descriptor()
        self.assertEqual(M.parse_manifest(json.dumps(value).encode()), value)
        self.assertTrue(M.NATIVE <= value['files'].keys())
        expanded = copy.deepcopy(value)
        expanded['files']['Cargo.lock'] = {
            'before': {'bytes': 159405, 'mode': '100644', 'sha256': M.BASE_LOCK},
            'after': {'bytes': 159400, 'mode': '100644', 'sha256': 'a' * 64},
        }
        self.assertEqual(M.parse_manifest(json.dumps(expanded).encode()), expanded)
        expanded['files']['Cargo.lock']['before']['sha256'] = '0' * 64
        self.reject_descriptor(expanded)

    def test_duplicate_fields_unknown_authority_flags_and_base_pin_changes_are_rejected(self):
        value = descriptor()
        raw = json.dumps(value).replace('"schema": 1', '"schema": 1, "schema": 1', 1).encode()
        with self.assertRaises(ValueError):
            M.parse_manifest(raw)
        for key in ('base_publication_manifest_sha256', 'base_publication_patch_sha256',
                    'base_patched_root_lock_sha256', 'upstream_commit'):
            changed = copy.deepcopy(value)
            changed[key] = '0' * len(changed[key])
            self.reject_descriptor(changed)
        for key in value['acceptance']:
            for bad in (True, 0, None):
                changed = copy.deepcopy(value)
                changed['acceptance'][key] = bad
                self.reject_descriptor(changed)
        for key, bad in (('schema', True), ('schema', 2), ('extra', False)):
            changed = copy.deepcopy(value)
            changed[key] = bad
            self.reject_descriptor(changed)

    def test_file_whitelist_modes_lengths_and_fixed_patch_filename_are_closed(self):
        value = descriptor()
        selected = sorted(M.NATIVE)[0]
        for name in ('../outside', '/absolute', 'desktop/src-tauri/Cargo.lock',
                     'server-rust/src/extra.rs'):
            changed = copy.deepcopy(value)
            changed['files'][name] = changed['files'].pop(selected)
            self.reject_descriptor(changed)
        for key, bad in (('mode', '100755'), ('mode', '120000'), ('bytes', True),
                         ('bytes', M.MAX_FILE + 1), ('sha256', 'A' * 64)):
            changed = copy.deepcopy(value)
            changed['files'][selected]['after'][key] = bad
            self.reject_descriptor(changed)
        changed = copy.deepcopy(value)
        changed['files'][selected]['before'] = None
        self.reject_descriptor(changed)
        for bad in ('../other.patch', '/absolute.patch', 'patches/other.patch'):
            changed = copy.deepcopy(value)
            changed['patch']['path'] = bad
            self.reject_descriptor(changed)
        with self.assertRaises(ValueError):
            M.parse_manifest(b' ' * (M.MAX_MANIFEST + 1))

    def test_patch_headers_modes_and_digest_fail_before_any_git_invocation(self):
        value = descriptor()
        raw = (HERE / M.PATCH_PATH).read_bytes()
        M.check_patch(raw, value['files'])
        without_index = b''.join(line for line in raw.splitlines(keepends=True)
                                 if not line.startswith(b'index '))
        M.check_patch(without_index, value['files'])
        if 'Cargo.lock' not in value['files']:
            lock = (b'diff --git a/Cargo.lock b/Cargo.lock\n--- a/Cargo.lock\n+++ b/Cargo.lock\n'
                    b'@@ -1 +1 @@\n-old\n+new\n')
            M.check_patch(raw + lock, M.NATIVE | {'Cargo.lock'})
        first = raw.splitlines()[0]
        cases = [
            raw.replace(first, b'diff --git a/../outside b/../outside', 1),
            raw.replace(b' 100644\n', b' 120000\n', 1),
            raw.replace(b'--- a/desktop/', b'--- a/other/', 1),
            b'GIT binary patch\n' + raw,
            raw.replace(b'index ', b'new file mode 100644\nindex ', 1),
            raw[:-1], raw + b'\0',
        ]
        for changed in cases:
            with self.subTest(kind=cases.index(changed)), self.assertRaises(ValueError):
                M.check_patch(changed, value['files'])
        with mock.patch.object(M, 'read', return_value=raw + b'changed'), \
                mock.patch.object(M, 'command') as command, self.assertRaises(ValueError):
            M.patch_bytes(value)
        command.assert_not_called()

    def test_owned_reader_refuses_symlink_hardlink_mode_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'payload'
            write(path, b'public source')
            self.assertEqual(M.read(path, 32), b'public source')
            path.chmod(0o666)
            with self.assertRaises(ValueError):
                M.read(path, 32)
            path.chmod(0o644)
            alias = root / 'alias'
            alias.symlink_to(path)
            with self.assertRaises((OSError, ValueError)):
                M.read(alias, 32)
            alias.unlink()
            os.link(path, alias)
            with self.assertRaises(ValueError):
                M.read(path, 32)
            alias.unlink()
            with self.assertRaises(ValueError):
                M.read(path, 2)
            alias.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                M.read(alias / 'payload', 32)

    def test_partial_source_extra_effects_and_changed_base_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            base = {'files': {}}
            value = {'files': {}}
            originals = {}
            for name in M.BASE_FILES:
                raw = f'approved base {name}\n'.encode()
                write(source / name, raw)
                base['files'][name] = {'after': recorded(raw)}
            for name in M.NATIVE:
                before, after = f'before {name}\n'.encode(), f'after {name}\n'.encode()
                write(source / name, before)
                originals[name] = before
                value['files'][name] = {'before': recorded(before), 'after': recorded(after)}
            for name in ('server-rust/Cargo.lock', 'desktop/src-tauri/Cargo.lock'):
                originals[name] = b'unchanged legacy lock\n'
                write(source / name, originals[name])
            changed = set(M.BASE_FILES)
            head = [M.UPSTREAM]

            def git(_source, *args, **_kwargs):
                if args == ('rev-parse', '--show-toplevel'):
                    return str(source).encode() + b'\n'
                if args == ('rev-parse', 'HEAD'):
                    return head[0].encode() + b'\n'
                if args[0] == 'show':
                    return originals[args[1].removeprefix('HEAD:')]
                if args[:2] == ('ls-files', '-v'):
                    return b'H tracked\0'
                if args[0] == 'diff' and '--cached' not in args:
                    return b'\0'.join(name.encode() for name in changed) + b'\0'
                return b''

            with mock.patch.object(M, 'command', side_effect=git):
                M.check_source(source, value, base, patched=False)
                head[0] = '0' * 40
                with self.assertRaises(ValueError):
                    M.check_source(source, value, base, patched=False)
                head[0] = M.UPSTREAM
                missing = source / sorted(M.NATIVE)[0]
                saved = missing.read_bytes()
                missing.unlink()
                with self.assertRaises((OSError, ValueError)):
                    M.check_source(source, value, base, patched=False)
                write(missing, saved)
                changed.add('extra.rs')
                with self.assertRaises(ValueError):
                    M.check_source(source, value, base, patched=False)
                changed.remove('extra.rs')
                for name in M.NATIVE:
                    write(source / name, f'after {name}\n'.encode())
                changed.update(M.NATIVE)
                M.check_source(source, value, base, patched=True)
                write(source / 'server-rust/Cargo.toml', b'mutated base')
                with self.assertRaises(ValueError):
                    M.check_source(source, value, base, patched=True)

    def test_hosted_pin_guards_reject_before_any_source_command(self):
        environment = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                       'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64'}
        with mock.patch.object(M.os, 'getuid', return_value=1001), \
                mock.patch.object(M.os, 'geteuid', return_value=1001), \
                mock.patch.object(M.os, 'uname', return_value=SimpleNamespace(machine='x86_64')), \
                mock.patch.object(M.sys, 'platform', 'linux'), mock.patch.object(M, 'command') as command:
            for key in environment:
                changed = dict(environment, **{key: 'not-approved'})
                with mock.patch.dict(os.environ, changed, clear=True), self.assertRaises(ValueError):
                    M.hosted_guard(Path('/not-used'))
            with mock.patch.object(M.os, 'geteuid', return_value=0), self.assertRaises(ValueError):
                M.hosted_guard(Path('/not-used'))
        command.assert_not_called()

    def test_apply_guard_and_bad_digest_never_reach_git_apply(self):
        value = descriptor()
        with mock.patch.object(M, 'hosted_guard', side_effect=M.Rejected()), \
                mock.patch.object(M, 'command') as command, self.assertRaises(ValueError):
            M.apply(Path('/not-used'), value, {})
        command.assert_not_called()
        with mock.patch.object(M, 'hosted_guard'), mock.patch.object(M, 'check_source'), \
                mock.patch.object(M, 'patch_bytes', side_effect=M.Rejected()), \
                mock.patch.object(M, 'command') as command, self.assertRaises(ValueError):
            M.apply(Path('/not-used'), value, {})
        command.assert_not_called()

    def test_only_fixed_studio_checkout_and_silex_sibling_or_runner_temp_are_allowed(self):
        workspace = Path('/approved-workspace')
        root = workspace / 'studio'
        temporary = Path('/approved-runner-temp')
        expected = 'a' * 40
        environment = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                       'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'GITHUB_SHA': expected,
                       'GITHUB_WORKSPACE': str(workspace), 'RUNNER_TEMP': str(temporary)}

        def git(source, *args):
            self.assertEqual(source, root)
            if args == ('rev-parse', '--show-toplevel'):
                return str(root).encode() + b'\n'
            if args == ('rev-parse', 'HEAD'):
                return expected.encode() + b'\n'
            return b''

        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(M, 'ROOT', root), mock.patch.object(M, 'directory'), \
                mock.patch.object(M.os, 'getuid', return_value=1001), \
                mock.patch.object(M.os, 'geteuid', return_value=1001), \
                mock.patch.object(M.os, 'uname', return_value=SimpleNamespace(machine='x86_64')), \
                mock.patch.object(M.sys, 'platform', 'linux'), \
                mock.patch.object(M, 'command', side_effect=git) as command:
            for source in (workspace / 'silex', temporary / 'private-source/silex'):
                M.hosted_guard(source)
            for source in (root / 'silex', workspace / 'other-source', temporary):
                command.reset_mock()
                with self.assertRaises(ValueError):
                    M.hosted_guard(source)
                command.assert_not_called()
            with mock.patch.object(M, 'ROOT', workspace):
                command.reset_mock()
                with self.assertRaises(ValueError):
                    M.hosted_guard(workspace / 'silex')
                command.assert_not_called()

    def test_git_output_deadline_and_interruption_kill_then_join_only_the_owned_child(self):
        for mode, failure in (('output', None), ('interrupt', KeyboardInterrupt()), ('deadline', None)):
            stdout, stderr = mock.Mock(), mock.Mock()
            stdout.fileno.return_value, stderr.fileno.return_value = 10, 11
            child = SimpleNamespace(stdin=None, stdout=stdout, stderr=stderr, pid=12345,
                                    returncode=None)

            def joined(timeout):
                self.assertLessEqual(timeout, 2)
                child.returncode = -9

            child.wait = mock.Mock(side_effect=joined)
            selector = mock.MagicMock()
            selector.__enter__.return_value = selector
            selector.get_map.return_value = {10: True}
            selector.select.return_value = [(SimpleNamespace(fileobj=stdout), None)]
            with mock.patch.object(M.subprocess, 'Popen', return_value=child) as spawn, \
                    mock.patch.object(M.selectors, 'DefaultSelector', return_value=selector), \
                    mock.patch.object(M.os, 'set_blocking'), mock.patch.object(M.os, 'killpg') as kill, \
                    mock.patch.object(M.os, 'read', return_value=b'four', side_effect=failure), \
                    mock.patch.object(M, 'MAX_FILE', 3), \
                    mock.patch.object(M.time, 'monotonic', side_effect=[0, 21] if mode == 'deadline'
                                      else None, return_value=0):
                expected = M.Rejected if failure is None else KeyboardInterrupt
                with self.assertRaises(expected) as caught:
                    M.command(Path('/fixed-source'), 'rev-parse', 'HEAD')
            if failure is not None:
                self.assertIs(caught.exception, failure)
            kill.assert_called_once_with(child.pid, M.signal.SIGKILL)
            child.wait.assert_called_once()
            stdout.close.assert_called_once()
            stderr.close.assert_called_once()
            self.assertEqual(spawn.call_args.args[0][0], '/usr/bin/git')
            self.assertEqual(spawn.call_args.kwargs['env']['PATH'], '/usr/bin:/bin')
            self.assertNotIn('SSH_AUTH_SOCK', spawn.call_args.kwargs['env'])

    def test_repeated_cancellation_during_cleanup_preserves_first_failure_and_restores_handlers(self):
        for cleanup_fails in (False, True):
            primary = M.Rejected('original source cancellation')

            def cancelled(_number, _frame):
                raise M.Rejected('later cancellation must not interrupt cleanup')

            handlers = {number: cancelled for number in (M.signal.SIGINT, M.signal.SIGTERM, M.signal.SIGHUP)}
            original = dict(handlers)

            def set_handler(number, handler):
                previous = handlers[number]
                handlers[number] = handler
                return previous

            def repeated_cancellation(*_args, **_kwargs):
                for number in handlers:
                    self.assertEqual(handlers[number], M.signal.SIG_IGN)
                    if callable(handlers[number]):
                        handlers[number](number, None)

            stdout, stderr = mock.Mock(), mock.Mock()
            stdout.fileno.return_value, stderr.fileno.return_value = 10, 11
            child = SimpleNamespace(stdin=None, stdout=stdout, stderr=stderr, pid=12345,
                                    returncode=None)

            def joined(timeout):
                self.assertEqual(timeout, 2)
                repeated_cancellation()
                if cleanup_fails:
                    raise M.subprocess.TimeoutExpired('fixed git', timeout)
                child.returncode = -9

            child.wait = mock.Mock(side_effect=joined)
            selector = mock.MagicMock()
            selector.__enter__.return_value = selector
            selector.get_map.return_value = {10: True}
            selector.select.return_value = [(SimpleNamespace(fileobj=stdout), None)]
            with mock.patch.object(M.subprocess, 'Popen', return_value=child), \
                    mock.patch.object(M.selectors, 'DefaultSelector', return_value=selector), \
                    mock.patch.object(M.os, 'set_blocking'), \
                    mock.patch.object(M.os, 'read', side_effect=primary), \
                    mock.patch.object(M.os, 'killpg', side_effect=repeated_cancellation) as kill, \
                    mock.patch.object(M.signal, 'getsignal', side_effect=handlers.__getitem__), \
                    mock.patch.object(M.signal, 'signal', side_effect=set_handler):
                with self.assertRaises(M.Rejected) as caught:
                    M.command(Path('/fixed-source'), 'rev-parse', 'HEAD')
            self.assertIs(caught.exception, primary)
            self.assertEqual(handlers, original)
            kill.assert_called_once_with(child.pid, M.signal.SIGKILL)
            child.wait.assert_called_once_with(timeout=2)
            stdout.close.assert_called_once()
            stderr.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
