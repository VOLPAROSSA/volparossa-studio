# SPDX-License-Identifier: GPL-3.0-only
"""Closed sanitized receipt for the version-2 fixture; legacy receipts stay v1."""
import json
import re
import os
import stat


def closed(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('closed viewer receipt required')


def flags(value, true=(), false=()):
    if any(value[key] is not True for key in true) or any(value[key] is not False for key in false):
        raise ValueError('exact viewer flags required')


def validate_viewer_proof(value):
    original_true = ('actual_cli_pack', 'production_site_bundle_decoded', 'all_zip_assets_verified',
        'edited_html_verified', 'edited_css_verified', 'no_clobber_verified', 'ephemeral_fixture_signing')
    closed(value, (*original_true, 'schema', 'status', 'content_type', 'asset_count',
                   'network_published', 'signing_authority_exercised', 'local_viewer'))
    flags(value, original_true, ('network_published', 'signing_authority_exercised'))
    if type(value['schema']) is not int or value['schema'] != 2 or value['status'] != 'passed':
        raise ValueError('viewer proof v2 required')
    if value['content_type'] != 'application/vnd.volparossa.site.v1':
        raise ValueError('native site content type required')
    viewer = value['local_viewer']
    viewer_true = ('ephemeral_test_publisher', 'mock_local_control_peer', 'direct_child_adversarial_cleanup', 'production_signed_verification',
        'actual_site_open_cli', 'private_spool_removed', 'listener_closed')
    closed(viewer, (*viewer_true, 'schema', 'status', 'bundle_sha256', 'bundle_bytes', 'asset_count',
                    'browser', 'network_published', 'independent_peer_retrieval'))
    flags(viewer, viewer_true, ('network_published', 'independent_peer_retrieval'))
    if type(viewer['schema']) is not int or viewer['schema'] != 1 or viewer['status'] != 'passed':
        raise ValueError('local viewer receipt version required')
    if type(viewer['bundle_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', viewer['bundle_sha256']):
        raise ValueError('exact bundle hash required')
    if type(viewer['bundle_bytes']) is not int or not 0 < viewer['bundle_bytes'] <= 32 * 1024 * 1024:
        raise ValueError('bounded bundle length required')
    if type(value['asset_count']) is not int or not 2 <= value['asset_count'] <= 256 or type(viewer['asset_count']) is not int or viewer['asset_count'] != value['asset_count']:
        raise ValueError('exact asset count required')
    browser = viewer['browser']
    browser_true = ('visible_marker', 'computed_37px', 'all_assets_verified',
        'security_headers_preserved', 'independent_browser', 'browser_closed')
    closed(browser, (*browser_true, 'schema', 'status', 'bundle_sha256', 'bundle_bytes', 'asset_count', 'rendered_http_requests'))
    flags(browser, browser_true)
    if type(browser['rendered_http_requests']) is not int or not 1 <= browser['rendered_http_requests'] <= 1024:
        raise ValueError('bounded rendered HTTP request count required')
    if type(browser['schema']) is not int or browser['schema'] != 1 or browser['status'] != 'passed':
        raise ValueError('browser proof required')
    for key in ('bundle_sha256', 'bundle_bytes', 'asset_count'):
        if type(browser[key]) is not type(viewer[key]) or browser[key] != viewer[key]:
            raise ValueError('browser must bind exact packed bytes')


def read_viewer_cleanup(path, require_success=True):
    if path.stat().st_size > 4096:
        raise ValueError('bounded cleanup receipt required')
    value = json.loads(path.read_text())
    keys = ('core_group_drained', 'core_joined', 'isolated_network_namespace',
            'capabilities_dropped', 'nonroot_runner_uid', 'cleanup_failed')
    closed(value, keys)
    if any(type(item) is not bool for item in value.values()):
        raise ValueError('cleanup booleans required')
    if require_success:
        flags(value, keys[:-1], ('cleanup_failed',))
    return value


CORE_STAGES = ('pack', 'decode', 'child_controls', 'sign', 'transfer', 'ready',
               'browser_observation', 'shutdown', 'complete')
# Marker refinements are repeated AFTER-failure observations, never causal proof.
# Unavailable, late, changed or now-visible observations retain generic 'marker'.
BROWSER_STAGES = ('not_observed', 'launch', 'http', 'securityheaders', 'marker', 'marker_absent', 'marker_hidden', 'marker_ambiguous',
                  'style', 'assets', 'close', 'invalid_receipt')
DIAGNOSTIC_PREFIX = b'STUDIO_VIEWER_DIAGNOSTIC '
DIAGNOSTIC_LOG_LIMIT = 4 * 1024 * 1024

# Exact source-owned Node test titles map to fixed public case IDs. TAP error
# messages, paths, stack traces and arbitrary test names never leave the log.
UNIT_CASES = {
    'repeated matching absent, ambiguous and hidden snapshots have finite labels': 'marker_labels',
    'visible later, changing counts or changing visibility keep generic failure': 'marker_changes',
    'invalid types and nonfinite or unsafe counts never enter a specific label': 'marker_types',
    'unavailable observation preserves primary identity without inspecting private errors': 'marker_errors',
    'one finite budget returns generic and late RPC completion cannot publish again': 'marker_budget',
    'successful primary check is called exactly once without observation or stage changes': 'marker_success',
    'recording failure cannot mask the original assertion or turn failure into success': 'marker_recording',
    'early timer stops every in-flight snapshot continuation before the clock deadline': 'marker_early_timer',
    'actual private regular file and strict multibyte UTF8 are read successfully': 'handoff_read',
    'actual symlinks, permissions, hardlinks and directories fail closed': 'handoff_files',
    'actual exact size bound succeeds and oversize input is refused': 'handoff_size',
    'malformed JSON, UTF8 and leading BOM return only closed error text': 'handoff_encoding',
    'one fixed open supplies both stats and all bounded reads and closes on success': 'handoff_fd',
    'invalid initial FD metadata denies before allocation/read and still closes': 'handoff_metadata',
    'growth, truncation and changed post-read FD identity or nanosecond metadata deny': 'handoff_mutation',
    'open/stat/read/parse/close failures never expose underlying errors and close acquired FD': 'handoff_errors',
}
UNIT_LOG_LIMIT = 1024 * 1024


def read_viewer_unit_diagnostic(path):
    """Optional failure-only projection; never acceptance or a primary exception."""
    empty = dict(schema=1, status='unavailable', failed_case_ids=[], case_count=0)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as source:
            metadata = os.fstat(source.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_size > UNIT_LOG_LIMIT
                    or metadata.st_uid != os.getuid() or metadata.st_nlink != 1):
                raise ValueError('bounded private unit log required')
            data = source.read(UNIT_LOG_LIMIT + 1)
        if len(data) > UNIT_LOG_LIMIT:
            raise ValueError('unit log grew beyond bound')
        lines = data.decode('utf-8', errors='strict').splitlines()
        if 'TAP version 13' not in lines:
            raise ValueError('explicit unit TAP format required')
        seen, indices, failed = set(), set(), set()
        for line in lines:
            if not line.startswith(('ok ', 'not ok ')):
                continue
            match = re.fullmatch(r'(not ok|ok) ([1-9][0-9]?) - (.{1,256})', line)
            if match is None:
                raise ValueError('closed unit record required')
            outcome, index, name = match.groups()
            case = UNIT_CASES.get(name)
            if (case is None or case in seen or index in indices
                    or int(index) > len(UNIT_CASES) or len(seen) >= len(UNIT_CASES)):
                raise ValueError('unique fixed unit case required')
            seen.add(case)
            indices.add(index)
            if outcome == 'not ok':
                failed.add(case)
        if not failed:
            raise ValueError('failure diagnostic cannot claim successful tests')
        return dict(schema=1, status='observed', failed_case_ids=sorted(failed), case_count=len(seen))
    except FileNotFoundError:
        return empty
    except Exception:
        # This optional observer must never mask the original unit failure.
        return dict(empty, status='invalid')


def read_viewer_diagnostic(path):
    """Project only fixed progress categories from this invocation's private log.

    Unavailable/malformed diagnostics never establish acceptance or mask the
    original runtime/cleanup exception. No raw line or exception is returned.
    """
    result = dict(schema=1, status='unavailable', core_stage='unavailable',
                  browser_stage='not_observed', record_count=0)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > DIAGNOSTIC_LOG_LIMIT:
                raise ValueError('bounded regular diagnostic log required')
            data = source.read(DIAGNOSTIC_LOG_LIMIT + 1)
        if len(data) > DIAGNOSTIC_LOG_LIMIT:
            raise ValueError('diagnostic log grew beyond bound')
        for line in data.splitlines():
            if not line.startswith(DIAGNOSTIC_PREFIX):
                continue
            if len(line) > 256 or result['record_count'] >= 16:
                raise ValueError('bounded diagnostic record required')
            value = json.loads(line[len(DIAGNOSTIC_PREFIX):])
            closed(value, ('schema', 'core_stage', 'browser_stage'))
            if (type(value['schema']) is not int or value['schema'] != 1
                    or type(value['core_stage']) is not str or value['core_stage'] not in CORE_STAGES
                    or type(value['browser_stage']) is not str or value['browser_stage'] not in BROWSER_STAGES
                    or (value['browser_stage'] != 'not_observed' and value['core_stage'] != 'browser_observation')):
                raise ValueError('closed diagnostic stage required')
            result.update(status='observed', core_stage=value['core_stage'],
                          browser_stage=value['browser_stage'], record_count=result['record_count'] + 1)
    except FileNotFoundError:
        pass
    except InterruptedError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        result = dict(schema=1, status='invalid', core_stage='unavailable',
                      browser_stage='not_observed', record_count=0)
    return result
