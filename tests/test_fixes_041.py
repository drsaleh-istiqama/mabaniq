"""اختبارات انحدار لإصلاحات 0.4.1 (المراجعة المستقلة 2026-10-09):
M1 الفواتير بمعرّف العميل لا باسمه · M2 لا تسليم مع قسط تمويل بنكي غير مسدَّد بلا خطاب صرف · M3 العربون في دفتر المدفوعات."""
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "fix041.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import connect  # noqa: E402

KYC = {"id_type": "بطاقة مدنية", "id_number": "12345678", "nationality": "عُماني", "id_expiry": "2030-01-01", "source_of_funds": "راتب", "consent_signed": True}


CSRF = 'csrf-test-token-' + 'x' * 24


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


def ledger(c):
    a = c.execute("SELECT COALESCE(SUM(paid_amount),0) FROM installments").fetchone()[0]
    b = c.execute("SELECT COALESCE(SUM(amount),0) FROM payments").fetchone()[0]
    return round(a - b, 3)


def book(cl, plan, name, project_idx=0):
    pid = cl.get("/api/projects").json()[project_idx]["id"]
    u = next(x for x in cl.get(f"/api/units?project_id={pid}").json() if x["status"] == "a")
    r = cl.post("/api/bookings", json={"unit_code": u["code"], "customer_name": name, "phone": "+968 9555 0041", "plan": plan})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- M3
def test_m3_ledger_balanced_after_seed_and_confirm(cl):
    db = connect()
    assert ledger(db) == 0, "البذور نفسها يجب أن تكون متوازنة بين الأقساط ودفتر المدفوعات"
    body = book(cl, "milestone", "عميل عربون")
    cl.post(f"/api/customers/{body['customer_id']}/kyc", json=KYC)
    r = cl.post(f"/api/bookings/{body['booking_id']}/confirm")
    assert r.status_code == 200 and r.json()["receipt"].startswith("MBQ-")
    assert ledger(db) == 0
    p = db.execute("SELECT * FROM payments WHERE gateway_ref=?", (f"deposit_{body['booking_id']}",)).fetchone()
    assert p and abs(p["amount"] - body["deposit"]) < 1
    inv = db.execute("SELECT * FROM invoices WHERE ref_type='installment' AND ref_id=?", (p["installment_id"],)).fetchone()
    assert inv and inv["customer_id"] == body["customer_id"]
    bank = cl.get("/api/bank").json()
    assert bank["ledger_ok"] and bank["ledger_gap"] == 0
    # العربون يظهر في تصدير ERPNext
    assert any(e["cheque_no"] == p["receipt"] for e in cl.get("/api/export/erpnext").json()["entries"])


# ---------------------------------------------------------------- M1
def test_m1_invoices_isolated_by_customer_id_not_name(cl):
    db = connect()
    c1 = db.execute("SELECT customer_id FROM users WHERE username='client1'").fetchone()[0]
    c2 = db.execute("SELECT customer_id FROM users WHERE username='client2'").fetchone()[0]
    n1 = db.execute("SELECT name FROM customers WHERE id=?", (c1,)).fetchone()[0]
    db.execute("UPDATE customers SET name=? WHERE id=?", (n1, c2))  # عميلان بالاسم نفسه
    db.commit()
    login_as(cl, "client1")
    b = cl.get("/api/portal").json()["bookings"][0]
    nxt = b["next"]
    if nxt:
        cl.post("/api/portal/pay", json={"installment_id": nxt["id"]})  # يُصدر فاتورة لعميل ١
    mine = {i["number"] for i in cl.get("/api/portal/extra").json()["invoices"]}
    db_mine = {r[0] for r in db.execute("SELECT number FROM invoices WHERE customer_id=?", (c1,))}
    assert mine and mine <= db_mine
    login_as(cl, "client2")
    other = {i["number"] for i in cl.get("/api/portal/extra").json()["invoices"]}
    assert not (mine & other), "عميل يحمل الاسم نفسه رأى فواتير غيره"
    db_other = {r[0] for r in db.execute("SELECT number FROM invoices WHERE customer_id=?", (c2,))}
    assert other <= db_other


def test_m1_no_invoice_without_customer_link_in_seed(cl):
    db = connect()
    n = db.execute("SELECT COUNT(*) FROM invoices WHERE customer_id IS NULL AND kind IN ('installment','service_charge','resale_fee')").fetchone()[0]
    assert n == 0


# ---------------------------------------------------------------- M2
def test_m2_handover_requires_bank_letter_for_unpaid_financing(cl):
    db = connect()
    body = book(cl, "murabaha", "عميل مرابحة", 2)
    bid = body["booking_id"]
    cl.post(f"/api/customers/{body['customer_id']}/kyc", json=KYC)
    assert cl.post(f"/api/bookings/{bid}/confirm").status_code == 200
    # سداد كل ما عدا قسط تمويل البنك عبر المسار الموحّد (المحاكاة)
    login_as(cl, "admin")
    db.execute("UPDATE installments SET paid_amount=amount, paid_date=date('now') WHERE booking_id=? AND label NOT LIKE '%تمويل البنك%'", (bid,))
    db.execute("INSERT OR IGNORE INTO sale_contracts(booking_id,number,body,sha256,status,customer_signed_at,customer_sig) VALUES(?,?,?,?,?,?,?)",
               (bid, "T", "t", "x", "signed", "2026-01-01", "migrated"))
    db.commit()
    r = cl.post(f"/api/bookings/{bid}/handover/complete", json={"electricity": 1, "water": 1, "keys": 2})
    assert r.status_code == 409 and "خطاب صرف" in r.json()["detail"]
    # مستند بفئة أخرى لا يكفي
    cl.post("/api/documents", data={"ref_type": "booking", "ref_id": str(bid), "title": "صورة الهوية", "category": "هوية"},
            files={"file": ("id.pdf", b"%PDF-1.4 id", "application/pdf")})
    assert cl.post(f"/api/bookings/{bid}/handover/complete", json={"electricity": 1, "water": 1, "keys": 2}).status_code == 409
    # خطاب الصرف البنكي يفتح التسليم
    up = cl.post("/api/documents", data={"ref_type": "booking", "ref_id": str(bid), "title": "خطاب صرف بنك نزوى", "category": "خطاب صرف بنكي"},
                 files={"file": ("letter.pdf", b"%PDF-1.4 bank", "application/pdf")})
    assert up.status_code == 200
    ok = cl.post(f"/api/bookings/{bid}/handover/complete", json={"electricity": 1, "water": 1, "keys": 2})
    assert ok.status_code == 200, ok.text
    assert any("خطاب صرف بنكي" in a["detail"] and a["action"] == "تسليم وحدة" for a in cl.get("/api/audit").json())


def test_m2_handover_still_blocked_for_own_unpaid_installments(cl):
    db = connect()
    body = book(cl, "6040", "عميل ٦٠/٤٠", 2)
    bid = body["booking_id"]
    cl.post(f"/api/customers/{body['customer_id']}/kyc", json=KYC)
    cl.post(f"/api/bookings/{bid}/confirm")
    db.execute("INSERT OR IGNORE INTO sale_contracts(booking_id,number,body,sha256,status,customer_signed_at,customer_sig) VALUES(?,?,?,?,?,?,?)",
               (bid, "T", "t", "x", "signed", "2026-01-01", "migrated"))
    db.commit()
    cl.post("/api/documents", data={"ref_type": "booking", "ref_id": str(bid), "title": "خطاب", "category": "خطاب صرف بنكي"},
            files={"file": ("l.pdf", b"%PDF-1.4 x", "application/pdf")})
    r = cl.post(f"/api/bookings/{bid}/handover/complete", json={"electricity": 1, "water": 1, "keys": 2})
    assert r.status_code == 409 and "أقساط غير مسددة" in r.json()["detail"]
