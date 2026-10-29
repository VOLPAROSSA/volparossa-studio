# SPDX-License-Identifier: GPL-3.0-only
"""Fixed hosted Core build/invocation after the real editor's fresh ZIP export."""
from pathlib import Path
import re

from signed_site_profile import TARGET, strict_json, write_signed_context
from signed_site_receipt import read_signed_proof
from viewer_receipt import read_viewer_cleanup


def compiler_artifact(log, core):
    if log.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('bounded compiler-artifact log required')
    artifacts = []
    for line in log.read_text().splitlines():
        try:
            value = strict_json(line)
        except ValueError:
            continue
        if (type(value) is dict and value.get('reason') == 'compiler-artifact'
                and type(value.get('target')) is dict
                and value['target'].get('name') == TARGET
                and value['target'].get('kind') == ['test']
                and value.get('executable') is not None):
            if type(value['executable']) is not str:
                raise ValueError('compiler executable must be a path')
            artifacts.append(Path(value['executable']))
    if (len(artifacts) != 1 or artifacts[0].parent != core.resolve() / 'target/debug/deps'
            or not re.fullmatch(TARGET + r'-[0-9a-f]+', artifacts[0].name)):
        raise ValueError('one exact signed-site compiler artifact required')
    return artifacts[0]


def execute(core, temporary, runtime_fixture, env, receipt, run):
    # The agent integration target supplies CARGO_BIN_EXE_volparossa-agent; the
    # CLI is a separate package and must be built explicitly at its fixed path.
    receipt['stage'] = 'build_actual_signed_site_fixture'
    run(['cargo', 'build', '--locked', '--offline', '-p', 'volparossa', '--bin', 'volparossa'],
        temporary, env, 'core-cli-build', timeout=900, cwd=core)
    log = run(['cargo', 'test', '--locked', '--offline', '-p', 'volparossa-agent', '--test',
               TARGET, '--no-run', '--message-format=json'],
              temporary, env, 'core-build', timeout=900, cwd=core)
    binary = compiler_artifact(log, core)
    write_signed_context(temporary / 'viewer-context.json', core, binary)
    receipt['stage'] = 'actual_signed_site_recovery_preview_and_independent_browser'
    run([core / 'scripts/run-isolated-test.sh', '--studio-nonroot-command', '/usr/bin/python3',
         'studio_export', 'VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS', 'loopback', '-B', runtime_fixture / 'viewer_runtime.py'],
        temporary, env, 'viewer-runtime', timeout=100)
    inventory = strict_json((temporary / 'inventory.json').read_bytes())
    if (type(inventory) is not dict or set(inventory) != {'schema', 'assets'}
            or type(inventory['schema']) is not int or inventory['schema'] != 1
            or type(inventory['assets']) is not list):
        raise ValueError('fresh actual ZIP inventory required')
    receipt['signed_site_recovery'] = read_signed_proof(temporary / 'signed-site-core.log', len(inventory['assets']))
    receipt['viewer_cleanup'] = read_viewer_cleanup(temporary / 'viewer-cleanup.json')
