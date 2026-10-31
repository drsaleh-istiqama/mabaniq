"""0.29.0 — the whole demo organisation, every phase in order (backend/seed_org.py): nothing fails, the books balance and tie to payroll, the registry is filled, a rerun is free."""
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "sa.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "almukhatat:المخطط العقارية;bayan:بيان عمان;almaqsura:المقصورة العقارية;view:رؤية العقارية"

import pytest  # noqa: E402

from backend import seed_org  # noqa: E402
from backend.db import TENANT, connect  # noqa: E402
from backend.seed import seed  # noqa: E402

T = "almukhatat"


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
def out():
    seed(force=True, tenant=T)
    yield seed_org.ensure_org_demo(T)
    seed(force=True, tenant=T)       # leave the tenant as found (a persistent PostgreSQL test database is shared by the files that follow)


def test_every_phase_ran_without_failing(out):
    assert [p for p, *_ in seed_org.PHASES] == list(out), out
    assert all(isinstance(v, dict) for v in out.values()), out
    assert seed_org.pending(T) == []
    assert out["acc_ops"]["sync_errors"] == 0


def test_the_books_balance_and_tie_to_payroll(out):
    tb = q("""SELECT ROUND(SUM(l.debit)*1000)/1000 d, ROUND(SUM(l.credit)*1000)/1000 c FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id WHERE j.status IN ('posted','reversed')""")[0]
    assert tb["d"] and abs(tb["d"] - tb["c"]) < 0.01
    runs = q("SELECT status, journal_id, payment_journal_id FROM payroll_runs WHERE status IN ('approved','paid')")
    assert runs and all(r["journal_id"] for r in runs) and all(r["payment_journal_id"] for r in runs if r["status"] == "paid")
    # every person's payable account closes to zero — the paid runs and the settlement name the employee on both sides
    open_ = q("""SELECT l.party_id, ROUND(SUM(l.credit - l.debit)*1000)/1000 bal FROM acc_lines l JOIN acc_accounts a ON a.id=l.account_id JOIN acc_journals j ON j.id=l.journal_id
                 WHERE a.system_key='payroll_payable' AND j.status IN ('posted','reversed') GROUP BY l.party_id HAVING ABS(SUM(l.credit - l.debit)) > 0.001""")
    assert open_ == []


def test_the_registry_the_leasing_and_the_sales_side_are_filled(out):
    pol = q("SELECT status, COUNT(*) n FROM policies GROUP BY status")
    assert {p["status"] for p in pol} >= {"approved", "draft", "retired"}
    for t in ("policy_acks", "cheques", "maint_requests", "ap_bills", "fixed_assets", "vat_returns", "report_defs", "quotes", "campaigns", "charity_dues", "refunds", "doc_issues"):
        assert q(f"SELECT COUNT(*) n FROM {t}")[0]["n"] > 0, t
    # nothing earns interest anywhere in the seeded books
    assert not q("SELECT 1 FROM acc_accounts WHERE name LIKE '%فائدة%' OR name LIKE '%فوائد%'")
    assert not q("SELECT 1 FROM acc_journals WHERE memo LIKE '%فائدة%' OR memo LIKE '%فوائد%'")


def test_every_running_project_has_its_engineering_file_and_advances_became_loans(out):
    bare = q("""SELECT p.code FROM projects p WHERE COALESCE(p.completed,0)=0 AND NOT EXISTS (SELECT 1 FROM contracts_c k WHERE k.project_id=p.id)""")
    assert bare == []                                                    # no project in construction is left without its contractor
    for t in ("schedule_tasks", "budgets", "ipcs", "change_orders", "ncrs", "permits"):
        assert q(f"""SELECT p.code FROM projects p WHERE COALESCE(p.completed,0)=0 AND p.build_pct>0 AND NOT EXISTS (SELECT 1 FROM {t} x WHERE x.project_id=p.id)""") == [], t
    # an advance the HR officer approved reached payroll as a loan tied to the request, never a duplicate
    assert q("SELECT 1 FROM hr_requests WHERE kind='advance' AND status='approved'") == []
    ln = q("SELECT request_id FROM employee_loans WHERE request_id IS NOT NULL")
    assert ln and len({x["request_id"] for x in ln}) == len(ln)


def test_a_second_pass_does_nothing(out):
    again = seed_org.ensure_org_demo(T)
    assert set(again.values()) == {"done"}
    assert seed_org.ensure_org_demo("jadwa") == {}                       # a tenant without the flag is untouched
    assert seed_org.ensure_org_demo("almaqsura") == {}
