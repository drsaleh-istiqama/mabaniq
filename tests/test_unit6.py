"""Unit 6 — quotations, PDF documents (quote / contract / invoice / receipt), delivery (e-mail attachment, WhatsApp share link),
public verification, letterhead, and building plans with unit markers (staff + customer visibility)."""
import io
import json
import os
import re
import struct
import tempfile
import time
import zlib

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "u6.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import mail  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import connect  # noqa: E402

CSRF = "csrf-unit6-" + "p" * 30
KYC = {"id_type": "بطاقة مدنية", "id_number": "12345678", "nationality": "عُماني", "id_expiry": "2030-01-01", "source_of_funds": "راتب", "consent_signed": True}


def login_as(c, user):
    c.cookies.set(A.COOKIE, A.issue_session(user))
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


@pytest.fixture()
def cl():
    from backend import observability as O
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        login_as(c, "admin")
        c.post("/api/reset")
        db = connect()
        db.execute("DELETE FROM login_attempts")  # the whole suite logs in many times from one address; this module logs customers in by password
        db.execute("DELETE FROM auth_failures")
        db.commit()
        yield c


def png_bytes(w=4, h=4, color=(200, 30, 30)) -> bytes:
    """A tiny valid PNG (no PIL needed)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(color) * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def free_unit(cl, idx=0):
    pid = cl.get("/api/projects").json()[idx]["id"]
    return next(x for x in cl.get(f"/api/units?project_id={pid}").json() if x["status"] == "a"), pid


def latest_mail():
    files = sorted(mail.outbox_dir().glob("*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8"))


def pdf_text(b: bytes) -> str:
    try:
        import pymupdf
    except Exception:  # noqa: BLE001
        return ""
    d = pymupdf.open(stream=io.BytesIO(b), filetype="pdf")
    return "\n".join(p.get_text() for p in d)


# ---------------------------------------------------------------- quotations
def test_quote_lifecycle_pdf_and_conversion(cl):
    u, pid = free_unit(cl)
    r = cl.post("/api/quotes", json={"unit_code": u["code"], "customer_name": "عميل عرض السعر", "phone": "+968 9111 2222", "email": "q@example.om",
                                     "plan": "6040", "discount_pct": 0.02, "valid_days": 10, "notes": "يشمل موقف سيارة واحد."})
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["number"].startswith("QT-") and q["status"] == "issued" and q["price"] == round(u["price"] * 0.98)
    assert len(q["schedule"]) == 7 and abs(sum(s["amount"] for s in q["schedule"]) - q["price"]) < 5
    # the unit stays available — a quote is not a reservation
    assert cl.get(f"/api/units/{u['code']}").json()["status"] == "a"
    # PDF: valid, Arabic, Western digits, verification code registered
    pdf = cl.get(f"/api/docs/quote/{q['id']}.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    assert "inline" in pdf.headers["content-disposition"]
    txt = pdf_text(pdf.content)
    if txt:
        assert q["number"] in txt and not re.search(r"[٠-٩]", txt)
    db = connect()
    iss = db.execute("SELECT * FROM doc_issues WHERE kind='quote' AND ref_id=?", (q["id"],)).fetchone()
    assert iss and len(iss["verify_code"]) >= 10
    assert cl.get(f"/api/quotes/{q['id']}").json()["verify_code"] == iss["verify_code"]
    # public verification page (no login), RTL, no personal data
    v = TestClient(app).get(f"/verify/jadwa/{iss['verify_code']}")
    assert v.status_code == 200 and 'dir="rtl"' in v.text and q["number"] in v.text and "ساري" in v.text and "9111" not in v.text
    assert "لا يوجد مستند" in TestClient(app).get("/verify/jadwa/NOPE12345").text
    # convert → booking at the quoted price through the shared path
    cv = cl.post(f"/api/quotes/{q['id']}/convert")
    assert cv.status_code == 200, cv.text
    bid = cv.json()["booking_id"]
    b = db.execute("SELECT price, list_price FROM bookings WHERE id=?", (bid,)).fetchone()
    assert b["price"] == q["price"] and b["list_price"] == u["price"]
    assert cl.get(f"/api/units/{u['code']}").json()["status"] == "r"
    assert cl.get(f"/api/quotes/{q['id']}").json()["status"] == "converted"
    assert cl.post(f"/api/quotes/{q['id']}/convert").status_code == 409
    assert cl.post(f"/api/quotes/{q['id']}/cancel").status_code == 409
    # the customer created by the conversion carries the e-mail from the quote
    cu = db.execute("SELECT email FROM customers WHERE id=?", (cv.json()["customer_id"],)).fetchone()
    assert cu["email"] == "q@example.om"


def test_quote_discount_authority_expiry_and_cancel(cl):
    u, _ = free_unit(cl, 1)
    with TestClient(app, base_url="https://testserver") as s:
        login_as(s, "sales")
        assert s.post("/api/quotes", json={"unit_code": u["code"], "customer_name": "عميل مبيعات", "phone": "99990000", "plan": "milestone", "discount_pct": 0.05}).status_code == 403
        ok = s.post("/api/quotes", json={"unit_code": u["code"], "customer_name": "عميل مبيعات", "phone": "99990000", "plan": "milestone", "discount_pct": 0.02})
        assert ok.status_code == 200
    qid = ok.json()["id"]
    db = connect()
    db.execute("UPDATE quotes SET valid_until='2020-01-01' WHERE id=?", (qid,))
    db.commit()
    assert cl.get(f"/api/quotes/{qid}").json()["status"] == "expired"
    assert cl.post(f"/api/quotes/{qid}/convert").status_code == 409
    assert any(x["id"] == qid for x in cl.get("/api/quotes?status=expired").json())
    assert cl.post(f"/api/quotes/{qid}/cancel").status_code == 200
    assert cl.get(f"/api/quotes/{qid}").json()["status"] == "cancelled"
    # a reserved unit cannot be quoted
    r_unit = next(x for x in cl.get(f"/api/units?project_id={cl.get('/api/projects').json()[0]['id']}").json() if x["status"] == "r")
    assert cl.post("/api/quotes", json={"unit_code": r_unit["code"], "customer_name": "عميل", "phone": "99990000", "plan": "6040"}).status_code == 409


# ---------------------------------------------------------------- contract / invoice / receipt PDFs + customer access
def test_contract_invoice_receipt_pdfs_and_portal_access(cl):
    u, _ = free_unit(cl, 2)
    b = cl.post("/api/bookings", json={"unit_code": u["code"], "customer_name": "عميل المستندات", "phone": "+968 9555 0600", "plan": "milestone"}).json()
    bid, cid = b["booking_id"], b["customer_id"]
    assert cl.get(f"/api/docs/contract/{bid}.pdf").status_code == 404  # no contract yet
    cl.post(f"/api/customers/{cid}/kyc", json=KYC)
    assert cl.post(f"/api/bookings/{bid}/confirm").status_code == 200  # deposit → payment + receipt + invoice
    k = cl.post(f"/api/bookings/{bid}/contract").json()
    pdf = cl.get(f"/api/docs/contract/{bid}.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    db = connect()
    before = db.execute("SELECT sha256 FROM doc_issues WHERE kind='contract' AND ref_id=?", (bid,)).fetchone()["sha256"]
    cl.post(f"/api/bookings/{bid}/contract/sign-inperson", json={"typed_name": "عميل المستندات", "accept": True})
    cl.get(f"/api/docs/contract/{bid}.pdf")
    after = db.execute("SELECT sha256, revised FROM doc_issues WHERE kind='contract' AND ref_id=?", (bid,)).fetchone()
    assert after["sha256"] != before and after["revised"]  # the registry follows the signature
    assert "موقَّع" in TestClient(app).get(f"/verify/jadwa/{db.execute('SELECT verify_code FROM doc_issues WHERE kind=? AND ref_id=?', ('contract', bid)).fetchone()['verify_code']}").text
    assert k["number"] in pdf_text(pdf.content) or not pdf_text(pdf.content)

    pay = db.execute("SELECT pm.id, pm.receipt FROM payments pm JOIN installments i ON i.id=pm.installment_id WHERE i.booking_id=?", (bid,)).fetchone()
    inv = db.execute("SELECT id, number FROM invoices WHERE customer_id=?", (cid,)).fetchone()
    for kind, rid in (("invoice", inv["id"]), ("receipt", pay["id"])):
        r = cl.get(f"/api/docs/{kind}/{rid}.pdf?download=1")
        assert r.status_code == 200 and r.content[:5] == b"%PDF-" and "attachment" in r.headers["content-disposition"]
    recs = cl.get("/api/receipts").json()
    assert any(x["receipt"] == pay["receipt"] for x in recs)

    # customer: own documents yes, someone else's no
    acc = cl.post(f"/api/customers/{cid}/account", json={"username": f"docs{int(time.time()) % 100000}"}).json()
    db.execute("UPDATE users SET must_change=0 WHERE username=?", (acc["username"],))  # skip the first-login password gate
    db.commit()
    with TestClient(app, base_url="https://testserver") as cust:
        assert cust.post("/api/auth/login", json={"username": acc["username"], "password": acc["temporary_password"]}).status_code == 200
        idx = cust.get("/api/portal/docs").json()
        assert idx["contracts"][0]["booking_id"] == bid and idx["invoices"] and idx["receipts"]
        for p in (idx["contracts"][0]["pdf"], idx["invoices"][0]["pdf"], idx["receipts"][0]["pdf"]):
            assert cust.get(p).status_code == 200
        other_inv = db.execute("SELECT id FROM invoices WHERE customer_id!=? LIMIT 1", (cid,)).fetchone()
        assert cust.get(f"/api/portal/docs/invoice/{other_inv['id']}.pdf").status_code == 404
        assert cust.get(f"/api/docs/invoice/{inv['id']}.pdf").status_code == 403  # staff route is closed to customers
    # engineer has no financial document access
    with TestClient(app, base_url="https://testserver") as eng:
        login_as(eng, "engineer")
        assert eng.get(f"/api/docs/invoice/{inv['id']}.pdf").status_code == 403


# ---------------------------------------------------------------- delivery
def test_send_by_email_attachment_and_whatsapp_share_link(cl):
    u, _ = free_unit(cl, 0)
    q = cl.post("/api/quotes", json={"unit_code": u["code"], "customer_name": "عميل الإرسال", "phone": "+968 9222 3333", "email": "send@example.om", "plan": "6040"}).json()
    r = cl.post(f"/api/docs/quote/{q['id']}/send", json={"channel": "email"})
    assert r.status_code == 200 and r.json()["to"] == "send@example.om" and r.json()["outbox"] is True
    m = latest_mail()
    assert m["attachments"] and m["attachments"][0]["name"] == f"{q['number']}.pdf" and m["attachments"][0]["bytes"] > 5000 and m["kind"] == "doc:quote"
    assert cl.post(f"/api/docs/quote/{q['id']}/send", json={"channel": "email", "to": "not-an-email"}).status_code == 400
    w = cl.post(f"/api/docs/quote/{q['id']}/send", json={"channel": "whatsapp", "message": "تفضّل عرض السعر"})
    assert w.status_code == 200 and w.json()["wa_url"].startswith("https://wa.me/96892223333?text=") and "/d/jadwa/" in w.json()["link"]
    # the share link works without any login, then expires
    path = w.json()["link"].split("https://testserver", 1)[1]
    with TestClient(app) as anon:
        got = anon.get(path)
        assert got.status_code == 200 and got.content[:5] == b"%PDF-"
        db = connect()
        db.execute("UPDATE share_links SET expires=?", (time.time() - 1,))
        db.commit()
        assert anon.get(path).status_code == 404
        assert anon.get("/d/jadwa/" + "x" * 30).status_code == 404
    db = connect()
    assert db.execute("SELECT COUNT(*) FROM doc_sends WHERE kind='quote' AND ref_id=?", (q["id"],)).fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM wa_messages WHERE direction='out' AND engine='docs'").fetchone()[0] >= 1


# ---------------------------------------------------------------- letterhead
def test_brand_letterhead_with_stamp_and_signature_images(cl):
    up = cl.post("/api/documents", data={"ref_type": "brand", "ref_id": "0", "title": "ختم الشركة", "category": "هوية"},
                 files={"file": ("stamp.png", png_bytes(), "image/png")})
    assert up.status_code == 200, up.text
    stamp_id = up.json()["id"]
    pdf_doc = cl.post("/api/documents", data={"ref_type": "brand", "ref_id": "0", "title": "ملف", "category": "هوية"},
                      files={"file": ("x.pdf", b"%PDF-1.4 not an image", "application/pdf")}).json()["id"]
    assert cl.post("/api/admin/brand", json={"stamp_doc": pdf_doc}).status_code == 400  # a stamp must be an image
    r = cl.post("/api/admin/brand", json={"name": "جدوى للتطوير العقاري ش.م.م", "cr": "1234567", "vat": "OM1100012345", "address": "مسقط، المعبيلة",
                                           "phone": "+968 2400 0000", "email": "sales@jadwa.om", "signatory": "المدير التنفيذي", "stamp_doc": stamp_id, "sign_doc": stamp_id})
    assert r.status_code == 200 and r.json()["stamp_doc"] == stamp_id
    g = cl.get("/api/admin/brand").json()
    assert g["name"].startswith("جدوى") and g["vat"] == "OM1100012345" and "stamp_path" not in g
    u, _ = free_unit(cl, 1)
    q = cl.post("/api/quotes", json={"unit_code": u["code"], "customer_name": "عميل الهوية", "phone": "99990001", "plan": "milestone"}).json()
    pdf = cl.get(f"/api/docs/quote/{q['id']}.pdf")
    assert pdf.status_code == 200 and b"/Image" in pdf.content  # stamp/signature embedded
    txt = pdf_text(pdf.content)
    if txt:
        assert "OM1100012345" in txt
    with TestClient(app, base_url="https://testserver") as s:
        login_as(s, "sales")
        assert s.post("/api/admin/brand", json={"name": "x"}).status_code == 403


# ---------------------------------------------------------------- plans
def test_plans_upload_markers_and_customer_visibility(cl):
    u, pid = free_unit(cl, 0)
    kinds = {k["kind"]: k for k in cl.get("/api/plans/kinds").json()}
    assert kinds["structural"]["internal"] and not kinds["floor"]["internal"]
    fp = cl.post("/api/plans", data={"project_id": str(pid), "kind": "floor", "title": f"مخطط الطابق {u['floor']}", "building": u["building"] or "", "floor": str(u["floor"] or "")},
                 files={"file": ("floor.png", png_bytes(8, 8), "image/png")})
    assert fp.status_code == 200, fp.text
    plan = fp.json()
    assert plan["kind_label"] == "مخطط طابق" and plan["public"] == 1 and plan["url"].startswith("/api/documents/")
    st = cl.post("/api/plans", data={"project_id": str(pid), "kind": "structural", "title": "أساسات", "public": "1"},
                 files={"file": ("str.pdf", b"%PDF-1.4 structural", "application/pdf")}).json()
    assert st["public"] == 0  # internal kinds are never public
    rend = cl.post("/api/plans", data={"project_id": str(pid), "kind": "render", "title": "التصور النهائي للمبنى"},
                   files={"file": ("r.jpg", b"\xff\xd8\xff\xe0" + b"0" * 100, "image/jpeg")}).json()
    assert cl.post("/api/plans", data={"project_id": str(pid), "kind": "weird", "title": "نوع غير معروف"}, files={"file": ("a.png", png_bytes(), "image/png")}).status_code == 400
    # markers: unknown unit refused, valid saved, one per unit
    assert cl.post(f"/api/plans/{plan['id']}/markers", json={"markers": [{"unit_code": "NOPE-1", "x": 10, "y": 10}]}).status_code == 404
    assert cl.post(f"/api/plans/{plan['id']}/markers", json={"markers": [{"unit_code": u["code"], "x": 150, "y": 10}]}).status_code == 400
    mk = cl.post(f"/api/plans/{plan['id']}/markers", json={"markers": [{"unit_code": u["code"], "x": 42.5, "y": 61.2}, {"unit_code": u["code"], "x": 1, "y": 1}]})
    assert mk.status_code == 200 and mk.json()["markers"] == [{"unit_code": u["code"], "x": 42.5, "y": 61.2}]
    lst = cl.get(f"/api/plans?project_id={pid}").json()
    assert [p["kind"] for p in lst][:1] == ["floor"] and len(lst) == 3
    up = cl.get(f"/api/units/{u['code']}/plans").json()
    assert up["floor_plan"]["me"]["x"] == 42.5 and any(o["kind"] == "render" for o in up["others"])
    assert cl.get(plan["url"]).status_code == 200  # staff can open the file

    # customer of a booking in this project: sees floor plan with only their marker and the render, never the structural drawing
    b = cl.post("/api/bookings", json={"unit_code": u["code"], "customer_name": "عميل المخططات", "phone": "+968 9444 5555", "plan": "6040"}).json()
    acc = cl.post(f"/api/customers/{b['customer_id']}/account", json={"username": f"plan{int(time.time()) % 100000}"}).json()
    db = connect()
    db.execute("UPDATE users SET must_change=0 WHERE username=?", (acc["username"],))
    db.commit()
    with TestClient(app, base_url="https://testserver") as cust:
        assert cust.post("/api/auth/login", json={"username": acc["username"], "password": acc["temporary_password"]}).status_code == 200
        mine = cust.get("/api/portal/plans").json()
        assert mine and mine[0]["unit"] == u["code"] and mine[0]["floor_plan"]["me"]["unit_code"] == u["code"]
        assert mine[0]["floor_plan"]["url"].startswith("/api/portal/plans/")
        assert cust.get(mine[0]["floor_plan"]["url"]).status_code == 200
        assert all(o["kind"] != "structural" for o in mine[0]["others"])
        assert cust.get(f"/api/portal/plans/{st['document_id']}").status_code == 404
        assert cust.get(plan["url"]).status_code == 403  # staff route
    # another project's customer cannot open this project's plan
    u2, pid2 = free_unit(cl, 1)
    b2 = cl.post("/api/bookings", json={"unit_code": u2["code"], "customer_name": "عميل آخر", "phone": "+968 9666 7777", "plan": "6040"}).json()
    acc2 = cl.post(f"/api/customers/{b2['customer_id']}/account", json={"username": f"plan2{int(time.time()) % 100000}"}).json()
    db.execute("UPDATE users SET must_change=0 WHERE username=?", (acc2["username"],))
    db.commit()
    with TestClient(app, base_url="https://testserver") as other:
        assert other.post("/api/auth/login", json={"username": acc2["username"], "password": acc2["temporary_password"]}).status_code == 200
        assert other.get(f"/api/portal/plans/{plan['document_id']}").status_code == 404
    # patch + remove
    assert cl.post(f"/api/plans/{rend['id']}", json={"public": False}).json()["public"] == 0
    assert cl.post(f"/api/plans/{rend['id']}/remove").json()["ok"] and len(cl.get(f"/api/plans?project_id={pid}").json()) == 2
    with TestClient(app, base_url="https://testserver") as eng:
        login_as(eng, "engineer")
        assert eng.post(f"/api/plans/{plan['id']}/markers", json={"markers": []}).status_code == 403  # markers need inventory permission
        assert eng.get(f"/api/plans?project_id={pid}").status_code == 200
