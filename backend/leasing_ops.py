"""Mabaniq 0.22.0 — leasing operations (design docs/DESIGN-leasing-accounting-hr-modules.md §3.2, phase 2b, first half).

Renewal, early termination and eviction; the hand-over report with meter readings; deposit settlement by documented deductions only; numbered arrears
notices; payment plans; and the late-payment charity of leases that carry the clause. The second half (maintenance, expenses, owner statements, the
scoped property-manager API) lives in `leasing_mgmt.py`, the Excel/CSV import in `importer.py`.

Rules kept on purpose (same spirit as leasing.py):
* No interest, no fee, no penalty is ever computed as income. Late-payment money exists only when the lease carries the charity clause and goes to the
  charity ledger (`charity_dues`), never to revenue. A payment plan re-spreads the *same* outstanding amount — the total is checked to the baisa.
* Nothing is deleted from the money trail: dues that stop being owed are cut down to what was paid (the line stays, labelled),
  numbered notices / owner statements / hand-overs are never edited or removed.
* A deposit is returned, kept in part or fully used ONLY through deductions that each carry a label and a document reference; there is no discretionary
  forfeiture.
"""
from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .db import setting, setting_f
from .leasing import EPS, USES, LeaseNew, apply_payment, create_lease, event, lease_detail, next_no, r3, sign_lease
from .modules import one

router = APIRouter()

NOTICE_KINDS = {"reminder": "تذكير بالسداد", "formal": "إنذار رسمي", "final": "إنذار نهائي"}
NOTICE_CURE = {"reminder": 7, "formal": 15, "final": 15}
CLOSED = ("expired", "terminated", "evicted")


def need_approve(u: dict) -> None:
    if "leasing_approve" not in u["perms"]:
        raise HTTPException(403, "هذا الإجراء يحتاج صلاحية اعتماد الإيجارات (المدير)")


def _lease(c, lid: int):
    return one(c, "SELECT * FROM leases WHERE id=?", (lid,), "العقد غير موجود")


def arrears_of(c, lid: int) -> float:
    return r3(c.execute("SELECT COALESCE(SUM(amount-paid),0) FROM rent_dues WHERE lease_id=? AND due<? AND amount-paid>? AND COALESCE(kind,'rent')<>'deposit'",
                        (lid, today().isoformat(), EPS)).fetchone()[0])


# ----------------------------------------------------------------------------------------------------- renewal
class RenewIn(BaseModel):
    months: int = Field(ge=1, le=120)
    annual_rent: float | None = Field(default=None, gt=0, le=10_000_000)
    rents: list[float] | None = Field(default=None, max_length=10)
    escalation_pct: float = Field(default=0, ge=0, le=50)
    frequency: int | None = Field(default=None, ge=1, le=12)
    prep_free_days: int = Field(default=0, ge=0, le=180)
    charity_clause: bool | None = None
    override_reason: str = Field(default="", max_length=300)
    sign: bool = True


@router.post("/api/lea/leases/{lid}/renew")
def api_renew(lid: int, b: RenewIn, u=Depends(act_as("leasing"))):
    """A new lease that starts the day after the old one ends and continues it (`renewed_from`). Signing it closes the old lease as «renewed»;
    the deposit moves with the tenant — no second deposit is billed."""
    c = db()
    old = _lease(c, lid)
    if old["status"] not in ("active", "expired"):
        raise HTTPException(409, "يُجدَّد العقد الساري أو المنتهي فقط")
    if c.execute("SELECT 1 FROM leases WHERE renewed_from=? AND status IN ('draft','active','expired','renewed')", (lid,)).fetchone():
        raise HTTPException(409, "جُدِّد هذا العقد سابقًا")
    last = c.execute("SELECT annual_rent FROM lease_terms WHERE lease_id=? ORDER BY year_no DESC LIMIT 1", (lid,)).fetchone()
    rent = None if b.rents else (b.annual_rent or (last["annual_rent"] if last else old["annual_rent"]))
    carry = (old["deposit"] or 0) > 0 and old["deposit_state"] in ("held", "recorded")
    nb = LeaseNew(unit_id=old["unit_id"], tenant_id=old["tenant_id"], start=dt.date.fromisoformat(old["end"]) + dt.timedelta(days=1), months=b.months, annual_rent=rent,
                  rents=b.rents, escalation_pct=b.escalation_pct, frequency=b.frequency or old["frequency"] or 12, prep_free_days=b.prep_free_days,
                  deposit=old["deposit"] if carry else 0, charity_clause=bool(old["charity_clause"]) if b.charity_clause is None else b.charity_clause,
                  kind=old["kind"] if old["kind"] in USES else None, override_reason=b.override_reason)
    nid = create_lease(c, nb, u, "manual", bill_deposit=False)
    c.execute("UPDATE leases SET renewed_from=?, deposit_state=? WHERE id=?", (lid, "carried" if carry else None, nid))
    event(c, nid, "renewal_of", f"تجديد للعقد {old['number']}", u["name"])
    if b.sign:
        sign_lease(c, nid, u)
    audit(c, "تجديد عقد إيجار", f"{old['number']} ⟵ {one(c, 'SELECT number FROM leases WHERE id=?', (nid,))['number']} · {b.months} شهرًا")
    c.commit()
    return {"id": nid, "status": "active" if b.sign else "draft"}


# ----------------------------------------------------------------------------------------------------- termination / eviction
def close_lease(c, l, kind: str, on: dt.date, note: str, u: dict, fee: float = 0.0, prorate_last: bool = False) -> dict:
    """Close an active lease. Dues of the periods after `on` stop being owed: cut down to what was paid (the line stays, labelled as cancelled — nothing is deleted);
    their still-held cheques are cancelled. Rescheduled arrears (plan instalments) are debts, not rent, and stay. Optionally the period in which `on` falls
    is charged only for the days used."""
    if l["status"] != "active":
        raise HTTPException(409, "يُنهى العقد الساري فقط")
    if on < dt.date.fromisoformat(l["start"]) or on > dt.date.fromisoformat(l["end"]):
        raise HTTPException(400, "تاريخ الإنهاء يقع خارج مدة العقد")
    iso = on.isoformat()
    dues = rows(c.execute("SELECT * FROM rent_dues WHERE lease_id=? AND COALESCE(kind,'rent')='rent' AND plan_id IS NULL ORDER BY due, id", (l["id"],)))
    cut, total = [], 0.0
    for d in [x for x in dues if x["due"] > iso]:
        c.execute("UPDATE cheques SET status='cancelled', bounce_reason=COALESCE(bounce_reason,'أُلغي بإنهاء العقد') WHERE due_id=? AND status='held'", (d["id"],))
        c.execute("UPDATE cheques SET due_id=NULL WHERE due_id=? AND status='deposited'", (d["id"],))
        # never DELETE: the application role has no DELETE on rent_dues; the due stays as a visible zero (or paid-only) line
        c.execute("UPDATE rent_dues SET amount=?, label=? WHERE id=?", (d["paid"], f"{d['label'] or 'إيجار'} (أُلغيت بإنهاء العقد)", d["id"]))
        cut.append(d["due"])
        total += d["amount"] - d["paid"]
    if prorate_last:
        past = [x for x in dues if x["due"] <= iso]
        if past:
            d = past[-1]
            nxt = next((x["due"] for x in dues if x["due"] > d["due"]), None)
            period_end = dt.date.fromisoformat(nxt) if nxt else dt.date.fromisoformat(l["end"]) + dt.timedelta(days=1)
            span = (period_end - dt.date.fromisoformat(d["due"])).days
            used = (on - dt.date.fromisoformat(d["due"])).days + 1
            new = max(d["paid"], r3(d["amount"] * min(used, span) / span)) if span > 0 else d["amount"]
            if new < d["amount"] - EPS:
                c.execute("UPDATE rent_dues SET amount=? WHERE id=?", (new, d["id"]))
                total += d["amount"] - new
    if fee > 0:
        c.execute("INSERT INTO rent_dues(lease_id,due,amount,kind,label) VALUES(?,?,?,?,?)", (l["id"], iso, r3(fee), "fee", "مبلغ إنهاء مبكر باتفاق الطرفين"))
    status = {"early": "terminated", "eviction": "evicted", "expiry": "expired"}[kind]
    c.execute("UPDATE leases SET status=?, terminated_at=?, termination_kind=?, termination_note=? WHERE id=?", (status, iso, kind, note, l["id"]))
    event(c, l["id"], {"early": "terminate", "eviction": "evict", "expiry": "expire"}[kind], f"{note} · أُلغيت {len(cut)} دفعة قادمة بقيمة {r3(total):,.3f} ر.ع", u["name"])
    audit(c, {"early": "إنهاء عقد إيجار", "eviction": "إخلاء مستأجر", "expiry": "انتهاء عقد إيجار"}[kind], f"{l['number']} · {iso} · {note}")
    return {"status": status, "cancelled_dues": len(cut), "cancelled_amount": r3(total), "fee": r3(fee)}


class TerminateIn(BaseModel):
    on: dt.date | None = None
    note: str = Field(min_length=5, max_length=300)
    fee: float = Field(default=0, ge=0, le=1_000_000)
    prorate_last: bool = False


@router.post("/api/lea/leases/{lid}/terminate")
def api_terminate(lid: int, b: TerminateIn, u=Depends(act_as("leasing"))):
    c = db()
    l = _lease(c, lid)
    if b.fee > 0:
        need_approve(u)  # a termination amount is a manager's decision
    out = close_lease(c, l, "early", b.on or today(), b.note, u, b.fee, b.prorate_last)
    c.commit()
    return out


class EvictIn(BaseModel):
    note: str = Field(min_length=5, max_length=300)
    on: dt.date | None = None


@router.post("/api/lea/leases/{lid}/evict")
def api_evict(lid: int, b: EvictIn, u=Depends(act_as("leasing_approve"))):
    """Only after a FINAL notice whose cure period has run out while the arrears are still there — the manager's recorded decision."""
    c = db()
    l = _lease(c, lid)
    if arrears_of(c, lid) <= EPS:
        raise HTTPException(409, "لا متأخرات على هذا العقد")
    if not c.execute("SELECT 1 FROM arrears_notices WHERE lease_id=? AND kind='final' AND cure_by<?", (lid, today().isoformat())).fetchone():
        raise HTTPException(409, "يلزم إنذار نهائي انقضت مهلته قبل الإخلاء")
    out = close_lease(c, l, "eviction", b.on or today(), b.note, u)
    c.commit()
    return out


# ----------------------------------------------------------------------------------------------------- hand-over report
class ReadingIn(BaseModel):
    meter_id: int
    reading: float = Field(ge=0, le=1e9)


class DeductionIn(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    amount: float = Field(gt=0, le=1_000_000)
    ref: str = Field(min_length=2, max_length=120)  # the document that proves it (repair invoice, hand-over line, bill …)
    due_id: int | None = None  # set it to settle an unpaid due of the lease from the deposit


class HandoverIn(BaseModel):
    kind: str = Field(pattern=r"^(in|out)$")
    at: dt.date | None = None
    keys: int | None = Field(default=None, ge=0, le=100)
    condition: dict[str, str] = Field(default_factory=dict, max_length=30)
    notes: str = Field(default="", max_length=800)
    readings: list[ReadingIn] = Field(default_factory=list, max_length=20)
    deductions: list[DeductionIn] = Field(default_factory=list, max_length=20)


def _handover_out(c, h) -> dict:
    x = dict(h)
    x["condition"] = json.loads(x["condition"] or "{}")
    x["deductions"] = json.loads(x["deductions"] or "[]")
    x["readings"] = rows(c.execute("""SELECT r.meter_id, r.reading, m.kind, m.number FROM meter_readings r LEFT JOIN unit_meters m ON m.id=r.meter_id
                                      WHERE r.handover_id=? ORDER BY r.id""", (h["id"],)))
    return x


@router.post("/api/lea/leases/{lid}/handover")
def api_handover(lid: int, b: HandoverIn, u=Depends(act_as("leasing"))):
    """The hand-over (in) or take-back (out) report: condition, keys, meter readings and — for «out» — the deductions the deposit settlement may use."""
    c = db()
    l = _lease(c, lid)
    if l["status"] == "draft":
        raise HTTPException(409, "العقد مسودة — وقّعه أولًا")
    if b.kind == "in" and b.deductions:
        raise HTTPException(400, "الخصومات في محضر الاستلام (out) فقط")
    if b.kind == "out" and l["status"] == "active" and dt.date.fromisoformat(l["end"]) >= today():
        raise HTTPException(409, "محضر الاستلام بعد إنهاء العقد أو انتهائه")
    if c.execute("SELECT 1 FROM lease_handovers WHERE lease_id=? AND kind=?", (lid, b.kind)).fetchone():
        raise HTTPException(409, "سُجّل محضر " + ("التسليم" if b.kind == "in" else "الاستلام") + " لهذا العقد سابقًا")
    mine = {m["id"] for m in c.execute("SELECT id FROM unit_meters WHERE unit_id=?", (l["unit_id"],)).fetchall()}
    seen = set()
    for r in b.readings:
        if r.meter_id not in mine:
            raise HTTPException(400, "عدّاد لا يخص هذه الوحدة")
        if r.meter_id in seen:
            raise HTTPException(400, "قراءتان لعدّاد واحد")
        seen.add(r.meter_id)
        if b.kind == "out":
            prev = c.execute("""SELECT r.reading FROM meter_readings r JOIN lease_handovers h ON h.id=r.handover_id WHERE h.lease_id=? AND h.kind='in' AND r.meter_id=?""",
                             (lid, r.meter_id)).fetchone()
            if prev and r.reading < prev["reading"]:
                raise HTTPException(400, "قراءة الاستلام أقل من قراءة التسليم لهذا العدّاد")
    hid = c.execute("INSERT INTO lease_handovers(lease_id,kind,at,by_user,condition,keys,notes,deductions,created) VALUES(?,?,?,?,?,?,?,?,?)",
                    (lid, b.kind, (b.at or today()).isoformat(), u["name"], json.dumps(b.condition, ensure_ascii=False), b.keys, b.notes,
                     json.dumps([d.model_dump() for d in b.deductions], ensure_ascii=False), now_s())).lastrowid
    for r in b.readings:
        c.execute("INSERT INTO meter_readings(handover_id,meter_id,reading) VALUES(?,?,?)", (hid, r.meter_id, r.reading))
    event(c, lid, "handover_" + b.kind, f"{len(b.readings)} قراءة · مفاتيح {b.keys if b.keys is not None else '—'}", u["name"])
    audit(c, "محضر " + ("تسليم" if b.kind == "in" else "استلام") + " إيجار", f"{l['number']} · {len(b.readings)} قراءة · {len(b.deductions)} خصم مقترح")
    c.commit()
    return {"id": hid}


# ----------------------------------------------------------------------------------------------------- deposit settlement
def deposit_basis(c, l) -> float:
    """What the lessee actually put down: the paid deposit dues when the deposit was billed, else the figure recorded on the lease."""
    if l["deposit_state"] == "held":
        return r3(c.execute("SELECT COALESCE(SUM(paid),0) FROM rent_dues WHERE lease_id=? AND kind='deposit'", (l["id"],)).fetchone()[0])
    return r3(l["deposit"] or 0)


class SettleIn(BaseModel):
    deductions: list[DeductionIn] | None = None  # None ⟵ the ones written on the take-back report
    note: str = Field(default="", max_length=300)


@router.post("/api/lea/leases/{lid}/deposit/settle")
def api_deposit_settle(lid: int, b: SettleIn, u=Depends(act_as("leasing"))):
    """Deposit − documented deductions = refund. A deduction that names a due also pays that due (method «other», reference = the deduction's document)."""
    c = db()
    l = _lease(c, lid)
    if l["status"] not in CLOSED:
        raise HTTPException(409, "تُسوّى الوديعة بعد إنهاء العقد أو انتهائه" if l["status"] != "renewed" else "انتقلت الوديعة إلى العقد المجدِّد")
    if l["deposit_state"] not in ("held", "recorded"):
        raise HTTPException(409, "لا وديعة قائمة للتسوية" if not l["deposit_state"] else "سُوّيت الوديعة سابقًا أو انتقلت لعقد آخر")
    basis = deposit_basis(c, l)
    if basis <= EPS:
        raise HTTPException(409, "لم تُسدَّد وديعة على هذا العقد")
    if b.deductions is None:
        ho = c.execute("SELECT deductions FROM lease_handovers WHERE lease_id=? AND kind='out'", (lid,)).fetchone()
        deds = [DeductionIn(**d) for d in json.loads(ho["deductions"] or "[]")] if ho else []
    else:
        deds = b.deductions
    deducted = r3(sum(d.amount for d in deds))
    if deducted > basis + EPS:
        raise HTTPException(409, f"الخصومات ({deducted:,.3f}) تتجاوز الوديعة ({basis:,.3f})")
    for d in deds:
        if d.due_id is not None:
            due = one(c, "SELECT * FROM rent_dues WHERE id=? AND lease_id=?", (d.due_id, lid), "الاستحقاق غير موجود في هذا العقد")
            if due["kind"] == "deposit":
                raise HTTPException(400, "لا يُخصم التأمين من التأمين")
            if d.amount > r3(due["amount"] - due["paid"]) + EPS:
                raise HTTPException(409, "الخصم يتجاوز المتبقي على الاستحقاق")
            apply_payment(c, lid, d.amount, today(), "other", f"خصم من التأمين — {d.ref}", u["name"], d.due_id)
    refund = r3(basis - deducted)
    state = "returned" if deducted <= EPS else "partly_settled" if refund > EPS else "settled"
    c.execute("UPDATE leases SET deposit_state=?, deposit_deducted=?, deposit_refund=?, deposit_settled_at=?, deposit_settled_by=? WHERE id=?",
              (state, deducted, refund, now_s(), u["name"], lid))
    event(c, lid, "deposit_settle", json.dumps({"basis": basis, "deducted": deducted, "refund": refund, "deductions": [d.model_dump() for d in deds], "note": b.note}, ensure_ascii=False), u["name"])
    audit(c, "تسوية تأمين إيجار", f"{l['number']} · التأمين {basis:,.3f} − خصومات {deducted:,.3f} = المردود {refund:,.3f} ر.ع")
    c.commit()
    return {"state": state, "basis": basis, "deducted": deducted, "refund": refund}


# ----------------------------------------------------------------------------------------------------- arrears notices
class NoticeIn(BaseModel):
    kind: str = Field(pattern=r"^(reminder|formal|final)$")
    cure_days: int | None = Field(default=None, ge=1, le=90)
    note: str = Field(default="", max_length=300)


@router.post("/api/lea/leases/{lid}/notices")
def api_notice(lid: int, b: NoticeIn, u=Depends(act_as("leasing"))):
    """A numbered notice for the arrears the lease has today. A final notice needs a formal one before it. The wording is a prepared form that waits for the
    legal adviser's approval (the footer says so until the owner records it)."""
    c = db()
    l = _lease(c, lid)
    if l["status"] not in ("active", "expired", "terminated", "evicted"):
        raise HTTPException(409, "لا إنذار لعقد مسودة")
    amount = arrears_of(c, lid)
    if amount <= EPS:
        raise HTTPException(409, "لا متأخرات على هذا العقد")
    if b.kind == "final" and not c.execute("SELECT 1 FROM arrears_notices WHERE lease_id=? AND kind='formal'", (lid,)).fetchone():
        raise HTTPException(409, "يلزم إنذار رسمي قبل الإنذار النهائي")
    y = today().year
    number = f"AN-{y}-{next_no(c, f'notice:{y}'):04d}"
    seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM arrears_notices WHERE lease_id=?", (lid,)).fetchone()[0]
    cure = today() + dt.timedelta(days=b.cure_days or NOTICE_CURE[b.kind])
    nid = c.execute("INSERT INTO arrears_notices(lease_id,seq,number,kind,issued,cure_by,amount,created_by,note) VALUES(?,?,?,?,?,?,?,?,?)",
                    (lid, seq, number, b.kind, today().isoformat(), cure.isoformat(), amount, u["name"], b.note)).lastrowid
    event(c, lid, "notice_" + b.kind, f"{number} · {amount:,.3f} ر.ع · مهلة حتى {cure}", u["name"])
    audit(c, "إنذار متأخرات", f"{number} · {NOTICE_KINDS[b.kind]} · عقد {l['number']} · {amount:,.3f} ر.ع")
    c.commit()
    return {"id": nid, "number": number, "cure_by": cure.isoformat(), "amount": amount}


class SentIn(BaseModel):
    via: str = Field(pattern=r"^(hand|email|registered|whatsapp)$")
    on: dt.date | None = None


@router.post("/api/lea/notices/{nid}/sent")
def api_notice_sent(nid: int, b: SentIn, u=Depends(act_as("leasing"))):
    c = db()
    n = one(c, "SELECT * FROM arrears_notices WHERE id=?", (nid,), "الإنذار غير موجود")
    if n["sent_at"]:
        raise HTTPException(409, "سُجِّل تسليم هذا الإنذار سابقًا")
    c.execute("UPDATE arrears_notices SET sent_via=?, sent_at=? WHERE id=?", (b.via, (b.on or today()).isoformat(), nid))
    event(c, n["lease_id"], "notice_sent", f"{n['number']} · {b.via}", u["name"])
    audit(c, "تسليم إنذار", f"{n['number']} · {b.via}")
    c.commit()
    return {"ok": True}


@router.get("/api/lea/notices")
def api_notices(_=Depends(need("leasing"))):
    c = db()
    out = rows(c.execute("""SELECT n.*, l.number lease_no, u.code unit, t.name tenant FROM arrears_notices n JOIN leases l ON l.id=n.lease_id JOIN units u ON u.id=l.unit_id
                            JOIN tenants_l t ON t.id=l.tenant_id ORDER BY n.id DESC LIMIT 300"""))
    for x in out:
        x["kind_label"] = NOTICE_KINDS[x["kind"]]
        x["open_arrears"] = arrears_of(c, x["lease_id"])
        x["state"] = "cured" if x["open_arrears"] <= EPS else "expired" if x["cure_by"] < today().isoformat() else "running"
    return out


# ----------------------------------------------------------------------------------------------------- payment plans
class PlanItem(BaseModel):
    due: dt.date
    amount: float = Field(gt=0, le=10_000_000)


class PlanIn(BaseModel):
    due_ids: list[int] = Field(min_length=1, max_length=60)
    installments: list[PlanItem] = Field(min_length=1, max_length=36)
    note: str = Field(default="", max_length=300)


@router.post("/api/lea/leases/{lid}/plans")
def api_plan(lid: int, b: PlanIn, u=Depends(act_as("leasing_approve"))):
    """Re-spread the outstanding amount of the chosen dues over new instalments. The total must equal the outstanding to the baisa — a plan can neither add a
    fee or interest nor forgive anything. The old dues keep only what was paid; their post-dated cheques become loose cheques that clear against the oldest due."""
    c = db()
    l = _lease(c, lid)
    if l["status"] == "draft":
        raise HTTPException(409, "العقد مسودة")
    olds, owed = [], 0.0
    for did in dict.fromkeys(b.due_ids):
        d = one(c, "SELECT * FROM rent_dues WHERE id=? AND lease_id=?", (did, lid), "استحقاق لا يخص هذا العقد")
        left = r3(d["amount"] - d["paid"])
        if (d["kind"] or "rent") == "deposit" or left <= EPS:
            raise HTTPException(409, "اختر استحقاقات غير مسدَّدة من الإيجار (لا التأمين)")
        olds.append(d)
        owed += left
    if abs(r3(sum(i.amount for i in b.installments)) - r3(owed)) > EPS:
        raise HTTPException(409, f"مجموع الأقساط يجب أن يساوي المتبقي ({r3(owed):,.3f}) تمامًا — بلا فوائد ولا رسوم")
    if any(i.due < today() for i in b.installments):
        raise HTTPException(400, "تواريخ الأقساط من اليوم فصاعدًا")
    pid = c.execute("INSERT INTO payment_plans(lease_id,agreed_on,status,note,approved_by,total,original) VALUES(?,?,?,?,?,?,?)",
                    (lid, today().isoformat(), "active", b.note, u["name"], r3(owed),
                     json.dumps([{"due_id": d["id"], "label": d["label"], "due": d["due"], "amount": d["amount"], "paid": d["paid"]} for d in olds], ensure_ascii=False))).lastrowid
    for d in olds:
        c.execute("UPDATE rent_dues SET amount=?, label=? WHERE id=?", (d["paid"], f"{d['label'] or 'إيجار'} (أُعيدت جدولته — خطة {pid})", d["id"]))
        c.execute("UPDATE cheques SET due_id=NULL WHERE due_id=? AND status IN ('held','deposited')", (d["id"],))
    n = len(b.installments)
    for i, it in enumerate(sorted(b.installments, key=lambda x: x.due), 1):
        c.execute("INSERT INTO rent_dues(lease_id,due,amount,kind,label,plan_id) VALUES(?,?,?,?,?,?)", (lid, it.due.isoformat(), r3(it.amount), "rent", f"خطة سداد {pid} — قسط {i} من {n}", pid))
    event(c, lid, "plan", f"خطة {pid} · {r3(owed):,.3f} ر.ع على {n} قسط", u["name"])
    audit(c, "خطة سداد إيجار", f"عقد {l['number']} · {r3(owed):,.3f} ر.ع على {n} قسط · اعتمدها {u['name']}")
    c.commit()
    return {"id": pid, "total": r3(owed), "installments": n}


def _plan_out(c, p) -> dict:
    x = dict(p)
    x["original"] = json.loads(x["original"] or "[]")
    dues = rows(c.execute("SELECT id, due, amount, paid FROM rent_dues WHERE plan_id=? ORDER BY due", (p["id"],)))
    x["dues"] = dues
    x["paid"] = r3(sum(d["paid"] for d in dues))
    x["state"] = "completed" if dues and all(d["amount"] - d["paid"] <= EPS for d in dues) else "broken" if any(d["due"] < today().isoformat() and d["amount"] - d["paid"] > EPS for d in dues) else "active"
    return x


@router.get("/api/lea/plans")
def api_plans(_=Depends(need("leasing"))):
    c = db()
    out = []
    for p in c.execute("""SELECT p.*, l.number lease_no, u.code unit, t.name tenant FROM payment_plans p JOIN leases l ON l.id=p.lease_id JOIN units u ON u.id=l.unit_id
                          JOIN tenants_l t ON t.id=l.tenant_id ORDER BY p.id DESC LIMIT 200""").fetchall():
        x = _plan_out(c, p)
        x.pop("original")
        out.append(x)
    return out


# ----------------------------------------------------------------------------------------------------- late-payment charity (rent)
def charity_accrue(c, lease, due_id: int, due_date: str, kind: str | None, amount: float, paid_on: dt.date) -> float:
    """Like the sale instalments: when a due is paid after the grace period, the paid amount × the monthly rate × the days beyond grace / 30 is owed as a
    charitable donation — only if the lease carries the clause and the developer's treatment is «charity». It never reaches revenue."""
    if not lease["charity_clause"] or (kind or "rent") == "deposit" or setting(c, "late_penalty_treatment", "charity") != "charity":
        return 0.0
    rate, grace = setting_f(c, "late_penalty_monthly", .01), int(setting_f(c, "late_grace_days", 15))
    late = (paid_on - dt.date.fromisoformat(due_date)).days
    if late <= grace or amount <= 1:
        return 0.0
    amt = r3(amount * rate * (late - grace) / 30)
    if amt <= 0:
        return 0.0
    cur = c.execute("SELECT id FROM charity_dues WHERE rent_due_id=?", (due_id,)).fetchone()
    if cur:
        c.execute("UPDATE charity_dues SET amount=amount+?, late_days=?, computed_at=? WHERE id=?", (amt, late, now_s(), cur["id"]))
    else:
        c.execute("INSERT INTO charity_dues(rent_due_id,lease_id,amount,rate,late_days,computed_at,status) VALUES(?,?,?,?,?,?,'due')", (due_id, lease["id"], amt, rate, late, now_s()))
    return amt


def charity_reverse(c, p) -> None:
    """A reversed payment (bounced cheque, refund) takes back the donation it created, as long as that donation is still only owed."""
    lease = c.execute("SELECT * FROM leases WHERE id=?", (p["lease_id"],)).fetchone()
    due = c.execute("SELECT id, due, kind FROM rent_dues WHERE id=?", (p["due_id"],)).fetchone()
    if not lease or not due or not lease["charity_clause"] or (due["kind"] or "rent") == "deposit":
        return
    rate, grace = setting_f(c, "late_penalty_monthly", .01), int(setting_f(c, "late_grace_days", 15))
    late = (dt.date.fromisoformat(p["paid_on"]) - dt.date.fromisoformat(due["due"])).days
    if late <= grace or p["amount"] <= 1:
        return
    amt = r3(p["amount"] * rate * (late - grace) / 30)
    c.execute("UPDATE charity_dues SET amount=CASE WHEN amount>? THEN amount-? ELSE 0 END WHERE rent_due_id=? AND status='due'", (amt, amt, due["id"]))


@router.get("/api/lea/charity")
def api_charity(_=Depends(need("leasing"))):
    c = db()
    items = rows(c.execute("""SELECT d.*, l.number lease_no, u.code unit, t.name tenant FROM charity_dues d JOIN leases l ON l.id=d.lease_id JOIN units u ON u.id=l.unit_id
                              JOIN tenants_l t ON t.id=l.tenant_id WHERE d.rent_due_id IS NOT NULL ORDER BY d.id DESC LIMIT 300"""))
    tot = {k: r3(sum(i["amount"] or 0 for i in items if i["status"] == k)) for k in ("due", "collected", "disbursed", "waived")}
    return {"items": items, "totals": tot, "note": "تبرع التأخير التزام على المستأجر بحكم العقد يُصرف لجهة خيرية معتمدة؛ لا يُقيَّد إيرادًا للمؤجِّر ولا يُعدّ فائدة."}


class CharityRef(BaseModel):
    reference: str = Field(min_length=2, max_length=80)
    beneficiary: str = Field(default="", max_length=120)


@router.post("/api/lea/charity/{did}/collect")
def api_charity_collect(did: int, r: CharityRef, u=Depends(act_as("leasing"))):
    c = db()
    d = one(c, "SELECT * FROM charity_dues WHERE id=? AND rent_due_id IS NOT NULL AND status='due'", (did,), "المبلغ ليس مستحقًا", 409)
    c.execute("UPDATE charity_dues SET status='collected', collected_at=?, collected_ref=? WHERE id=?", (now_s(), r.reference, did))
    audit(c, "تحصيل تبرع تأخير إيجار", f"{d['amount']:,.3f} ر.ع · {r.reference}")
    c.commit()
    return {"ok": True}


@router.post("/api/lea/charity/{did}/disburse")
def api_charity_disburse(did: int, r: CharityRef, u=Depends(act_as("leasing_approve"))):
    c = db()
    if not r.beneficiary:
        raise HTTPException(400, "حدّد الجهة الخيرية المستفيدة")
    d = one(c, "SELECT * FROM charity_dues WHERE id=? AND rent_due_id IS NOT NULL AND status='collected'", (did,), "المبلغ غير محصَّل بعد", 409)
    c.execute("UPDATE charity_dues SET status='disbursed', disbursed_at=?, beneficiary=?, disbursed_ref=? WHERE id=?", (now_s(), r.beneficiary, r.reference, did))
    audit(c, "صرف تبرع تأخير إيجار", f"{d['amount']:,.3f} ر.ع إلى {r.beneficiary} · {r.reference}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- one call for the lease screen
@router.get("/api/lea/leases/{lid}/ops")
def api_lease_ops(lid: int, _=Depends(need("leasing"))):
    c = db()
    l = _lease(c, lid)
    ho = [_handover_out(c, h) for h in c.execute("SELECT * FROM lease_handovers WHERE lease_id=? ORDER BY id", (lid,)).fetchall()]
    ins = {r["meter_id"]: r["reading"] for h in ho if h["kind"] == "in" for r in h["readings"]}
    for h in ho:
        for r in h["readings"]:
            r["consumption"] = r3(r["reading"] - ins[r["meter_id"]]) if h["kind"] == "out" and r["meter_id"] in ins else None
    notices = rows(c.execute("SELECT * FROM arrears_notices WHERE lease_id=? ORDER BY id DESC", (lid,)))
    for n in notices:
        n["kind_label"] = NOTICE_KINDS[n["kind"]]
    plans = [_plan_out(c, p) for p in c.execute("SELECT * FROM payment_plans WHERE lease_id=? ORDER BY id DESC", (lid,)).fetchall()]
    charity = rows(c.execute("SELECT * FROM charity_dues WHERE lease_id=? AND rent_due_id IS NOT NULL ORDER BY id DESC", (lid,)))
    basis = deposit_basis(c, l) if l["deposit_state"] in ("held", "recorded") else None
    return {"handovers": ho, "notices": notices, "plans": plans, "charity": charity, "arrears": arrears_of(c, lid),
            "deposit": {"state": l["deposit_state"], "amount": l["deposit"], "basis": basis, "deducted": l["deposit_deducted"], "refund": l["deposit_refund"],
                        "settled_at": l["deposit_settled_at"]},
            "renewed_to": next(iter(rows(c.execute("SELECT id, number, status FROM leases WHERE renewed_from=? ORDER BY id DESC LIMIT 1", (lid,)))), None)}


# ----------------------------------------------------------------------------------------------------- background (once a day per developer)
def daily(c) -> int:
    """Staff notifications that need no staff action to exist: a broken payment plan, a maintenance request past its SLA."""
    n, t = 0, today().isoformat()

    def put(title, body, key):
        return c.execute("INSERT OR IGNORE INTO notifications(audience,channel,title,body,status,created,dedupe) VALUES(?,?,?,?,?,?,?)",
                         ("staff", "app", title, body, "queued", now_s(), key)).rowcount

    for p in c.execute("SELECT * FROM payment_plans WHERE status='active'").fetchall():
        x = _plan_out(c, p)
        if x["state"] == "broken":
            n += put("خطة سداد متعثرة", f"خطة {p['id']} على العقد {c.execute('SELECT number FROM leases WHERE id=?', (p['lease_id'],)).fetchone()['number']} فيها قسط متأخر", f"plan-broken:{p['id']}")
    for m in c.execute("SELECT id, category, sla_due FROM maint_requests WHERE status NOT IN ('done','closed','rejected') AND sla_due<?", (t,)).fetchall():
        n += put("طلب صيانة تجاوز مهلته", f"الطلب {m['id']} ({m['category'] or 'عام'}) تجاوز موعد المعالجة {m['sla_due']}", f"maint-sla:{m['id']}")
    return n


# ----------------------------------------------------------------------------------------------------- document data (drawn by pdfgen)
def handover_doc_row(c, hid: int) -> dict:
    h = _handover_out(c, one(c, "SELECT * FROM lease_handovers WHERE id=?", (hid,), "المحضر غير موجود"))
    h["lease"] = lease_detail(c, h["lease_id"])
    ins = {r["meter_id"]: r["reading"] for x in c.execute("SELECT id FROM lease_handovers WHERE lease_id=? AND kind='in'", (h["lease_id"],)).fetchall()
           for r in rows(c.execute("SELECT meter_id, reading FROM meter_readings WHERE handover_id=?", (x["id"],)))}
    for r in h["readings"]:
        r["consumption"] = r3(r["reading"] - ins[r["meter_id"]]) if h["kind"] == "out" and r["meter_id"] in ins else None
    h["number"] = f"HO-{h['lease']['number']}-{h['kind'].upper()}"
    h["approved"] = (c.execute("SELECT v FROM settings WHERE k='lea:template_approved'").fetchone() or {"v": "0"})["v"] == "1"
    return h


def notice_doc_row(c, nid: int) -> dict:
    n = dict(one(c, "SELECT * FROM arrears_notices WHERE id=?", (nid,), "الإنذار غير موجود"))
    n["kind_label"] = NOTICE_KINDS[n["kind"]]
    n["lease"] = lease_detail(c, n["lease_id"])
    n["late_dues"] = [d for d in n["lease"]["dues"] if d["state"] == "late" and d["balance"] > EPS and (d["kind"] or "rent") != "deposit"]
    n["approved"] = (c.execute("SELECT v FROM settings WHERE k='lea:template_approved'").fetchone() or {"v": "0"})["v"] == "1"
    return n


__all__ = ["router", "charity_accrue", "charity_reverse", "daily", "close_lease", "need_approve", "arrears_of"]
