// SPDX-License-Identifier: GPL-3.0-only
// Hosted Node units run the actual app source. Synthetic HTTP/DOM capabilities
// test client behavior; actual FsStorage CRUD and native WebKit remain separate.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { DashboardError, LIMITS, ProjectController, mountDashboard,
  parseBoundedJson, validName, writableMetadata } from './dashboard.js';

const ID = 'e88c8b28-20d8-4f61-a684-ecf375198cc6';
const ID2 = '620b8cac-d9e8-4072-b2f9-5f0fa95a55ca';
const row = (name = 'Public example', websiteId = ID) => ({ websiteId, name,
  connectorUserSettings: {}, repoUrl: 'file:///UNUSED_PUBLIC_FIXTURE',
  imageUrl: 'https://never-fetch.invalid/image' });
const json = value => new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } });
const raw = text => new Response(text, { headers: { 'content-type': 'application/json' } });
const ack = () => json({ message: 'Public acknowledgement' });

function harness(responses) {
  const calls = [];
  const timers = new Map();
  const delays = [];
  let time = 0;
  let nextTimer = 0;
  const capabilities = {
    fetch: async (path, options) => {
      calls.push({ path, options });
      assert.ok(responses.length, 'unexpected HTTP request');
      const response = responses.shift();
      return typeof response === 'function' ? response(path, options) : response;
    },
    now: () => time,
    setTimer: (callback, delay) => { delays.push(delay); timers.set(++nextTimer, callback); return nextTimer; },
    clearTimer: key => timers.delete(key),
  };
  return { calls, capabilities, timers, delays,
    setTime(value, fire = false) { time = value; if (fire) for (const callback of timers.values()) callback(); },
    controller: new ProjectController(capabilities) };
}

async function rejectsCode(promise, code) {
  await assert.rejects(promise, error => error instanceof DashboardError && error.code === code
    && !/PRIVATE_SENTINEL|never-fetch|file:\/\//.test(error.message));
}

test('fixed local CRUD routes use the actual methods and never follow metadata URLs', async () => {
  const replies = [json([]), json({ websiteId: ID, message: 'Created' }), json([row()]),
    ack(), json([row(), row('Public example copy', ID2)]), ack(), json([row('Public example copy', ID2)])];
  const h = harness(replies);
  await h.controller.refresh();
  await h.controller.create('Public example');
  assert.equal(h.controller.editorPath(ID), `/?id=${ID}&connectorId=fs-storage`);
  await h.controller.duplicate(ID);
  await h.controller.delete(ID);
  assert.deepEqual(h.calls.map(call => [call.options.method, call.path]), [
    ['GET', '/api/website/?connectorId=fs-storage'],
    ['PUT', '/api/website/?connectorId=fs-storage'],
    ['GET', '/api/website/?connectorId=fs-storage'],
    ['POST', `/api/website/duplicate?websiteId=${ID}&connectorId=fs-storage`],
    ['GET', '/api/website/?connectorId=fs-storage'],
    ['DELETE', `/api/website/?websiteId=${ID}&connectorId=fs-storage`],
    ['GET', '/api/website/?connectorId=fs-storage'],
  ]);
  assert.deepEqual(JSON.parse(h.calls[1].options.body), { name: 'Public example', connectorUserSettings: {} });
  for (const call of h.calls) {
    assert.equal(call.options.mode, 'same-origin');
    assert.equal(call.options.credentials, 'same-origin');
    assert.equal(call.options.redirect, 'error');
    assert.equal(call.options.referrerPolicy, 'no-referrer');
    assert.equal(call.options.cache, 'no-store');
    assert.equal(call.options.signal.aborted, true);
  }
  assert.equal(replies.length, 0);
  assert.equal(h.timers.size, 0);
});

test('rename freshly reads and preserves writable settings and image without read-only fields', async () => {
  const settings = JSON.parse('{"__proto__":{"safe":true},"nested":[0.125,1e-7,9007199254740991,"public"]}');
  const fresh = { ...row('Fresh name'), connectorUserSettings: settings,
    updatedAt: '2026-10-29T00:00:00Z', pagesUrl: 'file:///NEVER_OPEN' };
  const h = harness([json([row('Old list name')]), json(fresh), ack(), json([row('New name')])]);
  await h.controller.refresh();
  await h.controller.rename(ID, 'New name');
  assert.deepEqual(h.calls.slice(1).map(call => call.options.method), ['GET', 'POST', 'GET']);
  assert.equal(h.calls[1].path, `/api/website/meta?websiteId=${ID}&connectorId=fs-storage`);
  const posted = JSON.parse(h.calls[2].options.body);
  assert.deepEqual(posted, { name: 'New name', connectorUserSettings: settings, imageUrl: fresh.imageUrl });
  assert.equal(Object.prototype.safe, undefined);
  assert.equal(h.controller.snapshot().projects[0].name, 'New name');
});

test('precision-losing and ambiguous metadata refuses rename before any POST', async () => {
  for (const number of ['9007199254740993', '9007199254740992', '0.10000000000000001', '1e-400', '-0', '1e309']) {
    const metadata = `{"websiteId":"${ID}","name":"Public example","connectorUserSettings":{"number":${number}}}`;
    const h = harness([json([row()]), raw(metadata)]);
    await h.controller.refresh();
    await assert.rejects(h.controller.rename(ID, 'Changed'), DashboardError);
    assert.deepEqual(h.calls.map(call => call.options.method), ['GET', 'GET']);
    assert.equal(h.controller.snapshot().requiresRefresh, false);
  }
  const h = harness([json([row()]), raw(`{"websiteId":"${ID}","name":"Public","connectorUserSettings":{"x":1,"x":2}}`)]);
  await h.controller.refresh();
  await assert.rejects(h.controller.rename(ID, 'Changed'), DashboardError);
  assert.equal(h.calls.length, 2);
  assert.deepEqual(parseBoundedJson('{"x":1.2500,"y":1e-7}', true), { x: 1.25, y: 1e-7 });
});

test('rename refuses unknown or excessive settings and wrong metadata identity without mutation', async () => {
  const settings = { nested: {} };
  let tip = settings.nested;
  for (let index = 0; index < 9; index += 1) { tip.next = {}; tip = tip.next; }
  for (const meta of [{ ...row(), futureField: 'unsupported' }, { ...row(), websiteId: ID2 },
    { ...row(), connectorUserSettings: settings }, { ...row(), connectorUserSettings: { x: 'x'.repeat(1025) } }]) {
    const h = harness([json([row()]), json(meta)]);
    await h.controller.refresh();
    await rejectsCode(h.controller.rename(ID, 'New'), 'metadata');
    assert.equal(h.calls.length, 2);
  }
  assert.deepEqual(JSON.parse(writableMetadata({ websiteId: ID, name: 'Old' }, ID, 'New')),
    { name: 'New', connectorUserSettings: {} });
});

test('current-map IDs and complete list validation reject traversal and ambiguous rows', async () => {
  for (const websiteId of ['../other', '/absolute', 'a%2fb', 'a\\b', '.', 'a?x=1', 'a b']) {
    const h = harness([json([row('Name', websiteId)])]);
    await rejectsCode(h.controller.refresh(), 'invalid');
    assert.equal(h.controller.snapshot().projects.length, 0);
  }
  const h = harness([json([row()])]);
  await h.controller.refresh();
  for (const id of [ID2, '../other']) {
    await rejectsCode(h.controller.delete(id), 'stale');
    assert.throws(() => h.controller.editorPath(id), DashboardError);
  }
  assert.equal(h.calls.length, 1);
  const duplicate = harness([json([row(), row('Duplicate ID')])]);
  await rejectsCode(duplicate.controller.refresh(), 'invalid');
});

test('project and name bounds fail before mutation and preserve names as entered', async () => {
  assert.equal(validName('  Public name  '), true);
  assert.equal(validName('😀'.repeat(128)), true);
  for (const name of ['', '   ', 'a'.repeat(129), '😀'.repeat(129), 'a\n', 'a\u202e', '\ud800']) {
    assert.equal(validName(name), false);
  }
  const many = Array.from({ length: 257 }, (_, index) => row('Name', `public-${index}`));
  const tooMany = harness([json(many)]);
  await rejectsCode(tooMany.controller.refresh(), 'limit');
  const h = harness([json([row('x'.repeat(125))])]);
  await h.controller.refresh();
  await rejectsCode(h.controller.duplicate(ID), 'limit');
  await rejectsCode(h.controller.create('\n'), 'name');
  assert.equal(h.calls.length, 1);
});

test('all JSON input is bounded and rejects duplicate keys malformed UTF-8 and deep geometry', async () => {
  for (const text of ['{"a":1,"\\u0061":2}', '[1,]', 'true false', '01', '"\\ud800"', '['.repeat(18) + '0' + ']'.repeat(18)]) {
    assert.throws(() => parseBoundedJson(text), DashboardError);
  }
  assert.throws(() => parseBoundedJson(JSON.stringify(Array(4096).fill(null))), DashboardError);
  const bad = new Response(new Uint8Array([0xc3, 0x28]), { headers: { 'content-type': 'application/json' } });
  const h = harness([bad]);
  await rejectsCode(h.controller.refresh(), 'invalid');
  const byteLimit = harness([raw(' '.repeat(LIMITS.listBytes + 1))]);
  await rejectsCode(byteLimit.controller.refresh(), 'limit');
});

test('streamed size denial cancels the body and never parses oversize metadata', async () => {
  let cancelled = false;
  let reads = 0;
  const stream = new ReadableStream({
    pull(controller) { reads += 1; controller.enqueue(new Uint8Array(40_000).fill(32)); },
    cancel() { cancelled = true; },
  });
  const h = harness([json([row()]), new Response(stream, { headers: { 'content-type': 'application/json' } })]);
  await h.controller.refresh();
  await rejectsCode(h.controller.rename(ID, 'New'), 'limit');
  assert.ok(cancelled);
  assert.ok(reads <= 3);
  assert.equal(h.calls.length, 2);
});

test('HTTP failure and redirect or wrong MIME never expose backend error data', async () => {
  for (const response of [new Response('PRIVATE_SENTINEL file:///secret', { status: 500 }),
    new Response('<PRIVATE_SENTINEL>', { headers: { 'content-type': 'text/html' } }),
    new Response('', { status: 302, headers: { location: 'https://never-fetch.invalid' } })]) {
    const h = harness([response]);
    await rejectsCode(h.controller.refresh(), 'unavailable');
    assert.equal(h.controller.snapshot().error, 'unavailable');
    assert.equal(h.calls.length, 1);
  }
});

test('one original action deadline covers fresh metadata mutation and reload without renewal', async () => {
  const h = harness([json([row()]),
    () => { h.setTime(10_000); return json(row()); },
    () => { h.setTime(14_999); return ack(); },
    () => { h.setTime(15_000, true); return json([row('New')]); }]);
  await h.controller.refresh();
  await rejectsCode(h.controller.rename(ID, 'New'), 'uncertain');
  assert.deepEqual(h.delays, [15_000, 15_000]);
  assert.equal(new Set(h.calls.slice(1).map(call => call.options.signal)).size, 1);
  assert.equal(h.controller.snapshot().requiresRefresh, true);
  assert.equal(h.timers.size, 0);
});

test('uncertain mutation is never retried and requires an explicit successful refresh', async () => {
  const h = harness([json([row()]), () => { throw new Error('PRIVATE_SENTINEL'); }, json([row()]), ack(), json([])]);
  await h.controller.refresh();
  await rejectsCode(h.controller.delete(ID), 'uncertain');
  await rejectsCode(h.controller.duplicate(ID), 'stale');
  assert.equal(h.calls.length, 2);
  assert.throws(() => h.controller.editorPath(ID), DashboardError);
  await h.controller.refresh();
  await h.controller.delete(ID);
  assert.equal(h.calls.length, 5);
  assert.equal(h.controller.snapshot().requiresRefresh, false);
});

test('failed refresh after acknowledged mutation retains the uncertainty lock', async () => {
  const h = harness([json([row()]), ack(), () => { throw new Error('PRIVATE_SENTINEL'); }]);
  await h.controller.refresh();
  await rejectsCode(h.controller.duplicate(ID), 'uncertain');
  assert.equal(h.calls.length, 3);
  assert.equal(h.controller.snapshot().requiresRefresh, true);
});

test('only one action can be active and page disposal aborts stale completion', async () => {
  let complete;
  const h = harness([() => new Promise(resolve => { complete = resolve; })]);
  const pending = h.controller.refresh();
  await rejectsCode(h.controller.refresh(), 'busy');
  h.controller.dispose();
  assert.equal(h.calls[0].options.signal.aborted, true);
  complete(json([row()]));
  await rejectsCode(pending, 'closed');
  assert.equal(h.controller.snapshot().projects.length, 0);
  assert.equal(h.calls.length, 1);
  assert.equal(h.timers.size, 0);
});

test('aborted reads fail before any rename POST and release the action timer', async () => {
  const h = harness([json([row()]), (_path, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('PRIVATE_SENTINEL')), { once: true });
  })]);
  await h.controller.refresh();
  const pending = h.controller.rename(ID, 'New');
  h.setTime(15_000, true);
  await rejectsCode(pending, 'deadline');
  assert.equal(h.calls.length, 2);
  assert.equal(h.controller.snapshot().requiresRefresh, true);
  assert.equal(h.controller.snapshot().reloadRequired, true);
  assert.equal(h.timers.size, 0);
});

test('deadline settles a fetch that ignores abort and blocks all further requests', async () => {
  const h = harness([() => new Promise(() => {})]);
  const pending = h.controller.refresh();
  assert.equal(h.controller.snapshot().busy, true);
  h.setTime(15_000, true);
  await rejectsCode(pending, 'deadline');
  assert.equal(h.controller.snapshot().busy, false);
  assert.equal(h.controller.snapshot().reloadRequired, true);
  await rejectsCode(h.controller.refresh(), 'reload');
  await rejectsCode(h.controller.create('Another'), 'reload');
  assert.equal(h.calls.length, 1);
  assert.equal(h.timers.size, 0);
});

test('deadline settles an abort-ignoring read and cancel without accepting late bytes', async () => {
  let completeRead;
  let readStarted;
  let readResult;
  const started = new Promise(resolve => { readStarted = resolve; });
  let cancelRequests = 0;
  let releases = 0;
  const reader = {
    read() { readResult = new Promise(resolve => { completeRead = resolve; }); readStarted(); return readResult; },
    cancel() { cancelRequests += 1; return new Promise(() => {}); },
    releaseLock() { releases += 1; },
  };
  const response = { status: 200, headers: new Headers({ 'content-type': 'application/json' }),
    body: { getReader: () => reader } };
  const h = harness([response]);
  const pending = h.controller.refresh();
  await started;
  h.setTime(15_000, true);
  await rejectsCode(pending, 'deadline');
  assert.equal(cancelRequests, 1);
  assert.equal(releases, 1);
  assert.equal(h.controller.snapshot().busy, false);
  assert.equal(h.controller.snapshot().reloadRequired, true);
  const before = h.controller.snapshot();
  completeRead({ done: false, value: new TextEncoder().encode(JSON.stringify([row()])) });
  await readResult;
  assert.deepEqual(h.controller.snapshot(), before);
  await rejectsCode(h.controller.refresh(), 'reload');
  assert.equal(h.calls.length, 1);
  assert.equal(h.timers.size, 0);
});

test('late mutation response is cancelled without parsing refreshing or reopening capacity', async () => {
  let completeFetch;
  let lateCancelRequests = 0;
  let lateCancelled;
  const cancelled = new Promise(resolve => { lateCancelled = resolve; });
  const h = harness([json([row()]), () => new Promise(resolve => { completeFetch = resolve; })]);
  await h.controller.refresh();
  const pending = h.controller.duplicate(ID);
  h.setTime(15_000, true);
  await rejectsCode(pending, 'uncertain');
  const before = h.controller.snapshot();
  assert.equal(before.reloadRequired, true);
  completeFetch({ body: { cancel() { lateCancelRequests += 1; lateCancelled(); return Promise.resolve(); } },
    get status() { assert.fail('late response was inspected'); } });
  await cancelled;
  assert.equal(lateCancelRequests, 1);
  assert.deepEqual(h.controller.snapshot(), before);
  await rejectsCode(h.controller.refresh(), 'reload');
  assert.throws(() => h.controller.editorPath(ID), DashboardError);
  assert.equal(h.calls.length, 2);
  assert.equal(h.timers.size, 0);
});

test('unconfirmed error-body cleanup is bounded and preserves the original closed failure', async () => {
  let cancellationStarted;
  const cancelling = new Promise(resolve => { cancellationStarted = resolve; });
  const h = harness([{ status: 500, headers: new Headers(),
    body: { cancel() { cancellationStarted(); return new Promise(() => {}); } } }]);
  const pending = h.controller.refresh();
  await cancelling;
  h.setTime(15_000, true);
  await rejectsCode(pending, 'unavailable');
  assert.equal(h.controller.snapshot().reloadRequired, true);
  assert.equal(h.controller.snapshot().busy, false);
  await rejectsCode(h.controller.refresh(), 'reload');
  assert.equal(h.calls.length, 1);
  assert.equal(h.timers.size, 0);
});

test('duplicate message cannot redirect or supply an editor identity', async () => {
  const h = harness([json([row()]), json({ message: 'Website duplicated with ID: https://never-fetch.invalid/PRIVATE_SENTINEL' }),
    json([row(), row('Copy', ID2)])]);
  await h.controller.refresh(); await h.controller.duplicate(ID);
  assert.equal(h.controller.editorPath(ID2), `/?id=${ID2}&connectorId=fs-storage`);
  assert.equal(h.calls.length, 3);
  assert.equal(JSON.stringify(h.controller.snapshot()).includes('PRIVATE_SENTINEL'), false);
});

// Minimal DOM capability model: tests actual handlers/text/focus. It does not
// stand in for browser accessibility, CSP enforcement or native GUI acceptance.
class Element extends EventTarget {
  constructor(tag, document) {
    super(); this.tagName = tag; this.document = document; this.children = []; this.parent = null;
    this.dataset = {}; this.attributes = {}; this.disabled = false; this.hidden = false;
    this.value = ''; this.validity = ''; this.textContent = ''; this.root = false; this.open = false;
  }
  set innerHTML(_value) { assert.fail('untrusted markup sink used'); }
  get isConnected() { return this.root || Boolean(this.parent?.isConnected); }
  append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
  replaceChildren(...children) { for (const old of this.children) old.parent = null; this.children = []; this.append(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
  setCustomValidity(message) { this.validity = message; }
  reportValidity() { return !this.validity; }
  focus() { if (!this.disabled) this.document.activeElement = this; }
  click() { if (!this.disabled) { this.focus(); this.dispatchEvent(new Event('click')); } }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatchEvent(new Event('close')); }
  escape() { const event = new Event('cancel', { cancelable: true }); if (this.dispatchEvent(event)) this.close(); }
}

function domHarness(responses) {
  const h = harness(responses);
  const elements = new Map();
  const document = { activeElement: null,
    getElementById: id => elements.get(id), createElement: tag => new Element(tag, document) };
  for (const id of ['projects', 'refresh-button', 'new-name', 'rename-dialog', 'delete-dialog',
    'create-button', 'projects-section', 'error', 'status', 'empty', 'rename-name', 'delete-name',
    'rename-cancel', 'delete-cancel', 'new-form', 'rename-form', 'delete-form']) {
    const element = new Element(id, document); element.root = true; elements.set(id, element);
  }
  const navigations = [];
  const browser = new EventTarget();
  Object.assign(browser, { fetch: h.capabilities.fetch, performance: { now: h.capabilities.now },
    setTimeout: h.capabilities.setTimer, clearTimeout: h.capabilities.clearTimer,
    location: { replace: path => navigations.push(path) } });
  const controller = mountDashboard(document, browser);
  const get = id => elements.get(id);
  const button = (label, index = 0) => get('projects').children[index].children[1].children.find(child => child.textContent === label);
  return { ...h, controller, document, browser, get, button, navigations };
}

async function idle(controller) {
  for (let index = 0; index < 1_000; index += 1) {
    if (!controller.snapshot().busy) return;
    await Promise.resolve();
  }
  assert.fail('app did not settle within bounded microtask turns');
}
const submit = element => element.dispatchEvent(new Event('submit', { cancelable: true }));

test('actual UI treats names as text and opens only the selected local editor route', async () => {
  const name = '<img src="https://never-fetch.invalid" onerror="PRIVATE_SENTINEL">';
  const h = domHarness([json([row(name)])]);
  await idle(h.controller);
  assert.equal(h.get('projects').children[0].children[0].textContent, name);
  assert.equal(h.get('projects').children[0].children[0].children.length, 0);
  h.button('Open').click();
  assert.deepEqual(h.navigations, [`/?id=${ID}&connectorId=fs-storage`]);
  assert.equal(h.calls.length, 1);
});

test('actual dialog handlers cancel safely restore focus and require explicit delete confirmation', async () => {
  const h = domHarness([json([row()]), ack(), json([])]);
  await idle(h.controller);
  h.button('Delete').click();
  assert.equal(h.get('delete-dialog').open, true);
  assert.equal(h.document.activeElement, h.get('delete-cancel'));
  h.get('delete-dialog').escape();
  assert.equal(h.calls.length, 1);
  assert.equal(h.document.activeElement, h.button('Delete'));
  h.button('Rename').click();
  assert.equal(h.document.activeElement, h.get('rename-name'));
  h.get('rename-cancel').click();
  assert.equal(h.calls.length, 1);
  h.button('Delete').click(); submit(h.get('delete-form'));
  await idle(h.controller);
  assert.equal(h.calls[1].options.method, 'DELETE');
  assert.equal(h.get('projects').children.length, 0);
  assert.equal(h.get('empty').hidden, false);
  assert.equal(h.document.activeElement, h.get('refresh-button'));
});

test('actual new and rename forms preserve input and focus with no persistent browser storage', async () => {
  const h = domHarness([json([]), json({ websiteId: ID, message: 'Created' }), json([row()]),
    json(row()), ack(), json([row('Renamed')])]);
  await idle(h.controller);
  h.get('new-name').value = '\n'; submit(h.get('new-form'));
  assert.equal(h.calls.length, 1);
  assert.notEqual(h.get('new-name').validity, '');
  h.get('new-name').value = 'Public example'; submit(h.get('new-form'));
  await idle(h.controller); await Promise.resolve();
  assert.equal(h.get('new-name').value, '');
  assert.equal(h.document.activeElement, h.get('new-name'));
  h.button('Rename').click(); h.get('rename-name').value = 'Renamed'; submit(h.get('rename-form'));
  await idle(h.controller);
  assert.equal(h.get('projects').children[0].children[0].textContent, 'Renamed');
  assert.equal(h.document.activeElement, h.button('Rename'));
  assert.equal(h.calls.length, 6);
  h.browser.dispatchEvent(new Event('pagehide'));
  await rejectsCode(h.controller.refresh(), 'closed');
});

test('actual UI disables further actions after uncertainty until explicit refresh', async () => {
  const h = domHarness([json([row()]), () => { throw new Error('PRIVATE_SENTINEL'); }, json([row()])]);
  await idle(h.controller);
  h.button('Duplicate').click(); await idle(h.controller);
  assert.equal(h.get('create-button').disabled, true);
  assert.equal(h.button('Delete').disabled, true);
  assert.equal(h.button('Open').disabled, true);
  assert.equal(h.get('refresh-button').disabled, false);
  assert.equal(h.get('error').hidden, false);
  assert.doesNotMatch(h.get('error').textContent, /PRIVATE_SENTINEL/);
  h.button('Delete').click(); assert.equal(h.calls.length, 2);
  h.get('refresh-button').click(); await idle(h.controller);
  assert.equal(h.button('Delete').disabled, false);
  assert.equal(h.get('error').hidden, true);
  assert.equal(h.calls.length, 3);
});

test('actual UI requires page reload after a transport misses the deadline', async () => {
  const h = domHarness([() => new Promise(() => {})]);
  h.setTime(15_000, true);
  await idle(h.controller);
  assert.equal(h.get('refresh-button').disabled, true);
  assert.equal(h.get('create-button').disabled, true);
  assert.match(h.get('status').textContent, /Reload this dashboard/);
  h.get('refresh-button').click();
  assert.equal(h.calls.length, 1);
});

test('HTML and CSS use only original local resources with a restrictive CSP and accessible controls', async () => {
  const html = await readFile(new URL('./index.html', import.meta.url), 'utf8');
  const css = await readFile(new URL('./dashboard.css', import.meta.url), 'utf8');
  const js = await readFile(new URL('./dashboard.js', import.meta.url), 'utf8');
  assert.match(html, /default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'/);
  assert.match(html, /form-action 'none'/);
  assert.match(html, /<script type="module" src="\.\/dashboard\.js"><\/script>/);
  assert.match(html, /<link rel="stylesheet" href="\.\/dashboard\.css">/);
  assert.match(html, /role="alert"/);
  assert.match(html, /<label for="new-name">/);
  assert.match(html, /<dialog id="delete-dialog" aria-labelledby=/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /system-ui/);
  for (const source of [html, css, js]) {
    assert.doesNotMatch(source, /https?:\/\/|@import|@font-face|\bconsole\.|localStorage|sessionStorage|navigator\.sendBeacon|window\.__TAURI__|innerHTML\s*=/);
  }
});
