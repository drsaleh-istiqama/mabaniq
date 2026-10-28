"""بيانات تجريبية حتمية (seed=42) لثلاثة مشاريع عُمانية افتراضية."""
import datetime as dt
import random

from .db import TENANT, connect, init, wipe_for_reseed
from .pii import enc as _enc
from .tenant_profiles import apply_brand, ensure_assets, ensure_pilot_accounts, lease_units, profile, profile_units

FIRST = ["خالد", "مريم", "سالم", "نورة", "يوسف", "سعيد", "فاطمة", "أحمد", "هلال", "ناصر", "عائشة", "محمد",
         "زينب", "علي", "منى", "حمد", "سلطان", "شيخة", "بدر", "ريم", "إبراهيم", "خلفان", "موزة", "طلال"]
LAST = ["البلوشي", "الحارثي", "الكندي", "الرواحي", "العامري", "السيابي", "الهنائي", "الشكيلي", "المعمري",
        "الغافري", "البوسعيدي", "الريامي", "المقبالي", "الجابري", "الهاشمي", "الوهيبي"]
PLANS = ["milestone", "milestone", "6040", "murabaha"]


def add_months(d: dt.date, m: int) -> dt.date:
    y, mo = divmod(d.month - 1 + m, 12)
    return dt.date(d.year + y, mo + 1, min(d.day, 28))


def schedule(plan: str, price: float, start: dt.date, handover: dt.date):
    """يولّد جدول أقساط حسب خطة الدفع — يُستخدم في الحجز الفعلي أيضًا."""
    if plan == "milestone":
        rows = [("عربون الحجز", start, 0.10)]
        labels = ["الأساسات", "الهيكل الخرساني", "البلوك والتمديدات", "التشطيبات", "الواجهات", "التسليم"]
        span = max(6, (handover.year - start.year) * 12 + handover.month - start.month)
        for i, lb in enumerate(labels, 1):
            rows.append((f"مرحلة {lb}", add_months(start, round(span * i / 6)), 0.15))
    elif plan == "6040":
        rows = [("عربون الحجز", start, 0.10)]
        for i in range(1, 6):
            rows.append((f"دفعة أثناء البناء {i}", add_months(start, i * 3), 0.10))
        rows.append(("عند التسليم", handover, 0.40))
    else:  # murabaha
        rows = [("عربون الحجز", start, 0.10), ("دفعة أولى", add_months(start, 1), 0.10),
                ("تمويل البنك عند التسليم", handover, 0.80)]
    return [(lb, d, round(price * p, 0)) for lb, d, p in rows]


ALL_TABLES = ["campaign_sends", "creatives", "campaigns", "plans", "quotes", "doc_sends", "share_links", "doc_issues", "charity_dues", "resale_settlements", "oa_votes", "oa_motions", "oa_charges", "oa_budget", "rent_dues", "leases", "tenants_l", "work_orders", "fm_assets",
              "titles", "handovers", "snags", "distributions", "bank_lines", "pay_intents", "refunds", "invoices", "wa_messages",
              "viewings", "resale_offers", "watchlist", "commissions", "brokers", "discount_requests", "sale_contracts", "budgets",
              "ncrs", "site_reports", "change_orders", "schedule_tasks", "contracts_c", "permits", "feasibility", "lands",
              "documents", "notifications", "privacy_requests",
              "payments", "resale", "service_requests", "audit", "decisions_log", "cost_schedule", "ipc_items", "ipcs",
              "contractors", "installments", "bookings", "leads", "customers", "units", "projects", "settings"]

TENANT_PROJECTS = {
    "jadwa": [("RAY", "أبراج الريحان", "المعبيلة", "tower", 54, 6, 10), ("SEB", "واجهة السيب", "السيب", "tower", 22, 6, 22),
              ("KHD", "ضاحية الخوض", "الخوض", "villa", 88, 4, 4)],
    "nahda": [("RAY", "أبراج النخيل", "بوشر", "tower", 40, 5, 14), ("SEB", "مرسى العذيبة", "العذيبة", "tower", 30, 5, 18),
              ("KHD", "حدائق الأنصب", "الأنصب", "villa", 70, 3, 8)],
}


def backfill_payments(c, today: dt.date) -> int:
    """0.4.1 — M3: كل ريال مسجَّل مسدَّدًا في الأقساط يجب أن يقابله صف في دفتر المدفوعات (payments)،
    وإلا اختلف كشف الضمان عن المطابقة البنكية وتصدير ERPNext. تُكمل البذور التاريخية الفارق كتحويل بنكي مطابَق."""
    n = 0
    for i in c.execute("""SELECT i.id, i.paid_amount, i.paid_date, COALESCE((SELECT SUM(amount) FROM payments p WHERE p.installment_id=i.id),0) booked
                          FROM installments i WHERE i.paid_amount>0""").fetchall():
        gap = round(i["paid_amount"] - i["booked"], 3)
        if gap > 0.5:
            c.execute("INSERT OR IGNORE INTO payments(installment_id,amount,at,method,receipt,gateway_ref,reconciled) VALUES(?,?,?,?,?,?,1)",
                      (i["id"], gap, (i["paid_date"] or today.isoformat()) + "T10:00:00", "تحويل بنكي", f"MBQ-B-{i['id']:06d}", f"fill_{i['id']}"))
            n += 1
    return n


def seed(force: bool = False, tenant: str | None = None) -> None:
    tenant = tenant or TENANT.get()
    tok = TENANT.set(tenant)
    try:
        _seed(force, tenant)
    except Exception:
        # 0.5.0: فشل البذر في منتصف معاملة كان يترك قفل كتابة مفتوحًا على القاعدة كلها
        c = connect()
        try:
            c.rollback()
        finally:
            c.close()
        raise
    finally:
        TENANT.reset(tok)


SEED_LOCK = 7340129  # PostgreSQL advisory lock: several uvicorn workers start together — one seeds, the others find the data


def _unlock(c, pg: bool) -> None:
    if pg:
        try:
            c.execute("SELECT pg_advisory_unlock(%d)" % SEED_LOCK)
            c.commit()
        except Exception:  # noqa: BLE001 — a closed connection releases its session locks anyway
            pass


def _seed(force: bool, tenant: str) -> None:
    c = connect()
    pg = getattr(c, "dialect", "") == "postgres"
    try:
        if pg:
            c.execute("SELECT pg_advisory_lock(%d)" % SEED_LOCK)  # 0.13.0: Railway start-up raced two workers into a duplicate-key crash
        _seed_body(c, force, tenant)
        _unlock(c, pg)
        c.close()
    except Exception:
        # لا يُترك اتصال البذر مفتوحًا بمعاملة ناقصة: كان ذلك يقفل القاعدة كلها أمام كل الطلبات التالية
        try:
            c.rollback()
        finally:
            _unlock(c, pg)
            c.close()
        raise

def _seed_body(c, force: bool, tenant: str) -> None:
    init(c)
    if c.execute("SELECT COUNT(*) FROM projects").fetchone()[0] and not force:
        if c.has_table("users") and c.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
            from .auth import apply_demo_password
            apply_demo_password(c)  # Unit 4: a persistent database keeps its data, but the declared demo password always applies
            ensure_assets(c, tenant)  # 0.13.0: bundled sample images are re-materialised after a redeploy (ephemeral storage)
            ensure_pilot_accounts(c, tenant)  # 0.14.0
            return
        # 0.13.0: projects without any account = a seed interrupted before `ensure_users` (nobody could have logged in yet) → rebuild
        force = True
    wipe_for_reseed(c, ALL_TABLES)
    # حسابات العملاء/الوسطاء المنشأة أثناء الاستخدام تشير إلى معرّفات عملاء ستُعاد؛ تُحذف مع إعادة البذر (حسابات العرض تُعاد ربطها في ensure_users)
    if c.has_table("users"):
        c.execute(c.wipe_sql("auth_failures"))  # قفل المحاولات من تشغيل سابق لا يُورَّث بعد إعادة البذر
        c.execute("""DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username NOT IN ('admin','sales','finance','engineer','investor1')
                     AND username NOT LIKE 'client%' AND username NOT LIKE 'broker%')""")
        c.execute("DELETE FROM users WHERE username NOT IN ('admin','sales','finance','engineer','investor1') AND username NOT LIKE 'client%' AND username NOT LIKE 'broker%'")
        c.commit()
    if (pf0 := profile(tenant)) and pf0.get("real_only"):  # 0.18.1: a real-data tenant takes nothing from the demo generators
        from .tenant_profiles import seed_real
        seed_real(c, pf0, tenant)
        return
    rnd = random.Random(42 if tenant == "jadwa" else 7)
    today = dt.date.today()

    # 0.13.0: a profile (backend/tenant_profiles.py) maps the seed's internal slots RAY/SEB/KHD to a real developer's projects and
    # drives the unit mix; `pid` is keyed by both the slot and the real code so every later stage keeps working.
    pf = profile(tenant)
    if pf:
        projects = [(code, name, loc, kind, b, pl, add_months(today, g)) for _s, code, name, loc, kind, b, pl, g, _e in pf["projects"]]
        slot_of = {code: slot for slot, code, *_r in pf["projects"]}
        escrow = {slot: e for slot, _c, _n, _l, _k, _b, _p, _g, e in pf["projects"]}
    else:
        projects = [(a, b, cc, d, e, f, add_months(today, g)) for a, b, cc, d, e, f, g in TENANT_PROJECTS.get(tenant, TENANT_PROJECTS["jadwa"])]
        slot_of = {"RAY": "RAY", "SEB": "SEB", "KHD": "KHD"}
        escrow = {"RAY": "260000", "SEB": "180000", "KHD": "90000"}
    pid = {}
    for code, name, loc, kind, b, pl, ho in projects:
        cur = c.execute("INSERT INTO projects(code,name,location,kind,build_pct,planned_monthly_sales,handover) "
                        "VALUES(?,?,?,?,?,?,?)", (code, name, loc, kind, b, pl, ho.isoformat()))
        pid[code] = pid[slot_of[code]] = (cur.lastrowid, ho)
        c.execute("INSERT INTO settings VALUES(?,?)", (f"escrow:{cur.lastrowid}", escrow.get(slot_of[code], "120000")))

    units, use_of = [], {}
    if pf:
        for u in profile_units(pf):
            units.append(u[:10])
            use_of[u[1]] = u[10]
    else:
        # أبراج الريحان: برج A (14 طابقًا) وبرج B (10 طوابق) × 6 وحدات
        spec6 = [("غرفتان وصالة", 118, "بحري", 640), ("غرفتان وصالة", 118, "بحري", 640),
                 ("3 غرف وصالة", 156, "حديقة", 560), ("3 غرف وصالة", 156, "حديقة", 560),
                 ("غرفة وصالة", 78, "شارع", 520), ("غرفة وصالة", 78, "شارع", 520)]
        sold_p = {"بحري": .86, "حديقة": .62, "شارع": .45}
        for bld, floors in (("A", 14), ("B", 10)):
            for f in range(1, floors + 1):
                for p, (tp, ar, vw, ppm) in enumerate(spec6, 1):
                    units.append(("RAY", f"RAY-{bld}-{f}{p:02d}", bld, f, p, tp, ar, vw, ppm * ar * (1 + f * .012), sold_p[vw]))
        # واجهة السيب: 8 طوابق × 12
        for f in range(1, 9):
            for p in range(1, 13):
                vw = "بحري" if p <= 4 else "حديقة" if p <= 8 else "شارع"
                tp, ar = [("غرفتان وصالة", 120), ("3 غرف وصالة", 160), ("غرفة وصالة", 80)][(p - 1) % 3]
                ppm = {"بحري": 660, "حديقة": 570, "شارع": 530}[vw]
                units.append(("SEB", f"SEB-S-{f}{p:02d}", "S", f, p, tp, ar, vw, ppm * ar * (1 + f * .01),
                              {"بحري": .6, "حديقة": .38, "شارع": .42}[vw]))
        # ضاحية الخوض: 120 فيلا
        for i in range(1, 121):
            corner = i % 5 in (1, 0)
            park = 41 <= i <= 80
            vw = "زاوية" if corner else "قرب الحديقة" if park else "داخلية"
            units.append(("KHD", f"KHD-V-{i:03d}", "V", 0, i, "فيلا 5 غرف" if i % 3 == 0 else "فيلا 4 غرف",
                          380 if i % 3 == 0 else 340, vw, (96000 if i % 3 == 0 else 84000) * (1.06 if corner else 1.03 if park else 1),
                          {"زاوية": .8, "قرب الحديقة": .7, "داخلية": .52}[vw]))

    keep = lease_units(pf)  # 0.15.0: units the profile keeps for leasing are never sold
    for proj, code, bld, f, p, tp, ar, vw, price, ps in units:
        x = rnd.random()
        st = "a" if code in keep else "s" if x < ps else "r" if x < ps + .04 else "a"
        cur = c.execute("INSERT INTO units(project_id,code,building,floor,pos,type,area,view,price,status,use) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (pid[proj][0], code, bld, f, p, tp, ar, vw, round(price / 100) * 100, st, use_of.get(code, "residential")))
        if st == "a":
            continue
        uid = cur.lastrowid
        name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
        omani = rnd.random() < .78
        cust = c.execute("INSERT INTO customers(name,phone,created,id_type,id_number,nationality,id_expiry,kyc_status,kyc_risk,source_of_funds,consent_at,consent_version,consent_source) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,?,'1.0','إقرار ورقي (بيانات تجريبية)')",
                         (name, f"+968 9{rnd.randint(1000000, 9999999)}", today.isoformat(),
                          "بطاقة مدنية" if omani else "جواز سفر",
                          _enc(str(rnd.randint(10000000, 99999999)) if omani else f"P{rnd.randint(1000000, 9999999)}"),
                          "عُماني" if omani else rnd.choice(["إماراتي", "كويتي", "هندي", "بريطاني"]),
                          add_months(today, rnd.randint(-2, 60)).isoformat(),
                          "verified" if st == "s" else "pending", "منخفض" if omani else "متوسط",
                          rnd.choice(["راتب", "راتب", "تجارة", "تمويل بنكي"]), today.isoformat())).lastrowid
        plan = rnd.choice(PLANS)
        sale_price = round(price / 100) * 100
        if st == "r":
            created = today - dt.timedelta(days=rnd.randint(0, 2))
            bid = c.execute("INSERT INTO bookings(unit_id,customer_id,plan,price,status,created,expires) VALUES(?,?,?,?,?,?,?)",
                            (uid, cust, plan, sale_price, "pending", created.isoformat(),
                             (created + dt.timedelta(days=3)).isoformat())).lastrowid
            for s, (lb, d, amt) in enumerate(schedule(plan, sale_price, created, pid[proj][1]), 1):
                c.execute("INSERT INTO installments(booking_id,seq,label,due_date,amount) VALUES(?,?,?,?,?)",
                          (bid, s, lb, d.isoformat(), amt))
            continue
        # مباعة: تاريخ البيع — السيب أبطأ مؤخرًا
        recent_w = .08 if proj == "SEB" else .22
        days = rnd.randint(1, 90) if rnd.random() < recent_w else rnd.randint(91, 540)
        created = today - dt.timedelta(days=days)
        bid = c.execute("INSERT INTO bookings(unit_id,customer_id,plan,price,status,created,expires) VALUES(?,?,?,?,?,?,?)",
                        (uid, cust, plan, sale_price, "confirmed", created.isoformat(), None)).lastrowid
        prof = rnd.random()
        behaviour = "late" if prof < .10 else "partial" if prof < .15 else "good"
        for s, (lb, d, amt) in enumerate(schedule(plan, sale_price, created, pid[proj][1]), 1):
            paid_amt, paid_d = 0, None
            if d <= today:
                if s == 1 or behaviour == "good":
                    paid_amt, paid_d = amt, d + dt.timedelta(days=rnd.randint(-3, 3))
                elif behaviour == "late":
                    lag = rnd.randint(9, 45)
                    if d + dt.timedelta(days=lag) <= today:
                        paid_amt, paid_d = amt, d + dt.timedelta(days=lag)
                else:
                    paid_amt, paid_d = round(amt * rnd.uniform(.5, .8)), d + dt.timedelta(days=rnd.randint(0, 6))
            c.execute("INSERT INTO installments(booking_id,seq,label,due_date,amount,paid_amount,paid_date) "
                      "VALUES(?,?,?,?,?,?,?)", (bid, s, lb, d.isoformat(), amt, paid_amt,
                                                 min(paid_d, today).isoformat() if paid_d else None))

    # العملاء المحتملون
    channels = ["واتساب", "إنستغرام", "الموقع", "وسيط", "معرض عقاري", "إعلان"]
    interests = pf["interests"] if pf else {"RAY": ["غرفتان بحري", "3 غرف حديقة", "طابق مرتفع", "استثمار للإيجار"],
                                                 "SEB": ["إطلالة بحرية", "غرفتان وصالة", "وحدات استثمارية"],
                                                 "KHD": ["فيلا زاوية", "فيلا قرب الحديقة", "فيلا 5 غرف"]}
    for i in range(36):
        proj = rnd.choice(pf["lead_mix"] if pf else ["RAY", "RAY", "SEB", "KHD"])
        created = today - dt.timedelta(days=rnd.randint(1, 60))
        last = today - dt.timedelta(days=rnd.randint(0, min(30, (today - created).days)))
        c.execute("INSERT INTO leads(name,phone,interest,project_id,channel,stage,interactions,budget,created,last_contact,score) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,0)",
                  (f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", f"+968 9{rnd.randint(1000000, 9999999)}",
                   rnd.choice(interests[proj]), pid[proj][0], rnd.choice(channels), rnd.choice([0, 0, 1, 1, 2, 2, 3]),
                   rnd.randint(1, 12), rnd.choice([50000, 65000, 80000, 95000, 120000]),
                   created.isoformat(), last.isoformat()))

    # المقاولون والمستخلصات
    k1 = c.execute("INSERT INTO contractors(name) VALUES('شركة البناء المتحد')").lastrowid
    k2 = c.execute("INSERT INTO contractors(name) VALUES('مؤسسة الإنشاءات الحديثة')").lastrowid
    k3 = c.execute("INSERT INTO contractors(name) VALUES('الخليج للمقاولات')").lastrowid

    def ipc(proj, k, no, stage, claimed, value, status, approved, items):
        iid = c.execute("INSERT INTO ipcs(project_id,contractor_id,no,stage,claimed_pct,stage_value,status,approved_pct,created) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", (pid[proj][0], k, no, stage, claimed, value, status, approved,
                                                      (today - dt.timedelta(days=rnd.randint(1, 6))).isoformat())).lastrowid
        for it, w, v, ev in items:
            c.execute("INSERT INTO ipc_items(ipc_id,item,weight,verified_pct,evidence) VALUES(?,?,?,?,?)", (iid, it, w, v, ev))

    ipc("RAY", k1, 6, "البلوك والتمديدات", 48, 900000, "approved", 48, [])
    ipc("RAY", k1, 7, "البلوك والتمديدات", 62, 900000, "pending", None,
        [("بلوك الطوابق 1–9", .45, 100, 21), ("تمديدات الطابق 10", .25, 35, 12),
         ("بلوك الطوابق 11–12", .20, 0, 9), ("تمديدات الطوابق 1–9", .10, 15, 6)])
    ipc("SEB", k2, 3, "الهيكل الخرساني", 25, 1480000, "pending", None,
        [("أعمدة وسقف الطابق 1", .5, 40, 14), ("أعمدة وسقف الطابق 2", .5, 6, 8)])
    ipc("KHD", k3, 11, "التشطيبات", 88, 2100000, "approved", 88, [])

    # جدول المصروفات المتوقعة: تكلفة متبقية = 72٪ من قيمة المشروع × (1 − نسبة الإنجاز)، موزعة حتى التسليم
    for code, name, loc, kind, b, pl, ho in projects:
        pj = pid[code][0]
        slot = slot_of[code]
        value = c.execute("SELECT SUM(price) FROM units WHERE project_id=?", (pj,)).fetchone()[0]
        remaining = value * .72 * (1 - b / 100)
        span = max(1, min(12, (ho.year - today.year) * 12 + ho.month - today.month))
        spike = 740000 if slot == "SEB" else 0
        fac = {"RAY": .55, "SEB": .80, "KHD": 0}.get(slot, .5) * (remaining - spike) / span
        c.execute("INSERT INTO settings VALUES(?,?)", (f"facility:{pj}", str(round(fac, -3))))
        c.execute("INSERT INTO settings VALUES(?,?)", (f"facility_months:{pj}", str(span)))
        for m in range(1, 13):
            month = add_months(today.replace(day=1), m).strftime("%Y-%m")
            amt = (remaining - spike * (slot == "SEB")) / span if m <= span else 25000
            label = "مستخلصات وتشغيل" if m <= span else "صيانة الضمان"
            if slot == "SEB" and m == 4:
                amt += spike
                label = "مستخلص الهيكل الخرساني"
            c.execute("INSERT INTO cost_schedule(project_id,month,amount,label) VALUES(?,?,?,?)",
                      (pj, month, round(amt, -3), label))
    c.commit()
    from .auth import ensure_users
    picks = []
    for p in c.execute("SELECT id FROM projects ORDER BY id").fetchall():
        r = c.execute("""SELECT cu.id, cu.name FROM customers cu JOIN bookings b ON b.customer_id=cu.id
                         JOIN units u ON u.id=b.unit_id WHERE u.project_id=? AND b.status='confirmed'
                         ORDER BY cu.id LIMIT 1""", (p["id"],)).fetchone()
        if r:
            picks.append((r["id"], r["name"]))
    from .seed_cycle import seed_cycle
    from .seed_ext import seed_ext
    brokers = seed_ext(c, rnd, today, pid, projects, tenant)
    if pf:
        apply_brand(c, pf)  # 0.13.0: letterhead + display name of the profiled developer
    seed_cycle(c, rnd, today, pid, tenant, schedule)
    backfill_payments(c, today)
    from .pii import encrypt_existing
    encrypt_existing(c)  # 0.5.0 — M5: أي حقل هوية بُذر نصًا (مثل هويات المستأجرين) يُشفَّر قبل الاستخدام
    # حساب عميل لمالك في المشروع المكتمل (ليظهر التسليم والملكية واتحاد الملاك في تطبيق العميل)
    r = c.execute("""SELECT cu.id, cu.name FROM customers cu JOIN bookings b ON b.customer_id=cu.id JOIN units u ON u.id=b.unit_id
                     JOIN projects p ON p.id=u.project_id JOIN handovers h ON h.booking_id=b.id
                     WHERE p.code='QRM' AND h.status='done' ORDER BY b.id LIMIT 1""").fetchone()
    if r:
        picks.append((r["id"], r["name"]))
    ensure_users(c, picks, brokers)
    # طلب صيانة نموذجي في مشروع الفلل المسلَّم قريبًا
    if picks:
        b = c.execute("SELECT id FROM bookings WHERE customer_id=? ORDER BY id LIMIT 1", (picks[-1][0],)).fetchone()
        c.execute("INSERT INTO service_requests(booking_id,category,description,status,created,updated) VALUES(?,?,?,?,?,?)",
                  (b["id"], "ملاحظة تشطيب", "تشقق بسيط في لياسة جدار المجلس الخارجي", "in_progress",
                   (today - dt.timedelta(days=4)).isoformat(), (today - dt.timedelta(days=1)).isoformat()))
    c.commit()
    from .engines import rescore_leads
    rescore_leads(c)
    c.commit()
    ensure_assets(c, tenant, pf)  # 0.13.0: bundled renders / plans / logo of a profiled developer
    ensure_pilot_accounts(c, tenant)  # 0.14.0: trial accounts of the profiled company (only with MABANIQ_PILOT_PASSWORD)


if __name__ == "__main__":
    seed(force=True)
    print("seeded")
