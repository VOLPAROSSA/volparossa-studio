# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only inert SDK installation controls: no sudo/APT/package execution."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import install_sdk as sdk
finally:
    sys.path.remove(str(HERE))


def records():
    return {'aa': dict(Version='1:2.0-1', Architecture='amd64', Size='3',
                       SHA256=hashlib.sha256(b'abc').hexdigest()),
            'bb': dict(Version='2.0-1', Architecture='all', Size='4',
                       SHA256=hashlib.sha256(b'defg').hexdigest())}


def dpkg(rows):
    return ''.join(name + '\t' + version + '\t' + arch + '\t' + state + '\n'
                   for name, version, arch, state in rows).encode()


def plan():
    return b'Reading package lists...\nInst aa [1:1.0-1] (1:2.0-1 Ubuntu:24.04/noble [amd64])\nConf aa (1:2.0-1 Ubuntu:24.04/noble [amd64])\n'


class InstallSdkTests(unittest.TestCase):
    def test_exact_manifest_and_actual_fetch_binding_cannot_gain_install_or_native_authority(self):
        data = (HERE / 'ubuntu-sdk.json').read_bytes()
        expected = sdk.records_from_manifest(data)
        self.assertEqual(len(expected), 182)
        self.assertEqual(sum(int(row['Size']) for row in expected.values()), 63772228)
        value = dict(schema=1, mode='native-sdk-archives-fetch', status='passed', stage='complete',
            studio_revision='a' * 40, sdk_manifest_sha256=sdk.MANIFEST, archives_verified=True,
            archive_count=182, archive_bytes=63772228, hashes=sdk.expected_hashes(expected),
            cleanup=dict(owned_groups_joined=True, owned_group_count=3, archives_retained=True, archive_tree_private=True),
            packages_installed=False, sdk_installed=False, archive_contents_executed=False, archive_contents_extracted=False,
            **dict.fromkeys(sdk.FALSE_FLAGS, False))
        sdk.check_fetch(value, expected, 'a' * 40)
        for key, bad in (('studio_revision', 'b' * 40), ('sdk_installed', True),
                         ('hashes', []), ('archives_verified', False), ('archive_count', 181)):
            with self.subTest(key=key), self.assertRaises(sdk.Rejected):
                sdk.check_fetch(dict(value, **{key: bad}), expected, 'a' * 40)
        with self.assertRaises(sdk.Rejected):
            sdk.records_from_manifest(data + b' ')
        with self.assertRaises(sdk.Rejected):
            sdk.parse(b'{"a":1,"a":2}')

    def test_dpkg_requires_exact_complete_versions_architecture_and_install_state(self):
        rows = [('aa', '1:2.0-1', 'amd64', 'install ok installed'), ('bb', '2.0-1', 'all', 'install ok installed')]
        self.assertEqual(set(sdk.dpkg_rows(dpkg(rows), records(), complete=True)), {'aa', 'bb'})
        for bad in (rows[:1], rows + rows[:1], [rows[0], ('bb', '2.1-1', 'all', 'install ok installed')],
                    [rows[0], ('bb', '2.0-1', 'amd64', 'install ok installed')],
                    [rows[0], ('bb', '2.0-1', 'all', 'install ok unpacked')]):
            with self.subTest(rows=bad), self.assertRaises(sdk.Rejected):
                sdk.dpkg_rows(dpkg(bad), records(), complete=True)
        self.assertEqual(sdk.dpkg_rows(b'', records(), complete=False), {})

    def test_simulation_refuses_removal_extra_missing_conf_old_version_drift_and_incomplete_closure(self):
        installed = {'aa': ('1:1.0-1', 'amd64'), 'bb': ('2.0-1', 'all')}
        self.assertEqual(sdk.plan_rows(plan(), records(), installed), {'aa': '1:2.0-1'})
        for bad in (plan() + b'Remv libc6 [2.39]\n', plan() + b'Purg bb\n',
                    plan().replace(b'Inst aa ', b'Inst cc '), plan().replace(b'1:2.0-1', b'1:3.0-1'),
                    plan().replace(b'[1:1.0-1]', b'[1:0.9-1]'), plan().split(b'Conf ')[0],
                    plan() + b'Conf aa (1:2.0-1 Ubuntu [amd64])\n'):
            with self.subTest(raw=bad), self.assertRaises(sdk.Rejected):
                sdk.plan_rows(bad, records(), installed)
        with self.assertRaises(sdk.Rejected):
            sdk.plan_rows(plan(), records(), {'aa': installed['aa']})

    def test_downgrade_denial_precedes_install_and_fixed_argv_never_downloads_or_removes(self):
        installed = {'aa': ('1:1.0-1', 'amd64'), 'bb': ('2.0-1', 'all')}
        invoke = Mock(side_effect=[(plan(), 0), (b'', 0)])
        argv, targets, _planned = sdk.install_plan(records(), installed, invoke, Path('/var/tmp/fixed-cache'))
        self.assertEqual(targets, ['aa=1:2.0-1', 'bb=2.0-1'])
        self.assertEqual(argv, ['/usr/bin/apt-get',
            '-o', 'APT::Get::AllowUnauthenticated=false', '-o', 'Acquire::AllowInsecureRepositories=false',
            '-o', 'Acquire::AllowDowngradeToInsecureRepositories=false',
            '-o', 'Acquire::http::AllowRedirect=false', '-o', 'Acquire::https::AllowRedirect=false',
            '-o', 'Acquire::http::Proxy=DIRECT', '-o', 'Acquire::https::Proxy=DIRECT',
            '-o', 'Dir::Etc::netrc=/dev/null', '-o', 'Dir::Etc::netrcparts=/nonexistent',
            '-o', 'Dir::Cache::archives=/var/tmp/fixed-cache', '-o', 'APT::Get::AutomaticRemove=false',
            '-o', 'DPkg::Lock::Timeout=10', '--no-remove', '--no-download', '--no-install-recommends'])
        self.assertEqual(invoke.call_args_list, [call([*argv, '--simulate', 'install', *targets]),
            call(['/usr/bin/dpkg', '--compare-versions', '1:1.0-1', 'le', '1:2.0-1'])])
        invoke = Mock(side_effect=[(plan(), 0), sdk.Rejected('downgrade')])
        with self.assertRaisesRegex(sdk.Rejected, 'downgrade'):
            sdk.install_plan(records(), installed, invoke, Path('/var/tmp/fixed-cache'))
        self.assertEqual(invoke.call_count, 2)

    def test_independent_fd_copy_hash_and_epoch_cache_names_with_no_symlink_or_partial_input(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source, cache = root / 'archives', root / 'cache'
            source.mkdir(mode=0o700)
            cache.mkdir(mode=0o700)
            (source / 'arbitrary_1%3a2.0_amd64.deb').write_bytes(b'abc')
            (source / 'second.deb').write_bytes(b'defg')
            sdk.stage_archives(source, cache, records(), os.geteuid())
            first = cache / 'aa_1%3a2.0-1_amd64.deb'
            self.assertEqual(first.read_bytes(), b'abc')
            self.assertEqual((cache / 'bb_2.0-1_all.deb').read_bytes(), b'defg')
            (source / 'arbitrary_1%3a2.0_amd64.deb').write_bytes(b'xxx')
            self.assertEqual(first.read_bytes(), b'abc')
            for mode in ('partial', 'symlink', 'hardlink', 'extra'):
                with self.subTest(mode=mode), tempfile.TemporaryDirectory() as new_cache:
                    bad = source / 'arbitrary_1%3a2.0_amd64.deb'
                    bad.unlink()
                    if mode == 'symlink':
                        bad.symlink_to(source / 'second.deb')
                    elif mode == 'hardlink':
                        os.link(source / 'second.deb', bad)
                    else:
                        bad.write_bytes(b'ab' if mode == 'partial' else b'abc')
                    if mode == 'extra':
                        (source / 'extra.deb').write_bytes(b'extra')
                    with self.assertRaises((sdk.Rejected, OSError)):
                        sdk.stage_archives(source, Path(new_cache), records(), os.geteuid())

    def test_input_mutation_during_copy_rejected_and_original_failure_not_replaced(self):
        with tempfile.TemporaryDirectory() as name:
            source, target = Path(name) / 'source', Path(name) / 'target'
            source.write_bytes(b'abc')
            descriptor = os.open(source, os.O_RDONLY)
            original = os.read
            mutated = False
            def read_and_mutate(fd, size):
                nonlocal mutated
                value = original(fd, size)
                if fd == descriptor and not mutated:
                    mutated = True
                    with source.open('ab') as output:
                        output.write(b'd')
                return value
            try:
                with patch.object(sdk.os, 'read', side_effect=read_and_mutate), self.assertRaises(sdk.Rejected):
                    sdk.copy_archive(descriptor, target, os.geteuid(), {records()['aa']['SHA256']: ('aa', records()['aa'])})
            finally:
                os.close(descriptor)

    def test_existing_policy_is_preserved_new_policy_restored_and_replacement_never_removed(self):
        with tempfile.TemporaryDirectory() as name, patch.object(sdk, 'POLICY', Path(name) / 'policy'):
            sdk.POLICY.write_bytes(b'original')
            with self.assertRaises(FileExistsError):
                sdk.policy_begin()
            self.assertEqual(sdk.POLICY.read_bytes(), b'original')
            sdk.POLICY.unlink()
            modes = []
            original_sync = os.fsync
            def observe_sync(descriptor):
                modes.append(stat.S_IMODE(os.fstat(descriptor).st_mode))
                original_sync(descriptor)
            with patch.object(sdk.os, 'fsync', side_effect=observe_sync):
                identity = sdk.policy_begin()
            self.assertEqual(modes, [0o600, 0o755])
            self.assertEqual(sdk.POLICY.read_bytes(), sdk.POLICY_BYTES)
            sdk.policy_end(identity, owner=os.geteuid())
            self.assertFalse(sdk.POLICY.exists())
            with patch.object(sdk, 'policy_end') as restore:
                self.assertFalse(sdk.finish_policy((1, 2), []))
                self.assertFalse(sdk.finish_policy((1, 2), [True, False]))
                restore.assert_not_called()
                self.assertTrue(sdk.finish_policy((1, 2), [True, True]))
                restore.assert_called_once_with((1, 2))
            identity = sdk.policy_begin()
            replacement = Path(name) / 'replacement'
            replacement.write_bytes(b'foreign policy')
            replacement.replace(sdk.POLICY)
            with self.assertRaises(sdk.Rejected):
                sdk.policy_end(identity, owner=os.geteuid())
            self.assertEqual(sdk.POLICY.read_bytes(), b'foreign policy')
            sdk.POLICY.unlink()
            with patch.object(sdk.os, 'fsync', side_effect=OSError('original fsync failure')):
                with self.assertRaisesRegex(OSError, 'original fsync failure'):
                    sdk.policy_begin()
            self.assertFalse(sdk.POLICY.exists())

    def test_root_actor_keeps_leader_unreaped_until_group_signals_and_reports_failed_join(self):
        child = SimpleNamespace(pid=12345, stdout=Mock(), stderr=Mock(), wait=Mock())
        child.stdout.fileno.return_value = 8
        child.stderr.fileno.return_value = 9
        selector = Mock()
        selector.__enter__ = Mock(return_value=selector)
        selector.__exit__ = Mock(return_value=False)
        selector.get_map.return_value = {}
        observed = SimpleNamespace(si_pid=12345, si_code=os.CLD_EXITED, si_status=0)
        order = []
        child.wait.side_effect = lambda **_kwargs: order.append('wait')
        with patch.object(sdk.subprocess, 'Popen', return_value=child), \
             patch.object(sdk.selectors, 'DefaultSelector', return_value=selector), \
             patch.object(sdk.os, 'set_blocking'), \
             patch.object(sdk.os, 'waitid', side_effect=lambda *_args: order.append('peek') or observed), \
             patch.object(sdk.os, 'killpg', side_effect=lambda *_args: order.append('signal')), \
             patch.object(sdk, 'live_group', return_value=False):
            cleanups = []
            self.assertEqual(sdk.root_actor(['/fixed'], sdk.time.monotonic() + 30, cleanups), (b'', 0))
            self.assertEqual(order, ['peek', 'signal', 'wait'])
            self.assertEqual(cleanups, [True])
            self.assertFalse(hasattr(child, 'poll'))
            child.wait.side_effect = OSError('join failed')
            cleanups = []
            with self.assertRaisesRegex(sdk.Rejected, 'root_group_cleanup_unconfirmed'):
                sdk.root_actor(['/fixed'], sdk.time.monotonic() + 30, cleanups)
            self.assertEqual(cleanups, [False])
            observed.si_status = 7
            with self.assertRaisesRegex(sdk.Rejected, 'sdk_install_rejected'):
                sdk.root_actor(['/fixed'], sdk.time.monotonic() + 30, [])

    def test_closed_root_receipt_requires_cleanup_exact_hashes_and_all_native_flags_false(self):
        value = dict(schema=1, mode='native-sdk-offline-root-install', status='passed', stage='complete',
            studio_revision='a' * 40, sdk_manifest_sha256=sdk.MANIFEST, packages_installed=True,
            sdk_installed=True, network_namespace_isolated=True, root_archive_cache_verified=True,
            post_install_exact_versions=True, dpkg_audit_clean=True, installation_attempted=True, policy_created=True, policy_restored=True,
            root_cache_retained=True, owned_groups_joined=True, owned_group_count=6,
            verified_package_count=182, hashes=sdk.expected_hashes(records()), **dict.fromkeys(sdk.FALSE_FLAGS, False))
        sdk.check_root(value, 'a' * 40, records())
        for key, bad in (('policy_restored', False), ('owned_groups_joined', False), ('status', 'failed'),
                         ('hashes', []), ('native_build', True), ('owned_group_count', True),
                         ('network_namespace_isolated', False)):
            with self.subTest(key=key), self.assertRaises(sdk.Rejected):
                sdk.check_root(dict(value, **{key: bad}), 'a' * 40, records())

    def test_outer_root_owner_has_separate_cleanup_reserve(self):
        drain = Mock(return_value={'leader_joined': True, 'live_group_drained': True})
        process, identity = object(), object()
        self.assertEqual(sdk.drain_install_owner(drain, process, identity, grace=1.0, kill_grace=1.0),
                         {'leader_joined': True, 'live_group_drained': True})
        drain.assert_called_once_with(process, identity, grace=15.0, kill_grace=3.0)
        # The root actor has at most TERM1 + KILL1 + wait1 before policy restore;
        # this outer reserve cannot be reduced by the generic caller's kwargs.
        self.assertGreater(drain.call_args.kwargs['grace'], 1 + 1 + 1)

    def test_root_actor_close_failure_attempts_both_pipes_restores_handlers_and_keeps_primary(self):
        child = SimpleNamespace(pid=12345, stdout=Mock(), stderr=Mock(), wait=Mock())
        child.stdout.fileno.return_value = 8
        child.stderr.fileno.return_value = 9
        child.stdout.close.side_effect = OSError('first close failed')
        selector = Mock()
        selector.__enter__ = Mock(return_value=selector)
        selector.__exit__ = Mock(return_value=False)
        selector.get_map.return_value = {}
        original = sdk.Rejected('original failure')
        signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
        handlers = {number: signal.getsignal(number) for number in signals}
        original_signal = signal.signal
        with patch.object(sdk.subprocess, 'Popen', return_value=child), \
             patch.object(sdk.selectors, 'DefaultSelector', return_value=selector), \
             patch.object(sdk.os, 'set_blocking'), \
             patch.object(sdk.os, 'waitid', side_effect=original), \
             patch.object(sdk.os, 'killpg'), patch.object(sdk, 'live_group', return_value=False), \
             patch.object(sdk.signal, 'signal', wraps=original_signal) as restore:
            cleanups = []
            with self.assertRaises(sdk.Rejected) as caught:
                sdk.root_actor(['/fixed'], sdk.time.monotonic() + 30, cleanups)
            self.assertIs(caught.exception, original)
            child.stdout.close.assert_called_once_with()
            child.stderr.close.assert_called_once_with()
            self.assertEqual(cleanups, [False])
            self.assertEqual(restore.call_args_list[-4:], [call(number, handlers[number]) for number in signals])
        self.assertEqual({number: signal.getsignal(number) for number in signals}, handlers)

    def test_real_harmless_term_resistant_descendant_is_killed_after_exited_leader(self):
        # HOSTED ONLY: installed Python, fixed public fixture and a sleep loop.
        # No SDK, sudo, APT, application, network or arbitrary executable runs.
        self.assertEqual(os.environ.get('GITHUB_ACTIONS'), 'true')
        self.assertEqual(os.environ.get('RUNNER_ENVIRONMENT'), 'github-hosted')
        self.assertEqual(os.environ.get('RUNNER_OS'), 'Linux')
        self.assertEqual(os.environ.get('RUNNER_ARCH'), 'X64')
        self.assertNotEqual(os.geteuid(), 0)
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        owned = []
        descendant = None
        real_popen, real_kill = subprocess.Popen, os.killpg
        def start(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            owned.append(child)
            return child
        try:
            with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP']) as directory:
                marker = Path(directory) / 'public-ready'
                code = ('import os,signal,time\nread,write=os.pipe()\npid=os.fork()\n'
                    'if pid==0:\n os.close(read)\n signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                    ' os.close(1)\n os.close(2)\n'
                    ' with open(' + repr(str(marker)) + ',"w") as out: out.write(str(os.getpid()))\n'
                    ' os.write(write,b"1")\n os.close(write)\n time.sleep(30)\n os._exit(0)\n'
                    'os.close(write)\nos.read(read,1)\nos.close(read)\nos._exit(0)\n')
                cleanups = []
                started = sdk.time.monotonic()
                try:
                    with patch.object(sdk.subprocess, 'Popen', side_effect=start), \
                         patch.object(sdk.os, 'killpg', wraps=real_kill) as kill:
                        self.assertEqual(sdk.root_actor([sys.executable, '-I', '-B', '-c', code],
                                                       started + 10, cleanups), (b'', 0))
                finally:
                    if marker.exists():
                        descendant = int(marker.read_text())
                self.assertLess(sdk.time.monotonic() - started, 10)
                self.assertEqual(cleanups, [True])
                self.assertEqual(len(owned), 1)
                self.assertEqual(owned[0].returncode, 0)
                self.assertEqual([item.args for item in kill.call_args_list],
                                 [(owned[0].pid, signal.SIGTERM), (owned[0].pid, signal.SIGKILL)])
                self.assertIsNotNone(descendant)
                limit = sdk.time.monotonic() + 2
                while True:
                    pid, status = os.waitpid(descendant, os.WNOHANG)
                    if pid:
                        break
                    self.assertLess(sdk.time.monotonic(), limit)
                    sdk.time.sleep(0.01)
                self.assertEqual(pid, descendant)
                self.assertEqual(os.waitstatus_to_exitcode(status), -signal.SIGKILL)
                self.assertFalse(Path('/proc', str(descendant)).exists())
                descendant = None
        finally:
            # Signal only an unreaped direct leader, or our unreaped adopted
            # child. Never signal a group after its leader has been reaped.
            try:
                for child in owned:
                    if child.returncode is None:
                        try:
                            real_kill(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        child.wait(timeout=2)
                if descendant is not None:
                    try:
                        observed = os.waitid(os.P_PID, descendant, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                        if observed is None:
                            os.kill(descendant, signal.SIGKILL)
                        limit = sdk.time.monotonic() + 2
                        while os.waitpid(descendant, os.WNOHANG)[0] == 0:
                            if sdk.time.monotonic() >= limit:
                                raise TimeoutError('owned fixture descendant join')
                            sdk.time.sleep(0.01)
                    except ChildProcessError:
                        pass
            finally:
                self.assertEqual(libc.prctl(36, previous.value, 0, 0, 0), 0)

    def test_shared_admission_failure_has_same_closed_substage_and_no_later_effects_in_both_modes(self):
        environment = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Linux',
            RUNNER_ARCH='X64', GITHUB_REPOSITORY='VOLPAROSSA/volparossa-studio', SILEX_SDK_OWNER='1001',
            GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='a' * 40, GITHUB_WORKFLOW_SHA='a' * 40,
            GITHUB_WORKSPACE=str(sdk.ROOT.parent), RUNNER_TEMP='/tmp/public-synthetic-unused')
        def refuse_directory(_path, _owners, *, diagnostic):
            diagnostic.update(canonical=True, owner_allowed=True, mode_safe=False, ancestor_depth=2)
            raise sdk.Rejected('synthetic directory guard refused')
        for admission_only in (False, True):
            with self.subTest(admission_only=admission_only):
                output = io.BytesIO()
                argument = '--privileged-admission' if admission_only else '--privileged-install'
                with patch.dict(os.environ, environment, clear=True), \
                     patch.object(sdk.sys, 'argv', [str(HERE / 'install_sdk.py'), argument]), \
                     patch.object(sdk.sys, 'stdout', SimpleNamespace(buffer=output)), \
                     patch.object(sdk.os, 'getuid', return_value=0), patch.object(sdk.os, 'geteuid', return_value=0), \
                     patch.object(sdk, 'canonical_directory', side_effect=refuse_directory), \
                     patch.object(sdk, 'records_from_manifest') as manifest, \
                     patch.object(sdk, 'check_fetch') as fetch, patch.object(sdk, 'stage_archives') as stage, \
                     patch.object(sdk, 'root_actor') as actor, patch.object(sdk, 'policy_begin') as policy, \
                     patch.object(sdk.Path, 'mkdir') as mkdir, patch.object(sdk, 'finish_policy', return_value=True):
                    self.assertEqual(sdk.root_main(admission_only=admission_only), 0)
                report = sdk.parse(output.getvalue())
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['failure_stage'], 'admission')
                self.assertEqual(report['admission_diagnostic'], dict(substage='directory_runner',
                    canonical=True, owner_allowed=True, mode_safe=False, ancestor_depth=2))
                sdk.check_admission_diagnostic(report['admission_diagnostic'])
                for mock in (manifest, fetch, stage, actor, policy, mkdir):
                    mock.assert_not_called()
                for key in ('packages_installed', 'sdk_installed', 'installation_attempted',
                            'root_cache_retained', 'root_archive_cache_verified', 'policy_created', *sdk.FALSE_FLAGS):
                    self.assertIs(report[key], False)

    def test_successful_admission_profile_is_readonly_and_cannot_be_installation_evidence(self):
        output = io.BytesIO()
        def admitted(report, argument):
            self.assertEqual(argument, '--privileged-admission')
            report.update(studio_revision='a' * 40, run_id='123', run_attempt='1', network_namespace_isolated=True)
            sdk.admission_stage(report, 'complete')
            return Path('/tmp/unused'), 'a' * 40, 1001, '123', '1', records()
        with patch.object(sdk, 'root_admission', side_effect=admitted), \
             patch.object(sdk.sys, 'stdout', SimpleNamespace(buffer=output)), \
             patch.object(sdk, 'check_fetch') as fetch, patch.object(sdk, 'stage_archives') as stage, \
             patch.object(sdk, 'root_actor') as actor, patch.object(sdk, 'policy_begin') as policy, \
             patch.object(sdk.Path, 'mkdir') as mkdir, patch.object(sdk, 'finish_policy', return_value=True) as finish:
            self.assertEqual(sdk.root_main(admission_only=True), 0)
        value = sdk.parse(output.getvalue())
        sdk.check_root_admission(value, 'a' * 40)
        with self.assertRaises(sdk.Rejected):
            sdk.check_root(value, 'a' * 40, records())
        for mock in (fetch, stage, actor, policy, mkdir):
            mock.assert_not_called()
        finish.assert_called_once_with(None, [])
        for key, bad in (('policy_created', True), ('root_cache_retained', True), ('owned_group_count', 1),
                         ('sdk_installed', True), ('admission_passed', False), ('native_gui_verified', True)):
            with self.subTest(key=key), self.assertRaises(sdk.Rejected):
                sdk.check_root_admission(dict(value, **{key: bad}), 'a' * 40)
        # A completed guard sequence is not PASS until final read-only cleanup
        # acknowledgement succeeds. Both a false acknowledgement and its error
        # must leave an internally consistent failed root artifact.
        for outcome in (False, OSError('synthetic cleanup failure')):
            with self.subTest(cleanup=type(outcome).__name__):
                output = io.BytesIO()
                options = {'side_effect': outcome} if isinstance(outcome, BaseException) else {'return_value': outcome}
                with patch.object(sdk, 'root_admission', side_effect=admitted), \
                     patch.object(sdk.sys, 'stdout', SimpleNamespace(buffer=output)), \
                     patch.object(sdk, 'finish_policy', **options):
                    self.assertEqual(sdk.root_main(admission_only=True), 0)
                failed = sdk.parse(output.getvalue())
                self.assertEqual(failed['status'], 'failed')
                self.assertIs(failed['admission_passed'], False)
                self.assertIs(failed['policy_restored'], False)
                self.assertEqual(failed['admission_diagnostic'], {'substage': 'complete'})
                self.assertEqual(failed['failure_stage'], 'policy_cleanup' if isinstance(outcome, BaseException) else 'cleanup')
                with self.assertRaises(sdk.Rejected):
                    sdk.check_root_admission(failed, 'a' * 40)

    def test_diagnostic_schema_never_discloses_arbitrary_path_identity_or_environment(self):
        sdk.check_admission_diagnostic(dict(substage='directory_runner', canonical=False,
            owner_allowed=False, mode_safe=False, ancestor_depth=32))
        for bad in ({'substage': 'unknown'}, {'substage': 'directory_runner', 'path': '/private'},
                    {'substage': 'directory_runner', 'uid': 1001}, {'substage': 'network_state', 'netns': 'net:[123]'},
                    {'substage': 'directory_runner', 'owner_allowed': 1},
                    {'substage': 'directory_runner', 'ancestor_depth': 33}):
            with self.subTest(value=bad), self.assertRaises(sdk.Rejected):
                sdk.check_admission_diagnostic(bad)


if __name__ == '__main__':
    unittest.main()
