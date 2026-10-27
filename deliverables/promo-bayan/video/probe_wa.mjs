// تجربة ردود محاكي وكيل واتساب على رسائل بالعامية العُمانية (لاختيار الرسالة الأنسب للفيديو) — لا تسجيل.
import {launch, newCtx, login, go, sub, clickEl} from './lib.mjs';
const browser = await launch();
const c = await newCtx(browser); const page = await c.newPage();
await login(page, 'admin');
await go(page, 'sal'); await sub(page, 'وكيل واتساب');
const msgs = [
  'السلام عليكم، ابغى مكتب في مساحات الخوض، كم بقي متاح وكم السعر؟',
  'مرحبا، كم بقي من المكاتب في مساحات الخوض؟ ابغى مكتب مساحته قريبة من 60 متر',
  'هلا، عندكم مكتب فاضي في الخوض؟ ميزانيتي 45000',
];
for (const m of msgs) {
  await page.fill('#wt', m); await page.click('#wgo'); await page.waitForTimeout(1500);
  const last = await page.locator('#wlog .wo').last().innerText();
  console.log('➤', m, '\n⟵', last.replace(/\n/g, ' | '), '\n');
}
await browser.close();
