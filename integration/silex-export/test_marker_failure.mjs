// SPDX-License-Identifier: GPL-3.0-only
// Pure behavior tests; execute only with the fixture's authenticated hosted Node.
import assert from 'node:assert/strict';
import test from 'node:test';
import { MARKER_OBSERVATION_BUDGET_MS, observeMarkerFailure } from './marker_failure.mjs';

function locator(counts, visibility = []) {
  const seen = { count: 0, visible: 0 };
  return {
    seen,
    async count() { return counts[seen.count++]; },
    async isVisible() { return visibility[seen.visible++]; },
  };
}
async function failed(probe) {
  const primary = new Error('public synthetic primary failure');
  const stages = [];
  await assert.rejects(observeMarkerFailure(async () => { throw primary; }, probe,
    stage => stages.push(stage)), error => error === primary);
  assert.equal(stages.length, 1);
  return stages[0];
}

test('repeated matching absent, ambiguous and hidden snapshots have finite labels', async () => {
  for (const [counts, visibility, expected] of [
    [[0, 0, 0], [], 'marker_absent'],
    [[2, 2, 2], [], 'marker_ambiguous'],
    [[5000, 5000, 5000], [], 'marker_ambiguous'],
    [[1, 1, 1], [false, false], 'marker_hidden'],
  ]) assert.equal(await failed(locator(counts, visibility)), expected);
});

test('visible later, changing counts or changing visibility keep generic failure', async () => {
  for (const [counts, visibility] of [
    [[1, 1, 1], [true, true]], [[0, 1], []], [[2, 3], []],
    [[1, 1, 0], [false, false]], [[1, 1], [false, true]],
  ]) assert.equal(await failed(locator(counts, visibility)), 'marker');
});

test('invalid types and nonfinite or unsafe counts never enter a specific label', async () => {
  for (const count of [true, false, null, undefined, '0', -1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(await failed(locator([count])), 'marker');
  }
  for (const visible of [null, undefined, 0, 1, 'false', {}]) {
    assert.equal(await failed(locator([1], [visible])), 'marker');
  }
});

test('unavailable observation preserves primary identity without inspecting private errors', async () => {
  const privateError = { toString() { throw new Error('must not format errors'); } };
  assert.equal(await failed({ async count() { throw privateError; } }), 'marker');
  assert.equal(await failed({ async count() { return 1; }, async isVisible() { throw privateError; } }), 'marker');
});

test('one finite budget returns generic and late RPC completion cannot publish again', async () => {
  assert.equal(MARKER_OBSERVATION_BUDGET_MS, 200);
  let finish;
  let countCalls = 0;
  const stages = [];
  const primary = new Error('public synthetic timeout failure');
  const operation = observeMarkerFailure(async () => { throw primary; }, {
    count() { ++countCalls; return new Promise(resolve => { finish = resolve; }); },
  }, stage => stages.push(stage));
  await assert.rejects(operation, error => error === primary);
  assert.deepEqual(stages, ['marker']);
  assert.equal(countCalls, 1);
  finish(0);
  // Drain the already-started promise chain without sleeping or issuing a new probe.
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(stages, ['marker']);
  assert.equal(countCalls, 1);
});

test('successful primary check is called exactly once without observation or stage changes', async () => {
  let checks = 0;
  const probe = { count() { throw new Error('observation on success forbidden'); } };
  const result = await observeMarkerFailure(async () => { ++checks; return 7; }, probe,
    () => { throw new Error('recording on success forbidden'); });
  assert.equal(result, 7);
  assert.equal(checks, 1);
});

test('recording failure cannot mask the original assertion or turn failure into success', async () => {
  const primary = new Error('public synthetic marker assertion');
  await assert.rejects(observeMarkerFailure(async () => { throw primary; }, locator([0, 0, 0]),
    () => { throw new Error('public synthetic recorder failure'); }), error => error === primary);
});
