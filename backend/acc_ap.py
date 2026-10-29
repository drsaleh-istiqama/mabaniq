"""Mabaniq 0.24.0 — accounting, payables and bank accounts (design §4.3–4.4, phase 3b).

Suppliers' bills are drafted, then approved by someone else (an administrator may approve their own) — approval posts expense + input VAT against the payable.
A bill is paid only through a *payment order*: two approvers above `ap_dual_over` OMR (the creator and both approvers must be different people — no administrator
exception here), then one execution that posts the payment (and, for a cheque, records the issued cheque). A supplier payment is a ledger row — a correction is a
negative row and a reversing journal, never an edit. Every bank / cash / escrow / charity account is Islamic only: a conventional account is refused at creation.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import ledger, pii
from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .db import setting_f

router = APIRouter()
r3 = ledger.r3
EPS = ledger.EPS
METHODS = ("cash", "transfer", "cheque", "card")
VAT_CLASSES = ("standard", "zero", "exempt", "out_of_scope")


def _active(c) -> str:
    s = ledger.start_date(c)
    if not s:
        raise HTTPException(409, "المحاسبة غير مفعَّلة بعد")
    ledger.ensure_chart(c)
    ensure_default_banks(c)
    return s


# ----------------------------------------------------------------------------------------------------- bank accounts
def ensure_default_banks(c) -> None:
    """The three accounts the leasing events already post to get their bank-account records once (cash box, main bank, charity bank)."""
    for key, name, kind in (("cash", "الصندوق", "cash"), ("bank_main", "الحساب الجاري الرئيسي", "bank"), ("bank_charity", "حساب التبرعات الخيرية", "charity")):
        a = c.execute("SELECT id FROM acc_accounts WHERE system_key=?", (key,)).fetchone()
        if a and not c.execute("SELECT 1 FROM bank_accounts WHERE account_id=?", (a["id"],)).fetchone():
            c.execute("INSERT INTO bank_accounts(name,kind,account_id) VALUES(?,?,?)", (name, kind, a["id"]))


@router.get("/api/acc/banks")
def api_banks(_=Depends(need("accounting"))):
    c = db()
    if ledger.start_date(c):
        ensure_default_banks(c)
        c.commit()
    out = rows(c.execute("""SELECT b.*, a.code account_code, a.name account_name,
                            COALESCE((SELECT SUM(l.debit - l.credit) FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id
                                      WHERE l.account_id=b.account_id AND j.status IN ('posted','reversed')),0) balance FROM bank_accounts b JOIN acc_accounts a ON a.id=b.account_id
                            ORDER BY b.id"""))
    for x in out:
        x["iban"] = pii.mask(pii.dec(x["iban"]) if x["iban"] else None)
        x["balance"] = r3(x["balance"])
    return out


class BankIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    bank: str = Field(default="", max_length=120)
    iban: str = Field(default="", max_length=40)
    kind: Literal["bank", "cash", "escrow", "charity"] = "bank"
    islamic: bool
    account_id: int | None = None
    project_id: int | None = None


@router.post("/api/acc/banks")
def api_bank_add(b: BankIn, u=Depends(act_as("accounting_approve"))):
    c = db()
    _active(c)
    if not b.islamic:
        raise HTTPException(400, "لا تُنشأ حسابات بنكية غير إسلامية في المنصة — اختر بنكًا أو نافذة إسلامية")
    if b.account_id:
        a = c.execute("SELECT id, type, postable FROM acc_accounts WHERE id=?", (b.account_id,)).fetchone()
        if not a or a["type"] != "asset" or not a["postable"]:
            raise HTTPException(400, "حساب الدليل المرتبط يجب أن يكون أصلًا قابلًا للترحيل")
        if c.execute("SELECT 1 FROM bank_accounts WHERE account_id=?", (b.account_id,)).fetchone():
            raise HTTPException(409, "هذا الحساب مرتبط ببنك آخر")
        gl = b.account_id
    else:
        parent = c.execute("SELECT id FROM acc_accounts WHERE code='1120'").fetchone()
        nums = [int(r["code"]) for r in c.execute("SELECT code FROM acc_accounts WHERE parent_id=?", (parent["id"],)).fetchall() if r["code"].isdigit()]
        code = str(max(nums + [1121]) + 1)
        gl = c.execute("INSERT INTO acc_accounts(code,name,type,parent_id,postable,normal,cash_class) VALUES(?,?,?,?,1,'debit','cash')", (code, b.name, "asset", parent["id"])).lastrowid
    bid = c.execute("INSERT INTO bank_accounts(name,bank,iban,kind,account_id,project_id) VALUES(?,?,?,?,?,?)",
                    (b.name, b.bank or None, pii.enc(b.iban) if b.iban else None, b.kind, gl, b.project_id)).lastrowid
    audit(c, "حساب بنكي جديد", f"{b.name} · {b.kind}")
    c.commit()
    return {"id": bid, "account_id": gl}


# ----------------------------------------------------------------------------------------------------- suppliers
@router.get("/api/acc/vendors")
def api_vendors(_=Depends(need("accounting"))):
    c = db()
    out = rows(c.execute("""SELECT v.id, v.name, v.cr_number, v.tax_no, v.phone, v.email, v.trade, v.iban, v.active,
                            COALESCE((SELECT SUM(b.total - b.paid) FROM ap_bills b WHERE b.vendor_id=v.id AND b.status IN ('approved','partly_paid')),0) owed FROM vendors v
                            WHERE COALESCE(v.active,1)=1 ORDER BY v.name"""))
    for x in out:
        x["iban"] = pii.mask(x["iban"])
        x["owed"] = r3(x["owed"])
    return out


class VendorIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    cr_number: str = Field(default="", max_length=40)
    tax_no: str = Field(default="", max_length=40)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=120)
    trade: str = Field(default="", max_length=80)
    iban: str = Field(default="", max_length=40)


@router.post("/api/acc/vendors")
def api_vendor_add(b: VendorIn, u=Depends(act_as("accounting"))):
    c = db()
    vid = c.execute("INSERT INTO vendors(name,cr_number,tax_no,phone,email,trade,iban) VALUES(?,?,?,?,?,?,?)",
                    (b.name, b.cr_number or None, b.tax_no or None, b.phone or None, b.email or None, b.trade or None, pii.enc(b.iban) if b.iban else None)).lastrowid
    audit(c, "مورّد جديد", b.name)
    c.commit()
    return {"id": vid}


class VendorTax(BaseModel):
    tax_no: str = Field(max_length=40)


@router.patch("/api/acc/vendors/{vid}")
def api_vendor_tax(vid: int, b: VendorTax, u=Depends(act_as("accounting"))):
    c = db()
    if not c.execute("SELECT 1 FROM vendors WHERE id=?", (vid,)).fetchone():
        raise HTTPException(404, "المورّد غير موجود")
    c.execute("UPDATE vendors SET tax_no=? WHERE id=?", (b.tax_no or None, vid))
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- bills
class BillLine(BaseModel):
    account: int | str
    amount: float = Field(gt=0, le=1_000_000_000)
    cost_center_id: int | None = None
    description: str = Field(default="", max_length=200)


class BillIn(BaseModel):
    vendor_id: int
    bill_date: dt.date
    due_date: dt.date | None = None
    vendor_ref: str = Field(default="", max_length=60)
    description: str = Field(default="", max_length=300)
    vat_class: Literal["standard", "zero", "exempt", "out_of_scope"] = "out_of_scope"
    lines: list[BillLine] = Field(min_length=1, max_length=100)


def _bill_amounts(c, b: BillIn) -> tuple[float, float, float]:
    net = r3(sum(x.amount for x in b.lines))
    rate = setting_f(c, "vat_standard", 0.05) if b.vat_class == "standard" else 0.0
    vat = r3(net * rate)
    return net, vat, r3(net + vat)


def _acct(c, ref) -> int:
    r = c.execute("SELECT id, postable, active FROM acc_accounts WHERE " + ("id=?" if isinstance(ref, int) else "code=?"), (ref,)).fetchone()
    if not r or not r["postable"] or not r["active"]:
        raise HTTPException(400, f"الحساب {ref} غير قابل للترحيل")
    return r["id"]


def _bill_out(c, bid: int) -> dict:
    b = c.execute("SELECT b.*, v.name vendor FROM ap_bills b JOIN vendors v ON v.id=b.vendor_id WHERE b.id=?", (bid,)).fetchone()
    if not b:
        raise HTTPException(404, "الفاتورة غير موجودة")
    x = dict(b)
    x["lines"] = rows(c.execute("""SELECT l.*, a.code account_code, a.name account_name FROM ap_bill_lines l JOIN acc_accounts a ON a.id=l.account_id WHERE l.bill_id=? ORDER BY l.line_no""", (bid,)))
    x["outstanding"] = r3(x["total"] - x["paid"]) if x["status"] in ("approved", "partly_paid") else 0.0
    x["payments"] = rows(c.execute("SELECT * FROM ap_payments WHERE bill_id=? ORDER BY id", (bid,)))
    return x


@router.get("/api/acc/bills")
def api_bills(status: str | None = None, vendor_id: int | None = None, limit: int = Query(200, ge=1, le=500), _=Depends(need("accounting"))):
    c = db()
    w, a = ["1=1"], []
    if status:
        w.append("b.status=?")
        a.append(status)
    if vendor_id:
        w.append("b.vendor_id=?")
        a.append(vendor_id)
    return rows(c.execute(f"SELECT b.*, v.name vendor FROM ap_bills b JOIN vendors v ON v.id=b.vendor_id WHERE {' AND '.join(w)} ORDER BY b.bill_date DESC, b.id DESC LIMIT ?", (*a, limit)))


@router.get("/api/acc/bills/{bid}")
def api_bill(bid: int, _=Depends(need("accounting"))):
    return _bill_out(db(), bid)


def _save_bill_lines(c, bid: int, b: BillIn) -> None:
    c.execute("DELETE FROM ap_bill_lines WHERE bill_id=?", (bid,))
    for i, x in enumerate(b.lines, 1):
        c.execute("INSERT INTO ap_bill_lines(bill_id,line_no,account_id,cost_center_id,description,amount) VALUES(?,?,?,?,?,?)", (bid, i, _acct(c, x.account), x.cost_center_id, x.description or None, r3(x.amount)))


@router.post("/api/acc/bills")
def api_bill_add(b: BillIn, u=Depends(act_as("accounting"))):
    c = db()
    start = _active(c)
    if not c.execute("SELECT 1 FROM vendors WHERE id=?", (b.vendor_id,)).fetchone():
        raise HTTPException(400, "المورّد غير موجود")
    if b.bill_date.isoformat() < start:
        raise HTTPException(400, f"تاريخ الفاتورة يسبق بدء المحاسبة ({start})")
    if b.bill_date > today():
        raise HTTPException(400, "تاريخ الفاتورة لا يكون في المستقبل")
    net, vat, total = _bill_amounts(c, b)
    bid = c.execute("INSERT INTO ap_bills(vendor_id,bill_date,due_date,vendor_ref,description,net,vat_class,vat,total,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (b.vendor_id, b.bill_date.isoformat(), b.due_date.isoformat() if b.due_date else None, b.vendor_ref or None, b.description or None, net, b.vat_class, vat, total, u["name"])).lastrowid
    _save_bill_lines(c, bid, b)
    audit(c, "فاتورة مورّد (مسودة)", f"#{bid} · {total:,.3f} ر.ع")
    c.commit()
    return {"id": bid, "net": net, "vat": vat, "total": total}


@router.put("/api/acc/bills/{bid}")
def api_bill_edit(bid: int, b: BillIn, u=Depends(act_as("accounting"))):
    c = db()
    cur = c.execute("SELECT * FROM ap_bills WHERE id=?", (bid,)).fetchone()
    if not cur or cur["status"] != "draft":
        raise HTTPException(409, "تُعدَّل المسودة فقط")
    net, vat, total = _bill_amounts(c, b)
    c.execute("UPDATE ap_bills SET vendor_id=?, bill_date=?, due_date=?, vendor_ref=?, description=?, net=?, vat_class=?, vat=?, total=? WHERE id=?",
              (b.vendor_id, b.bill_date.isoformat(), b.due_date.isoformat() if b.due_date else None, b.vendor_ref or None, b.description or None, net, b.vat_class, vat, total, bid))
    _save_bill_lines(c, bid, b)
    c.commit()
    return {"ok": True}


@router.post("/api/acc/bills/{bid}/approve")
def api_bill_approve(bid: int, u=Depends(act_as("accounting_approve"))):
    """Approval posts the bill: expense lines (+ input VAT) against the supplier payable. Maker ≠ checker, except for an administrator."""
    c = db()
    _active(c)
    b = c.execute("SELECT * FROM ap_bills WHERE id=?", (bid,)).fetchone()
    if not b or b["status"] != "draft":
        raise HTTPException(409, "تُعتمد المسودة فقط")
    if b["created_by"] == u["name"] and u["role"] != "admin":
        raise HTTPException(403, "لا يعتمد المُنشئ فاتورته بنفسه")
    ls = rows(c.execute("SELECT * FROM ap_bill_lines WHERE bill_id=? ORDER BY line_no", (bid,)))
    cls = None if b["vat_class"] == "out_of_scope" else b["vat_class"]
    lines = [dict(account=x["account_id"], debit=x["amount"], cc=x["cost_center_id"], memo=x["description"], vat_class=cls) for x in ls]
    if b["vat"] > EPS:
        lines.append(dict(account="vat_in", debit=b["vat"], memo="ضريبة مدخلات"))
    lines.append(dict(account="ap_vendors", credit=b["total"], party_type="vendor", party_id=b["vendor_id"]))
    year = int(b["bill_date"][:4])
    number = f"AP-{year}-{ledger_no(c, f'apbill:{year}'):04d}"
    try:
        jid = ledger.post(c, date=dt.date.fromisoformat(b["bill_date"]), lines=lines, memo=f"فاتورة مورّد {number} — {b['vendor_ref'] or ''} {b['description'] or ''}".strip(),
                          source_kind="bill", source_ref=str(bid), source_key=f"bill:{bid}", by=u["name"], kind="auto")
    except ledger.LedgerError as e:
        raise HTTPException(409, str(e)) from None
    c.execute("UPDATE ap_bills SET status='approved', number=?, journal_id=?, approved_by=?, approved_at=? WHERE id=?", (number, jid, u["name"], now_s(), bid))
    audit(c, "اعتماد فاتورة مورّد", f"{number} · {b['total']:,.3f} ر.ع")
    c.commit()
    return {"number": number, "journal_id": jid}


def ledger_no(c, key: str) -> int:
    c.execute("INSERT OR IGNORE INTO counters(k,n) VALUES(?,0)", (key,))
    c.execute("UPDATE counters SET n=n+1 WHERE k=?", (key,))
    return c.execute("SELECT n FROM counters WHERE k=?", (key,)).fetchone()["n"]


class VoidIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


@router.post("/api/acc/bills/{bid}/void")
def api_bill_void(bid: int, b: VoidIn, u=Depends(act_as("accounting_approve"))):
    c = db()
    row = c.execute("SELECT * FROM ap_bills WHERE id=?", (bid,)).fetchone()
    if not row or row["status"] not in ("draft", "approved"):
        raise HTTPException(409, "تُلغى المسودة أو الفاتورة المعتمدة غير المسدَّدة")
    if row["paid"] > EPS:
        raise HTTPException(409, "عليها مدفوعات — اعكس الدفعات أولًا")
    rid = None
    if row["journal_id"]:
        rid = ledger.reverse(c, row["journal_id"], today(), f"إلغاء فاتورة {row['number']}: {b.reason}", u["name"])
    c.execute("UPDATE ap_bills SET status='void', void_reason=?, void_journal_id=? WHERE id=?", (b.reason, rid, bid))
    audit(c, "إلغاء فاتورة مورّد", f"{row['number'] or '#' + str(bid)} · {b.reason}")
    c.commit()
    return {"ok": True}


def refresh_bill(c, bid: int) -> None:
    b = c.execute("SELECT total, status FROM ap_bills WHERE id=?", (bid,)).fetchone()
    paid = r3(c.execute("SELECT COALESCE(SUM(amount),0) FROM ap_payments WHERE bill_id=?", (bid,)).fetchone()[0])
    st = "paid" if paid >= b["total"] - EPS else "partly_paid" if paid > EPS else "approved"
    c.execute("UPDATE ap_bills SET paid=?, status=? WHERE id=?", (paid, st, bid))


# ----------------------------------------------------------------------------------------------------- payment orders → payments
class OrderIn(BaseModel):
    bill_id: int
    amount: float = Field(gt=0, le=1_000_000_000)
    method: Literal["cash", "transfer", "cheque", "card"]
    bank_account_id: int
    reference: str = Field(default="", max_length=80)
    cheque_number: str = Field(default="", max_length=30)
    cheque_due: dt.date | None = None


@router.get("/api/acc/orders")
def api_orders(status: str | None = None, _=Depends(need("accounting"))):
    c = db()
    over = setting_f(c, "ap_dual_over", 5000)
    out = rows(c.execute("""SELECT o.*, v.name vendor, b.number bill_number, k.name bank FROM payment_orders o JOIN vendors v ON v.id=o.vendor_id JOIN ap_bills b ON b.id=o.bill_id
                            JOIN bank_accounts k ON k.id=o.bank_account_id WHERE 1=1""" + (" AND o.status=?" if status else "") + " ORDER BY o.id DESC LIMIT 300", ((status,) if status else ())))
    for x in out:
        x["needs_second"] = x["amount"] >= over
    return out


@router.post("/api/acc/orders")
def api_order_add(b: OrderIn, u=Depends(act_as("accounting"))):
    c = db()
    _active(c)
    bill = c.execute("SELECT * FROM ap_bills WHERE id=?", (b.bill_id,)).fetchone()
    if not bill or bill["status"] not in ("approved", "partly_paid"):
        raise HTTPException(409, "تُدفع الفاتورة المعتمدة غير المسدَّدة فقط")
    pending = c.execute("SELECT COALESCE(SUM(amount),0) FROM payment_orders WHERE bill_id=? AND status IN ('pending','approved')", (b.bill_id,)).fetchone()[0]
    if r3(b.amount + pending) > r3(bill["total"] - bill["paid"]) + EPS:
        raise HTTPException(409, f"المبلغ (مع الأوامر المعلّقة) يتجاوز المتبقي {r3(bill['total'] - bill['paid']):,.3f}")
    bank = c.execute("SELECT * FROM bank_accounts WHERE id=? AND active=1", (b.bank_account_id,)).fetchone()
    if not bank:
        raise HTTPException(400, "الحساب البنكي غير موجود أو موقوف")
    if b.method == "cheque" and not b.cheque_number.strip():
        raise HTTPException(400, "رقم الشيك مطلوب")
    year = today().year
    number = f"PO-{year}-{ledger_no(c, f'porder:{year}'):04d}"
    oid = c.execute("""INSERT INTO payment_orders(number,bill_id,vendor_id,amount,method,bank_account_id,reference,cheque_number,cheque_due,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (number, b.bill_id, bill["vendor_id"], r3(b.amount), b.method, b.bank_account_id, b.reference or None, b.cheque_number.strip() or None,
                     b.cheque_due.isoformat() if b.cheque_due else None, u["name"])).lastrowid
    audit(c, "أمر دفع", f"{number} · {r3(b.amount):,.3f} ر.ع · فاتورة {bill['number']}")
    c.commit()
    return {"id": oid, "number": number}


@router.post("/api/acc/orders/{oid}/approve")
def api_order_approve(oid: int, u=Depends(act_as("accounting_approve"))):
    """First approval, and the second one when the amount reaches the dual-control limit. The creator never approves; one person never approves twice."""
    c = db()
    o = c.execute("SELECT * FROM payment_orders WHERE id=?", (oid,)).fetchone()
    if not o or o["status"] != "pending":
        raise HTTPException(409, "لا أمر دفع بانتظار الاعتماد")
    if o["created_by"] == u["name"]:
        raise HTTPException(403, "لا يعتمد المُنشئ أمر الدفع الذي أنشأه")
    over = setting_f(c, "ap_dual_over", 5000)
    if not o["approver1"]:
        c.execute("UPDATE payment_orders SET approver1=?, approver1_at=?, status=? WHERE id=?", (u["name"], now_s(), "approved" if o["amount"] < over else "pending", oid))
    else:
        if o["approver1"] == u["name"]:
            raise HTTPException(403, "الاعتماد الثاني من شخص آخر")
        c.execute("UPDATE payment_orders SET approver2=?, approver2_at=?, status='approved' WHERE id=?", (u["name"], now_s(), oid))
    audit(c, "اعتماد أمر دفع", f"{o['number']} · {o['amount']:,.3f} ر.ع")
    c.commit()
    return {"status": c.execute("SELECT status FROM payment_orders WHERE id=?", (oid,)).fetchone()["status"]}


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=300)


@router.post("/api/acc/orders/{oid}/reject")
def api_order_reject(oid: int, b: RejectIn, u=Depends(act_as("accounting_approve"))):
    c = db()
    o = c.execute("SELECT * FROM payment_orders WHERE id=?", (oid,)).fetchone()
    if not o or o["status"] not in ("pending", "approved"):
        raise HTTPException(409, "لا يُرفض إلا أمر لم يُنفَّذ")
    c.execute("UPDATE payment_orders SET status='rejected', reject_note=? WHERE id=?", (b.note, oid))
    audit(c, "رفض أمر دفع", f"{o['number']} · {b.note}")
    c.commit()
    return {"ok": True}


class ExecIn(BaseModel):
    paid_on: dt.date | None = None


@router.post("/api/acc/orders/{oid}/execute")
def api_order_execute(oid: int, b: ExecIn, u=Depends(act_as("accounting"))):
    c = db()
    start = _active(c)
    o = c.execute("SELECT * FROM payment_orders WHERE id=?", (oid,)).fetchone()
    if not o or o["status"] != "approved":
        raise HTTPException(409, "لا يُنفَّذ إلا أمر معتمد")
    day = b.paid_on or today()
    if day > today() or day.isoformat() < start:
        raise HTTPException(400, "تاريخ الدفع غير صالح")
    bill = c.execute("SELECT * FROM ap_bills WHERE id=?", (o["bill_id"],)).fetchone()
    if bill["status"] not in ("approved", "partly_paid") or r3(o["amount"]) > r3(bill["total"] - bill["paid"]) + EPS:
        raise HTTPException(409, "تغيّر رصيد الفاتورة — أنشئ أمرًا جديدًا")
    bank = c.execute("SELECT * FROM bank_accounts WHERE id=?", (o["bank_account_id"],)).fetchone()
    try:
        jid = ledger.post(c, date=day, memo=f"سداد فاتورة {bill['number']} — أمر {o['number']} — {o['method']} {o['reference'] or ''}".strip(), source_kind="appay", source_ref=str(oid),
                          source_key=f"appay:{oid}", by=u["name"], kind="auto",
                          lines=[dict(account="ap_vendors", debit=o["amount"], party_type="vendor", party_id=o["vendor_id"]), dict(account=bank["account_id"], credit=o["amount"])])
    except ledger.LedgerError as e:
        raise HTTPException(409, str(e)) from None
    cheque_id = None
    if o["method"] == "cheque":
        cheque_id = c.execute("""INSERT INTO cheques(direction,number,bank,amount,due_date,received_on,status,payee,vendor_id,journal_id,created_by) VALUES('out',?,?,?,?,?,'issued',?,?,?,?)""",
                              (o["cheque_number"], bank["name"], o["amount"], o["cheque_due"] or day.isoformat(), day.isoformat(),
                               c.execute("SELECT name FROM vendors WHERE id=?", (o["vendor_id"],)).fetchone()["name"], o["vendor_id"], jid, u["name"])).lastrowid
    pid = c.execute("""INSERT INTO ap_payments(bill_id,vendor_id,amount,paid_on,method,bank_account_id,cheque_id,reference,order_id,journal_id,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (o["bill_id"], o["vendor_id"], o["amount"], day.isoformat(), o["method"], o["bank_account_id"], cheque_id, o["reference"], oid, jid, u["name"])).lastrowid
    c.execute("UPDATE payment_orders SET status='executed', executed_at=?, payment_id=? WHERE id=?", (now_s(), pid, oid))
    refresh_bill(c, o["bill_id"])
    audit(c, "تنفيذ أمر دفع", f"{o['number']} · {o['amount']:,.3f} ر.ع")
    c.commit()
    return {"payment_id": pid, "journal_id": jid, "cheque_id": cheque_id}


@router.post("/api/acc/payments/{pid}/reverse")
def api_payment_reverse(pid: int, b: VoidIn, u=Depends(act_as("accounting_approve"))):
    c = db()
    p = c.execute("SELECT * FROM ap_payments WHERE id=?", (pid,)).fetchone()
    if not p or p["amount"] <= 0:
        raise HTTPException(404, "الدفعة غير موجودة")
    if c.execute("SELECT 1 FROM ap_payments WHERE reverses_id=?", (pid,)).fetchone():
        raise HTTPException(409, "عُكست هذه الدفعة سابقًا")
    rid = ledger.reverse(c, p["journal_id"], today(), f"عكس دفعة مورّد: {b.reason}", u["name"])
    c.execute("""INSERT INTO ap_payments(bill_id,vendor_id,amount,paid_on,method,bank_account_id,cheque_id,reference,order_id,journal_id,reverses_id,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
              (p["bill_id"], p["vendor_id"], -p["amount"], today().isoformat(), p["method"], p["bank_account_id"], p["cheque_id"], b.reason, p["order_id"], rid, pid, u["name"]))
    if p["cheque_id"]:
        c.execute("UPDATE cheques SET status='cancelled', bounce_reason=? WHERE id=? AND direction='out' AND status='issued'", (b.reason, p["cheque_id"]))
    refresh_bill(c, p["bill_id"])
    audit(c, "عكس دفعة مورّد", f"#{pid} · {b.reason}")
    c.commit()
    return {"journal_id": rid}


# ----------------------------------------------------------------------------------------------------- reports
@router.get("/api/acc/ap-aging")
def api_ap_aging(as_of: str | None = None, _=Depends(need("accounting"))):
    """What is owed to suppliers by how long it is overdue (days past the due date; a bill with no due date ages from its bill date)."""
    c = db()
    day = dt.date.fromisoformat(as_of) if as_of else today()
    buckets = {"current": 0.0, "d1_30": 0.0, "d31_60": 0.0, "d61_90": 0.0, "d90p": 0.0}
    items = []
    for b in c.execute("""SELECT b.*, v.name vendor FROM ap_bills b JOIN vendors v ON v.id=b.vendor_id WHERE b.status IN ('approved','partly_paid') AND b.bill_date<=? ORDER BY b.due_date""", (day.isoformat(),)).fetchall():
        left = r3(b["total"] - b["paid"])
        if left <= EPS:
            continue
        late = (day - dt.date.fromisoformat(b["due_date"] or b["bill_date"])).days
        k = "current" if late <= 0 else "d1_30" if late <= 30 else "d31_60" if late <= 60 else "d61_90" if late <= 90 else "d90p"
        buckets[k] = r3(buckets[k] + left)
        items.append({"id": b["id"], "number": b["number"], "vendor": b["vendor"], "due_date": b["due_date"], "outstanding": left, "days_late": max(late, 0), "bucket": k})
    return {"as_of": day.isoformat(), "buckets": buckets, "total": r3(sum(buckets.values())), "items": items}
