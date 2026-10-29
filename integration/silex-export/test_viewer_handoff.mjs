// SPDX-License-Identifier: GPL-3.0-only
// Hosted-only private-file/descriptor behavior; no browser or project data.
import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs/promises';
import { constants } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MAX_VIEWER_HANDOFF_BYTES, readViewerHandoff } from './viewer_handoff.mjs';

async function denied(operation) {
  await assert.rejects(operation, error => error instanceof Error
    && error.message === 'invalid_viewer_handoff' && error.cause === undefined);
}
async function privateFile(run, bytes = Buffer.from('{"schema":1,"synthetic":true}')) {
  const root = await fs.mkdtemp(join(tmpdir(), 'studio-handoff-'));
  try {
    const path = join(root, 'input.json');
    await fs.writeFile(path, bytes, { flag: 'wx', mode: 0o600 });
    await run(path, root);
  } finally { await fs.rm(root, { recursive: true, force: true }); }
}
function metadata(size, overrides = {}) {
  return { isFile: () => true, dev: 1n, ino: 2n, mode: 0o100600n,
    uid: BigInt(process.getuid()), gid: 3n, nlink: 1n, size: BigInt(size),
    mtimeNs: 100n, ctimeNs: 200n, ...overrides };
}
function handle(body = Buffer.from('{"schema":1}'), before = metadata(body.length), after = before) {
  const calls = { stat: 0, read: 0, close: 0, maximum: 0 };
  return { calls,
    async stat(options) { assert.deepEqual(options, { bigint: true }); return calls.stat++ === 0 ? before : after; },
    async read(bytes, offset, length, position) {
      ++calls.read;
      calls.maximum = Math.max(calls.maximum, bytes.length);
      assert.equal(offset, position);
      assert.ok(length > 0 && length <= 16384 && offset + length <= MAX_VIEWER_HANDOFF_BYTES + 1);
      const part = body.subarray(position, position + length);
      part.copy(bytes, offset);
      return { bytesRead: part.length, buffer: bytes };
    },
    async close() { ++calls.close; },
  };
}

test('actual private regular file and strict multibyte UTF8 are read successfully', async () => {
  await privateFile(async path => {
    assert.deepEqual(await readViewerHandoff(path), { schema: 1, synthetic: true });
  });
  await privateFile(async path => {
    assert.deepEqual(await readViewerHandoff(path), { label: 'é' });
  }, Buffer.from('{"label":"é"}'));
});

test('actual symlinks, permissions, hardlinks and directories fail closed', async () => {
  await privateFile(async (path, root) => {
    const alias = join(root, 'symlink');
    await fs.symlink(path, alias);
    await denied(readViewerHandoff(alias));
    await denied(readViewerHandoff(root));
    await fs.chmod(path, 0o640);
    await denied(readViewerHandoff(path));
    await fs.chmod(path, 0o600);
    const hardlink = join(root, 'hardlink');
    await fs.link(path, hardlink);
    await denied(readViewerHandoff(path));
  });
});

test('actual exact size bound succeeds and oversize input is refused', async () => {
  assert.equal(MAX_VIEWER_HANDOFF_BYTES, 131072);
  const bytes = Buffer.from(`{"padding":"${'x'.repeat(MAX_VIEWER_HANDOFF_BYTES - 14)}"}`);
  assert.equal(bytes.length, MAX_VIEWER_HANDOFF_BYTES);
  await privateFile(async path => {
    const value = await readViewerHandoff(path);
    assert.equal(value.padding.length, MAX_VIEWER_HANDOFF_BYTES - 14);
    await fs.appendFile(path, ' ');
    await denied(readViewerHandoff(path));
  }, bytes);
});

test('malformed JSON, UTF8 and leading BOM return only closed error text', async () => {
  for (const bytes of [Buffer.from('{'), Buffer.from([0x7b, 0xff, 0x7d]),
    Buffer.from([0xc0, 0xaf]), Buffer.from('\ufeff{"schema":1}')]) {
    await privateFile(async path => { await denied(readViewerHandoff(path)); }, bytes);
  }
});

test('one fixed open supplies both stats and all bounded reads and closes on success', async t => {
  const source = handle();
  const opened = [];
  t.mock.method(fs, 'open', async (...args) => { opened.push(args); return source; });
  t.mock.method(fs, 'stat', () => { throw new Error('path stat forbidden'); });
  t.mock.method(fs, 'readFile', () => { throw new Error('path read forbidden'); });
  assert.deepEqual(await readViewerHandoff('/synthetic/handoff'), { schema: 1 });
  assert.deepEqual(opened, [['/synthetic/handoff', constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK]]);
  assert.equal(source.calls.stat, 2);
  assert.equal(source.calls.maximum, MAX_VIEWER_HANDOFF_BYTES + 1);
  assert.equal(source.calls.close, 1);
});

test('invalid initial FD metadata denies before allocation/read and still closes', async t => {
  let source;
  t.mock.method(fs, 'open', async () => source);
  for (const override of [{ isFile: () => false }, { uid: BigInt(process.getuid()) + 1n },
    { mode: 0o100640n }, { mode: 0o104600n }, { nlink: 2n }, { size: -1n },
    { size: BigInt(MAX_VIEWER_HANDOFF_BYTES + 1) }, { size: 13 }, { mtimeNs: undefined }]) {
    source = handle(undefined, metadata(13, override));
    await denied(readViewerHandoff('/synthetic/handoff'));
    assert.equal(source.calls.read, 0);
    assert.equal(source.calls.close, 1);
  }
});

test('growth, truncation and changed post-read FD identity or nanosecond metadata deny', async t => {
  let source;
  t.mock.method(fs, 'open', async () => source);
  const body = Buffer.from('{"schema":1}');
  const sources = [handle(Buffer.concat([body, Buffer.from(' ')]), metadata(body.length)),
    handle(body, metadata(body.length + 1)),
    handle(Buffer.alloc(MAX_VIEWER_HANDOFF_BYTES + 1, 0x20), metadata(MAX_VIEWER_HANDOFF_BYTES))];
  for (const field of ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs']) {
    const before = metadata(body.length);
    sources.push(handle(body, before, { ...before, [field]: before[field] + 1n }));
  }
  for (source of sources) {
    await denied(readViewerHandoff('/synthetic/handoff'));
    assert.equal(source.calls.close, 1);
  }
});

test('open/stat/read/parse/close failures never expose underlying errors and close acquired FD', async t => {
  let source;
  let failOpen = false;
  const privateError = { toString() { throw new Error('error formatting forbidden'); } };
  t.mock.method(fs, 'open', async () => { if (failOpen) throw privateError; return source; });
  failOpen = true;
  await denied(readViewerHandoff('/synthetic/handoff'));
  failOpen = false;
  for (const operation of ['stat', 'post-stat', 'read', 'bad-read-count', 'parse', 'close']) {
    source = handle(operation === 'parse' ? Buffer.from('{') : undefined);
    if (operation === 'stat') source.stat = async () => { throw privateError; };
    if (operation === 'post-stat') {
      const originalStat = source.stat;
      source.stat = async options => { if (source.calls.stat > 0) throw privateError; return originalStat(options); };
    }
    if (operation === 'read') source.read = async () => { throw privateError; };
    if (operation === 'bad-read-count') source.read = async () => ({ bytesRead: MAX_VIEWER_HANDOFF_BYTES + 2 });
    if (operation === 'close') source.close = async () => { ++source.calls.close; throw privateError; };
    await denied(readViewerHandoff('/synthetic/handoff'));
    assert.equal(source.calls.close, 1);
  }
});
