// SPDX-License-Identifier: GPL-3.0-only
export const editorUrl = 'http://127.0.0.1:6805/?id=default&connectorId=fs-storage&lang=en';
const projectUrl = new URL('/api/website?websiteId=default&connectorId=fs-storage', editorUrl);

// The pinned FsStorage API acknowledges a POST after writing the project files.
// Match the synthetic style/text on that write so a prior autosave cannot race
// a fresh editor load. No project data is retained in the receipt.
export function projectResponse(response, method, marker) {
  const url = new URL(response.url());
  const request = response.request();
  if (response.status() !== 200 || request.method() !== method ||
      url.origin !== projectUrl.origin || url.pathname !== projectUrl.pathname ||
      url.searchParams.size !== 2 || url.searchParams.get('websiteId') !== 'default' ||
      url.searchParams.get('connectorId') !== 'fs-storage') return false;
  if (method === 'GET') return true;
  if (method !== 'POST') return false;
  const body = request.postDataBuffer();
  return body !== null && body.length <= 4 * 1024 * 1024 && body.includes(marker) &&
    body.includes('"font-size":"37px"');
}
