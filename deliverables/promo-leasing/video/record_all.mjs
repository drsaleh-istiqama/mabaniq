// تسجيل مشاهد قسم الإيجارات الحقيقية (المطوّر «بيان عمان»، نسخة محلية من بياناته التجريبية). الاستعمال:
//   MABANIQ_LEA_TOKEN=<رمز جلسة محلي> node record_all.mjs [r2 r3 …]   (بلا وسائط = الكل)
import {launch, newCtx, open, light, cursor, clickEl, go, sub, closeModal, record, scroll, typeSlow} from './lib.mjs';

const want = new Set(process.argv.slice(2));
const on = k => !want.size || want.has(k);
const browser = await launch();

async function desk() {
  const c = await newCtx(browser); const page = await c.newPage();
  await open(page); await light(page); await cursor(page);
  return {c, page};
}

// R2 — نظرة عامة على المحفظة
if (on('r2')) {
  const {c, page} = await desk();
  await go(page, 'lea');
  await record(page, 'r2', async () => {
    await page.waitForTimeout(2200);
    await clickEl(page, 'button:has-text("تشغيل التذكيرات")', {post: 2600});
    await scroll(page, 300, 14, 110); await page.waitForTimeout(1800);
    await scroll(page, -300, 14, 110); await page.waitForTimeout(1500);
  });
  await c.close();
}

// R3 — عقد جديد: وحدة شاغرة + مستأجر مسجَّل + معاينة جدول الدفعات
if (on('r3')) {
  const {c, page} = await desk();
  await go(page, 'lea'); await sub(page, 'العقود');
  await record(page, 'r3', async () => {
    await page.waitForTimeout(1800);
    await clickEl(page, 'button:has-text("+ عقد جديد")', {post: 1800});
    const vacant = await page.evaluate(() => { const s = document.querySelector('#nu'); const o = [...s.options].find(x => x.textContent.includes('شاغرة')); return o ? o.value : null; });
    if (vacant) await page.selectOption('#nu', vacant);
    await page.waitForTimeout(700);
    await page.selectOption('#nt', {index: 1}); await page.waitForTimeout(900);
    const d = new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10);
    await page.fill('#ns', d); await page.waitForTimeout(500);
    await typeSlow(page, '#nr', '4800');
    await page.fill('#ne', '5'); await page.waitForTimeout(500);
    await page.selectOption('#nf', '4'); await page.waitForTimeout(500);
    await page.fill('#np', '15'); await page.waitForTimeout(500);
    await page.fill('#nd', '600'); await page.waitForTimeout(500);
    await clickEl(page, '#npre', {post: 2600});
    await page.evaluate(() => { const m = document.querySelector('#mbox'); if (m) m.scrollTo({top: 9999, behavior: 'smooth'}); });
    await page.waitForTimeout(2600);
  });
  await closeModal(page);
  await c.close();
}

// R4 — ملف العقد (الجدول والتحصيل) ثم محضر التسليم
if (on('r4')) {
  const {c, page} = await desk();
  await go(page, 'lea'); await sub(page, 'العقود');
  await record(page, 'r4', async () => {
    await page.waitForTimeout(1500);
    const row = page.locator('#leaB tr[data-id]', {hasText: 'ساري'}).first();
    await clickEl(page, row, {post: 2600});
    await scroll(page, 500, 10); await page.waitForTimeout(1800);
    const hb = page.locator('button:has-text("محضر تسليم")').first();
    if (await hb.count()) {
      await clickEl(page, hb, {post: 2600});
      await page.evaluate(() => { const m = document.querySelector('#mbox'); if (m) m.scrollTo({top: 400, behavior: 'smooth'}); });
      await page.waitForTimeout(2200);
    } else { await page.waitForTimeout(2000); }
  });
  await closeModal(page);
  await c.close();
}

// R5 — دورة الشيك: حفظ ← إيداع ← صرف
if (on('r5')) {
  const {c, page} = await desk();
  await go(page, 'lea'); await sub(page, 'الشيكات');
  await record(page, 'r5', async () => {
    await page.waitForTimeout(2600);
    const dep = page.locator('#leaB button:has-text("إيداع")').first();
    if (await dep.count()) { await clickEl(page, dep, {post: 2600}); }
    const clr = page.locator('#leaB button:has-text("صرف")').first();
    if (await clr.count()) { await clickEl(page, clr, {post: 2800}); }
    await scroll(page, 120, 6); await page.waitForTimeout(1800);
  });
  await c.close();
}

// R6 — دفتر التحصيل والإيصالات
if (on('r6')) {
  const {c, page} = await desk();
  await go(page, 'lea'); await sub(page, 'التحصيل');
  await record(page, 'r6', async () => {
    await page.waitForTimeout(2800);
    await scroll(page, 520, 12); await page.waitForTimeout(2400);
    await scroll(page, 400, 10); await page.waitForTimeout(1600);
  });
  await c.close();
}

// R7 — المتأخرات: ملف العقد المتأخر ثم الإنذارات وخطط السداد وتبرعات التأخير
if (on('r7')) {
  const {c, page} = await desk();
  await go(page, 'lea'); await sub(page, 'المتأخرات والتبرع');
  await record(page, 'r7', async () => {
    await page.waitForTimeout(1600);
    const row = page.locator('#leaB tr[data-id]').nth(1);
    await clickEl(page, row, {post: 2800});
    await scroll(page, 380, 10); await page.waitForTimeout(1800);
    await scroll(page, -380, 8); await page.waitForTimeout(800);
    await scroll(page, 260, 10, 110); await page.waitForTimeout(2200);
  });
  await c.close();
}

// R8 — الصيانة: تسجيل طلب ثم أمر عمل بمورّد وتحميل
if (on('r8')) {
  const {c, page} = await desk();
  await go(page, 'lea'); await sub(page, 'الصيانة والمصاريف');
  await record(page, 'r8', async () => {
    await page.waitForTimeout(1800);
    await clickEl(page, 'button:has-text("+ طلب صيانة")', {post: 1600});
    await page.selectOption('#mu', {index: 2}); await page.waitForTimeout(500);
    await typeSlow(page, '#mc', 'تكييف');
    await typeSlow(page, '#md', 'المكيّف لا يبرّد في المحل');
    await page.selectOption('#mp', 'urgent'); await page.waitForTimeout(500);
    await page.selectOption('#ms', 'tenant'); await page.waitForTimeout(500);
    await clickEl(page, '#mgo', {post: 2200});
    await clickEl(page, '#leaB button:has-text("أمر عمل")', {post: 1800});
    await page.selectOption('#mbox #ov', {index: 1}); await page.waitForTimeout(500);
    await page.fill('#mbox #oc', '45'); await page.waitForTimeout(500);
    await page.selectOption('#mbox #ot', 'owner'); await page.waitForTimeout(1800);
  });
  await closeModal(page);
  await c.close();
}

// R9 — الملاك والكشف الشهري
if (on('r9')) {
  const {c, page} = await desk();
  await go(page, 'lea'); await sub(page, 'الملاك والكشوف');
  await record(page, 'r9', async () => {
    await page.waitForTimeout(2200);
    const btn = page.locator('#leaB button:has-text("كشف شهري")').nth(1);
    await clickEl(page, (await btn.count()) ? btn : page.locator('#leaB button:has-text("كشف شهري")').first(), {post: 3200});
    await page.evaluate(() => { const m = document.querySelector('#mbox'); if (m) m.scrollTo({top: 500, behavior: 'smooth'}); });
    await page.waitForTimeout(2600);
  });
  await closeModal(page);
  await c.close();
}

// R10 — المحاسبة: الترحيل التلقائي والقيود
if (on('r10')) {
  const {c, page} = await desk();
  await go(page, 'acc');
  await record(page, 'r10', async () => {
    await page.waitForTimeout(3000);
    await sub(page, 'القيود'); await page.waitForTimeout(3200);
    await scroll(page, 420, 10); await page.waitForTimeout(1800);
  });
  await c.close();
}
await browser.close();
