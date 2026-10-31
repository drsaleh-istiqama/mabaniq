"""Operating manuals — Markdown guides + screenshots → one RTL HTML per guide (→ PDF with topdf.mjs).

  deliverables/manuals/src/<key>.md      the guide (authoring conventions below)
  deliverables/manuals/_shots/...        screenshots from scripts/manuals/crawl.mjs
  deliverables/manuals/html/<key>.html   built page (images inlined, so the file is self-contained)

Authoring conventions (see deliverables/manuals/README.md):
  front matter  : "key: value" lines between two "---" lines  (title, sector, audience, order)
  # / ## / ###  : cover title is the front-matter title; "##" = chapter (auto-numbered), "###" = section
  figures       : ![caption](shot:bayan/lea/02-العقود.png)           picture from _shots, caption below it
  callouts      : a line starting with "!tip ", "!warn ", "!rule " or "!link "   (advice · caution · system rule · connection to another part)
  tables        : pipe tables;  lists: "1." and "-"
Run:  python scripts/manuals/build_manuals.py [key ...]
"""
from __future__ import annotations

import base64
import html
import io
import re
import sys
from datetime import date
from pathlib import Path

import markdown
from hijridate import Gregorian
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "deliverables" / "manuals"
SRC, SHOTS, OUT = BASE / "src", BASE / "_shots", BASE / "html"
FONTS = ROOT / "web" / "fonts"
VERSION = "1.0"
HIJRI_MONTHS = ["محرم", "صفر", "ربيع الأول", "ربيع الآخر", "جمادى الأولى", "جمادى الآخرة", "رجب", "شعبان", "رمضان", "شوال", "ذو القعدة", "ذو الحجة"]
GREG_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
CALLOUTS = {"tip": ("💡", "نصيحة"), "warn": ("⚠", "تنبيه"), "rule": ("🔒", "قاعدة في النظام"), "link": ("🔗", "ارتباط بباقي النظام")}


def western(n) -> str:
    return str(n)


def dates_line(d: date) -> str:
    h = Gregorian(d.year, d.month, d.day).to_hijri()
    return f"{h.day} {HIJRI_MONTHS[h.month - 1]} {h.year} هـ الموافق {d.day} {GREG_MONTHS[d.month - 1]} {d.year} م"


def font_face() -> str:
    out = []
    for w in (400, 500, 700):
        for sub, rng in (("arabic", "U+0600-06FF,U+0750-077F,U+FB50-FDFF,U+FE70-FEFF,U+200C-200F"), ("latin", "U+0000-00FF,U+2000-206F")):
            f = FONTS / f"tajawal-{sub}-{w}-normal.woff2"
            if f.exists():
                b64 = base64.b64encode(f.read_bytes()).decode()
                out.append(f"@font-face{{font-family:'Tajawal';font-weight:{w};src:url(data:font/woff2;base64,{b64}) format('woff2');unicode-range:{rng}}}")
    return "\n".join(out)


def image_uri(rel: str, max_w: int = 1100) -> str | None:
    p = SHOTS / rel
    if not p.exists():
        return None
    im = Image.open(p).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=84, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def split_front(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for ln in m.group(1).splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def preprocess(body: str, missing: list[str]) -> str:
    out = []
    chapter = 0
    for ln in body.splitlines():
        m = re.match(r"^!(tip|warn|rule|link)\s+(.*)$", ln)
        if m:
            kind, txt = m.groups()
            icon, label = CALLOUTS[kind]
            out.append(f'\n<div class="co {kind}" markdown="1"><b class="cl">{icon} {label}</b> {txt}</div>\n')
            continue
        m = re.match(r"^!\[(.*?)\]\(shot:(.+?)\)\s*$", ln)
        if m:
            cap, rel = m.groups()
            uri = image_uri(rel)
            if uri is None:
                missing.append(rel)
                out.append(f'\n<div class="co warn"><b>صورة غير موجودة:</b> {html.escape(rel)}</div>\n')
            else:
                out.append(f'\n<figure><img src="{uri}" alt="{html.escape(cap)}"><figcaption>{html.escape(cap)}</figcaption></figure>\n')
            continue
        m = re.match(r"^##\s+(.*)$", ln)
        if m:
            chapter += 1
            out.append(f'\n<h2 id="c{chapter}"><span class="num">{chapter}</span>{m.group(1)}</h2>\n')
            continue
        out.append(ln)
    return "\n".join(out)


CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
:root{--ink:#16233b;--mut:#5b6b85;--line:#d9e0ec;--gold:#a8741a;--navy:#14284b;--soft:#f4f7fb;--tip:#e8f5ee;--warn:#fdf2e0;--rule:#e9eefb;--link:#f1ecfb}
*{box-sizing:border-box}
html{direction:rtl}
body{font-family:'Tajawal',sans-serif;color:var(--ink);font-size:11.5pt;line-height:1.85;margin:0;direction:rtl;text-align:right}
.cover{page-break-after:always;min-height:255mm;display:flex;flex-direction:column;justify-content:space-between;padding:6mm 2mm}
.cover .brand{display:flex;align-items:center;gap:10px;color:var(--navy);font-weight:700;font-size:15pt}
.cover .brand small{display:block;font-weight:400;font-size:9.5pt;color:var(--mut)}
.cover .mid{border-inline-start:6px solid var(--gold);padding-inline-start:18px}
.cover h1{font-size:30pt;line-height:1.3;color:var(--navy);margin:0 0 10px}
.cover .sub{font-size:15pt;color:var(--gold);font-weight:700;margin:0 0 6px}
.cover .aud{font-size:12pt;color:var(--mut);margin:0}
.cover .foot{font-size:10.5pt;color:var(--mut);border-top:1px solid var(--line);padding-top:8px}
.cover .foot b{color:var(--ink)}
h2{font-size:18pt;color:var(--navy);margin:26px 0 8px;padding-bottom:6px;border-bottom:2px solid var(--gold);page-break-after:avoid;display:flex;align-items:center;gap:10px}
h2 .num{background:var(--navy);color:#fff;border-radius:7px;min-width:30px;height:30px;display:inline-flex;align-items:center;justify-content:center;font-size:13pt}
h3{font-size:13.5pt;color:var(--navy);margin:16px 0 4px;page-break-after:avoid}
p{margin:6px 0}
ol,ul{margin:6px 0;padding-inline-start:24px}
li{margin:3px 0}
li::marker{color:var(--gold);font-weight:700}
figure{margin:12px 0;page-break-inside:avoid;text-align:center}
figure img{max-width:100%;max-height:205mm;border:1px solid var(--line);border-radius:6px;box-shadow:0 2px 8px rgba(20,40,75,.08)}
figcaption{font-size:9.5pt;color:var(--mut);margin-top:4px}
.co{border-radius:8px;padding:8px 12px;margin:10px 0;font-size:10.5pt;line-height:1.7;page-break-inside:avoid;border-inline-start:4px solid}
.co.tip{background:var(--tip);border-color:#2f8f5d}.co.warn{background:var(--warn);border-color:#d28a14}.co.rule{background:var(--rule);border-color:#3b5bb5}.co.link{background:var(--link);border-color:#6b4bb5}
.co .cl{margin-inline-end:6px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:10.5pt;page-break-inside:avoid}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:right;vertical-align:top}
th{background:var(--soft);color:var(--navy)}
blockquote{margin:10px 0;padding:8px 14px;background:var(--soft);border-inline-start:4px solid var(--gold);border-radius:6px;color:var(--ink)}
code{font-family:'Tajawal',monospace;background:var(--soft);padding:0 4px;border-radius:4px;direction:ltr;unicode-bidi:isolate}
.toc{page-break-after:always}
.toc h2{margin-top:0}
.toc ol{list-style:none;padding:0;counter-reset:t}
.toc li{counter-increment:t;padding:7px 0;border-bottom:1px dashed var(--line);font-size:12.5pt}
.toc li::before{content:counter(t);display:inline-block;background:var(--navy);color:#fff;border-radius:6px;min-width:26px;text-align:center;margin-inline-end:10px;font-size:10.5pt}
.feedback{page-break-before:always}
.lines{border-bottom:1px solid var(--line);height:26px}
"""


def build(path: Path) -> list[str]:
    meta, body = split_front(path.read_text(encoding="utf-8"))
    missing: list[str] = []
    pre = preprocess(body, missing)
    md = markdown.Markdown(extensions=["tables", "md_in_html", "sane_lists"])
    content = md.convert(pre)
    chapters = re.findall(r'<h2 id="c(\d+)"><span class="num">\d+</span>(.*?)</h2>', content)
    toc = "".join(f"<li>{t}</li>" for _, t in chapters)
    today = date.today()
    title = meta.get("title", path.stem)
    sector = meta.get("sector", "")
    cover = f"""<section class="cover">
  <div class="brand"><svg width="44" height="44" viewBox="0 0 44 44"><rect width="44" height="44" rx="9" fill="#14284b"/><rect x="9" y="9" width="11" height="11" fill="#a8741a"/><rect x="24" y="9" width="11" height="11" fill="#fff"/><rect x="9" y="24" width="11" height="11" fill="#fff"/><rect x="24" y="24" width="11" height="11" fill="#a8741a"/></svg><div>مبانيك | Mabaneek<small>منصة المطوّر العقاري · جدوى للدراسات والتطوير</small></div></div>
  <div class="mid"><p class="sub">دليل التشغيل المصوّر</p><h1>{html.escape(title)}</h1><p class="aud">{html.escape(sector)}</p><p class="aud">{html.escape(meta.get('audience', ''))}</p></div>
  <div class="foot"><b>النسخة {VERSION}</b> · {dates_line(today)}<br>الصور مأخوذة من مؤسسة تجريبية ببيانات افتراضية مخترعة للعرض والتجربة، وليست بيانات حقيقية.</div>
</section>"""
    toc_html = f'<section class="toc"><h2 style="border:0">محتويات الدليل</h2><ol>{toc}</ol></section>' if chapters else ""
    doc = f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{html.escape(title)}</title><style>{font_face()}{CSS}</style></head><body dir="rtl">{cover}{toc_html}<main>{content}</main></body></html>"""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{path.stem}.html").write_text(doc, encoding="utf-8")
    return missing


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    keys = sys.argv[1:] or [p.stem for p in sorted(SRC.glob("*.md"))]
    for k in keys:
        miss = build(SRC / f"{k}.md")
        print(k, "ok", f"missing images: {miss}" if miss else "")
