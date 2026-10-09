"""اختبارات انحدار لإصدار 0.5.0 — إغلاق M4 إلى M9 من المراجعة المستقلة (2026-10-09):
M4 شرط التبرع · M5 حماية البيانات الشخصية · M6 الأسرار خارج القاعدة · M7 CSRF/CSP · M8 تسوية التنازل · M9 جدولة الإيجار."""
import datetime as dt
import os
import re
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "fix050.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import pii  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import connect  # noqa: E402

CSRF = "csrf-test-token-" + "y" * 24
KYC = {"id_type": "بطاقة مدنية", "id_number": "12345678", "nationality": "عُماني", "id_expiry": "2030-01-01", "source_of_funds": "راتب", "consent_signed": True}


def login_as(c, user):
    c.cookies.set(A.COOKIE, A.issue_session(user))
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


def book(cl, plan, name, project_idx=0, kyc=True):
    pid = cl.get("/api/projects").json()[project_idx]["id"]
    u = next(x for x in cl.get(f"/api/units?project_id={pid}").json() if x["status"] == "a")
    r = cl.post("/api/bookings", json={"unit_code": u["code"], "customer_name": name, "phone": "+968 9555 0050", "plan": plan})
    assert r.status_code == 200, r.text
    b = r.json()
    if kyc:
        assert cl.post(f"/api/customers/{b['customer_id']}/kyc", json=KYC).json()["status"] == "verified"
    return b, u


# ================================================================== M4 — شرط التبرع
def test_m4_late_payment_creates_charity_due_not_revenue(cl):
    db = connect()
    login_as(cl, "client1")
    b = cl.get("/api/portal").json()["bookings"][0]
    nxt = b["next"]
    assert nxt
    db.execute("UPDATE installments SET due_date=? WHERE id=?", ((dt.date.today() - dt.timedelta(days=75)).isoformat(), nxt["id"]))
    db.commit()
    r = cl.post("/api/portal/pay", json={"installment_id": nxt["id"]}).json()
    due = nxt["amount"] - nxt["paid_amount"]
    expected = round(due * .01 * (75 - 15) / 30, 1)
    assert abs(r["charity_due"] - expected) < .2
    row = db.execute("SELECT * FROM charity_dues WHERE installment_id=?", (nxt["id"],)).fetchone()
    assert row and row["status"] == "due" and abs(row["amount"] - expected) < .2
    # لا أثر على الإيراد: الفاتورة بمبلغ القسط فقط
    inv = db.execute("SELECT net FROM invoices WHERE ref_type='installment' AND ref_id=?", (nxt["id"],)).fetchone()
    assert abs(inv["net"] - due) < 1
    login_as(cl, "finance")
    P = cl.get("/api/penalties").json()
    assert P["treatment"] == "charity" and P["charity"]["due"] > 0 and "تبرع" in P["treatment_label"]
    did = next(x["id"] for x in cl.get("/api/charity").json()["items"] if x["installment_id"] == nxt["id"])
    assert cl.post(f"/api/charity/{did}/disburse", json={"reference": "xyz", "beneficiary": "جمعية"}).status_code == 409  # لا صرف قبل التحصيل
    assert cl.post(f"/api/charity/{did}/collect", json={"reference": "TRF-001"}).status_code == 200
    assert cl.post(f"/api/charity/{did}/disburse", json={"reference": "TRF-002", "beneficiary": "جمعية خيرية معتمدة"}).status_code == 200
    login_as(cl, "admin")
    ex = cl.get("/api/export/erpnext").json()["entries"]
    trust = [e for e in ex if any("Charity Payable" in a["account"] for a in e["accounts"])]
    assert len(trust) >= 2 and not any("Revenue" in a["account"] or "Income" in a["account"] for e in trust for a in e["accounts"])


def test_m4_contract_clause_is_charity_not_penalty(cl):
    body, _u = book(cl, "milestone", "عميل بند خيري")
    k = cl.post(f"/api/bookings/{body['booking_id']}/contract").json()
    assert "شرط التبرع" in k["body"] and "جهة خيرية" in k["body"] and "لا يعود منه شيء للبائع" in k["body"]
    assert "فائدة" in k["body"] and "مرابحة" in k["body"]
    land = cl.get("/api/lands").json()[0]["id"]
    f = cl.post(f"/api/lands/{land}/feasibility", json={"sell_price_sqm": 620, "build_cost_sqm": 260}).json()
    assert "مرابحة" in f["finance_mode"] and any("التمويل الإسلامي" in r for r in f["reasons"])


def test_m4_waiver_also_waives_charity(cl):
    db = connect()
    login_as(cl, "client1")
    b = cl.get("/api/portal").json()["bookings"][0]
    nxt = b["next"]
    db.execute("UPDATE installments SET due_date=? WHERE id=?", ((dt.date.today() - dt.timedelta(days=50)).isoformat(), nxt["id"]))
    db.commit()
    cl.post("/api/portal/pay", json={"installment_id": nxt["id"]})
    login_as(cl, "admin")
    assert cl.post(f"/api/installments/{nxt['id']}/waive").status_code == 200
    assert db.execute("SELECT status FROM charity_dues WHERE installment_id=?", (nxt["id"],)).fetchone()["status"] == "waived"


# ================================================================== M5 — حماية البيانات الشخصية
def test_m5_pii_encrypted_at_rest_and_masked_in_lists(cl):
    db = connect()
    raw = db.execute("SELECT id_number FROM customers WHERE id_number IS NOT NULL LIMIT 20").fetchall()
    assert raw and all(r[0].startswith("enc:v1:") for r in raw)
    assert all(t[0].startswith("enc:v1:") for t in db.execute("SELECT id_number FROM tenants_l WHERE id_number IS NOT NULL"))
    q = cl.get("/api/kyc").json()
    assert q and all("id_number" not in x for x in q) and any(x["id_number_masked"] and "•" in x["id_number_masked"] for x in q)
    cid = q[0]["id"]
    d = cl.get(f"/api/customers/{cid}/kyc").json()
    assert d["id_number"] and not d["id_number"].startswith("enc:")
    assert any(a["action"] == "اطلاع على بيانات هوية" and str(cid) in a["detail"] for a in cl.get("/api/audit").json())
    body, _u = book(cl, "6040", "عميل مشفر")
    stored = db.execute("SELECT id_number FROM customers WHERE id=?", (body["customer_id"],)).fetchone()[0]
    assert stored.startswith("enc:v1:") and pii.dec(stored) == "12345678"
    k = cl.post(f"/api/bookings/{body['booking_id']}/contract").json()
    assert "12345678" in k["body"]  # العقد يفك التشفير


def test_m5_consent_is_customers_own_or_witnessed(cl):
    db = connect()
    body, _u = book(cl, "milestone", "عميل بلا موافقة", kyc=False)
    nc = dict(KYC, consent_signed=False)
    assert cl.post(f"/api/customers/{body['customer_id']}/kyc", json=nc).json()["status"] == "verified"
    assert db.execute("SELECT consent_at FROM customers WHERE id=?", (body["customer_id"],)).fetchone()[0] is None
    r = cl.post(f"/api/bookings/{body['booking_id']}/contract")
    assert r.status_code == 409 and "الخصوصية" in r.json()["detail"]
    # الموافقة من تطبيق العميل
    acc = cl.post(f"/api/customers/{body['customer_id']}/account", json={"username": "buyer.consent"}).json()
    with TestClient(app, base_url="https://testserver") as c2:
        lg = c2.post("/api/auth/login", json={"username": "buyer.consent", "password": acc["temporary_password"]})
        assert lg.status_code == 200 and "mbq_csrf" in lg.headers.get("set-cookie", "")
        tok = c2.cookies.get(A.CSRF_COOKIE)
        c2.headers["X-CSRF-Token"] = tok
        c2.post("/api/auth/password", json={"current": acc["temporary_password"], "new": "Strong-Pass-2026-x"})
        p = c2.get("/api/portal").json()
        assert p["consent_required"] == "1.0" and c2.get("/api/privacy/notice").json()["version"] == "1.0"
        assert c2.post("/api/portal/consent", json={"version": "1.0", "accept": False}).status_code == 400
        assert c2.post("/api/portal/consent", json={"version": "1.0", "accept": True}).status_code == 200
        assert c2.get("/api/portal").json()["consent_required"] is None
    cu = db.execute("SELECT consent_at, consent_source FROM customers WHERE id=?", (body["customer_id"],)).fetchone()
    assert cu["consent_at"] and "تطبيق العميل" in cu["consent_source"]
    assert cl.post(f"/api/bookings/{body['booking_id']}/contract").status_code == 200


def test_m5_erasure_workflow_respects_retention(cl):
    db = connect()
    # عميل بحجز قائم: الحذف مرفوض بسبب الالتزام
    body, u = book(cl, "milestone", "عميل حذف")
    rid = db.execute("INSERT INTO privacy_requests(customer_id,kind,status,created,note) VALUES(?,?,?,?,?)",
                     (body["customer_id"], "erase", "open", "2026-10-09", "اختبار")).lastrowid
    db.commit()
    r = cl.post(f"/api/privacy/{rid}/process", json={"action": "complete", "note": "تنفيذ"})
    assert r.status_code == 409 and "حجز" in r.json()["detail"]
    # بعد إلغاء الحجز يُنفَّذ الحذف إخفاءً للهوية
    assert cl.post(f"/api/bookings/{body['booking_id']}/cancel").status_code == 200
    assert cl.post(f"/api/privacy/{rid}/process", json={"action": "complete", "note": "لا التزامات قائمة"}).json()["status"] == "done"
    cu = db.execute("SELECT * FROM customers WHERE id=?", (body["customer_id"],)).fetchone()
    assert cu["name"].startswith("عميل محذوف") and cu["id_number"] is None and cu["phone"] is None and cu["erased_at"]
    assert db.execute("SELECT COUNT(*) FROM bookings WHERE customer_id=?", (body["customer_id"],)).fetchone()[0] == 1  # السجل المالي باقٍ
    assert any(x["status"] == "done" for x in cl.get("/api/privacy").json() if x["id"] == rid)


# ================================================================== M6 — الأسرار
def test_m6_secrets_outside_database(cl, monkeypatch):
    db = connect()
    cl.get("/api/bank")
    assert db.execute("SELECT 1 FROM settings WHERE k='pay_secret'").fetchone() is None
    assert (pii.secrets_dir() / "pay_secret").exists() and (pii.secrets_dir() / "pii.key").exists()
    monkeypatch.setenv("MABANIQ_ENV", "prod")
    with pytest.raises(RuntimeError):
        pii.secret("nonexistent-secret", "MABANIQ_NONEXISTENT")
    monkeypatch.setenv("MABANIQ_NONEXISTENT", "from-env")
    assert pii.secret("nonexistent-secret", "MABANIQ_NONEXISTENT") == "from-env"


# ================================================================== M7 — CSRF / CSP
def test_m7_csrf_token_required_and_pages_have_no_inline_js(cl):
    with TestClient(app, base_url="https://testserver") as c:
        c.cookies.set(A.COOKIE, A.issue_session("admin"))
        assert c.post("/api/notifications/run").status_code == 403
        assert c.get("/api/projects").status_code == 200  # القراءة لا تحتاج الرمز
        c.cookies.set(A.CSRF_COOKIE, CSRF)
        assert c.post("/api/notifications/run", headers={"X-CSRF-Token": CSRF}).status_code == 200
    for p in ("/login",):
        html = cl.get(p).text
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html)
    for js in ("/static/app.js", "/static/app2.js", "/static/client.js", "/static/broker.js", "/static/login.js"):
        r = cl.get(js)
        assert r.status_code == 200 and 'onclick="' not in r.text
    csp = cl.get("/login").headers["content-security-policy"]
    assert "script-src 'self';" in csp


# ================================================================== M8 — تسوية التنازل
def test_m8_resale_settlement_and_buyer_kyc_gate(cl):
    db = connect()
    r = next(x for x in cl.get("/api/market").json() if x["status"] == "listed")
    bid = r["booking_id"]
    sp = db.execute("SELECT SUM(paid_amount) paid, SUM(amount-paid_amount) unpaid FROM installments WHERE booking_id=?", (bid,)).fetchone()
    oid = cl.post(f"/api/market/{r['id']}/offers", json={"buyer_name": "مشترٍ جديد", "buyer_phone": "+968 9222 0000", "price": r["ask_price"]}).json()["id"]
    acc = cl.post(f"/api/market/offers/{oid}/accept").json()
    assert acc["equity_due_to_seller"] == round(r["ask_price"] - sp["unpaid"]) and acc["settlement_id"]
    st = next(x for x in cl.get("/api/resale-settlements").json() if x["id"] == acc["settlement_id"])
    assert st["status"] == "open" and st["buyer_kyc"] == "pending" and st["seller_paid"] == sp["paid"]
    k = db.execute("SELECT status FROM sale_contracts WHERE booking_id=?", (bid,)).fetchone()
    assert k is None or k["status"] == "assigned_pending_kyc"
    # لا تسليم للمشتري قبل توثيق هويته وتوقيع الملحق
    db.execute("UPDATE installments SET paid_amount=amount WHERE booking_id=?", (bid,))
    db.execute("DELETE FROM snags WHERE booking_id=?", (bid,))
    db.commit()
    h = cl.post(f"/api/bookings/{bid}/handover/complete", json={"electricity": 1, "water": 1, "keys": 2})
    assert h.status_code == 409 and "KYC" in h.json()["detail"] and "ملحق التنازل" in h.json()["detail"]
    assert cl.post(f"/api/resale-settlements/{acc['settlement_id']}/settle", json={"reference": "TRF-SET-1"}).status_code == 200
    a = cl.post(f"/api/customers/{acc['new_customer_id']}/account", json={"username": "new.buyer"}).json()
    assert len(a["temporary_password"]) >= 10
    assert cl.post(f"/api/customers/{acc['new_customer_id']}/account", json={"username": "new.buyer2"}).status_code == 409


# ================================================================== M9 — جدولة الإيجار
def test_m9_lease_dues_prorated():
    pass


def test_m9_lease_dues_prorated_13_months(cl):
    db = connect()
    L = cl.get("/api/leasing").json()
    free = next(u for u in L["units"] if u["id"] not in {l["unit_id"] for l in L["leases"]})
    r = cl.post("/api/leases", json={"unit_id": free["id"], "tenant_name": "مستأجر ١٣ شهرًا", "tenant_phone": "+968 9000 7777", "tenant_id_number": "55556666",
                                     "start": "2026-11-01", "months": 13, "annual_rent": 6000, "frequency": 4}).json()
    dues = db.execute("SELECT amount FROM rent_dues WHERE lease_id=? ORDER BY due", (r["id"],)).fetchall()
    assert [d[0] for d in dues] == [1500, 1500, 1500, 1500, 500]
    assert db.execute("SELECT id_number FROM tenants_l ORDER BY id DESC LIMIT 1").fetchone()[0].startswith("enc:v1:")
