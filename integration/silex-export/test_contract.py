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
from run import COMPONENT_COUNTS, DRAG_COUNTS, DRAG_FLAGS, validate_drag_diagnostics, DIAGNOSTIC_COUNTS, DIAGNOSTIC_FLAGS, DOM_FLAGS, INTERACTION_COUNTS, INTERACTION_FLAGS, read_browser_receipt, validate_startup_diagnostics

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

    def test_drag_observer_cannot_modify_input_flow_or_read_payloads(self):
        driver = (ROOT / 'browser-export.mjs').read_text()
        observer = driver.split('dragObserver = await page.evaluateHandle', 1)[1].split("stage = 'manual_drag';", 1)[0]
        self.assertIn('event.isTrusted', observer)
        self.assertIn('passive: true', observer)
        self.assertIn('Math.min(32,', observer)
        self.assertIn('removeEventListener', observer)
        for forbidden in ('preventDefault', 'stopPropagation', 'return false', 'dispatchEvent',
                          'dataTransfer', 'getData(', 'innerHTML', 'innerText', 'textContent',
                          'setAttribute', 'appendChild', 'window.silex'):
            self.assertNotIn(forbidden, observer)

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
        return dict(schema=1, observer='captured', pre_drag=copy.deepcopy(phase),
            post_drag=copy.deepcopy(phase), events={key: 0 for key in DRAG_COUNTS})

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
