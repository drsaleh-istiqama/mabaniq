"""Mabaniq 0.26.0 — human resources: payroll (design docs/DESIGN-leasing-accounting-hr-modules.md §5.3, phase 4b).

Salary structures carry an effective date; a monthly run is created, computed, then approved by a *different* person with `hr_payroll` (the person who computed it never
approves it) and from then on its payslips are frozen by the database itself. Social-insurance rates and the day divisor are rows in `hr_rates` that start UNSET: a payslip
for an employee covered by PASI cannot be approved while a rate is missing — nothing is guessed. Staff advances and qard hasan loans have no rate, fee or profit field at all.

Everything here needs `hr_payroll` (admin and the payroll officer); an employee reads only his own payslips and salary through `/api/hr/me/*`. Maker and checker are compared
by *username* (stored in the `*_by` columns of this module), not by display name.
"""
from __future__ import annotations

import calendar
import csv
import datetime as dt
import hashlib
import io
import json
import math
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from . import ledger, pii
from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .hr import employee, own_employee, pdate
from .modules import one

router = APIRouter()
r3 = ledger.r3
EPS = ledger.EPS
PERIOD_RE = r"^\d{4}-(0[1-9]|1[0-2])$"
RATE_KEYS = {"pasi_employee_pct": ("حصة العامل من التأمينات ٪", 0, 50), "pasi_employer_pct": ("حصة صاحب العمل من التأمينات ٪", 0, 50),
             "pasi_ceiling": ("سقف الأجر الخاضع للتأمينات (ر.ع شهريًا)", 1, 1_000_000), "day_divisor": ("قاسم الأجر اليومي (أيام الشهر)", 20, 31)}
SEED_RATES = {"day_divisor": (30.0, "اصطلاح مبدئي: الأجر اليومي = الأجر الشهري ÷ 30 — يؤكده مختص بقانون العمل")}
SEED_COMPONENTS = (("basic", "الأجر الأساسي", 1, 1), ("housing", "بدل سكن", 0, 0), ("transport", "بدل مواصلات", 0, 0), ("other_allow", "بدلات أخرى", 0, 0))


# ----------------------------------------------------------------------------------------------------- setup, rates, components
def ensure_setup(c) -> None:
    """Seed once: the basic-wage component and a few allowances; the day divisor (provisional) and the PASI rates as UNSET rows."""
    if not c.execute("SELECT 1 FROM pay_components LIMIT 1").fetchone():
        for k, name, pb, sysf in SEED_COMPONENTS:
            c.execute("INSERT OR IGNORE INTO pay_components(key,name,kind,pasi_base,system) VALUES(?,?,'earning',?,?)", (k, name, pb, sysf))
    if not c.execute("SELECT 1 FROM hr_rates LIMIT 1").fetchone():
        for k in RATE_KEYS:
            v, note = SEED_RATES.get(k, (None, "لم تُدخَل بعد — لا يُحتسب ولا يُعتمد مسيّر لعامل خاضع للتأمينات قبل إدخالها"))
            c.execute("INSERT OR IGNORE INTO hr_rates(key,value,valid_from,provisional,note) VALUES(?,?,?,1,?)", (k, v, "2000-01-01", note))
    c.commit()


def rate_on(c, key: str, day: dt.date) -> float | None:
    r = c.execute("SELECT value FROM hr_rates WHERE key=? AND valid_from<=? ORDER BY valid_from DESC LIMIT 1", (key, day.isoformat())).fetchone()
    return None if not r or r["value"] is None else float(r["value"])


@router.get("/api/hr/payroll/rates")
def api_rates(_=Depends(need("hr_payroll"))):
    c = db()
    ensure_setup(c)
    out = rows(c.execute("SELECT * FROM hr_rates ORDER BY key, valid_from DESC"))
    seen = set()
    for r in out:
        r["label"] = RATE_KEYS.get(r["key"], (r["key"],))[0]
        r["current"] = r["key"] not in seen and r["valid_from"] <= today().isoformat()
        if r["current"]:
            seen.add(r["key"])
    return out


class RateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Literal["pasi_employee_pct", "pasi_employer_pct", "pasi_ceiling", "day_divisor"]
    value: float
    valid_from: str
    note: str = Field(default="", max_length=200)


@router.post("/api/hr/payroll/rates")
def api_rate_add(b: RateIn, u=Depends(act_as("hr_payroll"))):
    """A new version of a rate from `valid_from` on. Whoever enters it states its source in the note and takes responsibility — it is not provisional."""
    c = db()
    ensure_setup(c)
    label, lo, hi = RATE_KEYS[b.key]
    if not lo <= b.value <= hi:
        raise HTTPException(400, f"{label}: القيمة خارج المدى ({lo:g}–{hi:g})")
    if len(b.note.strip()) < 5:
        raise HTTPException(400, "اذكر مصدر القيمة في الملاحظة (نشرة، لائحة، مراجعة مختص)")
    vf = pdate(b.valid_from, "تاريخ السريان").isoformat()
    exists = c.execute("SELECT id, value FROM hr_rates WHERE key=? AND valid_from=?", (b.key, vf)).fetchone()
    if exists and exists["value"] is not None:
        raise HTTPException(409, "لهذه القيمة نسخة بالتاريخ نفسه — اختر تاريخ سريان آخر")
    if exists:  # the unset seed row for that date is filled in
        c.execute("UPDATE hr_rates SET value=?, provisional=0, note=?, created_by=? WHERE id=?", (b.value, b.note.strip(), u["username"], exists["id"]))
    else:
        c.execute("INSERT INTO hr_rates(key,value,valid_from,provisional,note,created_by) VALUES(?,?,?,0,?,?)", (b.key, b.value, vf, b.note.strip(), u["username"]))
    audit(c, "معدل رواتب", f"{label} = {b.value:g} من {vf} — {b.note.strip()}")
    c.commit()
    return {"ok": True}


@router.get("/api/hr/payroll/components")
def api_components(_=Depends(need("hr_payroll"))):
    c = db()
    ensure_setup(c)
    return rows(c.execute("SELECT id, key, name, kind, pasi_base, system, active FROM pay_components ORDER BY system DESC, id"))


class ComponentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=2, max_length=30, pattern=r"^[a-z][a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=60)
    pasi_base: bool = False


@router.post("/api/hr/payroll/components")
def api_component_add(b: ComponentIn, u=Depends(act_as("hr_payroll"))):
    c = db()
    ensure_setup(c)
    if c.execute("SELECT 1 FROM pay_components WHERE key=?", (b.key,)).fetchone():
        raise HTTPException(409, "مفتاح البدل مستخدم")
    cid = c.execute("INSERT INTO pay_components(key,name,kind,pasi_base) VALUES(?,?,'earning',?)", (b.key, b.name.strip(), int(b.pasi_base))).lastrowid
    audit(c, "بدل جديد في الرواتب", f"{b.name}" + (" · يدخل في وعاء التأمينات" if b.pasi_base else ""))
    c.commit()
    return {"id": cid}


# ----------------------------------------------------------------------------------------------------- salary structures
def structure_on(c, eid: int, day: dt.date) -> dict | None:
    s = c.execute("SELECT * FROM salary_structures WHERE employee_id=? AND effective_from<=? ORDER BY effective_from DESC LIMIT 1", (eid, day.isoformat())).fetchone()
    if not s:
        return None
    d = dict(s)
    d["lines"] = rows(c.execute("""SELECT l.component_id, p.key, p.name, p.pasi_base, l.amount FROM salary_lines l JOIN pay_components p ON p.id=l.component_id
                                   WHERE l.structure_id=? ORDER BY p.id""", (s["id"],)))
    d["total"] = r3(d["basic"] + sum(x["amount"] for x in d["lines"]))
    return d


@router.get("/api/hr/payroll/salaries")
def api_salaries(u=Depends(act_as("hr_payroll"))):
    """Every person on the payroll with the structure in force today. Opening this list is recorded: it is the whole salary bill."""
    c = db()
    ensure_setup(c)
    out = []
    for e in c.execute("""SELECT e.id, e.number, e.name, e.pasi_applies, d.name department FROM employees e LEFT JOIN departments d ON d.id=e.department_id
                          WHERE e.status!='terminated' ORDER BY e.number""").fetchall():
        s = structure_on(c, e["id"], today())
        out.append({"employee_id": e["id"], "number": e["number"], "name": e["name"], "department": e["department"], "pasi_applies": bool(e["pasi_applies"]),
                    "effective_from": s["effective_from"] if s else None, "basic": s["basic"] if s else None, "allowances": r3(sum(x["amount"] for x in s["lines"])) if s else None,
                    "total": s["total"] if s else None})
    audit(c, "اطلاع على الرواتب", f"قائمة الرواتب الحالية ({len(out)})")
    c.commit()
    return out


@router.get("/api/hr/payroll/structures")
def api_structures(employee_id: int, u=Depends(act_as("hr_payroll"))):
    c = db()
    e = employee(c, employee_id)
    out = []
    for s in rows(c.execute("SELECT id FROM salary_structures WHERE employee_id=? ORDER BY effective_from DESC", (employee_id,))):
        x = c.execute("SELECT * FROM salary_structures WHERE id=?", (s["id"],)).fetchone()
        d = dict(x)
        d["lines"] = rows(c.execute("SELECT l.component_id, p.name, l.amount FROM salary_lines l JOIN pay_components p ON p.id=l.component_id WHERE l.structure_id=? ORDER BY p.id", (s["id"],)))
        out.append(d)
    audit(c, "اطلاع على راتب موظف", f"{e['number']} · {e['name']}")
    c.commit()
    return out


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: int
    amount: float = Field(ge=0, le=1_000_000)


class StructureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int
    effective_from: str
    basic: float = Field(ge=0, le=1_000_000)
    lines: list[LineIn] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=200)


@router.post("/api/hr/payroll/structures")
def api_structure_add(b: StructureIn, u=Depends(act_as("hr_payroll"))):
    """A new salary structure from a date. History is kept (a raise is a new row); a date that falls in a month already approved is refused — it would rewrite a frozen payslip."""
    c = db()
    ensure_setup(c)
    e = employee(c, b.employee_id)
    if u.get("employee_id") == b.employee_id:
        raise HTTPException(403, "لا تعدّل هيكل راتبك بنفسك — يعدّله شخص آخر لديه صلاحية الرواتب")
    if e["status"] == "terminated":
        raise HTTPException(409, "الملف منتهي الخدمة")
    ef = pdate(b.effective_from, "تاريخ السريان")
    if ef.isoformat() < e["hire_date"]:
        raise HTTPException(400, "تاريخ السريان قبل التعيين")
    if c.execute("SELECT 1 FROM salary_structures WHERE employee_id=? AND effective_from=?", (b.employee_id, ef.isoformat())).fetchone():
        raise HTTPException(409, "للموظف هيكل بالتاريخ نفسه")
    frozen = c.execute("""SELECT r.period FROM payslips s JOIN payroll_runs r ON r.id=s.run_id WHERE s.employee_id=? AND r.status IN ('approved','paid') ORDER BY r.period DESC LIMIT 1""", (b.employee_id,)).fetchone()
    if frozen and ef.isoformat()[:7] <= frozen["period"]:
        raise HTTPException(409, f"مسيّر {frozen['period']} معتمد ومجمَّد — اجعل السريان بعده")
    seen = set()
    for ln in b.lines:
        comp = c.execute("SELECT kind, active FROM pay_components WHERE id=?", (ln.component_id,)).fetchone()
        if not comp or comp["kind"] != "earning" or not comp["active"]:
            raise HTTPException(400, "بدل غير معروف أو موقوف")
        if ln.component_id in seen:
            raise HTTPException(400, "البدل مكرر في الهيكل")
        seen.add(ln.component_id)
    sid = c.execute("INSERT INTO salary_structures(employee_id,effective_from,basic,note,created_by) VALUES(?,?,?,?,?)", (b.employee_id, ef.isoformat(), r3(b.basic), b.note or None, u["username"])).lastrowid
    for ln in b.lines:
        if ln.amount > 0:
            c.execute("INSERT INTO salary_lines(structure_id,component_id,amount) VALUES(?,?,?)", (sid, ln.component_id, r3(ln.amount)))
    audit(c, "هيكل راتب جديد", f"{e['number']} · من {ef.isoformat()}")  # the amounts are not written to the audit line
    c.commit()
    return {"id": sid}


# ----------------------------------------------------------------------------------------------------- adjustments (one-off earnings and deductions)
@router.get("/api/hr/payroll/adjustments")
def api_adjustments(period: str = Query(..., pattern=PERIOD_RE), _=Depends(need("hr_payroll"))):
    return rows(db().execute("""SELECT a.id, a.employee_id, e.number, e.name, a.period, a.kind, a.name item, a.amount, a.note, a.created_by FROM payroll_adjustments a
                                JOIN employees e ON e.id=a.employee_id WHERE a.period=? ORDER BY a.id""", (period,)))


class AdjIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int
    period: str = Field(pattern=PERIOD_RE)
    kind: Literal["earning", "deduction"]
    name: str = Field(min_length=2, max_length=60)
    amount: float = Field(gt=0, le=1_000_000)
    note: str = Field(default="", max_length=200)


def _run_frozen(c, period: str) -> bool:
    r = c.execute("SELECT status FROM payroll_runs WHERE period=?", (period,)).fetchone()
    return bool(r and r["status"] in ("approved", "paid"))


@router.post("/api/hr/payroll/adjustments")
def api_adjustment_add(b: AdjIn, u=Depends(act_as("hr_payroll"))):
    c = db()
    e = employee(c, b.employee_id)
    if u.get("employee_id") == b.employee_id:
        raise HTTPException(403, "لا تُسجّل تسوية على راتبك بنفسك — يسجّلها شخص آخر لديه صلاحية الرواتب")
    if _run_frozen(c, b.period):
        raise HTTPException(409, f"مسيّر {b.period} معتمد — ضع التسوية في الشهر التالي")
    aid = c.execute("INSERT INTO payroll_adjustments(employee_id,period,kind,name,amount,note,created_by) VALUES(?,?,?,?,?,?,?)",
                    (b.employee_id, b.period, b.kind, b.name.strip(), r3(b.amount), b.note or None, u["username"])).lastrowid
    audit(c, "تسوية راتب", f"{e['number']} · {b.period} · {'استحقاق' if b.kind == 'earning' else 'استقطاع'} {b.name}")
    c.commit()
    return {"id": aid}


@router.delete("/api/hr/payroll/adjustments/{aid}")
def api_adjustment_del(aid: int, u=Depends(act_as("hr_payroll"))):
    c = db()
    a = one(c, "SELECT * FROM payroll_adjustments WHERE id=?", (aid,), "التسوية غير موجودة")
    if _run_frozen(c, a["period"]):
        raise HTTPException(409, "المسيّر معتمد")
    c.execute("DELETE FROM payroll_adjustments WHERE id=?", (aid,))
    audit(c, "حذف تسوية راتب", f"#{aid} · {a['period']}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- staff advances and qard hasan loans
def _next_period(p: str, n: int = 1) -> str:
    y, m = int(p[:4]), int(p[5:])
    m0 = m - 1 + n
    return f"{y + m0 // 12:04d}-{m0 % 12 + 1:02d}"


@router.get("/api/hr/payroll/loans")
def api_loans(status: str | None = Query(None, pattern="^(pending|active|paid|cancelled)$"), employee_id: int | None = None, u=Depends(need("hr_payroll"))):
    c = db()
    where, args = [], []
    if status:
        where.append("l.status=?")
        args.append(status)
    if employee_id:
        where.append("l.employee_id=?")
        args.append(employee_id)
    out = rows(c.execute("""SELECT l.*, e.number, e.name, COALESCE((SELECT SUM(i.amount) FROM loan_installments i WHERE i.loan_id=l.id AND i.status='due'),0) outstanding
                            FROM employee_loans l JOIN employees e ON e.id=l.employee_id""" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY l.id DESC", tuple(args)))
    for x in out:
        x["outstanding"] = r3(x["outstanding"])
    return out


@router.get("/api/hr/payroll/loans/{lid}")
def api_loan(lid: int, _=Depends(need("hr_payroll"))):
    c = db()
    l = dict(one(c, "SELECT * FROM employee_loans WHERE id=?", (lid,), "القرض غير موجود"))
    l["schedule"] = rows(c.execute("SELECT no, period, amount, status FROM loan_installments WHERE loan_id=? ORDER BY no", (lid,)))
    return l


class LoanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a `rate`, `fee` or `profit` field is refused (422): a staff loan is repaid at exactly the amount lent
    employee_id: int
    kind: Literal["advance", "qard_hasan"]
    amount: float = Field(gt=0, le=1_000_000)
    installments: int = Field(ge=1, le=60)
    start_period: str = Field(pattern=PERIOD_RE)
    reason: str = Field(default="", max_length=200)
    request_id: int | None = None


@router.post("/api/hr/payroll/loans")
def api_loan_add(b: LoanIn, u=Depends(act_as("hr_payroll"))):
    c = db()
    e = employee(c, b.employee_id)
    if e["status"] == "terminated":
        raise HTTPException(409, "الملف منتهي الخدمة")
    if b.kind == "advance" and b.installments > 12:
        raise HTTPException(400, "السلفة لا تزيد عن 12 قسطًا — استعمل القرض الحسن للآجال الأطول")
    if b.request_id is not None:
        q = c.execute("SELECT employee_id, kind, status FROM hr_requests WHERE id=?", (b.request_id,)).fetchone()
        if not q or q["employee_id"] != b.employee_id or q["kind"] != "advance" or q["status"] != "approved":
            raise HTTPException(400, "الطلب غير موجود أو ليس سلفة معتمدة من الموارد البشرية لهذا الموظف")
    lid = c.execute("INSERT INTO employee_loans(employee_id,kind,amount,installments,start_period,reason,request_id,created_by) VALUES(?,?,?,?,?,?,?,?)",
                    (b.employee_id, b.kind, r3(b.amount), b.installments, b.start_period, b.reason or None, b.request_id, u["username"])).lastrowid
    if b.request_id is not None:
        c.execute("UPDATE hr_requests SET status='done' WHERE id=?", (b.request_id,))
    audit(c, "طلب سلفة/قرض حسن", f"{e['number']} · {'سلفة' if b.kind == 'advance' else 'قرض حسن'} · {b.installments} قسطًا")
    c.commit()
    return {"id": lid}


class LoanApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disbursed_on: str
    bank_account_id: int | None = None


@router.post("/api/hr/payroll/loans/{lid}/approve")
def api_loan_approve(lid: int, b: LoanApprove, u=Depends(act_as("hr_payroll"))):
    """A second person approves and the money goes out: the schedule is cut into equal instalments (the last absorbs the rounding), starting at the chosen month."""
    c = db()
    l = dict(one(c, "SELECT * FROM employee_loans WHERE id=?", (lid,), "القرض غير موجود"))
    if l["status"] != "pending":
        raise HTTPException(409, "القرض لم يعد بانتظار الاعتماد")
    if l["created_by"] == u["username"]:
        raise HTTPException(403, "لا تعتمد قرضًا أنشأته — يعتمده شخص آخر")
    if u.get("employee_id") == l["employee_id"]:
        raise HTTPException(403, "لا تعتمد قرضك")
    day = pdate(b.disbursed_on, "تاريخ الصرف")
    if b.bank_account_id is not None:
        one(c, "SELECT 1 FROM bank_accounts WHERE id=? AND active=1", (b.bank_account_id,), "الحساب البنكي غير موجود")
    elif ledger.start_date(c):
        raise HTTPException(400, "اختر الحساب البنكي الذي صُرف منه المبلغ — المحاسبة مفعَّلة ولا يُقيَّد الصرف بدونه")
    each = math.floor(l["amount"] / l["installments"] * 1000) / 1000   # rounded DOWN: the last instalment then absorbs the remainder and is never below the others
    if each < 0.001:
        raise HTTPException(400, "المبلغ أصغر من أن يُقسَّط على هذا العدد من الأقساط")
    for i in range(1, l["installments"] + 1):
        amt = each if i < l["installments"] else r3(l["amount"] - each * (l["installments"] - 1))
        c.execute("INSERT INTO loan_installments(loan_id,no,period,amount) VALUES(?,?,?,?)", (lid, i, _next_period(l["start_period"], i - 1), amt))
    c.execute("UPDATE employee_loans SET status='active', approved_by=?, approved_at=?, disbursed_on=?, bank_account_id=? WHERE id=?", (u["username"], now_s(), day.isoformat(), b.bank_account_id, lid))
    audit(c, "اعتماد سلفة/قرض حسن", f"#{lid} · {l['installments']} قسطًا من {l['start_period']}")
    note = None
    if ledger.start_date(c):
        res = {"posted": {"payroll": 0}, "pending": {"payroll": 0}, "errors": []}
        ledger.ensure_chart(c)
        sync_loans(c, ledger.Ctx(c), ledger.start_date(c), False, res)
        note = res["errors"][0] if res["errors"] else None
    c.commit()
    return {"ok": True, "note": note}


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=200)


@router.post("/api/hr/payroll/loans/{lid}/cancel")
def api_loan_cancel(lid: int, b: CancelIn, u=Depends(act_as("hr_payroll"))):
    c = db()
    l = dict(one(c, "SELECT * FROM employee_loans WHERE id=?", (lid,), "القرض غير موجود"))
    if l["status"] == "pending":
        c.execute("UPDATE employee_loans SET status='cancelled' WHERE id=?", (lid,))
    elif l["status"] == "active" and not c.execute("SELECT 1 FROM loan_installments WHERE loan_id=? AND status!='due'", (lid,)).fetchone() and not l["disburse_journal_id"]:
        if u["username"] in (l["created_by"], l["approved_by"]):
            raise HTTPException(403, "لا يُلغي قرضًا اعتُمد من أنشأه أو اعتمده — يلغيه شخص ثالث لديه صلاحية الرواتب")
        c.execute("UPDATE employee_loans SET status='cancelled' WHERE id=?", (lid,))
        c.execute("UPDATE loan_installments SET status='waived' WHERE loan_id=?", (lid,))
    else:
        raise HTTPException(409, "لا يُلغى قرض صُرف أو بدأ خصمه")
    audit(c, "إلغاء سلفة/قرض", f"#{lid} · {b.reason}")
    c.commit()
    return {"ok": True}


def sync_loans(c, ctx, start: str, dry: bool, res: dict) -> None:
    """Disbursed loans with a bank account: Dr staff loans / Cr the bank — once."""
    for l in c.execute("""SELECT l.*, b.account_id gl, e.number FROM employee_loans l JOIN bank_accounts b ON b.id=l.bank_account_id JOIN employees e ON e.id=l.employee_id
                          WHERE l.status IN ('active','paid') AND l.disburse_journal_id IS NULL AND l.disbursed_on>=?""", (start,)).fetchall():
        res["pending"]["payroll"] += 1
        if dry:
            continue
        try:
            jid = ledger.post(c, date=dt.date.fromisoformat(l["disbursed_on"]), memo=f"صرف {'سلفة' if l['kind'] == 'advance' else 'قرض حسن'} — {l['number']}", source_kind="loan", source_ref=str(l["id"]),
                              source_key=f"loan:{l['id']}", ctx=ctx, lines=[dict(account="emp_loans", debit=r3(l["amount"]), party_type="employee", party_id=l["employee_id"]),
                                                                          dict(account=l["gl"], credit=r3(l["amount"]))])
        except ledger.LedgerError as err:
            res["errors"].append(f"قرض {l['id']}: {err}")
            continue
        if jid:
            c.execute("UPDATE employee_loans SET disburse_journal_id=? WHERE id=?", (jid, l["id"]))
        res["posted"]["payroll"] += 1


# ----------------------------------------------------------------------------------------------------- the monthly run
def bounds(period: str) -> tuple[dt.date, dt.date]:
    y, m = int(period[:4]), int(period[5:])
    return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])


def _run(c, rid: int) -> dict:
    return dict(one(c, "SELECT * FROM payroll_runs WHERE id=?", (rid,), "المسيّر غير موجود"))


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str = Field(pattern=PERIOD_RE)


@router.get("/api/hr/payroll/runs")
def api_runs(_=Depends(need("hr_payroll"))):
    return rows(db().execute("SELECT * FROM payroll_runs ORDER BY period DESC"))


@router.post("/api/hr/payroll/runs")
def api_run_add(b: RunIn, u=Depends(act_as("hr_payroll"))):
    c = db()
    ensure_setup(c)
    ps, _pe = bounds(b.period)
    if ps > today():
        raise HTTPException(400, "لا يُنشأ مسيّر لشهر لم يبدأ")
    if c.execute("SELECT 1 FROM payroll_runs WHERE period=?", (b.period,)).fetchone():
        raise HTTPException(409, "لهذا الشهر مسيّر بالفعل")
    rid = c.execute("INSERT INTO payroll_runs(period,created_by) VALUES(?,?)", (b.period, u["username"])).lastrowid
    audit(c, "مسيّر رواتب جديد", b.period)
    c.commit()
    return {"id": rid}


def _unpaid_leave_days(c, eid: int, ws: dt.date, we: dt.date) -> float:
    from .hr_leave import leave_days
    n = 0.0
    for r in c.execute("""SELECT r.from_date, r.to_date, t.day_count FROM leave_requests r JOIN leave_types t ON t.id=r.type_id
                          WHERE r.employee_id=? AND r.status='approved' AND t.paid=0 AND r.from_date<=? AND r.to_date>=?""", (eid, we.isoformat(), ws.isoformat())).fetchall():
        a, z = max(ws, dt.date.fromisoformat(r["from_date"])), min(we, dt.date.fromisoformat(r["to_date"]))
        if a <= z:
            n += leave_days(c, a, z, r["day_count"])
    return n


def _fingerprint(c, rid: int) -> list:
    cols = ("employee_id", "gross", "absence_ded", "adj_earn", "adj_ded", "pasi_employee", "pasi_employer", "loan_ded", "net")
    return [[r[k] for k in cols] for r in c.execute(f"SELECT {', '.join(cols)} FROM payslips WHERE run_id=? ORDER BY employee_id", (rid,)).fetchall()]


def compute_run(c, run: dict, by: str) -> dict:
    """(Re)build every payslip of a run that is still draft/computed. Idempotent: running it twice gives the same payslips, and the instalments it assigned are released first."""
    if run["status"] not in ("draft", "computed"):
        raise HTTPException(409, "المسيّر معتمد ومجمَّد")
    ensure_setup(c)
    rid, period = run["id"], run["period"]
    ps, pe = bounds(period)
    days_in = (pe - ps).days + 1
    divisor = rate_on(c, "day_divisor", pe) or 30.0
    pct_e, pct_r, ceiling = rate_on(c, "pasi_employee_pct", pe), rate_on(c, "pasi_employer_pct", pe), rate_on(c, "pasi_ceiling", pe)
    c.execute("UPDATE loan_installments SET status='due', payslip_id=NULL WHERE payslip_id IN (SELECT id FROM payslips WHERE run_id=?)", (rid,))
    c.execute("DELETE FROM payslips WHERE run_id=?", (rid,))
    tot = {"gross": 0.0, "net": 0.0, "pe": 0.0, "pr": 0.0, "n": 0, "blockers": 0}
    skipped = []
    for e in [dict(x) for x in c.execute("""SELECT e.*, d.cost_center_id dcc FROM employees e LEFT JOIN departments d ON d.id=e.department_id
                                            WHERE e.hire_date<=? AND (e.terminated_on IS NULL OR e.terminated_on>=?) ORDER BY e.number""", (pe.isoformat(), ps.isoformat())).fetchall()]:
        s = structure_on(c, e["id"], pe)
        if not s:
            skipped.append({"employee_id": e["id"], "number": e["number"], "name": e["name"], "reason": "لا هيكل راتب"})
            continue
        warns: list[dict] = []
        # a structure that starts inside the month warns only when the person already had an earlier one — a new hire's first structure is not a "change"
        if c.execute("SELECT 1 FROM salary_structures WHERE employee_id=? AND effective_from>? AND effective_from<=?", (e["id"], ps.isoformat(), pe.isoformat())).fetchone()                 and c.execute("SELECT 1 FROM salary_structures WHERE employee_id=? AND effective_from<=?", (e["id"], ps.isoformat())).fetchone():
            warns.append({"kind": "mid_month_structure", "blocker": 0, "msg": "تغيّر هيكل الراتب خلال الشهر: احتُسب الشهر كله بالهيكل الأحدث (لا تقسيم بالأيام) — سوِّ الفرق بتسوية إن لزم"})
        ws = max(ps, dt.date.fromisoformat(e["hire_date"]))
        we = min(pe, dt.date.fromisoformat(e["terminated_on"])) if e["terminated_on"] else pe
        factor = round(((we - ws).days + 1) / days_in, 6)
        earn = [{"key": "basic", "name": "الأجر الأساسي", "amount": r3(s["basic"] * factor), "pasi": 1}] + \
               [{"key": x["key"], "name": x["name"], "amount": r3(x["amount"] * factor), "pasi": int(x["pasi_base"])} for x in s["lines"]]
        gross = r3(sum(x["amount"] for x in earn))
        absent = float(c.execute("SELECT COUNT(*) n FROM attendance WHERE employee_id=? AND status='absent' AND day>=? AND day<=?", (e["id"], ws.isoformat(), we.isoformat())).fetchone()["n"])
        abs_days = absent + _unpaid_leave_days(c, e["id"], ws, we)
        abs_ded = min(gross, r3(s["basic"] / divisor * abs_days))
        adj = rows(c.execute("SELECT kind, name, amount FROM payroll_adjustments WHERE employee_id=? AND period=?", (e["id"], period)))
        adj_earn, adj_ded = r3(sum(a["amount"] for a in adj if a["kind"] == "earning")), r3(sum(a["amount"] for a in adj if a["kind"] == "deduction"))
        from .hr_disc import deductions_for  # 0.27.0: a disciplinary deduction is days of wage, valued here from the salary (HR never sees the amount)
        for pen in deductions_for(c, e["id"], period):
            amt = r3(s["basic"] / divisor * pen["penalty_days"])
            adj_ded = r3(adj_ded + amt)
            warns.append({"kind": "discipline", "blocker": 0, "msg": f"جزاء {pen['number']} (مادة {pen['code']}): خصم {pen['penalty_days']:g} يومًا = {amt:.3f}"})
        pasi_base = pasi_e = pasi_r = 0.0
        if e["pasi_applies"]:
            pasi_base = r3(sum(x["amount"] for x in earn if x["pasi"]))
            if ceiling is not None:
                pasi_base = min(pasi_base, r3(ceiling))
            if pct_e is None or pct_r is None or ceiling is None:
                warns.append({"kind": "pasi_unset", "blocker": 1, "msg": "معدلات التأمينات أو السقف لم تُدخَل — لا يُعتمد المسيّر قبل إدخالها (تبويب «المعدلات»)"})
            else:
                pasi_e, pasi_r = r3(pasi_base * pct_e / 100), r3(pasi_base * pct_r / 100)
            if not e["social_ins_no"]:
                warns.append({"kind": "no_pasi_number", "blocker": 0, "msg": "لا رقم تأمينات في الملف"})
        avail = r3(gross + adj_earn - abs_ded - pasi_e - adj_ded)
        loan_ded = 0.0
        pend = rows(c.execute("""SELECT i.id, i.amount, i.loan_id FROM loan_installments i JOIN employee_loans l ON l.id=i.loan_id
                                 WHERE l.employee_id=? AND l.status='active' AND i.status='due' AND i.period<=? ORDER BY i.period, i.no""", (e["id"], period)))
        take = []
        for i in pend:
            if i["amount"] <= avail - loan_ded + EPS:
                loan_ded = r3(loan_ded + i["amount"])
                take.append(i["id"])
            else:
                warns.append({"kind": "loan_deferred", "blocker": 0, "msg": f"قسط {i['amount']:.3f} لا يتسع له صافي الراتب فأُجّل"})
        net = r3(avail - loan_ded)
        if net < -EPS:
            warns.append({"kind": "negative_net", "blocker": 1, "msg": f"صافي الراتب سالب ({net:.3f}) — راجع الاستقطاعات"})
        pid = c.execute("""INSERT INTO payslips(run_id,employee_id,basic,factor,earnings,gross,absence_days,absence_ded,adj_earn,adj_ded,pasi_base,pasi_employee,pasi_employer,loan_ded,net,warnings,cost_center_id)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (rid, e["id"], r3(s["basic"]), factor, json.dumps(earn, ensure_ascii=False), gross, abs_days, abs_ded, adj_earn, adj_ded, pasi_base, pasi_e, pasi_r, loan_ded, net,
                         json.dumps(warns, ensure_ascii=False) if warns else None, e["dcc"])).lastrowid
        for iid in take:
            c.execute("UPDATE loan_installments SET status='deducted', payslip_id=? WHERE id=?", (pid, iid))
        tot["gross"] += gross + adj_earn
        tot["net"] += net
        tot["pe"] += pasi_e
        tot["pr"] += pasi_r
        tot["n"] += 1
        tot["blockers"] += sum(w["blocker"] for w in warns)
    c.execute("""UPDATE payroll_runs SET status='computed', headcount=?, gross=?, net=?, pasi_employee=?, pasi_employer=?, blockers=?, computed_by=?, computed_at=? WHERE id=?""",
              (tot["n"], r3(tot["gross"]), r3(tot["net"]), r3(tot["pe"]), r3(tot["pr"]), tot["blockers"], by, now_s(), rid))
    return {"headcount": tot["n"], "gross": r3(tot["gross"]), "net": r3(tot["net"]), "blockers": tot["blockers"], "skipped": skipped}


@router.post("/api/hr/payroll/runs/{rid}/compute")
def api_compute(rid: int, u=Depends(act_as("hr_payroll"))):
    c = db()
    out = compute_run(c, _run(c, rid), u["username"])
    audit(c, "احتساب مسيّر رواتب", f"{_run(c, rid)['period']} · {out['headcount']} قسيمة · عوائق {out['blockers']}")
    c.commit()
    return out


def _payslip_view(p: dict) -> dict:
    p["earnings"] = json.loads(p["earnings"] or "[]")
    p["warnings"] = json.loads(p["warnings"] or "[]")
    return p


@router.get("/api/hr/payroll/runs/{rid}")
def api_run(rid: int, u=Depends(act_as("hr_payroll"))):
    c = db()
    run = _run(c, rid)
    ps, pe = bounds(run["period"])
    slips = [_payslip_view(dict(x)) for x in c.execute("""SELECT s.*, e.number, e.name FROM payslips s JOIN employees e ON e.id=s.employee_id WHERE s.run_id=? ORDER BY e.number""", (rid,)).fetchall()]
    have = {s["employee_id"] for s in slips}
    missing = [{"employee_id": e["id"], "number": e["number"], "name": e["name"], "reason": "لا هيكل راتب" if not structure_on(c, e["id"], pe) else "لم يُحتسب بعد"}
               for e in c.execute("SELECT id, number, name FROM employees WHERE hire_date<=? AND (terminated_on IS NULL OR terminated_on>=?) ORDER BY number", (pe.isoformat(), ps.isoformat())).fetchall()
               if e["id"] not in have]
    audit(c, "اطلاع على مسيّر رواتب", run["period"])
    c.commit()
    return {**run, "payslips": slips, "missing": missing}


@router.post("/api/hr/payroll/runs/{rid}/approve")
def api_approve(rid: int, confirm_missing: int = Query(0, ge=0, le=1), u=Depends(act_as("hr_payroll"))):
    """The person who computed the run never approves it. A blocker (a missing PASI rate, a negative net) stops the approval. Since 0.28.1 the run is also re-computed here:
    if anything it reads (an adjustment, a loan, a disciplinary deduction, a structure, attendance, leave) changed since the compute, the run is refreshed and the approval refused
    so the approver reviews what will actually be paid; the month must have ended; and employees with no salary structure must be acknowledged, not silently unpaid."""
    c = db()
    run = _run(c, rid)
    if run["status"] != "computed":
        raise HTTPException(409, "يُعتمد المسيّر بعد احتسابه فقط")
    if run["computed_by"] == u["username"]:
        raise HTTPException(403, "لا تعتمد مسيّرًا احتسبته — يعتمده شخص آخر لديه صلاحية الرواتب")
    ps, pe = bounds(run["period"])
    if pe > today():
        raise HTTPException(409, "لا يُعتمد مسيّر شهر لم ينتهِ بعد — الغياب والإجازات والجزاءات لم تكتمل")
    if u.get("employee_id") and c.execute("SELECT 1 FROM payslips WHERE run_id=? AND employee_id=?", (rid, u["employee_id"])).fetchone():
        raise HTTPException(403, "في المسيّر قسيمتك — يعتمده شخص آخر")
    before = _fingerprint(c, rid)
    compute_run(c, run, run["computed_by"])   # keeps the maker: the approver's refresh is not a second "compute by" him
    c.commit()   # the refreshed payslips are real state whatever happens next (no transaction is left open across a refusal)
    if _fingerprint(c, rid) != before:
        raise HTTPException(409, "تغيّرت مدخلات الشهر بعد الاحتساب (تسوية أو جزاء أو سلفة أو هيكل أو حضور أو إجازة) — أُعيد الاحتساب الآن؛ راجع القسائم ثم اعتمد")
    run = _run(c, rid)
    miss = [e["number"] for e in c.execute("SELECT id, number FROM employees WHERE hire_date<=? AND (terminated_on IS NULL OR terminated_on>=?) ORDER BY number", (pe.isoformat(), ps.isoformat())).fetchall()
            if not structure_on(c, e["id"], pe)]
    if miss and not confirm_missing:
        raise HTTPException(409, "موظفون بلا هيكل راتب لن يُصرف لهم: " + "، ".join(miss[:8]) + (f" … (+{len(miss) - 8})" if len(miss) > 8 else "") + " — أضف هياكلهم وأعد الاحتساب، أو أكّد المتابعة بدونهم")
    if run["blockers"]:
        bad = [f"{r['number']}: {w['msg']}" for r in c.execute("SELECT s.warnings, e.number FROM payslips s JOIN employees e ON e.id=s.employee_id WHERE s.run_id=?", (rid,)).fetchall()
               for w in json.loads(r["warnings"] or "[]") if w["blocker"]]
        raise HTTPException(409, "عوائق تمنع الاعتماد: " + " | ".join(bad[:5]) + (f" … (+{len(bad) - 5})" if len(bad) > 5 else ""))
    if run["headcount"] == 0:
        raise HTTPException(409, "لا قسائم في المسيّر")
    done = c.execute("UPDATE payroll_runs SET status='approved', approved_by=?, approved_at=? WHERE id=? AND status='computed'", (u["username"], now_s(), rid))
    if done.rowcount != 1:
        raise HTTPException(409, "اعتُمد المسيّر للتوّ من جهة أخرى")
    c.execute("""UPDATE disciplinary_cases SET applied_run_id=? WHERE status='issued' AND apply_period=? AND applied_run_id IS NULL AND employee_id IN (SELECT employee_id FROM payslips WHERE run_id=?)
                 AND rule_id IN (SELECT id FROM penalty_rules WHERE kind='deduction')""", (rid, run["period"], rid))
    for lid in {r["loan_id"] for r in c.execute("SELECT DISTINCT i.loan_id FROM loan_installments i JOIN payslips s ON s.id=i.payslip_id WHERE s.run_id=?", (rid,)).fetchall()}:
        if not c.execute("SELECT 1 FROM loan_installments WHERE loan_id=? AND status='due'", (lid,)).fetchone():
            c.execute("UPDATE employee_loans SET status='paid' WHERE id=? AND status='active'", (lid,))
    audit(c, "اعتماد مسيّر رواتب", f"{run['period']} · {run['headcount']} قسيمة")
    note = None
    if ledger.start_date(c):
        try:
            post_run(c, ledger.Ctx(c), _run(c, rid))
        except ledger.LedgerError as ex:
            note = f"لم يُرحَّل إلى المحاسبة: {ex}"
    c.commit()
    return {"status": "approved", "note": note}


class PayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paid_on: str
    bank_account_id: int | None = None


@router.post("/api/hr/payroll/runs/{rid}/pay")
def api_pay(rid: int, b: PayIn, u=Depends(act_as("hr_payroll"))):
    c = db()
    run = _run(c, rid)
    if run["status"] != "approved":
        raise HTTPException(409, "يُسجَّل الدفع بعد الاعتماد")
    day = pdate(b.paid_on, "تاريخ الدفع")
    if day < bounds(run["period"])[0]:
        raise HTTPException(400, "الدفع قبل بداية الشهر")
    if b.bank_account_id is not None:
        one(c, "SELECT 1 FROM bank_accounts WHERE id=? AND active=1", (b.bank_account_id,), "الحساب البنكي غير موجود")
    elif ledger.start_date(c):
        raise HTTPException(400, "اختر الحساب البنكي الذي صُرفت منه الرواتب — المحاسبة مفعَّلة ولا يُقيَّد الدفع بدونه")
    c.execute("UPDATE payroll_runs SET status='paid', paid_on=?, bank_account_id=? WHERE id=?", (day.isoformat(), b.bank_account_id, rid))
    audit(c, "دفع رواتب", f"{run['period']} · {day.isoformat()}")
    note = None
    if ledger.start_date(c) and b.bank_account_id:
        try:
            post_run(c, ledger.Ctx(c), _run(c, rid))
        except ledger.LedgerError as ex:
            note = f"لم يُرحَّل الدفع إلى المحاسبة: {ex}"
    c.commit()
    return {"status": "paid", "note": note}


# ----------------------------------------------------------------------------------------------------- the wage-protection file
def wps_check(c, run: dict) -> tuple[list[dict], list[dict]]:
    """→ (lines, problems). A problem with `error` stops the export; a warning is shown with the file."""
    lines, probs = [], []
    for r in c.execute("""SELECT s.net, e.id eid, e.number, e.name, e.bank_name, e.iban FROM payslips s JOIN employees e ON e.id=s.employee_id WHERE s.run_id=? ORDER BY e.number""", (run["id"],)).fetchall():
        iban = (pii.dec(r["iban"]) or "").replace(" ", "").upper()
        def p(kind, msg, err=1, r=r):
            probs.append({"number": r["number"], "name": r["name"], "error": err, "kind": kind, "msg": msg})
        if r["net"] <= EPS:
            continue  # nothing to transfer: not an error
        if not iban:
            p("no_iban", "لا IBAN في ملف الموظف")
            continue
        if not r["bank_name"]:
            p("no_bank", "لا اسم بنك في ملف الموظف")
            continue
        if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
            p("bad_iban", "صيغة IBAN غير صحيحة", 1)
            continue
        if not iban.startswith("OM"):
            p("foreign_iban", "IBAN غير عُماني — تحقق من قبول البنك", 0)
        lines.append({"number": r["number"], "name": r["name"], "bank": r["bank_name"], "iban": iban, "net": r3(r["net"])})
    dup = {}
    for x in lines:
        dup.setdefault(x["iban"], []).append(x["number"])
    for iban, nums in dup.items():
        if len(nums) > 1:
            probs.append({"number": ",".join(nums), "name": "", "error": 0, "kind": "dup_iban", "msg": "الحساب نفسه لأكثر من موظف", })
    return lines, probs


@router.get("/api/hr/payroll/runs/{rid}/wps")
def api_wps(rid: int, fmt: Literal["json", "csv"] = "json", u=Depends(act_as("hr_payroll"))):
    """Pre-flight report of the bank transfer file, and the file itself once there is no error. The layout is a plain CSV: each bank's exact format is a setting the owner supplies."""
    c = db()
    run = _run(c, rid)
    if run["status"] not in ("approved", "paid"):
        raise HTTPException(409, "الملف يُولَّد من مسيّر معتمد")
    lines, probs = wps_check(c, run)
    errors = [x for x in probs if x["error"]]
    if fmt == "json":
        return {"period": run["period"], "lines": lines, "total": r3(sum(x["net"] for x in lines)), "problems": probs, "ready": not errors}
    if errors:
        raise HTTPException(409, "أخطاء تمنع التصدير: " + " | ".join(f"{x['number']}: {x['msg']}" for x in errors[:5]))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["employee_number", "employee_name", "bank", "iban", "net_salary_omr", "period"])
    for x in lines:
        w.writerow([x["number"], x["name"], x["bank"], x["iban"], f"{x['net']:.3f}", run["period"]])
    data = buf.getvalue().encode("utf-8-sig")
    c.execute("UPDATE payroll_runs SET wps_sha=?, wps_at=? WHERE id=?", (hashlib.sha256(data).hexdigest(), now_s(), rid))
    audit(c, "تصدير ملف حماية الأجور", f"{run['period']} · {len(lines)} سطرًا · sha {hashlib.sha256(data).hexdigest()[:12]}")
    c.commit()
    return Response(data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="wps-{run["period"]}.csv"', "Cache-Control": "no-store"})


# ----------------------------------------------------------------------------------------------------- accounting
def post_run(c, ctx, run: dict) -> None:
    """Accrual at approval (expense by department cost centre against the payroll payable, the insurance payable and the staff loans) and, once paid from a bank
    account, the payment. Each is posted once (`source_key`); an inactive ledger posts nothing and the next sync picks the run up."""
    ledger.ensure_chart(c)  # the payroll accounts were added in 0.26.0
    ps, pe = bounds(run["period"])
    sl = [dict(x) for x in c.execute("SELECT * FROM payslips WHERE run_id=? ORDER BY id", (run["id"],)).fetchall()]
    if run["status"] in ("approved", "paid") and not run["journal_id"] and sl:
        lines: list[dict] = []
        for s in sl:
            exp = r3(s["gross"] + s["adj_earn"] - s["absence_ded"] - s["adj_ded"])
            lines.append(dict(account="exp_payroll", **({"debit": exp} if exp >= 0 else {"credit": -exp}), cc=s["cost_center_id"]))
            if s["pasi_employer"] > EPS:
                lines.append(dict(account="exp_pasi_employer", debit=s["pasi_employer"], cc=s["cost_center_id"]))
            if s["net"] > EPS:
                lines.append(dict(account="payroll_payable", credit=s["net"], party_type="employee", party_id=s["employee_id"]))
            if s["loan_ded"] > EPS:
                lines.append(dict(account="emp_loans", credit=s["loan_ded"], party_type="employee", party_id=s["employee_id"]))
        pasi = r3(sum(s["pasi_employee"] + s["pasi_employer"] for s in sl))
        if pasi > EPS:
            lines.append(dict(account="pasi_payable", credit=pasi))
        jid = ledger.post(c, date=pe, memo=f"مسيّر رواتب {run['period']}", source_kind="payroll", source_ref=str(run["id"]), source_key=f"payroll:{run['id']}", ctx=ctx, lines=lines)
        if jid:
            c.execute("UPDATE payroll_runs SET journal_id=? WHERE id=?", (jid, run["id"]))
    if run["status"] == "paid" and run["bank_account_id"] and not run["payment_journal_id"]:
        gl = c.execute("SELECT account_id FROM bank_accounts WHERE id=?", (run["bank_account_id"],)).fetchone()["account_id"]
        net = r3(sum(s["net"] for s in sl))
        if net > EPS:
            # 0.28.2: the debit side names each employee (as the accrual's credit side does), so every person's payable account closes to zero on its own
            pay = [dict(account="payroll_payable", debit=s["net"], party_type="employee", party_id=s["employee_id"]) for s in sl if s["net"] > EPS]
            jid = ledger.post(c, date=dt.date.fromisoformat(run["paid_on"]), memo=f"دفع رواتب {run['period']}", source_kind="payroll_pay", source_ref=str(run["id"]), source_key=f"payroll_pay:{run['id']}",
                              ctx=ctx, lines=pay + [dict(account=gl, credit=net)])
            if jid:
                c.execute("UPDATE payroll_runs SET payment_journal_id=? WHERE id=?", (jid, run["id"]))


def sync_payroll(c, ctx, start: str, dry: bool, res: dict) -> None:
    """The ledger sweep: approved runs, their payments, loan disbursements and settlements that the books have not seen yet (accounting activated later, a period that was closed)."""
    ledger.ensure_chart(c)
    for run in [dict(x) for x in c.execute("SELECT * FROM payroll_runs WHERE status IN ('approved','paid') ORDER BY period").fetchall()]:
        if bounds(run["period"])[1].isoformat() < start:
            continue
        need_acc = not run["journal_id"]
        need_pay = run["status"] == "paid" and run["bank_account_id"] and not run["payment_journal_id"]
        if not (need_acc or need_pay):
            continue
        res["pending"]["payroll"] += 1
        if dry:
            continue
        try:
            post_run(c, ctx, run)
        except ledger.LedgerError as err:
            res["errors"].append(f"مسيّر {run['period']}: {err}")
            continue
        res["posted"]["payroll"] += 1
    sync_loans(c, ctx, start, dry, res)
    from . import hr_end
    hr_end.sync_settlements(c, ctx, start, dry, res)


# ----------------------------------------------------------------------------------------------------- documents: a payslip
def payslip_row(c, pid: int) -> dict:
    p = dict(one(c, """SELECT s.*, r.period, r.status run_status, r.paid_on, e.number, e.name, e.hire_date, d.name department, po.title position FROM payslips s JOIN payroll_runs r ON r.id=s.run_id
                       JOIN employees e ON e.id=s.employee_id LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN positions po ON po.id=e.position_id WHERE s.id=?""", (pid,), "القسيمة غير موجودة"))
    return _payslip_view(p)


def payslip_pdf(c, p: dict) -> Response:
    from . import pdfgen
    from .paperwork import brand
    d = pdfgen.Doc(brand(c), "payslip", f"{p['period']}-{p['number']}", "", "")
    d.add_page()
    d.heading(f"قسيمة راتب {p['period']}", f"{pdfgen.hijri(bounds(p['period'])[1])}")
    d.kv([("الموظف", p["name"]), ("الرقم الوظيفي", p["number"]), ("القسم", p["department"] or "—"), ("المسمى", p["position"] or "—"), ("تاريخ التعيين", pdfgen.hijri(p["hire_date"])),
          ("حالة المسيّر", "مدفوع" if p["run_status"] == "paid" else "معتمد")])
    rows_ = [[x["name"], pdfgen.money(x["amount"])] for x in p["earnings"]]
    if p["adj_earn"]:
        rows_.append(["تسويات إضافية", pdfgen.money(p["adj_earn"])])
    rows_.append(["إجمالي الاستحقاقات", pdfgen.money(p["gross"] + p["adj_earn"])])
    d.grid(["الاستحقاقات", "المبلغ (ر.ع)"], rows_, widths=(4, 2), bold_last=True)
    ded = []
    if p["absence_ded"]:
        ded.append([f"غياب وإجازة بلا راتب ({p['absence_days']:g} يومًا)", pdfgen.money(p["absence_ded"])])
    if p["pasi_employee"]:
        ded.append(["حصة العامل من التأمينات الاجتماعية", pdfgen.money(p["pasi_employee"])])
    if p["loan_ded"]:
        ded.append(["قسط سلفة / قرض حسن", pdfgen.money(p["loan_ded"])])
    if p["adj_ded"]:
        ded.append(["استقطاعات أخرى", pdfgen.money(p["adj_ded"])])
    ded.append(["إجمالي الاستقطاعات", pdfgen.money(p["absence_ded"] + p["pasi_employee"] + p["loan_ded"] + p["adj_ded"])])
    d.grid(["الاستقطاعات", "المبلغ (ر.ع)"], ded, widths=(4, 2), bold_last=True)
    d.grid(["صافي الراتب", "المبلغ (ر.ع)"], [["الصافي المستحق", pdfgen.money(p["net"])]], widths=(4, 2), bold_last=True)
    d.para("صدرت هذه القسيمة إلكترونيًا من منصة مبانيك ولا تحتاج توقيعًا. تخص الموظف المذكور وحده.", 8.5, muted=True)
    return Response(bytes(d.output()), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="payslip-{p["period"]}-{p["number"]}.pdf"', "Cache-Control": "no-store"})


@router.get("/api/hr/payroll/payslips/{pid}.pdf")
def api_payslip_pdf(pid: int, u=Depends(act_as("hr_payroll"))):
    c = db()
    p = payslip_row(c, pid)
    audit(c, "فتح قسيمة راتب", f"{p['number']} · {p['period']}")
    c.commit()
    return payslip_pdf(c, p)


# ----------------------------------------------------------------------------------------------------- the employee's own salary papers
def _own_slip(c, u: dict, pid: int) -> dict:
    e = own_employee(c, u)
    p = payslip_row(c, pid)
    if p["employee_id"] != e["id"] or p["run_status"] not in ("approved", "paid"):
        raise HTTPException(404, "القسيمة غير موجودة")
    return p


@router.get("/api/hr/me/payslips")
def api_me_payslips(u=Depends(need("hr_self"))):
    c = db()
    e = own_employee(c, u)
    return rows(c.execute("""SELECT s.id, r.period, r.status, r.paid_on, s.gross, s.adj_earn, s.absence_ded, s.pasi_employee, s.loan_ded, s.adj_ded, s.net FROM payslips s JOIN payroll_runs r ON r.id=s.run_id
                             WHERE s.employee_id=? AND r.status IN ('approved','paid') ORDER BY r.period DESC""", (e["id"],)))


@router.get("/api/hr/me/payslips/{pid}.pdf")  # declared first: `{pid}` would otherwise swallow "12.pdf"
def api_me_payslip_pdf(pid: int, u=Depends(act_as("hr_self"))):
    c = db()
    return payslip_pdf(c, _own_slip(c, u, pid))


@router.get("/api/hr/me/payslips/{pid}")
def api_me_payslip(pid: int, u=Depends(need("hr_self"))):
    c = db()
    p = _own_slip(c, u, pid)
    p.pop("warnings", None)
    return p


@router.get("/api/hr/me/salary")
def api_me_salary(u=Depends(need("hr_self"))):
    c = db()
    e = own_employee(c, u)
    s = structure_on(c, e["id"], today())
    return s and {"effective_from": s["effective_from"], "basic": s["basic"], "lines": s["lines"], "total": s["total"]}
