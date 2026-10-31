// Screenshot crawl for the operating manuals: every section of the shell, every tab inside it, light theme, RTL, full height.
// Writes <out>/<tenant>/<section>/<NN>-<tab>.png and <out>/<tenant>/manifest.json (title, tab, headings, text excerpt, empty-state notes) that the guide writers read.
// usage: node scripts/manuals/crawl.mjs <base> <tenant> <token> <outDir> [section...]
import {chromium} from '@playwright/test';
import {mkdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';

const [base, tenant, token, outDir, ...only] = process.argv.slice(2);
const SECTIONS = only.length ? only : ['ov', 'pre', 'inv', 'crm', 'mk', 'sal', 'con', 'pmg', 'lp', 'lea', 'post', 'svc', 'fin', 'bill', 'acc', 'hr', 'pay', 'me', 'rep', 'pol', 'log', 'adm'];
const W = 1440;
const browser = await chromium.launch({channel: 'chrome'});
const ctx = await browser.newContext({viewport: {width: W, height: 900}, locale: 'ar-OM', timezoneId: 'Asia/Muscat', deviceScaleFactor: 1});
await ctx.addCookies([{name: 'mbq_session', value: token, url: base}, {name: 'mbq_tenant', value: tenant, url: base}]);
await ctx.addInitScript(() => { try { localStorage.setItem('mbq-theme', 'l'); } catch (e) { /* storage blocked */ } });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)));
page.on('response', (r) => { if (r.status() >= 500) errors.push(`${r.status()} ${r.url().slice(0, 120)}`); });

const slug = (s) => s.replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '').slice(0, 24) || 'x';
const manifest = [];

const ACTIONS = process.env.MANUAL_ACTIONS !== '0';
// every "+ …" button of the screen opens a form or dialog: take a picture of it (never submit), then close it again
async function actionShots(sec, tab, idx, reopen) {
  const labels = await page.evaluate(() => [...document.querySelectorAll('.center button')].filter((b) => (b.offsetWidth || b.offsetHeight) && /^\s*\+/.test(b.textContent)).map((b) => b.textContent.trim().replace(/\s+/g, ' ').slice(0, 40)));
  let n = 0;
  for (const lab of [...new Set(labels)].slice(0, 3)) {
    const b = page.locator('.center button', {hasText: lab}).filter({visible: true}).first();
    try { await b.click({timeout: 3000}); } catch (e) { continue; }
    await page.waitForTimeout(900);
    const dir = join(outDir, tenant, sec);
    mkdirSync(dir, {recursive: true});
    const file = join(dir, `${String(idx).padStart(2, '0')}-${slug(tab)}-act${++n}.png`);
    const modal = await page.evaluate(() => { const m = document.querySelector('#modal.on #mbox'); if (!m) return null; const r = m.getBoundingClientRect(); return {x: Math.max(0, Math.floor(r.x - 12)), y: Math.max(0, Math.floor(r.y - 12)), width: Math.ceil(r.width + 24), height: Math.ceil(Math.min(r.height + 24, window.innerHeight))}; });
    if (modal && modal.width > 200) await page.screenshot({path: file, clip: modal}); else await page.screenshot({path: file});
    const txt = await page.evaluate(() => (document.querySelector('#modal.on #mbox') || document.querySelector('.center'))?.innerText.replace(/\s+/g, ' ').slice(0, 500));
    manifest.push({section: sec, tab, kind: 'action', button: lab, file: file.replace(outDir, '').replace(/\\/g, '/'), modal: !!modal, excerpt: txt});
    console.log(sec, '|', tab, '| action', lab, modal ? '(modal)' : '(inline)');
    await page.evaluate(() => document.getElementById('modal')?.classList.remove('on'));
    await page.waitForTimeout(250);
    await reopen();
  }
}

async function shot(sec, idx, label) {
  // grow the viewport to the content so the picture is the whole screen, not the first 900 px
  const h = await page.evaluate(() => {
    const c = document.querySelector('.center');
    const sc = [...c.querySelectorAll('*')].reduce((m, e) => Math.max(m, e.scrollHeight && getComputedStyle(e).overflowY !== 'visible' ? e.scrollHeight : 0), 0);
    return Math.max(c.scrollHeight, sc, document.documentElement.scrollHeight);
  });
  await page.setViewportSize({width: W, height: Math.min(Math.max(h + 10, 760), 2400)});
  await page.waitForTimeout(350);
  const dir = join(outDir, tenant, sec);
  mkdirSync(dir, {recursive: true});
  const file = join(dir, `${String(idx).padStart(2, '0')}-${slug(label)}.png`);
  const box = await page.evaluate(() => { const r = document.querySelector('.center').getBoundingClientRect(); return {x: Math.floor(r.x), y: 0, width: Math.ceil(r.width), height: Math.ceil(Math.min(r.height, window.innerHeight))}; });
  await page.screenshot({path: file, clip: box});
  const info = await page.evaluate(() => {
    const c = document.querySelector('.center');
    const vis = (e) => !!(e.offsetWidth || e.offsetHeight);
    const text = (c.innerText || '').replace(/\s+/g, ' ').trim();
    const heads = [...c.querySelectorAll('h1,h2,h3,h4,.ttl,.card > b')].filter(vis).map((e) => e.textContent.trim().slice(0, 60)).slice(0, 14);
    const emptyHits = text.match(/(لا (توجد|يوجد)[^.|]{0,40}|لم (يُسجَّل|يتم)[^.|]{0,40}|فارغ[^.|]{0,30})/g) || [];
    const rows = c.querySelectorAll('tbody tr').length;
    return {crumb: document.getElementById('crumb')?.textContent, heads, emptyHits: emptyHits.slice(0, 6), rows, chars: text.length, excerpt: text.slice(0, 700)};
  });
  manifest.push({section: sec, tab: label, file: file.replace(outDir, '').replace(/\\/g, '/'), ...info});
  await page.setViewportSize({width: W, height: 900});
  console.log(sec, '|', label, '| rows', info.rows, '| chars', info.chars, info.emptyHits.length ? '| EMPTY? ' + info.emptyHits.join(' / ') : '');
}

await page.goto(base + '/', {waitUntil: 'networkidle'});
await page.waitForTimeout(1500);
for (const sec of SECTIONS) {
  const nav = page.locator(`.ni[data-s="${sec}"]`);
  if (!(await nav.count()) || !(await nav.first().isVisible())) { console.log(sec, '| not visible for this user'); continue; }
  await nav.first().click();
  await page.waitForTimeout(1600);
  // the tab strip = the container (inside .center) holding the highest number of sibling buttons, one of which carries class "on"
  const tabs = await page.evaluate(() => {
    const c = document.querySelector('.center');
    let best = null;
    for (const on of c.querySelectorAll('button.on')) {
      const par = on.parentElement;
      const bs = [...par.children].filter((x) => x.tagName === 'BUTTON' && x.offsetWidth);
      if (bs.length >= 2 && (!best || bs.length > best.length)) best = bs;
    }
    return best ? best.map((b) => (b.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40)) : [];
  });
  if (!tabs.length) { await shot(sec, 1, 'main'); if (ACTIONS) await actionShots(sec, 'main', 1, async () => {}); continue; }
  let i = 1;
  for (const t of tabs) {
    const btn = page.locator('.center button', {hasText: t}).filter({visible: true}).first();
    try { await btn.click({timeout: 4000}); } catch (e) { console.log(sec, '| cannot click tab', t); continue; }
    await page.waitForTimeout(1300);
    await shot(sec, i, t);
    if (ACTIONS) await actionShots(sec, t, i, async () => { try { await btn.click({timeout: 3000}); await page.waitForTimeout(900); } catch (e) { /* tab gone */ } });
    i++;
  }
}
writeFileSync(join(outDir, tenant, 'manifest.json'), JSON.stringify({errors, shots: manifest}, null, 1), 'utf-8');
console.log('errors:', errors.length, errors.slice(0, 6));
await browser.close();
