"""0.14.0 — public landing page: routes, SEO files, security headers, the demo-request form and its retention rule."""
import dataclasses
import json
import os
import re
import struct
import tempfile
import xml.etree.ElementTree as ET

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "landing.db"))
os.environ.setdefault("MABANIQ_RATE_DEMO", "5/3600")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import landing as L  # noqa: E402
from backend import mail  # noqa: E402
from backend import observability as O  # noqa: E402
from backend import retention as R  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import DEFAULT_TENANT, TENANT, audit_verify, connect  # noqa: E402

PUBLIC = "https://mabaniq.example.test"
GOOD = {"name": "محمد التجريبي", "company": "شركة الاختبار للتطوير", "email": "Lead@Example.com", "phone": "+968 9000 0000", "projects": 3,
        "message": "أريد رؤية التحصيل والسيولة", "lang": "ar", "website": ""}


@pytest.fixture
def cl():
    O.limiter.reset()
    with TestClient(app, base_url="https://landing.local") as c:
        yield c


@pytest.fixture
def public_url(monkeypatch):
    """MABANIQ_PUBLIC_URL set — every domain-dependent artefact must derive from it."""
    from backend import config, identity
    s = dataclasses.replace(config.settings, public_url=PUBLIC)
    monkeypatch.setattr(identity, "settings", s)
    monkeypatch.setattr(L, "settings", s)
    return PUBLIC


def staff(c, user="admin"):
    c.cookies.set(A.COOKIE, A.issue_session(user))
    return c


def ld_blocks(html: str) -> list[dict]:
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def demo_rows():
    tok = TENANT.set(DEFAULT_TENANT)
    try:
        c = connect()
        try:
            return [dict(r) for r in c.execute("SELECT * FROM demo_requests ORDER BY id").fetchall()]
        finally:
            c.close()
    finally:
        TENANT.reset(tok)


# ---------------------------------------------------------------- pages
def test_visitor_gets_arabic_landing_and_signed_in_users_their_dashboard(cl, public_url):
    r = cl.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert '<html lang="ar" dir="rtl">' in html
    assert html.count("<h1") == 1 and "من الحجز إلى التسليم" in html
    assert r.headers["x-robots-tag"] == "index, follow" and r.headers["cache-control"] == "no-store"
    assert f'<link rel="canonical" href="{PUBLIC}/">' in html and f'hreflang="en" href="{PUBLIC}/en"' in html
    assert f'property="og:image" content="{PUBLIC}/og.png"' in html and "__PUBLIC_URL__" not in html
    assert "googleapis" not in html and "cdn." not in html  # no external host — CSP would block it anyway
    # staff → dashboard (noindex), customer → /app, broker → /broker
    assert "لوحة القيادة" in staff(cl).get("/").text and staff(cl).get("/").headers["x-robots-tag"] == "noindex, nofollow"
    c2 = TestClient(app)
    c2.cookies.set(A.COOKIE, A.issue_session("client1"))
    assert c2.get("/", follow_redirects=False).headers["location"] == "/app"
    c3 = TestClient(app)
    c3.cookies.set(A.COOKIE, A.issue_session("broker1"))
    assert c3.get("/", follow_redirects=False).headers["location"] == "/broker"
    # a signed-in user asking for /en is routed like "/"
    assert staff(cl).get("/en", follow_redirects=False).status_code == 303


def test_english_twin_and_privacy_pages(cl, public_url):
    en = cl.get("/en")
    assert en.status_code == 200 and '<html lang="en" dir="ltr">' in en.text and en.text.count("<h1") == 1
    assert f'<link rel="canonical" href="{PUBLIC}/en">' in en.text and f'hreflang="ar" href="{PUBLIC}/"' in en.text
    assert en.headers["x-robots-tag"] == "index, follow"
    for path, lang, needle in (("/privacy", "ar", "اطلب عرضًا حيًّا"), ("/en/privacy", "en", "Request a live demo")):
        p = cl.get(path)
        assert p.status_code == 200 and f'<html lang="{lang}"' in p.text and needle in p.text, path
        assert str(R.policy()["demo_requests_days"]) in p.text  # the retention period is stated on the policy page
        assert "/static/assets/landing-" in p.text  # reuses the built landing stylesheet
        assert p.headers["x-robots-tag"] == "index, follow"


def test_json_ld_blocks_are_valid(cl):
    for path in ("/", "/en"):
        blocks = ld_blocks(cl.get(path).text)
        types = {b["@type"] for b in blocks}
        assert types == {"Organization", "SoftwareApplication", "FAQPage"}, path
        faq = next(b for b in blocks if b["@type"] == "FAQPage")
        assert 8 <= len(faq["mainEntity"]) <= 12 and all(q["acceptedAnswer"]["text"] for q in faq["mainEntity"])


def test_security_headers_and_no_executable_inline_script(cl):
    login_csp = cl.get("/login").headers["content-security-policy"]
    for path in ("/", "/en", "/privacy"):
        r = cl.get(path)
        assert r.headers["content-security-policy"] == login_csp, path  # CSP unchanged — no weakening for the public pages
        for h in ("strict-transport-security", "x-frame-options", "x-content-type-options", "referrer-policy", "permissions-policy"):
            assert h in r.headers, (path, h)
        body = re.sub(r'<script type="application/ld\+json">.*?</script>', "", r.text, flags=re.S)  # data blocks are not executable
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", body), path
        assert 'onclick="' not in body
    # images: every <img> has alt + explicit dimensions, below-the-fold ones are lazy
    imgs = re.findall(r"<img [^>]+>", cl.get("/").text)
    assert len(imgs) >= 10
    for tag in imgs:
        assert 'alt="' in tag and 'width="' in tag and 'height="' in tag, tag
    assert sum('loading="lazy"' in t for t in imgs) >= len(imgs) - 1


# ---------------------------------------------------------------- robots / sitemap / og / verification
def test_robots_and_sitemap_derive_from_public_url(cl, public_url):
    rb = cl.get("/robots.txt")
    assert rb.status_code == 200 and rb.headers["content-type"].startswith("text/plain")
    txt = rb.text
    for blocked in ("/api/", "/app", "/broker", "/login", "/verify/", "/d/"):
        assert f"Disallow: {blocked}" in txt
    assert "Allow: /" in txt and f"Sitemap: {PUBLIC}/sitemap.xml" in txt and "Disallow: /static" not in txt
    sm = cl.get("/sitemap.xml")
    assert sm.status_code == 200 and sm.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(sm.text)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}
    locs = [u.find("s:loc", ns).text for u in root.findall("s:url", ns)]
    assert locs == [f"{PUBLIC}/", f"{PUBLIC}/en", f"{PUBLIC}/privacy", f"{PUBLIC}/en/privacy"]
    first = root.find("s:url", ns)
    assert {a.get("hreflang") for a in first.findall("x:link", ns)} == {"ar", "en", "x-default"}
    assert first.find("s:lastmod", ns).text == L.LASTMOD


def test_og_images_are_generated_png_1200x630(cl):
    for path in ("/og.png", "/og-en.png"):
        r = cl.get(path)
        assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.headers["x-robots-tag"] == "index, follow"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = struct.unpack(">II", r.content[16:24])
        assert (w, h) == (1200, 630), path
    assert cl.get("/og.png").content == cl.get("/og.png").content  # cached per process


def test_search_console_verification_files_only_when_configured(cl, monkeypatch):
    from backend import config
    assert cl.get("/googleabcdef123456.html").status_code == 404
    assert cl.get("/BingSiteAuth.xml").status_code == 404
    monkeypatch.setattr(L, "settings", dataclasses.replace(config.settings, gsc_token="google1a2b3c4d5e6f.html", bing_token="BING1234567890"))
    ok = cl.get("/google1a2b3c4d5e6f.html")
    assert ok.status_code == 200 and ok.text == "google-site-verification: google1a2b3c4d5e6f.html"
    assert cl.get("/googleWRONGTOKEN00.html").status_code == 404
    bing = cl.get("/BingSiteAuth.xml")
    assert bing.status_code == 200 and "<user>BING1234567890</user>" in bing.text


# ---------------------------------------------------------------- demo request
def test_demo_request_saves_mails_and_audits_without_personal_data(cl):
    before = len(demo_rows())
    before_out = len(list(mail.outbox_dir().glob("*.json")))
    r = cl.post("/api/public/demo-request", json=GOOD, headers={"Origin": "https://landing.local"})
    assert r.status_code == 200 and r.json()["ok"] and "وصلنا طلبك" in r.json()["message"]
    rows = demo_rows()
    assert len(rows) == before + 1
    row = rows[-1]
    assert row["email"] == "lead@example.com" and row["company"] == GOOD["company"] and row["projects"] == 3 and row["lang"] == "ar"
    assert row["mailed"] == 1 and len(row["ip_hash"]) == 16 and "." not in row["ip_hash"]  # hashed, not the address
    files = sorted(mail.outbox_dir().glob("*.json"))
    assert len(files) == before_out + 1
    m = json.loads(files[-1].read_text(encoding="utf-8"))
    assert m["kind"] == "demo_request" and GOOD["company"] in m["subject"] and GOOD["phone"] in m["text"]
    # one audit line, no personal data in it, chain intact
    tok = TENANT.set(DEFAULT_TENANT)
    try:
        c = connect()
        try:
            a = c.execute("SELECT * FROM audit WHERE action='طلب عرض حي' ORDER BY id DESC LIMIT 1").fetchone()
            assert a and GOOD["email"].lower() not in a["detail"] and GOOD["name"] not in a["detail"] and GOOD["phone"] not in a["detail"]
            assert audit_verify(c)["ok"]
        finally:
            c.close()
    finally:
        TENANT.reset(tok)


def test_demo_request_honeypot_is_silently_dropped(cl):
    before = len(demo_rows())
    r = cl.post("/api/public/demo-request", json={**GOOD, "website": "http://spam.example"}, headers={"Origin": "https://landing.local"})
    assert r.status_code == 200 and r.json()["ok"]  # indistinguishable from success
    assert len(demo_rows()) == before


def test_demo_request_validation_limits(cl):
    bad = [{**GOOD, "email": "not-an-email"}, {**GOOD, "name": "x"}, {**GOOD, "name": "n" * 81}, {**GOOD, "phone": "abc"},
           {**GOOD, "projects": 5000}, {**GOOD, "message": "m" * 1001}, {**GOOD, "lang": "fr"}, {k: v for k, v in GOOD.items() if k != "company"}]
    for body in bad:
        O.limiter.reset()  # validation, not the demo bucket, is under test here
        assert cl.post("/api/public/demo-request", json=body, headers={"Origin": "https://landing.local"}).status_code == 422, body
    assert cl.post("/api/public/demo-request", content=b"a=b", headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 415


def test_demo_request_rate_limited_in_its_own_bucket(cl):
    O.limiter.reset()
    codes = [cl.post("/api/public/demo-request", json=GOOD, headers={"Origin": "https://landing.local"}).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    r = cl.post("/api/public/demo-request", json=GOOD, headers={"Origin": "https://landing.local"})
    assert r.status_code == 429 and r.headers["x-ratelimit-bucket"] == "demo" and "retry-after" in r.headers
    assert cl.get("/api/auth/methods").status_code == 200  # the general api bucket is untouched
    O.limiter.reset()
    assert cl.post("/api/public/demo-request", json=GOOD, headers={"Origin": "https://evil.example"}).status_code == 403  # cross-origin


def test_demo_requests_retention_rule(cl):
    tok = TENANT.set(DEFAULT_TENANT)
    try:
        c = connect()
        try:
            c.execute("INSERT INTO demo_requests(created,name,company,email,phone,projects,message,lang,ip_hash,user_agent,mailed) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                      ("2020-01-01T00:00:00", "قديم", "شركة قديمة", "old@example.com", "+968 90000001", 1, "", "ar", "x" * 16, ""))
            c.execute("INSERT INTO demo_requests(created,name,company,email,phone,projects,message,lang,ip_hash,user_agent,mailed) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                      ("2999-01-01T00:00:00", "جديد", "شركة جديدة", "new@example.com", "+968 90000002", 1, "", "ar", "y" * 16, ""))
            c.commit()
            counts = R.run(c, actor="اختبار")["counts"]
            assert counts["demo_requests"] >= 1
            assert c.execute("SELECT COUNT(*) FROM demo_requests WHERE email='old@example.com'").fetchone()[0] == 0
            assert c.execute("SELECT COUNT(*) FROM demo_requests WHERE email='new@example.com'").fetchone()[0] == 1
            assert "demo_requests_days" in R.policy()
        finally:
            c.close()
    finally:
        TENANT.reset(tok)
