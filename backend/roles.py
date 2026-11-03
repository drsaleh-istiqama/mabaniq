"""مبانيك 0.32.0 — الأدوار والصلاحيات كبيانات (التصميم: docs/DESIGN-roles-permissions.md).

مجموعة الصلاحيات تبقى في الكود (`auth.ALL_STAFF`) لأن الـendpoints تشير إليها؛ أما **ربط الأدوار بالصلاحيات** فصار جدولين لكل مطوّر (`roles`, `role_perms`) يُبذران من `auth.PERMS`
فلا يتغيّر سلوك أي مطوّر قائم، ويعدّلهما المدير من شاشة «الأدوار والصلاحيات». أدوار البوابات (عميل، وسيط، مستأجر، موظف، مدير عقاري خارجي) ثابتة.

* **الذاكرة المؤقتة** لكل مطوّر داخل العملية، **تُبطَل بعدّاد إصدار في القاعدة** (`settings['roles:ver']`) لا بمتغير في الذاكرة: كل طلب يقرأ العدّاد ويُعيد التحميل فقط إن اختلف؛
  فيسري تعديل دور على جلسات مستخدميه عند أول طلب بعده في أي عامل uvicorn (الصلاحيات تُحسب لكل طلب من الدور ولا تُخزَّن في الجلسة).
* **ترقية الكتالوج**: صلاحية جديدة في الكود (مثل `masterdata` في 0.31.0) تُمنح للأدوار المدمجة التي يشملها الكود مرة واحدة عند أول رؤية لها (`settings['roles:known']`)،
  فلا يُقفل مدير خارج ميزة جديدة، ولا يُعاد منح ما سحبه المدير عمدًا.
* **حواجز القفل الذاتي**: «مدير عام» لا يفقد `admin` و`users`؛ لا يُلغى آخر مدير نشط (إيقافًا أو تغيير دور أو سحب صلاحية)؛ لا يُحذف دور له مستخدمون؛ أدوار البوابات والمدمجة لا تُحذف.
"""
from __future__ import annotations

import json
import re
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import auth as A
from . import registry
from .auth import ALL_STAFF, PERMS, ROLES, need
from .common import act_as, audit, db, xlock
from .db import TENANT

router = APIRouter()

PORTAL_ROLES = frozenset({"customer", "broker", "lessee", "employee", "property_manager"})   # ثابتة: أدوار بوابات لا موظفين
VER_KEY, KNOWN_KEY = "roles:ver", "roles:known"
MUST_KEEP = {"admin": {"admin", "users"}}                                                  # «مدير عام» لا يفقد هاتين أبدًا

SECTIONS = [("general", "عام"), ("inventory", "المخزون والبيانات الأساسية"), ("sales", "المبيعات"), ("build", "الإنشاء"), ("after", "التسليم وخدمة العملاء"), ("finance", "المالية"),
            ("leasing", "الإيجارات"), ("accounting", "المحاسبة"), ("hr", "الموارد البشرية"), ("admin", "الحوكمة والإدارة")]
PERM_LABELS = {   # الصلاحية ⟵ (القسم، التسمية العربية): ما تعرضه المصفوفة
    "view": ("general", "لوحة القيادة والمؤشرات"), "reports": ("general", "التقارير الجاهزة ومنشئ التقارير"), "audit": ("general", "سجل التدقيق"),
    "docs": ("general", "المستندات والمخططات"), "notify": ("general", "الإشعارات"),
    "inventory": ("inventory", "عرض المخزون والتسعير"), "masterdata": ("inventory", "إدارة المشاريع والمباني والوحدات"), "land": ("inventory", "الأراضي ودراسات الجدوى"),
    "permits": ("inventory", "التراخيص والجهات الحكومية"),
    "leads": ("sales", "العملاء المحتملون والحملات"), "book": ("sales", "الحجز وعروض الأسعار والعملاء"), "kyc": ("sales", "التحقق من الهوية والعقود"),
    "brokers": ("sales", "الوسطاء والعمولات"), "market": ("sales", "السوق الثانوي"), "confirm": ("sales", "تأكيد البيع وتسجيل السداد"), "decide": ("sales", "قرارات التسعير والخصم"),
    "construction": ("build", "الإنشاء والجدول والمقاولون"), "approve_ipc": ("build", "اعتماد المستخلصات وأوامر التغيير"),
    "handover": ("after", "التسليم والعيوب والتمليك"), "oa": ("after", "اتحاد الملاك"), "service": ("after", "خدمة العملاء"),
    "finance": ("finance", "السيولة والتحصيل والضمان"), "invoices": ("finance", "الفواتير وضريبة القيمة المضافة"),
    "leasing": ("leasing", "الإيجارات والتحصيل والصيانة"), "leasing_approve": ("leasing", "اعتماد عمليات الإيجار"),
    "accounting": ("accounting", "المحاسبة والقيود"), "accounting_approve": ("accounting", "اعتماد القيود والحسابات"),
    "hr": ("hr", "ملفات الموظفين والإجازات والتوظيف"), "hr_manager": ("hr", "مدير مباشر: فريقه وطلباتهم"), "hr_self": ("hr", "بوابة الموظف: ملفه وإجازاته"),
    "hr_payroll": ("hr", "الرواتب والسلف ونهاية الخدمة"),
    "admin": ("admin", "الإدارة العامة والإعدادات"), "users": ("admin", "المستخدمون والأدوار"), "policies": ("admin", "قراءة السياسات والإقرار بها"),
    "policies_admin": ("admin", "إعداد السياسات واعتمادها"),
}
assert set(PERM_LABELS) == set(ALL_STAFF), set(PERM_LABELS) ^ set(ALL_STAFF)   # كل صلاحية موظف لها تسمية وقسم، ولا تسمية بلا صلاحية


# ----------------------------------------------------------------------------------------------------- التخزين والبذر
def _ver(c) -> str | None:
    r = c.execute("SELECT v FROM settings WHERE k=?", (VER_KEY,)).fetchone()
    return r["v"] if r else None


def _base() -> str:
    """بداية العدّاد من الوقت بالنانوثانية لا من 1: إعادة البذر بعد مسح الإعدادات (`/api/reset`) لا تعيد رقمًا سبق أن خزّنه عامل آخر (ABA)."""
    return str(time.time_ns())


def bump(c) -> None:
    """يرفع عدّاد الإصدار في المعاملة نفسها التي كتبت التعديل (زيادة ذرّية في القاعدة): العاملون الآخرون يرون الإصدار الجديد عند أول طلب."""
    c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)", (VER_KEY, _base()))
    c.execute("UPDATE settings SET v=CAST(CAST(v AS BIGINT)+1 AS TEXT) WHERE k=?", (VER_KEY,))


def _catalog() -> list[str]:
    return sorted(ALL_STAFF)


def seed(c) -> str:
    """يُدرج الأدوار المدمجة وصلاحياتها من الكود إن غابت، ويمنح ما أُضيف إلى الكتالوج بعد آخر مزامنة للأدوار المدمجة التي يشملها الكود. آمن للتكرار ولعدّة عمّال معًا. يلتزم ويعيد الإصدار."""
    existing = {r["code"] for r in c.execute("SELECT code FROM roles")}
    for code, label in ROLES.items():
        c.execute("INSERT OR IGNORE INTO roles(code,label,kind,builtin) VALUES(?,?,?,1)", (code, label, "portal" if code in PORTAL_ROLES else "staff"))
    row = c.execute("SELECT v FROM settings WHERE k=?", (KNOWN_KEY,)).fetchone()
    known = set(json.loads(row["v"])) if row else None
    new = set(_catalog()) - known if known is not None else set()
    for code, perms in PERMS.items():
        # أول بذر ودور مدمج جديد في الكود: كل صلاحياته من الكود؛ وإلا (ترقية) ما أُضيف إلى الكتالوج منذ آخر مزامنة فقط — فلا يُعاد منح ما سحبه المدير عمدًا
        for p in (perms if known is None or code not in existing else perms & new):
            c.execute("INSERT OR IGNORE INTO role_perms(role_code,perm) VALUES(?,?)", (code, p))
    if known is None or set(_catalog()) - known:
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (KNOWN_KEY, json.dumps(_catalog())))
    c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)", (VER_KEY, _base()))
    if known is not None and set(_catalog()) - known:
        bump(c)
    c.commit()
    return _ver(c) or _base()


def _load(c) -> dict[str, dict]:
    out = {r["code"]: {"code": r["code"], "label": r["label"], "kind": r["kind"], "builtin": bool(r["builtin"]), "perms": set()} for r in c.execute("SELECT code,label,kind,builtin FROM roles")}
    for r in c.execute("SELECT role_code, perm FROM role_perms"):
        if r["role_code"] in out:
            out[r["role_code"]]["perms"].add(r["perm"])
    for v in out.values():
        v["perms"] = frozenset(v["perms"])
    return out


class RolesCache:
    """نسخة لكل مطوّر داخل العملية؛ الصحة بمقارنة عدّاد القاعدة لا بوقت. نسخة ثانية = «عامل آخر» في الاختبارات."""

    def __init__(self):
        self._m: dict[str, tuple[str, dict]] = {}
        self._lock = threading.Lock()
        self.loads = 0

    def get(self, c) -> dict[str, dict]:
        tenant = TENANT.get()
        ver = _ver(c)
        ent = self._m.get(tenant)
        if ent and ver is not None and ent[0] == ver:
            return ent[1]
        if ver is None:
            ver = seed(c)
        data = _load(c)          # الإصدار يُقرأ قبل التحميل: تعديل بينهما يُعاد تحميله في الطلب التالي (محافظ، لا يفوّت شيئًا)
        with self._lock:
            self._m[tenant] = (ver, data)
            self.loads += 1
        return data

    def drop(self):
        with self._lock:
            self._m.clear()


CACHE = RolesCache()


def all_roles(c) -> dict[str, dict]:
    return CACHE.get(c)


def perms_for(c, code: str) -> frozenset:
    """صلاحيات الدور من القاعدة؛ دور غير معروف يعود إلى ما في الكود (وإلا لا شيء)."""
    r = CACHE.get(c).get(code)
    return r["perms"] if r else frozenset(PERMS.get(code, ()))


def label_for(c, code: str) -> str:
    r = CACHE.get(c).get(code)
    return r["label"] if r else ROLES.get(code, code)


def roles_with(c, perm: str) -> list[str]:
    return sorted(k for k, v in CACHE.get(c).items() if perm in v["perms"])


def staff_codes(c) -> list[str]:
    return [k for k, v in CACHE.get(c).items() if v["kind"] == "staff"]


def _sensitive() -> frozenset:
    """الصلاحيات التي لا يملكها بالافتراض إلا الأدوار ذات التحقق الثنائي الإلزامي: من يُمنحها يحمل حساسية تلك الأدوار فيلزمه تحققها (التحقق يتبع الصلاحية لا اسم الدور)."""
    by_2fa = set().union(*(PERMS[r] for r in A.TWO_FA_REQUIRED))
    by_others = set().union(*(PERMS[r] for r in PERMS if r not in A.TWO_FA_REQUIRED))
    return frozenset((by_2fa - by_others) & set(ALL_STAFF))


SENSITIVE = _sensitive()


def two_fa_required(c, code: str) -> bool:
    """الأدوار الخمسة الإلزامية كما هي (لا تسقط بسحب صلاحياتها)، وأي دور آخر مدمج أو مخصص يُمنح صلاحية حساسة يلزمه التحقق الثنائي في الإنتاج.
    للأدوار الافتراضية يعطي النتيجة نفسها التي كانت في `TWO_FA_REQUIRED` تمامًا (يثبتها اختبار)."""
    return code in A.TWO_FA_REQUIRED or bool(SENSITIVE & perms_for(c, code))


def role_info(c, code: str) -> tuple[frozenset, str, bool]:
    """(الصلاحيات، التسمية، التحقق الثنائي إلزامي؟) بقراءة واحدة للذاكرة — ما يحتاجه كل طلب في `auth.public` (استعلام العدّاد مرة لا ثلاثًا)."""
    r = CACHE.get(c).get(code)
    perms = r["perms"] if r else frozenset(PERMS.get(code, ()))
    return perms, (r["label"] if r else ROLES.get(code, code)), code in A.TWO_FA_REQUIRED or bool(SENSITIVE & perms)


CREATABLE_BUILTIN = frozenset({"admin", "sales", "finance", "engineer", "investor", "property_manager", "accountant", "hr", "payroll"})   # ما كان يقبله إنشاء المستخدم قبل 0.32.0؛ البقية حسابات بوابات لها مساراتها


def assignable(c, code: str) -> bool:
    """دور يُنشأ به مستخدم من شاشة المستخدمين: المدمج الذي كان مسموحًا، أو دور موظفين مخصص قائم."""
    r = CACHE.get(c).get(code)
    return bool(r) and (code in CREATABLE_BUILTIN or (r["kind"] == "staff" and not r["builtin"]))


# ----------------------------------------------------------------------------------------------------- الحواجز
def _admin_holders(c, perms_by_role: dict[str, frozenset | set], skip_user: int | None = None) -> int:
    """عدد المستخدمين النشطين الذين يحمل دورهم `admin` وفق الأدوار المعطاة (بعد التعديل المقترح)."""
    n = 0
    for u in c.execute("SELECT id, role FROM users WHERE active=1"):
        if u["id"] != skip_user and "admin" in perms_by_role.get(u["role"], ()):
            n += 1
    return n


def assert_not_last_admin(c, uid: int, new_role: str | None = None, deactivate: bool = False) -> None:
    """إيقاف الحساب أو تغيير دوره لا يترك المؤسسة بلا مدير نشط."""
    roles = {k: v["perms"] for k, v in CACHE.get(c).items()}
    u = c.execute("SELECT id, role, active FROM users WHERE id=?", (uid,)).fetchone()
    if not u or not u["active"] or "admin" not in roles.get(u["role"], ()):
        return
    leaving = deactivate or (new_role is not None and "admin" not in roles.get(new_role, ()))
    if leaving and _admin_holders(c, roles, skip_user=uid) < 1:
        raise HTTPException(409, "لا يُلغى آخر مدير نشط — أضف مديرًا آخر أولًا")


# ----------------------------------------------------------------------------------------------------- الواجهة البرمجية
def _module_of(p: str) -> str | None:
    return None if p in registry.CORE_PERMS else registry.PERM_MODULE.get(p)


@router.get("/api/roles")
def roles_list(u=Depends(need("users"))):
    c = db()
    allr = CACHE.get(c)
    users = {r["role"]: r["n"] for r in c.execute("SELECT role, COUNT(*) n FROM users WHERE active=1 GROUP BY role")}
    on = set(registry.enabled_modules(c))
    out = []
    order = {k: i for i, k in enumerate(ROLES)}
    for code, r in sorted(allr.items(), key=lambda kv: (kv[1]["kind"] != "staff", not kv[1]["builtin"], order.get(kv[0], 999), len(kv[0]), kv[0])):
        out.append({"code": code, "label": r["label"], "kind": r["kind"], "builtin": r["builtin"], "editable": r["kind"] == "staff", "deletable": r["kind"] == "staff" and not r["builtin"],
                    "perms": sorted(r["perms"]), "users": users.get(code, 0), "two_fa": code in A.TWO_FA_REQUIRED or bool(SENSITIVE & r["perms"]),
                    "assignable": code in CREATABLE_BUILTIN or (r["kind"] == "staff" and not r["builtin"])})
    return {"sections": [{"key": k, "title": t} for k, t in SECTIONS],
            "perms": [{"perm": p, "section": PERM_LABELS[p][0], "label": PERM_LABELS[p][1], "module": _module_of(p), "module_on": _module_of(p) is None or _module_of(p) in on} for p in sorted(ALL_STAFF, key=lambda x: ([k for k, _ in SECTIONS].index(PERM_LABELS[x][0]), x))],
            "roles": out, "must_keep": {k: sorted(v) for k, v in MUST_KEEP.items()}}


class RoleNew(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=3, max_length=40)
    copy_from: str | None = Field(default=None, max_length=30)


class RoleRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=3, max_length=40)


class PermsChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grant: list[str] = Field(default_factory=list, max_length=60)
    revoke: list[str] = Field(default_factory=list, max_length=60)


def _staff_role(c, code: str, what: str = "تُعدَّل") -> dict:
    r = CACHE.get(c).get(code)
    if not r:
        raise HTTPException(404, "الدور غير موجود")
    if r["kind"] != "staff":
        raise HTTPException(403, f"دور «{r['label']}» دور بوابة ثابت لا {what}")
    return r


def _names(perms) -> str:
    return "، ".join(PERM_LABELS[p][1] for p in sorted(perms, key=lambda x: list(PERM_LABELS).index(x)))


@router.post("/api/roles")
def role_create(b: RoleNew, u=Depends(act_as("users"))):
    c = db()
    xlock(c, "roles")      # كل كتابة في الأدوار أو في دور مستخدم تصطف: الحارس يقرأ ما كتبه الطلب السابق لا لقطة قديمة (PostgreSQL؛ كاتب واحد في SQLite)
    label = b.label.strip()
    if len(label) < 3:
        raise HTTPException(400, "اسم الدور ثلاثة أحرف على الأقل")
    allr = CACHE.get(c)
    if any(r["label"] == label for r in allr.values()):
        raise HTTPException(409, f"دور باسم «{label}» موجود")
    base = set()
    if b.copy_from:
        src = _staff_role(c, b.copy_from, "يُنسخ")
        base = set(src["perms"]) & set(ALL_STAFF)
    n = 1 + max([int(k.split("_")[1]) for k in allr if re.fullmatch(r"custom_\d+", k)] or [0])
    code = f"custom_{n}"
    c.execute("INSERT INTO roles(code,label,kind,builtin,created_by) VALUES(?,?,?,0,?)", (code, label, "staff", u["name"]))
    for p in sorted(base):
        c.execute("INSERT INTO role_perms(role_code,perm) VALUES(?,?)", (code, p))
    bump(c)
    audit(c, "دور جديد", f"«{label}»" + (f" · منسوخ من «{allr[b.copy_from]['label']}» ({len(base)} صلاحية)" if b.copy_from else " · بلا صلاحيات"))
    c.commit()
    return {"ok": True, "code": code, "label": label}


@router.patch("/api/roles/{code}")
def role_rename(code: str, b: RoleRename, u=Depends(act_as("users"))):
    c = db()
    xlock(c, "roles")
    r = _staff_role(c, code, "يُعاد تسميتها")
    if r["builtin"]:
        raise HTTPException(403, "تسمية الأدوار المدمجة ثابتة")
    label = b.label.strip()
    if len(label) < 3:
        raise HTTPException(400, "اسم الدور ثلاثة أحرف على الأقل")
    if label == r["label"]:
        return {"ok": True, "changed": []}
    if any(x["label"] == label for x in CACHE.get(c).values()):
        raise HTTPException(409, f"دور باسم «{label}» موجود")
    c.execute("UPDATE roles SET label=? WHERE code=?", (label, code))
    bump(c)
    audit(c, "تعديل دور", f"«{r['label']}» ⟵ «{label}»")
    c.commit()
    return {"ok": True, "changed": ["label"]}


@router.post("/api/roles/{code}/perms")
def role_perms(code: str, b: PermsChange, u=Depends(act_as("users"))):
    c = db()
    xlock(c, "roles")
    r = _staff_role(c, code)
    both = set(b.grant) & set(b.revoke)
    if both:
        raise HTTPException(400, "صلاحية في المنح والسحب معًا")
    unknown = [p for p in (*b.grant, *b.revoke) if p not in PERM_LABELS]
    if unknown:
        raise HTTPException(400, "صلاحية غير معروفة أو ليست من صلاحيات الموظفين: " + "، ".join(unknown))
    cur = set(r["perms"])
    add, drop = (set(b.grant) - cur), (set(b.revoke) & cur)
    if not add and not drop:
        return {"ok": True, "changed": [], "added": [], "removed": []}
    keep = MUST_KEEP.get(code, set())
    if drop & keep:
        raise HTTPException(409, "لا يُسحب من المدير العام: " + _names(drop & keep))
    new = (cur | add) - drop
    roles_after = {k: v["perms"] for k, v in CACHE.get(c).items()}
    roles_after[code] = frozenset(new)
    if "admin" in drop and _admin_holders(c, roles_after) < 1:
        raise HTTPException(409, "لا يُلغى آخر مدير نشط — هذا السحب لا يُبقي أحدًا بصلاحية الإدارة")
    for p in sorted(add):
        c.execute("INSERT OR IGNORE INTO role_perms(role_code,perm) VALUES(?,?)", (code, p))
    for p in sorted(drop):
        c.execute("DELETE FROM role_perms WHERE role_code=? AND perm=?", (code, p))
    bump(c)
    audit(c, "تعديل صلاحيات دور", f"«{r['label']}»" + (f" · أُضيفت: {_names(add)}" if add else "") + (f" · سُحبت: {_names(drop)}" if drop else ""))
    c.commit()
    return {"ok": True, "changed": sorted(add | drop), "added": sorted(add), "removed": sorted(drop)}


@router.delete("/api/roles/{code}")
def role_delete(code: str, u=Depends(act_as("users"))):
    c = db()
    xlock(c, "roles")
    r = _staff_role(c, code, "تُحذف")
    if r["builtin"]:
        raise HTTPException(403, "الأدوار المدمجة لا تُحذف")
    n, active = c.execute("SELECT COUNT(*), COALESCE(SUM(active), 0) FROM users WHERE role=?", (code,)).fetchone()
    if n:
        stopped = n - active      # الحساب الموقوف يحمل الدور أيضًا: يمنع الحذف ولو لم يظهر في عدّ المستخدمين النشطين
        raise HTTPException(409, f"للدور {n} مستخدم{f' (منهم {stopped} موقوف)' if stopped else ''} — انقلهم إلى دور آخر قبل حذفه")
    c.execute("DELETE FROM role_perms WHERE role_code=?", (code,))
    c.execute("DELETE FROM roles WHERE code=?", (code,))
    bump(c)
    audit(c, "حذف دور", f"«{r['label']}» ({len(r['perms'])} صلاحية)")
    c.commit()
    return {"ok": True}


class UserRole(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=2, max_length=30)


@router.post("/api/users/{uid}/role")
def user_role(uid: int, b: UserRole, u=Depends(act_as("users"))):
    """تغيير دور موظف إلى دور موظفين آخر (مدمج أو مخصص). حسابات البوابات لا تُحوَّل. لا يُترك المدير الأخير بلا صلاحية الإدارة."""
    c = A.conn()
    try:
        xlock(c, "roles")
        t = c.execute("SELECT id, username, role, active FROM users WHERE id=?", (uid,)).fetchone()
        if not t:
            raise HTTPException(404, "المستخدم غير موجود")
        allr = CACHE.get(c)
        cur, new = allr.get(t["role"]), allr.get(b.role)
        if not new or new["kind"] != "staff":
            raise HTTPException(400, "الدور غير معروف أو ليس دور موظفين")
        if not cur or cur["kind"] != "staff":
            raise HTTPException(403, "حسابات البوابات (عميل، وسيط، مستأجر، موظف…) لا يتغيّر دورها من هنا")
        if t["role"] == b.role:
            return {"ok": True, "changed": []}
        assert_not_last_admin(c, uid, new_role=b.role)
        c.execute("UPDATE users SET role=? WHERE id=?", (b.role, uid))
        audit(c, "تغيير دور مستخدم", f"{t['username']} · «{cur['label']}» ⟵ «{new['label']}»")
        c.commit()
        return {"ok": True, "changed": ["role"], "role": b.role, "role_label": new["label"]}
    finally:
        c.close()
