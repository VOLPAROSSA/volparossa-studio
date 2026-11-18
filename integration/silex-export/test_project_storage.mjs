// SPDX-License-Identifier: GPL-3.0-only
import assert from 'node:assert/strict';
import test from 'node:test';
import { containsSavedPage, projectResponse } from './project-storage.mjs';

const endpoint = 'http://127.0.0.1:6805/api/website?websiteId=default&connectorId=fs-storage';
const marker = 'stored synthetic text';
const makeResponse = ({ url = endpoint, method = 'POST', code = 200,
  body = Buffer.from(JSON.stringify({ text: marker, style: { 'font-size': '37px' } })) } = {}) => ({
  status: () => code, url: () => url, request: () => ({ method: () => method,
    postDataBuffer: () => { assert.equal(method, 'POST'); return body; } }),
});

test('only a completed edit to the configured project satisfies the autosave barrier', () => {
  assert.equal(projectResponse(makeResponse(), 'POST', marker), true);
  for (const override of [
    { code: 201 }, { code: 500 }, { method: 'GET' }, { body: null },
    { body: Buffer.from(marker) }, { body: Buffer.from('{"font-size":"37px"}') },
    { body: Buffer.concat([Buffer.from(marker + '"font-size":"37px"'), Buffer.alloc(4 * 1024 * 1024)]) },
    { url: endpoint.replace('6805', '6806') }, { url: endpoint.replace('default', 'another') },
    { url: endpoint.replace('fs-storage', 'another') }, { url: endpoint.replace('/website', '/website/meta') },
    { url: endpoint + '&websiteId=another' },
  ]) assert.equal(projectResponse(makeResponse(override), 'POST', marker), false);
});

test('reopen accepts the filesystem read with either query order and reads no payload', () => {
  const reverse = 'http://127.0.0.1:6805/api/website?connectorId=fs-storage&websiteId=default';
  assert.equal(projectResponse(makeResponse({ method: 'GET', url: reverse }), 'GET'), true);
  assert.equal(projectResponse(makeResponse({ method: 'GET', code: 304 }), 'GET'), false);
  assert.equal(projectResponse(makeResponse(), 'GET'), false);
});

test('readback requires the edited page exactly once with its saved frames', async () => {
  const page = { name: 'Studio export', frames: [{ component: { content: marker } }] };
  function read(pages) {
    return { body: async () => Buffer.from(JSON.stringify({ pages })) };
  }
  assert.equal(await containsSavedPage(read([{ name: 'main' }, page]), marker), true);
  for (const pages of [null, [], [page, page], [{ name: page.name, isFile: true }],
    [{ ...page, name: 'main' }, { name: page.name, frames: [] }]]) {
    assert.equal(await containsSavedPage(read(pages), marker), false);
  }
  for (const length of [0, 4 * 1024 * 1024 + 1]) {
    assert.equal(await containsSavedPage({ body: async () => Buffer.alloc(length) }, marker), false);
  }
});
