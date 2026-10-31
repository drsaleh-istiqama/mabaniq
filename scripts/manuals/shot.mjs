// One extra screenshot for a guide: open a section, click a sequence of things by visible text, then take the picture (the open dialog if there is one, else the content area).
// usage: node scripts/manuals/shot.mjs <user> <section> <out.png> [--tab "نص التبويب"] [--click "نص" ...] [--row N] [--wait ms]
//   --click "نص"   clicks the first visible button/link/row/cell containing that text (repeatable, in order)
//   --row N        clicks the N-th (1-based) table row of the content area before taking the picture
// Server: http://127.0.0.1:8802 (tenant bayan, the throw-away demo database). Never submits anything on purpose: it only opens things.
import {chromium} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdirSync} from 'node:fs';
import {dirname} from 'node:path';

const args = process.argv.slice(2);
const [user, sec, out] = args;
const opt = (name) => { const r = []; args.forEach((a, i) => { if (a === name && args[i + 1] !== undefined) r.push(args[i + 1]); }); return r; };
const base = process.env.MANUAL_BASE || 'http://127.0.0.1:8802';
const SP = process.env.MANUAL_SCRATCH || 'C:/Users/Istiqama/AppData/Local/Temp/claude/C--DrSaleh/62dec15e-6b79-4641-8616-33957f9fba05/scratchpad';
const tok = execFileSync('C:/mabaniq/.venv/Scripts/python.exe', [`${SP}/mint_session.py`, `${SP}/audit_bayan/m.db`, 'bayan', user], {encoding: 'utf8'}).split(/\r?\n/)[0].split(' ')[1];
mkdirSync(dirname(out), {recursive: true});
const b = await chromium.launch({channel: 'chrome'});
const ctx = await b.newContext({viewport: {width: 1440, height: 900}, locale: 'ar-OM', timezoneId: 'Asia/Muscat'});
await ctx.addCookies([{name: 'mbq_session', value: tok, url: base}, {name: 'mbq_tenant', value: 'bayan', url: base}]);
await ctx.addInitScript(() => { try { localStorage.setItem('mbq-theme', 'l'); } catch (e) { /* blocked */ } });
const p = await ctx.newPage();
await p.goto(base + '/', {waitUntil: 'networkidle'});
await p.waitForTimeout(1200);
await p.click(`.ni[data-s="${sec}"]`);
await p.waitForTimeout(1500);
const tab = opt('--tab')[0];
if (tab) { await p.locator('.center button', {hasText: tab}).filter({visible: true}).first().click(); await p.waitForTimeout(1300); }
for (const t of opt('--click')) {
  await p.locator('.center, #mbox').locator('button, a, tr, td, .card, label', {hasText: t}).filter({visible: true}).first().click({timeout: 5000});
  await p.waitForTimeout(1100);
}
const row = opt('--row')[0];
if (row) { await p.locator('.center tbody tr').filter({visible: true}).nth(Number(row) - 1).click(); await p.waitForTimeout(1200); }
await p.waitForTimeout(Number(opt('--wait')[0] || 300));
const modal = await p.evaluate(() => { const m = document.querySelector('#modal.on #mbox'); if (!m) return null; const r = m.getBoundingClientRect(); return {x: Math.max(0, Math.floor(r.x - 12)), y: Math.max(0, Math.floor(r.y - 12)), width: Math.ceil(r.width + 24), height: Math.ceil(Math.min(r.height + 24, window.innerHeight))}; });
if (modal) {
  await p.screenshot({path: out, clip: modal});
} else {
  const h = await p.evaluate(() => Math.max(document.querySelector('.center').scrollHeight, document.documentElement.scrollHeight));
  await p.setViewportSize({width: 1440, height: Math.min(Math.max(h + 10, 760), 2400)});
  await p.waitForTimeout(300);
  const box = await p.evaluate(() => { const r = document.querySelector('.center').getBoundingClientRect(); return {x: Math.floor(r.x), y: 0, width: Math.ceil(r.width), height: Math.ceil(Math.min(r.height, window.innerHeight))}; });
  await p.screenshot({path: out, clip: box});
}
console.log('saved', out, modal ? '(dialog)' : '(screen)');
await b.close();
