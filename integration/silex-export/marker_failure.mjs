// SPDX-License-Identifier: GPL-3.0-only
// Optional read-only observations AFTER the original marker check has failed.
// Repeated counts/visibility are snapshots, not proof of why that check failed,
// nor proof that the DOM stayed unchanged between reads. No page text is read.
import { performance } from 'node:perf_hooks';

export const MARKER_OBSERVATION_BUDGET_MS = 200;
const generic = 'marker';

async function snapshotStage(locator, expired) {
  if (expired()) return generic;
  const first = await locator.count();
  if (expired() || !Number.isSafeInteger(first) || first < 0) return generic;
  const firstVisible = first === 1 ? await locator.isVisible() : null;
  if (expired() || (first === 1 && typeof firstVisible !== 'boolean')) return generic;
  const second = await locator.count();
  if (expired() || second !== first) return generic;
  const secondVisible = second === 1 ? await locator.isVisible() : null;
  if (expired() || (second === 1 && (typeof secondVisible !== 'boolean' || secondVisible !== firstVisible))) return generic;
  // Detect a count change during the second visibility query as well.
  const third = await locator.count();
  if (expired() || third !== first) return generic;
  if (first === 0) return 'marker_absent';
  if (first > 1) return 'marker_ambiguous';
  return firstVisible === false ? 'marker_hidden' : generic;
}

async function boundedStage(locator) {
  // ONE monotonic budget, never a fresh timeout for each browser RPC. This does
  // not extend the Core-owned 35s browser deadline. A timed-out RPC may finish
  // later; normal browser/group cleanup still owns it, and it cannot republish.
  const deadline = performance.now() + MARKER_OBSERVATION_BUDGET_MS;
  let stopped = false;
  const expired = () => stopped || performance.now() >= deadline;
  let timer;
  try {
    const timeout = new Promise(resolve => {
      timer = setTimeout(() => {
        // Timer rounding may fire before the monotonic deadline. Stop future
        // RPCs immediately, including continuations of an in-flight snapshot.
        stopped = true;
        resolve(generic);
      }, MARKER_OBSERVATION_BUDGET_MS);
    });
    const observed = snapshotStage(locator, expired)
      .then(stage => expired() ? generic : stage)
      .catch(() => generic);
    return await Promise.race([observed, timeout]);
  } finally {
    stopped = true;
    clearTimeout(timer);
  }
}

export async function observeMarkerFailure(check, locator, recordStage) {
  try {
    return await check();
  } catch (primary) {
    try {
      recordStage(await boundedStage(locator));
    } catch {
      // Optional observation/recording must never replace the original error.
    }
    throw primary;
  }
}
