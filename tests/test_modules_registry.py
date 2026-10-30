"""0.20.0 — module registry: every route is classified, a switched-off module answers 404 and loses its permissions, the dashboard shows only
what the organisation has, licences bound the administrator, and existing developers are unchanged."""
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "mr.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "bayan:بيان عمان;almaqsura:المقصورة العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import registry as R  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect  # noqa: E402

CSRF = "csrf-modules-" + "m" * 28
LEASE = "almaqsura"


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
        for t in ("jadwa", "bayan", LEASE):
            tok = TENANT.set(t)
            try:
                d = connect()
                d.execute("DELETE FROM login_attempts")
                if d.has_table("org_modules"):
                    d.execute("DELETE FROM org_modules")
                d.commit()
                d.close()
            finally:
                TENANT.reset(tok)
        yield c


def _paths():
    return sorted(app.openapi()["paths"])


def test_every_api_path_is_classified():
    """A new route must be a deliberate core path or belong to a module's prefixes — never silently ungated."""
    core_ok = ("/api/auth", "/api/me", "/api/admin", "/api/users", "/api/audit", "/api/docs", "/api/documents", "/api/plans", "/api/notifications",
               "/api/privacy", "/api/projects", "/api/units", "/api/search", "/api/reset", "/api/appearance", "/api/public", "/api/v1",
               "/api/portal", "/api/decisions", "/api/kpis", "/api/dashboard", "/api/modules", "/api/license", "/api/tenants")
    stray = [p for p in _paths() if p.startswith("/api/") and R.route_module(p) is None and not any(p == c or p.startswith(c + "/") for c in core_ok)]
    assert stray == [], f"paths without a module or a core entry (add to registry.MODULES prefixes or to core_ok here): {stray}"


def test_prefix_map_has_no_dead_prefix():
    live = _paths()
    dead = [pre for m in R.MODULES.values() for pre in m["prefixes"] if not any(p == pre or p.startswith(pre + "/") for p in live)]
    assert dead == [], dead


def test_registry_dependencies_are_consistent():
    for k, m in R.MODULES.items():
        assert all(d in R.MODULES for d in m["deps"]), k
    for name, b in R.BUNDLES.items():
        closed = R._close(set(R._expand(list(b["modules"]))))
        assert closed == R._expand(list(b["modules"])), f"bundle {name} is not dependency-closed"
    assert R.effective_perms({"book", "view", "leasing"}, {"leasing"}) == ["leasing", "view"]
    assert R._close({"marketing"}) == set()  # marketing without sales cannot stand


def test_existing_developer_keeps_every_module(cl):
    login_as(cl, "admin", "jadwa")
    me = cl.get("/api/me").json()
    assert set(me["modules"]) == set(R.available())
    assert "book" in me["perms"] and "leasing" in me["perms"]
    assert cl.get("/api/leasing").status_code == 200 and cl.get("/api/bookings").status_code in (200, 405)


def test_leasing_company_sees_only_its_modules(cl):
    login_as(cl, "admin", LEASE)
    me = cl.get("/api/me").json()
    assert set(me["modules"]) == {"leasing", "finance", "reports", "assistant"}
    assert not {"book", "kyc", "brokers", "construction", "approve_ipc", "market", "handover", "oa", "land", "leads"} & set(me["perms"])
    assert {"leasing", "finance", "reports", "inventory", "view", "admin"} <= set(me["perms"])
    assert cl.get("/api/leasing").status_code == 200
    for path in ("/api/ipcs", "/api/leads", "/api/lands", "/api/campaigns", "/api/handover", "/api/quotes", "/api/kyc"):
        r = cl.get(path)
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}, (path, r.status_code, r.text)
    assert cl.post("/api/bookings", json={}).status_code == 404  # POST-only paths too (a GET there is a plain 405 for everyone)
    assert cl.get("/api/cash").status_code == 200  # finance is on


def test_dashboard_shows_only_enabled_modules(cl):
    login_as(cl, "admin", LEASE)
    d = cl.get("/api/dashboard").json()
    ids = {t["id"] for t in d["tiles"]}
    assert {"occupancy", "annualrent", "arrears", "expiring", "cashgap"} <= ids
    assert not ids & {"sales30", "collection", "stock"}, ids
    assert d["develop"] is False and d["lease_properties"] and "cash" in d
    kinds = {x["kind"] for x in d["decisions"]}
    assert not kinds & {"price", "reschedule", "ipc"}, kinds
    login_as(cl, "admin", "jadwa")
    j = cl.get("/api/dashboard").json()
    assert {"sales30", "collection", "stock", "cashgap", "occupancy"} <= {t["id"] for t in j["tiles"]} and j["develop"] is True


def test_decisions_hide_other_modules_and_act_is_refused(cl):
    login_as(cl, "admin", "jadwa")
    all_d = cl.get("/api/decisions").json()
    assert {"price", "ipc"} & {x["kind"] for x in all_d}
    ipc_key = next(x["key"] for x in all_d if x["kind"] == "price")
    r = cl.post("/api/modules", json={"modules": ["leasing", "finance", "reports"]})
    assert r.status_code == 200, r.text
    now = {x["kind"] for x in cl.get("/api/decisions").json()}
    assert not now & {"price", "reschedule", "ipc"}
    assert cl.post("/api/decisions/act", json={"key": ipc_key, "action": "approve"}).status_code == 404
    cl.post("/api/modules", json={"modules": R.available()})


def test_admin_toggles_with_dependencies_audit_and_no_data_loss(cl):
    login_as(cl, "admin", "bayan")
    before = cl.get("/api/units", params={"project_id": cl.get("/api/projects").json()[0]["id"]}).json()
    # disabling a module another one needs is refused with the reason
    r = cl.post("/api/modules", json={"modules": ["sales", "reports"]})  # sales needs finance
    assert r.status_code == 409 and "المالية" in r.json()["detail"]
    r = cl.post("/api/modules", json={"modules": ["sales"], "with_deps": True})
    assert r.status_code == 200 and set(r.json()["enabled"]) == {"sales", "finance"}
    me = cl.get("/api/me").json()
    assert set(me["modules"]) == {"sales", "finance"} and "reports" not in me["perms"] and "leasing" not in me["perms"]
    assert cl.get("/api/reports/catalog").status_code == 404 and cl.get("/api/leasing").status_code == 404
    log = cl.get("/api/license").json()["log"]
    assert any(x["action"] == "تعطيل وحدة" and x["detail"] == "الإيجارات" for x in log)
    # switching back restores everything, data untouched
    assert cl.post("/api/modules", json={"modules": R.available()}).status_code == 200
    after = cl.get("/api/units", params={"project_id": cl.get("/api/projects").json()[0]["id"]}).json()
    assert before == after and cl.get("/api/leasing").status_code == 200
    assert cl.post("/api/modules", json={"modules": ["nonsense"]}).status_code == 400
    assert cl.post("/api/modules", json={"modules": ["hr"]}).status_code == 200  # shipped in 0.25.0 (no dependencies)
    assert cl.post("/api/modules", json={"modules": R.available()}).status_code == 200


def test_licence_bounds_the_administrator(cl):
    login_as(cl, "admin", LEASE)
    mods = {m["key"]: m for m in cl.get("/api/modules").json()["modules"]}
    assert mods["leasing"]["enabled"] and mods["sales"]["licensed"] is False and mods["hr"]["available"] is True and mods["hr"]["licensed"] is False
    r = cl.post("/api/modules", json={"modules": ["sales", "finance"]})
    assert r.status_code == 403 and "ترخيص" in r.json()["detail"]
    os.environ["MABANIQ_LICENSES"] = f"{LEASE}:sales+leasing+finance+reports"
    try:
        assert cl.post("/api/modules", json={"modules": ["sales", "leasing", "finance"]}).status_code == 200
        assert "book" in cl.get("/api/me").json()["perms"]
    finally:
        os.environ.pop("MABANIQ_LICENSES", None)
    # licence withdrawn ⟵ the module is off again even though a row says on
    me = cl.get("/api/me").json()
    assert "sales" not in me["modules"] and "book" not in me["perms"]


def test_only_admin_changes_modules(cl):
    login_as(cl, "sales", "bayan")
    assert cl.post("/api/modules", json={"modules": ["sales"]}).status_code == 403
    assert cl.get("/api/modules").status_code == 403


def test_assistant_and_reports_follow_modules(cl):
    login_as(cl, "admin", LEASE)
    cat = cl.get("/api/reports/catalog").json()
    keys = {r["key"] for r in cat["ready"]}
    assert "sales" not in keys and "funnel" not in keys and "cash" in keys
    assert "bookings" not in {d["key"] for d in cat["datasets"]} and "invoices" in {d["key"] for d in cat["datasets"]}
    from backend.assistant import TOOL_MODULE, _allowed
    u = cl.get("/api/me").json()
    assert not _allowed(u, "project_ranking") and not _allowed(u, "bookings") and _allowed(u, "leasing") and _allowed(u, "find")
    assert TOOL_MODULE["leasing"] == "leasing"
