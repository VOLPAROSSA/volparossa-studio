# SPDX-License-Identifier: GPL-3.0-only
"""Pass the saved synthetic project through the native editor before authorizing its signed fixture."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from extract import extract
from signed_site_profile import read_owned, read_private, strict_json
from topology_image import NAME


def require(check):
    if not check:
        raise ValueError('native_project_handoff_rejected')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_file(path, data):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as output:
        output.write(data)


def prepare(core, studio, temporary, env, run):
    require(os.environ['GITHUB_REPOSITORY'] == 'VOLPAROSSA/volparossa-studio'
            and os.environ['GITHUB_SHA'] == os.environ['GITHUB_WORKFLOW_SHA'] == os.environ['STUDIO_REVISION']
            and temporary.parent == Path(os.environ['RUNNER_TEMP']))
    original = strict_json(read_owned(temporary / 'inventory.json', 8192, private=False))
    project = read_private(temporary / 'native-project.json', 65536)
    chart = read_private(temporary / NAME, 3 * 1024**2)
    # The transport exists only while the native job runs. Its original user creates every file.
    handoff = temporary.parent / 'silex-native-hosting-input'
    handoff.mkdir(mode=0o700)
    try:
        private_file(handoff / 'native-project.json', project)
        private_file(handoff / NAME, chart)
        private_file(handoff / 'native-inventory.json', json.dumps(original).encode())
        run([sys.executable, '-I', '-B', studio / 'integration/silex-native-runtime/isolation.py'],
            temporary, dict(os.environ, STUDIO_NATIVE_WEBVIEW='hosting'), 'native-editor', timeout=125, cwd=studio)
        report = strict_json(read_owned(temporary.parent / 'silex-native-webview.json', 65536, private=False))
        actor = report['root_result']['worker']['native_webview']['actor']
        native = actor['native_export']
        require(report['status'] == 'passed' and report['studio_revision'] == os.environ['STUDIO_REVISION']
                and report['cleanup_confirmed'] and actor['original_project_reopened'] is True
                and actor['canvas_readbacks'] == ['accessible_text'] * 2 and actor['native_window_closes'] == 2
                and native['asset_count'] == len(original['assets']) == 5)
        archive = read_private(handoff / 'native.zip', 3 * 1024**2)
        require(digest(archive) == native['archive_sha256'] and len(archive) == native['archive_bytes'])
        # The download remains intact as the independent byte reference. Core will read
        # the export obtained from the native File system hosting connector via this new tree.
        (temporary / 'export').rename(temporary / 'browser-export')
        require(extract(handoff / 'native.zip', temporary / 'export', temporary / 'native-inventory.json') == 5)
        require(strict_json(read_owned(temporary / 'native-inventory.json', 8192, private=False)) == original)
    finally:
        shutil.rmtree(handoff)
    bundle = temporary / 'native-reviewed.vps'
    log = run([core / 'target/debug/volparossa', '--control-socket', temporary / 'unavailable.sock',
        'content', 'site', 'pack', '--directory', temporary / 'export', '--output', bundle, '--review-receipt'],
        temporary, env, 'native-review', timeout=12, cwd=core)
    review = strict_json(read_owned(log, 8192, private=False))
    prepared = read_private(bundle, 3 * 1024**2)
    require(review['operation'] == 'site_pack_preparation' and review['review_required'] is True
            and review['native_consent_granted'] is False and review['network_published'] is False
            and review['publication_signed'] is False and review['bundle_sha256'] == digest(prepared)
            and review['bundle_bytes'] == len(prepared) and review['asset_count'] == 5
            and [{k: row[k] for k in ('path', 'sha256', 'bytes')} for row in review['assets']] == original['assets'])
    return dict(operation='native_file_hosting_export', native_reopened=True, original_assets_equal=True,
        asset_count=5, signing_input='native_file_hosting', source_project_sha256=digest(project),
        native_archive_sha256=native['archive_sha256'], reviewed_bundle_sha256=review['bundle_sha256'],
        bundle_bytes=len(prepared))
