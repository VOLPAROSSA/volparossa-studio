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
let dragObserver;
const emptyComponentCounts = () => ({ wrapper_descendants: 0, bare_texts: 0,
  default_texts: 0, texts: 0, editable_texts: 0 });
const emptyDragPhase = () => ({ components: emptyComponentCounts(), snapshot: 'not_attempted', source_draggable: false,
  source_point_in_block: false, target_main_hit_is_frame: false, target_frame_hit_in_wrapper: false });
const emptyNativeHandler = drop => ({ count: 0, observation: 'not_observed',
  cancelable: null, default_prevented: null, hit_is_wrapper: null, hit_in_wrapper: null,
  ...(drop ? { source_dragend_seen: null } : {}) });
const drag = { schema: 2, native_handlers: { dragover: emptyNativeHandler(false),
  drop: emptyNativeHandler(true) }, observer: 'not_attempted', pre_drag: emptyDragPhase(),
  post_drag: emptyDragPhase(), events: { source_dragstart: 0, source_dragend: 0,
    wrapper_dragenter: 0, wrapper_dragover: 0, wrapper_drop: 0 } };
const unavailableNativeHandlers = () => {
  for (const sample of Object.values(drag.native_handlers)) {
    sample.observation = 'unavailable';
    for (const key of Object.keys(sample)) {
      if (key !== 'count' && key !== 'observation') sample[key] = null;
    }
  }
};
let blocked = 0;
let localRequests = 0;
const startup = { schema: 1, page_errors: 0, console_errors: 0,
  failed_requests: 0, bad_responses: 0, blocked_external_requests: 0,
  first_page_error: 'none', missing_font_api_key_error: false,
  navigation_completed: false, dom_snapshot: 'not_attempted',
  dom: { editor_root_present: false, loader_present: false, loader_hidden: false,
    editor_root_visible: false, frame_present: false, silex_api_present: false,
    client_config_present: false, fonts_api_key_empty: false },
  interaction: { blocks: 0, text_blocks: 0, frames: 0, wrappers: 0, texts: 0,
    editable_texts: 0, wrapper_descendants: 0, bare_texts: 0, default_texts: 0,
    wrapper_visible: false, text_visible: false } };
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
  stage = 'manual_blocks_open';
  await page.locator('[title^="Blocks ("]').click();
  stage = 'manual_block_ready';
  const block = page.locator('.gjs-block').filter({ hasText: /^\s*Text\s*$/ }).first();
  await block.waitFor({ state: 'visible' });
  stage = 'manual_canvas_ready';
  const frame = page.frameLocator('.gjs-frame').first();
  // Pinned FrameView attaches Droppable to the wrapper, not the iframe shell.
  const wrapper = frame.locator('[data-gjs-type="wrapper"]').first();
  await wrapper.waitFor({ state: 'visible' });
  const wrapperBox = await wrapper.boundingBox();
  const frameBox = await page.locator('.gjs-frame').first().boundingBox();
  assert.ok(wrapperBox && frameBox);
  // Intersect the real drop root with its visible frame and fixed viewport.
  const left = Math.max(0, wrapperBox.x, frameBox.x);
  const top = Math.max(0, wrapperBox.y, frameBox.y);
  const right = Math.min(1440, wrapperBox.x + wrapperBox.width, frameBox.x + frameBox.width);
  const bottom = Math.min(1000, wrapperBox.y + wrapperBox.height, frameBox.y + frameBox.height);
  const box = { x: left, y: top, width: right - left, height: bottom - top };
  assert.ok(box.width > 0 && box.height > 0);
  const from = await block.boundingBox();
  assert.ok(from);
  // Observe only trusted native events and fixed hit-test booleans. These
  // listeners never read payloads, change DOM/models or alter event propagation.
  const sourcePoint = { x: from.x + from.width / 2, y: from.y + from.height / 2 };
  const targetPoint = { x: box.x + box.width / 2, y: box.y + Math.min(70, box.height / 2) };
  try {
    dragObserver = await page.evaluateHandle(({ sourcePoint, targetPoint }) => {
      // BlockView renders title from the same English Text label used above.
      const source = document.querySelector('.gjs-block[title="Text"]');
      const frame = document.querySelector('.gjs-frame');
      const doc = frame.contentDocument;
      const wrapper = doc.querySelector('[data-gjs-type="wrapper"]');
      const contains = (root, hit) => Boolean(root && hit && root.contains(hit));
      const count = (base, selector) => Math.min(32, base?.querySelectorAll(selector).length ?? 0);
      const components = () => ({
        wrapper_descendants: count(wrapper, '[data-gjs-type]'),
        bare_texts: count(doc, '[data-gjs-type="text"]'),
        default_texts: count(doc, '.silex-default-text'),
        texts: count(doc, '[data-gjs-type="text"].silex-default-text'),
        editable_texts: count(doc, '[data-gjs-type="text"].silex-default-text[contenteditable="true"]') });
      const probe = () => {
        const rect = frame.getBoundingClientRect();
        const localX = (targetPoint.x - rect.left) * frame.offsetWidth / rect.width - frame.clientLeft;
        const localY = (targetPoint.y - rect.top) * frame.offsetHeight / rect.height - frame.clientTop;
        return { components: components(), snapshot: 'captured', source_draggable: source.draggable === true,
          source_point_in_block: contains(source, document.elementFromPoint(sourcePoint.x, sourcePoint.y)),
          target_main_hit_is_frame: document.elementFromPoint(targetPoint.x, targetPoint.y) === frame,
          target_frame_hit_in_wrapper: contains(wrapper, doc.elementFromPoint(localX, localY)) };
      };
      const emptyNativeHandler = drop => ({ count: 0, observation: 'not_observed',
        cancelable: null, default_prevented: null, hit_is_wrapper: null, hit_in_wrapper: null,
        ...(drop ? { source_dragend_seen: null } : {}) });
      const state = { schema: 2, native_handlers: { dragover: emptyNativeHandler(false),
        drop: emptyNativeHandler(true) }, observer: 'captured', pre_drag: probe(),
        post_drag: { components: { wrapper_descendants: 0, bare_texts: 0,
          default_texts: 0, texts: 0, editable_texts: 0 }, snapshot: 'not_attempted', source_draggable: false,
          source_point_in_block: false, target_main_hit_is_frame: false, target_frame_hit_in_wrapper: false },
        events: { source_dragstart: 0, source_dragend: 0,
          wrapper_dragenter: 0, wrapper_dragover: 0, wrapper_drop: 0 } };
      const listeners = [];
      const observe = (root, type, key) => {
        const listener = event => {
          if (event.isTrusted) state.events[key] = Math.min(32, state.events[key] + 1);
        };
        root.addEventListener(type, listener, { capture: true, passive: true });
        listeners.push([root, type, listener, true]);
      };
      const observeNativeHandler = (type, drop) => {
        const listener = event => {
          if (!event.isTrusted) return;
          const count = Math.min(32, state.native_handlers[type].count + 1);
          // Last trusted bubble sample only; coordinates never leave this call.
          const sample = emptyNativeHandler(drop);
          sample.count = count;
          sample.observation = 'unavailable';
          try {
            const hit = doc.elementFromPoint(event.clientX, event.clientY);
            Object.assign(sample, { observation: 'captured', cancelable: event.cancelable,
              default_prevented: event.defaultPrevented, hit_is_wrapper: hit === wrapper,
              hit_in_wrapper: contains(wrapper, hit),
              ...(drop ? { source_dragend_seen: state.events.source_dragend > 0 } : {}) });
          } catch { /* Keep explicit unavailable/null fields, never error text. */ }
          state.native_handlers[type] = sample;
        };
        wrapper.addEventListener(type, listener, { capture: false, passive: true });
        listeners.push([wrapper, type, listener, false]);
      };
      const stop = () => {
        for (const [root, type, listener, capture] of listeners) root.removeEventListener(type, listener, capture);
        return state;
      };
      try {
        observe(source, 'dragstart', 'source_dragstart');
        observe(source, 'dragend', 'source_dragend');
        observe(wrapper, 'dragenter', 'wrapper_dragenter');
        observe(wrapper, 'dragover', 'wrapper_dragover');
        observe(wrapper, 'drop', 'wrapper_drop');
        observeNativeHandler('dragover', false);
        observeNativeHandler('drop', true);
      } catch (error) {
        stop();
        throw error;
      }
      return { stop, finish: () => {
        try { state.post_drag = probe(); } catch { state.post_drag.snapshot = 'unavailable'; }
        return stop();
      } };
    }, { sourcePoint, targetPoint });
  } catch {
    drag.observer = 'unavailable';
    unavailableNativeHandlers();
  }
  stage = 'manual_drop_idle';
  // CanvasView's real top-document placer, excluding any block drag ghost.
  const dropIndicator = page.locator('#gjs .gjs-cv-canvas > [data-tools] > .gjs-tools-gl > .gjs-placeholder');
  await dropIndicator.waitFor({ state: 'attached' });
  assert.equal(await dropIndicator.count(), 1);
  await dropIndicator.waitFor({ state: 'hidden' });
  assert.equal(await dropIndicator.count(), 1);
  stage = 'manual_drag';
  await page.mouse.move(sourcePoint.x, sourcePoint.y);
  await page.mouse.down();
  await page.mouse.move(targetPoint.x, targetPoint.y, { steps: 20 });
  stage = 'manual_drop_ready';
  try {
    // ComponentSorter reveals this placer only after accepting a drop target.
    // Use the existing default action timeout; no fixed delay or injected input.
    await dropIndicator.waitFor({ state: 'visible' });
    assert.equal(await dropIndicator.count(), 1);
  } catch (error) {
    // Escape cancels Playwright's native drag. Preserve the readiness failure
    // even if cancellation fails; never dispatch mouse-up on this path.
    try { await page.keyboard.press('Escape'); } catch { /* Browser teardown remains mandatory. */ }
    throw error;
  }
  await page.mouse.up();
  // This phase is sampled immediately after mouse-up, before component waiting.
  if (dragObserver) {
    try { Object.assign(drag, await dragObserver.evaluate(observer => observer.finish())); }
    catch { drag.observer = 'unavailable'; drag.post_drag.snapshot = 'unavailable';
      unavailableNativeHandlers(); }
  }
  stage = 'manual_text_ready';
  // ComponentView renders this attribute; Silex also adds silex-default-text.
  const text = frame.locator('[data-gjs-type="text"].silex-default-text').first();
  await text.waitFor({ state: 'visible' });
  stage = 'manual_text_activate';
  await text.dblclick();
  // ComponentTextView's dblclick enables the normal RTE on this DOM element.
  await frame.locator('[data-gjs-type="text"].silex-default-text[contenteditable="true"]').first().waitFor();
  stage = 'manual_text_edit';
  await page.keyboard.press('Control+a');
  await page.keyboard.insertText(marker);
  await page.keyboard.press('Escape');
  stage = 'manual_text_commit';
  await text.click();
  stage = 'manual_style';
  await page.keyboard.press('r');
  const typography = page.locator('.gjs-sm-sector').filter({ hasText: 'Typography' });
  const fontSize = typography.locator('.gjs-sm-property__font-size input').first();
  if (!await fontSize.isVisible()) await typography.locator('.gjs-sm-sector-title').click();
  await fontSize.fill('37');
  await fontSize.press('Enter');
  await fontSize.press('Tab');
  stage = 'manual_style_text_verify';
  assert.equal(await text.innerText(), marker);
  stage = 'manual_style_font_verify';
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
      // Read only fixed DOM/API booleans and capped counts. No text, HTML, URLs, keys,
      // project data or exception messages cross this observation boundary.
      const [observation] = await Promise.race([
        Promise.all([page.evaluate(() => {
          const root = document.getElementById('gjs');
          const loader = document.querySelector('.silex-loader');
          const visible = el => Boolean(el && getComputedStyle(el).visibility !== 'hidden');
          const api = window.silex;
          const frame = document.querySelector('.gjs-frame');
          const doc = frame?.contentDocument;
          const count = (base, selector) => Math.min(32, base?.querySelectorAll(selector).length ?? 0);
          const wrapper = doc?.querySelector('[data-gjs-type="wrapper"]');
          const text = doc?.querySelector('[data-gjs-type="text"].silex-default-text');
          const boxVisible = el => Boolean(el && el.getClientRects().length &&
            el.ownerDocument.defaultView.getComputedStyle(el).visibility !== 'hidden');
          return { dom: { editor_root_present: Boolean(root), loader_present: Boolean(loader),
            loader_hidden: Boolean(loader && !visible(loader)), editor_root_visible: visible(root),
            frame_present: Boolean(document.querySelector('.gjs-frame')),
            silex_api_present: typeof api?.start === 'function',
            client_config_present: typeof api?.config === 'object' && api.config !== null,
            fonts_api_key_empty: api?.config?.fontsApiKey === '' },
            interaction: { blocks: count(document, '.gjs-block'),
              text_blocks: count(document, '.gjs-block[title="Text"]'),
              frames: count(document, '.gjs-frame'),
              wrappers: count(doc, '[data-gjs-type="wrapper"]'),
              wrapper_descendants: count(wrapper, '[data-gjs-type]'),
              bare_texts: count(doc, '[data-gjs-type="text"]'),
              default_texts: count(doc, '.silex-default-text'),
              texts: count(doc, '[data-gjs-type="text"].silex-default-text'),
              editable_texts: count(doc, '[data-gjs-type="text"].silex-default-text[contenteditable="true"]'),
              wrapper_visible: boxVisible(wrapper), text_visible: boxVisible(text) } };
        }), dragObserver ? dragObserver.evaluate(observer => observer.stop()).then(value => {
          // stop() only returns already sampled phases; it cannot relabel a
          // late failure snapshot as an immediate post-drag observation.
          Object.assign(drag, value);
        }).catch(() => { drag.observer = 'unavailable'; unavailableNativeHandlers(); }) : Promise.resolve()]),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error()), 500); }),
      ]);
      startup.dom = observation.dom;
      startup.interaction = observation.interaction;
      startup.dom_snapshot = 'captured';
    } catch {
      startup.dom_snapshot = 'unavailable';
    } finally {
      clearTimeout(timer);
    }
  }
  // Snapshot before teardown so shutdown request failures do not change it.
  receipt.startup_diagnostics = structuredClone(startup);
  receipt.drag_diagnostics = structuredClone(drag);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  await writeFile(process.env.STUDIO_BROWSER_RECEIPT, JSON.stringify(receipt) + '\n', { flag: 'wx', mode: 0o600 });
}
