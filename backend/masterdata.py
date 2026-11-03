"""مبانيك 0.31.0 — البيانات الأساسية من الواجهة: المشروع والمبنى والوحدة والعميل والأرض والترخيص والمقاول وعقد المقاول ومهمة الجدول.

التصميم والجدول الكامل في docs/DESIGN-master-data-forms.md. القواعد المشتركة:
* لكل كيان: إنشاء · تعديل (PATCH صريح عبر backend/partial.py) · إيقاف واستعادة (`active`) — لا حذف فعليًا. الموقوف يخرج من القوائم الجارية ويُغلق أمام النشاط الجديد ويبقى تاريخه في التقارير.
* المجهول يبقى NULL: لا قيم افتراضية تُختلق لحقول اختيارية (المطوّر ذو البيانات الحقيقية).
* سلامة مالية: لا حقل لحالة الوحدة (يحكمها مسار الحجز)، وسعر وحدة عليها حجز/عقد نشط يتغيّر بسجل موثَّق فقط (`unit_price_changes` دفتر لا يُعدَّل)،
  ولا إيقاف لمشروع فيه حجوزات نشطة أو عقود ساري أو مستخلصات معلّقة، ولا مسار هنا يكتب في الأقساط والدفعات.
* كل نقطة كتابة: صلاحية في الخادم، نموذج Pydantic بحدود، سطر تدقيق واحد، اتصال واحد، commit واحد.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import need, need_any
from .common import act_as, audit, db, now_s, rows
from .modules import KycIn, apply_kyc, create_customer, one
from .partial import Col, diff

router = APIRouter()

KINDS = {"tower": "برج", "villa": "فلل", "land": "أرض"}
USES = {"residential": "سكني", "commercial": "تجاري", "office": "مكتبي", "warehouse": "مخزن", "land": "أرض"}
PHONE_RE = re.compile(r"[0-9+ ()-]{6,24}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
ACTIVE = Col("الحالة", required=True, kind="bool")
# الحجز النشط: معلّق، أو مؤكد لم يُسلَّم بعد (بعد التسليم يبقى سجلًّا تاريخيًا لا يمنع الإيقاف)
ACTIVE_BOOKING = "(b.status='pending' OR (b.status='confirmed' AND b.handed_over IS NULL))"
ACTIVE_LEASE = "l.status IN ('active','draft')"


# ----------------------------------------------------------------------------------------------------- common
def _is_active(r) -> bool:
    return r.get("active") is None or bool(r["active"])


def _lookup(c, table: str, rid: int, msg: str) -> dict:
    return dict(one(c, f"SELECT * FROM {table} WHERE id=?", (rid,), msg))


def _dup(c, sql: str, args: tuple, msg: str) -> None:
    if c.execute(sql, args).fetchone():
        raise HTTPException(409, msg)


def _set_active(c, table: str, rid: int, on: bool, cur: dict, action: str, subject: str) -> dict:
    """الإيقاف والاستعادة: `active` وحده، بسطر تدقيق واحد، ولا شيء إن كان الكيان في الحالة المطلوبة أصلًا."""
    cur = {**cur, "active": 1 if _is_active(cur) else 0}
    return diff(cur, {"active": on}, {"active": ACTIVE}).commit(c, table, rid, action, subject)


def _count(c, sql: str, args: tuple) -> int:
    return c.execute(sql, args).fetchone()[0]


def _need_open_project(c, pid: int) -> dict:
    p = _lookup(c, "projects", pid, "المشروع غير موجود")
    if not _is_active(p):
        raise HTTPException(409, "المشروع موقوف — استعده أولًا")
    return p


def assert_sellable(c, unit_id: int) -> None:
    """مسارات النشاط الجديد (حجز، عرض سعر، عقد إيجار) ترفض وحدة موقوفة أو في مشروع موقوف — تُستدعى من تلك المسارات."""
    r = c.execute("SELECT u.active ua, p.active pa FROM units u JOIN projects p ON p.id=u.project_id WHERE u.id=?", (unit_id,)).fetchone()
    if r and r["ua"] is not None and not r["ua"]:
        raise HTTPException(409, "الوحدة موقوفة — لا نشاط جديد عليها")
    if r and r["pa"] is not None and not r["pa"]:
        raise HTTPException(409, "مشروع الوحدة موقوف — لا نشاط جديد عليه")


# ====================================================================================================== المشروع
class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=12)
    name: str = Field(min_length=2, max_length=120)
    location: str = Field(default="", max_length=120)
    kind: Literal["tower", "villa", "land"]
    build_pct: float = Field(default=0, ge=0, le=100)
    planned_monthly_sales: float = Field(default=0, ge=0, le=10000)
    handover: dt.date | None = None
    land_id: int | None = None
    completed: bool = False


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    kind: str | None = None
    build_pct: float | None = Field(default=None, ge=0, le=100)
    planned_monthly_sales: float | None = Field(default=None, ge=0, le=10000)
    handover: dt.date | None = None
    land_id: int | None = None
    completed: bool | None = None


PROJECT_COLS = {
    "name": Col("اسم المشروع", required=True, check=lambda v: None if len(v) >= 2 else "اسم المشروع حرفان على الأقل"),
    "location": Col("الموقع"),
    "kind": Col("النوع", required=True, check=lambda v: None if v in KINDS else "نوع المشروع: برج أو فلل أو أرض"),
    "build_pct": Col("نسبة الإنجاز ٪", required=True, kind="num"),
    "planned_monthly_sales": Col("المبيعات الشهرية المخططة", required=True, kind="num"),
    "handover": Col("موعد التسليم", kind="date"),
    "land_id": Col("الأرض", kind="num"),
    "completed": Col("مكتمل", required=True, kind="bool"),
}


def _clean_code(code: str, what: str) -> str:
    code = (code or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,11}", code):
        raise HTTPException(400, f"رمز {what}: حروف إنجليزية وأرقام وشرطة، من حرفين إلى 12، يبدأ بحرف أو رقم")
    return code


@router.post("/api/projects")
def project_create(b: ProjectIn, u=Depends(act_as("masterdata"))):
    c = db()
    code = _clean_code(b.code, "المشروع")
    _dup(c, "SELECT 1 FROM projects WHERE code=?", (code,), f"رمز المشروع «{code}» مستخدم")
    if b.land_id is not None:
        one(c, "SELECT 1 FROM lands WHERE id=?", (b.land_id,), "الأرض غير موجودة")
    pid = c.execute("INSERT INTO projects(code,name,location,kind,build_pct,planned_monthly_sales,handover,land_id,completed) VALUES(?,?,?,?,?,?,?,?,?)",
                    (code, b.name.strip(), b.location.strip() or None, b.kind, b.build_pct, b.planned_monthly_sales,
                     b.handover.isoformat() if b.handover else None, b.land_id, int(b.completed))).lastrowid
    audit(c, "مشروع جديد", f"{code} · {b.name.strip()} · {KINDS[b.kind]}")
    c.commit()
    return {"id": pid, "code": code}


@router.patch("/api/projects/{pid}")
def project_edit(pid: int, b: ProjectPatch, u=Depends(act_as("masterdata"))):
    c = db()
    cur = _lookup(c, "projects", pid, "المشروع غير موجود")
    p = diff(cur, b, PROJECT_COLS)
    if "kind" in p.changed and _count(c, "SELECT COUNT(*) FROM units WHERE project_id=?", (pid,)):
        raise HTTPException(409, "لا يتغيّر نوع المشروع بعد إنشاء وحداته")
    if "land_id" in p.changed and p.value("land_id") is not None:
        one(c, "SELECT 1 FROM lands WHERE id=?", (p.value("land_id"),), "الأرض غير موجودة")
    return p.commit(c, "projects", pid, "تعديل مشروع", f"{cur['code']} · {cur['name']}")


def _project_blockers(c, pid: int) -> list[str]:
    out = []
    n = _count(c, f"SELECT COUNT(*) FROM bookings b JOIN units u ON u.id=b.unit_id WHERE u.project_id=? AND {ACTIVE_BOOKING}", (pid,))
    if n:
        out.append(f"{n} حجز نشط")
    n = _count(c, f"SELECT COUNT(*) FROM leases l JOIN units u ON u.id=l.unit_id WHERE u.project_id=? AND {ACTIVE_LEASE}", (pid,))
    if n:
        out.append(f"{n} عقد إيجار ساري أو مسودة")
    n = _count(c, "SELECT COUNT(*) FROM ipcs WHERE project_id=? AND status='pending'", (pid,))
    if n:
        out.append(f"{n} مستخلص معلّق")
    return out


@router.post("/api/projects/{pid}/archive")
def project_archive(pid: int, u=Depends(act_as("masterdata"))):
    c = db()
    cur = _lookup(c, "projects", pid, "المشروع غير موجود")
    why = _project_blockers(c, pid)
    if why and _is_active(cur):
        raise HTTPException(409, "لا يُوقف مشروع فيه " + "، ".join(why) + " — أنهِها أولًا")
    return _set_active(c, "projects", pid, False, cur, "إيقاف مشروع", f"{cur['code']} · {cur['name']}")


@router.post("/api/projects/{pid}/restore")
def project_restore(pid: int, u=Depends(act_as("masterdata"))):
    c = db()
    cur = _lookup(c, "projects", pid, "المشروع غير موجود")
    return _set_active(c, "projects", pid, True, cur, "استعادة مشروع", f"{cur['code']} · {cur['name']}")


# ====================================================================================================== المبنى
class BuildingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    floors: int | None = Field(default=None, ge=1, le=200)
    notes: str = Field(default="", max_length=200)


class BuildingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=40)
    floors: int | None = Field(default=None, ge=1, le=200)
    notes: str | None = Field(default=None, max_length=200)


BUILDING_COLS = {"name": Col("اسم المبنى", required=True), "floors": Col("عدد الطوابق", kind="num"), "notes": Col("ملاحظات")}


def _sync_buildings(c, pid: int) -> None:
    """يملأ سجل المباني من أسماء الوحدات القائمة (بيانات أُنشئت قبل 0.31.0). آمن للتكرار ومتزامن: الفريد (المشروع، الاسم) يمنع التكرار؛ التطبيق يكتبه لا الترحيل لأن مالك القاعدة تسري عليه سياسة الصف."""
    c.execute("""INSERT OR IGNORE INTO buildings(project_id,name) SELECT DISTINCT project_id, building FROM units
                 WHERE project_id=? AND building IS NOT NULL AND building<>''""", (pid,))
    c.commit()     # دائمًا: في SQLite يفتح الإدراج معاملة كتابة ولو لم يُدرج شيئًا فيبقى قفلها حتى نهاية الطلب ويصطدم به الطلب التالي


@router.get("/api/projects/{pid}/buildings")
def buildings(pid: int, archived: int = 0, _=Depends(need_any("inventory", "masterdata"))):
    c = db()
    one(c, "SELECT 1 FROM projects WHERE id=?", (pid,), "المشروع غير موجود")
    _sync_buildings(c, pid)
    return rows(c.execute("""SELECT bd.*, (SELECT COUNT(*) FROM units u WHERE u.project_id=bd.project_id AND u.building=bd.name AND COALESCE(u.active,1)=1) units
                             FROM buildings bd WHERE bd.project_id=? AND (?=1 OR COALESCE(bd.active,1)=1) ORDER BY bd.name""", (pid, int(archived))))


@router.post("/api/projects/{pid}/buildings")
def building_create(pid: int, b: BuildingIn, u=Depends(act_as("masterdata"))):
    c = db()
    p = _need_open_project(c, pid)
    name = b.name.strip()
    _sync_buildings(c, pid)
    _dup(c, "SELECT 1 FROM buildings WHERE project_id=? AND name=?", (pid, name), f"المبنى «{name}» موجود في المشروع")
    bid = c.execute("INSERT INTO buildings(project_id,name,floors,notes,created_by) VALUES(?,?,?,?,?)", (pid, name, b.floors, b.notes.strip() or None, u["name"])).lastrowid
    audit(c, "مبنى جديد", f"{p['code']} · {name}")
    c.commit()
    return {"id": bid}


@router.patch("/api/buildings/{bid}")
def building_edit(bid: int, b: BuildingPatch, u=Depends(act_as("masterdata"))):
    c = db()
    cur = _lookup(c, "buildings", bid, "المبنى غير موجود")
    p = diff(cur, b, BUILDING_COLS)
    if "name" in p.changed:
        new = p.value("name")
        _dup(c, "SELECT 1 FROM buildings WHERE project_id=? AND name=? AND id<>?", (cur["project_id"], new, bid), f"المبنى «{new}» موجود في المشروع")
        # إعادة التسمية تحمل وحداته ومخططاته معها في المعاملة نفسها (الربط بالاسم)
        c.execute("UPDATE units SET building=? WHERE project_id=? AND building=?", (new, cur["project_id"], cur["name"]))
        c.execute("UPDATE plans SET building=? WHERE project_id=? AND building=?", (new, cur["project_id"], cur["name"]))
    return p.commit(c, "buildings", bid, "تعديل مبنى", cur["name"])


@router.post("/api/buildings/{bid}/archive")
def building_archive(bid: int, u=Depends(act_as("masterdata"))):
    c = db()
    cur = _lookup(c, "buildings", bid, "المبنى غير موجود")
    n = _count(c, "SELECT COUNT(*) FROM units WHERE project_id=? AND building=? AND COALESCE(active,1)=1", (cur["project_id"], cur["name"]))
    if n and _is_active(cur):
        raise HTTPException(409, f"في المبنى {n} وحدة فعّالة — أوقفها أو انقلها أولًا")
    return _set_active(c, "buildings", bid, False, cur, "إيقاف مبنى", cur["name"])


@router.post("/api/buildings/{bid}/restore")
def building_restore(bid: int, u=Depends(act_as("masterdata"))):
    c = db()
    cur = _lookup(c, "buildings", bid, "المبنى غير موجود")
    return _set_active(c, "buildings", bid, True, cur, "استعادة مبنى", cur["name"])


# ====================================================================================================== الوحدة
class UnitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: int
    code: str = Field(min_length=2, max_length=30)
    building: str | None = Field(default=None, max_length=40)
    floor: int | None = Field(default=None, ge=-5, le=200)
    pos: int | None = Field(default=None, ge=1, le=500)
    type: str | None = Field(default=None, max_length=60)
    area: float | None = Field(default=None, gt=0, le=1_000_000)
    view: str | None = Field(default=None, max_length=40)
    price: float | None = Field(default=None, ge=0, le=1_000_000_000)
    use: Literal["residential", "commercial", "office", "warehouse", "land"] = "residential"


class UnitEdit(BaseModel):
    """الحالة ليست حقلًا: تُرسَل هنا فقط لنردّ عليها بسبب الرفض بدل 422 عام."""
    model_config = ConfigDict(extra="forbid")
    building: str | None = Field(default=None, max_length=40)
    floor: int | None = Field(default=None, ge=-5, le=200)
    pos: int | None = Field(default=None, ge=1, le=500)
    type: str | None = Field(default=None, max_length=60)
    area: float | None = Field(default=None, gt=0, le=1_000_000)
    view: str | None = Field(default=None, max_length=40)
    price: float | None = Field(default=None, ge=0, le=1_000_000_000)
    use: str | None = None
    status: str | None = None


UNIT_EDIT_COLS = {
    "building": Col("المبنى"), "floor": Col("الطابق", kind="num"), "pos": Col("الترتيب في الطابق", kind="num"), "type": Col("النوع"),
    "area": Col("المساحة م²", kind="num"), "view": Col("الإطلالة"), "price": Col("السعر", kind="num"),
    "use": Col("الاستخدام", required=True, check=lambda v: None if v in USES else "الاستخدام غير معروف"),
}


def _unit_activity(c, uid: int) -> dict:
    return {"bookings": _count(c, f"SELECT COUNT(*) FROM bookings b WHERE b.unit_id=? AND {ACTIVE_BOOKING}", (uid,)),
            "leases": _count(c, f"SELECT COUNT(*) FROM leases l WHERE l.unit_id=? AND {ACTIVE_LEASE}", (uid,))}


def _price_row(c, uid: int, old, new, reason: str, basis: str, by: str) -> None:
    c.execute("INSERT INTO unit_price_changes(unit_id,old_price,new_price,reason,basis,changed_by,changed_at) VALUES(?,?,?,?,?,?,?)", (uid, old, new, reason, basis, by, now_s()))


def _ensure_building(c, pid: int, name: str | None, by: str) -> None:
    """وحدة في مبنى جديد تُنشئ المبنى في سجل المشروع (الاسم نفسه يبقى في `units.building`)."""
    if name and name.strip() and not c.execute("SELECT 1 FROM buildings WHERE project_id=? AND name=?", (pid, name.strip())).fetchone():
        c.execute("INSERT INTO buildings(project_id,name,created_by) VALUES(?,?,?)", (pid, name.strip(), by))


@router.post("/api/units")
def unit_create(b: UnitIn, u=Depends(act_as("masterdata"))):
    c = db()
    p = _need_open_project(c, b.project_id)
    code = (b.code or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,29}", code):
        raise HTTPException(400, "رمز الوحدة: حروف إنجليزية وأرقام وشرطة، من حرفين إلى 30")
    _dup(c, "SELECT 1 FROM units WHERE code=?", (code,), f"رمز الوحدة «{code}» مستخدم")
    building = (b.building or "").strip() or None
    _ensure_building(c, b.project_id, building, u["name"])
    uid = c.execute("INSERT INTO units(project_id,code,building,floor,pos,type,area,view,price,status,use,retained) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (b.project_id, code, building, b.floor, b.pos, (b.type or "").strip() or None, b.area, (b.view or "").strip() or None, b.price, "a", b.use, 0)).lastrowid
    audit(c, "وحدة جديدة", f"{code} · {p['code']}" + (f" · {b.price:,.0f} ر.ع" if b.price is not None else ""))
    c.commit()
    return {"id": uid, "code": code}


@router.patch("/api/units/{uid}")
def unit_edit(uid: int, b: UnitEdit, u=Depends(act_as("masterdata"))):
    c = db()
    cur = _lookup(c, "units", uid, "الوحدة غير موجودة")
    if "status" in b.model_fields_set:
        raise HTTPException(400, "حالة الوحدة (متاحة/محجوزة/مباعة) يحكمها مسار الحجز ولا تُعدَّل يدويًا")
    p = diff(cur, b, UNIT_EDIT_COLS)
    act = _unit_activity(c, uid)
    if "price" in p.changed and (act["bookings"] or act["leases"]):
        raise HTTPException(409, "على الوحدة حجز أو عقد نشط — غيّر سعرها بـ«تغيير سعر موثَّق» (سبب إلزامي) لا بالتعديل المباشر")
    if "use" in p.changed and act["leases"]:
        raise HTTPException(409, "على الوحدة عقد إيجار نشط — لا يتغيّر استخدامها الآن")
    if "building" in p.changed and p.value("building"):
        _ensure_building(c, cur["project_id"], p.value("building"), u["name"])
    if "price" in p.changed:
        _price_row(c, uid, cur["price"], p.value("price"), "تعديل مباشر قبل أي حجز أو عقد", "free", u["name"])
    return p.commit(c, "units", uid, "تعديل وحدة", cur["code"])


class PriceChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: float = Field(ge=0, le=1_000_000_000)
    reason: str = Field(min_length=5, max_length=300)


@router.post("/api/units/{uid}/price")
def unit_price_change(uid: int, b: PriceChangeIn, u=Depends(act_as("decide"))):
    """تغيير سعر موثَّق: سبب إلزامي وصلاحية القرار؛ يغيّر سعر القائمة فقط — سعر الحجز المتعاقد عليه وأقساطه لا تُمس."""
    c = db()
    cur = _lookup(c, "units", uid, "الوحدة غير موجودة")
    if cur["price"] is not None and abs(float(cur["price"]) - b.price) < 0.0005:
        return {"ok": True, "changed": [], "changes": []}
    act = _unit_activity(c, uid)
    basis = "booking" if act["bookings"] else "lease" if act["leases"] else "free"
    _price_row(c, uid, cur["price"], b.price, b.reason.strip(), basis, u["name"])
    c.execute("UPDATE units SET price=? WHERE id=?", (b.price, uid))
    was = "بلا" if cur["price"] is None else f"{cur['price']:,.0f}"
    audit(c, "تغيير سعر موثَّق", f"{cur['code']} · {was} ⟵ {b.price:,.0f} ر.ع · {b.reason.strip()}")
    c.commit()
    return {"ok": True, "changed": ["price"], "changes": [{"field": "price", "label": "السعر", "old": cur["price"], "new": b.price}], "basis": basis}


@router.get("/api/units/{uid}/price-changes")
def unit_price_history(uid: int, _=Depends(need_any("inventory", "masterdata"))):
    c = db()
    one(c, "SELECT 1 FROM units WHERE id=?", (uid,), "الوحدة غير موجودة")
    return rows(c.execute("SELECT * FROM unit_price_changes WHERE unit_id=? ORDER BY id DESC LIMIT 100", (uid,)))


@router.post("/api/units/{uid}/archive")
def unit_archive(uid: int, u=Depends(act_as("masterdata"))):
    c = db()
    cur = _lookup(c, "units", uid, "الوحدة غير موجودة")
    if _is_active(cur):
        act = _unit_activity(c, uid)
        if cur["status"] != "a":
            raise HTTPException(409, "الوحدة محجوزة أو مباعة — لا تُوقف")
        if act["bookings"] or act["leases"]:
            raise HTTPException(409, "على الوحدة حجز أو عقد نشط — لا تُوقف")
    return _set_active(c, "units", uid, False, cur, "إيقاف وحدة", cur["code"])


@router.post("/api/units/{uid}/restore")
def unit_restore(uid: int, u=Depends(act_as("masterdata"))):
    c = db()
    cur = _lookup(c, "units", uid, "الوحدة غير موجودة")
    _need_open_project(c, cur["project_id"])
    return _set_active(c, "units", uid, True, cur, "استعادة وحدة", cur["code"])


# ====================================================================================================== العميل
class CustomerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=24)
    email: str | None = Field(default=None, max_length=120)
    kyc: KycIn | None = None      # كتلة الهوية الاختيارية تمرّ بمنطق التحقق القائم نفسه (تشفير، فحص قوائم، موافقة)


class CustomerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=24)
    email: str | None = Field(default=None, max_length=120)


CUSTOMER_COLS = {
    "name": Col("الاسم", required=True, personal=True, check=lambda v: None if len(v) >= 2 else "الاسم حرفان على الأقل"),
    "phone": Col("الهاتف", personal=True, check=lambda v: None if PHONE_RE.fullmatch(v) else "الهاتف أرقام وعلامات + - ( ) فقط"),
    "email": Col("البريد", personal=True, check=lambda v: None if EMAIL_RE.fullmatch(v) else "صيغة البريد غير صحيحة"),
}


@router.get("/api/customers")
def customers(q: str = Query("", max_length=60), archived: int = 0, limit: int = Query(200, ge=1, le=500), _=Depends(need_any("book", "kyc"))):
    c = db()
    sql = """SELECT cu.id, cu.name, cu.phone, cu.email, cu.kyc_status, cu.created, COALESCE(cu.active,1) active,
             (SELECT COUNT(*) FROM bookings b WHERE b.customer_id=cu.id AND b.status!='cancelled') bookings FROM customers cu WHERE cu.erased_at IS NULL"""
    args: list = []
    if not archived:
        sql += " AND COALESCE(cu.active,1)=1"
    if q.strip():
        sql += " AND (cu.name LIKE ? OR cu.phone LIKE ?)"
        args += [f"%{q.strip()}%"] * 2
    return rows(c.execute(sql + " ORDER BY cu.id DESC LIMIT ?", (*args, limit)))


@router.post("/api/customers")
def customer_create(b: CustomerIn, u=Depends(act_as("book"))):
    c = db()
    phone = (b.phone or "").strip() or None
    email = (b.email or "").strip() or None
    if phone and not PHONE_RE.fullmatch(phone):
        raise HTTPException(400, "الهاتف أرقام وعلامات + - ( ) فقط")
    if email and not EMAIL_RE.fullmatch(email):
        raise HTTPException(400, "صيغة البريد غير صحيحة")
    if b.kyc is not None and "kyc" not in u["perms"]:
        raise HTTPException(403, "بيانات الهوية تحتاج صلاحية التحقق من الهوية")
    cid = create_customer(c, b.name.strip(), phone, email)
    res = apply_kyc(c, cid, b.kyc, u["name"]) if b.kyc is not None else None
    audit(c, "عميل جديد", f"عميل {cid}" + (f" · تحقق الهوية: {res['status']}" if res else ""))
    c.commit()
    return {"id": cid, "kyc": res}


@router.patch("/api/customers/{cid}")
def customer_edit(cid: int, b: CustomerPatch, u=Depends(act_as("book"))):
    c = db()
    cur = _lookup(c, "customers", cid, "العميل غير موجود")
    if cur.get("erased_at"):
        raise HTTPException(409, "أُخفيت هوية العميل بطلب خصوصية — لا يُعدَّل")
    return diff(cur, b, CUSTOMER_COLS).commit(c, "customers", cid, "تعديل عميل", f"عميل {cid}")


@router.post("/api/customers/{cid}/archive")
def customer_archive(cid: int, u=Depends(act_as("admin"))):
    c = db()
    cur = _lookup(c, "customers", cid, "العميل غير موجود")
    n = _count(c, f"SELECT COUNT(*) FROM bookings b WHERE b.customer_id=? AND {ACTIVE_BOOKING}", (cid,))
    if n and _is_active(cur):
        raise HTTPException(409, f"للعميل {n} حجز نشط — لا يُوقف")
    return _set_active(c, "customers", cid, False, cur, "إيقاف عميل", f"عميل {cid}")


@router.post("/api/customers/{cid}/restore")
def customer_restore(cid: int, u=Depends(act_as("admin"))):
    c = db()
    cur = _lookup(c, "customers", cid, "العميل غير موجود")
    return _set_active(c, "customers", cid, True, cur, "استعادة عميل", f"عميل {cid}")


# ====================================================================================================== الأرض
LAND_STATUS = ("تحت الدراسة", "قيد التفاوض", "تم الشراء — قيد التطوير", "مؤجَّلة", "مباعة")


class LandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    location: str = Field(default="", max_length=120)
    area: float | None = Field(default=None, gt=0, le=100_000_000)
    zoning: str = Field(default="", max_length=80)
    far: float | None = Field(default=None, gt=0, le=20)
    max_floors: int | None = Field(default=None, ge=1, le=200)
    price: float | None = Field(default=None, ge=0, le=10_000_000_000)
    status: str = Field(default="تحت الدراسة", max_length=60)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    notes: str = Field(default="", max_length=500)


class LandPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    area: float | None = Field(default=None, gt=0, le=100_000_000)
    zoning: str | None = Field(default=None, max_length=80)
    far: float | None = Field(default=None, gt=0, le=20)
    max_floors: int | None = Field(default=None, ge=1, le=200)
    price: float | None = Field(default=None, ge=0, le=10_000_000_000)
    status: str | None = Field(default=None, max_length=60)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    notes: str | None = Field(default=None, max_length=500)


LAND_COLS = {
    "name": Col("اسم الأرض", required=True, check=lambda v: None if len(v) >= 2 else "اسم الأرض حرفان على الأقل"),
    "location": Col("الموقع"), "area": Col("المساحة م²", kind="num"), "zoning": Col("الاستخدام المسموح"), "far": Col("معامل البناء", kind="num"),
    "max_floors": Col("أقصى طوابق", kind="num"), "price": Col("السعر المطلوب", kind="num"), "status": Col("الحالة", required=True),
    "lat": Col("خط العرض", kind="num"), "lng": Col("خط الطول", kind="num"), "notes": Col("ملاحظات"),
}


@router.post("/api/lands")
def land_create(b: LandIn, u=Depends(act_as("land"))):
    c = db()
    if (b.lat is None) != (b.lng is None):
        raise HTTPException(400, "الإحداثيات معًا أو بدونهما: أدخل خط العرض وخط الطول")
    _dup(c, "SELECT 1 FROM lands WHERE name=? AND COALESCE(location,'')=?", (b.name.strip(), b.location.strip()), "أرض بالاسم والموقع نفسيهما موجودة")
    lid = c.execute("INSERT INTO lands(name,location,area,zoning,far,max_floors,price,status,lat,lng,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (b.name.strip(), b.location.strip() or None, b.area, b.zoning.strip() or None, b.far, b.max_floors, b.price, b.status.strip() or "تحت الدراسة",
                     b.lat, b.lng, b.notes.strip() or None)).lastrowid
    audit(c, "أرض جديدة", b.name.strip())
    c.commit()
    return {"id": lid}


@router.patch("/api/lands/{lid}")
def land_edit(lid: int, b: LandPatch, u=Depends(act_as("land"))):
    c = db()
    cur = _lookup(c, "lands", lid, "الأرض غير موجودة")
    p = diff(cur, b, LAND_COLS)
    if (p.value("lat") is None) != (p.value("lng") is None):
        raise HTTPException(400, "الإحداثيات معًا أو بدونهما: أدخل خط العرض وخط الطول")
    return p.commit(c, "lands", lid, "تعديل أرض", cur["name"])


@router.post("/api/lands/{lid}/archive")
def land_archive(lid: int, u=Depends(act_as("land"))):
    c = db()
    cur = _lookup(c, "lands", lid, "الأرض غير موجودة")
    n = _count(c, "SELECT COUNT(*) FROM projects WHERE land_id=? AND COALESCE(active,1)=1", (lid,))
    if n and _is_active(cur):
        raise HTTPException(409, "الأرض مربوطة بمشروع فعّال — أوقف المشروع أو افصل الربط أولًا")
    return _set_active(c, "lands", lid, False, cur, "إيقاف أرض", cur["name"])


@router.post("/api/lands/{lid}/restore")
def land_restore(lid: int, u=Depends(act_as("land"))):
    c = db()
    cur = _lookup(c, "lands", lid, "الأرض غير موجودة")
    return _set_active(c, "lands", lid, True, cur, "استعادة أرض", cur["name"])


# ====================================================================================================== الترخيص (الإنشاء والإيقاف؛ تعديل الحالة والمرجع في modules.permit_update)
class PermitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: int
    authority: str = Field(min_length=2, max_length=80)
    kind: str = Field(min_length=2, max_length=80)
    ref: str = Field(default="", max_length=40)
    status: Literal["not_started", "submitted", "in_review", "issued", "rejected"] = "not_started"
    applied: dt.date | None = None
    issued: dt.date | None = None
    expires: dt.date | None = None
    notes: str = Field(default="", max_length=300)


@router.post("/api/permits")
def permit_create(b: PermitIn, u=Depends(act_as("permits"))):
    c = db()
    p = _need_open_project(c, b.project_id)
    if b.issued and b.applied and b.issued < b.applied:
        raise HTTPException(400, "تاريخ الصدور قبل تاريخ التقديم")
    if b.expires and (b.issued or b.applied) and b.expires < (b.issued or b.applied):
        raise HTTPException(400, "تاريخ الانتهاء قبل الصدور")
    _dup(c, "SELECT 1 FROM permits WHERE project_id=? AND authority=? AND kind=? AND COALESCE(active,1)=1", (b.project_id, b.authority.strip(), b.kind.strip()),
         "ترخيص بالجهة والنوع نفسيهما موجود في المشروع")
    pid = c.execute("INSERT INTO permits(project_id,authority,kind,ref,status,applied,issued,expires,notes) VALUES(?,?,?,?,?,?,?,?,?)",
                    (b.project_id, b.authority.strip(), b.kind.strip(), b.ref.strip() or None, b.status, b.applied.isoformat() if b.applied else None,
                     b.issued.isoformat() if b.issued else None, b.expires.isoformat() if b.expires else None, b.notes.strip() or None)).lastrowid
    audit(c, "ترخيص جديد", f"{p['code']} · {b.kind.strip()} ({b.authority.strip()})")
    c.commit()
    return {"id": pid}


@router.post("/api/permits/{pid}/archive")
def permit_archive(pid: int, u=Depends(act_as("permits"))):
    c = db()
    cur = _lookup(c, "permits", pid, "الترخيص غير موجود")
    return _set_active(c, "permits", pid, False, cur, "إيقاف ترخيص", f"{cur['kind']} ({cur['authority']})")


@router.post("/api/permits/{pid}/restore")
def permit_restore(pid: int, u=Depends(act_as("permits"))):
    c = db()
    cur = _lookup(c, "permits", pid, "الترخيص غير موجود")
    return _set_active(c, "permits", pid, True, cur, "استعادة ترخيص", f"{cur['kind']} ({cur['authority']})")


# ====================================================================================================== المقاول
class ContractorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    cr_number: str = Field(default="", max_length=30)
    phone: str = Field(default="", max_length=24)
    email: str = Field(default="", max_length=120)
    trade: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=300)


class ContractorPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=120)
    cr_number: str | None = Field(default=None, max_length=30)
    phone: str | None = Field(default=None, max_length=24)
    email: str | None = Field(default=None, max_length=120)
    trade: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=300)


CONTRACTOR_COLS = {
    "name": Col("اسم المقاول", required=True, check=lambda v: None if len(v) >= 2 else "اسم المقاول حرفان على الأقل"),
    "cr_number": Col("السجل التجاري"),
    "phone": Col("الهاتف", check=lambda v: None if PHONE_RE.fullmatch(v) else "الهاتف أرقام وعلامات + - ( ) فقط"),
    "email": Col("البريد", check=lambda v: None if EMAIL_RE.fullmatch(v) else "صيغة البريد غير صحيحة"),
    "trade": Col("التخصص"), "notes": Col("ملاحظات"),
}


@router.get("/api/contractors")
def contractors(archived: int = 0, _=Depends(need("construction"))):
    c = db()
    return rows(c.execute("""SELECT k.*, COALESCE(k.active,1) active_flag,
                             (SELECT COUNT(*) FROM contracts_c cc WHERE cc.contractor_id=k.id AND COALESCE(cc.active,1)=1) contracts
                             FROM contractors k WHERE (?=1 OR COALESCE(k.active,1)=1) ORDER BY k.name""", (int(archived),)))


@router.post("/api/contractors")
def contractor_create(b: ContractorIn, u=Depends(act_as("construction"))):
    c = db()
    cr = b.cr_number.strip() or None
    if cr:
        _dup(c, "SELECT 1 FROM contractors WHERE cr_number=?", (cr,), f"السجل التجاري «{cr}» مسجَّل لمقاول آخر")
    if b.phone.strip() and not PHONE_RE.fullmatch(b.phone.strip()):
        raise HTTPException(400, "الهاتف أرقام وعلامات + - ( ) فقط")
    if b.email.strip() and not EMAIL_RE.fullmatch(b.email.strip()):
        raise HTTPException(400, "صيغة البريد غير صحيحة")
    kid = c.execute("INSERT INTO contractors(name,cr_number,phone,email,trade,notes) VALUES(?,?,?,?,?,?)",
                    (b.name.strip(), cr, b.phone.strip() or None, b.email.strip() or None, b.trade.strip() or None, b.notes.strip() or None)).lastrowid
    audit(c, "مقاول جديد", b.name.strip())
    c.commit()
    return {"id": kid}


@router.patch("/api/contractors/{kid}")
def contractor_edit(kid: int, b: ContractorPatch, u=Depends(act_as("construction"))):
    c = db()
    cur = _lookup(c, "contractors", kid, "المقاول غير موجود")
    p = diff(cur, b, CONTRACTOR_COLS)
    if "cr_number" in p.changed and p.value("cr_number"):
        _dup(c, "SELECT 1 FROM contractors WHERE cr_number=? AND id<>?", (p.value("cr_number"), kid), f"السجل التجاري «{p.value('cr_number')}» مسجَّل لمقاول آخر")
    return p.commit(c, "contractors", kid, "تعديل مقاول", cur["name"])


@router.post("/api/contractors/{kid}/archive")
def contractor_archive(kid: int, u=Depends(act_as("construction"))):
    c = db()
    cur = _lookup(c, "contractors", kid, "المقاول غير موجود")
    n = _count(c, "SELECT COUNT(*) FROM contracts_c WHERE contractor_id=? AND COALESCE(active,1)=1", (kid,))
    if n and _is_active(cur):
        raise HTTPException(409, f"للمقاول {n} عقد فعّال — أنهِه أولًا")
    return _set_active(c, "contractors", kid, False, cur, "إيقاف مقاول", cur["name"])


@router.post("/api/contractors/{kid}/restore")
def contractor_restore(kid: int, u=Depends(act_as("construction"))):
    c = db()
    cur = _lookup(c, "contractors", kid, "المقاول غير موجود")
    return _set_active(c, "contractors", kid, True, cur, "استعادة مقاول", cur["name"])


# ====================================================================================================== عقد المقاول
class ContractIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: int
    contractor_id: int
    value: float = Field(gt=0, le=10_000_000_000)
    retention_pct: float = Field(default=0.1, ge=0, le=0.3)
    delay_penalty_per_day: float = Field(default=0, ge=0, le=1_000_000)
    start: dt.date
    finish: dt.date


class ContractPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contractor_id: int | None = None
    value: float | None = Field(default=None, gt=0, le=10_000_000_000)
    retention_pct: float | None = Field(default=None, ge=0, le=0.3)
    delay_penalty_per_day: float | None = Field(default=None, ge=0, le=1_000_000)
    start: dt.date | None = None
    finish: dt.date | None = None


CONTRACT_COLS = {
    "contractor_id": Col("المقاول", required=True, kind="num"), "value": Col("قيمة العقد", required=True, kind="num"),
    "retention_pct": Col("نسبة الاحتجاز", required=True, kind="num"), "delay_penalty_per_day": Col("غرامة التأخير اليومية", required=True, kind="num"),
    "start": Col("بداية العقد", required=True, kind="date"), "finish": Col("نهاية العقد", required=True, kind="date"),
}


def _certified(c, pid: int) -> float:
    return float(c.execute("SELECT COALESCE(SUM(COALESCE(approved_pct,0)/100.0*stage_value),0) FROM ipcs WHERE project_id=? AND status='approved'", (pid,)).fetchone()[0] or 0)


@router.post("/api/contractor-contracts")
def contract_create(b: ContractIn, u=Depends(act_as("construction"))):
    c = db()
    p = _need_open_project(c, b.project_id)
    k = _lookup(c, "contractors", b.contractor_id, "المقاول غير موجود")
    if not _is_active(k):
        raise HTTPException(409, "المقاول موقوف — استعده أولًا")
    if b.finish <= b.start:
        raise HTTPException(400, "نهاية العقد يجب أن تلي بدايته")
    _dup(c, "SELECT 1 FROM contracts_c WHERE project_id=? AND COALESCE(active,1)=1", (b.project_id,), "للمشروع عقد مقاول فعّال — أنهِه قبل إنشاء عقد جديد")
    cid = c.execute("INSERT INTO contracts_c(project_id,contractor_id,value,retention_pct,delay_penalty_per_day,start,finish) VALUES(?,?,?,?,?,?,?)",
                    (b.project_id, b.contractor_id, b.value, b.retention_pct, b.delay_penalty_per_day, b.start.isoformat(), b.finish.isoformat())).lastrowid
    audit(c, "عقد مقاول جديد", f"{p['code']} · {k['name']} · {b.value:,.0f} ر.ع")
    c.commit()
    return {"id": cid}


@router.patch("/api/contractor-contracts/{cid}")
def contract_edit(cid: int, b: ContractPatch, u=Depends(act_as("construction"))):
    c = db()
    cur = _lookup(c, "contracts_c", cid, "العقد غير موجود")
    if not _is_active(cur):
        raise HTTPException(409, "العقد منتهٍ — لا يُعدَّل")
    p = diff(cur, b, CONTRACT_COLS)
    if str(p.value("finish"))[:10] <= str(p.value("start"))[:10]:
        raise HTTPException(400, "نهاية العقد يجب أن تلي بدايته")
    if "value" in p.changed:
        floor = _certified(c, cur["project_id"])
        if float(p.value("value")) + 0.0005 < floor:
            raise HTTPException(409, f"قيمة العقد أقل من المعتمد من المستخلصات ({floor:,.0f} ر.ع)")
    if "contractor_id" in p.changed:
        if _count(c, "SELECT COUNT(*) FROM ipcs WHERE project_id=?", (cur["project_id"],)):
            raise HTTPException(409, "للمشروع مستخلصات باسم المقاول الحالي — لا يتغيّر المقاول")
        k = _lookup(c, "contractors", p.value("contractor_id"), "المقاول غير موجود")
        if not _is_active(k):
            raise HTTPException(409, "المقاول موقوف — استعده أولًا")
    return p.commit(c, "contracts_c", cid, "تعديل عقد مقاول", f"عقد {cid}")


@router.post("/api/contractor-contracts/{cid}/terminate")
def contract_terminate(cid: int, u=Depends(act_as("construction"))):
    c = db()
    cur = _lookup(c, "contracts_c", cid, "العقد غير موجود")
    n = _count(c, "SELECT COUNT(*) FROM ipcs WHERE project_id=? AND status='pending'", (cur["project_id"],))
    if n and _is_active(cur):
        raise HTTPException(409, f"للمشروع {n} مستخلص معلّق — اعتمده أو ارفضه قبل إنهاء العقد")
    return _set_active(c, "contracts_c", cid, False, cur, "إنهاء عقد مقاول", f"عقد {cid}")


@router.post("/api/contractor-contracts/{cid}/restore")
def contract_restore(cid: int, u=Depends(act_as("construction"))):
    c = db()
    cur = _lookup(c, "contracts_c", cid, "العقد غير موجود")
    _dup(c, "SELECT 1 FROM contracts_c WHERE project_id=? AND COALESCE(active,1)=1 AND id<>?", (cur["project_id"], cid), "للمشروع عقد مقاول فعّال آخر")
    return _set_active(c, "contracts_c", cid, True, cur, "استعادة عقد مقاول", f"عقد {cid}")


# ====================================================================================================== مهمة الجدول الزمني
class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: int
    name: str = Field(min_length=2, max_length=120)
    planned_start: dt.date
    planned_end: dt.date
    weight: float = Field(gt=0, le=1)
    pct: float = Field(default=0, ge=0, le=100)
    actual_start: dt.date | None = None
    actual_end: dt.date | None = None
    depends_on: int | None = None


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=120)
    planned_start: dt.date | None = None
    planned_end: dt.date | None = None
    weight: float | None = Field(default=None, gt=0, le=1)
    pct: float | None = Field(default=None, ge=0, le=100)
    actual_start: dt.date | None = None
    actual_end: dt.date | None = None
    depends_on: int | None = None


TASK_COLS = {
    "name": Col("اسم المهمة", required=True, check=lambda v: None if len(v) >= 2 else "اسم المهمة حرفان على الأقل"),
    "planned_start": Col("بداية مخططة", required=True, kind="date"), "planned_end": Col("نهاية مخططة", required=True, kind="date"),
    "weight": Col("الوزن", required=True, kind="num"), "pct": Col("نسبة الإنجاز ٪", required=True, kind="num"),
    "actual_start": Col("بداية فعلية", kind="date"), "actual_end": Col("نهاية فعلية", kind="date"), "depends_on": Col("تعتمد على", kind="num"),
}


def _task_checks(c, project_id: int, tid: int | None, v: dict) -> None:
    """قواعد المهمة بعد التعديل (`v` القيم الفعّالة): تواريخ مرتَّبة، وزن لا يتجاوز المتبقي، تبعية داخل المشروع بلا دورة."""
    if str(v["planned_end"])[:10] < str(v["planned_start"])[:10]:
        raise HTTPException(400, "النهاية المخططة قبل البداية")
    if v.get("actual_start") and v.get("actual_end") and str(v["actual_end"])[:10] < str(v["actual_start"])[:10]:
        raise HTTPException(400, "النهاية الفعلية قبل البداية الفعلية")
    others = float(c.execute("SELECT COALESCE(SUM(weight),0) FROM schedule_tasks WHERE project_id=? AND COALESCE(active,1)=1 AND id<>?", (project_id, tid or 0)).fetchone()[0] or 0)
    if others + float(v["weight"]) > 1.0005:
        raise HTTPException(409, f"مجموع أوزان المشروع يتجاوز 100٪ (المتبقي {max(0, 1 - others) * 100:.0f}٪)")
    dep = v.get("depends_on")
    if dep is not None:
        d = c.execute("SELECT project_id, depends_on FROM schedule_tasks WHERE id=?", (dep,)).fetchone()
        if not d or d["project_id"] != project_id:
            raise HTTPException(400, "المهمة التي تعتمد عليها غير موجودة في هذا المشروع")
        seen, cur = set(), dep
        while cur is not None:
            if cur == tid:
                raise HTTPException(409, "التبعية تصنع دورة: لا تعتمد مهمة على نفسها ولا على فروعها")
            if cur in seen:
                break
            seen.add(cur)
            r = c.execute("SELECT depends_on FROM schedule_tasks WHERE id=?", (cur,)).fetchone()
            cur = r["depends_on"] if r else None


@router.post("/api/schedule-tasks")
def task_create(b: TaskIn, u=Depends(act_as("construction"))):
    c = db()
    p = _need_open_project(c, b.project_id)
    _task_checks(c, b.project_id, None, {"planned_start": b.planned_start, "planned_end": b.planned_end, "weight": b.weight, "actual_start": b.actual_start,
                                         "actual_end": b.actual_end, "depends_on": b.depends_on})
    tid = c.execute("INSERT INTO schedule_tasks(project_id,name,planned_start,planned_end,actual_start,actual_end,pct,depends_on,weight) VALUES(?,?,?,?,?,?,?,?,?)",
                    (b.project_id, b.name.strip(), b.planned_start.isoformat(), b.planned_end.isoformat(), b.actual_start.isoformat() if b.actual_start else None,
                     b.actual_end.isoformat() if b.actual_end else None, b.pct, b.depends_on, b.weight)).lastrowid
    audit(c, "مهمة جدول جديدة", f"{p['code']} · {b.name.strip()}")
    c.commit()
    return {"id": tid}


@router.patch("/api/schedule-tasks/{tid}")
def task_edit(tid: int, b: TaskPatch, u=Depends(act_as("construction"))):
    c = db()
    cur = _lookup(c, "schedule_tasks", tid, "المهمة غير موجودة")
    if not _is_active(cur):
        raise HTTPException(409, "المهمة موقوفة — استعدها أولًا")
    p = diff(cur, b, TASK_COLS)
    if p.changed:
        _task_checks(c, cur["project_id"], tid, {k: p.value(k) for k in ("planned_start", "planned_end", "weight", "actual_start", "actual_end", "depends_on")})
    return p.commit(c, "schedule_tasks", tid, "تعديل مهمة جدول", cur["name"])


@router.post("/api/schedule-tasks/{tid}/archive")
def task_archive(tid: int, u=Depends(act_as("construction"))):
    c = db()
    cur = _lookup(c, "schedule_tasks", tid, "المهمة غير موجودة")
    n = _count(c, "SELECT COUNT(*) FROM schedule_tasks WHERE depends_on=? AND COALESCE(active,1)=1", (tid,))
    if n and _is_active(cur):
        raise HTTPException(409, f"{n} مهمة تعتمد عليها — أعد ربطها أو أوقفها أولًا")
    return _set_active(c, "schedule_tasks", tid, False, cur, "إيقاف مهمة جدول", cur["name"])


@router.post("/api/schedule-tasks/{tid}/restore")
def task_restore(tid: int, u=Depends(act_as("construction"))):
    c = db()
    cur = _lookup(c, "schedule_tasks", tid, "المهمة غير موجودة")
    _task_checks(c, cur["project_id"], tid, {k: cur[k] for k in ("planned_start", "planned_end", "weight", "actual_start", "actual_end", "depends_on")})
    return _set_active(c, "schedule_tasks", tid, True, cur, "استعادة مهمة جدول", cur["name"])
