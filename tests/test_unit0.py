"""Unit 0 — configuration, observability, health, rate limiting and the full security-header set."""
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "u0.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from backend import observability as O  # noqa: E402
from backend.app import app  # noqa: E402
from backend.config import Settings, settings  # noqa: E402


def test_health_ready_version_without_auth():
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "ok"
        r = c.get("/ready")
        assert r.status_code == 200 and r.json()["checks"]["database"] == "ok"
        v = c.get("/version").json()
        assert v["version"] == settings.version and "database" in v and "secret" not in str(v).lower()


def test_request_id_generated_and_propagated():
    with TestClient(app) as c:
        a = c.get("/health")
        assert a.headers["x-request-id"] and len(a.headers["x-request-id"]) >= 8
        b = c.get("/health", headers={"X-Request-ID": "trace-abc-123"})
        assert b.headers["x-request-id"] == "trace-abc-123"
        bad = c.get("/health", headers={"X-Request-ID": "<script>" * 20})
        assert bad.headers["x-request-id"] != "<script>" * 20


def test_security_headers_complete():
    with TestClient(app) as c:
        h = c.get("/login").headers
        for k in ("content-security-policy", "strict-transport-security", "x-frame-options", "x-content-type-options",
                  "referrer-policy", "permissions-policy", "cross-origin-opener-policy", "cross-origin-resource-policy"):
            assert k in h, k
        assert "max-age=63072000" in h["strict-transport-security"]
        assert h["cross-origin-opener-policy"] == "same-origin"
        assert c.get("/static/app.js").headers["cache-control"].startswith("public")
        assert c.get("/login").headers["cache-control"] == "no-store"


def test_login_rate_limit_distinct_from_lockout():
    O.limiter.reset()
    with TestClient(app) as c:
        codes = []
        for i in range(settings.rate_login[0] + 2):
            r = c.post("/api/auth/login", json={"username": f"ghost{i}", "password": "wrong-pass-123"})
            codes.append((r.status_code, r.headers.get("retry-after"), r.headers.get("x-ratelimit-bucket")))
        assert all(code == 401 for code, _, _ in codes[: settings.rate_login[0]])
        assert codes[-1][0] == 429 and codes[-1][1] and codes[-1][2] == "login"
    O.limiter.reset()


def test_unhandled_error_is_json_with_request_id(monkeypatch):
    from fastapi import APIRouter

    from backend import app as A
    r = APIRouter()

    @r.get("/api/_boom")
    def boom():
        raise RuntimeError("boom")
    A.app.include_router(r)
    with TestClient(A.app, raise_server_exceptions=False) as c:
        resp = c.get("/api/_boom")
        assert resp.status_code == 500 and resp.json()["request_id"] == resp.headers["x-request-id"]
        assert "boom" not in resp.text


def test_settings_validation_prod_fail_fast(monkeypatch):
    for k in ("MABANIQ_PII_KEY", "MABANIQ_PAY_SECRET", "MABANIQ_DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MABANIQ_ENV", "prod")
    errs = Settings.from_env().validate()
    assert any("PII_KEY" in e for e in errs) and any("PAY_SECRET" in e for e in errs) and any("DATABASE_URL" in e for e in errs)
    monkeypatch.setenv("MABANIQ_PII_KEY", "k")
    monkeypatch.setenv("MABANIQ_PAY_SECRET", "s")
    monkeypatch.setenv("MABANIQ_DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("MABANIQ_APP_DOMAIN", "mabaniq.om")
    monkeypatch.setenv("MABANIQ_FORCE_PW_CHANGE", "1")
    assert Settings.from_env().validate() == []
    monkeypatch.setenv("MABANIQ_ENV", "demo")
    assert Settings.from_env().validate() == []


def test_demo_password_from_environment(monkeypatch):
    """Hosted demo: one password for every demo account, applied on (re)seed, never in a file."""
    from backend import auth as A
    monkeypatch.setenv("MABANIQ_DEMO_PASSWORD", "Demo-Pass-2026-x")
    with TestClient(app) as c:
        c.cookies.set(A.COOKIE, A.issue_session("admin"))
        c.cookies.set(A.CSRF_COOKIE, "t" * 40)
        assert c.post("/api/reset", headers={"X-CSRF-Token": "t" * 40}).status_code == 200
    with TestClient(app) as c2:
        r = c2.post("/api/auth/login", json={"username": "sales", "password": "Demo-Pass-2026-x"})
        assert r.status_code == 200 and r.json()["role"] == "sales"
    monkeypatch.delenv("MABANIQ_DEMO_PASSWORD")
    with TestClient(app) as c3:
        c3.cookies.set(A.COOKIE, A.issue_session("admin"))
        c3.cookies.set(A.CSRF_COOKIE, "t" * 40)
        c3.post("/api/reset", headers={"X-CSRF-Token": "t" * 40})
