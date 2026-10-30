"""Mabaniq 0.25.0 — human resources: the employee's own portal and the manager's team (design §5.1 "الدور employee", phase 4a).

Everything under `/api/hr/me` is the signed-in employee's own file and nothing else — the account carries its employee id, there is no id in the path to tamper with.
Everything under `/api/hr/team` is the direct reports of the signed-in manager; a file outside that line answers 404, as if it did not exist. Neither shows an identity
number, a bank number or (from 0.26.0) a salary of anyone but the employee himself.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import hr_leave, pii
from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .hr import BASE_SQL, documents_of, employee, expiry_items, own_employee, reveal
from .modules import one

router = APIRouter()
CARD = ("id", "number", "name", "name_en", "nationality", "omani", "department", "position", "manager", "hire_date", "contract_type", "contract_end", "probation_end", "status", "phone", "email")


def _self(c, u):
    return own_employee(c, u)


def _card(c, eid: int) -> dict:
    r = dict(one(c, BASE_SQL + " WHERE e.id=?", (eid,), "الموظف غير موجود"))
    return r


# ----------------------------------------------------------------------------------------------------- my file
@router.get("/api/hr/me")
def api_me(u=Depends(need("hr_self"))):
    c = db()
    e = _self(c, u)
    out = reveal(e)
    for k in ("created_by", "termination_note"):
        out.pop(k, None)
    out.update({k: v for k, v in _card(c, e["id"]).items() if k in ("department", "position", "manager", "username")})
    year = today().year
    out["balances"] = hr_leave.balances_of(c, e, year)
    out["documents"] = documents_of(c, e["id"])
    out["alerts"] = [i for i in expiry_items(c, today()) if i["employee_id"] == e["id"]]
    out["reports"] = c.execute("SELECT COUNT(*) n FROM employees WHERE manager_id=? AND status!='terminated'", (e["id"],)).fetchone()["n"]
    out["open_requests"] = c.execute("SELECT COUNT(*) n FROM leave_requests WHERE employee_id=? AND status='pending'", (e["id"],)).fetchone()["n"]
    c.commit()
    return out


class MePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=200)
    emergency_contact: str | None = Field(default=None, max_length=200)


@router.patch("/api/hr/me")
def api_me_edit(b: MePatch, u=Depends(act_as("hr_self"))):
    """Contact details only. Identity, bank and insurance numbers change through HR (a request), so a hijacked session cannot redirect a salary."""
    c = db()
    e = _self(c, u)
    sent = b.model_fields_set
    if not sent:
        return {"changed": []}
    cur = {"phone": e["phone"], "email": e["email"], "address": e["address"], "emergency_contact": pii.dec(e["emergency_contact"])}
    changed = []
    for k in sent:
        v = (getattr(b, k) or "").strip() or None
        if v != cur[k]:
            c.execute(f"UPDATE employees SET {k}=? WHERE id=?", (pii.enc(v) if k == "emergency_contact" and v else v, e["id"]))
            changed.append(k)
    if changed:
        audit(c, "تحديث بيانات الموظف لنفسه", f"{e['number']} · {', '.join(changed)}")
        c.commit()
    return {"changed": changed}


@router.get("/api/hr/me/documents")
def api_me_docs(u=Depends(need("hr_self"))):
    c = db()
    return documents_of(c, _self(c, u)["id"])


@router.get("/api/hr/me/documents/{did}/file")
def api_me_doc_file(did: int, u=Depends(need("hr_self"))):
    """The scan of one of my own documents; a document of anyone else answers 404."""
    from .modules2 import _send_doc
    c = db()
    e = _self(c, u)
    x = c.execute("SELECT document_id FROM employee_documents WHERE id=? AND employee_id=?", (did, e["id"])).fetchone()
    if not x or not x["document_id"]:
        raise HTTPException(404, "الملف غير موجود")
    return _send_doc(one(c, "SELECT * FROM documents WHERE id=? AND ref_type='employee' AND ref_id=?", (x["document_id"], e["id"]), "الملف غير موجود"))


# ----------------------------------------------------------------------------------------------------- my leave
@router.get("/api/hr/me/leave-types")
def api_me_types(u=Depends(need("hr_self"))):
    c = db()
    e = _self(c, u)
    hr_leave.ensure_types(c)
    out = []
    for k in [r["key"] for r in c.execute("SELECT DISTINCT key FROM leave_types").fetchall()]:
        lt = hr_leave.type_on(c, k, today())
        if lt["active"] and not (lt["gender_only"] and e.get("gender") != lt["gender_only"]):
            out.append({"key": k, "name": lt["name"], "paid": bool(lt["paid"]), "days_per_year": lt["days_per_year"], "needs_doc": bool(lt["needs_doc"]), "needs_hr": bool(lt["needs_hr"]),
                        "day_count": lt["day_count"], "provisional": bool(lt["provisional"])})
    return sorted(out, key=lambda x: x["key"])


@router.get("/api/hr/me/leave")
def api_me_leave(u=Depends(need("hr_self"))):
    c = db()
    hr_leave.ensure_types(c)
    return hr_leave.request_rows(c, "r.employee_id=?", (_self(c, u)["id"],))


class MyLeaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type_key: str = Field(min_length=2, max_length=30)
    from_date: str
    to_date: str
    reason: str = Field(default="", max_length=300)


@router.post("/api/hr/me/leave")
def api_me_leave_add(b: MyLeaveIn, u=Depends(act_as("hr_self"))):
    c = db()
    e = _self(c, u)
    rid = hr_leave.create_request(c, e, b.type_key, b.from_date, b.to_date, b.reason, None, u["name"])
    c.commit()
    return {"id": rid}


# ----------------------------------------------------------------------------------------------------- my attendance and my loans (0.28.0)
@router.get("/api/hr/me/attendance")
def api_me_attendance(month: str = Query("", max_length=7), u=Depends(need("hr_self"))):
    """The employee's own days for a month (default: this one): status, times, and a count per status. Only their own rows — the id comes from the account."""
    c = db()
    e = _self(c, u)
    m = month if len(month) == 7 and month[4] == "-" else today().isoformat()[:7]
    days = rows(c.execute("SELECT day, status, check_in, check_out, note FROM attendance WHERE employee_id=? AND day LIKE ? ORDER BY day", (e["id"], m + "%")))
    counts: dict = {}
    for d in days:
        counts[d["status"]] = counts.get(d["status"], 0) + 1
    return {"month": m, "days": days, "counts": counts}


@router.get("/api/hr/me/loans")
def api_me_loans(u=Depends(need("hr_self"))):
    """The employee's own advances and interest-free loans with the instalments and what is still to be deducted."""
    c = db()
    e = _self(c, u)
    out = rows(c.execute("SELECT id, kind, amount, installments, start_period, status, reason, disbursed_on FROM employee_loans WHERE employee_id=? ORDER BY id DESC", (e["id"],)))
    for ln in out:
        ln["schedule"] = rows(c.execute("SELECT no, period, amount, status FROM loan_installments WHERE loan_id=? ORDER BY no", (ln["id"],)))
        ln["remaining"] = round(sum(i["amount"] for i in ln["schedule"] if i["status"] == "due"), 3)
    return out


# ----------------------------------------------------------------------------------------------------- my other requests (a letter, an advance, anything else)
@router.get("/api/hr/me/requests")
def api_me_requests(u=Depends(need("hr_self"))):
    c = db()
    return rows(c.execute("SELECT id, kind, details, amount, status, requested_at, decided_by, decided_at, decision_note FROM hr_requests WHERE employee_id=? ORDER BY id DESC", (_self(c, u)["id"],)))


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["letter", "advance", "other"]
    details: str = Field(min_length=3, max_length=500)
    amount: float | None = Field(default=None, gt=0, le=1_000_000)


@router.post("/api/hr/me/requests")
def api_me_request_add(b: RequestIn, u=Depends(act_as("hr_self"))):
    c = db()
    e = _self(c, u)
    if b.kind == "advance" and not b.amount:
        raise HTTPException(400, "مبلغ السلفة مطلوب")
    if b.kind != "advance" and b.amount:
        raise HTTPException(400, "المبلغ للسلفة فقط")
    rid = c.execute("INSERT INTO hr_requests(employee_id,kind,details,amount,requested_at) VALUES(?,?,?,?,?)", (e["id"], b.kind, b.details.strip(), b.amount, now_s())).lastrowid
    audit(c, "طلب موظف", f"{e['number']} · {b.kind}")
    c.commit()
    return {"id": rid}


@router.get("/api/hr/requests")
def api_requests(status: str | None = Query(None, pattern="^(pending|approved|rejected|done)$"), _=Depends(need("hr"))):
    c = db()
    sql = """SELECT q.id, q.employee_id, e.number, e.name, q.kind, q.details, q.amount, q.status, q.requested_at, q.decided_by, q.decided_at, q.decision_note
             FROM hr_requests q JOIN employees e ON e.id=q.employee_id"""
    return rows(c.execute(sql + (" WHERE q.status=?" if status else "") + " ORDER BY q.id DESC", (status,) if status else ()))


class RequestDecide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["approved", "rejected", "done"]
    note: str = Field(default="", max_length=300)


@router.post("/api/hr/requests/{qid}/decide")
def api_request_decide(qid: int, b: RequestDecide, u=Depends(act_as("hr"))):
    c = db()
    q = dict(one(c, "SELECT * FROM hr_requests WHERE id=?", (qid,), "الطلب غير موجود"))
    if u.get("employee_id") == q["employee_id"]:
        raise HTTPException(403, "لا يمكنك البتّ في طلبك")
    if q["status"] in ("rejected", "done"):
        raise HTTPException(409, "الطلب مغلق")
    if b.status == "rejected" and len(b.note.strip()) < 3:
        raise HTTPException(400, "سبب الرفض مطلوب")
    if b.status == "approved" and q["status"] != "pending":
        raise HTTPException(409, "الطلب معتمد سلفًا")
    c.execute("UPDATE hr_requests SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?", (b.status, u["name"], now_s(), b.note.strip() or None, qid))
    audit(c, "قرار في طلب موظف", f"#{qid} · {q['kind']} ← {b.status}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- my team
def _reports(c, me: int) -> list[dict]:
    return [dict(r) for r in c.execute(BASE_SQL + " WHERE e.manager_id=? AND e.status!='terminated' ORDER BY e.number", (me,))]


@router.get("/api/hr/team")
def api_team(u=Depends(need("hr_manager"))):
    """The direct reports: contact and work card only, who is away today, and how many requests wait for the manager."""
    c = db()
    me = u.get("employee_id")
    if not me:
        return []
    hr_leave.ensure_types(c)
    d = today().isoformat()
    out = []
    for r in _reports(c, me):
        away = c.execute("SELECT 1 FROM leave_requests WHERE employee_id=? AND status='approved' AND from_date<=? AND to_date>=?", (r["id"], d, d)).fetchone()
        waiting = c.execute("SELECT COUNT(*) n FROM leave_requests WHERE employee_id=? AND status='pending' AND stage='manager'", (r["id"],)).fetchone()["n"]
        bal = next((b for b in hr_leave.balances_of(c, employee(c, r["id"]), today().year) if b["type_key"] == "annual"), None)
        out.append({**{k: r[k] for k in CARD if k in r}, "away_today": bool(away), "waiting": waiting, "annual_remaining": bal["remaining"] if bal else None})
    c.commit()
    return out


@router.get("/api/hr/team/leave")
def api_team_leave(status: str | None = Query(None, pattern="^(pending|approved|rejected|cancelled)$"), u=Depends(need("hr_manager"))):
    c = db()
    me = u.get("employee_id")
    if not me:
        return []
    hr_leave.ensure_types(c)
    where, args = "e.manager_id=?", [me]
    if status:
        where += " AND r.status=?"
        args.append(status)
    return hr_leave.request_rows(c, where, tuple(args))


@router.get("/api/hr/team/{eid}")
def api_team_member(eid: int, u=Depends(act_as("hr_manager"))):
    c = db()
    me = u.get("employee_id")
    r = c.execute("SELECT id FROM employees WHERE id=? AND manager_id=?", (eid, me or 0)).fetchone()
    if not r:
        raise HTTPException(404, "الموظف غير موجود")
    card = _card(c, eid)
    audit(c, "فتح بطاقة مرؤوس", f"{card['number']} · {card['name']}")
    c.commit()
    return {k: card[k] for k in CARD if k in card}
