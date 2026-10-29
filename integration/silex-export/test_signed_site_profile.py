# SPDX-License-Identifier: GPL-3.0-only
"""Hosted inert Python contracts. Inert fixture bytes are never executable proof."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import signed_site_controller as controller
import signed_site_profile as profile
import viewer_runtime


def private(path, data):
    path.write_bytes(data)
    path.chmod(0o600)


def core_files(root):
    core = root / 'core'
    (core / 'target/debug/deps').mkdir(parents=True)
    for name in ('volparossa', 'volparossa-agent', 'deps/' + profile.TARGET + '-abcd'):
        path = core / 'target/debug' / name
        path.write_bytes(b'inert public fixture, not executed')
        path.chmod(0o700)
    return core, core / 'target/debug/deps' / (profile.TARGET + '-abcd')


class SignedProfileTests(unittest.TestCase):
    def test_explicit_mode_preserves_old_three_paths_and_refuses_ambiguous_options(self):
        paths = ['/core', '/silex', '/receipt']
        self.assertEqual(profile.arguments(paths), ((Path('/core'), Path('/silex'), Path('/receipt')), 'viewer'))
        self.assertEqual(profile.arguments(paths + ['--proof-mode', profile.MODE])[1], profile.MODE)
        for invalid in (paths[:2], paths + [profile.MODE], paths + ['--proof-mode', 'viewer'],
                        paths + ['--proof-mode', 'other'], ['--proof-mode', profile.MODE] + paths,
                        paths + ['--proof-mode', profile.MODE, '--retry']):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                profile.arguments(invalid)

    def test_schema_two_roundtrip_binds_fixed_core_and_requires_both_real_binary_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core, binary = core_files(root)
            context = root / 'viewer-context.json'
            profile.write_signed_context(context, core, binary)
            actual = profile.read_core_context(context)
            self.assertEqual(actual, profile.CoreContext(profile.MODE, binary, core))
            self.assertEqual(context.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                profile.write_signed_context(context, core, binary)
            (core / 'target/debug/volparossa').unlink()
            with self.assertRaises(OSError):
                profile.read_core_context(context)

    def test_schema_one_keeps_legacy_target_but_never_accepts_new_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core, binary = core_files(root)
            legacy = binary.with_name('studio_site_pack-abcd')
            legacy.touch()
            context = root / 'viewer-context.json'
            private(context, json.dumps(dict(schema=1, executable=str(legacy))).encode())
            self.assertEqual(profile.read_core_context(context), profile.CoreContext('viewer', legacy))
            private(context, json.dumps(dict(schema=1, executable=str(binary))).encode())
            with self.assertRaises(ValueError):
                profile.read_core_context(context)

    def test_invalid_schema_two_mode_keys_or_artifact_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core, binary = core_files(root)
            value = dict(schema=2, proof_mode=profile.MODE, core_root=str(core), executable=str(binary))
            for changes in ({'schema': True}, {'schema': 3}, {'proof_mode': 'viewer'},
                            {'executable': str(binary.with_name('studio_site_pack-abcd'))},
                            {'executable': str(core / 'target/debug' / binary.name)},
                            {'core_root': str(root)}, {'executable': False}, {'raw_url': 'PRIVATE_SENTINEL'}):
                bad = dict(value, **changes)
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    profile.checked_signed_context(bad)
            for key in value:
                bad = copy.deepcopy(value)
                del bad[key]
                with self.subTest(missing=key), self.assertRaises(ValueError):
                    profile.checked_signed_context(bad)

    def test_context_refuses_aliases_wide_permissions_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core, binary = core_files(root)
            context = root / 'viewer-context.json'
            profile.write_signed_context(context, core, binary)
            link = root / 'alias'
            link.symlink_to(context)
            with self.assertRaises(OSError):
                profile.read_core_context(link)
            context.chmod(0o644)
            with self.assertRaises(ValueError):
                profile.read_core_context(context)
            context.chmod(0o600)
            os.link(context, root / 'hardlink')
            with self.assertRaises(ValueError):
                profile.read_core_context(context)
            (root / 'hardlink').unlink()
            private(context, b' ' * (profile.MAX_CONTEXT + 1))
            with self.assertRaises(ValueError):
                profile.read_core_context(context)
            binary.unlink()
            binary.symlink_to(core / 'target/debug/volparossa')
            with self.assertRaises(ValueError):
                profile.checked_signed_context(dict(schema=2, proof_mode=profile.MODE,
                    core_root=str(core), executable=str(binary)))

    def test_one_descriptor_checks_mutation_before_decoding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private'
            private(path, b'{}')
            before = path.stat()
            after = Mock(wraps=before)
            for field in ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_nlink',
                          'st_size', 'st_mtime_ns', 'st_ctime_ns'):
                setattr(after, field, getattr(before, field))
            after.st_ctime_ns += 1
            with patch.object(profile.os, 'fstat', side_effect=[before, after]), self.assertRaises(ValueError):
                profile.read_private(path, 1024)
            with patch.object(profile.os, 'fstat', return_value=before), \
                    patch.object(profile.os, 'open', return_value=99), \
                    patch.object(profile.os, 'fdopen') as opened:
                data = io.BytesIO(b'grown')
                data.fileno = lambda: 99
                opened.return_value = data
                with self.assertRaises(ValueError):
                    profile.read_private(path, 2)

    def test_duplicate_fields_and_nonfinite_json_are_rejected(self):
        for bad in ('{"schema":1,"schema":2}', '{"nested":{"a":1,"a":2}}',
                    '{"n":NaN}', '{"n":Infinity}', '{"n":-Infinity}', '\ufeff{}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                profile.strict_json(bad)

    def test_compiler_artifact_requires_one_matching_target_and_exact_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core, binary = core_files(root)
            value = dict(reason='compiler-artifact', target=dict(name=profile.TARGET, kind=['test']), executable=str(binary))
            log = root / 'compiler.log'
            log.write_text(json.dumps(value) + '\n')
            self.assertEqual(controller.compiler_artifact(log, core), binary)
            for bad in (dict(value, executable='/elsewhere/' + binary.name),
                        dict(value, target=dict(name='studio_site_pack', kind=['test'])),
                        dict(value, target=dict(name=profile.TARGET, kind=['bin'])),
                        dict(value, executable=True)):
                log.write_text(json.dumps(bad) + '\n')
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    controller.compiler_artifact(log, core)
            log.write_text((json.dumps(value) + '\n') * 2)
            with self.assertRaises(ValueError):
                controller.compiler_artifact(log, core)

    def test_signed_runtime_uses_only_exact_test_and_always_drains_owned_group(self):
        for outcome in (0, 7, subprocess.TimeoutExpired('inert', 80), InterruptedError('inert')):
            with self.subTest(outcome=type(outcome).__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                process = Mock()
                if type(outcome) is int:
                    process.wait.return_value = outcome
                else:
                    process.wait.side_effect = outcome
                identity = object()
                with patch.object(viewer_runtime, 'start_group', return_value=(process, identity)) as start, \
                        patch.object(viewer_runtime, 'drain_group', return_value=dict(live_group_drained=True, leader_joined=True)) as drain:
                    if outcome == 0:
                        viewer_runtime.run_core_fixture(Path('/inert-core-test'), root, {}, signed=True)
                    else:
                        with self.assertRaises((RuntimeError, subprocess.TimeoutExpired, InterruptedError)):
                            viewer_runtime.run_core_fixture(Path('/inert-core-test'), root, {}, signed=True)
                    self.assertEqual(start.call_args.args[0], ['/inert-core-test', profile.TEST,
                        '--ignored', '--exact', '--nocapture', '--test-threads=1'])
                    process.wait.assert_called_once_with(timeout=80)
                    drain.assert_called_once_with(process, identity)
                self.assertEqual((root / 'signed-site-core.log').stat().st_mode & 0o777, 0o600)
                self.assertFalse((root / 'viewer-core.log').exists())

    def test_controller_builds_cli_and_new_agent_target_then_uses_unchanged_wrapper(self):
        from test_signed_site_receipt import proof, log_text
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core, binary = core_files(root)
            temporary = root / 'studio-export-inert'
            temporary.mkdir(mode=0o700)
            fixture = temporary / 'fixture'
            fixture.mkdir()
            (temporary / 'inventory.json').write_text(json.dumps(dict(schema=1, assets=[{}] * 4)))
            compiler = temporary / 'core-build.log'
            compiler.write_text(json.dumps(dict(reason='compiler-artifact',
                target=dict(name=profile.TARGET, kind=['test']), executable=str(binary))) + '\n')
            private(temporary / 'signed-site-core.log', log_text(proof()).encode())
            (temporary / 'viewer-cleanup.json').write_text(json.dumps(dict(core_group_drained=True,
                core_joined=True, isolated_network_namespace=True, capabilities_dropped=True,
                nonroot_runner_uid=True, cleanup_failed=False)))
            run = Mock(return_value=compiler)
            actual = {}
            controller.execute(core, temporary, fixture, {}, actual, run)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0], ['cargo', 'build', '--locked', '--offline',
                                          '-p', 'volparossa', '--bin', 'volparossa'])
            self.assertEqual(commands[1], ['cargo', 'test', '--locked', '--offline', '-p',
                'volparossa-agent', '--test', profile.TARGET, '--no-run', '--message-format=json'])
            self.assertEqual(commands[2], [core / 'scripts/run-isolated-test.sh',
                '--studio-nonroot-command', '/usr/bin/python3', 'studio_export',
                'VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS', 'loopback', '-B', fixture / 'viewer_runtime.py'])
            self.assertEqual(run.call_args_list[-1].kwargs, {'timeout': 100})
            self.assertEqual(actual['signed_site_recovery'], proof())
            self.assertNotIn('core_pack', actual)
            self.assertEqual(profile.read_core_context(temporary / 'viewer-context.json').mode, profile.MODE)

    def test_controller_failed_child_cannot_accept_a_leftover_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core, binary = core_files(root)
            temporary = root / 'studio-export-inert'
            temporary.mkdir(mode=0o700)
            compiler = temporary / 'core-build.log'
            compiler.write_text(json.dumps(dict(reason='compiler-artifact',
                target=dict(name=profile.TARGET, kind=['test']), executable=str(binary))) + '\n')
            run = Mock(side_effect=[compiler, compiler, RuntimeError('private child failed')])
            actual = {}
            with patch.object(controller, 'read_signed_proof') as read, self.assertRaises(RuntimeError):
                controller.execute(core, temporary, temporary / 'fixture', {}, actual, run)
            read.assert_not_called()
            self.assertNotIn('signed_site_recovery', actual)

    def test_signed_runtime_failed_drain_or_spawn_never_claims_cleanup(self):
        for spawned in (False, True):
            with self.subTest(spawned=spawned), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                process = Mock()
                process.wait.return_value = 0
                spawn = dict(return_value=(process, object())) if spawned else dict(side_effect=OSError('inert spawn'))
                with patch.object(viewer_runtime, 'start_group', **spawn), \
                        patch.object(viewer_runtime, 'drain_group', return_value=dict(live_group_drained=False, leader_joined=True)) as drain:
                    with self.assertRaises((RuntimeError, OSError)):
                        viewer_runtime.run_core_fixture(Path('/inert-core-test'), root, {}, signed=True)
                value = json.loads((root / 'viewer-cleanup.json').read_text())
                self.assertTrue(value['cleanup_failed'])
                self.assertFalse(value['core_group_drained'])
                self.assertEqual(drain.call_count, int(spawned))


if __name__ == '__main__':
    unittest.main()
