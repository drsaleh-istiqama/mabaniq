"""بيانات تجريبية للوحدات الموسّعة (الأرض، التراخيص، الإنشاء، الوسطاء، العقود، ما بعد البيع، اتحاد الملاك، التأجير)."""
import datetime as dt
import hashlib
import json


def _m(d: dt.date, months: int) -> dt.date:
    y, mo = divmod(d.month - 1 + months, 12)
    return dt.date(d.year + y, mo + 1, min(d.day, 28))


SETTINGS = {
    # ضريبة القيمة المضافة — عُمان ٥٪؛ معالجة البيع السكني قابلة للضبط ويجب تأكيدها مع مستشار ضريبي
    "vat_standard": "0.05", "vat_residential_sale": "0.0", "vat_commercial_sale": "0.05",
    "title_fee_pct": "0.03",          # رسوم تسجيل نقل الملكية (قابلة للضبط)
    "late_penalty_monthly": "0.01",   # غرامة تأخير شهرية على القسط المتأخر بعد فترة سماح
    "late_grace_days": "15",
    "cancel_deduction_pct": "0.10",   # خصم الإلغاء بعد التأكيد (حسب العقد)
    "resale_fee_pct": "0.02",
    "resale_min_paid": "0.30",
    "discount_limit:sales": "0.02", "discount_limit:finance": "0.05",
    "warranty_months": "12", "structural_years": "10",
    "broker_default_rate": "0.02",
    "oa_rate_per_sqm": "2.4",         # رسوم خدمات سنوية ر.ع/م²
    "late_penalty_treatment": "charity",  # 0.5.0 — M4: مبالغ التأخير تبرع لجهة خيرية (شرط التبرع)، لا إيراد
}


def seed_ext(c, rnd, today: dt.date, pid: dict, projects: list, tenant: str) -> list:
    for k, v in SETTINGS.items():
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))

    # ------------------------------------------------ الأراضي والجدوى
    lands = [("أرض العامرات ٣", "العامرات", 12500, "سكني متعدد الطوابق", 3.2, 8, 1_450_000, "تحت الدراسة", 23.52, 58.50),
             ("أرض بركاء الساحلية", "بركاء", 46000, "سكني فلل", 0.9, 2, 2_100_000, "تفاوض", 23.70, 57.88),
             ("قطعة الموالح التجارية", "الموالح", 6800, "تجاري سكني", 4.0, 10, 1_900_000, "فرصة", 23.60, 58.21)]
    land_ids = []
    for ln in lands:
        land_ids.append(c.execute("INSERT INTO lands(name,location,area,zoning,far,max_floors,price,status,lat,lng) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                  ln).lastrowid)

    # ------------------------------------------------ التراخيص
    P = {code: pid[code][0] for code in pid}
    permit_rows = [
        ("RAY", "بلدية مسقط", "رخصة بناء", "BLD-2025-4471", "issued", -14, -12, 10),
        ("RAY", "وزارة الإسكان والتخطيط العمراني", "تسجيل المشروع وفتح حساب الضمان", "ESC-RAY-118", "issued", -13, -12, None),
        ("RAY", "الدفاع المدني والإسعاف", "اعتماد مخططات السلامة", "CD-88213", "issued", -12, -11, None),
        ("RAY", "شركة الكهرباء", "توصيل الكهرباء الدائم", "EL-55102", "in_review", -1, None, None),
        ("SEB", "بلدية مسقط", "رخصة بناء", "BLD-2026-0912", "issued", -6, -5, 1),
        ("SEB", "وزارة الإسكان والتخطيط العمراني", "تسجيل المشروع وفتح حساب الضمان", "ESC-SEB-204", "issued", -5, -5, None),
        ("SEB", "هيئة البيئة", "تصريح بيئي", "ENV-3391", "issued", -7, -6, 0),
        ("SEB", "الدفاع المدني والإسعاف", "اعتماد مخططات السلامة", "", "submitted", -1, None, None),
        ("KHD", "بلدية مسقط", "رخصة بناء", "BLD-2024-7720", "issued", -26, -25, 2),
        ("KHD", "بلدية مسقط", "شهادة إتمام البناء", "", "not_started", None, None, None),
        ("KHD", "وزارة الإسكان والتخطيط العمراني", "فرز الوحدات وإصدار الملكيات", "", "submitted", -1, None, None),
    ]
    for code, auth, kind, ref, st, ap, iss, exp in permit_rows:
        c.execute("INSERT INTO permits(project_id,authority,kind,ref,status,applied,issued,expires) VALUES(?,?,?,?,?,?,?,?)",
                  (P[code], auth, kind, ref, st, _m(today, ap).isoformat() if ap is not None else None,
                   _m(today, iss).isoformat() if iss is not None else None,
                   (_m(today, exp) + dt.timedelta(days=12)).isoformat() if exp is not None else None))

    # ------------------------------------------------ الإنشاء: العقود، الجدول، الميزانية، أوامر التغيير، التقارير
    stages = [("التصاريح والتجهيز", .05), ("الحفر والأساسات", .12), ("الهيكل الخرساني", .30), ("البلوك والتمديدات", .18),
              ("التشطيبات الداخلية", .20), ("الواجهات والأعمال الخارجية", .10), ("الاختبار والتسليم", .05)]
    kids = [r["id"] for r in c.execute("SELECT id FROM contractors ORDER BY id")]
    for (code, name, loc, kind, build, pl, ho), k in zip(projects, kids):
        pj = P[code]
        value = c.execute("SELECT SUM(price) FROM units WHERE project_id=?", (pj,)).fetchone()[0] * .72
        total_months = 30 if kind == "tower" else 24
        start = _m(ho, -total_months)
        c.execute("UPDATE contractors SET cr_number=? WHERE id=?", (str(1_100_000 + k * 7919), k))
        c.execute("INSERT INTO contracts_c(project_id,contractor_id,value,retention_pct,delay_penalty_per_day,start,finish) VALUES(?,?,?,?,?,?,?)",
                  (pj, k, round(value, -3), .10, round(value * .0005, -1), start.isoformat(), ho.isoformat()))
        acc, prev = 0, None
        for nm, w in stages:
            s0 = _m(start, round(total_months * acc))
            e0 = _m(start, round(total_months * (acc + w)))
            lo, hi = acc * 100, (acc + w) * 100
            pct = 100 if build >= hi else 0 if build <= lo else round((build - lo) / (hi - lo) * 100)
            lag = 0
            if code == "SEB" and nm == "الهيكل الخرساني":
                lag = 3  # تأخير مقصود في البيانات لإظهار تحليل المسار الحرج
                pct = max(0, pct - 35)
            a_start = s0.isoformat() if pct > 0 else None
            a_end = (_m(e0, lag)).isoformat() if pct == 100 else None
            prev = c.execute("INSERT INTO schedule_tasks(project_id,name,planned_start,planned_end,actual_start,actual_end,pct,depends_on,weight) "
                             "VALUES(?,?,?,?,?,?,?,?,?)", (pj, nm, s0.isoformat(), e0.isoformat(), a_start, a_end, pct, prev, w)).lastrowid
            acc += w
        for cat, share in (("أعمال إنشائية", .62), ("كهروميكانيك", .18), ("تشطيبات", .12), ("استشارات وإشراف", .04), ("احتياطي طوارئ", .04)):
            c.execute("INSERT INTO budgets(project_id,category,amount) VALUES(?,?,?)", (pj, cat, round(value * share, -3)))
        for i in range(3):
            d = today - dt.timedelta(days=i + 1)
            c.execute("INSERT INTO site_reports(project_id,day,workers,weather,work_done,issues,photos,by) VALUES(?,?,?,?,?,?,?,?)",
                      (pj, d.isoformat(), rnd.randint(40, 140), rnd.choice(["مشمس", "حار ورطب", "غبار خفيف"]),
                       rnd.choice(["صب سقف", "أعمال بلوك", "تمديدات كهربائية", "لياسة داخلية", "عزل أسطح"]),
                       rnd.choice(["", "", "تأخر توريد حديد التسليح يومين", "نقص عمالة في وردية المساء"]), rnd.randint(6, 30), "مهندس الموقع"))
    co = [("RAY", 1, "تغيير نوع البلاط في الردهات", "طلب تسويقي", 38_000, 10, "approved"),
          ("RAY", 2, "إضافة نظام شحن سيارات كهربائية", "متطلب سوق", 64_000, 21, "pending"),
          ("SEB", 1, "تعديل تصميم الأساسات بعد تقرير التربة", "ظروف موقع", 145_000, 45, "approved"),
          ("SEB", 2, "رفع مواصفات الواجهة الزجاجية", "طلب المالك", 92_000, 30, "pending"),
          ("KHD", 1, "مظلات سيارات للفلل الزاوية", "طلب العملاء", 21_000, 7, "approved")]
    for code, no, t, r, cost, days, st in co:
        c.execute("INSERT INTO change_orders(project_id,no,title,reason,cost,days,status,requested,decided,decided_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (P[code], no, t, r, cost, days, st, (today - dt.timedelta(days=30 + no * 9)).isoformat(),
                   (today - dt.timedelta(days=20)).isoformat() if st == "approved" else None, "مدير المنصة" if st == "approved" else None))
    for code, t, sev, st, loc in (("RAY", "تعشيش في عمود الطابق ٩ برج A", "major", "open", "A-9"),
                                  ("RAY", "انحراف في منسوب بلاط الطابق ٤", "minor", "closed", "B-4"),
                                  ("SEB", "غطاء خرساني أقل من المواصفة في القاعدة F3", "major", "open", "F3"),
                                  ("KHD", "تسرب في عزل سطح الفيلا ٠٣٦", "minor", "open", "V-036")):
        c.execute("INSERT INTO ncrs(project_id,title,severity,status,raised,closed,location) VALUES(?,?,?,?,?,?,?)",
                  (P[code], t, sev, st, (today - dt.timedelta(days=rnd.randint(3, 25))).isoformat(),
                   today.isoformat() if st == "closed" else None, loc))

    # ------------------------------------------------ الوسطاء والعمولات
    brokers = []
    for nm, lic, rate in (("دار الخليج للوساطة العقارية", "RE-B-2231", .02), ("مكتب الأمانة العقاري", "RE-B-1908", .025)):
        brokers.append((c.execute("INSERT INTO brokers(name,license_no,phone,rate) VALUES(?,?,?,?)",
                                  (nm, lic, f"+968 2{rnd.randint(1000000, 9999999)}", rate)).lastrowid, nm))
    conf = c.execute("SELECT b.id, b.price FROM bookings b WHERE b.status='confirmed' ORDER BY b.id").fetchall()
    for i, b in enumerate(conf[::9][:14]):
        br = brokers[i % 2]
        rate = .02 if i % 2 == 0 else .025
        c.execute("UPDATE bookings SET broker_id=? WHERE id=?", (br[0], b["id"]))
        c.execute("INSERT INTO commissions(broker_id,booking_id,amount,status,paid_at) VALUES(?,?,?,?,?)",
                  (br[0], b["id"], round(b["price"] * rate), "paid" if i % 3 else "due", today.isoformat() if i % 3 else None))
    for lid in [r["id"] for r in c.execute("SELECT id FROM leads WHERE channel='وسيط'")]:
        c.execute("UPDATE leads SET broker_id=? WHERE id=?", (brokers[lid % 2][0], lid))
    c.execute("UPDATE bookings SET list_price=price WHERE list_price IS NULL")

    # ------------------------------------------------ عقود البيع الموقعة لعينة
    for b in conf[:25]:
        num = f"SPA-{b['id']:05d}"
        body = f"عقد بيع على الخريطة رقم {num} — حجز {b['id']} — القيمة {b['price']:,.0f} ر.ع"
        h = hashlib.sha256(body.encode()).hexdigest()
        c.execute("INSERT INTO sale_contracts(booking_id,number,body,sha256,status,created,customer_signed_at,customer_sig,developer_signed_at,developer_sig) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)", (b["id"], num, body, h, "signed", today.isoformat(), today.isoformat(),
                                                  "migrated", today.isoformat(), "migrated"))

    # ------------------------------------------------ مشروع الفلل: تسليم وعيوب وملكيات وأصول واتحاد ملاك
    khd = P["KHD"]
    khd_b = c.execute("""SELECT b.id, u.area FROM bookings b JOIN units u ON u.id=b.unit_id
                         WHERE u.project_id=? AND b.status='confirmed' ORDER BY b.id""", (khd,)).fetchall()
    for i, b in enumerate(khd_b[:8]):
        appt = today + dt.timedelta(days=7 + i * 2)
        c.execute("INSERT INTO handovers(booking_id,appointment,status) VALUES(?,?,?)", (b["id"], appt.isoformat(), "scheduled"))
        for item, loc in rnd.sample([("خدش في باب المدخل", "المدخل"), ("ميلان بسيط في بلاط الحمام", "حمام ٢"),
                                     ("مفتاح إنارة لا يعمل", "المجلس"), ("تسرب بسيط تحت المغسلة", "المطبخ"),
                                     ("فراغ في سيليكون النافذة", "غرفة ١")], 2):
            c.execute("INSERT INTO snags(booking_id,item,location,status,raised) VALUES(?,?,?,?,?)",
                      (b["id"], item, loc, "open" if i % 2 else "fixed", today.isoformat()))
    for nm, cat, interval in (("مضخات المياه الرئيسية", "ميكانيك", 90), ("مولد الطوارئ", "كهرباء", 30),
                              ("نظام إنذار الحريق", "سلامة", 180), ("بوابات الدخول", "أمن", 60), ("شبكة الري", "زراعة", 30)):
        aid = c.execute("INSERT INTO fm_assets(project_id,name,category,last_service,interval_days,installed) VALUES(?,?,?,?,?,?)",
                        (khd, nm, cat, (today - dt.timedelta(days=rnd.randint(10, interval + 20))).isoformat(), interval,
                         (today - dt.timedelta(days=200)).isoformat())).lastrowid
        c.execute("INSERT INTO work_orders(asset_id,kind,title,due,status,cost) VALUES(?,?,?,?,?,?)",
                  (aid, "preventive", f"صيانة دورية: {nm}", (today + dt.timedelta(days=rnd.randint(-5, 20))).isoformat(), "open", 0))
    year = today.year + 1
    for line, amt in (("الأمن والحراسة", 54_000), ("النظافة", 26_000), ("صيانة المرافق المشتركة", 31_000),
                      ("الري والمسطحات الخضراء", 18_000), ("التأمين", 9_000), ("احتياطي رأسمالي", 12_000)):
        c.execute("INSERT INTO oa_budget(project_id,year,line,amount) VALUES(?,?,?,?)", (khd, year, line, amt))
    c.execute("INSERT INTO oa_motions(project_id,title,opened,closes,status) VALUES(?,?,?,?,?)",
              (khd, "اعتماد ميزانية الخدمات المشتركة للسنة القادمة", today.isoformat(), (today + dt.timedelta(days=14)).isoformat(), "open"))
    c.execute("INSERT INTO oa_motions(project_id,title,opened,closes,status) VALUES(?,?,?,?,?)",
              (khd, "تركيب كاميرات مراقبة إضافية عند البوابة الشرقية", today.isoformat(), (today + dt.timedelta(days=14)).isoformat(), "open"))

    # ------------------------------------------------ وحدات محتفظ بها للتأجير (أبراج الريحان)
    ray_units = c.execute("SELECT id FROM units WHERE project_id=? AND status='a' ORDER BY floor LIMIT 4", (P["RAY"],)).fetchall()
    for i, u in enumerate(ray_units):
        c.execute("UPDATE units SET retained=1 WHERE id=?", (u["id"],))
        if i < 3:
            tid = c.execute("INSERT INTO tenants_l(name,phone,id_number) VALUES(?,?,?)",
                            (["شركة النور للخدمات", "سالم الكندي", "منى الهنائي"][i], f"+968 9{rnd.randint(1000000, 9999999)}",
                             str(rnd.randint(10000000, 99999999)))).lastrowid
            start = today - dt.timedelta(days=60 + i * 90)
            rent = [7800, 6600, 5400][i]
            lid = c.execute("INSERT INTO leases(unit_id,tenant_id,start,end,annual_rent,frequency,deposit,status,municipality_ref) "
                            "VALUES(?,?,?,?,?,?,?,?,?)", (u["id"], tid, start.isoformat(), (start + dt.timedelta(days=365)).isoformat(),
                                                           rent, 4, rent / 12, "active", f"MCT-L-{rnd.randint(100000, 999999)}")).lastrowid
            for q in range(4):
                due = _m(start, q * 3)
                paid = rent / 4 if due <= today and not (i == 2 and q == 1) else 0
                c.execute("INSERT INTO rent_dues(lease_id,due,amount,paid,paid_date) VALUES(?,?,?,?,?)",
                          (lid, due.isoformat(), rent / 4, paid, due.isoformat() if paid else None))

    # ------------------------------------------------ سجل الدفعات التاريخية (للمطابقة البنكية والتصدير المحاسبي)
    for i in c.execute("SELECT id, paid_amount, paid_date FROM installments WHERE paid_amount>0").fetchall():
        c.execute("INSERT INTO payments(installment_id,amount,at,method,receipt,gateway_ref,reconciled) VALUES(?,?,?,?,?,?,?)",
                  (i["id"], i["paid_amount"], (i["paid_date"] or today.isoformat()) + "T10:00:00", "تحويل بنكي",
                   f"MBQ-H-{i['id']:06d}", f"hist_{i['id']}", 1))

    # ------------------------------------------------ توزيعات المستثمرين وقائمة الفحص
    c.execute("INSERT INTO distributions(project_id,investor,amount,day,note) VALUES(?,?,?,?,?)",
              (P["KHD"], "الشركاء المؤسسون", 350_000, (today - dt.timedelta(days=40)).isoformat(), "توزيع مرحلي بعد تجاوز ٨٥٪ من المبيعات"))
    for nm in ("مثال: شخص مدرج على قائمة عقوبات", "Example Sanctioned Person"):
        c.execute("INSERT INTO watchlist(name,source) VALUES(?,?)", (nm, "قائمة تجريبية — تُستبدل بمصدر رسمي"))
    c.execute("INSERT INTO settings VALUES('tenant_name',?)", (json.dumps(tenant),))
    c.commit()
    return brokers
