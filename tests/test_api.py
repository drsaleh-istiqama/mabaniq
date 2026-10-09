import json
import os
import tempfile

os.environ["MABANIQ_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402

KYC = {"id_type": "بطاقة مدنية", "id_number": "12345678", "nationality": "عُماني", "id_expiry": "2030-01-01", "source_of_funds": "راتب", "consent_signed": True}


def kyc(c, customer_id):
    who = c.cookies.get(A.COOKIE)
    as_user(c, "admin")
    assert c.post(f"/api/customers/{customer_id}/kyc", json=KYC).json()["status"] == "verified"
    c.cookies.set(A.COOKIE, who)


CSRF = 'csrf-test-token-' + 'x' * 24


def as_user(c, username):
    c.cookies.set(A.COOKIE, A.issue_session(username))
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


@pytest.fixture()
def cl():
    with TestClient(app) as c:
        as_user(c, "admin")
        c.post("/api/reset")
        as_user(c, "admin")
        yield c


def test_projects_and_kpis(cl):
    p = cl.get("/api/projects").json()
    assert len(p) == 5 and sum(x["total_units"] for x in p) == 468
    k = cl.get("/api/kpis").json()
    assert 0 <= k["collection_rate"] <= 100 and k["available"] > 0


def test_booking_lifecycle(cl):
    pid = cl.get("/api/projects").json()[0]["id"]
    u = next(x for x in cl.get(f"/api/units?project_id={pid}").json() if x["status"] == "a")
    r = cl.post("/api/bookings", json={"unit_code": u["code"], "customer_name": "عميل اختبار", "phone": "+96891234567", "plan": "milestone"})
    assert r.status_code == 200
    body = r.json()
    assert abs(sum(s["amount"] for s in body["schedule"]) - u["price"]) <= len(body["schedule"])
    assert body["deposit"] == round(u["price"] * .1)
    # لا حجز مزدوج
    r2 = cl.post("/api/bookings", json={"unit_code": u["code"], "customer_name": "آخر", "phone": "+96891234568", "plan": "6040"})
    assert r2.status_code == 409
    assert cl.get(f"/api/units/{u['code']}").json()["status"] == "r"
    assert cl.post(f"/api/bookings/{body['booking_id']}/confirm").status_code == 409  # لا تأكيد قبل KYC
    kyc(cl, body["customer_id"])
    assert cl.post(f"/api/bookings/{body['booking_id']}/confirm").status_code == 200
    d = cl.get(f"/api/units/{u['code']}").json()
    assert d["status"] == "s" and d["booking"]["paid"] == body["deposit"]
    assert any("تأكيد بيع" in a["action"] for a in cl.get("/api/audit").json())


def test_cancel_frees_unit(cl):
    pid = cl.get("/api/projects").json()[2]["id"]
    u = next(x for x in cl.get(f"/api/units?project_id={pid}").json() if x["status"] == "a")
    b = cl.post("/api/bookings", json={"unit_code": u["code"], "customer_name": "سالم", "phone": "+96899999999", "plan": "murabaha"}).json()
    assert cl.post(f"/api/bookings/{b['booking_id']}/cancel").status_code == 200
    assert cl.get(f"/api/units/{u['code']}").json()["status"] == "a"


def test_booking_validation(cl):
    r = cl.post("/api/bookings", json={"unit_code": "X", "customer_name": "a", "phone": "1", "plan": "bad"})
    assert r.status_code == 422


def test_ipc_verification_and_approval(cl):
    ipc = next(i for i in cl.get("/api/ipcs").json() if i["status"] == "pending" and i["verification"]["items"])
    v = ipc["verification"]
    assert v["verified_pct"] < v["claimed_pct"] and v["gap_amount"] > 0
    r = cl.post(f"/api/ipcs/{ipc['id']}/approve").json()
    assert r["amount"] == v["verified_amount"]
    assert cl.post(f"/api/ipcs/{ipc['id']}/approve").status_code == 409
    keys = [d for d in cl.get("/api/decisions").json() if d["key"] == f"ipc:{ipc['id']}"]
    assert not keys or keys[0]["done"]


def test_price_decision_applies(cl):
    d = next(x for x in cl.get("/api/decisions").json() if x["kind"] == "price")
    pid = d["project_id"]
    before = {u["code"]: u["price"] for u in cl.get(f"/api/units?project_id={pid}").json()
              if u["status"] == "a" and u["view"] == d["payload"]["view"] and u["type"] == d["payload"]["type"]}
    assert cl.post("/api/decisions/act", json={"key": d["key"], "action": "approve"}).status_code == 200
    after = {u["code"]: u["price"] for u in cl.get(f"/api/units?project_id={pid}").json() if u["code"] in before}
    assert all(after[c] > before[c] for c in before)
    assert cl.post("/api/decisions/act", json={"key": d["key"], "action": "approve"}).status_code == 409


def test_cash_plan_reduces_gap(cl):
    base, plan = cl.get("/api/cash").json(), cl.get("/api/cash?plan=true").json()
    assert base["gap"] > 0 and plan["gap"] < base["gap"] and plan["actions"]


def test_risk_and_reschedule(cl):
    risk = cl.get("/api/risk").json()
    assert risk and all(0 <= r["score"] <= 100 for r in risk)
    d = next((x for x in cl.get("/api/decisions").json() if x["kind"] == "reschedule"), None)
    if d:
        cl.post("/api/decisions/act", json={"key": d["key"], "action": "approve"})
        after = {r["booking_id"]: r["score"] for r in cl.get("/api/risk").json()}
        assert all(after.get(b, 0) < 70 for b in d["payload"]["booking_ids"])


def test_lead_stage_and_matches(cl):
    lead = cl.get("/api/leads").json()[-1]
    r = cl.post(f"/api/leads/{lead['id']}/stage", json={"stage": 3}).json()
    assert r["stage"] == 3 and r["score"] > lead["score"]
    m = cl.get(f"/api/leads/{lead['id']}/matches").json()
    assert all(u["status"] == "a" for u in m)


def test_assistant_and_search(cl):
    for q in ["ما المشروع الأخطر؟", "فجوة السيولة", "تسويق", "تعثر", "مستخلص", "ملخص"]:
        assert len(cl.post("/api/assistant", json={"q": q}).json()["answer"]) > 20
    assert cl.get("/api/search?q=RAY-A-1").json()


def test_frontend_served(cl):
    assert "مبانيك" in cl.get("/").text
    assert cl.get("/static/app.js").status_code == 200


# ---------------------------------------------------------------- الهوية والصلاحيات
def test_requires_login():
    with TestClient(app) as c:
        assert c.get("/api/projects").status_code == 401
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert c.get("/login").status_code == 200


def test_password_login_and_lockout():
    creds = json.loads(A.creds_file().read_text())
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "finance", "password": creds["finance"]})
        assert r.status_code == 200 and r.json()["role"] == "finance"
        assert "httponly" in r.headers["set-cookie"].lower()
        assert c.get("/api/me").json()["username"] == "finance"
        c.post("/api/auth/logout")
        assert c.get("/api/me").status_code == 401
        codes = [c.post("/api/auth/login", json={"username": "sales", "password": "wrong-pass"}).status_code for _ in range(6)]
        assert codes[:A.COOLDOWN_AFTER] == [401] * A.COOLDOWN_AFTER and 429 in codes[A.COOLDOWN_AFTER:]  # Unit 2: graded cooldown, not a lock


def test_role_permissions(cl):
    pid = cl.get("/api/projects").json()[0]["id"]
    u = next(x for x in cl.get(f"/api/units?project_id={pid}").json() if x["status"] == "a")
    ipc = next(i for i in cl.get("/api/ipcs").json() if i["status"] == "pending")
    as_user(cl, "sales")
    assert cl.get("/api/risk").status_code == 403
    assert cl.post(f"/api/ipcs/{ipc['id']}/approve").status_code == 403
    b = cl.post("/api/bookings", json={"unit_code": u["code"], "customer_name": "عميل", "phone": "+96891111111", "plan": "6040"})
    assert b.status_code == 200
    assert cl.post(f"/api/bookings/{b.json()['booking_id']}/confirm").status_code == 403
    kyc(cl, b.json()["customer_id"])
    as_user(cl, "engineer")
    assert cl.get("/api/ipcs").status_code == 200 and cl.get("/api/leads").status_code == 403
    as_user(cl, "finance")
    assert cl.post(f"/api/bookings/{b.json()['booking_id']}/confirm").status_code == 200
    assert cl.post(f"/api/ipcs/{ipc['id']}/approve").status_code == 403
    as_user(cl, "admin")
    log = cl.get("/api/audit").json()
    assert any("موظف المبيعات" in a["actor"] and a["action"] == "حجز مبدئي" for a in log)
    assert any("المحاسب" in a["actor"] and a["action"] == "تأكيد بيع" for a in log)


def test_customer_portal_flow(cl):
    as_user(cl, "client1")
    assert cl.get("/api/projects").status_code == 403
    p = cl.get("/api/portal").json()
    assert p["bookings"]
    b = p["bookings"][0]
    nxt = b["next"]
    assert nxt
    later = [i for i in b["installments"] if i["paid_amount"] < i["amount"] - 1 and i["id"] != nxt["id"]]
    if later:
        assert cl.post("/api/portal/pay", json={"installment_id": later[0]["id"]}).status_code == 409
    r = cl.post("/api/portal/pay", json={"installment_id": nxt["id"]}).json()
    assert r["receipt"].startswith("MBQ-")
    b2 = cl.get("/api/portal").json()["bookings"][0]
    assert b2["paid"] > b["paid"]
    s = cl.post("/api/portal/service", json={"booking_id": b["booking_id"], "category": "سباكة", "description": "تسريب تحت المغسلة"})
    assert s.status_code == 200
    # لا يصل العميل إلى وحدة غيره
    as_user(cl, "client2")
    assert cl.post("/api/portal/service", json={"booking_id": b["booking_id"], "category": "سباكة", "description": "محاولة وصول"}).status_code == 404
    assert cl.post("/api/portal/pay", json={"installment_id": nxt["id"]}).status_code in (404, 409)
    as_user(cl, "sales")
    req = next(x for x in cl.get("/api/service").json()["requests"] if x["category"] == "سباكة")
    assert cl.post(f"/api/service/{req['id']}/status", json={"status": "done", "note": "تم الإصلاح"}).status_code == 200
    as_user(cl, "client1")
    assert any(x["status"] == "done" and x["note"] == "تم الإصلاح" for x in cl.get("/api/portal").json()["bookings"][0]["service"])


def test_resale_flow(cl):
    for un in ["client1", "client2", "client3"]:
        as_user(cl, un)
        for b in cl.get("/api/portal").json()["bookings"]:
            if b["status"] == "confirmed" and b["paid"] / b["total"] >= .3:
                est = b["market_estimate"]
                assert est["low"] <= est["mid"] <= est["high"]
                r = cl.post("/api/portal/resale", json={"booking_id": b["booking_id"], "ask_price": est["mid"]})
                assert r.status_code == 200 and r.json()["fee"] == round(est["mid"] * .02)
                assert cl.post("/api/portal/resale", json={"booking_id": b["booking_id"], "ask_price": 1}).status_code == 409
                as_user(cl, "sales")
                rid = r.json()["id"]
                assert cl.post(f"/api/resale/{rid}", json={"action": "listed"}).status_code == 403
                as_user(cl, "admin")
                assert cl.post(f"/api/resale/{rid}", json={"action": "listed"}).status_code == 200
                return
    pytest.fail("لا يوجد عميل مؤهل لإعادة البيع في البيانات التجريبية")


def test_customer_pages_redirect(cl):
    as_user(cl, "client1")
    assert cl.get("/", follow_redirects=False).headers["location"] == "/app"
    assert "وحدتي" in cl.get("/app").text
    as_user(cl, "sales")
    assert cl.get("/app", follow_redirects=False).status_code == 303
