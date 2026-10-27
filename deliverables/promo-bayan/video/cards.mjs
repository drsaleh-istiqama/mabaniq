// بطاقات الفيديو وطبقاته (HTML عربي RTL مركَّب برمجيًا ⟵ PNG بـPlaywright). لا نص عربي بنموذج صور.
//   node cards.mjs            (يقرأ script.json ويكتب cards/*.png و cards/sub_*.png)
import {chromium} from '@playwright/test';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..', '..', '..');
const OUT = join(HERE, 'cards'); mkdirSync(OUT, {recursive: true});
const S = JSON.parse(readFileSync(join(HERE, 'script.json'), 'utf8'));
const F = f => pathToFileURL(join(ROOT, 'web', 'fonts', f)).href;
const BAYAN = pathToFileURL(join(ROOT, 'backend', 'assets', 'samples', 'bayan', 'bayan-logo.png')).href;
const MBQ = pathToFileURL(join(ROOT, 'web', 'img', 'logo-ar.png')).href;

const css = `
@font-face{font-family:T;font-weight:400;src:url(${F('tajawal-arabic-400-normal.woff2')})}
@font-face{font-family:T;font-weight:500;src:url(${F('tajawal-arabic-500-normal.woff2')})}
@font-face{font-family:T;font-weight:700;src:url(${F('tajawal-arabic-700-normal.woff2')})}
@font-face{font-family:T;font-weight:400;src:url(${F('tajawal-latin-400-normal.woff2')});unicode-range:U+0000-00FF}
@font-face{font-family:T;font-weight:700;src:url(${F('tajawal-latin-700-normal.woff2')});unicode-range:U+0000-00FF}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1920px;height:1080px;overflow:hidden;font-family:T,sans-serif;direction:rtl}
.bg{width:1920px;height:1080px;background:radial-gradient(1200px 800px at 80% 10%,#1A6F5A 0%,#124E42 55%,#0b3329 100%);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:34px;position:relative}
.tag{font-size:30px;color:#67BDA0;letter-spacing:.5px}
.big{font-size:96px;font-weight:700;line-height:1.35;max-width:1500px}
.mid{font-size:50px;font-weight:500;line-height:1.5;max-width:1500px}
.small{font-size:32px;color:#cfe9df}
.chip{display:inline-block;border:2px solid #67BDA0;color:#e8fff6;border-radius:40px;padding:10px 28px;font-size:32px}
.foot{position:absolute;bottom:42px;left:0;right:0;font-size:26px;color:#9fd3c0}
`;
const doc = (body, extra = '') => `<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><style>${css}${extra}</style></head><body>${body}</body></html>`;

const cards = {
  'q-card': doc(`<div class="bg">
    <div class="tag">رسالة عميل — مشهد تمثيلي</div>
    <div class="big">«كم بقي من المكاتب المتاحة؟»</div>
    <div class="mid">الجواب الآن… لا غدًا.</div>
    <div class="foot">مبانيك · منصة المطوّر العقاري</div></div>`),
  'group-card': doc(`<div class="bg">
    <div class="tag">المجموعة والأمان</div>
    <div class="mid" style="font-size:60px;font-weight:700">كيان معزول لكل شركة في المجموعة</div>
    <div style="display:flex;gap:60px;align-items:center;margin-top:10px">
      <div style="width:560px;height:300px;border-radius:28px;background:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px">
        <img src="${BAYAN}" style="height:150px"><div style="color:#124E42;font-size:38px;font-weight:700">بيان عمان</div></div>
      <div style="font-size:70px;color:#67BDA0">⟷</div>
      <div style="width:560px;height:300px;border-radius:28px;border:3px dashed #67BDA0;display:flex;align-items:center;justify-content:center;font-size:40px;color:#cfe9df">كيان آخر في المجموعة</div>
    </div>
    <div style="display:flex;gap:26px;margin-top:10px"><span class="chip">عزل على مستوى قاعدة البيانات</span><span class="chip">سجل تدقيق لا يُمحى</span><span class="chip">رمز تحقق علني لكل مستند</span></div>
    <div class="foot">بيانات تجريبية</div></div>`),
  'end-card': doc(`<div class="bg" style="gap:28px">
    <div style="display:flex;gap:70px;align-items:center">
      <div style="background:#fff;border-radius:26px;padding:22px 40px"><img src="${BAYAN}" style="height:130px"></div>
      <div style="font-size:60px;color:#67BDA0">×</div>
      <div style="background:#fff;border-radius:26px;padding:20px 54px;display:flex;flex-direction:column;align-items:center;gap:6px"><svg viewBox="0 0 386 382" style="height:104px" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="42" width="160" height="160" fill="#124E42"/><polygon points="281,0 384,103 281,206 178,103" fill="#67BDA0"/><path d="M2 220h160A160 160 0 0 1 2 380Z" fill="#1A6F5A"/><rect x="180" y="221" width="160" height="160" fill="#124E42"/></svg><div style="font-size:62px;font-weight:700;color:#124E42;line-height:1.2">مبانيك</div></div></div>
    <div class="big" style="font-size:84px">جرِّبوا مبانيك على بيانات مشاريعكم</div>
    <div class="mid" dir="ltr" style="font-size:46px">mabaneek.com &nbsp;·&nbsp; sales@mabaneek.com</div>
    <div class="small">${S.hijri} الموافق ${S.gregorian}</div>
    <div class="foot">مشاهد تمثيلية — البيانات والأسعار تجريبية</div></div>`),
  'badge-demo': doc(`<div style="position:absolute;top:30px;left:34px;background:rgba(18,78,66,.9);color:#fff;border:2px solid #67BDA0;border-radius:14px;padding:8px 24px;font-size:30px">بيانات تجريبية</div>`, 'html,body{background:transparent}'),
  'badge-gen': doc(`<div style="position:absolute;bottom:34px;left:34px;background:rgba(0,0,0,.55);color:#fff;border-radius:14px;padding:8px 24px;font-size:26px">مشاهد تمثيلية</div>`, 'html,body{background:transparent}')
};

const subCss = 'html,body{background:transparent}';
const subs = {};
for (const [nid, lines] of Object.entries(S.captions)) lines.forEach((t, i) => {
  subs[`sub_${nid}_${i}`] = doc(`<div style="position:absolute;bottom:64px;left:0;right:0;display:flex;justify-content:center"><div style="background:rgba(8,40,33,.78);color:#fff;font-size:50px;font-weight:500;line-height:1.5;padding:12px 44px;border-radius:18px;max-width:1740px;text-align:center">${t}</div></div>`, subCss);
});

const browser = await chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'});
const page = await (await browser.newContext({viewport: {width: 1920, height: 1080}})).newPage();
for (const [name, html] of Object.entries({...cards, ...subs})) {
  const f = join(OUT, name + '.html'); writeFileSync(f, html);
  await page.goto(pathToFileURL(f).href); await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(150);
  await page.screenshot({path: join(OUT, name + '.png'), omitBackground: name.startsWith('badge') || name.startsWith('sub_')});
}
await browser.close();
console.log('cards:', Object.keys(cards).length, 'subs:', Object.keys(subs).length);
