# SPDX-License-Identifier: GPL-3.0-only
"""Inert closed receipt/context rejection; synthetic values are not acceptance."""
import ast
import copy
import json
import io
import hashlib
import os
import stat
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
import unittest

import run as fixture_run

from viewer_receipt import validate_viewer_proof, read_viewer_cleanup
from viewer_runtime import read_viewer_context, run_core_fixture

ROOT = Path(__file__).resolve().parent


def proof():
    browser = dict(schema=1, status='passed', bundle_sha256='a' * 64, bundle_bytes=1024,
        asset_count=4, visible_marker=True, computed_37px=True, all_assets_verified=True,
        security_headers_preserved=True, independent_browser=True, browser_closed=True,
        rendered_http_requests=2)
    viewer = dict(schema=1, status='passed', bundle_sha256='a' * 64, bundle_bytes=1024,
        asset_count=4, ephemeral_test_publisher=True, mock_local_control_peer=True,
        production_signed_verification=True, direct_child_adversarial_cleanup=True, actual_site_open_cli=True, browser=browser,
        private_spool_removed=True, listener_closed=True, network_published=False,
        independent_peer_retrieval=False)
    return dict(schema=2, status='passed', actual_cli_pack=True, production_site_bundle_decoded=True,
        all_zip_assets_verified=True, edited_html_verified=True, edited_css_verified=True,
        no_clobber_verified=True, content_type='application/vnd.volparossa.site.v1', asset_count=4,
        network_published=False, signing_authority_exercised=False,
        ephemeral_fixture_signing=True, local_viewer=viewer)


class ViewerReceiptTests(unittest.TestCase):
    def test_closed_binding_and_flags(self):
        original = proof()
        validate_viewer_proof(original)
        for level in ((), ('local_viewer',), ('local_viewer', 'browser')):
            for field, bad in [('raw_url', 'private'), ('bundle_bytes', True),
                               ('schema', True), ('status', 'failed')]:
                value = copy.deepcopy(original)
                target = value
                for key in level:
                    target = target[key]
                target[field] = bad
                with self.subTest(level=level, field=field), self.assertRaises(ValueError):
                    validate_viewer_proof(value)
        for field, bad in [('bundle_sha256', 'b' * 64), ('bundle_bytes', 1025), ('asset_count', 3),
                           ('visible_marker', False), ('computed_37px', False), ('browser_closed', False),
                           ('rendered_http_requests', True), ('rendered_http_requests', 1025)]:
            value = copy.deepcopy(original)
            value['local_viewer']['browser'][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_viewer_proof(value)

    def test_cleanup_failure_cannot_pass_and_no_raw_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cleanup.json'
            value = dict(core_group_drained=True, core_joined=True, isolated_network_namespace=True,
                         capabilities_dropped=True, nonroot_runner_uid=True, cleanup_failed=False)
            path.write_text(json.dumps(value))
            read_viewer_cleanup(path)
            value['cleanup_failed'] = True
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                read_viewer_cleanup(path)
            read_viewer_cleanup(path, require_success=False)
            value['url'] = 'private'
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                read_viewer_cleanup(path, require_success=False)

    def test_private_context_metadata_and_fixed_artifact_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / 'core/target/debug/deps/studio_site_pack-abcd'
            executable.parent.mkdir(parents=True)
            executable.touch()
            context = root / 'viewer-context.json'
            context.write_text(json.dumps({'schema': 1, 'executable': str(executable)}))
            context.chmod(0o600)
            self.assertEqual(read_viewer_context(context), executable)
            context.chmod(0o644)
            with self.assertRaises(ValueError):
                read_viewer_context(context)
            context.chmod(0o600)
            executable.unlink()
            executable.symlink_to('/bin/true')
            with self.assertRaises(ValueError):
                read_viewer_context(context)

    def test_bounded_read_rejects_post_fstat_growth(self):
        data = io.BytesIO(b' ' * 16385)
        data.fileno = lambda: 91
        read = Mock(wraps=data.read)
        data.read = read
        metadata = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=os.getuid(), st_nlink=1, st_size=2)
        with patch('viewer_runtime.os.open', return_value=91), \
                patch('viewer_runtime.os.fdopen', return_value=data), \
                patch('viewer_runtime.os.fstat', return_value=metadata), \
                patch('viewer_runtime.json.loads') as decode:
            with self.assertRaisesRegex(ValueError, 'size bound'):
                read_viewer_context(Path('/inert-context'))
            read.assert_called_once_with(16385)
            decode.assert_not_called()

    def test_context_rejects_malformed_bool_owner_mode_size_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            context = Path(directory) / 'viewer-context.json'
            context.touch(mode=0o600)
            for value in ('{', '[]', '{"schema":true,"executable":"/inert"}',
                          '{"schema":1,"executable":true}', '{"schema":1}', ' ' * 16385):
                context.write_text(value)
                with self.subTest(value=value[:32]), self.assertRaises(ValueError):
                    read_viewer_context(context)
            context.write_text('{}')
            real = context.stat()
            for changes in ({'st_uid': os.getuid() + 1}, {'st_mode': stat.S_IFREG | 0o644},
                            {'st_mode': stat.S_IFDIR | 0o600}, {'st_size': 16385}, {'st_nlink': 2}):
                values = {name: getattr(real, name) for name in ('st_mode', 'st_uid', 'st_size', 'st_nlink')}
                values.update(changes)
                with self.subTest(changes=changes), patch('viewer_runtime.os.fstat', return_value=SimpleNamespace(**values)):
                    with self.assertRaisesRegex(ValueError, 'private viewer context'):
                        read_viewer_context(context)
            link = context.parent / 'link.json'
            link.symlink_to(context)
            with self.assertRaises(OSError):
                read_viewer_context(link)

    def test_mocked_runtime_early_exit_timeout_cancel_and_success_always_drain(self):
        for outcome in (0, 7, subprocess.TimeoutExpired('inert', 80), InterruptedError('inert cancel')):
            with self.subTest(outcome=type(outcome).__name__), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                process = Mock()
                if type(outcome) is int:
                    process.wait.return_value = outcome
                else:
                    process.wait.side_effect = outcome
                identity = object()
                with patch('viewer_runtime.start_group', return_value=(process, identity)) as start, \
                        patch('viewer_runtime.drain_group', return_value={'live_group_drained': True, 'leader_joined': True}) as drain:
                    if outcome == 0:
                        run_core_fixture(Path('/inert-test'), temporary, {})
                    else:
                        with self.assertRaises((RuntimeError, subprocess.TimeoutExpired, InterruptedError)):
                            run_core_fixture(Path('/inert-test'), temporary, {})
                    process.wait.assert_called_once_with(timeout=80)
                    drain.assert_called_once_with(process, identity)
                    self.assertEqual(start.call_args.args[0][0], '/inert-test')
                    cleanup = read_viewer_cleanup(temporary / 'viewer-cleanup.json')
                    self.assertFalse(cleanup['cleanup_failed'])
                    self.assertTrue((temporary / 'viewer-core.log').exists())

    def test_mocked_runtime_cleanup_failure_is_never_success(self):
        for observed in (TimeoutError('inert drain'), {'live_group_drained': False, 'leader_joined': True},
                         {'live_group_drained': True, 'leader_joined': False}):
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                process = Mock()
                process.wait.return_value = 0
                options = {'side_effect': observed} if isinstance(observed, Exception) else {'return_value': observed}
                with patch('viewer_runtime.start_group', return_value=(process, object())), \
                        patch('viewer_runtime.drain_group', **options):
                    with self.assertRaises((TimeoutError, RuntimeError)):
                        run_core_fixture(Path('/inert-test'), temporary, {})
                value = read_viewer_cleanup(temporary / 'viewer-cleanup.json', require_success=False)
                self.assertTrue(value['cleanup_failed'])
                with self.assertRaises(ValueError):
                    read_viewer_cleanup(temporary / 'viewer-cleanup.json')

    def test_mocked_runtime_spawn_failure_cannot_claim_join(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            with patch('viewer_runtime.start_group', side_effect=OSError('inert spawn')), \
                    patch('viewer_runtime.drain_group') as drain:
                with self.assertRaises(OSError):
                    run_core_fixture(Path('/inert-test'), temporary, {})
                drain.assert_not_called()
            value = read_viewer_cleanup(temporary / 'viewer-cleanup.json', require_success=False)
            self.assertTrue(value['cleanup_failed'])
            self.assertFalse(value['core_group_drained'])
            self.assertFalse(value['core_joined'])

    def test_mocked_outer_failure_removes_private_outputs_even_with_bad_cleanup_receipt(self):
        for malformed in (False, True):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                core, source, receipt = root / 'core', root / 'silex', root / 'receipt.json'
                source.mkdir()
                (source / 'pnpm-lock.yaml').write_bytes(b'inert lock')
                pins = copy.deepcopy(fixture_run.PINS)
                pins['silex']['lock_sha256'] = hashlib.sha256(b'inert lock').hexdigest()
                refs = {core: 'a' * 40, fixture_run.FIXTURE.parents[1]: 'b' * 40,
                        source: pins['silex']['commit']}
                created = []
                def fail_prepare(temporary):
                    created.append(temporary)
                    (temporary / 'private.log').write_text('PRIVATE_SENTINEL')
                    if malformed:
                        (temporary / 'viewer-cleanup.json').write_text('{invalid')
                    raise RuntimeError('PRIVATE_SENTINEL')
                env = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                    RUNNER_OS='Linux', RUNNER_ARCH='X64', RUNNER_TEMP=str(root),
                    STUDIO_CORE_REVISION='a' * 40, STUDIO_REVISION='b' * 40)
                with patch.dict(os.environ, env, clear=True), \
                        patch.object(fixture_run, 'PINS', pins), \
                        patch.object(fixture_run, 'revision', side_effect=lambda path: refs[path]), \
                        patch.object(fixture_run, 'check_font_source_contract'), \
                        patch.object(fixture_run, 'prepare', side_effect=fail_prepare), \
                        patch.object(fixture_run.signal, 'signal'), \
                        patch.object(fixture_run.sys, 'argv', ['inert-run', str(core), str(source), str(receipt)]):
                    with self.assertRaises((RuntimeError, ValueError)):
                        fixture_run.main()
                self.assertEqual(len(created), 1)
                self.assertFalse(created[0].exists())
                value = json.loads(receipt.read_text())
                self.assertEqual(value['status'], 'failed')
                self.assertTrue(value['temporary_outputs_removed'])
                self.assertFalse(value['network_published'])
                self.assertNotIn('PRIVATE_SENTINEL', receipt.read_text())

    def test_python_syntax_without_runtime(self):
        for name in ('run.py', 'viewer_runtime.py', 'viewer_receipt.py'):
            ast.parse((ROOT / name).read_text())


if __name__ == '__main__':
    unittest.main()
