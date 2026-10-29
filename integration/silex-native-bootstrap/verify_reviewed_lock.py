#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Verify one separately reviewed native lock candidate; never relax the generic resolver.

Only the exact candidate is admitted. Its reviewed transitive feature reductions
are distinct from the generic resolver's deliberately narrower desktop-only rule.
"""
import importlib.util
import json
import os
from pathlib import Path
import signal
import time

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('native_reviewed_lock_support', HERE / 'resolve_lock.py')
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)

CANDIDATE = 'de04aaf5ff1acbdde421e3447ea67f3eb7a00a7d5ed118f4387a180e84590118'
PACKAGES = 563
REVIEWED_FEATURE_CASES = ('libredox_redox_0_7', 'rustls_ring', 'uikit_nine_optional_edges')


def check_candidate(raw):
    SUPPORT.require(SUPPORT.digest(raw) == CANDIDATE, 'source_rejected')
    _version, records = SUPPORT.ledger(raw)
    SUPPORT.require(len(records) == PACKAGES, 'ledger_rejected')
    return len(records)


def unchanged(source, original, before_source, env, deadline, counts):
    current = SUPPORT.read(source / 'Cargo.lock')
    SUPPORT.require(current == original, 'source_rejected')
    check_candidate(current)
    SUPPORT.require(SUPPORT.snapshot(source, env, deadline, counts) == before_source, 'source_rejected')


def main():
    parser = SUPPORT.Parser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    counts = {'started': 0, 'joined': 0}
    report = {'schema': 1, 'operation': 'native_reviewed_lock', 'status': 'failed', 'stage': 'admission',
              'failure_kind': 'admission', 'source_commit': SUPPORT.UPSTREAM,
              'base_lock_sha256': SUPPORT.BASE_LOCK, 'baseline_package_records': 607,
              'candidate_lock_sha256': CANDIDATE, 'root_lock_sha256': None, 'package_records': None,
              'only_desktop_dependency_delta': False, 'reviewed_transitive_feature_reductions': False,
              'reviewed_feature_reduction_cases': list(REVIEWED_FEATURE_CASES),
              'offline_locked_metadata_passed': False, 'source_unchanged': False,
              'owned_children_started': 0, 'owned_children_joined': 0, 'owned_child_cleanup_confirmed': False,
              'native_build': False, 'native_runtime_privacy': False, 'native_gui_executed': False,
              'sdk_installed': False, 'locked_dependency_acceptance': False,
              'independently_authorized_volparossa_updates': False, 'full_studio': False}
    artifact = None
    primary = None
    deadline = time.monotonic() + 178
    try:
        temporary = Path(os.environ.get('RUNNER_TEMP', ''))
        SUPPORT.verify_source(args.source, temporary, deadline, counts, patched=True)
        artifact = temporary / 'silex-native-reviewed-lock.json'
        SUPPORT.require(not artifact.exists() and not artifact.is_symlink(), 'artifact_failed')
        original = SUPPORT.read(args.source / 'Cargo.lock')
        report['package_records'] = check_candidate(original)
        report.update(root_lock_sha256=SUPPORT.digest(original), reviewed_transitive_feature_reductions=True)
        env = SUPPORT.environment(args.source, temporary)
        before_source = SUPPORT.snapshot(args.source, env, deadline, counts)
        cargo = str(temporary / 'volparossa-rust-1.99.1/bin/cargo')
        report['stage'] = 'locked_metadata'
        raw = SUPPORT.run([cargo, 'metadata', '--offline', '--locked', '--format-version=1'], env,
                          args.source, deadline, counts, stdout_limit=SUPPORT.MAX_METADATA_BYTES)
        SUPPORT.metadata(raw, args.source)
        unchanged(args.source, original, before_source, env, deadline, counts)
        SUPPORT.verify_source(args.source, temporary, deadline, counts, patched=True)
        report.update(status='passed', stage='complete', failure_kind=None,
                      offline_locked_metadata_passed=True, source_unchanged=True)
    except BaseException as error:
        primary = error
        report['failure_kind'] = (error.kind if isinstance(error, SUPPORT.Rejected) else
                                  'deadline' if isinstance(error, SUPPORT.subprocess.TimeoutExpired) else
                                  'cancelled' if isinstance(error, KeyboardInterrupt) else 'source_rejected')
    finally:
        report.update(owned_children_started=counts['started'], owned_children_joined=counts['joined'],
                      owned_child_cleanup_confirmed=counts['started'] == counts['joined'])
        if counts['started'] != counts['joined']:
            report['status'] = 'failed'
            if primary is None:
                primary = SUPPORT.Rejected('cleanup_unconfirmed')
                report['failure_kind'] = 'cleanup_unconfirmed'
        raw = (json.dumps(report, sort_keys=True) + '\n').encode()
        if artifact is not None:
            try:
                SUPPORT.write_new(artifact, raw)
            except BaseException:
                primary = primary or SUPPORT.Rejected('artifact_failed')
                report.update(status='failed', failure_kind=report['failure_kind'] or 'artifact_failed')
                raw = (json.dumps(report, sort_keys=True) + '\n').encode()
        print(raw.decode().rstrip())
    if primary is not None:
        raise primary


if __name__ == '__main__':
    def cancelled(_number, _frame):
        raise SUPPORT.Rejected('cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancelled)
    try:
        main()
    except BaseException:
        raise SystemExit(1) from None
