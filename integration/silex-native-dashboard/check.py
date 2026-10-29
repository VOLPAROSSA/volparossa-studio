#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run only the source-bound dashboard unit fixture on an approved hosted runner."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOOTSTRAP = HERE.parent / 'silex-native-bootstrap'
NATIVE_HELPER = '9d8d45fe88922ced9ee43a0465177343f7b3757f6e9a28dc30884b0e3a03f51c'
FILES = {'index.html', 'dashboard.css', 'dashboard.js', 'test_dashboard.mjs'}


def require(value):
    if not value:
        raise RuntimeError('dashboard_unit_rejected')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_manifest(value):
    require(type(value) is dict and value.keys() == {'schema', 'operation', 'files', 'tests', 'scope'})
    require(type(value['schema']) is int and value['schema'] == 1
            and value['operation'] == 'original_local_dashboard_units')
    require(type(value['files']) is dict and value['files'].keys() == FILES)
    for row in value['files'].values():
        require(type(row) is dict and row.keys() == {'bytes', 'sha256'}
                and type(row['bytes']) is int and 0 < row['bytes'] <= 65536
                and type(row['sha256']) is str and re.fullmatch('[0-9a-f]{64}', row['sha256']))
    require(type(value['tests']) is list and 1 <= len(value['tests']) <= 64
            and len(set(value['tests'])) == len(value['tests']))
    require(all(type(name) is str and re.fullmatch(r'[A-Za-z0-9 ,:/().?+_-]{1,200}', name)
                for name in value['tests']))
    require(value['scope'] == {'unit_fixture_only': True, 'native_gui': False,
                              'real_server_crud': False, 'publication_authorized': False})


def check_tap(raw, expected):
    require(len(raw) <= 2 * 1024 * 1024)
    text = raw.decode('utf-8', errors='strict')
    names = re.findall(r'^# Subtest: (.+)$', text, re.MULTILINE)
    require(names == expected)
    require(not re.search(r'^not ok\b|# (?:SKIP|TODO)\b', text, re.MULTILINE))
    totals = {}
    for key in ('tests', 'suites', 'pass', 'fail', 'cancelled', 'skipped', 'todo'):
        values = re.findall(r'^# ' + key + r' ([0-9]+)$', text, re.MULTILINE)
        require(len(values) == 1)
        totals[key] = int(values[0])
    require(totals == {'tests': len(expected), 'suites': 0, 'pass': len(expected),
                       'fail': 0, 'cancelled': 0, 'skipped': 0, 'todo': 0})
    require(len(re.findall(r'^ok [0-9]+ - ', text, re.MULTILINE)) == len(expected))
    require(re.findall(r'^1\.\.([0-9]+)$', text, re.MULTILINE) == [str(len(expected))])


def source_snapshot(native, rows):
    result = {}
    for name, row in rows.items():
        raw = native.read_file(HERE / 'app' / name, 65536)
        require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'])
        result[name] = hashlib.sha256(raw).hexdigest()
    return result


def publish_receipt(artifact, raw):
    """The public name appears only after a complete, closed private write.

    A failed/partial write remains outside the workflow's artifact allowlist.
    The fixed private staging name is never replaced or borrowed from another
    caller. Its removal after publication is part of publication housekeeping.
    """
    require(len(raw) <= 65536)
    staging = artifact.with_name('.' + artifact.name + '.pending')
    owned = None
    try:
        descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            stream = os.fdopen(descriptor, 'wb')
        except BaseException:
            try:
                os.close(descriptor)
            except BaseException:
                pass
            raise
        with stream:
            owned = os.fstat(stream.fileno())
            require(stream.write(raw) == len(raw))
            stream.flush()
            os.fsync(stream.fileno())
        current = staging.lstat()
        require((current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino)
                and stat.S_ISREG(current.st_mode) and current.st_uid == os.geteuid()
                and stat.S_IMODE(current.st_mode) == 0o600 and current.st_nlink == 1
                and current.st_size == len(raw))
        os.link(staging, artifact, follow_symlinks=False)
    finally:
        if owned is not None:
            try:
                current = staging.lstat()
                if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                    staging.unlink()
            except FileNotFoundError:
                pass
            except BaseException:
                # Publication is already committed or already failed. This
                # bounded public JSON staging file is never an uploaded path.
                pass


def finish(artifact, work, report, groups, primary, *, child_attempted, work_created, ready):
    """Terminal commit: precommit cancellation fails; publication is noncancellable.

    All child/project actions and owned tool cleanup finish before this boundary.
    Pending precommit signals and every original-handler restore are checked.
    Thereafter only receipt publication remains: terminal nonthrowing handlers
    prevent a later signal from contradicting a committed receipt. This function
    is exclusively for this standalone checker's final action, not reusable work.
    """
    numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)
    previous = {number: signal.getsignal(number) for number in numbers}
    pending = set()
    old_mask = None
    try:
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
    except BaseException as error:
        primary = primary or error
    try:
        for number in numbers:
            try:
                signal.signal(number, lambda number, _frame: pending.add(number))
            except BaseException as error:
                primary = primary or error
    finally:
        try:
            if old_mask is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        except BaseException as error:
            primary = primary or error
    # Carrier acquisition uses only in-process bounded download/extraction. A
    # failed attempted actor with no measured group remains unconfirmed.
    confirmed = all(groups) and (bool(groups) or not child_attempted)
    report.update(owned_group_count=len(groups), owned_groups_joined=confirmed)
    if not confirmed:
        primary = primary or RuntimeError('dashboard_cleanup_unconfirmed')
    if confirmed and work_created:
        try:
            shutil.rmtree(work)
            report['private_tool_tree_removed'] = True
        except BaseException as error:
            primary = primary or error
    elif confirmed:
        report['private_tool_tree_removed'] = True  # No owned tree was created.
    publication_mask = None
    try:
        publication_mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
    except BaseException as error:
        primary = primary or error
    try:
        for number, handler in previous.items():
            try:
                signal.signal(number, handler)
            except BaseException as error:
                primary = primary or error
        pending.update(signal.sigpending().intersection(numbers))
        if pending:
            primary = primary or RuntimeError('dashboard_precommit_cancelled')
        # The original handlers were all restored/checked. Replace them only
        # for this terminal publication/exit, when no work may follow.
        for number in numbers:
            try:
                signal.signal(number, lambda _number, _frame: None)
            except BaseException as error:
                primary = primary or error
        pending.update(signal.sigpending().intersection(numbers))
        if pending:
            primary = primary or RuntimeError('dashboard_precommit_cancelled')
        passed = (primary is None and ready and confirmed
                  and report['private_tool_tree_removed'] is True)
        if not passed:
            primary = primary or RuntimeError('dashboard_preconditions_unconfirmed')
        report.update(status='passed' if passed else 'failed')
        if passed:
            report['stage'] = 'complete'
        # COMMIT BOUNDARY. No child, project read/write or tool cleanup follows.
        try:
            publish_receipt(artifact, (json.dumps(report, sort_keys=True) + '\n').encode())
        except BaseException as error:
            primary = primary or error  # Failure receipt is best effort only.
            report['status'] = 'failed'
    except BaseException as error:
        primary = primary or error
    finally:
        try:
            if publication_mask is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, publication_mask)
        except BaseException as error:
            # A synthetic late cancellation cannot negate valid publication;
            # a prior primary remains authoritative on the failure path.
            if primary is None and report['status'] != 'passed':
                primary = error
    return primary


def main():
    require(sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1
            and sys.argv == [str(HERE / 'check.py')])
    require(hashlib.sha256((BOOTSTRAP / 'native_build.py').read_bytes()).hexdigest() == NATIVE_HELPER)
    native = load('dashboard_unit_native_support', BOOTSTRAP / 'native_build.py')
    fetch = load('dashboard_unit_host_support', BOOTSTRAP / 'fetch_sdk.py')
    original = sys.argv
    try:
        sys.argv = [str(BOOTSTRAP / 'fetch_sdk.py')]
        temporary, revision = fetch.admission()
    finally:
        sys.argv = original
    require(ROOT == Path(os.environ['GITHUB_WORKSPACE']) / 'studio')
    artifact = temporary / 'silex-original-dashboard-units.json'
    require(not artifact.exists() and not artifact.is_symlink())
    manifest_raw = native.read_file(HERE / 'manifest.json', 65536)
    manifest = native.SUPPORT.json_value(manifest_raw)
    validate_manifest(manifest)
    before = source_snapshot(native, manifest['files'])
    work = temporary / 'silex-original-dashboard-unit-private'
    groups = []
    primary = None
    child_attempted = work_created = ready = False
    deadline = time.monotonic() + 360
    report = dict(schema=1, operation='original_local_dashboard_units', status='failed',
                  stage='carrier', studio_revision=revision,
                  manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                  source_sha256=before, tests=0, passed=0, failed=0, skipped=0,
                  tap_sha256=None, source_unchanged=False, owned_groups_joined=False,
                  owned_group_count=0, private_tool_tree_removed=False,
                  unit_fixture_only=True, unit_js_executed=False, native_gui=False,
                  real_server_crud=False, native_application_executed=False,
                  metadata_atomicity_verified=False, publication_authorized=False,
                  full_studio_acceptance=False)
    try:
        work.mkdir(mode=0o700)
        work_created = True
        node, _pnpm, _pins = native.export_carrier(work)
        lifecycle = sys.modules['lifecycle']
        for name in ('home', 'tmp'):
            (work / name).mkdir(mode=0o700)
        environment = dict(PATH=str(node.parent) + ':/usr/bin:/bin', HOME=str(work / 'home'),
                           TMPDIR=str(work / 'tmp'), LANG='C.UTF-8', LC_ALL='C.UTF-8', TZ='UTC')
        report['stage'] = 'unit_fixture'
        child_attempted = True
        raw = native.actor([node, '--test', '--test-concurrency=1', '--test-reporter=tap',
                            HERE / 'app/test_dashboard.mjs'], environment, ROOT,
                           deadline, groups, lifecycle, seconds=90)
        report['unit_js_executed'] = True
        check_tap(raw, manifest['tests'])
        report.update(tests=len(manifest['tests']), passed=len(manifest['tests']),
                      tap_sha256=hashlib.sha256(raw).hexdigest())
        require(source_snapshot(native, manifest['files']) == before)
        require(not fetch.support.git('status', '--porcelain=v1', '-z', '--untracked-files=all'))
        report['source_unchanged'] = True
        ready = True
    except BaseException as error:
        primary = error
    finally:
        primary = finish(artifact, work, report, groups, primary, child_attempted=child_attempted,
                         work_created=work_created, ready=ready)
    if primary is not None:
        raise primary
    print('ORIGINAL_DASHBOARD_UNITS=true; REAL_CRUD=false; NATIVE_GUI=false')


if __name__ == '__main__':
    def cancelled(_number, _frame):
        raise RuntimeError('dashboard_cancelled_or_deadline')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(number, cancelled)
    signal.setitimer(signal.ITIMER_REAL, 390)
    try:
        main()
    except BaseException:
        raise SystemExit(1) from None
