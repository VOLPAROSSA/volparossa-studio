# SPDX-License-Identifier: GPL-3.0-only
"""Hosted loopback-only runtime. Called through Core's reviewed namespace wrapper."""
import json
import os
from pathlib import Path
import signal
import resource
import subprocess
import sys
import time
import urllib.request

from lifecycle import drain_group, start_group
from runtime_context import read_context, restored_environment


def main():
    parent = os.environ['VOLPAROSSA_HANDOFF_TEST_PARENT_NETNS']
    if os.readlink('/proc/self/ns/net') == parent:
        raise RuntimeError('parent network namespace')
    if os.getuid() == 0 or os.geteuid() == 0:
        raise RuntimeError('sandboxed browser requires the original nonroot runner UID')
    # Namespace wrapper drops every capability before executing this process.
    status = Path('/proc/self/status').read_text().splitlines()
    caps = [line for line in status if line.startswith(('CapInh:', 'CapPrm:', 'CapEff:', 'CapBnd:', 'CapAmb:'))]
    if len(caps) != 5 or any(int(line.split()[1], 16) != 0 for line in caps):
        raise RuntimeError('capabilities retained')
    if [line.split()[1] for line in status if line.startswith('NoNewPrivs:')] != ['1']:
        raise RuntimeError('no-new-privileges boundary missing')
    fixture = Path(__file__).resolve().parent
    # Everything above is checked before opening the private handoff. It is
    # located from the fixed script argv, independent of sudo env_reset.
    values = read_context(fixture.parent / 'runtime-context.json')
    source = Path(values['STUDIO_SILEX_SOURCE'])
    temporary = Path(values['STUDIO_FIXTURE_TEMP'])
    # Includes downloaded ZIPs and browser/server logs. All browser temporary
    # files live under TMPDIR below, on the same private filesystem.
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    env = dict(restored_environment(values), SILEX_SERVER_CONFIG=str(fixture / 'fixture-config.cjs'),
               SILEX_CLIENT_CONFIG=str(fixture / 'client-config.js'),
               SILEX_URL='http://127.0.0.1:6805', SILEX_PORT='6805',
               SILEX_HOST='127.0.0.1', SILEX_PROTOCOL='http', SILEX_DEBUG='false',
               SILEX_SESSION_SECRET='synthetic-disposable-export-fixture-only',
               SILEX_EXPRESS_JSON_LIMIT='4mb', SILEX_EXPRESS_TEXT_LIMIT='4mb',
               TMPDIR=str(temporary / 'tmp'))
    Path(env['TMPDIR']).mkdir(mode=0o700)
    server = None
    browser = None
    server_identity = None
    browser_identity = None
    def cancel(signum, _frame):
        raise InterruptedError('cancelled')
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        # Private bounded files are removed by the outer finally; no project/log upload.
        with (temporary / 'server.log').open('xb') as log:
            server, server_identity = start_group([env['STUDIO_NODE'], str(source / 'dist/server/server')],
                                                  cwd=source, env=env, stdout=log, stderr=log)
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('server exited before readiness')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:6805/', timeout=0.3) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise TimeoutError('server readiness')
            with (temporary / 'browser.log').open('xb') as browser_log:
                browser, browser_identity = start_group([env['STUDIO_NODE'], str(fixture / 'browser-export.mjs')],
                                                         env=env, stdout=browser_log, stderr=browser_log)
                if browser.wait(timeout=85) != 0:
                    raise RuntimeError('browser driver failed')
            if any(path.stat().st_size > 4 * 1024 * 1024 for path in temporary.glob('*.log')):
                raise RuntimeError('log bound')
    finally:
        cleanup = {'server_joined': False, 'server_group_drained': False,
                   'browser_driver_group_drained': False, 'isolated_network_namespace': True,
                   'capabilities_dropped': True, 'nonroot_runner_uid': True}
        failed = False
        for label, process, identity in (('browser_driver', browser, browser_identity),
                                         ('server', server, server_identity)):
            if process is None:
                continue
            try:
                observed = drain_group(process, identity)
                cleanup[label + '_group_drained'] = observed['live_group_drained']
                if label == 'server':
                    cleanup['server_joined'] = observed['leader_joined']
            except (OSError, TimeoutError):
                failed = True
        # Chrome may start a separate session; the PID namespace destruction is
        # the additional boundary for all orphaned browser descendants.
        cleanup['cleanup_failed'] = failed
        (temporary / 'runtime-cleanup.json').write_text(json.dumps(cleanup) + '\n')
        if failed:
            raise RuntimeError('runtime process group cleanup failed')


if __name__ == '__main__':
    main()
