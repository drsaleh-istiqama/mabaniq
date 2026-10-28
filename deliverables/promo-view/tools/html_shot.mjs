// فحص النسخة التفاعلية index.html: الاتجاه RTL، عدم وجود تمرير أفقي، لقطة سطح المكتب والجوال.
//   node deliverables/promo-view/tools/html_shot.mjs <مجلد المخرجات>
import {chromium} from '@playwright/test';
import {mkdirSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(process.argv[2] || join(HERE, '_crops'));
mkdirSync(OUT, {recursive: true});
const url = pathToFileURL(join(HERE, '..', 'index.html')).href;
const browser = await chromium.launch({channel: 'chrome'});
for (const [name, vp] of [['desktop', {width: 1280, height: 900}], ['mobile', {width: 390, height: 844}]]) {
  const page = await browser.newPage({viewport: vp});
  await page.goto(url, {waitUntil: 'load'});
  await page.waitForTimeout(800);
  const info = await page.evaluate(() => ({dir: document.documentElement.dir, lang: document.documentElement.lang, sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
    imgs: [...document.images].filter(i => !i.complete || !i.naturalWidth).length, nImgs: document.images.length}));
  console.log(name, JSON.stringify(info));
  await page.screenshot({path: join(OUT, `html-${name}-top.png`)});
  await page.evaluate(() => document.querySelector('#t3')?.scrollIntoView());
  await page.waitForTimeout(500);
  await page.screenshot({path: join(OUT, `html-${name}-mid.png`)});
  await page.close();
}
await browser.close();
