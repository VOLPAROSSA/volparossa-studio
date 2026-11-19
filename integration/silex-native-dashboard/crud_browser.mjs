// SPDX-License-Identifier: GPL-3.0-only
// Real DOM actions against the real Rust HTTP service. No mocked responses.
import { chromium } from 'playwright-core';
import assert from 'node:assert/strict';
import { constants } from 'node:fs';
import { open, realpath } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

assert.equal(process.version, 'v24.19.0');
assert.deepEqual(process.execArgv, []);
assert.equal(process.argv.length, 4);
const phase = process.argv[2];
assert.ok(['first', 'second'].includes(phase));
const origin = new URL(process.argv[3]);
assert.equal(origin.protocol, 'http:');
assert.equal(origin.hostname, '127.0.0.1');
assert.equal(origin.pathname, '/');
assert.ok(Number(origin.port) > 1024);
const root = dirname(dirname(fileURLToPath(import.meta.url)));
assert.equal(await realpath(root), root);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const alpha = 'PUBLIC CRUD original';
const beta = 'PUBLIC CRUD renamed';
const copy = beta + ' copy';
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const end = performance.now() + 30000;
let browser;
let context;
let primary;
let action = 'browser_launch';
let renameRequests = 0;
const receipt = { schema: 1, phase, status: 'failed', steps: [], sandbox_requested: true,
  browser_closed: false, context_closed: false, external_denied: 0, requests: 0,
  ids: [], metadata_before_sha256: null, metadata_after_sha256: null,
  other_bytes_preserved: false, typed_rename_only: true, browser_version: '',
  failure_action: null, failure_http_status: null, chrome_sandbox_failure: false,
  chrome_namespace_failure: false, chrome_library_failure: false,
  chrome_startup_failure: false, dom_timeout: false };

async function read(path, max = 65536) {
  assert.equal(await realpath(path), path);
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = await file.stat({ bigint: true });
    assert.ok(before.isFile() && before.uid === BigInt(process.getuid()) && before.nlink === 1n);
    assert.equal(before.mode & 0o777n, 0o600n);
    assert.ok(before.size > 0n && before.size <= BigInt(max));
    const bytes = Buffer.alloc(Number(before.size) + 1);
    const { bytesRead } = await file.read(bytes, 0, bytes.length, 0);
    const after = await file.stat({ bigint: true });
    for (const key of ['dev', 'ino', 'uid', 'gid', 'mode', 'nlink', 'size', 'mtimeNs', 'ctimeNs']) {
      assert.equal(after[key], before[key]);
    }
    assert.equal(bytesRead, Number(before.size));
    return bytes.subarray(0, bytesRead);
  } finally { await file.close(); }
}

async function settled(page, names) {
  assert.ok(performance.now() < end);
  await page.waitForFunction(expected => {
    const section = document.getElementById('projects-section');
    const error = document.getElementById('error');
    const actual = [...document.querySelectorAll('.project-name')].map(node => node.textContent).sort();
    return section?.getAttribute('aria-busy') === 'false' && error?.hidden === true &&
      JSON.stringify(actual) === JSON.stringify([...expected].sort());
  }, names, { timeout: Math.min(8000, Math.max(1, end - performance.now())) });
}

async function projectId(page, name) {
  const key = await page.getByRole('button', { name: `Rename project: ${name}`, exact: true })
    .getAttribute('data-focus-key');
  assert.ok(key?.endsWith(':Rename'));
  const id = key.slice(0, -7);
  assert.match(id, uuid);
  return id;
}

try {
  const config = JSON.parse((await read(join(root, 'runtime-context.json'))).toString('utf8'));
  assert.ok(['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable'].includes(config.chrome));
  browser = await chromium.launch({ executablePath: config.chrome, headless: true,
    chromiumSandbox: true, timeout: 12000,
    args: ['--disable-background-networking', '--disable-component-update', '--disable-sync',
      '--no-first-run', '--disable-default-apps', '--no-proxy-server',
      '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'] });
  receipt.browser_version = browser.version();
  context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1100, height: 900 } });
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (++receipt.requests > 256) { await route.abort(); return; }
    const paths = ['/', '/dashboard.js', '/dashboard.css', '/api/connector',
      '/api/website', '/api/website/rename', '/api/website/duplicate'];
    if (url.origin !== origin.origin || !paths.includes(url.pathname)) {
      receipt.external_denied = Math.min(256, receipt.external_denied + 1);
      await route.abort('blockedbyclient'); return;
    }
    if (url.pathname === '/api/website/rename') {
      ++renameRequests;
      try {
        const body = JSON.parse(request.postData() ?? 'null');
        assert.equal(request.method(), 'POST');
        assert.deepEqual(body, { name: beta });
      } catch { receipt.typed_rename_only = false; await route.abort(); return; }
    }
    await route.continue();
  });
  const page = await context.newPage();
  page.on('response', response => {
    if (response.status() >= 400 && receipt.failure_http_status === null) receipt.failure_http_status = response.status();
  });
  action = 'page_load';
  const styles = page.waitForResponse(response => response.url() === origin.origin + '/dashboard.css', { timeout: 10000 });
  const scripts = page.waitForResponse(response => response.url() === origin.origin + '/dashboard.js', { timeout: 10000 });
  const [html, css, js] = await Promise.all([
    page.goto(origin.href, { waitUntil: 'domcontentloaded', timeout: 10000 }), styles, scripts]);
  const served = { 'index.html': html, 'dashboard.css': css, 'dashboard.js': js };
  action = 'static_assets';
  for (const asset of ['index.html', 'dashboard.css', 'dashboard.js']) {
    const bytes = await read(join(root, 'public', asset));
    assert.equal(digest(bytes), config.assets[asset].sha256);
    assert.equal(served[asset].status(), 200);
    const actual = await served[asset].body();
    assert.ok(actual.length <= 65536);
    assert.equal(actual.length, config.assets[asset].bytes);
    assert.equal(digest(actual), config.assets[asset].sha256);
  }
  if (phase === 'first') {
    action = 'empty';
    await settled(page, []); receipt.steps.push('empty');
    action = 'create';
    await page.locator('#new-name').fill(alpha);
    await page.getByRole('button', { name: 'Create project', exact: true }).click();
    await settled(page, [alpha]); receipt.steps.push('create');
    const original = await projectId(page, alpha);
    action = 'fixture_metadata';
    // Public fixture setup only, after the real create request has settled.
    // The tested rename still travels through the actual DOM and HTTP API.
    const meta = join(root, 'state', original, 'meta.json');
    const created = JSON.parse((await read(meta)).toString('utf8'));
    assert.equal(created.name, alpha);
    const seeded = Buffer.from('{ "name":"' + alpha + '", "imageUrl":"PUBLIC-preview", ' +
      '"connectorUserSettings":{"fs":{"integer":18446744073709551617,"decimal":0.10000000000000001}}, ' +
      '"future":{"integer":18446744073709551617,"decimal":0.10000000000000001} }');
    const file = await open(meta, constants.O_RDWR | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    try {
      const info = await file.stat();
      assert.ok(info.isFile() && info.uid === process.getuid() && info.nlink === 1 && (info.mode & 0o777) === 0o600);
      await file.truncate(0); await file.write(seeded, 0, seeded.length, 0); await file.sync();
    } finally { await file.close(); }
    assert.deepEqual(await read(meta), seeded);
    action = 'rename';
    await page.getByRole('button', { name: `Rename project: ${alpha}`, exact: true }).click();
    await page.locator('#rename-name').fill(beta);
    await page.locator('#rename-form').getByRole('button', { name: 'Rename', exact: true }).click();
    await settled(page, [beta]); receipt.steps.push('rename');
    const renamed = await read(meta);
    const expected = Buffer.from(seeded.toString('utf8').replace(JSON.stringify(alpha), JSON.stringify(beta)));
    assert.deepEqual(renamed, expected);
    receipt.metadata_before_sha256 = digest(seeded); receipt.metadata_after_sha256 = digest(renamed);
    receipt.other_bytes_preserved = true;
    action = 'duplicate';
    await page.getByRole('button', { name: `Duplicate project: ${beta}`, exact: true }).click();
    await settled(page, [beta, copy]); receipt.steps.push('duplicate');
    receipt.ids = [original, await projectId(page, copy)];
    assert.equal(renameRequests, 1);
  } else {
    action = 'persisted_list';
    const previous = JSON.parse((await read(join(root, 'browser-first.json'))).toString('utf8'));
    assert.equal(previous.status, 'passed');
    assert.ok(previous.ids.length === 2 && previous.ids.every(id => uuid.test(id)));
    await settled(page, [beta, copy]); receipt.steps.push('persisted_list');
    assert.deepEqual([await projectId(page, beta), await projectId(page, copy)], previous.ids);
    receipt.ids = previous.ids;
    for (const [name, step, remaining] of [[copy, 'delete_duplicate', [beta]], [beta, 'delete_original', []]]) {
      action = step;
      await page.getByRole('button', { name: `Delete project: ${name}`, exact: true }).click();
      await page.locator('#delete-form').getByRole('button', { name: 'Delete project', exact: true }).click();
      await settled(page, remaining); receipt.steps.push(step);
    }
    receipt.steps.push('empty'); assert.equal(renameRequests, 0);
  }
  assert.ok(receipt.typed_rename_only && receipt.requests <= 256 && performance.now() < end && receipt.failure_http_status === null);
} catch (error) {
  primary = true; // Never retain browser errors, URLs, payloads or screenshots.
  receipt.failure_action = action;
  const message = typeof error?.message === 'string' && error.message.length <= 65536 ? error.message : '';
  receipt.chrome_sandbox_failure = /No usable sandbox|Running as root without --no-sandbox|sandbox_linux.*Check failed/.test(message);
  receipt.chrome_namespace_failure = /Failed to move to new namespace|Failed to unshare|Operation not permitted/.test(message);
  receipt.chrome_library_failure = /error while loading shared libraries|cannot open shared object file/.test(message);
  receipt.chrome_startup_failure = action === 'browser_launch';
  receipt.dom_timeout = error?.name === 'TimeoutError' && action !== 'browser_launch';
} finally {
  action = 'browser_close';
  if (context) { try { await context.close(); receipt.context_closed = true; } catch { primary = true; } }
  if (browser) { try { await browser.close(); receipt.browser_closed = true; } catch { primary = true; } }
  if (primary && receipt.failure_action === null) receipt.failure_action = action;
  if (!primary && receipt.context_closed && receipt.browser_closed) receipt.status = 'passed';
  try {
    const file = await open(join(root, `browser-${phase}.json`), constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL, 0o600);
    try { await file.writeFile(JSON.stringify(receipt) + '\n'); await file.sync(); } finally { await file.close(); }
  } catch { primary = true; }
}
if (primary || receipt.status !== 'passed') process.exitCode = 1;
