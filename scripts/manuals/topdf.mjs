// HTML guides → PDF (A4, RTL, page numbers in the footer).  usage: node scripts/manuals/topdf.mjs [key ...]
import {chromium} from '@playwright/test';
import {readdirSync, mkdirSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const base = resolve('deliverables/manuals');
const keys = process.argv.slice(2).length ? process.argv.slice(2) : readdirSync(join(base, 'html')).filter((f) => f.endsWith('.html')).map((f) => f.replace(/\.html$/, ''));
mkdirSync(join(base, 'pdf'), {recursive: true});
const browser = await chromium.launch({channel: 'chrome'});
for (const k of keys) {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(join(base, 'html', `${k}.html`)).href, {waitUntil: 'load'});
  await page.evaluate(() => document.fonts.ready);
  await page.pdf({
    path: join(base, 'pdf', `${k}.pdf`),
    format: 'A4',
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: '<div style="width:100%;font-size:8px;color:#5b6b85;direction:ltr;unicode-bidi:isolate;text-align:center;font-family:Tahoma,Arial"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    margin: {top: '16mm', bottom: '18mm', left: '14mm', right: '14mm'},
  });
  console.log('pdf', k);
  await page.close();
}
await browser.close();
