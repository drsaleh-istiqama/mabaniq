"""Mabaniq — public landing page (0.14.0): the marketing front door, served by the platform itself.

The landing page is part of the API process (same security headers, same deploy), not a separate site:
  GET /                       Arabic landing page for a visitor — a signed-in user keeps being routed to their dashboard (app.py)
  GET /en                     English landing page (hreflang pair)
  GET /privacy · /en/privacy  privacy policy: the customers' notice (app.PRIVACY_NOTICE) + the demo-request form section
  GET /robots.txt · /sitemap.xml · /og.png · /og-en.png
  GET /google<token>.html · /BingSiteAuth.xml   search-console verification, served only when the token is configured
  POST /api/public/demo-request                 the only write: a live-demo request (honeypot, own rate bucket, bounded model,
                                                saved in `demo_requests`, mailed through mail.send; never creates an account)

Everything that depends on the final domain (canonical, hreflang, Open Graph, JSON-LD, sitemap) is derived from
MABANIQ_PUBLIC_URL at request time — the built HTML carries the placeholder `__PUBLIC_URL__` (owner decision 4: the domain is
not decided yet, nothing is hard-coded). Public responses mark themselves `X-Robots-Tag: index, follow`; the middleware adds
`noindex, nofollow` to everything else. The OG image is composed programmatically (fpdf2 + HarfBuzz + Tajawal, no people, no
image model — house rule) and rasterised once per process.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import html
import io
import re
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import auth as A
from . import mail
from .config import settings
from .db import DEFAULT_TENANT, TENANT, audit_insert
from .identity import public_url
from .observability import log

router = APIRouter()
FRONT = Path(__file__).resolve().parent.parent / "frontend" / "dist"
PAGES = {"ar": "landing.html", "en": "landing-en.html"}
LASTMOD = "2026-10-11"  # bump when the landing content changes — sitemap <lastmod> (docs/LANDING.md)
INDEXABLE = {"X-Robots-Tag": "index, follow"}
PLACEHOLDER = "__PUBLIC_URL__"
_PAGES: dict[str, tuple[float, str]] = {}
_PAGES_LOCK = threading.Lock()


# ---------------------------------------------------------------- pages
def _built(lang: str) -> str:
    f = FRONT / PAGES[lang]
    if not f.exists():
        raise HTTPException(503, "صفحة الهبوط غير مبنية — شغّل npm run build")
    mt = f.stat().st_mtime
    with _PAGES_LOCK:
        cached = _PAGES.get(lang)
        if cached and cached[0] == mt:
            return cached[1]
        text = f.read_text(encoding="utf-8")
        _PAGES[lang] = (mt, text)
        return text


def page(request: Request, lang: str) -> Response:
    """The built landing page with the public origin substituted (canonical, hreflang, OG, JSON-LD)."""
    body = _built(lang).replace(PLACEHOLDER, public_url(request))
    return HTMLResponse(body, headers={"Cache-Control": "no-store", **INDEXABLE})


@router.get("/en", include_in_schema=False)
def landing_en(request: Request):
    if A.session_user(request):
        return RedirectResponse("/", 303)  # signed-in users land on their dashboard, exactly like "/"
    return page(request, "en")


# ---------------------------------------------------------------- privacy policy (server-rendered, reuses the landing stylesheet)
def _css_links() -> str:
    try:
        src = (FRONT / PAGES["ar"]).read_text(encoding="utf-8")
    except OSError:
        return ""
    return "".join(f'<link rel="stylesheet" href="{h}">' for h in re.findall(r'<link rel="stylesheet"[^>]*href="([^"]+\.css)"', src))


def _logo_mark() -> str:
    """The hashed URL of the approved logo mark (web/img/logo-mark.svg) as Vite published it with the landing page."""
    try:
        m = re.search(r'src="(/static/assets/logo-mark-[^"]+\.svg)"', (FRONT / PAGES["ar"]).read_text(encoding="utf-8"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def _ul(items) -> str:
    return "<ul>" + "".join(f"<li>{html.escape(str(i))}</li>" for i in items) + "</ul>"


PRIVACY_TEXT = {
    "ar": {
        "title": "سياسة الخصوصية — مبانيك",
        "h1": "سياسة الخصوصية",
        "intro": "مبانيك منصة لإدارة التطوير العقاري من جدوى للدراسات والتطوير. تعالج المنصة بيانات عملاء كل مطوّر نيابةً عنه (المطوّر هو المتحكم والمنصة هي المعالج)، وتجمع من زوّار هذه الصفحات العامة ما يلزم للرد على طلب العرض الحي فقط.",
        "s1": "1. إشعار الخصوصية لعملاء المطوّرين", "version": "الإصدار", "effective": "ساري منذ", "controller": "المتحكم والمعالج",
        "purposes": "أغراض المعالجة", "data": "البيانات التي تُعالج", "retention": "مدة الاحتفاظ", "rights": "حقوقك", "law": "القانون الواجب التطبيق", "contact": "جهة التواصل",
        "s2": "2. نموذج «اطلب عرضًا حيًّا» على هذه الصفحة",
        "s2_items": [
            "ما نجمعه: الاسم، اسم الشركة، البريد الإلكتروني، رقم الهاتف، عدد المشاريع، ورسالة اختيارية.",
            "لماذا: للتواصل معك بشأن العرض الحي الذي طلبته فقط. لا تُستعمل البيانات لأي تسويق جماعي ولا تُشارك مع طرف ثالث.",
            "أين: تُحفظ في قاعدة بيانات المنصة وتُرسل نسخة إلى بريد فريق المبيعات في جدوى.",
            "كم: {days} يومًا من تاريخ الطلب ثم تُحذف آليًا بسياسة الاحتفاظ. يمكنك طلب حذفها قبل ذلك بالرد على رسالة التواصل التي تصلك.",
            "لا يُنشأ أي حساب من هذا النموذج، ولا يُخزَّن عنوان الإنترنت كاملًا (تُحفظ بصمة مختصرة منه لمنع الإساءة فقط).",
        ],
        "s3": "3. الكوكيز والتتبع",
        "s3_items": [
            "الصفحات العامة (الرئيسية، النسخة الإنجليزية، هذه السياسة) لا تضع أي كوكي ولا تستخدم أدوات تحليل أو إعلانات خارجية.",
            "بعد تسجيل الدخول تُستعمل كوكيز الجلسة الضرورية فقط (HttpOnly، للأمان) وتنتهي بالخروج أو بالخمول.",
            "لا تُحمَّل خطوط أو سكربتات أو صور من أي مضيف خارجي؛ كل شيء يُخدم من المنصة نفسها.",
        ],
        "s4": "4. الأمان",
        "s4_items": [
            "بيانات الهوية مشفّرة في قاعدة البيانات، وكل مطوّر معزول بصفوفه على مستوى قاعدة البيانات.",
            "كل تغيير مسجَّل في سجل تدقيق مسلسل ببصمة لا يُعدَّل ولا يُحذف.",
            "الاتصال عبر HTTPS فقط، مع ترويسات أمان موثَّقة (CSP بلا سكربتات مضمّنة ولا مضيف خارجي).",
        ],
        "back": "العودة إلى الصفحة الرئيسية", "other": "English version", "other_href": "/en/privacy", "login": "تسجيل الدخول",
        "footer": "جدوى للدراسات والتطوير · مسقط، سلطنة عُمان",
    },
    "en": {
        "title": "Privacy policy — Mabaniq",
        "h1": "Privacy policy",
        "intro": "Mabaniq is a real-estate development platform by Jadwa for Studies & Development. The platform processes each developer's customer data on the developer's behalf (the developer is the controller, the platform the processor), and collects from visitors of these public pages only what is needed to answer a live-demo request.",
        "s1": "1. Privacy notice for developers' customers", "version": "Version", "effective": "Effective since", "controller": "Controller and processor",
        "purposes": "Purposes", "data": "Data processed", "retention": "Retention", "rights": "Your rights", "law": "Applicable law", "contact": "Contact",
        "s2": "2. The “Request a live demo” form on this site",
        "s2_items": [
            "What we collect: name, company, e-mail, phone, number of projects and an optional message.",
            "Why: only to contact you about the live demo you asked for. Never used for bulk marketing, never shared with third parties.",
            "Where: stored in the platform database and a copy is e-mailed to the Jadwa sales team.",
            "How long: {days} days from the request, then deleted automatically by the retention policy. You may ask for earlier deletion by replying to the contact e-mail you receive.",
            "No account is created from this form, and the full IP address is not stored (only a short hash, for abuse prevention).",
        ],
        "s3": "3. Cookies and tracking",
        "s3_items": [
            "The public pages (home, Arabic version, this policy) set no cookies and use no third-party analytics or advertising tools.",
            "After sign-in only strictly necessary session cookies are used (HttpOnly, for security); they end on sign-out or inactivity.",
            "No fonts, scripts or images are loaded from any external host; everything is served by the platform itself.",
        ],
        "s4": "4. Security",
        "s4_items": [
            "Identity data is encrypted in the database, and every developer is isolated at the database row level.",
            "Every change is written to a hash-chained audit log that cannot be edited or deleted.",
            "HTTPS only, with documented security headers (a CSP without inline scripts or external hosts).",
        ],
        "back": "Back to the home page", "other": "النسخة العربية", "other_href": "/privacy", "login": "Sign in",
        "footer": "Jadwa for Studies & Development · Muscat, Sultanate of Oman",
    },
}


def privacy_html(request: Request, lang: str) -> str:
    from .app import PRIVACY_NOTICE  # late import: app.py includes this router at its bottom
    t = PRIVACY_TEXT[lang]
    n = PRIVACY_NOTICE
    days = settings.retention["demo_requests"]
    base = public_url(request)
    rtl = lang == "ar"
    e = html.escape
    home = "/" if rtl else "/en"
    sec1 = (f"<h2>{e(t['s1'])}</h2><p class='muted'>{e(t['version'])} {e(n['version'])} · {e(t['effective'])} {e(n['effective'])}</p>"
            f"<p><b>{e(t['controller'])}:</b> {e(n['controller'])}</p><h3>{e(t['purposes'])}</h3>{_ul(n['purposes'])}"
            f"<h3>{e(t['data'])}</h3>{_ul(n['data'])}<p><b>{e(t['retention'])}:</b> {e(n['retention'])}</p><h3>{e(t['rights'])}</h3>{_ul(n['rights'])}"
            f"<p><b>{e(t['law'])}:</b> {e(n['law'])}</p><p><b>{e(t['contact'])}:</b> {e(n['contact'])}</p>")
    sec2 = f"<h2>{e(t['s2'])}</h2>" + _ul(i.replace("{days}", str(days)) for i in t["s2_items"])
    sec3 = f"<h2>{e(t['s3'])}</h2>" + _ul(t["s3_items"]) + f"<h2>{e(t['s4'])}</h2>" + _ul(t["s4_items"])
    return (f'<!DOCTYPE html><html lang="{lang}" dir="{"rtl" if rtl else "ltr"}"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(t["title"])}</title>'
            f'<meta name="description" content="{e(t["intro"][:150])}"><link rel="canonical" href="{base}{"/privacy" if rtl else "/en/privacy"}">'
            f'<link rel="alternate" hreflang="ar" href="{base}/privacy"><link rel="alternate" hreflang="en" href="{base}/en/privacy">'
            f'<link rel="alternate" hreflang="x-default" href="{base}/privacy">{_css_links()}</head>'
            f'<body class="lp lp-doc"><header class="nav"><div class="wrap nav-in"><a class="brand" href="{home}"><img src="{_logo_mark()}" alt="" width="40" height="40">'
            f'<span>{"مبانيك" if rtl else "Mabaneek"}</span></a><nav class="nav-links"><a href="{e(t["other_href"])}">{e(t["other"])}</a>'
            f'<a class="btn btn-ghost" href="/login">{e(t["login"])}</a></nav></div></header>'
            f'<main class="wrap doc"><h1>{e(t["h1"])}</h1><p class="lead">{e(t["intro"])}</p>{sec1}{sec2}{sec3}'
            f'<p><a class="btn" href="{home}">{e(t["back"])}</a></p></main>'
            f'<footer class="foot"><div class="wrap">{e(t["footer"])}</div></footer></body></html>')


@router.get("/privacy", include_in_schema=False)
def privacy_ar(request: Request):
    return HTMLResponse(privacy_html(request, "ar"), headers={"Cache-Control": "no-store", **INDEXABLE})


@router.get("/en/privacy", include_in_schema=False)
def privacy_en(request: Request):
    return HTMLResponse(privacy_html(request, "en"), headers={"Cache-Control": "no-store", **INDEXABLE})


# ---------------------------------------------------------------- robots / sitemap / verification files
ROBOTS = ("User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /app\nDisallow: /broker\nDisallow: /login\nDisallow: /verify/\n"
          "Disallow: /d/\nDisallow: /auth/\nDisallow: /metrics\nDisallow: /health\nDisallow: /ready\nDisallow: /version\n")
PUBLIC_URLS = [("/", "/", "/en"), ("/en", "/", "/en"), ("/privacy", "/privacy", "/en/privacy"), ("/en/privacy", "/privacy", "/en/privacy")]


@router.get("/robots.txt", include_in_schema=False)
def robots(request: Request):
    return PlainTextResponse(ROBOTS + f"\nSitemap: {public_url(request)}/sitemap.xml\n", headers={"Cache-Control": "public, max-age=3600", **INDEXABLE})


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request):
    b = public_url(request)
    rows = []
    for path, ar, en in PUBLIC_URLS:
        rows.append(f"  <url><loc>{b}{path}</loc><lastmod>{LASTMOD}</lastmod>"
                    f'<xhtml:link rel="alternate" hreflang="ar" href="{b}{ar}"/><xhtml:link rel="alternate" hreflang="en" href="{b}{en}"/>'
                    f'<xhtml:link rel="alternate" hreflang="x-default" href="{b}{ar}"/></url>')
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(rows) + "\n</urlset>\n")
    return Response(body, media_type="application/xml", headers={"Cache-Control": "public, max-age=3600", **INDEXABLE})


def _gsc_token() -> str:
    """MABANIQ_GSC_TOKEN accepts the bare token or the file name Google hands out (google<token>.html)."""
    t = settings.gsc_token
    t = t[6:] if t.startswith("google") else t
    return t[:-5] if t.endswith(".html") else t


@router.get("/google{token}.html", include_in_schema=False)
def google_verification(token: str):
    want = _gsc_token()
    if not want or not re.fullmatch(r"[A-Za-z0-9]{6,80}", token) or not hmac.compare_digest(token, want):
        raise HTTPException(404)
    return PlainTextResponse(f"google-site-verification: google{want}.html", media_type="text/html")


@router.get("/BingSiteAuth.xml", include_in_schema=False)
def bing_verification():
    if not settings.bing_token or not re.fullmatch(r"[A-Za-z0-9]{6,80}", settings.bing_token):
        raise HTTPException(404)
    return Response(f'<?xml version="1.0"?>\n<users>\n  <user>{settings.bing_token}</user>\n</users>\n', media_type="application/xml")


# ---------------------------------------------------------------- Open Graph image (composed, no people, no image model)
_OG: dict[str, bytes] = {}
_OG_LOCK = threading.Lock()
OG_TEXT = {
    "ar": ("مبانيك", "منصة واحدة تدير دورة البيع العقاري كاملة", "من الحجز إلى التسليم", "منتج جدوى للدراسات والتطوير · عربية أولًا · تمويل إسلامي فقط"),
    "en": ("Mabaniq", "One platform for the whole property sales cycle", "From booking to handover", "A Jadwa for Studies & Development product · Arabic-first · Islamic finance only"),
}


def og_png(lang: str) -> bytes:
    """1200×630 PNG: dark navy, gold band, programmatic Arabic/English text (Tajawal + HarfBuzz) — cached per process."""
    with _OG_LOCK:
        if lang in _OG:
            return _OG[lang]
    import pymupdf
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    from .pdfgen import FONTS
    brand, head, sub, foot = OG_TEXT[lang]
    rtl = lang == "ar"
    w, h = 1200, 630
    p = FPDF(unit="pt", format=(w, h))
    p.add_font("Tajawal", "", str(FONTS / "Tajawal-Regular.ttf"))
    p.add_font("Tajawal", "B", str(FONTS / "Tajawal-Bold.ttf"))
    if rtl:
        p.set_text_shaping(use_shaping_engine=True, direction="rtl", script="arab", language="ar")
    p.set_auto_page_break(False)
    p.set_margins(0, 0, 0)
    p.add_page()
    # 0.14.1: the approved Mabaneek identity — white card, logo PNG (backend/assets/brand), greens #124E42 / #1A6F5A / #67BDA0
    dark, accent, ink, muted = (14, 59, 50), (103, 189, 160), (255, 255, 255), (185, 211, 200)
    p.set_fill_color(*dark)
    p.rect(0, 0, w, h, style="F")
    p.set_fill_color(*accent)
    p.rect(0, 0, w, 12, style="F")
    pad, align = 80, ("R" if rtl else "L")
    # logo on a white tile (top, start side)
    logo = Path(__file__).resolve().parent / "assets" / "brand" / "logo-full.png"
    tile_w, tile_h, top = 270, 262, 150
    lx = (w - pad - tile_w) if rtl else pad
    p.set_fill_color(255, 255, 255)
    p.rect(lx, top, tile_w, tile_h, style="F", round_corners=True, corner_radius=24)
    if logo.exists():
        p.image(str(logo), x=lx + 20, y=top + 10, w=tile_w - 40)
    # headline beside the logo
    p.set_text_color(*ink)
    p.set_font("Tajawal", "B", 54)
    tx = pad if rtl else pad + tile_w + 40
    p.set_xy(tx, top + 30)
    p.multi_cell(w - 2 * pad - tile_w - 40, 68, head, align=align, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.set_x(tx)
    # subline
    p.set_text_color(*accent)
    p.set_font("Tajawal", "", 34)
    p.set_x(tx)
    p.multi_cell(w - 2 * pad - tile_w - 40, 46, sub, align=align, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    # footer
    p.set_text_color(*muted)
    p.set_font("Tajawal", "", 20)
    p.set_xy(pad, h - pad - 30)
    p.cell(w - 2 * pad, 30, foot, align=align)
    pdf = bytes(p.output())
    png = pymupdf.open(stream=io.BytesIO(pdf), filetype="pdf")[0].get_pixmap(dpi=72, alpha=False).tobytes("png")
    with _OG_LOCK:
        _OG[lang] = png
    return png


@router.get("/og.png", include_in_schema=False)
def og_ar():
    return Response(og_png("ar"), media_type="image/png", headers={"Cache-Control": "public, max-age=86400", **INDEXABLE})


@router.get("/og-en.png", include_in_schema=False)
def og_en():
    return Response(og_png("en"), media_type="image/png", headers={"Cache-Control": "public, max-age=86400", **INDEXABLE})


# ---------------------------------------------------------------- live-demo request (the only public write)
class DemoIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    company: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=6, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[A-Za-z0-9-]{2,}$")
    phone: str = Field(min_length=6, max_length=24, pattern=r"^\+?[0-9][0-9 ()-]{5,23}$")
    projects: int = Field(default=0, ge=0, le=1000)
    message: str = Field(default="", max_length=1000)
    lang: str = Field(default="ar", pattern=r"^(ar|en)$")
    website: str = Field(default="", max_length=200)  # honeypot — hidden in the form; humans leave it empty


OK_MSG = {"ar": "وصلنا طلبك. سيتواصل معك فريق جدوى خلال يومي عمل لتحديد موعد العرض الحي.",
          "en": "Request received. The Jadwa team will contact you within two working days to schedule the live demo."}


def _notify(rid: int, body: DemoIn, created: str) -> bool:
    """Mail the sales inbox (SMTP, or the outbox in demo). The request is already saved — delivery is best effort."""
    to = settings.sales_email or settings.smtp.get("from_addr") or "sales@mabaniq.local"
    text = (f"طلب عرض حي جديد #{rid} — {created}\n\nالاسم: {body.name}\nالشركة: {body.company}\nالبريد: {body.email}\n"
            f"الهاتف: {body.phone}\nعدد المشاريع: {body.projects}\nلغة الصفحة: {body.lang}\n\nالرسالة:\n{body.message.strip() or '—'}\n")
    try:
        res = mail.send(to, f"طلب عرض حي — {body.company}", text, kind="demo_request")
        return bool(res.get("delivered") or res.get("outbox"))
    except Exception:  # noqa: BLE001 — prod without SMTP, or a transport error: the lead is in the database, the operator sees the log
        log.exception("demo request mail failed", extra={"event": "demo_mail_error"})
        return False


@router.post("/api/public/demo-request")
def demo_request(body: DemoIn, request: Request):
    if body.website.strip():  # honeypot: bots fill the hidden field — answer like a success, store nothing
        log.info("demo honeypot", extra={"event": "demo_honeypot", "path": request.url.path})
        return {"ok": True, "message": OK_MSG[body.lang]}
    ip_hash = hashlib.sha256(A.client_ip(request).encode()).hexdigest()[:16]
    ua = (request.headers.get("user-agent") or "")[:200]
    created = dt.datetime.now().isoformat(timespec="seconds")
    tok = TENANT.set(DEFAULT_TENANT)  # the inbox lives in the operator's database (SQLite: base file; PostgreSQL: the public table)
    try:
        c = A.conn()
        try:
            cur = c.execute("INSERT INTO demo_requests(created,name,company,email,phone,projects,message,lang,ip_hash,user_agent,mailed) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,0)",
                            (created, body.name.strip(), body.company.strip(), body.email.strip().lower(), body.phone.strip(), body.projects,
                             body.message.strip(), body.lang, ip_hash, ua))
            rid = cur.lastrowid
            audit_insert(c, "زائر", "طلب عرض حي", f"#{rid} · {body.lang} · {body.projects} مشاريع")  # no personal data in the audit line
            c.commit()
            if _notify(rid, body, created):
                c.execute("UPDATE demo_requests SET mailed=1 WHERE id=?", (rid,))
                c.commit()
        finally:
            c.close()
    finally:
        TENANT.reset(tok)
    log.info("demo request", extra={"event": "demo_request", "status": rid})
    return {"ok": True, "message": OK_MSG[body.lang]}
