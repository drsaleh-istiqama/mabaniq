"""0.13.0 — profile-driven developer organisations: `MABANIQ_TENANTS` adds a tenant by configuration, the seed builds it from
`backend/tenant_profiles.py` (real project codes, unit mix, letterhead, bundled sample renders/plans with unit markers), the
assets self-heal after an ephemeral container loses its files, and the ledgers stay consistent (payments == paid installments)."""
import hashlib
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "tp.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "almukhatat:المخطط العقارية;bayan:بيان عمان;almaqsura:المقصورة العقارية;view:رؤية العقارية"

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
    assert TP.tenants_from_env() == {T: "المخطط العقارية", "bayan": "بيان عمان", "almaqsura": "المقصورة العقارية", "view": "رؤية العقارية"}
    assert ts["bayan"] == "بيان عمان" and ts["almaqsura"] == "المقصورة العقارية" and ts["view"] == "رؤية العقارية"


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
        d.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username IN ('dawood','mk-sales','mk-finance','mk-engineer','mk-client'))")  # PG: FK from sessions
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
        d.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username IN ('dawood','mk-client'))")  # PG: FK from sessions
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


# ───────────────────────────────────────────────────────────────── 0.15.0 — بيان عمان (second profile: commercial, sold + leased)
B = "bayan"


def test_every_profile_is_internally_consistent():
    """Generic guard over PROFILES: real codes (no RAY/SEB/KHD leak), every asset file exists, markers point at seeded codes, lease units exist."""
    for code, p in TP.PROFILES.items():
        codes = {c for _s, c, *_ in p["projects"]}
        assert not {"RAY", "SEB", "KHD"} & codes, code
        units = {u[1] for u in TP.profile_units(p)}
        assert units, code
        for entry in p["assets"]:
            assert (TP.ASSETS / entry[0]).exists(), entry[0]
        for rel, marks in p.get("markers", {}).items():
            assert any(a[0] == rel for a in p["assets"]), rel
            assert all(u in units for u, _x, _y in marks), rel
        assert TP.lease_units(p) <= units, code
        assert sum((TP.ASSETS / e[0]).stat().st_size for e in p["assets"]) <= 3_200_000, code  # bundled samples stay small


def test_bayan_projects_units_leases_and_brand(cl):
    login_as(cl, "admin", B)
    ps = {p["code"]: p for p in cl.get("/api/projects").json()}
    for code in ("MSK", "ALA", "MQR", "SHB", "AMR", "QRM"):
        assert code in ps, code
    assert not {"RAY", "SEB", "KHD", "MAB"} & set(ps)
    assert ps["MSK"]["name"] == "مساحات الخوض" and ps["AMR"]["name"].startswith("بوابة المعبيلة") and ps["QRM"]["name"].startswith("ساحة الخوير")
    msk = cl.get("/api/units", params={"project_id": ps["MSK"]["id"]}).json()
    assert len(msk) == 43 and sum("محل" in u["type"] for u in msk) == 20 and sum("مكتب" in u["type"] for u in msk) == 23
    assert all(u["use"] == "commercial" for u in msk)
    ala = cl.get("/api/units", params={"project_id": ps["ALA"]["id"]}).json()
    assert len(ala) == 94 and all(u["code"].startswith("ALA-A-") for u in ala)
    shb = cl.get("/api/units", params={"project_id": ps["SHB"]["id"]}).json()
    assert sum("محل" in u["type"] for u in shb) == 10 and sum("مكتب" in u["type"] for u in shb) == 32
    assert len(cl.get("/api/units", params={"project_id": ps["MQR"]["id"]}).json()) == 30
    b = cl.get("/api/admin/brand").json()
    assert b["name"].startswith("بيان عمان") and b["phone"] == "72228000" and b["logo_doc"]
    # leasing portfolio from the profile: retained units are never sold, five leases, one in arrears, one renewing soon
    L = cl.get("/api/leasing").json()
    retained = {u["code"] for u in L["units"]}
    assert TP.lease_units(TP.profile(B)) <= retained  # plus the completed project's own retained units (cycle seed)
    by_unit = {x["unit"]: x for x in L["leases"]}
    assert {"MSK-M-001", "MSK-M-005", "MSK-M-103", "MSK-M-108", "MSK-M-205"} <= set(by_unit) and "MSK-M-012" not in by_unit
    assert by_unit["MSK-M-005"]["arrears"] > 0 and by_unit["MSK-M-001"]["arrears"] == 0
    assert by_unit["MSK-M-108"]["renewal_alert"] and L["annual_rent"] >= 6800 + 8400 + 6500 + 6300 + 5500
    assert by_unit["MSK-M-108"]["frequency"] == 12 and len(by_unit["MSK-M-108"]["dues"]) == 12
    assert all(u["status"] == "a" for u in msk if u["code"] in retained)


def test_bayan_assets_plans_markers_and_cycle_projects(cl):
    login_as(cl, "admin", B)
    ps = {p["code"]: p for p in cl.get("/api/projects").json()}
    plans = cl.get("/api/plans", params={"project_id": ps["MSK"]["id"]}).json()
    assert {"site", "floor", "render"} <= {p["kind"] for p in plans} and len(plans) >= 12
    gf = next(p for p in plans if p["kind"] == "floor" and p["floor"] == 0)
    assert {m["unit_code"] for m in gf["markers"]} == {f"MSK-M-0{i:02d}" for i in range(1, 21)}
    assert cl.get(f"/api/documents/{gf['document_id']}").status_code == 200
    assert len(cl.get("/api/plans", params={"project_id": ps["ALA"]["id"]}).json()) >= 7
    assert any(p["kind"] == "unit" for p in cl.get("/api/plans", params={"project_id": ps["SHB"]["id"]}).json())
    # the cycle seed's completed project carries the profile's photo too (0.15.0: AMR/QRM resolved in ensure_assets)
    assert cl.get("/api/plans", params={"project_id": ps["QRM"]["id"]}).json()
    tok = TENANT.set(B)
    try:
        c = connect()
        gap = c.execute("SELECT COALESCE(SUM(paid_amount),0) - (SELECT COALESCE(SUM(amount),0) FROM payments) FROM installments").fetchone()[0]
        assert abs(gap) < 0.01
        assert TP.ensure_assets(c, B) == 0  # idempotent after the seed
        c.close()
    finally:
        TENANT.reset(tok)
    # the first profile is untouched by the second
    login_as(cl, "admin", T)
    codes = {p["code"] for p in cl.get("/api/projects").json()}
    assert "MAB" in codes and "MSK" not in codes


M = "almaqsura"


def test_almaqsura_is_real_data_only(cl):
    """0.18.1 — the tenant holds only documented data: building 534 (42 units, August-2026 report), the purchased units workbook (29 units,
    8 leased), nine Souq Al Sad shops, one Azaiba plot (land sector); no demo buyers, leads or invented projects; unknowns stay NULL."""
    login_as(cl, "admin", M)
    ps = {p["code"]: p for p in cl.get("/api/projects").json()}
    assert set(ps) == {"IST", "MQT", "SAD", "AZB"}, set(ps)
    assert ps["AZB"]["kind"] == "land" and ps["IST"]["completed"]
    ist = {u["code"]: u for u in cl.get("/api/units", params={"project_id": ps["IST"]["id"]}).json()}
    assert len(ist) == 42 and sum("شقة" == u["type"] for u in ist.values()) == 30 and sum("محل" in u["type"] for u in ist.values()) == 7
    assert all(u["retained"] == 1 and u["status"] == "a" and u["price"] is None for u in ist.values())
    mqt = {u["code"]: u for u in cl.get("/api/units", params={"project_id": ps["MQT"]["id"]}).json()}
    assert len(mqt) == 29 and mqt["MQT-T1-703"]["area"] == 55 and mqt["MQT-T2-330"]["area"] == 205
    assert len(cl.get("/api/units", params={"project_id": ps["SAD"]["id"]}).json()) == 9
    azb = cl.get("/api/units", params={"project_id": ps["AZB"]["id"]}).json()
    assert len(azb) == 1 and azb[0]["use"] == "land" and azb[0]["price"] is None and azb[0]["retained"] == 0
    # leasing: 40 leases in building 534 (incl. two reserved shops and the association's storage) + 8 in the towers; August arrears as reported
    L = cl.get("/api/leasing").json()
    by_unit = {x["unit"]: x for x in L["leases"]}
    assert sum(k.startswith("IST-") for k in by_unit) == 40 and sum(k.startswith("MQT-") for k in by_unit) == 8
    assert by_unit["IST-A-M5"]["arrears"] == 330 * 9 and by_unit["IST-A-12"]["arrears"] == 750 and by_unit["IST-A-42"]["arrears"] == 520
    assert by_unit["IST-A-32"]["arrears"] == 260 and by_unit["IST-A-13"]["arrears"] == 0 and by_unit["IST-A-63"]["arrears"] == 0
    assert by_unit["IST-A-SW"]["arrears"] == 0 and by_unit["MQT-T1-707"]["arrears"] == 0  # undocumented months are not shown as arrears
    assert "IST-A-S2" not in by_unit and "IST-A-BA" not in by_unit and "MQT-T1-701" not in by_unit  # vacant / not leased
    assert L["annual_rent"] >= (8760 - 0) * 12 * 0.9  # the report's monthly total ≈ 8,760 OMR (two shops reserved, storage unpaid)
    # nothing demo-generated
    tok = TENANT.set(M)
    try:
        c = connect()
        for t in ("bookings", "customers", "leads", "contractors", "ipcs", "cost_schedule", "permits"):
            assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t
        assert c.execute("SELECT COUNT(*) FROM rent_dues WHERE paid>0").fetchone()[0] == 33  # 25 flats + 2 offices + 4 shops in August, + unit 63 (July + August)
        assert TP.ensure_assets(c, M) == 0
        c.close()
    finally:
        TENANT.reset(tok)
    b = cl.get("/api/admin/brand").json()
    assert b["name"].startswith("المقصورة العقارية") and b["logo_doc"]
    # a quote or booking on a unit without a price is refused clearly (not a 500)
    r = cl.post("/api/quotes", json={"unit_code": "AZB-L-01", "customer_name": "عميل", "phone": "+968 90000000", "plan": "milestone"})
    assert r.status_code == 400 and "سعر" in r.text
    # reports and dashboards render on a real-data tenant
    assert cl.get("/api/reports/ready/portfolio").status_code == 200
    assert cl.get("/api/decisions").status_code == 200 and cl.get("/api/marketing/board").status_code == 200
    for other, must in ((T, "MAB"), (B, "MSK")):
        login_as(cl, "admin", other)
        assert must in {p["code"] for p in cl.get("/api/projects").json()}


def test_unit_card_handles_null_price_and_shows_lease(cl):
    """0.18.2 — real-data units carry no price: the card must not 500 (pricing suggestion skipped, no price/m²), and retained units
    expose their active lease (tenant, rent, term, arrears) so the inventory map tells the leasing story too."""
    login_as(cl, "admin", M)
    sw = cl.get("/api/units/IST-A-SW")
    assert sw.status_code == 200, sw.text
    sw = sw.json()
    assert sw["price"] is None and sw["suggestion"] is None and sw["retained"] == 1
    assert sw["lease"] and "محل W" in sw["lease"]["tenant"] and sw["lease"]["annual_rent"] == 400 * 12 and sw["lease"]["arrears"] == 0
    m5 = cl.get("/api/units/IST-A-M5").json()
    assert m5["lease"]["arrears"] == 330 * 9 and m5["lease"]["next_due"] is not None
    vacant = cl.get("/api/units/IST-A-S2").json()
    assert vacant["retained"] == 1 and vacant["lease"] is None
    land = cl.get("/api/units/AZB-L-01")
    assert land.status_code == 200 and land.json()["suggestion"] is None and "lease" not in land.json()
    assert cl.get(f"/api/pricing/{land.json()['project_id']}").status_code == 200


# ───────────────────────────────────────────────────────────────── 0.19.0 — رؤية العقارية (off-plan developer, published data only)
V = "view"


def test_view_is_off_plan_published_data_only(cl):
    """0.19.0 — six projects from viewom.com: 265 units, the published unit mix, construction % ("status") and sold % applied to the unit
    count; nothing the site does not publish exists (no price, area, floor, buyer, booking, contractor); unit codes are placeholders."""
    login_as(cl, "admin", V)
    ps = {p["code"]: p for p in cl.get("/api/projects").json()}
    assert set(ps) == {"BRK", "SLH", "KYN", "VHT", "VBZ", "VGD"}, set(ps)
    assert {k: p["total_units"] for k, p in ps.items()} == {"BRK": 53, "SLH": 38, "KYN": 38, "VHT": 46, "VBZ": 34, "VGD": 56}
    assert {k: p["build_pct"] for k, p in ps.items()} == {"BRK": 100, "SLH": 40, "KYN": 40, "VHT": 10, "VBZ": 95, "VGD": 70}
    assert ps["BRK"]["completed"] and not ps["VHT"]["completed"]
    assert {k: p["sold_pct"] for k, p in ps.items()} == {"BRK": 100, "SLH": 76, "KYN": 76, "VHT": 20, "VBZ": 74, "VGD": 98}  # published 100/76/76/20/75/99, whole units
    from collections import Counter
    for code, mix in (("SLH", {"شقة": 24, "محل تجاري": 13}), ("VHT", {"مكتب": 45, "صالة عرض": 1}), ("BRK", {"مكتب": 45, "محل تجاري": 8}), ("VGD", {"شقة": 45, "محل تجاري": 11})):
        us = cl.get("/api/units", params={"project_id": ps[code]["id"]}).json()
        got = Counter(u["type"] for u in us if "غير مزوَّد" not in u["type"])
        assert dict(got) == mix, (code, got)
        assert all(u["price"] is None and u["area"] is None and u["floor"] is None and u["retained"] == 0 for u in us)
    unknown = [u for p in ps.values() for u in cl.get("/api/units", params={"project_id": p["id"]}).json() if "غير مزوَّد" in u["type"]]
    assert len(unknown) == 3 and all(u["status"] == "a" for u in unknown)  # SLH, KYN, VBZ: one unit each whose type the site does not state
    tok = TENANT.set(V)
    try:
        c = connect()
        for t in ("bookings", "customers", "leads", "contractors", "ipcs", "cost_schedule", "permits", "installments", "sale_contracts", "leases"):
            assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t
        assert TP.ensure_assets(c, V) == 0
        c.close()
    finally:
        TENANT.reset(tok)
    b = cl.get("/api/admin/brand").json()
    assert b["name"].startswith("رؤية للتطوير العقاري") and b["logo_doc"] and b["phone"] == "+968 9756 6600"
    # no price ⟵ a clear refusal, not a 500; the assistant answers an availability question on a portfolio without prices
    r = cl.post("/api/quotes", json={"unit_code": "VHT-O-20", "customer_name": "عميل", "phone": "+968 90000000", "plan": "milestone"})
    assert r.status_code == 400 and "سعر" in r.text
    # priced but the project has no published handover date ⟵ also a clear refusal (0.19.1), never a 500
    tok = TENANT.set(V)
    try:
        d = connect()
        d.execute("UPDATE units SET price=50000 WHERE code='VHT-O-20'")
        d.commit()
        r = cl.post("/api/quotes", json={"unit_code": "VHT-O-20", "customer_name": "عميل", "phone": "+968 90000000", "plan": "milestone"})
        assert r.status_code == 400 and "تسليم" in r.text, r.text
        r = cl.post("/api/bookings", json={"unit_code": "VHT-O-20", "customer_name": "عميل", "phone": "+968 90000000", "plan": "milestone"})
        assert r.status_code == 400 and "تسليم" in r.text, r.text
        d.execute("UPDATE units SET price=NULL, status='a' WHERE code='VHT-O-20'")
        d.commit()
        d.close()
    finally:
        TENANT.reset(tok)
    a = cl.post("/api/assistant", json={"q": "كم وحدة متاحة؟"})
    assert a.status_code == 200 and "غير مزوَّد" in a.json()["answer"] and "65" in a.json()["answer"], a.text
    assert cl.get("/api/units/VHT-O-20").json()["status"] == "a" and cl.get("/api/units/VHT-O-01").json()["status"] == "s"
    for path in ("/api/kpis", "/api/leasing", "/api/marketing/board", "/api/reports/ready/portfolio", "/api/reports/ready/inventory", "/api/ipcs", "/api/cash"):
        assert cl.get(path).status_code == 200, path
    login_as(cl, "admin", T)
    assert "MAB" in {p["code"] for p in cl.get("/api/projects").json()}
