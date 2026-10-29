"""Mabaniq 0.22.0 — leasing management (design §3.1 «الصيانة والمصاريف» and «المالك الخارجي والمدير العقاري», phase 2b, second half).

Vendors, maintenance requests and their work orders, property expenses (with tenant charge-back), the owner statements with the management commission, and
the scoped API an external property manager uses. The statements follow one formula, written once (`statement_calc`):

    net transferred to the owner = collected − expenses charged to the owner − management commission

* collected  = every rent-ledger movement of the owner's units dated in the month (negative rows — bounced cheques, refunds — included), deposits excluded
  (a deposit is the tenant's money, not the owner's income); a tenant charge-back (a «service» due) is collected like rent.
* expenses   = the owner's property expenses of the month marked «charged to the owner».
* commission = the owner's percentage × the month's collections (basis «collected») or × the month's rent dues (basis «invoiced»).
An issued statement is final; a later change in the same month (a cheque that bounced afterwards) becomes an *adjustment* statement for the difference.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import pii
from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .leasing import EPS, METHOD_LABEL, PayIn, apply_payment, event, lease_detail, next_no, r3
from .leasing_ops import need_approve
from .modules import one

router = APIRouter()

PRIORITY_DAYS = {"urgent": 1, "high": 3, "normal": 7, "low": 14}
PRIORITY_LABEL = {"urgent": "عاجل", "high": "مرتفع", "normal": "عادي", "low": "منخفض"}
MAINT_LABEL = {"new": "جديد", "triaged": "مُصنَّف", "assigned": "أُسند", "in_progress": "قيد التنفيذ", "done": "أُنجز", "closed": "مغلق", "rejected": "مرفوض"}
MAINT_FLOW = {"new": ("triaged", "assigned", "rejected"), "triaged": ("assigned", "rejected"), "assigned": ("in_progress", "rejected"), "in_progress": ("done",), "done": ("closed",)}
CHARGE_LABEL = {"owner": "على المالك", "company": "على الشركة", "tenant": "على المستأجر (يُسترد منه)"}


# ----------------------------------------------------------------------------------------------------- vendors
class VendorIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    cr_number: str = Field(default="", max_length=30)
    phone: str = Field(default="", max_length=30, pattern=r"^[0-9+ ()-]*$")
    email: str = Field(default="", max_length=120)
    trade: str = Field(default="", max_length=60)
    iban: str = Field(default="", max_length=40)


@router.get("/api/lea/vendors")
def api_vendors(_=Depends(need("leasing"))):
    out = rows(db().execute("SELECT * FROM vendors WHERE COALESCE(active,1)=1 ORDER BY name"))
    for x in out:
        x["iban"] = pii.mask(x["iban"])
    return out


@router.post("/api/lea/vendors")
def api_vendor_add(b: VendorIn, _=Depends(act_as("leasing"))):
    c = db()
    vid = c.execute("INSERT INTO vendors(name,cr_number,phone,email,trade,iban) VALUES(?,?,?,?,?,?)", (b.name, b.cr_number, b.phone, b.email, b.trade, pii.enc(b.iban))).lastrowid
    audit(c, "إضافة مورّد", b.name)
    c.commit()
    return {"id": vid}


# ----------------------------------------------------------------------------------------------------- expenses
def add_expense(c, *, unit_id: int | None, project_id: int | None, owner_id: int | None, category: str, amount: float, spent_on: dt.date, vendor_id: int | None,
                order_id: int | None, charge_owner: bool, charge_tenant: bool, description: str, doc_ref: str, by: str) -> int:
    if unit_id:
        u = one(c, "SELECT project_id, owner_id FROM units WHERE id=?", (unit_id,), "الوحدة غير موجودة")
        project_id, owner_id = project_id or u["project_id"], owner_id or u["owner_id"]
    if owner_id:
        one(c, "SELECT 1 FROM owners WHERE id=?", (owner_id,), "المالك غير موجود")
    eid = c.execute("""INSERT INTO property_expenses(project_id,unit_id,owner_id,category,amount,spent_on,vendor_id,order_id,charge_owner,charge_tenant,description,doc_ref,created_by)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (project_id, unit_id, owner_id, category, r3(amount), spent_on.isoformat(), vendor_id, order_id, int(charge_owner),
                                                              int(charge_tenant), description, doc_ref, by)).lastrowid
    audit(c, "مصروف عقار", f"{category} · {r3(amount):,.3f} ر.ع" + (" · على المالك" if charge_owner else " · على الشركة"))
    return eid


class ExpenseIn(BaseModel):
    unit_id: int | None = None
    project_id: int | None = None
    owner_id: int | None = None
    category: str = Field(min_length=2, max_length=60)
    amount: float = Field(gt=0, le=10_000_000)
    spent_on: dt.date | None = None
    vendor_id: int | None = None
    charge_owner: bool = True
    description: str = Field(default="", max_length=300)
    doc_ref: str = Field(default="", max_length=80)


@router.post("/api/lea/expenses")
def api_expense_add(b: ExpenseIn, u=Depends(act_as("leasing"))):
    c = db()
    if not (b.unit_id or b.project_id or b.owner_id):
        raise HTTPException(400, "حدّد الوحدة أو المشروع أو المالك")
    if (b.spent_on or today()) > today():
        raise HTTPException(400, "تاريخ المصروف لا يكون في المستقبل")
    eid = add_expense(c, unit_id=b.unit_id, project_id=b.project_id, owner_id=b.owner_id, category=b.category, amount=b.amount, spent_on=b.spent_on or today(),
                      vendor_id=b.vendor_id, order_id=None, charge_owner=b.charge_owner, charge_tenant=False, description=b.description, doc_ref=b.doc_ref, by=u["name"])
    c.commit()
    return {"id": eid}


@router.get("/api/lea/expenses")
def api_expenses(owner_id: int | None = None, period: str = Query("", pattern=r"^(\d{4}-\d{2})?$"), _=Depends(need("leasing"))):
    sql = """SELECT e.*, un.code unit, o.name owner, v.name vendor FROM property_expenses e LEFT JOIN units un ON un.id=e.unit_id LEFT JOIN owners o ON o.id=e.owner_id
             LEFT JOIN vendors v ON v.id=e.vendor_id WHERE 1=1"""
    args: list = []
    if owner_id:
        sql += " AND e.owner_id=?"
        args.append(owner_id)
    if period:
        sql += " AND e.spent_on LIKE ?"
        args.append(period + "%")
    return rows(db().execute(sql + " ORDER BY e.spent_on DESC, e.id DESC LIMIT 300", args))


# ----------------------------------------------------------------------------------------------------- maintenance
class MaintIn(BaseModel):
    unit_id: int
    category: str = Field(min_length=2, max_length=60)
    description: str = Field(min_length=5, max_length=600)
    priority: str = Field(default="normal", pattern=r"^(urgent|high|normal|low)$")
    source: str = Field(default="staff", pattern=r"^(staff|tenant)$")
    requester: str = Field(default="", max_length=120)


def _active_lease(c, unit_id: int, on: str | None = None):
    on = on or today().isoformat()
    return c.execute("""SELECT id FROM leases WHERE unit_id=? AND status='active' AND start<=? AND "end">=? ORDER BY start DESC LIMIT 1""", (unit_id, on, on)).fetchone()


@router.post("/api/lea/maint")
def api_maint_add(b: MaintIn, u=Depends(act_as("leasing"))):
    c = db()
    one(c, "SELECT 1 FROM units WHERE id=? AND retained=1", (b.unit_id,), "الوحدة ليست ضمن محفظة التأجير")
    lease = _active_lease(c, b.unit_id)
    sla = today() + dt.timedelta(days=PRIORITY_DAYS[b.priority])
    mid = c.execute("""INSERT INTO maint_requests(unit_id,lease_id,source,requester,category,description,priority,status,created,updated,sla_due,created_by)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (b.unit_id, lease["id"] if lease else None, b.source, b.requester or u["name"], b.category, b.description, b.priority,
                                                             "new", now_s(), now_s(), sla.isoformat(), u["name"])).lastrowid
    audit(c, "طلب صيانة", f"وحدة {b.unit_id} · {b.category} · {PRIORITY_LABEL[b.priority]}")
    c.commit()
    return {"id": mid, "sla_due": sla.isoformat()}


def _maint_out(c, m) -> dict:
    x = dict(m)
    x["status_label"] = MAINT_LABEL.get(x["status"], x["status"])
    x["priority_label"] = PRIORITY_LABEL.get(x["priority"], x["priority"])
    x["late"] = bool(x["sla_due"] and x["sla_due"] < today().isoformat() and x["status"] not in ("done", "closed", "rejected"))
    x["orders"] = rows(c.execute("""SELECT o.*, v.name vendor FROM maint_orders o LEFT JOIN vendors v ON v.id=o.vendor_id WHERE o.request_id=? ORDER BY o.id""", (m["id"],)))
    for o in x["orders"]:
        o["charge_label"] = CHARGE_LABEL.get(o["charge_to"], o["charge_to"])
    return x


@router.get("/api/lea/maint")
def api_maint(status: str | None = None, unit_id: int | None = None, _=Depends(need("leasing"))):
    c = db()
    sql = "SELECT m.*, u.code unit FROM maint_requests m JOIN units u ON u.id=m.unit_id WHERE 1=1"
    args: list = []
    if status:
        sql += " AND m.status=?"
        args.append(status)
    if unit_id:
        sql += " AND m.unit_id=?"
        args.append(unit_id)
    return [_maint_out(c, m) for m in c.execute(sql + " ORDER BY m.id DESC LIMIT 300", args).fetchall()]


class MaintStatus(BaseModel):
    status: str = Field(pattern=r"^(triaged|in_progress|done|closed|rejected)$")
    note: str = Field(default="", max_length=300)


@router.post("/api/lea/maint/{mid}/status")
def api_maint_status(mid: int, b: MaintStatus, u=Depends(act_as("leasing"))):
    c = db()
    m = one(c, "SELECT * FROM maint_requests WHERE id=?", (mid,), "الطلب غير موجود")
    if b.status not in MAINT_FLOW.get(m["status"], ()):
        raise HTTPException(409, f"لا يُنقل الطلب من «{MAINT_LABEL[m['status']]}» إلى «{MAINT_LABEL[b.status]}»")
    if b.status == "rejected" and len(b.note.strip()) < 5:
        raise HTTPException(400, "اذكر سبب الرفض")
    if b.status == "done" and not c.execute("SELECT 1 FROM maint_orders WHERE request_id=? AND done_at IS NOT NULL", (mid,)).fetchone():
        raise HTTPException(409, "أنجز أمر العمل أولًا (يسجّل التكلفة)")
    c.execute("UPDATE maint_requests SET status=?, updated=?, closed_at=? WHERE id=?", (b.status, now_s(), now_s() if b.status in ("closed", "rejected") else None, mid))
    audit(c, "حالة طلب صيانة", f"{mid} ⟵ {MAINT_LABEL[b.status]}" + (f" · {b.note}" if b.note else ""))
    c.commit()
    return {"ok": True}


class OrderIn(BaseModel):
    vendor_id: int | None = None
    scheduled: dt.date | None = None
    cost: float = Field(default=0, ge=0, le=1_000_000)
    charge_to: str = Field(default="owner", pattern=r"^(owner|company|tenant)$")
    basis: str = Field(default="", max_length=300)  # for a tenant charge: the clause / finding that makes the tenant liable


@router.post("/api/lea/maint/{mid}/orders")
def api_order_add(mid: int, b: OrderIn, u=Depends(act_as("leasing"))):
    c = db()
    m = one(c, "SELECT * FROM maint_requests WHERE id=?", (mid,), "الطلب غير موجود")
    if m["status"] in ("done", "closed", "rejected"):
        raise HTTPException(409, "الطلب مغلق")
    if b.vendor_id:
        one(c, "SELECT 1 FROM vendors WHERE id=?", (b.vendor_id,), "المورّد غير موجود")
    if b.charge_to == "tenant" and len(b.basis.strip()) < 5:
        raise HTTPException(400, "التحميل على المستأجر يحتاج سندًا من العقد أو محضر المعاينة")
    oid = c.execute("INSERT INTO maint_orders(request_id,vendor_id,scheduled,cost,charge_to,basis,created_by) VALUES(?,?,?,?,?,?,?)",
                    (mid, b.vendor_id, b.scheduled.isoformat() if b.scheduled else None, r3(b.cost), b.charge_to, b.basis, u["name"])).lastrowid
    if m["status"] in ("new", "triaged"):
        c.execute("UPDATE maint_requests SET status='assigned', updated=? WHERE id=?", (now_s(), mid))
    audit(c, "أمر عمل صيانة", f"طلب {mid} · {CHARGE_LABEL[b.charge_to]}")
    c.commit()
    return {"id": oid}


class OrderDone(BaseModel):
    cost: float | None = Field(default=None, gt=0, le=1_000_000)
    done_at: dt.date | None = None
    doc_ref: str = Field(default="", max_length=80)


@router.post("/api/lea/maint/orders/{oid}/done")
def api_order_done(oid: int, b: OrderDone, u=Depends(act_as("leasing"))):
    """Completing an order books the expense (charged to the owner unless it is the company's) and, for a tenant charge-back, bills the tenant a «service» due."""
    c = db()
    o = one(c, "SELECT * FROM maint_orders WHERE id=?", (oid,), "أمر العمل غير موجود")
    if o["done_at"]:
        raise HTTPException(409, "أُنجز أمر العمل سابقًا")
    m = one(c, "SELECT * FROM maint_requests WHERE id=?", (o["request_id"],))
    cost = r3(b.cost if b.cost is not None else o["cost"])
    if cost <= 0:
        raise HTTPException(400, "حدّد تكلفة الأمر")
    done = b.done_at or today()
    if done > today():
        raise HTTPException(400, "تاريخ الإنجاز لا يكون في المستقبل")
    due_id = None
    if o["charge_to"] == "tenant":
        need_approve(u)
        lease = _active_lease(c, m["unit_id"], done.isoformat()) or (c.execute("SELECT id FROM leases WHERE id=?", (m["lease_id"],)).fetchone() if m["lease_id"] else None)
        if not lease:
            raise HTTPException(409, "لا عقد قائم على الوحدة لتحميل المستأجر")
        due_id = c.execute("INSERT INTO rent_dues(lease_id,due,amount,kind,label) VALUES(?,?,?,?,?)",
                           (lease["id"], done.isoformat(), cost, "service", f"تحميل مستأجر — {m['category']} (طلب {m['id']})")).lastrowid
        event(c, lease["id"], "charge_tenant", f"{m['category']} · {cost:,.3f} ر.ع · {o['basis']}", u["name"])
    eid = add_expense(c, unit_id=m["unit_id"], project_id=None, owner_id=None, category=m["category"], amount=cost, spent_on=done, vendor_id=o["vendor_id"], order_id=oid,
                      charge_owner=o["charge_to"] != "company", charge_tenant=o["charge_to"] == "tenant", description=m["description"][:300], doc_ref=b.doc_ref, by=u["name"])
    c.execute("UPDATE maint_orders SET cost=?, done_at=?, expense_id=?, tenant_due_id=?, doc_ref=? WHERE id=?", (cost, done.isoformat(), eid, due_id, b.doc_ref, oid))
    c.execute("UPDATE maint_requests SET status='done', updated=? WHERE id=?", (now_s(), m["id"]))
    c.commit()
    return {"expense_id": eid, "tenant_due_id": due_id, "cost": cost}


# ----------------------------------------------------------------------------------------------------- owner statements
PERIOD = r"^\d{4}-(0[1-9]|1[0-2])$"


def statement_calc(c, owner_id: int, period: str) -> dict:
    o = one(c, "SELECT * FROM owners WHERE id=?", (owner_id,), "المالك غير موجود")
    pay = rows(c.execute("""SELECT p.amount, p.paid_on, u.code unit, t.name tenant, COALESCE(d.kind,'rent') kind FROM rent_payments p JOIN rent_dues d ON d.id=p.due_id
                            JOIN leases l ON l.id=p.lease_id JOIN units u ON u.id=l.unit_id JOIN tenants_l t ON t.id=l.tenant_id
                            WHERE u.owner_id=? AND p.paid_on LIKE ? AND COALESCE(d.kind,'rent')<>'deposit' ORDER BY u.code, p.paid_on""", (owner_id, period + "%")))
    collected = r3(sum(x["amount"] for x in pay))
    per_unit: dict = {}
    for x in pay:
        k = per_unit.setdefault(x["unit"], {"unit": x["unit"], "tenant": x["tenant"], "collected": 0.0})
        k["collected"] = r3(k["collected"] + x["amount"])
    invoiced = r3(c.execute("""SELECT COALESCE(SUM(d.amount),0) FROM rent_dues d JOIN leases l ON l.id=d.lease_id JOIN units u ON u.id=l.unit_id
                               WHERE u.owner_id=? AND d.due LIKE ? AND COALESCE(d.kind,'rent')='rent'""", (owner_id, period + "%")).fetchone()[0])
    exp = rows(c.execute("""SELECT e.id, e.category, e.amount, e.spent_on, e.description, u.code unit FROM property_expenses e LEFT JOIN units u ON u.id=e.unit_id
                            WHERE e.owner_id=? AND e.charge_owner=1 AND e.status='posted' AND e.spent_on LIKE ? ORDER BY e.spent_on""", (owner_id, period + "%")))
    expenses = r3(sum(e["amount"] for e in exp))
    base = collected if (o["mgmt_basis"] or "collected") == "collected" else invoiced
    commission = r3(max(base, 0) * (o["mgmt_fee_pct"] or 0) / 100)
    return {"owner": {"id": o["id"], "name": o["name"], "kind": o["kind"], "pct": o["mgmt_fee_pct"] or 0, "basis": o["mgmt_basis"] or "collected"}, "period": period,
            "collected": collected, "invoiced": invoiced, "expenses": expenses, "commission": commission, "net": r3(collected - expenses - commission),
            "units": sorted(per_unit.values(), key=lambda x: x["unit"]), "expense_rows": exp, "commission_base": r3(base)}


def _check_period(period: str) -> None:
    if not re.match(PERIOD, period):
        raise HTTPException(400, "الفترة بصيغة YYYY-MM")
    if period > today().isoformat()[:7]:
        raise HTTPException(400, "لا كشف لشهر لم يبدأ")


@router.get("/api/lea/owners/{oid}/statement")
def api_statement_preview(oid: int, period: str = Query(pattern=PERIOD), _=Depends(need("leasing"))):
    _check_period(period)
    c = db()
    out = statement_calc(c, oid, period)
    out["issued"] = rows(c.execute("SELECT id, number, seq, kind, collected, expenses, commission, net, status, issued_at FROM owner_statements WHERE owner_id=? AND period=? ORDER BY seq", (oid, period)))
    return out


class StatementIn(BaseModel):
    period: str = Field(pattern=PERIOD)


@router.post("/api/lea/owners/{oid}/statements")
def api_statement_issue(oid: int, b: StatementIn, u=Depends(act_as("leasing_approve"))):
    """Freeze the month's statement. If one was already issued for the month, only the *difference* since then is issued, as an adjustment statement."""
    _check_period(b.period)
    c = db()
    cur = statement_calc(c, oid, b.period)
    prev = rows(c.execute("SELECT * FROM owner_statements WHERE owner_id=? AND period=? ORDER BY seq", (oid, b.period)))
    d = {k: cur[k] for k in ("collected", "expenses", "commission", "net")}
    if prev:
        for k in d:
            d[k] = r3(d[k] - sum(p[k] for p in prev))
        if all(abs(v) <= EPS for v in d.values()):
            raise HTTPException(409, "لا تغيّر منذ آخر كشف صادر لهذا الشهر")
    seq = (prev[-1]["seq"] + 1) if prev else 1
    y = b.period[:4]
    number = f"OS-{y}-{next_no(c, f'ostmt:{y}'):04d}"
    sid = c.execute("""INSERT INTO owner_statements(owner_id,period,seq,kind,number,collected,expenses,commission,net,status,issued_at,issued_by,detail) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (oid, b.period, seq, "adjustment" if prev else "statement", number, d["collected"], d["expenses"], d["commission"], d["net"], "issued", now_s(), u["name"],
                     json.dumps({k: cur[k] for k in ("units", "expense_rows", "commission_base", "invoiced")} | {"pct": cur["owner"]["pct"], "basis": cur["owner"]["basis"]}, ensure_ascii=False))).lastrowid
    audit(c, "كشف مالك", f"{number} · {cur['owner']['name']} · {b.period} · الصافي {d['net']:,.3f} ر.ع" + (" (تعديلي)" if prev else ""))
    c.commit()
    return {"id": sid, "number": number, "net": d["net"], "kind": "adjustment" if prev else "statement"}


@router.get("/api/lea/statements")
def api_statements(owner_id: int | None = None, _=Depends(need("leasing"))):
    sql = "SELECT s.*, o.name owner FROM owner_statements s JOIN owners o ON o.id=s.owner_id"
    return rows(db().execute(sql + (" WHERE s.owner_id=?" if owner_id else "") + " ORDER BY s.id DESC LIMIT 200", ((owner_id,) if owner_id else ())))


class TransferIn(BaseModel):
    on: dt.date | None = None
    ref: str = Field(min_length=2, max_length=80)


@router.post("/api/lea/statements/{sid}/transferred")
def api_statement_transferred(sid: int, b: TransferIn, u=Depends(act_as("leasing_approve"))):
    c = db()
    s = one(c, "SELECT * FROM owner_statements WHERE id=?", (sid,), "الكشف غير موجود")
    if s["status"] != "issued":
        raise HTTPException(409, "سُجّل تحويل هذا الكشف سابقًا")
    if s["net"] <= EPS:
        raise HTTPException(409, "لا صافٍ موجب للتحويل في هذا الكشف")
    c.execute("UPDATE owner_statements SET status='transferred', transferred_on=?, transfer_ref=? WHERE id=?", ((b.on or today()).isoformat(), b.ref, sid))
    audit(c, "تحويل صافي كشف مالك", f"{s['number']} · {s['net']:,.3f} ر.ع · {b.ref}")
    c.commit()
    return {"ok": True}


def statement_doc_row(c, sid: int) -> dict:
    s = dict(one(c, "SELECT * FROM owner_statements WHERE id=?", (sid,), "الكشف غير موجود"))
    s["owner"] = dict(one(c, "SELECT id, name, kind, mgmt_fee_pct, mgmt_basis FROM owners WHERE id=?", (s["owner_id"],)))
    s["detail"] = json.loads(s["detail"] or "{}")
    s["prior"] = rows(c.execute("SELECT number, kind, net FROM owner_statements WHERE owner_id=? AND period=? AND seq<? ORDER BY seq", (s["owner_id"], s["period"], s["seq"])))
    return s


# ----------------------------------------------------------------------------------------------------- scopes (who a property manager may see)
class ScopeIn(BaseModel):
    user_id: int
    project_id: int | None = None
    owner_id: int | None = None


@router.get("/api/lea/scopes")
def api_scopes(_=Depends(need("leasing_approve"))):
    return rows(db().execute("""SELECT s.id, s.user_id, us.name user, us.username, s.project_id, p.name project, s.owner_id, o.name owner FROM user_scopes s JOIN users us ON us.id=s.user_id
                                LEFT JOIN projects p ON p.id=s.project_id LEFT JOIN owners o ON o.id=s.owner_id ORDER BY s.user_id, s.id"""))


@router.post("/api/lea/scopes")
def api_scope_add(b: ScopeIn, u=Depends(act_as("leasing_approve"))):
    c = db()
    if b.project_id is None and b.owner_id is None:
        raise HTTPException(400, "حدّد مشروعًا أو مالكًا — النطاق المفتوح غير مسموح")
    mgr = one(c, "SELECT id, name, role FROM users WHERE id=?", (b.user_id,), "المستخدم غير موجود")
    if mgr["role"] != "property_manager":
        raise HTTPException(409, "النطاق لدور «مدير عقاري» فقط")
    if b.project_id is not None:
        one(c, "SELECT 1 FROM projects WHERE id=?", (b.project_id,), "المشروع غير موجود")
    if b.owner_id is not None:
        one(c, "SELECT 1 FROM owners WHERE id=?", (b.owner_id,), "المالك غير موجود")
    sid = c.execute("INSERT INTO user_scopes(user_id,project_id,owner_id,created_by) VALUES(?,?,?,?)", (b.user_id, b.project_id, b.owner_id, u["name"])).lastrowid
    audit(c, "نطاق مدير عقاري", f"{mgr['name']} · مشروع {b.project_id or '—'} · مالك {b.owner_id or '—'}")
    c.commit()
    return {"id": sid}


@router.delete("/api/lea/scopes/{sid}")
def api_scope_del(sid: int, u=Depends(act_as("leasing_approve"))):
    c = db()
    one(c, "SELECT 1 FROM user_scopes WHERE id=?", (sid,), "النطاق غير موجود")
    c.execute("DELETE FROM user_scopes WHERE id=?", (sid,))
    audit(c, "إلغاء نطاق مدير عقاري", f"نطاق {sid}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- the property manager's own API (/api/pm)
# One clause decides what a manager may see: a unit is in scope when SOME scope row of the user matches its project and its owner (an empty side matches all);
# a user without rows sees nothing. Out-of-scope ids answer 404, not 403 — their existence is not revealed.
PM_UNIT = ("EXISTS (SELECT 1 FROM user_scopes s WHERE s.user_id=? AND (s.project_id IS NOT NULL OR s.owner_id IS NOT NULL) "
           "AND (s.project_id IS NULL OR s.project_id=u.project_id) AND (s.owner_id IS NULL OR s.owner_id=u.owner_id))")


def _pm_lease(c, u: dict, lid: int):
    return one(c, f"SELECT l.* FROM leases l JOIN units u ON u.id=l.unit_id WHERE l.id=? AND l.status<>'draft' AND {PM_UNIT}", (lid, u["id"]), "العقد غير موجود")


@router.get("/api/pm/overview")
def api_pm_overview(u=Depends(need("leasing_pm"))):
    c = db()
    t = today().isoformat()
    units = c.execute(f"SELECT COUNT(*) FROM units u WHERE COALESCE(u.retained,0)=1 AND {PM_UNIT}", (u["id"],)).fetchone()[0]
    leased = c.execute(f"""SELECT COUNT(DISTINCT u.id) FROM units u JOIN leases l ON l.unit_id=u.id WHERE COALESCE(u.retained,0)=1 AND l.status='active' AND l.start<=? AND l."end">=? AND {PM_UNIT}""",
                       (t, t, u["id"])).fetchone()[0]
    arrears = r3(c.execute(f"""SELECT COALESCE(SUM(d.amount-d.paid),0) FROM rent_dues d JOIN leases l ON l.id=d.lease_id JOIN units u ON u.id=l.unit_id
                               WHERE d.due<? AND d.amount-d.paid>? AND COALESCE(d.kind,'rent')<>'deposit' AND l.status<>'draft' AND {PM_UNIT}""", (t, EPS, u["id"])).fetchone()[0])
    month = r3(c.execute(f"""SELECT COALESCE(SUM(p.amount),0) FROM rent_payments p JOIN leases l ON l.id=p.lease_id JOIN units u ON u.id=l.unit_id
                             WHERE p.paid_on LIKE ? AND {PM_UNIT}""", (t[:7] + "%", u["id"])).fetchone()[0])
    return {"units": units, "leased": leased, "vacant": units - leased, "arrears": arrears, "collected_month": month}


@router.get("/api/pm/leases")
def api_pm_leases(_u=Depends(need("leasing_pm"))):
    c = db()
    out = rows(c.execute(f"""SELECT l.id, l.number, l.status, l.start, l."end", u.code unit, t.name tenant, t.phone,
                             COALESCE((SELECT SUM(d.amount-d.paid) FROM rent_dues d WHERE d.lease_id=l.id AND d.due<? AND d.amount-d.paid>? AND COALESCE(d.kind,'rent')<>'deposit'),0) arrears
                             FROM leases l JOIN units u ON u.id=l.unit_id JOIN tenants_l t ON t.id=l.tenant_id WHERE l.status IN ('active','expired') AND {PM_UNIT}
                             ORDER BY u.code LIMIT 500""", (today().isoformat(), EPS, _u["id"])))
    for x in out:
        x["arrears"] = r3(x["arrears"])
    return out


@router.get("/api/pm/leases/{lid}")
def api_pm_lease(lid: int, u=Depends(need("leasing_pm"))):
    c = db()
    _pm_lease(c, u, lid)
    d = lease_detail(c, lid)
    t = d["tenant"]
    return {"id": d["id"], "number": d["number"], "unit": d["unit"], "status": d["status"], "start": d["start"], "end": d["end"], "tenant": {"name": t["name"], "phone": t["phone"]},
            "dues": [{k: x[k] for k in ("id", "due", "amount", "paid", "balance", "state", "label", "kind")} for x in d["dues"] if (x["kind"] or "rent") != "deposit"],
            "payments": [{k: p[k] for k in ("id", "amount", "paid_on", "method", "receipt_no")} for p in d["payments"]], "totals": d["totals"]}


class PmPay(PayIn):
    method: str = Field(default="cash", pattern=r"^(cash|transfer|card|other)$")  # cheques go through the office's cheque life cycle, not here


@router.post("/api/pm/payments")
def api_pm_pay(b: PmPay, u=Depends(act_as("leasing_pm"))):
    """A manager records money he actually received within his scope; the receipt number comes from the same sequence as the office's."""
    c = db()
    _pm_lease(c, u, b.lease_id)
    r = apply_payment(c, b.lease_id, b.amount, b.paid_on or today(), b.method, b.reference or None, u["name"], b.due_id, None, (b.note or "") + " · تحصيل المدير العقاري")
    c.commit()
    return {"receipt_no": r["receipt_no"], "amount": r["amount"], "method": METHOD_LABEL[b.method]}


__all__ = ["router", "statement_calc", "statement_doc_row", "add_expense"]
