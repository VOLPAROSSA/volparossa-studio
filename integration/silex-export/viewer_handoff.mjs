// SPDX-License-Identifier: GPL-3.0-only
// One private descriptor supplies BOTH metadata and bytes. No path re-open/read.
import fs from 'node:fs/promises';
import { constants } from 'node:fs';
import { TextDecoder } from 'node:util';

export const MAX_VIEWER_HANDOFF_BYTES = 131072;
const metadataFields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const invalid = () => new Error('invalid_viewer_handoff');

function admissible(metadata) {
  return metadata.isFile() === true
    && metadataFields.every(field => typeof metadata[field] === 'bigint')
    && metadata.uid === BigInt(process.getuid())
    && (metadata.mode & 0o7777n) === 0o600n && metadata.nlink === 1n
    && metadata.size >= 0n && metadata.size <= BigInt(MAX_VIEWER_HANDOFF_BYTES);
}

export async function readViewerHandoff(path) {
  let source;
  try {
    if (!Number.isInteger(constants.O_RDONLY) || !Number.isInteger(constants.O_NOFOLLOW)
        || constants.O_NOFOLLOW <= 0 || !Number.isInteger(constants.O_NONBLOCK)
        || constants.O_NONBLOCK <= 0 || typeof process.getuid !== 'function') throw invalid();
    source = await fs.open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    const before = await source.stat({ bigint: true });
    if (!admissible(before)) throw invalid();
    const bytes = Buffer.alloc(MAX_VIEWER_HANDOFF_BYTES + 1);
    let count = 0;
    while (count < bytes.length) {
      const maximum = Math.min(16384, bytes.length - count);
      const { bytesRead } = await source.read(bytes, count, maximum, count);
      if (!Number.isSafeInteger(bytesRead) || bytesRead < 0 || bytesRead > maximum) throw invalid();
      if (bytesRead === 0) break;
      count += bytesRead;
      if (count > MAX_VIEWER_HANDOFF_BYTES || BigInt(count) > before.size) throw invalid();
    }
    const after = await source.stat({ bigint: true });
    if (BigInt(count) !== before.size || !admissible(after)
        || metadataFields.some(field => before[field] !== after[field])) throw invalid();
    // Decode only after bounded EOF and FD stability checks. Keep a leading BOM
    // as a character for JSON.parse to reject, matching the previous JSON reader.
    const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true })
      .decode(bytes.subarray(0, count));
    return JSON.parse(text);
  } catch {
    // Never expose the path, contents, underlying error text or error cause.
    throw invalid();
  } finally {
    if (source) {
      try { await source.close(); }
      catch { throw invalid(); }
    }
  }
}
