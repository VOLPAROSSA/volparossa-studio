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

from viewer_receipt import (validate_viewer_proof, read_viewer_cleanup, read_viewer_diagnostic,
    CORE_STAGES, BROWSER_STAGES, DIAGNOSTIC_LOG_LIMIT, DIAGNOSTIC_PREFIX,
    UNIT_CASES, UNIT_LOG_LIMIT, read_viewer_unit_diagnostic)
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
                    diagnostic = dict(schema=1, core_stage='browser_observation', browser_stage='style')
                    (temporary / 'viewer-core.log').write_bytes(
                        DIAGNOSTIC_PREFIX + json.dumps(diagnostic).encode() + b'\nPRIVATE_SENTINEL')
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
                self.assertEqual(value['viewer_diagnostic']['browser_stage'], 'style')
                self.assertEqual(value['viewer_diagnostic']['status'], 'observed')
                self.assertFalse(value['network_published'])
                self.assertNotIn('PRIVATE_SENTINEL', receipt.read_text())

    def test_closed_diagnostic_writer_to_reader_and_failure_projection(self):
        # The Rust enum mapping is the real writer's vocabulary. No Rust, Node,
        # browser or network runtime is executed by this source contract check.
        if 'STUDIO_DIAGNOSTIC_CORE_SOURCE' not in os.environ:
            self.skipTest('explicit inert Core source path required for writer contract')
        core_root = Path(os.environ['STUDIO_DIAGNOSTIC_CORE_SOURCE'])
        source = (core_root / 'crates/volparossa/tests/studio_site_pack/viewer.rs').read_text()
        names = __import__('re').findall(r'Self::[A-Za-z]+ => "([a-z_]+)"', source)
        self.assertEqual(tuple(names), CORE_STAGES)
        self.assertIn('"schema": 1, "core_stage": stage.name(), "browser_stage": browser_stage', source)
        for stage in BROWSER_STAGES[1:]:
            self.assertIn('"' + stage + '"', source)
        browser = (ROOT / 'browser-viewer.mjs').read_text()
        self.assertIn("schema: 1, status: 'failed', stage,", browser)
        self.assertIn('rendered_http_requests: Math.min(requests, 1024)', browser)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'viewer-core.log'
            for browser_stage in BROWSER_STAGES:
                records = [dict(schema=1, core_stage=stage, browser_stage='not_observed')
                           for stage in names[:7]]
                records.append(dict(schema=1, core_stage='browser_observation', browser_stage=browser_stage))
                path.write_bytes(b'PRIVATE_SENTINEL panic hook\n' + b''.join(
                    DIAGNOSTIC_PREFIX + json.dumps(record).encode() + b'\n' for record in records))
                value = read_viewer_diagnostic(path)
                self.assertEqual(value, dict(schema=1, status='observed', core_stage='browser_observation',
                    browser_stage=browser_stage, record_count=8))
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(value))

    def test_marker_refinements_are_closed_browser_phase_only_and_never_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'viewer-core.log'
            for marker in ('marker_absent', 'marker_hidden', 'marker_ambiguous'):
                self.assertIn(marker, BROWSER_STAGES)
                for core_stage in CORE_STAGES:
                    record = dict(schema=1, core_stage=core_stage, browser_stage=marker)
                    path.write_bytes(DIAGNOSTIC_PREFIX + json.dumps(record).encode() + b'\n')
                    result = read_viewer_diagnostic(path)
                    expected = 'observed' if core_stage == 'browser_observation' else 'invalid'
                    self.assertEqual(result['status'], expected)
                    self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
                # A failed marker label cannot supply a successful viewer/browser proof.
                value = proof()
                value['local_viewer']['browser'].update(status='failed', stage=marker)
                with self.assertRaises(ValueError):
                    validate_viewer_proof(value)
            for marker in ('marker_unavailable', 'marker_hidden PRIVATE_SENTINEL', True, 1, None):
                record = dict(schema=1, core_stage='browser_observation', browser_stage=marker)
                path.write_bytes(DIAGNOSTIC_PREFIX + json.dumps(record).encode() + b'\n')
                result = read_viewer_diagnostic(path)
                self.assertEqual(result['status'], 'invalid')
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))

    def test_marker_observer_keeps_primary_checks_and_uses_authenticated_node_preflight(self):
        browser = (ROOT / 'browser-viewer.mjs').read_text()
        self.assertIn("getByText('VOLPAROSSA Studio manual export 20261022', { exact: true })", browser)
        self.assertIn("await marker.waitFor({ state: 'visible', timeout: 5000 });", browser)
        self.assertIn('assert.equal(await marker.count(), 1);', browser)
        self.assertIn("getComputedStyle(element).fontSize), '37px'", browser)
        self.assertIn("content-security-policy", browser)
        tree = ast.parse((ROOT / 'run.py').read_text())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        runner = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run_viewer_units')
        calls = [node for node in ast.walk(runner) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'run'
                 and len(node.args) >= 4 and isinstance(node.args[3], ast.Constant)
                 and node.args[3].value == 'marker-unit']
        self.assertEqual(len(calls), 1)
        call = calls[0]
        argv = call.args[0].elts
        self.assertEqual(len(argv), 5)
        self.assertEqual(argv[0].id, 'node')
        self.assertEqual(ast.literal_eval(argv[1]), '--test')
        self.assertEqual(ast.literal_eval(argv[2]), '--test-reporter=tap')
        for argument, name in zip(argv[3:], ('test_marker_failure.mjs', 'test_viewer_handoff.mjs')):
            self.assertIsInstance(argument.op, ast.Div)
            self.assertEqual(argument.left.id, 'runtime_fixture')
            self.assertEqual(ast.literal_eval(argument.right), name)
        self.assertEqual(call.args[2].id, 'env')
        self.assertEqual({entry.arg: ast.literal_eval(entry.value) for entry in call.keywords}, {'timeout': 10})
        prepare = next(node for node in ast.walk(main) if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Name) and node.func.id == 'prepare')
        invocation = next(node for node in ast.walk(main) if isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Name) and node.func.id == 'run_viewer_units')
        installs = [node for node in ast.walk(main) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == 'run'
                    and len(node.args) >= 4 and isinstance(node.args[3], ast.Constant)
                    and node.args[3].value in ('install-silex', 'install-driver')]
        self.assertLess(prepare.lineno, invocation.lineno)
        self.assertTrue(installs)
        self.assertTrue(all(invocation.lineno < install.lineno for install in installs))
        self.assertIn('marker-unit', fixture_run.OPERATIONS)

    def test_unit_vocabulary_matches_both_static_node_sources(self):
        names = []
        for name in ('test_marker_failure.mjs', 'test_viewer_handoff.mjs'):
            names.extend(__import__('re').findall(r"test\('([^']+)'", (ROOT / name).read_text()))
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(UNIT_CASES))
        self.assertEqual(len(set(UNIT_CASES.values())), len(UNIT_CASES))

    def test_unit_failure_projection_is_closed_and_cannot_claim_success(self):
        name = next(name for name, case in UNIT_CASES.items() if case == 'marker_budget')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'units.log'
            path.write_text('TAP version 13\nnot ok 1 - ' + name + '\n  error: PRIVATE_SENTINEL\n')
            result = read_viewer_unit_diagnostic(path)
            self.assertEqual(result, dict(schema=1, status='observed', failed_case_ids=['marker_budget'], case_count=1))
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
            for text in ('TAP version 13\nnot ok 1 - PRIVATE_SENTINEL\n',
                         'TAP version 13\nok 1 - ' + name + '\n',
                         'TAP version 13\nnot ok 99 - ' + name + '\n',
                         'TAP version 13\n' + ('not ok 1 - ' + name + '\n') * 2,
                         'PRIVATE_SENTINEL'):
                path.write_text(text)
                result = read_viewer_unit_diagnostic(path)
                self.assertEqual(result['status'], 'invalid')
                self.assertEqual(result['failed_case_ids'], [])

    def test_unit_reader_refuses_links_and_bounds_growth_after_fstat(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'units.log'
            self.assertEqual(read_viewer_unit_diagnostic(path)['status'], 'unavailable')
            path.write_bytes(b' ' * (UNIT_LOG_LIMIT + 1))
            self.assertEqual(read_viewer_unit_diagnostic(path)['status'], 'invalid')
            link = Path(directory) / 'link'
            link.symlink_to(path)
            self.assertEqual(read_viewer_unit_diagnostic(link)['status'], 'invalid')
        data = io.BytesIO(b' ' * (UNIT_LOG_LIMIT + 1))
        data.fileno = lambda: 91
        read = Mock(wraps=data.read)
        data.read = read
        metadata = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_size=2,
                                   st_uid=os.getuid(), st_nlink=1)
        with patch('viewer_receipt.os.open', return_value=91), \
                patch('viewer_receipt.os.fdopen', return_value=data), \
                patch('viewer_receipt.os.fstat', return_value=metadata):
            self.assertEqual(read_viewer_unit_diagnostic(Path('/inert'))['status'], 'invalid')
            read.assert_called_once_with(UNIT_LOG_LIMIT + 1)

    def test_unit_failure_preserves_primary_and_never_prints_success(self):
        primary = fixture_run.OperationFailure('marker-unit', 1, 'exit_nonzero')
        projected = dict(schema=1, status='invalid', failed_case_ids=[], case_count=0)
        receipt = {}
        with patch.object(fixture_run, 'run', side_effect=primary), \
                patch.object(fixture_run, 'read_viewer_unit_diagnostic', return_value=projected), \
                patch('builtins.print') as output:
            with self.assertRaises(fixture_run.OperationFailure) as raised:
                fixture_run.run_viewer_units(Path('/node'), Path('/fixture'), Path('/temporary'), {}, receipt)
            self.assertIs(raised.exception, primary)
            self.assertEqual(receipt['viewer_unit_diagnostic'], projected)
            output.assert_called_once()
            self.assertTrue(output.call_args.args[0].startswith('STUDIO_VIEWER_UNIT_FAILURE '))

    def test_unit_observer_or_logger_error_preserves_primary(self):
        for failure in ('observer', 'logger'):
            primary = fixture_run.OperationFailure('marker-unit', 1, 'exit_nonzero')
            projected = dict(schema=1, status='invalid', failed_case_ids=[], case_count=0)
            options = {'side_effect': RuntimeError('PRIVATE_SENTINEL')} if failure == 'observer' else {'return_value': projected}
            receipt = {}
            with self.subTest(failure=failure), \
                    patch.object(fixture_run, 'run', side_effect=primary), \
                    patch.object(fixture_run, 'read_viewer_unit_diagnostic', **options), \
                    patch('builtins.print', side_effect=BrokenPipeError('PRIVATE_SENTINEL')):
                with self.assertRaises(fixture_run.OperationFailure) as raised:
                    fixture_run.run_viewer_units(Path('/node'), Path('/fixture'), Path('/temporary'), {}, receipt)
                self.assertIs(raised.exception, primary)
                self.assertEqual(receipt['viewer_unit_diagnostic'], projected)
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(receipt))

    def test_diagnostic_malformed_oversized_symlink_and_private_text_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'log'
            self.assertEqual(read_viewer_diagnostic(path)['status'], 'unavailable')
            record = dict(schema=1, core_stage='pack', browser_stage='not_observed')
            values = ['{', dict(record, schema=True), dict(record, raw='PRIVATE_SENTINEL'),
                      dict(record, core_stage='PRIVATE_SENTINEL'), dict(record, browser_stage='http')]
            for value in values:
                path.write_bytes(DIAGNOSTIC_PREFIX + (value if type(value) is str else json.dumps(value)).encode())
                result = read_viewer_diagnostic(path)
                self.assertEqual(result['status'], 'invalid')
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
            line = DIAGNOSTIC_PREFIX + json.dumps(record).encode() + b'\n'
            path.write_bytes(line * 17)
            self.assertEqual(read_viewer_diagnostic(path)['status'], 'invalid')
            path.write_bytes(b' ' * (DIAGNOSTIC_LOG_LIMIT + 1))
            self.assertEqual(read_viewer_diagnostic(path)['status'], 'invalid')
            link = Path(directory) / 'link'
            link.symlink_to(path)
            self.assertEqual(read_viewer_diagnostic(link)['status'], 'invalid')
            with patch('viewer_receipt.os.open', side_effect=InterruptedError('cancel')):
                with self.assertRaises(InterruptedError):
                    read_viewer_diagnostic(path)

    def test_diagnostic_read_is_bounded_after_fstat(self):
        data = io.BytesIO(b' ' * (DIAGNOSTIC_LOG_LIMIT + 1))
        data.fileno = lambda: 91
        read = Mock(wraps=data.read)
        data.read = read
        metadata = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_size=2)
        with patch('viewer_receipt.os.open', return_value=91), \
                patch('viewer_receipt.os.fdopen', return_value=data), \
                patch('viewer_receipt.os.fstat', return_value=metadata):
            self.assertEqual(read_viewer_diagnostic(Path('/inert'))['status'], 'invalid')
            read.assert_called_once_with(DIAGNOSTIC_LOG_LIMIT + 1)

    def test_python_syntax_without_runtime(self):
        for name in ('run.py', 'viewer_runtime.py', 'viewer_receipt.py'):
            ast.parse((ROOT / name).read_text())


if __name__ == '__main__':
    unittest.main()
