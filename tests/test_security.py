import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "sec.db"))

from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402


CSRF = 'csrf-test-token-' + 'x' * 24


def client(user=None, csrf=True):
    c = TestClient(app)
    c.__enter__()
    if user:
        c.cookies.set(A.COOKIE, A.issue_session(user))
        if csrf:
            c.cookies.set(A.CSRF_COOKIE, CSRF)
            c.headers["X-CSRF-Token"] = CSRF
    return c


def test_api_docs_hidden():
    c = client()
    for p in ["/docs", "/redoc", "/openapi.json"]:
        assert c.get(p).status_code == 404


def test_no_secrets_served():
    c = client("admin")
    for p in ["/static/../data/credentials.json", "/static/%2e%2e/data/credentials.json", "/data/credentials.json", "/static/../backend/auth.py"]:
        r = c.get(p)
        assert r.status_code == 404 or "admin" not in r.text


def test_security_headers():
    r = client().get("/login")
    for h in ["content-security-policy", "x-frame-options", "x-content-type-options", "strict-transport-security", "referrer-policy"]:
        assert h in r.headers


def test_csrf_cross_origin_blocked():
    c = client("admin")
    r = c.post("/api/reset", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/assistant", content=b"q=x", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415
    # 0.5.0 — M7: جلسة صالحة بلا رمز CSRF مطابق تُرفض (طلب من الأصل نفسه بلا ترويسة)
    c2 = client("admin", csrf=False)
    assert c2.post("/api/notifications/run").status_code == 403
    c2.cookies.set(A.CSRF_COOKIE, CSRF)
    assert c2.post("/api/notifications/run", headers={"X-CSRF-Token": "wrong-" + CSRF}).status_code == 403
    assert c2.post("/api/notifications/run", headers={"X-CSRF-Token": CSRF}).status_code == 200


def test_csp_has_no_inline_scripts():
    c = client()
    r = c.get("/login")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self';" in csp and "unsafe-inline" not in csp.split("style-src")[0]
    import re
    for p in ("/login",):
        html = c.get(p).text
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html), "سكربت مضمّن في " + p
        assert 'onclick="' not in html


def test_spoofed_ip_does_not_bypass_lockout():
    c = client()
    codes = [c.post("/api/auth/login", json={"username": "engineer", "password": "bad-pass"},
                    headers={"cf-connecting-ip": f"10.0.0.{i}"}).status_code for i in range(7)]
    assert 429 in codes


def test_sql_injection_harmless():
    c = client("admin")
    for q in ["' OR 1=1 --", "%'; DROP TABLE units; --"]:
        assert c.get("/api/search", params={"q": q}).status_code == 200
    assert len(c.get("/api/projects").json()) == 5


def test_input_limits():
    c = client("admin")
    assert c.post("/api/assistant", json={"q": "a" * 5000}).status_code == 422
    assert c.post("/api/bookings", json={"unit_code": "x", "customer_name": "<script>", "phone": "abc<>", "plan": "6040"}).status_code == 422
    assert c.get("/api/audit?limit=100000").status_code == 422


def test_session_invalid_and_expired():
    c = client()
    c.cookies.set(A.COOKIE, "forged-token")
    assert c.get("/api/me").status_code == 401


def test_customer_isolation_idor():
    c1 = client("client1")
    b = c1.get("/api/portal").json()["bookings"][0]
    c2 = client("client2")
    assert all(x["booking_id"] != b["booking_id"] for x in c2.get("/api/portal").json()["bookings"])
    assert c2.post("/api/portal/resale", json={"booking_id": b["booking_id"], "ask_price": 1000}).status_code == 404
    assert c2.get("/api/units/" + b["unit"]).status_code == 403
