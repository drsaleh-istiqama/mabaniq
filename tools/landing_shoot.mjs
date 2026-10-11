// Landing-page screenshots (0.14.0) — from the GENERIC demo developer `jadwa` only (demo data, no client names), Arabic RTL,
// light theme, JPEG ≤ 200 KB each, written to web/img/landing/ (Vite hashes them into /static/assets/).
//   MABANIQ_DEMO_PASSWORD=<test value> node tools/landing_shoot.mjs [name-prefix]
// Needs a platform running locally (MABANIQ_BASE, default http://127.0.0.1:8800) and the quote created by tools/landing_assets.py.
// The password is read from the environment only and never appears in a shot (the login field is masked; no login shot is taken).
import {chromium} from '@playwright/test';
import {mkdirSync, statSync, writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, '..', 'web', 'img', 'landing');
mkdirSync(OUT, {recursive: true});
const BASE = process.env.MABANIQ_BASE || 'http://127.0.0.1:8800';
const PW = process.env.MABANIQ_DEMO_PASSWORD;
if (!PW) { console.error('MABANIQ_DEMO_PASSWORD غير معيَّن'); process.exit(2); }
const TENANT = 'jadwa';
const MAX_KB = 200;
const only = process.argv[2];

const browser = await chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'});
const shots = [];
async function shot(page, name, opts = {}) {
  if (only && !name.startsWith(only)) return;
  await page.waitForTimeout(opts.wait ?? 800);
  const file = join(OUT, `${name}.jpg`);
  for (const quality of [86, 78, 70, 62, 55]) {
    const buf = await page.screenshot({type: 'jpeg', quality, fullPage: !!opts.full, ...(opts.clip ? {clip: opts.clip} : {})});
    writeFileSync(file, buf);
    if (buf.length / 1024 <= MAX_KB) break;
  }
  const kb = (statSync(file).size / 1024).toFixed(0);
  shots.push(name); console.log('📸', name, kb + ' KB');
}
async function ctx(size = {width: 1440, height: 900}, scale = 1) {
  return browser.newContext({viewport: size, deviceScaleFactor: scale, locale: 'ar-OM', timezoneId: 'Asia/Muscat', colorScheme: 'light'});
}
async function login(page, user) {
  await page.goto(BASE + '/login');
  await page.waitForFunction(() => document.querySelectorAll('#t option').length > 0);
  await page.selectOption('#t', TENANT);
  await page.fill('#u', user);
  await page.fill('#p', PW);
  await page.click('#b');
  await page.waitForURL(u => !u.pathname.startsWith('/login'), {timeout: 20000});
}
async function closeModal(page) {
  await page.keyboard.press('Escape'); await page.waitForTimeout(300);
  if (await page.isVisible('#scrim')) await page.evaluate(() => { document.querySelector('#scrim')?.classList.remove('on'); document.querySelectorAll('.modal.on,.sheet.on').forEach(m => m.classList.remove('on')); });
}
async function go(page, s) { await page.click(`[data-s="${s}"]`); await page.waitForTimeout(1000); }
async function sub(page, label) { await page.click(`.subt button:has-text("${label}")`); await page.waitForTimeout(1000); }
async function light(page) {
  const isLight = await page.evaluate(() => document.body.classList.contains('light'));
  if (!isLight) { await page.click('#theme'); await page.waitForTimeout(400); }
}

// ───────────────────────────── staff (admin)
{
  const c = await ctx(); const page = await c.newPage();
  await login(page, 'admin');
  await page.waitForSelector('#ov', {timeout: 20000});
  await page.waitForTimeout(1500);
  await light(page);
  await shot(page, 'dashboard', {wait: 1200});

  await go(page, 'inv');
  await page.waitForTimeout(800);
  await shot(page, 'inventory');
  await closeModal(page);

  await go(page, 'sal');
  await sub(page, 'عروض الأسعار');
  await shot(page, 'quotes');

  await go(page, 'fin'); await shot(page, 'finance');
  await go(page, 'bill'); await shot(page, 'billing');

  await go(page, 'mk'); await shot(page, 'marketing');
  await sub(page, 'استوديو الإعلانات'); await shot(page, 'ad-studio');

  await go(page, 'rep');
  await page.click('.rcard:has-text("لوحة المحفظة")'); await page.waitForTimeout(2200);
  await shot(page, 'report');

  await go(page, 'log'); await shot(page, 'audit');
  await go(page, 'adm'); await sub(page, 'أماني'); await shot(page, 'security');
  await c.close();
}

// ───────────────────────────── customer app (client1) — phone ×2
{
  const c = await ctx({width: 430, height: 900}, 2); const page = await c.newPage();
  await login(page, 'client1');
  await page.waitForSelector('nav button[data-t="pay"]', {timeout: 20000}); await page.waitForTimeout(1500);
  await shot(page, 'client-home');
  await page.click('nav button[data-t="pay"]'); await shot(page, 'client-payments');
  await c.close();
}

await browser.close();
console.log(`تم: ${shots.length} لقطة في ${OUT}`);
