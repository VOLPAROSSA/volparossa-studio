// SPDX-License-Identifier: GPL-3.0-only
import assert from 'node:assert/strict';
import { basename } from 'node:path';
import { projectResponse } from './project-storage.mjs';

export const imageName = 'studio-topology.png';
export const imagePath = '/assets/' + imageName;

export async function verifyChart(scope, exported = false) {
  const image = scope.locator('img[src*="' + imageName + '"]');
  assert.equal(await image.count(), 1);
  await image.waitFor({ state: 'visible' });
  const decoded = await image.evaluate(async element => {
    await element.decode();
    return { width: element.naturalWidth, height: element.naturalHeight, path: new URL(element.currentSrc).pathname };
  });
  assert.equal(decoded.width, 1024);
  assert.equal(decoded.height, 768);
  if (exported) assert.equal(decoded.path, imagePath);
  else assert.ok(decoded.path.endsWith(imagePath));
}

// The ordinary FileUploader submits the chosen PNG to the configured FsStorage
// connector. Only the editor attaches and serializes the selected image.
export async function attachChart(page, frame, marker, file, stage) {
  assert.equal(basename(file), imageName);
  stage('image_block');
  const block = page.locator('.gjs-block').filter({ hasText: /^\s*Image\s*$/ }).first();
  if (!await block.isVisible()) await page.locator('[title^="Blocks ("]').click();
  await block.waitFor({ state: 'visible' });
  const wrapper = frame.locator('[data-gjs-type="wrapper"]').first();
  const [source, target, canvas] = await Promise.all([block.boundingBox(), wrapper.boundingBox(),
    page.locator('.gjs-frame').first().boundingBox()]);
  assert.ok(source && target && canvas);
  const left = Math.max(target.x, canvas.x, 0), top = Math.max(target.y, canvas.y, 0);
  const right = Math.min(target.x + target.width, canvas.x + canvas.width, 1440);
  const bottom = Math.min(target.y + target.height, canvas.y + canvas.height, 1000);
  assert.ok(right > left && bottom > top);
  const placer = page.locator('#gjs .gjs-cv-canvas > [data-tools] > .gjs-tools-gl > .gjs-placeholder');
  await placer.waitFor({ state: 'hidden' });
  stage('image_drop');
  await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
  await page.mouse.down();
  await page.mouse.move((left + right) / 2, top + Math.min(170, (bottom - top) * 0.8), { steps: 20 });
  await placer.waitFor({ state: 'visible' });
  await page.mouse.up();
  stage('image_picker');
  const picture = frame.locator('img[data-gjs-type="image"]');
  await picture.waitFor({ state: 'attached' });
  const upload = page.locator('.gjs-am-file-uploader input[type="file"]');
  // Some block configurations activate the inserted image automatically.
  if (await upload.count() === 0 || !await page.locator('.gjs-am-file-uploader').isVisible()) await picture.dblclick();
  await upload.setInputFiles(file);
  stage('image_select');
  const tile = page.locator('.gjs-am-asset-image').filter({ hasText: imageName });
  await tile.waitFor({ state: 'visible' });
  await Promise.all([page.waitForResponse(response => projectResponse(response, 'POST', marker, imagePath)),
    tile.dblclick()]);
  stage('image_decode');
  await verifyChart(frame);
}
