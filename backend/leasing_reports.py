"""Mabaniq 0.22.0 — the ready reports of the leasing module (design §3.5), registered into `reports.READY` (same shape: kpis / charts / tables / notes).

Monthly rent report · occupancy and yield per project · arrears ageing · leases ending within 90 days · post-dated cheques · owners' monthly figures.
Every figure comes from the ledgers (`rent_payments`, `rent_dues`, `property_expenses`, `owner_statements` formulas) — nothing is estimated.
"""
from __future__ import annotations

import datetime as dt

from .common import rows, today
from .leasing import METHOD_LABEL, _units_state, aging, r3
from .leasing_mgmt import statement_calc


def _tbl(title, cols, data):
    return {"title": title, "columns": [{"key": k, "label": lab, "type": t} for k, lab, t in cols], "rows": data}


def _month(params: dict) -> str:
    m = (params.get("month") or params.get("to") or today().isoformat())[:7]
    return m if len(m) == 7 else today().isoformat()[:7]


def r_monthly(c, params):
    month = _month(params)
    due = rows(c.execute("""SELECT u.code unit, t.name tenant, SUM(d.amount) expected FROM rent_dues d JOIN leases l ON l.id=d.lease_id JOIN units u ON u.id=l.unit_id
                             JOIN tenants_l t ON t.id=l.tenant_id WHERE d.due LIKE ? AND COALESCE(d.kind,'rent')<>'deposit' AND l.status<>'draft' GROUP BY u.code, t.name ORDER BY u.code""", (month + "%",)))
    col = {r["unit"]: r["c"] for r in c.execute("""SELECT u.code unit, SUM(p.amount) c FROM rent_payments p JOIN leases l ON l.id=p.lease_id JOIN units u ON u.id=l.unit_id
                                                     JOIN rent_dues d ON d.id=p.due_id WHERE p.paid_on LIKE ? AND COALESCE(d.kind,'rent')<>'deposit' GROUP BY u.code""", (month + "%",)).fetchall()}
    for r in due:
        r["expected"], r["collected"] = r3(r["expected"]), r3(col.pop(r["unit"], 0))
        r["gap"] = r3(r["expected"] - r["collected"])
    for unit, amount in col.items():  # money received this month for dues of other months (arrears / advance)
        due.append({"unit": unit, "tenant": "—", "expected": 0.0, "collected": r3(amount), "gap": r3(-amount)})
    by_method: dict = {}
    for r in c.execute("""SELECT p.method, SUM(p.amount) a FROM rent_payments p JOIN rent_dues d ON d.id=p.due_id WHERE p.paid_on LIKE ? AND COALESCE(d.kind,'rent')<>'deposit'
                          GROUP BY p.method""", (month + "%",)).fetchall():
        by_method[METHOD_LABEL.get(r["method"], "غير موثَّقة")] = r3(r["a"])
    expected, collected = r3(sum(r["expected"] for r in due)), r3(sum(r["collected"] for r in due))
    exp = r3(c.execute("SELECT COALESCE(SUM(amount),0) FROM property_expenses WHERE spent_on LIKE ? AND status='posted'", (month + "%",)).fetchone()[0])
    owners = c.execute("SELECT id FROM owners WHERE COALESCE(active,1)=1").fetchall()
    stm = [statement_calc(c, o["id"], month) for o in owners]
    commission, net = r3(sum(s["commission"] for s in stm)), r3(sum(s["net"] for s in stm))
    ag = aging(c)
    return {"key": "lease_monthly", "title": "تقرير الإيجار الشهري", "subtitle": f"شهر {month}",
            "kpis": [{"label": "المستحق للشهر", "value": expected, "format": "money"}, {"label": "المحصَّل خلال الشهر", "value": collected, "format": "money"},
                     {"label": "نسبة التحصيل", "value": round(100 * collected / expected, 1) if expected else 0, "format": "pct"},
                     {"label": "المتأخرات الكلية", "value": ag["total"], "format": "money"}, {"label": "مصاريف العقارات", "value": exp, "format": "money"},
                     {"label": "عمولة الإدارة", "value": commission, "format": "money"}, {"label": "الصافي للملاك", "value": net, "format": "money"}],
            "charts": [{"type": "pie", "title": "المحصَّل بحسب طريقة السداد", "labels": list(by_method), "series": [{"name": "المحصَّل", "data": list(by_method.values())}], "format": "money"}] if by_method else [],
            "tables": [_tbl("بحسب الوحدة", [("unit", "الوحدة", "text"), ("tenant", "المستأجر", "text"), ("expected", "المستحق", "money"), ("collected", "المحصَّل", "money"), ("gap", "الفرق", "money")], due)],
            "notes": ["لا تدخل الودائع في المستحق ولا المحصَّل. الطريقة «غير موثَّقة» للحركات المرحَّلة التي لم تُدوَّن طريقتها في مصدرها."]}


def r_occupancy(c, params):
    us = _units_state(c)
    per: dict = {}
    for u in us:
        p = per.setdefault(u["project"], {"project": u["project"], "units": 0, "leased": 0, "vacant": 0, "other": 0, "rent": 0.0, "vdays": []})
        p["units"] += 1
        if u["state"] in ("leased", "prep"):
            p["leased"] += 1
            p["rent"] += (u["lease"] or {}).get("annual_rent") or 0
        elif u["state"] == "vacant":
            p["vacant"] += 1
            if u["vacant_days"] is not None:
                p["vdays"].append(u["vacant_days"])
        else:
            p["other"] += 1
    data = []
    for p in per.values():
        data.append({"project": p["project"], "units": p["units"], "leased": p["leased"], "vacant": p["vacant"], "other": p["other"], "occupancy": round(100 * p["leased"] / p["units"], 1),
                     "annual_rent": r3(p["rent"]), "avg_rent": r3(p["rent"] / p["leased"]) if p["leased"] else 0, "avg_vacant_days": round(sum(p["vdays"]) / len(p["vdays"])) if p["vdays"] else 0})
    leased = sum(d["leased"] for d in data)
    total = sum(d["units"] for d in data)
    return {"key": "lease_occupancy", "title": "الإشغال والعائد", "subtitle": f"حتى {today().isoformat()}",
            "kpis": [{"label": "الوحدات", "value": total}, {"label": "مؤجَّرة", "value": leased}, {"label": "نسبة الإشغال", "value": round(100 * leased / total, 1) if total else 0, "format": "pct"},
                     {"label": "الإيجار السنوي", "value": r3(sum(d["annual_rent"] for d in data)), "format": "money"}],
            "charts": [{"type": "bar", "title": "الإشغال بحسب المشروع", "labels": [d["project"] for d in data], "series": [{"name": "مؤجَّرة", "data": [d["leased"] for d in data]}, {"name": "شاغرة", "data": [d["vacant"] for d in data]}], "format": "num"}],
            "tables": [_tbl("بحسب المشروع", [("project", "المشروع", "text"), ("units", "الوحدات", "int"), ("leased", "مؤجَّرة", "int"), ("vacant", "شاغرة", "int"), ("other", "صيانة/غير قابلة", "int"),
                                             ("occupancy", "الإشغال", "pct"), ("annual_rent", "الإيجار السنوي", "money"), ("avg_rent", "متوسط الإيجار", "money"), ("avg_vacant_days", "متوسط أيام الشغور", "int")], data)],
            "notes": ["الإيجار السنوي هو إيجار السنة الأولى المسجَّل على العقد؛ الزيادات المجدولة في جدول الدفعات."]}


def r_aging(c, params):
    ag = aging(c)
    return {"key": "lease_aging", "title": "تعمير متأخرات الإيجار", "subtitle": f"حتى {today().isoformat()}",
            "kpis": [{"label": "إجمالي المتأخرات", "value": ag["total"], "format": "money"}, {"label": "عدد العقود المتأخرة", "value": len(ag["leases"])}],
            "charts": [{"type": "bar", "title": "المتأخرات بحسب العمر", "labels": [b["label"] for b in ag["buckets"]], "series": [{"name": "ر.ع", "data": [b["amount"] for b in ag["buckets"]]}], "format": "money"}],
            "tables": [_tbl("العقود المتأخرة", [("number", "العقد", "text"), ("unit", "الوحدة", "text"), ("tenant", "المستأجر", "text"), ("amount", "المتأخر", "money"), ("oldest_days", "أقدم تأخير (يوم)", "int")], ag["leases"])],
            "notes": ["التأمين غير المسدَّد لا يُعدّ متأخرات. لا تُحتسب فوائد ولا رسوم تأخير."]}


def r_expiring(c, params):
    t = today()
    data = rows(c.execute("""SELECT l.number, u.code unit, t.name tenant, l."end", l.annual_rent FROM leases l JOIN units u ON u.id=l.unit_id JOIN tenants_l t ON t.id=l.tenant_id
                             WHERE l.status='active' AND l."end">=? AND l."end"<=? ORDER BY l."end" """, (t.isoformat(), (t + dt.timedelta(days=90)).isoformat())))
    for r in data:
        r["days_left"] = (dt.date.fromisoformat(r["end"]) - t).days
        r["window"] = "30" if r["days_left"] <= 30 else "60" if r["days_left"] <= 60 else "90"
    return {"key": "lease_expiring", "title": "العقود المنتهية قريبًا", "subtitle": "خلال 90 يومًا",
            "kpis": [{"label": f"خلال {w} يومًا", "value": sum(1 for r in data if int(r["window"]) <= w)} for w in (30, 60, 90)],
            "charts": [], "tables": [_tbl("العقود", [("number", "العقد", "text"), ("unit", "الوحدة", "text"), ("tenant", "المستأجر", "text"), ("end", "تنتهي", "date"), ("days_left", "الأيام المتبقية", "int"),
                                                     ("annual_rent", "الإيجار السنوي", "money")], data)], "notes": []}


def r_cheques(c, params):
    t = today().isoformat()
    data = rows(c.execute("""SELECT q.number, q.bank, q.amount, q.due_date, q.status, l.number lease_no, u.code unit, tn.name tenant FROM cheques q JOIN leases l ON l.id=q.lease_id
                             JOIN units u ON u.id=l.unit_id JOIN tenants_l tn ON tn.id=l.tenant_id WHERE q.direction='in' AND (q.status IN ('deposited','bounced') OR (q.status='held' AND q.due_date<=?))
                             ORDER BY q.due_date""", (t,)))
    lab = {"held": "حان موعد إيداعه", "deposited": "مودَع بانتظار الصرف", "bounced": "مرتجع"}
    for r in data:
        r["status_label"] = lab[r["status"]]
    return {"key": "lease_cheques", "title": "الشيكات المؤجلة", "subtitle": f"حتى {t}",
            "kpis": [{"label": lab[k], "value": sum(1 for r in data if r["status"] == k)} for k in lab] + [{"label": "القيمة", "value": r3(sum(r["amount"] for r in data)), "format": "money"}],
            "charts": [], "tables": [_tbl("الشيكات", [("number", "الشيك", "text"), ("bank", "البنك", "text"), ("amount", "القيمة", "money"), ("due_date", "الاستحقاق", "date"), ("status_label", "الحالة", "text"),
                                                     ("lease_no", "العقد", "text"), ("unit", "الوحدة", "text"), ("tenant", "المستأجر", "text")], data)],
            "notes": ["تُحتسب الدفعة عند صرف الشيك فقط."]}


def r_owners(c, params):
    month = _month(params)
    data = []
    for o in c.execute("SELECT id FROM owners WHERE COALESCE(active,1)=1 ORDER BY kind, id").fetchall():
        s = statement_calc(c, o["id"], month)
        issued = c.execute("SELECT COUNT(*) FROM owner_statements WHERE owner_id=? AND period=?", (o["id"], month)).fetchone()[0]
        data.append({"owner": s["owner"]["name"], "pct": s["owner"]["pct"], "collected": s["collected"], "expenses": s["expenses"], "commission": s["commission"], "net": s["net"], "issued": issued})
    return {"key": "lease_owners", "title": "كشوف الملاك الشهرية", "subtitle": f"شهر {month}",
            "kpis": [{"label": "المحصَّل", "value": r3(sum(d["collected"] for d in data)), "format": "money"}, {"label": "المصاريف", "value": r3(sum(d["expenses"] for d in data)), "format": "money"},
                     {"label": "عمولة الإدارة", "value": r3(sum(d["commission"] for d in data)), "format": "money"}, {"label": "الصافي", "value": r3(sum(d["net"] for d in data)), "format": "money"}],
            "charts": [], "tables": [_tbl("بحسب المالك", [("owner", "المالك", "text"), ("pct", "العمولة ٪", "pct"), ("collected", "المحصَّل", "money"), ("expenses", "المصاريف", "money"),
                                                          ("commission", "العمولة", "money"), ("net", "الصافي", "money"), ("issued", "كشوف صادرة", "int")], data)],
            "notes": ["الصافي = المحصَّل − المصاريف المحمَّلة على المالك − عمولة الإدارة. الكشف الرسمي يصدر من شاشة الملاك."]}


READY_LEASING = {
    "lease_monthly": {"title": "تقرير الإيجار الشهري", "desc": "المستحق والمحصَّل بالطريقة والمتأخرات والمصاريف والعمولة والصافي للملاك.", "fn": r_monthly, "perm": "leasing", "group": "الإيجارات"},
    "lease_occupancy": {"title": "الإشغال والعائد", "desc": "الإشغال والإيجار ومتوسطه وأيام الشغور لكل مشروع.", "fn": r_occupancy, "perm": "leasing", "group": "الإيجارات"},
    "lease_aging": {"title": "تعمير المتأخرات", "desc": "المتأخرات بحسب العمر وبحسب العقد.", "fn": r_aging, "perm": "leasing", "group": "الإيجارات"},
    "lease_expiring": {"title": "العقود المنتهية قريبًا", "desc": "العقود التي تنتهي خلال 30 و60 و90 يومًا.", "fn": r_expiring, "perm": "leasing", "group": "الإيجارات"},
    "lease_cheques": {"title": "الشيكات المؤجلة", "desc": "الشيكات التي حان إيداعها أو المودَعة أو المرتجعة.", "fn": r_cheques, "perm": "leasing", "group": "الإيجارات"},
    "lease_owners": {"title": "كشوف الملاك الشهرية", "desc": "المحصَّل والمصاريف وعمولة الإدارة والصافي لكل مالك.", "fn": r_owners, "perm": "leasing", "group": "الإيجارات"},
}


def register(ready, ready_module) -> None:
    for k, v in READY_LEASING.items():
        ready[k] = v
        ready_module[k] = "leasing"


__all__ = ["register"]
