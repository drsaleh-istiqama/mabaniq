"""0.26.0 — payroll: salary structures, the monthly run with a maker and a different checker, PASI rates that are never guessed, frozen payslips, interest-free staff loans,
the wage-protection file, the end-of-service rule and the settlement of a leaver, and the posting to the books. The rates used below are TEST values — the platform ships none."""
import datetime as dt
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "hrpay.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "bayan:بيان عمان;almaqsura:المقصورة العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect, init  # noqa: E402

CSRF = "csrf-pay-" + "f" * 30
TODAY = dt.date.today()
PS = (TODAY.replace(day=1) - dt.timedelta(days=1)).replace(day=1)  # first day of last month
PE = TODAY.replace(day=1) - dt.timedelta(days=1)
PERIOD = PS.strftime("%Y-%m")
NEXT = TODAY.strftime("%Y-%m")
HR_TABLES = ("terminations", "eosb_rules", "loan_installments", "employee_loans", "payroll_adjustments", "payslips", "payroll_runs", "salary_lines", "salary_structures", "pay_components", "hr_rates",
             "hr_requests", "attendance", "holidays", "leave_requests", "leave_balances", "leave_types", "employee_documents", "employees", "positions", "departments")
ACC_TABLES = ("fin_installments", "fin_contracts", "acc_budgets", "depreciation_runs", "fixed_assets", "vat_returns", "bank_recons", "bank_stmt_lines", "payment_orders", "ap_payments",
              "ap_bill_lines", "ap_bills", "bank_accounts", "acc_lines", "acc_journals", "acc_source_state", "acc_periods", "acc_cost_centers", "acc_accounts")
RATES = [("pasi_employee_pct", 7), ("pasi_employer_pct", 10.5), ("pasi_ceiling", 3000)]  # TEST values


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


def _sql(sql, args=(), maint=False):
    tok = TENANT.set("bayan")
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


def _wipe():
    tok = TENANT.set("bayan")
    try:
        c = connect()
        pg = getattr(c, "dialect", "sqlite") == "postgres"
        sc = " AND org_id = current_setting('app.org_id', true)" if pg else ""
        c.maintenance()
        c.execute(f"UPDATE users SET employee_id=NULL WHERE employee_id IS NOT NULL{sc}")
        c.execute(f"DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'emp%' OR username LIKE 'hrt-%'){sc}")
        c.execute(f"DELETE FROM users WHERE username LIKE 'emp%' OR username LIKE 'hrt-%'{sc}")
        c.execute(c.wipe_sql("departments").replace("DELETE FROM departments", "UPDATE departments SET head_employee_id=NULL"))
        for t in HR_TABLES + ACC_TABLES:  # payroll rows point at bank accounts and cost centres: they go first
            c.execute(c.wipe_sql(t))
        c.execute(f"DELETE FROM settings WHERE k LIKE 'hr:%' OR k='acc_start'{sc}")
        c.execute(f"DELETE FROM counters WHERE k LIKE 'hr:%' OR k LIKE 'jv:%'{sc}")
        c.execute(f"DELETE FROM documents WHERE ref_type='employee'{sc}")
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
        _wipe()
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
    _wipe()


# ----------------------------------------------------------------------------------------------------- helpers
def _user(cl, name, role):
    login_as(cl, "admin")
    r = cl.post("/api/users", json={"username": name, "name": f"مستخدم {name}", "role": role})
    assert r.status_code == 200, r.text
    _sql("UPDATE users SET must_change=0 WHERE username=?", (name,))
    return name


def _comp(cl, key):
    return next(x["id"] for x in cl.get("/api/hr/payroll/components").json() if x["key"] == key)


def _staff(cl, name, basic, housing=0, omani=True, hire="2024-01-01", **kw):
    login_as(cl, "admin")
    r = cl.post("/api/hr/employees", json={"name": name, "omani": omani, "hire_date": hire, "iban": "OM810180000001299123456", "bank_name": "بنك إسلامي", "social_ins_no": "SI-1" if omani else "", **kw})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    lines = [{"component_id": _comp(cl, "housing"), "amount": housing}] if housing else []
    s = cl.post("/api/hr/payroll/structures", json={"employee_id": eid, "effective_from": hire, "basic": basic, "lines": lines})
    assert s.status_code == 200, s.text
    return eid


def _rates(cl):
    login_as(cl, "admin")
    for k, v in RATES:
        r = cl.post("/api/hr/payroll/rates", json={"key": k, "value": v, "valid_from": "2000-01-01", "note": "قيمة اختبار لا مرجع لها"})
        assert r.status_code == 200, r.text


def _run(cl, period=PERIOD):
    r = cl.post("/api/hr/payroll/runs", json={"period": period})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _slip(cl, rid, number):
    return next(s for s in cl.get(f"/api/hr/payroll/runs/{rid}").json()["payslips"] if s["number"] == number)


def _approved_run(cl, period=PERIOD):
    """Computed by the administrator, approved by a second payroll officer."""
    login_as(cl, "admin")
    rid = _run(cl, period)
    assert cl.post(f"/api/hr/payroll/runs/{rid}/compute").status_code == 200
    login_as(cl, _user(cl, f"hrt-pay-{period}", "payroll"))
    r = _approve(cl, rid, period)
    assert r.status_code == 200, r.text
    return rid


def _approve(cl, rid, period, **params):
    """A month is approved only once it has ended (0.28.1): for the running month the clock is moved to the day after it."""
    from unittest import mock

    from backend import hr_payroll as HP
    ps = dt.date.fromisoformat(period + "-01")
    after = (ps.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    q = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
    if after > TODAY:
        with mock.patch.object(HP, "today", lambda: after):
            return cl.post(f"/api/hr/payroll/runs/{rid}/approve{q}")
    return cl.post(f"/api/hr/payroll/runs/{rid}/approve{q}")


# ----------------------------------------------------------------------------------------------------- the calculation
def test_pasi_rates_are_never_guessed_and_the_run_is_calculated_line_by_line(cl):
    a = _staff(cl, "عامل عُماني", 500, housing=100)
    b = _staff(cl, "عامل وافد", 400, omani=False)
    login_as(cl, "admin")
    rates = {r["key"]: r for r in cl.get("/api/hr/payroll/rates").json() if r["current"]}
    assert rates["pasi_employee_pct"]["value"] is None and rates["pasi_ceiling"]["value"] is None, "no insurance rate or ceiling ships with the platform"
    assert rates["day_divisor"]["value"] == 30 and rates["day_divisor"]["provisional"] == 1
    for d in (1, 2):  # two marked absences for the expatriate
        assert cl.post("/api/hr/attendance", json={"employee_id": b, "day": (PS + dt.timedelta(days=d)).isoformat(), "status": "absent"}).status_code == 200
    rid = _run(cl)
    out = cl.post(f"/api/hr/payroll/runs/{rid}/compute").json()
    assert out["headcount"] == 2 and out["blockers"] == 1, out
    sa = _slip(cl, rid, "EMP-0001")
    assert sa["pasi_employee"] == 0 and any(w["kind"] == "pasi_unset" and w["blocker"] for w in sa["warnings"])
    login_as(cl, _user(cl, "hrt-pay2", "payroll"))
    r = cl.post(f"/api/hr/payroll/runs/{rid}/approve")
    assert r.status_code == 409 and "التأمينات" in r.text, "an unset rate blocks the approval"
    # rates entered (test values) → recompute → every line checked by hand
    _rates(cl)
    out = cl.post(f"/api/hr/payroll/runs/{rid}/compute").json() if login_as(cl, "admin") else None
    assert out["blockers"] == 0 and out["gross"] == 1000 and abs(out["net"] - (565 + 373.333)) < 1e-6, out
    sa, sb = _slip(cl, rid, "EMP-0001"), _slip(cl, rid, "EMP-0002")
    assert (sa["gross"], sa["pasi_base"], sa["pasi_employee"], sa["pasi_employer"], sa["net"]) == (600, 500, 35, 52.5, 565), "housing is outside the insurance base"
    assert (sb["absence_days"], sb["absence_ded"], sb["pasi_employee"], sb["net"]) == (2, 26.667, 0, 373.333)
    assert cl.post("/api/hr/payroll/rates", json={"key": "pasi_ceiling", "value": 3500, "valid_from": "2000-01-01", "note": "x" * 6}).status_code == 409  # that date already holds a value
    assert cl.post("/api/hr/payroll/rates", json={"key": "pasi_employee_pct", "value": 7, "valid_from": "2026-01-01", "note": "ab"}).status_code == 400  # a source is mandatory
    assert a and b


def test_a_mid_month_hire_and_unpaid_leave_are_prorated_and_deducted(cl):
    _rates(cl)
    hire = PS + dt.timedelta(days=15)  # works from the 16th
    e = _staff(cl, "موظف منتصف الشهر", 600, omani=False, hire=hire.isoformat())
    f = _staff(cl, "موظف بإجازة بلا راتب", 300, omani=False)
    login_as(cl, "admin")
    days_in = (PE - PS).days + 1
    sun = PS + dt.timedelta(days=(6 - PS.weekday()) % 7)  # first Sunday
    r = cl.post("/api/hr/leave/requests", json={"employee_id": f, "type_key": "unpaid", "from_date": sun.isoformat(), "to_date": (sun + dt.timedelta(days=1)).isoformat(), "approve": True})
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    rid = _run(cl)
    cl.post(f"/api/hr/payroll/runs/{rid}/compute")
    se, sf = _slip(cl, rid, "EMP-0001"), _slip(cl, rid, "EMP-0002")
    worked = (PE - hire).days + 1
    assert se["gross"] == round(600 * worked / days_in, 3) and se["factor"] == pytest.approx(worked / days_in, abs=1e-5)
    assert sf["absence_days"] == 2 and sf["absence_ded"] == 20.0 and sf["net"] == 280.0  # 300 / 30 × 2
    assert e


def test_adjustments_enter_the_payslip_and_one_off_deductions_cannot_make_the_net_negative(cl):
    _rates(cl)
    a = _staff(cl, "موظف التسويات", 200, omani=False)
    login_as(cl, "admin")
    assert cl.post("/api/hr/payroll/adjustments", json={"employee_id": a, "period": PERIOD, "kind": "earning", "name": "مكافأة", "amount": 50}).status_code == 200
    assert cl.post("/api/hr/payroll/adjustments", json={"employee_id": a, "period": PERIOD, "kind": "deduction", "name": "جزاء", "amount": 20}).status_code == 200
    rid = _run(cl)
    cl.post(f"/api/hr/payroll/runs/{rid}/compute")
    s = _slip(cl, rid, "EMP-0001")
    assert (s["adj_earn"], s["adj_ded"], s["net"]) == (50, 20, 230)
    big = cl.post("/api/hr/payroll/adjustments", json={"employee_id": a, "period": PERIOD, "kind": "deduction", "name": "غرامة كبيرة", "amount": 900}).json()["id"]
    out = cl.post(f"/api/hr/payroll/runs/{rid}/compute").json()
    assert out["blockers"] == 1 and _slip(cl, rid, "EMP-0001")["net"] < 0
    assert cl.delete(f"/api/hr/payroll/adjustments/{big}").status_code == 200
    assert cl.post(f"/api/hr/payroll/runs/{rid}/compute").json()["blockers"] == 0


# ----------------------------------------------------------------------------------------------------- maker, checker and the frozen payslip
def test_the_person_who_computed_never_approves_and_an_approved_payslip_is_frozen_by_the_database(cl):
    _rates(cl)
    a = _staff(cl, "محمد", 500, housing=100)
    login_as(cl, "admin")
    rid = _run(cl)
    cl.post(f"/api/hr/payroll/runs/{rid}/compute")
    assert cl.post(f"/api/hr/payroll/runs/{rid}/approve").status_code == 403  # not even the general manager approves what he computed
    p2 = _user(cl, "hrt-pay2", "payroll")
    login_as(cl, p2)
    assert cl.post(f"/api/hr/payroll/runs/{rid}/pay", json={"paid_on": TODAY.isoformat()}).status_code == 409  # approval comes first
    assert cl.post(f"/api/hr/payroll/runs/{rid}/approve").status_code == 200
    run = cl.get(f"/api/hr/payroll/runs/{rid}").json()
    assert run["status"] == "approved" and run["approved_by"] == p2 and run["computed_by"] == "admin"
    slip = run["payslips"][0]
    with pytest.raises(Exception, match="immutable"):
        _sql("UPDATE payslips SET net=1 WHERE id=?", (slip["id"],))
    with pytest.raises(Exception, match="immutable"):
        _sql("DELETE FROM payslips WHERE id=?", (slip["id"],))
    assert cl.post(f"/api/hr/payroll/runs/{rid}/compute").status_code == 409  # a frozen run is never recomputed
    login_as(cl, "admin")
    assert cl.post("/api/hr/payroll/adjustments", json={"employee_id": a, "period": PERIOD, "kind": "earning", "name": "متأخر", "amount": 5}).status_code == 409  # goes to the next month
    late = cl.post("/api/hr/payroll/structures", json={"employee_id": a, "effective_from": PS.isoformat(), "basic": 900})
    assert late.status_code == 409 and "مجمَّد" in late.text, "a raise cannot rewrite a frozen month"
    assert cl.post("/api/hr/payroll/structures", json={"employee_id": a, "effective_from": TODAY.replace(day=1).isoformat(), "basic": 550}).status_code == 200
    assert cl.post("/api/hr/payroll/runs", json={"period": PERIOD}).status_code == 409  # one run per month


# ----------------------------------------------------------------------------------------------------- who can see a salary
def test_salary_data_is_seen_only_by_payroll_and_the_employee_himself(cl):
    _rates(cl)
    a, b = _staff(cl, "صاحب القسيمة", 500, housing=100), _staff(cl, "زميله", 800)
    hr = _user(cl, "hrt-officer", "hr")
    login_as(cl, "admin")
    ua, ub = (cl.post(f"/api/hr/employees/{x}/account").json()["username"] for x in (a, b))
    for u in (ua, ub):
        _sql("UPDATE users SET must_change=0 WHERE username=?", (u,))
    rid = _approved_run(cl)
    paths = ["/api/hr/payroll/salaries", "/api/hr/payroll/runs", f"/api/hr/payroll/runs/{rid}", f"/api/hr/payroll/structures?employee_id={a}", "/api/hr/payroll/loans", "/api/hr/payroll/rates",
             "/api/hr/terminations", "/api/hr/eosb/rules"]
    for who in (hr, ua, "finance", "sales"):  # the people officer has no payroll permission, and neither has anyone else
        login_as(cl, who)
        assert all(cl.get(p).status_code == 403 for p in paths), who
    login_as(cl, ua)
    mine = cl.get("/api/hr/me/payslips").json()
    assert len(mine) == 1 and mine[0]["net"] == 565 and mine[0]["period"] == PERIOD
    pid = mine[0]["id"]
    assert cl.get(f"/api/hr/me/payslips/{pid}").json()["earnings"][0]["amount"] == 500
    pdf = cl.get(f"/api/hr/me/payslips/{pid}.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert cl.get("/api/hr/me/salary").json()["total"] == 600
    login_as(cl, ub)
    assert cl.get(f"/api/hr/me/payslips/{pid}").status_code == 404 and cl.get(f"/api/hr/me/payslips/{pid}.pdf").status_code == 404, "a colleague's payslip does not exist for him"
    assert cl.get("/api/hr/me/salary").json()["basic"] == 800
    # the HR file never carries a salary
    login_as(cl, hr)
    assert "basic" not in cl.get(f"/api/hr/employees/{a}").json() and "salary" not in str(cl.get(f"/api/hr/employees/{a}").json())


def test_an_unapproved_payslip_is_not_shown_to_the_employee_and_the_list_of_salaries_is_audited(cl):
    _rates(cl)
    a = _staff(cl, "قيد الاحتساب", 500)
    login_as(cl, "admin")
    u = cl.post(f"/api/hr/employees/{a}/account").json()["username"]
    _sql("UPDATE users SET must_change=0 WHERE username=?", (u,))
    rid = _run(cl)
    cl.post(f"/api/hr/payroll/runs/{rid}/compute")
    assert len(cl.get("/api/hr/payroll/salaries").json()) == 1
    assert any(r["action"] == "اطلاع على الرواتب" for r in _sql("SELECT action FROM audit ORDER BY id DESC LIMIT 8"))
    login_as(cl, u)
    assert cl.get("/api/hr/me/payslips").json() == [], "a computed payslip is a draft until a second person approves it"


# ----------------------------------------------------------------------------------------------------- loans without interest
def test_a_staff_loan_has_no_rate_is_approved_by_another_and_is_recovered_instalment_by_instalment(cl):
    _rates(cl)
    e = _staff(cl, "مقترض", 300, omani=False)
    login_as(cl, "admin")
    for field in ("rate", "interest", "fee", "profit"):
        r = cl.post("/api/hr/payroll/loans", json={"employee_id": e, "kind": "qard_hasan", "amount": 120, "installments": 3, "start_period": PERIOD, field: 5})
        assert r.status_code == 422, field  # there is no such field to set
    assert cl.post("/api/hr/payroll/loans", json={"employee_id": e, "kind": "advance", "amount": 120, "installments": 24, "start_period": PERIOD}).status_code == 400  # an advance is short
    lid = cl.post("/api/hr/payroll/loans", json={"employee_id": e, "kind": "qard_hasan", "amount": 100, "installments": 3, "start_period": PERIOD, "reason": "ظرف طارئ"}).json()["id"]
    assert cl.post(f"/api/hr/payroll/loans/{lid}/approve", json={"disbursed_on": TODAY.isoformat()}).status_code == 403  # the creator does not approve
    login_as(cl, _user(cl, "hrt-pay2", "payroll"))
    assert cl.post(f"/api/hr/payroll/loans/{lid}/approve", json={"disbursed_on": TODAY.isoformat()}).status_code == 200
    sch = cl.get(f"/api/hr/payroll/loans/{lid}").json()["schedule"]
    assert [x["amount"] for x in sch] == [33.333, 33.333, 33.334] and sum(x["amount"] for x in sch) == pytest.approx(100), "repaid at exactly the amount lent"
    assert [x["period"] for x in sch][0] == PERIOD
    login_as(cl, "admin")
    r1 = _approved_run(cl, PERIOD)
    s = _slip(cl, r1, "EMP-0001")
    assert (s["loan_ded"], s["net"]) == (33.333, 266.667)
    sch = cl.get(f"/api/hr/payroll/loans/{lid}").json()["schedule"]
    assert [x["status"] for x in sch] == ["deducted", "due", "due"]
    r2 = _approved_run(cl, NEXT) if NEXT != PERIOD else None
    assert _slip(cl, r2, "EMP-0001")["loan_ded"] == 33.333
    assert cl.post(f"/api/hr/payroll/loans/{lid}/cancel", json={"reason": "تراجع"}).status_code == 409  # money went out and deduction began


def test_a_loan_instalment_that_the_pay_cannot_bear_is_deferred_not_forced(cl):
    _rates(cl)
    e = _staff(cl, "راتب ضعيف", 100, omani=False)
    login_as(cl, "admin")
    lid = cl.post("/api/hr/payroll/loans", json={"employee_id": e, "kind": "advance", "amount": 90, "installments": 1, "start_period": PERIOD}).json()["id"]
    login_as(cl, _user(cl, "hrt-pay2", "payroll"))
    cl.post(f"/api/hr/payroll/loans/{lid}/approve", json={"disbursed_on": TODAY.isoformat()})
    login_as(cl, "admin")
    cl.post("/api/hr/payroll/adjustments", json={"employee_id": e, "period": PERIOD, "kind": "deduction", "name": "استقطاع", "amount": 50})
    rid = _run(cl)
    cl.post(f"/api/hr/payroll/runs/{rid}/compute")
    s = _slip(cl, rid, "EMP-0001")
    assert s["loan_ded"] == 0 and s["net"] == 50 and any(w["kind"] == "loan_deferred" for w in s["warnings"])
    assert cl.get(f"/api/hr/payroll/loans/{lid}").json()["schedule"][0]["status"] == "due"


# ----------------------------------------------------------------------------------------------------- the transfer file
def test_the_wage_file_reports_what_is_missing_before_it_exports(cl):
    _rates(cl)
    ok = _staff(cl, "حسابه سليم", 400, omani=False)
    login_as(cl, "admin")
    bad = cl.post("/api/hr/employees", json={"name": "بلا آيبان", "omani": False, "hire_date": "2024-01-01"}).json()["id"]
    cl.post("/api/hr/payroll/structures", json={"employee_id": bad, "effective_from": "2024-01-01", "basic": 350, "lines": []})
    rid = _approved_run(cl)
    login_as(cl, "admin")
    rep = cl.get(f"/api/hr/payroll/runs/{rid}/wps").json()
    assert rep["ready"] is False and rep["problems"][0]["kind"] == "no_iban" and rep["total"] == 400 and len(rep["lines"]) == 1
    assert cl.get(f"/api/hr/payroll/runs/{rid}/wps", params={"fmt": "csv"}).status_code == 409
    login_as(cl, "admin")
    assert cl.patch(f"/api/hr/employees/{bad}", json={"iban": "OM810180000001299123999", "bank_name": "بنك آخر"}).status_code == 200
    rep = cl.get(f"/api/hr/payroll/runs/{rid}/wps").json()
    assert rep["ready"] and rep["total"] == 750
    f = cl.get(f"/api/hr/payroll/runs/{rid}/wps", params={"fmt": "csv"})
    assert f.status_code == 200 and "OM810180000001299123999" in f.text and "400.000" in f.text and f.text.count("\n") == 3
    assert _sql("SELECT wps_sha FROM payroll_runs WHERE id=?", (rid,))[0]["wps_sha"]
    assert ok


# ----------------------------------------------------------------------------------------------------- the books
def test_an_approved_run_posts_a_balanced_journal_by_department_and_payment_clears_the_payable(cl):
    _rates(cl)
    login_as(cl, "admin")
    assert cl.post("/api/acc/activate", json={"start": (PS - dt.timedelta(days=40)).isoformat(), "confirm": True}).status_code == 200
    a = _staff(cl, "محاسب الرواتب", 500, housing=100)
    b = _staff(cl, "وافد", 400, omani=False)
    rid = _approved_run(cl)
    login_as(cl, "admin")
    run = cl.get(f"/api/hr/payroll/runs/{rid}").json()
    assert run["journal_id"], "approval posted the accrual"
    lines = _sql("""SELECT a.system_key k, SUM(l.debit) d, SUM(l.credit) c FROM acc_lines l JOIN acc_accounts a ON a.id=l.account_id WHERE l.journal_id=? GROUP BY a.system_key""", (run["journal_id"],))
    by = {r["k"]: (r["d"], r["c"]) for r in lines}
    assert by["exp_payroll"][0] == 1000 and by["exp_pasi_employer"][0] == 52.5 and by["payroll_payable"][1] == 965 and by["pasi_payable"][1] == 87.5
    assert sum(r["d"] for r in lines) == pytest.approx(sum(r["c"] for r in lines))
    bank = next(x["id"] for x in cl.get("/api/acc/banks").json() if x["kind"] == "bank")
    login_as(cl, "admin")
    assert cl.post(f"/api/hr/payroll/runs/{rid}/pay", json={"paid_on": TODAY.isoformat(), "bank_account_id": bank}).status_code == 200
    run = cl.get(f"/api/hr/payroll/runs/{rid}").json()
    assert run["payment_journal_id"]
    pay = _sql("""SELECT COALESCE(SUM(l.debit - l.credit),0) s FROM acc_lines l JOIN acc_accounts a ON a.id=l.account_id JOIN acc_journals j ON j.id=l.journal_id
                  WHERE a.system_key='payroll_payable' AND j.status IN ('posted','reversed')""")[0]["s"]
    assert abs(pay) < 1e-6, "once paid, the payroll payable is nil"
    sync = cl.post("/api/acc/sync").json()
    assert sync["posted"]["payroll"] == 0, "nothing is posted twice"
    assert a and b


def test_a_run_approved_before_accounting_started_is_picked_up_by_the_next_sync(cl):
    _rates(cl)
    _staff(cl, "قبل التفعيل", 300, omani=False)
    rid = _approved_run(cl)
    login_as(cl, "admin")
    assert cl.get(f"/api/hr/payroll/runs/{rid}").json()["journal_id"] is None
    assert cl.post("/api/acc/activate", json={"start": (PS - dt.timedelta(days=5)).isoformat(), "confirm": True}).status_code == 200
    assert cl.get("/api/acc/status").json()["unposted"]["counts"]["payroll"] == 1
    assert cl.post("/api/acc/sync").json()["posted"]["payroll"] >= 1
    assert cl.get(f"/api/hr/payroll/runs/{rid}").json()["journal_id"]


# ----------------------------------------------------------------------------------------------------- end of service
def _hire_years_ago(years):
    return (TODAY - dt.timedelta(days=int(years * 365.25))).isoformat()


def test_without_a_rule_the_gratuity_is_unknown_not_zero_and_the_settlement_cannot_be_approved(cl):
    _rates(cl)
    e = _staff(cl, "مغادر بلا قاعدة", 600, omani=False, hire=_hire_years_ago(5))
    login_as(cl, "admin")
    calc = cl.get("/api/hr/eosb/calc", params={"employee_id": e, "end_date": TODAY.isoformat()}).json()
    assert calc["amount"] is None and "قاعدة" in calc["reason"]
    tid = cl.post("/api/hr/terminations", json={"employee_id": e, "end_date": TODAY.isoformat(), "kind": "resignation", "note": "استقالة مقدَّمة"}).json()["id"]
    login_as(cl, _user(cl, "hrt-pay2", "payroll"))
    r = cl.post(f"/api/hr/terminations/{tid}/approve")
    assert r.status_code == 409 and "قاعدة" in r.text
    assert cl.get(f"/api/hr/employees/{e}").status_code == 403  # payroll has no people-file permission either


def test_the_gratuity_shows_every_step_and_the_settlement_ends_the_service_once_approved_and_cleared(cl):
    _rates(cl)
    e = _staff(cl, "مغادر بقاعدة", 600, omani=False, hire=_hire_years_ago(5))
    loan_e = e
    login_as(cl, "admin")
    login_user = cl.post(f"/api/hr/employees/{e}/account").json()["username"]
    _sql("UPDATE users SET must_change=0 WHERE username=?", (login_user,))
    bad = cl.post("/api/hr/eosb/rules", json={"grp": "expat", "valid_from": "2000-01-01", "tiers": [{"to_years": 3, "days_per_year": 15}, {"to_years": 2, "days_per_year": 30}], "note": "مرجع الاختبار"})
    assert bad.status_code == 400  # tiers must ascend and the last one is open
    ok = cl.post("/api/hr/eosb/rules", json={"grp": "expat", "valid_from": "2000-01-01", "tiers": [{"to_years": 3, "days_per_year": 15}, {"to_years": None, "days_per_year": 30}],
                                              "note": "قاعدة اختبار — ليست مرجعًا قانونيًا"})
    assert ok.status_code == 200, ok.text
    lid = cl.post("/api/hr/payroll/loans", json={"employee_id": loan_e, "kind": "qard_hasan", "amount": 90, "installments": 3, "start_period": NEXT}).json()["id"]
    p2 = _user(cl, "hrt-pay2", "payroll")
    login_as(cl, p2)
    cl.post(f"/api/hr/payroll/loans/{lid}/approve", json={"disbursed_on": TODAY.isoformat()})
    login_as(cl, "admin")
    calc = cl.get("/api/hr/eosb/calc", params={"employee_id": e, "end_date": TODAY.isoformat()}).json()
    yrs = calc["years"]
    want = round(3 * 15 * 20 + (yrs - 3) * 30 * 20, 3)  # daily wage 600 / 30 = 20
    assert [s["days_per_year"] for s in calc["steps"]] == [15, 30] and calc["amount"] == pytest.approx(want, abs=0.01)
    tid = cl.post("/api/hr/terminations", json={"employee_id": e, "end_date": TODAY.isoformat(), "kind": "resignation", "note": "استقالة مقدَّمة", "other_dues": 10}).json()["id"]
    t = cl.get(f"/api/hr/terminations/{tid}").json()
    assert t["loans_due"] == 90 and t["eosb_amount"] == pytest.approx(want, abs=0.01)
    assert t["net"] == pytest.approx(t["eosb_amount"] + t["leave_payout"] + 10 - 90, abs=0.002)
    assert cl.post(f"/api/hr/terminations/{tid}/approve").status_code == 403  # the drafter does not approve
    login_as(cl, p2)
    ap = cl.post(f"/api/hr/terminations/{tid}/approve")
    assert ap.status_code == 200, ap.text
    login_as(cl, "admin")
    emp = cl.get(f"/api/hr/employees/{e}").json()
    assert emp["status"] == "terminated" and emp["terminated_on"] == TODAY.isoformat()
    assert _sql("SELECT active FROM users WHERE username=?", (login_user,))[0]["active"] == 0
    assert cl.get(f"/api/hr/payroll/loans/{lid}").json()["status"] == "paid" and all(x["status"] == "settled" for x in cl.get(f"/api/hr/payroll/loans/{lid}").json()["schedule"])
    login_as(cl, p2)
    nopay = cl.post(f"/api/hr/terminations/{tid}/pay", json={"paid_on": TODAY.isoformat()})
    assert nopay.status_code == 409 and "إخلاء" in nopay.text, "the clearance list must be complete first"
    items = [{"item": x["item"], "done": True} for x in cl.get(f"/api/hr/terminations/{tid}").json()["clearance"]]
    assert cl.post(f"/api/hr/terminations/{tid}/recalc", json={"clearance": items}).status_code == 200
    assert cl.post(f"/api/hr/terminations/{tid}/pay", json={"paid_on": TODAY.isoformat()}).status_code == 200
    assert cl.post(f"/api/hr/terminations/{tid}/recalc", json={"other_dues": 99}).status_code == 409  # approved: frozen
    pdf = cl.get(f"/api/hr/terminations/{tid}.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_the_settlement_posts_one_balanced_journal_when_accounting_is_on(cl):
    _rates(cl)
    login_as(cl, "admin")
    assert cl.post("/api/acc/activate", json={"start": (TODAY - dt.timedelta(days=60)).isoformat(), "confirm": True}).status_code == 200
    e = _staff(cl, "مخالصة محاسبية", 600, omani=False, hire=_hire_years_ago(4))
    login_as(cl, "admin")
    cl.post("/api/hr/eosb/rules", json={"grp": "expat", "valid_from": "2000-01-01", "tiers": [{"to_years": None, "days_per_year": 30}], "note": "قاعدة اختبار"})
    tid = cl.post("/api/hr/terminations", json={"employee_id": e, "end_date": TODAY.isoformat(), "kind": "end_of_contract", "note": "انتهى العقد", "other_deductions": 5}).json()["id"]
    login_as(cl, _user(cl, "hrt-pay2", "payroll"))
    assert cl.post(f"/api/hr/terminations/{tid}/approve").status_code == 200
    jid = cl.get(f"/api/hr/terminations/{tid}").json()["journal_id"]
    assert jid
    lines = _sql("SELECT SUM(debit) d, SUM(credit) c FROM acc_lines WHERE journal_id=?", (jid,))[0]
    assert lines["d"] == pytest.approx(lines["c"]) and lines["d"] > 0


# ----------------------------------------------------------------------------------------------------- 0.28.1 audit round
def test_a_run_whose_inputs_changed_after_the_compute_is_refreshed_not_approved(cl):
    _rates(cl)
    _staff(cl, "موظف التسوية", 300, omani=False)
    e = _sql("SELECT id FROM employees")[0][0]
    login_as(cl, "admin")
    rid = _run(cl)
    assert cl.post(f"/api/hr/payroll/runs/{rid}/compute").status_code == 200
    cl.post("/api/hr/payroll/adjustments", json={"employee_id": e, "period": PERIOD, "kind": "deduction", "name": "استقطاع لاحق", "amount": 20})
    login_as(cl, _user(cl, "hrt-pay2", "payroll"))
    r = _approve(cl, rid, PERIOD)
    assert r.status_code == 409 and "أُعيد الاحتساب" in r.text      # the approver reviews what will really be paid
    assert _slip(cl, rid, "EMP-0001")["adj_ded"] == 20
    assert cl.get(f"/api/hr/payroll/runs/{rid}").json()["computed_by"] == "admin"   # the maker stays the maker
    assert _approve(cl, rid, PERIOD).status_code == 200


def test_a_month_that_has_not_ended_is_not_approved_and_nobody_is_silently_left_unpaid(cl):
    import calendar
    if TODAY.day == calendar.monthrange(TODAY.year, TODAY.month)[1]:
        pytest.skip("on the last day of the month the running month may already be approved (the rule counts that day as the month's end), so the 'not ended yet' refusal cannot be shown")
    _rates(cl)
    _staff(cl, "موظف أول", 300, omani=False)
    login_as(cl, "admin")
    assert cl.post("/api/hr/employees", json={"name": "بلا هيكل", "omani": False, "hire_date": "2024-01-01", "gender": "male"}).status_code == 200
    rid = _run(cl, NEXT)
    cl.post(f"/api/hr/payroll/runs/{rid}/compute")
    login_as(cl, _user(cl, "hrt-pay2", "payroll"))
    r = cl.post(f"/api/hr/payroll/runs/{rid}/approve")
    assert r.status_code == 409 and "لم ينتهِ" in r.text
    r = _approve(cl, rid, NEXT)
    assert r.status_code == 409 and "بلا هيكل" in r.text and "EMP-0002" in r.text
    assert _approve(cl, rid, NEXT, confirm_missing=1).status_code == 200


def test_nobody_sets_their_own_pay_or_approves_a_run_with_their_own_payslip(cl):
    _rates(cl)
    eid = _staff(cl, "مسؤول الرواتب", 300, omani=False)
    me = _user(cl, "hrt-pay2", "payroll")
    login_as(cl, "admin")
    uid = _sql("SELECT id FROM users WHERE username=?", (me,))[0][0]
    assert cl.post(f"/api/hr/employees/{eid}/link-user", json={"user_id": uid}).status_code == 200
    login_as(cl, me)
    assert cl.post("/api/hr/payroll/structures", json={"employee_id": eid, "effective_from": TODAY.isoformat(), "basic": 900, "lines": []}).status_code == 403
    assert cl.post("/api/hr/payroll/adjustments", json={"employee_id": eid, "period": PERIOD, "kind": "earning", "name": "علاوة", "amount": 50}).status_code == 403
    login_as(cl, "admin")
    rid = _run(cl)
    cl.post(f"/api/hr/payroll/runs/{rid}/compute")
    login_as(cl, me)
    r = _approve(cl, rid, PERIOD)
    assert r.status_code == 403 and "قسيمتك" in r.text


def test_loans_split_without_negative_instalments_and_a_third_person_cancels_an_approved_one(cl):
    _rates(cl)
    e = _staff(cl, "مقترض صغير", 300, omani=False)
    login_as(cl, "admin")
    tiny = cl.post("/api/hr/payroll/loans", json={"employee_id": e, "kind": "qard_hasan", "amount": 0.05, "installments": 60, "start_period": PERIOD}).json()["id"]
    one_omr = cl.post("/api/hr/payroll/loans", json={"employee_id": e, "kind": "qard_hasan", "amount": 1, "installments": 60, "start_period": PERIOD}).json()["id"]
    login_as(cl, _user(cl, "hrt-pay2", "payroll"))
    assert cl.post(f"/api/hr/payroll/loans/{tiny}/approve", json={"disbursed_on": TODAY.isoformat()}).status_code == 400
    assert cl.post(f"/api/hr/payroll/loans/{one_omr}/approve", json={"disbursed_on": TODAY.isoformat()}).status_code == 200
    sch = [x["amount"] for x in cl.get(f"/api/hr/payroll/loans/{one_omr}").json()["schedule"]]
    assert sum(sch) == pytest.approx(1.0) and min(sch) > 0 and sch[-1] >= sch[0]
    assert cl.post(f"/api/hr/payroll/loans/{one_omr}/cancel", json={"reason": "تراجع"}).status_code == 403   # the approver does not cancel what he approved
    login_as(cl, _user(cl, "hrt-pay3", "payroll"))
    assert cl.post(f"/api/hr/payroll/loans/{one_omr}/cancel", json={"reason": "تراجع"}).status_code == 200


# ----------------------------------------------------------------------------------------------------- 0.28.2 — the accepted-risk items of the audit
def test_a_leaver_with_pay_is_ended_by_the_settlement_and_not_by_the_status_switch(cl):
    _rates(cl)
    paid = _staff(cl, "موظف براتب", 400, omani=False)
    login_as(cl, "admin")
    bare = cl.post("/api/hr/employees", json={"name": "ملف بلا راتب", "omani": False, "hire_date": "2024-01-01"}).json()["id"]
    body = {"status": "terminated", "note": "استقالة", "date": TODAY.isoformat()}
    r = cl.post(f"/api/hr/employees/{paid}/status", json=body)
    assert r.status_code == 409 and "مخالصة" in r.json()["detail"]
    assert _sql("SELECT status FROM employees WHERE id=?", (paid,))[0]["status"] != "terminated"
    assert cl.post(f"/api/hr/employees/{bare}/status", json=body).status_code == 200   # nothing to settle: the switch is enough


def test_the_bank_account_of_a_run_awaiting_payment_is_not_rewritten_by_hr_alone(cl):
    _rates(cl)
    e = _staff(cl, "صاحب حساب", 400, omani=False)
    rid = _approved_run(cl)
    hr = _user(cl, "hrt-hr1", "hr")
    login_as(cl, hr)
    other = "OM110180000001299999999"
    r = cl.patch(f"/api/hr/employees/{e}", json={"iban": other})
    assert r.status_code == 409 and "معتمد" in r.json()["detail"]
    assert cl.patch(f"/api/hr/employees/{e}", json={"phone": "+968 90000009"}).status_code == 200   # other fields are not frozen
    login_as(cl, "admin")
    assert cl.patch(f"/api/hr/employees/{e}", json={"iban": other}).status_code == 200            # a payroll holder sees the payment and may correct the account
    assert cl.post(f"/api/hr/payroll/runs/{rid}/pay", json={"paid_on": TODAY.isoformat()}).status_code == 200
    login_as(cl, hr)
    assert cl.patch(f"/api/hr/employees/{e}", json={"iban": "OM810180000001299123456"}).status_code == 200   # once paid, HR edits again


def test_the_payment_journal_names_each_employee_and_the_portal_account_takes_no_unverified_email(cl):
    _rates(cl)
    login_as(cl, "admin")
    assert cl.post("/api/acc/activate", json={"start": (PS - dt.timedelta(days=40)).isoformat(), "confirm": True}).status_code == 200
    a = _staff(cl, "موظف أ", 500, omani=False)
    b = _staff(cl, "موظف ب", 300, omani=False)
    rid = _approved_run(cl)
    login_as(cl, "admin")
    bank = next(x["id"] for x in cl.get("/api/acc/banks").json() if x["kind"] == "bank")
    assert cl.post(f"/api/hr/payroll/runs/{rid}/pay", json={"paid_on": TODAY.isoformat(), "bank_account_id": bank}).status_code == 200
    jid = cl.get(f"/api/hr/payroll/runs/{rid}").json()["payment_journal_id"]
    lines = _sql("""SELECT l.party_id p, l.debit d FROM acc_lines l JOIN acc_accounts x ON x.id=l.account_id WHERE l.journal_id=? AND x.system_key='payroll_payable'""", (jid,))
    assert sorted(r["p"] for r in lines) == sorted([a, b]) and all(r["d"] > 0 for r in lines)
    by_emp = _sql("""SELECT l.party_id p, SUM(l.debit - l.credit) s FROM acc_lines l JOIN acc_accounts x ON x.id=l.account_id JOIN acc_journals j ON j.id=l.journal_id
                     WHERE x.system_key='payroll_payable' AND l.party_type='employee' AND j.status IN ('posted','reversed') GROUP BY l.party_id""")
    assert all(abs(r["s"]) < 1e-6 for r in by_emp), "each person's payable closes to nil on its own"
    # a portal login does not inherit the e-mail typed in the file (nobody has verified it)
    c2 = cl.post("/api/hr/employees", json={"name": "موظف بريد", "omani": False, "hire_date": "2024-01-01", "email": "typed-by-hr@example.test"}).json()["id"]
    assert cl.post(f"/api/hr/employees/{c2}/account").status_code == 200
    assert _sql("SELECT email FROM users WHERE employee_id=?", (c2,))[0]["email"] is None
