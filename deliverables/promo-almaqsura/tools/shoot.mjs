// لقطات شاشة الدليل الترويجي — من المطوّر «المقصورة العقارية» فقط، بالعربية وRTL، عرض 1600.
//   node deliverables/promo-almaqsura/tools/shoot.mjs            (يحتاج MABANIQ_DEMO_PASSWORD في البيئة)
// يُشغَّل على منصة تعمل محليًا (MABANIQ_BASE، افتراضيًا http://127.0.0.1:8800). كلمة المرور لا تظهر في أي لقطة (حقلها مقنَّع).
import {chromium} from '@playwright/test';
import {mkdirSync, readFileSync, existsSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, '..', 'screens');
mkdirSync(OUT, {recursive: true});
const BASE = process.env.MABANIQ_BASE || 'http://127.0.0.1:8800';
const PW = process.env.MABANIQ_DEMO_PASSWORD;
if (!PW) { console.error('MABANIQ_DEMO_PASSWORD غير معيَّن'); process.exit(2); }
const TENANT = 'almaqsura';
const PROJECT = 'مجمع المقصورة التجاري';
const state = existsSync(join(HERE, 'demo-state.json')) ? JSON.parse(readFileSync(join(HERE, 'demo-state.json'), 'utf8')) : {};
const only = process.argv[2]; // اختياري: بادئة اسم اللقطة لإعادة لقطة واحدة

const browser = await chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'});
const shots = [];
async function shot(page, name, opts = {}) {
  if (only && !name.startsWith(only)) return;
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
async function go(page, s) { await page.click(`[data-s="${s}"]`); await page.waitForTimeout(900); }
async function sub(page, label) { await page.click(`.subt button:has-text("${label}")`); await page.waitForTimeout(900); }
async function light(page) {
  const isLight = await page.evaluate(() => document.body.classList.contains('light'));
  if (!isLight) { await page.click('#theme'); await page.waitForTimeout(400); }
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

  // المخزون — مجمع المقصورة التجاري
  await go(page, 'inv');
  await page.selectOption('#selProj', {label: PROJECT});
  await page.waitForTimeout(1200);
  await shot(page, '03-inventory-mqc');
  await shot(page, '03b-inventory-mqc-full', {full: true});
  // وحدة العرض (مكتب متاح) ⟵ تفاصيل + مخطط الطابق
  const ucode = state?.quote?.unit_code || 'MQC-C-101';
  const cell = await page.$(`.cell[data-c="${ucode}"]`) || await page.$('.cell[data-c^="MQC-C-0"]');
  if (cell) { await cell.click(); await page.waitForTimeout(1200); await shot(page, '04-unit-detail-plan', {full: true}); }
  await closeModal(page);
  // المخططات — الطابق الأرضي بعلامات المحلات ثم الطابق الأول
  await page.click('button[data-call="EXT.plans"]'); await page.waitForTimeout(1500);
  const plans = await page.$$('.plan');
  const gf = (await Promise.all(plans.map(async p => ((await p.$$('.mk')).length >= 10 ? p : null)))).find(Boolean);
  if (gf) { await gf.scrollIntoViewIfNeeded(); await page.waitForTimeout(500); }
  await shot(page, '05-plans-gf-markers');
  const f1 = await page.$('.plan img[alt*="الطابق الأول"]');
  if (f1) { await f1.scrollIntoViewIfNeeded(); await page.waitForTimeout(500); await shot(page, '06-plan-f1-offices'); }
  await closeModal(page);

  // العملاء المحتملون
  await go(page, 'crm'); await shot(page, '07-crm');

  // العقود والوسطاء
  await go(page, 'sal'); await shot(page, '08-sales-kyc-contracts');
  await sub(page, 'عروض الأسعار'); await shot(page, '09-sales-quotes');
  await sub(page, 'الوسطاء والعمولات'); await shot(page, '10-sales-brokers');

  // الإنشاء والمستخلصات
  await go(page, 'con'); await shot(page, '11-construction-ipc'); await shot(page, '11b-construction-full', {full: true});

  // التسليم والأملاك — ثم اتحاد الملاك ثم التأجير
  await go(page, 'post'); await shot(page, '12-handover');
  await sub(page, 'اتحاد الملاك'); await shot(page, '13-owners-association');
  await sub(page, 'التأجير'); await page.waitForTimeout(600); await shot(page, '13b-leasing'); await shot(page, '13c-leasing-full', {full: true});

  // خدمة العملاء
  await go(page, 'svc'); await shot(page, '14-service-desk');

  // السيولة والتعثر
  await go(page, 'fin'); await shot(page, '15-finance-radar'); await shot(page, '15b-finance-full', {full: true});

  // الفواتير والضمان
  await go(page, 'bill'); await shot(page, '16-invoices-vat');
  await sub(page, 'تبرعات التأخير'); await shot(page, '17-late-charity');
  await sub(page, 'المطابقة البنكية'); await shot(page, '18-bank-reconciliation');
  await sub(page, 'حساب الضمان'); await shot(page, '19-escrow');

  // التقارير
  await go(page, 'rep'); await shot(page, '20-reports-catalog');
  await page.click('.rcard:has-text("لوحة المحفظة")'); await page.waitForTimeout(2000); await shot(page, '21-report-portfolio'); await shot(page, '21b-report-portfolio-full', {full: true});
  await go(page, 'rep'); await page.click('.rcard:has-text("التحصيل والمتأخرات")'); await page.waitForTimeout(2000); await shot(page, '22-report-collections', {full: true});
  await go(page, 'rep'); await sub(page, 'منشئ التقارير'); await shot(page, '23-report-builder');
  await sub(page, 'المحفوظة والمجدولة'); await shot(page, '23b-reports-saved');

  // تسويق المشاريع
  await go(page, 'mk'); await shot(page, '24-marketing-board'); await shot(page, '24b-marketing-board-full', {full: true});
  await sub(page, 'الحملات'); await shot(page, '25-campaigns');
  await sub(page, 'استوديو الإعلانات'); await shot(page, '26-ad-studio'); await shot(page, '26b-ad-studio-full', {full: true});
  await sub(page, 'التنبيهات التسويقية'); await shot(page, '27-market-alerts');

  // سجل التدقيق
  await go(page, 'log'); await shot(page, '28-audit-log');

  // الإدارة والأمان
  await go(page, 'adm'); await shot(page, '29-admin-users');
  await sub(page, 'أماني'); await shot(page, '30-security-2fa');
  await sub(page, 'هوية المستندات والختم'); await shot(page, '31-brand-letterhead');

  // التحقق العام من مستند
  const code = state?.quote?.verify_code;
  if (code) { await page.goto(`${BASE}/verify/${TENANT}/${code}`); await shot(page, '32-public-verify', {wait: 1000}); }
  await c.close();
}

// ───────────────────────────── تطبيق العميل (client1) — هاتف بدقة ×4 (عرض الصورة 1720)
{
  const c = await ctx({width: 430, height: 900}, 4); const page = await c.newPage();
  await login(page, 'client1'); await page.click('#b');
  await page.waitForURL(u => !u.pathname.startsWith('/login'), {timeout: 20000});
  await page.waitForSelector('nav button[data-t="pay"]', {timeout: 20000}); await page.waitForTimeout(1500);
  await shot(page, '40-client-home', {full: true});
  await page.click('nav button[data-t="pay"]'); await shot(page, '41-client-payments', {full: true});
  await page.click('nav button[data-t="svc"]'); await shot(page, '42-client-service', {full: true});
  await page.click('nav button[data-t="more"]'); await shot(page, '43-client-docs-plans', {full: true});
  await c.close();
}

// ───────────────────────────── بوابة الوسيط (broker1)
{
  const c = await ctx(); const page = await c.newPage();
  await login(page, 'broker1'); await page.click('#b');
  await page.waitForURL(u => !u.pathname.startsWith('/login'), {timeout: 20000}); await page.waitForTimeout(2000);
  await shot(page, '50-broker-portal');
  await c.close();
}

await browser.close();
console.log(`تم: ${shots.length} لقطة في ${OUT}`);
