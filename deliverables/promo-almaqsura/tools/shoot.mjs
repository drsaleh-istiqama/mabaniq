// لقطات شاشة الدليل الترويجي — المقصورة العقارية على بياناتها الحقيقية (0.18.1)، بالعربية وRTL، عرض 1600.
//   MABANIQ_BASE=http://127.0.0.1:8802 MABANIQ_DEMO_PASSWORD=<سر محلي> node deliverables/promo-almaqsura/tools/shoot.mjs [بادئة]
// كلمة المرور لا تظهر في أي لقطة (حقلها مقنَّع). لا تُنشئ هذه الأداة أي بيانات ولا تحصّل أي دفعة — قراءة فقط.
import {chromium} from '@playwright/test';
import {mkdirSync, readFileSync, existsSync, readdirSync, unlinkSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, '..', 'screens');
mkdirSync(OUT, {recursive: true});
const BASE = process.env.MABANIQ_BASE || 'http://127.0.0.1:8802';
const PW = process.env.MABANIQ_DEMO_PASSWORD;
if (!PW) { console.error('MABANIQ_DEMO_PASSWORD غير معيَّن'); process.exit(2); }
const TENANT = 'almaqsura';
const P = {IST: 'بناية الاستقامة — الخوير الجنوبية', MQT: 'الوحدات المملوكة — البرجان 1 و2', SAD: 'محلات سوق السد', AZB: 'أرض العذيبة — للبيع'};
const state = existsSync(join(HERE, 'demo-state.json')) ? JSON.parse(readFileSync(join(HERE, 'demo-state.json'), 'utf8')) : {};
const F = state.focus || {shop: 'IST-A-SW', arrears_lease: 'IST-A-M5', tower_unit: 'MQT-T2-330'};
const only = process.argv[2] ? process.argv[2].split(',') : null; // اختياري: بادئات أسماء اللقطات المطلوب إعادتها (مفصولة بفاصلة)
if (!only) for (const f of readdirSync(OUT)) if (f.endsWith('.png')) unlinkSync(join(OUT, f)); // لقطات النسخة التوضيحية السابقة

const browser = await chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'});
const shots = [];
async function shot(page, name, opts = {}) {
  if (only && !only.some(o => name.startsWith(o))) return;
  await page.waitForTimeout(opts.wait ?? 700);
  const file = join(OUT, `${name}.png`);
  await page.screenshot({path: file, fullPage: !!opts.full, ...(opts.clip ? {clip: opts.clip} : {})});
  shots.push(name); console.log('📸', name);
}
async function ctx(size = {width: 1600, height: 1000}, scale = 1) {
  return browser.newContext({viewport: size, deviceScaleFactor: scale, locale: 'ar-OM', timezoneId: 'Asia/Muscat', colorScheme: 'light'});
}
async function login(page, user) {
  await page.goto(BASE + '/login');
  await page.waitForFunction(() => document.querySelectorAll('#t option').length > 0);
  await page.selectOption('#t', TENANT);
  await page.fill('#u', user);
  await page.fill('#p', PW);
  return page;
}
async function closeModal(page) {
  await page.keyboard.press('Escape'); await page.waitForTimeout(300);
  if (await page.isVisible('#scrim')) { await page.click('#scrim', {force: true, position: {x: 5, y: 5}}); await page.waitForTimeout(300); }
  if (await page.isVisible('#scrim')) await page.evaluate(() => { document.querySelector('#scrim')?.classList.remove('on'); document.querySelectorAll('.modal.on,.sheet.on').forEach(m => m.classList.remove('on')); });
}
async function closeInsp(page) { await page.evaluate(() => { document.body.classList.remove('io'); document.querySelectorAll('tr.sel').forEach(x => x.classList.remove('sel')); }); await page.waitForTimeout(250); }
async function go(page, s) { await closeModal(page); await closeInsp(page); await page.click(`[data-s="${s}"]`); await page.waitForTimeout(900); }
async function sub(page, label) { await page.click(`.subt button:has-text("${label}")`); await page.waitForTimeout(900); }
async function light(page) {
  const isLight = await page.evaluate(() => document.body.classList.contains('light'));
  if (!isLight) { await page.click('#theme'); await page.waitForTimeout(400); }
}
async function project(page, code) { await page.selectOption('#selProj', {label: P[code]}); await page.waitForTimeout(1200); }
async function unitCard(page, code, name) {
  const cell = await page.$(`.cell[data-c="${code}"]`);
  if (cell) { await cell.click(); await page.waitForSelector('body.io', {timeout: 8000}).catch(() => {}); await page.waitForTimeout(1200); await shot(page, name); }
  await closeInsp(page); await closeModal(page);
}

// ───────────────────────────── الموظفون (admin)
{
  const c = await ctx(); const page = await c.newPage();
  await login(page, 'admin');
  await shot(page, '01-login', {wait: 400});
  await page.click('#b');
  await page.waitForURL(u => !u.pathname.startsWith('/login'), {timeout: 20000});
  await page.waitForSelector('#ov', {timeout: 20000});
  await page.waitForTimeout(1500);
  await light(page);
  await shot(page, '02-dashboard', {wait: 1200});
  await shot(page, '02b-dashboard-full', {full: true});

  // المخزون — بناية الاستقامة (534): 42 وحدة على مخطط حي، ثم محل W
  await go(page, 'inv');
  await project(page, 'IST');
  await shot(page, '03-inventory-ist');
  await shot(page, '03b-inventory-ist-full', {full: true});
  await unitCard(page, F.shop, '04-unit-detail-shop');
  // البرجان: 29 وحدة بمساحاتها، ثم أكبر وحدة مؤجرة
  await project(page, 'MQT');
  await shot(page, '05-inventory-towers');
  await shot(page, '05b-inventory-towers-full', {full: true});
  try { await page.selectOption('#selBld', {label: F.tower_unit.split('-')[1]}); await page.waitForTimeout(900); } catch {}
  await unitCard(page, F.tower_unit, '05c-unit-detail-tower');
  // محلات سوق السد
  await project(page, 'SAD');
  await shot(page, '06-inventory-sad');
  // أرض العذيبة — قطاع الأراضي
  await project(page, 'AZB');
  await shot(page, '07-inventory-land');
  await unitCard(page, 'AZB-L-01', '07b-unit-detail-land');

  // التأجير — العقود والمتأخرات (القلب الحقيقي للمحفظة)
  await go(page, 'post');
  await sub(page, 'التأجير'); await page.waitForTimeout(800);
  await shot(page, '08-leasing');
  await shot(page, '08b-leasing-full', {full: true});
  if (F.arrears_lease) {
    const row = page.locator('#postB tr[data-i]', {hasText: F.arrears_lease}).first();
    if (await row.count()) { await row.scrollIntoViewIfNeeded(); await row.click(); await page.waitForTimeout(1000); await shot(page, '09-lease-arrears'); }
  }
  // المساعد — أسئلة على البيانات الحقيقية
  await closeInsp(page);
  await page.click('#askBtn'); await page.waitForTimeout(900);
  await page.fill('#ci', 'ما الإيجارات المتأخرة؟'); await page.press('#ci', 'Enter'); await page.waitForTimeout(2500);
  await shot(page, '10-assistant-leasing');
  await page.fill('#ci', 'ما ملخص المحفظة؟'); await page.press('#ci', 'Enter'); await page.waitForTimeout(2500);
  await shot(page, '10b-assistant-portfolio');
  await page.click('#aiX'); await page.waitForTimeout(400);

  // المالية
  await go(page, 'fin'); await shot(page, '11-finance');

  // التقارير
  await go(page, 'rep'); await shot(page, '12-reports-catalog');
  await page.click('.rcard:has-text("لوحة المحفظة")'); await page.waitForTimeout(2000); await shot(page, '13-report-portfolio'); await shot(page, '13b-report-portfolio-full', {full: true});
  await go(page, 'rep'); await page.click('.rcard:has-text("المخزون والتسعير")'); await page.waitForTimeout(2000); await shot(page, '14-report-inventory', {full: true});
  await go(page, 'rep'); await sub(page, 'منشئ التقارير'); await shot(page, '15-report-builder');

  // تسويق المشاريع — الأرض مشروعًا للبيع، والاستوديو
  await go(page, 'mk'); await shot(page, '16-marketing-board'); await shot(page, '16b-marketing-board-full', {full: true});
  await sub(page, 'استوديو الإعلانات'); await shot(page, '17-ad-studio');

  // سجل التدقيق والإدارة والأمان
  await go(page, 'log'); await shot(page, '18-audit-log');
  await go(page, 'adm'); await shot(page, '19-admin-users');
  await sub(page, 'أماني'); await shot(page, '20-security-2fa');
  await sub(page, 'هوية المستندات والختم'); await shot(page, '21-brand-letterhead');
  await c.close();
}

await browser.close();
console.log(`تم: ${shots.length} لقطة في ${OUT}`);
