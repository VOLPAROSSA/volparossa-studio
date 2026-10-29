# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only unit controls; no inventoried tool is executed by these tests."""
import importlib.util
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location('runtime_inventory', Path(__file__).with_name('inventory.py'))
INVENTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INVENTORY)


def archive(name, version='2'):
    return (f'Package: {name}\nVersion: {version}\nArchitecture: amd64\n'
            f'Filename: pool/main/x/{name}/{name}_{version}_amd64.deb\n'
            'Size: 128\nSHA256: ' + 'a' * 64 + '\n').encode()


class MetadataCommands:
    def __init__(self, missing=()):
        self.missing = missing
        self.calls = []

    def run(self, arguments, accepted=(0,), *, diagnostic=None):
        self.calls.append(arguments)
        if arguments[:2] == ['/usr/bin/dpkg-query', '-W']:
            return 0, ''.join(f'{n}\t1\tamd64\tinstall ok installed\n'
                              for n in INVENTORY.PROVIDERS if n not in self.missing).encode()
        if arguments[:2] == ['/usr/bin/apt-cache', 'policy']:
            return 0, b'  Installed: 1\n  Candidate: 2\n'
        if arguments[:2] == ['/usr/bin/apt-cache', 'show']:
            return 0, archive(*arguments[-1].split('='))
        if arguments[:2] == ['/usr/bin/dpkg-query', '-S']:
            alias = arguments[-1]
            provider = next(provider for provider, aliases in INVENTORY.TOOLS.values() if alias in aliases)
            return 0, f'{provider}: {alias}\n'.encode()
        if arguments[0] == '/usr/bin/apt-get':
            raw = ''.join(f'Inst {n} (2 Ubuntu:24.04/noble [amd64])\n' for n in self.missing).encode()
            if diagnostic is not None:
                diagnostic.update(phase='actor', exit_class='normal', exit_code=0,
                    stdout_bytes=len(raw), stderr_bytes=0, output_limit_exceeded=False,
                    cumulative_limit_exceeded=False, parser_failure='not_run', **INVENTORY.simulation_shape(raw))
            return 0, raw
        raise AssertionError('unexpected metadata command')


def collect_fixture(missing=()):
    report = dict(packages={}, tools={}, installation_plan={}, simulation_performed=False,
                  installation_plan_sha256=None)
    commands = MetadataCommands(missing)
    def binary(aliases):
        return dict(path=aliases[0], sha256='b' * 64, bytes=256, owner=0,
                    group=0, mode=0o755, links=1), [aliases[0]]
    with patch.object(INVENTORY.Path, 'glob', return_value=[Path('/var/lib/apt/lists/public_InRelease')]), \
            patch.object(INVENTORY, 'read_file', return_value=(
                b'-----BEGIN PGP SIGNED MESSAGE-----\npublic\n-----BEGIN PGP SIGNATURE-----\n', None)), \
            patch.object(INVENTORY, 'binary_record', side_effect=binary):
        INVENTORY.collect(commands, report)
    return commands, report


class InventoryTests(unittest.TestCase):
    def test_simulation_failure_projects_only_bounded_shape_and_first_closed_predicate(self):
        secret = 'DO-NOT-PERSIST-private-origin-https://private.invalid/token'
        raw = ('Inst private-fixture:amd64 (2 ' + secret + ')\n').encode()
        diagnostic = {}
        with self.assertRaises(INVENTORY.Rejected):
            INVENTORY.simulation_rows(raw, ['xdotool'], diagnostic=diagnostic)
        self.assertEqual(diagnostic['phase'], 'parser')
        self.assertEqual(diagnostic['parser_failure'], 'inst_shape')
        self.assertEqual(diagnostic['failure_line_class'], 'inst')
        self.assertEqual(diagnostic['failure_line'], 0)
        self.assertIs(diagnostic['failure_inst_native_arch'], True)
        self.assertIs(diagnostic['failure_has_version_parenthesis'], True)
        self.assertIs(diagnostic['failure_closing_parenthesis'], True)
        self.assertEqual(diagnostic['inst_shape_matches'], 0)
        self.assertEqual(diagnostic['inst_shape_mismatches'], 1)
        self.assertEqual(diagnostic['native_arch_qualified_inst'], 1)
        INVENTORY.check_simulation_diagnostic(diagnostic)
        for private in ('private-fixture', secret, 'https://', 'token'):
            self.assertNotIn(private, json.dumps(diagnostic))
        original = dict(diagnostic)
        INVENTORY.simulation_failure(diagnostic, 'removal', 9999, 'Remv private')
        self.assertEqual(diagnostic, original)
        for value, predicate in ((b'Remv public [1]\n', 'removal'),
                (b'Inst public (2 Ubuntu [amd64])\n' * 2, 'duplicate'),
                (b'no requested install\n', 'missing_membership'), (b'\xff', 'encoding')):
            diagnostic = {}
            with self.assertRaises((INVENTORY.Rejected, UnicodeError)):
                INVENTORY.simulation_rows(value, ['xdotool'], diagnostic=diagnostic)
            self.assertEqual(diagnostic['parser_failure'], predicate)
            INVENTORY.check_simulation_diagnostic(diagnostic)
        shape = INVENTORY.simulation_shape(b'Inst public malformed\n' * 1025)
        self.assertEqual(shape['nonempty_lines'], 1024)
        self.assertEqual(shape['inst_lines'], 256)
        self.assertIs(shape['lines_clipped'], True)
        self.assertIs(shape['inst_lines_clipped'], True)
        self.assertEqual(shape['inst_shape_mismatches'], 256)
        commands, report = collect_fixture(('nftables',))
        self.assertEqual(report['simulation_diagnostic']['phase'], 'complete')
        self.assertEqual(report['simulation_diagnostic']['parser_failure'], 'none')
        self.assertEqual(report['simulation_diagnostic']['requested_covered_count'], 1)
        INVENTORY.check_simulation_diagnostic(report['simulation_diagnostic'])
        for bad in ({'stdout': secret}, {'error': secret}, {'path': secret}, {'environment': {}},
                    {'exit_code': True}, {'exit_code': 256}, {'failure_line': 1025},
                    {'stdout_bytes': INVENTORY.MAX_OUTPUT + 1}, {'parser_failure': secret}):
            with self.subTest(bad=bad), self.assertRaises(INVENTORY.Rejected):
                INVENTORY.check_simulation_diagnostic(bad)

    def test_simulation_exit_100_is_observed_before_unchanged_exit_guard_and_cleanup_preserves_rejection(self):
        stdout, stderr = MagicMock(), MagicMock()
        stdout.fileno.return_value, stderr.fileno.return_value = 10, 11
        child = SimpleNamespace(pid=123456, stdout=stdout, stderr=stderr, wait=MagicMock())
        selector = MagicMock()
        selector.get_map.side_effect = [{10: True, 11: True}, {}]
        out = b'Reading package lists...\n'
        err = b'DO-NOT-PERSIST-private-path-environment-or-APT-error\n'
        selector.select.return_value = [(SimpleNamespace(fd=10, fileobj=stdout), None),
            (SimpleNamespace(fd=10, fileobj=stdout), None),
            (SimpleNamespace(fd=11, fileobj=stderr), None),
            (SimpleNamespace(fd=11, fileobj=stderr), None)]
        diagnostic = {}
        with patch.object(INVENTORY.subprocess, 'Popen', return_value=child), \
                patch.object(INVENTORY.selectors, 'DefaultSelector', return_value=selector), \
                patch.object(INVENTORY.os, 'set_blocking'), \
                patch.object(INVENTORY.os, 'read', side_effect=[out, b'', err, b'']), \
                patch.object(INVENTORY.os, 'waitid', return_value=SimpleNamespace(
                    si_code=INVENTORY.os.CLD_EXITED, si_status=100)), \
                patch.object(INVENTORY.os, 'killpg'), patch.object(INVENTORY, 'group_live', return_value=False), \
                patch.object(INVENTORY.signal, 'pthread_sigmask', return_value=set()), \
                patch.object(INVENTORY.signal, 'sigpending', return_value=set()):
            commands = INVENTORY.Commands()
            with self.assertRaises(INVENTORY.Rejected):
                commands.run(['/usr/bin/apt-get', '--simulate', '--no-remove', '--no-download',
                    '--no-install-recommends', 'install', 'xdotool=2'], diagnostic=diagnostic)
        self.assertEqual(diagnostic['exit_class'], 'normal')
        self.assertEqual(diagnostic['exit_code'], 100)
        self.assertEqual(diagnostic['phase'], 'actor')
        self.assertEqual(diagnostic['parser_failure'], 'not_run')
        self.assertEqual(diagnostic['stdout_bytes'], len(out))
        self.assertEqual(diagnostic['stderr_bytes'], len(err))
        self.assertEqual(diagnostic['inst_lines'], 0)
        self.assertEqual(commands.started, 1)
        self.assertEqual(commands.joined, 1)
        INVENTORY.check_simulation_diagnostic(diagnostic)
        self.assertNotIn('DO-NOT-PERSIST', json.dumps(diagnostic))
        child.wait.assert_called_once()
        stdout.close.assert_called_once()
        stderr.close.assert_called_once()
        selector.close.assert_called_once()

    def test_fixed_providers_and_tools(self):
        self.assertEqual(INVENTORY.PROVIDERS, ('dbus-daemon', 'util-linux', 'mount', 'iproute2',
                         'nftables', 'xvfb', 'xauth', 'xdotool', 'bubblewrap'))
        self.assertEqual(set(INVENTORY.TOOLS), {'dbus-daemon', 'unshare', 'setpriv', 'mount',
                         'ip', 'nft', 'Xvfb', 'xauth', 'xdotool', 'bwrap'})
        self.assertEqual(set(p for p, _ in INVENTORY.TOOLS.values()), set(INVENTORY.PROVIDERS))

    def test_installed_and_absent_are_separate(self):
        rows = INVENTORY.installed_rows(b'mount\t2.39\tamd64\tinstall ok installed\n'
                                       b'xdotool\t\t\tunknown ok not-installed\n')
        self.assertEqual(rows['mount']['state'], 'installed')
        self.assertEqual(rows['xdotool'], dict(state='not_installed', version=None, architecture=None))
        for bad in (b'mount\t\t\tinstall ok installed\n', b'unknown\t1\tamd64\tinstall ok installed\n',
                    b'mount\t1\tamd64\tinstall ok installed\n' * 2,
                    b'mount\t1\tamd64\tinstall reinstreq half-installed\n'):
            with self.subTest(bad=bad), self.assertRaises(INVENTORY.Rejected):
                INVENTORY.installed_rows(bad)

    def test_candidate_missing_duplicate_and_malformed(self):
        self.assertEqual(INVENTORY.candidate_version(b'  Candidate: 2.39-1ubuntu8\n'), '2.39-1ubuntu8')
        self.assertIsNone(INVENTORY.candidate_version(b'  Candidate: (none)\n'))
        for bad in (b'', b'Candidate: 1\nCandidate: 2\n', b'Candidate: bad=override\n'):
            with self.subTest(bad=bad), self.assertRaises(INVENTORY.Rejected):
                INVENTORY.candidate_version(bad)

    def test_archive_binding_and_paths(self):
        row = INVENTORY.archive_record(archive('mount'), 'mount', '2')
        self.assertEqual(row['Version'], '2')
        for bad in (archive('mount', '1'), archive('nftables'), archive('mount') + b'SHA256: ' + b'a' * 64,
                    archive('mount').replace(b'pool/main/', b'pool/../'),
                    archive('mount').replace(b'Size: 128', b'Size: 9999999999'),
                    archive('mount').replace(b'Architecture: amd64', b'Architecture: arm64')):
            with self.subTest(bad=bad), self.assertRaises(INVENTORY.Rejected):
                INVENTORY.archive_record(bad, 'mount', '2')
        self.assertEqual(INVENTORY.archive_record(archive('mount') + b'\n' + archive('mount'), 'mount', '2'), row)

    def test_owner_binding_requires_exact_provider_and_alias(self):
        self.assertTrue(INVENTORY.owner_matches(b'mount: /bin/mount\n', 'mount', '/bin/mount'))
        self.assertTrue(INVENTORY.owner_matches(b'iproute2:amd64: /sbin/ip\n', 'iproute2', '/sbin/ip'))
        for raw in (b'', b'util-linux: /bin/mount\n', b'mount: /usr/bin/mount\n'):
            self.assertFalse(INVENTORY.owner_matches(raw, 'mount', '/bin/mount'))
        with self.assertRaises(INVENTORY.Rejected):
            INVENTORY.owner_matches(b'mount: /bin/mount\nmount: /usr/bin/mount\n', 'mount', '/bin/mount')

    def test_same_descriptor_read_bounds_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'file'
            path.write_bytes(b'public')
            path.chmod(0o600)
            self.assertEqual(INVENTORY.read_file(path, 6, os.geteuid())[0], b'public')
            with self.assertRaises(INVENTORY.Rejected):
                INVENTORY.read_file(path, 5, os.geteuid())
            alias = Path(directory) / 'alias'
            alias.symlink_to(path)
            with self.assertRaises(INVENTORY.Rejected):
                INVENTORY.read_file(alias, 6, os.geteuid())
            path.chmod(0o622)
            with self.assertRaises(INVENTORY.Rejected):
                INVENTORY.read_file(path, 6, os.geteuid())

    def test_read_rejects_mutation_without_publishing_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'file'
            path.write_bytes(b'public')
            path.chmod(0o600)
            first = path.stat()
            path.write_bytes(b'changed')
            second = path.stat()
            with patch.object(INVENTORY.os, 'fstat', side_effect=(first, second)), \
                    self.assertRaises(INVENTORY.Rejected):
                INVENTORY.read_file(path, 32, os.geteuid())

    def test_simulation_missing_membership_removal_and_duplicates(self):
        good = b'Inst mount (2 Ubuntu:24.04/noble [amd64])\n'
        self.assertEqual(INVENTORY.simulation_rows(good, ['mount']), {'mount': '2'})
        for raw in (b'', b'Remv mount [1]\n' + good, good * 2, b'Inst mount malformed\n'):
            with self.subTest(raw=raw), self.assertRaises(INVENTORY.Rejected):
                INVENTORY.simulation_rows(raw, ['mount'])

    def test_installed_metadata_is_not_newer_candidate_or_archive_verification(self):
        commands, report = collect_fixture()
        self.assertEqual(report['readiness'], 'ready')
        for row in report['packages'].values():
            self.assertEqual(row['installed_archive_metadata']['Version'], '1')
            self.assertEqual(row['candidate_archive_metadata']['Version'], '2')
            self.assertIs(row['archive_contents_verified'], False)
        self.assertFalse(report['simulation_performed'])
        self.assertTrue(all(c[0] in ('/usr/bin/apt-cache', '/usr/bin/dpkg-query') for c in commands.calls))

    def test_missing_provider_gets_simulation_but_not_ready(self):
        commands, report = collect_fixture(('nftables',))
        self.assertEqual(report['readiness'], 'not_ready')
        self.assertEqual(report['missing_providers'], ['nftables'])
        self.assertIsNone(report['packages']['nftables']['installed_archive_metadata'])
        self.assertIs(report['simulation_performed'], True)
        self.assertIn('nftables', report['installation_plan'])
        plan = next(c for c in commands.calls if c[0] == '/usr/bin/apt-get')
        self.assertEqual(plan, ['/usr/bin/apt-get', '--simulate', '--no-remove', '--no-download',
                               '--no-install-recommends', 'install', 'nftables=2'])

    def test_missing_installed_metadata_or_owner_cannot_be_ready(self):
        original = INVENTORY.metadata
        with patch.object(INVENTORY, 'metadata', side_effect=lambda c, n, v: None if n == 'mount' and v == '1' else original(c, n, v)):
            _, report = collect_fixture()
        self.assertEqual(report['readiness'], 'not_ready')
        with patch.object(INVENTORY, 'owner_matches', return_value=False):
            _, report = collect_fixture()
        self.assertEqual(report['readiness'], 'not_ready')
        with patch.object(INVENTORY, 'candidate_version', return_value=None):
            commands, report = collect_fixture(('nftables',))
        self.assertEqual(report['readiness'], 'not_ready')
        self.assertFalse(report['simulation_performed'])
        self.assertFalse(any(c[0] == '/usr/bin/apt-get' for c in commands.calls))

    def test_main_closed_failure_receipt_keeps_all_effects_false(self):
        class Commands:
            started = 1
            joined = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            def fail(_commands, report):
                report['stage'] = 'packages'
                raise RuntimeError('DO-NOT-PERSIST-private-path-or-environment')
            with patch.object(INVENTORY, 'Commands', return_value=Commands()), \
                    patch.object(INVENTORY, 'admission', return_value=('a' * 40, path)), \
                    patch.object(INVENTORY, 'collect', side_effect=fail), \
                    patch.object(INVENTORY.sys, 'argv', ['inventory.py']), \
                    patch('builtins.print'), self.assertRaises(INVENTORY.Rejected):
                INVENTORY.main()
            raw = path.read_bytes()
            self.assertNotIn(b'DO-NOT-PERSIST', raw)
            receipt = json.loads(raw)
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(receipt['readiness'], 'not_ready')
            self.assertIs(receipt['cleanup_confirmed'], True)
            self.assertTrue(all(receipt[k] is False for k in INVENTORY.EFFECTS))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_cancellation_during_drain_is_deferred_until_join_and_restore(self):
        for original_failure in (None, RuntimeError('original-primary')):
            for alarm in (False, True):
                with self.subTest(primary=original_failure is not None, alarm=alarm), ExitStack() as stack:
                    child = MagicMock(pid=123456)
                    selector = MagicMock()
                    selector.get_map.return_value = {}
                    selector.select.return_value = []
                    original_handler = object()
                    handlers = {}
                    restored = []
                    def change_handler(number, handler):
                        handlers[number] = handler
                        if handler is original_handler:
                            restored.append(number)
                    def interrupt(*_args, **_kwargs):
                        for number in (INVENTORY.signal.SIGINT, INVENTORY.signal.SIGTERM,
                                       INVENTORY.signal.SIGHUP) * 2:
                            handlers[number](number, None)
                        if alarm:
                            handlers[INVENTORY.signal.SIGALRM](INVENTORY.signal.SIGALRM, None)
                    for target, options in (
                        ('subprocess.Popen', dict(return_value=child)),
                        ('selectors.DefaultSelector', dict(return_value=selector)),
                        ('os.set_blocking', {}), ('os.killpg', dict(side_effect=interrupt)),
                        ('group_live', dict(return_value=False)),
                        ('signal.getsignal', dict(return_value=original_handler)),
                        ('signal.signal', dict(side_effect=change_handler)),
                        ('signal.pthread_sigmask', dict(return_value=set())),
                        ('signal.sigpending', dict(return_value=set())),
                    ):
                        owner, _, name = target.rpartition('.')
                        stack.enter_context(patch.object(getattr(INVENTORY, owner) if owner else INVENTORY, name, **options))
                    observed = SimpleNamespace(si_code=INVENTORY.os.CLD_EXITED, si_status=0)
                    stack.enter_context(patch.object(INVENTORY.os, 'waitid', **(
                        dict(side_effect=original_failure) if original_failure else dict(return_value=observed))))
                    child.wait.side_effect = interrupt
                    commands = INVENTORY.Commands()
                    with self.assertRaises(BaseException) as caught:
                        commands.run(['/usr/bin/apt-cache', 'policy', 'mount'])
                    if original_failure is not None:
                        self.assertIs(caught.exception, original_failure)
                    else:
                        self.assertIsInstance(caught.exception, INVENTORY.Rejected)
                        self.assertIn('deadline' if alarm else 'cancelled', str(caught.exception))
                    self.assertEqual(commands.started, 1)
                    self.assertEqual(commands.joined, 1)
                    self.assertEqual(set(restored), {INVENTORY.signal.SIGINT, INVENTORY.signal.SIGTERM,
                                                   INVENTORY.signal.SIGHUP, INVENTORY.signal.SIGALRM})
                    child.wait.assert_called_once()
                    child.stdout.close.assert_called_once()
                    child.stderr.close.assert_called_once()
                    selector.close.assert_called_once()

    def test_repeated_restore_phase_cancellation_attempts_all_restores_and_preserves_primary(self):
        for original_failure in (None, RuntimeError('original-primary')):
            with self.subTest(primary=original_failure is not None), ExitStack() as stack:
                child = MagicMock(pid=123456)
                selector = MagicMock()
                selector.get_map.return_value = {}
                selector.select.return_value = []
                original_handler = object()
                restore_failure = INVENTORY.Rejected('restore cancellation')
                unmask_failure = INVENTORY.Rejected('late queued cancellation')
                attempted = []
                masks = []
                def change_handler(number, handler):
                    if handler is original_handler:
                        attempted.append(number)
                        raise restore_failure
                def mask(operation, _numbers):
                    masks.append(operation)
                    if operation == INVENTORY.signal.SIG_SETMASK and masks.count(operation) == 2:
                        raise unmask_failure
                    return set()
                for target, options in (
                    ('subprocess.Popen', dict(return_value=child)),
                    ('selectors.DefaultSelector', dict(return_value=selector)),
                    ('os.set_blocking', {}), ('os.killpg', {}),
                    ('group_live', dict(return_value=False)),
                    ('signal.getsignal', dict(return_value=original_handler)),
                    ('signal.signal', dict(side_effect=change_handler)),
                    ('signal.pthread_sigmask', dict(side_effect=mask)),
                    ('signal.sigpending', dict(return_value=set())),
                ):
                    owner, _, name = target.rpartition('.')
                    stack.enter_context(patch.object(getattr(INVENTORY, owner) if owner else INVENTORY, name, **options))
                observed = SimpleNamespace(si_code=INVENTORY.os.CLD_EXITED, si_status=0)
                stack.enter_context(patch.object(INVENTORY.os, 'waitid', **(
                    dict(side_effect=original_failure) if original_failure else dict(return_value=observed))))
                commands = INVENTORY.Commands()
                with self.assertRaises(BaseException) as caught:
                    commands.run(['/usr/bin/apt-cache', 'policy', 'mount'])
                self.assertIs(caught.exception, original_failure or restore_failure)
                self.assertEqual(len(attempted), 4)
                self.assertEqual(masks, [INVENTORY.signal.SIG_BLOCK, INVENTORY.signal.SIG_SETMASK] * 2)
                self.assertEqual(commands.joined, 1)
                child.wait.assert_called_once()
                child.stdout.close.assert_called_once()
                child.stderr.close.assert_called_once()
                selector.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
