// لقطات «دليل التشغيل» — من المطوّر «بيان عمان» فقط، بالعربية وRTL، مع علامات مرقّمة تطابق خطوات الدليل.
//   MABANIQ_BASE=http://127.0.0.1:8831 MABANIQ_DEMO_PASSWORD=… node deliverables/promo-bayan/ops-manual/tools/shoot_ops.mjs [بادئة اسم اللقطة]
// يُشغَّل على نسخة محلية معزولة (بيانات مستنسخة)، لأن بعض اللقطات تنفّذ إجراءً فعليًا (حجز، مطابقة بنكية). كلمة المرور من البيئة فقط
// ولا تظهر في أي لقطة (تُكتب كلمة وهمية في حقل الدخول المعروض).
import {chromium} from '@playwright/test';
import {mkdirSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, '..', 'shots');
mkdirSync(OUT, {recursive: true});
const BASE = process.env.MABANIQ_BASE || 'http://127.0.0.1:8831';
const PW = process.env.MABANIQ_DEMO_PASSWORD;
if (!PW) { console.error('MABANIQ_DEMO_PASSWORD غير معيَّن'); process.exit(2); }
const TENANT = 'bayan', PROJECT = 'مساحات الخوض';
const only = process.argv[2];
const SCALE = 1.5;

const browser = await chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'});
const done = [], failed = [];

const ctx = (size = {width: 1180, height: 1300}, scale = SCALE, extra = {}) =>
  browser.newContext({viewport: size, deviceScaleFactor: scale, locale: 'ar-OM', timezoneId: 'Asia/Muscat', colorScheme: 'light', bypassCSP: true, ...extra});

const LOGINS = [];
async function login(page, user, {submit = true} = {}) {
  // حدّ الدخول في المنصة 10 محاولات/دقيقة: نتمهّل عند الاقتراب منه
  const now = Date.now(); while (LOGINS.length && now - LOGINS[0] > 60000) LOGINS.shift();
  if (LOGINS.length >= 8) { await new Promise(r => setTimeout(r, 61000 - (now - LOGINS[0]))); LOGINS.length = 0; }
  LOGINS.push(Date.now());
  await page.goto(BASE + '/login');
  await page.waitForFunction(() => document.querySelectorAll('#t option').length > 0);
  await page.selectOption('#t', TENANT);
  await page.fill('#u', user);
  await page.fill('#p', PW);
  if (!submit) return;
  await page.click('#b');
  await page.waitForURL(u => !u.pathname.startsWith('/login'), {timeout: 20000});
  await page.waitForTimeout(1200);
  await page.addStyleTag({content: 'body.io .scrim{display:none!important}'}).catch(() => {});  // الغطاء المعتّم يحجب النقرات واللقطات
}
const lightTheme = async page => { if (!(await page.evaluate(() => document.body.classList.contains('light')))) { await page.click('#theme').catch(() => {}); await page.waitForTimeout(300); } };
const go = async (page, s) => { await closeInsp(page); await page.click(`[data-s="${s}"]`); await page.waitForTimeout(1000); };
const sub = async (page, label) => { await closeInsp(page); await page.click(`.subt button:has-text("${label}")`); await page.waitForTimeout(1000); };
// وحدات متاحة قابلة للبيع: نستثني وحدات محفظة التأجير المحتفظ بها (تظهر متاحة لكن لا تُحجز للبيع)
const RETAINED = ['MSK-M-001', 'MSK-M-005', 'MSK-M-012', 'MSK-M-103', 'MSK-M-108', 'MSK-M-205'];
const sellable = async page => (await page.$$eval('#heat .cell.a', els => els.map(e => e.dataset.c))).filter(c => !RETAINED.includes(c));
const closeInsp = page => page.evaluate(() => document.body.classList.remove('io'));
const closeModal = async page => { await page.keyboard.press('Escape'); await page.waitForTimeout(300); };

// علامات مرقّمة: [محدِّد أو locator, رقم, {pos:'tl'|'tr'|'bl'|'br'|'r'|'l'}]
async function mark(page, list) {
  const items = [];
  for (const [sel, n, o = {}] of list) {
    const loc = typeof sel === 'string' ? page.locator(sel).first() : sel.first();
    let bb = null;
    try { bb = await loc.boundingBox({timeout: 2500}); } catch {}
    if (!bb) { console.warn('   ! هدف العلامة غير موجود:', String(sel).slice(0, 60), n); continue; }
    items.push({n, x: bb.x, y: bb.y, w: bb.width, h: bb.height, pos: o.pos || 'tl'});
  }
  await page.evaluate(items => {
    const sx = scrollX, sy = scrollY, R = 13;
    document.querySelectorAll('.opbadge').forEach(e => e.remove());
    for (const it of items) {
      const d = document.createElement('div'); d.className = 'opbadge'; d.textContent = it.n;
      let x = it.x - R, y = it.y - R;
      if (it.pos.includes('r') && it.pos !== 'l') x = it.x + it.w - R;
      if (it.pos.includes('b')) y = it.y + it.h - R;
      if (it.pos === 'r') { x = it.x + it.w - 6; y = it.y + it.h / 2 - R; }
      if (it.pos === 'l') { x = it.x - 2 * R + 6; y = it.y + it.h / 2 - R; }
      x = Math.max(3, x); y = Math.max(3, y);
      d.style.cssText = `position:absolute;left:${x + sx}px;top:${y + sy}px;width:${2 * R}px;height:${2 * R}px;border-radius:50%;background:#E8590C;color:#fff;font:700 16px/1 Tajawal,Arial,sans-serif;display:flex;align-items:center;justify-content:center;border:2px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.45);z-index:2147483000;pointer-events:none;direction:ltr`;
      document.body.appendChild(d);
    }
  }, items);
}
const unmark = page => page.evaluate(() => document.querySelectorAll('.opbadge').forEach(e => e.remove()));

// لقطة: target = 'page' (منطقة المحتوى الرئيسية بلا اللوحة الجانبية) | 'shell' (الشريط العلوي + المحتوى) | 'full' | محدِّد عنصر
async function shot(name, page, target, marks = [], wait = 600, maxH = 820) {
  if (only && !name.startsWith(only)) return;
  try {
    await page.waitForTimeout(wait);
    const file = join(OUT, `${name}.png`);
    const region = async sel => { const bb = await page.locator(sel).first().boundingBox(); return {x: bb.x, y: bb.y, width: bb.width, height: Math.min(bb.height, maxH)}; };
    if (marks.length) await mark(page, marks);
    if (target === 'page' || target === 'shell') {
      if (await page.evaluate(() => document.body.classList.contains('io'))) { await page.evaluate(() => document.body.classList.remove('io')); await page.waitForTimeout(250); if (marks.length) await mark(page, marks); }
      await page.screenshot({path: file, clip: await region(target === 'page' ? '#body .scr.on' : 'section.center')});
    } else if (target === 'view') await page.screenshot({path: file});
    else if (target === 'full') await page.screenshot({path: file, fullPage: true});
    else await page.locator(target).first().screenshot({path: file});
    await unmark(page);
    done.push(name); console.log('📸', name);
  } catch (e) { failed.push(name); console.error('✗', name, String(e.message).split('\n')[0]); await unmark(page).catch(() => {}); }
}
const step = async (fn, what) => { try { return await fn(); } catch (e) { console.error('✗ خطوة:', what, String(e.message).split('\n')[0]); } };

// ───────────────────────────── شاشة الدخول
{
  const c = await ctx({width: 1100, height: 760}); const page = await c.newPage();
  await page.goto(BASE + '/login');
  await page.waitForFunction(() => document.querySelectorAll('#t option').length > 0);
  await page.selectOption('#t', TENANT); await page.fill('#u', 'bayan-ceo'); await page.fill('#p', 'xxxxxxxxxxxx');
  await shot('o01-login', page, 'view', [['#t', 1], ['#u', 2], ['#p', 3], ['#b', 4]]);
  await c.close();
}

// ───────────────────────────── أشرطة الأدوار الجانبية (ما يراه كل دور)
for (const [user, nm] of [['admin', 'ceo'], ['sales', 'sales'], ['finance', 'finance'], ['engineer', 'engineer']]) {
  const c = await ctx({width: 1180, height: 1300}); const page = await c.newPage();
  await step(async () => { await login(page, user); await lightTheme(page); await shot(`o02-side-${nm}`, page, '.side'); }, 'side ' + user);
  await c.close();
}

// ───────────────────────────── المدير العام / الإدارة (admin)
{
  const c = await ctx(); const page = await c.newPage();
  await login(page, 'admin'); await lightTheme(page); await page.waitForSelector('#dq tr', {timeout: 15000}); await page.waitForTimeout(1200);
  await shot('o03-shell', page, 'shell', [['.side', 1, {pos: 'tr'}], ['#cmdBtn', 2], ['#theme', 3], ['#askBtn', 4], ['#cDec', 5, {pos: 'l'}], ['#kpis', 6], ['#dq', 7], ['#cycle', 8]]);
  // قرار
  await step(async () => { await page.click('#dq tr[data-i]:not(.done)'); await page.waitForTimeout(800); }, 'decision click');
  await shot('o04-decision', page, 'aside.insp .ib', [['aside.insp .ai', 1], ['aside.insp .btns .btn.p', 2], ['aside.insp .btns .btn:not(.p)', 3]]);
  await closeInsp(page);
  // لوحة الأوامر
  await step(async () => { await page.keyboard.press('Control+k'); await page.waitForTimeout(400); await page.fill('#pi', 'MSK-M-00'); await page.waitForTimeout(900); }, 'palette');
  await shot('o05-palette', page, '#pal > div', [['#pi', 1], ['#pl', 2]]);
  await page.keyboard.press('Escape');
  // المساعد
  await step(async () => { await page.click('#askBtn'); await page.fill('#ci', 'ما المشروع الأخطر؟'); await page.press('#ci', 'Enter'); await page.waitForTimeout(1800); }, 'assistant');
  await shot('o06-assistant', page, 'aside.insp .copilot', [['#ci', 1], ['#clog .a', 2]]);
  await closeInsp(page);

  // المخزون
  await go(page, 'inv'); await page.selectOption('#selProj', {label: PROJECT}); await page.waitForTimeout(1300);
  await shot('o10-inventory', page, 'page', [['#selProj', 1], ['#fStat', 2], ['#fAi', 3], ['button[data-call="EXT.plans"]', 4], ['#heat', 5], ['#segs', 6]]);
  // وحدة متاحة
  await step(async () => { const U = await sellable(page); await page.click(`#heat .cell[data-c="${U[0]}"]`); await page.waitForTimeout(1000); }, 'unit click');
  await shot('o11-unit-available', page, 'aside.insp .ib', [['aside.insp button[data-call="openBooking"]', 1], ['aside.insp button[data-call="EXT.newQuote"]', 2], ['aside.insp .ai', 3]]);
  // نافذة الحجز
  await step(async () => { await page.click('aside.insp button[data-call="openBooking"]'); await page.waitForSelector('#bn'); await page.fill('#bn', 'عميل تجريبي'); await page.fill('#bp', '+968 99000000'); await page.click('.plan[data-k="murabaha"]'); await page.fill('#bn', 'عميل تجريبي'); await page.fill('#bp', '+968 99000000'); }, 'booking modal');
  await shot('o12-booking-form', page, '#mbox', [['#bn', 1], ['#bp', 2], ['.plans', 3], ['#bgo', 4]]);
  await step(async () => { await page.click('#bgo'); await page.waitForTimeout(1500); }, 'booking submit');
  await shot('o13-booking-done', page, '#mbox', [['#mbox .inst', 1], ['#mbox button[data-call="closeModal"]', 2]]);
  await step(async () => { await page.click('#mbox button[data-call="closeModal"]'); await page.waitForTimeout(800); }, 'close booking');
  await shot('o14-confirm-deposit', page, 'aside.insp .ib', [['aside.insp button[data-call="confirmBooking"]', 1], ['aside.insp button[data-call="cancelBooking"]', 2], ['aside.insp .inst', 3]]);

  // عرض سعر
  await step(async () => { await closeInsp(page); const U2 = await sellable(page); await page.click(`#heat .cell[data-c="${U2[0]}"]`); await page.waitForTimeout(700); await page.click('aside.insp button[data-call="EXT.newQuote"]'); await page.waitForSelector('#qn'); await page.fill('#qn', 'شركة الواحة للاستشارات'); await page.fill('#qp', '+968 99000000'); await page.fill('#qe', 'customer@example.com'); await page.fill('#qd', '2'); }, 'quote modal');
  await shot('o15-quote-form', page, '#mbox', [['#qu', 1], ['#qn', 2], ['#qpl', 3], ['#qd', 4], ['#qgo', 5]]);
  await closeModal(page);

  // العملاء المحتملون
  await go(page, 'crm'); await page.waitForSelector('#leads tr'); await page.click('#leads tr'); await page.waitForTimeout(1000);
  await shot('o20b-lead', page, 'aside.insp .ib', [['aside.insp .seg', 1], ['aside.insp .ai', 2], ['aside.insp button[data-call="openBooking"]', 3]]);
  await shot('o20-crm', page, 'page', [['#pipe', 1], ['#leads', 2]]);

  // العقود والوسطاء
  await go(page, 'sal'); await sub(page, 'عروض الأسعار');
  await shot('o21-quotes', page, 'page', [['button[data-call="EXT.newQuote"]', 1, {pos: 'tr'}], ['#salB .docb', 2], ['button[data-call="EXT.quoteConvert"]', 3]]);
  await sub(page, 'التحقق والعقود');
  await step(async () => { const row = page.locator('#salB tr[data-i]', {hasText: 'عميل تجريبي'}); if (await row.count()) await row.first().click(); else await page.click('#salB tr[data-i]'); await page.waitForTimeout(1200); }, 'kyc row');
  await step(async () => { await page.fill('#kn', '12345678'); await page.fill('#ke', '2029-06-30'); await page.check('#kc'); }, 'kyc fill');
  await shot('o22-kyc', page, 'aside.insp .ib', [['#kt', 1], ['#kn', 2], ['#kf', 3], ['#kc', 4], ['#kgo', 5], ['aside.insp button[data-call="EXT.contract"]', 6]]);
  await step(async () => { await page.click('#kgo'); await page.waitForSelector('#kres .ai', {timeout: 8000}); await page.waitForTimeout(600); }, 'kyc run');
  await page.locator('#kres').scrollIntoViewIfNeeded().catch(() => {});
  await shot('o22b-kyc-result', page, 'aside.insp .ib', [['#kres .ai', 1], ['aside.insp button[data-call="EXT.contract"]', 2]]);
  await step(async () => { await page.click('aside.insp button[data-call="EXT.contract"]'); await page.waitForSelector('#mbox pre.contract'); await page.waitForTimeout(800); }, 'contract');
  await shot('o23-contract', page, '#mbox', [['#mbox pre.contract', 1], ['#sn', 2], ['#sa', 3], ['#sgo3', 4], ['#mbox .docb', 5]]);
  await closeModal(page);
  await sub(page, 'الوسطاء والعمولات');
  await step(async () => { await page.click('#salB tr[data-i]'); await page.waitForTimeout(900); }, 'broker row');
  await shot('o24b-broker', page, 'aside.insp .ib', [['aside.insp .ai', 1], ['aside.insp button[data-call="EXT.payCom"]', 2]]);
  await shot('o24-brokers', page, 'page', [['button[data-call="EXT.newBroker"]', 1, {pos: 'tr'}], ['#salB table', 2]]);
  await sub(page, 'السوق الثانوي'); await shot('o25-market', page, 'page', []);
  await sub(page, 'الخصومات'); await shot('o26-discounts', page, 'page', []);

  // التأجير
  await go(page, 'post'); await sub(page, 'التأجير'); await page.waitForTimeout(600);
  await step(async () => { await page.click('#postB tr[data-i]'); await page.waitForTimeout(900); }, 'lease row');
  await shot('o30b-lease', page, 'aside.insp .ib', [['aside.insp table', 1], ['aside.insp button[data-call="EXT.rent"]', 2]]);
  await shot('o30-leasing', page, 'page', [['#postB .kp', 1], ['button[data-call="EXT.newLease"]', 2, {pos: 'tr'}], ['#postB table', 3]]);
  await step(async () => { await closeInsp(page); await page.click('button[data-call="EXT.newLease"]'); await page.waitForSelector('#ln'); await page.fill('#ln', 'شركة تجريبية للمقاولات'); await page.fill('#lp', '+968 99000000'); await page.fill('#li', '12345678'); await page.fill('#ls', '2026-11-01'); await page.fill('#lr', '3600'); }, 'new lease');
  await shot('o31-new-lease', page, '#mbox', [['#lu', 1], ['#ln', 2], ['#ls', 3], ['#lr', 4], ['#lf', 5], ['#lgo', 6]]);
  await closeModal(page);

  // التسليم وملاحظات الفحص
  await sub(page, 'التسليم والعيوب');
  await step(async () => { await page.click('#postB tr[data-i]'); await page.waitForTimeout(900); }, 'handover row');
  await shot('o32b-handover', page, 'aside.insp .ib', [['aside.insp table', 1], ['aside.insp #hn', 2], ['aside.insp #hadd', 3], ['aside.insp #he', 4], ['aside.insp #hgo', 5]]);
  await shot('o32-handover', page, 'page', [['#postB table', 1]]);
  await sub(page, 'نقل الملكية'); await shot('o33-titles', page, 'page', []);
  await sub(page, 'إدارة المرافق'); await shot('o34-fm', page, 'page', []);
  await sub(page, 'اتحاد الملاك'); await shot('o35-oa', page, 'page', [['#oaP', 1], ['#oaBill', 2]]);

  // المخططات
  await go(page, 'inv'); await page.selectOption('#selProj', {label: PROJECT}); await page.waitForTimeout(1200);
  await step(async () => { await page.click('button[data-call="EXT.plans"]'); await page.waitForTimeout(1600); }, 'plans');
  await shot('o36-plans', page, 'aside.insp .ib', [['#plk', 1], ['#plfile', 2], ['#plgo', 3], ['button[data-call="EXT.planMark"]', 4]]);
  await step(async () => { await page.click('button[data-call="EXT.planMark"]'); await page.waitForSelector('#mku'); await page.waitForTimeout(1200); }, 'plan mark');
  await shot('o37-plan-mark', page, '#mbox', [['#mku', 1], ['.plan.edit', 2], ['#mksave', 3]]);
  await closeModal(page);

  // الإنشاء والمستخلصات
  await go(page, 'con'); await page.waitForSelector('#ipc tr'); await page.waitForTimeout(1500);
  await step(async () => { const r = page.locator('#ipc tr', {hasText: 'بانتظار الاعتماد'}); await (await r.count() ? r.first() : page.locator('#ipc tr').first()).click(); await page.waitForTimeout(900); }, 'ipc row');
  await shot('o40b-ipc', page, 'aside.insp .ib', [['aside.insp .ai', 1], ['aside.insp .items', 2], ['aside.insp button[data-call="approveIPC"]', 3]]);
  await shot('o40-ipc', page, 'page', [['#ipc', 1]]);
  await shot('o41-conx', page, 'page', [['#conP', 1], ['#conx .kp', 2], ['#conx .gantt', 3], ['button[data-call="EXT.newCO"]', 4, {pos: 'tr'}], ['button[data-call="EXT.newSite"]', 5, {pos: 'tr'}]], 600, 1250);
  await step(async () => { await closeInsp(page); await page.click('button[data-call="EXT.newCO"]'); await page.waitForSelector('#ct'); await page.fill('#ct', 'تعديل مواد تشطيب الواجهة'); await page.fill('#cc', '3500'); await page.fill('#cd', '5'); }, 'new CO');
  await shot('o42-new-co', page, '#mbox', [['#ct', 1], ['#cr', 2], ['#cc', 3], ['#cgo', 4]]);
  await closeModal(page);
  await step(async () => { await closeInsp(page); await page.click('button[data-call="EXT.newSite"]'); await page.waitForSelector('#sw'); await page.fill('#sw', '42'); await page.fill('#sd', 'صبّ سقف الطابق الثاني'); }, 'new site');
  await shot('o43-new-site', page, '#mbox', [['#sw', 1], ['#sh', 2], ['#sd', 3], ['#sgo2', 4]]);
  await closeModal(page);

  // خدمة العملاء
  await go(page, 'svc'); await page.waitForTimeout(800);
  await step(async () => { await page.click('#svcT tr[data-i]'); await page.waitForTimeout(900); }, 'svc row');
  await shot('o44b-service', page, 'aside.insp .ib', [['aside.insp #sn', 1], ['aside.insp button[data-call="svcSet"]', 2]]);
  await shot('o44-service', page, 'page', [['#svcT', 1], ['#rsT', 2]]);

  // السيولة والتعثر
  await go(page, 'fin'); await page.waitForTimeout(1500);
  await step(async () => { await page.click('#risk tr[data-i]'); await page.waitForTimeout(900); }, 'risk row');
  await shot('o50b-risk', page, 'aside.insp .ib', [['aside.insp .ai', 1], ['aside.insp button[data-call="showUnit"]', 2]]);
  await shot('o50-radar', page, 'page', [['[data-plan="0"]', 1], ['[data-plan="1"]', 2], ['#chart', 3], ['#cashNote', 4], ['#risk', 5]]);

  // الفواتير والضمان
  await go(page, 'bill'); await sub(page, 'الفواتير والضريبة');
  await shot('o51-invoices', page, 'page', [['#billB .kp', 1], ['#billB table', 2], ['#billB .docb', 3]]);
  await sub(page, 'تبرعات التأخير');
  await shot('o52-penalties', page, 'page', [['#billB .kp', 1], ['button[data-call="EXT.waive"]', 2]]);
  await sub(page, 'المطابقة البنكية');
  await step(async () => { await page.click('#bdemo'); await page.waitForTimeout(500); }, 'bank demo');
  await shot('o53-bank', page, 'page', [['#bt', 1], ['#bdemo', 2], ['#bgo2', 3]]);
  await step(async () => { await page.click('#bgo2'); await page.waitForTimeout(1800); }, 'bank run');
  await shot('o54-bank-result', page, 'page', [['#billB > .box:nth-child(2)', 1], ['#billB > .box:nth-child(3)', 2]], 600, 1250);
  await sub(page, 'حساب الضمان');
  await shot('o55-escrow', page, 'page', [['#escP', 1], ['#billB .kp', 2], ['#billB .ai', 3]]);
  await sub(page, 'التصدير المحاسبي'); await shot('o56-erp', page, 'page', []);

  // التسويق
  await go(page, 'mk');
  await shot('o60-mk-board', page, 'page', [['#mkB .kp', 1], ['.mkcard', 2], ['.mkcard details', 3], ['.mkcard button[data-call="EXT.mkNewCampaign"]', 4], ['.mkcard button[data-call="EXT.mkStudioFor"]', 5]]);
  await step(async () => { await page.click('.mkcard button[data-call="EXT.mkNewCampaign"]'); await page.waitForSelector('#cmN'); await page.fill('#cmN', 'حملة معاينة مساحات الخوض'); await page.fill('#cmB', '300'); }, 'campaign modal');
  await shot('o61-new-campaign', page, '#mbox', [['#cmP', 1], ['#cmN', 2], ['#cmO', 3], ['.cmCh', 4], ['#cmA', 5], ['#cmGo', 6]]);
  await closeModal(page);
  await sub(page, 'الحملات');
  await step(async () => { await page.click('button[data-call="EXT.mkOpen"]'); await page.waitForTimeout(1500); }, 'campaign open');
  await shot('o62-campaign', page, 'page', [['#mkDetail .kp', 1], ['#mkSendOut', 2], ['button[data-call="EXT.mkSend"]', 3]], 600, 1250);
  await sub(page, 'استوديو الإعلانات'); await shot('o63-ad-studio', page, 'page', [['#adP', 1], ['#adT', 2], ['#adS', 3], ['#adH', 4], ['#adGo', 5]]);
  await sub(page, 'التنبيهات التسويقية'); await shot('o64-mk-alerts', page, 'page', []);

  // التقارير
  await go(page, 'rep');
  await shot('o70-reports', page, 'page', [['.rcards', 1], ['.subt button:has-text("منشئ التقارير")', 2], ['.subt button:has-text("المحفوظة والمجدولة")', 3], ['.subt button:has-text("تقارير الممولين")', 4]]);
  await step(async () => { await page.click('.rcard:has-text("لوحة المحفظة")'); await page.waitForTimeout(2200); }, 'portfolio report');
  await shot('o71-report-open', page, 'page', [['#rpFrom', 1], ['#rpProj', 2], ['#rpRun', 3], ['button[data-call="EXT.repExport"][data-args*="csv"]', 4], ['button[data-call="EXT.repExport"][data-args*="pdf"]', 5], ['button[data-call="EXT.repSave"]', 6]]);
  await step(async () => { page.once('dialog', d => d.accept('لوحة المحفظة — أسبوعي')); await page.click('button[data-call="EXT.repSave"]'); await page.waitForTimeout(1200); }, 'save report');
  await go(page, 'rep'); await sub(page, 'منشئ التقارير');
  await shot('o72-report-builder', page, 'page', [['#rbDs', 1], ['.rbCol', 2], ['#rbAddF', 3], ['#rbG', 4], ['#rbAddA', 5], ['#rbRun', 6]]);
  await sub(page, 'المحفوظة والمجدولة');
  await step(async () => { await page.click('button[data-call="EXT.repSchedule"]'); await page.waitForSelector('#scC'); await page.fill('#scR', 'ceo@example.com'); }, 'schedule');
  await shot('o73-schedule', page, '#mbox', [['#scC', 1], ['#scH', 2], ['#scR', 3], ['#scF', 4], ['#scGo', 5]]);
  await closeModal(page);

  // الإدارة والأمان + السجل
  await go(page, 'adm');
  await shot('o80-users', page, 'page', [['#adm .subt', 1], ['#admB table', 2], ['button[data-call="EXT.newUser"]', 3, {pos: 'tr'}]]);
  await step(async () => { await page.click('button[data-call="EXT.newUser"]'); await page.waitForSelector('#un'); await page.fill('#un', 'bayan-sales2'); await page.fill('#unm', 'موظف مبيعات جديد'); }, 'new user');
  await shot('o81-new-user', page, '#mbox', [['#un', 1], ['#unm', 2], ['#ur', 3], ['#ugo', 4]]);
  await closeModal(page);
  await sub(page, 'أماني');
  await shot('o82-security', page, 'page', [['#t2', 1], ['#cpw', 2], ['#sall', 3]]);
  await sub(page, 'هوية المستندات والختم');
  await shot('o83-brand', page, 'page', [['#brn', 1], ['#brsave', 2], ['button[data-call="EXT.brandUpload"]', 3]]);
  await sub(page, 'السجل والنسخ والتكامل');
  await shot('o84-ops', page, 'page', [['#admB .kp', 1], ['#bk1', 2], ['#ak1', 3]]);
  await sub(page, 'الإشعارات'); await shot('o85-notif', page, 'page', [['#nrun', 1]]);
  await go(page, 'log'); await shot('o86-audit', page, 'page', [['#audit', 1]]);
  await c.close();
}

// ───────────────────────────── المهندس (engineer): تراخيص
{
  const c = await ctx(); const page = await c.newPage();
  await login(page, 'engineer'); await lightTheme(page);
  await step(async () => { await go(page, 'pre'); await page.waitForTimeout(800); await page.click('#preB tr[data-i]'); await page.waitForTimeout(900); }, 'permits');
  await shot('o45b-permit', page, 'aside.insp .ib', [['aside.insp #ps', 1], ['aside.insp #pr', 2], ['aside.insp #pgo', 3]]);
  await shot('o45-permits', page, 'page', [['#preB table', 1]]);
  await c.close();
}

// ───────────────────────────── تطبيق العميل (client1) — هاتف
{
  const c = await ctx({width: 430, height: 900}, 3); const page = await c.newPage();
  await login(page, 'client1'); await page.waitForSelector('nav button[data-t="pay"]', {timeout: 20000}); await page.waitForTimeout(1500);
  await shot('o90-client-home', page, 'full', []);
  await page.click('nav button[data-t="pay"]'); await page.waitForTimeout(600);
  await shot('o91-client-pay', page, 'full', []);
  await step(async () => { await page.click('button[data-call="payNow"]'); await page.waitForSelector('#pz'); await page.waitForTimeout(500); }, 'pay sheet');
  await shot('o92-client-pay-sheet', page, 'view', [['#pz', 1], ['#sh [data-call="unsheet"]', 2]]);
  await step(async () => { await page.click('#sh [data-call="unsheet"]'); await page.waitForTimeout(400); }, 'close sheet');
  await page.click('nav button[data-t="svc"]'); await page.waitForTimeout(500);
  await step(async () => { await page.selectOption('#sc', {label: 'سباكة'}); await page.fill('#sd', 'تسريب ماء تحت مغسلة المطبخ'); }, 'svc form');
  await shot('o93-client-service', page, 'full', [['#sc', 1], ['#sd', 2], ['#sgo', 3]]);
  await page.click('nav button[data-t="sell"]'); await page.waitForTimeout(500);
  await shot('o94-client-sell', page, 'full', []);
  await page.click('nav button[data-t="more"]'); await page.waitForTimeout(700);
  await shot('o95-client-more', page, 'full', [['button[data-call="openContract"]', 1], ['#pex', 2], ['#cpw', 3]]);
  await c.close();
  // عقد غير موقَّع: نبحث بين العملاء عمّن بقي عقده بانتظار توقيعه
  for (const u of ['client2', 'client3', 'client4', 'client5', 'client1']) {
    const c2 = await ctx({width: 430, height: 900}, 3); const p2 = await c2.newPage();
    try {
      await login(p2, u); await p2.waitForSelector('nav button[data-t="more"]', {timeout: 20000}); await p2.click('nav button[data-t="more"]'); await p2.waitForTimeout(700);
      const b = p2.locator('button[data-call="openContract"]', {hasText: 'قراءة العقد وتوقيعه'});
      if (await b.count()) { await b.first().click(); await p2.waitForSelector('#tgo', {timeout: 8000}); await p2.waitForTimeout(500); await shot('o96-client-contract', p2, 'view', [['#tn', 1], ['#tp', 2], ['#ta', 3], ['#tgo', 4]]); await c2.close(); break; }
    } catch (e) { console.error('✗ عقد العميل', u, String(e.message).split('\n')[0]); }
    await c2.close();
  }

}

// ───────────────────────────── الوسيط (broker1)
{
  const c = await ctx({width: 520, height: 900}, 2); const page = await c.newPage();
  await login(page, 'broker1'); await page.waitForTimeout(1500);
  await shot('o97-broker', page, 'full', [['#n', 1], ['#p', 2], ['#pr', 3], ['#go', 4]]);
  await c.close();
}

await browser.close();
console.log(`تم: ${done.length} لقطة · فشل: ${failed.length}${failed.length ? ' → ' + failed.join(', ') : ''} · ${OUT}`);
