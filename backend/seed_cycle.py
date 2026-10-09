"""بيانات «الدورة العقارية الكاملة»: تضيف مشروعين يمثلان طرفي الدورة، وتملأ المراحل الوسطى في المشاريع القائمة.

المحفظة بعد هذا البذر (للمطوّر الأول):
  ١. أبراج العامرات   — مرحلة الأرض والتراخيص والإطلاق (إنجاز ٣٪، مبيعات الإطلاق الأولى)
  ٢. واجهة السيب      — الهيكل الخرساني، متأخر، فجوة سيولة
  ٣. أبراج الريحان    — البلوك والتمديدات، مبيعات ناضجة، سوق ثانوي نشط
  ٤. ضاحية الخوض      — التشطيبات النهائية، التسليم جارٍ، أول سندات الملكية
  ٥. القرم ريزيدنس    — مكتمل ومسلَّم: إدارة أملاك، اتحاد ملاك، ضمان، تأجير، توزيعات
"""
import datetime as dt
import hashlib
import json

from .engines_ext import feasibility as feas_engine
from .pii import enc as _enc

FIRST = ["خالد", "مريم", "سالم", "نورة", "يوسف", "سعيد", "فاطمة", "أحمد", "هلال", "ناصر", "عائشة", "محمد",
         "زينب", "علي", "منى", "حمد", "سلطان", "شيخة", "بدر", "ريم", "إبراهيم", "خلفان", "موزة", "طلال"]
LAST = ["البلوشي", "الحارثي", "الكندي", "الرواحي", "العامري", "السيابي", "الهنائي", "الشكيلي", "المعمري",
        "الغافري", "البوسعيدي", "الريامي", "المقبالي", "الجابري", "الهاشمي", "الوهيبي"]

NAMES = {
    "jadwa": {"AMR": ("أبراج العامرات", "العامرات"), "QRM": ("القرم ريزيدنس", "القرم")},
    "nahda": {"AMR": ("أبراج الموالح", "الموالح"), "QRM": ("بوشر هايتس", "بوشر")},
}


def _m(d: dt.date, months: int) -> dt.date:
    y, mo = divmod(d.month - 1 + months, 12)
    return dt.date(d.year + y, mo + 1, min(d.day, 28))


def _iso(d):
    return d.isoformat() if d else None


class _Inv:
    """ترقيم الفواتير متسلسلًا مثل محرك الفوترة."""

    def __init__(self, c, today):
        self.c, self.today = c, today
        self.seq = c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]

    def add(self, kind, ref_type, ref_id, customer, net, rate, issued, note, customer_id=None):
        self.seq += 1
        vat = round(net * rate, 3)
        self.c.execute("INSERT INTO invoices(number,kind,ref_type,ref_id,customer,net,vat_rate,vat,total,issued,note,customer_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (f"INV-{issued[:4]}-{self.seq:06d}", kind, ref_type, ref_id, customer, round(net, 3), rate, vat,
                        round(net + vat, 3), issued, note, customer_id))


def _customer(c, rnd, today, verified=True, **kw):
    omani = rnd.random() < .8
    return c.execute("""INSERT INTO customers(name,phone,created,id_type,id_number,nationality,id_expiry,kyc_status,kyc_risk,
                        source_of_funds,consent_at,pep,kyc_note,consent_version,consent_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'1.0','إقرار ورقي (بيانات تجريبية)')""",
                     (kw.get("name") or f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", f"+968 9{rnd.randint(1000000, 9999999)}",
                      today.isoformat(), "بطاقة مدنية" if omani else "جواز سفر",
                      _enc(str(rnd.randint(10000000, 99999999)) if omani else f"P{rnd.randint(1000000, 9999999)}"),
                      "عُماني" if omani else rnd.choice(["إماراتي", "كويتي", "هندي", "بريطاني"]),
                      _m(today, rnd.randint(6, 60)).isoformat(), kw.get("kyc", "verified" if verified else "pending"),
                      kw.get("risk", "منخفض" if omani else "متوسط"), rnd.choice(["راتب", "تجارة", "تمويل بنكي"]),
                      today.isoformat(), kw.get("pep", 0), kw.get("note"))).lastrowid


def _contract(c, bid, price, signed):
    num = f"SPA-{bid:05d}"
    body = f"عقد بيع وحدة سكنية رقم {num} — حجز {bid} — القيمة {price:,.0f} ر.ع"
    c.execute("""INSERT OR IGNORE INTO sale_contracts(booking_id,number,body,sha256,status,created,customer_signed_at,customer_sig,
                 developer_signed_at,developer_sig) VALUES(?,?,?,?,?,?,?,?,?,?)""",
              (bid, num, body, hashlib.sha256(body.encode()).hexdigest(), "signed", signed, signed, "migrated", signed, "migrated"))


def seed_cycle(c, rnd, today: dt.date, pid: dict, tenant: str, schedule) -> None:
    names = NAMES.get(tenant, NAMES["jadwa"])
    inv = _Inv(c, today)
    contractor = lambda nm: c.execute("INSERT INTO contractors(name,cr_number) VALUES(?,?)", (nm, str(rnd.randint(1_000_000, 1_999_999)))).lastrowid
    stages = [("التصاريح والتجهيز", .05), ("الحفر والأساسات", .12), ("الهيكل الخرساني", .30), ("البلوك والتمديدات", .18),
              ("التشطيبات الداخلية", .20), ("الواجهات والأعمال الخارجية", .10), ("الاختبار والتسليم", .05)]

    def tasks(pj, start, total, build):
        acc, prev = 0, None
        for nm, w in stages:
            s0, e0 = _m(start, round(total * acc)), _m(start, round(total * (acc + w)))
            lo, hi = acc * 100, (acc + w) * 100
            pct = 100 if build >= hi else 0 if build <= lo else round((build - lo) / (hi - lo) * 100)
            prev = c.execute("""INSERT INTO schedule_tasks(project_id,name,planned_start,planned_end,actual_start,actual_end,pct,depends_on,weight)
                                VALUES(?,?,?,?,?,?,?,?,?)""", (pj, nm, _iso(s0), _iso(e0), _iso(s0) if pct else None,
                                                                _iso(e0) if pct == 100 else None, pct, prev, w)).lastrowid
            acc += w

    # ======================================================================= ٥) مشروع مكتمل ومسلَّم
    qn, ql = names["QRM"]
    q_ho = _m(today, -5)
    q_start = _m(q_ho, -26)
    qrm = c.execute("""INSERT INTO projects(code,name,location,kind,build_pct,planned_monthly_sales,handover,completed)
                       VALUES('QRM',?,?,'tower',100,0,?,1)""", (qn, ql, q_ho.isoformat())).lastrowid
    q_units = []
    for f in range(1, 7):
        for p in range(1, 9):
            tp, ar = [("غرفتان وصالة", 125), ("٣ غرف وصالة", 168), ("غرفة وصالة", 84), ("بنتهاوس", 240)][(p - 1) % 4 if f == 6 else (p - 1) % 3]
            vw = "بحري" if p <= 3 else "مدينة"
            price = round(ar * (720 if vw == "بحري" else 610) * (1 + f * .015), -2)
            retained = 1 if (f == 2 and p in (7, 8)) or (f == 3 and p in (7, 8)) else 0
            uid = c.execute("""INSERT INTO units(project_id,code,building,floor,pos,type,area,view,price,status,retained)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (qrm, f"QRM-Q-{f}{p:02d}", "Q", f, p, tp, ar, vw, price,
                                                                 "a" if retained else "s", retained)).lastrowid
            q_units.append((uid, price, ar, retained))
    q_book = []
    for uid, price, ar, retained in q_units:
        if retained:
            continue
        cid = _customer(c, rnd, today)
        created = q_start + dt.timedelta(days=rnd.randint(0, 420))
        plan = rnd.choice(["milestone", "6040", "murabaha"])
        bid = c.execute("""INSERT INTO bookings(unit_id,customer_id,plan,price,status,created,list_price,handed_over)
                           VALUES(?,?,?,?,?,?,?,?)""", (uid, cid, plan, price, "confirmed", created.isoformat(), price, None)).lastrowid
        late_owner = rnd.random() < .08
        for s, (lb, d, amt) in enumerate(schedule(plan, price, created, q_ho), 1):
            last = s == len(schedule(plan, price, created, q_ho))
            paid = 0 if (late_owner and last) else amt
            pd = d + dt.timedelta(days=rnd.randint(-2, 6))
            iid = c.execute("INSERT INTO installments(booking_id,seq,label,due_date,amount,paid_amount,paid_date) VALUES(?,?,?,?,?,?,?)",
                            (bid, s, lb, d.isoformat(), amt, paid, _iso(min(pd, today)) if paid else None)).lastrowid
            if paid:
                c.execute("INSERT INTO payments(installment_id,amount,at,method,receipt,gateway_ref,reconciled) VALUES(?,?,?,?,?,?,1)",
                          (iid, paid, _iso(min(pd, today)) + "T10:00:00", "تحويل بنكي", f"MBQ-H-{iid:06d}", f"hist_{iid}"))
        _contract(c, bid, price, created.isoformat())
        q_book.append((bid, cid, price, ar, late_owner))
    # التسليم ونقل الملكية: الكل مسلَّم إلا من عليه متأخرات؛ السندات صادرة لمعظمهم
    for i, (bid, cid, price, ar, late) in enumerate(q_book):
        if late:
            c.execute("INSERT INTO handovers(booking_id,appointment,status) VALUES(?,?,?)", (bid, _iso(today + dt.timedelta(days=10)), "scheduled"))
            c.execute("INSERT INTO snags(booking_id,item,location,status,raised) VALUES(?,?,?,?,?)",
                      (bid, "تسليم معلّق حتى سداد دفعة التسليم", "—", "open", today.isoformat()))
            continue
        h = q_ho + dt.timedelta(days=rnd.randint(0, 40))
        c.execute("""INSERT INTO handovers(booking_id,appointment,status,certificate_no,handed_at,warranty_until,structural_until,meter_readings,keys)
                     VALUES(?,?,?,?,?,?,?,?,?)""", (bid, h.isoformat(), "done", f"HC-{bid:05d}-Q{i:02d}", h.isoformat(), _m(h, 12).isoformat(),
                                                   h.replace(year=h.year + 10).isoformat(), json.dumps({"electricity": rnd.randint(10, 90), "water": rnd.randint(1, 9)}), 3))
        c.execute("UPDATE bookings SET handed_over=? WHERE id=?", (h.isoformat(), bid))
        c.execute("INSERT INTO snags(booking_id,item,location,status,raised,closed) VALUES(?,?,?,?,?,?)",
                  (bid, rnd.choice(["خدش في باب المدخل", "ميلان بلاط الحمام", "سيليكون النافذة"]), "—", "fixed", h.isoformat(), h.isoformat()))
        st = "issued" if i % 7 else "submitted" if i % 2 else "ready"
        fee = round(price * .03)
        c.execute("INSERT INTO titles(booking_id,status,fee,applied,deed_no,issued) VALUES(?,?,?,?,?,?)",
                  (bid, st, fee if st != "ready" else None, _iso(h + dt.timedelta(days=14)) if st != "ready" else None,
                   f"MH-{rnd.randint(100000, 999999)}/{today.year}" if st == "issued" else None,
                   _iso(h + dt.timedelta(days=45)) if st == "issued" else None))
    # الأقسام التشغيلية للمشروع المكتمل
    k = contractor("الوطنية للمقاولات العامة")
    val = sum(u[1] for u in q_units) * .70
    c.execute("INSERT INTO contracts_c(project_id,contractor_id,value,retention_pct,delay_penalty_per_day,start,finish) VALUES(?,?,?,?,?,?,?)",
              (qrm, k, round(val, -3), .10, round(val * .0005, -1), q_start.isoformat(), q_ho.isoformat()))
    tasks(qrm, q_start, 26, 100)
    for cat, share in (("أعمال إنشائية", .62), ("كهروميكانيك", .18), ("تشطيبات", .12), ("استشارات وإشراف", .04), ("احتياطي طوارئ", .04)):
        c.execute("INSERT INTO budgets(project_id,category,amount) VALUES(?,?,?)", (qrm, cat, round(val * share, -3)))
    c.execute("""INSERT INTO ipcs(project_id,contractor_id,no,stage,claimed_pct,stage_value,status,approved_pct,created)
                 VALUES(?,?,?,?,?,?,?,?,?)""", (qrm, k, 14, "الحساب الختامي وتحرير الضمان المحتجز", 100, round(val * .10, -3), "approved", 100, _iso(_m(today, -1))))
    c.execute("INSERT INTO change_orders(project_id,no,title,reason,cost,days,status,requested,decided,decided_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (qrm, 1, "ترقية المصاعد إلى سرعة أعلى", "طلب المالك", 48_000, 14, "approved", _iso(_m(q_ho, -12)), _iso(_m(q_ho, -11)), "مدير المنصة"))
    c.execute("INSERT INTO ncrs(project_id,title,severity,status,raised,closed,location) VALUES(?,?,?,?,?,?,?)",
              (qrm, "تسرب في خزان السطح", "minor", "closed", _iso(_m(q_ho, -2)), _iso(_m(q_ho, -1)), "السطح"))
    for kind, auth, ref in (("رخصة بناء", "بلدية مسقط", "BLD-2024-1187"), ("تسجيل المشروع وفتح حساب الضمان", "وزارة الإسكان والتخطيط العمراني", "ESC-QRM-077"),
                            ("شهادة إتمام البناء", "بلدية مسقط", "CC-2026-0418"), ("فرز الوحدات وإصدار الملكيات", "وزارة الإسكان والتخطيط العمراني", "SUB-QRM-12"),
                            ("شهادة السلامة النهائية", "الدفاع المدني والإسعاف", "CD-FIN-5521")):
        c.execute("INSERT INTO permits(project_id,authority,kind,ref,status,applied,issued,expires) VALUES(?,?,?,?,?,?,?,?)",
                  (qrm, auth, kind, ref, "issued", _iso(_m(q_start, -2)), _iso(_m(q_ho, -1) if "إتمام" in kind or "فرز" in kind or "النهائية" in kind else q_start), None))
    for nm, cat, interval, last in (("المصاعد (٣)", "ميكانيك", 30, 12), ("مضخات الحريق", "سلامة", 90, 95), ("المولد الاحتياطي", "كهرباء", 60, 20),
                                    ("التكييف المركزي للممرات", "ميكانيك", 90, 40), ("بوابات المواقف", "أمن", 60, 70)):
        aid = c.execute("INSERT INTO fm_assets(project_id,name,category,last_service,interval_days,installed) VALUES(?,?,?,?,?,?)",
                        (qrm, nm, cat, _iso(today - dt.timedelta(days=last)), interval, q_ho.isoformat())).lastrowid
        c.execute("INSERT INTO work_orders(asset_id,kind,title,due,status,done,cost) VALUES(?,?,?,?,?,?,?)",
                  (aid, "preventive", f"صيانة دورية: {nm}", _iso(today - dt.timedelta(days=last)), "done", _iso(today - dt.timedelta(days=last)), rnd.choice([120, 240, 380])))
        c.execute("INSERT INTO work_orders(asset_id,kind,title,due,status,cost) VALUES(?,?,?,?,?,?)",
                  (aid, "preventive", f"صيانة دورية: {nm}", _iso(today - dt.timedelta(days=last) + dt.timedelta(days=interval)), "open", 0))
    # طلبات ضمان من الملاك
    for (bid, *_), (cat, desc, st) in zip(q_book[:5], (("تكييف", "المكيف في غرفة النوم لا يبرد", "done"), ("سباكة", "تسرب بسيط في سيفون الحمام", "in_progress"),
                                                         ("كهرباء", "مقبس المطبخ لا يعمل", "new"), ("ملاحظة تشطيب", "تشقق شعري في جدار الصالة", "new"),
                                                         ("أخرى", "باب الشرفة يحتاج ضبط", "done"))):
        c.execute("INSERT INTO service_requests(booking_id,category,description,status,created,updated,note) VALUES(?,?,?,?,?,?,?)",
                  (bid, cat, desc, st, _iso(today - dt.timedelta(days=rnd.randint(2, 30))), _iso(today - dt.timedelta(days=1)),
                   "أُنجز ضمن ضمان التشطيب" if st == "done" else "الفني يزورك خلال ٤٨ ساعة" if st == "in_progress" else None))
    # اتحاد الملاك: ميزانية، مطالبات، تصويتات مغلقة ومفتوحة
    year = today.year + 1
    for line, amt in (("الأمن والحراسة", 38_000), ("النظافة", 16_000), ("صيانة المصاعد", 14_000), ("صيانة المرافق المشتركة", 19_000),
                      ("التأمين على المبنى", 7_500), ("فاتورة كهرباء الأجزاء المشتركة", 11_000), ("احتياطي رأسمالي", 9_000)):
        c.execute("INSERT INTO oa_budget(project_id,year,line,amount) VALUES(?,?,?,?)", (qrm, year, line, amt))
    total_area = sum(b[3] for b in q_book)
    budget = 114_500
    for bid, cid, price, ar, late in q_book:
        amt = round(budget * ar / total_area, 3)
        paid = amt if rnd.random() < .72 else round(amt * .5, 3) if rnd.random() < .5 else 0
        c.execute("INSERT INTO oa_charges(project_id,booking_id,year,amount,paid,issued) VALUES(?,?,?,?,?,?)",
                  (qrm, bid, year, amt, paid, _iso(today - dt.timedelta(days=20))))
        cname = c.execute("SELECT name FROM customers WHERE id=?", (cid,)).fetchone()[0]
        inv.add("service_charge", "oa", bid, cname, amt, .05, _iso(today - dt.timedelta(days=20)), f"رسوم خدمات {year}", customer_id=cid)
    m1 = c.execute("INSERT INTO oa_motions(project_id,title,opened,closes,status) VALUES(?,?,?,?,?)",
                   (qrm, "اعتماد ميزانية الخدمات المشتركة للسنة القادمة", _iso(today - dt.timedelta(days=40)), _iso(today - dt.timedelta(days=25)), "closed")).lastrowid
    m2 = c.execute("INSERT INTO oa_motions(project_id,title,opened,closes,status) VALUES(?,?,?,?,?)",
                   (qrm, "التعاقد مع شركة إدارة مرافق خارجية", _iso(today - dt.timedelta(days=30)), _iso(today - dt.timedelta(days=16)), "closed")).lastrowid
    c.execute("INSERT INTO oa_motions(project_id,title,opened,closes,status) VALUES(?,?,?,?,?)",
              (qrm, "تحويل سطح المبنى إلى حديقة ومنطقة جلوس للملاك", today.isoformat(), _iso(today + dt.timedelta(days=12)), "open"))
    for bid, cid, price, ar, late in q_book:
        w = ar / total_area
        if rnd.random() < .78:
            c.execute("INSERT INTO oa_votes VALUES(?,?,?,?,?)", (m1, bid, "yes" if rnd.random() < .8 else "no", w, _iso(today - dt.timedelta(days=30))))
        if rnd.random() < .6:
            c.execute("INSERT INTO oa_votes VALUES(?,?,?,?,?)", (m2, bid, "yes" if rnd.random() < .4 else "no", w, _iso(today - dt.timedelta(days=20))))
    # التأجير: الوحدات المحتفظ بها في المشروع المكتمل
    for (uid, price, ar, retained), (tn, rent) in zip([u for u in q_units if u[3]], (("شركة مسقط للخدمات اللوجستية", 9_600), ("د. هالة السعدي", 7_200),
                                                                                       ("سيف المحروقي", 7_800), (None, 0))):
        if not tn:
            continue
        tid = c.execute("INSERT INTO tenants_l(name,phone,id_number) VALUES(?,?,?)", (tn, f"+968 9{rnd.randint(1000000, 9999999)}", str(rnd.randint(10000000, 99999999)))).lastrowid
        start = q_ho + dt.timedelta(days=rnd.randint(20, 60))
        lid = c.execute("""INSERT INTO leases(unit_id,tenant_id,start,end,annual_rent,frequency,deposit,status,municipality_ref)
                           VALUES(?,?,?,?,?,?,?,?,?)""", (uid, tid, start.isoformat(), (start + dt.timedelta(days=364)).isoformat(), rent, 12, rent / 12,
                                                         "active", f"MCT-L-{rnd.randint(100000, 999999)}")).lastrowid
        for q in range(12):
            due = _m(start, q)
            paid = rent / 12 if due <= today and not (tn.startswith("سيف") and due > today - dt.timedelta(days=45)) else 0
            c.execute("INSERT INTO rent_dues(lease_id,due,amount,paid,paid_date) VALUES(?,?,?,?,?)", (lid, due.isoformat(), rent / 12, paid, _iso(due) if paid else None))
            if paid:
                inv.add("rent", "lease", lid, tn, rent / 12, .05 if "شركة" in tn else 0, due.isoformat() + "T09:00:00", f"إيجار شهر {due:%Y-%m}")
    for amt, d, note in ((900_000, _m(today, -4), "توزيع بعد إصدار شهادة الإتمام"), (420_000, _m(today, -1), "توزيع بعد تحصيل دفعات التسليم")):
        c.execute("INSERT INTO distributions(project_id,investor,amount,day,note) VALUES(?,?,?,?,?)", (qrm, "الشركاء المؤسسون", amt, d.isoformat(), note))

    # ======================================================================= ١) مشروع في مرحلة الأرض والتراخيص والإطلاق
    an, al = names["AMR"]
    land = c.execute("SELECT id FROM lands ORDER BY id LIMIT 1").fetchone()[0]
    c.execute("UPDATE lands SET status='تم الشراء — قيد التطوير', notes=? WHERE id=?", (f"تحولت إلى مشروع {an}", land))
    a_ho = _m(today, 30)
    amr = c.execute("""INSERT INTO projects(code,name,location,kind,build_pct,planned_monthly_sales,handover,land_id,completed)
                       VALUES('AMR',?,?,'tower',3,5,?,?,0)""", (an, al, a_ho.isoformat(), land)).lastrowid
    a_units = []
    for f in range(1, 11):
        for p in range(1, 7):
            tp, ar = [("غرفتان وصالة", 115), ("٣ غرف وصالة", 150), ("غرفة وصالة", 76)][(p - 1) % 3]
            vw = "جبلي" if p <= 2 else "حديقة" if p <= 4 else "شارع"
            price = round(ar * {"جبلي": 560, "حديقة": 520, "شارع": 480}[vw] * (1 + f * .01), -2)
            a_units.append((c.execute("INSERT INTO units(project_id,code,building,floor,pos,type,area,view,price,status) VALUES(?,?,?,?,?,?,?,?,?,'a')",
                                      (amr, f"AMR-T-{f}{p:02d}", "T", f, p, tp, ar, vw, price)).lastrowid, price, f, p))
    launch = rnd.sample(a_units, 14)
    for n, (uid, price, f, p) in enumerate(launch):
        confirmed = n < 6
        if n == 6:
            cid = _customer(c, rnd, today, verified=False, kyc="review", risk="مرتفع", pep=1, note="شخص معرّض سياسيًا — يلزم عناية معززة واعتماد المدير")
        else:
            cid = _customer(c, rnd, today, verified=confirmed)
        created = today - dt.timedelta(days=rnd.randint(1, 20) if confirmed else rnd.randint(0, 2))
        plan = rnd.choice(["milestone", "6040"])
        c.execute("UPDATE units SET status=? WHERE id=?", ("s" if confirmed else "r", uid))
        bid = c.execute("INSERT INTO bookings(unit_id,customer_id,plan,price,status,created,expires,list_price) VALUES(?,?,?,?,?,?,?,?)",
                        (uid, cid, plan, price, "confirmed" if confirmed else "pending", created.isoformat(),
                         None if confirmed else _iso(created + dt.timedelta(days=3)), price)).lastrowid
        for s, (lb, d, amt) in enumerate(schedule(plan, price, created, a_ho), 1):
            paid = amt if confirmed and s == 1 else 0
            iid = c.execute("INSERT INTO installments(booking_id,seq,label,due_date,amount,paid_amount,paid_date) VALUES(?,?,?,?,?,?,?)",
                            (bid, s, lb, d.isoformat(), amt, paid, created.isoformat() if paid else None)).lastrowid
            if paid:
                c.execute("INSERT INTO payments(installment_id,amount,at,method,receipt,gateway_ref,reconciled) VALUES(?,?,?,?,?,?,0)",
                          (iid, paid, created.isoformat() + "T11:00:00", "بوابة الدفع", f"MBQ-P-{iid:06d}", f"gw_{iid}"))
                cname = c.execute("SELECT name FROM customers WHERE id=?", (cid,)).fetchone()[0]
                inv.add("installment", "installment", iid, cname, paid, 0, created.isoformat() + "T11:00:00", "عربون الحجز — توريد سكني أول", customer_id=cid)
        if confirmed and n < 4:
            _contract(c, bid, price, created.isoformat())
        if n in (7, 9):
            c.execute("INSERT INTO discount_requests(booking_id,pct,reason,status,requested_by,created) VALUES(?,?,?,?,?,?)",
                      (bid, .04 if n == 7 else .08, "عميل إطلاق يشتري وحدتين" if n == 7 else "سداد نقدي كامل خلال ٣٠ يومًا", "pending", "موظف المبيعات", today.isoformat()))
    k2 = contractor("الرائد للهندسة والمقاولات")
    val = sum(u[1] for u in a_units) * .72
    a_start = _m(today, -1)
    c.execute("INSERT INTO contracts_c(project_id,contractor_id,value,retention_pct,delay_penalty_per_day,start,finish) VALUES(?,?,?,?,?,?,?)",
              (amr, k2, round(val, -3), .10, round(val * .0005, -1), a_start.isoformat(), a_ho.isoformat()))
    tasks(amr, a_start, 31, 3)
    for cat, share in (("أعمال إنشائية", .62), ("كهروميكانيك", .18), ("تشطيبات", .12), ("استشارات وإشراف", .04), ("احتياطي طوارئ", .04)):
        c.execute("INSERT INTO budgets(project_id,category,amount) VALUES(?,?,?)", (amr, cat, round(val * share, -3)))
    c.execute("INSERT INTO site_reports(project_id,day,workers,weather,work_done,issues,photos,by) VALUES(?,?,?,?,?,?,?,?)",
              (amr, _iso(today - dt.timedelta(days=1)), 18, "مشمس", "تسوير الموقع وتجهيز مكاتب الموقع", "بانتظار رخصة البناء لبدء الحفر", 9, "مهندس الموقع"))
    for auth, kind, ref, st, ap, iss in (("بلدية مسقط", "موافقة مبدئية على المخطط", "PRE-2026-0331", "issued", -5, -4),
                                         ("هيئة البيئة", "تصريح بيئي", "ENV-4410", "issued", -4, -2),
                                         ("بلدية مسقط", "رخصة بناء", "BLD-2026-1502", "in_review", -1, None),
                                         ("وزارة الإسكان والتخطيط العمراني", "تسجيل المشروع وفتح حساب الضمان", "ESC-AMR-311", "issued", -2, -1),
                                         ("الدفاع المدني والإسعاف", "اعتماد مخططات السلامة", "", "submitted", -1, None),
                                         ("شركة الكهرباء", "توصيل كهرباء مؤقت للموقع", "", "not_started", None, None)):
        c.execute("INSERT INTO permits(project_id,authority,kind,ref,status,applied,issued,expires) VALUES(?,?,?,?,?,?,?,?)",
                  (amr, auth, kind, ref, st, _iso(_m(today, ap)) if ap is not None else None, _iso(_m(today, iss)) if iss is not None else None,
                   _iso(_m(today, 22)) if kind == "تصريح بيئي" else None))
    # عملاء محتملون لحملة الإطلاق
    for _ in range(16):
        cr = today - dt.timedelta(days=rnd.randint(0, 25))
        c.execute("""INSERT INTO leads(name,phone,interest,project_id,channel,stage,interactions,budget,created,last_contact,score)
                     VALUES(?,?,?,?,?,?,?,?,?,?,0)""", (f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", f"+968 9{rnd.randint(1000000, 9999999)}",
                                                       rnd.choice(["غرفتان إطلالة جبلية", "استثمار للإيجار", "٣ غرف حديقة", "سعر الإطلاق"]), amr,
                                                       rnd.choice(["إنستغرام", "واتساب", "حملة الإطلاق", "وسيط", "الموقع"]), rnd.choice([0, 0, 1, 1, 2, 3]),
                                                       rnd.randint(1, 6), rnd.choice([45000, 60000, 70000, 85000]), cr.isoformat(), cr.isoformat()))

    # الأراضي الأخرى: دراسات جدوى محفوظة لإظهار مقارنة الفرص
    for lid, nm, inp in ((land, "دراسة الشراء (معتمدة)", dict(sell_price_sqm=560, build_cost_sqm=255, presale_pct=.6, months=30)),
                         (land + 1, "سيناريو فلل متوسطة", dict(sell_price_sqm=430, build_cost_sqm=240, presale_pct=.5, months=24)),
                         (land + 2, "برج تجاري سكني", dict(sell_price_sqm=780, build_cost_sqm=320, presale_pct=.55, months=36))):
        row = c.execute("SELECT * FROM lands WHERE id=?", (lid,)).fetchone()
        if not row:
            continue
        p = dict(efficiency=.82, soft_cost_pct=.12, finance_rate=.065, name=nm, **inp)
        res = feas_engine(dict(row), p)
        c.execute("INSERT INTO feasibility(land_id,name,inputs,results,created,by) VALUES(?,?,?,?,?,?)",
                  (lid, nm, json.dumps(p, ensure_ascii=False), json.dumps(res, ensure_ascii=False), _iso(today - dt.timedelta(days=60 if lid == land else 5)), "مدير المنصة"))

    # ======================================================================= المراحل الوسطى في المشاريع القائمة
    # ضاحية الخوض: أول ٣ تسليمات مكتملة، وسند صادر وآخر مقدَّم
    for i, h in enumerate(c.execute("SELECT h.booking_id, b.price FROM handovers h JOIN bookings b ON b.id=h.booking_id ORDER BY h.id LIMIT 3").fetchall()):
        d = today - dt.timedelta(days=12 - i * 4)
        c.execute("UPDATE handovers SET status='done', handed_at=?, appointment=?, certificate_no=?, warranty_until=?, structural_until=?, keys=3 WHERE booking_id=?",
                  (d.isoformat(), d.isoformat(), f"HC-{h['booking_id']:05d}-K{i}", _m(d, 12).isoformat(), d.replace(year=d.year + 10).isoformat(), h["booking_id"]))
        c.execute("UPDATE snags SET status='fixed', closed=? WHERE booking_id=?", (d.isoformat(), h["booking_id"]))
        c.execute("UPDATE bookings SET handed_over=? WHERE id=?", (d.isoformat(), h["booking_id"]))
        c.execute("UPDATE installments SET paid_amount=amount, paid_date=COALESCE(paid_date, ?) WHERE booking_id=?", (d.isoformat(), h["booking_id"]))
        st = ["issued", "submitted", "ready"][i]
        c.execute("INSERT INTO titles(booking_id,status,fee,applied,deed_no,issued) VALUES(?,?,?,?,?,?)",
                  (h["booking_id"], st, round(h["price"] * .03) if st != "ready" else None, _iso(d) if st != "ready" else None,
                   f"MH-{rnd.randint(100000, 999999)}/{today.year}" if st == "issued" else None, today.isoformat() if st == "issued" else None))

    # السوق الثانوي: إعلانات بعروض، وطلب معلّق، وصفقة مكتملة
    def eligible(code, n):
        return c.execute("""SELECT b.id, b.price FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id
                            WHERE p.code=? AND b.status='confirmed' AND (SELECT SUM(paid_amount) FROM installments WHERE booking_id=b.id) >= .3*b.price
                            AND b.id NOT IN (SELECT booking_id FROM resale) ORDER BY b.id DESC LIMIT ?""", (code, n)).fetchall()
    for j, b in enumerate(eligible("RAY", 3)):
        ask = round(b["price"] * (1.08 + j * .03), -2)
        st = "pending" if j == 2 else "listed"
        rid = c.execute("INSERT INTO resale(booking_id,ask_price,fee,status,created) VALUES(?,?,?,?,?)",
                        (b["id"], ask, round(ask * .02), st, _iso(today - dt.timedelta(days=10 - j * 3)))).lastrowid
        if st == "listed":
            for q in range(2 - j):
                c.execute("INSERT INTO resale_offers(resale_id,buyer_name,buyer_phone,price,status,created) VALUES(?,?,?,?,?,?)",
                          (rid, f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", f"+968 9{rnd.randint(1000000, 9999999)}", round(ask * (.96 + q * .02), -2), "open", today.isoformat()))
    for b in eligible("QRM", 1):
        ask = round(b["price"] * 1.14, -2)
        rid = c.execute("INSERT INTO resale(booking_id,ask_price,fee,status,created) VALUES(?,?,?,?,?)", (b["id"], ask, round(ask * .02), "sold", _iso(today - dt.timedelta(days=50)))).lastrowid
        c.execute("INSERT INTO resale_offers(resale_id,buyer_name,buyer_phone,price,status,created) VALUES(?,?,?,?,?,?)",
                  (rid, "عبدالله الفارسي", "+968 99112233", ask, "accepted", _iso(today - dt.timedelta(days=41))))
        seller = c.execute("SELECT customer_id, (SELECT name FROM customers WHERE id=customer_id) name FROM bookings WHERE id=?", (b["id"],)).fetchone()
        inv.add("resale_fee", "resale", rid, seller["name"], round(ask * .02), .05, _iso(today - dt.timedelta(days=41)) + "T12:00:00",
                "رسوم تنازل في السوق الثانوي (على البائع)", customer_id=seller["customer_id"])

    # خصومات بمستويات اعتماد مختلفة
    for b, pct, why, st, by in zip(c.execute("SELECT b.id FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id WHERE p.code='SEB' AND b.status='pending' LIMIT 2").fetchall()
                                   + c.execute("SELECT b.id FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id WHERE p.code='RAY' AND b.status='pending' LIMIT 1").fetchall(),
                                   (.015, .045, .03), ("مطابقة عرض منافس", "عميل مؤسسي (٣ وحدات)", "تمديد خطة السداد بدل الخصم"),
                                   ("approved", "pending", "rejected"), ("موظف المبيعات", "المالية", "موظف المبيعات")):
        c.execute("INSERT INTO discount_requests(booking_id,pct,reason,status,requested_by,decided_by,created) VALUES(?,?,?,?,?,?,?)",
                  (b["id"], pct, why, st, by, "مدير المنصة" if st != "pending" else None, _iso(today - dt.timedelta(days=3))))

    # الفواتير والمطابقة البنكية لآخر ٤٥ يومًا
    recent = c.execute("""SELECT p.id, p.amount, p.at, p.receipt, i.id iid, i.label, cu.name, cu.id cid FROM payments p JOIN installments i ON i.id=p.installment_id
                          JOIN bookings b ON b.id=i.booking_id JOIN customers cu ON cu.id=b.customer_id
                          WHERE p.at>=? AND p.receipt LIKE 'MBQ-H-%' ORDER BY p.at""", (_iso(today - dt.timedelta(days=45)),)).fetchall()
    for n, p in enumerate(recent):
        inv.add("installment", "installment", p["iid"], p["name"], p["amount"], 0, p["at"], f"{p['label']} — توريد سكني أول", customer_id=p["cid"])
        if n % 3 == 0:
            c.execute("UPDATE payments SET reconciled=0 WHERE id=?", (p["id"],))
        else:
            c.execute("INSERT INTO bank_lines(day,amount,reference,matched_payment,imported) VALUES(?,?,?,?,?)",
                      (p["at"][:10], p["amount"], p["receipt"], p["id"], _iso(today - dt.timedelta(days=1))))
    for amt, ref in ((1_250, "TRF-UNKNOWN-8812"), (480, "POS-REFUND-221")):
        c.execute("INSERT INTO bank_lines(day,amount,reference,matched_payment,imported) VALUES(?,?,?,?,?)", (_iso(today - dt.timedelta(days=3)), amt, ref, None, today.isoformat()))

    # قنوات العملاء: واتساب، معاينات، إشعارات، خصوصية
    for ph, msgs in (("+968 9123 4567", [("in", "السلام عليكم، عندكم شقق غرفتين في العامرات؟"), ("out", f"وعليكم السلام 🌿 نعم، في {an} شقق غرفتين وصالة تبدأ من ٦٣٬٠٠٠ ر.ع بإطلالة جبلية. هل تود حجز معاينة؟"),
                                        ("in", "نعم السبت العصر"), ("out", "تم حجز معاينتك يوم السبت الساعة ٤:٣٠ عصرًا. سيتواصل معك مستشار المبيعات.")]),
                     ("+968 9555 0101", [("in", "كم باقي على قسطي؟"), ("out", "لأمان حسابك، تفاصيل الأقساط متاحة في تطبيق مبانيك بعد تسجيل الدخول.")])):
        for k_, (d_, body) in enumerate(msgs):
            c.execute("INSERT INTO wa_messages(phone,direction,body,at,engine) VALUES(?,?,?,?,?)",
                      (ph, d_, body, (dt.datetime.combine(today, dt.time(10, k_ * 3))).isoformat(timespec="seconds"), "rules"))
    for lid in [r[0] for r in c.execute("SELECT id FROM leads WHERE project_id=? AND stage>=1 LIMIT 5", (amr,))]:
        c.execute("INSERT INTO viewings(lead_id,project_id,at,status,source) VALUES(?,?,?,?,?)",
                  (lid, amr, (dt.datetime.combine(today + dt.timedelta(days=rnd.randint(1, 6)), dt.time(16, 30))).isoformat(), "booked", "واتساب"))
    cid0 = q_book[0][1]
    for t, b, aud, cust in (("سند ملكيتك صدر", "صدر سند ملكية وحدتك في " + qn + ". يمكنك استلامه من مكتب المبيعات.", "customer", cid0),
                            ("رسوم الخدمات السنوية", f"صدرت مطالبة رسوم الخدمات لعام {year}. ادفعها من التطبيق.", "customer", cid0),
                            ("تصويت جديد لاتحاد الملاك", "بند جديد: تحويل سطح المبنى إلى حديقة. صوّت قبل الإغلاق.", "customer", cid0),
                            ("رخصة بناء قيد المراجعة", f"رخصة بناء {an} قيد المراجعة لدى البلدية منذ أكثر من ٣٠ يومًا.", "staff", None),
                            ("دفعات غير مطابقة", "يوجد حركتان بنكيتان دون مرجع مطابق.", "staff", None)):
        c.execute("INSERT INTO notifications(audience,customer_id,channel,title,body,status,created,dedupe) VALUES(?,?,?,?,?,?,?,?)",
                  (aud, cust, "app", t, b, "queued", _iso(today - dt.timedelta(days=1)) + "T08:00:00", f"cycle:{t}"))
    c.execute("INSERT INTO privacy_requests(customer_id,kind,status,created,note) VALUES(?,?,?,?,?)",
              (q_book[3][1], "correct", "open", _iso(today - dt.timedelta(days=2)), "تصحيح الاسم بالإنجليزية في العقد"))

    # ======================================================================= السيولة: ضمان افتتاحي، تسهيلات، جدول تكاليف
    for code, pj, opening, fac, months_c, plan in (("QRM", qrm, 410_000, 0, 0, None), ("AMR", amr, 140_000, None, 12, "ramp")):
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"escrow:{pj}", str(opening)))
        remaining = val * .97 if code == "AMR" else 0
        for m in range(1, 13):
            month = _m(today.replace(day=1), m).strftime("%Y-%m")
            if code == "QRM":
                amt, label = 9_000, "صيانة فترة الضمان"
            else:
                amt = 45_000 if m <= 3 else remaining / 30 * (.6 if m <= 6 else 1)
                label = "تصاميم تنفيذية وتجهيز الموقع" if m <= 3 else "حفر وأساسات"
            c.execute("INSERT INTO cost_schedule(project_id,month,amount,label) VALUES(?,?,?,?)", (pj, month, round(amt, -3), label))
        if code == "AMR":
            c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"facility:{pj}", str(round(remaining / 30 * .75, -3))))
            c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"facility_months:{pj}", "12"))
        else:
            c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"facility:{pj}", "0"))
            c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"facility_months:{pj}", "0"))
    c.commit()
