"""0.29.0 — the full-demo organisations: the people and payroll phases of `backend/seed_org.py`.

The seed goes through the platform's own functions, so these tests check what must hold for *any* data produced that way: the second person really was a second person,
nobody is paid twice, a leaver is settled and left out of the next run, an expired document shows in the alerts, a rerun adds nothing, and the screens' own endpoints read
the result without error. They never assume how many employees there are — only that the invariants hold for however many the seed made."""
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "so.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "almukhatat:المخطط العقارية;bayan:بيان عمان;almaqsura:المقصورة العقارية;view:رؤية العقارية"
os.environ.setdefault("MABANIQ_PILOT_PASSWORD", "Pilot-Pass-2026-xx")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import seed_org  # noqa: E402
from backend import tenant_profiles as TP  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect  # noqa: E402
from backend.seed import seed  # noqa: E402

CSRF = "csrf-seedorg-" + "q" * 28
T = "bayan"


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


def q(sql, *args):
    tok = TENANT.set(T)
    try:
        c = connect()
        try:
            return [dict(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()
    finally:
        TENANT.reset(tok)


@pytest.fixture(scope="module")
def cl():
    from backend import observability as O
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture(scope="module")
def org(cl):
    seed(force=True, tenant=T)
    yield seed_org.ensure_org_demo(T, ("hr", "pay"))
    seed(force=True, tenant=T)       # leave the tenant as found (a persistent PostgreSQL test database is shared by the files that follow)


def test_the_phases_ran_and_a_rerun_adds_nothing(org):
    assert isinstance(org["hr"], dict) and isinstance(org["pay"], dict), org
    before = {t: q(f"SELECT COUNT(*) n FROM {t}")[0]["n"] for t in ("employees", "leave_requests", "payslips", "salary_structures", "appraisals", "penalty_rules", "training_records")}
    assert before["employees"] >= 15 and before["payslips"] > before["employees"]
    again = seed_org.ensure_org_demo(T, ("hr", "pay"))
    assert again["hr"] == "done" and again["pay"] == "done"               # the markers stop a second run
    tok = TENANT.set(T)
    try:
        c = connect()
        c.execute("DELETE FROM settings WHERE k LIKE 'demo_org:%'")
        c.commit()
        c.close()
    finally:
        TENANT.reset(tok)
    seed_org.ensure_org_demo(T, ("hr", "pay"))                           # even with the markers gone, every section finds its rows and adds none
    after = {t: q(f"SELECT COUNT(*) n FROM {t}")[0]["n"] for t in before}
    assert after == before


def test_payroll_history_is_maker_checker_and_the_leaver_is_settled(org):
    runs = q("SELECT * FROM payroll_runs ORDER BY period")
    paid = [r for r in runs if r["status"] == "paid"]
    assert len(paid) >= 5 and runs[-1]["status"] == "computed"           # closed months paid, the month in progress waits for its approval
    for r in paid:
        assert r["computed_by"] and r["approved_by"] and r["computed_by"] != r["approved_by"]
        assert r["paid_on"] and r["net"] > 0 and r["headcount"] > 0
    t = q("SELECT * FROM terminations")
    assert len(t) == 1 and t[0]["status"] == "paid" and t[0]["created_by"] != t[0]["approved_by"]
    leaver = q("SELECT status, terminated_on FROM employees WHERE id=?", t[0]["employee_id"])[0]
    assert leaver["status"] == "terminated"
    in_current = q("SELECT 1 FROM payslips WHERE run_id=? AND employee_id=?", runs[-1]["id"], t[0]["employee_id"])
    assert not in_current                                                # service ended before the month in progress began
    assert not q("SELECT 1 FROM loan_installments i JOIN employee_loans l ON l.id=i.loan_id WHERE l.employee_id=? AND i.status='due'", t[0]["employee_id"])
    assert t[0]["net"] > 0 and t[0]["eosb_amount"] > 0


def test_social_insurance_only_for_omanis_and_loans_carry_no_interest(org):
    sl = q("""SELECT s.pasi_employee, s.pasi_employer, e.omani FROM payslips s JOIN employees e ON e.id=s.employee_id
              JOIN payroll_runs r ON r.id=s.run_id WHERE r.status='paid' AND s.gross > 0""")
    assert any(x["omani"] and x["pasi_employee"] > 0 and x["pasi_employer"] > 0 for x in sl)
    assert all(x["pasi_employee"] == 0 and x["pasi_employer"] == 0 for x in sl if not x["omani"])
    tok = TENANT.set(T)
    try:
        c = connect()
        try:
            cols = set(c.columns("employee_loans"))
        finally:
            c.close()
    finally:
        TENANT.reset(tok)
    assert cols and not ({"rate", "interest", "fee", "profit"} & cols)
    for ln in q("SELECT l.amount, (SELECT COALESCE(SUM(i.amount),0) FROM loan_installments i WHERE i.loan_id=l.id) total FROM employee_loans l WHERE l.status IN ('active','paid')"):
        assert abs(ln["amount"] - ln["total"]) < 0.01                    # repaid at exactly the amount lent


def test_the_bylaw_and_the_cases_respect_the_two_person_rules(org):
    rules = q("SELECT * FROM penalty_rules")
    assert len(rules) >= 8 and all(r["status"] == "approved" and r["approved_by"] != r["created_by"] and "افتراضية" in r["source"] for r in rules)
    cases = q("SELECT * FROM disciplinary_cases")
    assert {c["status"] for c in cases} >= {"issued", "proposed", "open", "closed"}
    for c in cases:
        if c["status"] in ("issued", "appealed", "revoked"):
            assert c["proposed_by"] and c["issued_by"] and c["proposed_by"] != c["issued_by"] and c["statement"]
            assert c["rule_id"]                                           # no penalty without an approved article
    # a deduction applied by payroll shows on the payslip as a warning line, valued from the salary
    assert q("SELECT 1 FROM payslips WHERE warnings LIKE '%discipline%'")


def test_leave_is_real_and_balances_never_go_negative(org, cl):
    login_as(cl, "admin")
    st = {r["status"] for r in q("SELECT status FROM leave_requests")}
    assert st >= {"approved", "pending", "rejected", "cancelled"}
    assert not q("SELECT 1 FROM leave_requests r JOIN leave_types t ON t.id=r.type_id WHERE r.status='approved' AND t.needs_doc=1 AND r.doc_id IS NULL")
    for e in q("SELECT id FROM employees WHERE status!='terminated'")[:6]:
        for b in cl.get(f"/api/hr/employees/{e['id']}/leave-balances").json():
            if b["capped"]:
                assert b["remaining"] >= -1e-9, b


def test_alerts_trainings_and_screens_read_the_data(org, cl):
    login_as(cl, "admin")
    al = cl.get("/api/hr/alerts?days=90").json()
    assert any(a["level"] == "expired" for a in al) and any(a["level"] in ("critical", "soon") for a in al)
    comp = cl.get("/api/hr/training/compliance")
    assert comp.status_code == 200
    for url in ("/api/hr/summary", "/api/hr/employees", "/api/hr/payroll/runs", "/api/hr/payroll/loans", "/api/hr/discipline/cases", "/api/hr/appraisals", "/api/hr/recruitment/candidates",
                "/api/hr/leave/requests", "/api/hr/holidays", "/api/hr/payroll/rates", "/api/hr/eosb/rules"):
        assert cl.get(url).status_code == 200, url
    run = q("SELECT id FROM payroll_runs WHERE status='paid' ORDER BY period DESC LIMIT 1")[0]["id"]
    assert cl.get(f"/api/hr/payroll/runs/{run}").status_code == 200
    w = cl.get(f"/api/hr/payroll/runs/{run}/wps").json()
    assert w["lines"] and w["total"] > 0 and not [p for p in w["problems"] if p["error"]]   # the wage file is exportable: every payee has a well-formed IBAN


def test_trial_logins_are_linked_to_their_employee_files(org):
    tok = TENANT.set(T)
    try:
        c = connect()
        try:
            assert TP.ensure_pilot_accounts(c, T) >= 0
            c.commit()
            rows = {r["username"]: r for r in c.execute("SELECT username, role, employee_id FROM users WHERE username LIKE 'bayan-%'").fetchall()}
        finally:
            c.close()
    finally:
        TENANT.reset(tok)
    assert rows["bayan-hr"]["role"] == "hr" and rows["bayan-hr"]["employee_id"]
    assert rows["bayan-employee"]["role"] == "employee" and rows["bayan-employee"]["employee_id"]
    assert rows["bayan-payroll"]["role"] == "payroll" and rows["bayan-payroll"]["employee_id"] is None
