"""Mabaniq — reports & analytics (Unit 7).

Two ways to get a report, one document shape for both:
* **Ready reports** (`READY`): curated analyses computed from the live data with period/project parameters — portfolio,
  sales, collections & arrears, cash/escrow, inventory & pricing, construction vs sales, lead funnel, brokers, handover &
  quality, quotations, charity dues.
* **Custom reports**: the user composes a report from a **whitelisted dataset** (columns with labels and types), filters,
  grouping (with date buckets), aggregates, sorting and a chart mapping. The builder never accepts SQL — it builds a
  parameterised statement over a fixed base query, so RLS and the permission model stay intact.

A report document: {title, subtitle, params, kpis[], charts[], tables[], notes[]} — rendered in the web app (SVG charts),
exported as CSV (UTF-8 with BOM) or PDF (`pdfgen.render_report`), saved (`report_defs`) and scheduled by e-mail
(`report_schedules`, run by the background tick).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from collections import OrderedDict, defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import engines as E
from . import mail, pdfcharts
from .auth import need_any
from .common import act_as, audit, db, now_s, rows, today
from .db import TENANT, connect, tenants
from .modules import PLAN_LABEL, one

router = APIRouter()
PERM = ("reports", "finance", "view")  # every staff role may read; writes need `reports` or `finance`
MAX_ROWS = 5000

# ---------------------------------------------------------------- datasets (whitelist)
STATUS = {"a": "متاحة", "r": "محجوزة", "s": "مباعة"}
BSTATUS = {"pending": "مبدئي", "confirmed": "مؤكَّد", "cancelled": "ملغى"}
QSTATUS = {"issued": "ساري", "converted": "تحوّل إلى حجز", "cancelled": "ملغى", "expired": "منتهٍ"}
STAGES = {0: "جديد", 1: "مؤهَّل", 2: "معاينة", 3: "تفاوض", 4: "حجز"}

DATASETS: dict[str, dict] = {
    "units": {"label": "الوحدات", "perm": "view",
              "sql": "SELECT u.id, u.code, p.name AS project, u.building, u.floor, u.type, u.area, u.view, u.price, u.status, u.use, u.price/NULLIF(u.area,0) AS sqm FROM units u JOIN projects p ON p.id=u.project_id",
              "columns": OrderedDict([("code", ("رمز الوحدة", "text")), ("project", ("المشروع", "text")), ("building", ("المبنى", "text")), ("floor", ("الطابق", "int")),
                                      ("type", ("النوع", "text")), ("area", ("المساحة م²", "num")), ("view", ("الإطلالة", "text")), ("price", ("السعر", "money")),
                                      ("sqm", ("سعر المتر", "money")), ("status", ("الحالة", "enum", STATUS)), ("use", ("الاستخدام", "text"))])},
    "bookings": {"label": "الحجوزات والمبيعات", "perm": "view",
                 "sql": """SELECT b.id, b.created, b.status, b.plan, b.price, b.list_price, p.name AS project, u.code, u.type, u.view, cu.name AS customer, br.name AS broker,
                                  l.channel, (SELECT COALESCE(SUM(paid_amount),0) FROM installments i WHERE i.booking_id=b.id) AS paid
                           FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id JOIN customers cu ON cu.id=b.customer_id
                           LEFT JOIN brokers br ON br.id=b.broker_id LEFT JOIN leads l ON l.id=b.lead_id""",
                 "columns": OrderedDict([("created", ("تاريخ الحجز", "date")), ("status", ("الحالة", "enum", BSTATUS)), ("plan", ("خطة السداد", "enum", PLAN_LABEL)),
                                         ("price", ("السعر المتفق", "money")), ("list_price", ("سعر القائمة", "money")), ("paid", ("المسدَّد", "money")), ("project", ("المشروع", "text")),
                                         ("code", ("الوحدة", "text")), ("type", ("النوع", "text")), ("view", ("الإطلالة", "text")), ("customer", ("العميل", "text")),
                                         ("broker", ("الوسيط", "text")), ("channel", ("قناة العميل", "text"))])},
    "installments": {"label": "الأقساط", "perm": "finance",
                     "sql": """SELECT i.id, i.seq, i.label, i.due_date, i.amount, i.paid_amount, i.amount-i.paid_amount AS outstanding, p.name AS project, u.code, cu.name AS customer, b.status AS booking_status,
                                      CASE WHEN i.paid_amount>=i.amount-1 THEN 'paid' WHEN i.paid_amount>0 THEN 'partial' WHEN i.due_date<DATE('now') THEN 'late' ELSE 'upcoming' END AS pay_status
                               FROM installments i JOIN bookings b ON b.id=i.booking_id JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id JOIN customers cu ON cu.id=b.customer_id
                               WHERE b.status!='cancelled'""",
                     "columns": OrderedDict([("due_date", ("تاريخ الاستحقاق", "date")), ("label", ("الدفعة", "text")), ("amount", ("المبلغ", "money")), ("paid_amount", ("المسدَّد", "money")),
                                             ("outstanding", ("المتبقي", "money")), ("pay_status", ("حالة السداد", "enum", {"paid": "مدفوع", "partial": "جزئي", "late": "متأخر", "upcoming": "قادم"})),
                                             ("project", ("المشروع", "text")), ("code", ("الوحدة", "text")), ("customer", ("العميل", "text"))])},
    "payments": {"label": "المدفوعات", "perm": "finance",
                 "sql": """SELECT pm.id, pm.receipt, pm.amount, pm.at, pm.method, pm.reconciled, i.label, p.name AS project, u.code, cu.name AS customer
                           FROM payments pm JOIN installments i ON i.id=pm.installment_id JOIN bookings b ON b.id=i.booking_id JOIN units u ON u.id=b.unit_id
                           JOIN projects p ON p.id=u.project_id JOIN customers cu ON cu.id=b.customer_id""",
                 "columns": OrderedDict([("at", ("التاريخ", "date")), ("receipt", ("الإيصال", "text")), ("amount", ("المبلغ", "money")), ("method", ("الطريقة", "text")),
                                         ("reconciled", ("مطابَق بنكيًا", "bool")), ("label", ("الدفعة", "text")), ("project", ("المشروع", "text")), ("code", ("الوحدة", "text")), ("customer", ("العميل", "text"))])},
    "invoices": {"label": "الفواتير", "perm": "invoices",
                 "sql": "SELECT id, number, kind, net, vat, total, issued, customer, note FROM invoices",
                 "columns": OrderedDict([("issued", ("التاريخ", "date")), ("number", ("الرقم", "text")), ("kind", ("النوع", "enum", {"installment": "قسط", "resale_fee": "رسوم تنازل", "service_charge": "رسوم خدمة", "rent": "إيجار"})),
                                         ("net", ("الصافي", "money")), ("vat", ("الضريبة", "money")), ("total", ("الإجمالي", "money")), ("customer", ("العميل", "text")), ("note", ("البيان", "text"))])},
    "leads": {"label": "العملاء المحتملون", "perm": "leads",
              "sql": "SELECT l.id, l.name, l.interest, l.channel, l.stage, l.score, l.budget, l.created, l.last_contact, l.bedrooms, p.name AS project, br.name AS broker, l.campaign_id FROM leads l LEFT JOIN projects p ON p.id=l.project_id LEFT JOIN brokers br ON br.id=l.broker_id",
              "columns": OrderedDict([("created", ("تاريخ التسجيل", "date")), ("name", ("الاسم", "text")), ("project", ("المشروع", "text")), ("channel", ("القناة", "text")),
                                      ("stage", ("المرحلة", "enum", STAGES)), ("score", ("الأولوية", "int")), ("budget", ("الميزانية", "money")), ("bedrooms", ("الغرف", "int")),
                                      ("interest", ("الاهتمام", "text")), ("broker", ("الوسيط", "text")), ("last_contact", ("آخر تواصل", "date")), ("campaign_id", ("الحملة", "int"))])},
    "quotes": {"label": "عروض الأسعار", "perm": "view",
               "sql": "SELECT q.id, q.number, q.created, q.valid_until, q.status, q.price, q.list_price, q.discount_pct, q.plan, q.created_by, p.name AS project, u.code, u.type FROM quotes q JOIN units u ON u.id=q.unit_id JOIN projects p ON p.id=u.project_id",
               "columns": OrderedDict([("created", ("التاريخ", "date")), ("number", ("الرقم", "text")), ("status", ("الحالة", "enum", QSTATUS)), ("price", ("السعر", "money")),
                                       ("discount_pct", ("الخصم", "pct")), ("plan", ("الخطة", "enum", PLAN_LABEL)), ("project", ("المشروع", "text")), ("code", ("الوحدة", "text")),
                                       ("type", ("النوع", "text")), ("created_by", ("أعدّه", "text")), ("valid_until", ("صالح حتى", "date"))])},
    "charity": {"label": "تبرعات التأخير", "perm": "finance",
                "sql": """SELECT cd.id, cd.amount, cd.status, cd.created, i.label, p.name AS project, u.code, cu.name AS customer FROM charity_dues cd JOIN installments i ON i.id=cd.installment_id
                          JOIN bookings b ON b.id=i.booking_id JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id JOIN customers cu ON cu.id=b.customer_id""",
                "columns": OrderedDict([("created", ("التاريخ", "date")), ("amount", ("المبلغ", "money")), ("status", ("الحالة", "enum", {"due": "مستحق", "collected": "محصَّل (أمانة)", "disbursed": "صُرف", "waived": "معفى"})),
                                        ("project", ("المشروع", "text")), ("code", ("الوحدة", "text")), ("customer", ("العميل", "text")), ("label", ("الدفعة", "text"))])},
    "service": {"label": "طلبات الخدمة", "perm": "service",
                "sql": "SELECT s.id, s.category, s.status, s.created, p.name AS project, u.code FROM service_requests s JOIN bookings b ON b.id=s.booking_id JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id",
                "columns": OrderedDict([("created", ("التاريخ", "date")), ("category", ("الفئة", "text")), ("status", ("الحالة", "enum", {"new": "جديد", "in_progress": "قيد التنفيذ", "done": "منجز"})), ("project", ("المشروع", "text")), ("code", ("الوحدة", "text"))])},
    "projects": {"label": "المشاريع", "perm": "view",
                 "sql": "SELECT id, name, location, kind, build_pct, planned_monthly_sales, handover, completed FROM projects",
                 "columns": OrderedDict([("name", ("المشروع", "text")), ("location", ("الموقع", "text")), ("kind", ("النوع", "enum", {"tower": "أبراج", "villa": "فلل"})), ("build_pct", ("الإنجاز ٪", "num")),
                                         ("planned_monthly_sales", ("المبيعات الشهرية المخططة", "num")), ("handover", ("التسليم", "date")), ("completed", ("مكتمل", "bool"))])},
}
OPS = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
AGG = {"count": "COUNT(*)", "sum": "SUM({c})", "avg": "AVG({c})", "min": "MIN({c})", "max": "MAX({c})"}
BUCKETS = {"day": "substr({c},1,10)", "month": "substr({c},1,7)", "year": "substr({c},1,4)"}


def datasets_public(perms: set) -> list[dict]:
    out = []
    for k, d in DATASETS.items():
        if d["perm"] in perms or "admin" in perms:
            out.append({"key": k, "label": d["label"], "columns": [{"key": c, "label": m[0], "type": m[1], "enum": m[2] if len(m) > 2 else None} for c, m in d["columns"].items()]})
    return out


# ---------------------------------------------------------------- custom query builder
class Filter(BaseModel):
    col: str
    op: str = Field(pattern="^(eq|ne|gt|gte|lt|lte|contains|in|between|null|notnull)$")
    value: object | None = None


class GroupBy(BaseModel):
    col: str
    bucket: str | None = Field(default=None, pattern="^(day|month|year)$")


class Agg(BaseModel):
    fn: str = Field(pattern="^(count|sum|avg|min|max)$")
    col: str | None = None
    label: str | None = Field(default=None, max_length=60)


class Sort(BaseModel):
    col: str
    dir: str = Field(default="desc", pattern="^(asc|desc)$")


class ChartSpec(BaseModel):
    type: str = Field(default="bar", pattern="^(bar|line|pie|stacked|none)$")
    x: str | None = None
    y: list[str] = Field(default_factory=list)


class Spec(BaseModel):
    dataset: str
    columns: list[str] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    group_by: list[GroupBy] = Field(default_factory=list, max_length=3)
    aggs: list[Agg] = Field(default_factory=list, max_length=8)
    sort: list[Sort] = Field(default_factory=list, max_length=3)
    limit: int = Field(default=500, ge=1, le=MAX_ROWS)
    chart: ChartSpec = Field(default_factory=ChartSpec)
    title: str | None = Field(default=None, max_length=120)


def _col(ds: dict, col: str) -> tuple[str, tuple]:
    if col not in ds["columns"]:
        raise HTTPException(400, f"العمود «{col}» ليس في مجموعة البيانات")
    return col, ds["columns"][col]


def build_sql(spec: Spec) -> tuple[str, list]:
    ds = DATASETS.get(spec.dataset)
    if not ds:
        raise HTTPException(404, "مجموعة البيانات غير معروفة")
    params: list = []
    where = []
    for f in spec.filters:
        col, meta = _col(ds, f.col)
        if f.op in OPS:
            where.append(f"{col} {OPS[f.op]} ?")
            params.append(_coerce(meta, f.value))
        elif f.op == "contains":
            where.append(f"{col} LIKE ?")
            params.append(f"%{str(f.value or '')[:80]}%")
        elif f.op == "in":
            vals = f.value if isinstance(f.value, list) else [f.value]
            vals = [_coerce(meta, v) for v in vals[:50]]
            if not vals:
                continue
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            params.extend(vals)
        elif f.op == "between":
            a, b = (f.value or [None, None])[:2] if isinstance(f.value, list) else (None, None)
            where.append(f"{col} BETWEEN ? AND ?")
            params.extend([_coerce(meta, a), _coerce(meta, b)])
        elif f.op == "null":
            where.append(f"{col} IS NULL")
        elif f.op == "notnull":
            where.append(f"{col} IS NOT NULL")
    select, group, labels = [], [], []
    if spec.group_by or spec.aggs:
        for g in spec.group_by:
            col, meta = _col(ds, g.col)
            expr = BUCKETS[g.bucket].format(c=col) if g.bucket and meta[1] == "date" else col
            alias = f"{col}_{g.bucket}" if g.bucket else col
            select.append(f"{expr} AS {alias}")
            group.append(expr)
            labels.append((alias, meta[0] + (f" ({ {'day': 'يوم', 'month': 'شهر', 'year': 'سنة'}[g.bucket]})" if g.bucket else ""), "text" if g.bucket else meta[1], meta[2] if len(meta) > 2 else None))
        aggs = spec.aggs or [Agg(fn="count")]
        for a in aggs:
            if a.fn == "count":
                alias, lab, typ = "count", a.label or "العدد", "int"
                select.append(f"COUNT(*) AS {alias}")
            else:
                col, meta = _col(ds, a.col or "")
                if meta[1] not in ("num", "money", "int", "pct"):
                    raise HTTPException(400, f"لا يمكن تجميع العمود «{meta[0]}» رقميًا")
                alias = f"{a.fn}_{col}"
                lab = a.label or f"{ {'sum': 'مجموع', 'avg': 'متوسط', 'min': 'أدنى', 'max': 'أعلى'}[a.fn]} {meta[0]}"
                typ = meta[1] if a.fn != "count" else "int"
                select.append(f"{AGG[a.fn].format(c=col)} AS {alias}")
            labels.append((alias, lab, typ, None))
        if not spec.group_by:
            group = []
    else:
        cols = spec.columns or list(ds["columns"].keys())
        for c in cols:
            col, meta = _col(ds, c)
            select.append(col)
            labels.append((col, meta[0], meta[1], meta[2] if len(meta) > 2 else None))
    order = []
    allowed_sort = {lab[0] for lab in labels}
    for s in spec.sort:
        if s.col in allowed_sort:
            order.append(f"{s.col} {'ASC' if s.dir == 'asc' else 'DESC'}")
    sql = f"SELECT {', '.join(select)} FROM ({ds['sql']}) d"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if group:
        sql += " GROUP BY " + ", ".join(group)
    if order:
        sql += " ORDER BY " + ", ".join(order)
    elif group:
        sql += " ORDER BY 1"
    sql += f" LIMIT {int(spec.limit)}"
    return sql, params, labels  # type: ignore[return-value]


def _coerce(meta, v):
    t = meta[1]
    if v is None:
        return None
    if t in ("num", "money", "pct"):
        return float(v)
    if t in ("int", "bool"):
        return int(v)
    return str(v)[:200]


def run_spec(c, spec: Spec, perms: set) -> dict:
    ds = DATASETS.get(spec.dataset)
    if not ds:
        raise HTTPException(404, "مجموعة البيانات غير معروفة")
    if ds["perm"] not in perms and "admin" not in perms:
        raise HTTPException(403, f"مجموعة «{ds['label']}» تحتاج صلاحية {ds['perm']}")
    sql, params, labels = build_sql(spec)
    data = rows(c.execute(sql, params))
    columns = [{"key": k, "label": lab, "type": typ, "enum": en} for k, lab, typ, en in labels]
    for r in data:
        for col in columns:
            if col["enum"] and r.get(col["key"]) in col["enum"]:
                r[col["key"]] = col["enum"][r[col["key"]]]
            elif col["enum"] and col["type"] == "enum":
                r[col["key"]] = col["enum"].get(str(r.get(col["key"])), r.get(col["key"]))
    doc = {"key": "custom", "title": spec.title or f"تقرير مخصّص — {ds['label']}", "subtitle": f"{len(data)} صف · {today().isoformat()}",
           "params": spec.model_dump(), "kpis": [{"label": "عدد الصفوف", "value": len(data)}], "charts": [], "tables": [{"title": ds["label"], "columns": columns, "rows": data}], "notes": []}
    ch = spec.chart
    if ch.type != "none" and data and (ch.x or spec.group_by):
        x = ch.x or columns[0]["key"]
        ys = ch.y or [col["key"] for col in columns if col["type"] in ("int", "num", "money", "pct") and col["key"] != x][:3]
        if ys:
            doc["charts"].append({"type": ch.type, "title": doc["title"], "labels": [str(r.get(x) if r.get(x) is not None else "—") for r in data[:60]],
                                  "series": [{"name": next((col["label"] for col in columns if col["key"] == y), y), "data": [float(r.get(y) or 0) for r in data[:60]]} for y in ys],
                                  "format": next((col["type"] for col in columns if col["key"] == ys[0]), "num")})
    return doc


# ---------------------------------------------------------------- ready reports
def _period(params: dict) -> tuple[str, str]:
    to = params.get("to") or today().isoformat()
    frm = params.get("from") or (dt.date.fromisoformat(to) - dt.timedelta(days=365)).isoformat()
    return frm[:10], to[:10]


def _months(frm: str, to: str) -> list[str]:
    a, b = dt.date.fromisoformat(frm), dt.date.fromisoformat(to)
    out, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out[-24:]


def _pf(params) -> tuple[str, list]:
    pid = params.get("project_id")
    return (" AND p.id=?", [int(pid)]) if pid else ("", [])


def _tbl(title, cols, data):
    return {"title": title, "columns": [{"key": k, "label": lab, "type": t} for k, lab, t in cols], "rows": data}


def r_portfolio(c, params):
    frm, to = _period(params)
    pf, pa = _pf(params)
    per = rows(c.execute(f"""SELECT p.id, p.name, p.location, p.build_pct, p.handover, p.planned_monthly_sales,
                             COUNT(u.id) total, SUM(CASE WHEN u.status='s' THEN 1 ELSE 0 END) sold, SUM(CASE WHEN u.status='r' THEN 1 ELSE 0 END) reserved,
                             SUM(CASE WHEN u.status='a' THEN 1 ELSE 0 END) available, SUM(CASE WHEN u.status='a' THEN u.price ELSE 0 END) unsold_value,
                             SUM(CASE WHEN u.status IN ('s','r') THEN u.price ELSE 0 END) sold_value
                             FROM projects p JOIN units u ON u.project_id=p.id WHERE 1=1{pf} GROUP BY p.id, p.name, p.location, p.build_pct, p.handover, p.planned_monthly_sales ORDER BY p.id""", pa))
    for r in per:
        r["sold_pct"] = round(100 * (r["sold"] + r["reserved"]) / r["total"], 1) if r["total"] else 0
    months = _months(frm, to)
    sales = rows(c.execute(f"""SELECT substr(b.created,1,7) m, COUNT(*) n, SUM(b.price) v FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id
                               WHERE b.status!='cancelled' AND b.created BETWEEN ? AND ?{pf} GROUP BY substr(b.created,1,7) ORDER BY 1""", [frm, to + "z", *pa]))
    by = {s["m"]: s for s in sales}
    kp = E.kpis(c, int(params["project_id"]) if params.get("project_id") else None)
    return {"key": "portfolio", "title": "لوحة المحفظة", "subtitle": f"من {frm} إلى {to}",
            "kpis": [{"label": "الوحدات", "value": sum(r["total"] for r in per)}, {"label": "المباع/المحجوز", "value": sum(r["sold"] + r["reserved"] for r in per)},
                     {"label": "قيمة غير المباع", "value": sum(r["unsold_value"] or 0 for r in per), "format": "money"}, {"label": "نسبة التحصيل (90 يومًا)", "value": kp.get("collection_rate"), "format": "pct"}],
            "charts": [{"type": "stacked", "title": "الوحدات بحسب الحالة", "labels": [r["name"] for r in per], "series": [{"name": "مباعة", "data": [r["sold"] for r in per]}, {"name": "محجوزة", "data": [r["reserved"] for r in per]}, {"name": "متاحة", "data": [r["available"] for r in per]}], "format": "num"},
                       {"type": "line", "title": "المبيعات الشهرية (قيمة)", "labels": months, "series": [{"name": "قيمة المبيعات", "data": [float(by.get(m, {}).get("v") or 0) for m in months]}], "format": "money"},
                       {"type": "bar", "title": "الإنجاز مقابل البيع ٪", "labels": [r["name"] for r in per], "series": [{"name": "الإنجاز ٪", "data": [r["build_pct"] or 0 for r in per]}, {"name": "المبيع ٪", "data": [r["sold_pct"] for r in per]}], "format": "pct"}],
            "tables": [_tbl("المشاريع", [("name", "المشروع", "text"), ("location", "الموقع", "text"), ("total", "الوحدات", "int"), ("sold", "مباعة", "int"), ("reserved", "محجوزة", "int"), ("available", "متاحة", "int"),
                                        ("sold_pct", "المبيع ٪", "pct"), ("build_pct", "الإنجاز ٪", "pct"), ("sold_value", "قيمة المبيعات", "money"), ("unsold_value", "قيمة غير المباع", "money"), ("handover", "التسليم", "date")], per)],
            "notes": ["المحجوز يُحتسب مع المباع في نسبة البيع لأنه يحجز الوحدة عن السوق؛ قيمة غير المباع بأسعار القائمة الحالية."]}


def r_sales(c, params):
    frm, to = _period(params)
    pf, pa = _pf(params)
    months = _months(frm, to)
    base = f"""FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id LEFT JOIN leads l ON l.id=b.lead_id LEFT JOIN brokers br ON br.id=b.broker_id
               WHERE b.status!='cancelled' AND b.created BETWEEN ? AND ?{pf}"""
    args = [frm, to + "z", *pa]
    bym = {r["m"]: r for r in rows(c.execute(f"SELECT substr(b.created,1,7) m, COUNT(*) n, SUM(b.price) v {base} GROUP BY substr(b.created,1,7)", args))}
    byp = rows(c.execute(f"SELECT p.name, COUNT(*) n, SUM(b.price) v, AVG(b.price) avg_price, SUM(b.list_price-b.price) discounts {base} GROUP BY p.name ORDER BY v DESC", args))
    bypl = rows(c.execute(f"SELECT b.plan, COUNT(*) n, SUM(b.price) v {base} GROUP BY b.plan", args))
    bych = rows(c.execute(f"SELECT COALESCE(l.channel,'مباشر') ch, COUNT(*) n {base} GROUP BY COALESCE(l.channel,'مباشر') ORDER BY n DESC", args))
    bybr = rows(c.execute(f"SELECT COALESCE(br.name,'بلا وسيط') brk, COUNT(*) n, SUM(b.price) v {base} GROUP BY COALESCE(br.name,'بلا وسيط') ORDER BY n DESC", args))
    bytype = rows(c.execute(f"SELECT u.type, COUNT(*) n, SUM(b.price) v {base} GROUP BY u.type ORDER BY n DESC", args))
    total_n = sum(r["n"] for r in byp)
    total_v = sum(r["v"] or 0 for r in byp)
    cancelled = c.execute(f"SELECT COUNT(*) FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id WHERE b.status='cancelled' AND b.created BETWEEN ? AND ?{pf}", args).fetchone()[0]
    for r in bypl:
        r["plan"] = PLAN_LABEL.get(r["plan"], r["plan"])
    return {"key": "sales", "title": "أداء المبيعات", "subtitle": f"من {frm} إلى {to}",
            "kpis": [{"label": "عمليات البيع", "value": total_n}, {"label": "قيمة المبيعات", "value": total_v, "format": "money"},
                     {"label": "متوسط السعر", "value": round(total_v / total_n) if total_n else 0, "format": "money"}, {"label": "الملغاة", "value": cancelled}],
            "charts": [{"type": "bar", "title": "عدد المبيعات شهريًا", "labels": months, "series": [{"name": "مبيعات", "data": [bym.get(m, {}).get("n", 0) for m in months]}], "format": "num"},
                       {"type": "pie", "title": "حصة المشاريع من القيمة", "labels": [r["name"] for r in byp], "series": [{"name": "القيمة", "data": [float(r["v"] or 0) for r in byp]}], "format": "money"},
                       {"type": "pie", "title": "قنوات العملاء", "labels": [r["ch"] for r in bych], "series": [{"name": "عمليات", "data": [r["n"] for r in bych]}], "format": "num"},
                       {"type": "bar", "title": "خطط السداد", "labels": [r["plan"] for r in bypl], "series": [{"name": "عمليات", "data": [r["n"] for r in bypl]}], "format": "num"}],
            "tables": [_tbl("بحسب المشروع", [("name", "المشروع", "text"), ("n", "عمليات", "int"), ("v", "القيمة", "money"), ("avg_price", "متوسط السعر", "money"), ("discounts", "الخصومات", "money")], byp),
                       _tbl("بحسب النوع", [("type", "النوع", "text"), ("n", "عمليات", "int"), ("v", "القيمة", "money")], bytype),
                       _tbl("بحسب الوسيط", [("brk", "الوسيط", "text"), ("n", "عمليات", "int"), ("v", "القيمة", "money")], bybr)],
            "notes": []}


def r_collections(c, params):
    frm, to = _period(params)
    pf, pa = _pf(params)
    months = _months(frm, to)
    t = today().isoformat()
    due = {r["m"]: r for r in rows(c.execute(f"""SELECT substr(i.due_date,1,7) m, SUM(i.amount) due, SUM(i.paid_amount) paid FROM installments i JOIN bookings b ON b.id=i.booking_id
                                                   JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id WHERE b.status!='cancelled' AND i.due_date BETWEEN ? AND ?{pf} GROUP BY substr(i.due_date,1,7)""", [frm, to + "z", *pa]))}
    late = rows(c.execute(f"""SELECT i.id, i.amount-i.paid_amount outstanding, i.due_date, p.name project, u.code, cu.name customer FROM installments i JOIN bookings b ON b.id=i.booking_id
                              JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id JOIN customers cu ON cu.id=b.customer_id
                              WHERE b.status!='cancelled' AND i.due_date<? AND i.paid_amount<i.amount-1{pf} ORDER BY i.due_date""", [t, *pa]))
    buckets = OrderedDict([("1–30 يومًا", 0.0), ("31–60", 0.0), ("61–90", 0.0), ("أكثر من 90", 0.0)])
    td = dt.date.fromisoformat(t)
    for r in late:
        d = (td - dt.date.fromisoformat(r["due_date"])).days
        r["days_late"] = d
        k = "1–30 يومًا" if d <= 30 else "31–60" if d <= 60 else "61–90" if d <= 90 else "أكثر من 90"
        buckets[k] += float(r["outstanding"] or 0)
    tot_due = sum(float(r["due"] or 0) for r in due.values())
    tot_paid = sum(float(r["paid"] or 0) for r in due.values())
    ch = rows(c.execute(f"""SELECT cd.status, SUM(cd.amount) a, COUNT(*) n FROM charity_dues cd JOIN installments i ON i.id=cd.installment_id JOIN bookings b ON b.id=i.booking_id
                            JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id WHERE 1=1{pf} GROUP BY cd.status""", pa))
    return {"key": "collections", "title": "التحصيل والمتأخرات", "subtitle": f"أقساط مستحقة من {frm} إلى {to} · المتأخرات حتى {t}",
            "kpis": [{"label": "المستحق في الفترة", "value": tot_due, "format": "money"}, {"label": "المحصَّل", "value": tot_paid, "format": "money"},
                     {"label": "نسبة التحصيل", "value": round(100 * tot_paid / tot_due, 1) if tot_due else 100, "format": "pct"}, {"label": "متأخرات قائمة", "value": sum(buckets.values()), "format": "money"}],
            "charts": [{"type": "bar", "title": "المستحق مقابل المحصَّل شهريًا", "labels": months, "series": [{"name": "مستحق", "data": [float(due.get(m, {}).get("due") or 0) for m in months]}, {"name": "محصَّل", "data": [float(due.get(m, {}).get("paid") or 0) for m in months]}], "format": "money"},
                       {"type": "pie", "title": "أعمار المتأخرات", "labels": list(buckets.keys()), "series": [{"name": "متأخر", "data": list(buckets.values())}], "format": "money"}],
            "tables": [_tbl("الأقساط المتأخرة", [("customer", "العميل", "text"), ("project", "المشروع", "text"), ("code", "الوحدة", "text"), ("due_date", "الاستحقاق", "date"), ("days_late", "أيام التأخر", "int"), ("outstanding", "المتبقي", "money")], late[:300]),
                       _tbl("تبرعات التأخير (شرط التبرع)", [("status", "الحالة", "text"), ("n", "العدد", "int"), ("a", "المبلغ", "money")], ch)],
            "notes": ["مبالغ التأخير تبرعات بشرط التبرع لجهة خيرية ولا تُحتسب إيرادًا — قاعدة التمويل الإسلامي."]}


def r_cash(c, params):
    pid = int(params["project_id"]) if params.get("project_id") else None
    radar = E.cash_radar(c, False, pid) if pid else E.cash_radar(c)
    projects = radar.get("projects") or []
    series_all = radar.get("series") or []
    labels = [x.get("month") for x in series_all]
    series = [{"name": p.get("name", "—"), "data": [float(x.get("balance") or 0) for x in p.get("series") or []]} for p in projects[:6]]
    tbl = [{"project": p.get("name"), "balance": (p.get("series") or [{}])[0].get("balance"), "min_balance": min((float(x.get("balance") or 0) for x in p.get("series") or []), default=0),
            "gap": p.get("gap") or 0, "gap_month": (p.get("worst") or {}).get("month"), "inflow": sum(float(x.get("inflow") or 0) for x in p.get("series") or []), "outflow": sum(float(x.get("outflow") or 0) for x in p.get("series") or [])} for p in projects]
    return {"key": "cash", "title": "السيولة وحسابات الضمان", "subtitle": "رادار 12 شهرًا من محرك السيولة",
            "kpis": [{"label": "فجوة السيولة المتوقعة", "value": radar.get("gap") or 0, "format": "money"}, {"label": "مشاريع بعجز", "value": sum(1 for p in projects if p.get("gap"))},
                     {"label": "تدفقات داخلة متوقعة", "value": sum(float(x.get("inflow") or 0) for x in series_all), "format": "money"}, {"label": "تدفقات خارجة متوقعة", "value": sum(float(x.get("outflow") or 0) for x in series_all), "format": "money"}],
            "charts": ([{"type": "line", "title": "رصيد حساب الضمان المتوقع شهريًا", "labels": labels, "series": series, "format": "money"},
                        {"type": "bar", "title": "الداخل مقابل الخارج (كل المشاريع)", "labels": labels, "series": [{"name": "داخل", "data": [float(x.get("inflow") or 0) for x in series_all]}, {"name": "خارج", "data": [float(x.get("outflow") or 0) for x in series_all]}], "format": "money"}] if labels else []),
            "tables": [_tbl("بحسب المشروع", [("project", "المشروع", "text"), ("balance", "الرصيد الحالي", "money"), ("min_balance", "أدنى رصيد متوقع", "money"), ("gap", "العجز", "money"), ("gap_month", "شهر الذروة", "text"), ("inflow", "داخل", "money"), ("outflow", "خارج", "money")], tbl)],
            "notes": [a if isinstance(a, str) else str(a) for a in (radar.get("actions") or [])][:5]}


def r_inventory(c, params):
    pf, pa = _pf(params)
    pr = rows(c.execute(f"SELECT p.id, p.name FROM projects p WHERE 1=1{pf} ORDER BY p.id", pa))
    data = []
    for p in pr:
        for s in E.pricing(c, p["id"]):
            data.append({"project": p["name"], **s})
    agg = rows(c.execute(f"""SELECT u.type, COUNT(*) total, SUM(CASE WHEN u.status='a' THEN 1 ELSE 0 END) available, AVG(u.price/NULLIF(u.area,0)) sqm
                             FROM units u JOIN projects p ON p.id=u.project_id WHERE 1=1{pf} GROUP BY u.type ORDER BY total DESC""", pa))
    aging = rows(c.execute(f"""SELECT p.name project, COUNT(*) available, SUM(u.price) value FROM units u JOIN projects p ON p.id=u.project_id WHERE u.status='a'{pf} GROUP BY p.name ORDER BY value DESC""", pa))
    ups = sum(1 for d in data if d["suggested_change"] > 0)
    downs = sum(1 for d in data if d["suggested_change"] < 0)
    return {"key": "inventory", "title": "المخزون والتسعير", "subtitle": "أداء الشرائح وتوصيات محرك التسعير",
            "kpis": [{"label": "شرائح", "value": len(data)}, {"label": "مرشّحة لرفع السعر", "value": ups}, {"label": "مرشّحة لخفض/حافز", "value": downs}, {"label": "المتاح", "value": sum(r["available"] for r in aging)}],
            "charts": [{"type": "bar", "title": "المتاح مقابل الإجمالي بحسب النوع", "labels": [r["type"] for r in agg], "series": [{"name": "الإجمالي", "data": [r["total"] for r in agg]}, {"name": "المتاح", "data": [r["available"] for r in agg]}], "format": "num"},
                       {"type": "pie", "title": "قيمة المخزون المتاح بحسب المشروع", "labels": [r["project"] for r in aging], "series": [{"name": "القيمة", "data": [float(r["value"] or 0) for r in aging]}], "format": "money"}],
            "tables": [_tbl("الشرائح", [("project", "المشروع", "text"), ("type", "النوع", "text"), ("view", "الإطلالة", "text"), ("total", "الإجمالي", "int"), ("available", "المتاح", "int"), ("recent_sales", "بيع 90 يومًا", "int"),
                                        ("demand_ratio", "الطلب النسبي", "num"), ("suggested_change", "التوصية", "pct")], data),
                       _tbl("سعر المتر بحسب النوع", [("type", "النوع", "text"), ("total", "الإجمالي", "int"), ("available", "المتاح", "int"), ("sqm", "متوسط سعر المتر", "money")], agg)],
            "notes": ["التوصية بنسبة من السعر (موجب = رفع، سالب = خفض أو حافز)؛ تُعتمد من شاشة المخزون لا من هذا التقرير."]}


def r_construction(c, params):
    pf, pa = _pf(params)
    pr = rows(c.execute(f"""SELECT p.id, p.name, p.build_pct, p.handover, COUNT(u.id) total, SUM(CASE WHEN u.status IN ('s','r') THEN 1 ELSE 0 END) sold,
                            (SELECT COALESCE(SUM(stage_value),0) FROM ipcs i WHERE i.project_id=p.id AND i.status='approved') ipc_approved,
                            (SELECT COUNT(*) FROM ipcs i WHERE i.project_id=p.id AND i.status NOT IN ('approved','rejected')) ipc_pending
                            FROM projects p JOIN units u ON u.project_id=p.id WHERE 1=1{pf} GROUP BY p.id, p.name, p.build_pct, p.handover ORDER BY p.id""", pa))
    for r in pr:
        r["sold_pct"] = round(100 * r["sold"] / r["total"], 1) if r["total"] else 0
        r["gap"] = round(r["sold_pct"] - (r["build_pct"] or 0), 1)
    return {"key": "construction", "title": "الإنشاء مقابل المبيعات", "subtitle": "هل يسبق البيع البناء أم يتأخر عنه؟",
            "kpis": [{"label": "مشاريع", "value": len(pr)}, {"label": "متوسط الإنجاز", "value": round(sum(r["build_pct"] or 0 for r in pr) / len(pr), 1) if pr else 0, "format": "pct"},
                     {"label": "مستخلصات معتمدة", "value": sum(float(r["ipc_approved"] or 0) for r in pr), "format": "money"}, {"label": "مستخلصات معلّقة", "value": sum(r["ipc_pending"] for r in pr)}],
            "charts": [{"type": "bar", "title": "الإنجاز ٪ مقابل البيع ٪", "labels": [r["name"] for r in pr], "series": [{"name": "الإنجاز", "data": [r["build_pct"] or 0 for r in pr]}, {"name": "البيع", "data": [r["sold_pct"] for r in pr]}], "format": "pct"}],
            "tables": [_tbl("المشاريع", [("name", "المشروع", "text"), ("build_pct", "الإنجاز ٪", "pct"), ("sold_pct", "البيع ٪", "pct"), ("gap", "الفارق (بيع − إنجاز)", "num"), ("ipc_approved", "مستخلصات معتمدة", "money"), ("ipc_pending", "معلّقة", "int"), ("handover", "التسليم", "date")], pr)],
            "notes": ["فارق موجب كبير = بيع يسبق البناء (مخاطر تسليم)؛ فارق سالب كبير = مخزون يتراكم مع تقدم البناء (يحتاج تسويقًا)."]}


def r_funnel(c, params):
    frm, to = _period(params)
    pf, pa = _pf(params)
    base = f"FROM leads l LEFT JOIN projects p ON p.id=l.project_id WHERE l.created BETWEEN ? AND ?{pf}"
    args = [frm, to + "z", *pa]
    st = {r["stage"]: r["n"] for r in rows(c.execute(f"SELECT l.stage, COUNT(*) n {base} GROUP BY l.stage", args))}
    ch = rows(c.execute(f"SELECT l.channel, COUNT(*) n, AVG(l.score) score, SUM(CASE WHEN l.stage>=4 THEN 1 ELSE 0 END) won {base} GROUP BY l.channel ORDER BY n DESC", args))
    byp = rows(c.execute(f"SELECT COALESCE(p.name,'—') project, COUNT(*) n, SUM(CASE WHEN l.stage>=4 THEN 1 ELSE 0 END) won {base} GROUP BY COALESCE(p.name,'—') ORDER BY n DESC", args))
    months = _months(frm, to)
    bym = {r["m"]: r["n"] for r in rows(c.execute(f"SELECT substr(l.created,1,7) m, COUNT(*) n {base} GROUP BY substr(l.created,1,7)", args))}
    total = sum(st.values())
    won = st.get(4, 0)
    stale = c.execute(f"SELECT COUNT(*) {base} AND l.stage BETWEEN 1 AND 3 AND (l.last_contact IS NULL OR l.last_contact < ?)", [*args, (today() - dt.timedelta(days=14)).isoformat()]).fetchone()[0]
    for r in ch:
        r["conv"] = round(100 * r["won"] / r["n"], 1) if r["n"] else 0
    return {"key": "funnel", "title": "قمع العملاء المحتملين", "subtitle": f"عملاء مسجَّلون من {frm} إلى {to}",
            "kpis": [{"label": "عملاء محتملون", "value": total}, {"label": "تحوّلوا إلى حجز", "value": won}, {"label": "نسبة التحويل", "value": round(100 * won / total, 1) if total else 0, "format": "pct"}, {"label": "بلا تواصل 14 يومًا", "value": stale}],
            "charts": [{"type": "bar", "title": "القمع بحسب المرحلة", "labels": [STAGES[i] for i in range(5)], "series": [{"name": "عملاء", "data": [st.get(i, 0) for i in range(5)]}], "format": "num"},
                       {"type": "pie", "title": "القنوات", "labels": [r["channel"] for r in ch], "series": [{"name": "عملاء", "data": [r["n"] for r in ch]}], "format": "num"},
                       {"type": "line", "title": "عملاء جدد شهريًا", "labels": months, "series": [{"name": "جدد", "data": [bym.get(m, 0) for m in months]}], "format": "num"}],
            "tables": [_tbl("القنوات", [("channel", "القناة", "text"), ("n", "عملاء", "int"), ("won", "حجوزات", "int"), ("conv", "التحويل ٪", "pct"), ("score", "متوسط الأولوية", "num")], ch),
                       _tbl("بحسب المشروع", [("project", "المشروع", "text"), ("n", "عملاء", "int"), ("won", "حجوزات", "int")], byp)],
            "notes": []}


def r_brokers(c, params):
    frm, to = _period(params)
    br = rows(c.execute("""SELECT br.id, br.name, br.rate, br.active, COUNT(DISTINCT b.id) bookings, COALESCE(SUM(CASE WHEN b.status!='cancelled' THEN b.price END),0) value,
                           (SELECT COALESCE(SUM(amount),0) FROM commissions cm WHERE cm.broker_id=br.id AND cm.status='due') due,
                           (SELECT COALESCE(SUM(amount),0) FROM commissions cm WHERE cm.broker_id=br.id AND cm.status='paid') paid,
                           (SELECT COUNT(*) FROM leads l WHERE l.broker_id=br.id AND l.created BETWEEN ? AND ?) leads
                           FROM brokers br LEFT JOIN bookings b ON b.broker_id=br.id AND b.created BETWEEN ? AND ? GROUP BY br.id, br.name, br.rate, br.active ORDER BY value DESC""", [frm, to + "z", frm, to + "z"]))
    return {"key": "brokers", "title": "الوسطاء والعمولات", "subtitle": f"من {frm} إلى {to}",
            "kpis": [{"label": "وسطاء نشطون", "value": sum(1 for r in br if r["active"])}, {"label": "مبيعات عبر وسطاء", "value": sum(r["bookings"] for r in br)},
                     {"label": "عمولات مستحقة", "value": sum(float(r["due"]) for r in br), "format": "money"}, {"label": "عمولات مصروفة", "value": sum(float(r["paid"]) for r in br), "format": "money"}],
            "charts": [{"type": "bar", "title": "قيمة المبيعات بحسب الوسيط", "labels": [r["name"] for r in br], "series": [{"name": "القيمة", "data": [float(r["value"]) for r in br]}], "format": "money"}],
            "tables": [_tbl("الوسطاء", [("name", "الوسيط", "text"), ("rate", "النسبة", "pct"), ("leads", "عملاء أحالهم", "int"), ("bookings", "حجوزات", "int"), ("value", "القيمة", "money"), ("due", "مستحق", "money"), ("paid", "مصروف", "money")], br)],
            "notes": ["العمولة تُصرف بعد تحصيل 20٪ من ثمن الوحدة (سياسة المنصة)."]}


def r_handover(c, params):
    pf, pa = _pf(params)
    hv = rows(c.execute(f"""SELECT p.name project, COUNT(h.id) scheduled, SUM(CASE WHEN h.certificate_no IS NOT NULL THEN 1 ELSE 0 END) done
                            FROM handovers h JOIN bookings b ON b.id=h.booking_id JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id WHERE 1=1{pf} GROUP BY p.name""", pa))
    sn = rows(c.execute(f"""SELECT p.name project, SUM(CASE WHEN s.status='open' THEN 1 ELSE 0 END) open_snags, SUM(CASE WHEN s.status!='open' THEN 1 ELSE 0 END) fixed
                            FROM snags s JOIN bookings b ON b.id=s.booking_id JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id WHERE 1=1{pf} GROUP BY p.name""", pa))
    tt = rows(c.execute(f"""SELECT t.status, COUNT(*) n FROM titles t JOIN bookings b ON b.id=t.booking_id JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id WHERE 1=1{pf} GROUP BY t.status""", pa))
    merged = defaultdict(dict)
    for r in hv:
        merged[r["project"]].update(r)
    for r in sn:
        merged[r["project"]].update(r)
    data = [{"project": k, "scheduled": v.get("scheduled", 0), "done": v.get("done", 0), "open_snags": v.get("open_snags", 0), "fixed": v.get("fixed", 0)} for k, v in merged.items()]
    return {"key": "handover", "title": "التسليم والجودة", "subtitle": "التسليمات والملاحظات وسندات الملكية",
            "kpis": [{"label": "تسليمات مكتملة", "value": sum(d["done"] for d in data)}, {"label": "مجدولة", "value": sum(d["scheduled"] for d in data)}, {"label": "ملاحظات مفتوحة", "value": sum(d["open_snags"] for d in data)}, {"label": "ملاحظات أُصلحت", "value": sum(d["fixed"] for d in data)}],
            "charts": [{"type": "stacked", "title": "الملاحظات بحسب المشروع", "labels": [d["project"] for d in data], "series": [{"name": "مفتوحة", "data": [d["open_snags"] for d in data]}, {"name": "أُصلحت", "data": [d["fixed"] for d in data]}], "format": "num"},
                       {"type": "pie", "title": "سندات الملكية", "labels": [r["status"] for r in tt], "series": [{"name": "سندات", "data": [r["n"] for r in tt]}], "format": "num"}],
            "tables": [_tbl("بحسب المشروع", [("project", "المشروع", "text"), ("scheduled", "مجدولة", "int"), ("done", "مكتملة", "int"), ("open_snags", "ملاحظات مفتوحة", "int"), ("fixed", "أُصلحت", "int")], data)],
            "notes": []}


def r_quotes(c, params):
    frm, to = _period(params)
    pf, pa = _pf(params)
    t = today().isoformat()
    q = rows(c.execute(f"""SELECT q.*, p.name project, u.code FROM quotes q JOIN units u ON u.id=q.unit_id JOIN projects p ON p.id=u.project_id WHERE q.created BETWEEN ? AND ?{pf} ORDER BY q.id DESC""", [frm, to + "z", *pa]))
    for r in q:
        if r["status"] == "issued" and r["valid_until"] < t:
            r["status"] = "expired"
        r["status_label"] = QSTATUS.get(r["status"], r["status"])
    months = _months(frm, to)
    bym = defaultdict(lambda: {"issued": 0, "converted": 0})
    for r in q:
        bym[r["created"][:7]]["issued"] += 1
        if r["status"] == "converted":
            bym[r["created"][:7]]["converted"] += 1
    byu = rows(c.execute(f"""SELECT q.created_by, COUNT(*) n, SUM(CASE WHEN q.status='converted' THEN 1 ELSE 0 END) conv, AVG(q.discount_pct) disc FROM quotes q JOIN units u ON u.id=q.unit_id JOIN projects p ON p.id=u.project_id
                             WHERE q.created BETWEEN ? AND ?{pf} GROUP BY q.created_by ORDER BY n DESC""", [frm, to + "z", *pa]))
    n = len(q)
    conv = sum(1 for r in q if r["status"] == "converted")
    return {"key": "quotes", "title": "عروض الأسعار", "subtitle": f"من {frm} إلى {to}",
            "kpis": [{"label": "عروض صادرة", "value": n}, {"label": "تحوّلت إلى حجز", "value": conv}, {"label": "نسبة التحويل", "value": round(100 * conv / n, 1) if n else 0, "format": "pct"},
                     {"label": "متوسط الخصم", "value": round(100 * sum(r["discount_pct"] or 0 for r in q) / n, 2) if n else 0, "format": "pct"}],
            "charts": [{"type": "bar", "title": "عروض صادرة ومحوَّلة شهريًا", "labels": months, "series": [{"name": "صادرة", "data": [bym[m]["issued"] for m in months]}, {"name": "محوَّلة", "data": [bym[m]["converted"] for m in months]}], "format": "num"}],
            "tables": [_tbl("بحسب مُعدّ العرض", [("created_by", "الموظف", "text"), ("n", "عروض", "int"), ("conv", "تحوّلت", "int"), ("disc", "متوسط الخصم", "pct")], byu),
                       _tbl("العروض", [("number", "الرقم", "text"), ("created", "التاريخ", "date"), ("project", "المشروع", "text"), ("code", "الوحدة", "text"), ("customer_name", "العميل", "text"), ("price", "السعر", "money"), ("status_label", "الحالة", "text")], q[:300])],
            "notes": []}


READY = OrderedDict([
    ("portfolio", {"title": "لوحة المحفظة", "desc": "الوحدات والمبيعات والإنجاز لكل مشروع مع اتجاه المبيعات الشهري.", "fn": r_portfolio, "perm": "view", "group": "عام"}),
    ("sales", {"title": "أداء المبيعات", "desc": "عدد المبيعات وقيمتها شهريًا وبحسب المشروع والنوع والخطة والقناة والوسيط.", "fn": r_sales, "perm": "view", "group": "المبيعات"}),
    ("funnel", {"title": "قمع العملاء المحتملين", "desc": "المراحل والقنوات ونسب التحويل والعملاء المتوقفون.", "fn": r_funnel, "perm": "leads", "group": "المبيعات"}),
    ("quotes", {"title": "عروض الأسعار", "desc": "العروض الصادرة ونسبة تحويلها والخصومات بحسب الموظف.", "fn": r_quotes, "perm": "view", "group": "المبيعات"}),
    ("brokers", {"title": "الوسطاء والعمولات", "desc": "مبيعات كل وسيط وعمولاته المستحقة والمصروفة.", "fn": r_brokers, "perm": "brokers", "group": "المبيعات"}),
    ("collections", {"title": "التحصيل والمتأخرات", "desc": "المستحق مقابل المحصَّل، أعمار المتأخرات، قائمة الأقساط المتأخرة، تبرعات التأخير.", "fn": r_collections, "perm": "finance", "group": "المالية"}),
    ("cash", {"title": "السيولة وحسابات الضمان", "desc": "رادار 12 شهرًا لأرصدة الضمان والعجز المتوقع.", "fn": r_cash, "perm": "finance", "group": "المالية"}),
    ("inventory", {"title": "المخزون والتسعير", "desc": "الشرائح والطلب النسبي وتوصيات محرك التسعير وقيمة المخزون.", "fn": r_inventory, "perm": "inventory", "group": "المخزون"}),
    ("construction", {"title": "الإنشاء مقابل المبيعات", "desc": "الإنجاز والبيع والمستخلصات لكل مشروع.", "fn": r_construction, "perm": "view", "group": "الإنشاء"}),
    ("handover", {"title": "التسليم والجودة", "desc": "التسليمات والملاحظات وسندات الملكية.", "fn": r_handover, "perm": "handover", "group": "التسليم"}),
])


def _perm_ok(perm: str, perms: set) -> bool:
    return perm in perms or "admin" in perms or "reports" in perms


@router.get("/api/reports/catalog")
def catalog(u=Depends(need_any(*PERM))):
    perms = set(u["perms"])
    ready = [{"key": k, "title": v["title"], "desc": v["desc"], "group": v["group"]} for k, v in READY.items() if _perm_ok(v["perm"], perms)]
    return {"ready": ready, "datasets": datasets_public(perms | ({"view", "leads", "finance", "invoices", "service", "inventory", "brokers", "handover"} if "admin" in perms or "reports" in perms else set())),
            "projects": rows(db().execute("SELECT id, name FROM projects ORDER BY id")),
            "links": [{"key": "lender", "title": "تقرير الممول (البنك)", "api": "/api/reports/lender"}, {"key": "investor", "title": "تقرير المستثمرين", "api": "/api/reports/investor"}]}


def run_ready(c, key: str, params: dict, perms: set) -> dict:
    r = READY.get(key)
    if not r:
        raise HTTPException(404, "التقرير غير موجود")
    if not _perm_ok(r["perm"], perms):
        raise HTTPException(403, "ليست لديك صلاحية هذا التقرير")
    doc = r["fn"](c, params or {})
    doc["params"] = {k: params.get(k) for k in ("from", "to", "project_id") if params.get(k)}
    doc["generated"] = now_s()
    return doc


@router.get("/api/reports/ready/{key}")
def ready_report(key: str, request: Request, u=Depends(need_any(*PERM))):
    params = {k: v for k, v in request.query_params.items() if k in ("from", "to", "project_id")}
    return run_ready(db(), key, params, set(u["perms"]))


@router.post("/api/reports/custom/run")
def custom_run(spec: Spec, u=Depends(need_any(*PERM))):
    return run_spec(db(), spec, set(u["perms"]) | ({"view"} if "reports" in u["perms"] else set()))


# ---------------------------------------------------------------- saved definitions
class SavedIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    kind: str = Field(pattern="^(ready|custom)$")
    ref: str | None = Field(default=None, max_length=40)   # ready key
    spec: dict | None = None                                # custom spec
    params: dict = Field(default_factory=dict)
    shared: bool = True


@router.get("/api/reports/saved")
def saved_list(u=Depends(need_any(*PERM))):
    c = db()
    out = []
    for r in rows(c.execute("SELECT * FROM report_defs ORDER BY id DESC")):
        if r["shared"] or r["owner"] == u["username"]:
            r["spec"] = json.loads(r["spec"] or "null")
            r["params"] = json.loads(r["params"] or "{}")
            out.append(r)
    return out


@router.post("/api/reports/saved")
def saved_create(body: SavedIn, u=Depends(act_as("reports"))):
    c = db()
    if body.kind == "ready" and body.ref not in READY:
        raise HTTPException(400, "تقرير جاهز غير معروف")
    if body.kind == "custom":
        Spec(**(body.spec or {}))  # validates
    rid = c.execute("INSERT INTO report_defs(name,kind,ref,spec,params,owner,shared,created) VALUES(?,?,?,?,?,?,?,?)",
                    (body.name, body.kind, body.ref, json.dumps(body.spec, ensure_ascii=False) if body.spec else None, json.dumps(body.params, ensure_ascii=False), u["username"], int(body.shared), now_s())).lastrowid
    audit(c, "حفظ تقرير", f"{body.name} ({body.kind})")
    c.commit()
    return {"id": rid}


@router.post("/api/reports/saved/{rid}/remove")
def saved_remove(rid: int, u=Depends(act_as("reports"))):
    c = db()
    r = one(c, "SELECT * FROM report_defs WHERE id=?", (rid,), "التقرير غير موجود")
    if r["owner"] != u["username"] and "admin" not in u["perms"]:
        raise HTTPException(403, "لا تملك هذا التقرير")
    c.execute("DELETE FROM report_schedules WHERE report_id=?", (rid,))
    c.execute("DELETE FROM report_defs WHERE id=?", (rid,))
    audit(c, "حذف تقرير محفوظ", r["name"])
    c.commit()
    return {"ok": True}


def run_saved(c, rid: int, perms: set, params_override: dict | None = None) -> dict:
    r = one(c, "SELECT * FROM report_defs WHERE id=?", (rid,), "التقرير غير موجود")
    params = {**json.loads(r["params"] or "{}"), **(params_override or {})}
    if r["kind"] == "ready":
        doc = run_ready(c, r["ref"], params, perms)
    else:
        doc = run_spec(c, Spec(**json.loads(r["spec"])), perms)
    doc["title"] = r["name"]
    doc["saved_id"] = rid
    return doc


@router.get("/api/reports/saved/{rid}/run")
def saved_run(rid: int, request: Request, u=Depends(need_any(*PERM))):
    params = {k: v for k, v in request.query_params.items() if k in ("from", "to", "project_id")}
    return run_saved(db(), rid, set(u["perms"]), params)


# ---------------------------------------------------------------- export
class ExportIn(BaseModel):
    format: str = Field(pattern="^(csv|pdf)$")
    kind: str = Field(pattern="^(ready|custom|saved)$")
    ref: str | None = None
    spec: dict | None = None
    params: dict = Field(default_factory=dict)
    saved_id: int | None = None
    table: int = 0  # csv: which table


def _doc_for(c, body: ExportIn, perms: set) -> dict:
    if body.kind == "ready":
        return run_ready(c, body.ref or "", body.params, perms)
    if body.kind == "saved":
        return run_saved(c, int(body.saved_id or 0), perms, body.params)
    return run_spec(c, Spec(**(body.spec or {})), perms)


def to_csv(doc: dict, table: int = 0) -> bytes:
    t = (doc.get("tables") or [{}])[min(table, len(doc.get("tables") or [{}]) - 1)]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([col["label"] for col in t.get("columns", [])])
    for r in t.get("rows", []):
        w.writerow([r.get(col["key"], "") for col in t.get("columns", [])])
    return ("﻿" + buf.getvalue()).encode("utf-8")


@router.post("/api/reports/export")
def export(body: ExportIn, request: Request, u=Depends(need_any(*PERM))):
    from .paperwork import brand
    c = db()
    doc = _doc_for(c, body, set(u["perms"]))
    name = re.sub(r"[^\w؀-ۿ -]", "", doc["title"])[:60] or "report"
    audit(c, "تصدير تقرير", f"{doc['title']} ({body.format})")
    c.commit()
    if body.format == "csv":
        from urllib.parse import quote as q
        return Response(to_csv(doc, body.table), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{q(name)}.csv", "Cache-Control": "no-store"})
    pdf = pdfcharts.render_report(brand(c), doc, by=u["name"])
    from urllib.parse import quote as q
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename*=UTF-8''{q(name)}.pdf", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


# ---------------------------------------------------------------- schedules (e-mail)
class ScheduleIn(BaseModel):
    report_id: int
    cadence: str = Field(pattern="^(daily|weekly|monthly)$")
    hour: int = Field(default=7, ge=0, le=23)
    recipients: str = Field(min_length=5, max_length=400)  # comma-separated e-mails
    format: str = Field(default="pdf", pattern="^(pdf|csv)$")
    active: bool = True


def _next_run(cadence: str, hour: int, after: dt.datetime) -> str:
    n = after.replace(hour=hour, minute=0, second=0, microsecond=0)
    if n <= after:
        n += dt.timedelta(days=1)
    if cadence == "weekly":
        while n.weekday() != 6:  # Sunday — first working day in Oman
            n += dt.timedelta(days=1)
    if cadence == "monthly":
        n = n.replace(day=1)
        if n <= after:
            n = (n + dt.timedelta(days=32)).replace(day=1)
    return n.isoformat(timespec="minutes")


@router.get("/api/reports/schedules")
def schedules(u=Depends(need_any(*PERM))):
    c = db()
    return rows(c.execute("SELECT s.*, d.name report_name FROM report_schedules s JOIN report_defs d ON d.id=s.report_id ORDER BY s.id DESC"))


@router.post("/api/reports/schedules")
def schedule_create(body: ScheduleIn, u=Depends(act_as("reports"))):
    from .identity import EMAIL_RE
    c = db()
    one(c, "SELECT id FROM report_defs WHERE id=?", (body.report_id,), "التقرير غير موجود")
    rcpts = [x.strip().lower() for x in body.recipients.split(",") if x.strip()]
    if not rcpts or any(not EMAIL_RE.match(x) for x in rcpts):
        raise HTTPException(400, "عناوين البريد غير صالحة (افصل بينها بفاصلة)")
    if not mail.available():
        raise HTTPException(503, "خدمة البريد غير مهيّأة — لا يمكن جدولة الإرسال")
    sid = c.execute("INSERT INTO report_schedules(report_id,cadence,hour,recipients,format,active,next_run,created_by,created) VALUES(?,?,?,?,?,?,?,?,?)",
                    (body.report_id, body.cadence, body.hour, ",".join(rcpts), body.format, int(body.active), _next_run(body.cadence, body.hour, dt.datetime.now()), u["username"], now_s())).lastrowid
    audit(c, "جدولة تقرير", f"#{body.report_id} {body.cadence} إلى {len(rcpts)} مستلمًا")
    c.commit()
    return {"id": sid}


@router.post("/api/reports/schedules/{sid}/remove")
def schedule_remove(sid: int, u=Depends(act_as("reports"))):
    c = db()
    c.execute("DELETE FROM report_schedules WHERE id=?", (sid,))
    audit(c, "إلغاء جدولة تقرير", f"#{sid}")
    c.commit()
    return {"ok": True}


def run_due_schedules(c, now: dt.datetime | None = None) -> int:
    """Called by the background tick: renders and e-mails every schedule whose next_run has passed."""
    from .paperwork import brand
    now = now or dt.datetime.now()
    sent = 0
    for s in rows(c.execute("SELECT * FROM report_schedules WHERE active=1 AND next_run<=?", (now.isoformat(timespec="minutes"),))):
        try:
            doc = run_saved(c, s["report_id"], {"admin"})
            if s["format"] == "csv":
                blob, mime, ext = to_csv(doc), "text/csv", "csv"
            else:
                blob, mime, ext = pdfcharts.render_report(brand(c), doc, by="المجدول"), "application/pdf", "pdf"
            for to in s["recipients"].split(","):
                mail.send(to, f"{doc['title']} — تقرير مجدول", f"مرفق تقرير «{doc['title']}» بتاريخ {today().isoformat()}.", kind="report", attachments=[(f"{doc['title']}.{ext}", blob, mime)])
            sent += 1
            c.execute("UPDATE report_schedules SET last_run=?, next_run=? WHERE id=?", (now.isoformat(timespec="minutes"), _next_run(s["cadence"], s["hour"], now), s["id"]))
        except Exception as e:  # noqa: BLE001
            c.execute("UPDATE report_schedules SET last_error=?, next_run=? WHERE id=?", (str(e)[:200], _next_run(s["cadence"], s["hour"], now), s["id"]))
    c.commit()
    return sent


def run_due_all() -> int:
    n = 0
    for t in tenants():
        tok = TENANT.set(t)
        try:
            c = connect()
            try:
                n += run_due_schedules(c)
            finally:
                c.close()
        finally:
            TENANT.reset(tok)
    return n
