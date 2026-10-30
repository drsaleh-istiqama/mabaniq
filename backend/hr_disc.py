"""Mabaniq 0.27.0 — human resources: discipline (design §5.4, phase 4c).

**No penalty without an approved bylaw.** A penalty is issued only under an article of `penalty_rules` that a second person approved, that was in force on the day of the
incident, and within the article's maximum; the employee's statement is taken before a penalty is proposed; the person who proposed it never issues it; the accused never
decides anything in his own case. The employee sees his issued notices and may appeal within a period (7 days unless the organisation sets another); an appeal is decided by
someone other than the issuer. A *deduction* is a number of days of wage that payroll applies in the chosen month — HR never sees the salary (`hr_payroll` computes the amount).
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .db import setting
from .hr import employee, next_no, own_employee, pdate
from .modules import one

router = APIRouter()
KINDS = {"warning": "إنذار كتابي", "deduction": "خصم من الأجر", "suspension": "إيقاف عن العمل"}
STATUS = {"open": "قيد الدراسة", "proposed": "مقترح — بانتظار الإصدار", "issued": "صادر", "appealed": "متظلَّم منه", "revoked": "ملغى", "closed": "مغلق بلا جزاء"}
APPEAL_DAYS = 7


# ----------------------------------------------------------------------------------------------------- the bylaw
@router.get("/api/hr/discipline/rules")
def api_rules(_=Depends(need("hr"))):
    return rows(db().execute("SELECT * FROM penalty_rules ORDER BY status, code"))


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=1000)
    kind: Literal["warning", "deduction", "suspension"]
    max_days: float = Field(default=0, ge=0, le=60)
    source: str = Field(min_length=5, max_length=300)  # the approved bylaw and article this comes from


@router.post("/api/hr/discipline/rules")
def api_rule_add(b: RuleIn, u=Depends(act_as("hr"))):
    c = db()
    if c.execute("SELECT 1 FROM penalty_rules WHERE code=?", (b.code.strip(),)).fetchone():
        raise HTTPException(409, "رمز المادة مستخدم")
    if b.kind != "warning" and b.max_days <= 0:
        raise HTTPException(400, "الخصم والإيقاف يلزمهما حد أقصى للأيام أكبر من صفر")
    rid = c.execute("INSERT INTO penalty_rules(code,name,description,kind,max_days,source,created_by) VALUES(?,?,?,?,?,?,?)",
                    (b.code.strip(), b.name.strip(), b.description or None, b.kind, b.max_days if b.kind != "warning" else 0, b.source.strip(), u["username"])).lastrowid
    audit(c, "مادة جزاء (مسودة)", f"{b.code} · {b.name}")
    c.commit()
    return {"id": rid}


class ApproveRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid_from: str


@router.post("/api/hr/discipline/rules/{rid}/approve")
def api_rule_approve(rid: int, b: ApproveRule, u=Depends(act_as("hr"))):
    """A second person confirms that the article matches the approved bylaw. `valid_from` is the bylaw's own effective date — a penalty cannot rest on an article newer than the incident."""
    c = db()
    r = dict(one(c, "SELECT * FROM penalty_rules WHERE id=?", (rid,), "المادة غير موجودة"))
    if r["status"] != "draft":
        raise HTTPException(409, "المادة ليست مسودة")
    if r["created_by"] == u["username"]:
        raise HTTPException(403, "لا تعتمد مادة أنشأتها — يعتمدها شخص آخر")
    vf = pdate(b.valid_from, "تاريخ سريان اللائحة")
    if vf > today():
        raise HTTPException(400, "سريان اللائحة في المستقبل")
    c.execute("UPDATE penalty_rules SET status='approved', valid_from=?, approved_by=?, approved_at=? WHERE id=?", (vf.isoformat(), u["username"], now_s(), rid))
    audit(c, "اعتماد مادة جزاء", f"{r['code']} · من {vf.isoformat()}")
    c.commit()
    return {"ok": True}


@router.post("/api/hr/discipline/rules/{rid}/retire")
def api_rule_retire(rid: int, u=Depends(act_as("hr"))):
    c = db()
    r = one(c, "SELECT code, status FROM penalty_rules WHERE id=?", (rid,), "المادة غير موجودة")
    if r["status"] == "retired":
        raise HTTPException(409, "المادة موقوفة")
    c.execute("UPDATE penalty_rules SET status='retired' WHERE id=?", (rid,))
    audit(c, "إيقاف مادة جزاء", r["code"])
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- cases
CASE_SQL = """SELECT d.*, e.number emp_number, e.name emp_name, r.code rule_code, r.name rule_name, r.kind rule_kind, r.max_days rule_max FROM disciplinary_cases d
              JOIN employees e ON e.id=d.employee_id LEFT JOIN penalty_rules r ON r.id=d.rule_id"""


def _case(c, did: int) -> dict:
    x = dict(one(c, CASE_SQL + " WHERE d.id=?", (did,), "القضية غير موجودة"))
    x["status_label"] = STATUS[x["status"]]
    return x


def _not_self(u: dict, case: dict) -> None:
    if u.get("employee_id") and u["employee_id"] == case["employee_id"]:
        raise HTTPException(403, "لا تبتّ في قضية تخصّك")


@router.get("/api/hr/discipline/cases")
def api_cases(status: str | None = Query(None, pattern="^(open|proposed|issued|appealed|revoked|closed)$"), employee_id: int | None = None, u=Depends(act_as("hr"))):
    c = db()
    where, args = [], []
    if status:
        where.append("d.status=?")
        args.append(status)
    if employee_id:
        where.append("d.employee_id=?")
        args.append(employee_id)
    out = rows(c.execute(CASE_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY d.id DESC", tuple(args)))
    for x in out:
        x["status_label"] = STATUS[x["status"]]
    audit(c, "اطلاع على قضايا تأديبية", f"{len(out)} قضية")
    c.commit()
    return out


@router.get("/api/hr/discipline/cases/{did}")
def api_case(did: int, u=Depends(act_as("hr"))):
    c = db()
    x = _case(c, did)
    audit(c, "فتح قضية تأديبية", x["number"])
    c.commit()
    return x


class CaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int
    incident_date: str
    description: str = Field(min_length=10, max_length=2000)
    witnesses: str = Field(default="", max_length=500)


@router.post("/api/hr/discipline/cases")
def api_case_add(b: CaseIn, u=Depends(act_as("hr"))):
    c = db()
    e = employee(c, b.employee_id)
    if e["status"] == "terminated":
        raise HTTPException(409, "الملف منتهي الخدمة")
    inc = pdate(b.incident_date, "تاريخ الواقعة")
    if inc > today() or inc.isoformat() < e["hire_date"]:
        raise HTTPException(400, "تاريخ الواقعة خارج مدة خدمة الموظف")
    if u.get("employee_id") == b.employee_id:
        raise HTTPException(403, "لا تفتح قضية على نفسك")
    number = f"DC-{today().year}-{next_no(c, f'hr:dc:{today().year}'):04d}"
    did = c.execute("INSERT INTO disciplinary_cases(number,employee_id,incident_date,description,witnesses,created_by) VALUES(?,?,?,?,?,?)",
                    (number, b.employee_id, inc.isoformat(), b.description.strip(), b.witnesses or None, u["username"])).lastrowid
    audit(c, "قضية تأديبية جديدة", f"{number} · {e['number']}")
    c.commit()
    return {"id": did, "number": number}


class StatementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=3, max_length=2000)


@router.post("/api/hr/discipline/cases/{did}/statement")
def api_statement(did: int, b: StatementIn, u=Depends(act_as("hr"))):
    """The employee's own words, taken before any penalty is proposed. If he declines, that is what is written."""
    c = db()
    x = _case(c, did)
    _not_self(u, x)
    if x["status"] not in ("open", "proposed"):
        raise HTTPException(409, "القضية لا تقبل إضافة أقوال في حالتها")
    c.execute("UPDATE disciplinary_cases SET statement=? WHERE id=?", (b.statement.strip(), did))
    audit(c, "أقوال موظف في قضية", x["number"])
    c.commit()
    return {"ok": True}


class ProposeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: int
    penalty_days: float = Field(default=0, ge=0, le=60)
    apply_period: str = Field(default="", pattern=r"^(\d{4}-(0[1-9]|1[0-2]))?$")


@router.post("/api/hr/discipline/cases/{did}/propose")
def api_propose(did: int, b: ProposeIn, u=Depends(act_as("hr"))):
    c = db()
    x = _case(c, did)
    _not_self(u, x)
    if x["status"] != "open":
        raise HTTPException(409, "تُقترح العقوبة على قضية قيد الدراسة")
    if not (x["statement"] or "").strip():
        raise HTTPException(409, "تؤخذ أقوال الموظف قبل اقتراح أي عقوبة")
    r = dict(one(c, "SELECT * FROM penalty_rules WHERE id=?", (b.rule_id,), "المادة غير موجودة"))
    if r["status"] != "approved":
        raise HTTPException(409, "لا جزاء إلا بمادة من لائحة معتمدة — هذه المادة ليست معتمدة")
    if r["valid_from"] > x["incident_date"]:
        raise HTTPException(409, "لم تكن المادة سارية يوم الواقعة")
    days = b.penalty_days if r["kind"] != "warning" else 0.0
    if r["kind"] != "warning" and not 0 < days <= r["max_days"]:
        raise HTTPException(400, f"أيام الجزاء بين أكثر من صفر و{r['max_days']:g} بحسب المادة")
    period = b.apply_period or None
    if r["kind"] == "deduction":
        if not period:
            raise HTTPException(400, "حدّد شهر الخصم")
        if c.execute("SELECT 1 FROM payroll_runs WHERE period=? AND status IN ('approved','paid')", (period,)).fetchone():
            raise HTTPException(409, "مسيّر هذا الشهر معتمد — اختر شهرًا لاحقًا")
    c.execute("UPDATE disciplinary_cases SET status='proposed', rule_id=?, penalty_days=?, apply_period=?, proposed_by=? WHERE id=?", (b.rule_id, days, period, u["username"], did))
    audit(c, "اقتراح جزاء", f"{x['number']} · مادة {r['code']}")
    c.commit()
    return {"ok": True}


@router.post("/api/hr/discipline/cases/{did}/issue")
def api_issue(did: int, u=Depends(act_as("hr"))):
    c = db()
    x = _case(c, did)
    _not_self(u, x)
    if x["status"] != "proposed":
        raise HTTPException(409, "القضية ليست بانتظار الإصدار")
    if x["proposed_by"] == u["username"]:
        raise HTTPException(403, "لا تُصدر جزاءً اقترحته — يُصدره شخص آخر")
    if x["rule_kind"] is None or c.execute("SELECT status FROM penalty_rules WHERE id=?", (x["rule_id"],)).fetchone()["status"] != "approved":
        raise HTTPException(409, "المادة لم تعد معتمدة")
    if x["rule_kind"] == "deduction" and x["apply_period"] and c.execute("SELECT 1 FROM payroll_runs WHERE period=? AND status IN ('approved','paid')", (x["apply_period"],)).fetchone():
        raise HTTPException(409, f"مسيّر {x['apply_period']} اعتُمد بعد الاقتراح — أعد اقتراح الجزاء على شهر لاحق حتى لا يضيع الخصم")
    c.execute("UPDATE disciplinary_cases SET status='issued', issued_by=?, issued_at=? WHERE id=?", (u["username"], now_s(), did))
    audit(c, "إصدار جزاء", f"{x['number']} · {x['emp_number']} · {KINDS[x['rule_kind']]}")
    c.commit()
    return {"status": "issued"}


class CloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=3, max_length=500)


@router.post("/api/hr/discipline/cases/{did}/close")
def api_close(did: int, b: CloseIn, u=Depends(act_as("hr"))):
    c = db()
    x = _case(c, did)
    _not_self(u, x)
    if x["status"] not in ("open", "proposed"):
        raise HTTPException(409, "القضية لا تُغلق بلا جزاء في حالتها")
    c.execute("UPDATE disciplinary_cases SET status='closed', closed_note=? WHERE id=?", (b.note.strip(), did))
    audit(c, "إغلاق قضية تأديبية بلا جزاء", x["number"])
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- the employee's side: notices and appeal
def appeal_days(c) -> int:
    try:
        return max(1, int(setting(c, "hr:appeal_days", APPEAL_DAYS)))
    except (TypeError, ValueError):
        return APPEAL_DAYS


@router.get("/api/hr/me/discipline")
def api_me_cases(u=Depends(need("hr_self"))):
    """Only what has been issued to him (and its fate): a case still being studied is not shown, and nobody else's case ever is."""
    c = db()
    e = own_employee(c, u)
    out = rows(c.execute("""SELECT d.id, d.number, d.incident_date, d.description, d.status, d.penalty_days, d.apply_period, d.issued_at, d.appeal_text, d.appeal_at, d.appeal_decision, d.appeal_decided_at,
                            r.name rule_name, r.kind rule_kind, r.code rule_code FROM disciplinary_cases d LEFT JOIN penalty_rules r ON r.id=d.rule_id
                            WHERE d.employee_id=? AND d.status IN ('issued','appealed','revoked') ORDER BY d.id DESC""", (e["id"],)))
    win = appeal_days(c)
    for x in out:
        x["status_label"] = STATUS[x["status"]]
        x["can_appeal"] = x["status"] == "issued" and not x["appeal_text"] and x["issued_at"] and (dt.datetime.now() - dt.datetime.fromisoformat(x["issued_at"])).days <= win
    return out


class AppealIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=10, max_length=2000)


@router.post("/api/hr/me/discipline/{did}/appeal")
def api_appeal(did: int, b: AppealIn, u=Depends(act_as("hr_self"))):
    c = db()
    e = own_employee(c, u)
    x = _case(c, did)
    if x["employee_id"] != e["id"] or x["status"] not in ("issued", "appealed", "revoked"):
        raise HTTPException(404, "القضية غير موجودة")
    if x["status"] != "issued" or x["appeal_text"]:
        raise HTTPException(409, "لا يُتظلَّم في هذه الحالة")
    if (dt.datetime.now() - dt.datetime.fromisoformat(x["issued_at"])).days > appeal_days(c):
        raise HTTPException(409, f"انقضت مهلة التظلم ({appeal_days(c)} أيام)")
    c.execute("UPDATE disciplinary_cases SET status='appealed', appeal_text=?, appeal_at=? WHERE id=?", (b.text.strip(), now_s(), did))
    audit(c, "تظلم من جزاء", x["number"])
    c.commit()
    return {"status": "appealed"}


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["upheld", "revoked"]
    apply_period: str = Field(default="", pattern=r"^(\d{4}-(0[1-9]|1[0-2]))?$")


@router.post("/api/hr/discipline/cases/{did}/appeal-decision")
def api_appeal_decision(did: int, b: DecisionIn, u=Depends(act_as("hr"))):
    c = db()
    x = _case(c, did)
    _not_self(u, x)
    if x["status"] != "appealed":
        raise HTTPException(409, "لا تظلّم قائمًا")
    if x["issued_by"] == u["username"]:
        raise HTTPException(403, "من أصدر الجزاء لا يبتّ في التظلم منه")
    if b.decision == "revoked":
        if x["applied_run_id"]:
            raise HTTPException(409, "طُبّق الخصم في مسيّر معتمد — سجّل تسوية استحقاق في الرواتب ثم ألغِ")
        c.execute("UPDATE disciplinary_cases SET status='revoked', appeal_decision='revoked', appeal_decided_by=?, appeal_decided_at=? WHERE id=?", (u["username"], now_s(), did))
    else:
        period = b.apply_period or x["apply_period"]
        if x["rule_kind"] == "deduction" and period and c.execute("SELECT 1 FROM payroll_runs WHERE period=? AND status IN ('approved','paid')", (period,)).fetchone() and not x["applied_run_id"]:
            raise HTTPException(409, "مسيّر شهر الخصم معتمد — اختر شهرًا لاحقًا")
        c.execute("UPDATE disciplinary_cases SET status='issued', appeal_decision='upheld', appeal_decided_by=?, appeal_decided_at=?, apply_period=? WHERE id=?", (u["username"], now_s(), period, did))
    audit(c, "قرار في تظلم", f"{x['number']} ← {b.decision}")
    c.commit()
    return {"ok": True}


def deductions_for(c, employee_id: int, period: str) -> list[dict]:
    """Issued deductions awaiting payroll for `period` — the payroll computes the amount from the salary; HR never sees it."""
    return rows(c.execute("""SELECT d.id, d.number, d.penalty_days, r.code FROM disciplinary_cases d JOIN penalty_rules r ON r.id=d.rule_id
                             WHERE d.employee_id=? AND d.status='issued' AND r.kind='deduction' AND d.apply_period=? AND d.applied_run_id IS NULL""", (employee_id, period)))
