// طباعة الشرائح والمختصر ودليل التجربة الإنجليزية إلى PDF (حجم الصفحة من @page في كل ملف).
//   node deliverables/promo-bayan/tools/print_extras_en.mjs
import {chromium} from '@playwright/test';
import {dirname, join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const PKG = join(dirname(fileURLToPath(import.meta.url)), '..');
const JOBS = [
  ['slides-en-print.html', 'mabaniq-bayan-slides-en.pdf', {width: '1280px', height: '720px'}],
  ['brief-en-print.html', 'mabaniq-bayan-brief-en.pdf', {}],
  ['trial-en-print.html', 'mabaniq-bayan-trial-guide-en.pdf', {}],
];
const browser = await chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'});
for (const [src, out, size] of JOBS) {
  const page = await browser.newPage({viewport: {width: 1280, height: 720}});
  await page.goto(pathToFileURL(join(PKG, src)).href, {waitUntil: 'networkidle'});
  await page.evaluate(async () => { await document.fonts.ready; for (const i of document.images) { i.loading = 'eager'; if (!i.complete) await new Promise(r => { i.onload = i.onerror = r; }); } });
  await page.emulateMedia({media: 'print', colorScheme: 'light'});
  await page.pdf({path: join(PKG, out), printBackground: true, preferCSSPageSize: true, ...size});
  await page.close();
  console.log('PDF written:', out);
}
await browser.close();
