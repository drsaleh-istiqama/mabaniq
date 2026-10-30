"""Mabaniq 0.28.0 — the ready reports and datasets of the accounting and HR modules (design §6), merged into `reports.READY` / `reports.DATASETS`.

Leasing registered its own in 0.22.0 (`leasing_reports`); this adds the leasing datasets for the custom builder, the accounting statements and ledgers, and the people reports.
Every report is filtered twice: by the module it belongs to (`READY_MODULE` / `DATASET_MODULE` — off ⟵ 404, as for any path of that module) and by the permission it needs.
The permissions below (`STRICT`) are never opened by the broad `reports` permission: someone who may build sales reports does not thereby read the books or the people file.
Payroll figures stay with `hr_payroll` and are never mailed (`NO_MAIL`).
"""
from __future__ import annotations

import datetime as dt
from collections import OrderedDict

from .common import rows, today

STRICT = frozenset({"hr", "hr_payroll", "accounting"})   # held in person (or by `admin`) — the `reports` permission does not stand in for them
NO_MAIL_READY = frozenset({"hr_payroll"})                # money-per-person reports are not e-mailed on a schedule
NO_MAIL_DATASETS = frozenset({"payslips", "journal_lines"})   # journal lines carry per-person loan and settlement entries


def _tbl(title, cols, data):
    return {"title": title, "columns": [{"key": k, "label": lab, "type": t} for k, lab, t in cols], "rows": data}


def _r3(v) -> float:
    return round(float(v or 0), 3)


def _day(params: dict) -> str:
    return (str(params.get("to") or today().isoformat()))[:10]


def _month(params: dict) -> str:
    m = (str(params.get("month") or params.get("to") or today().isoformat()))[:7]
    return m if len(m) == 7 else today().isoformat()[:7]


def clean_params(params: dict) -> dict:
    """Dates are YYYY-MM-DD (or YYYY-MM for a month) and a project is a number — anything else is a 400 here instead of a 500 deep inside a report (0.28.1)."""
    from fastapi import HTTPException
    out = {}
    for k, v in (params or {}).items():
        if v in (None, ""):
            continue
        s = str(v)
        if k in ("from", "to"):
            try:
                dt.date.fromisoformat(s[:10]) if len(s) >= 10 else dt.date.fromisoformat(s[:7] + "-01")
            except ValueError:
                raise HTTPException(400, "التاريخ غير صالح — الصيغة YYYY-MM-DD") from None
        elif k == "month":
            try:
                dt.date.fromisoformat(s[:7] + "-01")
            except ValueError:
                raise HTTPException(400, "الشهر غير صالح — الصيغة YYYY-MM") from None
        elif k == "project_id" and not s.isdigit():
            raise HTTPException(400, "المشروع غير صالح")
        out[k] = v
    return out


# ----------------------------------------------------------------------------------------------------- accounting
def _acc_off(key, title, c):
    from . import ledger
    if ledger.start_date(c):
        return None
    return {"key": key, "title": title, "subtitle": "المحاسبة غير مفعَّلة بعد", "kpis": [], "charts": [], "tables": [], "notes": ["فعّل المحاسبة من «المحاسبة ← الإعداد» بتاريخ بدء لتظهر الأرقام."]}


def r_acc_trial(c, params):
    from .accounting import api_trial_balance
    off = _acc_off("acc_trial", "ميزان المراجعة", c)
    if off:
        return off
    to = _day(params)
    frm = (params.get("from") or f"{to[:4]}-01-01")[:10]
    tb = api_trial_balance(to=to, frm=frm, cc=None, csv_=0)
    leaf = [a for a in tb["accounts"] if a["postable"]]
    t = tb["totals"]
    return {"key": "acc_trial", "title": "ميزان المراجعة", "subtitle": f"من {tb['from']} إلى {tb['to']}",
            "kpis": [{"label": "مجموع المدين", "value": t["debit"], "format": "money"}, {"label": "مجموع الدائن", "value": t["credit"], "format": "money"},
                     {"label": "فرق الميزان", "value": _r3(t["debit"] - t["credit"]), "format": "money"}],
            "charts": [],
            "tables": [_tbl("الحسابات", [("code", "الرمز", "text"), ("name", "الحساب", "text"), ("opening", "افتتاحي", "money"), ("debit", "مدين", "money"), ("credit", "دائن", "money"), ("closing", "ختامي", "money")], leaf)],
            "notes": ["الميزان يُحسب من القيود المرحَّلة فقط؛ الفرق يجب أن يكون صفرًا." + ("" if tb["balanced"] else " تنبيه: الميزان غير متوازن — راجع القيود.")]}


def _statement_doc(key, title, stmt, kpis, notes=()):
    data = [{"label": ("   " * r["level"]) + str(r["cells"][0]), "amount": r["cells"][1] if r["cells"][1] != "" else None, "bold": r["bold"]} for r in stmt["rows"]]
    return {"key": key, "title": title, "subtitle": stmt.get("as_of") and f"في {stmt['as_of']}" or f"من {stmt.get('from')} إلى {stmt.get('to')}",
            "kpis": kpis, "charts": [], "tables": [_tbl(title, [("label", "البند", "text"), ("amount", "المبلغ (ر.ع)", "money")], data)], "notes": list(notes)}


def r_acc_income(c, params):
    from .acc_reports import build
    off = _acc_off("acc_income", "قائمة الدخل", c)
    if off:
        return off
    to = _day(params)
    s = build(c, "income_statement", (params.get("from") or f"{to[:4]}-01-01")[:10], to)
    return _statement_doc("acc_income", "قائمة الدخل", s, [{"label": "الإيرادات", "value": s["revenue"], "format": "money"}, {"label": "المصروفات", "value": s["expenses"], "format": "money"},
                                                           {"label": "صافي الربح (الخسارة)", "value": s["net"], "format": "money"}], [n["text"] for n in s.get("notes", [])])


def r_acc_balance(c, params):
    from .acc_reports import build
    off = _acc_off("acc_balance", "قائمة المركز المالي", c)
    if off:
        return off
    s = build(c, "balance_sheet", None, _day(params))
    return _statement_doc("acc_balance", "قائمة المركز المالي", s, [{"label": "الأصول", "value": s["assets"], "format": "money"}, {"label": "الالتزامات", "value": s["liabilities"], "format": "money"},
                                                                    {"label": "حقوق الملكية", "value": s["equity"], "format": "money"}, {"label": "فرق المعادلة", "value": s["difference"], "format": "money"}],
                          ["الأصول = الالتزامات + حقوق الملكية؛ الفرق صفر في دفاتر متوازنة."])


def r_acc_payables(c, params):
    from .acc_ap import api_ap_aging
    off = _acc_off("acc_payables", "أعمار ذمم الموردين", c)
    if off:
        return off
    a = api_ap_aging(as_of=_day(params))
    names = {"current": "غير مستحق", "d1_30": "1–30 يومًا", "d31_60": "31–60 يومًا", "d61_90": "61–90 يومًا", "d90p": "أكثر من 90 يومًا"}
    return {"key": "acc_payables", "title": "أعمار ذمم الموردين", "subtitle": f"في {a['as_of']}",
            "kpis": [{"label": "إجمالي المستحق للموردين", "value": a["total"], "format": "money"}, {"label": "عدد الفواتير المفتوحة", "value": len(a["items"])}],
            "charts": [{"type": "bar", "title": "بحسب العمر", "labels": list(names.values()), "series": [{"name": "المبلغ", "data": [a["buckets"][k] for k in names]}], "format": "money"}],
            "tables": [_tbl("الفواتير المفتوحة", [("number", "الرقم", "text"), ("vendor", "المورد", "text"), ("due_date", "الاستحقاق", "date"), ("outstanding", "المتبقي", "money"), ("days_late", "أيام التأخير", "int")], a["items"])],
            "notes": ["العمر بالأيام بعد تاريخ الاستحقاق؛ الفاتورة بلا استحقاق تُعمَّر من تاريخها."]}


def r_acc_vat(c, params):
    from .acc_assets import vat_compute
    off = _acc_off("acc_vat", "إقرار ضريبة القيمة المضافة", c)
    if off:
        return off
    d = dt.date.fromisoformat(_day(params))
    v = vat_compute(c, d.year, (d.month - 1) // 3 + 1)
    labels = {"sales_standard": "مبيعات خاضعة بالنسبة الأساسية", "sales_zero": "مبيعات بنسبة صفر", "sales_exempt": "مبيعات معفاة", "purchases_standard": "مشتريات خاضعة بالنسبة الأساسية",
              "purchases_zero": "مشتريات بنسبة صفر", "purchases_exempt": "مشتريات معفاة", "output_vat": "ضريبة المخرجات", "input_vat": "ضريبة المدخلات"}
    return {"key": "acc_vat", "title": "إقرار ضريبة القيمة المضافة", "subtitle": f"{v['year']} — الربع {v['quarter']} ({v['from']} ← {v['to']})",
            "kpis": [{"label": "ضريبة المخرجات", "value": v["output_vat"], "format": "money"}, {"label": "ضريبة المدخلات", "value": v["input_vat"], "format": "money"},
                     {"label": "الصافي المستحق (السالب = استرداد)", "value": v["net"], "format": "money"}],
            "charts": [], "tables": [_tbl("خانات الإقرار", [("box", "الخانة", "text"), ("amount", "المبلغ (ر.ع)", "money")], [{"box": labels[k], "amount": v["boxes"][k]} for k in labels])],
            "notes": list(v["warnings"]) + ([f"قُدِّم الإقرار في {v['filed'].get('filed_on') or v['filed'].get('filed_at') or '—'}"] if v["filed"] else ["لم يُقدَّم هذا الإقرار بعد."])}


# ----------------------------------------------------------------------------------------------------- people
def _active_emps(c):
    return rows(c.execute("""SELECT e.id, e.number, e.name, e.omani, e.gender, e.hire_date, e.contract_type, e.status, COALESCE(d.name,'—') department, COALESCE(p.title,'—') position
                             FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN positions p ON p.id=e.position_id WHERE e.status!='terminated' ORDER BY e.number"""))


def r_hr_headcount(c, params):
    es = _active_emps(c)
    per: dict = {}
    for e in es:
        p = per.setdefault(e["department"], {"department": e["department"], "total": 0, "omani": 0, "expat": 0, "female": 0})
        p["total"] += 1
        p["omani" if e["omani"] else "expat"] += 1
        p["female"] += 1 if e["gender"] == "female" else 0
    n = len(es)
    om = sum(1 for e in es if e["omani"])
    yrs = [(today() - dt.date.fromisoformat(e["hire_date"][:10])).days / 365.25 for e in es if e["hire_date"]]
    ct = {"permanent": "دائم", "fixed": "محدد المدة", "part": "جزئي"}
    by_ct: dict = {}
    for e in es:
        k = ct.get(e["contract_type"], e["contract_type"])
        by_ct[k] = by_ct.get(k, 0) + 1
    hires = c.execute("SELECT COUNT(*) FROM employees WHERE hire_date>=?", (f"{today().year}-01-01",)).fetchone()[0]
    left = c.execute("SELECT COUNT(*) FROM employees WHERE terminated_on>=?", (f"{today().year}-01-01",)).fetchone()[0]
    return {"key": "hr_headcount", "title": "القوى العاملة", "subtitle": f"في {today().isoformat()}",
            "kpis": [{"label": "على رأس العمل", "value": n}, {"label": "نسبة العُمانيين", "value": round(100 * om / n, 1) if n else 0, "format": "pct"},
                     {"label": "متوسط سنوات الخدمة", "value": round(sum(yrs) / len(yrs), 1) if yrs else 0, "format": "num"},
                     {"label": "تعيينات هذه السنة", "value": hires}, {"label": "مغادرون هذه السنة", "value": left}],
            "charts": ([{"type": "stacked", "title": "بحسب القسم", "labels": [p["department"] for p in per.values()], "series": [{"name": "عُمانيون", "data": [p["omani"] for p in per.values()]},
                                                                                                                          {"name": "وافدون", "data": [p["expat"] for p in per.values()]}], "format": "num"},
                        {"type": "pie", "title": "نوع العقد", "labels": list(by_ct), "series": [{"name": "الموظفون", "data": list(by_ct.values())}], "format": "num"}] if es else []),
            "tables": [_tbl("بحسب القسم", [("department", "القسم", "text"), ("total", "الإجمالي", "int"), ("omani", "عُمانيون", "int"), ("expat", "وافدون", "int"), ("female", "إناث", "int")], list(per.values()))],
            "notes": ["نسبة العُمانيين تُحسب من الملف؛ النسبة المستهدفة قانونًا ليست مُدخَلة في المنصة (قرار ل43) فلا تُقارَن بها."]}


def r_hr_leave(c, params):
    from . import hr_leave
    year = int(_day(params)[:4])
    data = []
    for e in rows(c.execute("SELECT * FROM employees WHERE status!='terminated' ORDER BY number")):
        dep = c.execute("SELECT name FROM departments WHERE id=?", (e["department_id"],)).fetchone() if e["department_id"] else None
        for b in hr_leave.balances_of(c, e, year):
            data.append({"number": e["number"], "name": e["name"], "department": dep["name"] if dep else "—", "type": b["name"], "entitled": b["entitled"] + b["carried"] + b["adjusted"],
                         "taken": b["taken"], "pending": b["pending"], "remaining": b["remaining"]})
    c.commit()   # the balance rows are refreshed as a side effect of reading them
    ann = [d for d in data if d["type"] and "سنوية" in d["type"]]
    return {"key": "hr_leave", "title": "أرصدة الإجازات", "subtitle": f"سنة {year}",
            "kpis": [{"label": "موظفون", "value": len({d['number'] for d in data})}, {"label": "أيام مستحقة غير مستهلكة (كل الأنواع)", "value": _r3(sum(d['remaining'] for d in data)), "format": "num"},
                     {"label": "أيام قيد الطلب", "value": _r3(sum(d['pending'] for d in data)), "format": "num"}],
            "charts": [{"type": "bar", "title": "المتبقي من الإجازة السنوية", "labels": [d["name"] for d in ann[:30]], "series": [{"name": "المتبقي", "data": [d["remaining"] for d in ann[:30]]}], "format": "num"}] if ann else [],
            "tables": [_tbl("الأرصدة", [("number", "الرقم", "text"), ("name", "الموظف", "text"), ("department", "القسم", "text"), ("type", "النوع", "text"), ("entitled", "المستحق", "num"),
                                       ("taken", "المستهلك", "num"), ("pending", "قيد الطلب", "num"), ("remaining", "المتبقي", "num")], data)],
            "notes": ["الرصيد مشتق من الطلبات المعتمدة؛ قيم الأنواع مبدئية حتى يعتمد المالك قيمه (ل37)."]}


def r_hr_expiry(c, params):
    from .hr import expiry_items
    items = expiry_items(c, today(), 90)
    lv = {"expired": "منتهٍ", "critical": "حرج (≤30)", "soon": "قريب (≤90)", "ok": "سارٍ"}
    for i in items:
        i["level_label"] = lv.get(i["level"], i["level"])
    return {"key": "hr_expiry", "title": "انتهاء الوثائق والشهادات", "subtitle": "ما ينتهي خلال 90 يومًا أو انتهى",
            "kpis": [{"label": "منتهية", "value": sum(1 for i in items if i["level"] == "expired")}, {"label": "تنتهي خلال 30 يومًا", "value": sum(1 for i in items if i["level"] == "critical")},
                     {"label": "تنتهي خلال 90 يومًا", "value": sum(1 for i in items if i["level"] == "soon")}],
            "charts": [], "tables": [_tbl("البنود", [("number", "الرقم", "text"), ("name", "الموظف", "text"), ("label", "البند", "text"), ("date", "تاريخ الانتهاء", "date"), ("days_left", "الأيام المتبقية", "int"),
                                                    ("level_label", "الحالة", "text")], items)],
            "notes": ["الوثيقة الأحدث من كل نوع هي المعتدّ بها؛ شهادات التدريب وعقود المدة المحددة ونهاية التجربة تدخل في القائمة نفسها."]}


def r_hr_attendance(c, params):
    month = _month(params)
    data = rows(c.execute("""SELECT e.number, e.name, SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) present, SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) late,
                             SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) absent, SUM(CASE WHEN a.status='leave' THEN 1 ELSE 0 END) leave_days,
                             SUM(CASE WHEN a.status='remote' THEN 1 ELSE 0 END) remote FROM attendance a JOIN employees e ON e.id=a.employee_id
                             WHERE a.day LIKE ? GROUP BY e.number, e.name ORDER BY e.number""", (month + "%",)))
    tot = {k: sum(d[k] or 0 for d in data) for k in ("present", "late", "absent", "leave_days", "remote")}
    days = sum(tot.values())
    return {"key": "hr_attendance", "title": "الحضور الشهري", "subtitle": f"شهر {month}",
            "kpis": [{"label": "أيام حضور", "value": tot["present"] + tot["remote"] + tot["late"]}, {"label": "تأخير", "value": tot["late"]}, {"label": "غياب", "value": tot["absent"]}, {"label": "إجازات", "value": tot["leave_days"]},
                     {"label": "نسبة الغياب", "value": round(100 * tot["absent"] / days, 1) if days else 0, "format": "pct"}],
            "charts": [{"type": "bar", "title": "بحسب الحالة", "labels": ["حضور", "عن بُعد", "تأخير", "غياب", "إجازة"], "series": [{"name": "أيام", "data": [tot["present"], tot["remote"], tot["late"], tot["absent"], tot["leave_days"]]}], "format": "num"}],
            "tables": [_tbl("بحسب الموظف", [("number", "الرقم", "text"), ("name", "الموظف", "text"), ("present", "حضور", "int"), ("remote", "عن بُعد", "int"), ("late", "تأخير", "int"), ("absent", "غياب", "int"),
                                           ("leave_days", "إجازة", "int")], data)],
            "notes": ["من سجل الحضور المُدخَل أو المستورد؛ الأيام التي لم تُسجَّل لا تُحتسب غيابًا."]}


def r_hr_training(c, params):
    from .hr_perf import api_compliance
    items = api_compliance()
    st = {"valid": "ساري", "expiring": "ينتهي قريبًا", "expired": "منتهٍ", "missing": "لم تُؤخذ"}
    per: dict = {}
    for i in items:
        p = per.setdefault(i["course"], {"course": i["course"], "valid": 0, "expiring": 0, "expired": 0, "missing": 0})
        p[i["state"]] += 1
    lacking = [dict(i, state_label=st[i["state"]]) for i in items if i["state"] != "valid"]
    n = len(items)
    return {"key": "hr_training", "title": "الامتثال التدريبي", "subtitle": "الدورات الإلزامية لكل موظف على رأس العمل",
            "kpis": [{"label": "نسبة الامتثال", "value": round(100 * sum(1 for i in items if i["state"] in ("valid", "expiring")) / n, 1) if n else 0, "format": "pct"},
                     {"label": "منتهية", "value": sum(1 for i in items if i["state"] == "expired")}, {"label": "لم تُؤخذ", "value": sum(1 for i in items if i["state"] == "missing")}],
            "charts": [{"type": "stacked", "title": "بحسب الدورة", "labels": list(per), "series": [{"name": st[k], "data": [p[k] for p in per.values()]} for k in st], "format": "num"}] if per else [],
            "tables": [_tbl("من ينقصه شيء", [("number", "الرقم", "text"), ("name", "الموظف", "text"), ("course", "الدورة", "text"), ("state_label", "الحالة", "text"), ("days_left", "الأيام المتبقية", "int")], lacking)],
            "notes": ["تُحسب الدورات المعلَّمة «إلزامية» فقط."]}


def r_hr_payroll(c, params):
    data = rows(c.execute("""SELECT period, status, headcount, gross, net, pasi_employee, pasi_employer FROM payroll_runs WHERE status IN ('approved','paid') ORDER BY period DESC LIMIT 12"""))
    data.reverse()
    for d in data:
        d["cost"] = _r3(d["gross"] + d["pasi_employer"])
    last = data[-1] if data else None
    return {"key": "hr_payroll", "title": "ملخص الرواتب", "subtitle": "آخر 12 مسيّرًا معتمدًا",
            "kpis": [{"label": "إجمالي آخر مسيّر", "value": last["gross"] if last else 0, "format": "money"}, {"label": "صافي آخر مسيّر", "value": last["net"] if last else 0, "format": "money"},
                     {"label": "كلفة آخر مسيّر على المنشأة", "value": last["cost"] if last else 0, "format": "money"}, {"label": "العدد", "value": last["headcount"] if last else 0}],
            "charts": [{"type": "line", "title": "الإجمالي والصافي", "labels": [d["period"] for d in data], "series": [{"name": "الإجمالي", "data": [d["gross"] for d in data]}, {"name": "الصافي", "data": [d["net"] for d in data]}], "format": "money"}] if data else [],
            "tables": [_tbl("المسيّرات", [("period", "الشهر", "text"), ("headcount", "العدد", "int"), ("gross", "الإجمالي", "money"), ("pasi_employee", "تأمينات الموظف", "money"), ("pasi_employer", "تأمينات المنشأة", "money"),
                                          ("net", "الصافي", "money"), ("cost", "الكلفة على المنشأة", "money")], data)],
            "notes": ["إجماليات فقط، لا أسماء. لا يُرسل هذا التقرير بالبريد."]}


# ----------------------------------------------------------------------------------------------------- datasets for the custom builder
LSTATUS = {"draft": "مسودة", "active": "ساري", "expired": "منتهٍ", "terminated": "مُنهى", "cancelled": "ملغى"}
_L = "FROM leases l JOIN units u ON u.id=l.unit_id JOIN projects p ON p.id=u.project_id JOIN tenants_l t ON t.id=l.tenant_id"

DATASETS_EXT: dict[str, dict] = {
    "leases": {"label": "عقود الإيجار", "perm": "leasing",
               "sql": f"SELECT l.id, l.number, l.status, l.start, l.\"end\" AS end_date, l.annual_rent, l.frequency, l.deposit, p.name AS project, u.code, t.name AS tenant {_L} WHERE l.status<>'draft'",
               "columns": OrderedDict([("number", ("رقم العقد", "text")), ("status", ("الحالة", "enum", LSTATUS)), ("start", ("البداية", "date")), ("end_date", ("النهاية", "date")), ("annual_rent", ("الإيجار السنوي", "money")),
                                       ("frequency", ("عدد الدفعات في السنة", "int")), ("deposit", ("التأمين", "money")), ("project", ("العقار", "text")), ("code", ("الوحدة", "text")), ("tenant", ("المستأجر", "text"))])},
    "rent_dues": {"label": "استحقاقات الإيجار", "perm": "leasing",
                  "sql": """SELECT d.id, d.due, d.amount, d.paid, d.amount-d.paid AS outstanding, COALESCE(d.kind,'rent') AS kind, d.label, l.number, p.name AS project, u.code, t.name AS tenant
                             FROM rent_dues d JOIN leases l ON l.id=d.lease_id JOIN units u ON u.id=l.unit_id JOIN projects p ON p.id=u.project_id JOIN tenants_l t ON t.id=l.tenant_id WHERE l.status<>'draft'""",
                  "columns": OrderedDict([("due", ("الاستحقاق", "date")), ("kind", ("النوع", "enum", {"rent": "إيجار", "deposit": "تأمين", "fee": "رسوم", "service": "خدمة", "other": "أخرى"})), ("label", ("البيان", "text")),
                                          ("amount", ("المبلغ", "money")), ("paid", ("المسدَّد", "money")), ("outstanding", ("المتبقي", "money")), ("number", ("العقد", "text")), ("project", ("العقار", "text")),
                                          ("code", ("الوحدة", "text")), ("tenant", ("المستأجر", "text"))])},
    "rent_payments": {"label": "مقبوضات الإيجار", "perm": "leasing",
                      "sql": """SELECT pm.id, pm.paid_on, pm.amount, pm.method, pm.receipt_no, l.number, p.name AS project, u.code, t.name AS tenant
                                FROM rent_payments pm JOIN leases l ON l.id=pm.lease_id JOIN units u ON u.id=l.unit_id JOIN projects p ON p.id=u.project_id JOIN tenants_l t ON t.id=l.tenant_id""",
                      "columns": OrderedDict([("paid_on", ("تاريخ القبض", "date")), ("amount", ("المبلغ", "money")), ("method", ("الطريقة", "enum", {"cash": "نقدًا", "transfer": "تحويل", "cheque": "شيك", "card": "بطاقة", "other": "أخرى"})),
                                              ("receipt_no", ("الإيصال", "text")), ("number", ("العقد", "text")), ("project", ("العقار", "text")), ("code", ("الوحدة", "text")), ("tenant", ("المستأجر", "text"))])},
    "journal_lines": {"label": "أسطر القيود", "perm": "accounting",
                      "sql": """SELECT l.id, j.number, j.jdate, j.memo, j.kind, a.code AS account_code, a.name AS account, a.type AS account_type, l.debit, l.credit, COALESCE(cc.name,'') AS cost_center
                                FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id JOIN acc_accounts a ON a.id=l.account_id LEFT JOIN acc_cost_centers cc ON cc.id=l.cost_center_id
                                WHERE j.status IN ('posted','reversed')""",
                      "columns": OrderedDict([("jdate", ("تاريخ القيد", "date")), ("number", ("رقم القيد", "text")), ("memo", ("البيان", "text")), ("kind", ("النوع", "enum", {"manual": "يدوي", "auto": "آلي", "opening": "افتتاحي", "reversal": "عكسي"})),
                                              ("account_code", ("رمز الحساب", "text")), ("account", ("الحساب", "text")), ("account_type", ("نوع الحساب", "enum", {"asset": "أصول", "liability": "التزامات", "equity": "ملكية", "revenue": "إيرادات", "expense": "مصروفات"})),
                                              ("debit", ("مدين", "money")), ("credit", ("دائن", "money")), ("cost_center", ("مركز التكلفة", "text"))])},
    "employees": {"label": "الموظفون", "perm": "hr",
                  "sql": """SELECT e.id, e.number, e.name, e.nationality, e.omani, e.gender, e.hire_date, e.contract_type, e.status, COALESCE(d.name,'') AS department, COALESCE(p.title,'') AS position
                            FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN positions p ON p.id=e.position_id""",
                  "columns": OrderedDict([("number", ("الرقم", "text")), ("name", ("الاسم", "text")), ("department", ("القسم", "text")), ("position", ("المسمى", "text")), ("nationality", ("الجنسية", "text")), ("omani", ("عُماني", "bool")),
                                          ("gender", ("الجنس", "enum", {"male": "ذكر", "female": "أنثى"})), ("hire_date", ("تاريخ التعيين", "date")),
                                          ("contract_type", ("العقد", "enum", {"permanent": "دائم", "fixed": "محدد المدة", "part": "جزئي"})), ("status", ("الحالة", "enum", {"active": "على رأس العمل", "on_leave": "في إجازة", "terminated": "منتهية خدمته"}))])},
    "leave_requests": {"label": "طلبات الإجازة", "perm": "hr",
                       "sql": """SELECT r.id, e.number, e.name, COALESCE(d.name,'') AS department, r.type_key, r.from_date, r.to_date, r.days, r.status FROM leave_requests r JOIN employees e ON e.id=r.employee_id
                                 LEFT JOIN departments d ON d.id=e.department_id""",
                       "columns": OrderedDict([("from_date", ("من", "date")), ("to_date", ("إلى", "date")), ("number", ("الرقم", "text")), ("name", ("الموظف", "text")), ("department", ("القسم", "text")), ("type_key", ("النوع", "text")),
                                               ("days", ("الأيام", "num")), ("status", ("الحالة", "enum", {"pending": "قيد الدراسة", "approved": "معتمد", "rejected": "مرفوض", "cancelled": "ملغى"}))])},
    "training": {"label": "التدريب", "perm": "hr",
                 "sql": """SELECT r.id, e.number, e.name, k.title AS course, k.mandatory, r.status, r.completed_on, r.cert_expires, r.score FROM training_records r JOIN employees e ON e.id=r.employee_id
                           JOIN training_courses k ON k.id=r.course_id""",
                 "columns": OrderedDict([("completed_on", ("تاريخ الإتمام", "date")), ("number", ("الرقم", "text")), ("name", ("الموظف", "text")), ("course", ("الدورة", "text")), ("mandatory", ("إلزامية", "bool")),
                                         ("status", ("الحالة", "enum", {"planned": "مخطط", "completed": "أُتمّ", "cancelled": "ملغى", "no_show": "لم يحضر"})), ("cert_expires", ("انتهاء الشهادة", "date")), ("score", ("الدرجة", "num"))])},
    "payslips": {"label": "قسائم الرواتب", "perm": "hr_payroll",
                 "sql": """SELECT s.id, r.period, e.number, e.name, COALESCE(d.name,'') AS department, s.basic, s.gross, s.absence_ded, s.adj_earn, s.adj_ded, s.pasi_employee, s.pasi_employer, s.loan_ded, s.net
                           FROM payslips s JOIN payroll_runs r ON r.id=s.run_id JOIN employees e ON e.id=s.employee_id LEFT JOIN departments d ON d.id=e.department_id WHERE r.status IN ('approved','paid')""",
                 "columns": OrderedDict([("period", ("الشهر", "text")), ("number", ("الرقم", "text")), ("name", ("الموظف", "text")), ("department", ("القسم", "text")), ("basic", ("الأساسي", "money")), ("gross", ("الإجمالي", "money")),
                                         ("absence_ded", ("خصم الغياب", "money")), ("adj_earn", ("إضافات", "money")), ("adj_ded", ("استقطاعات", "money")), ("pasi_employee", ("تأمينات الموظف", "money")),
                                         ("pasi_employer", ("تأمينات المنشأة", "money")), ("loan_ded", ("قسط سلفة", "money")), ("net", ("الصافي", "money"))])},
}
DATASET_MODULE_EXT = {"leases": "leasing", "rent_dues": "leasing", "rent_payments": "leasing", "journal_lines": "accounting", "employees": "hr", "leave_requests": "hr", "training": "hr", "payslips": "hr"}

READY_EXT = {
    "acc_trial": {"title": "ميزان المراجعة", "desc": "افتتاحي ومدين ودائن وختامي لكل حساب، مع فحص التوازن.", "fn": r_acc_trial, "perm": "accounting", "group": "المحاسبة", "module": "accounting"},
    "acc_income": {"title": "قائمة الدخل", "desc": "الإيرادات والمصروفات وصافي الربح للفترة.", "fn": r_acc_income, "perm": "accounting", "group": "المحاسبة", "module": "accounting"},
    "acc_balance": {"title": "قائمة المركز المالي", "desc": "الأصول والالتزامات وحقوق الملكية في تاريخ.", "fn": r_acc_balance, "perm": "accounting", "group": "المحاسبة", "module": "accounting"},
    "acc_payables": {"title": "أعمار ذمم الموردين", "desc": "ما على المنشأة للموردين بحسب عمر التأخير.", "fn": r_acc_payables, "perm": "accounting", "group": "المحاسبة", "module": "accounting"},
    "acc_vat": {"title": "إقرار ضريبة القيمة المضافة", "desc": "خانات الإقرار للربع الذي يقع فيه التاريخ المختار.", "fn": r_acc_vat, "perm": "accounting", "group": "المحاسبة", "module": "accounting"},
    "hr_headcount": {"title": "القوى العاملة", "desc": "العدد بحسب القسم والجنسية ونوع العقد، ومتوسط الخدمة.", "fn": r_hr_headcount, "perm": "hr", "group": "الموارد البشرية", "module": "hr"},
    "hr_leave": {"title": "أرصدة الإجازات", "desc": "المستحق والمستهلك والمتبقي لكل موظف ولكل نوع إجازة.", "fn": r_hr_leave, "perm": "hr", "group": "الموارد البشرية", "module": "hr"},
    "hr_expiry": {"title": "انتهاء الوثائق والشهادات", "desc": "الوثائق وعقود المدة المحددة وشهادات التدريب التي تنتهي أو انتهت.", "fn": r_hr_expiry, "perm": "hr", "group": "الموارد البشرية", "module": "hr"},
    "hr_attendance": {"title": "الحضور الشهري", "desc": "الحضور والتأخير والغياب والإجازات لكل موظف في الشهر.", "fn": r_hr_attendance, "perm": "hr", "group": "الموارد البشرية", "module": "hr"},
    "hr_training": {"title": "الامتثال التدريبي", "desc": "الدورات الإلزامية: من أتمّها ومن انتهت شهادته ومن لم يأخذها.", "fn": r_hr_training, "perm": "hr", "group": "الموارد البشرية", "module": "hr"},
    "hr_payroll": {"title": "ملخص الرواتب", "desc": "إجماليات آخر 12 مسيّرًا معتمدًا (بلا أسماء) — لمسؤول الرواتب فقط.", "fn": r_hr_payroll, "perm": "hr_payroll", "group": "الموارد البشرية", "module": "hr"},
}


def register(ready, ready_module, datasets, dataset_module) -> None:
    for k, v in READY_EXT.items():
        ready[k] = {kk: vv for kk, vv in v.items() if kk != "module"}
        ready_module[k] = v["module"]
    datasets.update(DATASETS_EXT)
    dataset_module.update(DATASET_MODULE_EXT)


def mail_blocked(kind: str, ref: str | None, spec: dict | None) -> bool:
    """A scheduled e-mail must never carry per-person money: payroll reports and the payslip dataset are refused."""
    if kind == "ready":
        return ref in NO_MAIL_READY
    return bool(spec and spec.get("dataset") in NO_MAIL_DATASETS)


def readable(d: dict, perms, ready: dict, datasets: dict) -> bool:
    """May this viewer see that this saved report / schedule exists? Only if they could run it — the payroll officer does not list the books' reports (0.28.1)."""
    import json as _json
    ps = set(perms)
    if "admin" in ps:
        return True
    if d["kind"] == "ready":
        r = ready.get(d["ref"])
        return bool(r) and (r["perm"] in ps or (r["perm"] not in STRICT and "reports" in ps))
    try:
        ds = datasets.get((_json.loads(d["spec"]) or {}).get("dataset"))
    except Exception:  # noqa: BLE001
        return False
    return bool(ds) and (ds["perm"] in ps or (ds["perm"] not in STRICT and "reports" in ps))


__all__ = ["register", "mail_blocked", "STRICT"]
