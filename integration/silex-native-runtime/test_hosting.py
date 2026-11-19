# SPDX-License-Identifier: GPL-3.0-only
"""Inert tests for restoring and forwarding the original five portable assets."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('hosting', Path(__file__).with_name('hosting.py'))
hosting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hosting)


class HostingTests(unittest.TestCase):
    def test_saved_marker_chart_and_style_belong_to_the_authored_project(self):
        project = {'pages': [{'name': 'Index'}, {'name': 'Studio export', 'frames': [
            {'text': hosting.MARKER, 'image': '/assets/' + hosting.CHART, 'font-size': '37px'}]}]}
        self.assertEqual(hosting.capture_project(json.dumps(project).encode()), project)
        for field in ('text', 'image', 'font-size'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                copy = json.loads(json.dumps(project))
                del copy['pages'][1]['frames'][0][field]
                hosting.capture_project(json.dumps(copy).encode())

    def test_only_the_original_files_and_bytes_can_be_forwarded_for_signing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            source = home / 'public'
            source.mkdir()
            (source / 'assets').mkdir()
            (source / 'css').mkdir()
            assets = [('assets/studio-topology.png', b'original chart'),
                      ('css/index-' + 'a' * 64 + '.css', b'first styles'),
                      ('css/studio-export-' + 'b' * 64 + '.css', b'second styles'),
                      ('index.html', b'original index'), ('studio-export.html', b'original page')]
            for name, data in assets:
                (source / name).write_bytes(data)
            inventory = json.dumps(dict(schema=1, assets=[dict(path='/' + name, bytes=len(data),
                sha256=hosting.sha(data)) for name, data in assets])).encode()
            output = home / 'native.zip'
            record = hosting.archive(source, inventory, output, lambda _phase: None)
            self.assertEqual(record['asset_count'], 5)
            self.assertEqual(record['archive_sha256'], hosting.sha(output.read_bytes()))
            with zipfile.ZipFile(output) as archive:
                self.assertEqual([(path, archive.read(path)) for path in archive.namelist()], assets)
            output.unlink()
            (source / 'unreviewed').touch()
            with self.assertRaises(ValueError):
                hosting.archive(source, inventory, output, lambda _phase: None)
            (source / 'unreviewed').unlink()
            (source / 'index.html').write_bytes(b'replaced index')
            with self.assertRaises(ValueError):
                hosting.archive(source, inventory, output, lambda _phase: None)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
