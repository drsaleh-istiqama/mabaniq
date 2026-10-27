// فحص تخطيط النسخة الإنجليزية: لا تمرير أفقي بعرض الهاتف في الوضعين الفاتح والداكن، واتجاه LTR، ولا صور مكسورة.
import {chromium} from '@playwright/test';
import {dirname, join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
const HERE = dirname(fileURLToPath(import.meta.url));
const file = pathToFileURL(join(HERE, '..', 'guide-en-print.html')).href;
const browser = await chromium.launch({channel: 'chrome'});
for (const [name, w, scheme] of [['phone', 390, 'light'], ['phone', 390, 'dark'], ['desktop', 1280, 'light'], ['desktop', 1280, 'dark']]) {
  const ctx = await browser.newContext({viewport: {width: w, height: 900}, colorScheme: scheme});
  const page = await ctx.newPage();
  await page.goto(file, {waitUntil: 'networkidle'});
  await page.evaluate(async () => { await document.fonts.ready; for (const i of document.images) { i.loading = 'eager'; if (!i.complete) await new Promise(r => { i.onload = i.onerror = r; }); } });
  const r = await page.evaluate(() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth, dir: getComputedStyle(document.body).direction,
    broken: [...document.images].filter(i => !i.naturalWidth).map(i => i.src.split('/').pop()), bg: getComputedStyle(document.body).backgroundColor,
    over: [...document.querySelectorAll('section *')].filter(e => e.getBoundingClientRect().right > window.innerWidth + 1 && !e.closest('.tablewrap, nav')).length}));
  console.log(name, w, scheme, JSON.stringify(r));
  if (name === 'phone' && scheme === 'dark') await page.screenshot({path: join(HERE, '..', '_en-phone-dark.png'), clip: {x: 0, y: 0, width: 390, height: 1500}});
  await ctx.close();
}
await browser.close();
