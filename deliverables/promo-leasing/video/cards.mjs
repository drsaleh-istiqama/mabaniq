// بطاقات الفيديو وطبقاته (HTML عربي RTL مركَّب برمجيًا ⟵ PNG بـPlaywright). لا نص عربي بنموذج صور.
//   node cards.mjs     (يقرأ script.json ويكتب cards/*.png و cards/sub_*.png و cards/tag_*.png)
import {chromium} from '@playwright/test';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..', '..', '..');
const OUT = join(HERE, 'cards'); mkdirSync(OUT, {recursive: true});
const S = JSON.parse(readFileSync(join(HERE, 'script.json'), 'utf8'));
const F = f => pathToFileURL(join(ROOT, 'web', 'fonts', f)).href;
const P = k => pathToFileURL(join(OUT, `p_${k}.png`)).href;
const MARK = `<svg viewBox="0 0 386 382" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="42" width="160" height="160" fill="#124E42"/><polygon points="281,0 384,103 281,206 178,103" fill="#67BDA0"/><path d="M2 220h160A160 160 0 0 1 2 380Z" fill="#1A6F5A"/><rect x="180" y="221" width="160" height="160" fill="#124E42"/></svg>`;

const css = `
@font-face{font-family:T;font-weight:400;src:url(${F('tajawal-arabic-400-normal.woff2')})}
@font-face{font-family:T;font-weight:500;src:url(${F('tajawal-arabic-500-normal.woff2')})}
@font-face{font-family:T;font-weight:700;src:url(${F('tajawal-arabic-700-normal.woff2')})}
@font-face{font-family:T;font-weight:400;src:url(${F('tajawal-latin-400-normal.woff2')});unicode-range:U+0000-00FF}
@font-face{font-family:T;font-weight:700;src:url(${F('tajawal-latin-700-normal.woff2')});unicode-range:U+0000-00FF}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1920px;height:1080px;overflow:hidden;font-family:T,sans-serif;direction:rtl}
.bg{width:1920px;height:1080px;background:radial-gradient(1200px 800px at 80% 10%,#1A6F5A 0%,#124E42 55%,#0b3329 100%);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:34px;position:relative}
.tag{font-size:30px;color:#67BDA0}
.big{font-size:92px;font-weight:700;line-height:1.35;max-width:1500px}
.mid{font-size:46px;font-weight:500;line-height:1.5;max-width:1500px}
.small{font-size:32px;color:#cfe9df}
.foot{position:absolute;bottom:42px;left:0;right:0;font-size:26px;color:#9fd3c0}
.team{display:flex;gap:56px;margin-top:6px}
.who{display:flex;flex-direction:column;align-items:center;gap:14px;width:330px}
.who img{width:250px;height:250px;border-radius:50%;border:6px solid #67BDA0;background:#0b3329;object-fit:cover}
.who b{font-size:46px;font-weight:700}
.who span{font-size:30px;color:#cfe9df}
`;
const doc = (body, extra = '') => `<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><style>${css}${extra}</style></head><body>${body}</body></html>`;
const T = 'html,body{background:transparent}';
const chip = (a, b) => `<div style="position:absolute;top:44px;right:48px;display:flex;flex-direction:column;gap:6px;background:rgba(18,78,66,.92);color:#fff;border-right:8px solid #67BDA0;border-radius:14px;padding:12px 28px 14px 34px"><b style="font-size:46px;font-weight:700;line-height:1.2">${a}</b><span style="font-size:28px;color:#cfe9df">${b}</span></div>`;

const cards = {
  chars: doc(`<div class="bg">
    <div class="tag">مشاهد تمثيلية · أربع شخصيات تعمل مع قسم الإيجارات</div>
    <div class="big" style="font-size:78px">وهؤلاء أبطال قصتنا</div>
    <div class="team">
      <div class="who"><img src="${P('owner')}"><b>أبو سعيد</b><span>المالك</span></div>
      <div class="who"><img src="${P('manager')}"><b>سالم</b><span>مدير الإيجارات</span></div>
      <div class="who"><img src="${P('tenant')}"><b>يوسف</b><span>المستأجر</span></div>
      <div class="who"><img src="${P('accountant')}"><b>ناصر</b><span>المحاسب</span></div>
    </div></div>`),
  'end-card': doc(`<div class="bg" style="gap:26px">
    <div style="display:flex;gap:46px;align-items:center;background:#fff;border-radius:30px;padding:24px 60px"><div style="width:120px">${MARK}</div><div style="font-size:92px;font-weight:700;color:#124E42;line-height:1.1">مبانيك</div></div>
    <div class="big" style="font-size:78px">الإيجارات… بوضوح</div>
    <div class="mid" style="font-size:42px;color:#cfe9df">عقود · تحصيل · شيكات · متأخرات · صيانة · كشوف ملاك — في ملف واحد موثوق</div>
    <div class="mid" dir="ltr" style="font-size:46px">mabaneek.com &nbsp;·&nbsp; sales@mabaneek.com</div>
    <div class="small">${S.hijri} الموافق ${S.gregorian}</div>
    <div class="small" style="font-size:26px;color:#9fd3c0">مشاهد تمثيلية — الأسماء والأرقام والبيانات تجريبية</div></div>`),
  'badge-demo': doc(`<div style="position:absolute;top:30px;left:34px;background:rgba(18,78,66,.9);color:#fff;border:2px solid #67BDA0;border-radius:14px;padding:8px 24px;font-size:30px">بيانات تجريبية</div>`, T),
  'badge-gen': doc(`<div style="position:absolute;top:30px;left:34px;background:rgba(0,0,0,.55);color:#fff;border-radius:14px;padding:8px 24px;font-size:26px">مشاهد تمثيلية</div>`, T),
  tag_title: doc(`<div style="position:absolute;top:70px;left:0;right:0;display:flex;flex-direction:column;align-items:center;gap:12px"><div style="background:rgba(18,78,66,.9);color:#fff;border-radius:22px;padding:18px 60px;text-align:center"><div style="font-size:84px;font-weight:700;line-height:1.2">الإيجارات في مبانيك</div><div style="font-size:36px;color:#cfe9df">ملف الإيجار الواحد الموثوق</div></div></div>`, T),
  tag_owner: doc(chip('أبو سعيد', 'المالك'), T),
  tag_manager: doc(chip('سالم', 'مدير الإيجارات'), T),
  tag_tenant: doc(chip('يوسف', 'المستأجر'), T),
  tag_accountant: doc(chip('ناصر', 'المحاسب'), T),
  tag_pair: doc(`<div style="position:absolute;top:44px;right:48px;display:flex;flex-direction:column;gap:10px">
      <div style="background:rgba(18,78,66,.92);color:#fff;border-right:8px solid #67BDA0;border-radius:14px;padding:8px 28px 10px 34px"><b style="font-size:40px">سالم</b> <span style="font-size:26px;color:#cfe9df">&nbsp;مدير الإيجارات</span></div>
      <div style="background:rgba(18,78,66,.92);color:#fff;border-right:8px solid #67BDA0;border-radius:14px;padding:8px 28px 10px 34px"><b style="font-size:40px">يوسف</b> <span style="font-size:26px;color:#cfe9df">&nbsp;المستأجر</span></div></div>`, T)
};

const subs = {};
for (const [nid, lines] of Object.entries(S.captions)) lines.forEach((t, i) => {
  subs[`sub_${nid}_${i}`] = doc(`<div style="position:absolute;bottom:64px;left:0;right:0;display:flex;justify-content:center"><div style="background:rgba(8,40,33,.8);color:#fff;font-size:50px;font-weight:500;line-height:1.5;padding:12px 44px;border-radius:18px;max-width:1740px;text-align:center">${t}</div></div>`, T);
});

const browser = await chromium.launch({channel: process.env.PW_CHANNEL || 'chrome'});
const page = await (await browser.newContext({viewport: {width: 1920, height: 1080}})).newPage();
for (const [name, html] of Object.entries({...cards, ...subs})) {
  const f = join(OUT, name + '.html'); writeFileSync(f, html);
  await page.goto(pathToFileURL(f).href); await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(150);
  await page.screenshot({path: join(OUT, name + '.png'), omitBackground: /^(badge|tag_|sub_)/.test(name)});
}
await browser.close();
console.log('cards:', Object.keys(cards).length, 'subs:', Object.keys(subs).length);
