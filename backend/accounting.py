"""Mabaniq 0.23.0 — accounting core, the HTTP surface (design §4, phase 3a): activation, chart of accounts, cost centres, periods, manual journals with
maker-checker approval, the opening balance, trial balance, account ledger and party statement. The engine is `ledger.py`.

Rules kept on purpose:
* Nothing posts until an administrator activates accounting with a start date (events before it are the opening balance, entered from a documented trial balance).
* A manual journal is drafted by one person and approved by another (an administrator may approve their own); above `acc_attach_over` OMR it needs an attachment.
* A posted journal is never edited: it is reversed by a mirror journal. Automatic journals are never reversed by hand — the cause is corrected at its source.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import ledger
from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .db import setting_f

router = APIRouter()
r3 = ledger.r3
EPS = ledger.EPS
PARTY_TYPES = ("tenant", "owner", "vendor", "customer")
# the system keys the posting rules use, and what each is for (shown on the set-up screen so the mapping can be reviewed and changed)
MAPPING = (("cash", "الصندوق — مقبوضات نقدية"), ("bank_main", "البنك الجاري — تحويل وشيك وبطاقة وصرف"), ("bank_charity", "بنك التبرعات الخيرية"),
           ("receipts_unclassified", "مقبوضات لم تُوثَّق طريقة سدادها"), ("ar_tenants", "ذمم المستأجرين"), ("ap_vendors", "ذمم الموردين"),
           ("ap_owners", "أموال الملاك المُدارة"), ("deposits_held", "تأمينات المستأجرين"), ("charity_payable", "تبرعات التأخير المستحقة"),
           ("rev_rent", "إيراد الإيجار"), ("rev_recoveries", "استردادات من المستأجرين"), ("rev_other", "إيرادات أخرى"), ("rev_mgmt_fee", "عمولة الإدارة"),
           ("exp_maint", "صيانة"), ("exp_clean", "نظافة"), ("exp_utilities", "مرافق"), ("exp_security", "أمن"), ("exp_takaful", "تكافل"),
           ("exp_marketing", "تسويق"), ("exp_property_other", "مصروفات عقارية أخرى"))


def _need_active(c) -> str:
    s = ledger.start_date(c)
    if not s:
        raise HTTPException(409, "المحاسبة غير مفعَّلة بعد — فعّلها من «الإعداد» بتاريخ بدء")
    return s


def _d(v, what="التاريخ") -> dt.date:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(400, f"{what} غير صالح") from None


def _csv(name: str, header: list, data: list) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(data)
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ----------------------------------------------------------------------------------------------------- status and activation
@router.get("/api/acc/status")
def api_status(_=Depends(need("accounting"))):
    c = db()
    start = ledger.start_date(c)
    out = {"start": start, "active": bool(start), "accounts": c.execute("SELECT COUNT(*) FROM acc_accounts").fetchone()[0], "journals": {}, "unposted": None,
           "ledger_diff": 0.0, "opening": None, "attach_over": setting_f(c, "acc_attach_over", 1000)}
    for r in c.execute("SELECT status, COUNT(*) n FROM acc_journals GROUP BY status").fetchall():
        out["journals"][r["status"]] = r["n"]
    d = c.execute("""SELECT COALESCE(SUM(l.debit),0) - COALESCE(SUM(l.credit),0) FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id WHERE j.status IN ('posted','reversed')""").fetchone()[0]
    out["ledger_diff"] = r3(d)
    o = c.execute("SELECT id, number, jdate FROM acc_journals WHERE kind='opening' AND status='posted'").fetchone()
    out["opening"] = dict(o) if o else None
    if start:
        res = ledger.autopost(c, dry=True)
        out["unposted"] = {"counts": res["pending"], "total": sum(res["pending"].values())}
    return out


class ActivateIn(BaseModel):
    start: dt.date
    confirm: bool = False


@router.post("/api/acc/activate")
def api_activate(b: ActivateIn, u=Depends(act_as("accounting_approve"))):
    if not b.confirm:
        raise HTTPException(400, "أكّد التفعيل: لا تُرحَّل الأحداث السابقة لتاريخ البدء — هي الرصيد الافتتاحي")
    if b.start > today():
        raise HTTPException(400, "تاريخ بدء المحاسبة لا يكون في المستقبل")
    c = db()
    out = ledger.activate(c, b.start, u["name"])
    c.commit()
    return out


@router.post("/api/acc/sync")
def api_sync(u=Depends(act_as("accounting"))):
    """Carry every leasing event the ledger is missing (idempotent). Problems are returned, never hidden."""
    c = db()
    _need_active(c)
    res = ledger.autopost(c)
    audit(c, "ترحيل أحداث التأجير إلى الدفتر", f"قيود جديدة: {sum(res['posted'].values())} · أخطاء: {len(res['errors'])}")
    c.commit()
    return res


@router.get("/api/acc/mapping")
def api_mapping(_=Depends(need("accounting"))):
    c = db()
    keys = {r["system_key"]: dict(r) for r in c.execute("SELECT id, code, name, active, postable, system_key FROM acc_accounts WHERE system_key IS NOT NULL").fetchall()}
    return [{"key": k, "purpose": p, "account": keys.get(k)} for k, p in MAPPING]


# ----------------------------------------------------------------------------------------------------- chart of accounts
@router.get("/api/acc/accounts")
def api_accounts(balances: int = 0, _=Depends(need("accounting"))):
    c = db()
    accs = rows(c.execute("SELECT * FROM acc_accounts ORDER BY code"))
    if balances:
        bal = {r["account_id"]: r["b"] for r in c.execute("""SELECT l.account_id, SUM(l.debit - l.credit) b FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id
                                                             WHERE j.status IN ('posted','reversed') GROUP BY l.account_id""").fetchall()}
        for a in accs:
            a["balance"] = r3(bal.get(a["id"], 0))
    used = {r[0] for r in c.execute("SELECT DISTINCT account_id FROM acc_lines").fetchall()}
    for a in accs:
        a["used"] = a["id"] in used
    return accs


class AccountIn(BaseModel):
    code: str = Field(min_length=2, max_length=12, pattern=r"^[0-9A-Za-z\-\.]+$")
    name: str = Field(min_length=2, max_length=120)
    name_en: str = Field(default="", max_length=120)
    type: Literal["asset", "liability", "equity", "revenue", "expense"]
    parent_id: int | None = None
    postable: bool = True
    normal: Literal["debit", "credit"] | None = None
    vat_class: Literal["standard", "zero", "exempt", "out_of_scope"] | None = None
    cash_class: Literal["cash", "operating", "investing", "financing"] | None = None
    note: str = Field(default="", max_length=300)


@router.post("/api/acc/accounts")
def api_account_add(b: AccountIn, u=Depends(act_as("accounting_approve"))):
    c = db()
    _need_active(c)
    if c.execute("SELECT 1 FROM acc_accounts WHERE code=?", (b.code,)).fetchone():
        raise HTTPException(409, "رمز الحساب مستعمل")
    if b.parent_id:
        p = c.execute("SELECT type FROM acc_accounts WHERE id=?", (b.parent_id,)).fetchone()
        if not p or p["type"] != b.type:
            raise HTTPException(400, "الحساب الأب غير موجود أو من نوع مختلف")
    normal = b.normal or ("debit" if b.type in ("asset", "expense") else "credit")
    aid = c.execute("INSERT INTO acc_accounts(code,name,name_en,type,parent_id,postable,normal,vat_class,cash_class,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (b.code, b.name, b.name_en or None, b.type, b.parent_id, int(b.postable), normal, b.vat_class, b.cash_class, b.note or None)).lastrowid
    audit(c, "حساب جديد", f"{b.code} {b.name}")
    c.commit()
    return {"id": aid}


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    name_en: str | None = Field(default=None, max_length=120)
    active: bool | None = None
    system_key: str | None = Field(default=None, max_length=40)
    vat_class: Literal["standard", "zero", "exempt", "out_of_scope", ""] | None = None
    cash_class: Literal["cash", "operating", "investing", "financing", ""] | None = None
    note: str | None = Field(default=None, max_length=300)


@router.patch("/api/acc/accounts/{aid}")
def api_account_patch(aid: int, b: AccountPatch, u=Depends(act_as("accounting_approve"))):
    c = db()
    a = c.execute("SELECT * FROM acc_accounts WHERE id=?", (aid,)).fetchone()
    if not a:
        raise HTTPException(404, "الحساب غير موجود")
    sets, args = [], []
    for col in ("name", "name_en", "note"):
        v = getattr(b, col)
        if v is not None:
            sets.append(f"{col}=?")
            args.append(v)
    for col in ("vat_class", "cash_class"):
        v = getattr(b, col)
        if v is not None:
            sets.append(f"{col}=?")
            args.append(v or None)
    if b.system_key is not None:
        key = b.system_key.strip() or None
        if key:
            holder = c.execute("SELECT code FROM acc_accounts WHERE system_key=? AND id<>?", (key, aid)).fetchone()
            if holder:
                raise HTTPException(409, f"المفتاح «{key}» مربوط بالحساب {holder['code']} — فُكّ ربطه أولًا")
            if not a["postable"]:
                raise HTTPException(400, "لا يُربط حدث بحساب تجميعي غير قابل للترحيل")
        elif a["system_key"]:
            sets.append("system_key=?")
            args.append(None)
        if key:
            sets.append("system_key=?")
            args.append(key)
    if b.active is not None:
        if not b.active and a["system_key"] and b.system_key is None:
            raise HTTPException(409, "الحساب مربوط بحدث تلقائي — أعد الربط قبل إيقافه")
        sets.append("active=?")
        args.append(int(b.active))
    if sets:
        c.execute(f"UPDATE acc_accounts SET {', '.join(sets)} WHERE id=?", (*args, aid))
        audit(c, "تعديل حساب", f"{a['code']} {a['name']}")
        c.commit()
    return {"ok": True}


@router.get("/api/acc/cost-centers")
def api_ccs(_=Depends(need("accounting"))):
    return rows(db().execute("SELECT * FROM acc_cost_centers ORDER BY code"))


class CostCenterIn(BaseModel):
    code: str = Field(min_length=2, max_length=12, pattern=r"^[0-9A-Za-z\-\.]+$")
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["property", "project", "dept", "other"] = "other"


@router.post("/api/acc/cost-centers")
def api_cc_add(b: CostCenterIn, u=Depends(act_as("accounting_approve"))):
    c = db()
    if c.execute("SELECT 1 FROM acc_cost_centers WHERE code=?", (b.code,)).fetchone():
        raise HTTPException(409, "رمز مركز الكلفة مستعمل")
    cid = c.execute("INSERT INTO acc_cost_centers(code,name,kind) VALUES(?,?,?)", (b.code, b.name, b.kind)).lastrowid
    audit(c, "مركز كلفة جديد", f"{b.code} {b.name}")
    c.commit()
    return {"id": cid}


# ----------------------------------------------------------------------------------------------------- periods
@router.get("/api/acc/periods")
def api_periods(_=Depends(need("accounting"))):
    c = db()
    return rows(c.execute("""SELECT p.*, (SELECT COUNT(*) FROM acc_journals j WHERE j.period_id=p.id AND j.status IN ('posted','reversed')) journals,
                                    (SELECT COUNT(*) FROM acc_journals j WHERE j.period_id=p.id AND j.status IN ('draft','pending')) open_journals
                             FROM acc_periods p ORDER BY year DESC, month DESC"""))


class ReopenIn(BaseModel):
    reason: str = Field(default="", max_length=300)


@router.post("/api/acc/periods/{year}/{month}/close")
def api_period_close(year: int, month: int, u=Depends(act_as("accounting_approve"))):
    c = db()
    _need_active(c)
    if not 1 <= month <= 12:
        raise HTTPException(400, "شهر غير صالح")
    p = ledger.period_for(c, dt.date(year, month, 1))
    if p["status"] == "closed":
        raise HTTPException(409, "الفترة مقفلة أصلًا")
    if c.execute("SELECT 1 FROM acc_journals WHERE period_id=? AND status IN ('draft','pending')", (p["id"],)).fetchone():
        raise HTTPException(409, "في الفترة قيود مسودة أو بانتظار الاعتماد — اعتمدها أو احذفها أولًا")
    c.execute("UPDATE acc_periods SET status='closed', closed_by=?, closed_at=? WHERE id=?", (u["name"], now_s(), p["id"]))
    audit(c, "إقفال فترة محاسبية", f"{year}-{month:02d}")
    c.commit()
    return {"ok": True}


@router.post("/api/acc/periods/{year}/{month}/reopen")
def api_period_reopen(year: int, month: int, b: ReopenIn, u=Depends(act_as("accounting_approve"))):
    c = db()
    if len(b.reason.strip()) < 8:
        raise HTTPException(400, "اكتب سبب إعادة الفتح (8 أحرف على الأقل) — يُدقَّق")
    p = c.execute("SELECT * FROM acc_periods WHERE year=? AND month=?", (year, month)).fetchone()
    if not p or p["status"] != "closed":
        raise HTTPException(409, "الفترة ليست مقفلة")
    c.execute("UPDATE acc_periods SET status='open', reopened_by=?, reopened_at=?, reopen_reason=? WHERE id=?", (u["name"], now_s(), b.reason.strip(), p["id"]))
    audit(c, "إعادة فتح فترة محاسبية", f"{year}-{month:02d} · {b.reason.strip()}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- journals
class LineIn(BaseModel):
    account: int | str
    debit: float = Field(default=0, ge=0, le=1_000_000_000)
    credit: float = Field(default=0, ge=0, le=1_000_000_000)
    cost_center_id: int | None = None
    party_type: Literal["tenant", "owner", "vendor", "customer"] | None = None
    party_id: int | None = None
    memo: str = Field(default="", max_length=200)


class JournalIn(BaseModel):
    date: dt.date
    memo: str = Field(min_length=3, max_length=300)
    lines: list[LineIn] = Field(min_length=2, max_length=200)


def _account_id(c, ref) -> int:
    r = c.execute("SELECT id, code, postable, active FROM acc_accounts WHERE id=?" if isinstance(ref, int) else "SELECT id, code, postable, active FROM acc_accounts WHERE code=?", (ref,)).fetchone()
    if not r:
        raise HTTPException(400, f"الحساب {ref} غير موجود")
    if not r["postable"] or not r["active"]:
        raise HTTPException(400, f"الحساب {r['code']} غير قابل للترحيل أو موقوف")
    return r["id"]


def _lines(c, b: JournalIn) -> list[dict]:
    out = []
    for ln in b.lines:
        if ln.party_id and not ln.party_type:
            raise HTTPException(400, "حدّد نوع الطرف")
        out.append({"account": _account_id(c, ln.account), "debit": ln.debit, "credit": ln.credit, "cc": ln.cost_center_id, "party_type": ln.party_type,
                    "party_id": ln.party_id, "memo": ln.memo or None})
    return out


def _check_date(c, d: dt.date, start: str) -> None:
    if d.isoformat() < start:
        raise HTTPException(400, f"التاريخ يسبق بدء المحاسبة ({start}) — ما قبله في الرصيد الافتتاحي")
    if d > today():
        raise HTTPException(400, "تاريخ القيد لا يكون في المستقبل")


def _party_names(c, ls: list[dict]) -> None:
    tables = {"tenant": "tenants_l", "owner": "owners", "vendor": "vendors", "customer": "customers"}
    for ln in ls:
        if ln["party_type"] in tables and ln["party_id"]:
            r = c.execute(f"SELECT name FROM {tables[ln['party_type']]} WHERE id=?", (ln["party_id"],)).fetchone()
            ln["party_name"] = r["name"] if r else None


def journal_out(c, jid: int) -> dict:
    j = c.execute("SELECT * FROM acc_journals WHERE id=?", (jid,)).fetchone()
    if not j:
        raise HTTPException(404, "القيد غير موجود")
    out = dict(j)
    out["lines"] = rows(c.execute("""SELECT l.*, a.code account_code, a.name account_name, cc.code cc_code, cc.name cc_name FROM acc_lines l JOIN acc_accounts a ON a.id=l.account_id
                                     LEFT JOIN acc_cost_centers cc ON cc.id=l.cost_center_id WHERE l.journal_id=? ORDER BY l.line_no""", (jid,)))
    _party_names(c, out["lines"])
    out["attachments"] = rows(c.execute("SELECT id, title, filename, size, sha256, uploaded_by, at FROM documents WHERE ref_type='journal' AND ref_id=? ORDER BY id", (jid,)))
    return out


@router.get("/api/acc/journals")
def api_journals(status: str | None = None, kind: str | None = None, q: str = Query("", max_length=60), frm: str | None = None, to: str | None = None,
                 limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), _=Depends(need("accounting"))):
    c = db()
    where, args = ["1=1"], []
    if status:
        where.append("j.status=?")
        args.append(status)
    if kind:
        where.append("j.kind=?")
        args.append(kind)
    if q:
        where.append("(j.number LIKE ? OR j.memo LIKE ?)")
        args += [f"%{q}%", f"%{q}%"]
    if frm:
        where.append("j.jdate>=?")
        args.append(frm)
    if to:
        where.append("j.jdate<=?")
        args.append(to)
    w = " AND ".join(where)
    total = c.execute(f"SELECT COUNT(*) FROM acc_journals j WHERE {w}", args).fetchone()[0]
    items = rows(c.execute(f"SELECT j.* FROM acc_journals j WHERE {w} ORDER BY j.jdate DESC, j.id DESC LIMIT ? OFFSET ?", (*args, limit, offset)))
    return {"total": total, "items": items}


@router.get("/api/acc/journals/{jid}")
def api_journal(jid: int, _=Depends(need("accounting"))):
    return journal_out(db(), jid)


@router.post("/api/acc/journals")
def api_journal_add(b: JournalIn, u=Depends(act_as("accounting"))):
    c = db()
    start = _need_active(c)
    _check_date(c, b.date, start)
    try:
        jid = ledger.insert_draft(c, ledger.Ctx(c), d=b.date, memo=b.memo, lines=_lines(c, b), kind="manual", by=u["name"])
    except ledger.LedgerError as e:
        raise HTTPException(400, str(e)) from None
    audit(c, "قيد يدوي (مسودة)", f"#{jid} · {b.memo}")
    c.commit()
    return {"id": jid}


def _draft(c, jid: int, u: dict) -> dict:
    j = c.execute("SELECT * FROM acc_journals WHERE id=?", (jid,)).fetchone()
    if not j:
        raise HTTPException(404, "القيد غير موجود")
    if j["status"] != "draft" or j["kind"] != "manual":
        raise HTTPException(409, "تُعدَّل المسودة اليدوية فقط")
    if j["created_by"] != u["name"] and "accounting_approve" not in u["perms"]:
        raise HTTPException(403, "المسودة لغيرك")
    return dict(j)


@router.put("/api/acc/journals/{jid}")
def api_journal_edit(jid: int, b: JournalIn, u=Depends(act_as("accounting"))):
    c = db()
    start = _need_active(c)
    _draft(c, jid, u)
    _check_date(c, b.date, start)
    ctx = ledger.Ctx(c)
    try:
        ls = ledger._norm_lines(ctx, _lines(c, b))
    except ledger.LedgerError as e:
        raise HTTPException(400, str(e)) from None
    c.execute("DELETE FROM acc_lines WHERE journal_id=?", (jid,))
    for i, x in enumerate(ls, 1):
        c.execute("INSERT INTO acc_lines(journal_id,line_no,account_id,cost_center_id,debit,credit,party_type,party_id,vat_class,memo) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (jid, i, x["account_id"], x["cost_center_id"], x["debit"], x["credit"], x["party_type"], x["party_id"], x["vat_class"], x["memo"]))
    c.execute("UPDATE acc_journals SET jdate=?, period_id=?, memo=?, total=?, reject_note=NULL WHERE id=?",
              (b.date.isoformat(), ledger.period_for(c, b.date)["id"], b.memo, r3(sum(x["debit"] for x in ls)), jid))
    audit(c, "تعديل مسودة قيد", f"#{jid}")
    c.commit()
    return {"ok": True}


@router.delete("/api/acc/journals/{jid}")
def api_journal_del(jid: int, u=Depends(act_as("accounting"))):
    c = db()
    _draft(c, jid, u)
    c.execute("DELETE FROM acc_lines WHERE journal_id=?", (jid,))
    c.execute("DELETE FROM acc_journals WHERE id=?", (jid,))
    audit(c, "حذف مسودة قيد", f"#{jid}")
    c.commit()
    return {"ok": True}


@router.post("/api/acc/journals/{jid}/submit")
def api_journal_submit(jid: int, u=Depends(act_as("accounting"))):
    c = db()
    j = _draft(c, jid, u)
    _need_attachment(c, j)
    c.execute("UPDATE acc_journals SET status='pending', submitted_by=? WHERE id=?", (u["name"], jid))
    audit(c, "تقديم قيد للاعتماد", f"#{jid} · {j['total']:,.3f} ر.ع")
    c.commit()
    return {"ok": True}


def _need_attachment(c, j: dict) -> None:
    over = setting_f(c, "acc_attach_over", 1000)
    if j["total"] >= over and not c.execute("SELECT 1 FROM documents WHERE ref_type='journal' AND ref_id=?", (j["id"],)).fetchone():
        raise HTTPException(409, f"القيد بمبلغ {j['total']:,.3f} ر.ع (الحد {over:,.0f}) ويلزمه مستند مرفق — ارفعه من نافذة القيد")


@router.post("/api/acc/journals/{jid}/approve")
def api_journal_approve(jid: int, u=Depends(act_as("accounting_approve"))):
    c = db()
    j = c.execute("SELECT * FROM acc_journals WHERE id=?", (jid,)).fetchone()
    if not j or j["kind"] != "manual" or j["status"] not in ("draft", "pending"):
        raise HTTPException(409, "يُعتمد القيد اليدوي المقدَّم فقط")
    is_admin = u["role"] == "admin"
    if j["status"] == "draft" and not is_admin:
        raise HTTPException(409, "قدّم القيد للاعتماد أولًا")
    if j["created_by"] == u["name"] and not is_admin:
        raise HTTPException(403, "لا يعتمد المُنشئ قيده بنفسه — يعتمده مدير آخر")
    _need_attachment(c, dict(j))
    try:
        number = ledger.finalize(c, jid, u["name"], approved_by=u["name"])
    except ledger.LedgerError as e:
        raise HTTPException(409, str(e)) from None
    audit(c, "اعتماد وترحيل قيد", f"{number} · {j['total']:,.3f} ر.ع")
    c.commit()
    return {"number": number}


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=300)


@router.post("/api/acc/journals/{jid}/reject")
def api_journal_reject(jid: int, b: RejectIn, u=Depends(act_as("accounting_approve"))):
    c = db()
    j = c.execute("SELECT * FROM acc_journals WHERE id=? AND status='pending' AND kind='manual'", (jid,)).fetchone()
    if not j:
        raise HTTPException(409, "لا قيد بانتظار الاعتماد بهذا الرقم")
    c.execute("UPDATE acc_journals SET status='draft', reject_note=? WHERE id=?", (b.note, jid))
    audit(c, "رفض قيد", f"#{jid} · {b.note}")
    c.commit()
    return {"ok": True}


class ReverseIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)
    on: dt.date | None = None


@router.post("/api/acc/journals/{jid}/reverse")
def api_journal_reverse(jid: int, b: ReverseIn, u=Depends(act_as("accounting_approve"))):
    c = db()
    j = c.execute("SELECT * FROM acc_journals WHERE id=?", (jid,)).fetchone()
    if not j:
        raise HTTPException(404, "القيد غير موجود")
    if j["kind"] not in ("manual", "opening"):
        raise HTTPException(409, "قيود الأحداث التلقائية لا تُعكس يدويًا — صحّح مصدرها (دفعة/استحقاق/مصروف) فيُرحَّل الفرق تلقائيًا")
    rid = ledger.reverse(c, jid, b.on or today(), b.reason, u["name"])
    c.commit()
    return {"id": rid}


class OpeningLine(BaseModel):
    code: str = Field(min_length=2, max_length=12)
    debit: float = Field(default=0, ge=0, le=1_000_000_000)
    credit: float = Field(default=0, ge=0, le=1_000_000_000)
    party_type: Literal["tenant", "owner", "vendor", "customer"] | None = None
    party_id: int | None = None


class OpeningIn(BaseModel):
    lines: list[OpeningLine] = Field(min_length=2, max_length=1000)
    source: str = Field(min_length=5, max_length=300)  # the document the figures come from — never a guess


@router.post("/api/acc/opening")
def api_opening(b: OpeningIn, u=Depends(act_as("accounting_approve"))):
    """One opening journal, dated the day before accounting starts, from a documented trial balance."""
    c = db()
    start = _need_active(c)
    if c.execute("SELECT 1 FROM acc_journals WHERE kind='opening' AND status='posted'").fetchone():
        raise HTTPException(409, "الرصيد الافتتاحي مرحَّل — اعكسه أولًا إن لزم التصحيح")
    d = dt.date.fromisoformat(start) - dt.timedelta(days=1)
    ls = [{"account": _account_id(c, x.code), "debit": x.debit, "credit": x.credit, "party_type": x.party_type, "party_id": x.party_id} for x in b.lines]
    try:
        jid = ledger.insert_draft(c, ledger.Ctx(c), d=d, memo=f"رصيد افتتاحي — {b.source}", lines=ls, kind="opening", by=u["name"])
        number = ledger.finalize(c, jid, u["name"], approved_by=u["name"])
    except ledger.LedgerError as e:
        raise HTTPException(400, str(e)) from None
    audit(c, "رصيد افتتاحي", f"{number} · {b.source}")
    c.commit()
    return {"id": jid, "number": number, "date": d.isoformat()}


# ----------------------------------------------------------------------------------------------------- reports
POSTED = "j.status IN ('posted','reversed')"


@router.get("/api/acc/trial-balance")
def api_trial_balance(to: str | None = None, frm: str | None = None, cc: int | None = None, csv_: int = Query(0, alias="csv"), _=Depends(need("accounting"))):
    """Opening (before `frm`) · movement (frm..to) · closing, per account, rolled up to the headers. Σ debit = Σ credit is reported, not assumed."""
    c = db()
    to_d = _d(to) if to else today()
    frm_d = _d(frm) if frm else dt.date(to_d.year, 1, 1)
    if frm_d > to_d:
        raise HTTPException(400, "بداية المدة بعد نهايتها")
    sub = f"SELECT l.account_id, j.jdate, l.debit, l.credit FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id WHERE {POSTED}"
    args: list = []
    if cc:
        sub += " AND l.cost_center_id=?"
        args.append(cc)
    q = f"""SELECT a.id, a.code, a.name, a.type, a.normal, a.postable, a.parent_id,
                   COALESCE(SUM(CASE WHEN x.jdate < ? THEN x.debit - x.credit END),0) opening,
                   COALESCE(SUM(CASE WHEN x.jdate >= ? AND x.jdate <= ? THEN x.debit END),0) debit,
                   COALESCE(SUM(CASE WHEN x.jdate >= ? AND x.jdate <= ? THEN x.credit END),0) credit
            FROM acc_accounts a LEFT JOIN ({sub}) x ON x.account_id=a.id GROUP BY a.id, a.code, a.name, a.type, a.normal, a.postable, a.parent_id ORDER BY a.code"""
    f, t = frm_d.isoformat(), to_d.isoformat()
    accs = rows(c.execute(q, (f, f, t, f, t, *args)))
    by_id = {a["id"]: a for a in accs}
    for a in accs:
        a["children"] = False
    for a in accs:  # roll leaf figures up to their headers
        p = by_id.get(a["parent_id"])
        while p:
            p["children"] = True
            p = by_id.get(p["parent_id"])
    leaf = [a for a in accs if a["postable"]]
    for a in accs:
        if not a["postable"]:
            a["opening"] = a["debit"] = a["credit"] = 0.0
    for a in leaf:
        p = by_id.get(a["parent_id"])
        while p:
            p["opening"] += a["opening"]
            p["debit"] += a["debit"]
            p["credit"] += a["credit"]
            p = by_id.get(p["parent_id"])
    for a in accs:
        a["closing"] = r3(a["opening"] + a["debit"] - a["credit"])
        a["opening"], a["debit"], a["credit"] = r3(a["opening"]), r3(a["debit"]), r3(a["credit"])
    accs = [a for a in accs if abs(a["opening"]) > EPS or abs(a["debit"]) > EPS or abs(a["credit"]) > EPS or abs(a["closing"]) > EPS]
    tot = {"opening": r3(sum(a["opening"] for a in leaf)), "debit": r3(sum(a["debit"] for a in leaf)), "credit": r3(sum(a["credit"] for a in leaf)),
           "closing": r3(sum(a["closing"] for a in leaf))}
    out = {"from": f, "to": t, "cost_center": cc, "accounts": accs, "totals": tot, "balanced": abs(tot["debit"] - tot["credit"]) <= EPS and abs(tot["opening"]) <= EPS}
    if csv_:
        return _csv(f"trial-balance-{t}.csv", ["الرمز", "الحساب", "النوع", "افتتاحي", "مدين", "دائن", "ختامي"],
                    [[a["code"], a["name"], a["type"], a["opening"], a["debit"], a["credit"], a["closing"]] for a in accs if a["postable"]])
    return out


def _descendants(c, aid: int) -> list[int]:
    ids, frontier = [aid], [aid]
    while frontier:
        ph = ",".join("?" * len(frontier))
        frontier = [r[0] for r in c.execute(f"SELECT id FROM acc_accounts WHERE parent_id IN ({ph})", frontier).fetchall()]
        ids += frontier
    return ids


@router.get("/api/acc/ledger/{aid}")
def api_ledger(aid: int, frm: str | None = None, to: str | None = None, cc: int | None = None, party_type: str | None = None, party_id: int | None = None,
               csv_: int = Query(0, alias="csv"), _=Depends(need("accounting"))):
    """The general ledger of one account (or a header and everything under it) with a running balance and the opening balance before `frm`."""
    c = db()
    a = c.execute("SELECT * FROM acc_accounts WHERE id=?", (aid,)).fetchone()
    if not a:
        raise HTTPException(404, "الحساب غير موجود")
    ids = _descendants(c, aid)
    ph = ",".join("?" * len(ids))
    base = f"FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id JOIN acc_accounts ac ON ac.id=l.account_id WHERE {POSTED} AND l.account_id IN ({ph})"
    args: list = list(ids)
    if cc:
        base += " AND l.cost_center_id=?"
        args.append(cc)
    if party_type:
        base += " AND l.party_type=? AND l.party_id=?"
        args += [party_type, party_id]
    frm_d, to_d = (_d(frm) if frm else None), _d(to) if to else today()
    opening = 0.0
    if frm_d:
        opening = r3(c.execute(f"SELECT COALESCE(SUM(l.debit - l.credit),0) {base} AND j.jdate < ?", (*args, frm_d.isoformat())).fetchone()[0])
        base += " AND j.jdate >= ?"
        args.append(frm_d.isoformat())
    base += " AND j.jdate <= ?"
    args.append(to_d.isoformat())
    lines = rows(c.execute(f"""SELECT j.id journal_id, j.number, j.jdate, j.memo journal_memo, j.kind, l.memo, l.debit, l.credit, l.party_type, l.party_id, ac.code account_code
                               {base} ORDER BY j.jdate, j.id, l.line_no""", args))
    run = opening
    for ln in lines:
        run = r3(run + ln["debit"] - ln["credit"])
        ln["balance"] = run
    out = {"account": {k: a[k] for k in ("id", "code", "name", "type", "normal", "postable")}, "from": frm_d.isoformat() if frm_d else None, "to": to_d.isoformat(),
           "opening": opening, "lines": lines, "debit": r3(sum(x["debit"] for x in lines)), "credit": r3(sum(x["credit"] for x in lines)), "closing": run}
    if csv_:
        return _csv(f"ledger-{a['code']}.csv", ["التاريخ", "القيد", "البيان", "مدين", "دائن", "الرصيد"],
                    [[ln["jdate"], ln["number"], ln["memo"] or ln["journal_memo"], ln["debit"], ln["credit"], ln["balance"]] for ln in lines])
    return out


@router.get("/api/acc/party/{ptype}/{pid}")
def api_party(ptype: str, pid: int, frm: str | None = None, to: str | None = None, _=Depends(need("accounting"))):
    """Everything posted against one tenant / owner / vendor, in date order, with the running balance (receivable positive, payable negative)."""
    c = db()
    if ptype not in PARTY_TYPES:
        raise HTTPException(400, "نوع الطرف غير معروف")
    args: list = [ptype, pid]
    where = f"{POSTED} AND l.party_type=? AND l.party_id=?"
    if frm:
        where += " AND j.jdate>=?"
        args.append(_d(frm).isoformat())
    if to:
        where += " AND j.jdate<=?"
        args.append(_d(to).isoformat())
    lines = rows(c.execute(f"""SELECT j.id journal_id, j.number, j.jdate, j.memo journal_memo, a.code account_code, a.name account_name, l.debit, l.credit FROM acc_lines l
                               JOIN acc_journals j ON j.id=l.journal_id JOIN acc_accounts a ON a.id=l.account_id WHERE {where} ORDER BY j.jdate, j.id, l.line_no""", args))
    run = 0.0
    for ln in lines:
        run = r3(run + ln["debit"] - ln["credit"])
        ln["balance"] = run
    return {"type": ptype, "id": pid, "lines": lines, "balance": run}
