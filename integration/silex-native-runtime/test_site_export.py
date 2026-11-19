# SPDX-License-Identifier: GPL-3.0-only
"""Inert checks for exact native export bytes and Core's local review boundary."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


site = module('site_export')
supervisor = module('isolation_root')
ID = '0d59fb9a-33ae-4d4d-9e84-7dcd5284e337'


def saved(directory):
    css = b'h1{background:#abc}'
    basename = 'index-' + site.sha(css) + '.css'
    (directory / 'css').mkdir()
    (directory / 'css' / basename).write_bytes(css)
    (directory / 'index.html').write_text('<link href="css/' + basename + '"><h1>Restored canvas ' + ID + '</h1>')


def review(directory, packed=b'fixture'):
    return dict(schema_version=1, operation='site_pack_preparation', source='explicit_local_directory',
        content_type='application/vnd.volparossa.site.v1', bundle_sha256=site.sha(packed), bundle_bytes=len(packed),
        asset_count=2, assets=site.assets(directory, ID), native_consent_granted=False, publication_signed=False,
        network_published=False, publisher_authority_granted=False, permission_authority_granted=False,
        symlinks_followed=False, input_files_modified=False, hidden_entries_excluded=True,
        bundle_output_created=True, review_required=True)


class SiteExportTests(unittest.TestCase):
    def test_real_export_must_retain_the_exact_heading_stylesheet_and_regular_files(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            saved(root)
            rows = site.assets(root, ID)
            self.assertEqual([x['content_type'] for x in rows], ['text/css', 'text/html'])
            with self.assertRaises(ValueError):
                site.assets(root, ID[::-1])
            (root / 'private').touch()
            with self.assertRaises(ValueError):
                site.assets(root, ID)
            (root / 'private').unlink()
            html = root / 'index.html'
            html.rename(root / 'actual')
            html.symlink_to(root / 'actual')
            with self.assertRaises((OSError, ValueError)):
                site.read_regular(html, 32768)

    def test_only_the_closed_unsigned_preparation_receipt_is_publishable(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            saved(root)
            record = review(root)
            supervisor.verify_site_review(record)
            for key in ('native_consent_granted', 'publication_signed', 'network_published', 'publisher_authority_granted'):
                with self.subTest(key=key), self.assertRaises(supervisor.Rejected):
                    supervisor.verify_site_review(dict(record, **{key: True}))
            for wrong in (dict(record, secret='private'), dict(record, assets=[]), dict(record, review_required=False)):
                with self.assertRaises(supervisor.Rejected):
                    supervisor.verify_site_review(wrong)

    def test_export_profile_requires_its_review_and_the_reopen_profile_remains_independent(self):
        actor = dict(status='passed', stage='complete', process_groups_started=4, process_groups_joined=4,
            desktop_launches=2, native_window_closes=2, editor_title_states=['clean', 'clean'],
            canvas_readbacks=['accessible_text', 'accessible_text'], close_actions=['quit_dialog', 'quit_dialog'],
            original_project_reopened=True, project_id_sha256='0' * 64)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            saved(root)
            exported = dict(actor, site_pack_review=review(root))
            for enabled, accepted, rejected in ((False, actor, exported), (True, exported, actor)):
                with patch.object(supervisor, 'SITE_EXPORT', enabled):
                    supervisor.verify_gui(accepted)
                    with self.assertRaises(supervisor.Rejected):
                        supervisor.verify_gui(rejected)

    def test_packer_receipt_is_bound_to_actual_bundle_and_original_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'site'
            root.mkdir()
            saved(root)
            record = review(root)
            def prepare(command, **options):
                self.assertEqual(command[:2], ['/run/fixture/volparossa', '--control-socket'])
                self.assertEqual(command[3:8], ['content', 'site', 'pack', '--directory', str(root)])
                Path(command[command.index('--output') + 1]).write_bytes(b'fixture')
                options['stdout'].write(json.dumps(record).encode())
                return site.subprocess.CompletedProcess(command, 0)
            with patch.dict(os.environ, XDG_RUNTIME_DIR=temporary), patch.object(site.subprocess, 'run', side_effect=prepare):
                self.assertEqual(site.pack(root, ID), record)
                for field in ('bundle_sha256', 'assets'):
                    original = record[field]
                    record[field] = '0' * 64 if field == 'bundle_sha256' else []
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        site.pack(root, ID)
                    record[field] = original


if __name__ == '__main__':
    unittest.main()
