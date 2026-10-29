// SPDX-License-Identifier: GPL-3.0-only
// Original local project UI. Backend ownership, path confinement and concurrent
// metadata updates remain backend responsibilities; this is no authority boundary.
export const LIMITS = Object.freeze({
  projects: 256, listBytes: 1_048_576, metadataBytes: 65_536,
  acknowledgementBytes: 4_096, actionMilliseconds: 15_000,
});

const MESSAGES = Object.freeze({
  unavailable: 'The local project service is unavailable. Try Refresh.',
  invalid: 'The project response could not be used safely. No automatic retry was made.',
  limit: 'The local project data exceeds this dashboard’s limits.',
  name: 'Use 1–128 characters without control characters, and at least one non-space character.',
  metadata: 'These project settings cannot be preserved safely. Rename was not sent.',
  stale: 'Refresh the project list before making changes.',
  busy: 'Wait for the current action to finish.',
  deadline: 'The action timed out. No automatic retry was made.',
  uncertain: 'The result is uncertain. Refresh before making more changes.',
  reload: 'A request did not finish. Reload this dashboard before continuing.',
  closed: 'The dashboard has closed.',
});

export class DashboardError extends Error {
  constructor(code) { super(MESSAGES[code]); this.name = 'DashboardError'; this.code = code; }
}
const fail = (code = 'invalid') => { throw new DashboardError(code); };
const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const encoder = new TextEncoder();

function wellFormed(text) {
  for (let index = 0; index < text.length; index += 1) {
    const unit = text.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = text.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) return false;
  }
  return true;
}

export function validName(value) {
  return typeof value === 'string' && wellFormed(value)
    && value.trim().length > 0 && [...value].length <= 128
    && encoder.encode(value).length <= 512
    && !/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/u.test(value);
}

function validId(value) {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(value);
}

// Compare decimal values before/after the JS JSON roundtrip without binary
// arithmetic. Insignificant zeros/exponent notation may change; values may not.
function decimalForm(token) {
  const [mantissa, exponent = '0'] = token.toLowerCase().split('e');
  const negative = mantissa.startsWith('-');
  const unsigned = negative ? mantissa.slice(1) : mantissa;
  const [whole, fraction = ''] = unsigned.split('.');
  let digits = (whole + fraction).replace(/^0+/, '');
  if (!digits) return '0';
  let scale = Number(exponent) - fraction.length;
  while (digits.endsWith('0')) { digits = digits.slice(0, -1); scale += 1; }
  return `${negative ? '-' : ''}${digits}e${scale}`;
}

// Bound geometry and reject duplicate object keys BEFORE JSON.parse can discard
// them. Preservation mode additionally refuses precision-losing numeric tokens.
export function parseBoundedJson(text, preserveNumbers = false) {
  if (typeof text !== 'string' || text.length > LIMITS.listBytes) fail('limit');
  let cursor = 0;
  let nodes = 0;
  const numbers = /-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/y;
  const whitespace = () => { while (/[\t\n\r ]/.test(text[cursor] ?? '\0')) cursor += 1; };
  function string() {
    const start = cursor;
    if (text[cursor++] !== '"') fail();
    let closed = false;
    while (cursor < text.length) {
      const unit = text[cursor++];
      if (unit === '"') { closed = true; break; }
      if (unit === '\\') cursor += 1;
      if (cursor - start > 16_386) fail('limit');
    }
    if (!closed) fail();
    let value;
    try { value = JSON.parse(text.slice(start, cursor)); } catch { fail(); }
    if (!wellFormed(value) || value.length > 4_096) fail('limit');
    return value;
  }
  function value(depth) {
    whitespace();
    nodes += 1;
    if (depth > 16 || nodes > 4_096) fail('limit');
    const next = text[cursor];
    if (next === '"') { string(); return; }
    if (next === '{' || next === '[') {
      const object = next === '{';
      const end = object ? '}' : ']';
      const keys = new Set();
      cursor += 1; whitespace();
      if (text[cursor] === end) { cursor += 1; return; }
      for (;;) {
        if (object) {
          const key = string();
          if (keys.has(key)) fail();
          keys.add(key); whitespace();
          if (text[cursor++] !== ':') fail();
        }
        value(depth + 1); whitespace();
        if (text[cursor] === end) { cursor += 1; return; }
        if (text[cursor++] !== ',') fail();
        whitespace();
      }
    }
    for (const literal of ['true', 'false', 'null']) {
      if (text.startsWith(literal, cursor)) { cursor += literal.length; return; }
    }
    numbers.lastIndex = cursor;
    const match = numbers.exec(text);
    if (!match || match[0].length > 128) fail();
    const token = match[0];
    const number = Number(token);
    if (!Number.isFinite(number)) fail();
    if (preserveNumbers && (Object.is(number, -0)
      || (Number.isInteger(number) && !Number.isSafeInteger(number))
      || decimalForm(token) !== decimalForm(JSON.stringify(number)))) fail('metadata');
    cursor += token.length;
  }
  value(0); whitespace();
  if (cursor !== text.length) fail();
  try { return JSON.parse(text); } catch { return fail(); }
}

function settingsGeometry(settings) {
  if (!record(settings)) fail('metadata');
  let nodes = 0;
  function visit(value, depth) {
    nodes += 1;
    if (nodes > 512 || depth > 8) fail('metadata');
    if (typeof value === 'string' && value.length > 1_024) fail('metadata');
    if (value && typeof value === 'object') {
      for (const [key, child] of Object.entries(value)) {
        if (key.length > 128) fail('metadata');
        visit(child, depth + 1);
      }
    }
  }
  visit(settings, 0);
}

export function writableMetadata(meta, id, name) {
  if (!record(meta) || meta.websiteId !== id || !validName(name)) fail('metadata');
  const known = ['websiteId', 'name', 'imageUrl', 'connectorUserSettings', 'createdAt', 'updatedAt', 'repoUrl', 'pagesUrl'];
  if (Object.keys(meta).some(key => !known.includes(key))) fail('metadata');
  if (!validName(meta.name)) fail('metadata');
  const settings = own(meta, 'connectorUserSettings') ? meta.connectorUserSettings : {};
  settingsGeometry(settings);
  const result = { name, connectorUserSettings: settings };
  if (own(meta, 'imageUrl')) {
    if (meta.imageUrl !== null && (typeof meta.imageUrl !== 'string' || meta.imageUrl.length > 4_096)) fail('metadata');
    result.imageUrl = meta.imageUrl;
  }
  const json = JSON.stringify(result);
  if (encoder.encode(json).length > LIMITS.metadataBytes) fail('metadata');
  return json;
}

function projectList(value) {
  if (!Array.isArray(value) || value.length > LIMITS.projects) fail('limit');
  const result = new Map();
  for (const item of value) {
    if (!record(item) || !validId(item.websiteId) || !validName(item.name) || result.has(item.websiteId)) fail();
    // Deliberately retain no images, local file URLs, settings or timestamps.
    result.set(item.websiteId, Object.freeze({ id: item.websiteId, name: item.name }));
  }
  return result;
}

function apiPath(kind = '', id) {
  const query = new URLSearchParams();
  if (id !== undefined) { if (!validId(id)) fail(); query.set('websiteId', id); }
  query.set('connectorId', 'fs-storage');
  return `/api/website/${kind}?${query.toString()}`;
}

function acknowledgement(value, created = false) {
  const keys = created ? ['websiteId', 'message'] : ['message'];
  if (!record(value) || Object.keys(value).length !== keys.length
    || keys.some(key => !own(value, key)) || typeof value.message !== 'string'
    || value.message.length > 1_024 || (created && !validId(value.websiteId))) fail();
  // Message text is untrusted and is never displayed or used as an identifier.
}

export class ProjectController {
  #fetch; #now; #setTimer; #clearTimer; #onChange;
  #projects = new Map(); #active = null; #generation = 0;
  #requiresRefresh = true; #disposed = false; #error = null; #completed = false;
  #reloadRequired = false;

  constructor({ fetch = globalThis.fetch.bind(globalThis), now = () => performance.now(),
    setTimer = globalThis.setTimeout.bind(globalThis), clearTimer = globalThis.clearTimeout.bind(globalThis),
    onChange = () => {} } = {}) {
    this.#fetch = fetch; this.#now = now; this.#setTimer = setTimer;
    this.#clearTimer = clearTimer; this.#onChange = onChange;
  }

  snapshot() {
    return Object.freeze({ projects: Object.freeze([...this.#projects.values()]),
      busy: this.#active !== null, requiresRefresh: this.#requiresRefresh,
      reloadRequired: this.#reloadRequired, error: this.#error, completed: this.#completed });
  }

  #notify() { if (!this.#disposed) this.#onChange(this.snapshot()); }
  #check(operation) {
    if (this.#disposed || this.#generation !== operation.generation) fail('closed');
    if (operation.abort.signal.aborted || this.#now() >= operation.deadline) fail('deadline');
  }

  #wait(operation, pending, lateValue = () => {}) {
    // Every transport await races the SAME action's abort/deadline. A transport
    // may ignore AbortSignal; never leave the UI busy awaiting that promise.
    // One abandoned wait permanently closes this controller to further I/O,
    // including Refresh. Reloading is an explicit user action, not a retry.
    return new Promise((resolve, reject) => {
      let finished = false;
      let abandoned = false;
      const abort = () => {
        if (finished) return;
        finished = true; abandoned = true;
        this.#reloadRequired = true;
        operation.abort.signal.removeEventListener('abort', abort);
        reject(new DashboardError(this.#disposed ? 'closed' : 'deadline'));
      };
      operation.abort.signal.addEventListener('abort', abort, { once: true });
      Promise.resolve(pending).then(value => {
        if (finished) {
          if (abandoned) { try { lateValue(value); } catch { /* No late effects. */ } }
          return;
        }
        finished = true;
        operation.abort.signal.removeEventListener('abort', abort);
        resolve(value);
      }, error => {
        if (finished) return; // Consume even a late transport rejection.
        finished = true;
        operation.abort.signal.removeEventListener('abort', abort);
        reject(error);
      });
      if (operation.abort.signal.aborted) abort();
    });
  }

  async #request(operation, kind, id, method, maximum, body, preserveNumbers = false) {
    this.#check(operation);
    const options = { method, mode: 'same-origin', credentials: 'same-origin',
      cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer', signal: operation.abort.signal,
      headers: { Accept: 'application/json' } };
    if (body !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = body; }
    if (method !== 'GET') operation.mutationSent = true;
    let response;
    try {
      response = await this.#wait(operation, this.#fetch(apiPath(kind, id), options), late => {
        // A late fetch result may own an unread body. Request cancellation, but
        // do not re-open capacity or claim a browser/network join when it settles.
        try { void Promise.resolve(late?.body?.cancel()).catch(() => {}); } catch { /* Closed page. */ }
      });
    }
    catch { this.#check(operation); fail('unavailable'); }
    let reader;
    let consumed = false;
    let primary = null;
    try {
      this.#check(operation);
      if (response.status !== 200 || response.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json') fail('unavailable');
      const declared = response.headers.get('content-length');
      if (declared !== null && (!/^[0-9]+$/.test(declared) || Number(declared) > maximum)) fail('limit');
      if (!response.body) fail();
      reader = response.body.getReader();
      const chunks = [];
      let total = 0;
      for (;;) {
        this.#check(operation);
        const part = await this.#wait(operation, reader.read());
        this.#check(operation);
        if (part.done) { consumed = true; break; }
        if (!(part.value instanceof Uint8Array)) fail();
        total += part.value.byteLength;
        if (total > maximum) fail('limit');
        chunks.push(part.value);
        // Bound even a hostile stream made of tiny/empty chunks.
        if (chunks.length > 4_096) fail('limit');
      }
      const bytes = new Uint8Array(total);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      let text;
      try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch { fail(); }
      return parseBoundedJson(text, preserveNumbers);
    } catch (error) {
      primary = error;
      throw error;
    } finally {
      try {
        // Bound cancellation too; a stuck cancel must not permit a sequence of
        // abandoned bodies. Preserve the original failure if cleanup also fails.
        if (reader && !consumed) await this.#wait(operation, reader.cancel());
        else if (!reader && response?.body) await this.#wait(operation, response.body.cancel());
      } catch (error) {
        this.#reloadRequired = true;
        if (!primary) throw error instanceof DashboardError ? error : new DashboardError('unavailable');
      } finally {
        try { reader?.releaseLock(); }
        catch { this.#reloadRequired = true; if (!primary) fail('unavailable'); }
      }
    }
  }

  async #reload(operation) {
    const list = projectList(await this.#request(operation, '', undefined, 'GET', LIMITS.listBytes));
    this.#check(operation);
    this.#projects = list;
    this.#requiresRefresh = false;
    this.#completed = true;
  }

  async #action(mutation, work) {
    if (this.#disposed) fail('closed');
    if (this.#active) fail('busy');
    if (this.#reloadRequired) { this.#error = 'reload'; this.#notify(); fail('reload'); }
    if (mutation && this.#requiresRefresh) { this.#error = 'stale'; this.#notify(); fail('stale'); }
    const operation = { abort: new AbortController(), generation: ++this.#generation,
      deadline: this.#now() + LIMITS.actionMilliseconds, mutationSent: false };
    this.#active = operation; this.#error = null;
    const timer = this.#setTimer(() => operation.abort.abort(), LIMITS.actionMilliseconds);
    this.#notify();
    try {
      await work(operation);
      this.#check(operation);
    } catch (error) {
      const code = operation.mutationSent ? 'uncertain'
        : error instanceof DashboardError ? error.code : 'unavailable';
      if (operation.mutationSent || !mutation || this.#reloadRequired) this.#requiresRefresh = true;
      this.#error = code;
      throw new DashboardError(code);
    } finally {
      this.#clearTimer(timer); operation.abort.abort(); this.#active = null;
      this.#notify();
    }
  }

  #selected(id) {
    if (!validId(id) || !this.#projects.has(id)) fail('stale');
    return this.#projects.get(id);
  }

  refresh() { return this.#action(false, operation => this.#reload(operation)); }

  create(name) {
    return this.#action(true, async operation => {
      if (!validName(name)) fail('name');
      if (this.#projects.size >= LIMITS.projects) fail('limit');
      const created = await this.#request(operation, '', undefined, 'PUT', LIMITS.acknowledgementBytes,
        JSON.stringify({ name, connectorUserSettings: {} }));
      acknowledgement(created, true);
      await this.#reload(operation);
      if (!this.#projects.has(created.websiteId)) fail();
    });
  }

  rename(id, name) {
    return this.#action(true, async operation => {
      this.#selected(id);
      if (!validName(name)) fail('name');
      // Fresh metadata prevents knowingly overwriting a stale local snapshot.
      // GET+POST is not atomic and confers no cross-client concurrency guarantee.
      const fresh = await this.#request(operation, 'meta', id, 'GET', LIMITS.metadataBytes, undefined, true);
      const body = writableMetadata(fresh, id, name);
      acknowledgement(await this.#request(operation, 'meta', id, 'POST', LIMITS.acknowledgementBytes, body));
      await this.#reload(operation);
      if (this.#projects.get(id)?.name !== name) fail();
    });
  }

  duplicate(id) {
    return this.#action(true, async operation => {
      const project = this.#selected(id);
      if (this.#projects.size >= LIMITS.projects || !validName(`${project.name} copy`)) fail('limit');
      acknowledgement(await this.#request(operation, 'duplicate', id, 'POST', LIMITS.acknowledgementBytes));
      await this.#reload(operation);
    });
  }

  delete(id) {
    return this.#action(true, async operation => {
      this.#selected(id);
      acknowledgement(await this.#request(operation, '', id, 'DELETE', LIMITS.acknowledgementBytes));
      await this.#reload(operation);
      if (this.#projects.has(id)) fail();
    });
  }

  editorPath(id) {
    if (this.#disposed || this.#active || this.#requiresRefresh || this.#reloadRequired) fail('stale');
    this.#selected(id);
    return `/?id=${encodeURIComponent(id)}&connectorId=fs-storage`;
  }

  dispose() {
    this.#disposed = true; this.#generation += 1;
    this.#active?.abort.abort(); this.#projects.clear();
  }
}

export function mountDashboard(document, browser = globalThis) {
  const element = id => document.getElementById(id);
  const list = element('projects');
  const refresh = element('refresh-button');
  const name = element('new-name');
  const renameDialog = element('rename-dialog');
  const deleteDialog = element('delete-dialog');
  let selectedRename = null;
  let selectedDelete = null;
  let returnFocus = null;
  let pendingFocusKey = null;
  const safely = promise => { void promise.catch(() => {}); };

  function render(state) {
    const focusKey = document.activeElement?.dataset?.focusKey ?? pendingFocusKey;
    pendingFocusKey = state.busy ? focusKey : null;
    const disabled = state.busy || state.requiresRefresh || state.reloadRequired;
    refresh.disabled = state.busy || state.reloadRequired;
    element('create-button').disabled = disabled;
    name.disabled = state.busy || state.reloadRequired;
    element('projects-section').setAttribute('aria-busy', String(state.busy));
    element('error').hidden = state.error === null;
    element('error').textContent = state.error ? MESSAGES[state.error] : '';
    element('status').textContent = state.reloadRequired ? MESSAGES.reload : state.busy ? 'Working…'
      : state.requiresRefresh ? 'Refresh is required before changing projects.'
        : `${state.projects.length} local ${state.projects.length === 1 ? 'project' : 'projects'}.`;
    element('empty').hidden = !state.completed || state.busy || state.requiresRefresh || state.projects.length !== 0;
    const rows = [];
    let focusTarget;
    for (const project of state.projects) {
      const row = document.createElement('li'); row.className = 'project';
      const label = document.createElement('bdi'); label.className = 'project-name';
      label.textContent = project.name;
      const actions = document.createElement('div'); actions.className = 'project-actions';
      for (const action of ['Open', 'Rename', 'Duplicate', 'Delete']) {
        const button = document.createElement('button'); button.type = 'button';
        button.textContent = action; button.disabled = disabled;
        button.setAttribute('aria-label', `${action} project: ${project.name}`);
        button.dataset.focusKey = `${project.id}:${action}`;
        if (button.dataset.focusKey === focusKey) focusTarget = button;
        button.addEventListener('click', () => {
          if (action === 'Open') {
            try { browser.location.replace(controller.editorPath(project.id)); } catch { /* Closed UI, no navigation. */ }
          } else if (action === 'Duplicate') safely(controller.duplicate(project.id));
          else if (action === 'Rename') {
            returnFocus = button; selectedRename = project.id;
            element('rename-name').value = project.name;
            element('rename-name').setCustomValidity('');
            renameDialog.showModal(); element('rename-name').focus();
          } else {
            returnFocus = button; selectedDelete = project.id;
            element('delete-name').textContent = project.name;
            deleteDialog.showModal(); element('delete-cancel').focus();
          }
        });
        actions.append(button);
      }
      row.append(label, actions); rows.push(row);
    }
    list.replaceChildren(...rows);
    if (focusTarget && !focusTarget.disabled) focusTarget.focus();
    else if (focusKey && !state.busy) refresh.focus();
  }

  const controller = new ProjectController({ fetch: browser.fetch.bind(browser),
    now: () => browser.performance.now(), setTimer: browser.setTimeout.bind(browser),
    clearTimer: browser.clearTimeout.bind(browser), onChange: render });
  refresh.addEventListener('click', () => safely(controller.refresh()));
  name.addEventListener('input', () => name.setCustomValidity(''));
  element('rename-name').addEventListener('input', () => element('rename-name').setCustomValidity(''));
  function nameAllowed(input) {
    input.setCustomValidity(validName(input.value) ? '' : MESSAGES.name);
    return input.reportValidity();
  }
  element('new-form').addEventListener('submit', event => {
    event.preventDefault();
    if (nameAllowed(name)) safely(controller.create(name.value).then(() => { name.value = ''; name.focus(); }));
  });
  element('rename-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!nameAllowed(element('rename-name'))) return;
    const id = selectedRename; const value = element('rename-name').value;
    renameDialog.close(); safely(controller.rename(id, value));
  });
  element('delete-form').addEventListener('submit', event => {
    event.preventDefault();
    const id = selectedDelete; deleteDialog.close(); safely(controller.delete(id));
  });
  for (const [dialog, cancel] of [[renameDialog, 'rename-cancel'], [deleteDialog, 'delete-cancel']]) {
    element(cancel).addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => {
      selectedRename = null; selectedDelete = null;
      if (returnFocus?.isConnected) returnFocus.focus(); else refresh.focus();
      returnFocus = null;
    });
    // Native dialog Escape/cancel semantics and focus trapping are preserved.
  }
  browser.addEventListener('pagehide', () => controller.dispose(), { once: true });
  safely(controller.refresh());
  return controller;
}

if (typeof document !== 'undefined') mountDashboard(document);
