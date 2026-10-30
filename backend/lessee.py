"""Mabaniq 0.28.0 — the tenant's portal (design §6): a login linked to ONE tenant file sees that tenant's leases, dues, receipts, cheques, notices, statement and
maintenance requests, and files a maintenance request. Nothing else.

Ownership is decided in one place: every query below is bound to `users.lessee_id` (never to an id the client sends), and an id that is not theirs answers 404 — the same answer
as an id that does not exist, so a tenant cannot learn that another tenant's lease exists. Draft leases are the office's, not shown. The other tenants, the office's notes
and ratings, the blacklist and the lease event log never leave this file (the owner appears only as the party printed on the tenant's own lease PDF).
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .leasing import EPS, LEASE_STATUS, METHOD_LABEL, lease_detail, r3, tenant_statement
from .leasing_mgmt import MAINT_LABEL, PRIORITY_DAYS
from .modules import one

router = APIRouter()
CATEGORIES = "^(سباكة|كهرباء|تكييف|نظافة وأمن|مرافق ومصاعد|ملاحظة في العين المؤجرة|أخرى)$"


def _tid(u: dict) -> int:
    tid = u.get("lessee_id")
    if not tid:
        raise HTTPException(404, "حسابك غير مرتبط بملف مستأجر — راجع إدارة العقارات")
    return int(tid)


def _lease(c, u: dict, lid: int) -> dict:
    return dict(one(c, "SELECT * FROM leases WHERE id=? AND tenant_id=? AND status<>'draft'", (lid, _tid(u)), "العقد غير موجود"))


def _own_leases(c, u: dict) -> list[dict]:
    return rows(c.execute("""SELECT l.id, l.number, l.status, l.start, l."end", l.annual_rent, l.frequency, l.unit_id, un.code unit, un.type unit_type, p.name project
                             FROM leases l JOIN units un ON un.id=l.unit_id JOIN projects p ON p.id=un.project_id WHERE l.tenant_id=? AND l.status<>'draft' ORDER BY l.start DESC""", (_tid(u),)))


# ----------------------------------------------------------------------------------------------------- me and consent
@router.get("/api/lessee/me")
def api_me(u=Depends(need("lessee"))):
    from .app import PRIVACY_NOTICE
    c = db()
    t = one(c, "SELECT name, phone, email, address, consent_at, consent_version FROM tenants_l WHERE id=?", (_tid(u),), "الملف غير موجود")
    st = tenant_statement(c, _tid(u), drafts=False)
    late = c.execute("""SELECT COALESCE(SUM(d.amount-d.paid),0) FROM rent_dues d JOIN leases l ON l.id=d.lease_id WHERE l.tenant_id=? AND l.status<>'draft' AND d.due<? AND d.amount-d.paid>?
                        AND COALESCE(d.kind,'rent')<>'deposit'""", (_tid(u), today().isoformat(), EPS)).fetchone()[0]
    return {"name": t["name"], "phone": t["phone"], "email": t["email"], "address": t["address"], "leases": len(st["leases"]), "balance": st["balance"], "arrears": r3(late),
            "consent_at": t["consent_at"], "consent_required": PRIVACY_NOTICE["version"] if t["consent_version"] != PRIVACY_NOTICE["version"] else None}


class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[0-9.]{1,10}$")
    accept: bool


@router.post("/api/lessee/consent")
def api_consent(b: ConsentIn, u=Depends(act_as("lessee"))):
    """The tenant acknowledges the privacy notice themself (not the office on their behalf)."""
    from .app import PRIVACY_NOTICE
    if not b.accept:
        raise HTTPException(400, "يلزم الإقرار بقراءة إشعار الخصوصية والموافقة عليه")
    if b.version != PRIVACY_NOTICE["version"]:
        raise HTTPException(409, "إصدار الإشعار تغيّر — أعد قراءته")
    c = db()
    c.execute("UPDATE tenants_l SET consent_at=?, consent_version=? WHERE id=?", (dt.datetime.now().isoformat(timespec="seconds"), b.version, _tid(u)))
    audit(c, "موافقة مستأجر على إشعار الخصوصية", f"مستأجر {_tid(u)} · الإصدار {b.version}", u["name"] + " (مستأجر)")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- leases
@router.get("/api/lessee/leases")
def api_leases(u=Depends(need("lessee"))):
    c = db()
    t = today().isoformat()
    out = _own_leases(c, u)
    for x in out:
        x["status_label"] = LEASE_STATUS.get(x["status"], x["status"])
        x["arrears"] = r3(c.execute("""SELECT COALESCE(SUM(amount-paid),0) FROM rent_dues WHERE lease_id=? AND due<? AND amount-paid>? AND COALESCE(kind,'rent')<>'deposit'""", (x["id"], t, EPS)).fetchone()[0])
        nd = c.execute("""SELECT due, amount-paid AS left FROM rent_dues WHERE lease_id=? AND amount-paid>? AND COALESCE(kind,'rent')<>'deposit' ORDER BY due LIMIT 1""", (x["id"], EPS)).fetchone()
        x["next_due"] = {"due": nd["due"], "amount": r3(nd["left"])} if nd else None
    return out


@router.get("/api/lessee/leases/{lid}")
def api_lease(lid: int, u=Depends(need("lessee"))):
    c = db()
    _lease(c, u, lid)
    d = lease_detail(c, lid)
    receipts = {}
    reversed_ids = {p["reverses_id"] for p in d["payments"] if p["reverses_id"]}
    for p in d["payments"]:
        if p["receipt_no"] and not p["reverses_id"] and p["id"] not in reversed_ids and p["receipt_no"] not in receipts:   # a reversed payment has no receipt to download
            receipts[p["receipt_no"]] = p["id"]
    return {"id": d["id"], "number": d["number"], "status": d["status"], "status_label": d["status_label"], "start": d["start"], "end": d["end"], "annual_rent": d["annual_rent"],
            "frequency": d["frequency"], "deposit": d["deposit"], "deposit_state": d["deposit_state"], "unit": d["unit"], "unit_type": d["unit_type"], "area": d["area"],
            "project": d["project"], "location": d["location"], "terms": d["terms"], "totals": d["totals"],
            "dues": [{"id": x["id"], "due": x["due"], "label": x["label"], "kind": x["kind"] or "rent", "amount": x["amount"], "paid": x["paid"], "balance": x["balance"], "state": x["state"],
                      "cheque": ({"number": x["cheque"]["number"], "bank": x["cheque"]["bank"], "due_date": x["cheque"]["due_date"], "status": x["cheque"]["status"]} if x["cheque"] else None)} for x in d["dues"]],
            "payments": [{"id": p["id"], "paid_on": p["paid_on"], "amount": p["amount"], "method": METHOD_LABEL.get(p["method"], "غير موثَّقة"), "receipt_no": p["receipt_no"],
                          "pdf": f"/api/lessee/docs/rent_receipt/{receipts[p['receipt_no']]}.pdf" if p["receipt_no"] in receipts and receipts[p["receipt_no"]] == p["id"] else None} for p in d["payments"]],
            "cheques": [{"id": q["id"], "number": q["number"], "bank": q["bank"], "amount": q["amount"], "due_date": q["due_date"], "status": q["status"],
                         "pdf": f"/api/lessee/docs/cheque_receipt/{q['id']}.pdf" if q["receipt_no"] else None} for q in d["cheques"] if (q["direction"] or "in") == "in"],
            "pdf": f"/api/lessee/docs/lease/{lid}.pdf"}


@router.get("/api/lessee/statement")
def api_statement(u=Depends(need("lessee"))):
    return tenant_statement(db(), _tid(u), drafts=False)


@router.get("/api/lessee/notices")
def api_notices(u=Depends(need("lessee"))):
    """Arrears notices that the office has actually delivered (a notice not yet sent is the office's draft)."""
    c = db()
    out = rows(c.execute("""SELECT n.id, n.number, n.kind, n.issued, n.cure_by, n.amount, n.sent_at, l.number lease_no FROM arrears_notices n JOIN leases l ON l.id=n.lease_id
                            WHERE l.tenant_id=? AND l.status<>'draft' AND n.sent_at IS NOT NULL ORDER BY n.id DESC""", (_tid(u),)))
    for x in out:
        x["kind_label"] = {"reminder": "تذكير", "formal": "إنذار رسمي", "final": "إنذار نهائي"}.get(x["kind"], x["kind"])
        x["pdf"] = f"/api/lessee/docs/arrears_notice/{x['id']}.pdf"
    return out


# ----------------------------------------------------------------------------------------------------- documents
def _owned_doc(c, u: dict, kind: str, ref_id: int) -> None:
    """The one place that decides whether a document is this tenant's — 404 for anything else, whether it exists or not."""
    tid = _tid(u)
    if kind == "lease":
        ok = c.execute("SELECT 1 FROM leases WHERE id=? AND tenant_id=? AND status<>'draft'", (ref_id, tid)).fetchone()
    elif kind == "rent_receipt":
        ok = c.execute("""SELECT 1 FROM rent_payments p JOIN leases l ON l.id=p.lease_id WHERE p.id=? AND l.tenant_id=? AND l.status<>'draft' AND p.receipt_no IS NOT NULL
                          AND NOT EXISTS (SELECT 1 FROM rent_payments r2 WHERE r2.reverses_id=p.id)""", (ref_id, tid)).fetchone()
    elif kind == "cheque_receipt":
        ok = c.execute("SELECT 1 FROM cheques q JOIN leases l ON l.id=q.lease_id WHERE q.id=? AND l.tenant_id=? AND l.status<>'draft' AND COALESCE(q.direction,'in')='in'", (ref_id, tid)).fetchone()
    elif kind == "arrears_notice":
        ok = c.execute("SELECT 1 FROM arrears_notices n JOIN leases l ON l.id=n.lease_id WHERE n.id=? AND l.tenant_id=? AND n.sent_at IS NOT NULL", (ref_id, tid)).fetchone()
    else:
        ok = None
    if not ok:
        raise HTTPException(404, "المستند غير موجود")


@router.get("/api/lessee/docs/{kind}/{ref_id}.pdf")
def api_doc(kind: str, ref_id: int, request: Request, download: int = 0, u=Depends(need("lessee"))):
    from .paperwork import _pdf_response, render
    c = db()
    _owned_doc(c, u, kind, ref_id)
    pdf, name, d = render(c, request, kind, ref_id, u["name"])
    audit(c, "تنزيل مستند (بوابة المستأجر)", f"{kind} {d.get('number') or d.get('receipt') or d.get('receipt_no')}", u["name"] + " (مستأجر)")
    c.commit()
    return _pdf_response(pdf, name, bool(download))


# ----------------------------------------------------------------------------------------------------- maintenance
class MaintIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_id: int
    category: str = Field(pattern=CATEGORIES)
    description: str = Field(min_length=5, max_length=600)
    urgent: bool = False


@router.get("/api/lessee/maintenance")
def api_maint(u=Depends(need("lessee"))):
    c = db()
    out = rows(c.execute("""SELECT m.id, m.category, m.description, m.priority, m.status, m.created, m.updated, m.sla_due, l.number lease_no, un.code unit
                            FROM maint_requests m JOIN leases l ON l.id=m.lease_id JOIN units un ON un.id=m.unit_id WHERE l.tenant_id=? AND l.status<>'draft' AND m.source='tenant' ORDER BY m.id DESC LIMIT 100""", (_tid(u),)))   # what the tenant filed, not the office's own notes
    for x in out:
        x["status_label"] = MAINT_LABEL.get(x["status"], x["status"])
    return out


@router.post("/api/lessee/maintenance")
def api_maint_add(b: MaintIn, u=Depends(act_as("lessee"))):
    c = db()
    l = _lease(c, u, b.lease_id)
    t = today().isoformat()
    if l["status"] != "active" or not (l["start"] <= t <= l["end"]):
        raise HTTPException(409, "تُرفع طلبات الصيانة على عقد ساري")
    open_n = c.execute("SELECT COUNT(*) FROM maint_requests WHERE lease_id=? AND source='tenant' AND status IN ('new','triaged')", (l["id"],)).fetchone()[0]
    if open_n >= 5:
        raise HTTPException(409, "لديك 5 طلبات صيانة بانتظار المكتب — انتظر معالجتها قبل رفع المزيد")
    prio = "urgent" if b.urgent else "normal"
    sla = today() + dt.timedelta(days=PRIORITY_DAYS[prio])
    mid = c.execute("""INSERT INTO maint_requests(unit_id,lease_id,source,requester,category,description,priority,status,created,updated,sla_due,created_by)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (l["unit_id"], l["id"], "tenant", u["name"], b.category, b.description, prio, "new", now_s(), now_s(), sla.isoformat(), u["name"] + " (مستأجر)")).lastrowid
    audit(c, "طلب صيانة من مستأجر", f"عقد {l['number']} · {b.category}" + (" · عاجل" if b.urgent else ""), u["name"] + " (مستأجر)")
    c.commit()
    return {"id": mid, "sla_due": sla.isoformat()}


# ----------------------------------------------------------------------------------------------------- the office creates and resets the login
@router.get("/api/lea/tenants/{tid}/account")
def api_account(tid: int, _=Depends(need("leasing"))):
    c = db()
    one(c, "SELECT id FROM tenants_l WHERE id=?", (tid,), "المستأجر غير موجود")
    a = c.execute("SELECT username, active FROM users WHERE lessee_id=?", (tid,)).fetchone()
    return {"exists": bool(a), "username": a["username"] if a else None, "active": bool(a["active"]) if a else None}


@router.post("/api/lea/tenants/{tid}/account")
def api_account_create(tid: int, u=Depends(act_as("leasing"))):
    """A portal login (role `lessee`) for the tenant file. The temporary password is shown once; the tenant must change it at first sign-in."""
    from . import auth as A
    c = db()
    t = one(c, "SELECT * FROM tenants_l WHERE id=?", (tid,), "المستأجر غير موجود")
    if c.execute("SELECT 1 FROM users WHERE lessee_id=?", (tid,)).fetchone():
        raise HTTPException(409, "للمستأجر حساب بالفعل")
    username = f"ten{tid:04d}"
    if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise HTTPException(409, "اسم المستخدم المقترح مستخدم")
    email = None   # the address on the tenant file was typed by a clerk and is unverified: it must not become a sign-in identity (Google auto-link) — the tenant adds their own later
    temp = A.temp_password()
    c.execute("INSERT INTO users(username,name,role,pw,must_change,email,lessee_id) VALUES(?,?,?,?,1,?,?)", (username, t["name"], "lessee", A.hash_pw(temp), email, tid))
    audit(c, "حساب مستأجر جديد", f"{username} ↔ مستأجر {tid}")
    c.commit()
    return {"username": username, "temporary_password": temp, "note": "تُعرض مرة واحدة فقط، ويُلزم المستأجر بتغييرها عند أول دخول."}


@router.post("/api/lea/tenants/{tid}/account/reset")
def api_account_reset(tid: int, u=Depends(act_as("leasing"))):
    from . import auth as A
    c = db()
    one(c, "SELECT id FROM tenants_l WHERE id=?", (tid,), "المستأجر غير موجود")
    a = one(c, "SELECT id, username, role FROM users WHERE lessee_id=?", (tid,), "لا حساب لهذا المستأجر")
    if a["role"] != "lessee":
        raise HTTPException(403, "ليس حساب مستأجر")
    temp = A.temp_password()
    c.execute("UPDATE users SET pw=?, must_change=1 WHERE id=?", (A.hash_pw(temp), a["id"]))
    A.kill_sessions(c, a["id"])
    audit(c, "إعادة تعيين كلمة مرور مستأجر", f"{a['username']} ↔ مستأجر {tid}")
    c.commit()
    return {"username": a["username"], "temporary_password": temp}


__all__ = ["router"]
