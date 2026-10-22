// SPDX-License-Identifier: GPL-3.0-only
// Only real mouse/keyboard actions change the project. No editor API, injected
// components, project JSON, publication payload, or fabricated export tree.
import { chromium } from 'playwright-core';
import { writeFile, stat, link as hardLink } from 'node:fs/promises';
import assert from 'node:assert/strict';

const marker = 'VOLPAROSSA Studio manual export 20261022';
let stage = 'browser_start';
let browser;
let blocked = 0;
let localRequests = 0;
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
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  stage = 'editor_load';
  await page.goto('http://127.0.0.1:6805/?id=default&connectorId=fs-storage&lang=en');
  await page.locator('.silex-loading').waitFor({ state: 'detached' });
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
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  await writeFile(process.env.STUDIO_BROWSER_RECEIPT, JSON.stringify(receipt) + '\n', { flag: 'wx', mode: 0o600 });
}
