// SPDX-License-Identifier: GPL-3.0-only
// Only real mouse/keyboard actions change the project. No editor API, injected
// components, project JSON, publication payload, or fabricated export tree.
import { chromium } from 'playwright-core';
import { writeFile, stat, link as hardLink } from 'node:fs/promises';
import assert from 'node:assert/strict';

const marker = 'VOLPAROSSA Studio manual export 20261022';
let stage = 'browser_start';
let browser;
let page;
let blocked = 0;
let localRequests = 0;
const startup = { schema: 1, page_errors: 0, console_errors: 0,
  failed_requests: 0, bad_responses: 0, blocked_external_requests: 0,
  first_page_error: 'none', missing_font_api_key_error: false,
  navigation_completed: false, dom_snapshot: 'not_attempted',
  dom: { editor_root_present: false, loader_present: false, loader_hidden: false,
    editor_root_visible: false, frame_present: false, silex_api_present: false,
    client_config_present: false, fonts_api_key_empty: false } };
const bump = key => { startup[key] = Math.min(32, startup[key] + 1); };
const receipt = { schema: 1, status: 'failed', stage, synthetic_only: true,
  network_published: false, public_hosting_accepted: false, shared_ai_accepted: false };
try {
  browser = await chromium.launch({ executablePath: process.env.STUDIO_CHROME,
    headless: true, chromiumSandbox: true, timeout: 15000,
    args: ['--disable-background-networking', '--disable-component-update',
      '--disable-sync', '--no-first-run', '--disable-default-apps',
      '--no-proxy-server', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'] });
  receipt.browser_version = browser.version();
  const context = await browser.newContext({ acceptDownloads: true,
    serviceWorkers: 'block', viewport: { width: 1440, height: 1000 } });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin === 'http://127.0.0.1:6805') {
      if (++localRequests > 2048) throw new Error('request bound');
      await route.continue();
    } else {
      blocked++;
      await route.abort('blockedbyclient');
    }
  });
  page = await context.newPage();
  page.on('pageerror', error => {
    bump('page_errors');
    if (startup.first_page_error === 'none') {
      const allowed = ['Error', 'TypeError', 'ReferenceError', 'SyntaxError', 'RangeError'];
      startup.first_page_error = allowed.includes(error.name) ? error.name : 'other';
    }
    // Match only this fixed upstream guard; raw error text is never retained.
    if (error.message.includes('You must provide Google font api key')) {
      startup.missing_font_api_key_error = true;
    }
  });
  page.on('console', message => { if (message.type() === 'error') bump('console_errors'); });
  page.on('requestfailed', () => bump('failed_requests'));
  page.on('response', response => { if (response.status() >= 400) bump('bad_responses'); });
  page.setDefaultTimeout(12000);
  stage = 'editor_navigation';
  await page.goto('http://127.0.0.1:6805/?id=default&connectorId=fs-storage&lang=en');
  startup.navigation_completed = true;
  stage = 'editor_ready';
  // Pinned editor/index.ts loaded() hides the loader and reveals #gjs. The
  // body class silex-loading remains present in this release, even when ready.
  await page.locator('.silex-loader').waitFor({ state: 'hidden' });
  await page.locator('#gjs:not(.silex-dialog-hide)').waitFor({ state: 'visible' });
  stage = 'editor_frame';
  await page.locator('.gjs-frame').first().waitFor();
  stage = 'create_page';
  await page.keyboard.press('Control+Alt+n');
  await page.locator('.new-page-dialog input[name="name"]').fill('Studio export');
  await page.locator('.new-page-dialog input[type="submit"]').click();
  stage = 'manual_text';
  await page.locator('[title^="Blocks ("]').click();
  const block = page.locator('.gjs-block').filter({ hasText: /^\s*Text\s*$/ }).first();
  const frameElement = page.locator('.gjs-frame').first();
  const frame = page.frameLocator('.gjs-frame').first();
  const box = await frameElement.boundingBox();
  assert.ok(box);
  const from = await block.boundingBox();
  assert.ok(from);
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + 70, { steps: 20 });
  await page.mouse.up();
  const text = frame.locator('[data-gjs-type="text"]').first();
  await text.dblclick();
  await page.keyboard.press('Control+a');
  await page.keyboard.insertText(marker);
  await page.keyboard.press('Escape');
  await text.click();
  stage = 'manual_style';
  await page.keyboard.press('r');
  const typography = page.locator('.gjs-sm-sector').filter({ hasText: 'Typography' });
  const fontSize = typography.locator('.gjs-sm-property__font-size input').first();
  if (!await fontSize.isVisible()) await typography.locator('.gjs-sm-sector-title').click();
  await fontSize.fill('37');
  await fontSize.press('Enter');
  await fontSize.press('Tab');
  assert.equal(await text.innerText(), marker);
  assert.equal(await text.evaluate(el => getComputedStyle(el).fontSize), '37px');
  stage = 'preview';
  // Use the ordinary preview toolbar. Reading computed CSS never changes models.
  await page.locator('.gjs-pn-btn.fa-eye').click();
  assert.equal(await text.innerText(), marker);
  assert.equal(await text.evaluate(el => getComputedStyle(el).fontSize), '37px');
  await page.locator('.gjs-off-prv').click();
  stage = 'download_connector';
  await page.locator('[title^="Publish ("]').click();
  await page.getByText('Connected to', { exact: false }).waitFor();
  assert.ok(await page.getByText('Download zip file', { exact: false }).isVisible());
  await page.locator('#publish-button--primary').click();
  const link = page.locator('a[href^="/download/"]');
  await link.waitFor();
  const url = new URL(await link.getAttribute('href'), page.url());
  assert.equal(url.origin, 'http://127.0.0.1:6805');
  assert.match(url.pathname, /^\/download\/[A-Za-z0-9_.-]+\.zip$/);
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }), link.click(),
  ]);
  assert.equal(await download.failure(), null);
  assert.equal(new URL(download.url()).origin, url.origin);
  const path = await download.path();
  const zip = await stat(path);
  assert.ok(zip.isFile() && zip.size > 0 && zip.size <= 32 * 1024 * 1024);
  // Same private temporary filesystem; link() is no-clobber, unlike saveAs().
  await hardLink(path, process.env.STUDIO_ZIP_OUTPUT);
  // Server unlinks after transfer; require the real one-time endpoint to expire.
  for (let attempt = 0; attempt < 20; attempt++) {
    const retry = await context.request.get(url.href, { timeout: 3000 });
    if (retry.status() !== 200) { receipt.download_consumed = true; break; }
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  assert.equal(receipt.download_consumed, true);
  assert.equal(blocked, 0, 'fixture attempted external browser requests');
  Object.assign(receipt, { status: 'passed', stage: 'exported', manual_page_created: true,
    manual_text_edited: true, manual_style_edited: true, preview_checked: true,
    actual_download_connector_zip: true, zip_bytes: zip.size, local_requests: localRequests,
    external_requests_blocked: blocked });
} catch (error) {
  receipt.stage = stage;
  receipt.error_type = error.constructor.name;
  startup.blocked_external_requests = Math.min(32, blocked);
  if (page && !page.isClosed()) {
    let timer;
    try {
      // Read only fixed DOM/API-presence booleans. No text, HTML, URLs, keys,
      // project data or exception messages cross this observation boundary.
      startup.dom = await Promise.race([
        page.evaluate(() => {
          const root = document.getElementById('gjs');
          const loader = document.querySelector('.silex-loader');
          const visible = el => Boolean(el && getComputedStyle(el).visibility !== 'hidden');
          const api = window.silex;
          return { editor_root_present: Boolean(root), loader_present: Boolean(loader),
            loader_hidden: Boolean(loader && !visible(loader)), editor_root_visible: visible(root),
            frame_present: Boolean(document.querySelector('.gjs-frame')),
            silex_api_present: typeof api?.start === 'function',
            client_config_present: typeof api?.config === 'object' && api.config !== null,
            fonts_api_key_empty: api?.config?.fontsApiKey === '' };
        }),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error()), 500); }),
      ]);
      startup.dom_snapshot = 'captured';
    } catch {
      startup.dom_snapshot = 'unavailable';
    } finally {
      clearTimeout(timer);
    }
  }
  // Snapshot before teardown so shutdown request failures do not change it.
  receipt.startup_diagnostics = structuredClone(startup);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  await writeFile(process.env.STUDIO_BROWSER_RECEIPT, JSON.stringify(receipt) + '\n', { flag: 'wx', mode: 0o600 });
}
