// تسجيل مشاهد المنصة الحقيقية لفيديو «مبانيك لرؤية العقارية» — المطوّر «رؤية العقارية» على نسخة محلية معزولة بتمثيل توضيحي (sim_prepare.py).
//   MABANIQ_DEMO_PASSWORD=<سر> node record_all.mjs [r2 r3 …]   (بلا وسائط = الكل)
import {join} from 'node:path';
import {launch, newCtx, login, light, cursor, clickEl, go, sub, closeModal, closeInsp, openProject, record, HERE} from './lib.mjs';

const want = new Set(process.argv.slice(2));
const on = k => !want.size || want.has(k);
const browser = await launch();

async function scroll(page, dy, steps = 12, gap = 90) { for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, dy / steps); await page.waitForTimeout(gap); } }
async function typeSlow(page, sel, text, delay = 55) { await clickEl(page, sel, {post: 300}); await page.keyboard.type(text, {delay}); await page.waitForTimeout(500); }
async function desktop(user = 'admin') {
  const c = await newCtx(browser); const page = await c.newPage();
  await login(page, user); await light(page); await cursor(page);
  return {c, page};
}
async function nav(page, s) { await closeModal(page); await closeInsp(page); await go(page, s); }

// R2 — لوحة القيادة (المشاريع الستة + قرارات تُحسب من بيانات التمثيل) ثم المساعد
if (on('r2')) {
  const {c, page} = await desktop();
  await record(page, 'r2', async () => {
    await page.waitForTimeout(2500);
    await scroll(page, 520, 12); await page.waitForTimeout(2500);
    await clickEl(page, '#askBtn', {post: 900});
    await typeSlow(page, '#ci', 'كم وحدة متاحة في فيوو هايتس؟');
    await page.keyboard.press('Enter'); await page.waitForTimeout(3800);
  });
  await c.close();
}

// R3 — المخزون ⟵ شقة متاحة ⟵ حجز لعميل بخطة مرابحة ⟵ جدول الأقساط
if (on('r3')) {
  const {c, page} = await desktop();
  await go(page, 'inv'); await openProject(page, 'صلالة هيلز');
  await record(page, 'r3', async () => {
    await page.waitForTimeout(2200);
    await clickEl(page, '.cell[data-c="SLH-A-24"]', {post: 3000});
    await clickEl(page, 'button:has-text("حجز الوحدة لعميل")', {post: 1200});
    await typeSlow(page, '#bn', 'نورة بنت حمد الرواحي', 60);
    await typeSlow(page, '#bp', '+968 9123 4567', 60);
    await clickEl(page, '.plan[data-k="murabaha"]', {post: 1400});
    await clickEl(page, '#bgo', {post: 3800});
    await scroll(page, 280, 8); await page.waitForTimeout(1500);
  });
  await c.close();
}

// R4 — العقود: الحجوزات بانتظار التحقق ثم عروض الأسعار
if (on('r4')) {
  const {c, page} = await desktop();
  await record(page, 'r4', async () => {
    await clickEl(page, '[data-s="sal"]', {post: 1800}); await page.waitForTimeout(3000);
    await sub(page, 'عروض الأسعار'); await page.waitForTimeout(3500);
  });
  await c.close();
}

// R5 — وحدة مباعة: المشتري والخطة والأقساط
if (on('r5')) {
  const {c, page} = await desktop();
  await go(page, 'inv'); await openProject(page, 'فيوو هايتس');
  await record(page, 'r5', async () => {
    await page.waitForTimeout(2000);
    await clickEl(page, '.cell[data-c="VHT-O-10"]', {post: 3800});
    const insp = page.locator('aside.insp').first();
    await insp.evaluate(el => el.scrollBy({top: 380, behavior: 'smooth'})); await page.waitForTimeout(2500);
    await insp.evaluate(el => el.scrollBy({top: 380, behavior: 'smooth'})); await page.waitForTimeout(2500);
  });
  await c.close();
}

// R6 — الإنشاء والمستخلصات: ادّعاء 55٪ مقابل متحقَّق 40٪ ثم اعتماد مستخلص مطابق
if (on('r6')) {
  const {c, page} = await desktop();
  await go(page, 'con');
  await record(page, 'r6', async () => {
    await page.waitForTimeout(2500);
    await clickEl(page, page.locator('tr', {hasText: 'الهيكل الخرساني'}).first(), {post: 4500});
    await closeInsp(page);
    await clickEl(page, page.locator('tr', {hasText: 'التشطيبات الداخلية'}).first(), {post: 3800});
    await clickEl(page, 'button:has-text("اعتماد المستخلص")', {post: 3500});
  });
  await c.close();
}

// R7 — السيولة ⟵ حساب الضمان ⟵ تبرعات التأخير
if (on('r7')) {
  const {c, page} = await desktop();
  await record(page, 'r7', async () => {
    await clickEl(page, '[data-s="fin"]', {post: 1800}); await page.waitForTimeout(3800);
    await scroll(page, 400, 8); await page.waitForTimeout(1500);
    await clickEl(page, '[data-s="bill"]', {post: 1500}); await sub(page, 'حساب الضمان'); await page.waitForTimeout(3300);
    await sub(page, 'تبرعات التأخير'); await page.waitForTimeout(3300);
  });
  await c.close();
}

// R8 — تسويق المشاريع ⟵ استوديو الإعلانات: إعلان بتصور صلالة هيلز
if (on('r8')) {
  const {c, page} = await desktop();
  await go(page, 'mk');
  await record(page, 'r8', async () => {
    await page.waitForTimeout(2800);
    await sub(page, 'استوديو الإعلانات'); await page.waitForTimeout(1200);
    await page.selectOption('#adP', {label: 'صلالة هيلز'}); await page.waitForTimeout(700);
    await page.selectOption('#adT', {label: 'إطلاق المبيعات'}); await page.waitForTimeout(700);
    await page.selectOption('#adC', {label: 'رملي فاتح'}); await page.waitForTimeout(700);
    await page.selectOption('#adPl', {label: 'مرابحة بنكية'}); await page.waitForTimeout(500);
    await page.setInputFiles('#adBg', join(HERE, '..', '..', '..', 'backend', 'assets', 'samples', 'view', 'salalah-hills-render.jpg')); await page.waitForTimeout(1200);
    await clickEl(page, '#adGo', {post: 6000});
  });
  await c.close();
}

// R9 — التقارير (لوحة المحفظة) ⟵ سجل التدقيق
if (on('r9')) {
  const {c, page} = await desktop();
  await record(page, 'r9', async () => {
    await clickEl(page, '[data-s="rep"]', {post: 1500});
    await clickEl(page, '.rcard:has-text("لوحة المحفظة")', {post: 3800}); await scroll(page, 520, 10); await page.waitForTimeout(2200);
    await clickEl(page, '[data-s="log"]', {post: 1500}); await page.waitForTimeout(3300);
  });
  await c.close();
}
await browser.close();
