"""Mabaniq — profile-driven developer organisations (0.13.0).

A *profile* describes a real developer's portfolio (projects, buildings, unit mix, illustrative prices, letterhead and a set of
bundled sample images) so the demo seed can stand up a tenant that looks like that developer instead of the generic Jadwa
demo. The first profile is **المخطط العقارية (Al Mukhatat Real Estate)** — a pilot agreed with its CEO Dr. Dawood Al Hinai
(trial of the platform on his company's public material: almukhatat.com, the Maab brochure and @almukhatatreale).

Facts come from the company's public website/brochure; **prices, sold ratios, buyers, payments and schedules are illustrative**
(the company does not publish prices) and are flagged as such in the platform's documentation. No person appears in any asset.

The seed keeps its three internal *slots* (RAY = large tower mid-build, SEB = slow early tower, KHD = villas near handover) so
every later seed stage (permits, IPCs, resale, discounts, handovers…) still finds the project it expects; the profile maps each
slot to the real project code/name and may add further projects (slot MLZ here).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .config import tenants_extra

ASSETS = Path(__file__).resolve().parent / "assets" / "samples"


def tenants_from_env() -> dict:
    """`MABANIQ_TENANTS="code:الاسم;code2:الاسم"` — developer organisations added by configuration (persistent on Railway, where
    data/tenants.json is lost with the container). Codes follow the tenant slug rule (lowercase, digits, dash)."""
    out = {}
    for part in tenants_extra().split(";"):
        part = part.strip()
        if not part:
            continue
        code, _, name = part.partition(":")
        code = code.strip().lower()
        if code:
            out[code] = name.strip() or PROFILES.get(code, {}).get("display", code)
    return out


# ----------------------------------------------------------------------------------------------------------------------- profiles
# unit spec: (type label, area m², view/orientation, illustrative price per m² in OMR, use)
_MAAB_FLOOR = [("نموذج 01 — غرفتان وصالة", 97.70, "جبلي", 690, "residential"), ("نموذج 02 — غرفة وصالة", 67.10, "جبلي", 705, "residential"),
               ("نموذج 03 — غرفة وصالة", 63.60, "شارع الجامعة", 695, "residential"), ("نموذج 04 — غرفة وصالة", 67.00, "شارع الجامعة", 695, "residential"),
               ("نموذج 05 — غرفة وصالة", 62.60, "داخلي", 665, "residential"), ("شقة فندقية — غرفة وصالة", 63.60, "جبلي", 770, "hotel")]
_MAAB_SHOPS = [("محل تجاري", a, "شارع الجامعة", 1450, "commercial") for a in (25.28, 23.70, 23.70, 23.70, 25.28, 24.49)]
_MRT_RES = [("شقة 61 م² — غرفة وصالة", 61.25, "شارع نستو", 630, "residential"), ("شقة 78 م² — غرفتان وصالة", 78.0, "شارع نستو", 625, "residential"),
            ("شقة 95 م² — غرفتان وصالة", 95.0, "داخلي", 600, "residential"), ("شقة 112 م² — 3 غرف وصالة", 112.0, "داخلي", 600, "residential"),
            ("شقة 132 م² — 3 غرف وصالة", 132.6, "شارع نستو", 640, "residential")]
_MRT_OFF = [("مكتب", a, "شارع نستو" if i % 2 == 0 else "داخلي", 560, "commercial") for i, a in enumerate((50, 62, 75, 88, 100) * 3)]
_MRT_SHOPS = [("محل تجاري", a, "شارع نستو", 1300, "commercial") for a in (22, 24, 26, 28, 30, 32, 34, 38, 40, 44, 46)]
_MLZ_FLOOR = [("نموذج 1 — 3 غرف وصالة", 113.80, "الحديقة", 660, "residential"), ("نموذج 2 — غرفة وصالة", 63.0, "شارع النزهة", 680, "residential"),
              ("نموذج 3 — غرفة وصالة", 58.0, "شارع النزهة", 680, "residential"), ("نموذج 4 — غرفة وصالة", 58.70, "داخلي", 650, "residential"),
              ("نموذج 5 — غرفة وصالة", 60.0, "الحديقة", 665, "residential"), ("نموذج 6 — غرفة وصالة", 59.10, "داخلي", 650, "residential")]

# 0.15.0 — بيان عمان (Bayan Oman): a mostly commercial portfolio (offices + shops, sold *and* leased). Areas come from the three public
# brochures (Masahat Al Khoudh, Al Shabab Business Centre, Alaa Business Avenue); prices and rents are illustrative — the company publishes
# neither (offices ~450–600 OMR/m² sale or 6–9 OMR/m²/month rent, shops higher). MQ Residences has no public unit data: its mix is illustrative.
_MSK_SHOPS = [("محل تجاري — واجهة شارع السلام", a, "شارع السلام", 1000, "commercial")
              for a in (46.8, 46.8, 46.8, 46.8, 58.4, 58.4, 58.4, 58.4, 41.4, 41.4, 45.0, 45.0, 58.4, 58.4, 46.8, 45.6, 45.6, 46.8, 58.4, 61.3)]
_MSK_F1 = [(f"مكتب {a:g} م²", a, "شارع السلام" if i % 2 == 0 else "داخلي", 520, "commercial")
           for i, a in enumerate((84.3, 78.1, 75.4, 75.4, 80.5, 80.7, 92.77, 75.4, 75.4, 75.4, 58.0, 50.8))]
_MSK_F2 = [(f"مكتب بشرفة {a:g} م²", a, "شرفة خارجية", 530, "commercial") for a in (63.7, 52.4, 81.1, 67.4, 55.3, 64.2, 51.6, 51.6, 51.6, 92.4, 60.1)]
_ALA_TYPICAL = [(f"مكتب {a:g} م²", a, "شارع دوحة الأدب" if i < 8 else "داخلي", 580, "commercial")
                for i, a in enumerate((116.7, 76.1, 76.1, 86.0, 85.5, 85.5, 85.8, 116.7, 117.2, 74.0, 74.0, 85.8, 85.5, 85.5, 86.0, 117.2))]
_ALA_PENTHOUSE = [(f"مكتب علوي {a:g} م²", a, "الحديقة السماوية", 620, "commercial")
                  for a in (116.7, 76.1, 76.1, 86.0, 111.4, 85.8, 116.7, 117.1, 74.1, 74.1, 85.8, 111.4, 86.0, 122.9)]
_SHB_SHOPS = [("محل تجاري — شارع الشباب", a, "شارع الشباب", 950, "commercial") for a in (71.90, 45.78, 48.64, 63.95, 35.60, 71.30, 44.07, 54.88, 56.75, 33.97)]
_SHB_OFF = [(f"مكتب {L} — {a:g} م²", a, "شارع الشباب" if L in "ABC" else "داخلي", 480, "commercial")
            for L, a in zip("ABCDEFGH", (99.27, 96.94, 99.03, 53.90, 59.08, 66.63, 72.39, 69.75))]
_MQR_FLOOR = [("شقة غرفة وصالة — 68 م²", 68.0, "داخلي", 590, "residential"), ("شقة غرفتان وصالة — 95 م²", 95.0, "الشارع", 600, "residential"),
              ("شقة غرفتان وصالة — 102 م²", 102.0, "الشارع", 600, "residential"), ("شقة 3 غرف وصالة — 128 م²", 128.0, "الحديقة", 620, "residential"),
              ("شقة غرفتان وصالة — 98 م²", 98.0, "الحديقة", 610, "residential"), ("شقة غرفة وصالة — 72 م²", 72.0, "داخلي", 590, "residential")]


PROFILES: dict[str, dict] = {
    "bayan": {
        "display": "بيان عمان",
        "seed": 2015,
        "org_demo": {"seed": 7101},  # 0.29.0: backend/seed_org.py fills HR, payroll, books, leasing operations and policies with illustrative data
        "brand": {"name": "بيان عمان للتطوير العقاري (Bayan Oman)", "address": "العذيبة، محافظة مسقط، سلطنة عُمان — ص.ب 236، ر.ب 130", "phone": "72228000",
                  "email": "contact@bayanoman.com", "signatory": "", "signatory_title": "المؤسس والرئيس التنفيذي"},
        # slot, code, name, location, kind, build %, planned monthly sales, handover (months from today), escrow balance (illustrative)
        "projects": [
            ("RAY", "MSK", "مساحات الخوض", "الخوض — شارع السلام", "tower", 64, 4, 8, "180000"),
            ("SEB", "ALA", "آلاء بيزنس أفنيو", "مدينة السلطان قابوس — شارع دوحة الأدب", "tower", 36, 3, 16, "220000"),
            ("KHD", "MQR", "إم كيو ريزيدنسز (MQ Residences)", "مسقط", "tower", 92, 3, 3, "90000"),
            ("SHB", "SHB", "مركز الشباب للأعمال", "الخوض — شارع الشباب", "tower", 22, 3, 20, "140000"),
        ],
        "buildings": [
            ("RAY", "M", (0, 0), _MSK_SHOPS, 0, {"شارع السلام": .55}),
            ("RAY", "M", (1, 1), _MSK_F1, .01, {"شارع السلام": .5, "داخلي": .4}),
            ("RAY", "M", (2, 2), _MSK_F2, .01, {"شرفة خارجية": .45}),
            ("SEB", "A", (1, 5), _ALA_TYPICAL, .008, {"شارع دوحة الأدب": .22, "داخلي": .16}),
            ("SEB", "A", (6, 6), _ALA_PENTHOUSE, .008, {"الحديقة السماوية": .2}),
            ("KHD", "R", (1, 5), _MQR_FLOOR, .01, {"الشارع": .88, "الحديقة": .9, "داخلي": .82}),
            ("SHB", "S", (0, 0), _SHB_SHOPS, 0, {"شارع الشباب": .3}),
            ("SHB", "S", (1, 4), _SHB_OFF, .01, {"شارع الشباب": .28, "داخلي": .2}),
        ],
        "interests": {"RAY": ["محل بواجهة على شارع السلام", "مكتب 75 م² بالطابق الأول", "مكتب بشرفة بالطابق الثاني", "إيجار مكتب سنوي", "عائد إيجاري على محل"],
                      "SEB": ["مكتب 85 م² على دوحة الأدب", "مكتب زاوية 117 م²", "مكتب علوي مع الحديقة السماوية", "إيجار مكتب لشركة"],
                      "KHD": ["شقة غرفتان وصالة", "شقة 3 غرف للعائلة", "تمويل من بنك نزوى"],
                      "SHB": ["مكتب A 99 م²", "محل على شارع الشباب", "مكتب صغير 54 م²", "حجز مبكر بسعر الإطلاق"]},
        "lead_mix": ["RAY", "RAY", "SEB", "SHB", "KHD", "RAY"],
        "cycle_names": {"AMR": ("بوابة المعبيلة (Mabelah Gateway)", "المعبيلة"), "QRM": ("ساحة الخوير (Al Khuwair Square)", "الخوير")},
        # 0.15.0 — units the developer keeps for leasing (Bayan is a lessor as well as a seller): (unit code, lessee or None = vacant retained
        # unit, annual rent OMR, dues per year, lease start in months from today, arrears flag). Rents are illustrative.
        "leases": [("MSK-M-001", "شركة الأفق للتقنية الحديثة", 6800, 4, -8, 0),
                   ("MSK-M-005", "صيدلية الخوض الحديثة", 8400, 4, -14, 1),
                   ("MSK-M-103", "مكتب الريادة للاستشارات الهندسية", 6500, 4, -5, 0),
                   ("MSK-M-108", "شركة ذكاء لحلول الأعمال", 6300, 12, -11, 0),
                   ("MSK-M-205", "مؤسسة النخبة للمحاماة", 5500, 4, -3, 0),
                   ("MSK-M-012", None, 0, 0, 0, 0)],
        "assets": [
            ("bayan/bayan-logo.png", "brand", "logo", None, None, None, 0),
            ("bayan/masahat-site-map.jpg", "RAY", "site", "موقع المشروع — الخوض، شارع السلام (قرب مدرسة إلسمير ومسجد الرحمن الرحيم)", None, None, 1),
            ("bayan/masahat-plan-gf-shops.jpg", "RAY", "floor", "مخطط الطابق الأرضي — 20 محلًا تجاريًا", "M", 0, 1),
            ("bayan/masahat-plan-f1-offices.jpg", "RAY", "floor", "مخطط الطابق الأول — 12 مكتبًا وقاعتا اجتماعات", "M", 1, 1),
            ("bayan/masahat-plan-f2-offices.jpg", "RAY", "floor", "مخطط الطابق الثاني — 11 مكتبًا بشرفة خارجية", "M", 2, 1),
            ("bayan/masahat-render-front.jpg", "RAY", "render", "التصور النهائي — الواجهة على شارع السلام", None, None, 1),
            ("bayan/masahat-render-02.jpg", "RAY", "render", "التصور النهائي — المحلات والمكاتب", None, None, 1),
            ("bayan/masahat-render-street.jpg", "RAY", "render", "التصور النهائي — من الشارع", None, None, 1),
            ("bayan/masahat-render-entrance.jpg", "RAY", "render", "التصور النهائي — المدخل الرئيسي", None, None, 1),
            ("bayan/masahat-interior-office.jpg", "RAY", "render", "تصور داخلي — مكتب", None, None, 1),
            ("bayan/masahat-meeting-room.jpg", "RAY", "render", "قاعات الاجتماعات المشتركة", None, None, 1),
            ("bayan/masahat-lobby.jpg", "RAY", "render", "اللوبي", None, None, 1),
            ("bayan/masahat-parking.jpg", "RAY", "render", "70 موقفًا للسيارات", None, None, 1),
            ("bayan/alaa-location-map.jpg", "SEB", "site", "موقع المشروع — مدينة السلطان قابوس، شارع دوحة الأدب", None, None, 1),
            ("bayan/alaa-plan-typical.jpg", "SEB", "floor", "مخطط الطابق المتكرر (1–5) — 16 مكتبًا", "A", 1, 1),
            ("bayan/alaa-plan-penthouse.jpg", "SEB", "floor", "مخطط الطابق العلوي — 14 مكتبًا", "A", 6, 1),
            ("bayan/alaa-render-tower.jpg", "SEB", "render", "التصور النهائي — الطوابق العلوية", None, None, 1),
            ("bayan/alaa-aerial.jpg", "SEB", "render", "الموقع من الجو — مدينة السلطان قابوس", None, None, 1),
            ("bayan/alaa-roof-garden.jpg", "SEB", "render", "الحديقة السماوية", None, None, 1),
            ("bayan/alaa-interior-office.jpg", "SEB", "render", "تصور داخلي — مكتب 70–120 م²", None, None, 1),
            ("bayan/shabab-location-aerial.jpg", "SHB", "site", "الموقع — شارع الشباب، الخوض", None, None, 1),
            ("bayan/shabab-plan-gf-shops.jpg", "SHB", "floor", "مخطط الطابق الأرضي — 10 محلات", "S", 0, 1),
            ("bayan/shabab-plan-offices.jpg", "SHB", "unit", "مخطط الطابق المتكرر للمكاتب — المكتب A مظلَّل", "S", None, "مكتب A — 99.27 م²", 1),
            ("bayan/shabab-render-upper.jpg", "SHB", "render", "التصور النهائي — الطوابق العلوية", None, None, 1),
            ("bayan/shabab-stats.jpg", "SHB", "render", "32 وحدة مكتبية · 10 وحدات تجارية · 42 موقفًا", None, None, 1),
            ("bayan/shabab-features.jpg", "SHB", "render", "مميزات المركز", None, None, 1),
            ("bayan/shabab-interior-office.jpg", "SHB", "render", "تصور داخلي — مكتب", None, None, 1),
            ("bayan/shabab-interior-reception.jpg", "SHB", "render", "تصور داخلي — الاستقبال", None, None, 1),
            ("bayan/mq-residences-facade.jpg", "KHD", "render", "واجهة المبنى", None, None, 1),
            ("bayan/khuwair-square-photo.jpg", "QRM", "render", "المبنى بعد التشغيل", None, None, 1),
        ],
        "pilot_accounts": [
            ("bayan-ceo", "الرئيس التنفيذي — بيان عمان", "admin", None),
            ("bayan-sales", "فريق المبيعات والتأجير", "sales", None),
            ("bayan-finance", "المالية والتحصيل", "finance", None),
            ("bayan-engineer", "المشاريع والإنشاء", "engineer", None),
            ("bayan-client", "عميل تجريبي — وحدة في مساحات الخوض", "customer", "client1"),
            # 0.29.0 — the people side of the full demo: HR officer and the accountant also have their own employee file; "emp:<key>" links the login to that file
            ("bayan-hr", "مسؤولة الموارد البشرية", "hr", "emp:hr"),
            ("bayan-payroll", "مسؤول الرواتب", "payroll", None),
            ("bayan-pm", "مدير عقاري خارجي", "property_manager", None),
            ("bayan-accountant", "المحاسبة", "accountant", None),
            ("bayan-employee", "مدير المبيعات والتأجير (بوابة الموظف)", "employee", "emp:smgr"),
        ],
        # markers on the ground-floor plan of Masahat (percent of the image; the 20 shops sit in one row along Al Salam Street)
        "markers": {"bayan/masahat-plan-gf-shops.jpg": [(f"MSK-M-0{i:02d}", x, 44) for i, x in enumerate(
            (6.3, 10.5, 14.7, 18.9, 23.2, 27.4, 31.6, 35.8, 40.5, 45.3, 54.9, 60.0, 64.7, 68.9, 73.2, 77.4, 81.7, 85.9, 90.1, 94.5), 1)]},
    },
    "almaqsura": {
        "display": "المقصورة العقارية",
        "seed": 2005,
        # 0.18.1 — REAL data only (owner's instruction 2026-10-28): no demo buyers, leads, contractors or invented projects. Sources:
        # the approved August-2026 rent report of building 534 (Al Khuwair South, phase 3, plot 1742; manager Al Bara'a International),
        # the purchased-units workbook (two towers, 30 units, 8 leased), nine shops in Souq Al Sad, one plot for sale in Azaiba.
        # Unknown values stay empty (NULL) and are listed in docs/OWNER_DECISIONS.md — nothing is invented.
        "real_only": True,
        # 0.20.0 — a leasing company: no sales cycle. Licence and default modules = the leasing bundle (backend/registry.py BUNDLES);
        # accounting and HR join the licence when they ship (design §2.2) and stay off until the owner asks for them.
        "bundle": "leasing_only",
        "brand": {"name": "المقصورة العقارية (Almaqsura Real Estate)", "address": "مركز داود للأعمال، الخوض السابعة، ولاية السيب، محافظة مسقط",
                  "phone": "", "email": "", "signatory": "", "signatory_title": "المدير العام"},
        # code, name, location, kind, build %, planned monthly sales, handover (ISO), completed
        "real_projects": [
            ("IST", "بناية الاستقامة — الخوير الجنوبية", "الخوير الجنوبية، المرحلة 3 — شارع المها (مبنى 534، أرض 1742)", "tower", 100, 0, "2025-01-01", 1),
            ("MQT", "الوحدات المملوكة — البرجان 1 و2", "مسقط (الموقع والمبنى غير مزوَّدين)", "tower", 100, 0, "2025-01-01", 1),
            ("SAD", "محلات سوق السد", "سوق السد — مسقط", "tower", 100, 0, "2025-01-01", 1),
            ("AZB", "أرض العذيبة — للبيع", "العذيبة، محافظة مسقط", "land", 100, 1, "2027-01-01", 0),
        ],
        # the seed's `projects` tuple shape (slot = code) keeps the generic guards working
        "projects": [("IST", "IST", "بناية الاستقامة — الخوير الجنوبية", "الخوير الجنوبية — شارع المها", "tower", 100, 0, 0, "0"),
                     ("MQT", "MQT", "الوحدات المملوكة — البرجان 1 و2", "مسقط", "tower", 100, 0, 0, "0"),
                     ("SAD", "SAD", "محلات سوق السد", "سوق السد — مسقط", "tower", 100, 0, 0, "0"),
                     ("AZB", "AZB", "أرض العذيبة — للبيع", "العذيبة", "land", 100, 1, 0, "0")],
        # building 534: (unit, type, floor, pos, use, status, monthly rent, paid dues, unpaid dues, lessee, lease start, note)
        "ist_units": [
    ('11', 'شقة', 1, 1, 'residential', 'leased', 180, [('2026-08-01', 180, '2026-08-24', 'تحويل')], [], None, '2026-01-01', None),
    ('12', 'شقة', 1, 2, 'residential', 'leased', 250, [], ['2026-06-01', '2026-07-01', '2026-08-01'], None, '2026-01-01', None),
    ('13', 'شقة', 1, 3, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-10', 'شيك')], [], None, '2026-01-01', None),
    ('14', 'شقة', 1, 4, 'residential', 'leased', 200, [('2026-08-01', 200, '2026-09-04', 'تحويل')], [], None, '2026-01-01', None),
    ('15', 'شقة', 1, 5, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-16', 'شيك')], [], None, '2026-01-01', None),
    ('21', 'شقة', 2, 1, 'residential', 'leased', 160, [('2026-08-01', 160, '2026-08-25', 'تحويل')], [], None, '2026-01-01', None),
    ('22', 'شقة', 2, 2, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-06', 'شيك')], [], None, '2026-01-01', None),
    ('23', 'شقة', 2, 3, 'residential', 'leased', 230, [('2026-08-01', 230, '2026-08-26', 'تحويل')], [], None, '2026-01-01', None),
    ('24', 'شقة', 2, 4, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-24', 'تحويل')], [], None, '2026-01-01', None),
    ('25', 'شقة', 2, 5, 'residential', 'leased', 250, [('2026-08-01', 250, '2026-08-06', 'شيك')], [], None, '2026-01-01', None),
    ('31', 'شقة', 3, 1, 'residential', 'leased', 160, [('2026-08-01', 160, '2026-08-26', 'تحويل')], [], None, '2026-01-01', None),
    ('32', 'شقة', 3, 2, 'residential', 'leased', 260, [], ['2026-08-01'], None, '2026-01-01', None),
    ('33', 'شقة', 3, 3, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-24', 'تحويل')], [], None, '2026-01-01', None),
    ('34', 'شقة', 3, 4, 'residential', 'leased', 250, [('2026-08-01', 250, '2026-08-03', 'شيك')], [], None, '2026-01-01', None),
    ('35', 'شقة', 3, 5, 'residential', 'leased', 230, [('2026-08-01', 230, '2026-08-23', 'تحويل')], [], None, '2026-01-01', None),
    ('41', 'شقة', 4, 1, 'residential', 'leased', 180, [('2026-08-01', 180, '2026-09-01', 'تحويل')], [], None, '2026-01-01', None),
    ('42', 'شقة', 4, 2, 'residential', 'leased', 260, [], ['2026-02-01', '2026-08-01'], None, '2026-01-01', None),
    ('43', 'شقة', 4, 3, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-10', 'شيك')], [], None, '2026-01-01', None),
    ('44', 'شقة', 4, 4, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-16', 'شيك')], [], None, '2026-01-01', None),
    ('45', 'شقة', 4, 5, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-06', 'شيك')], [], None, '2026-01-01', None),
    ('51', 'شقة', 5, 1, 'residential', 'leased', 200, [('2026-08-01', 200, '2026-08-01', 'تحويل')], [], None, '2026-01-01', None),
    ('52', 'شقة', 5, 2, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-03', 'شيك')], [], None, '2026-01-01', None),
    ('53', 'شقة', 5, 3, 'residential', 'leased', 250, [('2026-08-01', 250, '2026-08-25', 'تحويل')], [], None, '2026-01-01', None),
    ('54', 'شقة', 5, 4, 'residential', 'leased', 230, [('2026-08-01', 230, '2026-08-18', 'شيك')], [], None, '2026-01-01', None),
    ('55', 'شقة', 5, 5, 'residential', 'leased', 160, [('2026-08-01', 160, '2026-08-02', 'شيك')], [], None, '2026-01-01', None),
    ('61', 'شقة', 6, 1, 'residential', 'leased', 180, [], ['2026-07-01', '2026-08-01'], None, '2026-01-01', None),
    ('62', 'شقة', 6, 2, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-05', 'شيك')], [], None, '2026-01-01', None),
    ('63', 'شقة', 6, 3, 'residential', 'leased', 260, [('2026-07-01', 260, '2026-08-16', 'شيك'), ('2026-08-01', 260, '2026-09-16', 'تحويل')], [], None, '2026-01-01', None),
    ('64', 'شقة', 6, 4, 'residential', 'leased', 260, [('2026-08-01', 260, '2026-08-29', 'تحويل')], [], None, '2026-01-01', None),
    ('65', 'شقة', 6, 5, 'residential', 'leased', 200, [('2026-08-01', 200, '2026-09-09', 'تحويل')], [], None, '2026-01-01', None),
    ('M4', 'مكتب 4', 0, 1, 'commercial', 'leased', 200, [('2026-07-01', 200, '2026-09-01', 'تحويل')], ['2026-08-01'], None, '2026-01-01', 'دفع إيجار 2026/7 ولم يدفع 2026/8'),
    ('M5', 'مكتب 5', 0, 2, 'commercial', 'leased', 330, [], ['2025-12-01', '2026-01-01', '2026-02-01', '2026-03-01', '2026-04-01', '2026-05-01', '2026-06-01', '2026-07-01', '2026-08-01'], None, '2025-12-01', 'لم يدفع من 2025/12 إلى 2026/08'),
    ('M6', 'مكتب 6', 0, 3, 'commercial', 'leased', 450, [('2026-08-01', 450, '2026-08-25', 'شيك')], [], None, '2026-01-01', None),
    ('S1', 'محل 1', 0, 4, 'commercial', 'leased', 150, [('2026-08-01', 150, '2026-08-03', 'شيك')], [], None, '2026-01-01', None),
    ('S2', 'محل 2', 0, 5, 'commercial', 'vacant', 0, [], [], None, None, 'شاغر'),
    ('S3', 'محل 3', 0, 6, 'commercial', 'reserved', 200, [], [], None, '2026-09-01', 'محجوز — يبدأ العقد 2026/09/01 (سماح فترة تجهيز)'),
    ('SDG', 'محل D/G', 0, 7, 'commercial', 'reserved', 900, [], [], None, '2026-10-01', 'محجوز — يبدأ العقد 2026/10/01 (سماح فترة تجهيز)'),
    ('SZ', 'محل Z', 0, 8, 'commercial', 'leased', 500, [('2026-08-01', 500, '2026-09-14', 'تحويل')], [], None, '2026-01-01', None),
    ('SH', 'محل H', 0, 9, 'commercial', 'leased', 800, [('2026-08-01', 800, '2026-08-02', 'شيك')], [], None, '2026-01-01', None),
    ('SW', 'محل W', 0, 10, 'commercial', 'leased', 400, [('2026-08-01', 400, '2026-09-04', 'تحويل')], [], None, '2026-01-01', 'محل الخوير — 400 ر.ع شهريًا'),
    ('BA', 'القبو A', -1, 1, 'commercial', 'vacant', 0, [], [], None, None, 'شاغر'),
    ('BB', 'القبو B', -1, 2, 'commercial', 'leased', 250, [], ['2026-08-01'], 'جمعية الاستقامة الخيرية — مخزن', '2026-01-01', 'مخزن الجمعية؛ لم يُسجَّل تحصيل في أغسطس'),
],
        # workbook: (tower, floor, unit, area m², lessee, monthly rent year 1, year 2, year 3, parking spaces)
        "wb_units": [
    (1, 7, '701', 132, None, 0, 0, 0, 0),
    (1, 7, '702', 99, None, 0, 0, 0, 0),
    (1, 7, '703', 55, 'Dineshcandra Agrawal Infra LLC', 655, 780, 0, 2),
    (1, 7, '704', 54, None, 0, 0, 0, 0),
    (1, 7, '705', 54, None, 0, 0, 0, 0),
    (1, 7, '706', 53, None, 0, 0, 0, 0),
    (1, 7, '707', 165, 'Nari Technology LTD', 950, 1060, 0, 5),
    (1, 7, '708', 116, None, 0, 0, 0, 0),
    (1, 7, '709', 80, 'Itizan International Capital LLC', 450, 600, 0, 1),
    (1, 7, '710', 52, None, 0, 0, 0, 0),
    (1, 7, '711', 51, None, 0, 0, 0, 0),
    (1, 7, '712', 51, None, 0, 0, 0, 0),
    (1, 7, '713', 51, None, 0, 0, 0, 0),
    (1, 7, '714', 51, None, 0, 0, 0, 0),
    (1, 7, '715', 51, None, 0, 0, 0, 0),
    (1, 7, '716', 52, None, 0, 0, 0, 0),
    (1, 7, '717', 52, None, 0, 0, 0, 0),
    (1, 7, '718', 114, None, 0, 0, 0, 0),
    (2, 0, '114', 70, 'Laqtah Projects for Businesses and Photography', 385, 735, 0, 1),
    (2, 0, '115', 52, None, 0, 0, 0, 0),
    (2, 0, '116', 63, None, 0, 0, 0, 0),
    (2, 0, '117', 64, None, 0, 0, 0, 0),
    (2, 2, '220', 110, None, 0, 0, 0, 0),
    (2, 2, '221', 103, None, 0, 0, 0, 0),
    (2, 3, '330', 205, 'Al Bahar Trading Business Agency SPC', 900, 1200, 1400, 4),
    (2, 4, '419', 147, 'شركة الحصين الدولية', 810, 1180, 0, 3),
    (2, 4, '433', 62, None, 0, 0, 0, 0),
    (2, 4, '434', 131, 'Distinctive Edge Business Projects SPC', 762, 1050, 0, 2),
    (2, 5, '519', 147, 'Apex One Services LLC', 885, 1180, 0, 3),
],
        "sad_shops": 9,
        "assets": [("almaqsura/almaqsura-logo.png", "brand", "logo", None, None, None, 0)],
        "pilot_accounts": [
            ("mq-ceo", "المدير العام — المقصورة العقارية", "admin", None),
            ("mq-sales", "التسويق والوساطة العقارية", "sales", None),
            ("mq-finance", "المالية والتحصيل", "finance", None),
            ("mq-engineer", "الاستشارات الهندسية والإشراف", "engineer", None),
        ],
    },
    "view": {
        "display": "رؤية العقارية",
        "seed": 2014,
        # 0.19.0 — REAL data only, an off-plan (sell-on-the-map) developer. Source: viewom.com (the About page and the six project pages),
        # collected 2026-10-28 in `view-realestate-mabaneek-data.md`. Published per project: location, coordinates, year, floors, total
        # units, the unit mix, sold % and a "status" % (read as construction progress until the company confirms). NOT published: unit
        # numbers, areas, prices, payment plans, handover dates, buyers, contractors — they stay NULL / "not supplied". Unit codes are
        # system placeholders (`VHT-O-01`), the sold count is the published % applied to the unit total (rounded, never up to sold-out
        # unless the site says 100 %), and which placeholder is sold is arbitrary until the sales ledger arrives.
        "real_only": True,
        "brand": {"name": "رؤية للتطوير العقاري (View Real Estate Development)", "address": "مسقط، سلطنة عُمان", "phone": "+968 9756 6600",
                  "email": "", "signatory": "", "signatory_title": "المؤسس والرئيس التنفيذي"},
        # code, name, location, kind, construction % (the site's "status"), sold units (see above), built year, floors, [(type, count, use)]
        "real_sales": [
            ("BRK", "واجهة بركاء", "بركاء", "tower", 100, 53, 2023, None, [("مكتب", 45, "commercial"), ("محل تجاري", 8, "commercial")]),
            ("SLH", "صلالة هيلز", "صلالة", "tower", 40, 29, 2025, 5, [("شقة", 24, "residential"), ("محل تجاري", 13, "commercial"), ("وحدة (النوع غير مزوَّد)", 1, "residential")]),
            ("KYN", "كيان", "الموالح، مسقط", "tower", 40, 29, 2025, 5, [("شقة", 24, "residential"), ("محل تجاري", 13, "commercial"), ("وحدة (النوع غير مزوَّد)", 1, "residential")]),
            ("VHT", "فيوو هايتس", "بوشر، مسقط", "tower", 10, 9, 2026, 9, [("مكتب", 45, "commercial"), ("صالة عرض", 1, "commercial")]),
            ("VBZ", "فيوو بازار", "قرب بركاء", "tower", 95, 25, 2025, 1, [("محل تجاري", 32, "commercial"), ("صالة عرض", 1, "commercial"), ("وحدة (النوع غير مزوَّد)", 1, "commercial")]),
            ("VGD", "فيوو جاردنس", "الموالح، مسقط", "tower", 70, 55, 2025, 5, [("شقة", 45, "residential"), ("محل تجاري", 11, "commercial")]),
        ],
        "projects": [("BRK", "BRK", "واجهة بركاء", "بركاء", "tower", 100, 0, 0, "0"), ("SLH", "SLH", "صلالة هيلز", "صلالة", "tower", 40, 0, 0, "0"),
                     ("KYN", "KYN", "كيان", "الموالح، مسقط", "tower", 40, 0, 0, "0"), ("VHT", "VHT", "فيوو هايتس", "بوشر، مسقط", "tower", 10, 0, 0, "0"),
                     ("VBZ", "VBZ", "فيوو بازار", "قرب بركاء", "tower", 95, 0, 0, "0"), ("VGD", "VGD", "فيوو جاردنس", "الموالح، مسقط", "tower", 70, 0, 0, "0")],
        "assets": [("view/view-logo.png", "brand", "logo", None, None, None, 0),
                   ("view/barka-render.jpg", "BRK", "render", "واجهة بركاء — التصور المنشور على موقع الشركة", None, None, 1),
                   ("view/salalah-hills-render.jpg", "SLH", "render", "صلالة هيلز — التصور المنشور على موقع الشركة", None, None, 1),
                   ("view/kayan-render.jpg", "KYN", "render", "كيان — التصور المنشور على موقع الشركة", None, None, 1),
                   ("view/view-heights-render.jpg", "VHT", "render", "فيوو هايتس — التصور المنشور على موقع الشركة", None, None, 1),
                   ("view/view-bazaar-render.jpg", "VBZ", "render", "فيوو بازار — التصور المنشور على موقع الشركة", None, None, 1),
                   ("view/view-gardens-render.jpg", "VGD", "render", "فيوو جاردنس — التصور المنشور على موقع الشركة", None, None, 1)],
        "pilot_accounts": [
            ("vw-ceo", "الرئيس التنفيذي — رؤية العقارية", "admin", None),
            ("vw-sales", "المبيعات والحجوزات", "sales", None),
            ("vw-finance", "المالية والتحصيل", "finance", None),
            ("vw-engineer", "المشاريع والإنشاء", "engineer", None),
        ],
    },
    "almukhatat": {
        "display": "المخطط العقارية",
        "seed": 2010,
        "org_demo": {"seed": 7102},  # 0.29.0: see above
        "brand": {"name": "شركة المخطط العقارية", "address": "المعبيلة الجنوبية، محافظة مسقط، سلطنة عُمان", "phone": "72700099",
                  "email": "contact@almukhatat.com", "signatory": "", "signatory_title": "رئيس مجلس الإدارة والرئيس التنفيذي"},
        # slot, code, name, location, kind, build %, planned monthly sales, handover (months from today), escrow balance (illustrative)
        "projects": [
            ("RAY", "MAB", "مشروع مآب", "الخوض — شارع جامعة السلطان قابوس", "tower", 58, 5, 10, "200000"),
            ("SEB", "MRT", "مشروع مرتيل", "المعبيلة الجنوبية — شارع نستو", "tower", 34, 4, 18, "150000"),
            ("KHD", "JWR", "مساكن جوار", "الموالح الجنوبية", "villa", 90, 3, 4, "80000"),
            ("MLZ", "MLZ", "مشروع ملاذ", "المعبيلة — شارع النزهة", "tower", 46, 4, 12, "120000"),
        ],
        # buildings: slot, building, floors (first, last), per-floor specs, floor uplift, sold probability by view
        "buildings": [
            ("RAY", "A", (0, 0), _MAAB_SHOPS, 0, {"شارع الجامعة": .5}),
            ("RAY", "A", (1, 7), _MAAB_FLOOR, .012, {"جبلي": .72, "شارع الجامعة": .6, "داخلي": .48}),
            ("SEB", "M", (0, 0), _MRT_SHOPS, 0, {"شارع نستو": .45}),
            ("SEB", "M", (1, 2), _MRT_OFF, .01, {"شارع نستو": .3, "داخلي": .22}),
            ("SEB", "M", (3, 7), _MRT_RES, .012, {"شارع نستو": .4, "داخلي": .3}),
            ("MLZ", "L", (1, 12), _MLZ_FLOOR, .01, {"الحديقة": .55, "شارع النزهة": .5, "داخلي": .42}),
        ],
        # villas: slot, building, count, (type, area, base price) by rule, views by position
        "villas": {"slot": "KHD", "building": "V", "count": 40,
                   "types": [("فيلا 3 غرف — 200 م²", 200, 98000), ("فيلا 4 غرف — 240 م²", 240, 118000)],
                   "views": {"زاوية": .85, "قرب المسجد": .78, "داخلية": .62}},
        "interests": {"RAY": ["نموذج 01 غرفتان وصالة", "شقة فندقية للاستثمار", "محل على شارع الجامعة", "عائد إيجاري"],
                      "SEB": ["مكتب 50 م²", "شقة 61 م²", "محل على شارع نستو", "مكتب بمدخل مستقل"],
                      "KHD": ["فيلا زاوية", "فيلا 4 غرف", "تمويل من بنك نزوى"],
                      "MLZ": ["نموذج 1 ثلاث غرف", "غرفة وصالة قرب مسقط مول", "شقة فندقية"]},
        "lead_mix": ["RAY", "RAY", "MLZ", "SEB", "KHD"],
        "cycle_names": {"AMR": ("مركز داود للأعمال", "الخوض السابعة"), "QRM": ("مساكن الفخامة 11", "بوشر")},
        # bundled sample assets → plans (kind, title, building, floor, unit_type, public) or brand logo
        "assets": [
            ("almukhatat/almukhatat-logo.png", "brand", "logo", None, None, None, 0),
            ("almukhatat/maab-site-map.jpg", "RAY", "site", "موقع المشروع — الخوض، شارع الجامعة", None, None, 1),
            ("almukhatat/maab-nearby.jpg", "RAY", "site", "المواقع القريبة (طريق مسقط السريع، جامعة السلطان قابوس، البندر لولو)", None, None, 1),
            ("almukhatat/maab-plan-shops-ground.jpg", "RAY", "floor", "مخطط المحلات التجارية — الطابق الأرضي", "A", 0, 1),
            ("almukhatat/maab-plan-typical-floor.jpg", "RAY", "floor", "مخطط الطابق المتكرر", "A", 1, 1),
            ("almukhatat/maab-plan-unit-01.jpg", "RAY", "unit", "نموذج الوحدة 01 — 97.70 م²", "A", None, "نموذج 01 — غرفتان وصالة", 1),
            ("almukhatat/maab-plan-units-02-03.jpg", "RAY", "unit", "نموذجا الوحدة 02 و03 — 67.10 و63.60 م²", "A", None, "نموذج 02 — غرفة وصالة", 1),
            ("almukhatat/maab-plan-units-04-05.jpg", "RAY", "unit", "نموذجا الوحدة 04 و05 — 67.00 و62.60 م²", "A", None, "نموذج 04 — غرفة وصالة", 1),
            ("almukhatat/maab-brochure-cover.jpg", "RAY", "render", "التصور النهائي للمبنى (غلاف الكتيّب)", None, None, 1),
            ("almukhatat/maab-render-01.jpg", "RAY", "render", "مآب — وجهة عصرية وفرصة استثمارية", None, None, 1),
            ("almukhatat/maab-render-02.jpg", "RAY", "render", "التصور النهائي — الواجهة الجبلية", None, None, 1),
            ("almukhatat/maab-render-03.jpg", "RAY", "render", "التصور النهائي — المدخل والمحلات", None, None, 1),
            ("almukhatat/maab-interior-living.jpg", "RAY", "render", "تصور داخلي — الصالة", None, None, 1),
            ("almukhatat/maab-interior-bedroom.jpg", "RAY", "render", "تصور داخلي — غرفة النوم", None, None, 1),
            ("almukhatat/maab-interior-kitchen-dining.jpg", "RAY", "render", "تصور داخلي — المطبخ وركن الطعام", None, None, 1),
            ("almukhatat/maab-interior-salon.jpg", "RAY", "render", "تصور داخلي — غرفة المعيشة بتشطيب فندقي", None, None, 1),
            ("almukhatat/maab-interior-kitchen.jpg", "RAY", "render", "تصور داخلي — المطبخ", None, None, 1),
            ("almukhatat/maab-interior-gym.jpg", "RAY", "render", "الصالة الرياضية", None, None, 1),
            ("almukhatat/maab-amenities.jpg", "RAY", "render", "الخدمات: صالة رياضية، بركة سباحة، صالة ألعاب أطفال", None, None, 1),
            ("almukhatat/malath-render-banner.jpg", "MLZ", "render", "مشروع ملاذ — استثمار في سكن المستقبل", None, None, 1),
            ("almukhatat/malath-interior-bedroom.jpg", "MLZ", "render", "تصور داخلي — غرفة النوم", None, None, 1),
        ],
        # 0.14.0 — trial accounts for the company's own people: (username, display name, role, customer link). Created at start-up
        # ONLY when MABANIQ_PILOT_PASSWORD is set (a temporary password, forced to change at first sign-in); never overwritten afterwards.
        "pilot_accounts": [
            ("dawood", "د. داود الهنائي", "admin", None),
            ("mk-sales", "فريق المبيعات", "sales", None),
            ("mk-finance", "المالية والتحصيل", "finance", None),
            ("mk-engineer", "الهندسة والإنشاء", "engineer", None),
            ("mk-client", "عميل تجريبي — محل في مآب", "customer", "client1"),
            ("mk-hr", "مسؤولة الموارد البشرية", "hr", "emp:hr"),
            ("mk-payroll", "مسؤول الرواتب", "payroll", None),
            ("mk-pm", "مدير عقاري خارجي", "property_manager", None),
            ("mk-accountant", "المحاسبة", "accountant", None),
            ("mk-employee", "مدير المبيعات والتسويق (بوابة الموظف)", "employee", "emp:smgr"),
        ],
        # markers on the typical floor plan (percent of the image, approximate — illustrative placement of floor-1 units)
        "markers": {"almukhatat/maab-plan-typical-floor.jpg": [("MAB-A-101", 64, 48), ("MAB-A-102", 62, 18), ("MAB-A-103", 24, 78),
                                                             ("MAB-A-104", 24, 20), ("MAB-A-105", 62, 80), ("MAB-A-106", 45, 82)]},
    },
}


def profile(tenant: str) -> dict | None:
    return PROFILES.get(tenant)


def profile_units(p: dict) -> list[tuple]:
    """→ [(slot, unit code, building, floor, pos, type, area, view, price, sold probability)] in the seed's tuple shape."""
    if p.get("real_only"):
        return [t[:11] for t in _unit_tuples(p)]
    code_of = {slot: code for slot, code, *_ in p["projects"]}
    units = []
    for slot, bld, (f0, f1), specs, uplift, sold in p.get("buildings", []):
        code = code_of[slot]
        for f in range(f0, f1 + 1):
            for pos, (tp, ar, vw, ppm, use) in enumerate(specs, 1):
                units.append((slot, f"{code}-{bld}-{f}{pos:02d}", bld, f, pos, tp, ar, vw, ppm * ar * (1 + f * uplift), sold[vw], use))
    v = p.get("villas")
    if v:
        code = code_of[v["slot"]]
        views = list(v["views"].items())
        for i in range(1, v["count"] + 1):
            tp, ar, base = v["types"][0] if i % 3 else v["types"][1]
            vw, ps = views[0] if i % 5 in (1, 0) else views[1] if v["count"] // 3 <= i <= 2 * v["count"] // 3 else views[2]
            units.append((v["slot"], f"{code}-{v['building']}-{i:03d}", v["building"], 0, i, tp, ar, vw,
                          base * (1.06 if vw == views[0][0] else 1.03 if vw == views[1][0] else 1), ps, "residential"))
    return units


def lease_units(p: dict | None) -> set[str]:
    """0.15.0 — unit codes a profile keeps for leasing: they are seeded *available* (never sold) and marked `retained`."""
    return {u for u, *_ in (p or {}).get("leases", [])}


def seed_leases(c, p: dict, rnd, today) -> int:
    """0.15.0 — materialise the profile's retained units and their leases (lessee, annual rent, dues by frequency, arrears flag).
    Returns the number of leases created. Mirrors the generic demo's shape so `/api/leasing` and the rent reports work unchanged."""
    import datetime as dt

    def _m(d, months):
        y, mo = divmod(d.month - 1 + months, 12)
        return dt.date(d.year + y, mo + 1, min(d.day, 28))
    n = 0
    for code, lessee, rent, freq, start_m, arrears in p.get("leases", []):
        u = c.execute("SELECT id FROM units WHERE code=?", (code,)).fetchone()
        if not u:
            continue
        c.execute("UPDATE units SET retained=1, status='a' WHERE id=?", (u["id"],))
        if not lessee:
            continue
        tid = c.execute("INSERT INTO tenants_l(name,phone,id_number) VALUES(?,?,?)",
                        (lessee, f"+968 9{rnd.randint(1000000, 9999999)}", str(rnd.randint(10000000, 99999999)))).lastrowid
        start = _m(today, start_m)
        end = _m(start, 12) - dt.timedelta(days=1)
        lid = c.execute("INSERT INTO leases(unit_id,tenant_id,start,\"end\",annual_rent,frequency,deposit,status,municipality_ref) VALUES(?,?,?,?,?,?,?,?,?)",
                        (u["id"], tid, start.isoformat(), end.isoformat(), rent, freq, rent / 12, "active", f"MCT-L-{rnd.randint(100000, 999999)}")).lastrowid
        step = 12 // freq
        past = [i for i in range(freq) if _m(start, i * step) <= today]
        for q in range(freq):
            due = _m(start, q * step)
            unpaid = bool(arrears) and past and q == past[-1]  # the arrears flag leaves the latest due instalment unpaid
            paid = rent / freq if due <= today and not unpaid else 0
            c.execute("INSERT INTO rent_dues(lease_id,due,amount,paid,paid_date) VALUES(?,?,?,?,?)",
                      (lid, due.isoformat(), rent / freq, paid, due.isoformat() if paid else None))
        n += 1
    return n


def _unit_tuples(p: dict) -> list[tuple]:
    """Real-data profiles: (slot, code, building, floor, pos, type, area, view, price, sold_p, use, retained, status, lease) for every unit."""
    out = []
    if p.get("real_sales"):  # 0.19.0 — off-plan developer: placeholders per published unit mix, sold count from the published %
        for code, _n, _l, _k, _b, sold, _y, _f, groups in p["real_sales"]:
            typed = [(tp, n, use) for tp, n, use in groups if "غير مزوَّد" not in tp]
            total = sum(n for _tp, n, _u in typed)
            quota = {tp: sold * n / total for tp, n, _u in typed}  # proportional split, largest remainder
            take = {tp: int(q) for tp, q in quota.items()}
            for tp in sorted(quota, key=lambda t: quota[t] - take[t], reverse=True)[:sold - sum(take.values())]:
                take[tp] += 1
            letter = {"مكتب": "O", "محل تجاري": "S", "شقة": "A", "صالة عرض": "H"}
            pos = 0
            for tp, n, use in groups:
                for i in range(1, n + 1):
                    pos += 1
                    st = "s" if i <= take.get(tp, 0) else "a"
                    out.append((code, f"{code}-{letter.get(tp, 'X')}-{i:02d}", "A", None, pos, tp, None, None, None, 0, use, 0, st, None))
        return out
    for u, tp, fl, pos, use, st, rent, paid, unpaid, lessee, start, note in p.get("ist_units", []):
        lease = None if st == "vacant" else {"lessee": lessee or f"مستأجر الوحدة {tp if tp != 'شقة' else u} (الاسم غير مزوَّد)", "monthly": rent,
                                                "start": start, "end": "2027-06-30", "paid": paid, "unpaid": unpaid, "note": note}
        out.append(("IST", f"IST-A-{u}", "A", fl, pos, tp, None, "شارع المها", None, 0, use, 1, "a", lease))
    for tower, fl, u, area, lessee, y1, y2, y3, parking in p.get("wb_units", []):
        lease = {"lessee": lessee, "monthly": y1, "start": "2026-01-01", "end": "2027-12-31", "paid": [], "unpaid": [],
                 "note": f"إيجار السنة الثانية {y2} ر.ع/شهر" + (f"، الثالثة {y3}" if y3 else "") + f"؛ مواقف: {parking}"} if lessee else None
        out.append(("MQT", f"MQT-T{tower}-{u}", f"T{tower}", fl, int(u[-2:]) if u[-2:].isdigit() else 1, "وحدة تجارية (مكتب)", area, "البرج " + str(tower), None, 0, "commercial", 1, "a", lease))
    for i in range(1, int(p.get("sad_shops", 0)) + 1):
        out.append(("SAD", f"SAD-S-{i:02d}", "S", 0, i, "محل تجاري", None, "سوق السد", None, 0, "commercial", 1, "a", None))
    out.append(("AZB", "AZB-L-01", "L", 0, 1, "قطعة أرض — للبيع", None, "العذيبة", None, 0, "land", 0, "a", None))
    return out


def seed_real(c, p: dict, tenant: str) -> None:
    """0.18.1 — real-data-only tenant: projects, units, leases and rent dues exactly as documented; staff accounts; letterhead; no demo
    buyers, leads, contractors, cost schedules or cycle projects. Dues exist only for documented months (the August-2026 report) and from
    the import month onward; undocumented months are neither invented as paid nor shown as arrears."""
    import datetime as dt

    from .auth import ensure_users
    from .seed_ext import SETTINGS
    today = dt.date.today()
    for k, v in SETTINGS.items():
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))
    pid = {}
    real_projects = p.get("real_projects") or [(code, name, loc, kind, b, 0, None, 1 if b >= 100 else 0)
                                               for code, name, loc, kind, b, _s, _y, _f, _g in p["real_sales"]]
    for code, name, loc, kind, b, pl, ho, completed in real_projects:
        pid[code] = c.execute("INSERT INTO projects(code,name,location,kind,build_pct,planned_monthly_sales,handover,completed) VALUES(?,?,?,?,?,?,?,?)",
                              (code, name, loc, kind, b, pl, ho, completed)).lastrowid
    for slot, code, bld, fl, pos, tp, area, vw, price, _sp, use, retained, st, lease in _unit_tuples(p):
        uid = c.execute("INSERT INTO units(project_id,code,building,floor,pos,type,area,view,price,status,use,retained) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid[slot], code, bld, fl, pos, tp, area, vw, price, st, use, retained)).lastrowid
        if not lease:
            continue
        tid = c.execute("INSERT INTO tenants_l(name,phone,id_number) VALUES(?,?,?)", (lease["lessee"], "", "")).lastrowid
        start = dt.date.fromisoformat(lease["start"])
        lid = c.execute("INSERT INTO leases(unit_id,tenant_id,start,\"end\",annual_rent,frequency,deposit,status,municipality_ref) VALUES(?,?,?,?,?,?,?,?,?)",
                        (uid, tid, lease["start"], lease["end"], lease["monthly"] * 12, 12, 0, "active", lease.get("note") or "")).lastrowid
        seen = set()
        for due, amount, paid_on, _method in lease["paid"]:
            c.execute("INSERT INTO rent_dues(lease_id,due,amount,paid,paid_date) VALUES(?,?,?,?,?)", (lid, due, amount, amount, paid_on))
            seen.add(due)
        for due in lease["unpaid"]:
            c.execute("INSERT INTO rent_dues(lease_id,due,amount,paid,paid_date) VALUES(?,?,?,?,?)", (lid, due, lease["monthly"], 0, None))
            seen.add(due)
        # from the month after the import forward, one due per month until the end of the lease (nothing is assumed about earlier months)
        y, m = today.year, today.month
        end = dt.date.fromisoformat(lease["end"])
        first = max(start, dt.date(y + (m // 12), m % 12 + 1, 1))
        d = first
        while d <= end:
            if d.isoformat() not in seen:
                c.execute("INSERT INTO rent_dues(lease_id,due,amount,paid,paid_date) VALUES(?,?,?,?,?)", (lid, d.isoformat(), lease["monthly"], 0, None))
            d = dt.date(d.year + (d.month // 12), d.month % 12 + 1, 1)
    apply_brand(c, p)
    c.commit()
    ensure_users(c, [], [])
    ensure_assets(c, tenant, p)
    ensure_pilot_accounts(c, tenant)
    c.commit()


def apply_brand(c, p: dict) -> None:
    for k, v in p.get("brand", {}).items():
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"brand:{k}", v))
    c.execute("INSERT OR REPLACE INTO settings VALUES('tenant_name',?)", (json.dumps(p["display"], ensure_ascii=False),))


def ensure_assets(c, tenant: str, p: dict | None = None) -> int:
    """Materialise the profile's bundled sample images as validated documents (+ plans / letterhead logo). Idempotent and
    self-healing: runs at every start-up, so an ephemeral container (Railway without a volume) gets its files back after a
    redeploy, and a database seeded earlier gains assets added later. Returns the number of files written."""
    from .modules2 import _docs_dir
    p = p or profile(tenant)
    if not p or not p.get("assets"):
        return 0
    if type(c).__name__ == "PgConn":
        c.execute("SELECT pg_advisory_xact_lock(7340128)")  # several uvicorn workers start together — one materialises, the rest find it
    proj = {r["code"]: r["id"] for r in c.execute("SELECT id, code FROM projects").fetchall()}
    code_of = {slot: code for slot, code, *_ in p["projects"]}
    code_of.setdefault("AMR", "AMR")  # 0.15.0: the cycle seed's launch / completed projects may carry assets too
    code_of.setdefault("QRM", "QRM")
    written = 0
    by_rel: dict[str, int] = {}
    for entry in p["assets"]:  # (file, slot|brand, kind, title, building, floor[, unit_type], public)
        rel, slot, kind, title, bld, fl = entry[:6]
        unit_type, public = (entry[6], entry[7]) if len(entry) == 8 else (None, entry[6])
        if kind == "logo":
            unit_type, public = None, 0
        src = ASSETS / rel
        if not src.exists():
            continue
        data = src.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        ext = ".png" if data.startswith(b"\x89PNG") else ".jpg"
        mime = "image/png" if ext == ".png" else "image/jpeg"
        ref_type = "brand" if slot == "brand" else "plan"
        ref_id = 0 if slot == "brand" else proj.get(code_of.get(slot, ""), 0)
        if not ref_id and slot != "brand":
            continue
        row = c.execute("SELECT id, stored FROM documents WHERE sha256=? AND ref_type=? AND ref_id=?", (sha, ref_type, ref_id)).fetchone()
        if row:
            did, stored = row["id"], row["stored"]
        else:
            stored = "sample-" + sha[:24] + ext
            did = c.execute("INSERT INTO documents(ref_type,ref_id,title,category,filename,mime,size,sha256,stored,uploaded_by,at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (ref_type, ref_id, title or "شعار المطوّر", "الهوية" if slot == "brand" else kind, Path(rel).name, mime, len(data), sha, stored,
                             "عيّنة المنصة", "1970-01-01 00:00")).lastrowid
        dest = _docs_dir() / stored
        if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest() != sha:
            dest.write_bytes(data)
            written += 1
        by_rel[rel] = did
        if slot == "brand":
            c.execute("INSERT OR REPLACE INTO settings VALUES('brand:logo_doc',?)", (str(did),))
        elif not c.execute("SELECT 1 FROM plans WHERE document_id=?", (did,)).fetchone():
            c.execute("INSERT INTO plans(project_id,building,floor,unit_type,kind,title,document_id,markers,public,created,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (ref_id, bld, fl, unit_type, kind, title, did, "[]", 1 if public else 0, "1970-01-01 00:00", "عيّنة المنصة"))
    for rel, marks in p.get("markers", {}).items():
        did = by_rel.get(rel)
        if not did:
            continue
        known = {r["code"] for r in c.execute("SELECT code FROM units").fetchall()}
        ms = [{"unit_code": u, "x": x, "y": y} for u, x, y in marks if u in known]
        c.execute("UPDATE plans SET markers=? WHERE document_id=? AND markers='[]'", (json.dumps(ms, ensure_ascii=False), did))
    c.commit()
    return written


__all__ = ["PROFILES", "ASSETS", "profile", "profile_units", "apply_brand", "ensure_assets", "tenants_from_env", "lease_units", "seed_real", "seed_leases"]


def ensure_pilot_accounts(c, tenant: str) -> int:
    """0.14.0 — creates the profile's trial accounts (see `pilot_accounts`) with the temporary password from
    `MABANIQ_PILOT_PASSWORD`. Missing variable (or one shorter than 12 characters) ⟵ nothing is created. An existing account is left
    untouched, so a password the person has already changed is never reset. Returns the number of accounts created."""
    p = profile(tenant)
    pw = os.environ.get("MABANIQ_PILOT_PASSWORD", "")
    if not p or not p.get("pilot_accounts") or len(pw) < 12:
        return 0
    from .auth import hash_pw
    n = 0
    for un, name, role, link in p["pilot_accounts"]:
        if c.execute("SELECT 1 FROM users WHERE username=?", (un,)).fetchone():
            continue
        cust = emp = None
        if link and link.startswith("emp:"):   # 0.29.0 — a staff login that is also an employee: the file is found by the profile's own list (backend/seed_org_data.py)
            from .seed_org_data import ORGS
            row = next((e for e in ORGS.get(tenant, {}).get("employees", []) if e[0] == link[4:]), None)
            r = c.execute("SELECT id FROM employees WHERE name=?", (row[1],)).fetchone() if row and c.has_table("employees") else None
            if not r or c.execute("SELECT 1 FROM users WHERE employee_id=?", (r["id"],)).fetchone():
                continue  # the people file is filled by the org-demo phase (a few seconds after start-up): the next start-up links it
            emp = r["id"]
        elif link:
            r = c.execute("SELECT customer_id FROM users WHERE username=?", (link,)).fetchone()
            if not r or not r["customer_id"]:
                continue  # the linked demo customer does not exist (yet): try again at the next start-up
            cust = r["customer_id"]
        uid = c.execute("INSERT INTO users(username,name,role,pw,customer_id,employee_id,must_change) VALUES(?,?,?,?,?,?,1)", (un, name, role, hash_pw(pw), cust, emp)).lastrowid
        n += 1
        if role == "property_manager" and c.has_table("user_scopes"):   # 0.29.0 — a property manager sees only the portfolio inside their scope: give the trial login the project that has most leases
            try:
                pr = c.execute("SELECT u.project_id pj FROM leases l JOIN units u ON u.id=l.unit_id GROUP BY u.project_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
            except Exception:  # noqa: BLE001 — a tenant without the leasing tables simply has nothing to scope
                pr = None
            if pr and not c.execute("SELECT 1 FROM user_scopes WHERE user_id=?", (uid,)).fetchone():
                c.execute("INSERT INTO user_scopes(user_id,project_id,owner_id,created_by) VALUES(?,?,NULL,?)", (uid, pr["pj"], "تهيئة حسابات التجربة"))
    if n:
        c.commit()
    return n
