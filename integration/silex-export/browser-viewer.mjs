// SPDX-License-Identifier: GPL-3.0-only
// Independent, read-only observer: all page content/styles come from Core HTTP.
import { chromium } from 'playwright-core';
import { readFile, writeFile, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
import { observeMarkerFailure } from './marker_failure.mjs';

const path = process.argv[2];
assert.ok((await stat(path)).size <= 131072);
const handoff = JSON.parse(await readFile(path, 'utf8'));
assert.equal(handoff.schema, 1);
const origin = new URL(handoff.url);
assert.equal(origin.protocol, 'http:');
assert.match(origin.hostname, /^vp[0-9a-f]{32}\.localhost$/);
assert.equal(origin.pathname, '/');
assert.equal(origin.search + origin.hash + origin.username + origin.password, '');
assert.ok(handoff.assets.length >= 2 && handoff.assets.length <= 256);
// The UI creates and edits this additional page. The original index is a
// different exported page; it remains covered by the all-asset integrity pass.
const editedPagePath = '/studio-export.html';
assert.equal(handoff.assets.filter(asset => asset.path === editedPagePath).length, 1);
let browser;
let passed = false;
let requests = 0;
let stage = 'launch';
const receipt = { schema: 1, status: 'failed', bundle_sha256: handoff.bundle_sha256,
  bundle_bytes: handoff.bundle_bytes, asset_count: handoff.assets.length,
  visible_marker: false, computed_37px: false, all_assets_verified: false,
  security_headers_preserved: false, independent_browser: true, browser_closed: false,
  rendered_http_requests: 0 };
try {
  browser = await chromium.launch({ executablePath: process.env.STUDIO_CHROME,
    headless: true, chromiumSandbox: true, timeout: 15000,
    args: ['--disable-background-networking', '--disable-component-update',
      '--disable-sync', '--no-first-run', '--disable-default-apps', '--no-proxy-server',
      `--host-resolver-rules=MAP ${origin.hostname} 127.0.0.1, MAP * ~NOTFOUND`] });
  const context = await browser.newContext({ serviceWorkers: 'block',
    viewport: { width: 1440, height: 1000 } });
  await context.route('**/*', async route => {
    if (new URL(route.request().url()).origin !== origin.origin) return route.abort('blockedbyclient');
    assert.ok(++requests <= 1024);
    await route.continue();
  });
  const page = await context.newPage();
  stage = 'http';
  const response = await page.goto(new URL(editedPagePath, origin).href,
    { waitUntil: 'networkidle', timeout: 15000 });
  assert.equal(response.status(), 200);
  stage = 'securityheaders';
  const headers = response.headers();
  assert.equal(headers['cache-control'], 'no-store');
  assert.equal(headers['x-content-type-options'], 'nosniff');
  assert.equal(headers['referrer-policy'], 'no-referrer');
  const csp = headers['content-security-policy'];
  assert.equal(csp, "default-src 'none'; sandbox allow-scripts allow-downloads; " +
    "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; " +
    "img-src 'self' data:; font-src 'self' data:; media-src 'self' blob:; connect-src 'self'; " +
    "worker-src 'none'; frame-src 'none'; child-src 'none'; object-src 'none'; " +
    "form-action 'none'; base-uri 'none'; frame-ancestors 'none'; manifest-src 'none'");
  receipt.security_headers_preserved = true;
  stage = 'marker';
  const marker = page.getByText('VOLPAROSSA Studio manual export 20261022', { exact: true });
  await observeMarkerFailure(async () => {
    await marker.waitFor({ state: 'visible', timeout: 5000 });
    assert.equal(await marker.count(), 1);
  }, marker, observedStage => { stage = observedStage; });
  receipt.visible_marker = true;
  stage = 'style';
  // Read-only computed layout observation, never setContent/evaluate mutations.
  assert.equal(await marker.evaluate(element => getComputedStyle(element).fontSize), '37px');
  receipt.computed_37px = true;
  receipt.rendered_http_requests = requests;
  stage = 'assets';
  // Integrity of every exported asset is separate from those requested by the
  // rendered page. Node HTTP retains the exact Host while connecting loopback.
  const { request } = await import('node:http');
  for (const asset of handoff.assets) {
    assert.ok(typeof asset.path === 'string' && asset.path.startsWith('/') && !asset.path.startsWith('//'));
    const bytes = await new Promise((resolve, reject) => {
      const req = request({ hostname: '127.0.0.1', port: origin.port, path: asset.path,
        method: 'GET', headers: { Host: origin.host, Connection: 'close' }, timeout: 3000 }, res => {
        if (res.statusCode !== 200) { res.resume(); return reject(new Error('asset response')); }
        const chunks = [];
        let length = 0;
        res.on('data', chunk => {
          length += chunk.length;
          if (length > asset.bytes || length > 32 * 1024 * 1024) res.destroy(new Error('asset bound'));
          else chunks.push(chunk);
        });
        res.on('error', reject);
        res.on('end', () => resolve(Buffer.concat(chunks)));
      });
      req.on('timeout', () => req.destroy(new Error('asset deadline')));
      req.on('error', reject);
      req.end();
    });
    assert.equal(bytes.length, asset.bytes);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), asset.sha256);
  }
  receipt.all_assets_verified = true;
  stage = 'close';
  await context.close();
  passed = true;
} finally {
  // A close failure must still leave a closed diagnostic; the original thrown
  // exception/exit remains failure and its text stays in the private log.
  try {
    if (browser) {
      await browser.close();
      receipt.browser_closed = true;
    }
    if (passed && receipt.browser_closed) receipt.status = 'passed';
  } finally {
    const output = receipt.status === 'passed' ? receipt : {
      schema: 1, status: 'failed', stage,
      browser_closed: receipt.browser_closed,
      rendered_http_requests: Math.min(requests, 1024),
    };
    await writeFile(handoff.receipt, JSON.stringify(output) + '\n', { flag: 'wx', mode: 0o600 });
  }
}
