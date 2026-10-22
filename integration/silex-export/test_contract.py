# SPDX-License-Identifier: GPL-3.0-only
"""Inert safety checks. Synthetic ZIPs below are NOT Silex/runtime evidence."""
import ast
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


if __name__ == '__main__':
    unittest.main()
