# SPDX-License-Identifier: GPL-3.0-only
"""Hosted inert validators; fixture .deb names contain public bytes, never SDK code."""
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import fetch_sdk as sdk
finally:
    sys.path.remove(str(HERE))


def record(name='aa', data=b'abc'):
    return dict(Package=name, Version='1.0-1', Architecture='amd64',
        Filename=f'pool/main/{name[0]}/{name}/{name}_1.0-1_amd64.deb',
        SHA256=hashlib.sha256(data).hexdigest(), Size=str(len(data)))


def metadata(records):
    return ('\n\n'.join('\n'.join(key + ': ' + value for key, value in row.items())
                        for row in records.values()) + '\n').encode()


def uris(records, *, mirror=False):
    prefix = 'mirror+file:/etc/apt/apt-mirrors.txt/' if mirror else sdk.ARCHIVE_ORIGIN + '/ubuntu/'
    return ('\n'.join("'" + prefix + row['Filename'] + "' " + name + '_1%3a1.0_amd64.deb '
        + row['Size'] + ' MD5Sum:' + 'a' * 32 for name, row in records.items()) + '\n').encode()


class SdkFetchTests(unittest.TestCase):
    def test_frozen_metadata_has_exact_union_budget_and_no_install_authority(self):
        raw = (HERE / 'ubuntu-sdk.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), sdk.MANIFEST_SHA256)
        value = json.loads(raw)
        records = sdk.validate_manifest(value)
        self.assertEqual(len(records), 182)
        self.assertEqual(sum(int(row['Size']) for row in records.values()), 63772228)
        self.assertEqual(set(value['requested']), sdk.REQUESTED)
        for key in value['scope']:
            self.assertIs(value['scope'][key], key == 'metadata_verified')

    def test_schema_and_provenance_types_cannot_gain_native_or_install_claims(self):
        value = json.loads((HERE / 'ubuntu-sdk.json').read_bytes())
        for key, bad in (('schema', True), ('system', 'debian-13-amd64'),
                         ('inventory_run', True), ('apt_verification', 'unsigned download'),
                         ('private_url', 'not-allowed')):
            changed = dict(value, **{key: bad})
            with self.subTest(key=key), self.assertRaises(sdk.support.Rejected):
                sdk.validate_manifest(changed)
        for key in value['scope']:
            changed = copy.deepcopy(value)
            changed['scope'][key] = not changed['scope'][key]
            with self.subTest(scope=key), self.assertRaises(sdk.support.Rejected):
                sdk.validate_manifest(changed)

    def test_overlap_consistency_and_unique_archive_identity_are_required(self):
        row = record()
        value = dict(requested={'aa': row}, installation_plan={'aa': dict(row)})
        self.assertEqual(sdk.collect_records(value), {'aa': row})
        value['installation_plan']['aa']['Version'] = '1.0-2'
        with self.assertRaises(sdk.support.Rejected):
            sdk.collect_records(value)
        with self.assertRaises(sdk.support.Rejected):
            sdk.collect_records(dict(requested={'aa': row}, installation_plan={'bb': record('bb')}))

    def test_names_versions_pool_paths_digests_and_resource_bounds_fail_closed(self):
        for key, bad in (('Package', '--config'), ('Version', '1.0 --config=/private'),
                         ('Version', '1.0=other'), ('Architecture', 'arm64'),
                         ('Filename', '/pool/main/a/aa/a.deb'),
                         ('Filename', 'pool/main/a/../a.deb'),
                         ('Filename', 'pool/main/a/aa/%2e%2e.deb'),
                         ('Filename', 'https://private.invalid/a.deb'),
                         ('SHA256', 'A' * 64), ('Size', str(sdk.MAX_ARCHIVE + 1)),
                         ('Size', True), ('Size', '-1'), ('URL', 'https://private.invalid')):
            row = dict(record(), **{key: bad})
            with self.subTest(key=key, bad=bad), self.assertRaises(sdk.support.Rejected):
                sdk.valid_record('aa', row)
        rows = {name: dict(record(name, name.encode()), Size=str(50 * 1024 * 1024)) for name in ('aa', 'bb', 'cc')}
        with self.assertRaises(sdk.support.Rejected):
            sdk.collect_records(dict(requested=rows, installation_plan={}))

    def test_exact_apt_cache_stanzas_cover_all_packages_before_download(self):
        records = {'aa': dict(record(), Depends='other, package'), 'bb': record('bb', b'defg')}
        good = metadata(records)
        sdk.parse_metadata(good, records)
        sdk.parse_metadata(good.replace(b'Depends: other, package', b'Depends: other,\n package'), records)
        for bad in (metadata({'aa': records['aa']}),
                    good.replace(b'Size: 3', b'Size: 4'),
                    good.replace(b'Package: aa', b'Package: aa\nPackage: aa'),
                    good.replace(b'Architecture: amd64', b'Architecture: arm64'),
                    good.replace(records['aa']['SHA256'].encode(), b'0' * 64)):
            with self.subTest(bad=bad[:40]), self.assertRaises(sdk.support.Rejected):
                sdk.parse_metadata(bad, records)

    def test_only_observed_public_apt_uris_and_fixed_mirror_descriptor_are_admitted(self):
        records = {'aa': record()}
        sdk.verify_uris(uris(records), records)
        mirrors = (sdk.ARCHIVE_ORIGIN + '/ubuntu priority:1\n').encode()
        sdk.verify_uris(uris(records, mirror=True), records, mirrors)
        for bad in (uris(records).replace(b'azure.archive.ubuntu.com', b'private.invalid'),
                    uris(records).replace(b'http://', b'http://user:secret@'),
                    uris(records).replace(b'/ubuntu/pool', b'/other/pool'),
                    uris(records).replace(b".deb'", b".deb?secret=not-permitted'"),
                    uris(records, mirror=True).replace(b'/etc/apt/apt-mirrors.txt', b'/private/mirrors'),
                    uris(records) + uris(records), b''):
            with self.subTest(bad=bad[:60]), self.assertRaises(sdk.support.Rejected):
                sdk.verify_uris(bad, records, mirrors)

    def test_unobserved_public_mirror_is_diagnostic_only_and_denies_before_effects(self):
        records = {'aa': record()}
        fallback = b'http://archive.ubuntu.com/ubuntu priority:2\n'
        text, approved = sdk.public_mirror_list(fallback)
        self.assertFalse(approved)
        self.assertEqual(text.encode(), fallback)
        noted = []
        with tempfile.TemporaryDirectory() as directory:
            archives = Path(directory) / 'never-created'
            invoke = Mock(side_effect=[metadata(records), uris(records, mirror=True)])
            with patch.object(sdk, 'system_read', return_value=fallback), self.assertRaises(sdk.support.Rejected):
                sdk.fetch(records, invoke, archives, mirror_note=noted.append)
            self.assertEqual(noted, [text])
            self.assertFalse(archives.exists())
            self.assertEqual(invoke.call_count, 2)
        for private in (b'http://user:secret@archive.ubuntu.com/ubuntu\n',
                        b'http://private.invalid/ubuntu\n', b'http://archive.ubuntu.com/ubuntu?secret=x\n'):
            with self.assertRaises(sdk.support.Rejected):
                sdk.public_mirror_list(private)

    def test_bad_metadata_never_creates_archive_directory_or_calls_download(self):
        records = {'aa': record()}
        with tempfile.TemporaryDirectory() as directory:
            archives = Path(directory) / 'never-created'
            invoke = Mock(return_value=metadata(records).replace(b'Size: 3', b'Size: 4'))
            with self.assertRaises(sdk.support.Rejected):
                sdk.fetch(records, invoke, archives)
            self.assertEqual(invoke.call_count, 1)
            self.assertFalse(archives.exists())
            # Exercise the actual caller, asserting both APT argv vectors in
            # full: no later duplicate option can re-enable redirects/auth.
            fixed_options = [
                '-o', 'APT::Get::AllowUnauthenticated=false',
                '-o', 'Acquire::AllowInsecureRepositories=false',
                '-o', 'Acquire::AllowDowngradeToInsecureRepositories=false',
                '-o', 'Dir::Etc::netrc=/dev/null', '-o', 'Dir::Etc::netrcparts=/nonexistent',
                '-o', 'Acquire::http::Proxy=DIRECT', '-o', 'Acquire::https::Proxy=DIRECT',
                '-o', 'Acquire::http::AllowRedirect=false', '-o', 'Acquire::https::AllowRedirect=false',
                '-o', 'Acquire::http::Timeout=20', '-o', 'Acquire::https::Timeout=20',
                '-o', 'Acquire::Retries=0',
            ]
            invoke = Mock(side_effect=[metadata(records), uris(records), b''])
            with patch.object(sdk, 'verify_archives', return_value=[]) as verify:
                self.assertEqual(sdk.fetch(records, invoke, archives), [])
            self.assertEqual(invoke.call_args_list, [
                unittest.mock.call(['/usr/bin/apt-cache', '--no-all-versions', 'show', 'aa=1.0-1'], 45),
                unittest.mock.call(['/usr/bin/apt-get', *fixed_options, '--print-uris', 'download', 'aa=1.0-1'], 30),
                unittest.mock.call(['/usr/bin/apt-get', *fixed_options, 'download', 'aa=1.0-1'], 240, cwd=archives),
            ])
            verify.assert_called_once_with(archives, records)

    def test_real_inert_file_hashes_not_apt_epoch_filenames_define_exact_archive_set(self):
        records = {'aa': record(), 'bb': record('bb', b'defg')}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'aa_1%3a1.0_amd64.deb', root / 'bb_1.0_all.deb'
            first.write_bytes(b'abc')
            second.write_bytes(b'defg')
            result = sdk.verify_archives(root, records)
            self.assertEqual([row['package'] for row in result], ['aa', 'bb'])
            second.write_bytes(b'def')
            with self.assertRaises(sdk.support.Rejected):
                sdk.verify_archives(root, records)
            second.unlink()
            second.symlink_to(first)
            with self.assertRaises((sdk.support.Rejected, OSError)):
                sdk.verify_archives(root, records)
            second.unlink()
            os.link(first, second)
            with self.assertRaises(sdk.support.Rejected):
                sdk.verify_archives(root, records)
            second.unlink()
            second.write_bytes(b'defg')
            extra = root / 'unexpected.deb'
            extra.write_bytes(b'extra')
            with self.assertRaises(sdk.support.Rejected):
                sdk.verify_archives(root, records)
            extra.unlink()
            first.write_bytes(b'defg')
            with self.assertRaises(sdk.support.Rejected):
                sdk.verify_archives(root, records)

    def test_download_progress_rejects_oversize_and_symlink_before_any_hash_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'public-inert.partial'
            with file.open('wb') as stream:
                stream.truncate(sdk.MAX_ARCHIVE + 1)
            with self.assertRaises(sdk.support.Rejected):
                sdk.archive_progress(root)
            file.unlink()
            file.symlink_to(root / 'absent')
            with self.assertRaises(sdk.support.Rejected):
                sdk.archive_progress(root)

    def test_actor_peeks_unreaped_leader_then_single_drain_and_keeps_primary_failure(self):
        class Selector:
            def __enter__(self):
                self.active = True
                return self
            def __exit__(self, *_args):
                return False
            def register(self, *_args):
                pass
            def get_map(self):
                return {99: True} if self.active else {}
            def select(self, *_args):
                return [(SimpleNamespace(fd=99, fileobj=child.stdout), 1)]
            def unregister(self, *_args):
                self.active = False
        for exit_status, joined, failure in ((0, True, None), (1, False, 'child_failed'), (0, False, 'cleanup_failed')):
            with self.subTest(exit_status=exit_status, joined=joined):
                events = []
                child = Mock(pid=12345)
                child.stdout.fileno.return_value = 99
                identity = object()
                start = Mock(return_value=(child, identity))
                def peek(*_args):
                    events.append('peek')
                    return SimpleNamespace(si_pid=12345, si_code=os.CLD_EXITED, si_status=exit_status)
                def drain(process, group, **_options):
                    self.assertIs(process, child)
                    self.assertIs(group, identity)
                    events.append('drain')
                    return dict(leader_joined=joined, live_group_drained=joined)
                cleanups = []
                with patch.object(sdk.selectors, 'DefaultSelector', Selector), \
                        patch.object(sdk.os, 'set_blocking'), patch.object(sdk.os, 'read', return_value=b''), \
                        patch.object(sdk.os, 'waitid', side_effect=peek), \
                        patch.object(sdk.signal, 'getsignal', return_value=signal.SIG_DFL), \
                        patch.object(sdk.signal, 'signal'):
                    if failure is None:
                        self.assertEqual(sdk.actor(['/not-executed/apt'], {}, Path('/unused'), start, drain,
                                                   sdk.time.monotonic() + 10, 5, cleanups), b'')
                    else:
                        with self.assertRaises(sdk.support.Rejected) as caught:
                            sdk.actor(['/not-executed/apt'], {}, Path('/unused'), start, drain,
                                      sdk.time.monotonic() + 10, 5, cleanups)
                        self.assertEqual(caught.exception.kind, failure)
                self.assertEqual(events, ['peek', 'drain'])
                self.assertEqual(cleanups, [joined])
                child.wait.assert_not_called()
                child.poll.assert_not_called()


if __name__ == '__main__':
    unittest.main()
