"""Unit 2 — identity and sessions: graded lockout (M10), database-backed login budget, session inventory and revocation,
idle timeout, recovery codes, admin 2FA reset, token rotation on 2FA enable."""
import json
import os
import tempfile
import time

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "u2.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import observability as O  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import connect  # noqa: E402

CSRF = "csrf-unit2-" + "q" * 30


def creds():
    return json.loads(A.creds_file().read_text())


def login_client(user, password=None, otp=None):
    c = TestClient(app, base_url="https://testserver", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0"})
    c.__enter__()
    body = {"username": user, "password": password or creds()[user]}
    if otp:
        body["otp"] = otp
    r = c.post("/api/auth/login", json=body)
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies.get(A.CSRF_COOKIE)
    return c


@pytest.fixture(autouse=True)
def _fresh():
    O.limiter.reset()
    db = connect()
    db.execute("DELETE FROM auth_failures")
    db.execute("DELETE FROM login_attempts")
    db.commit()
    yield
    O.limiter.reset()


@pytest.fixture()
def boot():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------- M10: graded lockout instead of account lock
def test_graded_cooldown_never_locks_the_account_out(boot):
    with TestClient(app, base_url="https://testserver") as c:
        for _ in range(A.COOLDOWN_AFTER):
            assert c.post("/api/auth/login", json={"username": "engineer", "password": "wrong-pass-1"}).status_code == 401
        r = c.post("/api/auth/login", json={"username": "engineer", "password": "wrong-pass-1"})
        assert r.status_code == 429 and r.headers.get("x-lockout") == "graded" and int(r.headers["retry-after"]) >= 1
        time.sleep(float(r.headers["retry-after"]) + 0.2)
        ok = c.post("/api/auth/login", json={"username": "engineer", "password": creds()["engineer"]})
        assert ok.status_code == 200, "the legitimate owner can still sign in after the cooldown — no hard lock"


def test_login_budget_is_in_the_database(boot):
    users = ["admin", "sales", "finance", "engineer", "investor1", "client1", "client2", "client3", "client4", "broker1", "broker2"]
    limit = A.LOGIN_WINDOW[0]
    codes = []
    with TestClient(app, base_url="https://testserver") as c:
        for i, u in enumerate(users[: limit + 1]):
            O.limiter.reset()  # the in-memory bucket is reset on purpose: the database budget must hold on its own
            r = c.post("/api/auth/login", json={"username": u, "password": creds()[u]})
            codes.append((r.status_code, r.headers.get("x-ratelimit-bucket")))
    assert all(code == 200 for code, _ in codes[:limit])
    assert codes[limit] == (429, "login-db")
    db = connect()
    assert db.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] >= limit


# ---------------------------------------------------------------- sessions: inventory, revocation, idle timeout
def test_session_inventory_and_revoke_others(boot):
    a = login_client("sales")
    a.post("/api/me/sessions/revoke", json={"others": True})  # sessions left behind by earlier test files
    b = login_client("sales")
    inv = a.get("/api/me/sessions").json()
    assert inv["idle_minutes"] == A.IDLE_MINUTES and len(inv["sessions"]) == 2
    cur = [s for s in inv["sessions"] if s["current"]]
    assert len(cur) == 1 and cur[0]["label"].startswith("Chrome") and cur[0]["ip"]
    assert b.get("/api/me").status_code == 200
    assert a.post("/api/me/sessions/revoke", json={"others": True}).json()["revoked"] == 1
    assert b.get("/api/me").status_code == 401 and a.get("/api/me").status_code == 200
    # revoke by id (own current session) → signed out
    sid = a.get("/api/me/sessions").json()["sessions"][0]["id"]
    assert a.post("/api/me/sessions/revoke", json={"id": sid}).json()["revoked"] == 1
    assert a.get("/api/me").status_code == 401


def test_idle_timeout_ends_session_before_absolute_expiry(boot):
    a = login_client("finance")
    db = connect()
    th = __import__("hashlib").sha256(a.cookies.get(A.COOKIE).encode()).hexdigest()
    db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (time.time() - (A.IDLE_MINUTES * 60 + 5), th))
    db.commit()
    assert a.get("/api/me").status_code == 401
    assert db.execute("SELECT COUNT(*) FROM sessions WHERE token_hash=?", (th,)).fetchone()[0] == 0


def test_admin_revokes_all_sessions_of_a_user(boot):
    victim = login_client("engineer")
    admin = login_client("admin")
    uid = victim.get("/api/me").json()["id"]
    assert len(admin.get(f"/api/users/{uid}/sessions").json()) >= 1
    assert admin.post(f"/api/users/{uid}/sessions/revoke").json()["revoked"] >= 1
    assert victim.get("/api/me").status_code == 401
    assert any(a["action"] == "إنهاء كل جلسات مستخدم" for a in admin.get("/api/audit").json())


# ---------------------------------------------------------------- 2FA: recovery codes, rotation, admin reset
def test_recovery_codes_and_rotation_and_admin_reset(boot):
    a = login_client("investor1")
    other = login_client("investor1")
    sec = a.post("/api/auth/2fa/setup").json()["secret"]
    code = A.totp_at(sec, int(time.time() // 30))
    en = a.post("/api/auth/2fa/enable", json={"otp": code}).json()
    assert len(en["recovery_codes"]) == 8 and all(len(x) == 9 for x in en["recovery_codes"])
    assert other.get("/api/me").status_code == 401, "enabling 2FA rotates: other sessions are ended"
    assert a.get("/api/me").status_code == 200
    # login with a recovery code works once
    with TestClient(app, base_url="https://testserver") as c:
        pw = creds()["investor1"]
        assert c.post("/api/auth/login", json={"username": "investor1", "password": pw}).json()["detail"] == "OTP_REQUIRED"
        rc = en["recovery_codes"][0]
        assert c.post("/api/auth/login", json={"username": "investor1", "password": pw, "otp": rc}).status_code == 200
    with TestClient(app, base_url="https://testserver") as c:
        assert c.post("/api/auth/login", json={"username": "investor1", "password": pw, "otp": rc}).status_code == 401, "consumed"
        assert c.post("/api/auth/login", json={"username": "investor1", "password": pw, "otp": en["recovery_codes"][1]}).status_code == 200
    # admin reset clears 2FA + codes and ends sessions
    admin = login_client("admin")
    uid = a.get("/api/me").json()["id"]
    assert admin.post(f"/api/users/{uid}/2fa/reset").json()["ok"]
    assert a.get("/api/me").status_code == 401
    db = connect()
    row = db.execute("SELECT totp_enabled, totp_secret, recovery_codes FROM users WHERE id=?", (uid,)).fetchone()
    assert row["totp_enabled"] == 0 and row["totp_secret"] is None and row["recovery_codes"] is None
    with TestClient(app, base_url="https://testserver") as c:
        assert c.post("/api/auth/login", json={"username": "investor1", "password": pw}).status_code == 200
