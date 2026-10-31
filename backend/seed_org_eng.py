"""0.29.0 — the engineering side of the full-demo organisations: every project gets a contractor contract, a programme, a budget, site reports, a payment certificate
(IPC), a change order, a non-conformance report and its licences, so the construction and escrow screens open on a working project whatever the project.

The platform's own base seed (`seed_ext.seed_ext`) covers the first three projects only; projects added later (a fourth development, a plot in design) were left bare. This phase
adds what is missing, project by project, and never touches a project that already has a contract (get-or-create on `contracts_c` / `ipcs` / `change_orders` / `ncrs` / `permits`).
These are illustrative figures — nothing here comes from a real contract.
"""
from __future__ import annotations

import calendar
import datetime as dt

STAGES = [("التصاريح والتجهيز", .05), ("الحفر والأساسات", .12), ("الهيكل الخرساني", .30), ("البلوك والتمديدات", .18),
          ("التشطيبات الداخلية", .20), ("الواجهات والأعمال الخارجية", .10), ("الاختبار والتسليم", .05)]
CONTRACTOR = ("شركة الأفق للإنشاءات", "1189932")
WEATHER = ["مشمس", "حار ورطب", "غبار خفيف"]
WORK = ["صب سقف", "أعمال بلوك", "تمديدات كهربائية", "لياسة داخلية", "عزل أسطح", "حفر وردم", "تركيب حديد التسليح"]
ISSUES = ["", "", "تأخر توريد حديد التسليح يومين", "نقص عمالة في وردية المساء", ""]


def _m(d: dt.date, months: int) -> dt.date:
    y, mo = divmod(d.month - 1 + months, 12)
    y, mo = d.year + y, mo + 1
    return dt.date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def _rows(ctx, sql, args=()):
    with ctx.request():
        c = ctx.conn()
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def _exec(ctx, sql, args=()):
    with ctx.request():
        c = ctx.conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def _has(ctx, table, pid) -> bool:
    return bool(_rows(ctx, f"SELECT 1 x FROM {table} WHERE project_id=?", (pid,)))


def _contractor(ctx) -> int:
    r = _rows(ctx, "SELECT id FROM contractors WHERE name=?", (CONTRACTOR[0],))
    if r:
        return r[0]["id"]
    return _exec(ctx, "INSERT INTO contractors(name,cr_number) VALUES(?,?)", CONTRACTOR)


def _handover(p, today) -> dt.date:
    try:
        return dt.date.fromisoformat(str(p.get("handover"))[:10])
    except (TypeError, ValueError):
        return _m(today, 18)


def run(ctx) -> dict:
    today = ctx.today
    rnd = ctx.rnd
    projects = _rows(ctx, "SELECT * FROM projects WHERE COALESCE(completed,0)=0 ORDER BY id")
    kid = None
    for p in projects:
        pj, build = p["id"], float(p.get("build_pct") or 0)
        ho = _handover(p, today)
        if not _has(ctx, "contracts_c", pj):
            kid = kid or _contractor(ctx)
            value = (_rows(ctx, "SELECT SUM(price) s FROM units WHERE project_id=?", (pj,))[0]["s"] or 3_000_000) * .72
            months = 30 if p.get("kind") == "tower" else 24
            start = _m(ho, -months)
            _exec(ctx, "INSERT INTO contracts_c(project_id,contractor_id,value,retention_pct,delay_penalty_per_day,start,finish) VALUES(?,?,?,?,?,?,?)",
                  (pj, kid, round(value, -3), .10, round(value * .0005, -1), start.isoformat(), ho.isoformat()))
            ctx.add("contracts")
            acc, prev = 0.0, None
            for nm, w in STAGES:
                s0, e0 = _m(start, round(months * acc)), _m(start, round(months * (acc + w)))
                lo, hi = acc * 100, (acc + w) * 100
                pct = 100 if build >= hi else 0 if build <= lo else round((build - lo) / (hi - lo) * 100)
                prev = _exec(ctx, "INSERT INTO schedule_tasks(project_id,name,planned_start,planned_end,actual_start,actual_end,pct,depends_on,weight) VALUES(?,?,?,?,?,?,?,?,?)",
                             (pj, nm, s0.isoformat(), e0.isoformat(), s0.isoformat() if pct > 0 else None, e0.isoformat() if pct == 100 else None, pct, prev, w))
                acc += w
            ctx.add("tasks", len(STAGES))
            if not _has(ctx, "budgets", pj):
                for cat, share in (("أعمال إنشائية", .62), ("كهروميكانيك", .18), ("تشطيبات", .12), ("استشارات وإشراف", .04), ("احتياطي طوارئ", .04)):
                    _exec(ctx, "INSERT INTO budgets(project_id,category,amount) VALUES(?,?,?)", (pj, cat, round(value * share, -3)))
                ctx.add("budget_lines", 5)
        kid_p = (_rows(ctx, "SELECT contractor_id k FROM contracts_c WHERE project_id=? ORDER BY id LIMIT 1", (pj,)) or [{"k": None}])[0]["k"]
        if not _has(ctx, "site_reports", pj) and build > 0:
            for i in range(3):
                d = today - dt.timedelta(days=i + 1)
                _exec(ctx, "INSERT INTO site_reports(project_id,day,workers,weather,work_done,issues,photos,by) VALUES(?,?,?,?,?,?,?,?)",
                      (pj, d.isoformat(), rnd.randint(30, 120), rnd.choice(WEATHER), rnd.choice(WORK), rnd.choice(ISSUES), rnd.randint(4, 24), "مهندس الموقع"))
            ctx.add("site_reports", 3)
        if not _has(ctx, "ipcs", pj) and kid_p:
            value = (_rows(ctx, "SELECT value v FROM contracts_c WHERE project_id=? LIMIT 1", (pj,)) or [{"v": 0}])[0]["v"] or 0
            cum, stage = 0.0, STAGES[-1][0]
            for nm, w in STAGES:
                cum += w
                if build / 100 <= cum + 1e-9:
                    stage = nm
                    break
            created = (today - dt.timedelta(days=4)).isoformat()
            _exec(ctx, "INSERT INTO ipcs(project_id,contractor_id,no,stage,claimed_pct,stage_value,status,approved_pct,created) VALUES(?,?,?,?,?,?,?,?,?)",
                  (pj, kid_p, 1, STAGES[0][0], 100, round(value * .05, -3), "approved", 100, (today - dt.timedelta(days=40)).isoformat()))
            if build >= 10:
                iid = _exec(ctx, "INSERT INTO ipcs(project_id,contractor_id,no,stage,claimed_pct,stage_value,status,approved_pct,created) VALUES(?,?,?,?,?,?,?,?,?)",
                            (pj, kid_p, 2, stage, 60, round(value * .12, -3), "pending", None, created))
                for it, w, v, ev in (("أعمال الحفر والأساسات", .5, 100, 18), ("حديد التسليح", .3, 70, 9), ("الصب والمعالجة", .2, 40, 6)):
                    _exec(ctx, "INSERT INTO ipc_items(ipc_id,item,weight,verified_pct,evidence) VALUES(?,?,?,?,?)", (iid, it, w, v, ev))
            ctx.add("ipcs", 2 if build >= 10 else 1)
        if not _has(ctx, "change_orders", pj):
            _exec(ctx, "INSERT INTO change_orders(project_id,no,title,reason,cost,days,status,requested,decided,decided_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (pj, 1, "تعديل مواصفات التشطيب في الردهات", "طلب تسويقي", 27_500, 8, "approved", (today - dt.timedelta(days=39)).isoformat(), (today - dt.timedelta(days=30)).isoformat(), "مدير المنصة"))
            _exec(ctx, "INSERT INTO change_orders(project_id,no,title,reason,cost,days,status,requested,decided,decided_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (pj, 2, "إضافة مواقف زوار وتوسعة المدخل", "متطلب بلدية", 46_000, 14, "pending", (today - dt.timedelta(days=12)).isoformat(), None, None))
            ctx.add("change_orders", 2)
        if not _has(ctx, "ncrs", pj) and build > 0:
            _exec(ctx, "INSERT INTO ncrs(project_id,title,severity,status,raised,closed,location) VALUES(?,?,?,?,?,?,?)",
                  (pj, "تفاوت في منسوب الخرسانة المصبوبة بالطابق الأول", "major", "open", (today - dt.timedelta(days=9)).isoformat(), None, "F1"))
            _exec(ctx, "INSERT INTO ncrs(project_id,title,severity,status,raised,closed,location) VALUES(?,?,?,?,?,?,?)",
                  (pj, "تأخر تركيب حواجز السلامة بالسقالات", "minor", "closed", (today - dt.timedelta(days=21)).isoformat(), (today - dt.timedelta(days=15)).isoformat(), "السقالات"))
            ctx.add("ncrs", 2)
        if not _has(ctx, "permits", pj):
            rows = (("بلدية مسقط", "رخصة بناء", "BLD-2026-" + str(1100 + pj), "issued", -8, -7, 12),
                    ("وزارة الإسكان والتخطيط العمراني", "تسجيل المشروع وفتح حساب الضمان", "ESC-" + str(300 + pj), "issued", -7, -6, None),
                    ("هيئة البيئة", "تصريح بيئي", "ENV-" + str(4000 + pj), "in_review", -1, None, None),
                    ("الدفاع المدني والإسعاف", "اعتماد مخططات السلامة", "", "submitted", -1, None, None))
            for auth, kind, ref, st, ap, iss, exp in rows:
                _exec(ctx, "INSERT INTO permits(project_id,authority,kind,ref,status,applied,issued,expires) VALUES(?,?,?,?,?,?,?,?)",
                      (pj, auth, kind, ref, st, _m(today, ap).isoformat(), _m(today, iss).isoformat() if iss is not None else None,
                       (_m(today, exp) + dt.timedelta(days=12)).isoformat() if exp is not None else None))
            ctx.add("permits", len(rows))
    return ctx.counts
