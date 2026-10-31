"""Mabaniq 0.26.0 — human resources: end of service (design §5.3 "مكافأة نهاية الخدمة" and §5.4 "إنهاء الخدمة والمخالصة", phase 4b).

The end-of-service gratuity is computed from a rule the organisation enters (`eosb_rules`: tiers of days of the basic wage per year of service, per group — Omani or expatriate).
**No rule is seeded and none is guessed**: without one the calculator says so, the settlement carries a blocker and cannot be approved. The calculator shows every step.

A settlement is drafted, approved by a *different* person with `hr_payroll` (approval is what ends the person's service, closes his login and settles his open loan instalments),
and paid once a clearance checklist is complete. Everything needs `hr_payroll`.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from . import hr, ledger
from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .hr import employee, pdate
from .hr_payroll import ensure_setup, rate_on, structure_on
from .modules import one

router = APIRouter()
r3 = ledger.r3
EPS = ledger.EPS
KINDS = {"resignation": "استقالة", "termination": "إنهاء من صاحب العمل", "end_of_contract": "انتهاء العقد", "retirement": "تقاعد", "death": "وفاة", "other": "أخرى"}
CLEARANCE = ["إعادة العهدة والمعدات", "تسليم البطاقات والمفاتيح", "إلغاء الصلاحيات والحسابات", "إغلاق الحسابات والسلف", "مقابلة الخروج"]


# ----------------------------------------------------------------------------------------------------- the end-of-service rule and its calculator
def rule_on(c, grp: str, day: dt.date) -> dict | None:
    r = c.execute("SELECT * FROM eosb_rules WHERE grp=? AND valid_from<=? ORDER BY valid_from DESC LIMIT 1", (grp, day.isoformat())).fetchone()
    if not r:
        return None
    d = dict(r)
    d["tiers"] = json.loads(d["tiers"])
    return d


@router.get("/api/hr/eosb/rules")
def api_rules(_=Depends(need("hr_payroll"))):
    out = rows(db().execute("SELECT * FROM eosb_rules ORDER BY grp, valid_from DESC"))
    seen = set()
    for r in out:
        r["tiers"] = json.loads(r["tiers"])
        r["current"] = r["grp"] not in seen and r["valid_from"] <= today().isoformat()
        if r["current"]:
            seen.add(r["grp"])
    return out


class TierIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_years: float | None = Field(default=None, gt=0, le=80)
    days_per_year: float = Field(gt=0, le=365)


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grp: Literal["omani", "expat"]
    valid_from: str
    tiers: list[TierIn] = Field(min_length=1, max_length=6)
    cap_months: float | None = Field(default=None, gt=0, le=240)
    note: str = Field(min_length=5, max_length=300)  # the source: the law's article, a circular, the specialist who reviewed it


@router.post("/api/hr/eosb/rules")
def api_rule_add(b: RuleIn, u=Depends(act_as("hr_payroll"))):
    c = db()
    vf = pdate(b.valid_from, "تاريخ السريان").isoformat()
    last = 0.0
    for i, t in enumerate(b.tiers):
        if i < len(b.tiers) - 1:
            if t.to_years is None or t.to_years <= last:
                raise HTTPException(400, "حدود الشرائح تتصاعد، ولا يكون الحد مفتوحًا إلا في الشريحة الأخيرة")
            last = t.to_years
        elif t.to_years is not None:
            raise HTTPException(400, "الشريحة الأخيرة بلا حد أعلى (مفتوحة)")
    if c.execute("SELECT 1 FROM eosb_rules WHERE grp=? AND valid_from=?", (b.grp, vf)).fetchone():
        raise HTTPException(409, "للفئة نسخة بالتاريخ نفسه")
    c.execute("INSERT INTO eosb_rules(grp,valid_from,tiers,cap_months,note,created_by) VALUES(?,?,?,?,?,?)",
              (b.grp, vf, json.dumps([t.model_dump() for t in b.tiers]), b.cap_months, b.note.strip(), u["username"]))
    audit(c, "قاعدة مكافأة نهاية الخدمة", f"{'عُمانيون' if b.grp == 'omani' else 'وافدون'} من {vf} — {b.note.strip()}")
    c.commit()
    return {"ok": True}


def eosb_calc(c, e: dict, end: dt.date, last_basic: float) -> dict:
    """→ {amount, steps, years, reason}. `amount` is None when no rule applies — the caller treats that as a blocker, never as zero."""
    grp = "omani" if e["omani"] else "expat"
    years = round(max(0, (end - dt.date.fromisoformat(e["hire_date"])).days) / 365.25, 4)
    rule = rule_on(c, grp, end)
    if not rule:
        return {"amount": None, "steps": [], "years": years, "reason": f"لا قاعدة مكافأة نهاية خدمة مُدخَلة لفئة {'العُمانيين' if grp == 'omani' else 'الوافدين'} (تبويب «نهاية الخدمة»)"}
    divisor = rate_on(c, "day_divisor", end) or 30.0
    daily = last_basic / divisor
    steps, prev, total = [], 0.0, 0.0
    for t in rule["tiers"]:
        upper = t["to_years"] if t["to_years"] is not None else float("inf")
        part = max(0.0, min(years, upper) - prev)
        if part > 0:
            days = part * t["days_per_year"]
            amt = r3(days * daily)
            steps.append({"from": prev, "to": round(min(years, upper), 4), "years": round(part, 4), "days_per_year": t["days_per_year"], "days": round(days, 3), "amount": amt})
            total += amt
        prev = upper
    total = r3(total)
    capped = False
    if rule["cap_months"] and total > r3(rule["cap_months"] * last_basic):
        total, capped = r3(rule["cap_months"] * last_basic), True
    return {"amount": total, "steps": steps, "years": years, "daily_wage": r3(daily), "cap_applied": capped, "rule_from": rule["valid_from"], "reason": None}


@router.get("/api/hr/eosb/calc")
def api_calc(employee_id: int, end_date: str, u=Depends(act_as("hr_payroll"))):
    c = db()
    e = employee(c, employee_id)
    end = pdate(end_date, "تاريخ النهاية")
    s = structure_on(c, employee_id, end)
    if not s:
        raise HTTPException(409, "لا هيكل راتب للموظف في هذا التاريخ")
    audit(c, "حساب مكافأة نهاية خدمة", f"{e['number']} · {end}")
    c.commit()
    return eosb_calc(c, e, end, s["basic"])


# ----------------------------------------------------------------------------------------------------- the settlement
def settlement_calc(c, e: dict, end: dt.date, other_dues: float, other_deductions: float) -> dict:
    warns: list[dict] = []
    s = structure_on(c, e["id"], end)
    last_basic = r3(s["basic"]) if s else 0.0
    if not s:
        warns.append({"kind": "no_structure", "blocker": 1, "msg": "لا هيكل راتب للموظف في تاريخ النهاية"})
    eos = eosb_calc(c, e, end, last_basic)
    if eos["amount"] is None:
        warns.append({"kind": "no_eosb_rule", "blocker": 1, "msg": eos["reason"]})
    divisor = rate_on(c, "day_divisor", end) or 30.0
    from .hr_leave import balance, type_on
    leave_days = 0.0
    try:
        lt = type_on(c, "annual", end)
        if lt["paid"] and float(lt["days_per_year"]) > 0:
            leave_days = max(0.0, balance(c, e, "annual", end.year, end)["remaining"])
    except HTTPException:
        pass
    leave_payout = r3(leave_days * last_basic / divisor)
    loans_due = r3(c.execute("""SELECT COALESCE(SUM(i.amount),0) s FROM loan_installments i JOIN employee_loans l ON l.id=i.loan_id WHERE l.employee_id=? AND l.status='active' AND i.status='due'""",
                             (e["id"],)).fetchone()["s"])
    eosb = eos["amount"] or 0.0
    net = r3(eosb + leave_payout + other_dues - loans_due - other_deductions)
    if net < -EPS:
        warns.append({"kind": "negative_net", "blocker": 0, "msg": f"الصافي سالب ({net:.3f}) — على الموظف مبلغ لصاحب العمل"})
    warns.append({"kind": "final_salary", "blocker": 0, "msg": "راتب الشهر الأخير لا يدخل هنا: يُدفع في مسيّره بالتناسب حتى تاريخ النهاية"})
    return {"service_years": eos["years"], "last_basic": last_basic, "eosb_amount": r3(eosb), "eosb_steps": eos["steps"], "leave_days": round(leave_days, 3), "leave_payout": leave_payout,
            "loans_due": loans_due, "other_dues": r3(other_dues), "other_deductions": r3(other_deductions), "net": net, "warnings": warns}


def _t(c, tid: int) -> dict:
    t = dict(one(c, """SELECT t.*, e.number, e.name, e.omani FROM terminations t JOIN employees e ON e.id=t.employee_id WHERE t.id=?""", (tid,), "المخالصة غير موجودة"))
    t["eosb_steps"] = json.loads(t["eosb_steps"] or "[]")
    t["warnings"] = json.loads(t["warnings"] or "[]")
    t["clearance"] = json.loads(t["clearance"] or "[]")
    t["kind_label"] = KINDS.get(t["kind"], t["kind"])
    return t


class TermIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int
    end_date: str
    kind: Literal["resignation", "termination", "end_of_contract", "retirement", "death", "other"]
    note: str = Field(min_length=3, max_length=300)
    other_dues: float = Field(default=0, ge=0, le=1_000_000)
    other_deductions: float = Field(default=0, ge=0, le=1_000_000)


def _store(c, tid: int, calc: dict) -> None:
    c.execute("""UPDATE terminations SET service_years=?, last_basic=?, eosb_amount=?, eosb_steps=?, leave_days=?, leave_payout=?, loans_due=?, other_dues=?, other_deductions=?, net=?, warnings=? WHERE id=?""",
              (calc["service_years"], calc["last_basic"], calc["eosb_amount"], json.dumps(calc["eosb_steps"], ensure_ascii=False), calc["leave_days"], calc["leave_payout"], calc["loans_due"],
               calc["other_dues"], calc["other_deductions"], calc["net"], json.dumps(calc["warnings"], ensure_ascii=False), tid))


@router.get("/api/hr/terminations")
def api_terms(_=Depends(need("hr_payroll"))):
    return rows(db().execute("""SELECT t.id, t.employee_id, e.number, e.name, t.end_date, t.kind, t.status, t.net, t.eosb_amount FROM terminations t JOIN employees e ON e.id=t.employee_id ORDER BY t.id DESC"""))


@router.post("/api/hr/terminations")
def api_term_add(b: TermIn, u=Depends(act_as("hr_payroll"))):
    c = db()
    ensure_setup(c)
    e = employee(c, b.employee_id)
    end = pdate(b.end_date, "تاريخ النهاية")
    if c.execute("SELECT 1 FROM terminations WHERE employee_id=?", (b.employee_id,)).fetchone():
        raise HTTPException(409, "للموظف مخالصة بالفعل")
    if e["status"] == "terminated" and e["terminated_on"] != end.isoformat():
        raise HTTPException(409, f"انتهت خدمته في {e['terminated_on']} — اجعل تاريخ النهاية مطابقًا")
    if end.isoformat() < e["hire_date"]:
        raise HTTPException(400, "تاريخ النهاية قبل التعيين")
    calc = settlement_calc(c, e, end, b.other_dues, b.other_deductions)
    tid = c.execute("INSERT INTO terminations(employee_id,end_date,kind,note,clearance,created_by) VALUES(?,?,?,?,?,?)",
                    (b.employee_id, end.isoformat(), b.kind, b.note.strip(), json.dumps([{"item": x, "done": False} for x in CLEARANCE], ensure_ascii=False), u["username"])).lastrowid
    _store(c, tid, calc)
    audit(c, "مخالصة نهاية خدمة (مسودة)", f"{e['number']} · {end.isoformat()} · {KINDS[b.kind]}")
    c.commit()
    return {"id": tid}


@router.get("/api/hr/terminations/{tid}.pdf")  # declared before `{tid}`, which would swallow "1.pdf"
def api_term_pdf(tid: int, u=Depends(act_as("hr_payroll"))):
    from . import pdfgen
    from .paperwork import brand
    c = db()
    t = _t(c, tid)
    d = pdfgen.Doc(brand(c), "settlement", t["number"], "", "")
    d.add_page()
    d.heading("مخالصة نهاية خدمة", f"{pdfgen.hijri(t['end_date'])}")
    d.kv([("الموظف", t["name"]), ("الرقم الوظيفي", t["number"]), ("سبب انتهاء الخدمة", t["kind_label"]), ("سنوات الخدمة", f"{t['service_years']:.2f}"), ("آخر أجر أساسي", pdfgen.money(t["last_basic"])),
          ("الحالة", {"draft": "مسودة", "approved": "معتمدة", "paid": "مدفوعة"}[t["status"]])])
    rws = [[f"مكافأة نهاية الخدمة ({s['years']:.2f} سنة × {s['days_per_year']:g} يومًا)", pdfgen.money(s["amount"])] for s in t["eosb_steps"]] or [["مكافأة نهاية الخدمة", pdfgen.money(t["eosb_amount"])]]
    rws += [[f"بدل إجازة رصيد ({t['leave_days']:g} يومًا)", pdfgen.money(t["leave_payout"])], ["مستحقات أخرى", pdfgen.money(t["other_dues"])],
            ["يُخصم: أقساط سلف وقروض حسنة", "−" + pdfgen.money(t["loans_due"])], ["يُخصم: استقطاعات أخرى", "−" + pdfgen.money(t["other_deductions"])], ["صافي المخالصة", pdfgen.money(t["net"])]]
    d.grid(["البند", "المبلغ (ر.ع)"], rws, widths=(4, 2), bold_last=True)
    d.para("بند إخلاء الطرف: " + "، ".join(f"{x['item']} ({'تم' if x['done'] else 'لم يتم'})" for x in t["clearance"]), 8.5, muted=True)
    d.para("راتب الشهر الأخير يُدفع في مسيّره بالتناسب حتى تاريخ النهاية ولا يدخل في هذه المخالصة.", 8.5, muted=True)
    d.signatures(("الموظف", t["name"]), ("صاحب العمل", brand(c).get("name") or "المنشأة"))
    audit(c, "طباعة مخالصة", t["number"])
    c.commit()
    return Response(bytes(d.output()), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="settlement-{t["number"]}.pdf"', "Cache-Control": "no-store"})


@router.get("/api/hr/terminations/{tid}")
def api_term(tid: int, u=Depends(act_as("hr_payroll"))):
    c = db()
    t = _t(c, tid)
    audit(c, "اطلاع على مخالصة", f"{t['number']}")
    c.commit()
    return t


class TermEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    end_date: str | None = None
    other_dues: float | None = Field(default=None, ge=0, le=1_000_000)
    other_deductions: float | None = Field(default=None, ge=0, le=1_000_000)
    note: str | None = Field(default=None, min_length=3, max_length=300)
    clearance: list[dict] | None = None


@router.post("/api/hr/terminations/{tid}/recalc")
def api_term_recalc(tid: int, b: TermEdit, u=Depends(act_as("hr_payroll"))):
    """Redo the arithmetic of a draft (a rule was entered, an amount changed) and/or tick the clearance list. An approved settlement is frozen."""
    c = db()
    t = _t(c, tid)
    e = employee(c, t["employee_id"])
    if t["status"] != "draft":
        clear_only = b.model_fields_set <= {"clearance"}
        if not clear_only:
            raise HTTPException(409, "المخالصة معتمدة — لا يُعاد حسابها")
    if b.clearance is not None:
        items = [{"item": str(x.get("item", ""))[:80], "done": bool(x.get("done"))} for x in b.clearance][:20]
        if [i["item"] for i in items] != [i["item"] for i in t["clearance"]]:
            raise HTTPException(400, "بنود الإخلاء ثابتة — غيّر حالتها فقط")
        c.execute("UPDATE terminations SET clearance=? WHERE id=?", (json.dumps(items, ensure_ascii=False), tid))
    if t["status"] == "draft" and (b.model_fields_set - {"clearance"}):
        end = pdate(b.end_date or t["end_date"], "تاريخ النهاية")
        if e["status"] == "terminated" and e["terminated_on"] != end.isoformat():
            raise HTTPException(409, f"انتهت خدمته في {e['terminated_on']}")
        calc = settlement_calc(c, e, end, t["other_dues"] if b.other_dues is None else b.other_dues, t["other_deductions"] if b.other_deductions is None else b.other_deductions)
        c.execute("UPDATE terminations SET end_date=?, note=? WHERE id=?", (end.isoformat(), (b.note or t["note"]), tid))
        _store(c, tid, calc)
    audit(c, "تعديل مخالصة", f"{t['number']}")
    c.commit()
    return _t(c, tid)


@router.post("/api/hr/terminations/{tid}/approve")
def api_term_approve(tid: int, u=Depends(act_as("hr_payroll"))):
    """Approval is the act that ends the service: the file becomes terminated (login closed, later leave cancelled), open loan instalments are marked settled, and the books
    get one journal. The person who drafted it never approves it, and nobody approves his own settlement."""
    c = db()
    t = _t(c, tid)
    if t["status"] != "draft":
        raise HTTPException(409, "المخالصة ليست مسودة")
    if t["created_by"] == u["username"]:
        raise HTTPException(403, "لا تعتمد مخالصة أعددتها — يعتمدها شخص آخر لديه صلاحية الرواتب")
    if u.get("employee_id") == t["employee_id"]:
        raise HTTPException(403, "لا تعتمد مخالصتك")
    e = employee(c, t["employee_id"])
    calc = settlement_calc(c, e, pdate(t["end_date"]), t["other_dues"], t["other_deductions"])  # recomputed at the moment of approval: a rule or a loan may have changed
    bad = [w["msg"] for w in calc["warnings"] if w["blocker"]]
    if bad:
        _store(c, tid, calc)
        c.commit()
        raise HTTPException(409, "عوائق تمنع الاعتماد: " + " | ".join(bad))
    _store(c, tid, calc)
    if e["status"] != "terminated":
        hr.terminate(c, e, t["end_date"], t["note"], u["name"])
    c.execute("""UPDATE loan_installments SET status='settled' WHERE status='due' AND loan_id IN (SELECT id FROM employee_loans WHERE employee_id=? AND status='active')""", (t["employee_id"],))
    c.execute("UPDATE employee_loans SET status='paid' WHERE employee_id=? AND status='active'", (t["employee_id"],))
    c.execute("UPDATE terminations SET status='approved', approved_by=?, approved_at=? WHERE id=?", (u["username"], now_s(), tid))
    audit(c, "اعتماد مخالصة نهاية خدمة", f"{t['number']} · {t['end_date']}")
    note = None
    if ledger.start_date(c):
        try:
            ledger.ensure_chart(c)
            post_settlement(c, ledger.Ctx(c), _t(c, tid))
        except ledger.LedgerError as ex:
            note = f"لم تُرحَّل إلى المحاسبة: {ex}"
    c.commit()
    return {"status": "approved", "note": note}


class TermPay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paid_on: str
    bank_account_id: int | None = None


@router.post("/api/hr/terminations/{tid}/pay")
def api_term_pay(tid: int, b: TermPay, u=Depends(act_as("hr_payroll"))):
    c = db()
    t = _t(c, tid)
    if t["status"] != "approved":
        raise HTTPException(409, "يُسجَّل الدفع بعد الاعتماد")
    if not all(x["done"] for x in t["clearance"]):
        raise HTTPException(409, "قائمة إخلاء الطرف غير مكتملة: " + "، ".join(x["item"] for x in t["clearance"] if not x["done"]))
    day = pdate(b.paid_on, "تاريخ الدفع")
    if b.bank_account_id is not None:
        one(c, "SELECT 1 FROM bank_accounts WHERE id=? AND active=1", (b.bank_account_id,), "الحساب البنكي غير موجود")
    elif ledger.start_date(c) and t["net"] > 0:
        raise HTTPException(400, "اختر الحساب البنكي الذي صُرفت منه المخالصة — المحاسبة مفعَّلة ولا يُقيَّد الدفع بدونه")
    c.execute("UPDATE terminations SET status='paid', paid_on=?, bank_account_id=? WHERE id=?", (day.isoformat(), b.bank_account_id, tid))
    audit(c, "دفع مخالصة", f"{t['number']} · {day.isoformat()}")
    note = None
    if ledger.start_date(c) and b.bank_account_id:
        try:
            post_settlement(c, ledger.Ctx(c), _t(c, tid))
        except ledger.LedgerError as ex:
            note = f"لم يُرحَّل الدفع إلى المحاسبة: {ex}"
    c.commit()
    return {"status": "paid", "note": note}


def post_settlement(c, ctx, t: dict) -> None:
    """One journal at approval: the gratuity and the leave pay are expenses, the loans are recovered, the rest is owed to the leaver. Then, once paid, the payment."""
    if t["status"] in ("approved", "paid") and not t["journal_id"]:
        L = [dict(account="exp_eosb", debit=t["eosb_amount"]), dict(account="exp_payroll", debit=r3(t["leave_payout"] + t["other_dues"])),
             dict(account="emp_loans", credit=t["loans_due"], party_type="employee", party_id=t["employee_id"]), dict(account="rev_other", credit=t["other_deductions"])]   # not "recoveries from tenants" (0.28.1)
        L.append(dict(account="payroll_payable", **({"credit": t["net"]} if t["net"] >= 0 else {"debit": -t["net"]}), party_type="employee", party_id=t["employee_id"]))
        jid = ledger.post(c, date=dt.date.fromisoformat(t["end_date"]), memo=f"مخالصة نهاية خدمة — {t['number']}", source_kind="settlement", source_ref=str(t["id"]),
                          source_key=f"settlement:{t['id']}", ctx=ctx, lines=L)
        if jid:
            c.execute("UPDATE terminations SET journal_id=? WHERE id=?", (jid, t["id"]))
    if t["status"] == "paid" and t["bank_account_id"] and not t["payment_journal_id"] and t["net"] > EPS:
        gl = c.execute("SELECT account_id FROM bank_accounts WHERE id=?", (t["bank_account_id"],)).fetchone()["account_id"]
        jid = ledger.post(c, date=dt.date.fromisoformat(t["paid_on"]), memo=f"دفع مخالصة — {t['number']}", source_kind="settlement_pay", source_ref=str(t["id"]),
                          source_key=f"settlement_pay:{t['id']}", ctx=ctx, lines=[dict(account="payroll_payable", debit=t["net"], party_type="employee", party_id=t["employee_id"]), dict(account=gl, credit=t["net"])])   # 0.29.0: names the leaver, so his payable closes to zero
        if jid:
            c.execute("UPDATE terminations SET payment_journal_id=? WHERE id=?", (jid, t["id"]))


def sync_settlements(c, ctx, start: str, dry: bool, res: dict) -> None:
    for tid in [r["id"] for r in c.execute("SELECT id FROM terminations WHERE status IN ('approved','paid') AND end_date>=? AND (journal_id IS NULL OR (status='paid' AND bank_account_id IS NOT NULL AND payment_journal_id IS NULL))",
                                          (start,)).fetchall()]:
        res["pending"]["payroll"] += 1
        if dry:
            continue
        try:
            post_settlement(c, ctx, _t(c, tid))
        except ledger.LedgerError as err:
            res["errors"].append(f"مخالصة {tid}: {err}")
            continue
        res["posted"]["payroll"] += 1
