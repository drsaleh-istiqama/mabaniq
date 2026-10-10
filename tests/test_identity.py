"""0.10.0 — external identity: sign-in by e-mail, recovery links, one-time e-mail sign-in links, Google OIDC (mocked exchange)."""
import dataclasses
import json
import os
import re
import tempfile
import time
from pathlib import Path

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "ident.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import identity as I  # noqa: E402
from backend import mail  # noqa: E402
from backend import observability as O  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import connect  # noqa: E402

CSRF = "csrf-ident-" + "z" * 30


def admin(c):
    c.cookies.set(A.COOKIE, A.issue_session("admin"))
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


def latest_mail() -> dict:
    files = sorted(mail.outbox_dir().glob("*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8"))


def outbox_count() -> int:
    return len(list(mail.outbox_dir().glob("*.json")))


@pytest.fixture(autouse=True)
def _clean():
    O.limiter.reset()
    db = A.conn()  # ensures the identity schema exists even before the first app start-up
    db.execute("DELETE FROM login_attempts")
    db.execute("DELETE FROM auth_failures")
    db.commit()
    yield
    O.limiter.reset()


@pytest.fixture()
def cl():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def set_email(cl, username, email):
    a = admin(TestClient(app, base_url="https://testserver"))
    with a:
        uid = next(u["id"] for u in a.get("/api/users").json() if u["username"] == username)
        r = a.post(f"/api/users/{uid}/email", json={"email": email})
        assert r.status_code == 200, r.text
    return uid


def test_methods_reflect_configuration(cl):
    m = cl.get("/api/auth/methods").json()
    assert m["password"] and m["email_login"] and m["forgot"] and m["email_link"] and m["mail_mode"] == "outbox"
    assert m["google"] is False  # no client id in tests


def test_login_with_email_instead_of_username(cl):
    set_email(cl, "engineer", "Eng@Example.om")
    pw = json.loads(A.creds_file().read_text())["engineer"]
    r = cl.post("/api/auth/login", json={"username": "eng@example.om", "password": pw})
    assert r.status_code == 200 and r.json()["username"] == "engineer"
    assert cl.get("/api/me/identity").json()["email"] == "eng@example.om"


def test_forgot_and_reset_flow(cl):
    set_email(cl, "sales", "sales@example.om")
    before = outbox_count()
    r = cl.post("/api/auth/password/forgot", json={"identifier": "sales", "tenant": "jadwa"})
    assert r.status_code == 200 and r.json()["sent"] and "demo_link" not in r.json()
    assert outbox_count() == before + 1
    m = latest_mail()
    assert m["to"] == "sales@example.om" and m["kind"] == "reset" and "/login?reset=" in m["link"]
    token = re.search(r"reset=([^&]+)", m["link"]).group(1)
    # an old session dies with the reset
    old = TestClient(app, base_url="https://testserver")
    old.cookies.set(A.COOKIE, A.issue_session("sales"))
    with old:
        assert old.get("/api/me").status_code == 200
        weak = cl.post("/api/auth/password/reset", json={"token": token, "new": "sales12345", "tenant": "jadwa"})
        assert weak.status_code == 400  # policy: resembles the username → token stays usable
        ok = cl.post("/api/auth/password/reset", json={"token": token, "new": "Nouvelle-Clef-2026!", "tenant": "jadwa"})
        assert ok.status_code == 200 and ok.json()["username"] == "sales"
        assert old.get("/api/me").status_code == 401
    # single use
    assert cl.post("/api/auth/password/reset", json={"token": token, "new": "Another-Clef-2026!", "tenant": "jadwa"}).status_code == 400
    r = cl.post("/api/auth/login", json={"username": "sales", "password": "Nouvelle-Clef-2026!"})
    assert r.status_code == 200
    db = connect()
    assert db.execute("SELECT COUNT(*) FROM audit WHERE action=?", ("تعيين كلمة مرور عبر رابط الاستعادة",)).fetchone()[0] >= 1
    # leave the demo account as the other test modules expect it (credentials file)
    db.execute("UPDATE users SET pw=? WHERE username='sales'", (A.hash_pw(json.loads(A.creds_file().read_text())["sales"]),))
    db.commit()


def test_forgot_is_enumeration_safe(cl):
    before = outbox_count()
    a = cl.post("/api/auth/password/forgot", json={"identifier": "nobody-here", "tenant": "jadwa"}).json()
    b = cl.post("/api/auth/password/forgot", json={"identifier": "finance", "tenant": "jadwa"}).json()  # exists, but no e-mail
    assert a == b and a["sent"] is True
    assert outbox_count() == before  # nothing sent, nothing leaked
    assert cl.post("/api/auth/password/forgot", json={"identifier": "xx", "tenant": "nopetenant"}).status_code == 404  # valid shape, unknown developer


def test_reset_token_expires(cl):
    set_email(cl, "engineer", "eng2@example.om")
    cl.post("/api/auth/password/forgot", json={"identifier": "eng2@example.om", "tenant": "jadwa"})
    token = re.search(r"reset=([^&]+)", latest_mail()["link"]).group(1)
    db = connect()
    db.execute("UPDATE auth_tokens SET expires=? WHERE kind='reset'", (time.time() - 1,))
    db.commit()
    assert cl.post("/api/auth/password/reset", json={"token": token, "new": "Expired-Clef-2026!", "tenant": "jadwa"}).status_code == 400


def test_email_link_signs_in_once(cl):
    set_email(cl, "engineer", "eng3@example.om")
    r = cl.post("/api/auth/email/request", json={"email": "eng3@example.om", "tenant": "jadwa"})
    assert r.status_code == 200
    link = latest_mail()["link"]
    assert "/auth/email/" in link
    path = link.split("https://testserver", 1)[1]
    with TestClient(app, base_url="https://testserver") as fresh:
        r = fresh.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/"
        assert A.COOKIE in r.cookies and A.CSRF_COOKIE in r.cookies
        assert fresh.get("/api/me").json()["username"] == "engineer"
        assert fresh.get("/api/me/identity").json()["email_verified"] is True
    with TestClient(app, base_url="https://testserver") as again:
        r = again.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login?err=link"  # consumed
    assert cl.post("/api/auth/email/request", json={"email": "not-an-email", "tenant": "jadwa"}).status_code == 400
    before = outbox_count()
    assert cl.post("/api/auth/email/request", json={"email": "unknown@example.om", "tenant": "jadwa"}).json()["sent"]
    assert outbox_count() == before


def test_email_link_refused_for_totp_accounts(cl):
    set_email(cl, "engineer", "eng4@example.om")
    db = connect()
    db.execute("UPDATE users SET totp_enabled=1, totp_secret='JBSWY3DPEHPK3PXP' WHERE username='engineer'")
    db.commit()
    try:
        before = outbox_count()
        cl.post("/api/auth/email/request", json={"email": "eng4@example.om", "tenant": "jadwa"})
        assert outbox_count() == before  # no link is even issued
    finally:
        db.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE username='engineer'")
        db.commit()


def test_identity_endpoints_and_admin_email_rules(cl):
    uid = set_email(cl, "engineer", "eng5@example.om")
    a = admin(TestClient(app, base_url="https://testserver"))
    with a:
        dup = a.post(f"/api/users/{uid + 1000}/email", json={"email": "x@y.om"})
        assert dup.status_code == 404
        sales_id = next(u["id"] for u in a.get("/api/users").json() if u["username"] == "sales")
        assert a.post(f"/api/users/{sales_id}/email", json={"email": "ENG5@example.om"}).status_code == 409  # taken
        assert a.post(f"/api/users/{sales_id}/email", json={"email": "bad"}).status_code == 400
        me = a.post("/api/me/email", json={"email": "admin@example.om"}).json()
        assert me["email"] == "admin@example.om" and me["email_verified"] is False
        users = {u["username"]: u for u in a.get("/api/users").json()}
        assert users["admin"]["email"] == "admin@example.om" and users["engineer"]["google_linked"] is False
    # anonymous cannot touch identity endpoints
    assert cl.get("/api/me/identity").status_code == 401
    assert cl.post("/api/me/email", json={"email": "a@b.om"}).status_code in (401, 403)


# ---------------------------------------------------------------- Google (exchange mocked; everything else real)
def _google_on(monkeypatch):
    s = dataclasses.replace(O.settings, google_client_id="cid.apps.googleusercontent.com", google_client_secret="s3cret")
    monkeypatch.setattr(I, "settings", s)
    monkeypatch.setattr(O, "settings", s)
    return s


def _start(cl, link=False):
    r = cl.get("/auth/google/start?t=jadwa" + ("&link=1" if link else ""), follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith(I.GOOGLE_AUTH)
    state = re.search(r"state=([^&]+)", loc).group(1)
    nonce = re.search(r"nonce=([^&]+)", loc).group(1)
    assert I.OAUTH_COOKIE in r.cookies
    return state, nonce


def test_google_hidden_when_unconfigured(cl):
    assert cl.get("/auth/google/start", follow_redirects=False).status_code == 404
    assert cl.get("/auth/google/callback?state=x&code=y", follow_redirects=False).headers["location"] == "/login?err=google"


def test_google_login_matches_existing_account_by_verified_email_then_by_sub(cl, monkeypatch):
    s = _google_on(monkeypatch)
    set_email(cl, "engineer", "eng.google@example.om")
    calls = []

    def fake_exchange(code, redirect_uri):
        calls.append((code, redirect_uri))
        return {"aud": s.google_client_id, "iss": "https://accounts.google.com", "exp": str(int(time.time()) + 300), "nonce": fake_exchange.nonce,
                "email": "Eng.Google@example.om", "email_verified": "true", "sub": "1122334455", "name": "Eng"}
    monkeypatch.setattr(I, "google_exchange", fake_exchange)

    state, nonce = _start(cl)
    fake_exchange.nonce = nonce
    r = cl.get(f"/auth/google/callback?state={state}&code=abc", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/", r.headers
    assert calls[0][1] == "https://testserver/auth/google/callback"
    assert cl.get("/api/me").json()["username"] == "engineer"
    ident = cl.get("/api/me/identity").json()
    assert ident["google_linked"] is True and ident["email_verified"] is True
    # second time: matched by sub even if the account e-mail changed
    db = connect()
    db.execute("UPDATE users SET email='other@example.om' WHERE username='engineer'")
    db.commit()
    with TestClient(app, base_url="https://testserver") as c2:
        state, nonce = _start(c2)
        fake_exchange.nonce = nonce
        r = c2.get(f"/auth/google/callback?state={state}&code=abc", follow_redirects=False)
        assert r.headers["location"] == "/" and c2.get("/api/me").json()["username"] == "engineer"
        assert c2.post("/api/me/google/unlink", headers={"X-CSRF-Token": c2.cookies.get(A.CSRF_COOKIE)}).json()["google_linked"] is False


def test_google_rejects_unknown_identity_wrong_browser_and_bad_claims(cl, monkeypatch):
    s = _google_on(monkeypatch)
    good = {"aud": s.google_client_id, "iss": "accounts.google.com", "exp": str(int(time.time()) + 300), "email": "stranger@example.om",
            "email_verified": "true", "sub": "99"}
    holder = {"info": dict(good)}
    monkeypatch.setattr(I, "google_exchange", lambda code, ru: holder["info"])
    # unknown e-mail: no account is created
    state, nonce = _start(cl)
    holder["info"]["nonce"] = nonce
    r = cl.get(f"/auth/google/callback?state={state}&code=abc", follow_redirects=False)
    assert r.headers["location"] == "/login?err=google-unknown"
    db = connect()
    assert db.execute("SELECT COUNT(*) FROM users WHERE email='stranger@example.om'").fetchone()[0] == 0
    # another browser (no binding cookie) cannot complete the state
    state, nonce = _start(cl)
    with TestClient(app, base_url="https://testserver") as other:
        assert other.get(f"/auth/google/callback?state={state}&code=abc", follow_redirects=False).headers["location"] == "/login?err=state"
    # wrong audience / nonce / unverified e-mail
    set_email(cl, "engineer", "eng.g2@example.om")
    for patch, err in (({"aud": "someone-else"}, "aud"), ({"nonce": "wrong"}, "nonce"), ({"email_verified": "false"}, "unverified")):
        state, nonce = _start(cl)
        holder["info"] = {**good, "nonce": nonce, "email": "eng.g2@example.om", **patch}
        r = cl.get(f"/auth/google/callback?state={state}&code=abc", follow_redirects=False)
        assert r.headers["location"] == f"/login?err={err}", (patch, r.headers["location"])
    assert cl.get("/api/me").status_code == 401


def test_google_link_from_signed_in_session(cl, monkeypatch):
    s = _google_on(monkeypatch)
    admin(cl)
    monkeypatch.setattr(I, "google_exchange", lambda code, ru: {"aud": s.google_client_id, "iss": "accounts.google.com", "exp": str(int(time.time()) + 60),
                                                                 "nonce": link_nonce["n"], "email": "ceo@example.om", "email_verified": "true", "sub": "777"})
    link_nonce = {}
    state, nonce = _start(cl, link=True)
    link_nonce["n"] = nonce
    r = cl.get(f"/auth/google/callback?state={state}&code=abc", follow_redirects=False)
    assert r.headers["location"] == "/#adm"
    ident = cl.get("/api/me/identity").json()
    assert ident["google_linked"] is True
    # unauthenticated link attempt is refused before Google is involved
    with TestClient(app, base_url="https://testserver") as anon:
        assert anon.get("/auth/google/start?t=jadwa&link=1", follow_redirects=False).headers["location"] == "/login?err=link-session"


def test_auth_tokens_are_retired_by_retention(cl):
    from backend import retention as R
    set_email(cl, "engineer", "eng6@example.om")
    cl.post("/api/auth/email/request", json={"email": "eng6@example.om", "tenant": "jadwa"})
    db = connect()
    db.execute("UPDATE auth_tokens SET expires=? WHERE kind='magic'", (time.time() - 30 * 86400,))
    db.commit()
    assert R.run(db)["counts"]["auth_tokens"] >= 1
    assert Path(mail.outbox_dir()).exists()
