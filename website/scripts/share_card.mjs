/** Render the actual Studio artwork and Silex illustration into its 1200×630 social card. */
import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'
const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH || undefined})
try {
  const page = await browser.newPage({viewport:{width:1200,height:630},deviceScaleFactor:1})
  await page.goto(process.env.STUDIO_URL || 'http://127.0.0.1:8786/volparossa-studio/')
  await page.locator('.studio-hero').waitFor()
  await page.evaluate(() => {
    const wall = document.querySelector('.studio-wall-scene').cloneNode(true)
    const poster = document.querySelector('.pasted-poster').cloneNode(true)
    const editor = document.querySelector('.silex-editor').cloneNode(true)
    const copy = document.createElement('div')
    copy.className = 'share-copy'
    copy.innerHTML = '<p>VOLPAROSSA Studio</p><h1>Your canvas.<br>Your website.</h1>'
    document.body.replaceChildren(wall, copy, poster, editor)
  })
  await page.addStyleTag({content:`
    body.studio-page {position:relative; isolation:isolate; overflow:hidden; height:630px; display:grid; grid-template-columns:33% 23% 44%; gap:0; align-items:center; padding:50px 38px; border-bottom:12px solid #183c9b;}
    .share-copy {position:relative; z-index:2; background:#f5eddf; padding:47px 24px; box-shadow:0 3px 8px #2a1b1366; transform:rotate(-1deg);}
    .share-copy h1 {font:700 61px/.92 var(--serif); letter-spacing:-.045em; margin:20px 0 0;}
    .share-copy p {font:700 16px/1.3 var(--sans); letter-spacing:.065em; color:#863918;}
    .pasted-poster {width:100%; margin:0; align-self:center; z-index:1;}
    .silex-editor {width:100%; transform:rotate(1deg);}
  `})
  await page.evaluate(async () => {await document.fonts.ready; await Promise.all([...document.images].map(im => im.decode().catch(()=>{})))})
  await page.screenshot({path:fileURLToPath(new URL('../assets/studio/social.jpg',import.meta.url)),quality:88,type:'jpeg'})
} finally {await browser.close()}
