# SPDX-License-Identifier: GPL-3.0-only
"""Check the source of bytes admitted to the signer without running native programs."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import native_handoff as handoff


class NativeHandoffTests(unittest.TestCase):
    def test_signer_receives_only_verified_native_files(self):
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as name:
                runner = Path(name)
                workspace = runner / 'studio-export-test'
                workspace.mkdir()
                (workspace / 'export').mkdir()
                (workspace / 'export/reference-only').touch()
                paths = ('assets/studio-topology.png', 'css/index.css', 'css/page.css', 'index.html', 'studio-export.html')
                bodies = {p: ('original ' + p).encode() for p in paths}
                rows = [dict(path='/' + p, bytes=len(data), sha256=handoff.digest(data)) for p, data in bodies.items()]
                handoff.private_file(workspace / 'inventory.json', json.dumps(dict(schema=1, assets=rows)).encode())
                handoff.private_file(workspace / 'native-project.json', b'{"pages":[]}')
                handoff.private_file(workspace / handoff.NAME, bodies[paths[0]])
                revision = 'a' * 40
                calls = []
                def run(command, temporary, env, label, **_options):
                    calls.append(label)
                    if label == 'native-editor':
                        owned = runner / 'silex-native-hosting-input'
                        self.assertEqual((owned / 'native-project.json').read_bytes(), b'{"pages":[]}')
                        with zipfile.ZipFile(owned / 'native.zip', 'w') as archive:
                            for path, body in bodies.items():
                                archive.writestr(path, b'other' if changed and path == 'index.html' else body)
                        raw = (owned / 'native.zip').read_bytes()
                        actor = dict(original_project_reopened=True, canvas_readbacks=['accessible_text'] * 2,
                            native_window_closes=2, native_export=dict(asset_count=5, archive_bytes=len(raw),
                            archive_sha256=handoff.digest(raw)))
                        receipt = dict(status='passed', studio_revision=revision, cleanup_confirmed=True,
                            root_result=dict(worker=dict(native_webview=dict(actor=actor))))
                        handoff.private_file(runner / 'silex-native-webview.json', json.dumps(receipt).encode())
                        return
                    self.assertEqual(label, 'native-review')
                    source = command[command.index('--directory') + 1]
                    self.assertTrue((temporary / 'browser-export/reference-only').is_file())
                    self.assertFalse((source / 'reference-only').exists())
                    self.assertEqual({p: (source / p).read_bytes() for p in paths}, bodies)
                    bundle = b'packed native export'
                    handoff.private_file(command[command.index('--output') + 1], bundle)
                    record = dict(operation='site_pack_preparation', review_required=True, native_consent_granted=False,
                        network_published=False, publication_signed=False, bundle_sha256=handoff.digest(bundle),
                        bundle_bytes=len(bundle), asset_count=5, assets=rows)
                    log = temporary / 'native-review.log'
                    handoff.private_file(log, json.dumps(record).encode())
                    return log
                env = dict(GITHUB_REPOSITORY='VOLPAROSSA/volparossa-studio', GITHUB_SHA=revision,
                    GITHUB_WORKFLOW_SHA=revision, STUDIO_REVISION=revision, RUNNER_TEMP=name)
                with patch.dict(handoff.os.environ, env):
                    if changed:
                        with self.assertRaises(ValueError):
                            handoff.prepare(runner / 'core', runner / 'studio', workspace, {}, run)
                        self.assertEqual(calls, ['native-editor'])
                    else:
                        result = handoff.prepare(runner / 'core', runner / 'studio', workspace, {}, run)
                        self.assertEqual(result['signing_input'], 'native_file_hosting')
                        self.assertEqual(calls, ['native-editor', 'native-review'])
                self.assertFalse((runner / 'silex-native-hosting-input').exists())


if __name__ == '__main__':
    unittest.main()
