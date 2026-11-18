# SPDX-License-Identifier: GPL-3.0-only
"""Pass the original, verified public publication to the same runner's isolated topology."""
import hashlib
from html.parser import HTMLParser
import io
import json
import os
import re
import shutil
import stat
import time
from urllib.parse import urljoin
import zipfile

from extract import MAX_ZIP, MAX_ENTRIES
from topology_image import NAME as CHART_NAME
from signed_site_profile import read_owned, read_private, strict_json
from signed_site_receipt import closed, digest, flags, integer, validate_signed_proof

DESTINATION = 'studio-topology-handoff'
FILES = ('site.vps', 'manifest.bin', 'evidence.json')
METADATA_LIMIT = 65536


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class ChartReference(HTMLParser):
    found = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            sources = [value for key, value in attrs if key == 'src']
            if len(sources) == 1 and urljoin('https://fixture.invalid/studio-export.html', sources[0]) == (
                    'https://fixture.invalid/assets/' + CHART_NAME):
                self.found += 1


def check_archive(archive, assets, temporary):
    image_path = '/assets/' + CHART_NAME
    authored = read_private(temporary / CHART_NAME, MAX_ZIP)
    if not 2 * 1024 * 1024 < len(authored) < 3 * 1024 * 1024:
        raise ValueError('multi-chunk source chart required')
    rows = {row['path']: row for row in assets}
    image = rows.get(image_path)
    if not image or image['sha256'] != sha256(authored) or image['bytes'] != len(authored):
        raise ValueError('exported image differs from the editor input')
    del authored
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        entries = zipped.infolist()
        copied = [entry for entry in entries if not entry.is_dir()]
        if (len(entries) > MAX_ENTRIES or sorted('/' + entry.filename for entry in copied) != sorted(rows)
                or sum(entry.file_size for entry in copied) > MAX_ZIP):
            raise ValueError('actual ZIP assets differ from checked inventory')
        for entry in copied:
            path = '/' + entry.filename
            if entry.file_size != rows[path]['bytes']:
                raise ValueError('asset size differs')
            with zipped.open(entry) as source:
                if path == '/studio-export.html':
                    page = source.read()
                    chart = ChartReference()
                    chart.feed(page.decode('utf-8'))
                    chart.close()
                    if chart.found != 1:
                        raise ValueError('exported page must display the authored chart')
                    actual = sha256(page)
                else:
                    actual = hashlib.file_digest(source, 'sha256').hexdigest()
            if actual != rows[path]['sha256']:
                raise ValueError('actual ZIP asset digest differs')


def prepare(temporary, receipt, environ):
    browser = receipt['browser_export']
    required = ('manual_page_created', 'manual_text_edited', 'manual_style_edited', 'preview_checked',
                'actual_download_connector_zip', 'download_consumed', 'saved_project_reopened', 'topology_image_reopened')
    if browser['status'] != 'passed' or any(browser[key] is not True for key in required):
        raise ValueError('freshly reopened actual editor export required')
    integer(browser['external_requests_blocked'], 0, 0)
    flags(receipt['runtime_cleanup'], ('server_joined', 'server_group_drained', 'browser_driver_group_drained',
          'isolated_network_namespace', 'capabilities_dropped', 'nonroot_runner_uid'), ('cleanup_failed',))
    flags(receipt['viewer_cleanup'], ('core_group_drained', 'core_joined', 'isolated_network_namespace',
          'capabilities_dropped', 'nonroot_runner_uid'), ('cleanup_failed',))
    run_id, attempt = environ['GITHUB_RUN_ID'], environ['GITHUB_RUN_ATTEMPT']
    if any(not re.fullmatch('[1-9][0-9]{0,19}', value) for value in (run_id, attempt)):
        raise ValueError('same hosted run identity required')
    sources = dict(core_revision=receipt['STUDIO_CORE_REVISION'], studio_revision=receipt['STUDIO_REVISION'],
                   silex_revision=receipt['silex_revision'])
    if any(not re.fullmatch('[0-9a-f]{40}', value) for value in sources.values()):
        raise ValueError('exact source revisions required')
    archive = read_owned(temporary / 'actual-export.zip', MAX_ZIP, private=False)
    integer(browser['zip_bytes'], 1, MAX_ZIP)
    if len(archive) != browser['zip_bytes']:
        raise ValueError('download size changed')
    zip_sha = sha256(archive)
    inventory = strict_json(read_owned(temporary / 'inventory.json', METADATA_LIMIT, private=False))
    closed(inventory, ('schema', 'assets'))
    integer(inventory['schema'], 1, 1)
    assets = inventory['assets']
    if type(assets) is not list:
        raise ValueError('actual ZIP asset inventory required')
    binding = validate_signed_proof(receipt['signed_site_recovery'], len(assets))['bindings']
    paths = []
    for asset in assets:
        closed(asset, ('path', 'bytes', 'sha256'))
        path = asset['path']
        if (not isinstance(path, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', path)
                or any(not part or part.startswith('.') for part in path[1:].split('/'))):
            raise ValueError('portable export path required')
        paths.append(path)
        integer(asset['bytes'], 0, MAX_ZIP)
        digest(asset['sha256'])
    if paths != sorted(set(paths)) or not {'/index.html', '/studio-export.html'}.issubset(paths):
        raise ValueError('reopened editor page and complete sorted inventory required')
    check_archive(archive, assets, temporary)
    del archive
    stage = temporary / 'signed-topology-input'
    metadata = stage.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700 or {p.name for p in stage.iterdir()} != set(FILES[:2])):
        raise ValueError('exclusive two-file signed publication required')
    bundle = read_private(stage / FILES[0], MAX_ZIP)
    manifest = read_private(stage / FILES[1], METADATA_LIMIT)
    if (not manifest or len(bundle) != binding['bundle_bytes'] or sha256(bundle) != binding['bundle_sha256']
            or sha256(manifest) != binding['manifest_id'] or binding['revision'] != 1):
        raise ValueError('original signed publication bytes differ')
    now = int(time.time())
    integer(binding['publication_expires_unix_seconds'], now + 1, now + 7200)
    evidence = dict(schema=1, kind='silex-topology-handoff', run_id=run_id, run_attempt=attempt,
                    **sources, **binding, assets=assets, zip_sha256=zip_sha, name='public-silex-signed-recovery-fixture')
    encoded = (json.dumps(evidence, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if len(encoded) > METADATA_LIMIT:
        raise ValueError('topology metadata bound exceeded')
    return dict(zip(FILES, (bundle, manifest, encoded)))


def deliver(runner_temp, files):
    if set(files) != set(FILES):
        raise ValueError('exact public handoff files required')
    destination = runner_temp / DESTINATION
    destination.mkdir(mode=0o700)
    try:
        for name in FILES:
            descriptor = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, 'wb') as output:
                output.write(files[name])
    except BaseException:
        shutil.rmtree(destination)
        raise
    return sha256(files['evidence.json'])
