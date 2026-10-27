// تسجيل مشاهد المنصة الحقيقية للفيديو (المطوّر «بيان عمان»، نسخة محلية 0.15.0). الاستعمال:
//   MABANIQ_DEMO_PASSWORD=<سر> node record_all.mjs [r2 r3 …]   (بلا وسائط = الكل)
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {launch, newCtx, login, light, cursor, glide, clickEl, go, sub, closeModal, record, HERE, BASE, TENANT} from './lib.mjs';

const state = JSON.parse(readFileSync(join(HERE, 'demo-state.video.json'), 'utf8'));
const want = new Set(process.argv.slice(2));
const on = k => !want.size || want.has(k);
const browser = await launch();

async function scroll(page, dy, steps = 12, gap = 90) { for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, dy / steps); await page.waitForTimeout(gap); } }
async function typeSlow(page, sel, text) { await clickEl(page, sel, {post: 300}); await page.keyboard.type(text, {delay: 55}); await page.waitForTimeout(500); }
async function desktop(user = 'admin') {
  const c = await newCtx(browser); const page = await c.newPage();
  await login(page, user); await light(page); await cursor(page);
  return {c, page};
}

// R2 — وكيل واتساب + العملاء المحتملون
if (on('r2')) {
  const {c, page} = await desktop();
  await go(page, 'sal'); await sub(page, 'وكيل واتساب');
  await record(page, 'r2', async () => {
    await page.waitForTimeout(800);
    await typeSlow(page, '#wt', 'السلام عليكم، كم بقي مكتب متاح؟ ميزانيتي 45 الف');
    await clickEl(page, '#wgo', {post: 3200});
    await typeSlow(page, '#wt', 'ممتاز، ابغى اشوف مكتب بكرة');
    await clickEl(page, '#wgo', {post: 3200});
    await go(page, 'crm'); await page.waitForTimeout(3500);
  });
  await c.close();
}

// R3 — المخزون ⟵ بطاقة الوحدة ⟵ عروض الأسعار
if (on('r3')) {
  const {c, page} = await desktop();
  await go(page, 'inv');
  await page.selectOption('#selProj', {label: 'مساحات الخوض'}); await page.waitForTimeout(1500);
  await record(page, 'r3', async () => {
    await page.waitForTimeout(1500);
    const cell = await page.$(`.cell[data-c="${state.quote.unit_code || 'MSK-M-205'}"]`) || await page.$('.cell[data-c^="MSK-M-0"]');
    if (cell) { await clickEl(page, cell, {post: 3500}); }
    await scroll(page, 500, 10); await page.waitForTimeout(1800);
    await closeModal(page);
    await go(page, 'sal'); await sub(page, 'عروض الأسعار'); await page.waitForTimeout(3500);
  });
  await c.close();
}

// R4 — المخططات ومواقع الوحدات + هوية المستندات
if (on('r4')) {
  const {c, page} = await desktop();
  await go(page, 'inv');
  await page.selectOption('#selProj', {label: 'مساحات الخوض'}); await page.waitForTimeout(1200);
  await record(page, 'r4', async () => {
    await clickEl(page, 'button[data-call="EXT.plans"]', {post: 2200});
    const plans = await page.$$('.plan');
    const gf = (await Promise.all(plans.map(async p => ((await p.$$('.mk')).length >= 10 ? p : null)))).find(Boolean);
    if (gf) { await gf.scrollIntoViewIfNeeded(); }
    await page.waitForTimeout(3500);
    await scroll(page, 450, 10); await page.waitForTimeout(2500);
    await closeModal(page);
    await go(page, 'adm'); await sub(page, 'هوية المستندات والختم'); await page.waitForTimeout(3500);
  });
  await c.close();
}

// R5 — أداء الشرائح ⟵ تسويق المشاريع ⟵ الحملات ⟵ استوديو الإعلانات
if (on('r5')) {
  const {c, page} = await desktop();
  await go(page, 'inv');
  await page.selectOption('#selProj', {label: 'آلاء بيزنس أفنيو'}); await page.waitForTimeout(1500);
  await record(page, 'r5', async () => {
    await page.waitForTimeout(1200);
    await scroll(page, 900, 16); await page.waitForTimeout(2200);
    await go(page, 'mk'); await page.waitForTimeout(3000); await scroll(page, 350, 8);
    await sub(page, 'الحملات'); await page.waitForTimeout(2800);
    await sub(page, 'استوديو الإعلانات'); await page.waitForTimeout(3500);
  });
  await c.close();
}

// R6 — التأجير
if (on('r6')) {
  const {c, page} = await desktop();
  await go(page, 'post');
  await record(page, 'r6', async () => {
    await sub(page, 'التأجير'); await page.waitForTimeout(3500);
    await scroll(page, 600, 12); await page.waitForTimeout(3000);
  });
  await c.close();
}

// R7 — الإنشاء والمستخلصات ⟵ السيولة ⟵ تبرعات التأخير
if (on('r7')) {
  const {c, page} = await desktop();
  await record(page, 'r7', async () => {
    await go(page, 'con'); await page.waitForTimeout(3500);
    await go(page, 'fin'); await page.waitForTimeout(3500);
    await go(page, 'bill'); await sub(page, 'تبرعات التأخير'); await page.waitForTimeout(3500);
  });
  await c.close();
}

// R8 — لوحة القيادة ⟵ تقرير المحفظة
if (on('r8')) {
  const {c, page} = await desktop();
  await record(page, 'r8', async () => {
    await go(page, 'ov'); await page.waitForTimeout(3500); await scroll(page, 500, 10); await page.waitForTimeout(2000);
    await go(page, 'rep');
    await clickEl(page, '.rcard:has-text("لوحة المحفظة")', {post: 3500});
    await scroll(page, 500, 10); await page.waitForTimeout(2500);
  });
  await c.close();
}

// R9 — سجل التدقيق + صفحة التحقق العامة
if (on('r9')) {
  const {c, page} = await desktop();
  await record(page, 'r9', async () => {
    await go(page, 'log'); await page.waitForTimeout(3500);
    await page.goto(`${BASE}/verify/${TENANT}/${state.quote.verify_code}`); await page.waitForTimeout(3500);
  });
  await c.close();
}

// R10 — تطبيق العميل (هاتف)
if (on('r10')) {
  const c = await newCtx(browser, {width: 430, height: 900}, 2); const page = await c.newPage();
  await login(page, 'client1'); await page.waitForSelector('nav button[data-t="pay"]', {timeout: 20000}); await cursor(page);
  await record(page, 'r10', async () => {
    await page.waitForTimeout(3000);
    await clickEl(page, 'nav button[data-t="pay"]', {post: 3000});
    await clickEl(page, 'nav button[data-t="more"]', {post: 3000});
  });
  await c.close();
}
await browser.close();
