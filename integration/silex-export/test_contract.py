# SPDX-License-Identifier: GPL-3.0-only
"""Inert safety checks. Synthetic ZIPs below are NOT Silex/runtime evidence."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import extract as extractor
from run import NATIVE_HANDLER_FLAGS, COMPONENT_COUNTS, DRAG_COUNTS, DRAG_FLAGS, validate_drag_diagnostics, DIAGNOSTIC_COUNTS, DIAGNOSTIC_FLAGS, DOM_FLAGS, INTERACTION_COUNTS, INTERACTION_FLAGS, read_browser_receipt, validate_startup_diagnostics

ROOT = Path(__file__).resolve().parent


class ExtractionTests(unittest.TestCase):
    def fixture(self, entries, callback):
        # Local synthetic parser input only. The hosted trial must use the real
        # browser DownloadConnector ZIP and never calls this fixture function.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'input.zip'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(archive, 'w') as bundle:
                    for name, content in entries:
                        bundle.writestr(name, content)
            callback(archive, root / 'export', root / 'inventory.json')

    def reject(self, entries):
        def check(*arguments):
            with self.assertRaises((ValueError, OSError)):
                extractor.extract(*arguments)
            self.assertFalse(arguments[2].exists(), 'failed extraction cannot claim complete inventory')
        self.fixture(entries, check)

    def test_exact_bytes_hashes_and_new_tree(self):
        html = b'<link rel="stylesheet" href="css/a.css">synthetic parser test'
        css = b'p {color: red;}'
        def check(archive, output, inventory):
            self.assertEqual(extractor.extract(archive, output, inventory), 2)
            actual = json.loads(inventory.read_text())
            self.assertEqual(actual['assets'], [
                {'path': '/css/a.css', 'bytes': len(css), 'sha256': hashlib.sha256(css).hexdigest()},
                {'path': '/index.html', 'bytes': len(html), 'sha256': hashlib.sha256(html).hexdigest()},
            ])
            self.assertEqual((output / 'css/a.css').read_bytes(), css)
            with self.assertRaises(FileExistsError):
                extractor.extract(archive, output, inventory)
        self.fixture([('index.html', html), ('css/a.css', css)], check)

    def test_reject_ambiguous_and_traversal_paths(self):
        for name in ('../escape', '/absolute', 'a/../escape', './index.html',
                     'a\\b', 'a//b', '.secret', 'a/.secret', 'C:/file', 'a/%2e%2e/file'):
            with self.subTest(name=name):
                self.reject([('index.html', b'parser test'), (name, b'unsafe')])

    def test_reject_duplicate_paths(self):
        self.reject([('index.html', b'one'), ('index.html', b'two')])

    def test_reject_symlink_and_device(self):
        for kind in (stat.S_IFLNK, stat.S_IFCHR, stat.S_IFIFO):
            entry = zipfile.ZipInfo('unsafe')
            entry.create_system = 3
            entry.external_attr = (kind | 0o600) << 16
            with self.subTest(kind=kind):
                self.reject([('index.html', b'parser test'), (entry, b'outside')])

    def test_reject_missing_portable_entry(self):
        self.reject([('other.html', b'parser test')])

    def test_reject_depth(self):
        self.reject([('index.html', b'parser test'), ('a/' * 17 + 'file', b'deep')])

    def test_reject_file_bound(self):
        with patch.object(extractor, 'MAX_FILES', 1):
            self.reject([('index.html', b'parser test'), ('a.css', b'css')])

    def test_reject_total_bound(self):
        with patch.object(extractor, 'MAX_TOTAL', 1):
            self.reject([('index.html', b'parser test')])

    def test_reject_zip_and_entry_bounds(self):
        with patch.object(extractor, 'MAX_ZIP', 1):
            self.reject([('index.html', b'parser test')])
        with patch.object(extractor, 'MAX_ENTRIES', 1):
            self.reject([('index.html', b'parser test'), ('a.css', b'css')])

    def test_reject_preexisting_symlink_tree(self):
        def check(archive, output, inventory):
            output.symlink_to(output.parent, target_is_directory=True)
            with self.assertRaises(FileExistsError):
                extractor.extract(archive, output, inventory)
        self.fixture([('index.html', b'parser test')], check)


class SourceChecks(unittest.TestCase):
    def test_python_sources_parse_without_executing_runtime(self):
        for path in ROOT.glob('*.py'):
            ast.parse(path.read_text(), filename=str(path))

    def test_manifest_lock_identity_and_evidence_boundary(self):
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        package = json.loads((ROOT / 'package.json').read_text())
        upstream = json.loads((ROOT.parents[1] / 'upstream.lock.json').read_text())
        self.assertEqual(upstream['commit'], manifest['silex']['commit'])
        self.assertEqual(package['dependencies'], {'playwright-core': manifest['browser_driver']['version']})
        self.assertIn(manifest['browser_driver']['integrity'], (ROOT / 'pnpm-lock.yaml').read_text())
        self.assertEqual(package['packageManager'], 'pnpm@' + manifest['pnpm']['version'])
        self.assertFalse(manifest['runtime_accepted'])
        self.assertFalse(manifest['network_published'])
        self.assertFalse(manifest['browser']['download_fallback'])
        edit = manifest['text_edit_source_evidence']
        self.assertEqual(edit['silex_commit'], manifest['silex']['commit'])
        grapes = manifest['render_source_evidence']['packages'][0]
        self.assertEqual(edit['grapesjs_version'], grapes['version'])
        self.assertEqual(edit['archive_sha256'], grapes['archive_sha256'])
        for path, short in (('dom_components/view/ComponentTextView.ts', 'ComponentTextView.ts'),
                            ('rich_text_editor/model/RichTextEditor.ts', 'RichTextEditor.ts')):
            self.assertEqual(edit['sources_content_sha256'][path], grapes['sources_content_sha256'][short])

    def test_drag_observer_cannot_modify_input_flow_or_read_payloads(self):
        driver = (ROOT / 'browser-export.mjs').read_text()
        observer = driver.split('dragObserver = await page.evaluateHandle', 1)[1].split("stage = 'manual_drop_idle';", 1)[0]
        self.assertIn('event.isTrusted', observer)
        self.assertIn('passive: true', observer)
        self.assertIn('Math.min(32,', observer)
        self.assertIn('removeEventListener', observer)
        for forbidden in ('preventDefault', 'stopPropagation', 'return false', 'dispatchEvent',
                          'dataTransfer', 'getData(', 'innerHTML', 'innerText', 'textContent',
                          'setAttribute', 'appendChild', 'window.silex'):
            self.assertNotIn(forbidden, observer)

    def test_drop_readiness_requires_unique_idle_and_ready_top_document_placer(self):
        driver = (ROOT / 'browser-export.mjs').read_text()
        readiness = driver.split("stage = 'manual_drop_idle';", 1)[1].split('// This phase is sampled', 1)[0]
        selector = '#gjs .gjs-cv-canvas > [data-tools] > .gjs-tools-gl > .gjs-placeholder'
        self.assertIn(f"const dropIndicator = page.locator('{selector}');", readiness)
        idle, after_down = readiness.split('await page.mouse.down();', 1)
        self.assertIn("await dropIndicator.waitFor({ state: 'attached' });", idle)
        self.assertIn("await dropIndicator.waitFor({ state: 'hidden' });", idle)
        self.assertEqual(idle.count('assert.equal(await dropIndicator.count(), 1);'), 2)
        self.assertEqual(driver.count('await page.mouse.up();'), 1)
        move, waiting = after_down.split("stage = 'manual_drop_ready';", 1)
        self.assertEqual(move.strip(), 'await page.mouse.move(targetPoint.x, targetPoint.y, { steps: 20 });')
        required = """try {
    // ComponentSorter reveals this placer only after accepting a drop target.
    // Use the existing default action timeout; no fixed delay or injected input.
    await dropIndicator.waitFor({ state: 'visible' });
    assert.equal(await dropIndicator.count(), 1);
  } catch (error) {
    // Escape cancels Playwright's native drag. Preserve the readiness failure
    // even if cancellation fails; never dispatch mouse-up on this path.
    try { await page.keyboard.press('Escape'); } catch { /* Browser teardown remains mandatory. */ }
    throw error;
  }
  await page.mouse.up();"""
        self.assertEqual(waiting.strip(), required)
        for forbidden in ('timeout:', 'setTimeout', 'waitForTimeout', 'dispatchEvent',
                          'window.silex', 'dataTransfer', '.first()', 'frame.locator', 'force:'):
            self.assertNotIn(forbidden, readiness)
        self.assertIn('page.setDefaultTimeout(12000);', driver)

    def test_readiness_provenance_is_bound_to_existing_locked_native_sources(self):
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        contract = manifest['native_drag_source_evidence']
        self.assertEqual(contract['silex_commit'], manifest['silex']['commit'])
        self.assertEqual(contract['grapesjs_version'], '0.23.2')
        self.assertEqual(contract['grapesjs_sources_content_sha256']['CanvasView.ts'],
            '306540ab7a9c3ac4f4e721f944af47d42bb2a659c55b0c2b12e3723f3d877427')
        self.assertEqual(contract['grapesjs_sources_content_sha256']['ComponentSorter.ts'],
            '149c41b3a4ec9a48f82cf316f4b3dbedefd23cc0a3a1818d9c9f07abf49a113e')
        self.assertEqual(contract['grapesjs_sources_content_sha256']['DropLocationDeterminer.ts'],
            '0b446a8620fd720e64e72f062209e0c948dda88ec1d45238c364cd317dbbbbfe')
        self.assertEqual(contract['grapesjs_sources_content_sha256']['PlaceholderClass.ts'],
            '81257e35c8fd7225ccc3aad0a1e461086c573e8951bd6046bfaf2d04c188a629')
        self.assertEqual(contract['grapesjs_archive_files_sha256'], {
            'package/dist/css/grapes.min.css': 'fb55e939b3349c280d68c0617dc87e56baa3eab55ea56a1855db9f5efcc7268d'})

    def test_native_handler_observation_is_passive_trusted_and_coordinate_only(self):
        driver = (ROOT / 'browser-export.mjs').read_text()
        observer = driver.split('const observeNativeHandler =', 1)[1].split('const stop =', 1)[0]
        self.assertIn('if (!event.isTrusted) return;', observer)
        self.assertIn('Math.min(32,', observer)
        self.assertIn('doc.elementFromPoint(event.clientX, event.clientY)', observer)
        self.assertIn('default_prevented: event.defaultPrevented', observer)
        self.assertIn('source_dragend_seen: state.events.source_dragend > 0', observer)
        self.assertIn('{ capture: false, passive: true }', observer)
        self.assertIn('listeners.push([wrapper, type, listener, false])', observer)
        self.assertIn('root.removeEventListener(type, listener, capture)', driver)
        self.assertIn("observeNativeHandler('dragover', false)", driver)
        self.assertIn("observeNativeHandler('drop', true)", driver)
        self.assertNotIn('setTimeout', observer)
        self.assertNotIn('await ', observer)

    def test_component_observation_uses_independent_fixed_dom_selectors(self):
        driver = (ROOT / 'browser-export.mjs').read_text()
        observer = driver.split('const components = () => ({', 1)[1].split('const probe =', 1)[0]
        late = driver.split('interaction: { blocks: count(document', 1)[1].split('} };', 1)[0]
        selectors = {
            'wrapper_descendants': ('wrapper', '[data-gjs-type]'),
            'bare_texts': ('doc', '[data-gjs-type="text"]'),
            'default_texts': ('doc', '.silex-default-text'),
            'texts': ('doc', '[data-gjs-type="text"].silex-default-text'),
            'editable_texts': ('doc', '[data-gjs-type="text"].silex-default-text[contenteditable="true"]'),
        }
        self.assertEqual(set(selectors), COMPONENT_COUNTS)
        for key, (base, selector) in selectors.items():
            expression = f"{key}: count({base}, '{selector}')"
            self.assertIn(expression, observer)
            self.assertIn(expression, late)
        for forbidden in ('.gjs-selected', 'MutationObserver', 'getData('):
            self.assertNotIn(forbidden, driver)

    def test_synthetic_font_contract_remains_pinned_and_loopback_only(self):
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        contract = manifest['font_plugin_contract']
        self.assertEqual(contract['silex_commit'], manifest['silex']['commit'])
        self.assertEqual(set(contract['files_sha256']), {'editor/grapesjs/index.ts',
            'grapesjs-plugins/grapesjs-fonts/src/index.js', 'grapesjs-plugins/grapesjs-fonts/src/fonts.js'})
        self.assertTrue(all(len(value) == 64 for value in contract['files_sha256'].values()))
        client = (ROOT / 'client-config.js').read_text()
        self.assertEqual(contract['synthetic_token'], 'VOLPAROSSA_SYNTHETIC_OFFLINE_FONT_TOKEN')
        self.assertIn("config.fontsApiKey = '" + contract['synthetic_token'] + "';", client)
        for key in ('fontsServerUrl', 'fontsApiUrl'):
            self.assertIn("config." + key + " = 'http://127.0.0.1:6805/disabled-fonts';", client)


class DiagnosticTests(unittest.TestCase):
    def value(self):
        return dict({key: 0 for key in DIAGNOSTIC_COUNTS},
            **{key: False for key in DIAGNOSTIC_FLAGS}, schema=1,
            first_page_error='none', dom_snapshot='captured',
            dom={key: False for key in DOM_FLAGS},
            interaction=dict({key: 0 for key in INTERACTION_COUNTS},
                **{key: False for key in INTERACTION_FLAGS}))

    def test_closed_diagnostic_accepts_only_bounded_counts_and_booleans(self):
        value = self.value()
        value.update(page_errors=32, first_page_error='TypeError', navigation_completed=True)
        value['interaction'].update({key: 32 for key in INTERACTION_COUNTS})
        value['interaction'].update({key: True for key in INTERACTION_FLAGS})
        validate_startup_diagnostics(value)

    def test_bounded_interaction_receipt_is_validated_before_retention(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'receipt.json'
            value = {'schema': 1, 'startup_diagnostics': self.value()}
            path.write_text(json.dumps(value))
            self.assertLess(path.stat().st_size, 4096)
            self.assertEqual(read_browser_receipt(path), value)
            del value['startup_diagnostics']['interaction']['texts']
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                read_browser_receipt(path)

    def test_unbounded_or_private_diagnostic_values_are_rejected(self):
        invalid = []
        for field, item in (('page_errors', 33), ('page_errors', True),
                            ('first_page_error', 'SYNTHETIC_PRIVATE_TEXT'),
                            ('dom_snapshot', 'SYNTHETIC_PRIVATE_TEXT'),
                            ('navigation_completed', 'SYNTHETIC_PRIVATE_TEXT')):
            value = self.value()
            value[field] = item
            invalid.append(value)
        value = self.value()
        value['url'] = 'SYNTHETIC_PRIVATE_TEXT'
        invalid.append(value)
        value = self.value()
        value['dom']['editor_root_present'] = 'SYNTHETIC_PRIVATE_TEXT'
        invalid.append(value)
        for field, item in (('texts', 33), ('texts', -1), ('texts', True),
                            ('wrapper_visible', 'SYNTHETIC_PRIVATE_TEXT'),
                            ('url', 'SYNTHETIC_PRIVATE_TEXT')):
            value = self.value()
            value['interaction'][field] = item
            invalid.append(value)
        for field in INTERACTION_COUNTS:
            for item in (-1, 33, True, 1.5, [], 'SYNTHETIC_PRIVATE_TEXT'):
                value = self.value()
                value['interaction'][field] = item
                invalid.append(value)
            value = self.value()
            del value['interaction'][field]
            invalid.append(value)
        for value in invalid:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ValueError) as caught:
                    validate_startup_diagnostics(copy.deepcopy(value))
                self.assertNotIn('SYNTHETIC_PRIVATE_TEXT', str(caught.exception))


class DragDiagnosticTests(unittest.TestCase):
    def value(self):
        phase = dict({key: False for key in DRAG_FLAGS}, snapshot='captured',
            components={key: 0 for key in COMPONENT_COUNTS})
        return dict(schema=2, observer='captured', pre_drag=copy.deepcopy(phase),
            post_drag=copy.deepcopy(phase), events={key: 0 for key in DRAG_COUNTS},
            native_handlers={kind: dict(count=0, observation='not_observed',
                **{key: None for key in NATIVE_HANDLER_FLAGS},
                **({'source_dragend_seen': None} if kind == 'drop' else {}))
                for kind in ('dragover', 'drop')})

    def test_closed_drag_phases_and_trusted_counts_validate(self):
        value = self.value()
        value['events'].update({key: 32 for key in DRAG_COUNTS})
        value['pre_drag'].update({key: True for key in DRAG_FLAGS})
        for phase in ('pre_drag', 'post_drag'):
            value[phase]['components'].update({key: 32 for key in COMPONENT_COUNTS})
        value['post_drag']['snapshot'] = 'unavailable'
        validate_drag_diagnostics(value)
        # The complete new receipt still fits the existing, unchanged limit.
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'receipt.json'
            receipt = dict(schema=1, startup_diagnostics=DiagnosticTests().value(), drag_diagnostics=value)
            path.write_text(json.dumps(receipt))
            self.assertLess(path.stat().st_size, 4096)
            self.assertEqual(read_browser_receipt(path), receipt)

    def test_native_handler_states_and_complete_receipt_bound(self):
        value = self.value()
        validate_drag_diagnostics(value)
        for count in (0, 32):
            for sample in value['native_handlers'].values():
                sample.update(observation='unavailable', count=count)
            validate_drag_diagnostics(value)
        for sample in value['native_handlers'].values():
            sample.update({key: True for key in sample if key not in ('count', 'observation')})
            sample.update(observation='captured', count=32)
        validate_drag_diagnostics(value)
        receipt = dict(schema=1, status='failed', stage='manual_text_ready',
            synthetic_only=True, network_published=False, public_hosting_accepted=False,
            shared_ai_accepted=False, error_type='TimeoutError', browser_version='123.123.123.123',
            startup_diagnostics=DiagnosticTests().value(), drag_diagnostics=value)
        for phase in ('pre_drag', 'post_drag'):
            value[phase]['components'].update({key: 32 for key in COMPONENT_COUNTS})
        value['events'].update({key: 32 for key in DRAG_COUNTS})
        receipt['startup_diagnostics']['interaction'].update({key: 32 for key in INTERACTION_COUNTS})
        receipt['startup_diagnostics'].update({key: 32 for key in DIAGNOSTIC_COUNTS})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'receipt.json'
            path.write_text(json.dumps(receipt))
            self.assertLess(path.stat().st_size, 4096)
            self.assertEqual(read_browser_receipt(path), receipt)

    def test_native_handler_schema_rejects_private_wrong_and_inconsistent_values(self):
        invalid = []
        for kind in ('dragover', 'drop'):
            baseline = self.value()['native_handlers'][kind]
            for key in baseline:
                value = self.value()
                del value['native_handlers'][kind][key]
                invalid.append(value)
            for key, item in (('count', True), ('count', 33), ('count', -1), ('count', 1.5),
                              ('count', 1), ('observation', []), ('observation', 'SYNTHETIC_PRIVATE_TEXT'),
                              ('observation', 'captured'), ('payload', 'SYNTHETIC_PRIVATE_TEXT')):
                value = self.value()
                value['native_handlers'][kind][key] = item
                invalid.append(value)
            for field in baseline.keys() - {'count', 'observation'}:
                value = self.value()
                value['native_handlers'][kind][field] = False
                invalid.append(value)
                for item in (None, 0, 1, [], 'SYNTHETIC_PRIVATE_TEXT'):
                    value = self.value()
                    sample = value['native_handlers'][kind]
                    sample.update({key: False for key in baseline.keys() - {'count', 'observation'}})
                    sample.update(observation='captured', count=1)
                    sample[field] = item
                    invalid.append(value)
        for handlers in (None, [], {}, {'payload': 'SYNTHETIC_PRIVATE_TEXT'}):
            value = self.value()
            value['native_handlers'] = handlers
            invalid.append(value)
        value = self.value()
        value['schema'] = 1
        invalid.append(value)  # Historical schema-1 artifacts are not revalidated as schema 2.
        for value in invalid:
            with self.assertRaises(ValueError) as caught:
                validate_drag_diagnostics(value)
            self.assertNotIn('SYNTHETIC_PRIVATE_TEXT', str(caught.exception))

    def test_independent_selector_counts_do_not_require_combined_matches(self):
        value = self.value()
        for phase in ('pre_drag', 'post_drag'):
            value[phase]['components'].update(wrapper_descendants=7, bare_texts=2,
                default_texts=1, texts=0, editable_texts=0)
        validate_drag_diagnostics(value)
        late = DiagnosticTests().value()
        late['interaction'].update(value['post_drag']['components'])
        validate_startup_diagnostics(late)

    def test_private_unbounded_and_wrong_phase_types_are_rejected(self):
        invalid = []
        for key, item in (('source_dragstart', 33), ('source_dragstart', -1),
                          ('source_dragstart', True), ('payload', 'SYNTHETIC_PRIVATE_TEXT')):
            value = self.value()
            value['events'][key] = item
            invalid.append(value)
        for phase in ('pre_drag', 'post_drag'):
            for key, item in (('snapshot', []), ('snapshot', 'SYNTHETIC_PRIVATE_TEXT'),
                              ('source_draggable', 'SYNTHETIC_PRIVATE_TEXT'),
                              ('target_id', 'SYNTHETIC_PRIVATE_TEXT')):
                value = self.value()
                value[phase][key] = item
                invalid.append(value)
        for phase in ('pre_drag', 'post_drag'):
            for field in COMPONENT_COUNTS:
                for item in (-1, 33, True, 1.5, [], 'SYNTHETIC_PRIVATE_TEXT'):
                    value = self.value()
                    value[phase]['components'][field] = item
                    invalid.append(value)
                value = self.value()
                del value[phase]['components'][field]
                invalid.append(value)
            for item in (None, [], {'payload': 'SYNTHETIC_PRIVATE_TEXT'}):
                value = self.value()
                value[phase]['components'] = item
                invalid.append(value)
        for key, item in (('schema', True), ('observer', []), ('observer', 'SYNTHETIC_PRIVATE_TEXT'),
                          ('url', 'SYNTHETIC_PRIVATE_TEXT')):
            value = self.value()
            value[key] = item
            invalid.append(value)
        value = self.value()
        del value['post_drag']
        invalid.append(value)
        for value in invalid:
            with self.assertRaises(ValueError) as caught:
                validate_drag_diagnostics(value)
            self.assertNotIn('SYNTHETIC_PRIVATE_TEXT', str(caught.exception))

    def test_invalid_drag_receipt_is_rejected_before_retention(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'receipt.json'
            value = self.value()
            value['events']['source_dragstart'] = 'SYNTHETIC_PRIVATE_TEXT'
            path.write_text(json.dumps(dict(drag_diagnostics=value)))
            with self.assertRaises(ValueError):
                read_browser_receipt(path)


if __name__ == '__main__':
    unittest.main()
