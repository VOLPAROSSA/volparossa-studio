# SPDX-License-Identifier: GPL-3.0-only
"""Explicit hosted-only trial; no publication keys, daemon, external deployment or AI."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

from extract import extract
from lifecycle import GroupCaptureFailure, drain_group, start_group
from runtime_context import write_context
from viewer_receipt import validate_viewer_proof, read_viewer_cleanup

FIXTURE = Path(__file__).resolve().parent
PINS = json.loads((FIXTURE / 'manifest.json').read_text())
OPERATIONS = frozenset(('install-silex', 'install-driver', 'build-client', 'build-server',
                        'build-public', 'runtime', 'core-pack', 'core-build', 'viewer-runtime'))
FAILURES = frozenset(('exit_nonzero', 'signal_terminated', 'deadline_exceeded',
                      'output_limit_exceeded', 'spawn_failed', 'cleanup_failed', 'cancelled'))
DIAGNOSTIC_COUNTS = frozenset(('page_errors', 'console_errors', 'failed_requests',
                              'bad_responses', 'blocked_external_requests'))
DIAGNOSTIC_FLAGS = frozenset(('missing_font_api_key_error', 'navigation_completed'))
DOM_FLAGS = frozenset(('editor_root_present', 'loader_present', 'loader_hidden',
    'editor_root_visible', 'frame_present', 'silex_api_present', 'client_config_present',
    'fonts_api_key_empty'))

COMPONENT_COUNTS = frozenset(('wrapper_descendants', 'bare_texts', 'default_texts', 'texts', 'editable_texts'))
INTERACTION_COUNTS = COMPONENT_COUNTS | {'blocks', 'text_blocks', 'frames', 'wrappers'}
INTERACTION_FLAGS = frozenset(('wrapper_visible', 'text_visible'))


def validate_startup_diagnostics(value):
    keys = DIAGNOSTIC_COUNTS | DIAGNOSTIC_FLAGS | {'schema', 'first_page_error', 'dom_snapshot', 'dom', 'interaction'}
    if type(value) is not dict or set(value) != keys or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('closed startup diagnostic schema required')
    if any(type(value[key]) is not int or not 0 <= value[key] <= 32 for key in DIAGNOSTIC_COUNTS):
        raise ValueError('bounded startup counters required')
    if any(type(value[key]) is not bool for key in DIAGNOSTIC_FLAGS):
        raise ValueError('startup flags must be booleans')
    if value['first_page_error'] not in ('none', 'Error', 'TypeError', 'ReferenceError', 'SyntaxError', 'RangeError', 'other'):
        raise ValueError('closed startup error category required')
    if value['dom_snapshot'] not in ('not_attempted', 'captured', 'unavailable'):
        raise ValueError('closed DOM observation status required')
    dom = value['dom']
    if type(dom) is not dict or set(dom) != DOM_FLAGS or any(type(item) is not bool for item in dom.values()):
        raise ValueError('read-only DOM boolean inventory required')

    interaction = value['interaction']
    if type(interaction) is not dict or set(interaction) != INTERACTION_COUNTS | INTERACTION_FLAGS:
        raise ValueError('closed interaction observation inventory required')
    if any(type(interaction[key]) is not int or not 0 <= interaction[key] <= 32 for key in INTERACTION_COUNTS):
        raise ValueError('bounded interaction counters required')
    if any(type(interaction[key]) is not bool for key in INTERACTION_FLAGS):
        raise ValueError('read-only interaction flags must be booleans')


DRAG_COUNTS = frozenset(('source_dragstart', 'source_dragend', 'wrapper_dragenter',
                        'wrapper_dragover', 'wrapper_drop'))
DRAG_FLAGS = frozenset(('source_draggable', 'source_point_in_block',
                       'target_main_hit_is_frame', 'target_frame_hit_in_wrapper'))
NATIVE_HANDLER_FLAGS = frozenset(('cancelable', 'default_prevented', 'hit_is_wrapper', 'hit_in_wrapper'))
NATIVE_HANDLER_STATES = frozenset(('not_observed', 'captured', 'unavailable'))
SNAPSHOT_STATES = frozenset(('not_attempted', 'captured', 'unavailable'))


def validate_drag_diagnostics(value):
    if type(value) is not dict or set(value) != {'schema', 'observer', 'pre_drag', 'post_drag', 'events', 'native_handlers'}:
        raise ValueError('closed drag diagnostic schema required')
    if type(value['schema']) is not int or value['schema'] != 2 or type(value['observer']) is not str or value['observer'] not in SNAPSHOT_STATES:
        raise ValueError('closed drag observation status required')
    for key in ('pre_drag', 'post_drag'):
        phase = value[key]
        if type(phase) is not dict or set(phase) != DRAG_FLAGS | {'snapshot', 'components'}:
            raise ValueError('closed drag phase inventory required')
        if type(phase['snapshot']) is not str or phase['snapshot'] not in SNAPSHOT_STATES or any(type(phase[key]) is not bool for key in DRAG_FLAGS):
            raise ValueError('read-only drag phase booleans required')
        components = phase['components']
        if type(components) is not dict or set(components) != COMPONENT_COUNTS:
            raise ValueError('closed DOM component inventory required')
        if any(type(item) is not int or not 0 <= item <= 32 for item in components.values()):
            raise ValueError('bounded DOM component counters required')
    events = value['events']
    if type(events) is not dict or set(events) != DRAG_COUNTS:
        raise ValueError('closed trusted drag event inventory required')
    if any(type(item) is not int or not 0 <= item <= 32 for item in events.values()):
        raise ValueError('bounded trusted drag counters required')

    handlers = value['native_handlers']
    if type(handlers) is not dict or set(handlers) != {'dragover', 'drop'}:
        raise ValueError('closed native handler inventory required')
    for kind in ('dragover', 'drop'):
        sample = handlers[kind]
        flags = NATIVE_HANDLER_FLAGS | ({'source_dragend_seen'} if kind == 'drop' else set())
        if type(sample) is not dict or set(sample) != flags | {'count', 'observation'}:
            raise ValueError('closed native handler sample required')
        if type(sample['count']) is not int or not 0 <= sample['count'] <= 32:
            raise ValueError('bounded native handler count required')
        status = sample['observation']
        if type(status) is not str or status not in NATIVE_HANDLER_STATES:
            raise ValueError('closed native handler observation status required')
        if status == 'captured':
            if sample['count'] == 0 or any(type(sample[key]) is not bool for key in flags):
                raise ValueError('observed native handler booleans required')
        elif any(sample[key] is not None for key in flags):
            raise ValueError('unobserved native handler fields must be null')
        if status == 'not_observed' and sample['count'] != 0:
            raise ValueError('unobserved native handler count must be zero')


def read_browser_receipt(path):
    if path.stat().st_size > 4096:
        raise ValueError('browser receipt bound')
    receipt = json.loads(path.read_text())
    if 'startup_diagnostics' in receipt:
        validate_startup_diagnostics(receipt['startup_diagnostics'])
    if 'drag_diagnostics' in receipt:
        validate_drag_diagnostics(receipt['drag_diagnostics'])
    return receipt


def check_font_source_contract(source):
    contract = PINS['font_plugin_contract']
    if contract['silex_commit'] != PINS['silex']['commit']:
        raise ValueError('font source contract revision mismatch')
    for relative, expected in contract['files_sha256'].items():
        if hashlib.sha256((source / relative).read_bytes()).hexdigest() != expected:
            raise ValueError('pinned font dependency contract changed')
    client = (FIXTURE / 'client-config.js').read_text()
    if "config.fontsApiKey = '" + contract['synthetic_token'] + "';" not in client:
        raise ValueError('synthetic fixture token contract changed')
    for key in ('fontsServerUrl', 'fontsApiUrl'):
        if "config." + key + " = 'http://127.0.0.1:6805/disabled-fonts';" not in client:
            raise ValueError('loopback-only font service boundary changed')


class OperationFailure(Exception):
    def __init__(self, operation, exit_code, classification):
        if operation not in OPERATIONS or classification not in FAILURES:
            raise ValueError('closed operation diagnostic required')
        if exit_code is not None and type(exit_code) is not int:
            raise ValueError('numeric exit status required')
        self.operation, self.exit_code, self.classification = operation, exit_code, classification
        super().__init__(operation + ':' + classification)

    def receipt(self):
        return {'operation': self.operation, 'exit_code': self.exit_code,
                'classification': self.classification}


def revision(path):
    return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()


def download(url, output, maximum):
    if not url.startswith(('https://nodejs.org/dist/', 'https://registry.npmjs.org/pnpm/-/')):
        raise ValueError('download origin')
    with urllib.request.urlopen(url, timeout=60) as response, output.open('xb') as target:
        if response.geturl() != url:
            raise ValueError('unexpected redirect')
        total = 0
        while data := response.read(65536):
            total += len(data)
            if total > maximum:
                raise ValueError('download bound')
            target.write(data)


def prepare(temporary):
    node_archive = temporary / 'node.tar.xz'
    pin = PINS['node']
    download(pin['url'], node_archive, pin['bytes'])
    if node_archive.stat().st_size != pin['bytes'] or hashlib.sha256(node_archive.read_bytes()).hexdigest() != pin['sha256']:
        raise ValueError('node archive integrity')
    node_root = temporary / 'node'
    node_root.mkdir(mode=0o700)
    with tarfile.open(node_archive, 'r:xz') as bundle:
        for name, expected in pin['files'].items():
            entry = bundle.getmember('node-v' + pin['version'] + '-linux-x64/' + name)
            if not entry.isfile() or entry.size != expected['bytes']:
                raise ValueError('node member')
            with bundle.extractfile(entry) as source:
                data = source.read(expected['bytes'] + 1)
            if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise ValueError('node member integrity')
            destination = node_root / Path(name).name
            destination.write_bytes(data)
            destination.chmod(0o700 if name == 'bin/node' else 0o600)
    pnpm_archive = temporary / 'pnpm.tgz'
    pin = PINS['pnpm']
    download(pin['url'], pnpm_archive, pin['maximum_download_bytes'])
    actual = 'sha512-' + base64.b64encode(hashlib.sha512(pnpm_archive.read_bytes()).digest()).decode()
    if actual != pin['integrity']:
        raise ValueError('pnpm archive integrity')
    pnpm_root = temporary / 'pnpm'
    pnpm_root.mkdir(mode=0o700)
    with tarfile.open(pnpm_archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if len(members) > 4096 or sum(entry.size for entry in members) > 64 * 1024 * 1024:
            raise ValueError('pnpm extraction bound')
        for entry in members:
            parts = entry.name.rstrip('/').split('/')
            if (parts[0] != 'package' or any(part in ('', '.', '..') for part in parts)
                    or '\\' in entry.name or not (entry.isfile() or entry.isdir())):
                raise ValueError('pnpm archive member')
            output = pnpm_root.joinpath(*parts)
            if entry.isdir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(entry) as source, output.open('xb') as target:
                    shutil.copyfileobj(source, target, 65536)
    return node_root / 'node', pnpm_root / 'package/bin/pnpm.cjs'


def run(command, temporary, env, label, timeout=600, cwd=None):
    # Do not stream dependency/project logs or credentials into public CI output.
    if label not in OPERATIONS:
        raise ValueError('unknown operation')
    path = temporary / (label + '.log')
    with path.open('xb') as output:
        try:
            process, identity = start_group(list(map(str, command)), cwd=cwd, env=env,
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError:
            raise OperationFailure(label, None, 'spawn_failed') from None
        except GroupCaptureFailure as error:
            raise OperationFailure(label, error.exit_code, 'cleanup_failed') from None
        deadline = time.monotonic() + timeout
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        written = 0
        failure = None
        try:
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise TimeoutError('bounded child execution')
                for key, _events in selector.select(timeout=0.1):
                    data = os.read(key.fd, 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    written += len(data)
                    if written > 16 * 1024 * 1024:
                        raise OperationFailure(label, None, 'output_limit_exceeded')
                    output.write(data)
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
            if process.returncode:
                raise OperationFailure(label, process.returncode,
                    'signal_terminated' if process.returncode < 0 else 'exit_nonzero')
        except (TimeoutError, subprocess.TimeoutExpired):
            failure = OperationFailure(label, None, 'deadline_exceeded')
        except InterruptedError:
            failure = OperationFailure(label, None, 'cancelled')
        except OperationFailure as error:
            failure = error
        finally:
            selector.close()
            # Also covers cancellation while pnpm/webpack/Cargo has descendants.
            try:
                drain_group(process, identity)
            except (OSError, TimeoutError):
                failure = OperationFailure(label, process.poll(), 'cleanup_failed')
            finally:
                process.stdout.close()
        if failure is not None:
            if failure.exit_code is None:
                failure.exit_code = process.returncode
            raise failure from None
    return path


def main():
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('RUNNER_OS') != 'Linux' or os.environ.get('RUNNER_ARCH') != 'X64'):
        raise RuntimeError('approved disposable GitHub Linux X64 runner required')
    core, source, receipt_path = map(Path, sys.argv[1:])
    studio = FIXTURE.parents[1]
    refs = {key: os.environ[key] for key in ('STUDIO_CORE_REVISION', 'STUDIO_REVISION')}
    if (any(not re.fullmatch('[0-9a-f]{40}', value) for value in refs.values())
            or revision(core) != refs['STUDIO_CORE_REVISION'] or revision(studio) != refs['STUDIO_REVISION']
            or revision(source) != PINS['silex']['commit']
            or hashlib.sha256((source / 'pnpm-lock.yaml').read_bytes()).hexdigest() != PINS['silex']['lock_sha256']):
        raise ValueError('exact source binding')
    check_font_source_contract(source)
    receipt = dict(schema=2, status='failed', stage='prepare', **refs,
                   silex_revision=PINS['silex']['commit'], network_published=False,
                   full_studio_acceptance=False, synthetic_only=True)
    temporary = Path(tempfile.mkdtemp(prefix='studio-export-', dir=os.environ['RUNNER_TEMP']))
    # Give SIGTERM the same finally/cleanup behavior as normal failure.
    def cancel(_signum, _frame):
        raise InterruptedError('cancelled')
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        node, pnpm = prepare(temporary)
        # Generated output and dependency installation belong entirely to the
        # trial's private temporary tree, including on timeout/cancellation.
        runtime_source = temporary / 'silex'
        runtime_fixture = temporary / 'fixture'
        shutil.copytree(source, runtime_source, symlinks=True,
                        ignore=shutil.ignore_patterns('.git', 'node_modules', 'dist'))
        shutil.copytree(FIXTURE, runtime_fixture,
                        ignore=shutil.ignore_patterns('__pycache__', 'node_modules'))
        chrome = shutil.which('google-chrome')
        if chrome is None:
            raise RuntimeError('preinstalled hosted Google Chrome unavailable; no download fallback')
        # Wrapper path and real browser binary identity are both recorded.
        chrome_binary = Path('/opt/google/chrome/chrome')
        if not chrome_binary.is_file() or chrome_binary.is_symlink():
            raise RuntimeError('expected hosted Chrome binary unavailable')
        receipt['browser'] = {'launcher': str(Path(chrome).resolve()),
            'binary': str(chrome_binary), 'sha256': hashlib.sha256(chrome_binary.read_bytes()).hexdigest(),
            'version': subprocess.check_output([chrome, '--version'], text=True, timeout=10).strip()[:128]}
        # Never pass Actions service tokens, signing keys or unrelated job env to
        # upstream builds, editor, browser, dependency manager or Core CLI.
        env = {key: os.environ[key] for key in (
            'PATH', 'HOME', 'LANG', 'LC_ALL', 'RUNNER_TEMP', 'GITHUB_ACTIONS',
            'RUNNER_ENVIRONMENT', 'RUNNER_OS', 'RUNNER_ARCH', 'CARGO_HOME', 'RUSTUP_HOME')
            if key in os.environ}
        env.update(PATH=str(node.parent) + os.pathsep + os.environ['PATH'],
                   STUDIO_NODE=str(node), STUDIO_CHROME=chrome,
                   STUDIO_SILEX_SOURCE=str(runtime_source), STUDIO_FIXTURE_TEMP=str(temporary),
                   STUDIO_ZIP_OUTPUT=str(temporary / 'actual-export.zip'),
                   STUDIO_BROWSER_RECEIPT=str(temporary / 'browser.json'),
                   CI='true', HUSKY='0', DO_NOT_TRACK='1', PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1',
                   NPM_CONFIG_UPDATE_NOTIFIER='false', PNPM_DISABLE_SELF_UPDATE_CHECK='1',
                   COREPACK_ENABLE_NETWORK='0')
        receipt['stage'] = 'frozen_install'
        options = ['install', '--frozen-lockfile', '--ignore-scripts', '--store-dir', str(temporary / 'store'),
                   '--config.manage-package-manager-versions=false', '--config.update-notifier=false']
        run([node, pnpm, '--dir', runtime_source, '--filter', '@silexlabs/silex', *options], temporary, env, 'install-silex')
        run([node, pnpm, '--dir', runtime_fixture, *options], temporary, env, 'install-driver')
        receipt['stage'] = 'build_pinned_silex'
        for target in ('build:client', 'build:server', 'build:public'):
            run([node, pnpm, '--dir', runtime_source, 'run', target], temporary, env, target.replace(':', '-'))
        if hashlib.sha256((runtime_source / 'pnpm-lock.yaml').read_bytes()).hexdigest() != PINS['silex']['lock_sha256']:
            raise ValueError('upstream lock changed')
        receipt['stage'] = 'real_editor_export'
        # Only loopback exists; kernel PID namespace teardown kills descendants on
        # timeout/cancellation. The existing wrapper performs capability removal.
        env['VOLPAROSSA_TEST_ALLOW_SUDO_NETNS'] = '1'
        # Sudo env_reset intentionally remains enabled. The fixed private file
        # is located from runtime.py itself and read only after privilege drop.
        write_context(temporary / 'runtime-context.json', env)
        run([core / 'scripts/run-isolated-test.sh', '--studio-nonroot-command', '/usr/bin/python3',
             'studio_export', 'VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS', 'loopback', '-B', runtime_fixture / 'runtime.py'],
            temporary, env, 'runtime', timeout=125)
        receipt['browser_export'] = read_browser_receipt(temporary / 'browser.json')
        if receipt['browser_export']['status'] != 'passed':
            raise ValueError('browser receipt')
        receipt['runtime_cleanup'] = json.loads((temporary / 'runtime-cleanup.json').read_text())
        receipt['stage'] = 'bounded_actual_zip_extraction'
        extract(temporary / 'actual-export.zip', temporary / 'export', temporary / 'inventory.json')
        receipt['stage'] = 'build_actual_core_viewer_fixture'
        build_log = run(['cargo', 'test', '--locked', '--offline', '-p', 'volparossa', '--test',
                         'studio_site_pack', '--no-run', '--message-format=json'],
                        temporary, env, 'core-build', timeout=900, cwd=core)
        artifacts = []
        for line in build_log.read_text().splitlines():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (message.get('reason') == 'compiler-artifact'
                    and message.get('target', {}).get('name') == 'studio_site_pack'
                    and message.get('executable')):
                artifacts.append(Path(message['executable']))
        if (len(artifacts) != 1 or artifacts[0].parent != core.resolve() / 'target/debug/deps'
                or artifacts[0].is_symlink() or not artifacts[0].is_file()
                or not re.fullmatch(r'studio_site_pack-[0-9a-f]+', artifacts[0].name)):
            raise ValueError('exact actual Core compiler artifact required')
        descriptor = os.open(temporary / 'viewer-context.json',
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump({'schema': 1, 'executable': str(artifacts[0])}, output)
        receipt['stage'] = 'actual_core_pack_signed_local_viewer_and_independent_browser'
        run([core / 'scripts/run-isolated-test.sh', '--studio-nonroot-command', '/usr/bin/python3',
             'studio_export', 'VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS', 'loopback', '-B', runtime_fixture / 'viewer_runtime.py'],
            temporary, env, 'viewer-runtime', timeout=100)
        log = temporary / 'viewer-core.log'
        if log.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('bounded viewer proof log required')
        proofs = [json.loads(line.removeprefix('STUDIO_SITE_PACK_PROOF '))
                  for line in log.read_text().splitlines() if line.startswith('STUDIO_SITE_PACK_PROOF ')]
        if len(proofs) != 1:
            raise ValueError('single Core proof required')
        validate_viewer_proof(proofs[0])
        receipt['core_pack'] = proofs[0]
        receipt['viewer_cleanup'] = read_viewer_cleanup(temporary / 'viewer-cleanup.json')
        receipt['status'], receipt['stage'] = 'passed', 'complete'
    except Exception as error:
        receipt['error_type'] = type(error).__name__
        if isinstance(error, OperationFailure):
            receipt['operation_failure'] = error.receipt()
        # Only a closed synthetic diagnostic survives. Never upload raw server,
        # browser, Cargo, project files, download URLs or environment dumps.
        browser_receipt = temporary / 'browser.json'
        if browser_receipt.is_file() and browser_receipt.stat().st_size <= 4096:
            receipt['browser_export'] = read_browser_receipt(browser_receipt)
        raise
    finally:
        try:
            viewer_cleanup = temporary / 'viewer-cleanup.json'
            if viewer_cleanup.is_file() and viewer_cleanup.stat().st_size <= 4096:
                receipt['viewer_cleanup'] = read_viewer_cleanup(viewer_cleanup, require_success=False)
            cleanup = temporary / 'runtime-cleanup.json'
            if cleanup.is_file() and cleanup.stat().st_size <= 4096:
                receipt['runtime_cleanup'] = json.loads(cleanup.read_text())
        except Exception as error:
            receipt.update(status='failed', stage='cleanup_receipt', cleanup_error_type=type(error).__name__)
            raise
        finally:
            try:
                shutil.rmtree(temporary)
            except OSError as error:
                receipt.update(status='failed', stage='cleanup', cleanup_error_type=type(error).__name__)
                raise
            finally:
                receipt['temporary_outputs_removed'] = not temporary.exists()
                with receipt_path.open('x') as output:
                    json.dump(receipt, output, sort_keys=True)
                    output.write('\n')



if __name__ == '__main__':
    main()
