"""Mabaniq 0.28.0 — the assistant's tools for the leasing (extended), accounting and HR modules (design §6).

They are registered into the assistant's own tables (`TOOLS`, `TOOL_MODULE`, `RULES`, `FOLLOW`, `_SCHEMA`), so the module registry decides what exists: a tool whose module is off is
neither offered to the language model nor reachable by the local engine. Read-only, filtered by the asker's permissions. Salary figures are shown only to `hr_payroll`, and
never when the answer would leave for an external model (`ctx.external`); an employee without the HR permission can ask only about their own leave.
"""
from __future__ import annotations

import datetime as dt

from .common import rows


def register(A) -> None:
    omr, n, d, today = A.omr, A.n, A.d, A.today

    def who(ctx, name, ref):
        return name if (not ctx.external or ctx.names) else f"موظف #{ref}"

    # ------------------------------------------------------------------------------------------------- leasing, extended
    def t_leasing(ctx, a):
        from .leasing import _units_state, aging
        c = ctx.c
        t = today()
        ls = [dict(r) for r in c.execute('SELECT id,"end",annual_rent,status FROM leases')]
        act = [r for r in ls if r["status"] == "active"]
        soon = [r for r in act if d(r["end"]) and t <= d(r["end"]) <= t + dt.timedelta(days=90)]
        ag = aging(c)
        vacant = [u for u in _units_state(c) if u["state"] == "vacant"]
        chq = c.execute("""SELECT COUNT(*) n, COALESCE(SUM(amount),0) v FROM cheques WHERE COALESCE(direction,'in')='in' AND status='held' AND due_date<=?""", ((t + dt.timedelta(days=7)).isoformat(),)).fetchone()
        bounced = c.execute("SELECT COUNT(*) n FROM cheques WHERE COALESCE(direction,'in')='in' AND status='bounced'").fetchone()["n"]
        lines = [f"عقود إيجار سارية {n(len(act))} بإجمالي إيجار سنوي {omr(sum(r['annual_rent'] or 0 for r in act))}.",
                 f"تنتهي خلال 90 يومًا: {n(len(soon))}. وحدات شاغرة: {n(len(vacant))}."]
        if ag["total"] > 0.0005:
            lines.append(f"متأخرات الإيجار {omr(ag['total'])}: " + "؛ ".join(f"{b['label']} {omr(b['amount'])}" for b in ag["buckets"] if b["amount"] > 0.0005) + ".")
            top = ag["leases"][:3]
            lines.append("أكبر المتأخرين: " + "؛ ".join(f"{ctx.who(x['tenant'], x['tenant_id'])} ({omr(x['amount'])})" for x in top) + ".")
        else:
            lines.append("لا متأخرات إيجار.")
        lines.append(f"شيكات مؤجلة حان إيداعها خلال 7 أيام: {n(chq['n'])} بقيمة {omr(chq['v'])}. شيكات مرتجعة: {n(bounced)}.")
        return {"data": {"active": len(act), "annual_rent": sum(r["annual_rent"] or 0 for r in act), "ending_90d": len(soon), "overdue_total": ag["total"], "overdue_buckets": ag["buckets"],
                         "vacant": len(vacant), "cheques_due_7d": {"count": chq["n"], "amount": chq["v"]}, "cheques_bounced": bounced},
                "text": "\n".join(lines), "source": "محفظة التأجير"}

    # ------------------------------------------------------------------------------------------------- accounting
    def t_accounting(ctx, a):
        if ctx.external:   # the books are answered by the local engine only (0.28.1)
            return {"data": None, "text": "بيانات المحاسبة لا تُرسل إلى نموذج لغوي خارجي. اطرح سؤالك كما هو وسيجيبه المساعد المحلي.", "source": "المحاسبة"}
        from . import ledger
        from .acc_reports import balances, income_statement
        c = ctx.c
        if not ledger.start_date(c):
            return {"data": None, "text": "المحاسبة غير مفعَّلة بعد في هذه المؤسسة — فعّلها من «المحاسبة ← الإعداد».", "source": "المحاسبة"}
        t = today().isoformat()
        accs = rows(c.execute("SELECT id, code, name, type, normal, postable, system_key, cash_class FROM acc_accounts"))
        bal = balances(c, None, t, True)
        cash = [(x, bal.get(x["id"], 0.0)) for x in accs if x["postable"] and x["cash_class"] == "cash"]
        lines, data = [], {}
        q = (a.get("account") or "").strip()
        if q:
            hits = [x for x in accs if x["postable"] and (x["code"] == q or q in x["name"])][:5]
            if hits:
                part = []
                for x in hits:
                    v = bal.get(x["id"], 0.0) * (1 if x["normal"] == "debit" else -1)
                    part.append(f"{x['code']} {x['name']}: {omr(v)}")
                    data.setdefault("accounts", []).append({"code": x["code"], "name": x["name"], "balance": round(v, 3)})
                lines.append("الأرصدة في " + t + " — " + "؛ ".join(part) + ".")
            else:
                lines.append(f"لم أجد حسابًا يطابق «{q}».")
        if not q or not hits:
            tot_cash = round(sum(v for _x, v in cash), 3)
            data["cash_total"] = tot_cash
            lines.append(f"النقد والبنوك: {omr(tot_cash)}" + (" (" + "؛ ".join(f"{x['name']} {omr(v)}" for x, v in cash[:4]) + ")." if cash else "."))
            inc = income_statement(c, f"{t[:4]}-01-01", t)
            data["ytd"] = {"revenue": inc["revenue"], "expenses": inc["expenses"], "net": inc["net"]}
            lines.append(f"منذ بداية السنة: الإيرادات {omr(inc['revenue'])}، المصروفات {omr(inc['expenses'])}، صافي {omr(inc['net'])}.")
            diff = c.execute("""SELECT COALESCE(SUM(l.debit),0) - COALESCE(SUM(l.credit),0) FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id WHERE j.status IN ('posted','reversed')""").fetchone()[0]
            pend = c.execute("SELECT COUNT(*) FROM acc_journals WHERE status='pending'").fetchone()[0]
            data["trial_diff"], data["pending_journals"] = round(diff, 3), pend
            lines.append(("الميزان متوازن." if abs(diff) < 0.0005 else f"تنبيه: الميزان غير متوازن بفرق {omr(diff)}.") + (f" قيود بانتظار الاعتماد: {n(pend)}." if pend else ""))
            ap = c.execute("SELECT COALESCE(SUM(total-paid),0) FROM ap_bills WHERE status IN ('approved','partly_paid')").fetchone()[0]
            data["payables"] = round(ap, 3)
            if ap > 0.0005:
                lines.append(f"المستحق للموردين: {omr(ap)}.")
            try:
                from .acc_assets import vat_compute
                v = vat_compute(c, today().year, (today().month - 1) // 3 + 1)
                data["vat"] = {"output": v["output_vat"], "input": v["input_vat"], "net": v["net"]}
                lines.append(f"ضريبة الربع الحالي: مخرجات {omr(v['output_vat'])}، مدخلات {omr(v['input_vat'])}، صافي {omr(v['net'])}.")
            except Exception:  # noqa: BLE001 — a missing VAT set-up must not hide the rest
                pass
        return {"data": data, "text": "\n".join(lines), "source": "المحاسبة"}

    # ------------------------------------------------------------------------------------------------- HR
    def _self_text(ctx):
        from . import hr_leave
        c = ctx.c
        eid = ctx.u.get("employee_id")
        e = c.execute("SELECT * FROM employees WHERE id=?", (eid,)).fetchone() if eid else None
        if not e:
            return {"data": None, "text": "حسابك غير مرتبط بملف موظف، فلا أستطيع إخبارك برصيد إجازاتك.", "source": "الموارد البشرية"}
        bs = hr_leave.balances_of(c, dict(e), today().year)
        c.commit()
        return {"data": {"balances": [{"name": b["name"], "remaining": b["remaining"], "pending": b["pending"]} for b in bs]},
                "text": "رصيد إجازاتك لهذه السنة: " + ("؛ ".join(f"{b['name']} {n(b['remaining'])} يومًا" + (f" (منها {n(b['pending'])} قيد الطلب)" if b["pending"] else "") for b in bs) or "لا أنواع إجازة مفعَّلة") + ".",
                "source": "الموارد البشرية"}

    def t_hr(ctx, a):
        c = ctx.c
        if ctx.external:   # the people file (counts, leave, balances, payroll) is answered by the local engine only (0.28.1)
            return {"data": None, "text": "بيانات الموارد البشرية لا تُرسل إلى نموذج لغوي خارجي. اطرح سؤالك كما هو وسيجيبه المساعد المحلي.", "source": "الموارد البشرية"}
        if not ctx.can("hr"):
            return _self_text(ctx) if ctx.can("hr_self") else {"data": None, "text": "", "source": ""}
        if a.get("topic") == "self":
            return _self_text(ctx)
        from .hr import expiry_items
        t = today()
        es = rows(c.execute("SELECT id, name, omani FROM employees WHERE status!='terminated'"))
        nn = len(es)
        om = sum(1 for e in es if e["omani"])
        on_leave = c.execute("SELECT COUNT(DISTINCT employee_id) FROM leave_requests WHERE status='approved' AND from_date<=? AND to_date>=?", (t.isoformat(), t.isoformat())).fetchone()[0]
        pend = c.execute("SELECT COUNT(*) FROM leave_requests WHERE status='pending'").fetchone()[0]
        items = expiry_items(c, t, 30)
        lines = [f"على رأس العمل {n(nn)} موظفًا" + (f"، منهم {n(om)} عُمانيًا ({round(100 * om / nn)}٪)." if nn else "."),
                 f"في إجازة اليوم: {n(on_leave)}. طلبات إجازة بانتظار القرار: {n(pend)}."]
        if items:
            lines.append(f"وثائق وشهادات تنتهي خلال 30 يومًا أو انتهت: {n(len(items))} — " + "؛ ".join(f"{who(ctx, i['name'], i['employee_id'])} ({i['label']}{' منتهٍ' if i['days_left'] < 0 else ' بعد ' + str(i['days_left']) + ' يومًا'})" for i in items[:3]) + ".")
        else:
            lines.append("لا وثائق تنتهي خلال 30 يومًا.")
        data = {"headcount": nn, "omani": om, "on_leave_today": on_leave, "pending_leave": pend, "expiring_30d": len(items)}
        if ctx.can("hr_payroll") and not ctx.external:
            r = c.execute("SELECT period, headcount, gross, net FROM payroll_runs WHERE status IN ('approved','paid') ORDER BY period DESC LIMIT 1").fetchone()
            if r:
                data["payroll"] = dict(r)
                lines.append(f"آخر مسيّر معتمد ({r['period']}): إجمالي {omr(r['gross'])} وصافي {omr(r['net'])} لـ {n(r['headcount'])} موظفًا.")
        return {"data": data, "text": "\n".join(lines), "source": "الموارد البشرية"}

    # ------------------------------------------------------------------------------------------------- registration
    A.t_leasing = t_leasing
    A.TOOLS["leasing"] = (("leasing",), "محفظة التأجير: العقود السارية والإيجار السنوي، المتأخرات بحسب العمر وأكبر المتأخرين، الشواغر، العقود المنتهية قريبًا، الشيكات المؤجلة والمرتجعة.", t_leasing)
    A.TOOLS["accounting"] = (("accounting",), "المحاسبة: رصيد حساب بعينه (بالرمز أو الاسم)، النقد والبنوك، الإيرادات والمصروفات منذ بداية السنة، توازن الميزان، المستحق للموردين، ضريبة الربع.", t_accounting)
    A.TOOLS["hr"] = (("hr", "hr_self"), "الموارد البشرية: عدد الموظفين ونسبة العُمانيين، من في إجازة، طلبات الإجازة المعلقة، وثائق تنتهي قريبًا؛ ولمن يملك صلاحية الرواتب آخر مسيّر؛ وللموظف رصيد إجازاته.", t_hr)
    A.TOOL_MODULE.update({"accounting": "accounting", "hr": "hr"})
    A._SCHEMA["accounting"] = {"account": "رمز الحساب أو جزء من اسمه (اختياري) مثل «البنك» أو «إيراد الإيجار»"}
    A._SCHEMA["hr"] = {"topic": "اكتب self للسؤال عن رصيد إجازات السائل نفسه (اختياري)"}
    A.RULES.extend([
        ("accounting", [("محاسبه", 4), ("ميزان", 5), ("ميزانيه", 4), ("قيد", 3), ("قيود", 3), ("رصيد", 3), ("بنك", 3), ("البنوك", 3), ("صندوق", 3), ("ضريبه", 4), ("قيمه مضافه", 4), ("ربح", 3), ("ارباح", 3),
                        ("خساره", 3), ("ايرادات", 3), ("مصروفات", 3), ("مصاريف", 2), ("ذمم", 3), ("موردين", 3), ("نقد", 1)]),
        ("hr", [("موظف", 3), ("موظفين", 4), ("موظفون", 4), ("اجازه", 4), ("اجازات", 4), ("اجازتي", 5), ("رصيد اجازه", 5), ("رصيد اجازتي", 6), ("موارد بشريه", 4), ("رواتب", 4), ("راتب", 3), ("مسير", 4), ("تدريب", 3),
                ("حضور", 3), ("غياب", 3), ("اقامه", 3), ("جواز", 3), ("وثايق الموظفين", 4), ("عمانه", 3), ("تعمين", 3)]),
        ("leasing", [("متاخرات", 3), ("شيك", 4), ("شيكات", 4), ("عقود تنتهي", 4), ("شواغر", 3), ("شاغره", 3)]),
    ])
    A.FOLLOW["accounting"] = ["ما رصيد البنك؟", "هل الميزان متوازن؟", "كم صافي الربح هذه السنة؟"]
    A.FOLLOW["hr"] = ["من في إجازة اليوم؟", "ما الوثائق التي تنتهي قريبًا؟", "كم نسبة العُمانيين؟"]
    A.FOLLOW["leasing"] = ["ما الإيجارات المتأخرة؟", "ما الشيكات المؤجلة؟", "كم وحدة شاغرة؟"]
