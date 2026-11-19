#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only pure ledger and source-only resolver controls; no Cargo or SDK execution."""
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
SPEC = importlib.util.spec_from_file_location('native_bootstrap_resolve_lock', HERE / 'resolve_lock.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def encode(packages, *, version=4):
    text = f'version = {version}\n'
    for package in packages:
        text += '\n[[package]]\n'
        for key, value in package.items():
            text += f'{key} = {json.dumps(value)}\n'
    return text.encode()


def original():
    packages = [
        {'name': 'silex-desktop', 'version': '0.1.0',
         'dependencies': sorted(M.REMOVED | {'silex-server', 'serde'})},
        {'name': 'silex-server', 'version': '0.1.0', 'dependencies': ['serde']},
    ]
    for name in sorted(M.REMOVED | {'serde'}):
        packages.append({'name': name, 'version': '1.0.0', 'source': M.REGISTRY, 'checksum': 'a' * 64})
    return packages


def candidate(packages):
    result = copy.deepcopy(packages)
    result[0]['dependencies'] = [name for name in result[0]['dependencies'] if name not in M.REMOVED]
    return [package for package in result if package['name'] not in M.REMOVED]


class LockResolutionTests(unittest.TestCase):
    def reject(self, old, new):
        with self.assertRaises(M.Rejected) as caught:
            M.compare_ledgers(encode(old), encode(new))
        self.assertEqual(caught.exception.kind, 'ledger_rejected')

    def test_only_desktop_removals_allow_unused_registry_records_to_disappear(self):
        old = original()
        new = candidate(old)
        proof = M.compare_ledgers(encode(old), encode(new))
        self.assertEqual(proof['old_package_records'], 8)
        self.assertEqual(proof['new_package_records'], 3)
        self.assertEqual(proof['desktop_removed_dependencies'], sorted(M.REMOVED))
        self.assertEqual([record['name'] for record in proof['removed_package_records']], sorted(M.REMOVED))
        self.assertTrue(all(record['source'] == 'crates_io' for record in proof['removed_package_records']))
        self.assertIs(proof['only_desktop_dependency_delta'], True)
        self.assertIs(proof['retained_pins_unchanged'], True)
        # Retaining now-unused registry records is also harmless; no package is added.
        retained = copy.deepcopy(old)
        retained[0]['dependencies'] = new[0]['dependencies']
        self.assertEqual(M.compare_ledgers(encode(old), encode(retained))['removed_package_records'], [])

    def test_additions_versions_sources_checksums_and_non_desktop_edges_fail_closed(self):
        old = original()
        valid = candidate(old)
        for field, bad in (('version', '2.0.0'), ('checksum', 'b' * 64),
                           ('source', 'git+https://not-allowed.invalid/repository')):
            changed = copy.deepcopy(valid)
            changed[2][field] = bad
            self.reject(old, changed)
        changed = copy.deepcopy(valid)
        changed.append({'name': 'added', 'version': '1.0.0', 'source': M.REGISTRY, 'checksum': 'a' * 64})
        self.reject(old, changed)
        changed = copy.deepcopy(valid)
        changed[1]['dependencies'] = ['serde', 'dirs']
        self.reject(old, changed)
        changed = copy.deepcopy(valid)
        changed[2]['dependencies'] = []  # Even a semantically plausible common-record rewrite needs review.
        self.reject(old, changed)

    def test_desktop_delta_is_exact_and_both_workspace_records_remain_required(self):
        old = original()
        valid = candidate(old)
        for dependencies in (valid[0]['dependencies'] + ['uuid'], ['serde'],
                             valid[0]['dependencies'] + ['unapproved']):
            changed = copy.deepcopy(valid)
            changed[0]['dependencies'] = dependencies
            self.reject(old, changed)
        for missing in ('silex-desktop', 'silex-server'):
            self.reject(old, [item for item in valid if item['name'] != missing])
        changed = copy.deepcopy(valid)
        changed.append(copy.deepcopy(changed[-1]))
        self.reject(old, changed)
        changed = copy.deepcopy(old)
        changed[0]['dependencies'].remove('uuid')
        self.reject(changed, valid)

    def test_top_level_types_unknown_tables_duplicate_records_and_oversize_are_rejected(self):
        old = encode(original())
        new = encode(candidate(original()))
        for raw in (new.replace(b'version = 4', b'version = true', 1),
                    new.replace(b'version = 4', b'version = 3', 1),
                    new + b'\n[metadata]\nextra = true\n',
                    new + b'\nversion = 4\n', b'x' * (M.MAX_BYTES + 1)):
            with self.assertRaises(M.Rejected):
                M.compare_ledgers(old, raw)

    def test_metadata_root_and_json_versions_are_checked_without_exposing_raw_values(self):
        source = Path('/public-source')
        valid = {'version': 1, 'workspace_root': str(source),
                 'resolve': {'nodes': [{'id': 'public fixture', 'dependencies': []}]}}
        M.metadata(json.dumps(valid).encode(), source)
        for raw in (b'{"version":true,"workspace_root":"/public-source"}',
                    b'{"version":1,"workspace_root":"/private/unexpected"}',
                    b'{"version":1,"version":1,"workspace_root":"/public-source"}', b'not json'):
            with self.assertRaises(M.Rejected) as caught:
                M.metadata(raw, source)
            self.assertEqual(str(caught.exception), 'native lock resolution rejected')
        for missing_graph in (None, {}, {'nodes': []}, {'nodes': None}, {'nodes': [None]}):
            with self.assertRaises(M.Rejected):
                M.metadata(json.dumps(dict(valid, resolve=missing_graph)).encode(), source)

    def test_full_graph_output_has_separate_bounded_cap_without_widening_lock_input(self):
        source = Path('/public-source')
        full = {'version': 1, 'workspace_root': str(source),
                'resolve': {'nodes': [{'id': 'public fixture', 'dependencies': []}]},
                'padding': 'x' * (M.MAX_BYTES + 1)}
        M.metadata(json.dumps(full).encode(), source)
        self.assertEqual(M.MAX_BYTES, 2 * 1024 * 1024)
        self.assertEqual(M.MAX_METADATA_BYTES, 8 * 1024 * 1024)
        with self.assertRaises(M.Rejected):
            M.metadata(b' ' * (M.MAX_METADATA_BYTES + 1), source)

    def test_fixed_environment_rejects_config_and_binary_wrappers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'silex'
            source.mkdir()
            prefix = root / 'volparossa-rust-1.99.1'
            prefix.mkdir(mode=0o700)
            (prefix / 'bin').mkdir()
            home = root / 'silex-native-cargo-public-v1'
            home.mkdir(mode=0o700)
            for name in ('cargo', 'rustc', 'rustdoc'):
                path = prefix / 'bin' / name
                path.write_bytes(b'\x7fELFpublic synthetic header only')
                path.chmod(0o755)
            with mock.patch.dict(os.environ, {'RUSTC_WRAPPER': '/not-inherited',
                                             'CARGO_REGISTRIES_CRATES_IO_TOKEN': 'not-inherited'}):
                env = M.environment(source, root)
            self.assertEqual(env['CARGO_HOME'], str(home))
            self.assertEqual(env['CARGO_TARGET_DIR'], str(root / 'silex-native-metadata-target'))
            self.assertEqual(env['RUSTC'], str(prefix / 'bin/rustc'))
            self.assertEqual(env['CARGO_NET_OFFLINE'], 'true')
            self.assertNotIn('RUSTC_WRAPPER', env)
            self.assertNotIn('CARGO_REGISTRIES_CRATES_IO_TOKEN', env)
            online = M.environment(source, root, fetch=True)
            self.assertEqual(online['CARGO_NET_OFFLINE'], 'false')
            self.assertEqual(online['CARGO_REGISTRIES_CRATES_IO_INDEX'], 'sparse+https://index.crates.io/')
            (home / 'already-populated').write_bytes(b'public cache marker')
            with self.assertRaises(M.Rejected):
                M.environment(source, root, fetch=True)
            self.assertEqual(M.environment(source, root)['CARGO_NET_OFFLINE'], 'true')
            (home / 'already-populated').unlink()
            (home / 'config.toml').write_text('[source.bad]\n')
            with self.assertRaises(M.Rejected):
                M.environment(source, root)
            # Exercise the actual fetch-mode ordering: an ambient source override
            # must fail before a Cargo process or source snapshot is started.
            with mock.patch.dict(os.environ, {'RUNNER_TEMP': str(root)}), \
                    mock.patch.object(M, 'verify_source'), mock.patch.object(M, 'read', return_value=b'old lock'), \
                    mock.patch.object(M, 'digest', return_value=M.BASE_LOCK), \
                    mock.patch.object(M, 'ledger', return_value=(4, dict.fromkeys(range(607)))), \
                    mock.patch.object(M, 'snapshot') as snapshot, mock.patch.object(M, 'run') as run, \
                    mock.patch('builtins.print'), self.assertRaises(M.Rejected):
                M.fetch_base(source)
            run.assert_not_called()
            snapshot.assert_not_called()
            receipt = json.loads((root / 'silex-native-base-fetch.json').read_bytes())
            self.assertEqual(receipt['stage'], 'environment')
            self.assertEqual(receipt['status'], 'failed')
            self.assertIs(receipt['fetched_locked'], False)
            self.assertEqual(receipt['owned_children_started'], 0)
            (home / 'config.toml').unlink()
            (prefix / 'bin/cargo').write_bytes(b'#!/bin/sh\nnot a compiler')
            with self.assertRaises(M.Rejected):
                M.environment(source, root)

    def test_retained_artifact_is_private_no_clobber_and_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'BEFORE.Cargo.lock'
            M.write_new(path, b'public lock snapshot')
            self.assertEqual(path.read_bytes(), b'public lock snapshot')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                M.write_new(path, b'overwritten')
            alias = root / 'RESULT.Cargo.lock'
            alias.symlink_to(path)
            with self.assertRaises(OSError):
                M.write_new(alias, b'overwritten')
            self.assertEqual(path.read_bytes(), b'public lock snapshot')

    def test_command_failure_retains_primary_and_counts_only_confirmed_owned_child_joins(self):
        for cleanup_fails in (False, True):
            primary = M.Rejected('cancelled')
            stdout, stderr = mock.Mock(), mock.Mock()
            stdout.fileno.return_value, stderr.fileno.return_value = 10, 11
            child = SimpleNamespace(pid=12345, stdout=stdout, stderr=stderr, returncode=None)

            def joined(timeout):
                self.assertEqual(timeout, 2)
                if cleanup_fails:
                    raise M.subprocess.TimeoutExpired('fixed metadata', timeout)
                child.returncode = -9

            child.wait = mock.Mock(side_effect=joined)
            selector = mock.MagicMock()
            selector.__enter__.return_value = selector
            selector.get_map.return_value = {10: True}
            selector.select.return_value = [(SimpleNamespace(fileobj=stdout), None)]
            counts = {'started': 0, 'joined': 0}
            with mock.patch.object(M.subprocess, 'Popen', return_value=child), \
                    mock.patch.object(M.selectors, 'DefaultSelector', return_value=selector), \
                    mock.patch.object(M.os, 'set_blocking'), mock.patch.object(M.os, 'read', side_effect=primary), \
                    mock.patch.object(M.os, 'killpg') as kill:
                with self.assertRaises(M.Rejected) as caught:
                    M.run(['/fixed/cargo', 'metadata'], {}, Path('/public-source'), M.time.monotonic() + 30, counts)
            self.assertIs(caught.exception, primary)
            self.assertEqual(counts, {'started': 1, 'joined': 0 if cleanup_fails else 1})
            kill.assert_called_once_with(child.pid, M.signal.SIGKILL)
            stdout.close.assert_called_once()
            stderr.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
