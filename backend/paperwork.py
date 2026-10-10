"""Mabaniq — paperwork (Unit 6): quotations, issued documents (PDF), delivery (print / e-mail / WhatsApp), verification, letterhead.

* A **quotation** is a priced offer for one available unit with a payment schedule and an expiry; it never reserves the
  unit. Discounts follow the sales authority (≤ 2 % for anyone who may book; more needs the `decide` permission).
  «تحويل إلى حجز» creates the booking at the quoted price through the same path as a manual booking.
* **Documents** (quote · contract · invoice · receipt) are rendered on demand from the database — nothing is stored as a
  file — and registered once in `doc_issues` with a verification code and a content hash, so `/verify/<tenant>/<code>`
  can confirm a printed copy without a login. Every delivery (print, e-mail, WhatsApp) is audited.
* **Delivery**: e-mail attaches the PDF through `mail.send`; WhatsApp gets a 30-day signed share link (`/d/<tenant>/<token>`)
  inside a `wa.me` message the staff member opens from their own WhatsApp — the platform has no Business API yet and says so.
* **Letterhead** (`brand:*` settings + uploaded logo/stamp/signature) is per developer organisation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import time
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import auth as A
from . import mail, pdfgen
from .auth import need, need_any
from .common import act_as, audit, db, now_s, rows, today
from .db import TENANT, audit_insert, setting_f, valid_tenant
from .modules import PLAN_LABEL, booking_full, one, portal_owned
from .seed import schedule

router = APIRouter()
KINDS = ("quote", "contract", "invoice", "receipt")
SHARE_DAYS = 30
QUOTE_MAX_DISCOUNT_SALES = 0.02
QUOTE_MAX_DISCOUNT_DECIDE = 0.15
METHOD_LABEL = {"sandbox": "بوابة الدفع (تجريبي)", "cash": "نقدًا", "transfer": "تحويل بنكي", "cheque": "شيك", "card": "بطاقة", "gateway": "بوابة الدفع"}


# ---------------------------------------------------------------- brand / letterhead
BRAND_KEYS = ("name", "cr", "vat", "address", "phone", "email", "signatory", "signatory_title")
BRAND_DOCS = ("logo", "stamp", "sign")


def _setting(c, k: str) -> str | None:
    r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return r["v"] if r else None


def brand(c) -> dict:
    """Letterhead data + absolute paths of the uploaded images (validated against their stored hash)."""
    from .modules2 import _docs_dir
    out = {k: _setting(c, f"brand:{k}") or "" for k in BRAND_KEYS}
    if not out["name"]:
        tn = _setting(c, "tenant_name")
        out["name"] = json.loads(tn) if tn and tn.startswith('"') else (tn or "المطوّر")
    for d in BRAND_DOCS:
        did = _setting(c, f"brand:{d}_doc")
        out[f"{d}_doc"] = int(did) if did and did.isdigit() else None
        out[f"{d}_path"] = None
        if out[f"{d}_doc"]:
            row = c.execute("SELECT stored, sha256 FROM documents WHERE id=? AND ref_type='brand'", (out[f"{d}_doc"],)).fetchone()
            if row:
                p = _docs_dir() / row["stored"]
                if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == row["sha256"]:
                    out[f"{d}_path"] = str(p)
    return out


class BrandIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    cr: str | None = Field(default=None, max_length=40)
    vat: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    signatory: str | None = Field(default=None, max_length=120)
    signatory_title: str | None = Field(default=None, max_length=120)
    logo_doc: int | None = None
    stamp_doc: int | None = None
    sign_doc: int | None = None


@router.get("/api/admin/brand")
def brand_get(_=Depends(need("admin"))):
    b = brand(db())
    return {k: v for k, v in b.items() if not k.endswith("_path")}


@router.post("/api/admin/brand")
def brand_set(body: BrandIn, _=Depends(act_as("admin"))):
    c = db()
    for k in BRAND_KEYS:
        v = getattr(body, k)
        if v is not None:
            c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"brand:{k}", v.strip()))
    for d in BRAND_DOCS:
        did = getattr(body, f"{d}_doc")
        if did is not None:
            if did and not c.execute("SELECT 1 FROM documents WHERE id=? AND ref_type='brand' AND mime IN ('image/png','image/jpeg')", (did,)).fetchone():
                raise HTTPException(400, f"المستند {did} ليس صورة مرفوعة ضمن هوية المطوّر")
            c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"brand:{d}_doc", str(did or "")))
    audit(c, "تحديث هوية المستندات", ", ".join(k for k in BRAND_KEYS + tuple(f"{d}_doc" for d in BRAND_DOCS) if getattr(body, k) is not None))
    c.commit()
    b = brand(c)
    return {k: v for k, v in b.items() if not k.endswith("_path")}


# ---------------------------------------------------------------- verification registry
def _public_url(request: Request) -> str:
    from .identity import public_url
    return public_url(request)


def _issue(c, kind: str, ref_id: int, number: str, payload: dict, by: str) -> dict:
    """One registry row per document; the content hash is refreshed when the content changed (e.g. a contract got signed)."""
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    row = c.execute("SELECT * FROM doc_issues WHERE kind=? AND ref_id=?", (kind, ref_id)).fetchone()
    if row:
        if row["sha256"] != h:
            c.execute("UPDATE doc_issues SET sha256=?, number=?, revised=? WHERE id=?", (h, number, now_s(), row["id"]))
        return {"verify_code": row["verify_code"], "sha256": h, "issued": row["issued"]}
    code = secrets.token_urlsafe(9).replace("-", "a").replace("_", "b")[:12].upper()
    c.execute("INSERT INTO doc_issues(kind,ref_id,number,verify_code,sha256,issued,issued_by) VALUES(?,?,?,?,?,?,?)", (kind, ref_id, number, code, h, now_s(), by))
    return {"verify_code": code, "sha256": h, "issued": now_s()}


def _verify_url(request: Request, code: str) -> str:
    return f"{_public_url(request)}/verify/{TENANT.get()}/{code}"


# ---------------------------------------------------------------- document data
def quote_row(c, qid: int) -> dict:
    q = one(c, """SELECT q.*, u.code, u.type, u.area, u.view, u.building, u.floor, p.name project, p.location, p.handover
                  FROM quotes q JOIN units u ON u.id=q.unit_id JOIN projects p ON p.id=u.project_id WHERE q.id=?""", (qid,), "عرض السعر غير موجود")
    d = dict(q)
    d["schedule"] = json.loads(d["schedule"] or "[]")
    d["plan_label"] = PLAN_LABEL.get(d["plan"], d["plan"])
    if d["status"] == "issued" and d["valid_until"] < today().isoformat():
        d["status"] = "expired"
    return d


def contract_row(c, bid: int) -> dict:
    k = one(c, "SELECT * FROM sale_contracts WHERE booking_id=?", (bid,), "لم يصدر عقد لهذا الحجز بعد")
    b = booking_full(c, bid)
    return {**dict(k), "customer": b["customer"], "code": b["code"], "project": b["project"], "booking_id": bid}


def invoice_row(c, iid: int) -> dict:
    inv = dict(one(c, "SELECT * FROM invoices WHERE id=?", (iid,), "الفاتورة غير موجودة"))
    inv["kind_label"] = {"installment": "قسط وحدة", "resale_fee": "رسوم نقل ملكية", "service_charge": "رسوم خدمة اتحاد الملاك", "rent": "إيجار"}.get(inv["kind"], inv["kind"])
    inv["unit"] = inv["project"] = None
    inv["booking_id"] = None
    if inv["ref_type"] == "installment":
        r = c.execute("""SELECT u.code, p.name project, b.id booking_id FROM installments i JOIN bookings b ON b.id=i.booking_id
                         JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id WHERE i.id=?""", (inv["ref_id"],)).fetchone()
        if r:
            inv.update({"unit": r["code"], "project": r["project"], "booking_id": r["booking_id"]})
    return inv


def receipt_row(c, pid: int) -> dict:
    r = one(c, """SELECT pm.*, i.label, i.amount inst_amount, i.booking_id, u.code, p.name project, cu.name customer, cu.id customer_id
                  FROM payments pm JOIN installments i ON i.id=pm.installment_id JOIN bookings b ON b.id=i.booking_id
                  JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id JOIN customers cu ON cu.id=b.customer_id WHERE pm.id=?""", (pid,), "الإيصال غير موجود")
    d = dict(r)
    tot = c.execute("SELECT SUM(amount) t, SUM(paid_amount) pd FROM installments WHERE booking_id=?", (d["booking_id"],)).fetchone()
    d["remaining"] = (tot["t"] or 0) - (tot["pd"] or 0)
    d["method_label"] = METHOD_LABEL.get(d.get("method") or "", d.get("method") or "")
    inv = c.execute("SELECT number FROM invoices WHERE ref_type='installment' AND ref_id=?", (d["installment_id"],)).fetchone()
    d["invoice_number"] = inv["number"] if inv else None
    return d


def render(c, request: Request, kind: str, ref_id: int, by: str = "النظام") -> tuple[bytes, str, dict]:
    """→ (pdf bytes, filename, data) — registers the issue and embeds the verification code."""
    b = brand(c)
    if kind == "quote":
        d = quote_row(c, ref_id)
        iss = _issue(c, kind, ref_id, d["number"], {k: d[k] for k in ("number", "price", "valid_until", "schedule", "customer_name", "code")}, by)
        d.update(iss)
        return pdfgen.render_quote(b, d, _verify_url(request, d["verify_code"])), f"{d['number']}.pdf", d
    if kind == "contract":
        d = contract_row(c, ref_id)
        iss = _issue(c, kind, ref_id, d["number"], {"number": d["number"], "sha256": d["sha256"], "signed": d.get("customer_signed_at")}, by)
        d.update(iss)
        return pdfgen.render_contract(b, d, _verify_url(request, d["verify_code"])), f"{d['number']}.pdf", d
    if kind == "invoice":
        d = invoice_row(c, ref_id)
        iss = _issue(c, kind, ref_id, d["number"], {k: d[k] for k in ("number", "net", "vat", "total", "issued", "customer")}, by)
        d.update(iss)
        return pdfgen.render_invoice(b, d, _verify_url(request, d["verify_code"])), f"{d['number']}.pdf", d
    if kind == "receipt":
        d = receipt_row(c, ref_id)
        d["issued_by"] = by
        iss = _issue(c, kind, ref_id, d["receipt"], {k: d[k] for k in ("receipt", "amount", "at", "customer", "label")}, by)
        d.update(iss)
        return pdfgen.render_receipt(b, d, _verify_url(request, d["verify_code"])), f"{d['receipt']}.pdf", d
    raise HTTPException(404, "نوع المستند غير معروف")


def _pdf_response(pdf: bytes, filename: str, download: bool = False) -> Response:
    disp = "attachment" if download else "inline"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{urlquote(filename)}", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


STAFF_PERMS = {"quote": ("book", "inventory", "finance"), "contract": ("book", "finance", "kyc"), "invoice": ("invoices", "finance", "book"), "receipt": ("invoices", "finance", "book")}


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(404, "نوع المستند غير معروف")
    return kind


@router.get("/api/docs/{kind}/{ref_id}.pdf")
def doc_pdf(kind: str, ref_id: int, request: Request, download: int = 0, u=Depends(need_any("book", "inventory", "finance", "invoices", "kyc"))):
    kind = _kind(kind)
    if not set(STAFF_PERMS[kind]) & set(u["perms"]):
        raise HTTPException(403, "ليست لديك صلاحية لهذا المستند")
    c = db()
    pdf, name, d = render(c, request, kind, ref_id, u["name"])
    audit(c, "إصدار مستند", f"{kind} {d.get('number') or d.get('receipt')} · طباعة/عرض")
    c.commit()
    return _pdf_response(pdf, name, bool(download))


def _portal_owned_doc(c, u, kind: str, ref_id: int) -> None:
    if kind == "contract":
        portal_owned(c, u, ref_id)
    elif kind == "invoice":
        inv = one(c, "SELECT customer_id FROM invoices WHERE id=?", (ref_id,), "الفاتورة غير موجودة")
        if inv["customer_id"] != u["customer_id"]:
            raise HTTPException(404, "الفاتورة غير موجودة")
    elif kind == "receipt":
        r = one(c, "SELECT b.customer_id FROM payments pm JOIN installments i ON i.id=pm.installment_id JOIN bookings b ON b.id=i.booking_id WHERE pm.id=?", (ref_id,), "الإيصال غير موجود")
        if r["customer_id"] != u["customer_id"]:
            raise HTTPException(404, "الإيصال غير موجود")
    else:
        raise HTTPException(404, "غير متاح في بوابة العميل")


@router.get("/api/portal/docs/{kind}/{ref_id}.pdf")
def portal_doc_pdf(kind: str, ref_id: int, request: Request, download: int = 0, u=Depends(need("portal"))):
    kind = _kind(kind)
    c = db()
    _portal_owned_doc(c, u, kind, ref_id)
    pdf, name, d = render(c, request, kind, ref_id, u["name"])
    audit(c, "تنزيل مستند (بوابة العميل)", f"{kind} {d.get('number') or d.get('receipt')}")
    c.commit()
    return _pdf_response(pdf, name, bool(download))


@router.get("/api/receipts")
def receipts(limit: int = 100, u=Depends(need_any("invoices", "finance", "book"))):
    c = db()
    return rows(c.execute("""SELECT pm.id, pm.receipt, pm.amount, pm.at, pm.method, pm.reconciled, i.label, u.code, cu.name customer, cu.email, cu.phone, i.booking_id
                             FROM payments pm JOIN installments i ON i.id=pm.installment_id JOIN bookings b ON b.id=i.booking_id
                             JOIN units u ON u.id=b.unit_id JOIN customers cu ON cu.id=b.customer_id ORDER BY pm.id DESC LIMIT ?""", (min(max(limit, 1), 500),)))


# ---------------------------------------------------------------- delivery
class SendIn(BaseModel):
    channel: str = Field(pattern="^(email|whatsapp)$")
    to: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=500)


def _recipient(c, kind: str, d: dict) -> dict:
    """Default recipient of a document: the customer on record."""
    if kind == "quote":
        return {"name": d["customer_name"], "email": d.get("email"), "phone": d.get("phone")}
    cid = d.get("customer_id")
    if kind == "contract":
        cid = c.execute("SELECT customer_id FROM bookings WHERE id=?", (d["booking_id"],)).fetchone()["customer_id"]
    if cid:
        cu = c.execute("SELECT name, phone, email FROM customers WHERE id=?", (cid,)).fetchone()
        if cu:
            return {"name": cu["name"], "email": cu["email"], "phone": cu["phone"]}
    return {"name": d.get("customer") or "", "email": None, "phone": None}


def _share_link(c, request: Request, kind: str, ref_id: int, by: str) -> str:
    token = secrets.token_urlsafe(24)
    c.execute("INSERT INTO share_links(token_hash,kind,ref_id,expires,created,created_by) VALUES(?,?,?,?,?,?)",
              (hashlib.sha256(token.encode()).hexdigest(), kind, ref_id, time.time() + SHARE_DAYS * 86400, time.time(), by))
    return f"{_public_url(request)}/d/{TENANT.get()}/{token}"


def _digits(phone: str | None) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


@router.post("/api/docs/{kind}/{ref_id}/send")
def doc_send(kind: str, ref_id: int, body: SendIn, request: Request, u=Depends(need_any("book", "invoices", "finance", "kyc"))):
    kind = _kind(kind)
    if not set(STAFF_PERMS[kind]) & set(u["perms"]):
        raise HTTPException(403, "ليست لديك صلاحية لهذا المستند")
    c = db()
    pdf, name, d = render(c, request, kind, ref_id, u["name"])
    rcpt = _recipient(c, kind, d)
    title = {"quote": "عرض سعر", "contract": "عقد البيع", "invoice": "الفاتورة", "receipt": "إيصال الاستلام"}[kind]
    number = d.get("number") or d.get("receipt")
    if body.channel == "email":
        to = (body.to or rcpt.get("email") or "").strip().lower()
        from .identity import EMAIL_RE
        if not EMAIL_RE.match(to):
            raise HTTPException(400, "لا يوجد بريد إلكتروني للعميل — أدخل بريدًا صالحًا")
        if not mail.available():
            raise HTTPException(503, "خدمة البريد غير مهيّأة على هذا الخادم")
        text = (body.message or "").strip() or f"مرحبًا {rcpt['name']}،\n\nمرفق {title} رقم {number} من {brand(c)['name']}. يمكنك التحقق من صحة المستند عبر رمز التحقق المطبوع فيه."
        res = mail.send(to, f"{title} {number} — {brand(c)['name']}", text, kind=f"doc:{kind}", attachments=[(name, pdf, "application/pdf")])
        c.execute("INSERT INTO doc_sends(kind,ref_id,channel,recipient,sent_by,at) VALUES(?,?,?,?,?,?)", (kind, ref_id, "email", to, u["name"], now_s()))
        audit(c, "إرسال مستند بالبريد", f"{kind} {number} إلى {to}")
        c.commit()
        return {"ok": True, "channel": "email", "to": to, "delivered": res.get("delivered", False), "outbox": not res.get("delivered", False)}
    phone = _digits(body.to or rcpt.get("phone"))
    if len(phone) < 8:
        raise HTTPException(400, "لا يوجد رقم هاتف صالح للعميل")
    link = _share_link(c, request, kind, ref_id, u["name"])
    text = (body.message or "").strip() or f"مرحبًا {rcpt['name']}، هذا {title} رقم {number} من {brand(c)['name']}. الرابط صالح {SHARE_DAYS} يومًا:"
    c.execute("INSERT INTO wa_messages(phone,direction,body,at,engine) VALUES(?,?,?,?,?)", (rcpt.get("phone") or phone, "out", f"{text} {link}", now_s(), "docs"))
    c.execute("INSERT INTO doc_sends(kind,ref_id,channel,recipient,sent_by,at) VALUES(?,?,?,?,?,?)", (kind, ref_id, "whatsapp", phone, u["name"], now_s()))
    audit(c, "إرسال مستند عبر واتساب", f"{kind} {number} إلى {phone} (رابط صالح {SHARE_DAYS} يومًا)")
    c.commit()
    return {"ok": True, "channel": "whatsapp", "to": phone, "wa_url": f"https://wa.me/{phone}?text={urlquote(text + ' ' + link)}", "link": link,
            "note": "يُفتح واتساب على جهازك بالرسالة جاهزة؛ الربط المباشر بواجهة WhatsApp Business يحتاج حسابًا رسميًا (قرار مالك)."}


@router.get("/d/{tenant}/{token}", include_in_schema=False)
def shared_doc(tenant: str, token: str, request: Request):
    if not valid_tenant(tenant) or len(token) > 100:
        raise HTTPException(404, "الرابط غير صالح")
    TENANT.set(tenant)
    c = db()
    row = c.execute("SELECT * FROM share_links WHERE token_hash=? AND expires>?", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    if not row:
        raise HTTPException(404, "الرابط غير صالح أو منتهٍ — اطلب من المطوّر إرساله مجددًا")
    pdf, name, d = render(c, request, row["kind"], row["ref_id"], "رابط مشاركة")
    c.execute("UPDATE share_links SET opened=COALESCE(opened,0)+1, last_open=? WHERE token_hash=?", (now_s(), row["token_hash"]))
    c.commit()
    return _pdf_response(pdf, name)


# ---------------------------------------------------------------- public verification page (no script, RTL, inline style attributes only)
def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


@router.get("/verify/{tenant}/{code}", include_in_schema=False)
def verify_page(tenant: str, code: str):
    ok = valid_tenant(tenant) and code.isalnum() and len(code) <= 16
    row = None
    if ok:
        TENANT.set(tenant)
        c = db()
        row = c.execute("SELECT * FROM doc_issues WHERE verify_code=?", (code.upper(),)).fetchone()
        name = brand(c)["name"]
    status = ""
    if row and row["kind"] == "quote":
        q = c.execute("SELECT status, valid_until FROM quotes WHERE id=?", (row["ref_id"],)).fetchone()
        if q:
            st = "expired" if q["status"] == "issued" and q["valid_until"] < today().isoformat() else q["status"]
            status = {"issued": "ساري", "expired": "منتهي الصلاحية", "converted": "تحوّل إلى حجز", "cancelled": "ملغى"}.get(st, st)
    if row and row["kind"] == "contract":
        k = c.execute("SELECT customer_signed_at FROM sale_contracts WHERE booking_id=?", (row["ref_id"],)).fetchone()
        status = "موقَّع من العميل" if k and k["customer_signed_at"] else "غير موقَّع"
    kind_ar = {"quote": "عرض سعر", "contract": "عقد بيع", "invoice": "فاتورة", "receipt": "إيصال استلام"}
    card = 'style="max-width:560px;margin:40px auto;background:#fff;border-radius:16px;padding:28px 26px;font-family:Tajawal,Segoe UI,Tahoma,sans-serif;color:#111827;direction:rtl;text-align:right"'
    if row:
        body = (f'<div style="color:#15803d;font-weight:700;font-size:18px">✓ مستند صادر من {_esc(name)} عبر منصة مبانيك</div>'
                f'<p>النوع: <b>{kind_ar.get(row["kind"], row["kind"])}</b><br>الرقم: <b dir="ltr">{_esc(row["number"])}</b><br>تاريخ الإصدار: {_esc(pdfgen.hijri(row["issued"][:10]))}'
                f'{"<br>آخر تعديل في المحتوى: " + _esc(row["revised"]) if row["revised"] else ""}{"<br>الحالة: <b>" + _esc(status) + "</b>" if status else ""}'
                f'<br>بصمة المحتوى: <span dir="ltr" style="font-size:12px;color:#6b7280">{_esc(row["sha256"][:24])}…</span></p>'
                f'<p style="color:#6b7280;font-size:13px">قارن الرقم والتاريخ والبصمة المختصرة بما في النسخة التي بين يديك. لا يُظهر هذا الرابط أي بيانات شخصية.</p>')
    else:
        body = '<div style="color:#b91c1c;font-weight:700;font-size:18px">✗ لا يوجد مستند بهذا الرمز</div><p style="color:#6b7280">تحقق من الرمز المطبوع أسفل المستند، أو تواصل مع المطوّر.</p>'
    html = (f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>التحقق من مستند — مبانيك</title></head>'
            f'<body style="margin:0;background:#f5f6f8;padding:16px"><div {card}><div style="font-weight:700;margin-bottom:8px">مبانيك · التحقق من المستندات</div>{body}</div></body></html>')
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- quotations
class QuoteIn(BaseModel):
    unit_code: str = Field(min_length=3, max_length=30)
    customer_name: str = Field(min_length=3, max_length=80)
    phone: str = Field(min_length=7, max_length=30)
    email: str | None = Field(default=None, max_length=120)
    plan: str = Field(pattern="^(milestone|6040|murabaha)$")
    discount_pct: float = Field(default=0, ge=0, le=0.5)
    valid_days: int = Field(default=7, ge=1, le=60)
    lead_id: int | None = None
    notes: str | None = Field(default=None, max_length=600)


def _quote_number(c) -> str:
    seq = (c.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] or 0) + 1
    return f"QT-{today():%Y}-{seq:05d}"


@router.post("/api/quotes")
def quote_create(q: QuoteIn, request: Request, u=Depends(act_as("book"))):
    c = db()
    unit = c.execute("SELECT u.*, p.handover, p.name project FROM units u JOIN projects p ON p.id=u.project_id WHERE u.code=?", (q.unit_code,)).fetchone()
    if not unit:
        raise HTTPException(404, "الوحدة غير موجودة")
    if unit["status"] != "a" or unit["retained"]:
        raise HTTPException(409, "الوحدة غير متاحة للعرض")
    limit = QUOTE_MAX_DISCOUNT_DECIDE if "decide" in u["perms"] else QUOTE_MAX_DISCOUNT_SALES
    if q.discount_pct > limit + 1e-9:
        raise HTTPException(403, f"الخصم يتجاوز صلاحيتك ({limit * 100:g}٪) — يحتاج اعتماد الإدارة/المالية")
    if q.email:
        from .identity import EMAIL_RE, norm_email
        q.email = norm_email(q.email)
        if not EMAIL_RE.match(q.email):
            raise HTTPException(400, "صيغة البريد غير صحيحة")
    price = round(unit["price"] * (1 - q.discount_pct))
    t = today()
    sched = schedule(q.plan, price, t, dt.date.fromisoformat(unit["handover"]))
    number = _quote_number(c)
    qid = c.execute("""INSERT INTO quotes(number,unit_id,customer_name,phone,email,plan,list_price,discount_pct,price,valid_until,status,schedule,notes,created,created_by,lead_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (number, unit["id"], q.customer_name, q.phone, q.email, q.plan, unit["price"], q.discount_pct, price,
                     (t + dt.timedelta(days=q.valid_days)).isoformat(), "issued",
                     json.dumps([{"label": lb, "due": d.isoformat(), "amount": a} for lb, d, a in sched], ensure_ascii=False), q.notes, t.isoformat(), u["name"], q.lead_id)).lastrowid
    audit(c, "إصدار عرض سعر", f"{number} · {q.unit_code} لـ {q.customer_name} · {price:,.0f} ر.ع ({q.plan}, خصم {q.discount_pct * 100:g}٪)")
    c.commit()
    return quote_row(c, qid)


@router.get("/api/quotes")
def quote_list(status: str | None = None, _=Depends(need_any("book", "inventory", "finance"))):
    c = db()
    out = []
    t = today().isoformat()
    for r in c.execute("""SELECT q.id, q.number, q.customer_name, q.phone, q.email, q.plan, q.list_price, q.discount_pct, q.price, q.valid_until, q.status, q.created,
                                 q.created_by, q.booking_id, u.code, p.name project FROM quotes q JOIN units u ON u.id=q.unit_id JOIN projects p ON p.id=u.project_id ORDER BY q.id DESC"""):
        d = dict(r)
        if d["status"] == "issued" and d["valid_until"] < t:
            d["status"] = "expired"
        if not status or d["status"] == status:
            out.append(d)
    return out


@router.get("/api/quotes/{qid}")
def quote_get(qid: int, _=Depends(need_any("book", "inventory", "finance"))):
    return quote_row(db(), qid)


def create_booking(c, unit, customer_name: str, phone: str, plan: str, lead_id: int | None = None, broker_id: int | None = None,
                   price: float | None = None, email: str | None = None) -> dict:
    """The one path that turns a unit into a pending booking (manual booking and quotation conversion share it)."""
    t = today()
    cid = c.execute("INSERT INTO customers(name,phone,email,created) VALUES(?,?,?,?)", (customer_name, phone, email, t.isoformat())).lastrowid
    agreed = price if price is not None else unit["price"]
    bid = c.execute("INSERT INTO bookings(unit_id,customer_id,lead_id,plan,price,status,created,expires,broker_id,list_price) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (unit["id"], cid, lead_id, plan, agreed, "pending", t.isoformat(), (t + dt.timedelta(days=3)).isoformat(), broker_id, unit["price"])).lastrowid
    sched = schedule(plan, agreed, t, dt.date.fromisoformat(unit["handover"]))
    for s, (lb, d, amt) in enumerate(sched, 1):
        c.execute("INSERT INTO installments(booking_id,seq,label,due_date,amount) VALUES(?,?,?,?,?)", (bid, s, lb, d.isoformat(), amt))
    c.execute("UPDATE units SET status='r' WHERE id=?", (unit["id"],))
    if lead_id:
        c.execute("UPDATE leads SET stage=4 WHERE id=?", (lead_id,))
    return {"booking_id": bid, "customer_id": cid, "deposit": sched[0][2], "expires": (t + dt.timedelta(days=3)).isoformat(),
            "schedule": [{"label": lb, "due": d.isoformat(), "amount": a} for lb, d, a in sched],
            "next_step": "استكمال التحقق من الهوية ثم إصدار العقد للتوقيع"}


@router.post("/api/quotes/{qid}/convert")
def quote_convert(qid: int, u=Depends(act_as("book"))):
    c = db()
    q = quote_row(c, qid)
    if q["status"] != "issued":
        raise HTTPException(409, {"expired": "انتهت صلاحية العرض — أصدر عرضًا جديدًا", "converted": "تحوّل هذا العرض إلى حجز من قبل", "cancelled": "العرض ملغى"}.get(q["status"], "العرض غير قابل للتحويل"))
    unit = c.execute("SELECT u.*, p.handover FROM units u JOIN projects p ON p.id=u.project_id WHERE u.id=?", (q["unit_id"],)).fetchone()
    if unit["status"] != "a" or unit["retained"]:
        raise HTTPException(409, "الوحدة لم تعد متاحة")
    res = create_booking(c, unit, q["customer_name"], q["phone"], q["plan"], q.get("lead_id"), None, q["price"], q.get("email"))
    c.execute("UPDATE quotes SET status='converted', booking_id=? WHERE id=?", (res["booking_id"], qid))
    audit(c, "تحويل عرض سعر إلى حجز", f"{q['number']} ⟵ حجز {res['booking_id']} بسعر {q['price']:,.0f} ر.ع")
    c.commit()
    return {**res, "quote": q["number"]}


@router.post("/api/quotes/{qid}/cancel")
def quote_cancel(qid: int, u=Depends(act_as("book"))):
    c = db()
    q = quote_row(c, qid)
    if q["status"] not in ("issued", "expired"):
        raise HTTPException(409, "العرض غير قابل للإلغاء")
    c.execute("UPDATE quotes SET status='cancelled' WHERE id=?", (qid,))
    audit(c, "إلغاء عرض سعر", q["number"])
    c.commit()
    return {"ok": True}


# ---------------------------------------------------------------- customer: my documents index (portal)
@router.get("/api/portal/docs")
def portal_docs(u=Depends(need("portal"))):
    c = db()
    out = {"contracts": [], "invoices": [], "receipts": []}
    for b in c.execute("SELECT id FROM bookings WHERE customer_id=? AND status!='cancelled'", (u["customer_id"],)):
        k = c.execute("SELECT number, customer_signed_at FROM sale_contracts WHERE booking_id=?", (b["id"],)).fetchone()
        if k:
            out["contracts"].append({"booking_id": b["id"], "number": k["number"], "signed": bool(k["customer_signed_at"]), "pdf": f"/api/portal/docs/contract/{b['id']}.pdf"})
        for pm in c.execute("""SELECT pm.id, pm.receipt, pm.amount, pm.at, i.label FROM payments pm JOIN installments i ON i.id=pm.installment_id WHERE i.booking_id=? ORDER BY pm.id DESC""", (b["id"],)):
            out["receipts"].append({**dict(pm), "pdf": f"/api/portal/docs/receipt/{pm['id']}.pdf"})
    for inv in c.execute("SELECT id, number, total, issued, note FROM invoices WHERE customer_id=? ORDER BY id DESC LIMIT 50", (u["customer_id"],)):
        out["invoices"].append({**dict(inv), "pdf": f"/api/portal/docs/invoice/{inv['id']}.pdf"})
    return out


__all__ = ["router", "create_booking", "brand", "render", "audit_insert", "setting_f", "RedirectResponse", "A"]
