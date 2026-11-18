# SPDX-License-Identifier: GPL-3.0-only
"""Filesystem tests for the producer's same-run transport of public artifacts."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from extract import extract
from test_signed_site_receipt import private, proof
from topology_handoff import prepare, deliver
from topology_image import NAME, write_chart


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class TopologyHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as source:
            cls.chart = write_chart(Path(source)).read_bytes()

    def setUp(self):
        self.runner = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.temp = self.runner / 'studio-export'
        self.temp.mkdir(mode=0o700)
        self.stage = self.temp / 'signed-topology-input'
        self.stage.mkdir(mode=0o700)
        self.output = self.runner / 'studio-topology-handoff'
        self.now = 2_000_000_000
        self.enterContext(patch('topology_handoff.time.time', return_value=self.now))
        self.environ = {'GITHUB_RUN_ID': '123456', 'GITHUB_RUN_ATTEMPT': '2'}

        private(self.temp / NAME, self.chart)
        archive = self.temp / 'actual-export.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('studio-export.html', f'<p>Edited synthetic public page</p><img src="/assets/{NAME}">')
            z.writestr('index.html', '<a href="studio-export.html">Site</a>')
            z.writestr('assets/' + NAME, self.chart)
        self.inventory = self.temp / 'inventory.json'
        extract(archive, self.temp / 'export', self.inventory)
        self.assets = json.loads(self.inventory.read_bytes())['assets']
        self.bundle = b'synthetic signed-test output' + self.chart
        self.manifest = b'synthetic manifest'
        private(self.stage / 'site.vps', self.bundle)
        private(self.stage / 'manifest.bin', self.manifest)
        signed = proof()
        bindings = {'bundle_sha256': sha256(self.bundle), 'bundle_bytes': len(self.bundle),
                    'asset_count': len(self.assets)}
        signed['bindings'].update(bindings, manifest_id=sha256(self.manifest),
                                  chunk_count=(len(self.bundle) + 262143) // 262144,
                                  publication_expires_unix_seconds=self.now + 7200)
        signed['browser'].update(bindings)
        browser = dict.fromkeys(('manual_page_created', 'manual_text_edited', 'manual_style_edited',
            'preview_checked', 'actual_download_connector_zip', 'download_consumed',
            'saved_project_reopened', 'topology_image_reopened'), True)
        browser.update(status='passed', zip_bytes=archive.stat().st_size, external_requests_blocked=0)
        clean = {'capabilities_dropped': True, 'isolated_network_namespace': True,
                 'nonroot_runner_uid': True, 'cleanup_failed': False}
        self.receipt = {
            'STUDIO_CORE_REVISION': 'd' * 40, 'STUDIO_REVISION': 'e' * 40, 'silex_revision': 'f' * 40,
            'signed_site_recovery': signed, 'browser_export': browser,
            'runtime_cleanup': dict(clean, server_joined=True, server_group_drained=True,
                                    browser_driver_group_drained=True),
            'viewer_cleanup': dict(clean, core_joined=True, core_group_drained=True),
        }

    def prepare(self):
        return prepare(self.temp, self.receipt, self.environ)

    def test_exact_public_files_bind_reopened_export_run_and_original_publication(self):
        # An accidental attempt to read the unrelated key file must fail.
        (self.temp / 'operator.key').symlink_to(self.temp / 'absent-key-file')
        marker = 'synthetic diagnostic outside the public receipt'
        self.receipt['private_diagnostics'] = marker
        files = self.prepare()
        self.assertEqual(set(files), {'site.vps', 'manifest.bin', 'evidence.json'})
        self.assertEqual((files['site.vps'], files['manifest.bin']), (self.bundle, self.manifest))
        evidence = json.loads(files['evidence.json'])
        self.assertEqual(evidence['assets'], self.assets)
        self.assertEqual(evidence['zip_sha256'], sha256((self.temp / 'actual-export.zip').read_bytes()))
        self.assertEqual((evidence['run_id'], evidence['run_attempt']), ('123456', '2'))
        self.assertEqual((evidence['core_revision'], evidence['studio_revision'], evidence['silex_revision']),
                         ('d' * 40, 'e' * 40, 'f' * 40))
        for field, value in self.receipt['signed_site_recovery']['bindings'].items():
            self.assertEqual(evidence[field], value)
        self.assertNotIn(marker.encode(), files['evidence.json'])
        self.assertNotIn(str(self.runner), files['evidence.json'].decode())
        self.assertEqual(deliver(self.runner, files), sha256(files['evidence.json']))
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        self.assertEqual({p.name for p in self.output.iterdir()}, set(files))
        for name, expected in files.items():
            path = self.output / name
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_wrong_publication_bytes_cannot_be_rebound(self):
        for name in ('manifest.bin', 'site.vps'):
            path = self.stage / name
            original = path.read_bytes()
            with self.subTest(name=name):
                private(path, b'!' + original[1:])
                with self.assertRaises(ValueError):
                    self.prepare()
                private(path, original)
        self.assertFalse(self.output.exists())

    def test_staging_rejects_extra_private_file_and_public_input_permissions(self):
        extra = self.stage / 'identity.key'
        private(extra, b'test private state')
        with self.assertRaises(ValueError):
            self.prepare()
        extra.unlink()
        for path in (self.stage, self.stage / 'site.vps', self.stage / 'manifest.bin'):
            with self.subTest(path=path.name):
                original = stat.S_IMODE(path.stat().st_mode)
                path.chmod(original | 0o040)
                with self.assertRaises(ValueError):
                    self.prepare()
                path.chmod(original)

    def test_signed_revision_and_positive_bounded_remaining_lifetime(self):
        binding = self.receipt['signed_site_recovery']['bindings']
        for expiry in (self.now - 1, self.now, self.now + 7201):
            with self.subTest(expiry=expiry):
                binding['publication_expires_unix_seconds'] = expiry
                with self.assertRaises(ValueError):
                    self.prepare()
        binding['publication_expires_unix_seconds'] = self.now + 1
        self.assertIn('evidence.json', self.prepare())
        binding['revision'] = 2
        with self.assertRaises(ValueError):
            self.prepare()

    def test_reopening_cleanup_and_source_identity_are_required(self):
        for mapping, key, bad in (
            (self.receipt['browser_export'], 'saved_project_reopened', False),
            (self.receipt['browser_export'], 'download_consumed', 1),
            (self.receipt['browser_export'], 'zip_bytes', 1),
            (self.receipt['browser_export'], 'external_requests_blocked', True),
            (self.receipt['viewer_cleanup'], 'core_joined', False),
            (self.receipt['runtime_cleanup'], 'cleanup_failed', True),
            (self.environ, 'GITHUB_RUN_ATTEMPT', '0'),
            (self.environ, 'GITHUB_RUN_ID', '0123'),
            (self.receipt, 'STUDIO_REVISION', 'main'),
        ):
            with self.subTest(key=key):
                with patch.dict(mapping, {key: bad}), self.assertRaises(ValueError):
                    self.prepare()

    def test_substituted_asset_inventory_is_rejected(self):
        entry = next(asset for asset in self.assets if asset['path'] == '/index.html')
        entry['sha256'] = sha256(b'unrelated bytes')
        self.inventory.write_text(json.dumps({'schema': 1, 'assets': self.assets}))
        with self.assertRaises(ValueError):
            self.prepare()

    def test_reopened_image_must_still_match_the_uploaded_file(self):
        image = self.temp / NAME
        private(image, self.chart[:-1] + bytes([self.chart[-1] ^ 1]))
        with self.assertRaises(ValueError):
            self.prepare()

    def test_failed_delivery_removes_partial_output_before_retry(self):
        files = self.prepare()
        original_open = os.open

        def interrupt_manifest(path, *args, **kwargs):
            if path == self.output / 'manifest.bin':
                raise OSError('simulated write failure')
            return original_open(path, *args, **kwargs)

        with patch('topology_handoff.os.open', side_effect=interrupt_manifest), self.assertRaises(OSError):
            deliver(self.runner, files)
        self.assertFalse(self.output.exists())
        self.assertEqual(deliver(self.runner, files), sha256(files['evidence.json']))

    def test_delivery_never_overwrites_existing_state(self):
        files = self.prepare()
        with self.assertRaises(ValueError):
            deliver(self.runner, dict(files, **{'private.key': b'secret'}))
        self.assertFalse(self.output.exists())
        self.output.mkdir()
        existing = self.output / 'site.vps'
        existing.write_bytes(b'pre-existing public handoff')
        with self.assertRaises(FileExistsError):
            deliver(self.runner, files)
        self.assertEqual(existing.read_bytes(), b'pre-existing public handoff')
        self.assertEqual(list(self.output.iterdir()), [existing])


if __name__ == '__main__':
    unittest.main()
