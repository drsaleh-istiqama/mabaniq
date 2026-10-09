"""محركات الذكاء في مبانيك.

كل محرك هنا يحسب نتائجه من البيانات الحية ويُرجع «الأسباب» مع التوصية (قابلية التفسير).
في MVP هي نماذج إحصائية شفافة؛ يمكن لاحقًا استبدال أي محرك بنموذج تعلّم آلي بالواجهة نفسها.
"""
import datetime as dt
from collections import defaultdict

TODAY = dt.date.today


AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def ar_month(m: str) -> str:
    y, mo = m.split("-")
    return f"{AR_MONTHS[int(mo) - 1]} {y}"


def d(s):
    return dt.date.fromisoformat(s) if s else None


# ---------------------------------------------------------------- التسعير الديناميكي
def pricing(c, project_id: int):
    """سرعة البيع لكل شريحة (مشروع × إطلالة × نوع) في آخر 90 يومًا مقابل متوسط المشروع."""
    today = TODAY()
    since = (today - dt.timedelta(days=90)).isoformat()
    rows = c.execute("""
      SELECT u.view, u.type, COUNT(*) total,
        SUM(CASE WHEN u.status='a' THEN 1 ELSE 0 END) avail,
        SUM(CASE WHEN b.status IN('confirmed','pending') AND b.created>=? THEN 1 ELSE 0 END) recent
      FROM units u LEFT JOIN bookings b ON b.unit_id=u.id AND b.status!='cancelled'
      WHERE u.project_id=? GROUP BY u.view,u.type""", (since, project_id)).fetchall()
    segs = []
    tot_recent = sum(r["recent"] for r in rows)
    tot_units = sum(r["total"] for r in rows) or 1
    base_rate = tot_recent / tot_units  # مبيعات حديثة لكل وحدة في المشروع
    for r in rows:
        rate = r["recent"] / r["total"] if r["total"] else 0
        ratio = rate / base_rate if base_rate else 1
        absorbed = 1 - r["avail"] / r["total"]
        if r["avail"] == 0:
            adj = 0.0
        elif ratio >= 1.4 and absorbed >= .7:
            adj = .04
        elif ratio >= 1.15:
            adj = .02
        elif ratio <= .6 and absorbed < .6:
            adj = -.02
        else:
            adj = 0.0
        segs.append({"view": r["view"], "type": r["type"], "total": r["total"], "available": r["avail"],
                     "recent_sales": r["recent"], "absorption": round(absorbed, 2),
                     "demand_ratio": round(ratio, 2), "suggested_change": adj,
                     "reason": f"بيع {r['recent']} من {r['total']} خلال ٩٠ يومًا، أي {ratio:.1f} ضعف متوسط المشروع؛ "
                               f"المتاح المتبقي: {r['avail']}."})
    return segs


def unit_suggestion(c, unit_row):
    segs = pricing(c, unit_row["project_id"])
    s = next((x for x in segs if x["view"] == unit_row["view"] and x["type"] == unit_row["type"]), None)
    if not s or unit_row["status"] != "a":
        return None
    return {"change": s["suggested_change"],
            "price": round(unit_row["price"] * (1 + s["suggested_change"]) / 100) * 100,
            "reason": s["reason"]}


# ---------------------------------------------------------------- التنبؤ بالتعثر
def default_risk(c, horizon_days: int = 60):
    today = TODAY()
    rows = c.execute("""
      SELECT i.*, b.id bid, b.customer_id, cu.name cname, cu.phone, cu.rescheduled, u.code ucode, p.name pname
      FROM installments i JOIN bookings b ON b.id=i.booking_id JOIN customers cu ON cu.id=b.customer_id
      JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id
      WHERE b.status='confirmed' ORDER BY i.booking_id, i.seq""").fetchall()
    by_b = defaultdict(list)
    for r in rows:
        by_b[r["bid"]].append(r)
    out = []
    for bid, ins in by_b.items():
        past = [i for i in ins if d(i["due_date"]) <= today and i["seq"] > 1]
        nxt = next((i for i in ins if d(i["due_date"]) > today), None)
        if not past or not nxt:
            continue
        lates, partial, overdue_amt = 0, 0, 0
        for i in past:
            pd = d(i["paid_date"])
            if i["paid_amount"] < i["amount"] - 1:
                if i["paid_amount"] > 0:
                    partial += 1
                overdue_amt += i["amount"] - i["paid_amount"]
            if pd is None or (pd - d(i["due_date"])).days > 7:
                lates += 1
        n = len(past)
        last_pd = d(past[-1]["paid_date"])
        last_late = last_pd is None or (last_pd - d(past[-1]["due_date"])).days > 7
        score = min(.97, .08 + .5 * (lates / n) + .3 * (partial / n) + (.2 if overdue_amt > 0 else 0)
                    + (.12 if last_late else 0))
        if ins[0]["rescheduled"]:
            score *= .5
        if score < .4 or (d(nxt["due_date"]) - today).days > horizon_days * 3:
            continue
        reasons = []
        if lates:
            reasons.append(f"تأخر {lates} من {n} أقساط سابقة أكثر من ٧ أيام")
        if partial:
            reasons.append(f"{partial} دفعات جزئية")
        if overdue_amt:
            reasons.append(f"متأخرات قائمة {overdue_amt:,.0f} ر.ع")
        out.append({"booking_id": bid, "customer_id": ins[0]["customer_id"], "customer": ins[0]["cname"],
                    "unit": ins[0]["ucode"], "project": ins[0]["pname"], "next_due": nxt["due_date"],
                    "next_amount": nxt["amount"], "overdue": overdue_amt, "score": round(score * 100),
                    "reasons": reasons,
                    "action": "عرض إعادة جدولة" if score >= .7 else "اتصال من المحصّل"})
    return sorted(out, key=lambda x: -x["score"])


# ---------------------------------------------------------------- رادار السيولة
def _months(n=12):
    m0 = TODAY().replace(day=1)
    out = []
    for k in range(1, n + 1):
        y, mo = divmod(m0.month - 1 + k, 12)
        out.append(f"{m0.year + y}-{mo + 1:02d}")
    return out


def project_cash(c, project_id: int, apply_plan: bool = False):
    """رادار سيولة لكل مشروع على حدة: أموال المشترين في حساب ضمان المشروع لا تموّل مشروعًا آخر."""
    today = TODAY()
    months = _months()
    risk = {r["booking_id"]: r["score"] / 100 for r in default_risk(c, 365)}
    inflow, outflow, drivers = defaultdict(float), defaultdict(float), defaultdict(list)
    for r in c.execute("""SELECT i.booking_id, substr(i.due_date,1,7) m, i.amount-i.paid_amount due, b.status
                          FROM installments i JOIN bookings b ON b.id=i.booking_id JOIN units u ON u.id=b.unit_id
                          WHERE u.project_id=? AND b.status IN('confirmed','pending') AND i.due_date>?""",
                       (project_id, today.isoformat())):
        p = .55 if r["status"] == "pending" else 1 - risk.get(r["booking_id"], .03)
        inflow[r["m"]] += r["due"] * p
    since = (today - dt.timedelta(days=90)).isoformat()
    r = c.execute("""SELECT COUNT(*) n, AVG(b.price) avg FROM bookings b JOIN units u ON u.id=b.unit_id
                     WHERE u.project_id=? AND b.created>=? AND b.status!='cancelled'""", (project_id, since)).fetchone()
    pace, avg = (r["n"] or 0) / 3, r["avg"] or 0
    facility = float((c.execute("SELECT v FROM settings WHERE k=?", (f"facility:{project_id}",)).fetchone() or [0])[0])
    fac_months = int((c.execute("SELECT v FROM settings WHERE k=?", (f"facility_months:{project_id}",)).fetchone() or [0])[0])
    for k, m in enumerate(months):
        inflow[m] += pace * avg * .10  # عربون المبيعات الجديدة بالسرعة الحالية
        if k < fac_months:
            inflow[m] += facility  # سحب من تسهيل تمويل الإنشاء (بنك/حقوق ملكية المطوّر)
    for x in c.execute("SELECT month, amount, label FROM cost_schedule WHERE project_id=?", (project_id,)):
        if x["month"] in months:
            outflow[x["month"]] += x["amount"]
            if "الهيكل" in x["label"] or x["amount"] >= 500000:
                drivers[x["month"]].append(x["label"])
    actions = []
    if apply_plan:
        big = max(months, key=lambda m: outflow[m])
        i = months.index(big)
        base = sorted(outflow[m] for m in months)[len(months) // 2]
        excess = max(0, outflow[big] - base)
        if excess and i + 2 < len(months):
            outflow[big] -= excess / 2
            outflow[months[i + 2]] += excess / 2
            actions.append(f"تقسيط {drivers[big][0] if drivers[big] else 'المستخلص الأكبر'} على دفعتين بالتفاوض مع المقاول "
                           f"(تأجيل {excess/2:,.0f} ر.ع شهرين)")
        extra_units = 6
        for m in months[:3]:
            inflow[m] += extra_units / 3 * avg * .10
        actions.append(f"حملة مركّزة لبيع {extra_units} وحدات إضافية خلال ٣ أشهر (عربون ١٠٪)")
        early = 0
        for x in c.execute("""SELECT i.amount-i.paid_amount due, substr(i.due_date,1,7) m FROM installments i
                              JOIN bookings b ON b.id=i.booking_id JOIN units u ON u.id=b.unit_id
                              WHERE u.project_id=? AND b.status='confirmed' AND i.due_date>? AND substr(i.due_date,1,7)>?""",
                           (project_id, today.isoformat(), big)):
            if x["m"] in months and early < 120000:
                take = min(x["due"] * .3, 120000 - early)
                early += take
                inflow[x["m"]] -= take
                inflow[big] += take * .98
        if early:
            actions.append(f"عرض خصم ٢٪ لتقديم أقساط لاحقة (تحصيل مبكر {early:,.0f} ر.ع)")
    opening = float((c.execute("SELECT v FROM settings WHERE k=?", (f"escrow:{project_id}",)).fetchone() or [0])[0])
    bal, series, worst = opening, [], None
    for m in months:
        bal += inflow[m] - outflow[m]
        row = {"month": m, "inflow": round(inflow[m]), "outflow": round(outflow[m]), "net": round(inflow[m] - outflow[m]),
               "balance": round(bal), "drivers": drivers[m]}
        series.append(row)
        if worst is None or bal < worst["balance"]:
            worst = row
    return {"project_id": project_id, "opening": opening, "series": series, "worst": worst,
            "gap": max(0, -worst["balance"]), "actions": actions, "sales_pace": round(pace, 1)}


def cash_radar(c, apply_plan: bool = False, project_id: int | None = None):
    names = {p["id"]: p["name"] for p in c.execute("SELECT id,name FROM projects")}
    ids = [project_id] if project_id else list(names)
    per = []
    for pid in ids:
        # الخطة تُطبَّق فقط على المشروع الذي فيه فجوة
        base = project_cash(c, pid)
        r = project_cash(c, pid, apply_plan and base["gap"] > 0)
        r["name"] = names[pid]
        r["actions"] = [f"«{names[pid]}»: {a}" for a in r["actions"]]
        r["gap_before"] = base["gap"]
        per.append(r)
    months = [s["month"] for s in per[0]["series"]]
    total = []
    for k, m in enumerate(months):
        total.append({"month": m, "inflow": sum(p["series"][k]["inflow"] for p in per),
                      "outflow": sum(p["series"][k]["outflow"] for p in per),
                      "balance": sum(p["series"][k]["balance"] for p in per),
                      "net": sum(p["series"][k]["net"] for p in per),
                      "drivers": sum((p["series"][k]["drivers"] for p in per), [])})
    worst_p = max(per, key=lambda p: p["gap"])
    return {"series": total, "projects": per, "gap": sum(p["gap"] for p in per),
            "worst": {**worst_p["worst"], "project": worst_p["name"]}, "worst_project": worst_p["name"],
            "applied_plan": apply_plan, "actions": [a for p in per for a in p["actions"]]}


# ---------------------------------------------------------------- التحقق من المستخلص
def verify_ipc(c, ipc_id: int):
    ipc = c.execute("SELECT * FROM ipcs WHERE id=?", (ipc_id,)).fetchone()
    items = c.execute("SELECT * FROM ipc_items WHERE ipc_id=?", (ipc_id,)).fetchall()
    if not items:
        return {"verified_pct": ipc["approved_pct"] or ipc["claimed_pct"], "items": [], "gap": 0}
    verified = sum(i["weight"] * i["verified_pct"] for i in items)
    evidence = sum(i["evidence"] for i in items)
    claimed_amt = ipc["stage_value"] * ipc["claimed_pct"] / 100
    verified_amt = ipc["stage_value"] * verified / 100
    return {"claimed_pct": ipc["claimed_pct"], "verified_pct": round(verified, 1), "evidence_photos": evidence,
            "claimed_amount": round(claimed_amt), "verified_amount": round(verified_amt),
            "gap_amount": round(claimed_amt - verified_amt),
            "items": [dict(i) for i in items],
            "note": "التحقق مبني على تقييم بنود المرحلة المرفقة بأدلة مصورة. في الإنتاج يُغذّى بنموذج رؤية حاسوبية "
                    "يقارن صور الموقع/الدرون بنموذج BIM."}


# ---------------------------------------------------------------- تقييم العملاء المحتملين
def lead_score(l) -> int:
    today = TODAY()
    recency = (today - d(l["last_contact"])).days
    s = 20 + l["stage"] * 15 + min(l["interactions"], 10) * 3
    s -= min(recency, 30) * 1.2
    s += {"وسيط": 8, "معرض عقاري": 6, "واتساب": 4}.get(l["channel"], 0)
    s += 5 if (l["budget"] or 0) >= 80000 else 0
    return int(max(5, min(97, s)))


def rescore_leads(c):
    for l in c.execute("SELECT * FROM leads").fetchall():
        c.execute("UPDATE leads SET score=? WHERE id=?", (lead_score(l), l["id"]))


def match_units(c, lead_id: int, limit: int = 3):
    l = c.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    units = c.execute("SELECT * FROM units WHERE project_id=? AND status='a'", (l["project_id"],)).fetchall()
    words = l["interest"]

    def fit(u):
        s = 0
        if u["price"] <= (l["budget"] or 1e9):
            s += 3
        else:
            s -= (u["price"] - l["budget"]) / 10000
        for key in ("بحري", "حديقة", "زاوية"):
            if key in words and key in u["view"]:
                s += 3
        if "مرتفع" in words:
            s += u["floor"] / 5
        if "٣ غرف" in words and "٣" in u["type"]:
            s += 2
        if "٥ غرف" in words and "٥" in u["type"]:
            s += 2
        return s
    best = sorted(units, key=fit, reverse=True)[:limit]
    return [dict(u) for u in best]


# ---------------------------------------------------------------- صندوق القرارات
def decisions(c):
    done = {r["key"]: r["action"] for r in c.execute("SELECT * FROM decisions_log")}
    out = []
    for p in c.execute("SELECT * FROM projects WHERE COALESCE(completed,0)=0"):
        for s in pricing(c, p["id"]):
            if s["suggested_change"] > 0 and s["available"] >= 2:
                avail = c.execute("SELECT SUM(price) FROM units WHERE project_id=? AND status='a' AND view=? AND type=?",
                                  (p["id"], s["view"], s["type"])).fetchone()[0] or 0
                key = f"price:{p['id']}:{s['view']}:{s['type']}"
                out.append({"key": key, "kind": "price", "priority": "عالية", "source": "التسعير الديناميكي",
                            "title": f"رفع سعر {s['type']} · {s['view']} في {p['name']} بنسبة {s['suggested_change']*100:.0f}٪ (المتاح: {s['available']})",
                            "impact": round(avail * s["suggested_change"]), "impact_label": "إيراد إضافي",
                            "why": s["reason"], "project_id": p["id"],
                            "payload": {"view": s["view"], "type": s["type"], "change": s["suggested_change"]},
                            "done": done.get(key)})
    risks = [r for r in default_risk(c) if r["score"] >= 70]
    if risks:
        key = "resched:" + ",".join(str(r["booking_id"]) for r in risks[:5])
        out.append({"key": key, "kind": "reschedule", "priority": "عالية", "source": "نموذج التعثر",
                    "title": f"عرض إعادة جدولة قبل التعثر (عدد العملاء: {min(5, len(risks))})",
                    "impact": round(sum(r["next_amount"] + r["overdue"] for r in risks[:5])), "impact_label": "مبالغ محمية",
                    "why": "؛ ".join(f"{r['customer']}: {r['reasons'][0]}" for r in risks[:3]),
                    "payload": {"booking_ids": [r["booking_id"] for r in risks[:5]]}, "done": done.get(key)})
    for i in c.execute("SELECT i.*, p.name pname FROM ipcs i JOIN projects p ON p.id=i.project_id WHERE status='pending'"):
        v = verify_ipc(c, i["id"])
        if v["items"] and v["claimed_pct"] - v["verified_pct"] >= 3:
            key = f"ipc:{i['id']}"
            out.append({"key": key, "kind": "ipc", "priority": "حرجة", "source": "التحقق من الإنجاز",
                        "title": f"المستخلص {i['no']} في {i['pname']}: اعتماد {v['verified_pct']:.0f}٪ بدل {v['claimed_pct']:.0f}٪",
                        "impact": v["gap_amount"], "impact_label": "صرف زائد يُتجنّب",
                        "why": f"{v['evidence_photos']} صورة/دليل لا تدعم النسبة المعلنة في بنود المرحلة.",
                        "payload": {"ipc_id": i["id"]}, "done": done.get(key)})
    cr = cash_radar(c)
    if cr["gap"] > 0:
        key = f"cash:{cr['worst']['month']}"
        out.append({"key": key, "kind": "cash", "priority": "حرجة", "source": "رادار السيولة",
                    "title": f"فجوة سيولة في حساب ضمان «{cr['worst_project']}» تبلغ ذروتها في {ar_month(cr['worst']['month'])}",
                    "impact": cr["gap"], "impact_label": "عجز متوقع",
                    "why": "؛ ".join(cr["worst"]["drivers"]) or "تجاوز المصروفات للتحصيل المتوقع",
                    "payload": {}, "done": done.get(key)})
    order = {"حرجة": 0, "عالية": 1}
    return sorted(out, key=lambda x: (x["done"] is not None, order.get(x["priority"], 2), -x["impact"]))


# ---------------------------------------------------------------- المساعد
def assistant(c, q: str):
    q = q.strip()
    if any(k in q for k in ("خطر", "أخطر", "مشكلة", "انتباه")):
        rows = []
        for p in c.execute("SELECT * FROM projects WHERE COALESCE(completed,0)=0 AND planned_monthly_sales>0"):
            since = (TODAY() - dt.timedelta(days=90)).isoformat()
            n = c.execute("""SELECT COUNT(*) FROM bookings b JOIN units u ON u.id=b.unit_id
                             WHERE u.project_id=? AND b.created>=? AND b.status!='cancelled'""", (p["id"], since)).fetchone()[0]
            pace = n / 3
            gap = (p["planned_monthly_sales"] - pace) / p["planned_monthly_sales"]
            r = len([x for x in default_risk(c) if x["project"] == p["name"]])
            rows.append((gap, p["name"], pace, p["planned_monthly_sales"], r))
        rows.sort(reverse=True)
        g, name, pace, plan, r = rows[0]
        return {"answer": f"«{name}» هو الأكثر خطرًا: سرعة البيع {pace:.1f} وحدة شهريًا مقابل {plan:.0f} في الخطة "
                          f"({g*100:.0f}٪ أبطأ)، ولديه {r} عملاء بمؤشرات تعثر.",
                "source": "المبيعات آخر ٩٠ يومًا + نموذج التعثر"}
    if any(k in q for k in ("فجوة", "سيولة", "نقد")):
        cr = cash_radar(c)
        cp = cash_radar(c, True)
        if cr["gap"] <= 0:
            return {"answer": "لا توجد فجوة سيولة متوقعة خلال ١٢ شهرًا.", "source": "رادار السيولة"}
        return {"answer": f"حساب ضمان «{cr['worst_project']}» يصل إلى عجز {cr['gap']:,.0f} ر.ع في {ar_month(cr['worst']['month'])} "
                          f"({'؛ '.join(cr['worst']['drivers']) or 'المصروفات تتجاوز التحصيل'}). "
                          f"الخطة المقترحة: {'؛ '.join(cp['actions'])} — والعجز بعدها {cp['gap']:,.0f} ر.ع.",
                "source": "جدول الأقساط مرجّحًا باحتمال التعثر + جدول المستخلصات"}
    if any(k in q for k in ("تسويق", "أسوّق", "سعر", "تسعير")):
        best = []
        for p in c.execute("SELECT * FROM projects"):
            for s in pricing(c, p["id"]):
                if s["available"]:
                    best.append((s["demand_ratio"], p["name"], s))
        best.sort(key=lambda x: -x[0])
        hi = best[0]
        lo = best[-1]
        return {"answer": f"الأعلى طلبًا: {hi[2]['type']} · {hi[2]['view']} في «{hi[1]}» ({hi[2]['available']} متاحة) — "
                          f"مرشّحة لرفع السعر. الأبطأ: {lo[2]['type']} · {lo[2]['view']} في «{lo[1]}» — تحتاج حملة أو حافز.",
                "source": "محرك التسعير الديناميكي"}
    if any(k in q for k in ("تعثر", "متأخر", "يتأخر", "سداد")):
        r = default_risk(c)[:3]
        if not r:
            return {"answer": "لا يوجد عملاء بمؤشرات تعثر حاليًا.", "source": "نموذج التعثر"}
        return {"answer": "الأعلى خطرًا: " + "؛ ".join(f"{x['customer']} ({x['unit']}) {x['score']}٪" for x in r),
                "source": "نموذج التعثر"}
    if any(k in q for k in ("مقاول", "مستخلص", "إنجاز")):
        rows = c.execute("SELECT id,no FROM ipcs WHERE status='pending'").fetchall()
        parts = []
        for r in rows:
            v = verify_ipc(c, r["id"])
            if v["items"]:
                parts.append(f"المستخلص {r['no']}: معلن {v['claimed_pct']:.0f}٪ ومُتحقق {v['verified_pct']:.0f}٪ (فرق {v['gap_amount']:,.0f} ر.ع)")
        return {"answer": "؛ ".join(parts) or "لا مستخلصات معلقة.", "source": "التحقق من الإنجاز"}
    if any(k in q for k in ("مبيعات", "حال", "ملخص", "وضع")):
        k = kpis(c)
        return {"answer": f"مبيعات آخر ٣٠ يومًا {k['sales_30d_count']} وحدة بقيمة {k['sales_30d_value']:,.0f} ر.ع، "
                          f"التحصيل {k['collection_rate']}٪، المتاح {k['available']} من {k['total_units']} وحدة.",
                "source": "لوحة المؤشرات"}
    return {"answer": "أستطيع الإجابة عن: المخاطر، السيولة، التسعير والتسويق، التعثر، المستخلصات، وملخص المبيعات.",
            "source": "المساعد (نسخة MVP بقواعد على البيانات الحية)"}


def kpis(c, project_id=None):
    w, a = ("AND u.project_id=?", (project_id,)) if project_id else ("", ())
    today = TODAY()
    since = (today - dt.timedelta(days=30)).isoformat()
    s = c.execute(f"""SELECT COUNT(*) n, COALESCE(SUM(b.price),0) v FROM bookings b JOIN units u ON u.id=b.unit_id
                      WHERE b.created>=? AND b.status!='cancelled' {w}""", (since, *a)).fetchone()
    col = c.execute(f"""SELECT COALESCE(SUM(i.amount),0) due, COALESCE(SUM(CASE WHEN i.paid_amount<i.amount THEN i.paid_amount ELSE i.amount END),0) paid
                        FROM installments i JOIN bookings b ON b.id=i.booking_id JOIN units u ON u.id=b.unit_id
                        WHERE b.status='confirmed' AND i.due_date<=? AND i.due_date>=? {w}""",
                    (today.isoformat(), (today - dt.timedelta(days=90)).isoformat(), *a)).fetchone()
    un = c.execute(f"SELECT COUNT(*) t, SUM(CASE WHEN status='a' THEN 1 ELSE 0 END) av FROM units u WHERE 1=1 {w}", a).fetchone()
    return {"sales_30d_count": s["n"], "sales_30d_value": s["v"],
            "collection_rate": round(100 * col["paid"] / col["due"]) if col["due"] else 100,
            "available": un["av"], "total_units": un["t"]}


# ---------------------------------------------------------------- تقدير قيمة إعادة البيع
def resale_estimate(c, booking_id: int) -> dict:
    """تقدير شفاف: سعر القائمة الحالي لوحدات مماثلة متاحة، مع علاوة الإنجاز."""
    b = c.execute("""SELECT b.price paid_price, u.project_id, u.type, u.view, u.area, p.build_pct
                     FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id WHERE b.id=?""",
                  (booking_id,)).fetchone()
    if not b:
        return {}
    r = c.execute("""SELECT AVG(price/area) FROM units WHERE project_id=? AND type=? AND view=? AND status='a'""",
                  (b["project_id"], b["type"], b["view"])).fetchone()[0]
    basis = "متوسط سعر المتر للوحدات المماثلة المتاحة حاليًا"
    if not r:
        r = c.execute("SELECT AVG(price/area) FROM units WHERE project_id=? AND type=?", (b["project_id"], b["type"])).fetchone()[0]
        basis = "متوسط سعر المتر لنفس النوع في المشروع"
    est = round(r * b["area"] * (1 + .03 * b["build_pct"] / 100), -2)
    return {"low": round(est * .96, -2), "high": round(est * 1.04, -2), "mid": est,
            "gain_pct": round(100 * (est - b["paid_price"]) / b["paid_price"], 1), "basis": basis}
