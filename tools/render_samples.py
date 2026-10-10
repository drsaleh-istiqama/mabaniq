"""Dev helper: render one sample of each PDF (quote, contract, invoice, receipt) from a throw-away SQLite demo and rasterize
page 1 to PNG for a visual check. Writes to .local/samples/. Not part of the product."""
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
os.environ["MABANIQ_DB"] = os.path.join(tempfile.mkdtemp(), "samples.db")
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_RETENTION"] = "0"
os.environ["MABANIQ_LOG_JSON"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import connect  # noqa: E402

OUT = os.path.join(ROOT, ".local", "samples")
os.makedirs(OUT, exist_ok=True)
CSRF = "csrf-samples-" + "s" * 28
KYC = {"id_type": "بطاقة مدنية", "id_number": "12345678", "nationality": "عُماني", "id_expiry": "2030-01-01", "source_of_funds": "راتب", "consent_signed": True}

with TestClient(app, base_url="https://demo.mabaniq.local") as c:
    c.cookies.set(A.COOKIE, A.issue_session("admin"))
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    c.post("/api/admin/brand", json={"name": "جدوى للتطوير العقاري ش.م.م", "cr": "1234567", "vat": "OM1100012345", "address": "مسقط — المعبيلة الجنوبية، مبنى 12",
                                     "phone": "+968 2400 0000", "email": "sales@jadwa.om", "signatory": "صالح الزهيمي", "signatory_title": "الرئيس التنفيذي"})
    pid = c.get("/api/projects").json()[2]["id"]
    u = next(x for x in c.get(f"/api/units?project_id={pid}").json() if x["status"] == "a")
    q = c.post("/api/quotes", json={"unit_code": u["code"], "customer_name": "خالد بن سعيد الهنائي", "phone": "+968 9123 4567", "email": "khalid@example.om",
                                    "plan": "6040", "discount_pct": 0.02, "valid_days": 10, "notes": "يشمل موقف سيارة مظلل ومخزنًا في الطابق الأرضي."}).json()
    b = c.post(f"/api/quotes/{q['id']}/convert").json()
    bid, cid = b["booking_id"], b["customer_id"]
    c.post(f"/api/customers/{cid}/kyc", json=KYC)
    c.post(f"/api/bookings/{bid}/confirm")
    c.post(f"/api/bookings/{bid}/contract")
    c.post(f"/api/bookings/{bid}/contract/sign-inperson", json={"typed_name": "خالد بن سعيد الهنائي", "accept": True})
    db = connect()
    pay = db.execute("SELECT pm.id FROM payments pm JOIN installments i ON i.id=pm.installment_id WHERE i.booking_id=?", (bid,)).fetchone()["id"]
    inv = db.execute("SELECT id FROM invoices WHERE customer_id=?", (cid,)).fetchone()["id"]
    import pymupdf
    for kind, rid in (("quote", q["id"]), ("contract", bid), ("invoice", inv), ("receipt", pay)):
        r = c.get(f"/api/docs/{kind}/{rid}.pdf")
        assert r.status_code == 200, (kind, r.text)
        open(os.path.join(OUT, f"{kind}.pdf"), "wb").write(r.content)
        d = pymupdf.open(stream=r.content, filetype="pdf")
        d[0].get_pixmap(dpi=70).save(os.path.join(OUT, f"{kind}.png"))
        print(kind, len(r.content), "bytes", d.page_count, "pages")
print("samples in", OUT)
