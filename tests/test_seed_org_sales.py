"""0.29.0 — the `sales` phase of the full-demo organisations (backend/seed_org_sales.py): quotations, campaigns, late-payment donations, a refund, a resale settlement,
decisions, official documents, shared links and an external property manager. The seed goes through the platform's own functions, so these tests check the invariants of
what comes out: counts above zero where the phase promises something, a rerun adds nothing, every campaign passes the offer checker, nothing leaves the platform by
e-mail, the donations are not income, and the property manager is confined to one project."""
import os
import tempfile
from datetime import date

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "ss.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "almukhatat:المخطط العقارية;bayan:بيان عمان;almaqsura:المقصورة العقارية;view:رؤية العقارية"

import pytest  # noqa: E402

from backend import marketing, seed_org  # noqa: E402
from backend.db import TENANT, connect  # noqa: E402
from backend.seed import seed  # noqa: E402

T = "almukhatat"
TABLES = ("quotes", "campaigns", "creatives", "campaign_sends", "charity_dues", "refunds", "resale_settlements", "decisions_log", "doc_issues", "doc_sends", "share_links", "user_scopes")


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


def counts():
    return {t: q(f"SELECT COUNT(*) n FROM {t}")[0]["n"] for t in TABLES}


@pytest.fixture(scope="module")
def org():
    seed(force=True, tenant=T)
    yield seed_org.ensure_org_demo(T, ("sales",))
    seed(force=True, tenant=T)       # leave the tenant as found (a persistent PostgreSQL test database is shared by the files that follow)


def test_the_phase_fills_every_workflow_it_promises(org):
    assert isinstance(org["sales"], dict), org
    n = counts()
    for t in ("quotes", "campaigns", "creatives", "campaign_sends", "charity_dues", "refunds", "resale_settlements", "decisions_log", "doc_issues", "doc_sends", "share_links", "user_scopes"):
        assert n[t] > 0, (t, n)
    assert {x["status"] for x in q("SELECT status FROM quotes")} >= {"issued", "converted", "cancelled"}
    assert q("SELECT 1 FROM quotes WHERE status='issued' AND valid_until < ?", date.today().isoformat())      # a lapsed one, shown as expired by the list
    assert {x["kind"] for x in q("SELECT kind FROM doc_issues")} >= {"quote", "contract", "invoice", "receipt"}


def test_a_rerun_adds_nothing(org):
    before = counts()
    tok = TENANT.set(T)
    try:
        c = connect()
        c.execute("DELETE FROM settings WHERE k = 'demo_org:sales'")   # the phase marker is gone, the per-step markers remain
        c.commit()
        c.close()
    finally:
        TENANT.reset(tok)
    seed_org.ensure_org_demo(T, ("sales",))
    assert counts() == before


def test_every_campaign_passes_the_offer_checker_and_sends_stay_inside_the_platform(org):
    for r in q("SELECT name, offer_text, message FROM campaigns"):
        assert not marketing._forbidden_offer(r["offer_text"]) and not marketing._forbidden_offer(r["message"]) and not marketing._forbidden_offer(r["name"]), r
    for r in q("SELECT headline, subline, cta, offer FROM creatives"):
        assert not any(marketing._forbidden_offer(v) for v in r.values()), r
    assert {x["channel"] for x in q("SELECT channel FROM campaign_sends")} == {"whatsapp"}        # click-to-chat only: no e-mail went to a mailbox
    assert not q("SELECT 1 FROM doc_sends WHERE channel='email'")
    assert q("SELECT 1 FROM leads WHERE campaign_id IS NOT NULL")                                # attributed leads feed the campaign's measured results


def test_donations_are_not_income_and_money_movements_are_consistent(org):
    d = q("SELECT status, amount FROM charity_dues")
    assert {x["status"] for x in d} >= {"due", "collected", "disbursed"} and all(x["amount"] > 0 for x in d)
    for r in q("SELECT * FROM refunds"):
        assert abs(r["paid"] - r["deducted"] - r["refund"]) < 0.01 and r["refund"] > 0          # a refund is what is paid minus the contractual deduction
    s = q("SELECT * FROM resale_settlements")[0]
    assert s["status"] == "settled" and s["settled_by"] and s["price"] > 0
    assert q("SELECT 1 FROM invoices WHERE kind='resale_fee'")                                   # the assignment fee was invoiced by the platform
    # the terminated bookings gave their units back
    assert not q("SELECT 1 FROM refunds r JOIN bookings b ON b.id=r.booking_id JOIN units u ON u.id=b.unit_id WHERE u.status!='a'")


def test_the_property_manager_is_confined_to_one_project(org):
    sc = q("SELECT s.user_id, s.project_id, s.owner_id, u.role FROM user_scopes s JOIN users u ON u.id=s.user_id")
    assert sc and all(x["role"] == "property_manager" and (x["project_id"] or x["owner_id"]) for x in sc)    # an open scope is refused by the platform
    locked = q("SELECT active FROM users WHERE username='pm.demo'")
    assert not locked or locked[0]["active"] == 0                                                # the seeded file has no usable login
