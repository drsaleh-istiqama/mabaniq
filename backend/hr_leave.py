"""Mabaniq 0.25.0 — human resources: leave, holidays and attendance (design §5.2, phase 4a).

Leave types are rows with an effective date (the row valid on a day is the latest `valid_from` on or before it), so a change in the labour rules is a new row, not an edit.
The platform seeds the usual types with `provisional = 1`: the figures are placeholders that a labour-law specialist must confirm — the screen says so until someone does.

A balance is never incremented and decremented by hand: `taken` is always recomputed from the approved requests, so approving takes days out and cancelling puts them
back without any chance of drift. A request goes employee → direct manager → (for the special types) HR; nobody decides his own request, and approving writes the days
into the attendance sheet as `leave`.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from .auth import need, need_any
from .common import ACTOR, act_as, audit, db, now_s, rows, today
from .db import setting
from .hr import employee, is_hr, pdate
from .importer import read_table
from .modules import one

router = APIRouter()

DAY = dt.timedelta(days=1)
STATUS_AR = {"pending": "بانتظار الاعتماد", "approved": "معتمدة", "rejected": "مرفوضة", "cancelled": "ملغاة"}
ATT_STATUS = {"present": "حاضر", "absent": "غائب", "late": "متأخر", "leave": "إجازة", "holiday": "عطلة", "remote": "عن بُعد"}
ATT_WORDS = {"حاضر": "present", "present": "present", "غائب": "absent", "absent": "absent", "متأخر": "late", "late": "late", "إجازة": "leave", "leave": "leave",
             "عطلة": "holiday", "holiday": "holiday", "عن بعد": "remote", "عن بُعد": "remote", "remote": "remote"}
PROV_NOTE = "قيمة مبدئية وضعتها المنصة — تحتاج مراجعة مختص بقانون العمل قبل الاعتماد"

# key, name, paid, days_per_year, accrual, needs_doc, needs_hr, gender_only, min_service_months, day_count, allow_negative, rules
SEED_TYPES = [
    ("annual", "الإجازة السنوية", 1, 30, "monthly", 0, 0, None, 0, "working", 0, {}),
    ("sick", "الإجازة المرضية", 1, 10, "event", 1, 0, None, 0, "calendar", 0, {}),
    ("emergency", "إجازة اضطرارية", 1, 3, "event", 0, 0, None, 0, "working", 0, {}),
    ("hajj", "إجازة الحج", 1, 15, "event", 1, 1, None, 0, "calendar", 0, {"once_in_service": True}),
    ("maternity", "إجازة الوضع", 1, 98, "event", 1, 1, "female", 0, "calendar", 0, {}),
    ("paternity", "إجازة الأبوّة", 1, 7, "event", 1, 0, "male", 0, "calendar", 0, {}),
    ("marriage", "إجازة الزواج", 1, 3, "event", 1, 0, None, 0, "working", 0, {"once_in_service": True}),
    ("bereavement", "إجازة الوفاة", 1, 3, "event", 0, 0, None, 0, "calendar", 0, {}),
    ("unpaid", "إجازة بلا راتب", 0, 0, "event", 0, 1, None, 0, "working", 1, {}),
    ("study", "إجازة دراسية", 0, 0, "event", 1, 1, None, 0, "working", 1, {}),
]


def act_any(*perms):
    async def dep(u: dict = Depends(need_any(*perms))):
        ACTOR.set(f"{u['name']} ({u['role_label']})")
        return u
    return dep


# ----------------------------------------------------------------------------------------------------- settings & calendar
def ensure_types(c) -> None:
    if c.execute("SELECT 1 FROM leave_types LIMIT 1").fetchone():
        return
    for k, name, paid, days, acc, nd, nh, g, ms, dc, an, rules in SEED_TYPES:
        c.execute("""INSERT OR IGNORE INTO leave_types(key,name,paid,days_per_year,accrual,needs_doc,needs_hr,gender_only,min_service_months,day_count,allow_negative,rules,valid_from,provisional,note)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""", (k, name, paid, days, acc, nd, nh, g, ms, dc, an, json.dumps(rules) if rules else None, "2000-01-01", PROV_NOTE))
    c.commit()


def weekend(c) -> set[int]:
    return {int(x) for x in str(setting(c, "hr:weekend", "4,5")).split(",") if x.strip().isdigit()}  # Monday = 0 … Friday = 4, Saturday = 5


def work_start(c) -> str:
    return str(setting(c, "hr:work_start", "08:00"))


def late_grace(c) -> int:
    try:
        return int(setting(c, "hr:late_grace", 15))
    except (TypeError, ValueError):
        return 15


def holiday_set(c, frm: str, to: str) -> set[str]:
    return {r["day"] for r in c.execute("SELECT day FROM holidays WHERE day>=? AND day<=?", (frm, to))}


def leave_days(c, frm: dt.date, to: dt.date, day_count: str) -> float:
    wk, hol = weekend(c), holiday_set(c, frm.isoformat(), to.isoformat())
    n, d = 0, frm
    while d <= to:
        if day_count == "calendar" or (d.weekday() not in wk and d.isoformat() not in hol):
            n += 1
        d += DAY
    return float(n)


def add_months(d: dt.date, m: int) -> dt.date:
    y, mo = divmod(d.month - 1 + m, 12)
    y += d.year
    mo += 1
    nxt = dt.date(y + (mo == 12), mo % 12 + 1, 1)
    return dt.date(y, mo, min(d.day, (nxt - DAY).day))


def type_on(c, key: str, day: dt.date) -> dict:
    ensure_types(c)
    r = c.execute("SELECT * FROM leave_types WHERE key=? AND valid_from<=? ORDER BY valid_from DESC LIMIT 1", (key, day.isoformat())).fetchone()
    if not r:
        raise HTTPException(404, "نوع الإجازة غير موجود")
    return dict(r)


def rules_of(lt: dict) -> dict:
    try:
        return json.loads(lt.get("rules") or "{}")
    except ValueError:
        return {}


# ----------------------------------------------------------------------------------------------------- entitlement & balance
def _credited_months(first: dt.date, year: int, upto: dt.date) -> int:
    n = 0
    for m in range(1, 13):
        ms = dt.date(year, m, 1)
        me = dt.date(year + (m == 12), m % 12 + 1, 1) - DAY
        if ms >= first and me <= upto:
            n += 1
    return n


def entitlement(emp: dict, lt: dict, year: int, as_of: dt.date) -> float:
    """Days entitled for `year`. `annual` credits the whole year (pro-rata from the first full month of service in the hire year); `monthly` credits each completed
    month as it passes (so the balance on 15 June holds five months); `event` is the full allowance every year with no pro-rata. Eligibility starts after
    `min_service_months`; service ends at the termination date."""
    days = float(lt["days_per_year"])
    if days <= 0:
        return 0.0
    hire = pdate(emp["hire_date"])
    ys, ye = dt.date(year, 1, 1), dt.date(year, 12, 31)
    first = max(hire, add_months(hire, int(lt["min_service_months"] or 0)), ys)
    end = min(ye, pdate(emp["terminated_on"])) if emp.get("terminated_on") else ye
    if first > end:
        return 0.0
    if lt["accrual"] == "event":
        return round(days, 2)
    upto = end if lt["accrual"] == "annual" else min(end, as_of)
    return round(days * _credited_months(first, year, upto) / 12, 2)


def balance(c, emp: dict, key: str, year: int, as_of: dt.date | None = None) -> dict:
    """Recomputes and stores the balance row; `available` also subtracts the days of requests still waiting for a decision."""
    as_of = as_of or today()
    clip = min(max(as_of, dt.date(year, 1, 1)), dt.date(year, 12, 31))
    lt = type_on(c, key, clip)
    entitled = entitlement(emp, lt, year, as_of)
    ys, ye = f"{year}-01-01", f"{year}-12-31"
    taken = c.execute("SELECT COALESCE(SUM(days),0) s FROM leave_requests WHERE employee_id=? AND type_key=? AND status='approved' AND from_date>=? AND from_date<=?",
                      (emp["id"], key, ys, ye)).fetchone()["s"]
    pending = c.execute("SELECT COALESCE(SUM(days),0) s FROM leave_requests WHERE employee_id=? AND type_key=? AND status='pending' AND from_date>=? AND from_date<=?",
                        (emp["id"], key, ys, ye)).fetchone()["s"]
    row = c.execute("SELECT * FROM leave_balances WHERE employee_id=? AND type_key=? AND year=?", (emp["id"], key, year)).fetchone()
    if not row:
        c.execute("INSERT INTO leave_balances(employee_id,type_key,year,entitled,taken) VALUES(?,?,?,?,?)", (emp["id"], key, year, entitled, taken))
        carried = adjusted = 0.0
        note = None
    else:
        carried, adjusted, note = row["carried"], row["adjusted"], row["adj_note"]
        if abs(row["entitled"] - entitled) > 1e-9 or abs(row["taken"] - taken) > 1e-9:
            c.execute("UPDATE leave_balances SET entitled=?, taken=? WHERE id=?", (entitled, taken, row["id"]))
    remaining = round(entitled + carried + adjusted - taken, 2)
    return {"type_key": key, "name": lt["name"], "year": year, "entitled": entitled, "carried": carried, "adjusted": adjusted, "adj_note": note, "taken": taken, "pending": pending,
            "remaining": remaining, "available": round(remaining - pending, 2), "capped": float(lt["days_per_year"]) > 0 and not lt["allow_negative"], "paid": bool(lt["paid"])}


def balances_of(c, emp: dict, year: int) -> list[dict]:
    ensure_types(c)
    keys = [r["key"] for r in c.execute("SELECT DISTINCT key FROM leave_types WHERE active=1")]
    out = []
    for k in sorted(keys):
        lt = type_on(c, k, min(max(today(), dt.date(year, 1, 1)), dt.date(year, 12, 31)))
        if not lt["active"] or float(lt["days_per_year"]) <= 0 or (lt["gender_only"] and emp.get("gender") != lt["gender_only"]):
            continue
        out.append(balance(c, emp, k, year))
    return out


# ----------------------------------------------------------------------------------------------------- attendance marks for approved leave
def _mark_leave(c, emp_id: int, frm: dt.date, to: dt.date) -> None:
    wk, hol = weekend(c), holiday_set(c, frm.isoformat(), to.isoformat())
    d = frm
    while d <= to:
        if d.weekday() not in wk and d.isoformat() not in hol:
            iso = d.isoformat()
            if c.execute("SELECT 1 FROM attendance WHERE employee_id=? AND day=?", (emp_id, iso)).fetchone():
                c.execute("UPDATE attendance SET status='leave', source='leave', check_in=NULL, check_out=NULL, note='إجازة معتمدة' WHERE employee_id=? AND day=?", (emp_id, iso))
            else:
                c.execute("INSERT INTO attendance(employee_id,day,status,source,note) VALUES(?,?,'leave','leave','إجازة معتمدة')", (emp_id, iso))
        d += DAY


def _unmark_leave(c, emp_id: int, frm: str, to: str) -> None:
    c.execute("DELETE FROM attendance WHERE employee_id=? AND source='leave' AND day>=? AND day<=?", (emp_id, frm, to))


# ----------------------------------------------------------------------------------------------------- requests
def _doc_of(c, emp_id: int, doc_id) -> None:
    if doc_id is not None:
        d = c.execute("SELECT ref_type, ref_id FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not d or d["ref_type"] != "employee" or d["ref_id"] != emp_id:
            raise HTTPException(400, "المرفق غير تابع لهذا الموظف")


def create_request(c, emp: dict, key: str, frm_s: str, to_s: str, reason: str, doc_id, by: str) -> int:
    """Every check runs before the first write (a failed request must not leave a half-written transaction). Returns the new request id."""
    if emp["status"] == "terminated":
        raise HTTPException(409, "الملف منتهي الخدمة")
    frm, to = pdate(frm_s, "تاريخ البداية"), pdate(to_s, "تاريخ النهاية")
    if to < frm:
        raise HTTPException(400, "تاريخ النهاية قبل البداية")
    if (to - frm).days > 370:
        raise HTTPException(400, "المدة أطول من سنة")
    if frm.year != to.year:
        raise HTTPException(400, "الطلب يعبر سنتين — قسّمه إلى طلبين، لكل سنة رصيدها")
    lt = type_on(c, key, frm)
    if not lt["active"]:
        raise HTTPException(409, "نوع الإجازة موقوف")
    if lt["gender_only"] and emp.get("gender") != lt["gender_only"]:
        raise HTTPException(409, "هذا النوع لا ينطبق على الموظف" if emp.get("gender") else "جنس الموظف غير مسجَّل في ملفه")
    hire = pdate(emp["hire_date"])
    if frm < hire:
        raise HTTPException(400, "البداية قبل تاريخ التعيين")
    if lt["min_service_months"] and frm < add_months(hire, int(lt["min_service_months"])):
        raise HTTPException(409, f"يشترط {lt['min_service_months']} شهرًا من الخدمة لهذا النوع")
    days = leave_days(c, frm, to, lt["day_count"])
    if days <= 0:
        raise HTTPException(400, "المدة كلها عطلة أسبوعية أو رسمية — لا أيام تُحتسب")
    if c.execute("SELECT 1 FROM leave_requests WHERE employee_id=? AND status IN ('pending','approved') AND from_date<=? AND to_date>=?", (emp["id"], to.isoformat(), frm.isoformat())).fetchone():
        raise HTTPException(409, "تتقاطع المدة مع إجازة أخرى للموظف")
    if rules_of(lt).get("once_in_service") and c.execute("SELECT 1 FROM leave_requests WHERE employee_id=? AND type_key=? AND status IN ('pending','approved')", (emp["id"], key)).fetchone():
        raise HTTPException(409, "هذا النوع يُمنح مرة واحدة طوال الخدمة وقد طُلب أو مُنح من قبل")
    if float(lt["days_per_year"]) > 0 and not lt["allow_negative"]:
        b = balance(c, emp, key, frm.year)
        if days > b["available"] + 1e-9:
            raise HTTPException(409, f"الرصيد المتاح {b['available']:g} يومًا والمطلوب {days:g}")
    _doc_of(c, emp["id"], doc_id)
    mgr = c.execute("SELECT status FROM employees WHERE id=?", (emp["manager_id"],)).fetchone() if emp["manager_id"] else None
    stage = "manager" if mgr and mgr["status"] != "terminated" else "hr"
    rid = c.execute("""INSERT INTO leave_requests(employee_id,type_id,type_key,from_date,to_date,days,reason,status,stage,doc_id,created_by) VALUES(?,?,?,?,?,?,?,'pending',?,?,?)""",
                    (emp["id"], lt["id"], key, frm.isoformat(), to.isoformat(), days, reason.strip() or None, stage, doc_id, by)).lastrowid
    audit(c, "طلب إجازة", f"{emp['number']} · {lt['name']} · {frm} → {to} ({days:g} يومًا)")
    return rid


def _request(c, rid: int) -> dict:
    return dict(one(c, "SELECT * FROM leave_requests WHERE id=?", (rid,), "الطلب غير موجود"))


def _finalize(c, r: dict, emp: dict, lt: dict, by: str, note: str, hr_stage: bool) -> None:
    if lt["needs_doc"] and not r["doc_id"]:
        raise HTTPException(409, "هذا النوع يلزمه مرفق (تقرير طبي أو ما يماثله) قبل الاعتماد")
    year = int(r["from_date"][:4])
    if float(lt["days_per_year"]) > 0 and not lt["allow_negative"]:
        b = balance(c, emp, r["type_key"], year)
        if r["days"] > b["remaining"] + 1e-9:  # the request's own days are still `pending`, not `taken`, so `remaining` is what is left before it
            raise HTTPException(409, f"الرصيد لا يكفي: المتبقي {b['remaining']:g} والمطلوب {r['days']:g}")
    c.execute("UPDATE leave_requests SET status='approved', stage='done', decided_by=?, decided_at=?, decision_note=? WHERE id=?", (by, now_s(), note or None, r["id"]))
    _mark_leave(c, emp["id"], pdate(r["from_date"]), pdate(r["to_date"]))
    balance(c, emp, r["type_key"], year)


def decide(c, rid: int, u: dict, action: str, note: str) -> dict:
    r = _request(c, rid)
    emp = employee(c, r["employee_id"])
    me = u.get("employee_id")
    hr_ok = is_hr(u)
    mgr_ok = me is not None and me == emp["manager_id"] and "hr_manager" in u["perms"]
    if me is not None and me == r["employee_id"]:
        raise HTTPException(403, "لا يمكنك البتّ في طلبك")
    if not hr_ok and not mgr_ok:
        raise HTTPException(404, "الطلب غير موجود")  # not revealed to someone outside the line
    if r["status"] != "pending":
        raise HTTPException(409, "الطلب لم يعد بانتظار قرار")
    if r["stage"] == "hr" and not hr_ok:
        raise HTTPException(403, "الطلب بانتظار الموارد البشرية")
    lt = dict(one(c, "SELECT * FROM leave_types WHERE id=?", (r["type_id"],), "نوع الإجازة غير موجود"))
    who = u["name"] + (" (موارد بشرية)" if hr_ok and r["stage"] == "manager" and not mgr_ok else "")
    if action == "reject":
        if len(note.strip()) < 3:
            raise HTTPException(400, "سبب الرفض مطلوب")
        c.execute("UPDATE leave_requests SET status='rejected', stage='done', decided_by=?, decided_at=?, decision_note=? WHERE id=?", (who, now_s(), note.strip(), rid))
        audit(c, "رفض إجازة", f"{emp['number']} · {lt['name']} · {r['from_date']}")
        return {"status": "rejected"}
    if r["stage"] == "manager" and mgr_ok and not hr_ok:
        c.execute("UPDATE leave_requests SET manager_by=?, manager_at=?, manager_note=? WHERE id=?", (who, now_s(), note.strip() or None, rid))
        if lt["needs_hr"]:
            c.execute("UPDATE leave_requests SET stage='hr' WHERE id=?", (rid,))
            audit(c, "اعتماد مدير لإجازة", f"{emp['number']} · {lt['name']} · بانتظار الموارد البشرية")
            return {"status": "pending", "stage": "hr"}
    elif r["stage"] == "manager":
        c.execute("UPDATE leave_requests SET manager_by=?, manager_at=? WHERE id=?", (who, now_s(), rid))
    _finalize(c, r, emp, lt, who, note.strip(), hr_ok)
    audit(c, "اعتماد إجازة", f"{emp['number']} · {lt['name']} · {r['from_date']} → {r['to_date']} ({r['days']:g} يومًا)")
    return {"status": "approved"}


def cancel(c, rid: int, u: dict, reason: str) -> dict:
    r = _request(c, rid)
    emp = employee(c, r["employee_id"])
    own = u.get("employee_id") == r["employee_id"]
    hr_ok = is_hr(u)
    if not own and not hr_ok:
        raise HTTPException(404, "الطلب غير موجود")
    if r["status"] not in ("pending", "approved"):
        raise HTTPException(409, "الطلب لا يُلغى في حالته")
    if not hr_ok and r["status"] == "approved" and r["from_date"] <= today().isoformat():
        raise HTTPException(409, "بدأت الإجازة — يطلب الموظف الإلغاء من الموارد البشرية")
    if (not own or hr_ok) and r["status"] == "approved" and len(reason.strip()) < 3:
        raise HTTPException(400, "سبب الإلغاء مطلوب")
    c.execute("UPDATE leave_requests SET status='cancelled', cancelled_by=?, cancelled_at=?, cancel_reason=? WHERE id=?", (u["name"], now_s(), reason.strip() or None, rid))
    if r["status"] == "approved":
        _unmark_leave(c, emp["id"], r["from_date"], r["to_date"])
    balance(c, emp, r["type_key"], int(r["from_date"][:4]))
    audit(c, "إلغاء إجازة", f"{emp['number']} · {r['type_key']} · {r['from_date']} → {r['to_date']}")
    return {"status": "cancelled"}


def cancel_after(c, eid: int, day: str, reason: str, by: str) -> int:
    """Termination on `day`: later leave goes, and a waiting request that reaches past it too. A leave already running stays as it was."""
    emp = employee(c, eid)
    n = 0
    for r in c.execute("SELECT * FROM leave_requests WHERE employee_id=? AND status IN ('pending','approved') AND to_date>?", (eid, day)).fetchall():
        if r["from_date"] > day or r["status"] == "pending":
            c.execute("UPDATE leave_requests SET status='cancelled', cancelled_by=?, cancelled_at=?, cancel_reason=? WHERE id=?", (by, now_s(), reason, r["id"]))
            if r["status"] == "approved":
                _unmark_leave(c, eid, r["from_date"], r["to_date"])
            balance(c, emp, r["type_key"], int(r["from_date"][:4]))
            n += 1
    return n


REQ_SQL = """SELECT r.id, r.employee_id, e.number, e.name, e.manager_id, m.name manager, r.type_id, r.type_key, t.name type_name, r.from_date, r.to_date, r.days, r.reason, r.status, r.stage,
             r.manager_by, r.manager_at, r.manager_note, r.decided_by, r.decided_at, r.decision_note, r.doc_id, r.created_by, r.cancelled_by, r.cancelled_at, r.cancel_reason, t.needs_hr, t.needs_doc
             FROM leave_requests r JOIN employees e ON e.id=r.employee_id JOIN leave_types t ON t.id=r.type_id LEFT JOIN employees m ON m.id=e.manager_id"""


def request_rows(c, where: str = "", args: tuple = ()) -> list[dict]:
    out = rows(c.execute(REQ_SQL + (" WHERE " + where if where else "") + " ORDER BY r.from_date DESC, r.id DESC", args))
    for x in out:
        x["status_label"] = STATUS_AR[x["status"]] + (" · عند الموارد البشرية" if x["status"] == "pending" and x["stage"] == "hr" else " · عند المدير" if x["status"] == "pending" else "")
    return out


@router.get("/api/hr/leave/requests")
def api_requests(status: str | None = Query(None, pattern="^(pending|approved|rejected|cancelled)$"), employee_id: int | None = None, year: int | None = Query(None, ge=2000, le=2100),
                 _=Depends(need("hr"))):
    c = db()
    ensure_types(c)
    where, args = [], []
    if status:
        where.append("r.status=?")
        args.append(status)
    if employee_id:
        where.append("r.employee_id=?")
        args.append(employee_id)
    if year:
        where.append("r.from_date>=? AND r.from_date<=?")
        args += [f"{year}-01-01", f"{year}-12-31"]
    return request_rows(c, " AND ".join(where), tuple(args))


class LeaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int
    type_key: str = Field(min_length=2, max_length=30)
    from_date: str
    to_date: str
    reason: str = Field(default="", max_length=300)
    doc_id: int | None = None
    approve: bool = False


@router.post("/api/hr/leave/requests")
def api_request_add(b: LeaveIn, u=Depends(act_as("hr"))):
    """HR records leave for an employee (a phone call, a medical report handed in). `approve` records it as already approved — except for HR's own file, which another person must decide."""
    c = db()
    emp = employee(c, b.employee_id)
    if b.approve and u.get("employee_id") == emp["id"]:
        raise HTTPException(403, "لا يمكنك اعتماد إجازتك — يعتمدها شخص آخر")
    rid = create_request(c, emp, b.type_key, b.from_date, b.to_date, b.reason, b.doc_id, u["name"])
    out = {"id": rid}
    if b.approve:
        out.update(decide(c, rid, u, "approve", "سُجّلت واعتُمدت من الموارد البشرية"))
    c.commit()
    return out


class DecideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject"]
    note: str = Field(default="", max_length=300)


@router.post("/api/hr/leave/requests/{rid}/decide")
def api_decide(rid: int, b: DecideIn, u=Depends(act_any("hr", "hr_manager"))):
    c = db()
    out = decide(c, rid, u, b.action, b.note)
    c.commit()
    return out


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=300)


@router.post("/api/hr/leave/requests/{rid}/cancel")
def api_cancel(rid: int, b: CancelIn, u=Depends(act_any("hr", "hr_self"))):
    c = db()
    out = cancel(c, rid, u, b.reason)
    c.commit()
    return out


@router.post("/api/hr/leave/requests/{rid}/attachment")
async def api_attach(rid: int, file: UploadFile = File(...), u=Depends(act_any("hr", "hr_self"))):
    """The medical report or proof for a request — the employee attaches to his own, HR to anyone's. Stored in the people file."""
    from .modules2 import store_upload
    c = db()
    r = _request(c, rid)
    if not (is_hr(u) or u.get("employee_id") == r["employee_id"]):
        raise HTTPException(404, "الطلب غير موجود")
    if r["status"] not in ("pending", "approved"):
        raise HTTPException(409, "الطلب مغلق")
    data = await file.read(5 * 1024 * 1024 + 1)
    did, _sha = store_upload(c, data, file.filename, "employee", r["employee_id"], f"مرفق إجازة #{rid}", "إجازات", u["name"])
    c.execute("UPDATE leave_requests SET doc_id=? WHERE id=?", (did, rid))
    c.commit()
    return {"doc_id": did}


# ----------------------------------------------------------------------------------------------------- types, balances
@router.get("/api/hr/leave/types")
def api_types(_=Depends(need("hr"))):
    """Every version of every type, newest first per key; `current` marks the one in force today."""
    c = db()
    ensure_types(c)
    out = rows(c.execute("SELECT * FROM leave_types ORDER BY key, valid_from DESC"))
    seen = set()
    for t in out:
        t["rules"] = rules_of(t)
        t["current"] = t["key"] not in seen and t["valid_from"] <= today().isoformat()
        if t["current"]:
            seen.add(t["key"])
    return out


class TypeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=2, max_length=30, pattern=r"^[a-z][a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=60)
    paid: bool = True
    days_per_year: float = Field(default=0, ge=0, le=400)
    accrual: Literal["annual", "monthly", "event"] = "annual"
    carry_over_max: float = Field(default=0, ge=0, le=400)
    needs_doc: bool = False
    needs_hr: bool = False
    gender_only: Literal["male", "female"] | None = None
    min_service_months: int = Field(default=0, ge=0, le=120)
    day_count: Literal["working", "calendar"] = "working"
    allow_negative: bool = False
    once_in_service: bool = False
    valid_from: str
    active: bool = True
    note: str = Field(default="", max_length=200)


@router.post("/api/hr/leave/types")
def api_type_add(b: TypeIn, u=Depends(act_as("hr"))):
    """A new version of a type from `valid_from` on (or a new type). Whoever enters it takes responsibility for the figures, so it is not provisional."""
    c = db()
    ensure_types(c)
    vf = pdate(b.valid_from, "تاريخ السريان").isoformat()
    if c.execute("SELECT 1 FROM leave_types WHERE key=? AND valid_from=?", (b.key, vf)).fetchone():
        raise HTTPException(409, "لهذا النوع نسخة بالتاريخ نفسه — اختر تاريخ سريان آخر")
    if b.days_per_year == 0 and b.paid and not b.allow_negative:
        raise HTTPException(400, "نوع مدفوع بلا رصيد سنوي يلزمه السماح بالتجاوز أو رصيد أكبر من صفر")
    tid = c.execute("""INSERT INTO leave_types(key,name,paid,days_per_year,accrual,carry_over_max,needs_doc,needs_hr,gender_only,min_service_months,day_count,allow_negative,rules,valid_from,active,provisional,note)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
                    (b.key, b.name.strip(), int(b.paid), b.days_per_year, b.accrual, b.carry_over_max, int(b.needs_doc), int(b.needs_hr), b.gender_only, b.min_service_months,
                     b.day_count, int(b.allow_negative), json.dumps({"once_in_service": True}) if b.once_in_service else None, vf, int(b.active), b.note or None)).lastrowid
    audit(c, "نوع إجازة", f"{b.name} ({b.key}) من {vf} · {b.days_per_year:g} يومًا")
    c.commit()
    return {"id": tid}


@router.post("/api/hr/leave/types/{tid}/confirm")
def api_type_confirm(tid: int, u=Depends(act_as("hr"))):
    c = db()
    t = one(c, "SELECT key, name FROM leave_types WHERE id=?", (tid,), "النوع غير موجود")
    c.execute("UPDATE leave_types SET provisional=0, note=NULL WHERE id=?", (tid,))
    audit(c, "اعتماد قيم نوع إجازة", f"{t['name']} — راجعها مختص وأقرّها")
    c.commit()
    return {"ok": True}


@router.get("/api/hr/employees/{eid}/leave-balances")
def api_balances(eid: int, year: int | None = Query(None, ge=2000, le=2100), _=Depends(need("hr"))):
    c = db()
    out = balances_of(c, employee(c, eid), year or today().year)
    c.commit()
    return out


class AdjustIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int
    type_key: str = Field(max_length=30)
    year: int = Field(ge=2000, le=2100)
    delta: float = Field(ge=-365, le=365)
    note: str = Field(min_length=3, max_length=200)


@router.post("/api/hr/leave/adjust")
def api_adjust(b: AdjustIn, u=Depends(act_as("hr"))):
    """A manual correction to a balance (an opening balance when the system starts, a grant). The note is mandatory and goes to the audit log."""
    c = db()
    emp = employee(c, b.employee_id)
    if abs(b.delta) < 1e-9:
        raise HTTPException(400, "الفرق صفر")
    if u.get("employee_id") == emp["id"]:
        raise HTTPException(403, "لا تعدّل رصيدك — يعدّله شخص آخر")
    bal = balance(c, emp, b.type_key, b.year)
    if bal["capped"] and bal["remaining"] + b.delta < -1e-9:
        raise HTTPException(409, f"التعديل يجعل الرصيد سالبًا ({bal['remaining'] + b.delta:g})")
    c.execute("UPDATE leave_balances SET adjusted=adjusted+?, adj_note=? WHERE employee_id=? AND type_key=? AND year=?", (b.delta, b.note.strip(), emp["id"], b.type_key, b.year))
    audit(c, "تعديل رصيد إجازة", f"{emp['number']} · {b.type_key} · {b.year}: {b.delta:+g} — {b.note.strip()}")
    c.commit()
    return balance(c, emp, b.type_key, b.year)


class RolloverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=2000, le=2100)


@router.post("/api/hr/leave/rollover")
def api_rollover(b: RolloverIn, u=Depends(act_as("hr"))):
    """Carry the unused days of `year` into `year + 1` up to each type's `carry_over_max`. Safe to run again: it sets the carried amount, it never adds to it."""
    c = db()
    ensure_types(c)
    n = 0
    for emp in [dict(r) for r in c.execute("SELECT * FROM employees WHERE status!='terminated'")]:
        for t in c.execute("SELECT DISTINCT key FROM leave_types WHERE active=1").fetchall():
            lt = type_on(c, t["key"], dt.date(b.year, 12, 31))
            if float(lt["carry_over_max"]) <= 0 or float(lt["days_per_year"]) <= 0 or (lt["gender_only"] and emp.get("gender") != lt["gender_only"]):
                continue
            rem = balance(c, emp, t["key"], b.year, dt.date(b.year, 12, 31))["remaining"]
            carry = round(min(max(rem, 0.0), float(lt["carry_over_max"])), 2)
            balance(c, emp, t["key"], b.year + 1)
            c.execute("UPDATE leave_balances SET carried=? WHERE employee_id=? AND type_key=? AND year=?", (carry, emp["id"], t["key"], b.year + 1))
            n += 1 if carry > 0 else 0
    audit(c, "ترحيل أرصدة الإجازات", f"من {b.year} إلى {b.year + 1}: {n} رصيدًا")
    c.commit()
    return {"carried": n}


# ----------------------------------------------------------------------------------------------------- holidays & settings
@router.get("/api/hr/holidays")
def api_holidays(year: int | None = Query(None, ge=2000, le=2100), _=Depends(need_any("hr", "hr_self"))):
    y = year or today().year
    return rows(db().execute("SELECT id, day, name FROM holidays WHERE day>=? AND day<=? ORDER BY day", (f"{y}-01-01", f"{y}-12-31")))


class HolidayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: str
    name: str = Field(min_length=2, max_length=80)


@router.post("/api/hr/holidays")
def api_holiday_add(b: HolidayIn, u=Depends(act_as("hr"))):
    c = db()
    d = pdate(b.day, "اليوم").isoformat()
    if c.execute("SELECT 1 FROM holidays WHERE day=?", (d,)).fetchone():
        raise HTTPException(409, "اليوم مسجَّل عطلةً")
    hid = c.execute("INSERT INTO holidays(day,name) VALUES(?,?)", (d, b.name.strip())).lastrowid
    audit(c, "عطلة رسمية", f"{d} · {b.name}")
    c.commit()
    return {"id": hid, "note": "الإجازات المعتمدة قبل إضافة العطلة تبقى بأيامها كما اعتُمدت"}


@router.delete("/api/hr/holidays/{hid}")
def api_holiday_del(hid: int, u=Depends(act_as("hr"))):
    c = db()
    h = one(c, "SELECT day, name FROM holidays WHERE id=?", (hid,), "العطلة غير موجودة")
    c.execute("DELETE FROM holidays WHERE id=?", (hid,))
    audit(c, "حذف عطلة رسمية", f"{h['day']} · {h['name']}")
    c.commit()
    return {"ok": True}


@router.get("/api/hr/settings")
def api_settings(_=Depends(need_any("hr", "hr_self"))):
    c = db()
    return {"weekend": sorted(weekend(c)), "work_start": work_start(c), "late_grace": late_grace(c)}


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weekend: list[int] = Field(min_length=0, max_length=3)
    work_start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    late_grace: int = Field(ge=0, le=120)


@router.put("/api/hr/settings")
def api_settings_put(b: SettingsIn, u=Depends(act_as("hr"))):
    if any(d < 0 or d > 6 for d in b.weekend):
        raise HTTPException(400, "أيام الراحة أرقام من 0 (الإثنين) إلى 6 (الأحد)")
    c = db()
    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ("hr:weekend", ",".join(str(d) for d in sorted(set(b.weekend)))))
    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ("hr:work_start", b.work_start))
    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ("hr:late_grace", str(b.late_grace)))
    audit(c, "إعدادات الحضور", f"راحة {sorted(set(b.weekend))} · بدء الدوام {b.work_start} · سماح {b.late_grace} د")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- attendance
def _time(v, what: str) -> str | None:
    if v in (None, ""):
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", str(v).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise HTTPException(400, f"{what} غير صالح (استعمل 08:05)")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def infer_status(c, check_in: str | None) -> str:
    if not check_in:
        return "present"
    h, m = map(int, work_start(c).split(":"))
    cut = h * 60 + m + late_grace(c)
    ci = int(check_in[:2]) * 60 + int(check_in[3:5])
    return "late" if ci > cut else "present"


class AttIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int
    day: str
    status: Literal["present", "absent", "late", "remote", "holiday"] | None = None
    check_in: str = ""
    check_out: str = ""
    note: str = Field(default="", max_length=200)


@router.post("/api/hr/attendance")
def api_att_set(b: AttIn, u=Depends(act_as("hr"))):
    c = db()
    emp = employee(c, b.employee_id)
    day = pdate(b.day, "اليوم")
    if day > today():
        raise HTTPException(400, "لا يُسجَّل حضور ليوم لم يأتِ بعد")
    if day.isoformat() < emp["hire_date"] or (emp["terminated_on"] and day.isoformat() > emp["terminated_on"]):
        raise HTTPException(400, "اليوم خارج مدة خدمة الموظف")
    ci, co = _time(b.check_in, "وقت الدخول"), _time(b.check_out, "وقت الخروج")
    if ci and co and co < ci:
        raise HTTPException(400, "الخروج قبل الدخول")
    status = b.status or ("absent" if not ci and not co else infer_status(c, ci))
    cur = c.execute("SELECT id, source FROM attendance WHERE employee_id=? AND day=?", (emp["id"], day.isoformat())).fetchone()
    if cur and cur["source"] == "leave":
        raise HTTPException(409, "اليوم إجازة معتمدة — ألغِ الإجازة أولًا لتعديله")
    if cur:
        c.execute("UPDATE attendance SET status=?, check_in=?, check_out=?, source='manual', note=? WHERE id=?", (status, ci, co, b.note or None, cur["id"]))
    else:
        c.execute("INSERT INTO attendance(employee_id,day,status,check_in,check_out,source,note) VALUES(?,?,?,?,?,'manual',?)", (emp["id"], day.isoformat(), status, ci, co, b.note or None))
    c.commit()
    return {"status": status}


@router.get("/api/hr/attendance")
def api_att_day(day: str | None = None, _=Depends(need("hr"))):
    """One day for everyone on the payroll — people with no mark are listed too (`status` null)."""
    c = db()
    d = pdate(day or today().isoformat(), "اليوم").isoformat()
    return rows(c.execute("""SELECT e.id employee_id, e.number, e.name, a.status, a.check_in, a.check_out, a.source, a.note FROM employees e
                             LEFT JOIN attendance a ON a.employee_id=e.id AND a.day=? WHERE e.status!='terminated' AND e.hire_date<=? ORDER BY e.number""", (d, d)))


@router.get("/api/hr/attendance/month")
def api_att_month(month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), _=Depends(need("hr"))):
    """Per person: the days by status and the working days up to today with no mark at all (`unrecorded`) — those are not counted as absence until HR decides."""
    c = db()
    y, m = int(month[:4]), int(month[5:])
    ms, me = dt.date(y, m, 1), dt.date(y + (m == 12), m % 12 + 1, 1) - DAY
    upto = min(me, today())
    wk, hol = weekend(c), holiday_set(c, ms.isoformat(), me.isoformat())
    marks: dict = {}
    for r in c.execute("SELECT employee_id, day, status FROM attendance WHERE day>=? AND day<=?", (ms.isoformat(), me.isoformat())):
        marks.setdefault(r["employee_id"], {})[r["day"]] = r["status"]
    out = []
    for e in c.execute("SELECT id, number, name, hire_date, terminated_on FROM employees WHERE hire_date<=? AND (terminated_on IS NULL OR terminated_on>=?) ORDER BY number", (me.isoformat(), ms.isoformat())):
        mk = marks.get(e["id"], {})
        cnt = {s: 0 for s in ATT_STATUS}
        for s in mk.values():
            cnt[s] += 1
        unrec, d = 0, max(ms, pdate(e["hire_date"]))
        end = min(upto, pdate(e["terminated_on"])) if e["terminated_on"] else upto
        while d <= end:
            if d.weekday() not in wk and d.isoformat() not in hol and d.isoformat() not in mk:
                unrec += 1
            d += DAY
        out.append({"employee_id": e["id"], "number": e["number"], "name": e["name"], **cnt, "unrecorded": unrec})
    return out


@router.post("/api/hr/attendance/import")
async def api_att_import(file: UploadFile = File(...), dry: bool = Query(False), u=Depends(act_as("hr"))):
    """Attendance from a device export (xlsx/csv: employee number, date, check-in, check-out, optional status). Re-importing the same file changes nothing; a day that HR
    marked by hand or that is approved leave is never overwritten — it is reported instead."""
    c = db()
    table = read_table(file.filename or "", await file.read(5_000_001), "attendance")
    by_no = {r["number"].upper(): dict(r) for r in c.execute("SELECT id, number, hire_date, terminated_on FROM employees")}
    new = upd = dup = skipped = 0
    errors: list[dict] = []
    for rn, r in table:
        try:
            emp = by_no.get(str(r.get("number") or "").strip().upper())
            if not emp:
                raise ValueError("رقم موظف غير معروف")
            raw = str(r.get("date") or "").strip()[:10]
            try:
                day = dt.date.fromisoformat(raw)
            except ValueError:
                day = dt.datetime.strptime(raw, "%d/%m/%Y").date()
            if day > today():
                raise ValueError("تاريخ في المستقبل")
            if day.isoformat() < emp["hire_date"] or (emp["terminated_on"] and day.isoformat() > emp["terminated_on"]):
                raise ValueError("خارج مدة الخدمة")
            ci, co = _time(r.get("check_in"), "الدخول"), _time(r.get("check_out"), "الخروج")
            if ci and co and co < ci:
                raise ValueError("الخروج قبل الدخول")
            word = str(r.get("status") or "").strip()
            if word and word not in ATT_WORDS:
                raise ValueError(f"حالة غير معروفة: {word}")
            if not word and not ci and not co:
                raise ValueError("لا حالة ولا أوقات")
            st = ATT_WORDS[word] if word else infer_status(c, ci)
        except (ValueError, HTTPException) as ex:
            errors.append({"row": rn, "reason": ex.detail if isinstance(ex, HTTPException) else str(ex)})
            continue
        cur = c.execute("SELECT id, source, status, check_in, check_out FROM attendance WHERE employee_id=? AND day=?", (emp["id"], day.isoformat())).fetchone()
        if cur and cur["source"] in ("manual", "leave"):
            skipped += 1
        elif cur and (cur["status"], cur["check_in"], cur["check_out"]) == (st, ci, co):
            dup += 1
        elif cur:
            upd += 1
            if not dry:
                c.execute("UPDATE attendance SET status=?, check_in=?, check_out=?, source='import' WHERE id=?", (st, ci, co, cur["id"]))
        else:
            new += 1
            if not dry:
                c.execute("INSERT INTO attendance(employee_id,day,status,check_in,check_out,source) VALUES(?,?,?,?,?,'import')", (emp["id"], day.isoformat(), st, ci, co))
    if not dry:
        audit(c, "استيراد حضور", f"{file.filename} · جديد {new} · محدَّث {upd} · مكرر {dup} · متروك (يدوي/إجازة) {skipped} · أخطاء {len(errors)}")
        c.commit()
    return {"dry": dry, "new": new, "updated": upd, "duplicate": dup, "skipped_manual": skipped, "errors": errors[:50], "error_count": len(errors)}
