#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Source/patch contracts only; no build, server, browser or publication."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('publication_source', HERE / 'prepare.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class SourceContracts(unittest.TestCase):
    def test_manifest_and_patch_digest_bind_exact_pinned_source_and_scope(self):
        value = M.manifest()
        patch = M.read(HERE / value['patch']['path'], M.MAX_PATCH)
        self.assertEqual(len(patch), value['patch']['bytes'])
        self.assertEqual(hashlib.sha256(patch).hexdigest(), value['patch']['sha256'])
        self.assertEqual(set(value['files']), M.ALLOWED)
        self.assertIn('server-rust/src/connectors/mod.rs', value['files'])
        self.assertEqual(value['baseline_root_lock_sha256'], M.ROOT_LOCK)
        for line in patch.decode().splitlines():
            if line.startswith('+++ b/'):
                self.assertIn(line[len('+++ b/'):], M.ALLOWED)
        self.assertIn(b'SPDX-License-Identifier: AGPL-3.0-or-later', patch)
        self.assertFalse(value['acceptance']['native_publication_authorization'])
        self.assertFalse(value['capability']['whole_shutdown_drain_proven'])

    def test_manifest_rejects_scope_drift_wrong_pins_extra_paths_and_bad_types(self):
        original = M.manifest()
        cases = []
        for key, value in [('schema', True), ('upstream_commit', 'a' * 40),
                           ('baseline_root_lock_sha256', 'b' * 64), ('origin', 'https://other.invalid')]:
            changed = copy.deepcopy(original); changed[key] = value; cases.append(changed)
        changed = copy.deepcopy(original); changed['files']['private-path'] = {}; cases.append(changed)
        changed = copy.deepcopy(original); changed['patch']['path'] = '../outside'; cases.append(changed)
        changed = copy.deepcopy(original); changed['acceptance']['full_studio'] = True; cases.append(changed)
        changed = copy.deepcopy(original); changed['capability']['whole_shutdown_drain_proven'] = 0; cases.append(changed)
        for changed in cases:
            with self.subTest(changed=changed.keys()), mock.patch.object(M, 'read', return_value=json.dumps(changed).encode()):
                with self.assertRaises(ValueError): M.manifest()
        with self.assertRaises(ValueError): M.pairs([('duplicate', 1), ('duplicate', 2)])

    def test_host_apply_denied_before_source_access_or_commands(self):
        with mock.patch.dict(M.os.environ, {}, clear=True), mock.patch.object(M, 'check_source') as source, \
                mock.patch.object(M.subprocess, 'run') as command:
            with self.assertRaises(ValueError): M.apply(Path('/not-a-hosted-checkout'), {})
            source.assert_not_called(); command.assert_not_called()

    def test_apply_checks_original_patch_before_mutation_then_verifies_complete_result(self):
        value = M.manifest()
        with mock.patch.dict(M.os.environ, GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted'), \
                mock.patch.object(M, 'check_source') as source, mock.patch.object(M.subprocess, 'run') as command:
            M.apply(Path('/owned/disposable/source'), value)
        self.assertEqual([call.kwargs['patched'] for call in source.call_args_list], [False, True])
        self.assertEqual(command.call_count, 2)
        self.assertIn('--check', command.call_args_list[0].args[0])
        self.assertNotIn('--check', command.call_args_list[1].args[0])
        self.assertEqual(command.call_args_list[0].kwargs['input'], command.call_args_list[1].kwargs['input'])
        for call in command.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 20)
            self.assertNotIn('shell', call.kwargs)

    def test_actual_reader_refuses_symlink_and_oversized_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original = root / 'original'; original.write_bytes(b'public bytes')
            original.chmod(0o644)
            link = root / 'link'; link.symlink_to(original)
            with self.assertRaises(OSError): M.read(link, 100)
            with self.assertRaises(ValueError): M.read(original, 1)
            self.assertEqual(M.read(original, 100), b'public bytes')

    def graph_fixture(self, root, drift):
        original = b'version = 4\n\n[[package]]\nname = "other"\nversion = "1"\n\n[[package]]\nname = "silex-server"\nversion = "0.1.0"\ndependencies = [\n "mime_guess",\n]\n'
        patched = original.replace(b' "mime_guess",\n', b' "mime_guess",\n "rustix",\n')
        if drift == 'other': patched = patched.replace(b'name = "other"\nversion = "1"', b'name = "other"\nversion = "2"')
        if drift == 'extra': patched += b'\n[[package]]\nname = "unreviewed"\nversion = "1"\n'
        if drift == 'server': patched = patched.replace(b' "rustix",', b' "unreviewed",')
        records = {}
        for name in M.ALLOWED:
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            raw = patched if name == 'Cargo.lock' else b'public source\n'
            path.write_bytes(raw); path.chmod(0o644)
            records[name] = {'before': None, 'after': {'bytes': len(raw), 'sha256': M.digest(raw), 'mode': '100644'}}
        ignored = root / 'server-rust/Cargo.lock'; ignored.write_bytes(b'ignored lock\n'); ignored.chmod(0o644)
        def git(_source, *arguments):
            if arguments == ('rev-parse', 'HEAD'): return M.UPSTREAM.encode() + b'\n'
            if arguments == ('diff', '--name-only', 'HEAD'): return ('\n'.join(sorted(M.ALLOWED)) + '\n').encode()
            if arguments == ('ls-files', '--others', '--exclude-standard'): return b''
            if arguments == ('show', 'HEAD:Cargo.lock'): return original
            if arguments == ('show', 'HEAD:server-rust/Cargo.lock'): return b'ignored lock\n'
            self.fail('unexpected source query')
        return original, {'files': records}, git

    def test_root_workspace_graph_allows_only_one_existing_rustix_edge(self):
        for drift in (None, 'other', 'extra', 'server'):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as directory:
                source = Path(directory).resolve()
                original, value, git = self.graph_fixture(source, drift)
                with mock.patch.object(M, 'ROOT_LOCK', M.digest(original)), mock.patch.object(M, 'git', side_effect=git):
                    if drift is None: M.check_source(source, value, patched=True)
                    else:
                        with self.assertRaises(ValueError): M.check_source(source, value, patched=True)


if __name__ == '__main__':
    unittest.main()
