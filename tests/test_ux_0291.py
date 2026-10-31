"""0.29.1 — the gaps found while writing the operating manuals: the audit log is searchable / filterable / paged, and editing a tenant keeps all sixteen fields."""
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "ux.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "bayan:بيان عمان;almaqsura:المقصورة العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect  # noqa: E402

CSRF = "csrf-ux0291-" + "u" * 28
NAME = "مستأجر اختبار الواجهة 0291"


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


@pytest.fixture(scope="module", autouse=True)
def _purge_my_rows():
    yield
    tok = TENANT.set("bayan")
    try:
        c = connect()
        c.execute("DELETE FROM tenants_l WHERE name=?", (NAME,))
        c.commit()
        c.close()
    finally:
        TENANT.reset(tok)


FULL = {"name": NAME, "phone": "+96891234567", "id_number": "12345678", "kind": "company", "cr_number": "CR778899", "tax_no": "OM1100223344",
        "rep_name": "سالم بن خلفان", "rep_title": "المدير العام", "rep_id_number": "87654321", "contact_name": "مكتب الاستقبال", "email": "ux0291@example.test",
        "address": "مسقط، الخوير", "nationality": "عُماني", "id_expiry": "2031-05-20", "rating": "B", "rating_note": "يسدد قبل الموعد بيومين غالبًا"}


def test_editing_a_tenant_keeps_all_sixteen_fields(cl):
    tid = cl.post("/api/lea/tenants", json=FULL).json()["id"]
    got = cl.get(f"/api/lea/tenants/{tid}").json()
    body = {k: got[k] or "" for k in FULL}
    body["phone"] = "+96899990000"                      # the form changes one field and sends the whole record
    assert cl.post(f"/api/lea/tenants/{tid}", json=body).status_code == 200
    after = cl.get(f"/api/lea/tenants/{tid}").json()
    for k in FULL:
        assert after[k] == (body[k] or None) or after[k] == body[k], k
    assert after["rating"] == "B" and after["nationality"] == "عُماني" and after["tax_no"] == "OM1100223344" and after["id_number"] == "12345678"


def test_audit_log_search_actor_dates_and_paging(cl):
    cl.post("/api/lea/tenants", json={**FULL, "name": NAME + " ب"})
    all_rows = cl.get("/api/audit", params={"limit": 500}).json()
    assert all_rows and all(set(("at", "actor", "action", "detail")) <= set(r) for r in all_rows)
    hit = cl.get("/api/audit", params={"q": "إضافة مستأجر", "limit": 500}).json()
    assert hit and all("إضافة مستأجر" in (r["action"] or "") + (r["detail"] or "") + (r["actor"] or "") for r in hit)
    assert len(hit) < len(all_rows)
    assert cl.get("/api/audit", params={"q": "لا-يوجد-هذا-النص-أبدًا-9f3"}).json() == []
    actors = cl.get("/api/audit/actors").json()
    assert actors and actors == sorted(actors)
    who = hit[0]["actor"]
    by_actor = cl.get("/api/audit", params={"actor": who, "limit": 500}).json()
    assert by_actor and all(r["actor"] == who for r in by_actor)
    day = hit[0]["at"][:10]
    same_day = cl.get("/api/audit", params={"since": day, "until": day, "limit": 500}).json()
    assert same_day and all(r["at"][:10] == day for r in same_day)
    assert cl.get("/api/audit", params={"until": "2000-01-01"}).json() == []
    p1 = cl.get("/api/audit", params={"limit": 2, "offset": 0}).json()
    p2 = cl.get("/api/audit", params={"limit": 2, "offset": 2}).json()
    assert len(p1) == 2 and {r["id"] for r in p1}.isdisjoint({r["id"] for r in p2})
    assert p1[0]["id"] > p1[1]["id"] > p2[0]["id"]      # newest first, the second page continues where the first stopped
    assert cl.get("/api/audit", params={"offset": -1}).status_code == 422
