// SPDX-License-Identifier: GPL-3.0-only
// Hosted-only behavior tests of exact source. The VM is a fixture, not an app sandbox.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { URL, URLSearchParams } from 'node:url';
import vm from 'node:vm';

const BASELINE_SHA256 = 'f91e9debbe5a67175ce93bdcd17c29b8b13ba1ae5616ffa450bea4d315d90fa3';
const PATCHED_SHA256 = 'f51c34bb965e69ba7f907b2473b4aa310faef1fa98ba20003e49e6b8c824a482';
const MAX_SOURCE = 64 * 1024;
const VM_MILLISECONDS = 200;
const TEST_MILLISECONDS = 5000;

function admittedSource() {
  assert.equal(process.env.GITHUB_ACTIONS, 'true');
  assert.equal(process.env.RUNNER_ENVIRONMENT, 'github-hosted');
  assert.equal(process.env.RUNNER_OS, 'Linux');
  assert.equal(process.env.RUNNER_ARCH, 'X64');
  assert.equal(process.platform, 'linux');
  assert.equal(process.arch, 'x64');
  assert.equal(process.version, 'v24.19.0');
  assert.notEqual(process.getuid(), 0);
  assert.notEqual(process.geteuid(), 0);
  const args = process.argv.slice(2);
  assert.equal(args.length, 6);
  assert.equal(args[0], '--source-root');
  assert.equal(args[2], '--bridge-sha256');
  assert.equal(args[4], '--baseline-bridge');
  assert.equal(args[3], PATCHED_SHA256);
  const allowed = ['GITHUB_WORKSPACE', 'RUNNER_TEMP'].map(key => {
    const value = process.env[key];
    assert.ok(typeof value === 'string' && path.isAbsolute(value));
    return fs.realpathSync(value);
  });
  function within(value) {
    assert.ok(path.isAbsolute(value));
    const actual = fs.realpathSync(value);
    assert.equal(actual, value, 'source paths must be canonical without symlink components');
    assert.ok(allowed.some(root => actual.startsWith(root + path.sep)), 'source must remain under hosted workspace or temporary root');
    return actual;
  }
  const root = within(args[1]);
  assert.ok(fs.lstatSync(root).isDirectory());
  return {
    bridge: readSource(within(path.join(root, 'desktop/src-tauri/scripts/desktop-bridge.js')), args[3]),
    baseline: readSource(within(args[5]), BASELINE_SHA256),
  };
}

function readSource(filename, expected) {
  const descriptor = fs.openSync(filename, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  let data;
  try {
    const before = fs.fstatSync(descriptor, { bigint: true });
    assert.ok(before.isFile());
    assert.equal(before.uid, BigInt(process.getuid()));
    assert.equal(before.nlink, 1n);
    assert.equal(before.mode & 0o022n, 0n);
    assert.ok(before.size > 0n && before.size <= BigInt(MAX_SOURCE));
    const bytes = Buffer.alloc(MAX_SOURCE + 1);
    let count = 0;
    while (count < bytes.length) {
      const read = fs.readSync(descriptor, bytes, count, Math.min(16384, bytes.length - count), count);
      if (!read) break;
      count += read;
    }
    const after = fs.fstatSync(descriptor, { bigint: true });
    assert.equal(BigInt(count), before.size);
    for (const key of ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs']) {
      assert.equal(after[key], before[key], 'source changed during bounded read');
    }
    data = bytes.subarray(0, count);
  } finally {
    fs.closeSync(descriptor);
  }
  assert.equal(createHash('sha256').update(data).digest('hex'), expected);
  return new TextDecoder('utf-8', { fatal: true }).decode(data);
}

// No process, module loader or real network/timer is exposed to the context.
// URL constructors supply browser parsing; all stub Promise jobs stay on the
// VM's bounded microtask queue. This is not a sandbox for arbitrary source.
const PRELUDE = String.raw`
'use strict';
globalThis.observed = { invokes: [], fetches: [], scripts: [], listeners: [], rejectedListeners: 0,
  sentryReads: 0, sdkInitializations: 0, sdkUsers: 0, sdkErrors: 0, breadcrumbs: 0,
  spanStarts: 0, spanEnds: 0, spanStatuses: 0, clockReads: 0,
  stores: 0, undos: 0, redos: 0, prevented: 0, consoleCalls: 0 };
const record = (collection, value) => {
  if (collection.length >= 64) throw new Error('public fixture observation bound');
  collection.push(value);
};
globalThis.editorHandlers = new Map();
globalThis.menuHandlers = new Map();
globalThis.documentHandlers = new Map();
globalThis.intervals = new Map();
let nextInterval = 1;
globalThis.setInterval = (callback, delay) => {
  if (delay !== 300 || intervals.size >= 1) throw new Error('unexpected bridge timer');
  const id = nextInterval++;
  intervals.set(id, callback);
  return id;
};
globalThis.clearInterval = id => intervals.delete(id);
globalThis.tick = () => {
  const callbacks = Array.from(intervals.values());
  if (callbacks.length > 1) throw new Error('timer count bound');
  for (const callback of callbacks) callback();
};
const OriginalDate = Date;
globalThis.Date = class extends OriginalDate {
  static now() { observed.clockReads++; return 1234000; }
};
globalThis.console = { log() { observed.consoleCalls++; } };
const component = (ccid, id, children = []) => ({
  ccid, values: {}, getId() { return id; }, components() { return { models: children }; },
  get(key) { return this.values[key]; }, set(key, value) { this.values[key] = value; }
});
globalThis.leaf = component('leaf-ccid', 'leaf-id');
globalThis.wrapper = component('root-ccid', 'root-id', [leaf]);
globalThis.editor = {
  on(event, callback) {
    if (editorHandlers.has(event) || editorHandlers.size >= 16) throw new Error('duplicate editor handler');
    editorHandlers.set(event, callback);
  },
  store() { observed.stores++; },
  UndoManager: { undo() { observed.undos++; }, redo() { observed.redos++; } },
  getWrapper() { return wrapper; },
  Devices: { getSelected() { return { id: 'desktop', get() { return 'Desktop'; } }; } },
  Pages: { getSelected() { return { id: 'public-page', get() { return 'Public page'; } }; } },
  getSelected() { return leaf; },
  StyleManager: { getSelected() { return { selectorsToString() { return '.public-marker'; } }; } }
};
globalThis.emitEditor = event => {
  const callback = editorHandlers.get(event);
  if (callback) callback();
};
globalThis.emitMenu = event => {
  const callback = menuHandlers.get(event);
  if (!callback) throw new Error('missing functional native menu callback');
  callback();
};
globalThis.clickLink = href => {
  const callback = documentHandlers.get('click');
  if (!callback) throw new Error('missing link callback');
  callback({ target: { closest() { return { getAttribute() { return href; }, href }; } },
    preventDefault() { observed.prevented++; } });
};
const sdk = {
  init(options) {
    if (options.dsn !== 'https://PUBLIC-CANARY.invalid/1') throw new Error('missing stale DSN canary');
    observed.sdkInitializations++;
  },
  setUser(user) {
    if (user.id !== 'PUBLIC-CANARY-INSTALL-ID') throw new Error('missing stale install-ID canary');
    observed.sdkUsers++;
  }, setTag() {},
  browserTracingIntegration() { return {}; }, addBreadcrumb() { observed.breadcrumbs++; },
  captureException() { observed.sdkErrors++; },
  startInactiveSpan() { observed.spanStarts++; return {
    end() { observed.spanEnds++; }, setStatus() { observed.spanStatuses++; }
  }; }
};
globalThis.window = {
  location: { href: 'http://localhost:6805/' + settings.search,
    origin: 'http://localhost:6805', search: settings.search },
  silex: { getEditor() { return settings.editorAvailable ? editor : null; } },
  grapesjsAiCapabilities: { getAllCapabilities() { return [{ id: 'public-edit', command: 'public-edit' }]; } }
};
Object.defineProperty(window, 'Sentry', { get() {
  observed.sentryReads++;
  if (settings.poisonSentry) throw new Error('legacy SDK must not be consulted');
  return sdk;
} });
globalThis.document = {
  addEventListener(event, callback) {
    if (event !== 'click' || documentHandlers.has(event)) throw new Error('unexpected document callback');
    documentHandlers.set(event, callback);
  },
  createElement(tag) {
    record(observed.scripts, { tag });
    if (!settings.allowSdk) throw new Error('external SDK insertion refused');
    return {};
  },
  head: { appendChild(script) {
    if (!settings.allowSdk || script.src !== 'https://browser.sentry-cdn.com/8.46.0/bundle.tracing.min.js')
      throw new Error('unexpected external script');
    observed.scripts[observed.scripts.length - 1].src = script.src;
    if (script.onload) script.onload();
  } }
};
globalThis.fetch = (url, options) => {
  record(observed.fetches, String(url));
  if (url !== '/api/website/meta?websiteId=public-fixture' || options !== undefined)
    throw new Error('unexpected bridge network request');
  if (settings.failMetadata) return Promise.reject(new Error('public synthetic metadata failure'));
  return Promise.resolve({ json() { return Promise.resolve({ name: 'Public fixture' }); } });
};
if (settings.tauri) window.__TAURI__ = {
  core: { invoke(command, args) {
    if (!['get_telemetry_context', 'log_debug', 'clear_current_project', 'set_current_project', 'mark_unsaved', 'open_folder'].includes(command))
      throw new Error('unexpected native command');
    record(observed.invokes, { command, args });
    // Adversarial stale native response: even a still-available old command/DSN
    // must not be used by the patched bootstrap.
    if (command === 'get_telemetry_context') return Promise.resolve({
      dsn: 'https://PUBLIC-CANARY.invalid/1', release: 'public-canary-release',
      environment: 'public-fixture', user_id: 'PUBLIC-CANARY-INSTALL-ID', os: 'linux', arch: 'x64'
    });
    return Promise.resolve();
  } },
  event: { listen(event, callback) {
    if (!['menu-save', 'menu-undo', 'menu-redo', 'menu-close-project'].includes(event))
      throw new Error('unexpected native event');
    record(observed.listeners, event);
    if (settings.rejectListeners) {
      observed.rejectedListeners++;
      return Promise.reject(new Error('public synthetic listener rejection'));
    }
    menuHandlers.set(event, callback);
    return Promise.resolve(() => menuHandlers.delete(event));
  } }
};
globalThis.snapshot = () => JSON.stringify({ ...observed,
  editorEvents: Array.from(editorHandlers.keys()).sort(),
  intervalCount: intervals.size, href: window.location.href,
  hasMcp: typeof window.__silexMcp === 'object' });
`;

function fixture(source, options = {}) {
  const settings = { search: '?id=public-fixture', tauri: true, editorAvailable: true,
    poisonSentry: true, allowSdk: false, failMetadata: false, rejectListeners: false, ...options };
  const context = vm.createContext(Object.assign(Object.create(null), { URL, URLSearchParams }), {
    name: 'public-synthetic-desktop-bridge', microtaskMode: 'afterEvaluate',
    codeGeneration: { strings: false, wasm: false },
  });
  function execute(code) {
    return new vm.Script(code, { filename: 'public-bridge-fixture.js' })
      .runInContext(context, { timeout: VM_MILLISECONDS });
  }
  execute('globalThis.settings = ' + JSON.stringify(settings) + ';');
  execute(PRELUDE);
  new vm.Script(source, { filename: 'desktop-bridge.js' })
    .runInContext(context, { timeout: VM_MILLISECONDS });
  return { execute, snapshot: () => JSON.parse(execute('snapshot()')) };
}

function noTelemetry(observed) {
  assert.equal(observed.invokes.filter(call => call.command === 'get_telemetry_context').length, 0);
  for (const key of ['sentryReads', 'sdkInitializations', 'sdkUsers', 'sdkErrors', 'breadcrumbs',
    'spanStarts', 'spanEnds', 'spanStatuses', 'clockReads']) assert.equal(observed[key], 0, key);
  assert.deepEqual(observed.scripts, []);
}

const sources = admittedSource();
const boundedTest = (name, callback) => test(name, { timeout: TEST_MILLISECONDS }, callback);

boundedTest('pristine 672 bridge positively detects stale-context SDK identity error and timing paths', () => {
  const f = fixture(sources.baseline, { allowSdk: true, poisonSentry: false, rejectListeners: true });
  f.execute('tick(); emitEditor("storage:start:store"); emitEditor("storage:end:store");'
    + 'emitEditor("storage:start:store"); emitEditor("storage:error:store");'
    + 'emitEditor("silex:publish:start"); emitEditor("silex:publish:end");'
    + 'emitEditor("silex:publish:start"); emitEditor("silex:publish:error");');
  const s = f.snapshot();
  assert.equal(s.invokes.filter(call => call.command === 'get_telemetry_context').length, 1);
  assert.equal(s.scripts.length, 1);
  assert.equal(s.sdkInitializations, 1);
  assert.equal(s.sdkUsers, 1);
  assert.equal(s.sdkErrors, 4);
  assert.equal(s.breadcrumbs, 4);
  assert.equal(s.spanStarts, 5);
  assert.equal(s.spanEnds, 5);
  assert.equal(s.spanStatuses, 2);
  assert.equal(s.clockReads, 1);
});

boundedTest('patched bridge remains inert outside Tauri', () => {
  const f = fixture(sources.bridge, { tauri: false });
  const s = f.snapshot();
  noTelemetry(s);
  assert.deepEqual(s.invokes, []);
  assert.deepEqual(s.fetches, []);
  assert.equal(s.hasMcp, false);
  assert.equal(s.intervalCount, 0);
});

boundedTest('patched dashboard clears project without stale telemetry SDK identity or timing', () => {
  const f = fixture(sources.bridge, { search: '' });
  const s = f.snapshot();
  noTelemetry(s);
  assert.deepEqual(s.invokes.map(call => call.command), ['log_debug', 'clear_current_project']);
  assert.deepEqual(s.fetches, []);
  assert.equal(s.hasMcp, true);
  assert.equal(s.intervalCount, 0);
});

boundedTest('patched project metadata dirty and all four native menu callbacks still work', () => {
  const f = fixture(sources.bridge);
  f.execute('tick(); emitEditor("change:changesCount"); emitMenu("menu-save");'
    + 'emitMenu("menu-undo"); emitMenu("menu-redo"); emitMenu("menu-close-project");'
    + 'emitEditor("storage:start:store"); emitEditor("storage:end:store");'
    + 'emitEditor("storage:error:store"); emitEditor("silex:publish:start");'
    + 'emitEditor("silex:publish:end"); emitEditor("silex:publish:error");');
  const s = f.snapshot();
  noTelemetry(s);
  assert.deepEqual(s.fetches, ['/api/website/meta?websiteId=public-fixture']);
  assert.deepEqual(s.editorEvents, ['change:changesCount']);
  assert.deepEqual(s.listeners, ['menu-save', 'menu-undo', 'menu-redo', 'menu-close-project']);
  assert.deepEqual(s.invokes.filter(call => call.command === 'set_current_project'), [
    { command: 'set_current_project', args: { websiteId: 'public-fixture', websiteName: 'Public fixture' } },
  ]);
  assert.equal(s.invokes.filter(call => call.command === 'mark_unsaved').length, 1);
  assert.equal(s.stores, 1);
  assert.equal(s.undos, 1);
  assert.equal(s.redos, 1);
  assert.equal(s.href, '/');
  assert.equal(s.intervalCount, 0);
});

boundedTest('patched metadata fallback and rejected listeners stay handled without SDK error reporting', () => {
  const f = fixture(sources.bridge, { failMetadata: true, rejectListeners: true });
  f.execute('tick(); emitEditor("change:changesCount");');
  const s = f.snapshot();
  noTelemetry(s);
  assert.equal(s.rejectedListeners, 4);
  assert.deepEqual(s.invokes.filter(call => call.command === 'set_current_project'), [
    { command: 'set_current_project', args: { websiteId: 'public-fixture', websiteName: 'public-fixture' } },
  ]);
  assert.equal(s.invokes.filter(call => call.command === 'mark_unsaved').length, 1);
});

boundedTest('patched MCP component selection capability and state helpers preserve actual behavior', () => {
  const f = fixture(sources.bridge);
  const result = JSON.parse(f.execute(`JSON.stringify((() => {
    const m = window.__silexMcp;
    const found = m.findComponent(editor, 'leaf-id') === leaf && m.findComponent(editor, 'leaf-ccid') === leaf;
    m.setState(leaf, 'public-state', { label: 'Public', hidden: false, expression: [] }, true);
    m.setState(leaf, 'public-state', { label: 'Changed', hidden: true, expression: [] }, true);
    m.setState(leaf, 'private-state', { label: 'Private fixture', hidden: true, expression: [] }, false);
    const changed = m.getState(leaf, 'public-state', true).label;
    const privateLabel = m.getState(leaf, 'private-state', false).label;
    m.removeState(leaf, 'public-state', true);
    return { found, missing: m.findComponent(editor, 'absent') === null, changed, privateLabel,
      removed: m.getState(leaf, 'public-state', true) === null,
      capabilities: m.getCapabilities(), selection: m.getSelectionState(editor),
      persistent: m.getOrCreatePersistantId(leaf) === m.getOrCreatePersistantId(leaf) };
  })())`));
  assert.deepEqual(result, { found: true, missing: true, changed: 'Changed', privateLabel: 'Private fixture',
    removed: true, capabilities: [{ id: 'public-edit', command: 'public-edit' }], persistent: true,
    selection: { breakpoint: 'Desktop', page: 'Public page', component: 'leaf-ccid', selector: '.public-marker' } });
  noTelemetry(f.snapshot());
});

boundedTest('patched MCP data-source expression and delegated state helpers remain available', () => {
  const f = fixture(sources.bridge);
  const result = JSON.parse(f.execute(`JSON.stringify((() => {
    const calls = [];
    window.silex.dataSource = {
      getAllDataSources() { return [{ id: 'public-source' }]; },
      getDataSource(id) { return id === 'public-source' ? {
        id, getQueryables() { return [{ id: 'article', label: 'Article', typeIds: ['article-type'], kind: 'object' }]; },
        getTypes() { return [{ id: 'article-type', fields: [{ id: 'title', label: 'Title', typeIds: [], kind: 'scalar' }] }]; }
      } : null; },
      setState(...args) { calls.push(['set', args[1]]); },
      removeState(...args) { calls.push(['remove', args[1]]); },
      getState() { return 'delegated-public-fixture'; },
      getOrCreatePersistantId() { return 'delegated-id'; }
    };
    const m = window.__silexMcp;
    const tokens = m.resolveExpression(editor, 'public-source.article.title');
    m.setState(leaf, 'state', {}, true); m.removeState(leaf, 'state', true);
    return { fields: tokens.map(token => token.fieldId), calls, delegated: m.getState(leaf, 'state', true),
      persistent: m.getOrCreatePersistantId(leaf), unavailable: m.resolveExpression(editor, 'missing.article').error };
  })())`));
  assert.deepEqual(result, { fields: ['article', 'title'], calls: [['set', 'state'], ['remove', 'state']],
    delegated: 'delegated-public-fixture', persistent: 'delegated-id', unavailable: 'Data source not found: missing' });
  noTelemetry(f.snapshot());
});

boundedTest('patched local and external link callbacks preserve routing without real I/O', () => {
  const f = fixture(sources.bridge);
  f.execute('clickLink("file:///public-fixture"); clickLink("https://public-fixture.invalid/path");'
    + 'clickLink("http://localhost:6805/another-local-page");');
  const s = f.snapshot();
  noTelemetry(s);
  assert.deepEqual(s.invokes.filter(call => call.command === 'open_folder').map(call => call.args.path),
    ['file:///public-fixture', 'https://public-fixture.invalid/path']);
  assert.equal(s.prevented, 2);
  assert.deepEqual(s.fetches, []);
});

boundedTest('patched editor polling and bounded VM refuse real network module access and runaway code', () => {
  const f = fixture(sources.bridge, { editorAvailable: false });
  f.execute('tick();');
  assert.equal(f.snapshot().intervalCount, 1);
  assert.deepEqual(f.snapshot().fetches, []);
  f.execute('settings.editorAvailable = true; tick();');
  assert.equal(f.snapshot().intervalCount, 0);
  assert.deepEqual(f.snapshot().editorEvents, ['change:changesCount']);
  assert.equal(f.execute('typeof process + ":" + typeof require'), 'undefined:undefined');
  assert.throws(() => f.execute('fetch("https://unexpected.invalid/")'), /unexpected bridge network request/);
  noTelemetry(f.snapshot());
  // Never reuse a context after termination with queued microtasks.
  const looping = fixture(sources.bridge);
  assert.throws(() => looping.execute('while (true) {}'), /Script execution timed out/);
  const promises = fixture(sources.bridge);
  assert.throws(() => promises.execute('Promise.resolve().then(function again() { Promise.resolve().then(again); });'),
    /Script execution timed out/);
});
