"""Mabaniq 0.29.0 — the `hr` phase of the demo organisation (backend/seed_org.py): the people file and everything around it.

Departments, positions, twenty invented employees (Omani and expatriate, with documents whose expiry dates make the alerts show something), the default working week and
public holidays, leave requests that go through the real employee → manager → HR route, a daily attendance sheet, employees' own requests, a recruitment pipeline with a
hire, two appraisal cycles (one closed, one under way), training with certificates, and a bylaw with disciplinary cases at every stage.

All of it goes through the same functions the screens use (see the module docstring of seed_org.py), so every rule — a leave balance, a second person to approve a bylaw
article, a statement before a penalty — is the platform's own. Whatever a rule refuses is skipped and counted, never forced.
"""
from __future__ import annotations

import datetime as dt

from . import hr, hr_disc, hr_leave, hr_perf, hr_recruit, hr_self
from .auth import PERMS, ROLES
from .common import db
from .seed_org import Ctx
from .seed_org_data import BANKS, ORGS

DAY = dt.timedelta(days=1)
WORKDAYS = {6, 0, 1, 2, 3}  # Sunday … Thursday (Python Monday = 0); the weekend is Friday + Saturday ("hr:weekend" = 4,5)

BYLAW_SRC = "لائحة تنظيم العمل والجزاءات النموذجية للتجربة (مسودة افتراضية — تُراجَع من مختص قانوني قبل الاعتماد الفعلي)"
# code, name, description, kind, max days, article
BYLAW = [
    ("P01", "التأخر عن الدوام دون عذر", "التأخر عن بدء الدوام بعد فترة السماح بلا إذن مسبق.", "warning", 0, "المادة 1"),
    ("P02", "التأخر المتكرر", "التأخر أكثر من ثلاث مرات في الشهر الواحد بعد إنذار سابق.", "deduction", 1, "المادة 2"),
    ("P03", "الغياب دون إذن", "الغياب يومًا أو أكثر دون إذن أو عذر مقبول يُقدَّم خلال مهلة معقولة.", "deduction", 3, "المادة 3"),
    ("P04", "مخالفة تعليمات السلامة في المواقع", "عدم ارتداء معدات الوقاية أو مخالفة إجراءات السلامة في موقع المشروع.", "deduction", 3, "المادة 4"),
    ("P05", "إساءة استخدام أصول الشركة", "استعمال سيارة الشركة أو معداتها أو أنظمتها لغير أغراض العمل.", "deduction", 2, "المادة 5"),
    ("P06", "الإخلال بسرية بيانات العملاء", "الإفصاح عن بيانات العملاء أو الأسعار أو العقود لغير المخوَّلين.", "suspension", 5, "المادة 6"),
    ("P07", "عدم الالتزام بإجراءات التحقق من هوية العملاء", "إتمام حجز أو عقد دون استيفاء متطلبات التحقق من الهوية ومكافحة غسل الأموال.", "warning", 0, "المادة 7"),
    ("P08", "مخالفة سياسة تضارب المصالح", "عدم الإفصاح عن مصلحة شخصية في تعامل مع مقاول أو مورد أو عميل.", "suspension", 5, "المادة 8"),
    ("P09", "سلوك غير لائق في بيئة العمل", "الإساءة اللفظية أو الإخلال بآداب التعامل مع الزملاء أو العملاء.", "warning", 0, "المادة 9"),
    ("P10", "التقصير في أداء الواجبات", "إهمال أداء المهام المكلَّف بها رغم التنبيه.", "deduction", 2, "المادة 10"),
]
COURSES = [
    # title, provider, hours, certificate months, mandatory
    ("السلامة والصحة المهنية في مواقع المشاريع", "مركز التدريب المهني والسلامة", 8, 24, 1),
    ("مكافحة غسل الأموال والتحقق من هوية العملاء", "معهد المهن المالية والعقارية", 4, 12, 1),
    ("حماية البيانات الشخصية في بيئة العمل", "إدارة الامتثال الداخلي", 3, 12, 1),
    ("مهارات المبيعات والتفاوض العقاري", "أكاديمية التطوير العقاري", 16, None, 0),
    ("إدارة المشاريع الإنشائية (مدخل)", "جمعية المهندسين", 24, None, 0),
    ("القيادة الإدارية للمشرفين", "معهد الإدارة", 20, None, 0),
    ("الإسعافات الأولية والإخلاء", "الهلال الأحمر", 6, 24, 0),
    ("التحليل المالي والتقارير الإدارية", "معهد المهن المالية والعقارية", 12, None, 0),
]
GOALS = {
    "exec": ["تنفيذ خطة الأعمال السنوية", "تحسين التدفق النقدي للمشاريع", "بناء علاقات مع الجهات الحكومية والممولين"],
    "sales": ["تحقيق مستهدف المبيعات أو التأجير", "رفع نسبة التحويل من الاستفسار إلى الحجز", "تحديث بيانات العملاء المحتملين أسبوعيًا"],
    "proj": ["الالتزام بالجدول الزمني للمشاريع", "خفض ملاحظات الجودة وعدم المطابقة", "ضبط أوامر التغيير ضمن الموازنة"],
    "fin": ["إقفال شهري خلال خمسة أيام عمل", "تحسين نسبة التحصيل", "دقة التقارير المالية وسرعة إصدارها"],
    "hr": ["اكتمال ملفات الموظفين ووثائقهم", "خفض زمن التوظيف", "الالتزام بخطة التدريب الإلزامي"],
    "pm": ["رفع نسبة الإشغال", "خفض زمن الاستجابة لطلبات الصيانة", "تحصيل الإيجارات في مواعيدها"],
    "cx": ["رفع رضا العملاء", "إغلاق الطلبات خلال المهلة المحددة", "قياس عائد الحملات التسويقية"],
}


def _iso(d: dt.date) -> str:
    return d.isoformat()


def _as(u: dict) -> dict:
    """Make `u` the actor of the audit lines that follow (what `common.act_as` does for a request) and hand it back."""
    from .common import ACTOR
    ACTOR.set(f"{u['name']} ({u['role_label']})")
    return u


def _emp_user(e: dict) -> dict:
    """The signed-in employee as `auth.public()` would build him: the `employee` role, linked to his own file."""
    return {"id": 0, "username": "emp" + e["number"].split("-")[-1], "name": e["name"], "role": "employee", "role_label": ROLES["employee"], "perms": sorted(PERMS["employee"]),
            "customer_id": None, "employee_id": e["id"], "lessee_id": None, "modules": [], "broker_id": None, "must_change": False, "totp_enabled": True, "needs_2fa": False}


def _mini_pdf(line: str) -> bytes:
    """A valid one-page PDF with a single Latin line — the placeholder for a medical report or a certificate in the demo (nobody's real document)."""
    text = line.encode("latin-1", "replace").decode("latin-1").replace("(", " ").replace(")", " ")
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)


def _next_workday(d: dt.date, hol: set) -> dt.date:
    while d.weekday() not in WORKDAYS or d.isoformat() in hol:
        d += DAY
    return d


def _add_workdays(d: dt.date, n: int, hol: set) -> dt.date:
    """The date `n` working days long starting at `d` (n = 1 → d itself)."""
    d = _next_workday(d, hol)
    left = n - 1
    while left > 0:
        d += DAY
        if d.weekday() in WORKDAYS and d.isoformat() not in hol:
            left -= 1
    return d


def _holidays(year: int) -> list[tuple[str, str]]:
    """Public holidays of Oman (dates that follow the moon are approximate and say so; the real ones are entered by the decree)."""
    ap = " (تاريخ تقريبي — يُعدَّل بالقرار الرسمي)"
    return [(f"{year}-01-01", "رأس السنة الميلادية"), (f"{year}-01-16", "الإسراء والمعراج" + ap), (f"{year}-03-20", "عيد الفطر" + ap), (f"{year}-03-21", "عيد الفطر" + ap),
            (f"{year}-03-22", "عيد الفطر" + ap), (f"{year}-05-26", "وقفة عرفة" + ap), (f"{year}-05-27", "عيد الأضحى" + ap), (f"{year}-05-28", "عيد الأضحى" + ap),
            (f"{year}-06-17", "رأس السنة الهجرية" + ap), (f"{year}-07-23", "يوم النهضة"), (f"{year}-08-25", "المولد النبوي الشريف" + ap),
            (f"{year}-11-18", "العيد الوطني"), (f"{year}-11-19", "العيد الوطني")]


# ----------------------------------------------------------------------------------------------------------------------- the phase
def run(ctx: Ctx) -> None:
    P = ORGS[ctx.tenant]
    keys = _setup(ctx, P)
    _documents(ctx, P, keys)
    _leave(ctx, P, keys)
    _requests(ctx, P, keys)
    _attendance(ctx, P, keys)
    _recruitment(ctx, P, keys)
    _discipline(ctx, P, keys)
    _appraisals(ctx, P, keys)
    _training(ctx, P, keys)


def _emps(ctx: Ctx, P: dict) -> dict:
    """key → employee row (dict) for the organisation's list, found by name (so a second run finds what the first created)."""
    out = {}
    with ctx.request():
        c = db()
        for row in P["employees"]:
            r = c.execute("SELECT * FROM employees WHERE name=?", (row[1],)).fetchone()
            if r:
                out[row[0]] = dict(r)
    return out


def _setup(ctx: Ctx, P: dict) -> dict:
    hr_u, today, rnd = ctx.act("hr"), ctx.today, ctx.rnd
    # the working week, the leave types, the public holidays — settings the organisation would enter once
    ctx.tryc(hr_leave.api_settings_put, hr_leave.SettingsIn(weekend=[4, 5], work_start="08:00", late_grace=15), u=hr_u)
    with ctx.request():
        c = db()
        hr_leave.ensure_types(c)
        c.commit()
        have_v2 = c.execute("SELECT 1 FROM leave_types WHERE key='annual' AND valid_from='2026-01-01'").fetchone()
    if not have_v2:   # the annual allowance with the organisation's own carry-over rule (ten days), in force from the start of the year
        ctx.tryc(hr_leave.api_type_add, hr_leave.TypeIn(key="annual", name="الإجازة السنوية", paid=True, days_per_year=30, accrual="monthly", carry_over_max=10, valid_from="2026-01-01",
                                                          note="سياسة افتراضية للتجربة: ثلاثون يومًا في السنة تُستحق شهريًا، ويُرحَّل منها حتى عشرة أيام"), u=hr_u)
    have_h = {r["day"] for r in _q(ctx, "SELECT day FROM holidays")}
    for y in (today.year - 1, today.year):
        for day, name in _holidays(y):
            if day not in have_h:
                ctx.tryc(hr_leave.api_holiday_add, hr_leave.HolidayIn(day=day, name=name), u=hr_u)
    # structure
    dept = {r["name"]: r["id"] for r in _q(ctx, "SELECT id, name FROM departments")}
    for key, name in P["departments"]:
        if name not in dept:
            r = ctx.tryc(hr.api_dept_add, hr.DeptIn(name=name), u=hr_u)
            if r:
                dept[name] = r["id"]
    dkey = {k: dept.get(n) for k, n in P["departments"]}
    have_p = {(r["title"], r["department_id"]) for r in _q(ctx, "SELECT title, department_id FROM positions")}
    for title, dk, grade, head in P["positions"]:
        if (title, dkey[dk]) not in have_p:
            ctx.tryc(hr.api_position_add, hr.PositionIn(title=title, department_id=dkey[dk], grade=grade, headcount=head), u=hr_u)
    pos = {(r["title"], r["department_id"]): r["id"] for r in _q(ctx, "SELECT id, title, department_id FROM positions")}
    # people: managers come first in the list
    made = _emps(ctx, P)
    for row in P["employees"]:
        key, ar, en, nat, gender, marital, dk, title, mgr, hired, ctype, cend, basic, housing, transport, bank = row
        if key in made:
            continue
        omani = not nat
        hire = today - dt.timedelta(days=hired)
        age = rnd.randint(24, 52) if omani else rnd.randint(27, 49)
        b = hr.EmployeeIn(
            name=ar, name_en=en, nationality=nat or "عُماني", omani=omani, id_number=str(rnd.randint(10_000_000, 99_999_999)) if omani else f"{rnd.randint(10_000_000, 99_999_999)}",
            dob=_iso(today - dt.timedelta(days=age * 365 + rnd.randint(0, 300))), gender=gender, marital=marital, phone=f"+968 9999 {rnd.randint(1000, 9999)}",
            email=f"{key}.{en.split()[-1].lower()}@{ctx.tenant}-demo.example", address="مسقط، سلطنة عُمان",
            department_id=dkey[dk], position_id=pos.get((title, dkey[dk])), manager_id=made[mgr]["id"] if mgr else None, hire_date=_iso(hire), contract_type=ctype,
            contract_end=_iso(today + dt.timedelta(days=cend)) if cend else "",
            probation_end=_iso(hire + dt.timedelta(days=180)) if hired < 400 else "", bank_name=BANKS[bank],
            iban=f"OM{rnd.randint(10, 99)}0{rnd.randint(10, 99)}0" + "".join(str(rnd.randint(0, 9)) for _ in range(15)),
            social_ins_no=f"{rnd.randint(100000, 999999)}" if omani else "", emergency_contact=f"{rnd.choice(('أخ', 'زوجة', 'أب', 'أم', 'زوج'))} — +968 9999 {rnd.randint(1000, 9999)}")
        r = ctx.tryc(hr.api_employee_add, b, u=hr_u)
        if r:
            ctx.add("employees")
            made[key] = {"id": r["id"], "number": r["number"], "name": ar}
    made = _emps(ctx, P)
    # heads of department (the most senior person of each) and the department's cost centre
    heads = {"exec": "ceo", "sales": "smgr", "proj": "pmgr", "fin": "cfo", "hr": "hr", "pm": "pmg2", "cx": "mkt" if "mkt" in made else "cxm"}
    for k, name in P["departments"]:
        did, hk = dept.get(name), heads.get(k)
        if not did:
            continue
        patch = {}
        if hk in made:
            patch["head_employee_id"] = made[hk]["id"]
        cc = _dept_cost_center(ctx, did, name)
        if cc:
            patch["cost_center_id"] = cc
        if patch:
            ctx.tryc(hr.api_dept_edit, did, hr.DeptPatch(**patch), u=hr_u)
    return {k: v["id"] for k, v in made.items()}


def _q(ctx: Ctx, sql: str, args: tuple = ()) -> list:
    with ctx.request():
        c = db()
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def _dept_cost_center(ctx: Ctx, did: int, name: str):
    """One cost centre per department (kind `dept`) so payroll expense is spread by department in the books; created if the accounting phase has not."""
    with ctx.request():
        c = db()
        r = c.execute("SELECT id FROM acc_cost_centers WHERE kind='dept' AND ref_id=?", (did,)).fetchone()
        if r:
            return r["id"]
        code = f"D{did:03d}"
        if c.execute("SELECT 1 FROM acc_cost_centers WHERE code=?", (code,)).fetchone():
            return None
        cid = c.execute("INSERT INTO acc_cost_centers(code,name,kind,ref_id) VALUES(?,?,'dept',?)", (code, name, did)).lastrowid
        c.commit()
        return cid


# ----------------------------------------------------------------------------------------------------------------------- documents
def _documents(ctx: Ctx, P: dict, keys: dict) -> None:
    if _q(ctx, "SELECT 1 FROM employee_documents LIMIT 1"):
        return
    hr_u, today, rnd = ctx.act("hr"), ctx.today, ctx.rnd
    # the first expatriates are given the expiry dates the alerts are made to show: expired, within 30 days, within 90 days, soon
    fixed_exp = [-8, 22, 58, 12, 140, 260]
    ex = 0
    for row in P["employees"]:
        key, nat = row[0], row[3]
        eid = keys.get(key)
        if not eid:
            continue

        def add(kind, number, issued, expires, note="", eid=eid):
            return ctx.tryc(hr.api_doc_add, eid, hr.DocIn(kind=kind, number=number, issued=issued, expires=expires, note=note), u=hr_u)
        if nat:
            e_days = fixed_exp[ex % len(fixed_exp)] if ex < len(fixed_exp) else rnd.randint(150, 700)
            ex += 1
            add("passport", f"P{rnd.randint(1000000, 9999999)}", _iso(today - dt.timedelta(days=rnd.randint(800, 2500))), _iso(today + dt.timedelta(days=rnd.randint(200, 1500))))
            add("resident_card", f"{rnd.randint(10000000, 99999999)}", _iso(today - dt.timedelta(days=rnd.randint(100, 700))), _iso(today + dt.timedelta(days=e_days)))
            add("labour_card", f"LC{rnd.randint(100000, 999999)}", _iso(today - dt.timedelta(days=rnd.randint(100, 700))), _iso(today + dt.timedelta(days=e_days + rnd.randint(-5, 40))))
        else:
            add("health_insurance", f"HI{rnd.randint(100000, 999999)}", _iso(today - dt.timedelta(days=rnd.randint(30, 300))), _iso(today + dt.timedelta(days=rnd.randint(30, 330))))
        add("contract", f"CT-{rnd.randint(1000, 9999)}", _iso(today - dt.timedelta(days=row[9])), "", "عقد العمل الأصلي")
        if rnd.random() < .5:
            add("certificate", f"CERT-{rnd.randint(100, 999)}", "", "", "مؤهل علمي موثَّق")
        ctx.add("documents")


# ----------------------------------------------------------------------------------------------------------------------- leave
def _doc_for(ctx: Ctx, e: dict, title: str) -> int | None:
    from .modules2 import store_upload

    def go():
        c = db()
        did, _ = store_upload(c, _mini_pdf("Illustrative document - demo data only"), "demo-document.pdf", "employee", e["id"], title, "إجازات", "التعبئة التجريبية")
        c.commit()
        return did
    try:
        return ctx.call(go)
    except Exception:  # noqa: BLE001
        return None


def _leave_case(ctx: Ctx, e: dict, mgr: dict | None, key: str, frm: dt.date, n: int, outcome: str, hol: set, reason: str, *, calendar: bool = False, doc: bool = False) -> int | None:
    """One leave request the way it happens: the employee asks, the line manager (or HR for the special types) decides. outcome: approved | pending | rejected | cancelled | hr."""
    to = (frm + dt.timedelta(days=n - 1)) if calendar else _add_workdays(frm, n, hol)
    start = frm if calendar else _next_workday(frm, hol)
    if not calendar:
        to = _add_workdays(start, n, hol)
    hr_u, eu = ctx.act("hr"), _emp_user(e)
    if outcome == "hr":   # recorded and approved by HR on the employee's behalf (a phone call, a report handed in)
        rid = ctx.tryc(hr_leave.api_request_add, hr_leave.LeaveIn(employee_id=e["id"], type_key=key, from_date=_iso(start), to_date=_iso(to), reason=reason, approve=False), u=hr_u)
    else:
        rid = ctx.tryc(hr_self.api_me_leave_add, hr_self.MyLeaveIn(type_key=key, from_date=_iso(start), to_date=_iso(to), reason=reason), u=_as(eu))
    if not rid:
        return None
    rid = rid["id"]
    ctx.add("leave_requests")
    if doc:
        did = _doc_for(ctx, e, "تقرير طبي (نموذج توضيحي)" if key == "sick" else "مستند داعم (نموذج توضيحي)")
        if did:
            with ctx.request():
                c = db()
                c.execute("UPDATE leave_requests SET doc_id=? WHERE id=?", (did, rid))
                c.commit()
    if outcome == "pending":
        return rid
    st = _q(ctx, "SELECT stage FROM leave_requests WHERE id=?", (rid,))[0]["stage"]
    if outcome == "cancelled":
        ctx.tryc(hr_leave.api_cancel, rid, hr_leave.CancelIn(reason="تغيّرت الخطة"), u=_as(eu))
        return rid
    approver = _as(ctx.user("hr") if (st == "hr" or not mgr) else _emp_user(mgr))
    if outcome == "rejected":
        ctx.tryc(hr_leave.api_decide, rid, hr_leave.DecideIn(action="reject", note="يتعارض مع ضغط العمل في هذه الفترة؛ يُقترح موعد آخر"), u=approver)
        return rid
    r = ctx.tryc(hr_leave.api_decide, rid, hr_leave.DecideIn(action="approve", note="معتمدة"), u=approver)
    if r and r.get("stage") == "hr":      # the manager passed it on to HR (a special type)
        ctx.tryc(hr_leave.api_decide, rid, hr_leave.DecideIn(action="approve", note="اعتمدتها الموارد البشرية"), u=_as(ctx.user("hr")))
    return rid


def _leave(ctx: Ctx, P: dict, keys: dict) -> None:
    if _q(ctx, "SELECT 1 FROM leave_requests LIMIT 1"):
        return
    today, rnd = ctx.today, ctx.rnd
    emps = _emps(ctx, P)
    hol = {r["day"] for r in _q(ctx, "SELECT day FROM holidays")}
    # opening balances for a few long-serving people (carried from last year)
    hr_u = ctx.act("hr")
    for k in list(emps)[:12:3]:
        ctx.tryc(hr_leave.api_adjust, hr_leave.AdjustIn(employee_id=emps[k]["id"], type_key="annual", year=today.year, delta=5, note="رصيد مرحَّل من العام السابق (افتتاحي)"), u=hr_u)
    by_id = {v["id"]: v for v in emps.values()}
    mgr_of = lambda e: by_id.get(e["manager_id"]) if e["manager_id"] else None  # noqa: E731
    leaver, newhire = P["leaver"], P["newhire"]
    # special events first (they use fixed windows)
    female_married = [k for k, v in emps.items() if v["gender"] == "female" and v["marital"] == "married" and k not in ("hr",)]
    if female_married:
        k = female_married[1] if len(female_married) > 1 else female_married[0]
        _leave_case(ctx, emps[k], mgr_of(emps[k]), "maternity", today - dt.timedelta(days=118), 98, "hr", hol, "إجازة وضع", calendar=True, doc=True)
    male_married = [k for k, v in emps.items() if v["gender"] == "male" and v["marital"] == "married" and k not in (leaver,)]
    if male_married:
        _leave_case(ctx, emps[male_married[2 % len(male_married)]], mgr_of(emps[male_married[2 % len(male_married)]]), "paternity", today - dt.timedelta(days=75), 7, "approved", hol, "ولادة مولود", calendar=True, doc=True)
    single = [k for k, v in emps.items() if v["marital"] == "single" and not v["terminated_on"] and k != newhire]
    if single:
        _leave_case(ctx, emps[single[0]], mgr_of(emps[single[0]]), "marriage", today - dt.timedelta(days=150), 3, "approved", hol, "إجازة زواج", doc=True)
    if len(emps) > 10:
        k = list(emps)[10]
        _leave_case(ctx, emps[k], mgr_of(emps[k]), "unpaid", today - dt.timedelta(days=70), 3, "hr", hol, "ظرف عائلي — إجازة بلا راتب")
    # the ordinary year: every active person takes some annual leave and a day or two of sick leave
    for k, e in emps.items():
        if k == newhire or e["status"] == "terminated":
            continue
        m = mgr_of(e)
        hired = dt.date.fromisoformat(e["hire_date"])
        for _ in range(rnd.randint(1, 2)):
            back = rnd.randint(25, 200)
            frm = today - dt.timedelta(days=back)
            if frm > hired:
                _leave_case(ctx, e, m, "annual", frm, rnd.randint(2, 7), "approved", hol, rnd.choice(("إجازة سفر عائلية", "إجازة سنوية", "راحة بعد إنجاز مرحلة", "مناسبة عائلية")))
        if rnd.random() < .6:
            _leave_case(ctx, e, m, "sick", today - dt.timedelta(days=rnd.randint(8, 150)), rnd.randint(1, 3), "approved", hol, "إجازة مرضية", calendar=True, doc=True)
        if rnd.random() < .25:
            _leave_case(ctx, e, m, "emergency", today - dt.timedelta(days=rnd.randint(10, 120)), 1, "approved", hol, "ظرف طارئ")
    # waiting, rejected and cancelled
    ks = [k for k in emps if k not in (leaver, newhire, "ceo")]
    for i, k in enumerate(ks[:5]):
        _leave_case(ctx, emps[k], mgr_of(emps[k]), "annual", today + dt.timedelta(days=14 + i * 9), rnd.randint(3, 6), "pending", hol, "إجازة قادمة")
    _leave_case(ctx, emps[ks[5]], mgr_of(emps[ks[5]]), "annual", today + dt.timedelta(days=21), 4, "rejected", hol, "إجازة في فترة تسليم مرحلة")
    _leave_case(ctx, emps[ks[6]], mgr_of(emps[ks[6]]), "annual", today + dt.timedelta(days=40), 5, "cancelled", hol, "إجازة (ألغيت)")
    if len(ks) > 8:
        _leave_case(ctx, emps[ks[7]], mgr_of(emps[ks[7]]), "hajj", today + dt.timedelta(days=210), 12, "pending", hol, "أداء فريضة الحج", calendar=True, doc=True)


# ----------------------------------------------------------------------------------------------------------------------- employees' own requests
def _requests(ctx: Ctx, P: dict, keys: dict) -> None:
    if _q(ctx, "SELECT 1 FROM hr_requests LIMIT 1"):
        return
    emps = _emps(ctx, P)
    items = [("letter", "شهادة راتب لتقديمها إلى البنك لغرض تمويل سكن", None, "done"), ("letter", "خطاب تعريف بالعمل لتجديد جواز السفر", None, "done"), ("letter", "شهادة خبرة", None, "pending"),
             ("other", "طلب نقل مكتب إلى الطابق الأول لقربه من الفريق", None, "rejected"), ("advance", "سلفة لتسوية رسوم دراسية للأبناء", 500.0, "approved"),
             ("advance", "سلفة لصيانة طارئة للمنزل", 300.0, "approved"), ("advance", "سلفة لمصاريف علاج", 400.0, "pending")]
    order = [k for k in emps if k not in (P["leaver"], P["newhire"], "ceo", "hr")]
    hr_u = ctx.act("hr")
    for i, (kind, details, amount, outcome) in enumerate(items):
        if i >= len(order):
            break
        e = emps[order[(i * 2) % len(order)]]
        r = ctx.tryc(hr_self.api_me_request_add, hr_self.RequestIn(kind=kind, details=details, amount=amount), u=_as(_emp_user(e)))
        if not r:
            continue
        ctx.add("requests")
        if outcome == "pending":
            continue
        status, note = {"done": ("done", "أُنجز وسُلّم للموظف"), "rejected": ("rejected", "لا تتوافر مساحة في الطابق المطلوب"), "approved": ("approved", "وُجّه إلى الرواتب لإجراء السلفة")}[outcome]
        ctx.tryc(hr_self.api_request_decide, r["id"], hr_self.RequestDecide(status=status, note=note), u=_as(hr_u))


# ----------------------------------------------------------------------------------------------------------------------- attendance
def _attendance(ctx: Ctx, P: dict, keys: dict) -> None:
    if _q(ctx, "SELECT 1 FROM attendance WHERE source='manual' LIMIT 1"):
        return
    today, rnd = ctx.today, ctx.rnd
    emps = _emps(ctx, P)
    start = today - dt.timedelta(days=210)
    hol = {r["day"] for r in _q(ctx, "SELECT day FROM holidays")}
    ids = sorted(emps.values(), key=lambda e: e["id"])
    lv_id = emps[P["leaver"]]["id"] if P["leaver"] in emps else 0
    absent_for = {ids[3 % len(ids)]["id"]: 2, ids[8 % len(ids)]["id"]: 1}   # a few unexcused absences in a closed month so payroll shows a deduction
    with ctx.request():
        c = db()
        have = {(r["employee_id"], r["day"]) for r in c.execute("SELECT employee_id, day FROM attendance").fetchall()}
        n = 0
        for e in ids:
            first = max(start, dt.date.fromisoformat(e["hire_date"]))
            last = min(today - DAY, dt.date.fromisoformat(e["terminated_on"])) if e["terminated_on"] else today - DAY
            if e["id"] == lv_id:
                last = min(last, today.replace(day=1) - DAY)   # his service ends with the last closed month (see seed_org_pay)
            d, planned_absent = first, absent_for.get(e["id"], 0)
            while d <= last:
                iso = d.isoformat()
                if d.weekday() in WORKDAYS and iso not in hol and (e["id"], iso) not in have:
                    r = rnd.random()
                    month_closed = d < today.replace(day=1) - dt.timedelta(days=1)
                    if planned_absent and month_closed and d.month == (today.replace(day=1) - DAY).month and 8 <= d.day <= 20 and r < .25:
                        c.execute("INSERT OR IGNORE INTO attendance(employee_id,day,status,source,note) VALUES(?,?,'absent','manual','غياب دون إذن')", (e["id"], iso))
                        planned_absent -= 1
                    elif r < .045:
                        c.execute("INSERT OR IGNORE INTO attendance(employee_id,day,status,check_in,check_out,source) VALUES(?,?,'late',?,?,'manual')",
                                  (e["id"], iso, f"08:{rnd.randint(18, 50):02d}", f"{rnd.randint(16, 17)}:{rnd.randint(0, 59):02d}"))
                    elif r < .08:
                        c.execute("INSERT OR IGNORE INTO attendance(employee_id,day,status,check_in,check_out,source,note) VALUES(?,?,'remote',?,?,'manual','عمل عن بُعد')",
                                  (e["id"], iso, f"08:{rnd.randint(0, 10):02d}", f"{rnd.randint(16, 17)}:{rnd.randint(0, 59):02d}"))
                    else:
                        c.execute("INSERT OR IGNORE INTO attendance(employee_id,day,status,check_in,check_out,source) VALUES(?,?,'present',?,?,'manual')",
                                  (e["id"], iso, f"07:{rnd.randint(40, 59):02d}" if rnd.random() < .6 else f"08:{rnd.randint(0, 14):02d}", f"{rnd.randint(16, 17)}:{rnd.randint(0, 59):02d}"))
                    n += 1
                d += DAY
        c.commit()
    ctx.add("attendance_days", n)


# ----------------------------------------------------------------------------------------------------------------------- recruitment
def _recruitment(ctx: Ctx, P: dict, keys: dict) -> None:
    if _q(ctx, "SELECT 1 FROM job_openings LIMIT 1"):
        return
    hr_u, today, rnd = ctx.act("hr"), ctx.today, ctx.rnd
    dept = {k: r["id"] for k, n in P["departments"] for r in _q(ctx, "SELECT id FROM departments WHERE name=?", (n,))}
    ids = {}
    for i, (title, dk, head, desc, req) in enumerate(P["openings"]):
        pos = _q(ctx, "SELECT id FROM positions WHERE title=? AND department_id=?", (title, dept[dk]))
        r = ctx.tryc(hr_recruit.api_opening_add, hr_recruit.OpeningIn(title=title, department_id=dept[dk], position_id=pos[0]["id"] if pos else None, headcount=head,
                                                                    closes_on=_iso(today + dt.timedelta(days=30 + i * 10)), description=desc, requirements=req), u=hr_u)
        if r:
            ids[i] = r["id"]
            ctx.tryc(hr_recruit.api_opening_status, r["id"], hr_recruit.OpeningStatus(status="open"), u=hr_u)
    hire_name = P["hire_candidate"][0]
    sources = ("موقع الشركة", "لينكدإن", "ترشيح موظف", "معرض التوظيف", "وزارة العمل — منصة التوظيف")
    # who goes where: opening 0 and 1 stay open with candidates at every stage; opening 2 is the one that ends in a hire
    plan = [(0, 0, "interview"), (0, 1, "offer"), (0, 2, "screening"), (0, 3, "rejected"), (1, 4, "interview"), (1, 5, "screening"), (1, 6, "applied"), (2, 7, "offer")]
    for opening, ci, target in plan:
        if opening not in ids:
            continue
        name, first = P["candidates"][ci]
        r = ctx.tryc(hr_recruit.api_candidate_add, hr_recruit.CandidateIn(opening_id=ids[opening], name=name, phone=f"+968 9999 {rnd.randint(1000, 9999)}", email=f"{first.lower()}.{ci}@candidates-demo.example",
                                                                          source=rnd.choice(sources), notes="خبرة مناسبة حسب السيرة الذاتية"), u=hr_u)
        if not r:
            continue
        cid = r["id"]
        ctx.add("candidates")
        if target == "applied":
            continue
        if target == "rejected":
            ctx.tryc(hr_recruit.api_candidate_stage, cid, hr_recruit.StageIn(stage="rejected", reason="الخبرة لا تطابق متطلبات الوظيفة", rating=2), u=hr_u)
            continue
        ctx.tryc(hr_recruit.api_candidate_stage, cid, hr_recruit.StageIn(stage="screening", rating=rnd.randint(3, 5)), u=hr_u)
        if target == "screening":
            continue
        iv = ctx.tryc(hr_recruit.api_interview_add, cid, hr_recruit.InterviewIn(scheduled_at=_iso(today - dt.timedelta(days=rnd.randint(2, 12))) + " 10:00", kind="in_person",
                                                                                 interviewer="مدير القسم ومسؤول الموارد البشرية"), u=hr_u)
        if iv and target in ("offer",) or (iv and target == "interview" and ci % 2 == 0):
            ctx.tryc(hr_recruit.api_interview_result, iv["id"], hr_recruit.ResultIn(score=rnd.randint(4, 5), notes="أداء جيد في المقابلة ويتوافق مع متطلبات الوظيفة"), u=hr_u)
        if iv and target == "interview" and ci % 2 == 1:
            ctx.tryc(hr_recruit.api_interview_add, cid, hr_recruit.InterviewIn(scheduled_at=_iso(today + dt.timedelta(days=4)) + " 11:30", kind="technical", interviewer="المدير المباشر"), u=hr_u)
        if target == "offer":
            ctx.tryc(hr_recruit.api_candidate_stage, cid, hr_recruit.StageIn(stage="offer", rating=5), u=hr_u)
            if name == hire_name:
                emps = _emps(ctx, P)
                _, _, dk, gender, *_ = P["hire_candidate"]
                mgr = {"fin": "cfo", "cx": "cxm" if "cxm" in emps else "mkt"}.get(dk)
                ctx.tryc(hr_recruit.api_hire, cid, hr_recruit.HireIn(hire_date=_iso(today - dt.timedelta(days=24)), omani=True, gender=gender, nationality="عُماني",
                                                                  probation_end=_iso(today + dt.timedelta(days=156)), manager_id=emps[mgr]["id"] if mgr in emps else None), u=hr_u)
    ctx.add("openings", len(ids))


# ----------------------------------------------------------------------------------------------------------------------- discipline
def _discipline(ctx: Ctx, P: dict, keys: dict) -> None:
    if _q(ctx, "SELECT 1 FROM penalty_rules LIMIT 1"):
        return
    hr_u, admin, today = ctx.act("hr"), ctx.user("admin"), ctx.today
    rule = {}
    for code, name, desc, kind, mx, art in BYLAW:
        r = ctx.tryc(hr_disc.api_rule_add, hr_disc.RuleIn(code=code, name=name, description=desc, kind=kind, max_days=mx, source=f"{BYLAW_SRC} — {art}"), u=hr_u)
        if r:
            rule[code] = r["id"]
            ctx.tryc(hr_disc.api_rule_approve, r["id"], hr_disc.ApproveRule(valid_from=f"{today.year}-01-01"), u=_as(admin))   # the second person
    emps = _emps(ctx, P)
    ids = [v for k, v in emps.items() if k not in ("ceo", P["newhire"], P["leaver"])]
    prev_month = (today.replace(day=1) - DAY)
    apply_period = f"{prev_month.year}-{prev_month.month:02d}"
    cases = [  # employee index, incident days ago, description, statement, rule, days, outcome
        (2, 60, "تأخر عن بدء الدوام أربع مرات خلال أسبوعين دون إذن مسبق.", "أقرّ بالتأخر لظروف المواصلات ووعد بالالتزام.", "P01", 0, "issued"),
        (5, 44, "غياب يوم عمل كامل دون إذن ودون إشعار الجهة المباشرة.", "ذكر أنه أبلغ زميلًا شفهيًا ولم يقدم ما يثبت ذلك.", "P03", 1, "issued"),
        (7, 38, "عدم ارتداء معدات الوقاية في الموقع رغم التنبيه المسبق من مسؤول السلامة.", "أقرّ بالمخالفة وتعهد بالالتزام.", "P04", 2, "appeal-upheld"),
        (9, 30, "استعمال سيارة الشركة لغرض شخصي دون إذن.", "ذكر أنه كان في طريقه إلى مهمة عمل وتوقف مرة واحدة.", "P05", 1, "appeal-revoked"),
        (4, 12, "الإفصاح لطرف خارجي عن شروط تسعير وحدة قبل الإعلان الرسمي.", "", "", 0, "open"),
        (11, 8, "إتمام حجز دون استكمال مستندات التحقق من هوية العميل.", "أقرّ بالنقص وأكمل المستندات في اليوم التالي.", "P07", 0, "proposed"),
        (12, 20, "ادّعاء بإهمال متابعة طلب عميل — تبيّن بعد التحقيق أن الطلب أُغلق في موعده.", "قدّم سجل المتابعة الذي يثبت إغلاق الطلب.", "", 0, "closed"),
    ]
    for idx, ago, desc, statement, rcode, days, outcome in cases:
        if idx >= len(ids):
            continue
        e = ids[idx]
        r = ctx.tryc(hr_disc.api_case_add, hr_disc.CaseIn(employee_id=e["id"], incident_date=_iso(today - dt.timedelta(days=ago)), description=desc, witnesses="مسؤول الموقع وزميلان"), u=hr_u)
        if not r:
            continue
        did = r["id"]
        ctx.add("cases")
        if statement:
            ctx.tryc(hr_disc.api_statement, did, hr_disc.StatementIn(statement=statement), u=hr_u)
        if outcome == "open":
            continue
        if outcome == "closed":
            ctx.tryc(hr_disc.api_close, did, hr_disc.CloseIn(note="لم يثبت ما نُسب إلى الموظف؛ أُغلقت القضية بلا جزاء"), u=hr_u)
            continue
        kind = next(b[3] for b in BYLAW if b[0] == rcode)
        ctx.tryc(hr_disc.api_propose, did, hr_disc.ProposeIn(rule_id=rule[rcode], penalty_days=days, apply_period=apply_period if kind == "deduction" else ""), u=hr_u)
        if outcome == "proposed":
            continue
        ctx.tryc(hr_disc.api_issue, did, u=_as(admin))   # a different person issues
        if outcome.startswith("appeal"):
            ctx.tryc(hr_disc.api_appeal, did, hr_disc.AppealIn(text="أطلب إعادة النظر في الجزاء لأن الواقعة لم تتكرر منذ ذلك الحين وللظروف التي شرحتها في أقوالي."), u=_as(_emp_user(e)))
            ctx.tryc(hr_disc.api_appeal_decision, did, hr_disc.DecisionIn(decision="upheld" if outcome.endswith("upheld") else "revoked"), u=_as(hr_u))


# ----------------------------------------------------------------------------------------------------------------------- appraisals
def _appraisals(ctx: Ctx, P: dict, keys: dict) -> None:
    if _q(ctx, "SELECT 1 FROM appraisal_cycles LIMIT 1"):
        return
    hr_u, today, rnd = ctx.act("hr"), ctx.today, ctx.rnd
    emps = _emps(ctx, P)
    by_id = {v["id"]: v for v in emps.values()}
    dkey = {r["id"]: k for k, n in P["departments"] for r in _q(ctx, "SELECT id FROM departments WHERE name=?", (n,))}
    comps = hr_perf.DEFAULT_COMPETENCIES

    def goals_for(e):
        titles = GOALS.get(dkey.get(e["department_id"]), GOALS["hr"])
        weights = (40, 35, 25)
        return [hr_perf.GoalIn(title=t, weight=w, self_score=rnd.randint(3, 5)) for t, w in zip(titles, weights)]

    def walk(cid: int, upto: str) -> None:
        """Drive every appraisal of the cycle as far as `upto` (self | manager | hr | final | ack) allows, varying how far each person got."""
        apps = _q(ctx, "SELECT id, employee_id, reviewer_id, status FROM appraisals WHERE cycle_id=? ORDER BY id", (cid,))
        for i, a in enumerate(apps):
            e = by_id[a["employee_id"]]
            stop = upto if upto in ("ack",) else ("ack", "final", "final", "hr", "manager", "self")[i % 6]
            ctx.tryc(hr_perf.api_self_review, a["id"], hr_perf.SelfIn(goals=goals_for(e), competencies=[hr_perf.CompIn(name=n, self_score=rnd.randint(3, 5)) for n in comps],
                                                                      self_comment="أنجزت معظم الأهداف المطلوبة وأطمح لتطوير مهاراتي القيادية.", submit=stop != "self"), u=_as(_emp_user(e)))
            if stop == "self":
                continue
            mgr = by_id.get(a["reviewer_id"])
            gs, cs = [rnd.randint(3, 5) for _ in range(3)], [rnd.randint(3, 5) for _ in comps]
            review = hr_perf.MgrIn(goal_scores=gs, competency_scores=cs, manager_comment="أداء جيد ويلتزم بالمواعيد، ويحتاج إلى مزيد من المبادرة في تطوير الإجراءات.", submit=stop != "manager")
            if mgr:
                ctx.tryc(hr_perf.api_manager_review, a["id"], review, u=_as(_emp_user(mgr)))
            else:
                ctx.tryc(hr_perf.api_hr_review, a["id"], review, u=_as(hr_u))
            if stop in ("manager", "hr"):
                continue
            dec = rnd.choice(("raise", "no_action", "training", "promotion", "no_action"))
            ctx.tryc(hr_perf.api_finalize, a["id"], hr_perf.FinalIn(decision=dec, hr_comment="اعتُمد التقييم وفق مراجعة المدير ومعايير الدورة."), u=_as(ctx.user("admin")))
            if stop == "final":
                continue
            ctx.tryc(hr_perf.api_ack, a["id"], hr_perf.AckIn(comment=""), u=_as(_emp_user(e)))

    y = today.year
    c1 = ctx.tryc(hr_perf.api_cycle_add, hr_perf.CycleIn(name=f"تقييم الأداء السنوي {y - 1}", year=y - 1, start_date=f"{y - 1}-12-01", end_date=f"{y}-02-28"), u=hr_u)
    if c1:
        ctx.tryc(hr_perf.api_cycle_open, c1["id"], u=hr_u)
        walk(c1["id"], "ack")
        ctx.tryc(hr_perf.api_cycle_close, c1["id"], hr_perf.CloseIn(force=True), u=hr_u)
    c2 = ctx.tryc(hr_perf.api_cycle_add, hr_perf.CycleIn(name=f"تقييم منتصف العام {y}", year=y, start_date=f"{y}-07-01", end_date=_iso(today + dt.timedelta(days=20))), u=hr_u)
    if c2:
        ctx.tryc(hr_perf.api_cycle_open, c2["id"], u=hr_u)
        walk(c2["id"], "mixed")
    ctx.add("appraisal_cycles", int(bool(c1)) + int(bool(c2)))


# ----------------------------------------------------------------------------------------------------------------------- training
def _training(ctx: Ctx, P: dict, keys: dict) -> None:
    if _q(ctx, "SELECT 1 FROM training_courses LIMIT 1"):
        return
    hr_u, today, rnd = ctx.act("hr"), ctx.today, ctx.rnd
    cid = {}
    for title, provider, hours, months, mand in COURSES:
        r = ctx.tryc(hr_perf.api_course_add, hr_perf.CourseIn(title=title, provider=provider, hours=hours, cert_valid_months=months, mandatory=bool(mand)), u=hr_u)
        if r:
            cid[title] = r["id"]
    emps = [e for e in _emps(ctx, P).values() if e["status"] != "terminated"]
    n = 0
    for i, e in enumerate(emps):
        for j, (title, provider, hours, months, mand) in enumerate(COURSES[:3]):     # the mandatory courses: most are valid, a few expire soon or have expired
            if title not in cid:
                continue
            if (i + j) % 7 == 0:
                continue  # never taken (the compliance table shows the gap)
            ago = rnd.randint(30, 330) if (i + j) % 5 else rnd.randint(350, 400) if months == 12 else rnd.randint(30, 300)
            r = ctx.tryc(hr_perf.api_record_add, hr_perf.RecordIn(course_id=cid[title], employee_id=e["id"], status="completed", completed_on=_iso(today - dt.timedelta(days=ago)),
                                                                   score=float(rnd.randint(72, 98)), certificate_no=f"CRT-{rnd.randint(10000, 99999)}"), u=hr_u)
            n += 1 if r else 0
        if i % 3 == 0:
            title = COURSES[3 + (i % 5)][0]
            ctx.tryc(hr_perf.api_record_add, hr_perf.RecordIn(course_id=cid[title], employee_id=e["id"], status="completed", completed_on=_iso(today - dt.timedelta(days=rnd.randint(40, 200))),
                                                               score=float(rnd.randint(75, 99)), certificate_no=f"CRT-{rnd.randint(10000, 99999)}"), u=hr_u)
        if i % 4 == 1:
            title = COURSES[3 + ((i + 1) % 5)][0]
            ctx.tryc(hr_perf.api_record_add, hr_perf.RecordIn(course_id=cid[title], employee_id=e["id"], status="planned", planned_on=_iso(today + dt.timedelta(days=rnd.randint(10, 70)))), u=hr_u)
        if i == 5:
            ctx.tryc(hr_perf.api_record_add, hr_perf.RecordIn(course_id=cid[COURSES[4][0]], employee_id=e["id"], status="no_show", planned_on=_iso(today - dt.timedelta(days=20)), note="لم يحضر لظرف عمل طارئ"), u=hr_u)
    ctx.add("training_records", n)
