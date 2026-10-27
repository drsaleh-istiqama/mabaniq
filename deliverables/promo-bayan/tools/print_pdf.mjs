// طباعة guide-en-print.html إلى PDF بحجم A4 عبر Chrome المحلي (Playwright).
//   node deliverables/promo-bayan/tools/print_pdf.mjs [الملف المدخل] [ملف PDF المخرج]
import {chromium} from '@playwright/test';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = join(HERE, '..');
const src = resolve(process.argv[2] || join(PKG, 'guide-en-print.html'));
const out = resolve(process.argv[3] || join(PKG, 'mabaniq-bayan-guide-en.pdf'));

const browser = await chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'});
const page = await browser.newPage({viewport: {width: 1100, height: 1400}});
await page.goto(pathToFileURL(src).href, {waitUntil: 'networkidle'});
await page.evaluate(async () => { await document.fonts.ready; for (const i of document.images) { i.loading = 'eager'; if (!i.complete) await new Promise(r => { i.onload = i.onerror = r; }); } });
await page.emulateMedia({media: 'print', colorScheme: 'light'});
await page.pdf({
  path: out, format: 'A4', printBackground: true, preferCSSPageSize: true, displayHeaderFooter: true,
  headerTemplate: '<span></span>',
  footerTemplate: '<div style="font:8px Arial,sans-serif;color:#5b6b66;width:100%;padding:0 14mm;display:flex;justify-content:space-between"><span>Mabaneek for Bayan Oman · illustrative data</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>',
});
// الغلاف بلا تذييل: يُطبع وحده ثم يستبدل الصفحة الأولى (يُدمج بـpymupdf في الخطوة التالية)
const coverOut = out.replace(/\.pdf$/, '-cover.pdf');
await page.pdf({path: coverOut, format: 'A4', printBackground: true, preferCSSPageSize: true, pageRanges: '1', displayHeaderFooter: false});
await browser.close();
console.log('PDF written:', out, '| cover:', coverOut);
