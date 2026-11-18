# SPDX-License-Identifier: GPL-3.0-only
"""Inert closed-report regressions; these constructed receipts prove no runtime."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import signed_site_receipt as receipt


def proof():
    binding = dict(bundle_sha256='a' * 64, bundle_bytes=1204, asset_count=4,
        chunk_count=1, manifest_id='b' * 64, publisher_key='c' * 64, revision=1,
        publication_expires_unix_seconds=2000000000)
    browser = dict(schema=1, status='passed', bundle_sha256=binding['bundle_sha256'],
        bundle_bytes=binding['bundle_bytes'], asset_count=binding['asset_count'],
        rendered_http_requests=3, **dict.fromkeys(receipt.BROWSER_TRUE, True))
    return dict(schema=1, status='passed', proof_mode='signed-site-recovery', bindings=binding,
        counts=dict(positive_cli_started=6, positive_cli_joined=6, daemon_started=2,
                    crash_joined=1, graceful_joined=1, negative_cli_started=2,
                    negative_cli_joined=2, cli_rejections=2, agent_rejections=0),
        checks=dict.fromkeys(receipt.CHECKS, True), cleanup=dict.fromkeys(receipt.CLEANUP, True),
        scope=dict(**dict.fromkeys(receipt.SCOPE_TRUE, True), **dict.fromkeys(receipt.SCOPE_FALSE, False)),
        browser=browser)


def log_text(value):
    return ('\nrunning 1 test\n' + receipt.PREFIX + json.dumps(value) + '\n'
        'test studio_signed_site_recovery_native_preview_and_browser ... ok\n\n'
        'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.23s\n')


def private(path, value):
    path.write_bytes(value)
    path.chmod(0o600)


class SignedReceiptTests(unittest.TestCase):
    def test_complete_report_binds_dynamic_bundle_size_asset_and_chunk_counts(self):
        value = proof()
        self.assertEqual(receipt.validate_signed_proof(value, 4), value)
        value['bindings']['bundle_bytes'] = 262145
        value['bindings']['chunk_count'] = 2
        value['browser']['bundle_bytes'] = 262145
        receipt.validate_signed_proof(value, 4)
        with self.assertRaises(ValueError):
            receipt.validate_signed_proof(value, 3)

    def test_missing_extra_and_private_fields_fail_at_every_object(self):
        for level in (None, 'bindings', 'counts', 'checks', 'cleanup', 'scope', 'browser'):
            original = proof()
            target = original if level is None else original[level]
            keys = tuple(target)
            for key in keys:
                value = copy.deepcopy(original)
                changed = value if level is None else value[level]
                del changed[key]
                with self.subTest(level=level, missing=key), self.assertRaises(ValueError):
                    receipt.validate_signed_proof(value)
            target['private_payload'] = 'PRIVATE_SENTINEL'
            with self.subTest(level=level), self.assertRaises(ValueError):
                receipt.validate_signed_proof(original)

    def test_bool_is_never_an_integer_or_version_and_all_denials_are_counted(self):
        for level in ('bindings', 'counts', 'browser'):
            for key, original in proof()[level].items():
                if type(original) is not int:
                    continue
                value = proof()
                value[level][key] = True
                with self.subTest(level=level, key=key), self.assertRaises(ValueError):
                    receipt.validate_signed_proof(value)
        for key, bad in (('schema', True), ('proof_mode', 'viewer'), ('status', 'failed')):
            value = proof()
            value[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                receipt.validate_signed_proof(value)
        for key in receipt.COUNTS:
            value = proof()
            value['counts'][key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                receipt.validate_signed_proof(value)

    def test_browser_cannot_supply_different_bytes_or_skip_any_observation(self):
        for key, bad in (('bundle_sha256', 'd' * 64), ('bundle_bytes', 1205),
                         ('asset_count', 3), ('rendered_http_requests', 0),
                         ('rendered_http_requests', 1025), ('schema', 2), ('status', 'failed')):
            value = proof()
            value['browser'][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                receipt.validate_signed_proof(value)
        for key in receipt.BROWSER_TRUE:
            value = proof()
            value['browser'][key] = False
            with self.subTest(key=key), self.assertRaises(ValueError):
                receipt.validate_signed_proof(value)

    def test_claims_and_cleanup_cannot_be_weakened_or_gained(self):
        for level in ('checks', 'cleanup', 'scope'):
            for key, current in proof()[level].items():
                for bad in (not current, int(current), None):
                    value = proof()
                    value[level][key] = bad
                    with self.subTest(level=level, key=key, bad=bad), self.assertRaises(ValueError):
                        receipt.validate_signed_proof(value)

    def test_length_chunks_revisions_expiry_and_digest_are_bounded(self):
        for key, bad in (('bundle_bytes', 0), ('bundle_bytes', 32 * 1024 * 1024 + 1),
                         ('asset_count', 1), ('asset_count', 257), ('chunk_count', 2),
                         ('revision', 0), ('revision', 2**64),
                         ('publication_expires_unix_seconds', 0),
                         ('publication_expires_unix_seconds', 2**64),
                         ('bundle_sha256', 'a' * 63), ('manifest_id', 'B' * 64),
                         ('publisher_key', 'not-a-publisher')):
            value = proof()
            value['bindings'][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                receipt.validate_signed_proof(value)

    def test_log_requires_one_actual_success_and_single_current_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'signed-site-core.log'
            good = log_text(proof())
            private(path, good.encode())
            self.assertEqual(receipt.read_signed_proof(path, 4), proof())
            for bad in (good.replace('running 1 test', 'running 0 tests'),
                        good.replace('1 passed; 0 failed; 0 ignored', '0 passed; 0 failed; 1 ignored'),
                        good.replace('0 failed', '1 failed'),
                        good + receipt.PREFIX + json.dumps(proof()) + '\n',
                        good + 'running 1 test\n',
                        good + 'test result: FAILED. 0 passed; 1 failed; 0 ignored;\n',
                        good.replace(receipt.PREFIX, 'STUDIO_SITE_PACK_PROOF ')):
                private(path, bad.encode())
                with self.subTest(bad=bad[-80:]), self.assertRaises(ValueError):
                    receipt.read_signed_proof(path, 4)

    def test_log_rejects_duplicate_fields_nonfinite_and_oversize_before_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'signed-site-core.log'
            good = log_text(proof())
            for bad in (good.replace('"schema": 1', '"schema": 1, "schema": 1', 1),
                        good.replace('"bundle_bytes": 1204', '"bundle_bytes": NaN', 1)):
                private(path, bad.encode())
                with self.assertRaises(ValueError):
                    receipt.read_signed_proof(path, 4)
            private(path, b' ' * (receipt.LOG_LIMIT + 1))
            with self.assertRaises(ValueError):
                receipt.read_signed_proof(path, 4)

    def test_failure_diagnostics_are_finite_ordered_and_never_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'signed-site-core.log'
            self.assertEqual(receipt.read_signed_diagnostic(path)['status'], 'unavailable')
            lines = [receipt.DIAGNOSTIC_PREFIX + json.dumps(dict(schema=1, stage=stage))
                     for stage in ('pack', 'publish', 'preview')]
            private(path, ('PRIVATE_SENTINEL\n' + '\n'.join(lines) + '\n').encode())
            actual = receipt.read_signed_diagnostic(path)
            self.assertEqual(actual, dict(schema=1, status='observed', stage='preview', record_count=3))
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(actual))
            for bad in (lines + [lines[-1]], list(reversed(lines)),
                        [receipt.DIAGNOSTIC_PREFIX + '{"schema":true,"stage":"pack"}'],
                        [receipt.DIAGNOSTIC_PREFIX + '{"schema":1,"stage":"raw_error"}'],
                        [receipt.DIAGNOSTIC_PREFIX + '{"schema":1,"stage":"pack","url":"private"}']):
                private(path, ('\n'.join(bad) + '\n').encode())
                self.assertEqual(receipt.read_signed_diagnostic(path)['status'], 'invalid')


if __name__ == '__main__':
    unittest.main()
