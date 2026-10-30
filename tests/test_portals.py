"""0.28.0 — portals, reports and assistant across the modules.

* the tenant's portal: ownership is checked on every endpoint (another tenant's lease/receipt/cheque/notice/maintenance answers 404, never a leak), drafts are the office's, other roles
  cannot enter it and the tenant cannot enter theirs;
* the employee's portal: the new attendance and loans views show only the signed-in employee's rows;
* the manager's portal: aging / expiring / vacant / maintenance stay inside the scope;
* ready reports and datasets of accounting and HR: gated by module and by the permission (the broad `reports` permission does not open the books or the people file), payroll never
  mailed, a schedule runs with its owner's current permissions;
* the assistant: the new tools exist only for the modules that are on and the permissions that allow them; payroll figures only for `hr_payroll`;
* the dashboard is built from the widgets registry and each viewer gets only the tiles their permissions allow.
"""
import datetime as dt
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "portals.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "bayan:بيان عمان;almaqsura:المقصورة العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect, init  # noqa: E402

CSRF = "csrf-portals-" + "p" * 27
TODAY = dt.date.today()
_N = [0]
_UNITS = "SELECT id FROM units WHERE code LIKE 'T-POR-%'"
_LEASES = f"SELECT id FROM leases WHERE unit_id IN ({_UNITS})"
HR_TABLES = ("disciplinary_cases", "penalty_rules", "training_records", "training_courses", "appraisals", "appraisal_cycles", "interviews", "candidates", "job_openings", "terminations", "eosb_rules",
             "loan_installments", "employee_loans", "payroll_adjustments", "payslips", "payroll_runs", "salary_lines", "salary_structures", "pay_components", "hr_rates", "hr_requests", "attendance",
             "holidays", "leave_requests", "leave_balances", "leave_types", "employee_documents", "employees", "positions", "departments")


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


def _sql(sql, args=(), tenant="bayan"):
    tok = TENANT.set(tenant)
    try:
        c = connect()
        try:
            r = c.execute(sql, args)
            out = r.fetchall() if sql.lstrip().upper().startswith("SELECT") else None
            c.commit()
            return out
        finally:
            c.close()
    finally:
        TENANT.reset(tok)


def _purge():
    tok = TENANT.set("bayan")
    try:
        c = connect()
        pg = getattr(c, "dialect", "sqlite") == "postgres"
        sc = " AND org_id = current_setting('app.org_id', true)" if pg else ""
        c.maintenance()
        c.execute(f"UPDATE users SET employee_id=NULL WHERE employee_id IS NOT NULL{sc}")
        c.execute(f"UPDATE users SET lessee_id=NULL WHERE lessee_id IS NOT NULL{sc}")
        c.execute(f"DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'emp%' OR username LIKE 'ten%' OR username LIKE 'pmp-%' OR username LIKE 'por-%'){sc}")
        c.execute(f"DELETE FROM user_scopes WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'pmp-%'){sc}")
        c.execute(f"DELETE FROM users WHERE username LIKE 'emp%' OR username LIKE 'ten%' OR username LIKE 'pmp-%' OR username LIKE 'por-%'{sc}")
        c.execute(c.wipe_sql("departments").replace("DELETE FROM departments", "UPDATE departments SET head_employee_id=NULL"))
        for t in HR_TABLES:
            c.execute(c.wipe_sql(t))
        stmts = [f"DELETE FROM arrears_notices WHERE lease_id IN ({_LEASES}{sc})", f"DELETE FROM maint_requests WHERE unit_id IN ({_UNITS}{sc})",
                 f"DELETE FROM rent_payments WHERE lease_id IN ({_LEASES}{sc})", f"DELETE FROM cheques WHERE lease_id IN ({_LEASES}{sc})",
                 f"DELETE FROM lease_events WHERE lease_id IN ({_LEASES}{sc})", f"DELETE FROM lease_terms WHERE lease_id IN ({_LEASES}{sc})", f"DELETE FROM rent_dues WHERE lease_id IN ({_LEASES}{sc})",
                 f"DELETE FROM tenants_l WHERE id IN (SELECT tenant_id FROM leases WHERE unit_id IN ({_UNITS}{sc})){sc}", f"DELETE FROM leases WHERE unit_id IN ({_UNITS}{sc})",
                 f"DELETE FROM units WHERE code LIKE 'T-POR-%'{sc}", f"DELETE FROM report_schedules{'' if not pg else ' WHERE true' + sc}", f"DELETE FROM report_defs WHERE name LIKE 'اختبار-%'{sc}",
                 f"DELETE FROM doc_issues WHERE kind IN ('lease','rent_receipt','cheque_receipt','arrears_notice'){sc}", f"DELETE FROM settings WHERE k LIKE 'hr:%'{sc}", f"DELETE FROM counters WHERE k LIKE 'hr:%'{sc}"]
        for s in stmts:
            c.execute(s)
        c.commit()
        c.end_maintenance()
        if not pg:
            init(c)
        c.close()
    finally:
        TENANT.reset(tok)


@pytest.fixture()
def cl():
    from backend import observability as O
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        _purge()
        for t in ("jadwa", "bayan", "almaqsura"):
            _sql("DELETE FROM login_attempts", tenant=t)
        yield c


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    _purge()


# ----------------------------------------------------------------------------------------------------- helpers
def _unit():
    tok = TENANT.set("bayan")
    try:
        c = connect()
        _N[0] += 1
        row = c.execute("SELECT project_id FROM units WHERE retained=1 ORDER BY project_id LIMIT 1").fetchone()
        uid = c.execute("INSERT INTO units(project_id,code,type,area,status,retained,use) VALUES(?,?,?,?,?,?,?)", (row[0], f"T-POR-{_N[0]:03d}", "مكتب", 60, "a", 1, "commercial")).lastrowid
        c.commit()
        c.close()
        return uid
    finally:
        TENANT.reset(tok)


def _lease(cl, name, idn, **kw):
    login_as(cl, "admin")
    body = {"unit_id": _unit(), "tenant": {"name": name, "phone": "+968 91234567", "id_number": idn}, "start": (TODAY - dt.timedelta(days=60)).isoformat(), "months": 12, "annual_rent": 1200,
            "frequency": 4, "sign": True} | kw
    r = cl.post("/api/lea/leases", json=body)
    assert r.status_code == 200, r.text
    lid = r.json()["id"]
    return lid, cl.get(f"/api/lea/leases/{lid}").json()["tenant_id"]


def _tenant_login(cl, tid):
    login_as(cl, "admin")
    r = cl.post(f"/api/lea/tenants/{tid}/account")
    assert r.status_code == 200, r.text
    un = r.json()["username"]
    _sql("UPDATE users SET must_change=0 WHERE username=?", (un,))
    return un


@pytest.fixture()
def two_tenants(cl):
    a_lease, a_tid = _lease(cl, "المستأجر الأول", "POR111")
    b_lease, b_tid = _lease(cl, "المستأجر الثاني", "POR222")
    # B has a receipt, a cheque and a delivered arrears notice — A must not be able to reach any of them
    pay = cl.post("/api/lea/payments", json={"lease_id": b_lease, "amount": 100, "method": "cash"}).json()
    chq = cl.post("/api/lea/cheques", json={"lease_id": b_lease, "number": "POR-CQ-1", "bank": "بنك مسقط", "amount": 100, "due_date": (TODAY + dt.timedelta(days=30)).isoformat()}).json()
    note = cl.post(f"/api/lea/leases/{b_lease}/notices", json={"kind": "formal", "cure_days": 10}).json()
    cl.post(f"/api/lea/notices/{note['id']}/sent", json={"via": "hand"})
    draft, _ = _lease(cl, "المستأجر الأول", "POR111", sign=False, start="2036-01-01")   # A's own draft (same tenant file) — still the office's, not shown
    return {"a": (a_lease, a_tid, _tenant_login(cl, a_tid)), "b": (b_lease, b_tid, _tenant_login(cl, b_tid)), "pay": pay["first_id"], "chq": chq["id"], "note": note["id"], "draft": draft}


# ----------------------------------------------------------------------------------------------------- the tenant's portal
def test_a_tenant_sees_only_their_own_file(cl, two_tenants):
    a_lease, _a_tid, a_user = two_tenants["a"]
    b_lease, _b_tid, b_user = two_tenants["b"]
    login_as(cl, a_user)
    me = cl.get("/api/lessee/me").json()
    assert me["name"] == "المستأجر الأول" and me["leases"] >= 1
    leases = cl.get("/api/lessee/leases").json()
    assert {x["id"] for x in leases} == {a_lease}   # his own signed lease; the draft and the other tenant's are not listed
    d = cl.get(f"/api/lessee/leases/{a_lease}")
    assert d.status_code == 200 and d.json()["number"]
    leaked = {"owner", "events", "rating", "rating_note", "blacklisted", "tenant", "created_by", "source"}
    assert not leaked & set(d.json())
    assert cl.get(f"/api/lessee/leases/{b_lease}").status_code == 404                # another tenant's lease: 404, same as one that does not exist
    assert cl.get("/api/lessee/leases/999999").status_code == 404
    assert cl.get(f"/api/lessee/leases/{two_tenants['draft']}").status_code == 404   # his own draft is the office's
    st = cl.get("/api/lessee/statement").json()
    assert st["tenant"] == "المستأجر الأول" and {x["lease_id"] for x in st["leases"]} == {a_lease}
    # documents: his lease yes, the other tenant's receipt / cheque / notice / lease no
    assert cl.get(f"/api/lessee/docs/lease/{a_lease}.pdf").content[:4] == b"%PDF"
    for kind, ref in (("lease", b_lease), ("rent_receipt", two_tenants["pay"]), ("cheque_receipt", two_tenants["chq"]), ("arrears_notice", two_tenants["note"]), ("lease", two_tenants["draft"])):
        assert cl.get(f"/api/lessee/docs/{kind}/{ref}.pdf").status_code == 404, (kind, ref)
    assert cl.get("/api/lessee/docs/receipt/1.pdf").status_code == 404 and cl.get("/api/lessee/docs/owner_statement/1.pdf").status_code == 404   # kinds that are not a tenant's
    assert cl.get("/api/lessee/notices").json() == []
    # and the other way round: B sees his own receipt, cheque and delivered notice
    login_as(cl, b_user)
    bd = cl.get(f"/api/lessee/leases/{b_lease}").json()
    assert bd["payments"] and bd["payments"][0]["pdf"] and bd["cheques"][0]["pdf"]
    assert cl.get(bd["payments"][0]["pdf"]).content[:4] == b"%PDF" and cl.get(bd["cheques"][0]["pdf"]).content[:4] == b"%PDF"
    n = cl.get("/api/lessee/notices").json()
    assert len(n) == 1 and cl.get(n[0]["pdf"]).content[:4] == b"%PDF"
    assert cl.get(f"/api/lessee/leases/{a_lease}").status_code == 404


def test_a_tenant_files_maintenance_only_on_their_own_active_lease(cl, two_tenants):
    a_lease, _tid, a_user = two_tenants["a"]
    b_lease, _btid, b_user = two_tenants["b"]
    login_as(cl, a_user)
    body = {"lease_id": a_lease, "category": "سباكة", "description": "تسرّب في حوض الغسيل"}
    r = cl.post("/api/lessee/maintenance", json=body)
    assert r.status_code == 200 and r.json()["sla_due"] == (TODAY + dt.timedelta(days=7)).isoformat()
    assert cl.post("/api/lessee/maintenance", json=body | {"urgent": True}).json()["sla_due"] == (TODAY + dt.timedelta(days=1)).isoformat()
    assert cl.post("/api/lessee/maintenance", json=body | {"lease_id": b_lease}).status_code == 404       # not his lease
    assert cl.post("/api/lessee/maintenance", json=body | {"lease_id": two_tenants["draft"]}).status_code == 404
    assert cl.post("/api/lessee/maintenance", json=body | {"category": "ما يشاء"}).status_code == 422
    assert cl.post("/api/lessee/maintenance", json=body | {"extra": 1}).status_code == 422
    mine = cl.get("/api/lessee/maintenance").json()
    assert len(mine) == 2 and all(m["lease_no"] for m in mine) and mine[0]["status_label"] == "جديد"
    login_as(cl, b_user)
    assert cl.get("/api/lessee/maintenance").json() == []                                             # B sees none of A's
    login_as(cl, "admin")
    office = [m for m in cl.get("/api/lea/maint").json() if m["source"] == "tenant"]
    assert len(office) == 2 and office[0]["requester"] == "المستأجر الأول"                              # the office receives it like any request


def test_privacy_consent_is_the_tenants_own(cl, two_tenants):
    _l, _t, a_user = two_tenants["a"]
    login_as(cl, a_user)
    me = cl.get("/api/lessee/me").json()
    assert me["consent_required"] == "1.0" and me["consent_at"] is None
    assert cl.post("/api/lessee/consent", json={"version": "1.0", "accept": False}).status_code == 400
    assert cl.post("/api/lessee/consent", json={"version": "0.1", "accept": True}).status_code == 409
    assert cl.post("/api/lessee/consent", json={"version": "1.0", "accept": True}).status_code == 200
    me = cl.get("/api/lessee/me").json()
    assert me["consent_required"] is None and me["consent_at"]


def test_the_portal_is_closed_to_everyone_else_and_the_tenant_to_everything_else(cl, two_tenants):
    _l, _t, a_user = two_tenants["a"]
    for who in ("admin", "finance", "sales"):
        login_as(cl, who)
        assert cl.get("/api/lessee/leases").status_code == 403, who
    login_as(cl, a_user)
    for path in ("/api/lea/leases", "/api/lea/tenants", "/api/pm/overview", "/api/portal", "/api/hr/me", "/api/hr/employees", "/api/acc/status", "/api/reports/catalog", "/api/dashboard",
                 "/api/users", "/api/audit", "/api/lea/maint"):
        assert cl.get(path).status_code == 403, path
    assert cl.get("/api/me").json()["perms"] == ["lessee"]
    # a login with the role but no linked file sees nothing, and says why
    _sql("INSERT INTO users(username,name,role,pw,must_change) VALUES('por-orphan','بلا ملف','lessee',?,0)", (A.hash_pw("Orphan-Pass-2026"),))
    login_as(cl, "por-orphan")
    assert cl.get("/api/lessee/leases").status_code == 404 and cl.get("/api/lessee/me").status_code == 404
    # one login per tenant file; the office can reset it
    login_as(cl, "admin")
    assert cl.post(f"/api/lea/tenants/{two_tenants['a'][1]}/account").status_code == 409
    r = cl.post(f"/api/lea/tenants/{two_tenants['a'][1]}/account/reset")
    assert r.status_code == 200 and r.json()["temporary_password"]
    assert cl.get(f"/api/lea/tenants/{two_tenants['a'][1]}/account").json()["exists"] is True


# ----------------------------------------------------------------------------------------------------- the employee's portal
def _employee_with_login(cl, name, number_hint):
    login_as(cl, "admin")
    r = cl.post("/api/hr/employees", json={"name": name, "omani": True, "hire_date": (TODAY - dt.timedelta(days=400)).isoformat(), "gender": "male", "email": f"{number_hint}@example.test"})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    un = cl.post(f"/api/hr/employees/{eid}/account").json()["username"]
    _sql("UPDATE users SET must_change=0 WHERE username=?", (un,))
    return eid, un


def test_an_employee_sees_only_their_own_attendance_and_loans(cl):
    e1, u1 = _employee_with_login(cl, "موظف أول", "por1")
    e2, u2 = _employee_with_login(cl, "موظف ثانٍ", "por2")
    month = TODAY.isoformat()[:7]
    for eid, st in ((e1, "present"), (e2, "absent")):
        _sql("INSERT INTO attendance(employee_id,day,status,source) VALUES(?,?,?,'manual')", (eid, f"{month}-01", st))
    _sql("INSERT INTO employee_loans(employee_id,kind,amount,installments,start_period,status) VALUES(?,?,?,?,?,?)", (e2, "advance", 300, 3, month, "active"))
    lid = _sql("SELECT id FROM employee_loans WHERE employee_id=?", (e2,))[0][0]
    for i in range(3):
        _sql("INSERT INTO loan_installments(loan_id,no,period,amount,status) VALUES(?,?,?,?,?)", (lid, i + 1, month, 100, "due"))
    login_as(cl, u1)
    a = cl.get("/api/hr/me/attendance").json()
    assert a["month"] == month and [d["status"] for d in a["days"]] == ["present"] and a["counts"] == {"present": 1}
    assert cl.get("/api/hr/me/loans").json() == []                       # the other employee's loan is not his
    login_as(cl, u2)
    ln = cl.get("/api/hr/me/loans").json()
    assert len(ln) == 1 and ln[0]["remaining"] == 300 and len(ln[0]["schedule"]) == 3
    assert [d["status"] for d in cl.get("/api/hr/me/attendance").json()["days"]] == ["absent"]
    assert cl.get("/api/hr/me/attendance?month=2000-01").json()["days"] == []
    for path in ("/api/hr/employees", "/api/hr/payroll/runs", "/api/lessee/leases", "/api/lea/leases", "/api/reports/catalog"):
        assert cl.get(path).status_code == 403, path


# ----------------------------------------------------------------------------------------------------- the property manager's portal
def test_the_managers_new_views_stay_inside_their_scope(cl):
    login_as(cl, "admin")
    mine_lease, _ = _lease(cl, "مستأجر داخل النطاق", "POR333")
    other_lease, _ = _lease(cl, "مستأجر خارج النطاق", "POR444")
    mine_unit = _sql("SELECT unit_id, (SELECT project_id FROM units WHERE id=leases.unit_id) FROM leases WHERE id=?", (mine_lease,))[0]
    other_unit = _sql("SELECT unit_id FROM leases WHERE id=?", (other_lease,))[0][0]
    owner_a = cl.post("/api/lea/owners", json={"name": "مالك اختبار أ", "kind": "third_party"}).json()["id"]
    owner_b = cl.post("/api/lea/owners", json={"name": "مالك اختبار ب", "kind": "third_party"}).json()["id"]
    _sql("UPDATE units SET owner_id=? WHERE id=?", (owner_a, mine_unit[0]))
    _sql("UPDATE units SET owner_id=? WHERE id=?", (owner_b, other_unit))
    r = cl.post("/api/users", json={"username": "pmp-one", "name": "مدير اختبار", "role": "property_manager"})
    assert r.status_code == 200, r.text
    _sql("UPDATE users SET must_change=0 WHERE username='pmp-one'")
    uid = _sql("SELECT id FROM users WHERE username='pmp-one'")[0][0]
    assert cl.post("/api/lea/scopes", json={"user_id": uid, "owner_id": owner_a}).status_code == 200
    for lid, uc in ((mine_lease, 1), (other_lease, 2)):   # both leases: late dues, a delivered ending soon, a maintenance request
        unit_id = _sql("SELECT unit_id FROM leases WHERE id=?", (lid,))[0][0]
        _sql("INSERT INTO maint_requests(unit_id,lease_id,source,category,description,priority,status,created,updated,sla_due) VALUES(?,?,?,?,?,?,?,?,?,?)",
             (unit_id, lid, "staff", "كهرباء", f"طلب {uc}", "normal", "new", "2026-01-01", "2026-01-01", "2026-01-08"))
        _sql('UPDATE leases SET "end"=? WHERE id=?', ((TODAY + dt.timedelta(days=40)).isoformat(), lid))
    login_as(cl, "pmp-one")
    ag = cl.get("/api/pm/aging").json()
    assert {x["number"] for x in ag["leases"]} == {cl.get(f"/api/pm/leases/{mine_lease}").json()["number"]} and ag["total"] > 0
    ex = cl.get("/api/pm/expiring").json()
    assert [x["id"] for x in ex] == [mine_lease] and ex[0]["days_left"] == 40
    mt = cl.get("/api/pm/maint").json()
    assert len(mt) == 1 and mt[0]["description"] == "طلب 1" and mt[0]["late"] is True
    assert all(v["code"] != _sql("SELECT code FROM units WHERE id=?", (other_unit,))[0][0] for v in cl.get("/api/pm/vacant").json())
    assert cl.get("/api/lessee/leases").status_code == 403 and cl.get("/api/lea/maint").status_code == 403


# ----------------------------------------------------------------------------------------------------- reports
def test_new_ready_reports_follow_module_and_permission(cl):
    login_as(cl, "admin")
    cat = cl.get("/api/reports/catalog").json()
    keys = {r["key"] for r in cat["ready"]}
    assert {"acc_trial", "acc_income", "acc_balance", "acc_payables", "acc_vat", "hr_headcount", "hr_leave", "hr_expiry", "hr_attendance", "hr_training", "hr_payroll"} <= keys
    assert {"leases", "rent_dues", "rent_payments", "journal_lines", "employees", "leave_requests", "training", "payslips"} <= {d["key"] for d in cat["datasets"]}
    for k in ("acc_trial", "acc_income", "acc_balance", "acc_payables", "acc_vat", "hr_headcount", "hr_leave", "hr_expiry", "hr_attendance", "hr_training", "hr_payroll"):
        r = cl.get(f"/api/reports/ready/{k}")
        assert r.status_code == 200, (k, r.text)
        assert r.json()["title"] and "tables" in r.json()
        pdf = cl.post("/api/reports/export", json={"format": "pdf", "kind": "ready", "ref": k})
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF", k
    # the broad `reports` permission (investor) does not open the books or the people file
    login_as(cl, "investor1")
    assert not {r["key"] for r in cl.get("/api/reports/catalog").json()["ready"]} & {"acc_trial", "hr_headcount", "hr_payroll"}
    for k in ("acc_trial", "hr_headcount", "hr_payroll"):
        assert cl.get(f"/api/reports/ready/{k}").status_code == 403, k
    assert cl.post("/api/reports/custom/run", json={"dataset": "employees"}).status_code == 403
    # an HR officer reads people reports and datasets, not the books and not payroll
    _sql("INSERT INTO users(username,name,role,pw,must_change) VALUES('por-hr','مسؤول','hr',?,0)", (A.hash_pw("Hr-Pass-2026-x"),))
    login_as(cl, "por-hr")
    assert cl.get("/api/reports/ready/hr_headcount").status_code == 200 and cl.get("/api/reports/ready/acc_trial").status_code == 403
    assert cl.get("/api/reports/ready/hr_payroll").status_code == 403
    assert cl.post("/api/reports/custom/run", json={"dataset": "employees"}).status_code == 200
    assert cl.post("/api/reports/custom/run", json={"dataset": "payslips"}).status_code == 403
    # an accountant reads the books, not the people
    login_as(cl, "finance")
    _sql("INSERT INTO users(username,name,role,pw,must_change) VALUES('por-acct','محاسب','accountant',?,0)", (A.hash_pw("Acct-Pass-2026-x"),))
    login_as(cl, "por-acct")
    assert cl.get("/api/reports/ready/acc_trial").status_code == 200 and cl.get("/api/reports/ready/hr_headcount").status_code == 403
    # the payroll officer reads the payroll summary and nothing else of the catalogue
    _sql("INSERT INTO users(username,name,role,pw,must_change) VALUES('por-pay','رواتب','payroll',?,0)", (A.hash_pw("Pay-Pass-2026-x"),))
    login_as(cl, "por-pay")
    assert {r["key"] for r in cl.get("/api/reports/catalog").json()["ready"]} == {"hr_payroll"}
    assert cl.get("/api/reports/ready/hr_payroll").status_code == 200 and cl.get("/api/reports/ready/hr_headcount").status_code == 403


def test_accounting_reports_match_the_books(cl):
    login_as(cl, "admin")
    lid, _t = _lease(cl, "مستأجر الدفاتر", "POR666")
    assert cl.post("/api/lea/payments", json={"lease_id": lid, "amount": 100, "method": "cash"}).status_code == 200
    if not _sql("SELECT 1 FROM settings WHERE k='acc_start' AND v<>''"):   # nothing posted before activation (the module's state persists across tests of this file)
        assert "غير مفعَّلة" in cl.get("/api/reports/ready/acc_trial").json()["subtitle"]
    start = (TODAY - dt.timedelta(days=90)).isoformat()
    assert cl.post("/api/acc/activate", json={"start": start, "confirm": True}).status_code == 200
    assert cl.post("/api/acc/sync").status_code == 200   # the dues and the payment above become balanced entries
    tb = cl.get(f"/api/acc/trial-balance?frm={start}&to={TODAY.isoformat()}").json()
    rep = cl.get(f"/api/reports/ready/acc_trial?from={start}&to={TODAY.isoformat()}").json()
    assert rep["kpis"][0]["value"] == tb["totals"]["debit"] and rep["kpis"][1]["value"] == tb["totals"]["credit"] and rep["kpis"][2]["value"] == 0
    assert len(rep["tables"][0]["rows"]) == len([a for a in tb["accounts"] if a["postable"]])
    bs = cl.get("/api/reports/ready/acc_balance").json()
    assert bs["kpis"][3]["value"] == 0   # assets = liabilities + equity
    ds = cl.post("/api/reports/custom/run", json={"dataset": "journal_lines", "aggs": [{"fn": "sum", "col": "debit"}, {"fn": "sum", "col": "credit"}]}).json()["tables"][0]["rows"][0]
    assert ds["sum_debit"] and round(ds["sum_debit"], 3) == round(ds["sum_credit"], 3)   # the ledger has entries and balances


def test_hr_reports_count_the_people_file(cl):
    login_as(cl, "admin")
    for n, om in (("أول", True), ("ثانٍ", False), ("ثالث", True)):
        assert cl.post("/api/hr/employees", json={"name": f"موظف {n}", "omani": om, "hire_date": (TODAY - dt.timedelta(days=800)).isoformat(), "gender": "male"}).status_code == 200
    h = cl.get("/api/reports/ready/hr_headcount").json()
    assert h["kpis"][0]["value"] == 3 and h["kpis"][1]["value"] == 66.7 and h["kpis"][3]["value"] == 0
    assert sum(r["total"] for r in h["tables"][0]["rows"]) == 3
    ds = cl.post("/api/reports/custom/run", json={"dataset": "employees", "columns": ["number", "name", "omani"]}).json()
    assert len(ds["tables"][0]["rows"]) == 3 and set(ds["tables"][0]["rows"][0]) == {"number", "name", "omani"}
    cols = {c["key"] for c in [d for d in cl.get("/api/reports/catalog").json()["datasets"] if d["key"] == "employees"][0]["columns"]}
    assert not cols & {"id_number", "dob", "iban", "social_ins_no", "bank_name", "emergency_contact", "phone", "email", "address"}   # the dataset carries no identity or bank field
    lv = cl.get("/api/reports/ready/hr_leave").json()
    assert lv["tables"][0]["rows"] and all("remaining" in r for r in lv["tables"][0]["rows"])


def test_payroll_is_never_mailed_and_a_schedule_runs_as_its_owner(cl, monkeypatch):
    from backend import mail, reports
    sent = []
    monkeypatch.setattr(mail, "available", lambda: True)
    monkeypatch.setattr(mail, "send", lambda to, subject, body, **kw: sent.append((to, subject)))
    login_as(cl, "admin")
    rid = cl.post("/api/reports/saved", json={"name": "اختبار-رواتب", "kind": "ready", "ref": "hr_payroll"}).json()["id"]
    r = cl.post("/api/reports/schedules", json={"report_id": rid, "cadence": "daily", "recipients": "boss@example.test"})
    assert r.status_code == 409 and "الرواتب" in r.text
    pid = cl.post("/api/reports/saved", json={"name": "اختبار-رواتب-مخصص", "kind": "custom", "spec": {"dataset": "payslips"}}).json()["id"]
    assert cl.post("/api/reports/schedules", json={"report_id": pid, "cadence": "daily", "recipients": "boss@example.test"}).status_code == 409
    hid = cl.post("/api/reports/saved", json={"name": "اختبار-قوى", "kind": "ready", "ref": "hr_headcount"}).json()["id"]
    sid = cl.post("/api/reports/schedules", json={"report_id": hid, "cadence": "daily", "recipients": "boss@example.test", "format": "csv"}).json()["id"]
    # an accountant cannot schedule a people report he cannot read
    _sql("INSERT INTO users(username,name,role,pw,must_change) VALUES('por-acct2','محاسب','accountant',?,0)", (A.hash_pw("Acct-Pass-2026-y"),))
    login_as(cl, "por-acct2")
    assert cl.post("/api/reports/schedules", json={"report_id": hid, "cadence": "daily", "recipients": "boss@example.test"}).status_code in (403, 404)
    # the schedule runs with the owner's *current* permissions: deactivate the owner and it stops, with a recorded reason
    tok = TENANT.set("bayan")
    try:
        c = connect()
        c.execute("UPDATE report_schedules SET next_run='2000-01-01T00:00' WHERE id=?", (sid,))
        c.commit()
        assert reports.run_due_schedules(c) == 1 and len(sent) == 1
        _sql("UPDATE users SET active=0 WHERE username='admin'")
        c.execute("UPDATE report_schedules SET next_run='2000-01-01T00:00' WHERE id=?", (sid,))
        c.commit()
        assert reports.run_due_schedules(c) == 0 and len(sent) == 1
        assert "لم يعد مفعَّلًا" in c.execute("SELECT last_error FROM report_schedules WHERE id=?", (sid,)).fetchone()[0]
        c.close()
    finally:
        _sql("UPDATE users SET active=1 WHERE username='admin'")
        TENANT.reset(tok)


# ----------------------------------------------------------------------------------------------------- assistant
def _u(perms, modules, **kw):
    return {"id": 1, "name": "اختبار", "perms": perms, "modules": modules, **kw}


def test_assistant_tools_exist_only_for_enabled_modules_and_allowed_permissions():
    from backend import assistant as AS
    assert AS._allowed(_u(["accounting"], ["accounting", "finance"]), "accounting")
    assert not AS._allowed(_u(["accounting"], ["finance"]), "accounting")                       # module off
    assert not AS._allowed(_u(["view", "finance"], ["accounting", "finance"]), "accounting")    # no permission
    assert AS._allowed(_u(["hr"], ["hr"]), "hr") and AS._allowed(_u(["hr_self"], ["hr"]), "hr")
    assert not AS._allowed(_u(["hr"], ["leasing"]), "hr")
    assert not AS._allowed(_u(["view"], ["hr"]), "hr")
    names = {t["name"] for t in AS._tool_defs(_u(["view", "leasing"], ["leasing", "finance"]))}
    assert "leasing" in names and not names & {"accounting", "hr", "leads", "bookings"}
    names = {t["name"] for t in AS._tool_defs(_u(["view", "accounting", "hr"], ["accounting", "hr", "finance"]))}
    assert {"accounting", "hr"} <= names


def test_assistant_answers_from_the_new_tools(cl):
    login_as(cl, "admin")
    lid, _ = _lease(cl, "مستأجر المساعد", "POR555")
    cl.post("/api/lea/cheques", json={"lease_id": lid, "number": "AS-1", "bank": "بنك مسقط", "amount": 100, "due_date": (TODAY + dt.timedelta(days=3)).isoformat()})
    r = cl.post("/api/assistant", json={"q": "ما المتأخرات والشيكات؟"}).json()
    assert "شيكات" in r["answer"] and "متأخرات" in r["answer"]
    r = cl.post("/api/assistant", json={"q": "كم موظف لدينا ونسبة العمانيين؟"}).json()
    assert r["intent"] == "hr" and "على رأس العمل" in r["answer"]
    r = cl.post("/api/assistant", json={"q": "هل الميزان متوازن؟"}).json()
    assert r["intent"] == "accounting" and "المحاسبة" in r["source"]
    # a sales user is told the topic is outside their role; a user of another module is not told that
    login_as(cl, "sales")
    assert "خارج صلاحيات" in cl.post("/api/assistant", json={"q": "ما رصيد البنك والميزان؟"}).json()["answer"]
    # a leasing-only organisation asking about arrears gets the leasing answer, not "outside your permissions"
    login_as(cl, "admin", "almaqsura")
    r = cl.post("/api/assistant", json={"q": "ما المتأخرات؟"}).json()
    assert "خارج صلاحيات" not in r["answer"] and "متأخرات" in r["answer"]
    assert "المحاسبة" not in cl.post("/api/assistant", json={"q": "هل الميزان متوازن؟"}).json()["source"]   # accounting is not part of the Almaqsura bundle


def test_assistant_hides_payroll_unless_hr_payroll_and_local(cl):
    from backend import assistant as AS
    login_as(cl, "admin")
    _sql("INSERT INTO payroll_runs(period,status,headcount,gross,net) VALUES('2026-09','approved',3,1500,1400)")
    tok = TENANT.set("bayan")
    try:
        c = connect()
        full = _u(["hr", "hr_payroll", "hr_self", "view"], ["hr"])
        hr_only = _u(["hr", "hr_self", "view"], ["hr"])
        t_full = AS.run_tool(AS.Ctx(c, full), "hr", {})
        assert "مسيّر" in t_full["text"] and t_full["data"]["payroll"]["gross"] == 1500
        assert "مسيّر" not in AS.run_tool(AS.Ctx(c, hr_only), "hr", {})["text"]                          # HR without payroll
        assert "مسيّر" not in AS.run_tool(AS.Ctx(c, full, external=True), "hr", {})["text"]               # never to an external model
        c.close()
    finally:
        TENANT.reset(tok)


def test_an_employee_can_ask_about_their_own_leave_only(cl):
    _eid, un = _employee_with_login(cl, "موظف المساعد", "porask")
    login_as(cl, un)
    r = cl.post("/api/assistant", json={"q": "ما رصيد إجازتي؟"})
    assert r.status_code == 200 and "رصيد إجازاتك" in r.json()["answer"]
    r = cl.post("/api/assistant", json={"q": "كم موظف لدينا؟"}).json()
    assert "على رأس العمل" not in r["answer"]                      # no organisation figures for someone without the HR permission
    r = cl.post("/api/assistant", json={"q": "ما ملخص المحفظة؟"}).json()
    assert "خارج صلاحيات" in r["answer"] or "لم أفهم" in r["answer"]


# ----------------------------------------------------------------------------------------------------- dashboard
def test_the_dashboard_is_built_from_the_widgets_registry_and_filtered_per_viewer(cl):
    from backend import orgmodules
    assert list(orgmodules.WIDGETS) == ["sales", "finance", "leasing", "accounting", "hr"]
    login_as(cl, "admin")
    ids = {t["id"] for t in cl.get("/api/dashboard").json()["tiles"]}
    assert {"hr_head", "hr_expiry", "occupancy", "sales30"} <= ids and ids & {"acc_off", "acc_cash"}   # the books tile is "not active yet" or the real figures, depending on the state
    login_as(cl, "sales")
    ids = {t["id"] for t in cl.get("/api/dashboard").json()["tiles"]}
    assert "sales30" in ids and not ids & {"acc_off", "acc_cash", "acc_net", "acc_ap", "hr_head", "hr_payroll"}                # the books and the people are not for every viewer of the dashboard
    _sql("INSERT INTO payroll_runs(period,status,headcount,gross,net) VALUES('2026-09','approved',3,1500,1400)")
    login_as(cl, "por-hr") if _sql("SELECT 1 FROM users WHERE username='por-hr'") else None
    _sql("INSERT INTO users(username,name,role,pw,must_change) SELECT 'por-hr2','مسؤول','hr',?,0 WHERE NOT EXISTS (SELECT 1 FROM users WHERE username='por-hr2')", (A.hash_pw("Hr-Pass-2026-z"),))
    login_as(cl, "por-hr2")
    ids = {t["id"] for t in cl.get("/api/dashboard").json()["tiles"]}
    assert "hr_head" in ids and "hr_payroll" not in ids                                                    # HR sees the people, payroll sees the money
    login_as(cl, "admin")
    assert "hr_payroll" in {t["id"] for t in cl.get("/api/dashboard").json()["tiles"]}
    # the leasing-only organisation has no books and no people tiles at all
    login_as(cl, "admin", "almaqsura")
    ids = {t["id"] for t in cl.get("/api/dashboard").json()["tiles"]}
    assert "occupancy" in ids and not ids & {"acc_off", "acc_cash", "acc_net", "hr_head", "sales30"}

# ----------------------------------------------------------------------------------------------------- 0.28.1 audit round
def test_a_reversed_receipt_is_not_served_and_the_tenant_sees_only_what_they_filed(cl, two_tenants):
    b_lease, _bt, b_user = two_tenants["b"]
    a_lease, _at, a_user = two_tenants["a"]
    login_as(cl, "admin")
    assert cl.post(f"/api/lea/payments/{two_tenants['pay']}/reverse", json={"reason": "خطأ في الإدخال"}).status_code == 200
    login_as(cl, b_user)
    d = cl.get(f"/api/lessee/leases/{b_lease}").json()
    assert all(p["pdf"] is None for p in d["payments"])
    assert cl.get(f"/api/lessee/docs/rent_receipt/{two_tenants['pay']}.pdf").status_code == 404
    # the office's own request on A's unit is not listed to A; A is capped at five open requests
    login_as(cl, "admin")
    unit_id = cl.get(f"/api/lea/leases/{a_lease}").json()["unit_id"]
    assert cl.post("/api/lea/maint", json={"unit_id": unit_id, "category": "كهرباء", "description": "ملاحظة داخلية عن المستأجر"}).status_code == 200
    login_as(cl, a_user)
    body = {"lease_id": a_lease, "category": "سباكة", "description": "تسرّب في حوض الغسيل"}
    for _ in range(5):
        assert cl.post("/api/lessee/maintenance", json=body).status_code == 200
    assert cl.post("/api/lessee/maintenance", json=body).status_code == 409
    mine = cl.get("/api/lessee/maintenance").json()
    assert len(mine) == 5 and all("داخلية" not in m["description"] for m in mine)
    # the clerk's e-mail on the tenant file does not become a sign-in identity
    assert _sql("SELECT email FROM users WHERE username=?", (a_user,))[0][0] is None


def test_odd_report_input_is_a_400_and_sensitive_reads_are_on_record(cl):
    login_as(cl, "admin")
    for url in ("/api/reports/ready/acc_vat?to=2026-13-40", "/api/reports/ready/acc_income?from=abc", "/api/reports/ready/acc_payables?to=bad", "/api/reports/ready/hr_leave?to=abcd",
                "/api/reports/ready/hr_attendance?to=2026-99", "/api/reports/ready/portfolio?project_id=x"):
        assert cl.get(url).status_code == 400, url
    assert cl.post("/api/reports/export", json={"format": "csv", "kind": "ready", "ref": "acc_vat", "params": {"to": 5}}).status_code == 400
    assert cl.post("/api/reports/saved", json={"name": "اختبار-سيئ", "kind": "custom", "spec": {"dataset": "employees", "limit": 0}}).status_code == 422
    assert cl.post("/api/reports/custom/run", json={"dataset": "employees", "filters": [{"col": "omani", "op": "eq", "value": "abc"}]}).status_code == 400
    assert cl.post("/api/reports/custom/run", json={"dataset": "employees", "filters": [{"col": "hire_date", "op": "between", "value": ["2020-01-01"]}]}).status_code == 400
    assert cl.get("/api/reports/ready/hr_headcount").status_code == 200
    assert cl.post("/api/reports/export", json={"format": "csv", "kind": "ready", "ref": "hr_headcount"}).status_code == 200
    audit = [r[0] + "|" + r[1] for r in _sql("SELECT action, actor FROM audit WHERE action IN ('اطلاع على تقرير حساس','تصدير تقرير') ORDER BY id DESC LIMIT 4")]
    assert any(a.startswith("اطلاع على تقرير حساس") and "مدير" in a for a in audit) and not any("النظام" in a for a in audit)


def test_saved_reports_and_schedules_are_listed_only_to_those_who_can_read_them_and_ledger_lines_are_not_mailed(cl, monkeypatch):
    from backend import mail
    monkeypatch.setattr(mail, "available", lambda: True)
    login_as(cl, "admin")
    acc = cl.post("/api/reports/saved", json={"name": "اختبار-ميزان", "kind": "ready", "ref": "acc_trial"}).json()["id"]
    ledger = cl.post("/api/reports/saved", json={"name": "اختبار-قيود", "kind": "custom", "spec": {"dataset": "journal_lines"}}).json()["id"]
    assert cl.post("/api/reports/schedules", json={"report_id": acc, "cadence": "daily", "recipients": "a@example.test"}).status_code == 200
    r = cl.post("/api/reports/schedules", json={"report_id": ledger, "cadence": "daily", "recipients": "a@example.test"})
    assert r.status_code == 409                                   # per-person loan and settlement entries live in the ledger lines
    assert any(s["report_name"] == "اختبار-ميزان" for s in cl.get("/api/reports/schedules").json())
    _sql("INSERT INTO users(username,name,role,pw,must_change) VALUES('por-pay3','رواتب','payroll',?,0)", (A.hash_pw("Pay-Pass-2026-q"),))
    login_as(cl, "por-pay3")
    assert [x for x in cl.get("/api/reports/saved").json() if x["name"].startswith("اختبار-")] == []
    assert cl.get("/api/reports/schedules").json() == []
    # a schedule made before the rule existed is refused at send time too
    from backend import reports
    _sql("INSERT INTO report_schedules(report_id,cadence,hour,recipients,format,active,next_run,created_by,created) VALUES(?,?,?,?,?,1,'2000-01-01T00:00','admin','x')", (ledger, "daily", 7, "a@example.test", "csv"))
    tok = TENANT.set("bayan")
    try:
        c = connect()
        reports.run_due_schedules(c)
        assert "الرواتب والقيود" in c.execute("SELECT last_error FROM report_schedules WHERE report_id=? AND last_error IS NOT NULL", (ledger,)).fetchone()[0]
        c.close()
    finally:
        TENANT.reset(tok)


def test_books_and_people_never_reach_an_external_model(cl, monkeypatch):
    from backend import assistant as AS
    login_as(cl, "admin")
    tok = TENANT.set("bayan")
    try:
        c = connect()
        u = _u(["view", "accounting", "hr", "hr_payroll", "hr_self"], ["accounting", "hr", "finance"])
        for tool in ("accounting", "hr"):
            out = AS.run_tool(AS.Ctx(c, u, external=True), tool, {"account": "رواتب"})
            assert out["data"] is None and "لا تُرسل" in out["text"], tool
        # the model sees earlier questions only — never earlier answers (which may have come from the local engine)
        seen = []

        class Fake:
            def post(self, url, headers=None, json=None):
                seen.append(json["messages"])

                class R:
                    status_code = 200

                    def json(self):
                        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "تمام"}]}
                return R()
        monkeypatch.setattr(AS, "ai_key", lambda: "k")
        AS.llm_answer(AS.Ctx(c, u, external=True), "وماذا بعد؟", [{"q": "كم موظف؟", "a": "آخر مسيّر 1500 ر.ع لـ 3 موظفين"}], Fake())
        flat = " ".join(str(m["content"]) for m in seen[0])
        assert "كم موظف؟" in flat and "1500" not in flat
        # a question about the books or the people is answered locally even when the model is on
        monkeypatch.setattr(AS, "tenant_cfg", lambda c_: {"llm": True, "names": False})
        monkeypatch.setattr(AS, "llm_answer", lambda *a, **k: (_ for _ in ()).throw(AssertionError("the model must not be called")))
        r = AS.answer(c, u, "كم موظف لدينا ونسبة العمانيين؟")
        assert r["mode"] == "rules" and "على رأس العمل" in r["answer"]
        c.close()
    finally:
        TENANT.reset(tok)


def test_the_employee_attendance_month_is_validated_and_hr_remarks_stay_internal(cl):
    _eid, un = _employee_with_login(cl, "موظف الملاحظات", "porrem")
    eid = _sql("SELECT id FROM employees ORDER BY id DESC LIMIT 1")[0][0]
    month = TODAY.isoformat()[:7]
    _sql("INSERT INTO attendance(employee_id,day,status,source,note) VALUES(?,?,?,'manual',?)", (eid, f"{month}-02", "late", "ملاحظة داخلية من الموارد البشرية"))
    login_as(cl, un)
    a = cl.get("/api/hr/me/attendance?month=%25%25%25%25-%25%25").json()
    assert a["month"] == month and [d["status"] for d in a["days"]] == ["late"] and "note" not in a["days"][0]
