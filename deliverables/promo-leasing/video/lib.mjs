// أدوات تسجيل لقطات المنصة الحقيقية (CDP screencast) لفيديو قسم الإيجارات — المطوّر «بيان عمان».
// الجلسة تُحقن من رمز يُنشأ محليًا (MABANIQ_LEA_TOKEN) فلا كلمة مرور في أي ملف ولا تُطبع.
import {chromium} from '@playwright/test';
import {mkdirSync, writeFileSync, rmSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

export const HERE = dirname(fileURLToPath(import.meta.url));
export const BASE = process.env.MABANIQ_BASE || 'http://127.0.0.1:8810';
const TOKEN = process.env.MABANIQ_LEA_TOKEN;
if (!TOKEN) { console.error('MABANIQ_LEA_TOKEN غير معيَّن'); process.exit(2); }

export async function launch() { return chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'}); }
export async function newCtx(browser, size = {width: 1600, height: 900}, scale = 1.2) {
  const c = await browser.newContext({viewport: size, deviceScaleFactor: scale, locale: 'ar-OM', timezoneId: 'Asia/Muscat', colorScheme: 'light'});
  await c.addCookies([{name: 'mbq_session', value: TOKEN, url: BASE}, {name: 'mbq_tenant', value: 'bayan', url: BASE}, {name: 'mbq_csrf', value: 'csrf-lea-video-' + 'x'.repeat(24), url: BASE}]);
  return c;
}
export async function open(page) {
  await page.goto(BASE + '/');
  await page.waitForSelector('[data-s="lea"]', {timeout: 30000});
  await page.waitForTimeout(1500);
}
export async function light(page) {
  const isLight = await page.evaluate(() => document.body.classList.contains('light'));
  if (!isLight) { await page.click('#theme'); await page.waitForTimeout(400); }
  // التطبيق لا يلوّن جذر الصفحة في الوضع الفاتح فيظهر شريط داكن أسفل الصفحة عند التمرير: نوحّده مع لون الجسم
  await page.evaluate(() => { document.documentElement.style.background = getComputedStyle(document.body).backgroundColor; });
}
export async function cursor(page) {
  await page.evaluate(() => {
    if (document.getElementById('__cur')) return;
    const d = document.createElement('div'); d.id = '__cur';
    d.style.cssText = 'position:fixed;z-index:2147483647;width:22px;height:22px;border-radius:50%;background:rgba(26,111,90,.85);border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.4);pointer-events:none;left:-50px;top:-50px;transform:translate(-50%,-50%);transition:transform .08s';
    document.documentElement.appendChild(d);
    addEventListener('mousemove', e => { d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', () => d.style.transform = 'translate(-50%,-50%) scale(.7)', true);
    addEventListener('mouseup', () => d.style.transform = 'translate(-50%,-50%) scale(1)', true);
  });
}
export async function glide(page, x, y, steps = 28) { await page.mouse.move(x, y, {steps}); }
export async function clickEl(page, sel, opts = {}) {
  const el = typeof sel === 'string' ? page.locator(sel).first() : sel;
  await el.scrollIntoViewIfNeeded();
  const b = await el.boundingBox();
  await glide(page, b.x + b.width / 2, b.y + b.height / 2);
  await page.waitForTimeout(opts.pre ?? 250);
  await page.mouse.click(b.x + b.width / 2, b.y + b.height / 2);
  await page.waitForTimeout(opts.post ?? 900);
}
export async function go(page, s) { await clickEl(page, `[data-s="${s}"]`, {post: 1200}); }
export async function sub(page, label) { await clickEl(page, `.subt button:has-text("${label}")`, {post: 1200}); }
export async function closeModal(page) {
  await page.keyboard.press('Escape'); await page.waitForTimeout(300);
  if (await page.isVisible('#scrim')) await page.evaluate(() => { document.querySelector('#scrim')?.classList.remove('on'); document.querySelectorAll('.modal.on,.sheet.on,#modal.on').forEach(m => m.classList.remove('on')); });
}
export async function scroll(page, dy, steps = 12, gap = 90) { for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, dy / steps); await page.waitForTimeout(gap); } }
export async function typeSlow(page, sel, text) { await clickEl(page, sel, {post: 250}); await page.keyboard.type(text, {delay: 60}); await page.waitForTimeout(400); }

// تسجيل: يحفظ الإطارات بمددها الحقيقية ويكتب ffconcat
export async function record(page, name, fn) {
  const dir = join(HERE, 'rec', name);
  rmSync(dir, {recursive: true, force: true}); mkdirSync(dir, {recursive: true});
  const cdp = await page.context().newCDPSession(page);
  const frames = [];
  cdp.on('Page.screencastFrame', async ev => {
    const i = frames.length; const f = `f${String(i).padStart(5, '0')}.jpg`;
    writeFileSync(join(dir, f), Buffer.from(ev.data, 'base64'));
    frames.push({f, t: ev.metadata.timestamp});
    cdp.send('Page.screencastFrameAck', {sessionId: ev.sessionId}).catch(() => {});
  });
  const wall0 = Date.now();
  await cdp.send('Page.startScreencast', {format: 'jpeg', quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1});
  await page.waitForTimeout(500);
  await fn();
  await page.waitForTimeout(600);
  const wall = (Date.now() - wall0) / 1000;
  await cdp.send('Page.stopScreencast');
  await page.waitForTimeout(300);
  const tail = Math.max(0.5, wall - (frames.at(-1).t - frames[0].t) - 0.3);
  let txt = 'ffconcat version 1.0\n';
  for (let i = 0; i < frames.length; i++) {
    const d = i + 1 < frames.length ? Math.max(0.01, frames[i + 1].t - frames[i].t) : tail;
    txt += `file '${frames[i].f}'\nduration ${d.toFixed(4)}\n`;
  }
  txt += `file '${frames[frames.length - 1].f}'\n`;
  writeFileSync(join(dir, 'list.ffconcat'), txt);
  console.log('🎬', name, frames.length, 'إطارًا', (frames.at(-1).t - frames[0].t + tail).toFixed(1), 'ث');
}
