"""0.29.0 — the books and leasing-operations phases of the full-demo developers (backend/seed_org_acc.py, seed_org_lea.py, seed_org_rep.py).

The two demo developers (bayan, almukhatat) are seeded in a throw-away folder and filled through the module endpoint functions; then the books are checked the way an
accountant would: the ledger balances, nothing is posted without its partner, the work the screens need exists, a second run adds nothing, and there is no interest anywhere.
"""
import os

import pytest

TENANTS = ("bayan", "almukhatat")
PHASES = ("acc_base", "lea", "acc_ops", "rep")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    d = tmp_path_factory.mktemp("orgbooks")
    mp.setenv("MABANIQ_DB", os.path.join(str(d), "m.db"))
    mp.setenv("MABANIQ_TENANTS", "almukhatat:المخطط العقارية;bayan:بيان عمان")
    mp.setenv("MABANIQ_FORCE_PW_CHANGE", "0")
    mp.setenv("MABANIQ_CACHE_TTL", "0")
    from backend import common
    from backend.seed import seed
    from backend.seed_org import ensure_org_demo
    saved = set(common._ready)       # which tenants other test modules already initialised — put back as found, so the order of the test files does not matter
    common.reset_ready()
    out = {}
    for t in TENANTS:
        seed(force=True, tenant=t)
        out[t] = ensure_org_demo(t, phases=PHASES)
    yield out
    for t in TENANTS:                  # a persistent (PostgreSQL) test database must not keep the filled organisation for the test files that run after this one
        seed(force=True, tenant=t)
    mp.undo()
    common._ready.clear()
    common._ready.update(saved)


def q(tenant, sql, args=()):
    from backend.db import TENANT, connect
    tok = TENANT.set(tenant)
    try:
        c = connect()
        try:
            return [dict(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()
    finally:
        TENANT.reset(tok)


def n(tenant, sql, args=()):
    return list(q(tenant, sql, args)[0].values())[0]


@pytest.mark.parametrize("t", TENANTS)
def test_every_phase_ran_and_none_failed(world, t):
    res = world[t]
    assert set(res) == set(PHASES), res
    for ph, r in res.items():
        assert isinstance(r, dict), (ph, r)
    # the work each phase is for
    assert res["acc_base"].get("activated") and res["acc_base"].get("banks", 0) >= 2 and res["acc_base"].get("vendors", 0) >= 8
    assert res["lea"].get("leases", 0) >= 10 and res["lea"].get("receipts", 0) >= 30 and res["lea"].get("cheques", 0) >= 8
    assert res["acc_ops"].get("bills", 0) >= 15 and res["acc_ops"].get("sync_errors", 0) == 0, res["acc_ops"]
    assert q(t, "SELECT COUNT(*) n FROM report_defs")[0]["n"] >= 20      # saved reports survive a reset (not in the wipe list), so the phase may have found them already there
    assert q(t, "SELECT COUNT(*) n FROM report_schedules")[0]["n"] >= 5


@pytest.mark.parametrize("t", TENANTS)
def test_the_ledger_balances_and_the_screens_have_their_data(world, t):
    assert n(t, "SELECT COUNT(*) FROM acc_accounts") > 50
    d = q(t, "SELECT COALESCE(SUM(l.debit),0) d, COALESCE(SUM(l.credit),0) c FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id WHERE j.status IN ('posted','reversed')")[0]
    assert d["d"] > 100000 and abs(d["d"] - d["c"]) < 0.01
    # every posted journal balances on its own
    assert n(t, """SELECT COUNT(*) FROM (SELECT j.id FROM acc_journals j JOIN acc_lines l ON l.journal_id=j.id WHERE j.status='posted' GROUP BY j.id
                   HAVING ABS(SUM(l.debit)-SUM(l.credit))>0.0005)""") == 0
    assert n(t, "SELECT COUNT(*) FROM acc_journals WHERE kind='opening' AND status='posted'") == 1
    assert n(t, "SELECT COUNT(*) FROM acc_journals WHERE kind='manual' AND status='posted'") >= 5
    assert n(t, "SELECT COUNT(*) FROM acc_journals WHERE kind='manual' AND status='pending'") == 1 and n(t, "SELECT COUNT(*) FROM acc_journals WHERE kind='manual' AND status='draft'") == 1
    for tbl, floor in (("ap_bills", 15), ("ap_payments", 10), ("fixed_assets", 3), ("depreciation_runs", 6), ("acc_budgets", 80), ("vat_returns", 2), ("bank_recons", 1),
                       ("bank_stmt_lines", 10), ("fin_contracts", 2), ("fin_installments", 20), ("vendors", 8), ("cheques", 8), ("maint_requests", 8), ("maint_orders", 6),
                       ("property_expenses", 10), ("owner_statements", 3), ("lease_handovers", 5), ("arrears_notices", 3), ("payment_plans", 1), ("unit_meters", 8),
                       ("common_facilities", 10), ("report_defs", 20), ("report_schedules", 1)):
        assert n(t, f"SELECT COUNT(*) FROM {tbl}") >= floor, tbl
    # the first active bank account is the main current account (payroll takes its money from there), not the cash box
    assert q(t, "SELECT kind FROM bank_accounts WHERE active=1 ORDER BY id LIMIT 1")[0]["kind"] == "bank"
    # accounting is active from 1 January and the old months are closed, the current one is open
    import datetime as dt
    y = dt.date.today().year
    assert n(t, "SELECT v FROM settings WHERE k='acc_start'") == f"{y}-01-01"
    assert n(t, "SELECT COUNT(*) FROM acc_periods WHERE status='closed'") >= 1
    assert n(t, "SELECT COUNT(*) FROM acc_periods WHERE status='closed' AND year=? AND month=?", (y, dt.date.today().month)) == 0
    # a reconciliation was closed balanced
    assert n(t, "SELECT COUNT(*) FROM bank_recons WHERE ABS(difference)<0.0005") >= 1


@pytest.mark.parametrize("t", TENANTS)
def test_leasing_situations_exist_and_the_payments_reach_the_books(world, t):
    st = {r["status"] for r in q(t, "SELECT DISTINCT status FROM leases")}
    assert {"active", "expired", "terminated", "renewed"} <= st, st
    assert n(t, "SELECT COUNT(*) FROM cheques WHERE direction='in' AND status IN ('held','deposited','cleared','bounced','returned') GROUP BY direction") >= 8
    assert {r["status"] for r in q(t, "SELECT DISTINCT status FROM cheques WHERE direction='in'")} >= {"held", "cleared", "bounced", "returned"}
    assert n(t, "SELECT COUNT(*) FROM maint_requests WHERE status='rejected'") >= 1 and n(t, "SELECT COUNT(*) FROM maint_requests WHERE status='closed'") >= 1
    assert n(t, "SELECT COUNT(*) FROM owners WHERE kind='third_party'") == 1
    assert n(t, "SELECT COUNT(*) FROM owner_statements WHERE status='transferred'") >= 1
    assert n(t, "SELECT COUNT(*) FROM tenants_l WHERE blacklisted=1") == 1
    assert n(t, "SELECT COUNT(*) FROM units WHERE lease_state='maintenance'") == 1
    assert n(t, "SELECT COUNT(*) FROM charity_dues") >= 1
    # the cached paid amounts equal the immutable receipts ledger
    from backend.db import TENANT, connect
    from backend.leasing import ledger_mismatches
    tok = TENANT.set(t)
    try:
        c = connect()
        assert ledger_mismatches(c) == []
        c.close()
    finally:
        TENANT.reset(tok)
    # arrears are real (an open aging bucket), and an unpaid supplier bill is overdue
    assert n(t, "SELECT COUNT(*) FROM rent_dues WHERE due<? AND amount-paid>0.0005 AND COALESCE(kind,'rent')<>'deposit'", (dt_today(),)) >= 2
    assert n(t, "SELECT COUNT(*) FROM ap_bills WHERE status='approved'") >= 2


def dt_today():
    import datetime as dt
    return dt.date.today().isoformat()


@pytest.mark.parametrize("t", TENANTS)
def test_no_interest_anywhere(world, t):
    kinds = {r["kind"] for r in q(t, "SELECT DISTINCT kind FROM fin_contracts")}
    assert kinds <= {"murabaha", "ijara", "installment", "istisna"}
    from backend.db import TENANT, connect
    tok = TENANT.set(t)
    try:
        c = connect()
        try:
            cols = set(c.columns("fin_contracts")) | set(c.columns("fin_installments"))
        finally:
            c.close()
    finally:
        TENANT.reset(tok)
    assert not {c for c in cols if "rate" in c or "interest" in c}
    for bad in ("فائدة", "فوائد", "الربا", "ربوي"):
        assert n(t, "SELECT COUNT(*) FROM acc_journals WHERE memo LIKE ?", (f"%{bad}%",)) == 0
        assert n(t, "SELECT COUNT(*) FROM acc_accounts WHERE name LIKE ?", (f"%{bad}%",)) == 0
    # every bank account is Islamic
    assert n(t, "SELECT COUNT(*) FROM bank_accounts WHERE islamic<>1") == 0


@pytest.mark.parametrize("t", TENANTS)
def test_a_second_run_adds_nothing(world, t):
    from backend.seed_org import ensure_org_demo
    again = ensure_org_demo(t, phases=PHASES)
    assert all(v == "done" for v in again.values()), again
    tables = ("leases", "rent_payments", "cheques", "maint_requests", "property_expenses", "ap_bills", "payment_orders", "acc_journals", "fixed_assets", "vendors", "report_defs",
              "owner_statements", "bank_stmt_lines", "fin_contracts", "tenants_l", "unit_meters", "common_facilities", "acc_budgets")
    before = {x: n(t, f"SELECT COUNT(*) FROM {x}") for x in tables}
    # forget the markers: every phase runs again over the data it already made (the crash-between-commit-and-marker case)
    from backend.db import TENANT, connect
    tok = TENANT.set(t)
    try:
        c = connect()
        c.execute("DELETE FROM settings WHERE k LIKE 'demo_org:%'")
        c.commit()
        c.close()
    finally:
        TENANT.reset(tok)
    ensure_org_demo(t, phases=PHASES)
    after = {x: n(t, f"SELECT COUNT(*) FROM {x}") for x in tables}
    assert after == before, {k: (before[k], after[k]) for k in tables if before[k] != after[k]}
