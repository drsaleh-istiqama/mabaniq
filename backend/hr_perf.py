"""Mabaniq 0.27.0 — human resources: the annual appraisal and training (design §5.4, phase 4c).

An appraisal runs self → direct manager → HR → acknowledged by the employee. The employee never sees his manager's scores or comment before HR finalises (so a draft opinion
cannot be argued over), the manager reviews only his direct reports, and nobody reviews, finalises or acknowledges his own appraisal on someone else's behalf. The overall score is
computed, not typed: 70 % goals (each weighted, weights = 100) + 30 % competencies, on the 1–5 scale; the rating bands are fixed labels, not a pay decision — a decision such as a
promotion or a raise is only recorded here and changes no salary.

Training: courses, who attended what, a certificate with an expiry that joins the document alerts of 0.25.0, and a compliance list of the mandatory courses.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import hr
from .auth import need, need_any
from .common import ACTOR, act_as, audit, db, now_s, rows, today
from .hr import employee, own_employee, pdate
from .hr_leave import add_months
from .modules import one

router = APIRouter()
DEFAULT_COMPETENCIES = ["جودة العمل", "الالتزام والانضباط", "العمل ضمن فريق", "المبادرة وحل المشكلات", "التواصل"]
BANDS = ((4.5, "متميز"), (3.5, "يتجاوز التوقعات"), (2.5, "يلبّي التوقعات"), (1.5, "يحتاج إلى تحسين"), (0.0, "دون المطلوب"))
GOAL_WEIGHT, COMP_WEIGHT = 0.7, 0.3
DECISIONS = {"none": "بلا قرار", "promotion": "ترقية", "raise": "زيادة", "training": "تدريب", "improvement_plan": "خطة تحسين", "no_action": "لا إجراء"}


def act_any(*perms):
    async def dep(u: dict = Depends(need_any(*perms))):
        ACTOR.set(f"{u['name']} ({u['role_label']})")
        return u
    return dep


def band(score: float) -> str:
    return next(label for lo, label in BANDS if score >= lo)


# ----------------------------------------------------------------------------------------------------- cycles
@router.get("/api/hr/appraisal-cycles")
def api_cycles(_=Depends(need("hr"))):
    return rows(db().execute("""SELECT k.*, (SELECT COUNT(*) FROM appraisals a WHERE a.cycle_id=k.id) total,
                                (SELECT COUNT(*) FROM appraisals a WHERE a.cycle_id=k.id AND a.status IN ('final','ack')) done FROM appraisal_cycles k ORDER BY k.year DESC, k.id DESC"""))


class CycleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=80)
    year: int = Field(ge=2000, le=2100)
    start_date: str
    end_date: str


@router.post("/api/hr/appraisal-cycles")
def api_cycle_add(b: CycleIn, u=Depends(act_as("hr"))):
    c = db()
    s, e = pdate(b.start_date, "بداية الدورة"), pdate(b.end_date, "نهاية الدورة")
    if e <= s:
        raise HTTPException(400, "نهاية الدورة بعد بدايتها")
    if c.execute("SELECT 1 FROM appraisal_cycles WHERE name=?", (b.name.strip(),)).fetchone():
        raise HTTPException(409, "دورة بهذا الاسم موجودة")
    cid = c.execute("INSERT INTO appraisal_cycles(name,year,start_date,end_date,created_by) VALUES(?,?,?,?,?)", (b.name.strip(), b.year, s.isoformat(), e.isoformat(), u["name"])).lastrowid
    audit(c, "دورة تقييم", b.name)
    c.commit()
    return {"id": cid}


@router.post("/api/hr/appraisal-cycles/{cid}/open")
def api_cycle_open(cid: int, u=Depends(act_as("hr"))):
    """Open the cycle and give every person on the payroll who had served at least 90 days by its end an appraisal (idempotent: a second call adds only the missing)."""
    c = db()
    k = dict(one(c, "SELECT * FROM appraisal_cycles WHERE id=?", (cid,), "الدورة غير موجودة"))
    if k["status"] == "closed":
        raise HTTPException(409, "الدورة مغلقة")
    cutoff = (pdate(k["end_date"]) - dt.timedelta(days=90)).isoformat()
    comps = json.dumps([{"name": n, "self_score": None, "mgr_score": None} for n in DEFAULT_COMPETENCIES], ensure_ascii=False)
    added = 0
    for e in c.execute("SELECT id, manager_id FROM employees WHERE status!='terminated' AND hire_date<=?", (cutoff,)).fetchall():
        if not c.execute("SELECT 1 FROM appraisals WHERE cycle_id=? AND employee_id=?", (cid, e["id"])).fetchone():
            c.execute("INSERT INTO appraisals(cycle_id,employee_id,reviewer_id,goals,competencies) VALUES(?,?,?,?,?)", (cid, e["id"], e["manager_id"], "[]", comps))
            added += 1
    c.execute("UPDATE appraisal_cycles SET status='open' WHERE id=?", (cid,))
    audit(c, "فتح دورة تقييم", f"{k['name']} · {added} تقييمًا")
    c.commit()
    return {"added": added}


class CloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force: bool = False


@router.post("/api/hr/appraisal-cycles/{cid}/close")
def api_cycle_close(cid: int, b: CloseIn, u=Depends(act_as("hr"))):
    c = db()
    k = dict(one(c, "SELECT * FROM appraisal_cycles WHERE id=?", (cid,), "الدورة غير موجودة"))
    open_n = c.execute("SELECT COUNT(*) n FROM appraisals WHERE cycle_id=? AND status IN ('self','manager','hr')", (cid,)).fetchone()["n"]
    if open_n and not b.force:
        raise HTTPException(409, f"{open_n} تقييمًا لم يكتمل — أكمله أو أغلق بتجاوز صريح")
    c.execute("UPDATE appraisal_cycles SET status='closed' WHERE id=?", (cid,))
    audit(c, "إغلاق دورة تقييم", f"{k['name']} · غير مكتمل {open_n}")
    c.commit()
    return {"ok": True, "incomplete": open_n}


# ----------------------------------------------------------------------------------------------------- reading an appraisal
def _load(c, aid: int) -> dict:
    a = dict(one(c, """SELECT a.*, k.name cycle, k.status cycle_status, e.number, e.name, e.manager_id, m.name reviewer FROM appraisals a JOIN appraisal_cycles k ON k.id=a.cycle_id
                       JOIN employees e ON e.id=a.employee_id LEFT JOIN employees m ON m.id=a.reviewer_id WHERE a.id=?""", (aid,), "التقييم غير موجود"))
    a["goals"] = json.loads(a["goals"] or "[]")
    a["competencies"] = json.loads(a["competencies"] or "[]")
    a["decision_label"] = DECISIONS[a["decision"]]
    return a


def _view_for_employee(a: dict) -> dict:
    """What the employee himself may see: his own self-assessment always; the manager's scores, comment, overall and decision only after HR finalised."""
    a = dict(a)
    if a["status"] not in ("final", "ack"):
        for g in a["goals"]:
            g.pop("mgr_score", None)
        for k in a["competencies"]:
            k.pop("mgr_score", None)
        for f in ("manager_comment", "hr_comment", "overall", "rating", "manager_at", "hr_at", "hr_by"):
            a[f] = None
        a["decision"], a["decision_label"] = "none", ""
    return a


@router.get("/api/hr/appraisals")
def api_appraisals(cycle_id: int | None = None, status: str | None = Query(None, pattern="^(self|manager|hr|final|ack)$"), _=Depends(need("hr"))):
    c = db()
    where, args = [], []
    if cycle_id:
        where.append("a.cycle_id=?")
        args.append(cycle_id)
    if status:
        where.append("a.status=?")
        args.append(status)
    return rows(c.execute("""SELECT a.id, a.cycle_id, k.name cycle, a.employee_id, e.number, e.name, m.name reviewer, a.status, a.overall, a.rating, a.decision FROM appraisals a
                             JOIN appraisal_cycles k ON k.id=a.cycle_id JOIN employees e ON e.id=a.employee_id LEFT JOIN employees m ON m.id=a.reviewer_id"""
                          + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY k.year DESC, e.number", tuple(args)))


@router.get("/api/hr/appraisals/{aid}")
def api_appraisal(aid: int, u=Depends(act_as("hr"))):
    c = db()
    a = _load(c, aid)
    audit(c, "فتح تقييم موظف", f"{a['number']} · {a['cycle']}")
    c.commit()
    return a


# ----------------------------------------------------------------------------------------------------- the three steps
class GoalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=160)
    weight: int = Field(ge=1, le=100)
    self_score: int | None = Field(default=None, ge=1, le=5)


class CompIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    self_score: int | None = Field(default=None, ge=1, le=5)


class SelfIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goals: list[GoalIn] = Field(max_length=7)
    competencies: list[CompIn] = Field(max_length=10)
    self_comment: str = Field(default="", max_length=1500)
    submit: bool = False


@router.get("/api/hr/me/appraisals")
def api_me_appraisals(u=Depends(need("hr_self"))):
    c = db()
    e = own_employee(c, u)
    ids = [r["id"] for r in c.execute("SELECT a.id FROM appraisals a JOIN appraisal_cycles k ON k.id=a.cycle_id WHERE a.employee_id=? AND k.status!='draft' ORDER BY k.year DESC", (e["id"],)).fetchall()]
    return [_view_for_employee(_load(c, i)) for i in ids]


@router.put("/api/hr/me/appraisals/{aid}/self")
def api_self_review(aid: int, b: SelfIn, u=Depends(act_as("hr_self"))):
    c = db()
    e = own_employee(c, u)
    a = _load(c, aid)
    if a["employee_id"] != e["id"]:
        raise HTTPException(404, "التقييم غير موجود")
    if a["status"] != "self" or a["cycle_status"] != "open":
        raise HTTPException(409, "لا يُعدَّل تقييمك الذاتي في هذه الحالة")
    goals = [{"title": g.title.strip(), "weight": g.weight, "self_score": g.self_score, "mgr_score": None} for g in b.goals]
    old = {k["name"] for k in a["competencies"]}
    if {k.name for k in b.competencies} != old:
        raise HTTPException(400, "بنود الكفاءات ثابتة — قيّم كل بند")
    comps = [{"name": k.name, "self_score": k.self_score, "mgr_score": None} for k in b.competencies]
    if b.submit:
        if not goals or sum(g["weight"] for g in goals) != 100:
            raise HTTPException(400, "أهدافك يلزم أن تكون هدفًا واحدًا على الأقل ومجموع أوزانها 100")
        if any(g["self_score"] is None for g in goals) or any(k["self_score"] is None for k in comps):
            raise HTTPException(400, "قيّم كل هدف وكل كفاءة قبل الإرسال")
    c.execute("UPDATE appraisals SET goals=?, competencies=?, self_comment=? WHERE id=?", (json.dumps(goals, ensure_ascii=False), json.dumps(comps, ensure_ascii=False), b.self_comment.strip() or None, aid))
    if b.submit:
        nxt = "manager" if a["reviewer_id"] else "hr"
        c.execute("UPDATE appraisals SET status=?, self_at=? WHERE id=?", (nxt, now_s(), aid))
        audit(c, "تقييم ذاتي", f"{a['number']} · {a['cycle']}")
    c.commit()
    return {"status": "manager" if b.submit and a["reviewer_id"] else "hr" if b.submit else "self"}


class MgrIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal_scores: list[int] = Field(max_length=7)
    competency_scores: list[int] = Field(max_length=10)
    manager_comment: str = Field(default="", max_length=1500)
    submit: bool = False


def _manager_step(c, a: dict, b: MgrIn, who: str) -> dict:
    if a["status"] != "manager" or a["cycle_status"] != "open":
        raise HTTPException(409, "التقييم ليس بانتظار مراجعة المدير")
    if len(b.goal_scores) != len(a["goals"]) or len(b.competency_scores) != len(a["competencies"]):
        raise HTTPException(400, "عدد الدرجات لا يطابق الأهداف والكفاءات")
    if any(not 1 <= s <= 5 for s in b.goal_scores + b.competency_scores):
        raise HTTPException(400, "الدرجات من 1 إلى 5")
    for g, s in zip(a["goals"], b.goal_scores):
        g["mgr_score"] = s
    for k, s in zip(a["competencies"], b.competency_scores):
        k["mgr_score"] = s
    c.execute("UPDATE appraisals SET goals=?, competencies=?, manager_comment=? WHERE id=?", (json.dumps(a["goals"], ensure_ascii=False), json.dumps(a["competencies"], ensure_ascii=False), b.manager_comment.strip() or None, a["id"]))
    if b.submit:
        if len(b.manager_comment.strip()) < 5:
            raise HTTPException(400, "تعليق المدير مطلوب عند الإرسال")
        gs = sum(g["weight"] * g["mgr_score"] for g in a["goals"]) / 100
        cs = sum(k["mgr_score"] for k in a["competencies"]) / len(a["competencies"])
        overall = round(GOAL_WEIGHT * gs + COMP_WEIGHT * cs, 2)
        c.execute("UPDATE appraisals SET status='hr', manager_at=?, overall=?, rating=? WHERE id=?", (now_s(), overall, band(overall), a["id"]))
        audit(c, "مراجعة مدير لتقييم", f"{a['number']} · {a['cycle']} · {overall}")
    return {"status": "hr" if b.submit else "manager"}


@router.get("/api/hr/team-appraisals")  # not under /team/: `/api/hr/team/{eid}` would swallow it
def api_team_appraisals(u=Depends(need("hr_manager"))):
    c = db()
    me = u.get("employee_id")
    if not me:
        return []
    ids = [r["id"] for r in c.execute("SELECT a.id FROM appraisals a JOIN appraisal_cycles k ON k.id=a.cycle_id WHERE a.reviewer_id=? AND a.status IN ('manager','hr','final','ack') AND k.status='open' ORDER BY a.id", (me,)).fetchall()]
    out = []
    for i in ids:
        a = _load(c, i)
        if a["status"] in ("final", "ack"):  # the finished ones show the result to the manager who gave it
            pass
        out.append(a)
    return out


@router.put("/api/hr/team/appraisals/{aid}/review")
def api_manager_review(aid: int, b: MgrIn, u=Depends(act_as("hr_manager"))):
    c = db()
    a = _load(c, aid)
    me = u.get("employee_id")
    if me == a["employee_id"]:
        raise HTTPException(403, "لا تقيّم نفسك")
    if not me or me != a["reviewer_id"]:
        raise HTTPException(404, "التقييم غير موجود")
    out = _manager_step(c, a, b, u["name"])
    c.commit()
    return out


@router.put("/api/hr/appraisals/{aid}/review")
def api_hr_review(aid: int, b: MgrIn, u=Depends(act_as("hr"))):
    """HR gives the manager's review only when the employee has no manager or his manager has left — never for its own file."""
    c = db()
    a = _load(c, aid)
    if u.get("employee_id") == a["employee_id"]:
        raise HTTPException(403, "لا تقيّم نفسك")
    rv = c.execute("SELECT status FROM employees WHERE id=?", (a["reviewer_id"],)).fetchone() if a["reviewer_id"] else None
    if rv and rv["status"] != "terminated":
        raise HTTPException(409, "للموظف مدير على رأس العمل — هو من يراجع")
    if a["status"] == "hr" and not a["reviewer_id"]:
        c.execute("UPDATE appraisals SET status='manager' WHERE id=?", (aid,))
        a["status"] = "manager"
    out = _manager_step(c, a, b, u["name"])
    c.commit()
    return out


class FinalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["none", "promotion", "raise", "training", "improvement_plan", "no_action"]
    hr_comment: str = Field(min_length=3, max_length=1500)


@router.post("/api/hr/appraisals/{aid}/finalize")
def api_finalize(aid: int, b: FinalIn, u=Depends(act_as("hr"))):
    c = db()
    a = _load(c, aid)
    if u.get("employee_id") == a["employee_id"]:
        raise HTTPException(403, "لا تعتمد تقييمك")
    if a["status"] != "hr":
        raise HTTPException(409, "التقييم ليس بانتظار الموارد البشرية")
    c.execute("UPDATE appraisals SET status='final', decision=?, hr_comment=?, hr_at=?, hr_by=? WHERE id=?", (b.decision, b.hr_comment.strip(), now_s(), u["username"], aid))
    audit(c, "اعتماد تقييم", f"{a['number']} · {a['cycle']} · {DECISIONS[b.decision]}")  # a decision here moves no salary
    c.commit()
    return {"status": "final"}


class AckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comment: str = Field(default="", max_length=500)


@router.post("/api/hr/me/appraisals/{aid}/ack")
def api_ack(aid: int, b: AckIn, u=Depends(act_as("hr_self"))):
    c = db()
    e = own_employee(c, u)
    a = _load(c, aid)
    if a["employee_id"] != e["id"]:
        raise HTTPException(404, "التقييم غير موجود")
    if a["status"] != "final":
        raise HTTPException(409, "لا يُقرّ بتقييم لم يُعتمد")
    c.execute("UPDATE appraisals SET status='ack', ack_at=?, self_comment=CASE WHEN ?<>'' THEN COALESCE(self_comment,'')||' | اعتراض/ملاحظة بعد الاعتماد: '||? ELSE self_comment END WHERE id=?", (now_s(), b.comment.strip(), b.comment.strip(), aid))
    audit(c, "إقرار بتقييم", f"{a['number']} · {a['cycle']}")
    c.commit()
    return {"status": "ack"}


# ----------------------------------------------------------------------------------------------------- training
@router.get("/api/hr/training/courses")
def api_courses(_=Depends(need("hr"))):
    return rows(db().execute("""SELECT t.*, (SELECT COUNT(*) FROM training_records r WHERE r.course_id=t.id AND r.status='completed') completed FROM training_courses t ORDER BY t.mandatory DESC, t.title"""))


class CourseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=120)
    provider: str = Field(default="", max_length=120)
    hours: float = Field(default=0, ge=0, le=2000)
    cert_valid_months: int | None = Field(default=None, ge=1, le=240)
    mandatory: bool = False


@router.post("/api/hr/training/courses")
def api_course_add(b: CourseIn, u=Depends(act_as("hr"))):
    c = db()
    if c.execute("SELECT 1 FROM training_courses WHERE title=?", (b.title.strip(),)).fetchone():
        raise HTTPException(409, "دورة بهذا العنوان موجودة")
    tid = c.execute("INSERT INTO training_courses(title,provider,hours,cert_valid_months,mandatory) VALUES(?,?,?,?,?)", (b.title.strip(), b.provider or None, b.hours, b.cert_valid_months, int(b.mandatory))).lastrowid
    audit(c, "دورة تدريبية", b.title)
    c.commit()
    return {"id": tid}


def _records(c, where: str = "", args: tuple = ()) -> list[dict]:
    out = rows(c.execute("""SELECT r.*, t.title course, t.hours, t.mandatory, e.number, e.name FROM training_records r JOIN training_courses t ON t.id=r.course_id JOIN employees e ON e.id=r.employee_id"""
                         + (" WHERE " + where if where else "") + " ORDER BY COALESCE(r.completed_on, r.planned_on) DESC, r.id DESC", args))
    for x in out:
        x["days_left"] = (pdate(x["cert_expires"]) - today()).days if x["cert_expires"] else None
    return out


@router.get("/api/hr/training/records")
def api_records(employee_id: int | None = None, course_id: int | None = None, status: str | None = Query(None, pattern="^(planned|completed|cancelled|no_show)$"), _=Depends(need("hr"))):
    c = db()
    where, args = [], []
    for col, v in (("r.employee_id", employee_id), ("r.course_id", course_id), ("r.status", status)):
        if v:
            where.append(f"{col}=?")
            args.append(v)
    return _records(c, " AND ".join(where), tuple(args))


class RecordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: int
    employee_id: int
    status: Literal["planned", "completed", "cancelled", "no_show"] = "planned"
    planned_on: str = ""
    completed_on: str = ""
    score: float | None = Field(default=None, ge=0, le=100)
    certificate_no: str = Field(default="", max_length=60)
    cert_expires: str = ""
    document_id: int | None = None
    note: str = Field(default="", max_length=300)


def _fill(c, b: RecordIn) -> dict:
    emp = employee(c, b.employee_id)
    if emp["status"] == "terminated":
        raise HTTPException(409, "الملف منتهي الخدمة")
    course = dict(one(c, "SELECT * FROM training_courses WHERE id=? AND active=1", (b.course_id,), "الدورة غير موجودة أو موقوفة"))
    done = pdate(b.completed_on, "تاريخ الإتمام").isoformat() if b.completed_on else None
    plan = pdate(b.planned_on, "التاريخ المخطط").isoformat() if b.planned_on else None
    exp = pdate(b.cert_expires, "انتهاء الشهادة").isoformat() if b.cert_expires else None
    if b.status == "completed":
        if not done:
            raise HTTPException(400, "تاريخ الإتمام مطلوب")
        if done > today().isoformat():
            raise HTTPException(400, "الإتمام في المستقبل")
        if not exp and course["cert_valid_months"]:
            exp = add_months(dt.date.fromisoformat(done), course["cert_valid_months"]).isoformat()
    if b.document_id is not None:
        d = c.execute("SELECT ref_type, ref_id FROM documents WHERE id=?", (b.document_id,)).fetchone()
        if not d or d["ref_type"] != "employee" or d["ref_id"] != b.employee_id:
            raise HTTPException(400, "المرفق غير تابع لهذا الموظف")
    return {"done": done, "plan": plan, "exp": exp}


@router.post("/api/hr/training/records")
def api_record_add(b: RecordIn, u=Depends(act_as("hr"))):
    c = db()
    f = _fill(c, b)
    rid = c.execute("""INSERT INTO training_records(course_id,employee_id,status,planned_on,completed_on,score,certificate_no,cert_expires,document_id,note,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (b.course_id, b.employee_id, b.status, f["plan"], f["done"], b.score, b.certificate_no or None, f["exp"], b.document_id, b.note or None, u["name"])).lastrowid
    audit(c, "سجل تدريب", f"موظف {b.employee_id} · دورة {b.course_id} · {b.status}")
    c.commit()
    return {"id": rid, "cert_expires": f["exp"]}


@router.put("/api/hr/training/records/{rid}")
def api_record_edit(rid: int, b: RecordIn, u=Depends(act_as("hr"))):
    c = db()
    r = one(c, "SELECT employee_id, course_id FROM training_records WHERE id=?", (rid,), "السجل غير موجود")
    if (r["employee_id"], r["course_id"]) != (b.employee_id, b.course_id):
        raise HTTPException(400, "لا يتغير الموظف ولا الدورة — أنشئ سجلًا جديدًا")
    f = _fill(c, b)
    c.execute("UPDATE training_records SET status=?, planned_on=?, completed_on=?, score=?, certificate_no=?, cert_expires=?, document_id=?, note=? WHERE id=?",
              (b.status, f["plan"], f["done"], b.score, b.certificate_no or None, f["exp"], b.document_id, b.note or None, rid))
    audit(c, "تعديل سجل تدريب", f"#{rid} ← {b.status}")
    c.commit()
    return {"ok": True, "cert_expires": f["exp"]}


@router.get("/api/hr/training/compliance")
def api_compliance(_=Depends(need("hr"))):
    """Every mandatory course against every person on the payroll: valid, expiring (≤ 90 days), expired, or never taken."""
    c = db()
    out = []
    emps = c.execute("SELECT id, number, name FROM employees WHERE status!='terminated' ORDER BY number").fetchall()
    for course in c.execute("SELECT id, title FROM training_courses WHERE mandatory=1 AND active=1").fetchall():
        for e in emps:
            r = c.execute("""SELECT completed_on, cert_expires FROM training_records WHERE employee_id=? AND course_id=? AND status='completed' ORDER BY COALESCE(cert_expires,'9999-12-31') DESC, completed_on DESC LIMIT 1""",
                          (e["id"], course["id"])).fetchone()
            if not r:
                state, left = "missing", None
            elif r["cert_expires"]:
                left = (pdate(r["cert_expires"]) - today()).days
                state = "expired" if left < 0 else "expiring" if left <= 90 else "valid"
            else:
                state, left = "valid", None
            out.append({"employee_id": e["id"], "number": e["number"], "name": e["name"], "course_id": course["id"], "course": course["title"], "state": state, "days_left": left})
    return out


@router.get("/api/hr/me/training")
def api_me_training(u=Depends(need("hr_self"))):
    c = db()
    e = own_employee(c, u)
    return {"records": _records(c, "r.employee_id=? AND r.status!='cancelled'", (e["id"],)),
            "mandatory_missing": [x["course"] for x in api_compliance() if x["employee_id"] == e["id"] and x["state"] in ("missing", "expired")]}


def training_expiry_items(c, as_of: dt.date, horizon: int) -> list[dict]:
    """Certificates that end within `horizon` days — only the latest of each (employee, course): a renewed certificate silences the old one. Joined to the alerts of `hr.expiry_items`."""
    latest: dict = {}
    for r in c.execute("""SELECT r.id, r.employee_id, r.course_id, r.cert_expires, t.title, e.number, e.name FROM training_records r JOIN training_courses t ON t.id=r.course_id JOIN employees e ON e.id=r.employee_id
                          WHERE r.status='completed' AND r.cert_expires IS NOT NULL AND e.status!='terminated'""").fetchall():
        k = (r["employee_id"], r["course_id"])
        if k not in latest or r["cert_expires"] > latest[k]["cert_expires"]:
            latest[k] = dict(r)
    out = []
    for r in latest.values():
        days = (pdate(r["cert_expires"]) - as_of).days
        if days <= horizon:
            out.append({"source": "training", "ref_id": r["id"], "employee_id": r["employee_id"], "number": r["number"], "name": r["name"], "kind": "training_cert", "label": f"شهادة: {r['title']}",
                        "date": r["cert_expires"], "days_left": days, "level": hr.level_of(days)})
    return out
