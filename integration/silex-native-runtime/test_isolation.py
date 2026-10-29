# SPDX-License-Identifier: GPL-3.0-only
"""Hosted controls only. No GUI, application, root command or network is run.

The process controls execute only public Python fixture actors in owned groups;
actual privileged namespace admission/calibration is a separate workflow step.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


C = load('isolation_controller_tests', HERE / 'isolation.py')
S = C.S
A = load('isolation_actor_tests', HERE / 'isolation_actor.py')
L = load('isolation_lifecycle_tests', HERE.parent / 'silex-export/lifecycle.py')


def passed_root():
    admission = dict(schema=1, operation='isolation_actor_admission', passed=True,
                     **dict.fromkeys(S.ADMISSION, True))
    calibration = dict(synthetic_actor=True, ipv4_attempts=1, ipv6_attempts=1,
        ipv4_drop_packets=1, ipv6_drop_packets=1, dns_queries=1, dns_replies=1,
        dns_output_packets=1, dns_reply_packets=1)
    worker = dict(schema=1, operation='namespace_isolation_worker', status='passed', stage='complete',
        admission=admission, calibration=calibration, namespace_groups_started=28,
        namespace_groups_joined=28, actors_started=2, actors_joined=2,
        owner_scope='namespace_process_groups', failure_kind=None, actor_failure_predicate=None)
    host = dict.fromkeys(('routes_sha256', 'resolver_sha256', 'firewall_configuration_sha256'), 'a' * 64)
    return dict(schema=1, operation='root_isolation_supervisor', status='passed', stage='complete',
        studio_revision='b' * 40, source_sha256={'public': 'c' * 64}, worker=worker,
        namespace_parent_joined=True, namespace_init_exit_confirmed=True,
        host_before_sha256=host, host_after_sha256=dict(host),
        host_network_configuration_unchanged=True, root_carrier_removed=True,
        source_groups_started=8, source_groups_joined=8,
        owned_groups_started=3, owned_groups_joined=3, failure_kind=None)


def verify(value):
    return C.verify_root(value, 'b' * 40, {'public': 'c' * 64})


class IsolationTests(unittest.TestCase):
    def test_duplicate_nonfinite_oversized_or_invalid_utf8_protocol_is_closed(self):
        for raw in (b'{"passed":true,"passed":false}', b'{"value":NaN}', b'\xff',
                    b' ' * (S.MAX_JSON + 1), b''):
            with self.subTest(raw_length=len(raw)), self.assertRaises(S.Rejected):
                S.parse(raw)
        self.assertEqual(S.parse(b'{"public":1}'), {'public': 1})

    def test_same_fd_read_rejects_symlink_hardlink_mode_and_observed_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'source'
            path.write_bytes(b'public fixture')
            path.chmod(0o600)
            self.assertEqual(S.read(path, 64, owner=os.getuid()), b'public fixture')
            alias = root / 'alias'
            alias.symlink_to(path)
            with self.assertRaises(S.Rejected):
                S.read(alias, 64, owner=os.getuid())
            alias.unlink()
            os.link(path, alias)
            with self.assertRaises(S.Rejected):
                S.read(path, 64, owner=os.getuid())
            alias.unlink()
            path.chmod(0o666)
            with self.assertRaises(S.Rejected):
                S.read(path, 64, owner=os.getuid())
            path.chmod(0o600)
            real_read = os.read
            changed = False
            def mutate(fd, count):
                nonlocal changed
                data = real_read(fd, count)
                if data and not changed:
                    changed = True
                    path.write_bytes(b'changed fixture!')
                return data
            with patch.object(S.os, 'read', side_effect=mutate), self.assertRaises(S.Rejected):
                S.read(path, 64, owner=os.getuid())

    def test_descriptor_closes_on_fstat_failure_and_retains_primary(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'public'
            path.write_bytes(b'public')
            path.chmod(0o600)
            captured = []
            real_open = os.open
            def opened(*args, **kwargs):
                fd = real_open(*args, **kwargs)
                captured.append(fd)
                return fd
            original = OSError('private-looking-path-must-not-be-reported')
            with patch.object(S.os, 'open', side_effect=opened), \
                    patch.object(S.os, 'fstat', side_effect=original), self.assertRaises(OSError) as caught:
                S.read(path, 64, owner=os.getuid())
            self.assertIs(caught.exception, original)
            with self.assertRaises(OSError):
                os.fstat(captured[0])

    def test_original_budget_is_not_renewed_or_accepted_after_work_deadline(self):
        now = 100_000_000_000
        environment = dict(VP_ISOLATION_WORK_NS=str(now + 90_000_000_000),
                           VP_ISOLATION_END_NS=str(now + 120_000_000_000))
        with patch.dict(os.environ, environment), patch.object(S.time, 'monotonic_ns', return_value=now):
            self.assertEqual(S.deadlines(), (190, 220))
            for key, value in (('VP_ISOLATION_WORK_NS', str(now)),
                               ('VP_ISOLATION_END_NS', str(now + 121_000_000_000))):
                with patch.dict(os.environ, {key: value}), self.assertRaises(S.Rejected):
                    S.deadlines()

    def test_root_stdio_transport_has_no_closefrom_override_or_ambient_environment(self):
        environment = dict(S.ENV, GITHUB_SHA='a' * 40)
        command = C.root_command(environment)
        self.assertEqual(command[:4], ['/usr/bin/sudo', '-n', '/usr/bin/env', '-i'])
        self.assertNotIn('-C', command)
        self.assertEqual(command[-5:], ['/usr/bin/python3', '-I', '-B',
                         str(HERE / 'isolation_root.py'), '--privileged-supervisor'])
        actor = S.actor_environment(1001, 1001, dict.fromkeys(S.NAMESPACES, 'public'),
                                   '/public/host-canary', {'shm': [1, 2], 'mqueue': [3, 4]}, '/public/marker')
        self.assertFalse(any(k.startswith(('LD_', 'WEBKIT_', 'GTK_', 'GDK_')) for k in actor))
        self.assertFalse({'DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SENTRY_DSN'} & actor.keys())
        self.assertIn('--no-new-privs', S.actor_command(1001, 1001, 'admission'))
        with self.assertRaises(S.Rejected):
            S.actor_command(1001, 1001, 'arbitrary-command')

    def test_original_identity_is_bound_to_checkout_owner_and_pwd_primary_gid(self):
        root = SimpleNamespace(stat=lambda: SimpleNamespace(st_uid=1001))
        with patch.dict(os.environ, VP_ISOLATION_UID='1001', VP_ISOLATION_GID='1002'), \
                patch.object(S, 'directory'), \
                patch.object(S.pwd, 'getpwuid', return_value=SimpleNamespace(pw_gid=1002)):
            self.assertEqual(S.owner_identity(root), (1001, 1002))
            for key, value in (('VP_ISOLATION_UID', '0'), ('VP_ISOLATION_GID', '1001')):
                with patch.dict(os.environ, {key: value}), self.assertRaises(S.Rejected):
                    S.owner_identity(root)

    def test_missing_nested_ack_or_host_change_never_becomes_cleanup_success(self):
        verify(passed_root())
        for key in ('namespace_parent_joined', 'namespace_init_exit_confirmed', 'root_carrier_removed'):
            changed = passed_root(); changed[key] = False
            with self.subTest(key=key), self.assertRaises(S.Rejected):
                verify(changed)
        for mutate in (
            lambda v: v['worker'].update(namespace_groups_joined=27),
            lambda v: v['worker'].update(actors_joined=1),
            lambda v: v['worker']['admission'].update(private_shared_memory=False),
            lambda v: v['worker']['calibration'].update(ipv4_drop_packets=0),
            lambda v: v['worker']['calibration'].update(dns_queries=True),
            lambda v: v['host_after_sha256'].update(routes_sha256='d' * 64)):
            changed = passed_root(); mutate(changed)
            with self.assertRaises(S.Rejected):
                verify(changed)

    def test_private_posix_ipc_requires_new_mounts_safe_flags_and_hidden_marker(self):
        parent = {'shm': [1, 2], 'mqueue': [3, 4]}
        mounts = ['1 0 0:1 / /dev/shm rw,nosuid,nodev,noexec - tmpfs tmpfs rw',
                  '2 0 0:2 / /dev/mqueue rw,nosuid,nodev,noexec - mqueue mqueue rw']
        marker = Path('/dev/shm/volparossa-native-isolation-1-1')
        with patch.object(A.os, 'stat', return_value=SimpleNamespace(st_dev=5, st_ino=6)), \
                patch.object(A.Path, 'exists', return_value=False), patch.object(A.Path, 'is_symlink', return_value=False):
            A.private_ipc_views(parent, mounts, marker)
            for bad in ([mounts[0].replace(',noexec', ''), mounts[1]],
                        [mounts[0], mounts[1].replace('mqueue mqueue', 'tmpfs tmpfs')]):
                with self.assertRaises(A.Rejected):
                    A.private_ipc_views(parent, bad, marker)
            with patch.object(A.os, 'stat', return_value=SimpleNamespace(st_dev=1, st_ino=2)), self.assertRaises(A.Rejected):
                A.private_ipc_views(parent, mounts, marker)
            with patch.object(A.Path, 'exists', return_value=True), self.assertRaises(A.Rejected):
                A.private_ipc_views(parent, mounts, marker)

    def test_observer_requires_exact_named_counters_not_route_failure_or_fabricated_attempts(self):
        rows = [dict(counter=dict(family='inet', table='vpcal', name=name, packets=1, bytes=42))
                for name in ('denied4', 'denied6', 'dns', 'dns_reply')]
        self.assertEqual(len(S.counters(json.dumps({'nftables': rows}).encode())), 4)
        for changed in (rows[:-1], rows + [rows[0]],
                        [dict(counter=dict(rows[0]['counter'], packets=True)), *rows[1:]],
                        [dict(counter=dict(rows[0]['counter'], bytes=4097)), *rows[1:]]):
            with self.assertRaises(S.Rejected):
                S.counters(json.dumps({'nftables': changed}).encode())
        self.assertEqual(A.QUERY, S.DNS_QUERY)
        self.assertEqual(A.REPLY, S.DNS_REPLY)
        with patch.object(A.socket, 'socket') as socket:
            socket.return_value.__enter__.return_value.sendto.side_effect = OSError(101, 'public network unavailable')
            with self.assertRaises(A.Rejected):
                A.denied_datagram(A.socket.AF_INET, ('198.51.100.9', 9))

    def test_host_comparison_excludes_only_dynamic_nft_counter_values(self):
        original = {'nftables': [{'counter': {'family': 'inet', 'name': 'public', 'packets': 1, 'bytes': 40}}]}
        dynamic = copy.deepcopy(original)
        dynamic['nftables'][0]['counter'].update(packets=7, bytes=280)
        self.assertEqual(S.clean_network_json(original), S.clean_network_json(dynamic))
        dynamic['nftables'][0]['counter']['name'] = 'changed-policy'
        self.assertNotEqual(S.clean_network_json(original), S.clean_network_json(dynamic))

    def test_repeated_cleanup_signal_does_not_replace_primary_or_skip_action(self):
        original = S.Rejected('deadline')
        completed = []
        with patch.object(S.signal, 'pthread_sigmask', side_effect=[set(), S.Rejected('cancelled')]):
            result = S.masked_cleanup(original, lambda: completed.append(True))
        self.assertIs(result, original)
        self.assertEqual(completed, [True])

    def test_actual_boot_frames_reject_malformed_eof_and_unsolicited_phase_bytes(self):
        self.assertEqual(os.environ.get('GITHUB_ACTIONS'), 'true')
        self.assertEqual(os.environ.get('RUNNER_ENVIRONMENT'), 'github-hosted')
        script = f'''import importlib.util,time
s=importlib.util.spec_from_file_location('boot_protocol',{str(HERE / 'isolation_root.py')!r})
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
try:
 m.boot_read(time.monotonic()+2)
 m.check_control()
except m.Rejected as error:
 print(error.kind)
'''
        for frame, expected in ((b'', b'protocol\n'), (b'wrong-frame-1\n', b'protocol\n'),
                                (S.BOOT, b'cancelled\n'), (S.BOOT + b'unsolicited', b'protocol\n')):
            owner = S.Owner(L, time.monotonic() + 4, time.monotonic() + 7, control=False)
            self.assertEqual(owner.run(['/usr/bin/python3', '-I', '-B', '-c', script], payload=frame), expected)
            self.assertEqual((owner.started, owner.joined), (1, 1))

    def publish(self, path, report, primary=None):
        previous = None
        try:
            result, previous = C.publish_receipt(path, report, primary)
            return result
        finally:
            if previous is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)

    def test_terminal_receipt_is_closed_private_atomic_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'receipt.json'
            report = dict(status='passed', failure_kind=None, **dict.fromkeys(S.SCOPES, False))
            self.assertIsNone(self.publish(path, report))
            self.assertEqual(S.parse(path.read_bytes()), report)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(path.with_name(path.name + '.pending').exists())
            original = path.read_bytes()
            self.assertIsInstance(self.publish(path, dict(report)), S.Rejected)
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn('full_gui_acceptance', report)

    def test_terminal_cancellation_before_or_during_staging_publishes_failure_only(self):
        for pending in ([{signal.SIGTERM}], [set(), {signal.SIGTERM}]):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'receipt.json'
                with patch.object(C.signal, 'sigpending', side_effect=pending):
                    result = self.publish(path, dict(status='passed', failure_kind=None))
                self.assertIsInstance(result, S.Rejected)
                self.assertEqual(S.parse(path.read_bytes()), dict(status='failed', failure_kind='cancelled'))

    def test_partial_write_close_or_publication_failure_cannot_expose_pass_or_mask_primary(self):
        original = S.Rejected('observer')
        for failure in ('write', 'close', 'link'):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'receipt.json'
                real_write = S.write_new
                def failed_write(p, raw, **kwargs):
                    if failure == 'write':
                        p.write_bytes(raw[:8]); p.chmod(0o600)
                        raise OSError('private write path')
                    real_write(p, raw, **kwargs)
                    if failure == 'close':
                        raise OSError('private close path')
                with patch.object(S, 'write_new', side_effect=failed_write), \
                        patch.object(C.os, 'link', side_effect=OSError('private link path')):
                    self.assertIs(self.publish(path, dict(status='failed', failure_kind='observer'), original), original)
                self.assertFalse(path.exists())

    def test_actual_owned_group_drains_term_resistant_descendant_and_keeps_original_failure(self):
        self.assertEqual(os.environ.get('GITHUB_ACTIONS'), 'true')
        self.assertEqual(os.environ.get('RUNNER_ENVIRONMENT'), 'github-hosted')
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'ready'
            script = ('import os,signal,time; from pathlib import Path; '
                'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                'child=os.fork(); '
                f'Path({str(marker)!r}).write_text("ready") if child else None; '
                'time.sleep(60)')
            original = S.Rejected('cancelled')
            owner = S.Owner(L, time.monotonic() + 5, time.monotonic() + 10, control=False)
            def service():
                if marker.exists():
                    raise original
            with self.assertRaises(S.Rejected) as caught:
                owner.run(['/usr/bin/python3', '-I', '-B', '-c', script], service=service, seconds=5)
            self.assertIs(caught.exception, original)
            self.assertEqual((owner.started, owner.joined), (1, 1))

    def test_actual_nested_cleanup_reserve_allows_inner_owner_to_join_before_outer(self):
        self.assertEqual(os.environ.get('GITHUB_ACTIONS'), 'true')
        self.assertEqual(os.environ.get('RUNNER_ENVIRONMENT'), 'github-hosted')
        self.assertGreater(S.COOPERATIVE_GRACE['root'], S.COOPERATIVE_GRACE['namespace'] + 4)
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'ready'
            joined = Path(temporary) / 'joined'
            root_file, lifecycle = str(HERE / 'isolation_root.py'), str(HERE.parent / 'silex-export/lifecycle.py')
            child = ('import signal,time; from pathlib import Path; '
                     'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                     f'Path({str(marker)!r}).write_text("ready"); time.sleep(60)')
            synthetic = f'''import importlib.util,sys,time
from pathlib import Path
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m
S=load('nested_root',{root_file!r});L=load('nested_lifecycle',{lifecycle!r})
S.boot_read(time.monotonic()+3)
owner=S.Owner(L,time.monotonic()+20,time.monotonic()+25)
try:
 owner.run(['/usr/bin/python3','-I','-B','-c',{child!r}],cooperative=True,role='namespace',seconds=20)
except S.Rejected:
 assert owner.started==owner.joined==1
 Path({str(joined)!r}).write_text('joined')
'''
            owner = S.Owner(L, time.monotonic() + 25, time.monotonic() + 30, control=False)
            original = S.Rejected('cancelled')
            def cancel():
                if marker.exists():
                    raise original
            with self.assertRaises(S.Rejected) as caught:
                owner.run(['/usr/bin/python3', '-I', '-B', '-c', synthetic], payload=S.BOOT,
                    keep_stdin=True, cooperative=True, role='root', service=cancel, seconds=25)
            self.assertIs(caught.exception, original)
            self.assertEqual(joined.read_text(), 'joined')
            self.assertEqual((owner.started, owner.joined), (1, 1))

    def entry_failure(self, **changes):
        value = dict(schema=1, operation='root_isolation_entry_failure', status='failed',
            studio_revision='b' * 40, stage='identity', failure_kind='identity',
            source_verified=False, source_sha256=None, source_groups_started=None,
            source_groups_joined=None, owned_groups_started=None, owned_groups_joined=None,
            root_carrier_removed=None, host_before_sha256=None, host_after_sha256=None)
        value.update(changes)
        return value

    def test_entry_failure_observation_is_closed_nullable_and_source_stage_bound(self):
        state = dict(stage='identity', source_verified=False, source_sha256=None,
                     source_owner=None, root_carrier_removed=None)
        with patch.dict(S.ENTRY_STATE, state, clear=True), patch.dict(os.environ, GITHUB_SHA='b' * 40):
            produced = S.entry_failure(S.Rejected('identity'))
            self.assertEqual(produced, self.entry_failure())
            projected = C.root_failure(S.encoded(produced), 'b' * 40, {'public': 'c' * 64})
            self.assertEqual(projected['layer'], 'root_entry')
            self.assertIsNone(projected['source_groups_started'])
            self.assertIsNone(projected['host_before_sha256'])
            # Exception text/attributes are never inspected or serialized.
            opaque = RuntimeError('PRIVATE path https://private.invalid secret')
            self.assertNotIn('PRIVATE', json.dumps(S.entry_failure(opaque)))
        complete = self.entry_failure(stage='carrier_write', failure_kind='filesystem',
            source_verified=True, source_sha256={'public': 'c' * 64},
            source_groups_started=8, source_groups_joined=8, root_carrier_removed=True)
        self.assertIs(C.root_failure(S.encoded(complete), 'b' * 40, {'public': 'c' * 64})['source_verified'], True)

    def test_failed_supervisor_observation_retains_only_counts_hashes_and_finite_worker_stage(self):
        value = passed_root()
        value.update(status='failed', stage='namespace_worker', failure_kind='child',
                     namespace_parent_joined=False, namespace_init_exit_confirmed=False,
                     host_after_sha256=None, host_network_configuration_unchanged=False)
        value['worker'] = dict(schema=1, operation='namespace_isolation_worker', status='failed',
            stage='admission_actor', failure_kind='child', namespace_groups_started=10,
            namespace_groups_joined=10, actors_started=1, actors_joined=1,
            owner_scope='namespace_process_groups', actor_failure_predicate='private_mqueue')
        projected = C.root_failure(S.encoded(value), 'b' * 40, {'public': 'c' * 64})
        self.assertEqual(projected['worker_failure']['actor_failure_predicate'], 'private_mqueue')
        self.assertEqual(projected['host_before_sha256'], value['host_before_sha256'])
        self.assertIsNone(projected['host_after_sha256'])
        self.assertNotIn('namespace_parent_joined', projected)
        for key, bad in (('stage', 'PRIVATE/path'), ('actors_started', True),
                         ('actor_failure_predicate', 'PRIVATE/path'),
                         ('namespace_groups_joined', 11), ('actors_started', 3), ('actors_joined', 2)):
            changed = copy.deepcopy(value); changed['worker'][key] = bad
            with self.assertRaises(S.Rejected):
                C.root_failure(S.encoded(changed), 'b' * 40, {'public': 'c' * 64})

    def test_root_failure_refuses_unknown_fields_types_revision_and_cross_phase_output(self):
        for changes in ({'stage': 'PRIVATE stage'}, {'stage': 'host_before'}, {'raw_error': 'PRIVATE'},
                {'schema': True}, {'source_verified': 1}, {'source_verified': True},
                {'source_groups_started': True, 'source_groups_joined': 0},
                {'source_groups_started': 129, 'source_groups_joined': 0},
                {'source_groups_started': 1, 'source_groups_joined': 2},
                {'studio_revision': 'd' * 40}, {'failure_kind': 'PRIVATE'},
                {'stage': 'carrier_exec'}, {'host_before_sha256': {'raw': 'PRIVATE'}}):
            with self.subTest(changes=changes), self.assertRaises(S.Rejected):
                C.root_failure(S.encoded(self.entry_failure(**changes)), 'b' * 40, {'public': 'c' * 64})
        for raw in (b'', b'{', b'{"schema":1,"schema":1}', S.encoded(passed_root()),
                    b'PRIVATE stderr\n', b'x' * (S.MAX_JSON + 1)):
            with self.assertRaises(S.Rejected):
                C.root_failure(raw, 'b' * 40, {'public': 'c' * 64})

    def test_optional_observation_never_changes_first_error_or_missing_ack_cleanup(self):
        primary = S.Rejected('child')
        report = dict(root_failure=None, root_result=None, cleanup_confirmed=False,
                      private_work_removed=False, host_ipc_canary_removed=False)
        self.assertIs(C.retain_root_failure(primary, report, S.encoded(self.entry_failure()),
                        'b' * 40, {'public': 'c' * 64}), primary)
        self.assertEqual(report['root_failure']['stage'], 'identity')
        self.assertIsNone(report['root_result'])
        self.assertTrue(all(report[name] is False for name in
            ('cleanup_confirmed', 'private_work_removed', 'host_ipc_canary_removed')))
        for raw in (b'', b'corrupt'):
            empty = dict(report, root_failure=None)
            self.assertIs(C.retain_root_failure(primary, empty, raw, 'b' * 40, {}), primary)
            self.assertIsNone(empty['root_failure'])
        with patch.object(C, 'root_failure', side_effect=InterruptedError('observer cancelled')):
            self.assertIs(C.retain_root_failure(primary, report, b'public', 'b' * 40, {}), primary)

    def test_actual_entry_failure_and_owned_rejection_retain_closed_request_bound_stdout(self):
        self.assertEqual(os.environ.get('GITHUB_ACTIONS'), 'true')
        self.assertEqual(os.environ.get('RUNNER_ENVIRONMENT'), 'github-hosted')
        self.assertNotEqual(os.geteuid(), 0)
        # Nonroot staged entry rejects BEFORE any carrier, namespace or host
        # action. Only a new Python process/group is created by this control.
        now = time.monotonic_ns()
        environment = dict(S.ENV, GITHUB_SHA='b' * 40,
            VP_ISOLATION_WORK_NS=str(now + 5_000_000_000), VP_ISOLATION_END_NS=str(now + 35_000_000_000))
        owner = S.Owner(L, time.monotonic() + 5, time.monotonic() + 8, control=False)
        with self.assertRaises(S.Rejected) as caught:
            owner.run(['/usr/bin/python3', '-I', '-B', HERE / 'isolation_root.py', '--supervisor-staged'],
                      environment=environment, seconds=4)
        self.assertEqual(caught.exception.kind, 'child')
        report = dict(root_failure=None)
        self.assertIs(C.retain_root_failure(caught.exception, report, owner.last_output,
                        'b' * 40, {'public': 'c' * 64}), caught.exception)
        self.assertEqual(report['root_failure']['stage'], 'staged_source')
        self.assertIsNone(report['root_failure']['root_carrier_removed'])
        self.assertEqual((owner.started, owner.joined), (1, 1))


if __name__ == '__main__':
    unittest.main()
