# -*- coding: utf-8 -*-
"""يبني «دليل التشغيل» (HTML للطباعة) من ops_content.py واللقطات في ../shots.
    python deliverables/promo-bayan/ops-manual/tools/build_ops_manual.py [--pages pages.json]
ثم:  node deliverables/promo-bayan/ops-manual/tools/print_ops.mjs   (يطبع PDF ويستبدل الغلاف)
واجهة عربية RTL صراحةً، التاريخ الهجري أولًا، أرقام غربية، بلا كلمات مرور في أي مخرَج."""
from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

from hijridate import Gregorian
from PIL import Image

HERE = Path(__file__).resolve().parent
OPS = HERE.parent
PKG = OPS.parent
sys.path.insert(0, str(HERE))
import ops_content as C  # noqa: E402

SHOTS, IMG, FONTS = OPS / "shots", OPS / "img", OPS / "fonts"
IMG.mkdir(exist_ok=True)
FONTS.mkdir(exist_ok=True)
for f in (Path(r"C:\mabaniq\web\fonts")).glob("tajawal-*.woff2"):
    if not (FONTS / f.name).exists():
        shutil.copy(f, FONTS / f.name)

import datetime as dt  # noqa: E402

TODAY = dt.date(2026, 10, 27)
_h = Gregorian(TODAY.year, TODAY.month, TODAY.day).to_hijri()
DATE_LINE = f"{_h.day} {_h.month_name('ar')} {_h.year}هـ الموافق {TODAY.day} أكتوبر {TODAY.year}م"
E = html.escape
PAGES = {}
if "--pages" in sys.argv:
    PAGES = json.loads(Path(sys.argv[sys.argv.index("--pages") + 1]).read_text(encoding="utf-8"))

fig_no = [0]


def prep(name: str, kind: str) -> str:
    """يحوّل لقطة PNG إلى JPEG خفيف في img/ ويقصّ لقطات الهاتف الطويلة."""
    src = SHOTS / f"{name}.png"
    if not src.exists():
        print("  ! لقطة ناقصة:", name)
        return ""
    out = IMG / f"{name}.jpg"
    im = Image.open(src).convert("RGB")
    if kind == "phone":
        w, h = im.size
        im = im.crop((0, 0, w, min(h, int(w * 2.1))))   # أول شاشة ونصف تقريبًا
        out = IMG / f"{name}-p.jpg"
    im.save(out, "JPEG", quality=80, optimize=True)
    return f"img/{out.name}"


def role_strip() -> str:
    """يلصق الأشرطة الجانبية للأدوار الأربعة بجانب بعض في صورة واحدة."""
    names = [("o02-side-ceo", "المدير العام"), ("o02-side-sales", "المبيعات"), ("o02-side-finance", "المالية"), ("o02-side-engineer", "المهندس")]
    ims = []
    for n, _ in names:
        p = SHOTS / f"{n}.png"
        if p.exists():
            ims.append(Image.open(p).convert("RGB"))
    if not ims:
        return ""
    H = max(i.height for i in ims)
    W = sum(i.width for i in ims) + 24 * (len(ims) - 1)
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    x = 0
    for i in ims:
        canvas.paste(i, (x, 0))
        x += i.width + 24
    out = IMG / "roles-sidebars.jpg"
    canvas.save(out, "JPEG", quality=88)
    return "img/roles-sidebars.jpg"


def steps_html(steps) -> str:
    out = []
    for n, text in steps:
        badge = f'<span class="n">{n}</span>' if n else '<span class="n dot"></span>'
        out.append(f"<li>{badge}<div>{E(text)}</div></li>")
    return '<ol class="steps">' + "".join(out) + "</ol>"


def figure_html(fig) -> str:
    if not fig:
        return ""
    name, cap, kind = fig
    src = prep(name, kind)
    if not src:
        return ""
    fig_no[0] += 1
    return f'<figure class="f {kind}"><img src="{src}" alt="{E(cap)}"><figcaption>الشكل {fig_no[0]} · {E(cap)}</figcaption></figure>'


def block_html(b) -> str:
    fig = b.get("fig")
    kind = fig[2] if fig else "none"
    steps = steps_html(b["steps"])
    f = figure_html(fig)
    return f'<div class="blk {kind}"><div class="st">{steps}</div>{f}</div>'


CALL = {"tip": ("نصيحة", "tip"), "warn": ("تنبيه", "warn"), "note": ("ملاحظة", "note")}


def task_html(t) -> str:
    meta = f'<span class="chip role">الدور: {E(t["role"])}</span><span class="chip path">المسار: {E(t["path"])}</span>'
    out = [f'<section class="task" id="t{t["id"].replace(".", "-")}"><h3><span class="tid">{t["id"]}</span>{E(t["title"])}<span class="mk">@@t{t["id"]}@@</span></h3><div class="meta">{meta}</div>',
           f'<p class="goal"><b>الغاية:</b> {E(t["goal"])}</p>']
    out += [block_html(b) for b in t["blocks"]]
    for kind, text in t.get("tips", []):
        label, cls = CALL[kind]
        out.append(f'<div class="call {cls}"><b>{label}</b> {E(text)}</div>')
    if t.get("result"):
        out.append(f'<div class="result"><b>ما الذي تتوقعه:</b> {E(t["result"])}</div>')
    out.append("</section>")
    return "".join(out)


def chapter_html(ch) -> str:
    out = [f'<section class="chap" id="c{ch["n"]}"><header class="chead"><div class="cn">{ch["n"]}</div><div><h2>{E(ch["title"])}<span class="mk">@@c{ch["n"]}@@</span></h2>'
           f'<div class="cwho">{E(ch["who"])}</div></div></header><p class="cintro">{E(ch["intro"])}</p>']
    out += [task_html(t) for t in ch["tasks"]]
    out.append("</section>")
    return "".join(out)


def pg(key: str) -> str:
    v = PAGES.get(key)
    return f'<span class="pn">{v}</span>' if v else ""


CHAPTERS = [C.CH1, C.CH2, C.CH3, C.CH4, C.CH5, C.CH6, C.CH7, C.CH8, C.CH9, C.CH10, C.CH11]


def toc_html() -> str:
    rows = ['<h2 class="plain">المحتويات</h2><div class="toc">']
    for ch in CHAPTERS:
        rows.append(f'<div class="tc"><span class="tn">{ch["n"]}</span><span class="tt">{E(ch["title"])}</span><span class="dots"></span>{pg("c%d" % ch["n"])}</div>')
        for t in ch["tasks"]:
            rows.append(f'<div class="tr"><span class="tn">{t["id"]}</span><span class="tt">{E(t["title"])}</span><span class="dots"></span>{pg("t" + t["id"])}</div>')
    extra = [("scen", "12", "سيناريوهات كاملة متعددة الأدوار"), ("faq", "13", "استكشاف الأخطاء والأسئلة الشائعة"), ("perm", "14", "مصفوفة الصلاحيات"), ("lim", "15", "حدود هذه البيئة ومسرد المصطلحات")]
    for k, n, t in extra:
        rows.append(f'<div class="tc"><span class="tn">{n}</span><span class="tt">{E(t)}</span><span class="dots"></span>{pg(k)}</div>')
    rows.append("</div>")
    return "".join(rows)


FLOW = [("عميل محتمل", "المبيعات"), ("عرض سعر", "المبيعات"), ("حجز مبدئي", "المبيعات"), ("تأكيد البيع والعربون", "المالية"), ("التحقق من الهوية", "المبيعات"),
        ("العقد والتوقيع", "المبيعات + العميل"), ("التحصيل والفواتير", "المالية"), ("المستخلص والإنجاز", "المهندس + المدير"), ("التسليم", "المهندس"), ("نقل الملكية", "المهندس + المالية")]


def flow_html() -> str:
    boxes = []
    for i, (a, b) in enumerate(FLOW, 1):
        boxes.append(f'<div class="fb"><span class="fi">{i}</span><b>{E(a)}</b><small>{E(b)}</small></div>')
    return '<div class="flow">' + '<span class="ar">◂</span>'.join(boxes) + "</div>"


ROLE_ROWS = [
    ("المدير العام", "bayan-ceo", "كل الأقسام", "القرارات، اعتماد المستخلصات وأوامر التغيير والخصومات، المستخدمون، الهوية والنسخ", "2 و9"),
    ("المبيعات", "bayan-sales", "لوحة القيادة، المخزون، العملاء المحتملون، التسويق، العقود والوسطاء، التسليم (التسليم والعيوب وإدارة المرافق)، خدمة العملاء، التقارير", "العملاء، العروض، الحجز، الهوية والعقود، الوسطاء، الحملات", "3 و6 و7"),
    ("المالية", "bayan-finance", "كل ما سبق + الأراضي، الإنشاء، السيولة والتعثر، الفواتير والضمان، سجل التدقيق، ونقل الملكية واتحاد الملاك والتأجير", "العربون وتأكيد البيع، التحصيل، المطابقة، الضمان، التأجير", "4"),
    ("مهندس المشاريع", "bayan-engineer", "لوحة القيادة، التراخيص، الإنشاء والمستخلصات، التسليم والأملاك (التسليم ونقل الملكية والمرافق)، التقارير", "المستخلصات، تقارير الموقع، التراخيص، التسليم", "5"),
    ("العميل", "bayan-client", "تطبيق الجوال: وحدتي، الدفعات، الصيانة، إعادة البيع، المزيد", "المتابعة والدفع والتوقيع والصيانة", "10"),
    ("الوسيط", "(يُفتح بطلب)", "بوابة الوسيط", "تسجيل العملاء ومتابعة العمولات", "11"),
]


def tbl(head, rows, cls="") -> str:
    h = "".join(f"<th>{E(x)}</th>" for x in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>'


def about_html() -> str:
    strip = role_strip()
    roles = tbl(["الدور", "حساب التجربة", "ما يظهر في القائمة", "أبرز مهامه", "الباب"],
                [[E(a), f'<span class="ltr">{E(b)}</span>', E(c), E(d), E(e)] for a, b, c, d, e in ROLE_ROWS], "roles")
    return f"""
<section class="about"><h2 class="plain">كيف تستعمل هذا الدليل</h2>
<p class="lead">هذا دليل <b>تشغيلي</b>: لكل موظف ما يفعله في مبانيك يومًا بيوم، بخطوات مرقّمة ولقطات حقيقية من منصة «بيان عمان». ليس شرحًا لمزايا المنصة (لذلك دليل التعريف)، بل «اضغط هنا ثم هنا».</p>
<div class="legend"><div><span class="n big">3</span><b>الرقم البرتقالي</b> في الخطوة يطابق العلامة التي تحمل الرقم نفسه على اللقطة.</div>
<div><span class="n dot big"></span><b>النقطة الخضراء</b> خطوة بلا علامة على اللقطة (فتح شاشة أو قراءة).</div>
<div><b class="tag tip">نصيحة</b><b class="tag warn">تنبيه</b><b class="tag note">ملاحظة</b> إطارات تلفت إلى ما يغيّر القرار أو يوقع في الخطأ.</div></div>
<h3 class="sub">مسار البيع كاملًا: من يفعل ماذا</h3>{flow_html()}
<h3 class="sub">الأدوار وحسابات التجربة</h3>{roles}
<h3 class="sub">ما تراه أنت يتغيّر بحسب دورك</h3>
<figure class="f wide"><img src="{strip}" alt="الأشرطة الجانبية للأدوار"><figcaption>الشكل 1 · الشريط الجانبي لكل دور من اليمين: المدير العام، المبيعات، المالية، المهندس (ما لا يسمح به الدور لا يظهر).</figcaption></figure>
<div class="call note"><b>ملاحظة</b> بيانات الأسعار والعملاء والمستأجرين في هذه البيئة افتراضية مبنية على مساحات كتيّبات الشركة؛ لا تُدخل بيانات عملاء أو مستأجرين حقيقيين في بيئة التجربة.</div>
</section>"""


def scen_html() -> str:
    out = ['<section class="chap" id="cscen"><header class="chead"><div class="cn">12</div><div><h2>سيناريوهات كاملة متعددة الأدوار<span class="mk">@@scen@@</span></h2><div class="cwho">الدورة من أولها إلى آخرها</div></div></header>',
           '<p class="cintro">ثلاث دورات تتقاطع فيها أدوار المنصة؛ كل صف يحيلك إلى المهمة التي تشرحه.</p>']
    for s in C.SCEN:
        out.append(f'<h3 class="sub">{E(s["title"])}</h3>')
        out.append(tbl(["#", "الدور", "الشاشة", "ما يحدث", "انظر"], [[E(a), E(b), E(c), E(d), E(e)] for a, b, c, d, e in s["rows"]], "scen"))
    out.append("</section>")
    return "".join(out)


def faq_html() -> str:
    out = ['<section class="chap" id="cfaq"><header class="chead"><div class="cn">13</div><div><h2>استكشاف الأخطاء والأسئلة الشائعة<span class="mk">@@faq@@</span></h2><div class="cwho">حين لا يعمل شيء كما تتوقع</div></div></header>']
    out.append(tbl(["المشكلة", "السبب والحل"], [[f"<b>{E(a)}</b>", E(b)] for a, b in C.FAQ], "faq"))
    out.append("</section>")
    return "".join(out)


def perm_html() -> str:
    cols = [("admin", "المدير"), ("sales", "المبيعات"), ("finance", "المالية"), ("engineer", "المهندس")]
    rows = []
    for key, label in C.PERM_LABELS:
        rows.append([E(label)] + ['<span class="ok">✓</span>' if key in C.PERMS[r] else '<span class="no">—</span>' for r, _ in cols])
    out = ['<section class="chap" id="cperm"><header class="chead"><div class="cn">14</div><div><h2>مصفوفة الصلاحيات<span class="mk">@@perm@@</span></h2><div class="cwho">من يستطيع ماذا (كما في الإعداد الحالي)</div></div></header>',
           '<p class="cintro">إن لم تجد زرًا ذكره الدليل فراجع هذا الجدول. تعديل دور مستخدم يتم من «الإدارة والأمان ⟵ المستخدمون»؛ أما تغيير ما يملكه الدور نفسه فيتم عبر فريق جدوى.</p>',
           tbl(["الصلاحية"] + [l for _, l in cols], rows, "perm"), "</section>"]
    return "".join(out)


def limits_html() -> str:
    lim = "".join(f"<li>{E(x)}</li>" for x in C.LIMITS)
    gl = tbl(["المصطلح", "المعنى"], [[f"<b>{E(a)}</b>", E(b)] for a, b in C.GLOSSARY], "faq")
    sc = tbl(["الاختصار", "الوظيفة"], [["<span class='ltr'>Ctrl + K</span>", "لوحة الأوامر والبحث السريع"], ["<span class='ltr'>Esc</span>", "يغلق اللوحة أو النافذة"], ["<span class='ltr'>Enter</span>", "يفتح النتيجة المحددة في لوحة الأوامر"], ["<span class='ltr'>↑ ↓</span>", "التنقل بين النتائج"]], "faq")
    return f"""<section class="chap" id="clim"><header class="chead"><div class="cn">15</div><div><h2>حدود هذه البيئة ومسرد المصطلحات<span class="mk">@@lim@@</span></h2><div class="cwho">اقرأه قبل أن تعتمد على ما ترى</div></div></header>
<h3 class="sub">ما يجب أن يُقال بصراحة</h3><ul class="lim">{lim}</ul>
<h3 class="sub">اختصارات لوحة المفاتيح</h3>{sc}
<h3 class="sub">مسرد المصطلحات</h3>{gl}</section>"""


CSS = """
@font-face{font-family:'Tajawal';font-weight:400;src:url('fonts/tajawal-arabic-400-normal.woff2') format('woff2');unicode-range:U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF,U+200C-200F}
@font-face{font-family:'Tajawal';font-weight:500;src:url('fonts/tajawal-arabic-500-normal.woff2') format('woff2');unicode-range:U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF,U+200C-200F}
@font-face{font-family:'Tajawal';font-weight:700;src:url('fonts/tajawal-arabic-700-normal.woff2') format('woff2');unicode-range:U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF,U+200C-200F}
@font-face{font-family:'Tajawal';font-weight:400;src:url('fonts/tajawal-latin-400-normal.woff2') format('woff2');unicode-range:U+0000-00FF,U+2000-206F,U+2190-21FF,U+25A0-25FF,U+2713}
@font-face{font-family:'Tajawal';font-weight:500;src:url('fonts/tajawal-latin-500-normal.woff2') format('woff2');unicode-range:U+0000-00FF,U+2000-206F,U+2190-21FF,U+25A0-25FF,U+2713}
@font-face{font-family:'Tajawal';font-weight:700;src:url('fonts/tajawal-latin-700-normal.woff2') format('woff2');unicode-range:U+0000-00FF,U+2000-206F,U+2190-21FF,U+25A0-25FF,U+2713}
:root{--ink:#16231f;--muted:#4f605a;--line:#cfdad5;--pale:#f1f6f4;--brand:#124E42;--brand2:#1A6F5A;--brand3:#67BDA0;--badge:#E8590C;--navy:#0F1B2D;--warn:#B45309;--warnbg:#FFF4E5}
@page{size:A4;margin:14mm 14mm 17mm}
*{box-sizing:border-box}
html{direction:rtl}
body{margin:0;font-family:'Tajawal','Noto Naskh Arabic',Arial,sans-serif;font-size:10.1pt;line-height:1.72;color:var(--ink);background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact;text-align:start}
.ltr{direction:ltr;unicode-bidi:isolate;display:inline-block}
h1,h2,h3{font-weight:700;line-height:1.45;margin:0}
/* الغلاف */
.cover{height:297mm;margin:-14mm -14mm -17mm;padding:0;background:var(--navy);color:#fff;position:relative;display:flex;flex-direction:column;justify-content:space-between;break-after:page;overflow:hidden}
.cover:before{content:"";position:absolute;inset-block:0;inset-inline-start:0;width:9mm;background:var(--brand2)}
.cover .in{padding:22mm 24mm 0 18mm;padding-inline-start:26mm}
.logos{display:flex;align-items:center;justify-content:space-between;gap:12mm}
.logos .a{background:#fff;border-radius:3mm;padding:4mm 6mm}.logos .a img{height:20mm;display:block}
.logos .b img{height:22mm;display:block}
.cover h1{font-size:34pt;margin-top:34mm}
.cover .sub{font-size:17pt;color:var(--brand3);margin-top:3mm;font-weight:500}
.cover .tag{font-size:12pt;color:#dfe6ec;margin-top:6mm;max-width:130mm}
.cover .hero{margin-top:14mm;height:86mm;border-radius:3mm;overflow:hidden;border:1px solid rgba(255,255,255,.18)}
.cover .hero img{width:100%;height:100%;object-fit:cover;object-position:center 35%;display:block}
.cover .cap{font-size:8.5pt;color:#9fb0c0;margin-top:2mm}
.cover .foot{padding:0 26mm 16mm 24mm;font-size:11pt;color:#fff}
.cover .foot .d{color:var(--brand3);font-weight:700;font-size:12pt}
.cover .foot .m{color:#aebccb;font-size:9.5pt;margin-top:1mm}
/* العناوين */
h2.plain{font-size:20pt;color:var(--brand);margin:0 0 4mm;border-bottom:.7mm solid var(--brand3);padding-bottom:2mm}
.lead{font-size:11.2pt;margin:0 0 5mm}
h3.sub{font-size:13pt;color:var(--brand);margin:6mm 0 2.5mm;break-after:avoid}
.chap{break-before:page}
.chead{display:flex;align-items:center;gap:6mm;background:var(--brand);color:#fff;border-radius:3mm;padding:5mm 7mm;margin-bottom:5mm}
.chead .cn{font-size:34pt;font-weight:700;color:var(--brand3);line-height:1;min-width:14mm;text-align:center}
.chead h2{font-size:19pt}
.cwho{font-size:10pt;color:#cfe6dd;margin-top:1mm}
.cintro{font-size:10.8pt;color:var(--muted);margin:0 0 4mm}
/* المهام */
.task{margin-bottom:8mm}
.task h3{font-size:14.5pt;color:var(--brand);display:flex;align-items:baseline;gap:3mm;break-after:avoid;margin-top:3mm;border-bottom:.35mm solid var(--line);padding-bottom:1.5mm}
.tid{background:var(--brand2);color:#fff;border-radius:2mm;font-size:11pt;padding:0 2.4mm;line-height:1.7;font-weight:700}
.meta{display:flex;flex-wrap:wrap;gap:2mm;margin:2mm 0;break-after:avoid}
.chip{font-size:8.6pt;background:var(--pale);color:var(--brand);border:.3mm solid var(--line);border-radius:5mm;padding:0 3mm;line-height:1.8}
.goal{margin:1.5mm 0 3mm;color:var(--ink);break-after:avoid}
.blk{margin:3mm 0}
.blk.side,.blk.phone{break-inside:avoid}
figure.f{break-inside:avoid}
.blk.side,.blk.phone{display:grid;grid-template-columns:1fr 74mm;gap:6mm;align-items:start}
.blk.phone{grid-template-columns:1fr 54mm}
.blk.wide .st{margin-bottom:3mm}
ol.steps{list-style:none;margin:0;padding:0}
ol.steps li{display:flex;gap:3mm;align-items:flex-start;margin:0 0 2.2mm;line-height:1.7}
ol.steps li>div{flex:1;min-width:0}
.n{flex:0 0 6.4mm;width:6.4mm;height:6.4mm;border-radius:50%;background:var(--badge);color:#fff;font-weight:700;font-size:9.5pt;display:inline-flex;align-items:center;justify-content:center;margin-top:.6mm;border:.4mm solid #fff;box-shadow:0 0 0 .3mm var(--badge)}
.n.dot{background:var(--brand2);box-shadow:0 0 0 .3mm var(--brand2);width:2.6mm;height:2.6mm;flex-basis:2.6mm;margin:2.5mm 1.8mm 0;border:0}
.n.big{width:7mm;height:7mm;flex-basis:7mm;vertical-align:middle;margin-inline-end:2mm}
.n.dot.big{width:3mm;height:3mm;flex-basis:3mm;margin:0 2mm 0 0}
figure.f{margin:0}
figure.f img{width:100%;display:block;border:.35mm solid var(--line);border-radius:2mm;box-shadow:0 .6mm 2mm rgba(15,27,45,.12)}
figure.f.wide img{max-height:112mm;object-fit:contain;object-position:top center;background:#fff}
figure.f.phone img{max-height:140mm;object-fit:cover;object-position:top}
figcaption{font-size:8.3pt;color:var(--muted);margin-top:1.3mm;line-height:1.5}
.call{border-inline-start:1.3mm solid;border-radius:1.5mm;padding:2mm 3.5mm;margin:2.5mm 0;font-size:9.8pt;line-height:1.7;break-inside:avoid}
.call b:first-child,.tag{display:inline-block;font-size:8.6pt;border-radius:1mm;padding:0 2mm;margin-inline-end:2mm;color:#fff;vertical-align:baseline}
.call.tip,.tip{border-color:var(--brand2);background:#EEF7F3}.call.tip b:first-child,.tag.tip{background:var(--brand2)}
.call.warn{border-color:var(--warn);background:var(--warnbg)}.call.warn b:first-child,.tag.warn{background:var(--warn)}
.call.note{border-color:#6b7b8c;background:#F2F4F7}.call.note b:first-child,.tag.note{background:#6b7b8c}
.tag{margin-inline-start:1mm}
.result{margin:2.5mm 0;padding:2mm 3.5mm;background:var(--pale);border-radius:1.5mm;font-size:9.8pt;border:.3mm dashed var(--brand3);break-inside:avoid}
.result b{color:var(--brand)}
/* جداول */
table{width:100%;border-collapse:collapse;font-size:9.2pt;margin:2mm 0 4mm;break-inside:auto}
th{background:var(--brand);color:#fff;text-align:start;padding:1.8mm 2.5mm;font-weight:700}
td{padding:1.8mm 2.5mm;border-bottom:.3mm solid var(--line);vertical-align:top}
tr{break-inside:avoid}tbody tr:nth-child(even) td{background:var(--pale)}
table.perm td:not(:first-child),table.perm th:not(:first-child){text-align:center;width:17mm}
table.perm td{padding:1mm 2.5mm;font-size:8.8pt}table.perm{margin-bottom:0}
.ok{color:var(--brand2);font-weight:700}.no{color:#a5b3ad}
table.scen td:first-child,table.scen th:first-child{width:7mm;text-align:center}
.legend{display:grid;gap:2.5mm;background:var(--pale);border:.3mm solid var(--line);border-radius:2mm;padding:3.5mm 5mm;margin:3mm 0}
.legend div{display:flex;align-items:center;gap:1mm;flex-wrap:wrap}
.tag{display:inline-block}
/* مسار */
.flow{display:flex;flex-wrap:wrap;align-items:stretch;gap:1.5mm;margin:2mm 0 4mm}
.fb{flex:1 1 30mm;background:var(--pale);border:.3mm solid var(--line);border-radius:2mm;padding:2mm 2.5mm;text-align:center;position:relative;min-width:30mm}
.fb b{display:block;font-size:9.4pt;color:var(--brand)}.fb small{display:block;font-size:8pt;color:var(--muted)}
.fi{position:absolute;inset-block-start:-2mm;inset-inline-start:-2mm;background:var(--brand2);color:#fff;width:5mm;height:5mm;border-radius:50%;font-size:7.5pt;display:flex;align-items:center;justify-content:center}
.ar{align-self:center;color:var(--brand3);font-size:10pt}
.lim{margin:0;padding-inline-start:5mm}.lim li{margin:0 0 2mm}
/* المحتويات */
.toc{display:block}
.tc,.tr{display:flex;align-items:baseline;gap:2mm}
.tc{margin-top:2.6mm;font-weight:700;color:var(--brand);font-size:11pt}
.tr{padding-inline-start:9mm;font-size:9.8pt;color:var(--ink)}
.tn{min-width:9mm;color:var(--brand2);font-weight:700}
.tt{flex:0 1 auto}
.dots{flex:1;border-bottom:.3mm dotted #9bb0a7;transform:translateY(-1mm);min-width:6mm}
.pn{min-width:7mm;text-align:end;font-weight:700;color:var(--muted)}
.toc-page{break-before:page}
.mk{font-size:2px;line-height:0;color:#fffffe;direction:ltr;unicode-bidi:isolate}
.about{break-before:page}
"""


def build() -> str:
    body = []
    body.append(f"""<div class="cover"><div class="in"><div class="logos"><div class="b"><img src="web-assets/bayan-logo.png" alt="بيان عمان"></div><div class="a"><img src="web-assets/mabaniq-logo.png" alt="مبانيك"></div></div>
<h1>دليل التشغيل</h1><div class="sub">مبانيك لمؤسسة بيان العقارية</div>
<div class="tag">لكل موظف ما يفعله يومًا بيوم: الدخول، البيع، التحصيل، التأجير، المستخلصات، التسليم، التسويق، والتقارير — بخطوات مرقّمة ولقطات حقيقية.</div>
<div class="hero"><img src="web-assets/masahat-render-entrance.jpg" alt=""></div><div class="cap">التصور النهائي لمشروع مساحات الخوض — من كتيّب الشركة.</div></div>
<div class="foot"><div class="d">{DATE_LINE}</div><div class="m">الإصدار 1.0 · مبانيك 0.15.0 · بيانات افتراضية لأغراض التدريب والتجربة</div><div class="m">إعداد: جدوى للدراسات والتطوير — مسقط، سلطنة عُمان</div></div></div>""")
    body.append(f'<section class="toc-page">{toc_html()}</section>')
    body.append(about_html())
    for ch in CHAPTERS:
        body.append(chapter_html(ch))
    body += [scen_html(), faq_html(), perm_html(), limits_html()]
    return f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>دليل التشغيل — مبانيك لمؤسسة بيان العقارية</title><style>{CSS}</style></head><body dir="rtl">{"".join(body)}</body></html>'


if __name__ == "__main__":
    # web-assets: ننسخ الشعارين والصورة من حزمة الدليل الترويجي
    wa = OPS / "web-assets"
    wa.mkdir(exist_ok=True)
    for f in ("bayan-logo.png", "mabaniq-logo.png", "masahat-render-entrance.jpg"):
        shutil.copy(PKG / "web-assets" / f, wa / f)
    out = OPS / "ops-manual-print.html"
    out.write_text(build(), encoding="utf-8", newline="\n")
    print("HTML:", out.name, f"{out.stat().st_size // 1024} KB", "· أشكال:", fig_no[0])
