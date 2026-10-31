import {chromium} from '@playwright/test';
const [base, tenant, token, sec] = process.argv.slice(2);
const b = await chromium.launch({channel: 'chrome'});
const ctx = await b.newContext({viewport: {width: 1440, height: 900}, locale: 'ar-OM'});
await ctx.addCookies([{name: 'mbq_session', value: token, url: base}, {name: 'mbq_tenant', value: tenant, url: base}]);
const p = await ctx.newPage();
await p.goto(base + '/', {waitUntil: 'networkidle'});
await p.waitForTimeout(1200);
await p.click(`.ni[data-s=${sec}]`);
await p.waitForTimeout(1800);
const r = await p.evaluate(() => {
  const c = document.querySelector('.center');
  const els = [...c.querySelectorAll('button,a,[role=tab]')].filter((e) => e.offsetWidth).map((e) => `${e.tagName}.${e.className}|${(e.textContent||'').trim().slice(0,30)}`);
  return {crumb: document.getElementById('crumb').textContent, els: els.slice(0, 60)};
});
console.log(JSON.stringify(r, null, 1));
await b.close();
