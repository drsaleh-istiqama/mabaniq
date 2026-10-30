"""0.21.0 — integrated leasing core: schedule arithmetic, the immutable payment ledger (partial / advance / reversal), post-dated cheques, blacklist,
arrears ageing, the three PDFs, compatibility of the old endpoints, and the carry-over of pre-0.21 payments (ledger total = cached total)."""
import datetime as dt
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "lea.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "bayan:بيان عمان;almaqsura:المقصورة العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import leasing as L  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect  # noqa: E402

CSRF = "csrf-leasing-" + "l" * 28
D = dt.date


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


@pytest.fixture()
def cl():
    from backend import observability as O
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        for t in ("jadwa", "bayan", "almaqsura"):
            tok = TENANT.set(t)
            try:
                d = connect()
                d.execute("DELETE FROM login_attempts")
                d.commit()
                d.close()
            finally:
                TENANT.reset(tok)
        yield c


_N = [0]
_UNITS = "SELECT id FROM units WHERE code LIKE 'T-LEA-%'"
_LEASES = f"SELECT id FROM leases WHERE unit_id IN ({_UNITS})"


@pytest.fixture(scope="module", autouse=True)
def _purge_my_rows():
    """The suite shares one database: remove every unit / lease / payment this module created so other modules' counts stay what they expect.
    (The ledger refuses DELETE for the application role on PostgreSQL, so the clean-up runs in maintenance mode there.)"""
    yield
    tok = TENANT.set("bayan")
    try:
        c = connect()
        pg = getattr(c, "dialect", "sqlite") == "postgres"
        if pg:
            c.maintenance()
        sc = " AND org_id = current_setting('app.org_id', true)" if pg else ""
        for sql in (f"DELETE FROM rent_payments WHERE lease_id IN ({_LEASES}{sc})", f"DELETE FROM cheques WHERE lease_id IN ({_LEASES}{sc})",
                    f"DELETE FROM lease_events WHERE lease_id IN ({_LEASES}{sc})", f"DELETE FROM lease_terms WHERE lease_id IN ({_LEASES}{sc})",
                    f"DELETE FROM rent_dues WHERE lease_id IN ({_LEASES}{sc})",
                    f"DELETE FROM tenants_l WHERE id IN (SELECT tenant_id FROM leases WHERE unit_id IN ({_UNITS}{sc}))",
                    f"DELETE FROM leases WHERE unit_id IN ({_UNITS}{sc})", f"DELETE FROM unit_meters WHERE unit_id IN ({_UNITS}{sc})",
                    f"DELETE FROM units WHERE code LIKE 'T-LEA-%'{sc}", f"DELETE FROM doc_issues WHERE kind IN ('lease','rent_receipt','cheque_receipt'){sc}"):
            c.execute(sql)
        c.commit()
        if pg:
            c.end_maintenance()
        c.close()
    finally:
        TENANT.reset(tok)


def _free_unit(cl):
    """A brand-new unit in the leasing portfolio of the signed-in developer (tests must not fight over the few seeded vacant units)."""
    tenant = cl.cookies.get(A.TENANT_COOKIE)
    tok = TENANT.set(tenant)
    try:
        c = connect()
        _N[0] += 1
        pid = c.execute("SELECT project_id FROM units WHERE retained=1 LIMIT 1").fetchone()[0]
        uid = c.execute("INSERT INTO units(project_id,code,type,area,status,retained,use) VALUES(?,?,?,?,?,?,?)", (pid, f"T-LEA-{_N[0]:03d}", "مكتب", 60, "a", 1, "commercial")).lastrowid
        c.commit()
        c.close()
    finally:
        TENANT.reset(tok)
    return next(u for u in cl.get("/api/lea/units").json()["units"] if u["id"] == uid)


def _new_lease(cl, unit=None, **kw):
    body = {"unit_id": (unit or _free_unit(cl))["id"], "tenant": {"name": "شركة النور للتجارة", "phone": "+968 91234567", "id_number": "AB123456"},
            "start": "2031-01-01", "months": 12, "annual_rent": 1200, "frequency": 12, "sign": True} | kw
    r = cl.post("/api/lea/leases", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ----------------------------------------------------------------------------------------------------- pure arithmetic
def test_three_year_schedule_with_prep_matches_hand_calculation():
    # 36 months, rents 6000 / 6600 / 7200 (500, 550, 600 a month), quarterly, 30 days free = month 1 free, rent from month index 1
    s = L.build_schedule(D(2026, 1, 1), 36, [6000, 6600, 7200], 4, 30)
    assert len(s) == 12 and s[0]["due"] == "2026-01-31"
    assert s[0]["amount"] == 1500 and s[0]["year_no"] == 1  # months 1,2,3 of year 1
    assert s[3]["amount"] == 1550  # months 10,11 (year 1, 500 each) + month 12 (year 2, 550) — priced month by month across the boundary
    assert s[-1]["amount"] == 1200  # last period is the 2 months left (rule M9): 2 x 600
    assert round(sum(d["amount"] for d in s), 3) == 11 * 500 + 12 * 550 + 12 * 600 == 19300


def test_schedule_without_prep_and_proportional_last_period():
    s = L.build_schedule(D(2026, 3, 15), 14, [2400, 2400], 4, 0)
    assert [d["amount"] for d in s] == [600, 600, 600, 600, 400] and s[0]["due"] == "2026-03-15" and s[1]["due"] == "2026-06-15"
    odd = L.build_schedule(D(2026, 1, 1), 12, [1000], 12, 0)  # 1000/12 does not divide: the last due absorbs the baisa
    assert round(sum(d["amount"] for d in odd), 3) == 1000 and len(odd) == 12


def test_schedule_rejects_bad_input():
    with pytest.raises(ValueError):
        L.build_schedule(D(2026, 1, 1), 12, [1000], 5, 0)
    with pytest.raises(ValueError):
        L.build_schedule(D(2026, 1, 1), 24, [1000], 4, 0)  # no rent for year 2
    with pytest.raises(ValueError):
        L.build_schedule(D(2026, 1, 1), 1, [1000], 12, 30)  # preparation covers the whole term


# ----------------------------------------------------------------------------------------------------- lease + ledger
def test_create_preview_sign_and_numbering(cl):
    login_as(cl, "admin", "bayan")
    u = _free_unit(cl)
    body = {"unit_id": u["id"], "tenant": {"name": "مؤسسة الأفق", "phone": "+968 90000001"}, "start": "2031-01-01", "months": 24, "annual_rent": 1200,
            "escalation_pct": 10, "frequency": 4, "prep_free_days": 30, "deposit": 100}
    pv = cl.post("/api/lea/leases/preview", json=body).json()
    assert pv["rents"] == [1200, 1320] and pv["rent_start"] == "2031-01-31" and len(pv["schedule"]) == 8
    assert cl.get("/api/lea/leases", params={"q": "مؤسسة الأفق"}).json() == []  # preview wrote nothing
    r = cl.post("/api/lea/leases", json=body).json()
    assert r["status"] == "draft"
    lid = r["id"]
    d = cl.get(f"/api/lea/leases/{lid}").json()
    assert d["dues"] == [] and len(d["terms"]) == 2 and d["number"].startswith("LS-2031-")
    assert cl.post("/api/lea/payments", json={"lease_id": lid, "amount": 10}).status_code == 409  # a draft takes no money
    assert cl.post(f"/api/lea/leases/{lid}/sign").status_code == 200
    d = cl.get(f"/api/lea/leases/{lid}").json()
    assert d["status"] == "active" and len([x for x in d["dues"] if x["kind"] == "rent"]) == 8 and [x for x in d["dues"] if x["kind"] == "deposit"][0]["amount"] == 100
    assert round(d["totals"]["billed"], 3) == round(1200 * 11 / 12 + 1320, 3)  # month 0 is free
    assert cl.post("/api/lea/leases", json=body | {"sign": True}).status_code == 409  # same unit, same dates
    n2 = _new_lease(cl, start="2032-02-01")
    assert cl.get(f"/api/lea/leases/{n2}").json()["number"] != d["number"]


def test_partial_advance_overpay_and_reversal_keep_cache_and_ledger_equal(cl):
    login_as(cl, "admin", "bayan")
    lid = _new_lease(cl, start="2033-01-01", months=12, annual_rent=1200, frequency=12)
    dues = cl.get(f"/api/lea/leases/{lid}").json()["dues"]
    first = dues[0]
    r = cl.post("/api/lea/payments", json={"lease_id": lid, "amount": 30, "due_id": first["id"], "method": "cash"}).json()  # partial
    assert r["receipt_no"].startswith("RC-") and r["applied"] == [{"due_id": first["id"], "amount": 30}]
    d = cl.get(f"/api/lea/leases/{lid}").json()
    assert d["dues"][0]["paid"] == 30 and d["dues"][0]["balance"] == 70
    adv = cl.post("/api/lea/payments", json={"lease_id": lid, "amount": 270, "method": "transfer", "reference": "TRF-1"}).json()  # advance over several dues
    assert [a["amount"] for a in adv["applied"]] == [70, 100, 100] and adv["receipt_no"] != r["receipt_no"]
    assert cl.post("/api/lea/payments", json={"lease_id": lid, "amount": 5000}).status_code == 409  # more than the whole balance
    assert cl.post("/api/lea/payments", json={"lease_id": lid, "amount": 10, "paid_on": "2999-01-01"}).status_code == 400
    d = cl.get(f"/api/lea/leases/{lid}").json()
    assert d["totals"]["paid"] == 300 and d["totals"]["balance"] == 900
    pid = adv["payment_ids"][1]
    assert cl.post(f"/api/lea/payments/{pid}/reverse", json={"reason": "خطأ في الإدخال"}).status_code == 200
    assert cl.post(f"/api/lea/payments/{pid}/reverse", json={"reason": "مرة ثانية"}).status_code == 409
    d = cl.get(f"/api/lea/leases/{lid}").json()
    assert d["totals"]["paid"] == 200 and d["dues"][1]["paid"] == 0
    c = connect()
    tok = TENANT.set("bayan")
    try:
        c = connect()
        assert L.ledger_mismatches(c) == []
        c.close()
    finally:
        TENANT.reset(tok)


def test_cheque_life_cycle_pays_only_on_clearing_and_bounce_reopens(cl):
    login_as(cl, "admin", "bayan")
    lid = _new_lease(cl, start="2034-01-01", months=12, annual_rent=1200, frequency=12)
    due = cl.get(f"/api/lea/leases/{lid}").json()["dues"][0]
    ch = cl.post("/api/lea/cheques", json={"lease_id": lid, "due_id": due["id"], "number": "100234", "bank": "بنك مسقط", "amount": 100, "due_date": "2034-01-05"}).json()
    assert ch["receipt_no"].startswith("CQ-")
    assert cl.get(f"/api/lea/leases/{lid}").json()["totals"]["paid"] == 0  # custody is not payment
    assert cl.post("/api/lea/cheques", json={"lease_id": lid, "number": "100234", "bank": "بنك مسقط", "amount": 100, "due_date": "2034-01-05"}).status_code == 409
    assert cl.post(f"/api/lea/cheques/{ch['id']}/clear", json={}).status_code == 409  # not deposited yet
    assert cl.post(f"/api/lea/cheques/{ch['id']}/deposit", json={}).status_code == 200
    ok = cl.post(f"/api/lea/cheques/{ch['id']}/clear", json={"on": "2026-10-01"}).json()
    assert ok["applied"] == [{"due_id": due["id"], "amount": 100}]
    d = cl.get(f"/api/lea/leases/{lid}").json()
    assert d["dues"][0]["paid"] == 100 and d["payments"][0]["method"] == "cheque" and d["payments"][0]["cheque_id"] == ch["id"]
    assert cl.post(f"/api/lea/cheques/{ch['id']}/bounce", json={"reason": "الرصيد غير كافٍ"}).status_code == 200  # bounces after clearing: payment reversed
    d = cl.get(f"/api/lea/leases/{lid}").json()
    assert d["dues"][0]["paid"] == 0 and d["dues"][0]["balance"] == 100 and d["cheques"][0]["status"] == "bounced"
    assert not any(x["amount"] for x in d["dues"] if x["balance"] and x["amount"] != x["balance"] and x["paid"])  # no fee / penalty was added anywhere


def test_blacklist_blocks_a_new_lease_unless_the_manager_overrides_with_a_reason(cl):
    login_as(cl, "admin", "bayan")
    lid = _new_lease(cl, start="2035-01-01")
    tid = cl.get(f"/api/lea/leases/{lid}").json()["tenant_id"]
    assert cl.post(f"/api/lea/tenants/{tid}/blacklist", json={"reason": "تأخر متكرر موثَّق"}).status_code == 200
    u2 = _free_unit(cl)
    body = {"unit_id": u2["id"], "tenant_id": tid, "start": "2036-01-01", "months": 12, "annual_rent": 600, "frequency": 12, "sign": True}
    assert cl.post("/api/lea/leases", json=body).status_code == 409
    assert cl.post("/api/lea/leases", json=body | {"override_reason": "سداد المتأخرات كاملةً"}).status_code == 200  # admin may, with a reason
    assert cl.post(f"/api/lea/tenants/{tid}/unblacklist", json={"reason": "سوّى حسابه"}).status_code == 200
    t = cl.get(f"/api/lea/tenants/{tid}").json()
    assert t["id_number"] == "AB123456" and not t["blacklisted"]  # decrypted for the file; masked in the list
    listed = next(x for x in cl.get("/api/lea/tenants", params={"q": "النور"}).json() if x["id"] == tid)
    assert listed["id_number"].endswith("3456") and "AB12" not in listed["id_number"]


def test_aging_buckets_and_overview(cl):
    login_as(cl, "admin", "bayan")
    lid = _new_lease(cl, start="2026-01-01", months=12, annual_rent=1200, frequency=12)
    ag = cl.get("/api/lea/aging").json()
    mine = next(x for x in ag["leases"] if x["lease_id"] == lid)
    today = dt.date.today()
    late = [d for d in cl.get(f"/api/lea/leases/{lid}").json()["dues"] if d["due"] < today.isoformat()]
    assert round(mine["amount"], 3) == round(sum(d["balance"] for d in late), 3) and sum(b["count"] for b in ag["buckets"]) >= len(late)
    assert round(sum(b["amount"] for b in ag["buckets"]), 3) == ag["total"]
    ov = cl.get("/api/lea/overview").json()
    assert ov["units"] >= 1 and ov["arrears"] == ag["total"] and set(ov["expiring"]) == {"30", "60", "90"}


def test_documents_render_with_verification(cl):
    login_as(cl, "admin", "bayan")
    lid = _new_lease(cl, start="2037-01-01", months=12, annual_rent=1200, frequency=4, prep_free_days=30, deposit=100)
    for kind, ref in (("lease", lid),):
        r = cl.get(f"/api/docs/{kind}/{ref}.pdf")
        assert r.status_code == 200 and r.content[:4] == b"%PDF"
    dues = cl.get(f"/api/lea/leases/{lid}").json()["dues"]
    pay = cl.post("/api/lea/payments", json={"lease_id": lid, "amount": 150, "due_id": dues[1]["id"], "method": "cash"}).json()
    r = cl.get(f"/api/docs/rent_receipt/{pay['first_id']}.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    ch = cl.post("/api/lea/cheques", json={"lease_id": lid, "number": "7001", "bank": "بنك ظفار", "amount": 100, "due_date": "2037-03-01"}).json()
    r = cl.get(f"/api/docs/cheque_receipt/{ch['id']}.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    c = connect()
    tok = TENANT.set("bayan")
    try:
        c = connect()
        codes = [x["verify_code"] for x in c.execute("SELECT verify_code FROM doc_issues WHERE kind IN ('lease','rent_receipt','cheque_receipt')").fetchall()]
        c.close()
    finally:
        TENANT.reset(tok)
    assert len(codes) >= 3 and cl.get(f"/verify/bayan/{codes[0]}").status_code == 200
    cl.cookies.clear()
    assert cl.get(f"/api/docs/lease/{lid}.pdf").status_code in (401, 403)


def test_old_endpoints_still_work_on_the_new_engine(cl):
    login_as(cl, "admin", "bayan")
    u = _free_unit(cl)
    r = cl.post("/api/leases", json={"unit_id": u["id"], "tenant_name": "علي بن سالم", "tenant_phone": "+968 99999999", "tenant_id_number": "12345678", "start": "2038-01-01",
                                     "months": 12, "annual_rent": 2400, "frequency": 4})
    assert r.status_code == 200, r.text
    lid = r.json()["id"]
    d = cl.get(f"/api/lea/leases/{lid}").json()
    assert d["status"] == "active" and d["number"] and len([x for x in d["dues"] if x["kind"] == "rent"]) == 4 and d["deposit"] == 200
    old = cl.get("/api/leasing").json()
    mine = next(x for x in old["leases"] if x["id"] == lid)
    assert mine["arrears"] == 0 and len(mine["dues"]) == 4  # the deposit of the old API is recorded, not billed
    did = next(x["id"] for x in d["dues"] if x["kind"] == "rent")
    assert cl.post(f"/api/rent-dues/{did}/pay").status_code == 200
    assert cl.post(f"/api/rent-dues/{did}/pay").status_code == 409
    d = cl.get(f"/api/lea/leases/{lid}").json()
    assert d["payments"][0]["method"] is None and d["payments"][0]["amount"] == 600  # the method of an old-style collection is not invented
    assert cl.post("/api/leases", json={"unit_id": u["id"], "tenant_name": "ثان", "tenant_phone": "+968 99999990", "tenant_id_number": "1234567", "start": "2038-06-01",
                                        "months": 12, "annual_rent": 100, "frequency": 4}).status_code == 409


def test_carry_over_of_old_payments_and_documented_methods(cl):
    """Almaqsura: every paid due of the approved August report is in the ledger with the method the report states; totals agree."""
    login_as(cl, "admin", "almaqsura")
    pays = cl.get("/api/lea/payments", params={"limit": 500}).json()
    assert pays and all(p["reference"] == "ترحيل 0009" for p in pays)
    methods = {p["method"] for p in pays}
    assert methods <= {"transfer", "cheque", None} and "transfer" in methods and "cheque" in methods
    c = None
    tok = TENANT.set("almaqsura")
    try:
        c = connect()
        assert L.ledger_mismatches(c) == []
        assert c.execute("SELECT COUNT(*) FROM leases WHERE number IS NULL").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM leases l WHERE NOT EXISTS (SELECT 1 FROM lease_terms t WHERE t.lease_id=l.id)").fetchone()[0] == 0
        # the purchased-units workbook states a year-2 rent and parking: they became a term / a unit field, and the unpaid 2027 dues follow the term
        t = c.execute("""SELECT t.year_no, t.annual_rent, l.id, u.parking_bays FROM lease_terms t JOIN leases l ON l.id=t.lease_id JOIN units u ON u.id=l.unit_id
                         WHERE u.code='MQT-T1-703' ORDER BY t.year_no""").fetchall()
        assert [(x[0], x[1]) for x in t] == [(1, 655 * 12), (2, 780 * 12)] and t[0][3] == 2
        amounts = {r["due"][:4]: r["amount"] for r in c.execute("SELECT due, amount FROM rent_dues WHERE lease_id=? AND paid=0", (t[0][2],)).fetchall()}
        assert amounts.get("2027") == 780 and amounts.get("2026") in (None, 655)
        again = L.ensure_core(c)  # idempotent
        assert again["payments"] == 0 and again["numbered"] == 0 and again["terms"] == 0
        c.close()
    finally:
        TENANT.reset(tok)
    ov = cl.get("/api/lea/overview").json()
    assert ov["leased"] >= 1 and ov["units"] >= ov["leased"]


def test_non_leasing_roles_and_modules_are_refused(cl):
    login_as(cl, "sales", "bayan")
    assert cl.get("/api/lea/overview").status_code == 403
    assert cl.post("/api/lea/payments", json={"lease_id": 1, "amount": 5}).status_code == 403
    login_as(cl, "admin", "bayan")
    assert cl.post("/api/modules", json={"modules": ["sales", "finance", "reports"]}).status_code == 200
    try:
        assert cl.get("/api/lea/overview").status_code == 404  # module off ⟵ same 404 as an unknown path
    finally:
        cl.post("/api/modules", json={"modules": __import__("backend.registry", fromlist=["x"]).available()})


def test_a_lump_payment_without_a_chosen_due_pays_the_rent_before_the_deposit(cl):
    login_as(cl, "admin", "bayan")
    lid = _new_lease(cl, start="2038-01-01", months=12, annual_rent=1200, frequency=4, prep_free_days=30, deposit=100)
    d = cl.get(f"/api/lea/leases/{lid}").json()
    dep = next(x for x in d["dues"] if x["kind"] == "deposit")
    first_rent = min((x for x in d["dues"] if x["kind"] == "rent"), key=lambda x: x["due"])
    assert dep["due"] <= first_rent["due"], "the deposit falls due first — the case the old ordering got wrong"
    r = cl.post("/api/lea/payments", json={"lease_id": lid, "amount": 50}).json()
    assert r["applied"][0]["due_id"] == first_rent["id"]
    assert cl.post("/api/lea/payments", json={"lease_id": lid, "amount": 50, "due_id": dep["id"]}).status_code == 200   # the deposit is still payable when chosen


def test_two_simultaneous_receipts_for_one_due_cannot_both_succeed(cl):
    """0.28.2: on PostgreSQL two requests used to read the same unpaid balance and both write against it (a double payment); the per-lease lock queues them."""
    from concurrent.futures import ThreadPoolExecutor

    from starlette.testclient import TestClient as TC

    from backend.app import app as application
    login_as(cl, "admin", "bayan")
    lid = _new_lease(cl, start="2039-01-01", months=12, annual_rent=1200, frequency=12)
    due = cl.get(f"/api/lea/leases/{lid}").json()["dues"][0]

    def pay(_):
        c2 = TC(application, base_url="https://testserver")   # not entered as a context: leaving one would shut the shared connection pool under the other threads
        login_as(c2, "admin", "bayan")
        return c2.post("/api/lea/payments", json={"lease_id": lid, "amount": due["amount"], "due_id": due["id"]}).status_code
    with ThreadPoolExecutor(4) as ex:
        codes = sorted(ex.map(pay, range(4)))
    assert codes.count(200) == 1 and all(x in (409, 429) for x in codes if x != 200), codes
    assert cl.get(f"/api/lea/leases/{lid}").json()["dues"][0]["paid"] == due["amount"]
