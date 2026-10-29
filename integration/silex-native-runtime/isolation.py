# SPDX-License-Identifier: GPL-3.0-only
"""Explicit hosted isolation admission/calibration, never an application trial.

The workflow must first produce the unchanged SDK receipts and fresh read-only
runtime inventory in THIS job. Only stdin/stdout/stderr cross sudo; no sudoers
change, preserved arbitrary descriptor, tool-path override or command API exists.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location('native_isolation_protocol', HERE / 'isolation_root.py')
S = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = S
SPEC.loader.exec_module(S)
SDK_HELPER = '817f0ad22c4b0e6447782738e4afacb70d0c31305e883976b1a658e41291606b'
INVENTORY_SOURCE = '3be00d4d68eece6920d2332af64a815f0f434584575574aeb04daef7c9dbcf70'
TOOLS = {'Xvfb': '/usr/bin/Xvfb', 'bwrap': '/usr/bin/bwrap',
    'dbus-daemon': '/usr/bin/dbus-daemon', 'ip': '/usr/bin/ip',
    'mount': '/usr/bin/mount', 'nft': '/usr/sbin/nft', 'setpriv': '/usr/bin/setpriv',
    'unshare': '/usr/bin/unshare', 'xauth': '/usr/bin/xauth', 'xdotool': '/usr/bin/xdotool'}
PROVIDERS = frozenset(('bubblewrap', 'dbus-daemon', 'iproute2', 'mount', 'nftables',
                       'util-linux', 'xauth', 'xdotool', 'xvfb'))
ROOT_RECEIPT_KEYS = frozenset(('admission_diagnostic', 'dpkg_audit_clean', 'full_application_privacy',
    'full_studio_acceptance', 'hashes', 'installation_attempted', 'mode', 'native_build',
    'native_gui_verified', 'native_runtime_acceptance', 'network_namespace_isolated',
    'owned_group_count', 'owned_groups_joined', 'packages_installed', 'plan_sha256',
    'planned_package_count', 'policy_created', 'policy_restored', 'post_install_exact_versions',
    'root_archive_cache_verified', 'root_cache_retained', 'run_attempt', 'run_id', 'schema',
    'sdk_installed', 'sdk_manifest_sha256', 'stage', 'status', 'studio_revision',
    'verified_package_count', 'volparossa_updates_verified'))
OUTER_RECEIPT_KEYS = frozenset(('admission_diagnostic', 'archive_bytes', 'cleanup',
    'full_application_privacy', 'full_studio_acceptance', 'hashes', 'mode', 'native_build',
    'native_gui_verified', 'native_runtime_acceptance', 'packages_installed', 'schema',
    'sdk_installed', 'sdk_manifest_sha256', 'stage', 'status', 'studio_revision',
    'verified_package_count', 'volparossa_updates_verified'))
INVENTORY_KEYS = frozenset(('application_executed', 'apt_verification', 'archive_contents_verified',
    'archives_downloaded', 'candidate_archive_signatures_independently_verified', 'cleanup_confirmed',
    'compiler_or_node_executed', 'display_started', 'full_studio_acceptance', 'installation_plan',
    'installation_plan_sha256', 'inventoried_tools_executed', 'missing_providers', 'namespaces_created',
    'native_runtime_acceptance', 'network_configuration_changed', 'operation', 'owned_groups_joined',
    'owned_groups_started', 'packages', 'packages_installed', 'readiness', 'schema', 'signed_apt_indices',
    'simulation_performed', 'stage', 'status', 'studio_revision', 'system', 'tools'))


def load_sdk(uid):
    path = ROOT / 'integration/silex-native-bootstrap/install_sdk.py'
    S.require(hashlib.sha256(S.read(path, S.MAX_SOURCE, owner=uid, modes=(0o644,))).hexdigest() == SDK_HELPER, 'source')
    spec = importlib.util.spec_from_file_location('isolation_sdk_contract', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def prerequisites(temporary, revision, uid):
    sdk = load_sdk(uid)
    manifest = S.read(ROOT / 'integration/silex-native-bootstrap/ubuntu-sdk.json', 1024 * 1024,
                      owner=uid, modes=(0o644,))
    S.require(hashlib.sha256(manifest).hexdigest() == S.SDK, 'source')
    records = sdk.records_from_manifest(manifest)
    root_value = S.parse(S.read(temporary / 'silex-native-sdk-install-root.json', S.MAX_JSON, owner=uid))
    outer = S.parse(S.read(temporary / 'silex-native-sdk-install.json', S.MAX_JSON, owner=uid))
    sdk.check_root(root_value, revision, records)
    S.require(root_value.keys() == ROOT_RECEIPT_KEYS and root_value['admission_diagnostic'] == {'substage': 'complete'}
              and root_value['run_id'] == os.environ['GITHUB_RUN_ID']
              and root_value['run_attempt'] == os.environ['GITHUB_RUN_ATTEMPT'], 'source')
    S.require(type(outer) is dict and outer.keys() == OUTER_RECEIPT_KEYS and type(outer.get('schema')) is int
        and outer.get('schema') == 1
        and outer.get('mode') == 'native-sdk-offline-install' and outer.get('status') == 'passed'
        and outer.get('stage') == 'complete' and outer.get('studio_revision') == revision
        and outer.get('sdk_manifest_sha256') == S.SDK and outer.get('packages_installed') is True
        and outer.get('sdk_installed') is True and outer.get('hashes') == sdk.expected_hashes(records)
        and outer.get('verified_package_count') == 182 and outer.get('archive_bytes') == 63772228
        and outer.get('admission_diagnostic') == {'substage': 'complete'}
        and outer.get('cleanup') == dict(owned_group_count=1, owned_groups_joined=True,
                package_rollback_attempted=False, root_cache_retained=True)
        and all(outer.get(name) is False for name in sdk.FALSE_FLAGS), 'source')
    S.require(hashlib.sha256(S.read(HERE / 'inventory.py', S.MAX_SOURCE, owner=uid,
                                   modes=(0o644,))).hexdigest() == INVENTORY_SOURCE, 'source')
    raw = S.read(temporary / 'silex-native-runtime-inventory.json', S.MAX_JSON, owner=uid)
    inventory = S.parse(raw)
    S.require(type(inventory) is dict and inventory.keys() == INVENTORY_KEYS and type(inventory.get('schema')) is int
        and inventory['schema'] == 1 and inventory.get('operation') == 'native-runtime-prerequisite-inventory'
        and inventory.get('studio_revision') == revision and inventory.get('status') == 'passed'
        and inventory.get('stage') == 'complete' and inventory.get('readiness') == 'ready'
        and inventory.get('cleanup_confirmed') is True and type(inventory.get('owned_groups_started')) is int
        and inventory['owned_groups_started'] == inventory.get('owned_groups_joined')
        and 0 < inventory['owned_groups_started'] <= 384 and inventory.get('missing_providers') == []
        and inventory.get('simulation_performed') is False and inventory.get('installation_plan') == {}
        and inventory.get('installation_plan_sha256') is None
        and set(inventory.get('packages', {})) == PROVIDERS
        and set(inventory.get('tools', {})) == TOOLS.keys(), 'source')
    for name in ('packages_installed', 'archives_downloaded', 'archive_contents_verified',
            'namespaces_created', 'network_configuration_changed', 'display_started',
            'inventoried_tools_executed', 'compiler_or_node_executed', 'application_executed',
            'native_runtime_acceptance', 'full_studio_acceptance',
            'candidate_archive_signatures_independently_verified'):
        S.require(inventory.get(name) is False, 'source')
    for name, path in TOOLS.items():
        row = inventory['tools'][name]
        S.require(type(row) is dict and row.get('installed_provenance_verified') is True
            and row.get('provider') in PROVIDERS and type(row.get('binary')) is dict, 'source')
        binary = row['binary']
        S.require(binary.get('path') == path and binary.get('owner') == 0
            and type(binary.get('mode')) is int and binary['mode'] in (0o755, 0o4755)
            and (binary['mode'] == 0o755 or name == 'mount')
            and type(binary.get('bytes')) is int and 0 < binary['bytes'] <= 32 * 1024 * 1024
            and type(binary.get('sha256')) is str and re.fullmatch('[0-9a-f]{64}', binary['sha256']), 'source')
        observed = S.read(Path(path), 32 * 1024 * 1024, owner=0, modes=(binary['mode'],))
        S.require(len(observed) == binary['bytes'] and hashlib.sha256(observed).hexdigest() == binary['sha256'], 'source')
    return hashlib.sha256(raw).hexdigest()


def root_command(environment):
    # The source path is fixed relative to our admitted checkout. sudo's default
    # close-from behavior is retained: only the ordinary stdio pipes are used.
    return ['/usr/bin/sudo', '-n', '/usr/bin/env', '-i',
        *[key + '=' + value for key, value in sorted(environment.items())],
        '/usr/bin/python3', '-I', '-B', str(HERE / 'isolation_root.py'), '--privileged-supervisor']


def verify_root(value, revision, hashes):
    keys = {'schema', 'operation', 'status', 'stage', 'studio_revision', 'source_sha256', 'worker',
        'namespace_parent_joined', 'namespace_init_exit_confirmed', 'host_before_sha256', 'host_after_sha256',
        'host_network_configuration_unchanged', 'root_carrier_removed', 'source_groups_started',
        'source_groups_joined', 'owned_groups_started', 'owned_groups_joined', 'failure_kind'}
    S.require(type(value) is dict and value.keys() == keys and type(value['schema']) is int
        and value['schema'] == 1 and value['operation'] == 'root_isolation_supervisor'
        and value['status'] == 'passed' and value['stage'] == 'complete'
        and value['studio_revision'] == revision and value['source_sha256'] == hashes
        and value['failure_kind'] is None, 'protocol')
    S.require(all(value[name] is True for name in ('namespace_parent_joined', 'namespace_init_exit_confirmed',
        'host_network_configuration_unchanged', 'root_carrier_removed')), 'cleanup')
    for prefix in ('source_groups', 'owned_groups'):
        S.require(type(value[prefix + '_started']) is int and 0 < value[prefix + '_started'] <= 128
            and value[prefix + '_started'] == value[prefix + '_joined'], 'cleanup')
    host = value['host_before_sha256']
    S.require(type(host) is dict and host.keys() == {'routes_sha256', 'resolver_sha256',
        'firewall_configuration_sha256'} and all(type(v) is str and re.fullmatch('[0-9a-f]{64}', v)
        for v in host.values()) and value['host_after_sha256'] == host, 'host_changed')
    worker = value['worker']
    S.require(type(worker) is dict and worker.keys() == {'schema', 'operation', 'status', 'stage', 'admission',
        'calibration', 'namespace_groups_started', 'namespace_groups_joined', 'actors_started', 'actors_joined', 'owner_scope'}
        | {'failure_kind', 'actor_failure_predicate'}
        and type(worker['schema']) is int and worker['schema'] == 1
        and worker['operation'] == 'namespace_isolation_worker' and worker['status'] == 'passed'
        and worker['stage'] == 'complete' and worker['owner_scope'] == 'namespace_process_groups'
        and worker['failure_kind'] is None and worker['actor_failure_predicate'] is None
        and type(worker['namespace_groups_started']) is int and 0 < worker['namespace_groups_started'] <= 128
        and worker['namespace_groups_started'] == worker['namespace_groups_joined']
        and type(worker['actors_started']) is int and worker['actors_started'] == worker['actors_joined'] == 2, 'protocol')
    admission = worker['admission']
    S.require(type(admission) is dict and admission.keys() == S.ADMISSION | {'schema', 'operation', 'passed'}
        and type(admission['schema']) is int and admission['schema'] == 1
        and admission['operation'] == 'isolation_actor_admission' and admission['passed'] is True
        and all(admission[name] is True for name in S.ADMISSION), 'identity')
    calibration = worker['calibration']
    S.require(type(calibration) is dict and calibration.keys() == {'synthetic_actor', 'ipv4_attempts',
        'ipv6_attempts', 'ipv4_drop_packets', 'ipv6_drop_packets', 'dns_queries', 'dns_replies',
        'dns_output_packets', 'dns_reply_packets'} and calibration['synthetic_actor'] is True
        and all(type(v) is int and v == 1 for k, v in calibration.items() if k != 'synthetic_actor'), 'observer')
    return worker


def root_failure(raw, revision, hashes):
    """Validate request-bound failed stdout, project only a closed vocabulary.

    This is an observation after the original backend rejection, never an ack
    and never a reason to accept a child exit or mark cleanup confirmed.
    """
    value = S.parse(raw)
    S.require(type(value) is dict and type(value.get('schema')) is int and value['schema'] == 1
        and value.get('status') == 'failed' and value.get('studio_revision') == revision
        and value.get('failure_kind') in S.KINDS, 'protocol')
    common = {'schema', 'operation', 'status', 'studio_revision', 'stage', 'failure_kind',
        'source_groups_started', 'source_groups_joined', 'owned_groups_started', 'owned_groups_joined',
        'root_carrier_removed', 'host_before_sha256', 'host_after_sha256'}
    entry = value.get('operation') == 'root_isolation_entry_failure'
    worker = None
    if entry:
        S.require(value.keys() == common | {'source_verified', 'source_sha256'}
            and value['stage'] in S.ROOT_ENTRY_STAGES and type(value['source_verified']) is bool, 'protocol')
        verified = value['source_verified']
        S.require(value['source_sha256'] == (hashes if verified else None), 'source')
        S.require(verified is (value['stage'] in ('carrier_write', 'carrier_exec')), 'source')
        S.require(value['owned_groups_started'] is None and value['owned_groups_joined'] is None
                  and value['host_before_sha256'] is None and value['host_after_sha256'] is None, 'protocol')
    else:
        S.require(value.keys() == common | {'source_sha256', 'worker', 'namespace_parent_joined',
            'namespace_init_exit_confirmed', 'host_network_configuration_unchanged'}
            and value['operation'] == 'root_isolation_supervisor'
            and value['stage'] in S.ROOT_SUPERVISOR_STAGES and value['source_sha256'] == hashes, 'source')
        verified = True
        S.require(all(type(value[name]) is bool for name in ('namespace_parent_joined',
            'namespace_init_exit_confirmed', 'host_network_configuration_unchanged')), 'protocol')
        candidate = value['worker']
        if candidate is not None:
            S.require(type(candidate) is dict, 'protocol')
            if candidate.get('status') == 'failed':
                keys = {'schema', 'operation', 'status', 'stage', 'failure_kind',
                    'namespace_groups_started', 'namespace_groups_joined', 'actors_started',
                    'actors_joined', 'owner_scope', 'actor_failure_predicate'}
                S.require(candidate.keys() == keys and type(candidate['schema']) is int and candidate['schema'] == 1
                    and candidate['operation'] == 'namespace_isolation_worker'
                    and candidate['stage'] in S.WORKER_STAGES and candidate['failure_kind'] in S.KINDS
                    and candidate['owner_scope'] == 'namespace_process_groups'
                    and candidate['actor_failure_predicate'] in S.ACTOR_PREDICATES | {None}, 'protocol')
                S.require(all(type(candidate[name]) is int and 0 <= candidate[name] <= 128 for name in
                    ('namespace_groups_started', 'namespace_groups_joined', 'actors_started', 'actors_joined')), 'protocol')
                S.require(0 <= candidate['namespace_groups_joined'] <= candidate['namespace_groups_started'] <= 128
                    and 0 <= candidate['actors_joined'] <= candidate['actors_started'] <= 2, 'protocol')
                worker = {name: candidate[name] for name in ('stage', 'failure_kind',
                    'namespace_groups_started', 'namespace_groups_joined', 'actors_started',
                    'actors_joined', 'actor_failure_predicate')}
            else:
                # No successful worker detail is copied into a failure receipt.
                S.require(candidate.get('status') == 'passed', 'protocol')
    for prefix in ('source_groups', 'owned_groups'):
        started, joined = value[prefix + '_started'], value[prefix + '_joined']
        S.require((started is None and joined is None and entry)
            or (type(started) is int and type(joined) is int and 0 <= joined <= started <= 128), 'protocol')
    S.require(value['root_carrier_removed'] is None or type(value['root_carrier_removed']) is bool, 'protocol')
    for name in ('host_before_sha256', 'host_after_sha256'):
        host = value[name]
        S.require(host is None or (type(host) is dict and host.keys() == {
            'routes_sha256', 'resolver_sha256', 'firewall_configuration_sha256'}
            and all(type(v) is str and re.fullmatch('[0-9a-f]{64}', v) for v in host.values())), 'protocol')
    return dict(schema=1, operation='root_isolation_failure_observation',
        layer='root_entry' if entry else 'root_supervisor', stage=value['stage'],
        failure_kind=value['failure_kind'], source_verified=verified,
        source_groups_started=value['source_groups_started'], source_groups_joined=value['source_groups_joined'],
        owned_groups_started=value['owned_groups_started'], owned_groups_joined=value['owned_groups_joined'],
        root_carrier_removed=value['root_carrier_removed'], host_before_sha256=value['host_before_sha256'],
        host_after_sha256=value['host_after_sha256'], worker_failure=worker)


def retain_root_failure(primary, report, raw, revision, hashes):
    try:
        report['root_failure'] = root_failure(raw, revision, hashes)
    except BaseException:
        pass
    return primary


def publish_receipt(path, report, primary):
    """Terminal, no-replace commit after all actors/cleanup have completed.

    The caller MUST immediately exit with the returned signal mask still held.
    A signal pending at the precommit check converts PASS to failure. Signals
    arriving after that linearization point are deferred through process exit.
    No claim is made that an unresponsive filesystem can be interrupted here.
    """
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, S.SIGNALS)
    pending = path.with_name(path.name + '.pending')
    identity = None
    committed = False
    try:
        S.require(not path.exists() and not path.is_symlink()
                  and not pending.exists() and not pending.is_symlink(), 'filesystem')
        if signal.sigpending() & set(S.SIGNALS):
            primary = primary or S.Rejected('cancelled')
        report['status'] = 'passed' if primary is None else 'failed'
        if primary is not None:
            report['failure_kind'] = report['failure_kind'] or (
                primary.kind if isinstance(primary, S.Rejected) else 'cleanup')
        S.write_new(pending, S.encoded(report), mode=0o600)
        info = pending.lstat()
        identity = info.st_dev, info.st_ino
        # Also observe cancellation received during the bounded staging write.
        if primary is None and signal.sigpending() & set(S.SIGNALS):
            primary = S.Rejected('cancelled')
            report.update(status='failed', failure_kind='cancelled')
            pending.unlink()
            identity = None
            S.write_new(pending, S.encoded(report), mode=0o600)
            info = pending.lstat()
            identity = info.st_dev, info.st_ino
        os.link(pending, path, follow_symlinks=False)  # Atomic and no overwrite.
        committed = True
        # Public link is already complete and closed. A staging unlink error
        # cannot turn a committed PASS into exit failure.
        try:
            pending.unlink()
        except OSError:
            pass
    except BaseException as error:
        primary = primary or error
        if not committed and identity is not None:
            try:
                info = pending.lstat()
                if (info.st_dev, info.st_ino) == identity:
                    pending.unlink()
            except BaseException:
                pass
    return primary, previous


def main():
    started = time.monotonic_ns()
    work_ns, end_ns = started + 90_000_000_000, started + 120_000_000_000
    S.require(sys.argv == [str(HERE / 'isolation.py')] and os.getuid() == os.geteuid() != 0)
    root, revision = S.admission_environment()
    S.require(root == ROOT and Path(__file__).resolve() == HERE / 'isolation.py')
    uid, gid = os.geteuid(), os.getegid()
    S.require(ROOT.stat().st_uid == uid and os.getgid() == gid == pwd.getpwuid(uid).pw_gid)
    temporary = Path(os.environ['RUNNER_TEMP'])
    S.directory(temporary, uid)
    artifact = temporary / 'silex-native-isolation.json'
    S.require(not artifact.exists() and not artifact.is_symlink(), 'filesystem')
    lifecycle = S.load_lifecycle(ROOT / S.LIFECYCLE, S.LIFECYCLE_SHA, uid)
    owner = S.Owner(lifecycle, work_ns / 1e9, end_ns / 1e9, control=False)
    private = temporary / 'silex-native-isolation-private-v1'
    ipc_canary = Path('/dev/shm/volparossa-native-isolation-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT'])
    primary = None
    private_created = False
    ipc_created = False
    private_identity = ipc_identity = None
    root_acknowledged = False
    report = dict(schema=1, operation='native_isolation_admission_calibration', status='failed', stage='source',
        studio_revision=revision, source_sha256=None, sdk_manifest_sha256=S.SDK,
        runtime_inventory_sha256=None, root_result=None, root_failure=None,
        failure_kind=None,
        controller_groups_started=0, controller_groups_joined=0,
        private_work_removed=False, host_ipc_canary_removed=False, cleanup_confirmed=False,
        **dict.fromkeys(S.SCOPES, False))
    try:
        payloads = S.source_payloads(owner, ROOT, revision, uid)
        hashes = {label: hashlib.sha256(raw).hexdigest() for label, raw in payloads.items()}
        report['source_sha256'] = hashes
        report['stage'] = 'prerequisites'
        report['runtime_inventory_sha256'] = prerequisites(temporary, revision, uid)
        private.mkdir(mode=0o700)
        private_created = True
        private_identity = S.directory(private, uid, private=True)
        S.write_new(private / 'host-canary', b'public host-view canary\n', mode=0o600)
        S.write_new(ipc_canary, b'public host IPC canary\n', mode=0o600)
        ipc_created = True
        info = ipc_canary.lstat()
        ipc_identity = info.st_dev, info.st_ino
        environment = {key: os.environ[key] for key in S.HOST_KEYS}
        environment.update(S.ENV, VP_ISOLATION_UID=str(uid), VP_ISOLATION_GID=str(gid),
                           VP_ISOLATION_WORK_NS=str(work_ns), VP_ISOLATION_END_NS=str(end_ns))
        report['stage'] = 'root_supervisor'
        raw = owner.run(root_command(environment), environment=S.ENV, payload=S.BOOT,
                        keep_stdin=True, cooperative=True, seconds=90, role='root')
        value = S.parse(raw)
        verify_root(value, revision, hashes)
        report['root_result'] = value
        root_acknowledged = True
        S.require(S.source_payloads(owner, ROOT, revision, uid) == payloads, 'source')
        report['stage'] = 'complete'
    except BaseException as error:
        primary = error
        report['failure_kind'] = error.kind if isinstance(error, S.Rejected) else 'admission'
        if report['stage'] == 'root_supervisor':
            primary = retain_root_failure(primary, report, owner.last_output, revision, report['source_sha256'])
    finally:
        def finish():
            S.require(owner.started == owner.joined, 'cleanup')
            # A joined sudo/root leader alone says nothing about its separate
            # unshare session. Require the closed nested acknowledgement before
            # claiming cleanup or discarding fixture inputs after a root launch.
            S.require(owner.roles_started['root'] == 0 or root_acknowledged, 'cleanup')
            if private_created:
                S.require(S.directory(private, uid, private=True) == private_identity, 'cleanup')
                S.require({p.name for p in private.iterdir()} == {'host-canary'}, 'cleanup')
                shutil.rmtree(private)
            else:
                S.require(not private.exists() and not private.is_symlink(), 'cleanup')
            report['private_work_removed'] = True
            if ipc_created:
                current = ipc_canary.lstat()
                S.require((current.st_dev, current.st_ino) == ipc_identity, 'cleanup')
                S.require(S.read(ipc_canary, 128, owner=uid) == b'public host IPC canary\n', 'cleanup')
                ipc_canary.unlink()
            else:
                S.require(not ipc_canary.exists() and not ipc_canary.is_symlink(), 'cleanup')
            report['host_ipc_canary_removed'] = True
            report['cleanup_confirmed'] = True
        primary = S.masked_cleanup(primary, finish)
        report.update(controller_groups_started=owner.started, controller_groups_joined=owner.joined)
        if primary is None:
            report['status'] = 'passed'
        else:
            report['failure_kind'] = report['failure_kind'] or (primary.kind if isinstance(primary, S.Rejected) else 'cleanup')
    # No raw logs, addresses or DNS question. Exit immediately: do not restore
    # raising handlers after committing an accepted public receipt.
    primary, _previous_mask = publish_receipt(artifact, report, primary)
    os._exit(0 if primary is None else 1)


if __name__ == '__main__':
    def cancelled(number, _frame):
        raise S.Rejected('deadline' if number == signal.SIGALRM else 'cancelled')
    for number in S.SIGNALS:
        signal.signal(number, cancelled)
    signal.setitimer(signal.ITIMER_REAL, 90)
    try:
        main()
    except BaseException:
        raise SystemExit(1) from None
