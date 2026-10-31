"""0.29.3 — the last buttons the manuals found missing: units outside the leasing portfolio, a cheque linked to one due, an unscheduled handover list, budgets."""
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "ux3.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "almukhatat:المخطط العقارية;bayan:بيان عمان;almaqsura:المقصورة العقارية;view:رؤية العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect  # noqa: E402

CSRF = "csrf-ux0293-" + "u" * 28


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
        yield login_as(c, "admin", "bayan")


def _sql(sql, args=()):
    """Run one raw write as the tenant (maintenance mode on PostgreSQL, which scopes the row by hand)."""
    tok = TENANT.set("bayan")
    try:
        c = connect()
        if getattr(c, "dialect", "sqlite") == "postgres":
            c.maintenance()
        c.execute(sql, args)
        c.commit()
        c.close()
    finally:
        TENANT.reset(tok)


def test_units_outside_the_portfolio_can_be_listed_and_added(cl):
    cand = cl.get("/api/lea/units/candidates").json()
    assert isinstance(cand, list)
    assert all({"id", "code", "project"} <= set(x) and x["status"] != "s" for x in cand)
    in_portfolio = {u["id"] for u in cl.get("/api/lea/units").json()["units"]}
    assert not in_portfolio & {x["id"] for x in cand}
    if not cand:
        pytest.skip("this tenant has no unit outside the leasing portfolio")
    uid = cand[0]["id"]
    try:
        assert cl.post(f"/api/lea/units/{uid}", json={"retained": True, "use": "residential"}).status_code == 200
        assert uid in {u["id"] for u in cl.get("/api/lea/units").json()["units"]}
        assert uid not in {x["id"] for x in cl.get("/api/lea/units/candidates").json()}
        added = next(u for u in cl.get("/api/lea/units").json()["units"] if u["id"] == uid)
        assert added["state"] == "vacant" and added["use"] == "residential"      # nothing leases it yet
    finally:
        cl.post(f"/api/lea/units/{uid}", json={"retained": False})
    assert uid in {x["id"] for x in cl.get("/api/lea/units/candidates").json()}


def test_unscheduled_handover_list_holds_confirmed_bookings_without_a_row(cl):
    un = cl.get("/api/handover/unscheduled").json()
    assert isinstance(un, list)
    assert all({"booking_id", "unit", "customer", "project"} <= set(x) for x in un)
    scheduled = {h["booking_id"] for h in cl.get("/api/handover").json()}
    assert not scheduled & {x["booking_id"] for x in un}
    if not un:
        pytest.skip("every confirmed booking of this tenant already has an appointment")
    bid = un[0]["booking_id"]
    try:
        assert cl.post(f"/api/bookings/{bid}/handover/schedule", json={"appointment": "2099-01-01"}).status_code == 200
        assert bid not in {x["booking_id"] for x in cl.get("/api/handover/unscheduled").json()}
        assert bid in {h["booking_id"] for h in cl.get("/api/handover").json()}
    finally:
        _sql("DELETE FROM handovers WHERE booking_id=?", (bid,))


def test_a_cheque_can_be_tied_to_one_due_and_not_beyond_its_balance(cl):
    L = next((x for x in cl.get("/api/lea/leases").json() if x["status"] == "active"), None)
    if not L:
        pytest.skip("no active lease")
    d = cl.get(f"/api/lea/leases/{L['id']}").json()
    due = next((x for x in d["dues"] if x["balance"] > 0.5), None)
    if not due:
        pytest.skip("no open due")
    base = {"lease_id": L["id"], "due_id": due["id"], "bank": "بنك اختبار", "due_date": "2099-01-01"}
    assert cl.post("/api/lea/cheques", json={**base, "number": "UX293-OVER", "amount": due["balance"] + 5}).status_code == 409     # beyond the due's balance
    r = cl.post("/api/lea/cheques", json={**base, "number": "UX293-OK", "amount": 1})
    assert r.status_code == 200
    try:
        q = next(x for x in cl.get("/api/lea/cheques").json() if x["number"] == "UX293-OK")
        assert q["due_id"] == due["id"] and q["status"] == "held"
        assert cl.post(f"/api/lea/cheques/{q['id']}/return", json={"reason": "اختبار الواجهة"}).status_code == 200
    finally:
        _sql("DELETE FROM cheques WHERE number=?", ("UX293-OK",))


def test_a_yearly_budget_is_spread_over_twelve_months_and_reads_back_against_actuals(cl):
    if not cl.get("/api/acc/status").json()["active"]:
        assert cl.post("/api/acc/activate", json={"start": "2026-01-01", "confirm": True}).status_code == 200
    accs = cl.get("/api/acc/accounts").json()
    exp = next(a for a in accs if a["type"] == "expense" and a["postable"] and a["active"])
    total = 1000.001                                                            # not divisible by 12: the last month carries the remainder
    base = int(total * 1000) // 12
    cells = [{"account": exp["id"], "month": m, "amount": (base if m < 12 else int(total * 1000) - base * 11) / 1000} for m in range(1, 13)]
    try:
        assert cl.post("/api/acc/budgets", json={"year": 2099, "lines": cells}).json()["cells"] == 12
        rep = cl.get("/api/acc/budget-report", params={"year": 2099, "to_month": 12}).json()
        row = next(x for x in rep["rows"] if x["code"] == exp["code"])
        assert abs(row["budget"] - total) < 0.0005 and row["actual"] == 0 and row["variance"] == row["budget"]
        half = cl.get("/api/acc/budget-report", params={"year": 2099, "to_month": 6}).json()
        assert abs(next(x for x in half["rows"] if x["code"] == exp["code"])["budget"] - base * 6 / 1000) < 0.0005
        assert cl.get("/api/acc/budget-report", params={"year": 2099, "to_month": 13}).status_code == 422
    finally:
        cl.post("/api/acc/budgets", json={"year": 2099, "lines": [{**c, "amount": 0} for c in cells]})
    after = cl.get("/api/acc/budget-report", params={"year": 2099, "to_month": 12}).json()
    assert all(x["code"] != exp["code"] for x in after["rows"])
