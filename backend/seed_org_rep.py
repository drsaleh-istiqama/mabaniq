"""Mabaniq 0.29.0 — saved reports and schedules of a full-demo developer (phase `rep` of backend/seed_org.py).

The report centre starts empty; this saves the reports a manager of a real-estate company would keep at hand — leasing, the books, the people file — as ready reports and as
custom ones built on the datasets, through the reports module's own endpoint functions (so each is checked: a ready key must exist, a custom spec must validate).
Schedules are created INACTIVE and addressed to a placeholder, so a demo deployment with real mail settings can never send anything because of this seed; the page shows
them as the schedule the office would switch on. Payroll reports are never scheduled by mail (the module refuses it). Re-runnable: a report is found by its name.
"""
from __future__ import annotations

from .seed_org_acc import _do, _one

READY = [
    ("متأخرات الإيجار وأعمارها", "lease_aging"), ("إشغال المحفظة والعائد", "lease_occupancy"), ("العقود المنتهية خلال 90 يومًا", "lease_expiring"),
    ("الشيكات المؤجلة وحالتها", "lease_cheques"), ("تقرير الإيجار الشهري", "lease_monthly"), ("كشوف الملاك الشهرية", "lease_owners"),
    ("ميزان المراجعة", "acc_trial"), ("قائمة الدخل", "acc_income"), ("قائمة المركز المالي", "acc_balance"), ("أعمار ذمم الموردين", "acc_payables"),
    ("إقرار ضريبة القيمة المضافة", "acc_vat"), ("القوى العاملة بحسب القسم والجنسية", "hr_headcount"), ("أرصدة الإجازات", "hr_leave"),
    ("انتهاء الوثائق والشهادات", "hr_expiry"), ("الحضور الشهري", "hr_attendance"), ("الامتثال التدريبي", "hr_training"), ("ملخص الرواتب (إجماليات بلا أسماء)", "hr_payroll"),
    ("التحصيل والمتأخرات (المبيعات)", "collections"), ("لوحة المحفظة", "portfolio"),
]
CUSTOM = [
    ("العقود السارية بحسب العقار", {"dataset": "leases", "filters": [{"col": "status", "op": "eq", "value": "active"}], "group_by": [{"col": "project"}],
                                  "aggs": [{"fn": "count", "label": "عدد العقود"}, {"fn": "sum", "col": "annual_rent", "label": "الإيجار السنوي"}], "title": "العقود السارية بحسب العقار"}),
    ("مقبوضات الإيجار بحسب طريقة السداد", {"dataset": "rent_payments", "group_by": [{"col": "method"}], "aggs": [{"fn": "count", "label": "عدد الحركات"}, {"fn": "sum", "col": "amount", "label": "المقبوض"}],
                                          "title": "مقبوضات الإيجار بحسب طريقة السداد"}),
    ("الموظفون بحسب القسم", {"dataset": "employees", "filters": [{"col": "status", "op": "ne", "value": "terminated"}], "group_by": [{"col": "department"}],
                            "aggs": [{"fn": "count", "label": "عدد الموظفين"}], "title": "الموظفون بحسب القسم"}),
    ("الإجازات المعتمدة بحسب النوع", {"dataset": "leave_requests", "filters": [{"col": "status", "op": "eq", "value": "approved"}], "group_by": [{"col": "type_key"}],
                                     "aggs": [{"fn": "count", "label": "عدد الطلبات"}, {"fn": "sum", "col": "days", "label": "الأيام"}], "title": "الإجازات المعتمدة بحسب النوع"}),
    ("مصروفات الأقسام من أسطر القيود", {"dataset": "journal_lines", "filters": [{"col": "account_type", "op": "eq", "value": "expense"}], "group_by": [{"col": "account"}],
                                        "aggs": [{"fn": "sum", "col": "debit", "label": "المدين"}], "title": "المصروفات بحسب الحساب"}),
]
# (report name, cadence, hour) — all inactive
SCHEDULES = [("متأخرات الإيجار وأعمارها", "weekly", 7), ("العقود المنتهية خلال 90 يومًا", "monthly", 8), ("ميزان المراجعة", "monthly", 9), ("انتهاء الوثائق والشهادات", "weekly", 7),
             ("إشغال المحفظة والعائد", "monthly", 8)]


def run(ctx) -> dict:
    from . import reports
    for name, ref in READY:
        if _one(ctx, "SELECT 1 x FROM report_defs WHERE name=?", (name,)):
            continue
        if _do(ctx, "admin", reports.saved_create, reports.SavedIn(name=name, kind="ready", ref=ref, shared=True)):
            ctx.add("saved_reports")
    for name, spec in CUSTOM:
        if _one(ctx, "SELECT 1 x FROM report_defs WHERE name=?", (name,)):
            continue
        if _do(ctx, "admin", reports.saved_create, reports.SavedIn(name=name, kind="custom", spec=spec, shared=True)):
            ctx.add("saved_reports")
    for name, cadence, hour in SCHEDULES:
        d = _one(ctx, "SELECT id FROM report_defs WHERE name=?", (name,))
        if not d or _one(ctx, "SELECT 1 x FROM report_schedules WHERE report_id=?", (d["id"],)):
            continue
        if _do(ctx, "admin", reports.schedule_create, reports.ScheduleIn(report_id=d["id"], cadence=cadence, hour=hour, recipients="reports@example.test", format="pdf", active=False)):
            ctx.add("schedules")
    return ctx.counts
