"""Unit 4 — operations: retention policy, metrics endpoint, connection pool and integrity migration (PostgreSQL only)."""
import dataclasses
import datetime as dt
import os
import tempfile
import time

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "u4.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import dbx  # noqa: E402
from backend import observability as O  # noqa: E402
from backend import retention as R  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, audit_verify, connect  # noqa: E402

CSRF = "csrf-unit4-" + "r" * 30


def admin(c):
    c.cookies.set(A.COOKIE, A.issue_session("admin"))
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


@pytest.fixture()
def cl():
    with TestClient(app, base_url="https://testserver") as c:
        yield admin(c)


# ---------------------------------------------------------------- retention
def test_retention_policy_applies_only_to_telemetry_and_stale_rows(cl):
    db = connect()
    now = time.time()
    old = now - 40 * 86400
    old_iso = (dt.datetime.now() - dt.timedelta(days=400)).isoformat(timespec="seconds")
    before_audit = db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    before_pay = db.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    db.execute("INSERT INTO login_attempts(k, at) VALUES(?,?)", ("ip:1.2.3.4", old))
    db.execute("INSERT INTO login_attempts(k, at) VALUES(?,?)", ("ip:1.2.3.5", now))
    db.execute("INSERT INTO auth_failures(k, at) VALUES(?,?)", ("u:ghost", old))
    db.execute("INSERT INTO sessions(token_hash, user_id, expires, created, last_seen) VALUES(?,?,?,?,?)", ("old-session", 1, old, old, old))
    db.execute("INSERT INTO sessions(token_hash, user_id, expires, created, last_seen) VALUES(?,?,?,?,?)", ("live-session", 1, now + 3600, now, now))
    db.execute("INSERT INTO notifications(audience, channel, title, body, status, created, dedupe) VALUES(?,?,?,?,?,?,?)",
               ("staff", "inapp", "قديم", "x", "sent", old_iso, f"u4-old-{now}"))
    db.execute("INSERT INTO pay_intents(id, installment_id, amount, status, created, provider) VALUES(?,?,?,?,?,?)",
               (f"pi_u4_{int(now)}", 1, 10, "pending", old_iso, "sandbox"))
    very_old_iso = (dt.datetime.now() - dt.timedelta(days=800)).isoformat(timespec="seconds")  # messages: 730-day rule
    db.execute("INSERT INTO wa_messages(phone, direction, body, at) VALUES(?,?,?,?)", ("+968 9123 4567", "in", "مرحبا", very_old_iso))
    db.execute("INSERT INTO wa_messages(phone, direction, body, at) VALUES(?,?,?,?)", ("+968 9999 0000", "in", "جديد", dt.datetime.now().isoformat()))
    db.commit()

    r = R.run(db, now=now, actor="اختبار")
    c = r["counts"]
    assert c["login_attempts"] >= 1 and c["auth_failures"] >= 1 and c["sessions"] >= 1  # >=: a shared PostgreSQL database may hold older rows
    assert db.execute("SELECT COUNT(*) FROM login_attempts WHERE at < ?", (old + 1,)).fetchone()[0] == 0
    assert c["notifications"] >= 1 and c["pay_intents_expired"] == 1 and c["wa_messages_masked"] == 1
    assert db.execute("SELECT COUNT(*) FROM login_attempts WHERE k='ip:1.2.3.5'").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM sessions WHERE token_hash='live-session'").fetchone()[0] == 1
    assert db.execute("SELECT status FROM pay_intents WHERE id=?", (f"pi_u4_{int(now)}",)).fetchone()["status"] == "expired"
    masked = db.execute("SELECT phone FROM wa_messages WHERE body='مرحبا'").fetchone()["phone"]
    assert masked.endswith("4567") and masked.startswith("•") and "9123" not in masked
    assert db.execute("SELECT phone FROM wa_messages WHERE body='جديد'").fetchone()["phone"] == "+968 9999 0000"
    # never touches ledgers or the audit log, and leaves one signed audit line of its own
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == before_pay
    assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == before_audit + 1
    assert audit_verify(db)["ok"]
    assert R.last_run(db) and not R.due(db, now)
    assert R.due(db, now + 25 * 3600)
    # idempotent
    assert R.run(db, now=now)["total"] == 0


def test_retention_endpoints_admin_only(cl):
    st = cl.get("/api/admin/retention").json()
    assert st["policy"]["login_telemetry_days"] == 30 and "audit" in st["policy"]["never"]
    r = cl.post("/api/admin/retention/run")
    assert r.status_code == 200 and "counts" in r.json()
    with TestClient(app, base_url="https://testserver") as other:
        other.cookies.set(A.COOKIE, A.issue_session("sales"))
        other.cookies.set(A.CSRF_COOKIE, CSRF)
        assert other.post("/api/admin/retention/run", headers={"X-CSRF-Token": CSRF}).status_code == 403
        assert other.get("/api/admin/retention").status_code == 403


# ---------------------------------------------------------------- metrics
def test_metrics_hidden_without_token_and_served_with_it(cl, monkeypatch):
    assert cl.get("/metrics").status_code == 404
    monkeypatch.setattr(O, "settings", dataclasses.replace(O.settings, metrics_token="metrics-secret-token"))
    assert cl.get("/metrics").status_code == 401
    assert cl.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    cl.get("/api/projects")
    r = cl.get("/metrics", headers={"Authorization": "Bearer metrics-secret-token"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert 'mabaniq_http_requests_total{method="GET",route="/api/projects",status="200"}' in body
    assert "mabaniq_http_request_duration_ms_bucket" in body and "mabaniq_build_info" in body
    import re
    assert not re.search(r'route="[^"]*\d', body)  # ids collapsed to {id}: no identifiers or tokens leak into labels
    assert "token_hash" not in body and "mbq_" not in body
    assert O.Metrics.route("/api/bookings/42/contract") == "/api/bookings/{id}/contract"
    assert O.Metrics.route("/static/assets/index-BVWribFC.js") == "/static/*"


# ---------------------------------------------------------------- PostgreSQL only: pool + integrity migration
pg_only = pytest.mark.skipif(not dbx.is_postgres(), reason="PostgreSQL only")


@pg_only
def test_pool_resets_role_and_tenant_between_uses(cl):
    a = connect("jadwa")
    assert a.execute("SELECT current_user AS u").fetchone()["u"] == dbx.APP_ROLE
    assert a.execute("SELECT current_setting('app.org_id', true) AS o").fetchone()["o"] == "jadwa"
    a.close()
    a.close()  # idempotent
    b = connect("nahda")
    assert b.execute("SELECT current_setting('app.org_id', true) AS o").fetchone()["o"] == "nahda"
    assert b.execute("SELECT current_user AS u").fetchone()["u"] == dbx.APP_ROLE
    b.close()
    s = dbx.pool_stats()
    assert s["pool_size"] <= O.settings.pg_pool_max and s["requests_errors"] == 0


@pg_only
def test_integrity_migration_updated_at_and_no_ledger_delete(cl):
    import psycopg
    c = connect("jadwa")
    c.execute("INSERT OR REPLACE INTO settings VALUES(?, ?)", ("u4:probe", "1"))
    c.commit()
    c.execute("UPDATE settings SET v='2' WHERE k='u4:probe'")
    c.commit()
    assert c.execute("SELECT updated_at FROM settings WHERE k='u4:probe'").fetchone()["updated_at"] is not None
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("DELETE FROM payments WHERE id=-1")
    c.rollback()
    c.close()
    tok = TENANT.set("jadwa")
    TENANT.reset(tok)


# ---------------------------------------------------------------- dashboard cache (Unit 4, acceptance 15)
def test_dashboard_cache_shares_results_and_invalidates_on_writes(cl):
    from backend import cache
    cache.clear()
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"n": calls["n"]}

    t = TENANT.get()
    assert cache.get(t, "k", compute, ttl=30) == {"n": 1}
    assert cache.get(t, "k", compute, ttl=30) == {"n": 1}  # shared within the TTL
    assert cache.get("other-tenant", "k", compute, ttl=30) == {"n": 2}  # never across tenants
    cache.bump(t)
    assert cache.get(t, "k", compute, ttl=30) == {"n": 3}  # a write of the tenant invalidates
    assert cache.get(t, "k", compute, ttl=0) == {"n": 4}  # ttl 0 = off (what the API tests run with)
    # through the API: a mutating request bumps the tenant's generation
    g = cache.generation(t)
    cl.post("/api/notifications/run")
    assert cache.generation(t) == g + 1
