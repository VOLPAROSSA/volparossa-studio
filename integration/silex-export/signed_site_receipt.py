# SPDX-License-Identifier: GPL-3.0-only
"""Closed local signed-site proof; no raw logs, URL, payload or signing secrets."""
import re

from signed_site_profile import MODE, read_private, strict_json

PREFIX = 'STUDIO_SIGNED_SITE_PROOF '
DIAGNOSTIC_PREFIX = 'STUDIO_SIGNED_SITE_DIAGNOSTIC '
LOG_LIMIT = 4 * 1024 * 1024
CONTENT_TYPE = 'application/vnd.volparossa.site.v1'
STAGES = ('pack', 'publish', 'agent_import', 'crash_join', 'reopen', 'export',
          'assemble', 'preview', 'browser_observation', 'shutdown', 'cleanup', 'complete')
CHECKS = ('actual_cli_pack', 'original_signed_publication', 'roles_off_agent_import',
          'crash_reopen_same_cache', 'agent_export_assemble_equal', 'local_signed_preview',
          'all_zip_assets_verified')
CLEANUP = ('cli_children_joined', 'agent_children_joined', 'browser_closed',
           'listener_closed', 'private_state_removed')
SCOPE_TRUE = ('ephemeral_test_identity', 'real_cli_test_key_signing')
SCOPE_FALSE = ('mock_local_control_peer', 'gui_native_publication_consent',
               'named_lookup_performed', 'globally_latest', 'https_origin_authenticated',
               'network_published', 'protected_peer_retrieval', 'independent_hosting',
               'full_studio_acceptance', 'power_loss_recovery', 'physical_node_participation')
BROWSER_TRUE = ('visible_marker', 'computed_37px', 'all_assets_verified',
                'security_headers_preserved', 'independent_browser', 'browser_closed')
BINDINGS = ('bundle_sha256', 'bundle_bytes', 'asset_count', 'chunk_count', 'manifest_id',
            'publisher_key', 'revision', 'publication_expires_unix_seconds')
COUNTS = ('positive_cli_started', 'positive_cli_joined', 'daemon_started', 'crash_joined',
          'graceful_joined', 'negative_cli_started', 'negative_cli_joined',
          'cli_rejections', 'agent_rejections')


def closed(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('closed signed-site receipt required')


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('bounded signed-site integer required')


def digest(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('exact signed-site digest required')


def flags(value, true, false=()):
    closed(value, (*true, *false))
    if (any(value[key] is not True for key in true)
            or any(value[key] is not False for key in false)):
        raise ValueError('exact signed-site flags required')


def validate_signed_proof(value, expected_assets=None):
    closed(value, ('schema', 'status', 'proof_mode', 'bindings', 'counts', 'checks',
                   'cleanup', 'scope', 'browser'))
    if type(value['schema']) is not int or value['schema'] != 1 or value['status'] != 'passed' or value['proof_mode'] != MODE:
        raise ValueError('signed-site proof version and mode required')
    binding = value['bindings']
    closed(binding, BINDINGS)
    for key in ('bundle_sha256', 'manifest_id', 'publisher_key'):
        digest(binding[key])
    integer(binding['bundle_bytes'], 1, 32 * 1024 * 1024)
    integer(binding['asset_count'], 2, 256)
    integer(binding['chunk_count'], 1, 128)
    if binding['chunk_count'] != (binding['bundle_bytes'] + 262143) // 262144:
        raise ValueError('chunk count must bind actual bundle length')
    integer(binding['revision'], 1, 2**64 - 1)
    integer(binding['publication_expires_unix_seconds'], 1, 2**64 - 1)
    if expected_assets is not None:
        integer(expected_assets, 2, 256)
        if binding['asset_count'] != expected_assets:
            raise ValueError('fresh ZIP inventory asset count differs')
    counts = value['counts']
    closed(counts, COUNTS)
    fixed = dict(positive_cli_started=6, positive_cli_joined=6, daemon_started=2,
                 crash_joined=1, graceful_joined=1, negative_cli_started=2,
                 negative_cli_joined=2, cli_rejections=2, agent_rejections=0)
    for key, expected in fixed.items():
        integer(counts[key], expected, expected)
    flags(value['checks'], CHECKS)
    flags(value['cleanup'], CLEANUP)
    flags(value['scope'], SCOPE_TRUE, SCOPE_FALSE)
    browser = value['browser']
    closed(browser, ('schema', 'status', 'bundle_sha256', 'bundle_bytes', 'asset_count',
                     *BROWSER_TRUE, 'rendered_http_requests'))
    if type(browser['schema']) is not int or browser['schema'] != 1 or browser['status'] != 'passed':
        raise ValueError('fresh browser success required')
    for key in BROWSER_TRUE:
        if browser[key] is not True:
            raise ValueError('fresh browser observations required')
    integer(browser['rendered_http_requests'], 1, 1024)
    for key in ('bundle_sha256', 'bundle_bytes', 'asset_count'):
        if type(browser[key]) is not type(binding[key]) or browser[key] != binding[key]:
            raise ValueError('browser must bind reconstructed bundle bytes')
    return value


def read_signed_proof(path, expected_assets):
    lines = read_private(path, LOG_LIMIT).decode('utf-8', errors='strict').splitlines()
    proofs = [strict_json(line[len(PREFIX):]) for line in lines if line.startswith(PREFIX)]
    if len(proofs) != 1:
        raise ValueError('one current-invocation signed-site proof required')
    # --exact/--ignored is not enough: reject a stale record or a harness that
    # executed no tests. The actual successful one-test summary is mandatory.
    if (sum(line == 'running 1 test' for line in lines) != 1
            or sum(bool(re.fullmatch(r'test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; [0-9]+ filtered out; finished in [0-9.]+s', line)) for line in lines) != 1
            or any(line.startswith('test result: ') and not line.startswith('test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; ') for line in lines)):
        raise ValueError('one actual successful signed-site test required')
    return validate_signed_proof(proofs[0], expected_assets)


def read_signed_diagnostic(path):
    empty = dict(schema=1, status='unavailable', stage='not_observed', record_count=0)
    try:
        lines = read_private(path, LOG_LIMIT).decode('utf-8', errors='strict').splitlines()
        records = []
        for line in lines:
            if not line.startswith(DIAGNOSTIC_PREFIX):
                continue
            if len(line.encode()) > 256 or len(records) >= len(STAGES):
                raise ValueError('bounded signed-site progress required')
            value = strict_json(line[len(DIAGNOSTIC_PREFIX):])
            closed(value, ('schema', 'stage'))
            if type(value['schema']) is not int or value['schema'] != 1 or value['stage'] not in STAGES:
                raise ValueError('closed signed-site progress required')
            if records and STAGES.index(value['stage']) <= STAGES.index(records[-1]):
                raise ValueError('ordered unique signed-site progress required')
            records.append(value['stage'])
        if not records:
            return empty
        return dict(schema=1, status='observed', stage=records[-1], record_count=len(records))
    except FileNotFoundError:
        return empty
    except Exception:
        # Optional failure projection cannot mask the primary child failure.
        return dict(empty, status='invalid')
