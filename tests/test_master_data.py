"""0.31.0 — البيانات الأساسية من الواجهة (docs/DESIGN-master-data-forms.md): إنشاء وتعديل وإيقاف المشروع والمبنى والوحدة والعميل والأرض والترخيص والمقاول وعقد المقاول ومهمة الجدول.

لكل كيان: الإنشاء، التعديل الجزئي، الإيقاف والاستعادة، تكرار الرمز بالعربية، الصلاحية الناقصة، وسلامة الحجز والعقد والمستخلص. لا SQL خاص بمحرك إلا للتنظيف وما لا يصنعه الـAPI
(حجز معلّق، مستخلص معتمد)، فتعمل الاختبارات كما هي على SQLite وPostgreSQL. كل اختبار ينظّف ما أنشأه بالرمز الفريد.
"""
import contextlib
import os
import tempfile
import time

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "md.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "almukhatat:المخطط العقارية;bayan:بيان عمان;almaqsura:المقصورة العقارية;view:رؤية العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect, init  # noqa: E402

CSRF = "csrf-md-" + "m" * 30
_seq = [0]


def uniq(prefix="MD") -> str:
    _seq[0] += 1
    return f"{prefix}{int(time.time()) % 10**7}{_seq[0]}"


def login_as(c, user, tenant):
    tok = TENANT.set(tenant)
    try:
        c.cookies.set(A.COOKIE, A.issue_session(user))
    finally:
        TENANT.reset(tok)
    c.cookies.set(A.TENANT_COOKIE, tenant)
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


@contextlib.contextmanager
def _client(tenant, user="admin"):
    from backend import observability as O
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        yield login_as(c, user, tenant)


@pytest.fixture()
def jd():
    with _client("jadwa") as c:
        yield c


def _sql(sql, args=(), tenant="jadwa", maint=False):
    tok = TENANT.set(tenant)
    try:
        c = connect()
        try:
            pg = getattr(c, "dialect", "sqlite") == "postgres"
            if maint:
                c.maintenance()
            r = c.execute(sql, args)
            out = r.fetchall() if sql.lstrip().upper().startswith("SELECT") else None
            c.commit()
            if maint:
                c.end_maintenance()
                if not pg:
                    init(c)
            return out
        finally:
            c.close()
    finally:
        TENANT.reset(tok)


def last_audit(c) -> dict:
    r = c.get("/api/audit", params={"limit": 1}).json()
    return r[0] if r else {"id": 0, "action": "", "detail": ""}


def purge_project(code: str, tenant="jadwa") -> None:
    """Remove everything a test made under one project code (ledger tables need maintenance mode on PostgreSQL)."""
    ids = "(SELECT id FROM projects WHERE code=?)"
    uids = f"(SELECT id FROM units WHERE project_id IN {ids})"
    for sql in (f"DELETE FROM unit_price_changes WHERE unit_id IN {uids}",
                f"DELETE FROM installments WHERE booking_id IN (SELECT id FROM bookings WHERE unit_id IN {uids})",
                f"DELETE FROM bookings WHERE unit_id IN {uids}",
                f"DELETE FROM ipcs WHERE project_id IN {ids}",
                f"DELETE FROM contracts_c WHERE project_id IN {ids}",
                f"DELETE FROM schedule_tasks WHERE project_id IN {ids}",
                f"DELETE FROM permits WHERE project_id IN {ids}",
                f"DELETE FROM plans WHERE project_id IN {ids}",
                f"DELETE FROM units WHERE project_id IN {ids}",
                f"DELETE FROM buildings WHERE project_id IN {ids}",
                "DELETE FROM projects WHERE code=?"):
        n = sql.count("?")
        _sql(sql, (code,) * n, tenant, maint=True)


def new_project(c, **kw) -> tuple[int, str]:
    code = uniq()
    body = {"code": code, "name": "مشروع اختبار البيانات الأساسية", "kind": "tower", "handover": "2031-01-01"}
    body.update(kw)
    r = c.post("/api/projects", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"], r.json()["code"]


def new_unit(c, pid, code, **kw) -> int:
    body = {"project_id": pid, "code": code, "building": "ب1", "floor": 2, "pos": 1, "type": "غرفتان وصالة", "area": 90, "view": "بحر", "price": 100000}
    body.update(kw)
    r = c.post("/api/units", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def make_booking(uid: int, price=110000, status="pending") -> tuple[int, int]:
    """An active booking without the schedule (the API path is covered elsewhere); the unit becomes reserved like the real path does."""
    _sql("INSERT INTO customers(name, phone, created) VALUES(?,?,?)", ("عميل اختبار البيانات", "+968 9000 0000", "2026-11-03"))
    cid = _sql("SELECT id FROM customers WHERE name=? ORDER BY id DESC LIMIT 1", ("عميل اختبار البيانات",))[0]["id"]
    _sql("INSERT INTO bookings(unit_id, customer_id, plan, price, status, created, expires, list_price) VALUES(?,?,?,?,?,?,?,?)", (uid, cid, "6040", price, status, "2026-11-03", "2099-01-01", price))
    bid = _sql("SELECT id FROM bookings WHERE unit_id=? ORDER BY id DESC LIMIT 1", (uid,))[0]["id"]
    _sql("UPDATE units SET status='r' WHERE id=?", (uid,))
    return bid, cid


def drop_customer(cid: int) -> None:
    _sql("DELETE FROM customers WHERE id=?", (cid,), maint=True)


# ====================================================================================================== المشروع والمبنى
def test_project_is_created_edited_stopped_and_restored_and_its_code_stays_unique_and_fixed(jd):
    code = uniq()
    r = jd.post("/api/projects", json={"code": code.lower(), "name": "مشروع اختبار البيانات", "kind": "tower", "handover": "2031-01-01", "build_pct": 5})
    assert r.status_code == 200 and r.json()["code"] == code, r.text           # stored upper-case
    pid = r.json()["id"]
    try:
        dup = jd.post("/api/projects", json={"code": code, "name": "مكرر", "kind": "villa"})
        assert dup.status_code == 409 and code in dup.json()["detail"] and "مستخدم" in dup.json()["detail"]
        assert jd.post("/api/projects", json={"code": "!!", "name": "رمز غير صالح", "kind": "tower"}).status_code == 400
        assert jd.post("/api/projects", json={"code": uniq(), "name": "أرض غير موجودة", "kind": "tower", "land_id": 99999999}).status_code == 404
        assert any(p["id"] == pid for p in jd.get("/api/projects").json())
        r = jd.patch(f"/api/projects/{pid}", json={"location": "مسقط — العذيبة", "build_pct": 12.5})
        assert r.status_code == 200 and sorted(r.json()["changed"]) == ["build_pct", "location"], r.text
        assert [x["label"] for x in r.json()["changes"]] == ["الموقع", "نسبة الإنجاز ٪"] or sorted(x["label"] for x in r.json()["changes"]) == sorted(["الموقع", "نسبة الإنجاز ٪"])
        before = last_audit(jd)["id"]
        assert jd.patch(f"/api/projects/{pid}", json={"location": "مسقط — العذيبة", "build_pct": 12.5}).json()["changed"] == []
        assert last_audit(jd)["id"] == before
        assert jd.patch(f"/api/projects/{pid}", json={"code": "OTHER"}).status_code == 422                       # the code never changes
        for bad in ({"name": ""}, {"name": None}, {"kind": ""}, {"build_pct": None}):
            r = jd.patch(f"/api/projects/{pid}", json=bad)
            assert r.status_code == 400 and "إلزامي" in r.json()["detail"], (bad, r.text)
        assert jd.patch(f"/api/projects/{pid}", json={"kind": "castle"}).status_code == 400
        assert jd.patch(f"/api/projects/{pid}", json={"handover": None}).json()["changed"] == ["handover"]       # optional: cleared
        assert jd.patch(f"/api/projects/{pid}", json={"kind": "villa"}).json()["changed"] == ["kind"]             # no unit yet: the type may change
        new_unit(jd, pid, f"{code}-V1", building=None)
        r = jd.patch(f"/api/projects/{pid}", json={"kind": "tower"})
        assert r.status_code == 409 and "نوع المشروع" in r.json()["detail"]                                        # …but not after the first unit
        r = jd.post(f"/api/projects/{pid}/archive")
        assert r.status_code == 200 and r.json()["changed"] == ["active"]
        assert not any(p["id"] == pid for p in jd.get("/api/projects").json())                                      # hidden from the working list
        assert jd.post(f"/api/projects/{pid}/archive").json()["changed"] == []                                      # already stopped: nothing is written
        assert jd.post("/api/units", json={"project_id": pid, "code": f"{code}-V2"}).status_code == 409             # closed to new activity
        assert jd.post(f"/api/projects/{pid}/restore").json()["changed"] == ["active"]
        assert any(p["id"] == pid for p in jd.get("/api/projects").json())
        assert jd.post("/api/projects/99999999/archive").status_code == 404
    finally:
        purge_project(code)


def test_a_project_with_an_active_booking_a_live_lease_or_a_pending_certificate_cannot_be_stopped(jd):
    pid, code = new_project(jd)
    cid = bid = None
    try:
        uid = new_unit(jd, pid, f"{code}-A1")
        bid, cid = make_booking(uid)
        r = jd.post(f"/api/projects/{pid}/archive")
        assert r.status_code == 409 and "حجز نشط" in r.json()["detail"], r.text
        _sql("UPDATE bookings SET status='confirmed' WHERE id=?", (bid,))
        assert jd.post(f"/api/projects/{pid}/archive").status_code == 409                                           # confirmed and not yet handed over is still active
        _sql("UPDATE bookings SET handed_over='2026-11-03' WHERE id=?", (bid,))
        _sql("INSERT INTO ipcs(project_id, no, stage, claimed_pct, stage_value, status, created) VALUES(?,?,?,?,?,?,?)",
             ((_sql("SELECT id FROM projects WHERE code=?", (code,))[0]["id"]), 1, "أساسات", 10, 1000, "pending", "2026-11-03"))
        r = jd.post(f"/api/projects/{pid}/archive")
        assert r.status_code == 409 and "مستخلص معلّق" in r.json()["detail"], r.text
        _sql("UPDATE ipcs SET status='approved', approved_pct=10 WHERE project_id=?", (pid,))
        assert jd.post(f"/api/projects/{pid}/archive").status_code == 200                                           # delivered + certified: history, not activity
    finally:
        if cid:
            _sql("DELETE FROM installments WHERE booking_id=?", (bid,), maint=True)
            _sql("DELETE FROM bookings WHERE id=?", (bid,), maint=True)
            drop_customer(cid)
        purge_project(code)


def test_buildings_register_renames_with_their_units_and_refuses_to_stop_while_units_are_active(jd):
    pid, code = new_project(jd)
    try:
        r = jd.post(f"/api/projects/{pid}/buildings", json={"name": "ب1", "floors": 12})
        assert r.status_code == 200, r.text
        bid = r.json()["id"]
        dup = jd.post(f"/api/projects/{pid}/buildings", json={"name": "ب1"})
        assert dup.status_code == 409 and "ب1" in dup.json()["detail"]
        uid = new_unit(jd, pid, f"{code}-B1", building="ب1")
        new_unit(jd, pid, f"{code}-B2", building="ب2")                                                              # a unit in a new building creates its record
        names = {b["name"]: b for b in jd.get(f"/api/projects/{pid}/buildings").json()}
        assert set(names) == {"ب1", "ب2"} and names["ب1"]["units"] == 1 and names["ب1"]["floors"] == 12
        r = jd.patch(f"/api/buildings/{bid}", json={"name": "البرج الأول"})
        assert r.json()["changed"] == ["name"]
        assert next(u for u in jd.get(f"/api/units?project_id={pid}").json() if u["id"] == uid)["building"] == "البرج الأول"      # the rename carries its units
        assert jd.patch(f"/api/buildings/{bid}", json={"name": "ب2"}).status_code == 409
        assert jd.patch(f"/api/buildings/{bid}", json={"name": ""}).status_code == 400
        assert jd.patch(f"/api/buildings/{bid}", json={"floors": None, "notes": "ملاحظة"}).json()["changed"] == ["floors", "notes"]
        r = jd.post(f"/api/buildings/{bid}/archive")
        assert r.status_code == 409 and "وحدة فعّالة" in r.json()["detail"]
        assert jd.post(f"/api/units/{uid}/archive").status_code == 200
        assert jd.post(f"/api/buildings/{bid}/archive").json()["changed"] == ["active"]
        assert "البرج الأول" not in {b["name"] for b in jd.get(f"/api/projects/{pid}/buildings").json()}
        assert "البرج الأول" in {b["name"] for b in jd.get(f"/api/projects/{pid}/buildings", params={"archived": 1}).json()}
        assert jd.post(f"/api/buildings/{bid}/restore").json()["changed"] == ["active"]
    finally:
        purge_project(code)


# ====================================================================================================== الوحدة
def test_unit_status_is_not_editable_price_is_free_only_without_activity_and_a_documented_change_needs_a_reason(jd):
    pid, code = new_project(jd)
    cid = bid = None
    try:
        r = jd.post("/api/units", json={"project_id": pid, "code": f"{code}-A1".lower(), "building": "ب1", "floor": 2, "pos": 1, "type": "غرفتان", "area": 90, "view": "بحر", "price": 100000})
        assert r.status_code == 200 and r.json()["code"] == f"{code}-A1", r.text
        uid = r.json()["id"]
        row = next(u for u in jd.get(f"/api/units?project_id={pid}").json() if u["id"] == uid)
        assert row["status"] == "a" and row["use"] == "residential" and row["price"] == 100000
        dup = jd.post("/api/units", json={"project_id": pid, "code": f"{code}-A1"})
        assert dup.status_code == 409 and "مستخدم" in dup.json()["detail"]
        assert jd.post("/api/units", json={"project_id": pid, "code": "x"}).status_code == 422
        assert jd.post("/api/units", json={"project_id": pid, "code": f"{code}-Z", "status": "s"}).status_code == 422          # no status field on creation either
        r = jd.patch(f"/api/units/{uid}", json={"status": "s"})
        assert r.status_code == 400 and "الحجز" in r.json()["detail"], r.text                                              # the booking path owns the status
        assert jd.patch(f"/api/units/{uid}", json={"code": "OTHER-1"}).status_code == 422                                  # the code never changes
        r = jd.patch(f"/api/units/{uid}", json={"floor": None, "view": "", "type": "ثلاث غرف"})                            # optional unknowns clear
        assert sorted(r.json()["changed"]) == ["floor", "type", "view"], r.text
        row = next(u for u in jd.get(f"/api/units?project_id={pid}").json() if u["id"] == uid)
        assert row["floor"] is None and not row["view"] and row["type"] == "ثلاث غرف"
        assert jd.patch(f"/api/units/{uid}", json={"use": ""}).status_code == 400
        assert jd.patch(f"/api/units/{uid}", json={"use": "castle"}).status_code == 400
        assert jd.patch(f"/api/units/{uid}", json={"area": 0}).status_code == 422
        # free price while nothing is active on the unit — and it is on the ledger
        assert jd.patch(f"/api/units/{uid}", json={"price": 110000}).json()["changed"] == ["price"]
        hist = jd.get(f"/api/units/{uid}/price-changes").json()
        assert len(hist) == 1 and hist[0]["basis"] == "free" and hist[0]["old_price"] == 100000 and hist[0]["new_price"] == 110000
        bid, cid = make_booking(uid, price=110000)
        r = jd.patch(f"/api/units/{uid}", json={"price": 120000})
        assert r.status_code == 409 and "تغيير سعر موثَّق" in r.json()["detail"], r.text
        assert jd.patch(f"/api/units/{uid}", json={"view": "جبل"}).json()["changed"] == ["view"]                           # the rest of the card still edits
        with _client("jadwa", "sales") as s:                                                                                # no `decide` ⟵ no documented price change
            assert s.post(f"/api/units/{uid}/price", json={"price": 120000, "reason": "تعديل بقرار اللجنة"}).status_code == 403
        assert jd.post(f"/api/units/{uid}/price", json={"price": 120000, "reason": "ق"}).status_code == 422               # a reason is mandatory
        r = jd.post(f"/api/units/{uid}/price", json={"price": 120000, "reason": "تعديل بقرار لجنة التسعير"})
        assert r.status_code == 200 and r.json()["basis"] == "booking" and r.json()["changed"] == ["price"], r.text
        assert _sql("SELECT price FROM bookings WHERE id=?", (bid,))[0]["price"] == 110000                                # the contracted price is untouched
        assert next(u for u in jd.get(f"/api/units?project_id={pid}").json() if u["id"] == uid)["price"] == 120000
        assert jd.post(f"/api/units/{uid}/price", json={"price": 120000, "reason": "نفس السعر مرة أخرى"}).json()["changed"] == []
        hist = jd.get(f"/api/units/{uid}/price-changes").json()
        assert [h["basis"] for h in hist] == ["booking", "free"] and "لجنة التسعير" in hist[0]["reason"]
        assert "لجنة التسعير" in last_audit(jd)["detail"] and last_audit(jd)["action"] == "تغيير سعر موثَّق"
        # a reserved unit is not stopped
        r = jd.post(f"/api/units/{uid}/archive")
        assert r.status_code == 409 and "محجوزة" in r.json()["detail"]
        _sql("UPDATE bookings SET status='cancelled' WHERE id=?", (bid,))
        _sql("UPDATE units SET status='a' WHERE id=?", (uid,))
        assert jd.post(f"/api/units/{uid}/archive").json()["changed"] == ["active"]
        assert uid not in {u["id"] for u in jd.get(f"/api/units?project_id={pid}").json()}                                 # hidden from the inventory
        assert uid in {u["id"] for u in jd.get("/api/units", params={"project_id": pid, "archived": 1}).json()}
        assert jd.post(f"/api/units/{uid}/restore").json()["changed"] == ["active"]
    finally:
        if cid:
            _sql("DELETE FROM bookings WHERE id=?", (bid,), maint=True)
            drop_customer(cid)
        purge_project(code)


def test_an_archived_unit_or_project_takes_no_booking_quote_or_lease_and_does_not_count_as_available(jd):
    pid, code = new_project(jd)
    try:
        uid = new_unit(jd, pid, f"{code}-A1")
        k0 = jd.get("/api/kpis", params={"project_id": pid}).json()
        assert k0["total_units"] == 1 and k0["available"] == 1
        assert jd.post(f"/api/units/{uid}/archive").status_code == 200
        k1 = jd.get("/api/kpis", params={"project_id": pid}).json()
        assert k1["total_units"] == 0 and k1["available"] == 0                                                              # the stopped unit leaves the availability count
        r = jd.post("/api/bookings", json={"unit_code": f"{code}-A1", "customer_name": "عميل اختبار", "phone": "+968 9555 1234", "plan": "milestone"})
        assert r.status_code == 409 and "موقوفة" in r.json()["detail"], r.text
        assert jd.post(f"/api/units/{uid}/restore").status_code == 200
        assert jd.post(f"/api/projects/{pid}/archive").status_code == 200
        r = jd.post("/api/bookings", json={"unit_code": f"{code}-A1", "customer_name": "عميل اختبار", "phone": "+968 9555 1234", "plan": "milestone"})
        assert r.status_code == 409 and "موقوف" in r.json()["detail"], r.text
    finally:
        purge_project(code)


# ====================================================================================================== العميل
def test_customer_is_created_through_the_shared_path_identity_stays_encrypted_and_personal_data_stays_out_of_the_audit(jd):
    name = "عميل اختبار " + uniq("C")
    r = jd.post("/api/customers", json={"name": name, "phone": "+968 9123 4567", "email": "cust.md@example.test"})
    assert r.status_code == 200 and r.json()["kyc"] is None, r.text
    cid = r.json()["id"]
    cid2 = None
    try:
        a = last_audit(jd)
        assert a["action"] == "عميل جديد" and name not in a["detail"] and "9123" not in a["detail"] and "example.test" not in a["detail"]
        assert any(x["id"] == cid and x["name"] == name for x in jd.get("/api/customers", params={"q": name}).json())
        assert jd.post("/api/customers", json={"name": "ا"}).status_code == 422
        assert jd.post("/api/customers", json={"name": "عميل بهاتف خاطئ", "phone": "abc"}).status_code == 400
        assert jd.post("/api/customers", json={"name": "عميل ببريد خاطئ", "email": "bad"}).status_code == 400
        # identity block: goes through the existing KYC logic (screening, consent) and is sealed at rest
        kyc = {"id_type": "بطاقة مدنية", "id_number": "12345678", "nationality": "عُماني", "id_expiry": "2032-01-01", "source_of_funds": "راتب", "consent_signed": True}
        r2 = jd.post("/api/customers", json={"name": name + " (هوية)", "phone": "+968 9000 1111", "kyc": kyc})
        assert r2.status_code == 200 and r2.json()["kyc"]["status"] in ("verified", "review"), r2.text
        cid2 = r2.json()["id"]
        raw = _sql("SELECT id_number, consent_at FROM customers WHERE id=?", (cid2,))[0]
        assert str(raw["id_number"]).startswith("enc:v1:") and raw["consent_at"]
        assert "12345678" not in last_audit(jd)["detail"]
        with _client("jadwa", "engineer") as eng:
            assert eng.post("/api/customers", json={"name": "ممنوع من المهندس"}).status_code == 403
        with _client("jadwa", "sales") as sal:
            assert sal.post("/api/customers", json={"name": "عميل المبيعات " + uniq("S")}).status_code == 200
        # edit: only contact data (identity has its own screen); personal values never echoed
        r = jd.patch(f"/api/customers/{cid}", json={"phone": "+968 9222 3333"})
        assert r.json()["changed"] == ["phone"] and r.json()["changes"][0].get("personal") is True and "old" not in r.json()["changes"][0]
        assert "9222" not in last_audit(jd)["detail"] and "9123" not in last_audit(jd)["detail"]
        before = last_audit(jd)["id"]
        assert jd.patch(f"/api/customers/{cid}", json={"name": name, "email": "cust.md@example.test"}).json()["changed"] == []
        assert last_audit(jd)["id"] == before
        assert jd.patch(f"/api/customers/{cid}", json={"email": ""}).json()["changed"] == ["email"]
        for bad in ({"name": ""}, {"name": None}):
            assert jd.patch(f"/api/customers/{cid}", json=bad).status_code == 400
        assert jd.patch(f"/api/customers/{cid}", json={"id_number": "1"}).status_code == 422                           # the identity is not an edit field
        # stopping: admin only; an active booking forbids it
        with _client("jadwa", "sales") as sal:
            assert sal.post(f"/api/customers/{cid}/archive").status_code == 403
        pid, code = new_project(jd)
        try:
            uid = new_unit(jd, pid, f"{code}-A1")
            _sql("INSERT INTO bookings(unit_id, customer_id, plan, price, status, created, expires, list_price) VALUES(?,?,?,?,?,?,?,?)", (uid, cid, "6040", 1000, "pending", "2026-11-03", "2099-01-01", 1000))
            r = jd.post(f"/api/customers/{cid}/archive")
            assert r.status_code == 409 and "حجز نشط" in r.json()["detail"], r.text
            _sql("UPDATE bookings SET status='cancelled' WHERE customer_id=?", (cid,))
            assert jd.post(f"/api/customers/{cid}/archive").json()["changed"] == ["active"]
            assert not any(x["id"] == cid for x in jd.get("/api/customers", params={"q": name}).json())
            assert any(x["id"] == cid for x in jd.get("/api/customers", params={"q": name, "archived": 1}).json())
            assert jd.post(f"/api/customers/{cid}/restore").json()["changed"] == ["active"]
        finally:
            _sql("DELETE FROM bookings WHERE customer_id=?", (cid,), maint=True)
            purge_project(code)
    finally:
        for x in (cid, cid2):
            if x:
                drop_customer(x)
        _sql("DELETE FROM customers WHERE name LIKE ?", ("عميل المبيعات C%",), maint=True)
        _sql("DELETE FROM customers WHERE name LIKE ?", ("عميل المبيعات S%",), maint=True)


# ====================================================================================================== الأرض والترخيص
def test_land_is_created_edited_and_stopped_and_a_land_with_a_live_project_is_not_stopped(jd):
    name = "أرض اختبار " + uniq("L")
    r = jd.post("/api/lands", json={"name": name, "location": "بوشر", "area": 5000, "zoning": "سكني", "far": 2.5, "max_floors": 6, "price": 750000, "lat": 23.58, "lng": 58.4})
    assert r.status_code == 200, r.text
    lid = r.json()["id"]
    pid = None
    try:
        row = next(x for x in jd.get("/api/lands").json() if x["id"] == lid)
        assert row["status"] == "تحت الدراسة" and row["area"] == 5000
        assert jd.post("/api/lands", json={"name": name, "location": "بوشر"}).status_code == 409
        assert jd.post("/api/lands", json={"name": name + " ب", "lat": 23.5}).status_code == 400                           # coordinates come as a pair
        assert jd.post("/api/lands", json={"name": name + " ج", "area": -4}).status_code == 422
        r = jd.patch(f"/api/lands/{lid}", json={"price": None, "notes": "ملاحظة", "status": "قيد التفاوض"})
        assert sorted(r.json()["changed"]) == ["notes", "price", "status"]
        assert next(x for x in jd.get("/api/lands").json() if x["id"] == lid)["price"] is None                            # an optional number clears
        assert jd.patch(f"/api/lands/{lid}", json={"lat": None}).status_code == 400                                          # one half of a pair is refused
        assert jd.patch(f"/api/lands/{lid}", json={"lat": None, "lng": None}).json()["changed"] == ["lat", "lng"]
        assert jd.patch(f"/api/lands/{lid}", json={"name": ""}).status_code == 400
        before = last_audit(jd)["id"]
        assert jd.patch(f"/api/lands/{lid}", json={"status": "قيد التفاوض"}).json()["changed"] == []
        assert last_audit(jd)["id"] == before
        pid, code = new_project(jd, land_id=lid)
        r = jd.post(f"/api/lands/{lid}/archive")
        assert r.status_code == 409 and "مشروع فعّال" in r.json()["detail"]
        assert jd.post(f"/api/projects/{pid}/archive").status_code == 200
        assert jd.post(f"/api/lands/{lid}/archive").json()["changed"] == ["active"]
        assert not any(x["id"] == lid for x in jd.get("/api/lands").json())
        assert any(x["id"] == lid for x in jd.get("/api/lands", params={"archived": 1}).json())
        assert jd.post(f"/api/lands/{lid}/restore").json()["changed"] == ["active"]
        with _client("jadwa", "sales") as s:
            assert s.post("/api/lands", json={"name": "ممنوعة على المبيعات"}).status_code == 403
    finally:
        if pid:
            purge_project(code)
        _sql("DELETE FROM lands WHERE id=?", (lid,), maint=True)


def test_permit_is_created_for_a_project_edited_beyond_its_status_and_stopped(jd):
    pid, code = new_project(jd)
    try:
        r = jd.post("/api/permits", json={"project_id": pid, "authority": "بلدية مسقط", "kind": "رخصة بناء", "ref": "BLD-MD-1", "expires": "2032-01-01"})
        assert r.status_code == 200, r.text
        perm_id = r.json()["id"]
        row = next(p for p in jd.get("/api/permits").json() if p["id"] == perm_id)
        assert row["status"] == "not_started" and row["project"] and row["expires"] == "2032-01-01"
        assert jd.post("/api/permits", json={"project_id": pid, "authority": "بلدية مسقط", "kind": "رخصة بناء"}).status_code == 409
        assert jd.post("/api/permits", json={"project_id": pid, "authority": "ب", "kind": "x"}).status_code == 422
        assert jd.post("/api/permits", json={"project_id": pid, "authority": "هيئة", "kind": "ترخيص", "issued": "2026-01-01", "applied": "2026-02-01"}).status_code == 400
        r = jd.patch(f"/api/permits/{perm_id}", json={"authority": "وزارة الإسكان", "notes": "تجديد سنوي"})                 # the descriptive fields join the status/ref/expiry edit
        assert sorted(r.json()["changed"]) == ["authority", "notes"], r.text
        for bad in ({"authority": ""}, {"kind": None}):
            r = jd.patch(f"/api/permits/{perm_id}", json=bad)
            assert r.status_code == 400 and "إلزامي" in r.json()["detail"], (bad, r.text)
        assert jd.patch(f"/api/permits/{perm_id}", json={"status": "submitted"}).json()["changed"].count("status") == 1
        assert jd.patch(f"/api/permits/{perm_id}", json={"status": "not_started"}).status_code == 200                      # a mistaken transition can be undone
        assert jd.post(f"/api/permits/{perm_id}/archive").json()["changed"] == ["active"]
        assert perm_id not in {p["id"] for p in jd.get("/api/permits").json()}
        assert perm_id in {p["id"] for p in jd.get("/api/permits", params={"archived": 1}).json()}
        assert jd.post(f"/api/permits/{perm_id}/restore").json()["changed"] == ["active"]
        with _client("jadwa", "sales") as s:
            assert s.post("/api/permits", json={"project_id": pid, "authority": "هيئة أخرى", "kind": "ترخيص"}).status_code == 403
    finally:
        purge_project(code)


# ====================================================================================================== المقاول والعقد والجدول
def test_contractor_contract_and_schedule_rules(jd):
    cr = "CR-" + uniq("")
    r = jd.post("/api/contractors", json={"name": "مقاول اختبار البيانات", "cr_number": cr, "phone": "+968 2400 0000", "trade": "هيكل"})
    assert r.status_code == 200, r.text
    kid = r.json()["id"]
    pid, code = new_project(jd)
    try:
        dup = jd.post("/api/contractors", json={"name": "مقاول آخر", "cr_number": cr})
        assert dup.status_code == 409 and cr in dup.json()["detail"]
        assert jd.post("/api/contractors", json={"name": "م"}).status_code == 422
        assert jd.post("/api/contractors", json={"name": "هاتف خاطئ", "phone": "x"}).status_code == 400
        assert any(k["id"] == kid and k["contracts"] == 0 for k in jd.get("/api/contractors").json())
        r = jd.patch(f"/api/contractors/{kid}", json={"trade": "", "notes": "موثوق"})
        assert sorted(r.json()["changed"]) == ["notes", "trade"]
        assert jd.patch(f"/api/contractors/{kid}", json={"name": ""}).status_code == 400
        # --- the contract
        body = {"project_id": pid, "contractor_id": kid, "value": 500000, "retention_pct": 0.1, "delay_penalty_per_day": 200, "start": "2026-01-01", "finish": "2027-06-30"}
        assert jd.post("/api/contractor-contracts", json={**body, "finish": "2025-12-31"}).status_code == 400
        assert jd.post("/api/contractor-contracts", json={**body, "value": 0}).status_code == 422
        r = jd.post("/api/contractor-contracts", json=body)
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        dup = jd.post("/api/contractor-contracts", json=body)
        assert dup.status_code == 409 and "عقد مقاول فعّال" in dup.json()["detail"]                                         # one live contract per project
        con = jd.get(f"/api/construction/{pid}").json()
        assert con["contract"]["id"] == cid and con["contract"]["contractor"] == "مقاول اختبار البيانات"
        r = jd.post(f"/api/contractors/{kid}/archive")
        assert r.status_code == 409 and "عقد فعّال" in r.json()["detail"]
        _sql("INSERT INTO ipcs(project_id, contractor_id, no, stage, claimed_pct, stage_value, status, approved_pct, created) VALUES(?,?,?,?,?,?,?,?,?)", (pid, kid, 1, "أساسات", 50, 100000, "approved", 50, "2026-03-01"))
        r = jd.patch(f"/api/contractor-contracts/{cid}", json={"value": 40000})
        assert r.status_code == 409 and "المعتمد" in r.json()["detail"], r.text                                              # never below what is certified
        assert jd.patch(f"/api/contractor-contracts/{cid}", json={"value": 600000, "delay_penalty_per_day": 250}).json()["changed"] == ["value", "delay_penalty_per_day"]
        k2 = jd.post("/api/contractors", json={"name": "مقاول بديل"}).json()["id"]
        r = jd.patch(f"/api/contractor-contracts/{cid}", json={"contractor_id": k2})
        assert r.status_code == 409 and "مستخلصات" in r.json()["detail"]                                                    # the certified work is the contractor's
        assert jd.patch(f"/api/contractor-contracts/{cid}", json={"finish": "2025-01-01"}).status_code == 400
        assert jd.patch(f"/api/contractor-contracts/{cid}", json={"value": None}).status_code == 400
        _sql("INSERT INTO ipcs(project_id, contractor_id, no, stage, claimed_pct, stage_value, status, created) VALUES(?,?,?,?,?,?,?,?)", (pid, kid, 2, "هيكل", 20, 50000, "pending", "2026-05-01"))
        r = jd.post(f"/api/contractor-contracts/{cid}/terminate")
        assert r.status_code == 409 and "مستخلص معلّق" in r.json()["detail"]
        _sql("UPDATE ipcs SET status='rejected' WHERE project_id=? AND no=2", (pid,))
        assert jd.post(f"/api/contractor-contracts/{cid}/terminate").json()["changed"] == ["active"]
        assert jd.get(f"/api/construction/{pid}").json()["contract"] is None                                                 # an ended contract leaves the screen
        assert jd.post(f"/api/contractors/{kid}/archive").json()["changed"] == ["active"]
        assert kid not in {k["id"] for k in jd.get("/api/contractors").json()} and kid in {k["id"] for k in jd.get("/api/contractors", params={"archived": 1}).json()}
        assert jd.post("/api/contractor-contracts", json={**body, "contractor_id": kid}).status_code == 409                   # a stopped contractor takes no new contract
        assert jd.post(f"/api/contractors/{kid}/restore").json()["changed"] == ["active"]
        assert jd.post(f"/api/contractor-contracts/{cid}/restore").json()["changed"] == ["active"]
        with _client("jadwa", "sales") as s:
            assert s.post("/api/contractors", json={"name": "ممنوع على المبيعات"}).status_code == 403
        # --- the schedule
        t = {"project_id": pid, "name": "الحفريات", "planned_start": "2026-01-01", "planned_end": "2026-03-01", "weight": 0.4}
        assert jd.post("/api/schedule-tasks", json={**t, "planned_end": "2025-12-01"}).status_code == 400
        assert jd.post("/api/schedule-tasks", json={**t, "weight": 1.5}).status_code == 422
        t1 = jd.post("/api/schedule-tasks", json=t).json()["id"]
        t2 = jd.post("/api/schedule-tasks", json={**t, "name": "الهيكل", "planned_start": "2026-03-01", "planned_end": "2026-09-01", "weight": 0.5, "depends_on": t1}).json()["id"]
        r = jd.post("/api/schedule-tasks", json={**t, "name": "التشطيب", "weight": 0.2})
        assert r.status_code == 409 and "100" in r.json()["detail"] and "10" in r.json()["detail"], r.text                      # 0.4 + 0.5 + 0.2 > 1
        assert jd.post("/api/schedule-tasks", json={**t, "name": "ربط خاطئ", "weight": 0.05, "depends_on": 99999999}).status_code == 400
        r = jd.patch(f"/api/schedule-tasks/{t1}", json={"depends_on": t2})
        assert r.status_code == 409 and "دورة" in r.json()["detail"], r.text
        assert jd.patch(f"/api/schedule-tasks/{t2}", json={"pct": 30, "actual_start": "2026-03-05", "depends_on": None}).json()["changed"] == ["pct", "actual_start", "depends_on"]
        assert jd.patch(f"/api/schedule-tasks/{t2}", json={"pct": 30}).json()["changed"] == []
        assert jd.patch(f"/api/schedule-tasks/{t2}", json={"name": ""}).status_code == 400
        assert jd.patch(f"/api/schedule-tasks/{t2}", json={"weight": 0.7}).status_code == 409
        jd.patch(f"/api/schedule-tasks/{t2}", json={"depends_on": t1})
        r = jd.post(f"/api/schedule-tasks/{t1}/archive")
        assert r.status_code == 409 and "تعتمد عليها" in r.json()["detail"]
        sched = jd.get(f"/api/construction/{pid}").json()["schedule"]
        assert {x["name"] for x in sched["tasks"]} == {"الحفريات", "الهيكل"} and sched["actual_pct"] == round((0.5 * 30) / 0.9, 1)      # progress divides by the total weight
        assert jd.post(f"/api/schedule-tasks/{t2}/archive").json()["changed"] == ["active"]
        assert jd.post(f"/api/schedule-tasks/{t1}/archive").json()["changed"] == ["active"]
        assert jd.get(f"/api/construction/{pid}").json()["schedule"]["tasks"] == []
        assert jd.post(f"/api/schedule-tasks/{t1}/restore").json()["changed"] == ["active"]
    finally:
        purge_project(code)
        _sql("DELETE FROM contractors WHERE name IN (?,?)", ("مقاول اختبار البيانات", "مقاول بديل"), maint=True)


# ====================================================================================================== الصلاحيات والمجهول
def test_only_the_roles_with_masterdata_create_projects_buildings_and_units(jd):
    pid, code = new_project(jd)
    try:
        for user, ok in (("sales", False), ("engineer", False), ("investor1", False), ("finance", True)):
            with _client("jadwa", user) as c:
                r = c.post("/api/projects", json={"code": uniq("R"), "name": "مشروع بصلاحية " + user, "kind": "villa"})
                assert (r.status_code == 200) is ok, (user, r.status_code, r.text)
                if ok:
                    _sql("DELETE FROM projects WHERE id=?", (r.json()["id"],), maint=True)
                else:
                    assert r.status_code == 403
                    assert c.post(f"/api/projects/{pid}/buildings", json={"name": "ممنوع"}).status_code == 403
                    assert c.post("/api/units", json={"project_id": pid, "code": uniq("N")}).status_code == 403
                    assert c.patch(f"/api/projects/{pid}", json={"name": "ممنوع"}).status_code == 403
    finally:
        purge_project(code)


def test_unknown_values_stay_null_in_a_real_data_developer(jd):
    with _client("almaqsura") as c:
        prof = c.get("/api/projects").json()
        if not prof:
            pytest.skip("this tenant has no project")
        pid = prof[0]["id"]
        code = uniq("RU")
        r = c.post("/api/units", json={"project_id": pid, "code": code, "use": "commercial"})                              # a code and a use — nothing else is known
        assert r.status_code == 200, r.text
        try:
            row = _sql("SELECT area, price, floor, pos, type, view, building, status FROM units WHERE code=?", (code,), "almaqsura")[0]
            assert row["area"] is None and row["price"] is None and row["floor"] is None and row["type"] is None and row["view"] is None and row["building"] is None
            assert row["status"] == "a"
            shown = next(u for u in c.get(f"/api/units?project_id={pid}").json() if u["code"] == code)
            assert shown["price"] is None and shown["area"] is None
            assert c.get("/api/units/" + code).status_code == 200                                                          # the card of a unit without a price still opens
            assert _sql("SELECT COUNT(*) n FROM unit_price_changes WHERE unit_id=?", (r.json()["id"],), "almaqsura")[0]["n"] == 0
        finally:
            _sql("DELETE FROM units WHERE code=?", (code,), "almaqsura", maint=True)


def _get_paths() -> list[str]:
    """Every GET route with no path parameter (the working screens' reads), whichever router declares it."""
    out = []

    def walk(router):
        for r in router.routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                walk(inner)
            elif hasattr(r, "path") and "GET" in (getattr(r, "methods", None) or ()) and "{" not in r.path and r.path.startswith("/api/"):
                out.append(r.path)
    walk(app.router)
    return sorted(set(out))


def test_every_read_screen_survives_a_project_with_no_units_no_contract_and_no_schedule_and_a_stopped_one(jd):
    """A project made from the form starts empty (it surfaced a division by zero in the project list). Every parameterless read must answer without a server error."""
    from backend import observability as O
    pid, code = new_project(jd)
    try:
        paths = _get_paths()
        assert len(paths) > 80, len(paths)
        bad = []
        for rnd in ("empty", "stopped"):
            if rnd == "stopped":
                assert jd.post(f"/api/projects/{pid}/archive").status_code == 200
            for i, path in enumerate(paths):
                if i % 25 == 0:
                    O.limiter.reset()
                r = jd.get(path)
                if r.status_code >= 500:
                    bad.append((rnd, path, r.status_code, r.text[:120]))
        assert not bad, bad
        assert jd.get(f"/api/construction/{pid}").status_code == 200 and jd.get(f"/api/pricing/{pid}").status_code == 200 and jd.get(f"/api/units?project_id={pid}").status_code == 200
    finally:
        purge_project(code)


def test_the_buildings_register_is_filled_from_the_unit_names_that_already_exist(jd):
    pid, code = new_project(jd)
    try:
        _sql("INSERT INTO units(project_id, code, building, status) VALUES(?,?,?,?)", (pid, f"{code}-L1", "برج قديم", "a"))
        assert _sql("SELECT COUNT(*) n FROM buildings WHERE project_id=?", (pid,))[0]["n"] == 0                                # a unit made the old way has no register row
        names = [b["name"] for b in jd.get(f"/api/projects/{pid}/buildings").json()]
        assert names == ["برج قديم"]
        assert jd.get(f"/api/projects/{pid}/buildings").json()[0]["units"] == 1
        assert jd.post(f"/api/projects/{pid}/buildings", json={"name": "برج قديم"}).status_code == 409                       # the legacy name counts as taken
    finally:
        purge_project(code)
