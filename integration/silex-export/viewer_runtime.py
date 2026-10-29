# SPDX-License-Identifier: GPL-3.0-only
"""Actual Core test + viewer + fresh browser in the existing disposable boundary."""
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat

from lifecycle import drain_group, start_group
from runtime_context import read_context, restored_environment
from signed_site_profile import MODE as SIGNED_SITE_MODE, TEST as SIGNED_SITE_TEST, read_core_context


def read_viewer_context(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as source:
        metadata = os.fstat(source.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_nlink != 1
                or metadata.st_size > 16384):
            raise ValueError('private viewer context required')
        data = source.read(16385)
    if len(data) > 16384:
        raise ValueError('viewer context size bound')
    values = json.loads(data)
    if type(values) is not dict or set(values) != {'schema', 'executable'} or type(values['schema']) is not int or values['schema'] != 1 or type(values['executable']) is not str:
        raise ValueError('closed viewer context required')
    executable = Path(values['executable'])
    if (not executable.is_absolute() or executable.parent.parts[-3:] != ('target', 'debug', 'deps')
            or not re.fullmatch(r'studio_site_pack-[0-9a-f]+', executable.name)
            or executable.is_symlink() or not executable.is_file()):
        raise ValueError('actual Core test executable boundary')
    return executable


def main():
    parent = os.environ['VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS']
    if os.readlink('/proc/self/ns/net') == parent or os.getuid() == 0 or os.geteuid() == 0:
        raise RuntimeError('isolated nonroot viewer required')
    status = Path('/proc/self/status').read_text().splitlines()
    caps = [line for line in status if line.startswith(('CapInh:', 'CapPrm:', 'CapEff:', 'CapBnd:', 'CapAmb:'))]
    if len(caps) != 5 or any(int(line.split()[1], 16) for line in caps):
        raise RuntimeError('capabilities retained')
    if [line.split()[1] for line in status if line.startswith('NoNewPrivs:')] != ['1']:
        raise RuntimeError('no-new-privileges boundary missing')
    fixture = Path(__file__).resolve().parent
    temporary = fixture.parent
    values = read_context(temporary / 'runtime-context.json')
    context = read_core_context(temporary / 'viewer-context.json')
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    env = dict(restored_environment(values), TMPDIR=str(temporary / 'tmp'),
        STUDIO_VIEWER_OBSERVER=str(fixture / 'browser-viewer.mjs'),
        VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS=parent,
        VOLPAROSSA_STUDIO_EXPORT_DIRECTORY=str(temporary / 'export'),
        VOLPAROSSA_STUDIO_EXPORT_INVENTORY=str(temporary / 'inventory.json'))
    if context.mode == SIGNED_SITE_MODE:
        env.update(VOLPAROSSA_REQUIRE_STUDIO_SIGNED_SITE_PROOF='1',
                   GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted')
    def cancel(_signum, _frame):
        raise InterruptedError('cancelled')
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    run_core_fixture(context.executable, temporary, env, signed=context.mode == SIGNED_SITE_MODE)


def run_core_fixture(executable, temporary, env, *, signed=False):
    """Only called after boundary validation; owns the complete Core child group."""
    process = identity = None
    cleanup = {'core_group_drained': False, 'core_joined': False,
        'isolated_network_namespace': True, 'capabilities_dropped': True,
        'nonroot_runner_uid': True, 'cleanup_failed': True}
    try:
        name = 'signed-site-core.log' if signed else 'viewer-core.log'
        with (temporary / name).open('xb') as log:
            if signed:
                os.fchmod(log.fileno(), 0o600)
            arguments = [str(executable),
                SIGNED_SITE_TEST if signed else 'actual_silex_export_packs_and_decodes_without_publication',
                '--ignored', '--exact', '--nocapture']
            if signed:
                arguments.append('--test-threads=1')
            process, identity = start_group(arguments, env=env, stdout=log, stderr=log)
            if process.wait(timeout=80) != 0:
                raise RuntimeError('actual Core viewer proof failed')
    finally:
        try:
            if process is not None:
                observed = drain_group(process, identity)
                cleanup.update(core_group_drained=observed['live_group_drained'],
                    core_joined=observed['leader_joined'],
                    cleanup_failed=not (observed['live_group_drained'] and observed['leader_joined']))
                if cleanup['cleanup_failed']:
                    raise RuntimeError('Core process group cleanup incomplete')
        finally:
            (temporary / 'viewer-cleanup.json').write_text(json.dumps(cleanup) + '\n')


if __name__ == '__main__':
    main()
