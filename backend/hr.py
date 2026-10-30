"""Mabaniq 0.25.0 — human resources, the people file (design docs/DESIGN-leasing-accounting-hr-modules.md §5.1, phase 4a).

Departments and positions, the employee file (identity, bank and insurance numbers are encrypted at rest), the documents each employee must keep valid with expiry
alerts at 90 / 30 days, and the login of an employee. Nothing here holds a salary — payroll arrives in 0.26.0 behind its own permission (`hr_payroll`).

Who sees what: `hr` sees every file (each opening is written to the audit log); a manager sees the work card of his direct reports only (no identity numbers, no bank);
an employee sees his own file. A file is never deleted: service ends with status `terminated`, which also closes the login.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import auth as A
from . import pii
from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .db import TENANT, connect, tenants
from .modules import one

router = APIRouter()

SENSITIVE = ("id_number", "dob", "iban", "social_ins_no", "emergency_contact")
DOC_KINDS = {"passport": "جواز السفر", "resident_card": "البطاقة المدنية / الإقامة", "work_permit": "تصريح العمل", "labour_card": "بطاقة العمل",
             "health_insurance": "التأمين الصحي", "contract": "عقد العمل", "certificate": "شهادة", "other": "أخرى"}
CONTRACTS = {"permanent": "دائم", "fixed": "محدد المدة", "part": "دوام جزئي"}
STATUSES = {"active": "على رأس العمل", "on_leave": "في إجازة", "terminated": "منتهي الخدمة"}
ALERT_DAYS = (90, 30)


# ----------------------------------------------------------------------------------------------------- helpers
def pdate(s, what: str = "التاريخ") -> dt.date:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        raise HTTPException(400, f"{what} غير صالح") from None


def opt_date(s, what: str):
    return pdate(s, what).isoformat() if s not in (None, "") else None


def next_no(c, key: str) -> int:
    c.execute("INSERT OR IGNORE INTO counters(k,n) VALUES(?,0)", (key,))
    c.execute("UPDATE counters SET n=n+1 WHERE k=?", (key,))
    return c.execute("SELECT n FROM counters WHERE k=?", (key,)).fetchone()["n"]


def employee(c, eid: int) -> dict:
    return dict(one(c, "SELECT * FROM employees WHERE id=?", (eid,), "الموظف غير موجود"))


def is_hr(u: dict) -> bool:
    return "hr" in u["perms"]


def own_employee(c, u: dict) -> dict:
    """The employee file behind the signed-in account; a clear 404 for an account that is not linked to one."""
    if not u.get("employee_id"):
        raise HTTPException(404, "حسابك غير مرتبط بملف موظف")
    return employee(c, u["employee_id"])


def reveal(e: dict) -> dict:
    """The file with its encrypted fields opened — only for hr and the employee himself."""
    e = dict(e)
    for k in SENSITIVE:
        e[k] = pii.dec(e.get(k))
    return e


BASE_SQL = """SELECT e.id, e.number, e.name, e.name_en, e.nationality, e.omani, e.gender, e.marital, e.phone, e.email, e.department_id, d.name department, e.position_id, p.title position,
              e.manager_id, m.name manager, e.hire_date, e.contract_type, e.contract_end, e.probation_end, e.status, e.terminated_on,
              (SELECT u.username FROM users u WHERE u.employee_id=e.id) username
              FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN positions p ON p.id=e.position_id LEFT JOIN employees m ON m.id=e.manager_id"""


def _chain_has(c, start: int | None, target: int, table: str, col: str) -> bool:
    """Walk up a parent chain: does `start` reach `target`? (prevents cycles in the manager line and the department tree)."""
    seen = 0
    cur = start
    while cur is not None and seen < 100:
        if cur == target:
            return True
        r = c.execute(f"SELECT {col} p FROM {table} WHERE id=?", (cur,)).fetchone()
        cur = r["p"] if r else None
        seen += 1
    return False


# ----------------------------------------------------------------------------------------------------- departments & positions
@router.get("/api/hr/departments")
def api_departments(_=Depends(need("hr"))):
    c = db()
    return rows(c.execute("""SELECT d.id, d.name, d.parent_id, pd.name parent, d.head_employee_id, h.name head, d.cost_center_id, cc.name cost_center, d.active,
                             (SELECT COUNT(*) FROM employees e WHERE e.department_id=d.id AND e.status!='terminated') headcount
                             FROM departments d LEFT JOIN departments pd ON pd.id=d.parent_id LEFT JOIN employees h ON h.id=d.head_employee_id
                             LEFT JOIN acc_cost_centers cc ON cc.id=d.cost_center_id ORDER BY d.name"""))


class DeptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    parent_id: int | None = None
    head_employee_id: int | None = None
    cost_center_id: int | None = None


class DeptPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=80)
    parent_id: int | None = None
    head_employee_id: int | None = None
    cost_center_id: int | None = None
    active: bool | None = None


def _dept_refs(c, b, did: int | None = None) -> None:
    if b.parent_id is not None:
        one(c, "SELECT 1 FROM departments WHERE id=?", (b.parent_id,), "القسم الأب غير موجود")
        if did is not None and _chain_has(c, b.parent_id, did, "departments", "parent_id"):
            raise HTTPException(409, "لا يصحّ أن يكون القسم تحت نفسه أو تحت أحد فروعه")
    if b.head_employee_id is not None:
        h = one(c, "SELECT status FROM employees WHERE id=?", (b.head_employee_id,), "رئيس القسم غير موجود")
        if h["status"] == "terminated":
            raise HTTPException(409, "رئيس القسم منتهي الخدمة")
    if b.cost_center_id is not None:
        one(c, "SELECT 1 FROM acc_cost_centers WHERE id=?", (b.cost_center_id,), "مركز الكلفة غير موجود")


@router.post("/api/hr/departments")
def api_dept_add(b: DeptIn, u=Depends(act_as("hr"))):
    c = db()
    if c.execute("SELECT 1 FROM departments WHERE name=?", (b.name.strip(),)).fetchone():
        raise HTTPException(409, "قسم بهذا الاسم موجود")
    _dept_refs(c, b)
    did = c.execute("INSERT INTO departments(name,parent_id,head_employee_id,cost_center_id) VALUES(?,?,?,?)", (b.name.strip(), b.parent_id, b.head_employee_id, b.cost_center_id)).lastrowid
    audit(c, "قسم جديد", b.name)
    c.commit()
    return {"id": did}


@router.patch("/api/hr/departments/{did}")
def api_dept_edit(did: int, b: DeptPatch, u=Depends(act_as("hr"))):
    c = db()
    cur = dict(one(c, "SELECT * FROM departments WHERE id=?", (did,), "القسم غير موجود"))
    sent = b.model_fields_set
    if "name" in sent and b.name and b.name.strip() != cur["name"] and c.execute("SELECT 1 FROM departments WHERE name=? AND id!=?", (b.name.strip(), did)).fetchone():
        raise HTTPException(409, "قسم بهذا الاسم موجود")
    _dept_refs(c, b, did)
    if b.active is False and c.execute("SELECT 1 FROM employees WHERE department_id=? AND status!='terminated'", (did,)).fetchone():
        raise HTTPException(409, "في القسم موظفون على رأس العمل — انقلهم قبل إيقافه")
    new = {k: (getattr(b, k) if k in sent else cur[k]) for k in ("name", "parent_id", "head_employee_id", "cost_center_id")}
    new["name"] = (new["name"] or cur["name"]).strip()
    c.execute("UPDATE departments SET name=?, parent_id=?, head_employee_id=?, cost_center_id=?, active=? WHERE id=?",
              (new["name"], new["parent_id"], new["head_employee_id"], new["cost_center_id"], int(b.active) if b.active is not None else cur["active"], did))
    audit(c, "تعديل قسم", new["name"])
    c.commit()
    return {"ok": True}


@router.get("/api/hr/positions")
def api_positions(_=Depends(need("hr"))):
    c = db()
    return rows(c.execute("""SELECT p.id, p.title, p.department_id, d.name department, p.grade, p.headcount, p.active,
                             (SELECT COUNT(*) FROM employees e WHERE e.position_id=p.id AND e.status!='terminated') filled
                             FROM positions p LEFT JOIN departments d ON d.id=p.department_id ORDER BY d.name, p.title"""))


class PositionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=80)
    department_id: int | None = None
    grade: str = Field(default="", max_length=20)
    headcount: int = Field(default=1, ge=0, le=1000)


class PositionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=2, max_length=80)
    grade: str | None = Field(default=None, max_length=20)
    headcount: int | None = Field(default=None, ge=0, le=1000)
    active: bool | None = None


@router.post("/api/hr/positions")
def api_position_add(b: PositionIn, u=Depends(act_as("hr"))):
    c = db()
    if b.department_id is not None:
        one(c, "SELECT 1 FROM departments WHERE id=?", (b.department_id,), "القسم غير موجود")
    if c.execute("SELECT 1 FROM positions WHERE title=? AND COALESCE(department_id,0)=?", (b.title.strip(), b.department_id or 0)).fetchone():
        raise HTTPException(409, "مسمى وظيفي بهذا الاسم موجود في القسم")
    pid = c.execute("INSERT INTO positions(title,department_id,grade,headcount) VALUES(?,?,?,?)", (b.title.strip(), b.department_id, b.grade or None, b.headcount)).lastrowid
    audit(c, "مسمى وظيفي جديد", b.title)
    c.commit()
    return {"id": pid}


@router.patch("/api/hr/positions/{pid}")
def api_position_edit(pid: int, b: PositionPatch, u=Depends(act_as("hr"))):
    c = db()
    cur = dict(one(c, "SELECT * FROM positions WHERE id=?", (pid,), "المسمى غير موجود"))
    sent = b.model_fields_set
    title = (b.title or cur["title"]).strip() if "title" in sent else cur["title"]
    if title != cur["title"] and c.execute("SELECT 1 FROM positions WHERE title=? AND COALESCE(department_id,0)=? AND id!=?", (title, cur["department_id"] or 0, pid)).fetchone():
        raise HTTPException(409, "مسمى وظيفي بهذا الاسم موجود في القسم")
    if b.active is False and c.execute("SELECT 1 FROM employees WHERE position_id=? AND status!='terminated'", (pid,)).fetchone():
        raise HTTPException(409, "يشغل المسمى موظفون على رأس العمل")
    c.execute("UPDATE positions SET title=?, grade=?, headcount=?, active=? WHERE id=?",
              (title, (b.grade or None) if "grade" in sent else cur["grade"], b.headcount if "headcount" in sent and b.headcount is not None else cur["headcount"],
               int(b.active) if b.active is not None else cur["active"], pid))
    audit(c, "تعديل مسمى وظيفي", title)
    c.commit()
    return {"ok": True}


@router.get("/api/hr/tree")
def api_tree(_=Depends(need("hr"))):
    """The organisation as nested departments, each with its head and the people (name + position only) — for the chart on the HR screen."""
    c = db()
    depts = rows(c.execute("SELECT d.id, d.name, d.parent_id, h.name head FROM departments d LEFT JOIN employees h ON h.id=d.head_employee_id WHERE d.active=1 ORDER BY d.name"))
    people = rows(c.execute("SELECT e.id, e.name, e.department_id, p.title position FROM employees e LEFT JOIN positions p ON p.id=e.position_id WHERE e.status!='terminated' ORDER BY e.name"))
    by_dept: dict = {}
    for p in people:
        by_dept.setdefault(p["department_id"], []).append({"id": p["id"], "name": p["name"], "position": p["position"]})
    nodes = {d["id"]: {**d, "people": by_dept.get(d["id"], []), "children": []} for d in depts}
    roots = []
    for d in depts:
        (nodes[d["parent_id"]]["children"] if d["parent_id"] in nodes else roots).append(nodes[d["id"]])
    return {"departments": roots, "unassigned": by_dept.get(None, [])}


# ----------------------------------------------------------------------------------------------------- employees
class EmployeeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    name_en: str = Field(default="", max_length=120)
    nationality: str = Field(default="", max_length=60)
    omani: bool = False
    id_number: str = Field(default="", max_length=40)
    dob: str = ""
    gender: Literal["male", "female"] | None = None
    marital: Literal["single", "married", "divorced", "widowed"] | None = None
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=200)
    department_id: int | None = None
    position_id: int | None = None
    manager_id: int | None = None
    hire_date: str
    contract_type: Literal["permanent", "fixed", "part"] = "permanent"
    contract_end: str = ""
    probation_end: str = ""
    bank_name: str = Field(default="", max_length=80)
    iban: str = Field(default="", max_length=40)
    social_ins_no: str = Field(default="", max_length=40)
    pasi_applies: bool | None = None
    emergency_contact: str = Field(default="", max_length=200)


class EmployeePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=120)
    name_en: str | None = Field(default=None, max_length=120)
    nationality: str | None = Field(default=None, max_length=60)
    omani: bool | None = None
    id_number: str | None = Field(default=None, max_length=40)
    dob: str | None = None
    gender: Literal["male", "female"] | None = None
    marital: Literal["single", "married", "divorced", "widowed"] | None = None
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=200)
    department_id: int | None = None
    position_id: int | None = None
    manager_id: int | None = None
    hire_date: str | None = None
    contract_type: Literal["permanent", "fixed", "part"] | None = None
    contract_end: str | None = None
    probation_end: str | None = None
    bank_name: str | None = Field(default=None, max_length=80)
    iban: str | None = Field(default=None, max_length=40)
    social_ins_no: str | None = Field(default=None, max_length=40)
    pasi_applies: bool | None = None
    emergency_contact: str | None = Field(default=None, max_length=200)


def _check_refs(c, department_id, position_id, manager_id, eid: int | None = None) -> list[str]:
    """Foreign references exist and the manager line has no cycle; returns non-blocking warnings (a position above its headcount)."""
    warns = []
    if department_id is not None:
        d = one(c, "SELECT active FROM departments WHERE id=?", (department_id,), "القسم غير موجود")
        if not d["active"]:
            raise HTTPException(409, "القسم موقوف")
    if position_id is not None:
        p = one(c, "SELECT title, headcount, active, department_id FROM positions WHERE id=?", (position_id,), "المسمى الوظيفي غير موجود")
        if not p["active"]:
            raise HTTPException(409, "المسمى الوظيفي موقوف")
        filled = c.execute("SELECT COUNT(*) n FROM employees WHERE position_id=? AND status!='terminated' AND id!=?", (position_id, eid or 0)).fetchone()["n"]
        if filled >= p["headcount"]:
            warns.append(f"المسمى «{p['title']}» تجاوز العدد المعتمد ({p['headcount']})")
    if manager_id is not None:
        m = one(c, "SELECT status FROM employees WHERE id=?", (manager_id,), "المدير المباشر غير موجود")
        if m["status"] == "terminated":
            raise HTTPException(409, "المدير المباشر منتهي الخدمة")
        if eid is not None and _chain_has(c, manager_id, eid, "employees", "manager_id"):
            raise HTTPException(409, "سلسلة المدراء تدور على نفسها — اختر مديرًا آخر")
    return warns


def _fmt_dates(hire, contract_type, contract_end, probation_end, dob):
    h = pdate(hire, "تاريخ التعيين")
    if h > today() + dt.timedelta(days=366):
        raise HTTPException(400, "تاريخ التعيين بعيد في المستقبل")
    ce, pe, db_ = opt_date(contract_end, "نهاية العقد"), opt_date(probation_end, "نهاية التجربة"), opt_date(dob, "تاريخ الميلاد")
    if contract_type == "fixed" and not ce:
        raise HTTPException(400, "العقد محدد المدة يلزمه تاريخ نهاية")
    if ce and ce < h.isoformat():
        raise HTTPException(400, "نهاية العقد قبل تاريخ التعيين")
    if pe and pe < h.isoformat():
        raise HTTPException(400, "نهاية التجربة قبل تاريخ التعيين")
    if db_ and db_ >= h.isoformat():
        raise HTTPException(400, "تاريخ الميلاد بعد تاريخ التعيين")
    return h.isoformat(), ce, pe, db_


@router.get("/api/hr/employees")
def api_employees(status: str | None = Query(None, pattern="^(active|on_leave|terminated|current)$"), department_id: int | None = None, q: str | None = Query(None, max_length=60),
                  _=Depends(need("hr"))):
    c = db()
    sql, args = BASE_SQL + " WHERE 1=1", []
    if status == "current":
        sql += " AND e.status!='terminated'"
    elif status:
        sql += " AND e.status=?"
        args.append(status)
    if department_id:
        sql += " AND e.department_id=?"
        args.append(department_id)
    if q:
        sql += " AND (e.name LIKE ? OR e.number LIKE ? OR e.name_en LIKE ?)"
        args += [f"%{q}%"] * 3
    return rows(c.execute(sql + " ORDER BY e.number", args))


@router.get("/api/hr/summary")
def api_summary(_=Depends(need("hr"))):
    """The headline figures. The Omanisation ratio is the share of Omani nationals among the people on the payroll — informational; the ministry's own method may differ."""
    c = db()
    cur = [dict(r) for r in c.execute("SELECT omani, status, contract_type, hire_date, department_id FROM employees WHERE status!='terminated'")]
    n = len(cur)
    om = sum(1 for e in cur if e["omani"])
    since = (today() - dt.timedelta(days=90)).isoformat()
    by_dept = rows(c.execute("""SELECT COALESCE(d.name,'بلا قسم') department, COUNT(*) n FROM employees e LEFT JOIN departments d ON d.id=e.department_id
                                WHERE e.status!='terminated' GROUP BY COALESCE(d.name,'بلا قسم') ORDER BY 2 DESC"""))
    items = expiry_items(c, today())
    return {"headcount": n, "omani": om, "omani_pct": round(100 * om / n, 1) if n else None, "on_leave_today": c.execute("SELECT COUNT(DISTINCT employee_id) n FROM leave_requests WHERE status='approved' AND from_date<=? AND to_date>=?",
                                                              (today().isoformat(),) * 2).fetchone()["n"],
            "contracts": {k: sum(1 for e in cur if e["contract_type"] == k) for k in CONTRACTS}, "hired_90d": sum(1 for e in cur if e["hire_date"] >= since),
            "terminated": c.execute("SELECT COUNT(*) n FROM employees WHERE status='terminated'").fetchone()["n"], "by_department": by_dept,
            "expiring_30": sum(1 for i in items if i["level"] in ("expired", "critical")), "expiring_90": len(items),
            "pending_leave": c.execute("SELECT COUNT(*) n FROM leave_requests WHERE status='pending'").fetchone()["n"],
            "pending_requests": c.execute("SELECT COUNT(*) n FROM hr_requests WHERE status='pending'").fetchone()["n"]}


@router.get("/api/hr/employees/{eid}")
def api_employee(eid: int, u=Depends(act_as("hr"))):
    """The whole file, identity and bank included — each opening is recorded in the audit log."""
    c = db()
    e = reveal(employee(c, eid))
    e.update({k: v for k, v in dict(one(c, BASE_SQL + " WHERE e.id=?", (eid,))).items() if k in ("department", "position", "manager", "username")})
    e["documents"] = documents_of(c, eid)
    audit(c, "فتح ملف موظف", f"{e['number']} · {e['name']}")
    c.commit()
    return e


@router.post("/api/hr/employees")
def api_employee_add(b: EmployeeIn, u=Depends(act_as("hr"))):
    c = db()
    hire, ce, pe, dob = _fmt_dates(b.hire_date, b.contract_type, b.contract_end, b.probation_end, b.dob)
    warns = _check_refs(c, b.department_id, b.position_id, b.manager_id)
    if b.email and c.execute("SELECT 1 FROM employees WHERE lower(email)=? AND status!='terminated'", (b.email.strip().lower(),)).fetchone():
        raise HTTPException(409, "هذا البريد لموظف آخر")
    if b.id_number and any(pii.dec(r["id_number"]) == b.id_number.strip() for r in c.execute("SELECT id_number FROM employees WHERE id_number IS NOT NULL").fetchall()):
        raise HTTPException(409, "رقم الهوية مسجَّل لملف موظف آخر")
    n = next_no(c, "hr:emp")
    number = f"EMP-{n:04d}"
    nat = b.nationality.strip() or ("عُماني" if b.omani else "")
    pasi = int(b.omani if b.pasi_applies is None else b.pasi_applies)
    eid = c.execute("""INSERT INTO employees(number,name,name_en,nationality,omani,id_number,dob,gender,marital,phone,email,address,department_id,position_id,manager_id,hire_date,
                       contract_type,contract_end,probation_end,bank_name,iban,social_ins_no,pasi_applies,emergency_contact,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (number, b.name.strip(), b.name_en.strip() or None, nat or None, int(b.omani), pii.enc(b.id_number.strip()) if b.id_number else None, pii.enc(dob) if dob else None,
                     b.gender, b.marital, b.phone or None, b.email.strip() or None, b.address or None, b.department_id, b.position_id, b.manager_id, hire, b.contract_type, ce, pe,
                     b.bank_name or None, pii.enc(b.iban.strip()) if b.iban else None, pii.enc(b.social_ins_no.strip()) if b.social_ins_no else None, pasi,
                     pii.enc(b.emergency_contact) if b.emergency_contact else None, u["name"])).lastrowid
    audit(c, "موظف جديد", f"{number} · {b.name}")
    c.commit()
    return {"id": eid, "number": number, "warnings": warns}


@router.patch("/api/hr/employees/{eid}")
def api_employee_edit(eid: int, b: EmployeePatch, u=Depends(act_as("hr"))):
    c = db()
    cur = employee(c, eid)
    if cur["status"] == "terminated":
        raise HTTPException(409, "الملف منتهي الخدمة ولا يُعدَّل")
    sent = b.model_fields_set
    new: dict = {}
    plain = ("name", "name_en", "nationality", "gender", "marital", "phone", "email", "address", "bank_name", "contract_type")
    for k in plain:
        if k in sent:
            v = getattr(b, k)
            new[k] = (v.strip() or None) if isinstance(v, str) else v
    if "name" in new and not new["name"]:
        raise HTTPException(400, "الاسم مطلوب")
    if "contract_type" in new and not new["contract_type"]:
        raise HTTPException(400, "نوع العقد مطلوب")
    for k in ("omani", "pasi_applies"):
        if k in sent and getattr(b, k) is not None:
            new[k] = int(getattr(b, k))
    sens = {}
    for k in ("id_number", "iban", "social_ins_no", "emergency_contact"):
        if k in sent:
            sens[k] = (getattr(b, k) or "").strip() or None
    if sens.get("id_number") and any(pii.dec(r["id_number"]) == sens["id_number"] for r in c.execute("SELECT id_number FROM employees WHERE id_number IS NOT NULL AND id!=?", (eid,)).fetchall()):
        raise HTTPException(409, "رقم الهوية مسجَّل لملف موظف آخر")
    ct = new.get("contract_type", cur["contract_type"])
    hire_in = b.hire_date if "hire_date" in sent and b.hire_date else cur["hire_date"]
    dob_plain = (b.dob if "dob" in sent else pii.dec(cur["dob"])) or None
    hire, ce, pe, dob = _fmt_dates(hire_in, ct, b.contract_end if "contract_end" in sent else cur["contract_end"], b.probation_end if "probation_end" in sent else cur["probation_end"], dob_plain)
    new.update(hire_date=hire, contract_end=ce, probation_end=pe)
    sens["dob"] = dob
    dep = b.department_id if "department_id" in sent else cur["department_id"]
    pos = b.position_id if "position_id" in sent else cur["position_id"]
    mgr = b.manager_id if "manager_id" in sent else cur["manager_id"]
    warns = _check_refs(c, dep, pos, mgr, eid) if ({"department_id", "position_id", "manager_id"} & sent) else []
    new.update(department_id=dep, position_id=pos, manager_id=mgr)
    changed = [k for k, v in new.items() if cur.get(k) != v]
    for k, v in sens.items():  # ciphertext differs on every encryption — compare the opened values
        if (pii.dec(cur.get(k)) or None) != v:
            changed.append(k)
            new[k] = pii.enc(v) if v else None
    new = {k: v for k, v in new.items() if k in changed}
    if changed:
        c.execute("UPDATE employees SET " + ", ".join(f"{k}=?" for k in new) + " WHERE id=?", (*new.values(), eid))
        # the audit line names the fields, never the values of the sensitive ones
        audit(c, "تعديل ملف موظف", f"{cur['number']} · الحقول: {', '.join(changed)}")
        c.commit()
    return {"ok": True, "changed": changed, "warnings": warns}


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "on_leave", "terminated"]
    date: str = ""
    note: str = Field(default="", max_length=300)


def terminate(c, e: dict, day: str, note: str, by: str) -> int:
    """End a person's service on `day`: final, closes the login, cancels later leave. Shared by the status endpoint and the approval of a settlement. Returns the leave requests cancelled."""
    if day < e["hire_date"]:
        raise HTTPException(400, "تاريخ انتهاء الخدمة قبل التعيين")
    if not (note or "").strip():
        raise HTTPException(400, "سبب انتهاء الخدمة مطلوب")
    if c.execute("SELECT 1 FROM employees WHERE manager_id=? AND status!='terminated'", (e["id"],)).fetchone():
        raise HTTPException(409, "له مرؤوسون على رأس العمل — أسند لهم مديرًا آخر أولًا")
    from . import hr_leave
    n = hr_leave.cancel_after(c, e["id"], day, "إنهاء الخدمة", by)
    c.execute("UPDATE employees SET status='terminated', terminated_on=?, termination_note=? WHERE id=?", (day, note.strip(), e["id"]))
    c.execute("UPDATE departments SET head_employee_id=NULL WHERE head_employee_id=?", (e["id"],))
    for r in c.execute("SELECT id FROM users WHERE employee_id=?", (e["id"],)).fetchall():
        c.execute("UPDATE users SET active=0 WHERE id=?", (r["id"],))
        A.kill_sessions(c, r["id"])
    audit(c, "إنهاء خدمة موظف", f"{e['number']} · {e['name']} · {day} · إجازات أُلغيت {n}")
    return n


@router.post("/api/hr/employees/{eid}/status")
def api_employee_status(eid: int, b: StatusIn, u=Depends(act_as("hr"))):
    """Termination is final: the login is closed, future leave is cancelled, and the file stays (service history is kept). The end-of-service settlement arrives in 0.26.0."""
    c = db()
    e = employee(c, eid)
    if e["status"] == "terminated":
        raise HTTPException(409, "الملف منتهي الخدمة — يُنشأ ملف جديد عند إعادة التعيين")
    if b.status == "terminated":
        terminate(c, e, pdate(b.date or today().isoformat(), "تاريخ انتهاء الخدمة").isoformat(), b.note, u["name"])
    else:
        c.execute("UPDATE employees SET status=? WHERE id=?", (b.status, eid))
        audit(c, "حالة موظف", f"{e['number']} ← {STATUSES[b.status]}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- the employee's login
@router.post("/api/hr/employees/{eid}/account")
def api_account_create(eid: int, u=Depends(act_as("hr"))):
    """A portal login (role `employee`) for the file. HR may only create this role — staff roles are made by the administrator and linked to a file by it."""
    c = db()
    e = employee(c, eid)
    if e["status"] == "terminated":
        raise HTTPException(409, "الملف منتهي الخدمة")
    if c.execute("SELECT 1 FROM users WHERE employee_id=?", (eid,)).fetchone():
        raise HTTPException(409, "للموظف حساب بالفعل")
    username = "emp" + e["number"].split("-")[-1].lower()
    if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise HTTPException(409, "اسم المستخدم المقترح مستخدم")
    email = (e["email"] or "").strip().lower() or None
    if email and c.execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone():
        email = None  # the address belongs to another login; the account is still created, without e-mail sign-in
    temp = A.temp_password()
    c.execute("INSERT INTO users(username,name,role,pw,must_change,email,employee_id) VALUES(?,?,?,?,1,?,?)", (username, e["name"], "employee", A.hash_pw(temp), email, eid))
    audit(c, "حساب موظف جديد", f"{username} ↔ {e['number']}")
    c.commit()
    return {"username": username, "temporary_password": temp, "note": "تُعرض مرة واحدة فقط، ويُلزم الموظف بتغييرها عند أول دخول."}


@router.post("/api/hr/employees/{eid}/account/reset")
def api_account_reset(eid: int, u=Depends(act_as("hr"))):
    c = db()
    e = employee(c, eid)
    t = one(c, "SELECT id, username, role FROM users WHERE employee_id=?", (eid,), "لا حساب لهذا الموظف")
    if t["role"] != "employee":
        raise HTTPException(403, "حسابات الأدوار الإدارية يعيد تعيينها المدير العام")
    temp = A.temp_password()
    c.execute("UPDATE users SET pw=?, must_change=1 WHERE id=?", (A.hash_pw(temp), t["id"]))
    A.kill_sessions(c, t["id"])
    audit(c, "إعادة تعيين كلمة مرور موظف", f"{t['username']} ↔ {e['number']}")
    c.commit()
    return {"username": t["username"], "temporary_password": temp}


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int


@router.post("/api/hr/employees/{eid}/link-user")
def api_link_user(eid: int, b: LinkIn, u=Depends(act_as("users"))):
    """Administrator: attach an existing staff login (an HR officer, a finance user…) to the person's file so he also has his own portal."""
    c = db()
    if "hr" not in u["perms"]:
        raise HTTPException(403, "ليست لديك صلاحية لهذا الإجراء")
    e = employee(c, eid)
    t = one(c, "SELECT id, username, employee_id FROM users WHERE id=?", (b.user_id,), "المستخدم غير موجود")
    if t["employee_id"] and t["employee_id"] != eid:
        raise HTTPException(409, "المستخدم مرتبط بملف موظف آخر")
    if c.execute("SELECT 1 FROM users WHERE employee_id=? AND id!=?", (eid, b.user_id)).fetchone():
        raise HTTPException(409, "الملف مرتبط بحساب آخر")
    c.execute("UPDATE users SET employee_id=? WHERE id=?", (eid, b.user_id))
    audit(c, "ربط حساب بملف موظف", f"{t['username']} ↔ {e['number']}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- documents & expiry
def level_of(days: int) -> str:
    return "expired" if days < 0 else "critical" if days <= ALERT_DAYS[1] else "soon" if days <= ALERT_DAYS[0] else "ok"


def documents_of(c, eid: int, as_of: dt.date | None = None) -> list[dict]:
    as_of = as_of or today()
    out = rows(c.execute("SELECT * FROM employee_documents WHERE employee_id=? ORDER BY kind, id", (eid,)))
    for d in out:
        d["number"] = pii.dec(d["number"])
        d["kind_label"] = DOC_KINDS.get(d["kind"], d["kind"])
        d["days_left"] = (pdate(d["expires"]) - as_of).days if d["expires"] else None
        d["level"] = level_of(d["days_left"]) if d["days_left"] is not None else None
    return out


def expiry_items(c, as_of: dt.date, horizon: int = 90) -> list[dict]:
    """Everything that ends within `horizon` days (or already has), across the people on the payroll: the latest document of each kind per person (an old, replaced
    document does not keep alerting), the end of a fixed contract and the end of probation."""
    items: list[dict] = []
    latest: dict = {}
    for r in c.execute("""SELECT x.id doc_id, x.employee_id, x.kind, x.expires, e.number, e.name FROM employee_documents x JOIN employees e ON e.id=x.employee_id
                          WHERE x.expires IS NOT NULL AND x.expires!='' AND e.status!='terminated'"""):
        k = (r["employee_id"], r["kind"])
        if k not in latest or r["expires"] > latest[k]["expires"]:
            latest[k] = dict(r)
    for r in latest.values():
        days = (pdate(r["expires"]) - as_of).days
        if days <= horizon:
            items.append({"source": "document", "ref_id": r["doc_id"], "employee_id": r["employee_id"], "number": r["number"], "name": r["name"], "kind": r["kind"],
                          "label": DOC_KINDS.get(r["kind"], r["kind"]), "date": r["expires"], "days_left": days, "level": level_of(days)})
    for r in c.execute("SELECT id, number, name, contract_type, contract_end, probation_end FROM employees WHERE status!='terminated'"):
        if r["contract_type"] == "fixed" and r["contract_end"]:
            days = (pdate(r["contract_end"]) - as_of).days
            if days <= horizon:
                items.append({"source": "contract", "ref_id": r["id"], "employee_id": r["id"], "number": r["number"], "name": r["name"], "kind": "contract_end", "label": "نهاية العقد",
                              "date": r["contract_end"], "days_left": days, "level": level_of(days)})
        if r["probation_end"]:
            days = (pdate(r["probation_end"]) - as_of).days
            if 0 <= days <= ALERT_DAYS[1]:
                items.append({"source": "probation", "ref_id": r["id"], "employee_id": r["id"], "number": r["number"], "name": r["name"], "kind": "probation_end", "label": "نهاية فترة التجربة",
                              "date": r["probation_end"], "days_left": days, "level": level_of(days)})
    return sorted(items, key=lambda i: (i["days_left"], i["name"]))


@router.get("/api/hr/alerts")
def api_alerts(days: int = Query(90, ge=1, le=365), _=Depends(need("hr"))):
    return expiry_items(db(), today(), days)


@router.get("/api/hr/employees/{eid}/documents")
def api_docs(eid: int, u=Depends(need("hr"))):
    c = db()
    employee(c, eid)
    return documents_of(c, eid)


class DocIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["passport", "resident_card", "work_permit", "labour_card", "health_insurance", "contract", "certificate", "other"]
    number: str = Field(default="", max_length=60)
    issued: str = ""
    expires: str = ""
    document_id: int | None = None
    note: str = Field(default="", max_length=200)


def _doc_scan(c, eid: int, document_id) -> None:
    if document_id is not None:
        d = c.execute("SELECT ref_type, ref_id FROM documents WHERE id=?", (document_id,)).fetchone()
        if not d or d["ref_type"] != "employee" or d["ref_id"] != eid:
            raise HTTPException(400, "الملف المرفوع غير تابع لهذا الموظف — ارفعه أولًا من ملف الموظف")


@router.post("/api/hr/employees/{eid}/documents")
def api_doc_add(eid: int, b: DocIn, u=Depends(act_as("hr"))):
    c = db()
    e = employee(c, eid)
    iss, exp = opt_date(b.issued, "تاريخ الإصدار"), opt_date(b.expires, "تاريخ الانتهاء")
    if iss and exp and exp < iss:
        raise HTTPException(400, "تاريخ الانتهاء قبل الإصدار")
    if b.kind in ("passport", "resident_card", "work_permit", "labour_card", "health_insurance") and not exp:
        raise HTTPException(400, "هذه الوثيقة تلزمها نهاية صلاحية")
    _doc_scan(c, eid, b.document_id)
    did = c.execute("INSERT INTO employee_documents(employee_id,kind,number,issued,expires,document_id,note,created_by) VALUES(?,?,?,?,?,?,?,?)",
                    (eid, b.kind, pii.enc(b.number.strip()) if b.number else None, iss, exp, b.document_id, b.note or None, u["name"])).lastrowid
    audit(c, "وثيقة موظف", f"{e['number']} · {DOC_KINDS[b.kind]}" + (f" · تنتهي {exp}" if exp else ""))
    c.commit()
    return {"id": did}


@router.patch("/api/hr/documents/{did}")
def api_doc_edit(did: int, b: DocIn, u=Depends(act_as("hr"))):
    c = db()
    d = dict(one(c, "SELECT * FROM employee_documents WHERE id=?", (did,), "الوثيقة غير موجودة"))
    iss, exp = opt_date(b.issued, "تاريخ الإصدار"), opt_date(b.expires, "تاريخ الانتهاء")
    if iss and exp and exp < iss:
        raise HTTPException(400, "تاريخ الانتهاء قبل الإصدار")
    _doc_scan(c, d["employee_id"], b.document_id)
    c.execute("UPDATE employee_documents SET kind=?, number=?, issued=?, expires=?, document_id=?, note=? WHERE id=?",
              (b.kind, pii.enc(b.number.strip()) if b.number else None, iss, exp, b.document_id, b.note or None, did))
    audit(c, "تعديل وثيقة موظف", f"#{did} · {DOC_KINDS[b.kind]}")
    c.commit()
    return {"ok": True}


@router.delete("/api/hr/documents/{did}")
def api_doc_del(did: int, u=Depends(act_as("hr"))):
    c = db()
    d = dict(one(c, "SELECT * FROM employee_documents WHERE id=?", (did,), "الوثيقة غير موجودة"))
    c.execute("DELETE FROM employee_documents WHERE id=?", (did,))
    audit(c, "حذف سجل وثيقة موظف", f"#{did} · {DOC_KINDS.get(d['kind'], d['kind'])} (الملف المرفوع يبقى في المستندات)")
    c.commit()
    return {"ok": True}


def alerts_run(c) -> int:
    """Queue one notification per document / contract / probation the first time it crosses 90 days, 30 days, or its end — never twice for the same expiry date."""
    n = 0
    for i in expiry_items(c, today()):
        step = "0" if i["days_left"] < 0 else "30" if i["days_left"] <= 30 else "90"
        title = f"{i['label']}: {i['name']} ({i['number']})"
        body = ("انتهت في " if i["days_left"] < 0 else "تنتهي في ") + i["date"] + (f" — بعد {i['days_left']} يومًا" if i["days_left"] >= 0 else f" — منذ {-i['days_left']} يومًا")
        cur = c.execute("INSERT OR IGNORE INTO notifications(audience,customer_id,channel,title,body,status,created,dedupe) VALUES(?,?,?,?,?,?,?,?)",
                        ("hr", None, "app", title, body, "queued", now_s(), f"hrexp:{i['source']}:{i['ref_id']}:{i['date']}:{step}"))
        n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return n


def alerts_due_all() -> int:
    """Background tick: once a day per tenant whose HR module is on."""
    n = 0
    for tn in tenants():
        tok = TENANT.set(tn)
        try:
            c = connect()
            try:
                from . import registry
                if "hr" not in registry.enabled_modules(c) or not c.has_table("employees"):
                    continue
                last = c.execute("SELECT v FROM settings WHERE k='hr:alerts_last_run'").fetchone()
                if not last or last["v"][:10] < today().isoformat():
                    n += alerts_run(c)
                    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ("hr:alerts_last_run", now_s()))
                    c.commit()
            finally:
                c.close()
        finally:
            TENANT.reset(tok)
    return n
