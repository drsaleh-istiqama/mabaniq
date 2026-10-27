// يطبع ops-manual-print.html إلى PDF (A4) بتذييل عربي، ثم يطبع الغلاف وحده بلا تذييل ليُدمج مكان الصفحة الأولى.
//   node deliverables/promo-bayan/ops-manual/tools/print_ops.mjs
import {chromium} from '@playwright/test';
import {dirname, join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const OPS = join(dirname(fileURLToPath(import.meta.url)), '..');
const src = join(OPS, 'ops-manual-print.html');
const out = join(OPS, 'mabaniq-bayan-ops-manual.pdf');
const browser = await chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'});
const page = await browser.newPage({viewport: {width: 1100, height: 1400}});
await page.goto(pathToFileURL(src).href, {waitUntil: 'networkidle'});
await page.evaluate(async () => { await document.fonts.ready; for (const i of document.images) { i.loading = 'eager'; if (!i.complete) await new Promise(r => { i.onload = i.onerror = r; }); } });
await page.emulateMedia({media: 'print', colorScheme: 'light'});
const foot = '<div dir="rtl" style="font:8.5px Arial,Tahoma,sans-serif;color:#5b6b66;width:100%;padding:0 14mm;display:flex;justify-content:space-between;direction:rtl"><span>دليل التشغيل · مبانيك لمؤسسة بيان العقارية · بيانات افتراضية</span><span>صفحة <span class="pageNumber"></span> من <span class="totalPages"></span></span></div>';
await page.pdf({path: out, format: 'A4', printBackground: true, preferCSSPageSize: true, displayHeaderFooter: true, headerTemplate: '<span></span>', footerTemplate: foot});
const coverOut = out.replace(/\.pdf$/, '-cover.pdf');
await page.pdf({path: coverOut, format: 'A4', printBackground: true, preferCSSPageSize: true, pageRanges: '1', displayHeaderFooter: false});
await browser.close();
console.log('PDF written:', out, '| cover:', coverOut);
