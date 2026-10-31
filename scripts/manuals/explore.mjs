// Explore the app shell: for each section hash, list its visible tabs/sub-navigation so the screenshot crawl can click through them.
// usage: node scripts/manuals/explore.mjs <base> <tenant> <token> [section...]
import {chromium} from '@playwright/test';

const [base, tenant, token, ...only] = process.argv.slice(2);
const SECTIONS = only.length ? only : ['ov', 'pre', 'inv', 'crm', 'mk', 'sal', 'con', 'pmg', 'lp', 'lea', 'post', 'svc', 'fin', 'bill', 'acc', 'hr', 'pay', 'me', 'rep', 'pol', 'log', 'adm'];
const browser = await chromium.launch({channel: 'chrome'});
const ctx = await browser.newContext({viewport: {width: 1440, height: 900}, locale: 'ar-OM', timezoneId: 'Asia/Muscat'});
const url = new URL(base);
await ctx.addCookies([
  {name: 'mbq_session', value: token, url: base},
  {name: 'mbq_tenant', value: tenant, url: base},
]);
const page = await ctx.newPage();
const out = {};
for (const s of SECTIONS) {
  await page.goto(`${base}/#${s}`, {waitUntil: 'networkidle'});
  await page.waitForTimeout(1200);
  out[s] = await page.evaluate(() => {
    const vis = (e) => !!(e.offsetWidth || e.offsetHeight);
    const sec = document.querySelector('.view.on, section.on, main .on') || document.body;
    const tabs = [...document.querySelectorAll('.center [role=tab], .center .tabs button, .center .tabs a, .center .sub button, .center .seg button, .center .tab')].filter(vis).map((e) => (e.textContent || '').trim().slice(0, 40));
    const h = [...document.querySelectorAll('.center h2, .center h3')].filter(vis).map((e) => (e.textContent || '').trim().slice(0, 50)).slice(0, 12);
    const empties = [...document.querySelectorAll('.center .empty, .center .muted')].filter(vis).map((e) => (e.textContent || '').trim().slice(0, 60)).filter((t) => /لا (توجد|يوجد)|فارغ|بعد/.test(t)).slice(0, 8);
    return {title: document.getElementById('crumb')?.textContent, tabs, h, empties, root: sec.id || sec.className};
  });
}
console.log(JSON.stringify(out, null, 1));
await browser.close();
