import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import AxeBuilder from '@axe-core/playwright';
import {chromium, firefox, webkit} from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const site = new URL(process.env.STUDIO_QA_URL || 'http://127.0.0.1:8786/volparossa-studio/');
const output = path.resolve(root, process.env.QA_OUTPUT || 'qa/browser');
const engines = {chromium, firefox, webkit};
const evidence = 'https://github.com/VOLPAROSSA/volparossa-studio/blob/main/docs/IMPLEMENTATION_STATUS.md';
const posterTitle = 'Open Studio Saturday';
const wcagTags = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

async function focused(link) {
  return link.evaluate(element => element === document.activeElement);
}

async function checkFocus(link) {
  assert(await focused(link), `Expected keyboard focus on ${await link.textContent()}`);
  const visible = await link.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return element.matches(':focus-visible') && style.outlineStyle !== 'none' &&
      parseFloat(style.outlineWidth) > 0 && rect.bottom > 0 && rect.right > 0 &&
      rect.top < innerHeight && rect.left < innerWidth;
  });
  assert(visible, `Keyboard focus is not visible on ${await link.textContent()}`);
}

async function checkKeyboard(page, width) {
  const skip = page.locator('.skip-link');
  await page.keyboard.press('Tab');
  await checkFocus(skip);

  const menu = page.locator('.mobile-nav');
  if (width < 500) assert(await menu.isVisible(), 'The shared Menu is missing on mobile');
  const usesMenu = await menu.isVisible();
  if (usesMenu) {
    const summary = menu.locator('summary');
    const discover = menu.getByRole('link', {name: 'Discover'});
    assert.equal(await menu.getAttribute('open'), null);
    assert.equal(await discover.count(), 0, 'Closed Menu links should be hidden');
    await page.keyboard.press('Tab');
    await checkFocus(page.locator('.site-header .brand'));
    await page.keyboard.press('Tab');
    await checkFocus(summary);
    await page.keyboard.press('Enter');
    assert.notEqual(await menu.getAttribute('open'), null);
    await page.keyboard.press('Tab');
    await checkFocus(discover);
    await page.keyboard.press('Shift+Tab');
    await checkFocus(summary);
    await page.keyboard.press('Space');
    assert.equal(await menu.getAttribute('open'), null);
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Shift+Tab');
    await checkFocus(skip);
  }

  await page.keyboard.press('Enter');
  await page.waitForURL(url => url.hash === '#main');
  assert(await focused(page.locator('main')), 'Skip link did not move focus to the main content');
  const explore = page.getByRole('link', {name: 'Explore the workflow'});
  await page.keyboard.press('Tab');
  await checkFocus(explore);
  await page.keyboard.press('Enter');
  await page.waitForURL(url => url.hash === '#workflow');
  assert(await page.getByRole('heading', {name: 'Begin on the canvas.'}).isVisible());

  for (const name of ['Read the test record', 'View implementation status']) {
    const record = page.getByRole('link', {name});
    for (let attempt = 0; attempt < 12 && !await focused(record); attempt++) {
      await page.keyboard.press('Tab');
    }
    await checkFocus(record);
    assert.equal(await record.getAttribute('href'), evidence);
  }
  return {menu: usesMenu, skip: true, workflow: true, evidence: true};
}

async function inspectLayout(page, {width, mode}) {
  const details = await page.evaluate(() => {
    const bounds = element => {
      const {x, y, width, height} = element.getBoundingClientRect();
      return {x, y, width, height};
    };
    const rect = selector => bounds(document.querySelector(selector));
    const diagram = document.querySelector('.studio-network-diagram');
    const hero = document.querySelector('.studio-hero');
    const posterTexts = [...document.querySelectorAll('.studio-poster')].map(element => element.innerText.trim());
    const peerLabels = [...diagram.querySelectorAll('[data-peer]')].map(element => ({
      id: element.dataset.peer,
      label: element.textContent.trim(),
      labelBox: bounds(element.querySelector('strong')),
      iconBox: bounds(element.querySelector('.studio-peer-laptop')),
    }));
    return {
      pageWidth: document.documentElement.scrollWidth,
      rootFontSize: parseFloat(getComputedStyle(document.documentElement).fontSize),
      title: rect('.studio-title-sheet'),
      heroPoster: rect('.pasted-poster'),
      heroEditor: rect('.studio-hero-editor'),
      workflowEditor: rect('.studio-workflow-editor'),
      workflowPhone: rect('.studio-workflow-phone'),
      illustratedTitles: [...hero.querySelectorAll('.studio-poster')].map(poster =>
        bounds([...poster.querySelectorAll('*')].find(element => element.textContent.replace(/\s+/g, ' ').trim() === 'Open Studio Saturday'))),
      posterTexts,
      diagram: bounds(diagram),
      peerLabels,
      edges: [...diagram.querySelectorAll('[data-edge]')].map(edge => edge.dataset.edge.split('-').sort().join('-')),
    };
  });
  assert(details.pageWidth <= width + 1, `Horizontal overflow in ${mode} at ${width}px: ${details.pageWidth}px`);
  for (const key of ['title', 'heroPoster', 'heroEditor', 'workflowEditor', 'workflowPhone', 'diagram']) {
    const box = details[key];
    assert(box.width > 0 && box.height > 0 && box.x >= -1 && box.x + box.width <= width + 1,
      `${key} is outside the viewport at ${width}px (${mode}): ${JSON.stringify(box)}`);
  }
  assert.equal(details.illustratedTitles.length, 2);
  assert(details.illustratedTitles.every(box => box.width > 0 && box.height > 0), 'Poster and editor titles must both remain visible');
  if (width < 500) {
    assert(details.title.y < details.heroPoster.y && details.heroPoster.y < details.heroEditor.y, 'Mobile hero reading order');
    assert(details.workflowEditor.y < details.workflowPhone.y, 'Mobile workflow reading order');
    if (mode !== 'text-200') {
      assert(Math.abs(details.diagram.width - details.diagram.height) <= 1, 'Mobile network figure should be square');
    }
  }
  if (width === 1440 && mode === 'default') {
    assert(details.title.x < details.heroPoster.x && details.heroPoster.x < details.heroEditor.x &&
      details.heroEditor.y < details.heroPoster.y + details.heroPoster.height, 'Desktop poster and editor should sit side by side');
  }
  assert.equal(details.posterTexts.length, 6);
  assert(details.posterTexts.every(text => text.replace(/\s+/g, ' ').includes(posterTitle)), 'Each preview needs the same poster title');
  assert.deepEqual(details.peerLabels.map(peer => peer.id).sort(), ['A', 'B', 'C', 'D']);
  assert.deepEqual(details.edges.sort(), ['A-B', 'A-C', 'A-D', 'B-C', 'C-D']);
  assert(details.peerLabels.every(peer => {
    const {x, width: labelWidth, height: labelHeight} = peer.labelBox;
    return peer.label && labelWidth > 0 && labelHeight > 0 && x >= -1 && x + labelWidth <= width + 1;
  }), 'Network labels must remain visible within the viewport');
  const firstIcon = details.peerLabels[0].iconBox;
  assert(firstIcon.width > 0 && firstIcon.height > 0);
  for (const {iconBox} of details.peerLabels) {
    assert(Math.abs(iconBox.width - firstIcon.width) <= 1 && Math.abs(iconBox.height - firstIcon.height) <= 1,
      'Peer icons must use the same dimensions');
  }
  return details;
}

async function checkAxe(page, label) {
  const result = await new AxeBuilder({page}).withTags(wcagTags).analyze();
  const violations = result.violations.map(item => ({
    rule: item.id,
    nodes: item.nodes.map(node => ({target: node.target, reason: node.failureSummary})),
  }));
  assert.deepEqual(violations, [], label);
  return {violations, passes: result.passes.length, manualChecks: result.incomplete.map(item => item.id)};
}

async function verifyImages(page) {
  for (const image of await page.locator('img').all()) {
    if (await image.isVisible()) {
      await image.scrollIntoViewIfNeeded();
      // Firefox can defer selecting a lazy picture source until after the scroll completes.
      const element = await image.elementHandle();
      await page.waitForFunction(img => img.complete && img.naturalWidth > 0, element, {timeout: 8000});
      await image.evaluate(img => img.decode());
      await element.dispose();
    }
  }
  const ogImage = await page.locator('meta[property="og:image"]').getAttribute('content');
  const imagePath = new URL(ogImage).pathname;
  const dimensions = await page.evaluate(async (source) => {
    const image = new Image();
    image.src = source;
    await image.decode();
    return [image.naturalWidth, image.naturalHeight];
  }, imagePath);
  assert.deepEqual(dimensions, [1200, 630], 'Social card dimensions');
  await page.evaluate(() => window.scrollTo(0, 0));
  return dimensions;
}

async function render(browser, engine, {width, mode}) {
  const height = width < 700 ? 844 : 900;
  const context = await browser.newContext({
    viewport: {width, height}, reducedMotion: 'reduce', javaScriptEnabled: mode !== 'no-js',
  });
  const page = await context.newPage();
  const requests = new Set();
  const errors = [];
  let blockedImages = 0;
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
  });
  page.on('requestfailed', request => {
    if (mode !== 'images-off' || request.resourceType() !== 'image') {
      errors.push(`${request.failure().errorText} ${request.url()}`);
    }
  });
  await context.route('**/*', async route => {
    const request = route.request();
    const resource = new URL(request.url());
    if (resource.origin !== site.origin || !resource.pathname.startsWith(site.pathname)) {
      errors.push(`Unexpected resource ${request.url()}`);
      await route.abort();
    } else if (mode === 'images-off' && request.resourceType() === 'image') {
      blockedImages++;
      await route.abort();
    } else {
      requests.add(resource.pathname);
      await route.continue();
    }
  });
  try {
    assert((await page.goto(site.href, {waitUntil: 'load'})).ok());
    await page.evaluate(() => document.fonts.ready);
    if (mode === 'default') {
      assert((await page.reload({waitUntil: 'load'})).ok(), 'Direct reload of the project route');
      await page.evaluate(() => document.fonts.ready);
    }
    if (mode === 'text-200') {
      const {base, larger} = await page.locator('#workflow .studio-section-copy p').evaluate(copy => {
        const size = () => parseFloat(getComputedStyle(copy).fontSize);
        const base = size();
        document.documentElement.style.fontSize = '200%';
        return {base, larger: size()};
      });
      assert.equal(larger, base * 2, 'The 200% text-size scenario must double the reading text');
    }
    assert(await page.getByRole('heading', {level: 1, name: 'Your canvas. Your website.'}).isVisible());
    const layout = await inspectLayout(page, {width, mode});
    const socialImage = mode === 'default' ? await verifyImages(page) : undefined;
    if (mode === 'images-off') assert(blockedImages > 0, 'Images were not blocked');
    if (mode === 'default' && [390, 1440].includes(width)) {
      await page.screenshot({path: path.join(output, `${engine}-${width}.png`), fullPage: true});
    }
    const keyboard = await checkKeyboard(page, width);
    const accessibility = engine === 'chromium' && mode === 'default' && [390, 1440].includes(width)
      ? await checkAxe(page, 'Studio product page') : undefined;
    let creditsAccessibility;
    if (engine === 'chromium' && mode === 'default' && width === 1440) {
      const credits = new URL('credits/', site);
      assert((await page.goto(credits.href, {waitUntil: 'load'})).ok());
      assert((await page.locator('main').innerText()).includes('Silex Labs and contributors'));
      creditsAccessibility = await checkAxe(page, 'Studio credits');
    }
    assert.deepEqual(errors, []);
    return {engine, width, height, mode, layout, blockedImages, socialImage, keyboard, accessibility,
      creditsAccessibility, localRequests: [...requests].sort()};
  } catch (error) {
    await page.screenshot({path: path.join(output, `${engine}-${width}-${mode}-failure.png`), fullPage: true}).catch(() => {});
    throw error;
  } finally {
    await context.close();
  }
}

await fs.mkdir(output, {recursive: true});
for (const engine of (process.env.QA_ENGINES || 'chromium,firefox').split(',')) {
  assert(engine in engines, `Unknown browser engine: ${engine}`);
  const browser = await engines[engine].launch(engine === 'chromium' ? {executablePath: process.env.CHROME_PATH} : {});
  const widths = engine === 'chromium' ? [1440, 768, 390, 320] : [1440, 390];
  const cases = widths.map(width => ({width, mode: 'default'}));
  if (engine === 'chromium') {
    cases.push(...[1440, 320].map(width => ({width, mode: 'text-200'})));
    cases.push(...[1440, 390].map(width => ({width, mode: 'images-off'})));
    cases.push({width: 390, mode: 'no-js'});
  }
  const results = [];
  try {
    for (const item of cases) {
      results.push(await render(browser, engine, item));
      console.log(`${engine} ${item.width}px ${item.mode} passed`);
    }
  } finally {
    await browser.close();
    await fs.writeFile(path.join(output, `${engine}.json`), JSON.stringify(results, null, 2) + '\n');
  }
}
