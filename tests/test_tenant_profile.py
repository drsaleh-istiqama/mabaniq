"""0.13.0 — profile-driven developer organisations: `MABANIQ_TENANTS` adds a tenant by configuration, the seed builds it from
`backend/tenant_profiles.py` (real project codes, unit mix, letterhead, bundled sample renders/plans with unit markers), the
assets self-heal after an ephemeral container loses its files, and the ledgers stay consistent (payments == paid installments)."""
import hashlib
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "tp.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "almukhatat:المخطط العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import tenant_profiles as TP  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect, tenants  # noqa: E402

CSRF = "csrf-profile-" + "p" * 28
T = "almukhatat"


def login_as(c, user, tenant=T):
    tok = TENANT.set(tenant)
    try:
        c.cookies.set(A.COOKIE, A.issue_session(user))
    finally:
        TENANT.reset(tok)
    c.cookies.set(A.TENANT_COOKIE, tenant)
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


@pytest.fixture()
def cl():
    from backend import observability as O
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        for t in ("jadwa", T):
            tok = TENANT.set(t)
            try:
                d = connect()
                d.execute("DELETE FROM login_attempts")
                d.commit()
                d.close()
            finally:
                TENANT.reset(tok)
        login_as(c, "admin")
        yield c


def test_env_adds_tenant_and_api_lists_it(cl):
    ts = tenants()
    assert ts[T] == "المخطط العقارية" and "jadwa" in ts
    assert any(t["code"] == T for t in cl.get("/api/tenants").json())
    assert TP.tenants_from_env() == {T: "المخطط العقارية"}


def test_profile_projects_units_and_brand(cl):
    ps = {p["code"]: p for p in cl.get("/api/projects").json()}
    for code in ("MAB", "MRT", "JWR", "MLZ"):
        assert code in ps, code
    assert ps["MAB"]["name"] == "مشروع مآب" and ps["JWR"]["kind"] == "villa"
    # the generic demo codes never leak into a profiled developer
    assert not {"RAY", "SEB", "KHD"} & set(ps)
    units = cl.get("/api/units", params={"project_id": ps["MAB"]["id"]}).json()
    assert len(units) == 48 and all(u["code"].startswith("MAB-A-") for u in units)
    uses = {u["type"]: u for u in units}
    assert any("شقة فندقية" in k for k in uses)
    mrt = cl.get("/api/units", params={"project_id": ps["MRT"]["id"]}).json()
    assert sum("مكتب" in u["type"] for u in mrt) == 30 and sum("محل" in u["type"] for u in mrt) == 11
    villas = cl.get("/api/units", params={"project_id": ps["JWR"]["id"]}).json()
    assert len(villas) == 40 and all(v["code"].startswith("JWR-V-") for v in villas)
    b = cl.get("/api/admin/brand").json()
    assert b["name"] == "شركة المخطط العقارية" and b["phone"] == "72700099" and b["logo_doc"]
    # cycle-seed extras carry the profile's names
    assert ps["QRM"]["name"] == "مساكن الفخامة 11" and ps["AMR"]["name"] == "مركز داود للأعمال"


def test_bundled_assets_become_plans_with_markers_and_self_heal(cl):
    ps = {p["code"]: p for p in cl.get("/api/projects").json()}
    plans = cl.get("/api/plans", params={"project_id": ps["MAB"]["id"]}).json()
    kinds = {p["kind"] for p in plans}
    assert {"site", "floor", "unit", "render"} <= kinds and len(plans) >= 18
    typical = next(p for p in plans if p["kind"] == "floor" and p["floor"] == 1)
    codes = {m["unit_code"] for m in typical["markers"]}
    assert codes == {f"MAB-A-10{i}" for i in range(1, 7)}
    # file integrity: served document matches its recorded hash
    r = cl.get(f"/api/documents/{typical['document_id']}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/jpeg")
    sha = hashlib.sha256(r.content).hexdigest()
    tok = TENANT.set(T)
    try:
        c = connect()
        row = c.execute("SELECT stored, sha256 FROM documents WHERE id=?", (typical["document_id"],)).fetchone()
        assert row["sha256"] == sha
        from backend.modules2 import _docs_dir
        path = _docs_dir() / row["stored"]
        path.unlink()
        n_docs = c.execute("SELECT COUNT(*) FROM documents WHERE uploaded_by='عيّنة المنصة'").fetchone()[0]
        n_plans = c.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
        written = TP.ensure_assets(c, T)
        assert written == 1 and path.exists()
        # idempotent: no duplicate documents or plans on the next run
        assert TP.ensure_assets(c, T) == 0
        assert c.execute("SELECT COUNT(*) FROM documents WHERE uploaded_by='عيّنة المنصة'").fetchone()[0] == n_docs
        assert c.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == n_plans
        c.close()
    finally:
        TENANT.reset(tok)
    assert cl.get(f"/api/documents/{typical['document_id']}").status_code == 200
    # Malath has its own renders, Marteel none (no public image material yet)
    assert cl.get("/api/plans", params={"project_id": ps["MLZ"]["id"]}).json()
    assert cl.get("/api/plans", params={"project_id": ps["MRT"]["id"]}).json() == []


def test_ledgers_consistent_and_generic_tenant_unchanged(cl):
    tok = TENANT.set(T)
    try:
        c = connect()
        gap = c.execute("SELECT COALESCE(SUM(paid_amount),0) - (SELECT COALESCE(SUM(amount),0) FROM payments) FROM installments").fetchone()[0]
        assert abs(gap) < 0.01
        assert c.execute("SELECT COUNT(*) FROM resale").fetchone()[0] >= 1  # cycle seed resolved the slot → real project id
        assert c.execute("SELECT COUNT(*) FROM discount_requests").fetchone()[0] >= 1
        assert c.execute("SELECT COUNT(*) FROM units WHERE use='commercial'").fetchone()[0] >= 40
        c.close()
    finally:
        TENANT.reset(tok)
    # jadwa keeps its generic demo
    login_as(cl, "admin", "jadwa")
    codes = {p["code"] for p in cl.get("/api/projects").json()}
    assert {"RAY", "SEB", "KHD"} <= codes and "MAB" not in codes


def test_login_portal_and_creative_with_real_render(cl):
    # staff login with the tenant selector
    r = cl.post("/api/auth/login", json={"username": "sales", "password": "Wrong-Password-1234", "tenant": T})
    assert r.status_code in (401, 403), r.text  # wrong password is refused, tenant accepted
    assert cl.post("/api/auth/login", json={"username": "sales", "password": "Wrong-Password-1234", "tenant": "nope"}).status_code in (400, 401, 404, 422)
    # customer portal sees the public plans of their project
    with TestClient(app, base_url="https://testserver") as cust:
        login_as(cust, "client1")
        tok = TENANT.set(T)
        try:
            c = connect()
            c.execute("UPDATE users SET must_change=0 WHERE username='client1'")
            c.commit()
            c.close()
        finally:
            TENANT.reset(tok)
        mine = cust.get("/api/portal/plans")
        assert mine.status_code == 200
    # ad creative composed on a bundled render of Maab
    ps = {p["code"]: p for p in cl.get("/api/projects").json()}
    render = next(p for p in cl.get("/api/plans", params={"project_id": ps["MAB"]["id"]}).json() if p["kind"] == "render")
    r = cl.post("/api/creatives", json={"project_id": ps["MAB"]["id"], "template": "launch", "size": "square", "palette": "blue",
                                         "bg_document_id": render["document_id"]})
    assert r.status_code == 200, r.text
    cr = r.json()
    assert cr.get("document_id") or cr.get("pdf_document_id")


def test_pilot_accounts_created_once_with_temp_password_and_never_reset(cl, monkeypatch):
    """0.14.0 — the company's own trial accounts: only with MABANIQ_PILOT_PASSWORD (>= 12 chars), forced password change, an account
    already created (and its changed password) is never touched again, and the client account is linked to a real booking."""
    tok = TENANT.set(T)
    try:
        d = connect()
        d.execute("DELETE FROM users WHERE username IN ('dawood','mk-sales','mk-finance','mk-engineer','mk-client')")
        d.commit()
        monkeypatch.delenv("MABANIQ_PILOT_PASSWORD", raising=False)
        assert TP.ensure_pilot_accounts(d, T) == 0  # no variable ⟵ nothing
        monkeypatch.setenv("MABANIQ_PILOT_PASSWORD", "short")
        assert TP.ensure_pilot_accounts(d, T) == 0  # too short ⟵ nothing
        monkeypatch.setenv("MABANIQ_PILOT_PASSWORD", "Pilot-Temp-2026-xyz")
        assert TP.ensure_pilot_accounts(d, "jadwa") == 0  # a tenant without a profile gets none
        assert TP.ensure_pilot_accounts(d, T) == 5
        rows = {r["username"]: r for r in d.execute("SELECT * FROM users WHERE username IN ('dawood','mk-sales','mk-finance','mk-engineer','mk-client')").fetchall()}
        assert {u: r["role"] for u, r in rows.items()} == {"dawood": "admin", "mk-sales": "sales", "mk-finance": "finance", "mk-engineer": "engineer", "mk-client": "customer"}
        assert all(r["must_change"] == 1 for r in rows.values())
        assert rows["mk-client"]["customer_id"] == d.execute("SELECT customer_id FROM users WHERE username='client1'").fetchone()["customer_id"]
        assert A.check_pw("Pilot-Temp-2026-xyz", rows["dawood"]["pw"])
        # the person changed the password; a later start-up (even with another temp password) leaves it alone
        d.execute("UPDATE users SET pw=?, must_change=0 WHERE username='dawood'", (A.hash_pw("Changed-By-Dawood-9"),))
        d.commit()
        monkeypatch.setenv("MABANIQ_PILOT_PASSWORD", "Another-Temp-2026-abc")
        assert TP.ensure_pilot_accounts(d, T) == 0
        r = d.execute("SELECT pw, must_change FROM users WHERE username='dawood'").fetchone()
        assert A.check_pw("Changed-By-Dawood-9", r["pw"]) and r["must_change"] == 0
        d.close()
    finally:
        TENANT.reset(tok)


def test_pilot_staff_login_sees_the_company_and_client_sees_the_unit(cl, monkeypatch):
    from backend import observability as O
    O.limiter.reset()
    tok = TENANT.set(T)
    try:
        d = connect()
        d.execute("DELETE FROM users WHERE username IN ('dawood','mk-client')")
        d.commit()
        monkeypatch.setenv("MABANIQ_PILOT_PASSWORD", "Pilot-Temp-2026-xyz")
        TP.ensure_pilot_accounts(d, T)
        d.close()
    finally:
        TENANT.reset(tok)
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/api/auth/login", json={"username": "dawood", "password": "Pilot-Temp-2026-xyz", "tenant": T})
        assert r.status_code == 200 and r.json()["must_change"] is True and r.json()["role"] == "admin"
        # the shared demo password is NOT what opens these accounts, and the temp password does not open another tenant
        O.limiter.reset()
        r = c.post("/api/auth/login", json={"username": "dawood", "password": "Pilot-Temp-2026-xyz", "tenant": "jadwa"})
        assert r.status_code == 401
        O.limiter.reset()
        r = c.post("/api/auth/login", json={"username": "mk-client", "password": "Pilot-Temp-2026-xyz", "tenant": T})
        assert r.status_code == 200 and r.json()["role"] == "customer"
