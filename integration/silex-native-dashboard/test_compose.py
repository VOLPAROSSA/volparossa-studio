# SPDX-License-Identifier: GPL-3.0-only
"""Hosted-only controls for original assets and refusal before source overwrite."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('dashboard_compose', Path(__file__).with_name('compose.py'))
COMPOSE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPOSE)


class TrackedFDs:
    """Observe only adapter-owned os.open/close, allowing FD-number reuse."""
    def __init__(self):
        self.active = {}
        self.closed = []
        self.real_open = os.open
        self.real_close = os.close

    def open(self, path, flags, *args, **kwargs):
        descriptor = self.real_open(path, flags, *args, **kwargs)
        self.active[descriptor] = (path, flags, kwargs)
        return descriptor

    def close(self, descriptor):
        self.real_close(descriptor)
        self.active.pop(descriptor)
        self.closed.append(descriptor)


class DeferredSignals:
    """Controlled pending delivery; no real process signals are sent."""
    def __init__(self):
        self.original = {COMPOSE.signal.SIGUSR1}
        self.blocked = set(self.original)
        self.pending = 0
        self.queued = 0
        self.cancellation = KeyboardInterrupt('controlled repeated cancellation')

    def queue(self):
        if not set(COMPOSE.SIGNALS) <= self.blocked:
            raise self.cancellation
        self.pending += 2
        self.queued += 2

    def mask(self, operation, numbers):
        previous = set(self.blocked)
        if operation == COMPOSE.signal.SIG_BLOCK:
            self.blocked.update(numbers)
        else:
            self.blocked = set(numbers)
        if self.pending and not set(COMPOSE.SIGNALS) <= self.blocked:
            self.pending = 0
            raise self.cancellation
        return previous


class ComposeTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'silex'
        source.mkdir(mode=0o700)
        target = source / 'silex-dashboard-2026'
        target.mkdir(mode=0o700)
        env = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                   GITHUB_REPOSITORY='VOLPAROSSA/volparossa-studio', GITHUB_WORKSPACE=str(root))
        return source, target, env

    def test_exact_original_assets_without_tests_or_upstream_fetch(self):
        content, digest = COMPOSE.assets()
        self.assertEqual(set(content), set(COMPOSE.ASSETS))
        self.assertEqual(len(digest), 64)
        with tempfile.TemporaryDirectory() as directory:
            source, target, env = self.fixture(Path(directory))
            with patch.dict(os.environ, env, clear=True):
                receipt = COMPOSE.install(source)
            self.assertEqual(sorted(p.name for p in target.iterdir()), ['public'])
            self.assertEqual(set(p.name for p in (target / 'public').iterdir()), set(COMPOSE.ASSETS))
            for name in COMPOSE.ASSETS:
                self.assertEqual((target / 'public' / name).read_bytes(), content[name])
                self.assertEqual(COMPOSE.stat.S_IMODE((target / 'public' / name).stat().st_mode), 0o600)
            self.assertEqual(COMPOSE.stat.S_IMODE((target / 'public').stat().st_mode), 0o700)
            self.assertEqual(receipt['asset_count'], 3)
            self.assertFalse(receipt['application_executed'])
            self.assertFalse(receipt['native_gui_verified'])
            self.assertFalse(receipt['redistribution_acceptance'])

    def test_existing_dashboard_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, env = self.fixture(Path(directory))
            sentinel = target / 'upstream-public-fixture'
            sentinel.write_bytes(b'preserved')
            with patch.dict(os.environ, env, clear=True), self.assertRaises(COMPOSE.Rejected):
                COMPOSE.install(source)
            self.assertEqual(sentinel.read_bytes(), b'preserved')
            self.assertFalse((target / 'public').exists())

    def test_non_hosted_and_wrong_source_refuse_before_asset_or_destination_access(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, env = self.fixture(Path(directory))
            for changes, path in (({'GITHUB_ACTIONS': 'false'}, source),
                                  ({'RUNNER_ENVIRONMENT': 'self-hosted'}, source),
                                  ({}, target)):
                with self.subTest(changes=changes, path=path), patch.dict(os.environ, env | changes, clear=True), \
                        patch.object(COMPOSE, 'assets') as reader, self.assertRaises(COMPOSE.Rejected):
                    COMPOSE.install(path)
                reader.assert_not_called()
            self.assertEqual(list(target.iterdir()), [])

    def test_symlink_gitlink_cannot_select_outside_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, env = self.fixture(Path(directory))
            outside = Path(directory) / 'outside'
            outside.mkdir()
            target.rmdir()
            target.symlink_to(outside, target_is_directory=True)
            with patch.dict(os.environ, env, clear=True), self.assertRaises(OSError):
                COMPOSE.install(source)
            self.assertEqual(list(outside.iterdir()), [])

    def test_partial_copy_failure_removes_only_its_own_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, env = self.fixture(Path(directory))
            original = OSError('public injected fsync failure')
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(COMPOSE.os, 'fsync', side_effect=original), \
                    self.assertRaises(OSError) as caught:
                COMPOSE.install(source)
            self.assertIs(caught.exception, original)
            self.assertEqual(list(target.iterdir()), [])

    def test_manifest_duplicate_extra_asset_and_changed_digest_are_rejected(self):
        raw = (COMPOSE.HERE / 'manifest.json').read_bytes()
        value = json.loads(raw)
        candidates = [b'{"schema":1,"schema":1}', json.dumps(value | {'unexpected': True}).encode()]
        changed = json.loads(raw)
        changed['files']['index.html']['sha256'] = '0' * 64
        candidates.append(json.dumps(changed).encode())
        changed = json.loads(raw)
        changed['files']['external.js'] = changed['files']['index.html']
        candidates.append(json.dumps(changed).encode())
        original = COMPOSE.read
        for candidate in candidates:
            def read(path, maximum):
                return candidate if path.name == 'manifest.json' else original(path, maximum)
            with self.subTest(candidate=candidate[:32]), patch.object(COMPOSE, 'read', side_effect=read), \
                    self.assertRaises(COMPOSE.Rejected):
                COMPOSE.assets()

    def test_asset_read_refuses_symlinks_and_world_writable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public'
            path.write_bytes(b'public fixture')
            alias = Path(directory) / 'alias'
            alias.symlink_to(path)
            with self.assertRaises(COMPOSE.Rejected):
                COMPOSE.read(alias, 64)
            path.chmod(0o622)
            with self.assertRaises(COMPOSE.Rejected):
                COMPOSE.read(path, 64)
            path.chmod(0o600)
            os.link(path, Path(directory) / 'hardlink')
            with self.assertRaises(COMPOSE.Rejected):
                COMPOSE.read(path, 64)

    def test_fdopen_is_not_an_ownership_boundary_for_read_copy_or_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _target, env = self.fixture(Path(directory))
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(COMPOSE.os, 'fdopen', side_effect=OSError('must never be called')) as fdopen:
                receipt = COMPOSE.install(source)
            fdopen.assert_not_called()
            self.assertEqual(receipt['asset_count'], 3)

    def test_fstat_failure_closes_read_write_and_verification_descriptors_without_false_success(self):
        for phase in ('read', 'write', 'verify'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, target, env = self.fixture(root)
                path = root / 'public-input'
                path.write_bytes(b'public input')
                tracked = TrackedFDs()
                real_stat = os.fstat
                original = OSError('controlled fstat failure')
                def metadata(descriptor):
                    selected, flags, options = tracked.active[descriptor]
                    selected_asset = options.get('dir_fd') is not None and selected in COMPOSE.ASSETS
                    if (phase == 'read' or phase == 'write' and selected_asset and flags & os.O_WRONLY
                            or phase == 'verify' and selected_asset and not flags & os.O_WRONLY):
                        raise original
                    return real_stat(descriptor)
                with patch.dict(os.environ, env, clear=True), \
                        patch.object(COMPOSE.os, 'open', side_effect=tracked.open), \
                        patch.object(COMPOSE.os, 'close', side_effect=tracked.close), \
                        patch.object(COMPOSE.os, 'fstat', side_effect=metadata), \
                        self.assertRaises(OSError) as caught:
                    COMPOSE.read(path, 64) if phase == 'read' else COMPOSE.install(source)
                self.assertIs(caught.exception, original)
                self.assertFalse(tracked.active)
                self.assertTrue(tracked.closed)
                if phase == 'write':
                    # Inode capture failed: this path is deliberately retained,
                    # not falsely certified as owned/rolled back. Abandon tree.
                    self.assertTrue((target / 'public' / COMPOSE.ASSETS[0]).exists())

    def test_open_unmask_cancellation_does_not_lose_an_unassigned_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public-input'
            path.write_bytes(b'public input')
            tracked = TrackedFDs()
            signals = DeferredSignals()
            def acquire(*args, **kwargs):
                descriptor = tracked.open(*args, **kwargs)
                signals.queue()
                return descriptor
            with patch.object(COMPOSE.os, 'open', side_effect=acquire), \
                    patch.object(COMPOSE.os, 'close', side_effect=tracked.close), \
                    patch.object(COMPOSE.signal, 'pthread_sigmask', side_effect=signals.mask), \
                    self.assertRaises(KeyboardInterrupt) as caught:
                COMPOSE.read(path, 64)
            self.assertIs(caught.exception, signals.cancellation)
            self.assertFalse(tracked.active)
            self.assertEqual(len(tracked.closed), 1)
            self.assertEqual(signals.blocked, signals.original)

    def test_repeated_cleanup_cancellation_preserves_primary_and_closes_all_owned_descriptors(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, env = self.fixture(Path(directory))
            tracked = TrackedFDs()
            signals = DeferredSignals()
            original = OSError('controlled copy fsync failure')
            cleanup_started = False
            real_unlink = os.unlink
            def fail_sync(_descriptor):
                nonlocal cleanup_started
                cleanup_started = True
                raise original
            def remove(*args, **kwargs):
                signals.queue()
                return real_unlink(*args, **kwargs)
            def close(descriptor):
                if cleanup_started:
                    signals.queue()
                tracked.close(descriptor)
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(COMPOSE.os, 'open', side_effect=tracked.open), \
                    patch.object(COMPOSE.os, 'close', side_effect=close), \
                    patch.object(COMPOSE.os, 'unlink', side_effect=remove), \
                    patch.object(COMPOSE.os, 'fsync', side_effect=fail_sync), \
                    patch.object(COMPOSE.signal, 'pthread_sigmask', side_effect=signals.mask), \
                    self.assertRaises(OSError) as caught:
                COMPOSE.install(source)
            self.assertIs(caught.exception, original)
            self.assertFalse(tracked.active)
            self.assertGreaterEqual(signals.queued, 10)
            self.assertEqual(signals.blocked, signals.original)
            self.assertEqual(list(target.iterdir()), [])

    def test_late_cancel_during_final_directory_close_cannot_return_a_success_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, env = self.fixture(Path(directory))
            tracked = TrackedFDs()
            signals = DeferredSignals()
            real_stat = os.fstat
            def close(descriptor):
                if COMPOSE.stat.S_ISDIR(real_stat(descriptor).st_mode):
                    signals.queue()
                tracked.close(descriptor)
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(COMPOSE.os, 'open', side_effect=tracked.open), \
                    patch.object(COMPOSE.os, 'close', side_effect=close), \
                    patch.object(COMPOSE.signal, 'pthread_sigmask', side_effect=signals.mask), \
                    self.assertRaises(KeyboardInterrupt) as caught:
                COMPOSE.install(source)
            self.assertIs(caught.exception, signals.cancellation)
            self.assertFalse(tracked.active)
            self.assertEqual(signals.blocked, signals.original)
            # This is an exception, not confirmed rollback. Caller discards tree.
            self.assertEqual(set(p.name for p in (target / 'public').iterdir()), set(COMPOSE.ASSETS))

    def test_close_failure_does_not_skip_other_owned_descriptors_or_replace_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _target, env = self.fixture(Path(directory))
            tracked = TrackedFDs()
            original = OSError('controlled fsync failure')
            attempted = []
            cleanup_started = False
            def sync(_descriptor):
                nonlocal cleanup_started
                cleanup_started = True
                raise original
            def close(descriptor):
                tracked.close(descriptor)
                if cleanup_started:
                    attempted.append(descriptor)
                    raise OSError('controlled ambiguous close failure')
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(COMPOSE.os, 'open', side_effect=tracked.open), \
                    patch.object(COMPOSE.os, 'close', side_effect=close), \
                    patch.object(COMPOSE.os, 'fsync', side_effect=sync), \
                    self.assertRaises(OSError) as caught:
                COMPOSE.install(source)
            self.assertIs(caught.exception, original)
            self.assertFalse(tracked.active)
            self.assertEqual(len(attempted), 4)

    def test_failure_after_mkdir_before_public_open_retains_unknown_directory_and_closes_parents(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, env = self.fixture(Path(directory))
            tracked = TrackedFDs()
            original = OSError('controlled public-open failure')
            def acquire(path, *args, **kwargs):
                if path == 'public':
                    raise original
                return tracked.open(path, *args, **kwargs)
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(COMPOSE.os, 'open', side_effect=acquire), \
                    patch.object(COMPOSE.os, 'close', side_effect=tracked.close), \
                    self.assertRaises(OSError) as caught:
                COMPOSE.install(source)
            self.assertIs(caught.exception, original)
            self.assertFalse(tracked.active)
            self.assertEqual(list((target / 'public').iterdir()), [])

    def test_observed_source_gitlink_or_public_directory_swap_cannot_attest_detached_assets(self):
        for selected in ('source', 'gitlink', 'public'):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, target, env = self.fixture(root)
                real_sync = os.fsync
                real_stat = os.fstat
                swapped = False
                def sync(descriptor):
                    nonlocal swapped
                    if not swapped and COMPOSE.stat.S_ISDIR(real_stat(descriptor).st_mode):
                        swapped = True
                        old = source if selected == 'source' else target if selected == 'gitlink' else target / 'public'
                        held = root / 'held' if selected == 'source' else old.with_name('held')
                        old.rename(held)
                        old.mkdir(mode=0o700)
                        (old / 'foreign').write_bytes(b'public replacement preserved')
                    return real_sync(descriptor)
                with patch.dict(os.environ, env, clear=True), patch.object(COMPOSE.os, 'fsync', side_effect=sync), \
                        self.assertRaises(COMPOSE.Rejected):
                    COMPOSE.install(source)
                visible = source if selected == 'source' else target if selected == 'gitlink' else target / 'public'
                self.assertEqual((visible / 'foreign').read_bytes(), b'public replacement preserved')

    def test_unexpected_gitlink_sibling_and_changed_permissions_are_not_accepted(self):
        for selected in ('sibling', 'public-readable', 'public-writable'):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                source, target, env = self.fixture(Path(directory))
                real_sync = os.fsync
                real_stat = os.fstat
                changed = False
                def sync(descriptor):
                    nonlocal changed
                    if not changed and COMPOSE.stat.S_ISDIR(real_stat(descriptor).st_mode):
                        changed = True
                        if selected == 'sibling':
                            (target / 'foreign').write_bytes(b'public sibling preserved')
                        else:
                            (target / 'public').chmod(0o755 if selected == 'public-readable' else 0o777)
                    return real_sync(descriptor)
                with patch.dict(os.environ, env, clear=True), patch.object(COMPOSE.os, 'fsync', side_effect=sync), \
                        self.assertRaises(COMPOSE.Rejected):
                    COMPOSE.install(source)
                if selected == 'sibling':
                    self.assertEqual((target / 'foreign').read_bytes(), b'public sibling preserved')

    def test_changed_manifest_or_asset_at_final_recheck_fails_before_composition_result(self):
        for selected in ('manifest', 'asset'):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, target, env = self.fixture(root)
                carrier = root / 'original-source'
                (carrier / 'app').mkdir(parents=True)
                (carrier / 'manifest.json').write_bytes((COMPOSE.HERE / 'manifest.json').read_bytes())
                for name in (*COMPOSE.ASSETS, 'test_dashboard.mjs'):
                    (carrier / 'app' / name).write_bytes((COMPOSE.HERE / 'app' / name).read_bytes())
                real_sync = os.fsync
                real_stat = os.fstat
                changed = False
                def sync(descriptor):
                    nonlocal changed
                    if not changed and COMPOSE.stat.S_ISDIR(real_stat(descriptor).st_mode):
                        changed = True
                        path = carrier / 'manifest.json' if selected == 'manifest' else carrier / 'app/dashboard.js'
                        path.write_bytes(path.read_bytes() + b' ')
                    return real_sync(descriptor)
                with patch.dict(os.environ, env, clear=True), patch.object(COMPOSE, 'HERE', carrier), \
                        patch.object(COMPOSE.os, 'fsync', side_effect=sync), self.assertRaises(COMPOSE.Rejected):
                    COMPOSE.install(source)
                self.assertEqual(list(target.iterdir()), [])

    def test_raw_read_handles_short_chunks_and_rejects_an_oversize_or_observed_growing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public-input'
            path.write_bytes(b'public input')
            real_read = os.read
            with patch.object(COMPOSE.os, 'read', side_effect=lambda fd, size: real_read(fd, min(size, 2))):
                self.assertEqual(COMPOSE.read(path, 64), b'public input')
            with self.assertRaises(COMPOSE.Rejected):
                COMPOSE.read(path, 4)
            changed = False
            def growing(descriptor, size):
                nonlocal changed
                if not changed:
                    changed = True
                    path.write_bytes(b'changed public input')
                return real_read(descriptor, size)
            with patch.object(COMPOSE.os, 'read', side_effect=growing), self.assertRaises(COMPOSE.Rejected):
                COMPOSE.read(path, 64)


if __name__ == '__main__':
    unittest.main()
