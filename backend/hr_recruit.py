"""Mabaniq 0.27.0 — human resources: recruitment (design §5.4, phase 4c).

An opening is drafted, opened, and closed or filled; candidates move applied → screening → interview → offer → hired (only through `hire`, which opens the employee file and
moves the CV into it) or rejected / withdrawn. A candidate who was not hired is a stranger who sent us a CV: **his data is erased after a retention period** (180 days unless
the organisation sets another) — name replaced, phone, e-mail, notes and the CV file removed — and the erasure runs daily. Everything needs `hr`.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from . import hr
from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .db import setting
from .hr import EmployeeIn, pdate
from .modules import one

router = APIRouter()
STAGES = {"applied": "تقدّم", "screening": "فرز", "interview": "مقابلة", "offer": "عرض", "hired": "عُيّن", "rejected": "مرفوض", "withdrawn": "انسحب"}
FLOW = {"applied": ("screening", "rejected", "withdrawn"), "screening": ("interview", "rejected", "withdrawn"), "interview": ("offer", "rejected", "withdrawn"), "offer": ("rejected", "withdrawn")}
DEFAULT_RETENTION_DAYS = 180


# ----------------------------------------------------------------------------------------------------- openings
@router.get("/api/hr/recruitment/openings")
def api_openings(status: str | None = Query(None, pattern="^(draft|open|closed|filled|cancelled)$"), _=Depends(need("hr"))):
    c = db()
    sql = """SELECT o.*, d.name department, p.title position,
             (SELECT COUNT(*) FROM candidates x WHERE x.opening_id=o.id) candidates, (SELECT COUNT(*) FROM candidates x WHERE x.opening_id=o.id AND x.stage='hired') hired,
             (SELECT COUNT(*) FROM candidates x WHERE x.opening_id=o.id AND x.stage IN ('applied','screening','interview','offer')) active
             FROM job_openings o LEFT JOIN departments d ON d.id=o.department_id LEFT JOIN positions p ON p.id=o.position_id"""
    return rows(c.execute(sql + (" WHERE o.status=?" if status else "") + " ORDER BY o.id DESC", (status,) if status else ()))


class OpeningIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=120)
    department_id: int | None = None
    position_id: int | None = None
    headcount: int = Field(default=1, ge=1, le=100)
    closes_on: str = ""
    description: str = Field(default="", max_length=2000)
    requirements: str = Field(default="", max_length=2000)


@router.post("/api/hr/recruitment/openings")
def api_opening_add(b: OpeningIn, u=Depends(act_as("hr"))):
    c = db()
    if b.department_id is not None:
        one(c, "SELECT 1 FROM departments WHERE id=?", (b.department_id,), "القسم غير موجود")
    if b.position_id is not None:
        one(c, "SELECT 1 FROM positions WHERE id=?", (b.position_id,), "المسمى غير موجود")
    closes = pdate(b.closes_on, "تاريخ الإغلاق").isoformat() if b.closes_on else None
    oid = c.execute("INSERT INTO job_openings(title,department_id,position_id,headcount,closes_on,description,requirements,created_by) VALUES(?,?,?,?,?,?,?,?)",
                    (b.title.strip(), b.department_id, b.position_id, b.headcount, closes, b.description or None, b.requirements or None, u["name"])).lastrowid
    audit(c, "وظيفة شاغرة", b.title)
    c.commit()
    return {"id": oid}


class OpeningStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "closed", "cancelled"]


@router.post("/api/hr/recruitment/openings/{oid}/status")
def api_opening_status(oid: int, b: OpeningStatus, u=Depends(act_as("hr"))):
    c = db()
    o = dict(one(c, "SELECT * FROM job_openings WHERE id=?", (oid,), "الوظيفة غير موجودة"))
    ok = {"draft": ("open", "cancelled"), "open": ("closed", "cancelled"), "closed": ("open",), "filled": (), "cancelled": ()}[o["status"]]
    if b.status not in ok:
        raise HTTPException(409, "هذا الانتقال غير متاح للحالة الحالية")
    c.execute("UPDATE job_openings SET status=?, opened_on=COALESCE(opened_on, ?) WHERE id=?", (b.status, today().isoformat() if b.status == "open" else None, oid))
    audit(c, "حالة وظيفة شاغرة", f"{o['title']} ← {b.status}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- candidates
CAND_SQL = """SELECT x.id, x.opening_id, o.title opening, x.name, x.phone, x.email, x.source, x.stage, x.rating, x.notes, x.cv_document_id, x.reject_reason, x.hired_employee_id, x.anonymized, x.stage_at,
              (SELECT COUNT(*) FROM interviews i WHERE i.candidate_id=x.id AND i.status='done') interviews_done,
              (SELECT AVG(i.score) FROM interviews i WHERE i.candidate_id=x.id AND i.status='done' AND i.score IS NOT NULL) avg_score
              FROM candidates x JOIN job_openings o ON o.id=x.opening_id"""


@router.get("/api/hr/recruitment/candidates")
def api_candidates(opening_id: int | None = None, stage: str | None = Query(None, pattern="^(applied|screening|interview|offer|hired|rejected|withdrawn)$"), _=Depends(need("hr"))):
    c = db()
    where, args = [], []
    if opening_id:
        where.append("x.opening_id=?")
        args.append(opening_id)
    if stage:
        where.append("x.stage=?")
        args.append(stage)
    out = rows(c.execute(CAND_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY x.id DESC", tuple(args)))
    for x in out:
        x["avg_score"] = None if x["avg_score"] is None else round(x["avg_score"], 2)
    return out


@router.get("/api/hr/recruitment/candidates/{cid}")
def api_candidate(cid: int, u=Depends(act_as("hr"))):
    c = db()
    x = dict(one(c, CAND_SQL + " WHERE x.id=?", (cid,), "المرشح غير موجود"))
    x["interviews"] = rows(c.execute("SELECT * FROM interviews WHERE candidate_id=? ORDER BY scheduled_at", (cid,)))
    audit(c, "فتح ملف مرشح", f"#{cid} · {x['name']}")
    c.commit()
    return x


class CandidateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opening_id: int
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=120)
    source: str = Field(default="", max_length=60)
    notes: str = Field(default="", max_length=1000)


@router.post("/api/hr/recruitment/candidates")
def api_candidate_add(b: CandidateIn, u=Depends(act_as("hr"))):
    c = db()
    o = one(c, "SELECT status, title FROM job_openings WHERE id=?", (b.opening_id,), "الوظيفة غير موجودة")
    if o["status"] != "open":
        raise HTTPException(409, "الوظيفة غير مفتوحة للتقديم")
    if b.email and c.execute("SELECT 1 FROM candidates WHERE opening_id=? AND lower(email)=? AND anonymized=0", (b.opening_id, b.email.strip().lower())).fetchone():
        raise HTTPException(409, "هذا البريد تقدّم لهذه الوظيفة من قبل")
    cid = c.execute("INSERT INTO candidates(opening_id,name,phone,email,source,notes,stage_at,created_by) VALUES(?,?,?,?,?,?,?,?)",
                    (b.opening_id, b.name.strip(), b.phone or None, b.email.strip() or None, b.source or None, b.notes or None, now_s(), u["name"])).lastrowid
    audit(c, "مرشح جديد", f"{o['title']} · #{cid}")
    c.commit()
    return {"id": cid}


class StageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal["screening", "interview", "offer", "rejected", "withdrawn"]
    reason: str = Field(default="", max_length=300)
    rating: int | None = Field(default=None, ge=1, le=5)


@router.post("/api/hr/recruitment/candidates/{cid}/stage")
def api_candidate_stage(cid: int, b: StageIn, u=Depends(act_as("hr"))):
    c = db()
    x = dict(one(c, "SELECT * FROM candidates WHERE id=?", (cid,), "المرشح غير موجود"))
    if b.stage not in FLOW.get(x["stage"], ()):
        raise HTTPException(409, f"لا يُنقل المرشح من «{STAGES[x['stage']]}» إلى «{STAGES[b.stage]}»")
    if b.stage == "rejected" and len(b.reason.strip()) < 3:
        raise HTTPException(400, "سبب الرفض مطلوب")
    if b.stage == "offer" and not c.execute("SELECT 1 FROM interviews WHERE candidate_id=? AND status='done'", (cid,)).fetchone():
        raise HTTPException(409, "لا يُقدَّم عرض لمن لم تُجرَ معه مقابلة")
    c.execute("UPDATE candidates SET stage=?, stage_at=?, reject_reason=?, rating=COALESCE(?, rating) WHERE id=?", (b.stage, now_s(), b.reason.strip() or None, b.rating, cid))
    audit(c, "مرحلة مرشح", f"#{cid} ← {STAGES[b.stage]}")
    c.commit()
    return {"ok": True}


@router.post("/api/hr/recruitment/candidates/{cid}/cv")
async def api_candidate_cv(cid: int, file: UploadFile = File(...), u=Depends(act_as("hr"))):
    """The CV is stored in the file store under `candidate` (HR only — the generic documents permission does not open it)."""
    from .modules2 import store_upload
    c = db()
    x = dict(one(c, "SELECT * FROM candidates WHERE id=?", (cid,), "المرشح غير موجود"))
    if x["anonymized"] or x["stage"] in ("hired", "rejected", "withdrawn"):
        raise HTTPException(409, "لا يُرفع ملف لمرشح أُغلق ملفه")
    did, _sha = store_upload(c, await file.read(5 * 1024 * 1024 + 1), file.filename, "candidate", cid, f"سيرة ذاتية — {x['name']}", "توظيف", u["name"])
    c.execute("UPDATE candidates SET cv_document_id=? WHERE id=?", (did, cid))
    c.commit()
    return {"document_id": did}


# ----------------------------------------------------------------------------------------------------- interviews
class InterviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2})?$")
    kind: Literal["phone", "in_person", "online", "technical"] = "in_person"
    interviewer: str = Field(default="", max_length=80)


@router.post("/api/hr/recruitment/candidates/{cid}/interviews")
def api_interview_add(cid: int, b: InterviewIn, u=Depends(act_as("hr"))):
    c = db()
    x = one(c, "SELECT stage FROM candidates WHERE id=?", (cid,), "المرشح غير موجود")
    if x["stage"] not in ("screening", "interview"):
        raise HTTPException(409, "تُحدَّد المقابلة لمرشح في الفرز أو المقابلة")
    pdate(b.scheduled_at[:10], "موعد المقابلة")
    iid = c.execute("INSERT INTO interviews(candidate_id,scheduled_at,kind,interviewer,created_by) VALUES(?,?,?,?,?)", (cid, b.scheduled_at.replace("T", " "), b.kind, b.interviewer or None, u["name"])).lastrowid
    if x["stage"] == "screening":
        c.execute("UPDATE candidates SET stage='interview', stage_at=? WHERE id=?", (now_s(), cid))
    audit(c, "مقابلة مرشح", f"#{cid} · {b.scheduled_at}")
    c.commit()
    return {"id": iid}


class ResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int = Field(ge=1, le=5)
    notes: str = Field(default="", max_length=1000)


@router.post("/api/hr/recruitment/interviews/{iid}/result")
def api_interview_result(iid: int, b: ResultIn, u=Depends(act_as("hr"))):
    c = db()
    i = one(c, "SELECT status FROM interviews WHERE id=?", (iid,), "المقابلة غير موجودة")
    if i["status"] != "scheduled":
        raise HTTPException(409, "المقابلة ليست مجدولة")
    c.execute("UPDATE interviews SET status='done', score=?, notes=? WHERE id=?", (b.score, b.notes or None, iid))
    audit(c, "نتيجة مقابلة", f"#{iid} · {b.score}/5")
    c.commit()
    return {"ok": True}


@router.post("/api/hr/recruitment/interviews/{iid}/cancel")
def api_interview_cancel(iid: int, u=Depends(act_as("hr"))):
    c = db()
    i = one(c, "SELECT status FROM interviews WHERE id=?", (iid,), "المقابلة غير موجودة")
    if i["status"] != "scheduled":
        raise HTTPException(409, "المقابلة ليست مجدولة")
    c.execute("UPDATE interviews SET status='cancelled' WHERE id=?", (iid,))
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- hiring
class HireIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hire_date: str
    omani: bool = False
    gender: Literal["male", "female"] | None = None
    nationality: str = Field(default="", max_length=60)
    contract_type: Literal["permanent", "fixed", "part"] = "permanent"
    contract_end: str = ""
    probation_end: str = ""
    manager_id: int | None = None


@router.post("/api/hr/recruitment/candidates/{cid}/hire")
def api_hire(cid: int, b: HireIn, u=Depends(act_as("hr"))):
    """Offer accepted: the employee file is opened from the candidate and the opening (department, position), the CV moves into the file, and the candidate's contact data is cleared
    from the recruitment side. When the opening's headcount is reached it is marked filled."""
    c = db()
    x = dict(one(c, "SELECT * FROM candidates WHERE id=?", (cid,), "المرشح غير موجود"))
    if x["stage"] != "offer":
        raise HTTPException(409, "يُعيَّن من قُدّم له عرض فقط")
    o = dict(one(c, "SELECT * FROM job_openings WHERE id=?", (x["opening_id"],), "الوظيفة غير موجودة"))
    out = hr.create_employee(c, EmployeeIn(name=x["name"], omani=b.omani, nationality=b.nationality, gender=b.gender, phone=x["phone"] or "", email=x["email"] or "", department_id=o["department_id"],
                                          position_id=o["position_id"], manager_id=b.manager_id, hire_date=b.hire_date, contract_type=b.contract_type, contract_end=b.contract_end,
                                          probation_end=b.probation_end), u["name"])
    if x["cv_document_id"]:
        c.execute("UPDATE documents SET ref_type='employee', ref_id=?, category='توظيف' WHERE id=?", (out["id"], x["cv_document_id"]))
    c.execute("UPDATE candidates SET stage='hired', stage_at=?, hired_employee_id=?, cv_document_id=NULL, phone=NULL, email=NULL WHERE id=?", (now_s(), out["id"], cid))
    n = c.execute("SELECT COUNT(*) n FROM candidates WHERE opening_id=? AND stage='hired'", (o["id"],)).fetchone()["n"]
    if n >= o["headcount"]:
        c.execute("UPDATE job_openings SET status='filled' WHERE id=?", (o["id"],))
    audit(c, "تعيين من التوظيف", f"{out['number']} ← مرشح #{cid} · {o['title']}")
    c.commit()
    return {**out, "opening_filled": n >= o["headcount"]}


# ----------------------------------------------------------------------------------------------------- erasure of candidates who were not hired
def retention_days(c) -> int:
    try:
        return max(30, int(setting(c, "hr:candidate_days", DEFAULT_RETENTION_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS


def purge(c, days: int) -> int:
    """Erase candidates rejected or withdrawn for more than `days`: name, phone, e-mail, notes, reason, interview notes and the CV file. The row stays (counts, history) but names nobody."""
    from .modules2 import _docs_dir
    cutoff = (dt.datetime.now() - dt.timedelta(days=days)).isoformat(timespec="seconds")
    n = 0
    for x in c.execute("SELECT id, cv_document_id FROM candidates WHERE stage IN ('rejected','withdrawn') AND anonymized=0 AND stage_at<?", (cutoff,)).fetchall():
        if x["cv_document_id"]:
            d = c.execute("SELECT stored FROM documents WHERE id=?", (x["cv_document_id"],)).fetchone()
            if d:
                try:
                    (_docs_dir() / d["stored"]).unlink(missing_ok=True)
                except OSError:
                    pass
                c.execute("DELETE FROM documents WHERE id=?", (x["cv_document_id"],))
        c.execute("UPDATE interviews SET notes=NULL, interviewer=NULL WHERE candidate_id=?", (x["id"],))
        c.execute("UPDATE candidates SET name=?, phone=NULL, email=NULL, notes=NULL, reject_reason=NULL, source=NULL, cv_document_id=NULL, anonymized=1 WHERE id=?", (f"مرشح محذوف #{x['id']}", x["id"]))
        n += 1
    if n:
        audit(c, "محو بيانات مرشحين", f"{n} مرشحًا بعد {days} يومًا من الرفض أو الانسحاب")
    return n


class PurgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(ge=30, le=3650)


@router.post("/api/hr/recruitment/purge")
def api_purge(b: PurgeIn, u=Depends(act_as("hr"))):
    c = db()
    n = purge(c, b.days)
    c.commit()
    return {"erased": n}


@router.get("/api/hr/recruitment/retention")
def api_retention(_=Depends(need("hr"))):
    c = db()
    return {"days": retention_days(c), "default": DEFAULT_RETENTION_DAYS}


@router.put("/api/hr/recruitment/retention")
def api_retention_set(b: PurgeIn, u=Depends(act_as("hr"))):
    """How long a rejected or withdrawn candidate's data is kept. Not below 30 days (so a decision can still be explained) and the erasure itself is irreversible."""
    c = db()
    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ("hr:candidate_days", str(b.days)))
    audit(c, "مدة الاحتفاظ ببيانات المرشحين", f"{b.days} يومًا")
    c.commit()
    return {"days": b.days}
