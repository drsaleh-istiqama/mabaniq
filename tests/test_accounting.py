"""0.23.0 — accounting core: activation and the chart, double-entry journals, the immutable ledger (database guards), maker-checker for manual journals, the
opening balance, closed periods, and the posting rules that carry the leasing events (rent due, receipt, reversal, termination, payment plan, deposit, late
payment charity, expense, owner commission) to the books — idempotently and without ever guessing a payment method."""
import datetime as dt
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "acc.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "bayan:بيان عمان;almaqsura:المقصورة العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect, init  # noqa: E402

CSRF = "csrf-acc-" + "a" * 31
TODAY = dt.date.today()
_N = [0]
CODE = {"cash": "1110", "bank": "1121", "bank_charity": "1125", "unclassified": "1130", "ar": "1210", "deposits": "2130", "owners": "2120", "vendors": "2110",
        "charity": "2190", "rent": "4110", "recov": "4140", "fee": "4130", "maint": "5110", "capital": "3100"}


def login_as(c, user, tenant="bayan"):
    tok = TENANT.set(tenant)
    try:
        c.cookies.set(A.COOKIE, A.issue_session(user))
    finally:
        TENANT.reset(tok)
    c.cookies.set(A.TENANT_COOKIE, tenant)
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


def _raw(sql, args=(), commit=True):
    tok = TENANT.set("bayan")
    try:
        c = connect()
        try:
            r = c.execute(sql, args)
            out = r.fetchall() if sql.lstrip().upper().startswith("SELECT") else None
            if commit:
                c.commit()
            return out
        finally:
            c.close()
    finally:
        TENANT.reset(tok)


def _maint(sql, args=()):
    """A statement the application role may not run (it has no UPDATE on the payments ledger) — used only to age test data."""
    tok = TENANT.set("bayan")
    try:
        c = connect()
        pg = getattr(c, "dialect", "sqlite") == "postgres"
        c.maintenance()
        c.execute(sql, args)
        c.commit()
        c.end_maintenance()
        if not pg:
            init(c)
        c.close()
    finally:
        TENANT.reset(tok)


def _wipe_acc():
    """Test-only: clear the books of the `bayan` developer (the guards honour the maintenance flag, as the demo reseed does)."""
    tok = TENANT.set("bayan")
    try:
        c = connect()
        pg = getattr(c, "dialect", "sqlite") == "postgres"
        sc = " AND org_id = current_setting('app.org_id', true)" if pg else ""
        c.maintenance()
        for t in ("fin_installments", "fin_contracts", "acc_budgets", "depreciation_runs", "fixed_assets", "vat_returns", "bank_recons", "bank_stmt_lines", "payment_orders", "ap_payments", "ap_bill_lines", "ap_bills", "bank_accounts",
                  "acc_lines", "acc_journals", "acc_source_state", "acc_periods", "acc_cost_centers", "acc_accounts"):
            c.execute(c.wipe_sql(t))
        c.execute(f"DELETE FROM settings WHERE k IN ('acc_start','acc_attach_over'){sc}")
        c.execute(f"DELETE FROM counters WHERE k LIKE 'jv:%'{sc}")
        c.execute(f"DELETE FROM documents WHERE ref_type='journal'{sc}")
        c.commit()
        c.end_maintenance()
        if not pg:
            init(c)  # the SQLite guards were dropped for the wipe; recreate them
        c.close()
    finally:
        TENANT.reset(tok)


@pytest.fixture()
def cl():
    from backend import observability as O
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        _wipe_acc()  # after start-up, which creates the schema
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


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    _wipe_acc()
    tok = TENANT.set("bayan")
    try:
        c = connect()
        pg = getattr(c, "dialect", "sqlite") == "postgres"
        sc = " AND org_id = current_setting('app.org_id', true)" if pg else ""
        if pg:
            c.maintenance()
        lease_ids = "SELECT id FROM leases WHERE unit_id IN (SELECT id FROM units WHERE code LIKE 'T-ACC-%')"
        for sql in (f"DELETE FROM charity_dues WHERE lease_id IN ({lease_ids}){sc}", f"DELETE FROM payment_plans WHERE lease_id IN ({lease_ids}){sc}",
                    f"DELETE FROM property_expenses WHERE unit_id IN (SELECT id FROM units WHERE code LIKE 'T-ACC-%'){sc}",
                    f"DELETE FROM owner_statements WHERE owner_id IN (SELECT id FROM owners WHERE name LIKE 'مالك محاسبة%'){sc}",
                    f"DELETE FROM rent_payments WHERE lease_id IN ({lease_ids}){sc}", f"DELETE FROM cheques WHERE lease_id IN ({lease_ids}){sc}",
                    f"DELETE FROM lease_events WHERE lease_id IN ({lease_ids}){sc}", f"DELETE FROM lease_terms WHERE lease_id IN ({lease_ids}){sc}",
                    f"DELETE FROM rent_dues WHERE lease_id IN ({lease_ids}){sc}",
                    f"DELETE FROM tenants_l WHERE id IN (SELECT tenant_id FROM leases WHERE unit_id IN (SELECT id FROM units WHERE code LIKE 'T-ACC-%')){sc}",
                    f"DELETE FROM leases WHERE unit_id IN (SELECT id FROM units WHERE code LIKE 'T-ACC-%'){sc}", f"DELETE FROM units WHERE code LIKE 'T-ACC-%'{sc}",
                    f"DELETE FROM owners WHERE name LIKE 'مالك محاسبة%'{sc}", f"DELETE FROM doc_issues WHERE kind IN ('lease','rent_receipt'){sc}"):
            c.execute(sql)
        c.commit()
        if pg:
            c.end_maintenance()
        c.close()
    finally:
        TENANT.reset(tok)


# ----------------------------------------------------------------------------------------------------- helpers
def _activate(cl, days_back=90):
    start = (TODAY - dt.timedelta(days=days_back)).isoformat()
    r = cl.post("/api/acc/activate", json={"start": start, "confirm": True})
    assert r.status_code == 200, r.text
    return start


def _unit(owner_id=None, use="commercial"):
    tok = TENANT.set("bayan")
    try:
        c = connect()
        _N[0] += 1
        row = c.execute("SELECT project_id FROM units WHERE retained=1 ORDER BY project_id LIMIT 1").fetchone()
        uid = c.execute("INSERT INTO units(project_id,code,type,area,status,retained,use,owner_id) VALUES(?,?,?,?,?,?,?,?)",
                        (row[0], f"T-ACC-{_N[0]:03d}-{os.getpid() % 1000}", "مكتب", 60, "a", 1, use, owner_id)).lastrowid
        c.commit()
        c.close()
    finally:
        TENANT.reset(tok)
    return uid


def _lease(cl, owner_id=None, days_ago=60, **kw):
    _N[0] += 1
    body = {"unit_id": _unit(owner_id), "tenant": {"name": f"مستأجر محاسبة {_N[0]}", "phone": "+968 91234567", "id_number": f"AC{os.getpid()}{_N[0]:05d}"},
            "start": (TODAY - dt.timedelta(days=days_ago)).isoformat(), "months": 12, "annual_rent": 1200, "frequency": 4, "sign": True} | kw
    r = cl.post("/api/lea/leases", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _detail(cl, lid):
    return cl.get(f"/api/lea/leases/{lid}").json()


def _sync(cl):
    r = cl.post("/api/acc/sync")
    assert r.status_code == 200, r.text
    assert r.json()["errors"] == [], r.json()["errors"]
    return r.json()


def _journals(cl, lease_no):
    """Every posted journal whose memo names the lease, with its lines."""
    items = cl.get("/api/acc/journals", params={"q": lease_no, "limit": 500}).json()["items"]
    return [cl.get(f"/api/acc/journals/{j['id']}").json() for j in items if j["status"] in ("posted", "reversed")]


def _net(js, code):
    """debit − credit on one account over a list of journals."""
    return round(sum(ln["debit"] - ln["credit"] for j in js for ln in j["lines"] if ln["account_code"] == code), 3)


def _pay(cl, lid, amount, due_id=None, method="cash"):
    body = {"lease_id": lid, "amount": amount, "due_id": due_id} | ({"method": method} if method else {})
    r = cl.post("/api/lea/payments", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ----------------------------------------------------------------------------------------------------- activation and the chart
def test_nothing_posts_until_accounting_is_activated_and_the_chart_is_seeded_once(cl):
    login_as(cl, "admin")
    st = cl.get("/api/acc/status").json()
    assert st["active"] is False and st["accounts"] == 0
    assert cl.post("/api/acc/journals", json={"date": TODAY.isoformat(), "memo": "قبل التفعيل", "lines": []}).status_code == 422
    lid = _lease(cl)
    _pay(cl, lid, 300)  # a receipt before activation: the business works, the books stay empty
    assert cl.get("/api/acc/journals").json()["total"] == 0
    assert cl.post("/api/acc/activate", json={"start": TODAY.isoformat()}).status_code == 400  # needs the explicit confirmation
    assert cl.post("/api/acc/activate", json={"start": (TODAY + dt.timedelta(days=3)).isoformat(), "confirm": True}).status_code == 400
    start = _activate(cl)
    st = cl.get("/api/acc/status").json()
    assert st["active"] and st["start"] == start and st["accounts"] >= 50 and st["ledger_diff"] == 0
    assert _activate(cl) == start and cl.get("/api/acc/status").json()["accounts"] == st["accounts"]  # seeding is once
    keys = {m["key"]: m["account"] for m in cl.get("/api/acc/mapping").json()}
    assert all(keys[k] for k in keys), [k for k in keys if not keys[k]]  # every posting rule has an account to post to
    assert keys["receipts_unclassified"]["code"] == CODE["unclassified"]
    login_as(cl, "sales")
    assert cl.get("/api/acc/status").status_code == 403  # not the sales role's business


# ----------------------------------------------------------------------------------------------------- leasing events → journals
def test_a_rent_due_then_its_receipt_reach_the_books_and_nothing_posts_twice(cl):
    login_as(cl, "admin")
    start = _activate(cl)
    lid = _lease(cl, days_ago=60)
    no = _detail(cl, lid)["number"]
    res = _sync(cl)
    assert res["posted"]["dues"] >= 1
    js = _journals(cl, no)
    assert _net(js, CODE["ar"]) == 300 and _net(js, CODE["rent"]) == -300  # the first quarter fell due 60 days ago
    rent_line = next(ln for j in js for ln in j["lines"] if ln["account_code"] == CODE["rent"])
    assert rent_line["vat_class"] == "standard"  # a commercial unit: the class is carried, the VAT split waits for phase 3b
    again = _sync(cl)
    assert sum(again["posted"].values()) == 0  # idempotent: a second sweep finds nothing to post
    assert len(_journals(cl, no)) == len(js)
    due = _detail(cl, lid)["dues"][0]
    _pay(cl, lid, 300, due["id"], "cash")  # the receipt is posted in the same request — no sync needed
    js = _journals(cl, no)
    assert _net(js, CODE["ar"]) == 0 and _net(js, CODE["cash"]) == 300 and _net(js, CODE["rent"]) == -300
    st = cl.get("/api/acc/status").json()
    assert st["ledger_diff"] == 0 and st["start"] == start
    tb = cl.get("/api/acc/trial-balance").json()
    assert tb["balanced"] is True and tb["totals"]["debit"] == tb["totals"]["credit"]
    nums = [j["number"] for j in js]
    assert all(n and n.startswith(f"JV-{TODAY.year}-") for n in nums) and len(set(nums)) == len(nums)


def test_a_receipt_with_no_recorded_method_is_not_guessed_into_cash_or_bank(cl):
    login_as(cl, "admin")
    _activate(cl)
    lid = _lease(cl)
    no = _detail(cl, lid)["number"]
    _pay(cl, lid, 100, None, method=None)
    js = _journals(cl, no)
    assert _net(js, CODE["unclassified"]) == 100 and _net(js, CODE["cash"]) == 0 and _net(js, CODE["bank"]) == 0
    _pay(cl, lid, 50, None, method="transfer")
    assert _net(_journals(cl, no), CODE["bank"]) == 50


def test_reversing_a_receipt_mirrors_it_and_a_receipt_before_the_start_is_left_to_the_opening_balance(cl):
    login_as(cl, "admin")
    lid = _lease(cl, days_ago=200)  # its first dues are older than the books
    no = _detail(cl, lid)["number"]
    old = _pay(cl, lid, 50, None, "cash")  # paid today but we will move it before the start below
    _maint("UPDATE rent_payments SET paid_on=? WHERE id=?", ((TODAY - dt.timedelta(days=150)).isoformat(), old["first_id"]))
    _activate(cl, days_back=90)
    _sync(cl)
    assert _net(_journals(cl, no), CODE["cash"]) == 0  # 150 days ago < start: not posted
    p = _pay(cl, lid, 120, None, "cash")
    assert _net(_journals(cl, no), CODE["cash"]) == 120
    assert cl.post(f"/api/lea/payments/{p['first_id']}/reverse", json={"reason": "شيك مرتجع"}).status_code == 200
    js = _journals(cl, no)
    assert _net(js, CODE["cash"]) == 0  # the reversal is its own mirror journal
    assert cl.get("/api/acc/status").json()["ledger_diff"] == 0


def test_terminating_a_lease_posts_only_the_difference_for_dues_that_were_already_accrued(cl):
    login_as(cl, "admin")
    start = _activate(cl, days_back=200)
    lid = _lease(cl, days_ago=100, frequency=12, annual_rent=1200)  # monthly 100, the 4 oldest are past due
    no = _detail(cl, lid)["number"]
    _sync(cl)
    before = _net(_journals(cl, no), CODE["rent"])
    assert before <= -400
    on = (TODAY - dt.timedelta(days=90)).isoformat()
    assert cl.post(f"/api/lea/leases/{lid}/terminate", json={"on": on, "note": "إنهاء مبكر باتفاق"}).status_code == 200
    _sync(cl)
    js = _journals(cl, no)
    kept = sum(d["amount"] for d in _detail(cl, lid)["dues"] if d["kind"] == "rent")
    assert 0 < kept < -before  # the dues after the exit were cut
    assert _net(js, CODE["rent"]) == -kept and _net(js, CODE["ar"]) == kept  # revenue follows what is still owed
    assert any("تخفيض" in j["memo"] for j in js) and start  # the cut is its own reducing journal — the first accrual was never edited


def test_a_payment_plan_moves_the_debt_without_reversing_revenue(cl):
    login_as(cl, "admin")
    _activate(cl, days_back=200)
    lid = _lease(cl, days_ago=100, frequency=4)  # quarterly 300: two are past due (100 and ~9 days ago)
    no = _detail(cl, lid)["number"]
    _sync(cl)
    d = _detail(cl, lid)
    past = [x for x in d["dues"] if x["due"] <= TODAY.isoformat()]
    assert len(past) == 2
    rev0, ar0 = _net(_journals(cl, no), CODE["rent"]), _net(_journals(cl, no), CODE["ar"])
    inst = [{"due": TODAY.isoformat(), "amount": 300}, {"due": (TODAY + dt.timedelta(days=30)).isoformat(), "amount": 300}]
    r = cl.post(f"/api/lea/leases/{lid}/plans", json={"due_ids": [x["id"] for x in past], "installments": inst, "note": "اتفاق سداد"})
    assert r.status_code == 200, r.text
    _sync(cl)
    js = _journals(cl, no)
    assert _net(js, CODE["rent"]) == rev0 and _net(js, CODE["ar"]) == ar0  # the receivable is the same debt, re-scheduled: no revenue reversed or doubled
    new = [x for x in _detail(cl, lid)["dues"] if "خطة" in (x["label"] or "") and x["amount"] > x["paid"]]
    _pay(cl, lid, 300, new[0]["id"], "cash")
    js = _journals(cl, no)
    assert _net(js, CODE["ar"]) == ar0 - 300 and _net(js, CODE["rent"]) == rev0


def test_a_deposit_is_a_liability_never_revenue_and_its_settlement_releases_it(cl):
    login_as(cl, "admin")
    _activate(cl, days_back=200)
    lid = _lease(cl, days_ago=100, frequency=12, deposit=200)
    no = _detail(cl, lid)["number"]
    dep = next(d for d in _detail(cl, lid)["dues"] if d["kind"] == "deposit")
    _pay(cl, lid, 200, dep["id"], "transfer")
    js = _journals(cl, no)
    assert _net(js, CODE["deposits"]) == -200 and _net(js, CODE["bank"]) == 200
    assert not [ln for j in js for ln in j["lines"] if ln["account_code"] == CODE["rent"] and "deposit" in (j["memo"] or "")]  # a deposit is not accrued as rent
    assert cl.post(f"/api/lea/leases/{lid}/terminate", json={"on": (TODAY - dt.timedelta(days=20)).isoformat(), "note": "إنهاء بالتراضي"}).status_code == 200
    r = cl.post(f"/api/lea/leases/{lid}/deposit/settle", json={"deductions": [{"label": "إصلاح باب", "amount": 50, "ref": "فاتورة 77"}]})
    assert r.status_code == 200, r.text
    js = _journals(cl, no)
    assert _net(js, CODE["deposits"]) == 0  # fully released: 150 refunded + 50 kept against a documented repair
    assert _net(js, CODE["bank"]) == 200 - 150 and _net(js, CODE["recov"]) == -50


def test_late_payment_charity_is_a_liability_to_a_charity_not_income(cl):
    login_as(cl, "admin")
    _activate(cl, days_back=200)
    lid = _lease(cl, days_ago=90, frequency=1, charity_clause=True)
    no = _detail(cl, lid)["number"]
    due = _detail(cl, lid)["dues"][0]
    _pay(cl, lid, 1200, due["id"], "cash")
    item = next(i for i in cl.get("/api/lea/charity").json()["items"] if i["lease_id"] == lid)
    assert cl.post(f"/api/lea/charity/{item['id']}/collect", json={"reference": f"إيصال تبرع {no}"}).status_code == 200
    mine = _journals(cl, f"إيصال تبرع {no}")
    assert len(mine) == 1 and _net(mine, CODE["bank_charity"]) == item["amount"] and _net(mine, CODE["charity"]) == -item["amount"]  # cash in, owed to the charity
    assert cl.post(f"/api/lea/charity/{item['id']}/disburse", json={"reference": f"تحويل {no}", "beneficiary": "جمعية الاستقامة"}).status_code == 200
    paid = _journals(cl, f"تحويل {no}")
    assert len(paid) == 1 and _net(mine + paid, CODE["charity"]) == 0 and _net(mine + paid, CODE["bank_charity"]) == 0  # paid out: the liability and the account clear
    assert not any(ln["account_code"] == CODE["rent"] and ln["credit"] == item["amount"] for j in _journals(cl, no) for ln in j["lines"])  # and it was never rent income


def test_a_managed_units_rent_is_owner_money_and_only_the_commission_is_income(cl):
    login_as(cl, "admin")
    _activate(cl, days_back=200)
    oid = cl.post("/api/lea/owners", json={"name": f"مالك محاسبة {os.getpid()}", "kind": "third_party", "mgmt_fee_pct": 10, "mgmt_basis": "collected"}).json()["id"]
    lid = _lease(cl, owner_id=oid, days_ago=60, frequency=4)
    no = _detail(cl, lid)["number"]
    _sync(cl)
    assert _net(_journals(cl, no), CODE["rent"]) == 0 and _net(_journals(cl, no), CODE["ar"]) == 0  # not the company's revenue, not its receivable
    _pay(cl, lid, 300, _detail(cl, lid)["dues"][0]["id"], "cash")
    js = _journals(cl, no)
    assert _net(js, CODE["cash"]) == 300 and _net(js, CODE["owners"]) == -300
    period = TODAY.strftime("%Y-%m")
    r = cl.post(f"/api/lea/owners/{oid}/statements", json={"period": period})
    assert r.status_code == 200, r.text
    st = next(s for s in cl.get("/api/lea/statements", params={"owner_id": oid}).json() if s["id"] == r.json()["id"])
    own = cl.get(f"/api/acc/party/owner/{oid}").json()
    assert round(-own["balance"], 3) == round(300 - st["commission"] - st["expenses"], 3)  # what the company still owes the owner
    com_js = [cl.get(f"/api/acc/journals/{j['id']}").json() for j in cl.get("/api/acc/journals", params={"q": st["number"]}).json()["items"]]
    assert round(sum(-_net([j], CODE["fee"]) for j in com_js), 3) == round(st["commission"], 3)
    assert cl.post(f"/api/lea/statements/{st['id']}/transferred", json={"ref": "تحويل بنكي 55"}).status_code == 200
    own = cl.get(f"/api/acc/party/owner/{oid}").json()
    assert abs(own["balance"]) < 0.001 or round(-own["balance"], 3) == round(300 - st["commission"] - st["expenses"] - st["net"], 3)


def test_expenses_are_debited_to_the_right_account_and_to_the_owner_when_charged_to_him(cl):
    login_as(cl, "admin")
    _activate(cl)
    oid = cl.post("/api/lea/owners", json={"name": f"مالك محاسبة {os.getpid()}x", "kind": "third_party", "mgmt_fee_pct": 5}).json()["id"]
    uid_own, uid_mgd = _unit(), _unit(owner_id=oid)
    for uid, charge in ((uid_own, True), (uid_mgd, True)):
        r = cl.post("/api/lea/expenses", json={"unit_id": uid, "category": "صيانة مكيفات", "amount": 75, "charge_owner": charge, "description": f"محاسبة-{uid}"})
        assert r.status_code == 200, r.text
    own = [cl.get(f"/api/acc/journals/{j['id']}").json() for j in cl.get("/api/acc/journals", params={"q": f"محاسبة-{uid_own}"}).json()["items"]]
    mgd = [cl.get(f"/api/acc/journals/{j['id']}").json() for j in cl.get("/api/acc/journals", params={"q": f"محاسبة-{uid_mgd}"}).json()["items"]]
    assert _net(own, CODE["maint"]) == 75 and _net(own, CODE["vendors"]) == -75  # the company's own property: its expense
    assert _net(mgd, CODE["owners"]) == 75 and _net(mgd, CODE["maint"]) == 0  # a managed one: it reduces what the company owes the owner


# ----------------------------------------------------------------------------------------------------- manual journals
def _jl(lines, memo="قيد يدوي للاختبار", date=None):
    return {"date": (date or TODAY).isoformat(), "memo": memo, "lines": lines}


def test_manual_journal_needs_balance_then_a_different_approver_and_is_then_frozen(cl):
    login_as(cl, "finance")
    _activate_as_admin(cl)
    login_as(cl, "finance")
    bad = cl.post("/api/acc/journals", json=_jl([{"account": CODE["cash"], "debit": 100}, {"account": CODE["capital"], "credit": 90}]))
    assert bad.status_code == 400 and "متوازن" in bad.text
    assert cl.post("/api/acc/journals", json=_jl([{"account": "1000", "debit": 100}, {"account": CODE["capital"], "credit": 100}])).status_code == 400  # a header account
    jid = cl.post("/api/acc/journals", json=_jl([{"account": CODE["cash"], "debit": 100}, {"account": CODE["capital"], "credit": 100}])).json()["id"]
    assert cl.post(f"/api/acc/journals/{jid}/approve").status_code == 403  # the accountant cannot approve
    assert cl.post(f"/api/acc/journals/{jid}/submit").status_code == 200
    login_as(cl, "admin")
    r = cl.post(f"/api/acc/journals/{jid}/approve")
    assert r.status_code == 200 and r.json()["number"].startswith("JV-"), r.text
    j = cl.get(f"/api/acc/journals/{jid}").json()
    assert j["status"] == "posted" and j["approved_by"] and j["total"] == 100
    login_as(cl, "finance")
    assert cl.put(f"/api/acc/journals/{jid}", json=_jl([{"account": CODE["cash"], "debit": 1}, {"account": CODE["capital"], "credit": 1}])).status_code == 409
    assert cl.delete(f"/api/acc/journals/{jid}").status_code == 409


def _activate_as_admin(cl):
    login_as(cl, "admin")
    _activate(cl)


def test_a_large_journal_needs_an_attachment_and_an_administrator_may_approve_their_own(cl):
    login_as(cl, "admin")
    _activate(cl)
    jid = cl.post("/api/acc/journals", json=_jl([{"account": CODE["bank"], "debit": 5000}, {"account": CODE["capital"], "credit": 5000}])).json()["id"]
    r = cl.post(f"/api/acc/journals/{jid}/approve")
    assert r.status_code == 409 and "مستند" in r.text  # 5,000 ≥ the 1,000 limit and nothing is attached
    up = cl.post("/api/documents", data={"ref_type": "journal", "ref_id": str(jid), "title": "كشف البنك", "category": "محاسبة"},
                 files={"file": ("bank.pdf", b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF", "application/pdf")})
    assert up.status_code == 200, up.text
    assert cl.post(f"/api/acc/journals/{jid}/approve").status_code == 200  # an administrator's own journal is allowed; the attachment is there
    assert len(cl.get(f"/api/acc/journals/{jid}").json()["attachments"]) == 1


def test_the_database_itself_refuses_to_change_or_unbalance_a_posted_journal(cl):
    login_as(cl, "admin")
    _activate(cl)
    jid = cl.post("/api/acc/journals", json=_jl([{"account": CODE["cash"], "debit": 10}, {"account": CODE["capital"], "credit": 10}])).json()["id"]
    cl.post(f"/api/acc/journals/{jid}/approve")
    for sql in ("UPDATE acc_journals SET memo='x' WHERE id=?", "UPDATE acc_journals SET total=1 WHERE id=?", "DELETE FROM acc_journals WHERE id=?",
                "UPDATE acc_lines SET debit=99 WHERE journal_id=?", "DELETE FROM acc_lines WHERE journal_id=?",
                "INSERT INTO acc_lines(journal_id,line_no,account_id,debit,credit) SELECT journal_id,9,account_id,5,0 FROM acc_lines WHERE journal_id=? LIMIT 1"):
        with pytest.raises(Exception):  # noqa: B017 — sqlite3.IntegrityError / psycopg errors differ by engine
            _raw(sql, (jid,))
    d2 = cl.post("/api/acc/journals", json=_jl([{"account": CODE["cash"], "debit": 10}, {"account": CODE["capital"], "credit": 10}])).json()["id"]
    _raw("UPDATE acc_lines SET debit=11 WHERE journal_id=? AND debit>0", (d2,))  # a draft is free to change…
    with pytest.raises(Exception):  # noqa: B017
        _raw("UPDATE acc_journals SET status='posted', number='JV-X-1', posted_by='t', posted_at='x' WHERE id=?", (d2,))  # …but it cannot be posted unbalanced
    still = _raw("SELECT status FROM acc_journals WHERE id=?", (d2,))[0][0]
    assert still == "draft"


def test_reversing_a_manual_journal_and_an_automatic_one_cannot_be_reversed_by_hand(cl):
    login_as(cl, "admin")
    _activate(cl)
    jid = cl.post("/api/acc/journals", json=_jl([{"account": CODE["cash"], "debit": 40}, {"account": CODE["capital"], "credit": 40}])).json()["id"]
    cl.post(f"/api/acc/journals/{jid}/approve")
    assert cl.post(f"/api/acc/journals/{jid}/reverse", json={"reason": "قيد مكرر بالخطأ"}).status_code == 200
    j = cl.get(f"/api/acc/journals/{jid}").json()
    assert j["status"] == "reversed" and j["reversed_by"]
    rev = cl.get(f"/api/acc/journals/{j['reversed_by']}").json()
    assert rev["kind"] == "reversal" and rev["reversal_of"] == jid and {ln["account_code"]: (ln["debit"], ln["credit"]) for ln in rev["lines"]}[CODE["cash"]] == (0, 40)
    assert cl.post(f"/api/acc/journals/{jid}/reverse", json={"reason": "مرة ثانية"}).status_code == 409
    lid = _lease(cl)
    _pay(cl, lid, 60, None, "cash")
    auto = next(j for j in cl.get("/api/acc/journals", params={"kind": "auto", "limit": 5}).json()["items"])
    assert cl.post(f"/api/acc/journals/{auto['id']}/reverse", json={"reason": "محاولة يدوية"}).status_code == 409
    assert cl.get("/api/acc/status").json()["ledger_diff"] == 0


# ----------------------------------------------------------------------------------------------------- opening balance and periods
def test_the_opening_balance_is_one_documented_journal_dated_before_the_start(cl):
    login_as(cl, "admin")
    start = _activate(cl)
    lines = [{"code": CODE["bank"], "debit": 5000}, {"code": CODE["ar"], "debit": 700}, {"code": CODE["capital"], "credit": 5700}]
    assert cl.post("/api/acc/opening", json={"lines": lines[:2], "source": "ميزان المراجعة المدقق 2026"}).status_code == 400  # unbalanced
    r = cl.post("/api/acc/opening", json={"lines": lines, "source": "ميزان المراجعة المدقق 2026"})
    assert r.status_code == 200, r.text
    assert r.json()["date"] == (dt.date.fromisoformat(start) - dt.timedelta(days=1)).isoformat()
    assert cl.post("/api/acc/opening", json={"lines": lines, "source": "ميزان المراجعة المدقق 2026"}).status_code == 409  # once
    tb = cl.get("/api/acc/trial-balance", params={"frm": start, "to": TODAY.isoformat()}).json()
    bank = next(a for a in tb["accounts"] if a["code"] == CODE["bank"])
    assert bank["opening"] == 5000 and bank["closing"] >= 5000 and tb["balanced"] is True
    csv = cl.get("/api/acc/trial-balance", params={"csv": 1})
    assert csv.status_code == 200 and csv.content[:3] == b"\xef\xbb\xbf"


def test_a_closed_period_refuses_postings_and_reopening_needs_a_reason(cl):
    login_as(cl, "admin")
    _activate(cl)
    jid = cl.post("/api/acc/journals", json=_jl([{"account": CODE["cash"], "debit": 10}, {"account": CODE["capital"], "credit": 10}])).json()["id"]
    assert cl.post(f"/api/acc/periods/{TODAY.year}/{TODAY.month}/close").status_code == 409  # a draft is still open in it
    cl.post(f"/api/acc/journals/{jid}/approve")
    assert cl.post(f"/api/acc/periods/{TODAY.year}/{TODAY.month}/close").status_code == 200
    j2 = cl.post("/api/acc/journals", json=_jl([{"account": CODE["cash"], "debit": 10}, {"account": CODE["capital"], "credit": 10}])).json()["id"]
    assert cl.post(f"/api/acc/journals/{j2}/approve").status_code == 409  # the month is closed
    lid = _lease(cl)
    _pay(cl, lid, 25, None, "cash")  # the business is never blocked…
    assert cl.get("/api/acc/status").json()["unposted"]["counts"]["payments"] >= 1  # …but the receipt waits, visibly, until the period reopens
    assert cl.post(f"/api/acc/periods/{TODAY.year}/{TODAY.month}/reopen", json={"reason": "x"}).status_code == 400
    assert cl.post(f"/api/acc/periods/{TODAY.year}/{TODAY.month}/reopen", json={"reason": "تصحيح قيد متأخر"}).status_code == 200
    assert cl.post(f"/api/acc/journals/{j2}/approve").status_code == 200
    res = _sync(cl)
    assert res["posted"]["payments"] >= 1


def test_account_ledger_runs_a_balance_and_the_chart_can_be_extended_and_remapped(cl):
    login_as(cl, "admin")
    _activate(cl)
    new = cl.post("/api/acc/accounts", json={"code": "1122", "name": "بنك ثانٍ", "type": "asset", "parent_id": next(a["id"] for a in cl.get("/api/acc/accounts").json() if a["code"] == "1120")})
    assert new.status_code == 200, new.text
    assert cl.post("/api/acc/accounts", json={"code": "1122", "name": "مكرر", "type": "asset"}).status_code == 409
    accs = {a["code"]: a for a in cl.get("/api/acc/accounts").json()}
    assert cl.patch(f"/api/acc/accounts/{new.json()['id']}", json={"system_key": "bank_main"}).status_code == 409  # held by 1121
    assert cl.patch(f"/api/acc/accounts/{accs['1121']['id']}", json={"active": False}).status_code == 409  # mapped to events: re-map first
    for amt in (100, 50):
        j = cl.post("/api/acc/journals", json=_jl([{"account": "1122", "debit": amt}, {"account": CODE["capital"], "credit": amt}])).json()["id"]
        cl.post(f"/api/acc/journals/{j}/approve")
    led = cl.get(f"/api/acc/ledger/{new.json()['id']}").json()
    assert [ln["balance"] for ln in led["lines"]] == [100, 150] and led["closing"] == 150
    hdr = cl.get(f"/api/acc/ledger/{accs['1120']['id']}").json()  # a header collects its children
    assert hdr["closing"] >= 150
    assert cl.get(f"/api/acc/ledger/{new.json()['id']}", params={"csv": 1}).status_code == 200
