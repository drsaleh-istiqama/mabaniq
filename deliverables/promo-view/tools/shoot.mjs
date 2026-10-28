// لقطات شاشة الدليل الترويجي — رؤية العقارية على بياناتها الحقيقية المنشورة (0.19.0)، بالعربية وRTL، عرض 1600.
//   MABANIQ_BASE=http://127.0.0.1:8803 MABANIQ_DEMO_PASSWORD=<سر محلي> node deliverables/promo-view/tools/shoot.mjs [بادئة,بادئة]
// الجزء الأول (v-…): المطوّر «رؤية العقارية». الجزء الثاني (j-…): دورة البيع الكاملة من بيئة العرض العامة (جدوى) — بيانات افتراضية لا تخص رؤية.
// كلمة المرور لا تظهر في أي لقطة (حقلها مقنَّع). لا تُنشئ هذه الأداة أي بيانات ولا تحصّل أي دفعة — قراءة فقط.
import {chromium} from '@playwright/test';
import {mkdirSync, readdirSync, unlinkSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, '..', 'screens');
mkdirSync(OUT, {recursive: true});
const BASE = process.env.MABANIQ_BASE || 'http://127.0.0.1:8803';
const PW = process.env.MABANIQ_DEMO_PASSWORD;
if (!PW) { console.error('MABANIQ_DEMO_PASSWORD غير معيَّن'); process.exit(2); }
const only = process.argv[2] ? process.argv[2].split(',') : null;
if (!only) for (const f of readdirSync(OUT)) if (f.endsWith('.png')) unlinkSync(join(OUT, f));

const browser = await chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'});
const shots = [];
async function shot(page, name, opts = {}) {
  if (only && !only.some(o => name.startsWith(o))) return;
  await page.waitForTimeout(opts.wait ?? 700);
  await page.screenshot({path: join(OUT, `${name}.png`), fullPage: !!opts.full});
  shots.push(name); console.log('📸', name);
}
const ctx = () => browser.newContext({viewport: {width: 1600, height: 1000}, deviceScaleFactor: 1, locale: 'ar-OM', timezoneId: 'Asia/Muscat', colorScheme: 'light'});
async function login(page, tenant, user) {
  await page.goto(BASE + '/login');
  await page.waitForFunction(() => document.querySelectorAll('#t option').length > 0);
  await page.selectOption('#t', tenant);
  await page.fill('#u', user);
  await page.fill('#p', PW);
}
async function enter(page) {
  await page.click('#b');
  await page.waitForURL(u => !u.pathname.startsWith('/login'), {timeout: 20000});
  await page.waitForSelector('#ov', {timeout: 20000});
  await page.waitForTimeout(1500);
  const isLight = await page.evaluate(() => document.body.classList.contains('light'));
  if (!isLight) { await page.click('#theme'); await page.waitForTimeout(400); }
}
async function closeModal(page) {
  await page.keyboard.press('Escape'); await page.waitForTimeout(300);
  if (await page.isVisible('#scrim')) { await page.click('#scrim', {force: true, position: {x: 5, y: 5}}); await page.waitForTimeout(300); }
  if (await page.isVisible('#scrim')) await page.evaluate(() => { document.querySelector('#scrim')?.classList.remove('on'); document.querySelectorAll('.modal.on,.sheet.on').forEach(m => m.classList.remove('on')); });
}
async function closeInsp(page) { await page.evaluate(() => { document.body.classList.remove('io'); document.querySelectorAll('tr.sel').forEach(x => x.classList.remove('sel')); }); await page.waitForTimeout(250); }
async function go(page, s) { await closeModal(page); await closeInsp(page); await page.click(`[data-s="${s}"]`); await page.waitForTimeout(900); }
async function sub(page, label) { await page.click(`.subt button:has-text("${label}")`); await page.waitForTimeout(1000); }
async function project(page, name) { await page.selectOption('#selProj', {label: name}); await page.waitForTimeout(1200); }
async function unitCard(page, code, name) {
  const cell = await page.$(`.cell[data-c="${code}"]`);
  if (cell) { await cell.click(); await page.waitForSelector('body.io', {timeout: 8000}).catch(() => {}); await page.waitForTimeout(1200); await shot(page, name); }
  await closeInsp(page); await closeModal(page);
}
async function ask(page, q, name) {
  if (!(await page.isVisible('#ci'))) { await page.click('#askBtn'); await page.waitForTimeout(800); }
  await page.fill('#ci', q); await page.press('#ci', 'Enter'); await page.waitForTimeout(2500);
  await shot(page, name);
}

// ───────────────────────────── القسم الأول — رؤية العقارية (admin)
{
  const c = await ctx(); const page = await c.newPage();
  await login(page, 'view', 'admin');
  await shot(page, 'v01-login', {wait: 400});
  await enter(page);
  await shot(page, 'v02-dashboard', {wait: 1200});
  await shot(page, 'v02b-dashboard-full', {full: true});

  // المخزون — ستة مشاريع، كل مشروع بخريطة وحداته (المباع داكن، المتاح فاتح)
  await go(page, 'inv');
  await project(page, 'صلالة هيلز'); await shot(page, 'v03-inventory-salalah');
  await shot(page, 'v03b-inventory-salalah-full', {full: true});
  await unitCard(page, 'SLH-A-05', 'v04-unit-sold');
  await unitCard(page, 'SLH-A-24', 'v05-unit-available');
  await project(page, 'فيوو هايتس'); await shot(page, 'v06-inventory-heights');
  await project(page, 'واجهة بركاء'); await shot(page, 'v07-inventory-barka');
  await project(page, 'فيوو جاردنس'); await shot(page, 'v08-inventory-gardens');
  await project(page, 'فيوو بازار'); await shot(page, 'v09-inventory-bazaar');
  await project(page, 'كيان'); await shot(page, 'v10-inventory-kayan');
  // المخططات والتصورات المنشورة
  await project(page, 'صلالة هيلز');
  await page.click('button:has-text("المخططات")'); await page.waitForTimeout(1500); await shot(page, 'v11-plans-render');
  await closeModal(page);

  // العملاء والحجز والعقود (فارغة بصدق — لم تُزوَّد بيانات مشترين)
  await go(page, 'sal'); await shot(page, 'v12-contracts-kyc');
  await sub(page, 'عروض الأسعار'); await shot(page, 'v13-quotes');
  await sub(page, 'الوسطاء والعمولات'); await shot(page, 'v14-brokers');
  await go(page, 'crm'); await shot(page, 'v15-leads');

  // الإنشاء والمستخلصات: تقدم كل مشروع كما نُشر («الحالة»)
  await go(page, 'con'); await page.waitForTimeout(800);
  await shot(page, 'v16-construction');
  await shot(page, 'v16b-construction-full', {full: true});

  // الأقساط والتحصيل
  await go(page, 'fin'); await shot(page, 'v17-liquidity');
  await go(page, 'bill'); await shot(page, 'v18-billing');
  await sub(page, 'حساب الضمان'); await shot(page, 'v19-escrow');
  await go(page, 'post'); await shot(page, 'v20-handover');

  // المساعد
  await closeInsp(page);
  await ask(page, 'ما ملخص المحفظة؟', 'v21-assistant-portfolio');
  await ask(page, 'كم وحدة متاحة؟', 'v21b-assistant-available');
  await ask(page, 'كيف أحجز وحدة؟', 'v21c-assistant-booking');
  await page.click('#aiX').catch(() => {}); await page.waitForTimeout(400);

  // التقارير
  await go(page, 'rep'); await shot(page, 'v22-reports-catalog');
  await page.click('.rcard:has-text("لوحة المحفظة")'); await page.waitForTimeout(2000); await shot(page, 'v23-report-portfolio'); await shot(page, 'v23b-report-portfolio-full', {full: true});
  await go(page, 'rep'); await page.click('.rcard:has-text("المخزون والتسعير")'); await page.waitForTimeout(2000); await shot(page, 'v24-report-inventory', {full: true});
  await go(page, 'rep'); await sub(page, 'منشئ التقارير'); await shot(page, 'v25-report-builder');

  // التسويق
  await go(page, 'mk'); await shot(page, 'v26-marketing-board'); await shot(page, 'v26b-marketing-board-full', {full: true});
  await sub(page, 'استوديو الإعلانات'); await shot(page, 'v27-ad-studio');

  // الحوكمة والأمان
  await go(page, 'log'); await shot(page, 'v28-audit-log');
  await go(page, 'adm'); await shot(page, 'v29-admin-users');
  await sub(page, 'أماني'); await shot(page, 'v30-security-2fa');
  await sub(page, 'هوية المستندات والختم'); await shot(page, 'v31-brand-letterhead');
  await c.close();
}

// ───────────────────────────── القسم الثاني — دورة البيع الكاملة من بيئة العرض (جدوى): بيانات افتراضية
{
  const c = await ctx(); const page = await c.newPage();
  await login(page, 'jadwa', 'admin');
  await enter(page);
  await shot(page, 'j01-dashboard', {wait: 1200});
  await go(page, 'inv'); await page.waitForTimeout(800);
  await shot(page, 'j02-inventory');
  for (const [cls, nm] of [['s', 'j02b-unit-sold'], ['r', 'j02c-unit-reserved']]) {
    const cell = await page.$(`.cell.${cls}`);
    if (cell) { await cell.click(); await page.waitForSelector('body.io', {timeout: 8000}).catch(() => {}); await page.waitForTimeout(1500); await shot(page, nm); await closeInsp(page); await closeModal(page); }
  }
  await go(page, 'sal'); await shot(page, 'j03-kyc-contracts');
  await sub(page, 'عروض الأسعار'); await shot(page, 'j04-quotes');
  await go(page, 'con'); await shot(page, 'j05-ipcs');
  await shot(page, 'j05b-construction-full', {full: true});
  await go(page, 'fin'); await shot(page, 'j06-liquidity');
  await shot(page, 'j06b-liquidity-full', {full: true});
  await go(page, 'bill'); await shot(page, 'j07-invoices');
  await sub(page, 'حساب الضمان'); await shot(page, 'j08-escrow');
  await sub(page, 'تبرعات التأخير (شرط التبرع) والفسخ'); await shot(page, 'j09-late-donations');
  await go(page, 'post'); await shot(page, 'j10-handover');
  await c.close();
}

await browser.close();
console.log(`تم: ${shots.length} لقطة في ${OUT}`);
