"""اختبارات الوحدات الموسّعة: الأمان (التعدد، 2FA، سياسة كلمات المرور، سجل التدقيق، توقيع البوابة، الرفع)،
ومنطق الأعمال (الجدوى، العقد والتوقيع، الخصومات، الوسطاء، التسليم، اتحاد الملاك، التأجير، التقارير)."""
import hashlib
import hmac
import json
import os
import tempfile
import time

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "mod.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect  # noqa: E402

KYC = {"id_type": "بطاقة مدنية", "id_number": "12345678", "nationality": "عُماني", "id_expiry": "2030-01-01", "source_of_funds": "راتب", "consent_signed": True}


CSRF = 'csrf-test-token-' + 'x' * 24


def login_as(c, user, tenant="jadwa"):
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
    with TestClient(app, base_url="https://testserver") as c:
        login_as(c, "admin")
        c.post("/api/reset")
        login_as(c, "admin")
        yield c


def new_booking(cl, project_idx=0, plan="milestone", name="عميل اختبار الوحدات"):
    pid = cl.get("/api/projects").json()[project_idx]["id"]
    u = next(x for x in cl.get(f"/api/units?project_id={pid}").json() if x["status"] == "a")
    r = cl.post("/api/bookings", json={"unit_code": u["code"], "customer_name": name, "phone": "+968 9555 1234", "plan": plan})
    assert r.status_code == 200, r.text
    return r.json(), u


# ================================================================== أمان
def test_tenant_isolation(cl):
    a = cl.get("/api/projects").json()
    login_as(cl, "admin", "nahda")
    b = cl.get("/api/projects").json()
    assert {p["name"] for p in a}.isdisjoint({p["name"] for p in b})
    # جلسة مطوّر لا تعمل عند تبديل كوكي المطوّر
    tok = TENANT.set("jadwa")
    s = A.issue_session("admin")
    TENANT.reset(tok)
    cl.cookies.set(A.COOKIE, s)
    cl.cookies.set(A.TENANT_COOKIE, "nahda")
    assert cl.get("/api/projects").status_code == 401
    cl.cookies.set(A.TENANT_COOKIE, "../etc")
    assert cl.get("/api/projects").status_code == 401


def test_password_policy_and_forced_change(cl):
    c = A.conn()
    c.execute("UPDATE users SET must_change=1 WHERE username='sales'")
    c.commit()
    login_as(cl, "sales")
    assert cl.get("/api/leads").json()["detail"] == "MUST_CHANGE_PASSWORD"
    assert cl.get("/api/me").status_code == 200
    creds = json.loads(A.creds_file().read_text())
    for bad in ("short1", "onlyletterslong", "sales12345678"):
        r = cl.post("/api/auth/password", json={"current": creds["sales"], "new": bad})
        assert r.status_code in (400, 422)
    assert cl.post("/api/auth/password", json={"current": creds["sales"], "new": "Strong-Pass-2026"}).status_code == 200
    assert cl.get("/api/leads").status_code == 200
    c.execute("UPDATE users SET pw=? WHERE username='sales'", (A.hash_pw(creds["sales"]),))
    c.commit()


def test_totp_2fa(cl):
    login_as(cl, "finance")
    sec = cl.post("/api/auth/2fa/setup").json()["secret"]
    assert cl.post("/api/auth/2fa/enable", json={"otp": "000000"}).status_code == 400
    code = A.totp_at(sec, int(time.time() // 30))
    assert cl.post("/api/auth/2fa/enable", json={"otp": code}).status_code == 200
    creds = json.loads(A.creds_file().read_text())
    with TestClient(app, base_url="https://testserver") as c2:
        r = c2.post("/api/auth/login", json={"username": "finance", "password": creds["finance"]})
        assert r.status_code == 401 and r.json()["detail"] == "OTP_REQUIRED"
        # الرمز المستخدم مسبقًا مرفوض (منع إعادة الاستخدام)
        assert c2.post("/api/auth/login", json={"username": "finance", "password": creds["finance"], "otp": code}).status_code == 401
    c = A.conn()
    c.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL, totp_last=0 WHERE username='finance'")
    c.execute("DELETE FROM auth_failures")
    c.commit()


def test_audit_append_only_and_chain(cl):
    cl.post("/api/notifications/run")
    v = cl.get("/api/audit/verify").json()
    assert v["ok"] and v["entries"] >= 1
    raw = connect()
    with pytest.raises(Exception, match="append-only|denied|permission"):
        raw.execute("UPDATE audit SET detail='x'")
    raw.rollback()
    with pytest.raises(Exception, match="append-only|denied|permission"):
        raw.execute("DELETE FROM audit")
    raw.rollback()
    raw.close()


def test_payment_webhook_signature(cl):
    login_as(cl, "client1")
    b = cl.get("/api/portal").json()["bookings"][0]
    intent = cl.post("/api/portal/pay/intent", json={"installment_id": b["next"]["id"]}).json()
    ev = {"type": "payment.succeeded", "intent": intent["intent"], "ref": "gw_test_1", "amount": intent["amount"], "ts": int(time.time())}
    raw = json.dumps(ev).encode()
    with TestClient(app, base_url="https://testserver") as anon:
        assert anon.post("/api/pay/webhook", content=raw, headers={"content-type": "application/json", "x-mabaniq-signature": "bad"}).status_code == 401
        from backend import pii
        key = pii.secret("pay_secret", "MABANIQ_PAY_SECRET").encode()  # 0.5.0 — M6: السر خارج القاعدة
        sig = hmac.new(key, raw, hashlib.sha256).hexdigest()
        r1 = anon.post("/api/pay/webhook", content=raw, headers={"content-type": "application/json", "x-mabaniq-signature": sig})
        assert r1.status_code == 200 and r1.json()["receipt"]
        r2 = anon.post("/api/pay/webhook", content=raw, headers={"content-type": "application/json", "x-mabaniq-signature": sig})
        assert r2.json().get("duplicate")  # idempotent
        old = dict(ev, ts=int(time.time()) - 3600, ref="gw_old")
        raw2 = json.dumps(old).encode()
        sig2 = hmac.new(key, raw2, hashlib.sha256).hexdigest()
        assert anon.post("/api/pay/webhook", content=raw2, headers={"content-type": "application/json", "x-mabaniq-signature": sig2}).status_code == 401


def test_document_upload_validation(cl):
    ok = cl.post("/api/documents", data={"ref_type": "project", "ref_id": "1", "title": "رخصة البناء"},
                 files={"file": ("permit.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert ok.status_code == 200
    bad = cl.post("/api/documents", data={"ref_type": "project", "ref_id": "1", "title": "ملف خبيث"},
                  files={"file": ("x.pdf", b"<script>alert(1)</script>", "application/pdf")})
    assert bad.status_code == 415
    path = cl.post("/api/documents", data={"ref_type": "../../etc", "ref_id": "1", "title": "x"},
                   files={"file": ("a.pdf", b"%PDF", "application/pdf")})
    assert path.status_code == 422
    d = cl.get(f"/api/documents/{ok.json()['id']}")
    assert d.status_code == 200 and d.headers["content-security-policy"] == "sandbox"
    login_as(cl, "client1")
    assert cl.get(f"/api/portal/documents/{ok.json()['id']}").status_code == 404


def test_broker_isolation(cl):
    login_as(cl, "broker1")
    p = cl.get("/api/broker/portal").json()
    assert p["broker"]["name"] and "inventory" in p
    assert cl.get("/api/leads").status_code == 403 and cl.get("/api/projects").status_code == 403
    pid = cl.get("/api/broker/projects").json()[0]["id"]
    r = cl.post("/api/broker/leads", json={"name": "عميل وسيط", "phone": "+968 9777 0001", "project_id": pid})
    assert r.status_code == 200
    dup = cl.post("/api/broker/leads", json={"name": "مكرر", "phone": "9777 0001", "project_id": pid})
    assert dup.status_code == 409
    login_as(cl, "broker2")
    assert all(l["id"] != r.json()["id"] for l in cl.get("/api/broker/portal").json()["leads"])


def test_api_key_readonly(cl):
    key = cl.post("/api/admin/api-keys").json()["key"]
    with TestClient(app, base_url="https://testserver") as anon:
        assert anon.get("/api/v1/inventory").status_code == 401
        assert anon.get("/api/v1/inventory", headers={"x-api-key": "mbq_wrong"}).status_code == 401
        r = anon.get("/api/v1/inventory", headers={"x-api-key": key})
        assert r.status_code == 200 and r.json()
        assert anon.get("/api/projects", headers={"x-api-key": key}).status_code == 401


# ================================================================== منطق الأعمال
def test_feasibility(cl):
    land = cl.get("/api/lands").json()[0]["id"]
    r = cl.post(f"/api/lands/{land}/feasibility", json={"sell_price_sqm": 620, "build_cost_sqm": 260})
    assert r.status_code == 200
    f = r.json()
    assert f["revenue"] > f["total_cost"] > 0 and f["irr"] is not None and len(f["sensitivity"]) == 3
    bad = cl.post(f"/api/lands/{land}/feasibility", json={"sell_price_sqm": 300, "build_cost_sqm": 290}).json()
    assert "غير" in bad["verdict"] or bad["margin"] < 12
    login_as(cl, "sales")
    assert cl.post(f"/api/lands/{land}/feasibility", json={"sell_price_sqm": 620, "build_cost_sqm": 260}).status_code == 403


def test_kyc_watchlist(cl):
    body, _u = new_booking(cl, name="Example Sanctioned Person")
    r = cl.post(f"/api/customers/{body['customer_id']}/kyc", json=KYC).json()
    assert r["status"] == "review" and r["risk"] == "مرتفع"
    assert cl.post(f"/api/bookings/{body['booking_id']}/confirm").status_code == 409
    expired = dict(KYC, id_expiry="2020-01-01")
    body2, _ = new_booking(cl, 1, name="عميل هوية منتهية")
    assert cl.post(f"/api/customers/{body2['customer_id']}/kyc", json=expired).json()["status"] == "rejected"


def test_contract_and_esign(cl):
    body, u = new_booking(cl)
    bid = body["booking_id"]
    assert cl.post(f"/api/bookings/{bid}/contract").status_code == 409  # قبل KYC
    cl.post(f"/api/customers/{body['customer_id']}/kyc", json=KYC)
    k = cl.post(f"/api/bookings/{bid}/contract").json()
    assert u["code"] in k["body"] and len(k["sha256"]) == 64
    assert cl.post(f"/api/bookings/{bid}/contract/sign-inperson", json={"typed_name": "اسم خاطئ", "accept": True}).status_code == 400
    assert cl.post(f"/api/bookings/{bid}/contract/sign-inperson", json={"typed_name": "عميل اختبار الوحدات", "accept": False}).status_code == 400
    s = cl.post(f"/api/bookings/{bid}/contract/sign-inperson", json={"typed_name": "عميل اختبار الوحدات", "accept": True})
    assert s.status_code == 200
    assert cl.get(f"/api/bookings/{bid}/contract").json()["integrity_ok"]
    assert cl.post(f"/api/bookings/{bid}/contract").status_code == 409  # لا إعادة إصدار بعد التوقيع
    assert cl.post(f"/api/bookings/{bid}/discount", json={"pct": .01, "reason": "بعد التوقيع"}).status_code == 409


def test_discount_authority(cl):
    body, u = new_booking(cl)
    login_as(cl, "sales")
    r = cl.post(f"/api/bookings/{body['booking_id']}/discount", json={"pct": .015, "reason": "عميل نقدي"}).json()
    assert r["status"] == "approved"
    r2 = cl.post(f"/api/bookings/{body['booking_id']}/discount", json={"pct": .08, "reason": "طلب كبير"}).json()
    assert r2["status"] == "pending"
    login_as(cl, "admin")
    did = next(d["id"] for d in cl.get("/api/discounts").json() if d["status"] == "pending")
    assert cl.post(f"/api/discounts/{did}/decide", json={"action": "approve"}).json()["amount"] > 0
    after = cl.get(f"/api/units/{u['code']}").json()["booking"]
    total = sum(i["amount"] for i in after["installments"]) if "installments" in after else None
    assert total is None or total < u["price"]


def test_commission_on_confirm(cl):
    pid = cl.get("/api/projects").json()[0]["id"]
    u = next(x for x in cl.get(f"/api/units?project_id={pid}").json() if x["status"] == "a")
    broker_id = cl.get("/api/brokers").json()[0]["id"]
    b = cl.post("/api/bookings", json={"unit_code": u["code"], "customer_name": "عميل عبر وسيط", "phone": "+968 9123 0000",
                                       "plan": "6040", "broker_id": broker_id}).json()
    cl.post(f"/api/customers/{b['customer_id']}/kyc", json=KYC)
    assert cl.post(f"/api/bookings/{b['booking_id']}/confirm").status_code == 200
    br = next(x for x in cl.get("/api/brokers").json() if x["id"] == broker_id)
    cm = next(x for x in br["commissions"] if x["booking_id"] == b["booking_id"])
    assert cm["status"] == "due" and cm["amount"] == round(u["price"] * br["rate"])


def test_handover_blockers_and_complete(cl):
    h = cl.get("/api/handover").json()
    item = next(x for x in h if any(s["status"] == "open" for s in x["snags"]))
    r = cl.post(f"/api/bookings/{item['booking_id']}/handover/complete", json={"electricity": 10, "water": 5, "keys": 3})
    assert r.status_code == 409 and "ملاحظات" in r.json()["detail"]
    # جهّز وحدة مستوفية: سداد كامل + إغلاق الملاحظات + عقد موقَّع
    c = connect()
    c.execute("UPDATE installments SET paid_amount=amount WHERE booking_id=?", (item["booking_id"],))
    c.commit()
    for s in item["snags"]:
        if s["status"] == "open":
            cl.post(f"/api/snags/{s['id']}/fix")
    c.execute("INSERT OR IGNORE INTO sale_contracts(booking_id,number,body,sha256,status,customer_signed_at,customer_sig) VALUES(?,?,?,?,?,?,?)",
              (item["booking_id"], "T", "t", "x", "signed", "2026-01-01", "migrated"))
    c.commit()
    ok = cl.post(f"/api/bookings/{item['booking_id']}/handover/complete", json={"electricity": 10, "water": 5, "keys": 3})
    assert ok.status_code == 200, ok.text
    assert ok.json()["certificate"].startswith("HC-")
    t = next(x for x in cl.get("/api/titles").json() if x["booking_id"] == item["booking_id"])
    assert cl.post(f"/api/titles/{t['id']}", json={"status": "issued"}).status_code == 400
    assert cl.post(f"/api/titles/{t['id']}", json={"status": "submitted"}).status_code == 200


def test_owners_association(cl):
    pid = cl.get("/api/projects").json()[2]["id"]
    r = cl.post(f"/api/oa/{pid}/bill").json()
    assert r["owners"] > 0
    assert cl.post(f"/api/oa/{pid}/bill").status_code == 409
    oa = cl.get(f"/api/oa/{pid}").json()
    assert abs(oa["billed"] - oa["budget_total"]) < oa["owners"]  # التوزيع يساوي الميزانية (مع التقريب)
    for un in ("client1", "client2", "client3"):
        login_as(cl, un)
        ex = cl.get("/api/portal/extra").json()
        if ex["motions"]:
            m = ex["motions"][0]
            v = cl.post(f"/api/portal/oa/{m['id']}/vote", json={"booking_id": m["booking_id"], "vote": "yes"})
            assert v.status_code == 200 and v.json()["weight"] > 0
            assert cl.post(f"/api/portal/oa/{m['id']}/vote", json={"booking_id": m["booking_id"], "vote": "no"}).status_code == 409
            return
    pytest.fail("لا يوجد مالك في مشروع اتحاد الملاك")


def test_leasing(cl):
    L = cl.get("/api/leasing").json()
    free = next(u for u in L["units"] if u["id"] not in {l["unit_id"] for l in L["leases"]})
    r = cl.post("/api/leases", json={"unit_id": free["id"], "tenant_name": "مستأجر اختبار", "tenant_phone": "+968 9000 1111",
                                     "tenant_id_number": "87654321", "start": "2026-11-01", "months": 12, "annual_rent": 6000, "frequency": 4})
    assert r.status_code == 200
    dup = cl.post("/api/leases", json={"unit_id": free["id"], "tenant_name": "آخر", "tenant_phone": "+968 9000 2222",
                                       "tenant_id_number": "87654322", "start": "2026-12-01", "months": 12, "annual_rent": 6000, "frequency": 4})
    assert dup.status_code == 409
    L2 = cl.get("/api/leasing").json()
    assert L2["occupancy"] > L["occupancy"]
    login_as(cl, "sales")
    assert cl.get("/api/leasing").status_code == 403


def test_construction_and_change_orders(cl):
    pid = cl.get("/api/projects").json()[1]["id"]
    k = cl.get(f"/api/construction/{pid}").json()
    assert k["schedule"]["spi"] < 1 and k["schedule"]["forecast_delay_days"] > 0
    co = cl.post("/api/change-orders", json={"project_id": pid, "title": "تعديل اختبار", "reason": "اختبار", "cost": 10000, "days": 5}).json()
    login_as(cl, "engineer")
    assert cl.post(f"/api/change-orders/{co['id']}/decide", json={"action": "approve"}).status_code == 403
    login_as(cl, "admin")
    assert cl.post(f"/api/change-orders/{co['id']}/decide", json={"action": "approve"}).status_code == 200
    k2 = cl.get(f"/api/construction/{pid}").json()
    assert k2["committed"] == k["committed"] + 10000 and k2["extension_days"] == k["extension_days"] + 5


def test_termination_and_refund(cl):
    body, u = new_booking(cl, 2)
    cl.post(f"/api/customers/{body['customer_id']}/kyc", json=KYC)
    cl.post(f"/api/bookings/{body['booking_id']}/confirm")
    pv = cl.get(f"/api/bookings/{body['booking_id']}/termination").json()
    assert pv["refund"] == pv["paid"] - pv["deduction"]
    login_as(cl, "finance")
    assert cl.post(f"/api/bookings/{body['booking_id']}/terminate", json={"reason": "طلب العميل"}).status_code == 403
    login_as(cl, "admin")
    assert cl.post(f"/api/bookings/{body['booking_id']}/terminate", json={"reason": "طلب العميل"}).status_code == 200
    assert cl.get(f"/api/units/{u['code']}").json()["status"] == "a"


def test_lender_and_investor_reports(cl):
    login_as(cl, "investor1")
    r = cl.get("/api/reports/lender").json()
    assert len(r["projects"]) == 5 and all(p["rating"] in ("أخضر", "أصفر", "أحمر") for p in r["projects"])
    seb = next(p for p in r["projects"] if "السيب" in p["project"])
    assert seb["flags"]
    assert cl.get("/api/reports/investor").status_code == 200
    first_project = connect().execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()[0]
    assert cl.get("/api/leads").status_code == 403 and cl.get(f"/api/escrow/{first_project}").status_code == 200


def test_whatsapp_agent(cl):
    r = cl.post("/api/wa/simulate", json={"phone": "+968 9333 4444", "text": "ابغى شقة غرفتين بميزانية 80 الف"}).json()
    assert r["intent"]["intent"] == "availability" and r["intent"]["bedrooms"] == 2 and r["intent"]["budget"] == 80000
    assert cl.post("/api/wa/simulate", json={"phone": "+968 9333 4444", "text": "ابي اكلم موظف"}).json()["actions"] == ["handoff"]


def test_notifications_dedupe(cl):
    n1 = cl.post("/api/notifications/run").json()["created"]
    n2 = cl.post("/api/notifications/run").json()["created"]
    assert n1 > 0 and n2 == 0


def test_erpnext_export(cl):
    j = cl.get("/api/export/erpnext").json()
    e = j["entries"][0]
    assert e["doctype"] == "Journal Entry"
    assert sum(a.get("debit_in_account_currency", 0) for a in e["accounts"]) == sum(a.get("credit_in_account_currency", 0) for a in e["accounts"])
    assert cl.get("/api/export/erpnext?fmt=csv").headers["content-type"].startswith("text/csv")


def test_user_admin(cl):
    r = cl.post("/api/users", json={"username": "new.eng", "name": "مهندس جديد", "role": "engineer"}).json()
    assert len(r["temporary_password"]) >= 10
    assert cl.post("/api/users", json={"username": "x", "name": "y", "role": "superuser"}).status_code == 422
    login_as(cl, "sales")
    assert cl.get("/api/users").status_code == 403


def test_full_lifecycle_data(cl):
    """كل مرحلة من دورة التطوير العقاري ممثلة ببيانات: أرض → تراخيص → إطلاق → إنشاء → تسليم → ملكية → إدارة أملاك."""
    P = cl.get("/api/projects").json()
    assert {round(p["build_pct"]) for p in P} >= {3, 100}
    done = next(p for p in P if p["completed"])
    assert cl.get("/api/lands").json()[0]["studies"]
    assert any(p["status"] == "in_review" for p in cl.get("/api/permits").json())
    assert any(t["status"] == "issued" for t in cl.get("/api/titles").json())
    oa = cl.get(f"/api/oa/{done['id']}").json()
    assert oa["charges"] and any(m["quorum_met"] for m in oa["motions"])
    assert cl.get("/api/leasing").json()["leases"]
    assert cl.get("/api/market").json()
    assert cl.get("/api/invoices").json()["summary"]["n"] > 50
    assert cl.get("/api/bank").json()["unreconciled_payments"]
    assert any(k["kyc_status"] == "review" for k in cl.get("/api/kyc").json())
    rep = cl.get("/api/reports/lender").json()["projects"]
    assert len({r["rating"] for r in rep}) >= 2
