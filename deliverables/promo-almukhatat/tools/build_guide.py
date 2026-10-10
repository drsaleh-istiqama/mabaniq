# -*- coding: utf-8 -*-
"""بناء حزمة الدليل الترويجي «مبانيك لشركة المخطط العقارية»: دليل PDF (A4)، عرض تقديمي PDF (16:9)، ونسخة HTML تفاعلية.

    python deliverables/promo-almukhatat/tools/build_guide.py

كل النص عربي مركَّب برمجيًا (fpdf2 + HarfBuzz، خط Tajawal المضمَّن في المنصة)؛ لا كلمة عربية من نموذج صور. الصور كلها لقطات شاشة
من المنصة (screens/) أو مستندات صادرة منها (docs/preview، ads/) أو عيّنات الشركة المرفقة في المستودع.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import sys
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from hijridate import Gregorian
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PKG = HERE.parent
ROOT = PKG.parents[1]
FONTS = ROOT / "backend" / "assets" / "fonts"
SAMPLES = ROOT / "backend" / "assets" / "samples" / "almukhatat"
SCREENS, DOCPREV, ADS = PKG / "screens", PKG / "docs" / "preview", PKG / "ads"
TMP = PKG / "tools" / "_crops"
TMP.mkdir(exist_ok=True)

TODAY = dt.date(2026, 10, 11)
_h = Gregorian(TODAY.year, TODAY.month, TODAY.day).to_hijri()
HIJRI = f"{_h.day} {_h.month_name('ar')} {_h.year}هـ"
GREG = f"{TODAY.day} أكتوبر {TODAY.year}م"
DATE_LINE = f"{HIJRI} الموافق {GREG}"

INK = (23, 32, 48)
GOLD = (212, 166, 74)
MUTED = (110, 120, 135)
LINE = (214, 218, 226)
PALE = (247, 248, 250)
GREEN = (36, 120, 84)
LIVE = "https://mabaniq-api-production.up.railway.app"

# ──────────────────────────────────────────────────────────────────────────────────────────────────── الصور


def crop(name: str, ratio: float | None = None, top: bool = True, src: Path | None = None) -> Path:
    """نسخة مقصوصة من الصورة بنسبة ارتفاع/عرض قصوى (للتحكم في مساحة الصفحة). تُحفظ في tools/_crops."""
    p = src or (SCREENS / f"{name}.png")
    if not p.exists():
        p = DOCPREV / f"{name}.png" if (DOCPREV / f"{name}.png").exists() else ADS / f"{name}.png"
    im = Image.open(p).convert("RGB")
    w, h = im.size
    if ratio and h / w > ratio:
        nh = int(w * ratio)
        im = im.crop((0, 0, w, nh)) if top else im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    out = TMP / f"{p.stem}-{ratio or 'full'}-{'t' if top else 'c'}.jpg"
    if not out.exists():
        if im.size[0] > 1800:
            im = im.resize((1800, int(im.size[1] * 1800 / im.size[0])))
        im.save(out, quality=86, optimize=True)
    return out


def fig(name: str, caption: str, ratio: float | None = 0.625, top: bool = True, web: str | None = None) -> dict:
    return {"path": crop(name, ratio, top), "caption": caption, "web": web or f"web-assets/{name}.jpg"}


# ──────────────────────────────────────────────────────────────────────────────────────────────────── المحتوى

TITLE = "مبانيك لشركة المخطط العقارية"
SUBTITLE = "منصتكم العقارية من الحجز إلى التسليم"
TAGLINE = "منصة واحدة تدير دورة البيع العقاري كاملة"

INTRO = {
    "title": "عن هذا الدليل",
    "lead": "هذا الدليل يعرض منصة «مبانيك» — منصة التطوير العقاري من جدوى للدراسات والتطوير — كما تبدو لو كانت شركة المخطط العقارية تعمل عليها اليوم: "
            "مشاريعكم (مآب، مرتيل، مساكن جوار، ملاذ، مركز داود للأعمال، مساكن الفخامة 11)، مخططاتكم وتصوراتكم من كتيّب مآب، وترويستكم على كل مستند يصدر.",
    "bullets": [
        "كل اللقطات في هذا الدليل مأخوذة من المنصة الفعلية (الإصدار 0.13.0) بعد تحميل بيانات الشركة المنشورة.",
        "الأسعار ونِسب البيع والعملاء والدفعات **افتراضية** مبنية على مساحات الشركة المنشورة؛ الشركة لا تنشر أسعارها، وما يُستبدل بالبيانات الحقيقية يعمل بالمنطق نفسه.",
        "لا نَعِد بميزة غير موجودة: ما لم يُجرَّب حيًّا بعدُ أو ما ينتظر قرارًا من الشركة مذكور صراحةً في الصفحتين الأخيرتين.",
        "المنصة عربية أولًا، من اليمين إلى اليسار، بالتاريخ الهجري قبل الميلادي، وبالتمويل الإسلامي وحده: لا فوائد ولا قروض ربوية؛ خطط السداد مرابحة أو أقساط، وغرامة التأخير تبرع لا إيراد.",
    ],
}

WHY = {
    "title": "لماذا الآن؟ ثلاث مشكلات يعيشها مطوّر بأكثر من 39 مشروعًا",
    "lead": "مع كل مشروع جديد تتضاعف الملفات والمحادثات، ويتأخر الوصول إلى الحقيقة الواحدة: من حجز ماذا، ومن دفع كم، وأي مشروع يحتاج تدخلًا اليوم.",
    "cards": [
        ("تشتّت الحجوزات والتحصيل", "جداول Excel، مجموعات واتساب، وصور إيصالات: الحجز في مكان والدفعة في مكان آخر، والمطابقة البنكية في نهاية الشهر عملٌ يدوي."),
        ("المشروع المتعثّر بيعيًا يُكتشف متأخرًا", "لا يظهر تباطؤ البيع في مرتيل مثلًا إلا حين تُراجع الأرقام يدويًا؛ والتسعير والحملة والوسطاء قرارات تُتخذ بلا إشارة مبكرة."),
        ("العميل لا يرى وحدته ولا مستنداته", "يسأل عن موقع شقته على المخطط، وعن عقده وإيصالاته وموعد قسطه القادم، فيُجاب عبر مكالمة كل مرة."),
    ],
    "close": "مبانيك تضع الثلاثة في مكان واحد: مخزون حي، تحصيل مرتبط بالعقد، تطبيق للعميل، ولوحة تخبر الإدارة بما يحتاج قرارها اليوم.",
}

OVERVIEW = {
    "title": "المنصة في صفحة واحدة",
    "lead": "تتبع المنصة دورة التطوير العقاري الثلاثية، ويعمل فوقها طبقتان مشتركتان: المالية والتحصيل، والحوكمة والتقارير. كل مطوّر معزول ببياناته، وكل مستخدم بدوره وصلاحياته.",
    "columns": [
        ("1 · الأرض والتراخيص", ["الأراضي ودراسات الجدوى", "التراخيص والجهات الحكومية"]),
        ("2 · البيع والإنشاء", ["المخزون والتسعير والمخططات", "العملاء المحتملون والتسويق", "عروض الأسعار والحجز والعقود", "الإنشاء والمستخلصات"]),
        ("3 · التسليم والتشغيل", ["التسليم والعيوب ونقل الملكية", "اتحاد الملاك وإدارة المرافق", "خدمة العملاء والتأجير"]),
        ("عبر الدورة", ["السيولة والتعثر · الفواتير والضمان", "التقارير والتحليلات · سجل التدقيق", "الإدارة والأمان · هوية المستندات"]),
    ],
    "figures": [fig("02-dashboard", "لوحة القيادة لمطوّر «المخطط العقارية»: المؤشرات الأربعة، وصندوق القرارات بترتيب الأولوية، ودورة المشروع في الشريط الجانبي.", 0.5)],
}

TOUR = [
    {"sec": "الدخول والهوية", "title": "دخول آمن باسم الشركة",
     "lead": "يختار المستخدم المطوّر «المخطط العقارية» ثم يدخل بكلمة المرور أو بحساب Google الخاص بالشركة. لا يُنشأ حساب من الخارج أبدًا: الهوية تُطابَق على حساب قائم أنشأه مدير النظام.",
     "bullets": ["أدوار جاهزة: مدير عام، مبيعات، مالية، مهندس، مستثمر، وسيط، وعميل — كل دور يرى ما يخصه فقط.",
                 "تحقق ثنائي (TOTP) برموز استرداد، جلسات بأجهزتها وإمكانية إنهائها عن بُعد، وقفل متدرّج ضد التخمين.",
                 "استرجاع كلمة المرور ودخول برابط إلى البريد — يعملان على بيئة العرض بصندوق صادر حتى يُربط بريد الشركة."],
     "figures": [fig("01-login", "شاشة الدخول باختيار المطوّر، وزر الدخول بحساب Google (يظهر لأن Google مضبوط على الخادم). حقل كلمة المرور مقنَّع.", 0.62),
                 fig("30-security-2fa", "تبويب «أماني»: تفعيل التحقق الثنائي، الجلسات النشطة، والخروج من كل الأجهزة.", 0.5)]},
    {"sec": "لوحة القيادة", "title": "ما يحتاج قرارك اليوم",
     "lead": "اللوحة لا تعرض أرقامًا فقط؛ تقترح قرارات مرتّبة بالأولوية والأثر المالي: فجوة سيولة متوقعة في حساب ضمان مشروع، مستخلص لا تدعمه أدلة الإنجاز، عميل يحتاج إعادة جدولة، أو شريحة يُنصح برفع سعرها.",
     "bullets": ["المحفظة: 334 وحدة في ستة مشاريع (بيانات افتراضية على مساحات الشركة الفعلية).", "السيولة: تنبؤ شهري بحساب الضمان لكل مشروع مع ذروة العجز المتوقعة وسببها.",
                 "قرارات اليوم: كل قرار يحمل مصدره (رادار السيولة، التحقق من الإنجاز، نموذج التعثر، التسعير الديناميكي) وحالته."],
     "figures": [fig("02b-dashboard-full", "صندوق القرارات كاملًا: الأولوية، الأثر، المصدر، والحالة.", 0.95)]},
    {"sec": "المخزون والتسعير", "title": "مشروع مآب: 48 وحدة على مخطط حي",
     "lead": "مخطط المبنى A بطوابقه السبعة والطابق الأرضي التجاري: كل خلية وحدة بحالتها (متاحة، محجوزة، مباعة) ونموذجها. تحته «أداء الشرائح»: الطلب النسبي على كل نموذج وإطلالة، وتوصية محرّك التسعير.",
     "bullets": ["خمسة نماذج سكنية من 62.6 إلى 97.7 م² + شقق فندقية + 6 محلات على شارع الجامعة، كما في كتيّب مآب.",
                 "التسعير الديناميكي يقترح تعديلات بنسبة محدودة على الشرائح مرتفعة الطلب، ويُعلّم الوحدة المرشَّحة بعلامة ✦.",
                 "الضغط على أي وحدة يفتح بطاقتها: السعر، الإطلالة، الحجز إن وُجد، وموقعها على مخطط الطابق."],
     "figures": [fig("03-inventory-maab", "المخزون والتسعير — مشروع مآب، المبنى A.", 0.62)]},
    {"sec": "المخططات", "title": "مخططاتكم الحقيقية داخل المنصة",
     "lead": "مخططات كتيّب مآب (الموقع، المواقع القريبة، مخطط المحلات، الطابق المتكرر، نماذج الوحدات 01–05، التصورات الداخلية والخارجية) مرفوعة كمستندات ببصمة محتوى، ومخطط الطابق المتكرر يحمل علامات الوحدات 101–106.",
     "bullets": ["مواضع العلامات في هذه النسخة تقريبية؛ الموظف يضبطها بالنقر على المخطط («تحديد مواقع الوحدات»).",
                 "المخططات العامة يراها العميل في تطبيقه؛ المخططات الإنشائية والكهروميكانيكية داخلية دائمًا.",
                 "الملفات المرفوعة على بيئة العرض مؤقتة حتى يُربط تخزين دائم؛ عيّنات الشركة وحدها تعود تلقائيًا."],
     "figures": [fig("05-plans-typical-floor-markers", "لوحة المخططات: مخطط الطابق المتكرر بعلامات الوحدات (أخضر = متاحة)، ونموذج الوحدة 01.", 0.62),
                 fig("04-unit-detail-plan", "بطاقة الوحدة: الموقع على مخطط الطابق ومخطط نموذجها.", 0.62)]},
    {"sec": "رحلة العميل ١", "title": "عرض السعر بخطة سداد غير ربوية",
     "lead": "يُصدر موظف المبيعات عرض سعر مرقّمًا لوحدة متاحة بخطة سداد (مرتبطة بمراحل الإنجاز، أو 60/40، أو مرابحة عبر بنك إسلامي) وخصم ضمن صلاحيته. العرض لا يحجز الوحدة، ويتحوّل إلى حجز بضغطة واحدة بالسعر المعروض.",
     "bullets": ["عرض السعر PDF بترويسة الشركة وشعارها: الهجري أولًا، أرقام غربية، جدول دفعات صريح، ورمز تحقق مع QR.",
                 "صلاحية محددة، وسقف خصم بحسب الدور (موظف المبيعات 2٪، صاحب صلاحية القرار حتى 15٪)؛ كل عرض في سجل التدقيق.",
                 "العرض المرفق صدر فعليًا من المنصة للوحدة MAB-A-706 (شقة فندقية) لعميل متخيَّل."],
     "figures": [fig("09-sales-quotes", "تبويب عروض الأسعار: العرض الساري، خطته، ونسبة التحويل.", 0.45),
                 fig("QT-2026-00001-quote-p1", "عرض السعر QT-2026-00001 كما صدر من المنصة بترويسة المخطط العقارية.", 1.0, web="web-assets/QT-2026-00001-quote-p1.jpg")]},
    {"sec": "رحلة العميل ٢", "title": "الحجز، التحقق من الهوية، والعقد الموقَّع",
     "lead": "الحجز يُنشئ جدول الأقساط فورًا؛ التحقق من الهوية (KYC) يسجّل الوثيقة ويقيّم المخاطر؛ العقد يصدر بنص موقَّع ببصمته، يوقّعه العميل من تطبيقه أو حضوريًا، ثم يُنشأ حسابه تلقائيًا.",
     "bullets": ["العقد يحوي شرط التبرع (بدل غرامة التأخير) معلَّمًا «تحتاج اعتماد مستشار شرعي» حتى تعتمده الشركة.",
                 "لا تسليم بلا خطاب صرف، ولا صرف من الضمان إلا بمستخلص معتمد؛ القواعد في النواة لا في العُرف.",
                 "كل مستند (عقد، فاتورة، إيصال) يُولَّد من القاعدة عند الطلب ولا يُخزَّن ملفًا، ويمكن التحقق منه علنًا برمزه."],
     "figures": [fig("08-sales-kyc-contracts", "الحجوزات بانتظار التحقق من الهوية وإصدار العقد.", 0.5),
                 fig("SPA-00001-contract-p1", "عقد البيع SPA-00001 — موقَّع من العميل، بترويسة الشركة ورمز تحقق.", 0.9, web="web-assets/SPA-00001-contract-p1.jpg")]},
    {"sec": "رحلة العميل ٣", "title": "الفاتورة والإيصال بترويسة الشركة",
     "lead": "كل قسط مستحق يُصدر فاتورة (أو فاتورة ضريبية حين تنطبق الضريبة)، وكل دفعة تُصدر إيصال استلام. الإرسال للعميل طباعةً، أو بريدًا بمرفق، أو برابط واتساب موقَّع صالح 30 يومًا.",
     "bullets": ["الترقيم متسلسل لكل سنة، والمبالغ بأرقام غربية والتواريخ هجري ثم ميلادي.",
                 "الشعار والختم والتوقيع المعتمد تُرفع مرة واحدة من شاشة «هوية المستندات والختم» فتظهر على كل مستند.",
                 "النموذجان أدناه صدرا من المنصة للعميل الأول في مآب (بيانات افتراضية)."],
     "figures": [fig("INV-2026-000127-invoice-p1", "الفاتورة INV-2026-000127.", 0.8, web="web-assets/INV-2026-000127-invoice-p1.jpg"),
                 fig("MBQ-H-000003-receipt-p1", "إيصال الاستلام MBQ-H-000003.", 0.8, web="web-assets/MBQ-H-000003-receipt-p1.jpg")], "side": True},
    {"sec": "تطبيق العميل", "title": "العميل يرى وحدته ومستنداته وموقعه على المخطط",
     "lead": "تطبيق ويب للهاتف يدخله العميل بحسابه: وحدتي (تقدم البناء، الموعد المتوقع، وصور الإنجاز)، الدفعات (جدول الأقساط والدفع الإلكتروني)، الصيانة (طلبات بعد التسليم)، إعادة البيع (السوق الثانوي بموافقة المطوّر)، والمزيد (العقد، الفواتير، الإيصالات، المخططات، التصويت في اتحاد الملاك).",
     "bullets": ["يرى العميل مخطط طابقه وعلامة وحدته وحدها، ومخطط نموذج وحدته، والتصورات العامة.",
                 "تغيير كلمة المرور إلزامي عند أول دخول؛ وله الخروج من كل الأجهزة الأخرى.",
                 "تصدير بياناته الشخصية وطلبات الخصوصية من التطبيق مباشرة."],
     "figures": [fig("40-client-home", "وحدتي: المحل MAB-A-001 في مآب، تقدم البناء 58٪.", 1.5),
                 fig("41-client-payments", "الدفعات: جدول الأقساط المرتبط بمراحل الإنشاء.", 1.5),
                 fig("43-client-docs-plans", "المزيد: العقد الموقَّع والمستندات والمخططات.", 1.5)], "side": True},
    {"sec": "التحصيل والمالية", "title": "رادار السيولة وتعثر العملاء",
     "lead": "تنبؤ شهري بالتدفقات لكل حساب ضمان، مع المحرّكات (مستخلص، دفعات مجدولة) وذروة العجز المتوقعة. وقائمة العملاء المعرّضين للتعثر بدرجاتهم واقتراح إعادة الجدولة قبل التأخر لا بعده.",
     "bullets": ["المتأخرات بأعمارها (30/60/90 يومًا) وقائمة الأقساط المتأخرة بالعميل والوحدة.",
                 "التأخير لا يولّد غرامة إيرادًا؛ يُقيَّد تبرعًا بشرط التبرع في العقد (1٪ شهريًا بعد 15 يومًا كقيمة مؤقتة تُراجَع مع المستشار الشرعي)، ويمكن إعفاؤه.",
                 "الفواتير وضريبة القيمة المضافة، والمطابقة البنكية باستيراد الكشف، وحساب ضمان لكل مشروع: لا صرف إلا بمستخلص معتمد واحتجاز 10٪ حتى التسليم (قواعد عامة حتى تُضبط على متطلبات وزارة الإسكان)."],
     "figures": [fig("15-finance-radar", "السيولة والتعثر: التنبؤ الشهري لحسابات الضمان الأربعة.", 0.5)],
     "figures2_side": [fig("17-late-charity", "تبرعات التأخير (شرط التبرع) والفسخ.", 0.5), fig("18-bank-reconciliation", "المطابقة البنكية: كل دفعة تُقابل بسطر كشف، وغير المطابَق يظهر وحده.", 0.5)]},
    {"sec": "الإنشاء والمستخلصات", "title": "الإنجاز الفعلي مقابل المبيعات",
     "lead": "المستخلصات (IPC) تُعتمد بنسبة يدعمها الدليل (صور ومحاضر)؛ حين تعلن نسبة أعلى من الأدلة يقترح النظام اعتماد النسبة المدعومة ويقدّر الصرف الزائد المتجنَّب. الجدول الزمني يُقارن بالمبيعات ليظهر المشروع الذي يبيع أسرع مما يُبنى أو العكس.",
     "bullets": ["مآب عند 58٪ إنجاز مقابل 73٪ بيع (افتراضيًا): البيع أسبق من البناء، والتسليم المتوقع 2027.",
                 "مرتيل 34٪ إنجاز: مرحلة الهيكل الخرساني هي محرّك ذروة السيولة في فبراير 2027 على اللوحة.",
                 "كل اعتماد مستخلص بصلاحية مستقلة (approve_ipc) وسطر تدقيق."],
     "figures": [fig("11-construction-ipc", "الإنشاء والمستخلصات.", 0.62)]},
    {"sec": "التسليم واتحاد الملاك", "title": "مساكن جوار ومساكن الفخامة 11",
     "lead": "التسليم يُجدول بموعد ويُوثَّق بشهادة ومحضر ملاحظات (العيوب) وقراءات عدادات ومفاتيح، ولا يكتمل قبل سداد دفعة التسليم. بعد الاكتمال يتولى اتحاد الملاك الميزانية والتصويت الموزون بمساحة الوحدة من تطبيق العميل.",
     "bullets": ["مساكن جوار (فلل 200/240 م² بالموالح) عند 90٪ إنجاز: مواعيد التسليم والملاحظات المفتوحة.",
                 "مساكن الفخامة 11 (مكتمل ومسلَّم): اتحاد الملاك، الميزانية، والتصويت على البنود.",
                 "إدارة المرافق والتأجير ونقل الملكية في التبويبات المجاورة."],
     "figures": [fig("12-handover", "التسليم والعيوب.", 0.5), fig("13-owners-association", "اتحاد الملاك: الميزانية والتصويت.", 0.5)]},
    {"sec": "التقارير والتحليلات", "title": "عشرة تقارير جاهزة ومنشئ تقارير بلا SQL",
     "lead": "تقارير جاهزة بالنقر (المحفظة، أداء المبيعات، قمع العملاء، عروض الأسعار، الوسطاء، التحصيل والمتأخرات، السيولة، المخزون، الإنشاء، التسليم) بمعاملات ورسوم؛ ومنشئ تقارير على مجموعات بيانات معتمدة بفلاتر وتجميع، وتصدير CSV/PDF برسوم، وحفظ وجدولة بالبريد.",
     "bullets": ["الرسوم تُرسم داخل المنصة بلا مكتبة خارجية، وفي PDF بالمحرّك نفسه.",
                 "تقارير الممولين والمستثمرين بصلاحيات مستقلة.", "التقريران المرفقان (المحفظة، التحصيل) صدرا من المنصة بترويسة الشركة."],
     "figures": [fig("21-report-portfolio", "تقرير لوحة المحفظة داخل المنصة.", 0.5),
                 fig("report-portfolio-p1", "التقرير نفسه مصدَّرًا PDF.", 0.8, web="web-assets/report-portfolio-p1.jpg")], "side": True},
    {"sec": "التسويق", "title": "لوحة التسويق: أي مشروع يحتاج تدخلًا",
     "lead": "تصنّف اللوحة كل مشروع من بياناته الحية (وتيرة البيع 30/90 يومًا مقابل المخطط، الطلب النسبي على الشرائح، العملاء المتوقفون، الإنجاز) إلى: إطلاق، ضعيف البيع، مستقر، شبه مكتمل، مكتمل — مع إشارات وإجراءات مقترحة وزرّ «حملة جديدة» و«إعلان».",
     "bullets": ["الحملة تحمل عرضًا هيكليًا فقط (تأجيل، تقسيط، إعفاء رسوم، باقات)؛ المنصة ترفض أي عرض بفائدة.",
                 "رمز تتبع لكل حملة يقيس العملاء الواردين وكلفة العميل؛ الإرسال بريدًا/واتساب مسجَّل.",
                 "في هذه اللقطة التجريبية صُنّف مرتيل «مستقرًا» لأن بيانات البيع الافتراضية أسرع من مخططه؛ مع البيانات الحقيقية يتغيّر التصنيف تلقائيًا."],
     "figures": [fig("24-marketing-board", "لوحة التسويق لمشاريع الشركة الستة.", 0.62), fig("25-campaigns", "حملة مرتيل بعرض غير ربوي ورمز تتبع.", 0.45)]},
    {"sec": "استوديو الإعلانات", "title": "إعلان جاهز على تصوّر مآب الحقيقي",
     "lead": "ستة قوالب (تشويقي، إطلاق، عرض خاص، آخر الوحدات، تقدم البناء، جاهزة للسكن) بثلاثة مقاسات، النص العربي مركَّب برمجيًا على صورة الخلفية التي تختارونها — هنا تصور مآب من الكتيّب — بشعار الشركة وبيانات التواصل، بلا أشخاص.",
     "bullets": ["الإعلانان أدناه أُنتجا من الاستوديو في المنصة (قالب الإطلاق، وآخر الوحدات — مقاس مربع).",
                 "يُحفظ الإعلان مستندًا PNG وPDF ويُربط بحملة ويُرسل لجمهورها.", "التنبيهات التسويقية تُسجَّل يوميًا من حركة السوق (توقف عملاء، انخفاض وتيرة، فرصة رفع سعر)."],
     "figures": [fig("ad-maab-launch-square", "إطلاق مبيعات مشروع مآب.", 1.0, web="web-assets/ad-maab-launch-square.jpg"),
                 fig("ad-maab-last_units-square", "آخر الوحدات في مشروع مآب.", 1.0, web="web-assets/ad-maab-last_units-square.jpg")], "side": True,
     "figures2": [fig("26-ad-studio", "استوديو الإعلانات داخل المنصة.", 0.5)]},
    {"sec": "الحوكمة والأمان", "title": "سجل تدقيق لا يُمحى، وتحقق عام من كل مستند",
     "lead": "كل فعل في المنصة سطر في سجل تدقيق مسلسل ببصمة (hash chain) لا يستطيع أحد تعديله؛ البيانات الشخصية مشفّرة في القاعدة؛ وكل مطوّر معزول بصفوفه على مستوى قاعدة البيانات لا على مستوى التطبيق.",
     "bullets": ["المستخدمون والأدوار: إضافة، تعديل البريد، إنهاء الجلسات، إعادة ضبط التحقق الثنائي.",
                 "هوية المستندات والختم: اسم الشركة، السجل التجاري، الرقم الضريبي، العنوان، الشعار، الختم، والتوقيع.",
                 "صفحة التحقق العامة /verify: تُظهر النوع والرقم والتاريخ وبصمة المحتوى بلا أي بيانات شخصية."],
     "figures": [fig("28-audit-log", "سجل التدقيق.", 0.45), fig("31-brand-letterhead", "هوية المستندات والختم.", 0.45), fig("32-public-verify", "صفحة التحقق العامة لعرض السعر.", 0.33)]},
]

NEEDS = {
    "title": "ما تحتاجه الشركة للانطلاق الفعلي",
    "lead": "كل ما في هذا الدليل يعمل اليوم على بيانات افتراضية. لتصبح المنصة منصة المخطط العقارية فعلًا نحتاج من الشركة:",
    "items": [
        ("جداول الوحدات والأسعار وخطط السداد الحقيقية", "لكل مشروع: رموز الوحدات، المساحات، الإطلالات، الأسعار، وخطط السداد المعتمدة (مراحل/60-40/مرابحة)."),
        ("الشعار والختم والتوقيع بدقة الطباعة", "ملفات PNG شفافة بدقة عالية؛ الشعار الحالي بدقة الموقع الإلكتروني فقط."),
        ("صور ومخططات مرتيل ومساكن جوار", "لا صور عامة كافية لهما؛ يلزم المخططات والتصورات كما توفّرت لمآب وملاذ."),
        ("حساب بريد SMTP ونطاق", "لإرسال المستندات والتنبيهات وروابط الدخول من بريد الشركة؛ اليوم البريد في وضع «صندوق صادر»."),
        ("WhatsApp Business (اختياري)", "اليوم الإرسال برابط wa.me من جهاز الموظف؛ الإرسال الآلي يحتاج حساب Business API ومزوّدًا."),
        ("تخزين دائم للمرفقات", "المخططات والمستندات المرفوعة تحتاج تخزينًا دائمًا (Volume أو S3) قبل أول استعمال فعلي."),
        ("اعتماد الصياغات الشرعية والقانونية", "صيغة شرط التبرع والعقد النموذجي من مستشار الشركة الشرعي والقانوني."),
        ("حسابات المستخدمين", "قائمة الموظفين وأدوارهم؛ والسماح بدخول Google على نطاق الشركة إن رغبتم."),
    ],
}

MODELS = {
    "title": "صيغتا التعاون",
    "lead": "تُترك الأرقام للاجتماع. الفرق الجوهري بين الصيغتين: من يشغّل، ومن يملك، وكيف تصل التحديثات.",
    "heads": ["الوجه", "اشتراك على منصة جدوى المستضافة", "نسخة خاصة على بنية الشركة"],
    "rows": [
        ("الملكية", "ترخيص استخدام؛ الشيفرة والتشغيل لدى جدوى", "نسخة مرخَّصة تُنشر على خوادم الشركة (Docker + PostgreSQL)"),
        ("العزل والبيانات", "مطوّر معزول بصفوفه (RLS) على قاعدة مشتركة؛ البيانات ملك الشركة وتُصدَّر عند الطلب", "قاعدة بيانات خاصة بالكامل داخل بنية الشركة"),
        ("التحديثات", "مستمرة وتلقائية مع كل إصدار", "بحسب اتفاق الصيانة؛ تُطبَّق على نسخة الشركة"),
        ("النسخ الاحتياطي", "يومي من جدوى مع تمرين استرجاع", "مسؤولية فريق الشركة بدليل التشغيل RUNBOOK"),
        ("الدعم والتدريب", "ضمن الاشتراك", "ضمن عقد التنفيذ والصيانة"),
        ("الكلفة الأولية", "", ""),
        ("الكلفة الدورية", "", ""),
    ],
}

LIMITS = {
    "title": "ما يجب أن يُقال بصراحة",
    "items": [
        "الأسعار ونِسب البيع والعملاء والدفعات في هذا الدليل افتراضية، مبنية على مساحات الشركة المنشورة (الشركة لا تنشر أسعارها).",
        "لا صور لمرتيل ومساكن جوار في المنصة بعد؛ ومواضع علامات الوحدات على مخطط الطابق تقريبية.",
        "البريد في وضع «صندوق صادر» حتى يُضبط SMTP؛ وواتساب عبر روابط wa.me لا عبر Business API.",
        "الملفات التي يرفعها الموظفون على بيئة العرض مؤقتة حتى يُربط تخزين دائم؛ عيّنات المخطط العقارية وحدها تعود تلقائيًا.",
        "لقطات هذا الدليل التُقطت من نسخة محلية مطابقة للإصدار المنشور (0.13.0) لأن كلمة مرور بيئة العرض لا تُكتب في أي ملف؛ ورموز التحقق في النماذج المرفقة صدرت من تلك النسخة فلا تُستعلم على الموقع الحي.",
        "ما لم يُجرَّب حيًّا بعد: بوابة الدفع العُمانية (اليوم محاكاة)، الربط مع الجهات الحكومية، وWhatsApp Business.",
    ],
    "close": "ما عدا ذلك يعمل اليوم على الرابط الحي، ويمكن للشركة تجربته بحسابات عرض.",
}

CLOSE = {
    "title": "الخطوة التالية: اجتماع عرض حي",
    "lead": "نقترح اجتماعًا لمدة ساعة في مقر الشركة نعرض فيه المنصة حيّة على بيانات مآب، ونستلم فيه قائمة الاحتياجات أعلاه، ونتفق على الصيغة والجدول الزمني للانطلاق.",
    "bullets": ["جدوى للدراسات والتطوير — مسقط · jadwa.om", f"رابط بيئة العرض: {LIVE}", "المطوّر في شاشة الدخول: «المخطط العقارية»"],
}

# ──────────────────────────────────────────────────────────────────────────────────────────────────── PDF


class Guide(FPDF):
    def __init__(self, landscape=False):
        super().__init__(unit="mm", format=(297, 210) if landscape else "A4")
        self.add_font("Tajawal", "", str(FONTS / "Tajawal-Regular.ttf"))
        self.add_font("Tajawal", "B", str(FONTS / "Tajawal-Bold.ttf"))
        self.set_text_shaping(use_shaping_engine=True, direction="rtl", script="arab", language="ar")
        self.set_margins(16, 18, 16)
        self.set_auto_page_break(auto=True, margin=18)
        self.sec = ""
        self.alias_nb_pages()
        self.cover = True

    @property
    def cw(self):
        return self.w - self.l_margin - self.r_margin

    def header(self):
        if self.cover:
            return
        self.set_font("Tajawal", "", 8.5)
        self.set_text_color(*MUTED)
        self.set_xy(self.l_margin, 8)
        self.cell(self.cw, 5, f"{TITLE} — {SUBTITLE}", align="R")
        self.set_xy(self.l_margin, 8)
        self.cell(self.cw, 5, self.sec, align="L")
        self.set_draw_color(*GOLD)
        self.set_line_width(0.5)
        self.line(self.l_margin, 14.5, self.w - self.r_margin, 14.5)
        self.set_y(18)

    def footer(self):
        if self.cover:
            return
        self.set_y(-12)
        self.set_font("Tajawal", "", 8)
        self.set_text_color(*MUTED)
        self.cell(self.cw, 5, f"صفحة {self.page_no()} من {{nb}} · {DATE_LINE} · بيانات العرض افتراضية", align="R")
        self.set_y(-12)
        self.cell(self.cw, 5, "جدوى للدراسات والتطوير · مبانيك 0.13.0", align="L")

    # ---- نصوص
    def h1(self, t, size=19):
        self.set_font("Tajawal", "B", size)
        self.set_text_color(*INK)
        self.multi_cell(self.cw, size * 0.5, t, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1.5)

    def lead(self, t, size=10.5):
        self.set_font("Tajawal", "", size)
        self.set_text_color(*INK)
        self.multi_cell(self.cw, size * 0.58, t, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def bullets(self, items, size=9.8):
        for it in items:
            y = self.get_y()
            self.set_fill_color(*GOLD)
            self.ellipse(self.w - self.r_margin - 2.6, y + 2.1, 1.7, 1.7, style="F")
            self.set_xy(self.l_margin, y)
            self.set_font("Tajawal", "", size)
            self.set_text_color(*INK)
            self.multi_cell(self.cw - 5, size * 0.56, it.replace("**", ""), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(1.2)
        self.ln(1)

    def caption(self, t, w=None, x=None):
        self.set_font("Tajawal", "", 8.3)
        self.set_text_color(*MUTED)
        if x is not None:
            self.set_x(x)
        self.multi_cell(w or self.cw, 4.2, t, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def tag(self, t, x, y, w=None):
        self.set_font("Tajawal", "B", 8.5)
        tw = w or self.get_string_width(t) + 8
        self.set_fill_color(*GOLD)
        self.set_text_color(255, 255, 255)
        self.set_xy(x - tw, y)
        self.cell(tw, 6, t, align="C", fill=True)
        self.set_text_color(*INK)

    # ---- صور
    def figure(self, f, max_h=None, w=None, x=None, caption=True):
        im = Image.open(f["path"])
        iw, ih = im.size
        w = w or self.cw
        h = w * ih / iw
        avail = self.h - self.b_margin - self.get_y() - (10 if caption else 2)
        lim = min(avail, max_h or 1e9)
        if h > lim:
            h = lim
            w2 = h * iw / ih
            x = (x if x is not None else self.l_margin) + (w - w2) if x is None else x + (w - w2)
            w = w2
        x = self.l_margin + (self.cw - w) if x is None else x
        y = self.get_y()
        self.set_draw_color(*LINE)
        self.set_line_width(0.3)
        self.rect(x - 0.4, y - 0.4, w + 0.8, h + 0.8)
        self.image(str(f["path"]), x=x, y=y, w=w, h=h)
        self.set_y(y + h + 1.5)
        if caption:
            self.caption(f["caption"], w=w, x=x)
            self.ln(2)
        return h

    def figures_side(self, figs, max_h=None):
        n = len(figs)
        gap = 4
        w = (self.cw - gap * (n - 1)) / n
        y0 = self.get_y()
        hs = []
        avail = self.h - self.b_margin - y0 - 12
        for i, f in enumerate(figs):
            im = Image.open(f["path"])
            iw, ih = im.size
            hs.append(w * ih / iw)
        hmax = min(max(hs), avail, max_h or 1e9)
        xr = self.w - self.r_margin
        for i, f in enumerate(figs):
            im = Image.open(f["path"])
            iw, ih = im.size
            h = min(w * ih / iw, hmax)
            ww = h * iw / ih if w * ih / iw > hmax else w
            x = xr - w + (w - ww)
            self.set_draw_color(*LINE)
            self.rect(x - 0.4, y0 - 0.4, ww + 0.8, h + 0.8)
            self.image(str(f["path"]), x=x, y=y0, w=ww, h=h)
            self.set_xy(xr - w, y0 + hmax + 1.5)
            self.caption(f["caption"], w=w, x=xr - w)
            xr -= w + gap
        self.set_y(y0 + hmax + 10)

    def mabaniq_mark(self, x, y, s=14, text=True):
        self.set_fill_color(*GOLD)
        self.rect(x, y, s, s, style="F", round_corners=True, corner_radius=s * 0.22)
        self.set_font("Tajawal", "B", s * 1.9)
        self.set_text_color(*INK)
        self.set_xy(x, y + s * 0.02)
        self.cell(s, s, "م", align="C")
        if text:
            self.set_font("Tajawal", "B", s * 1.6)
            self.set_xy(x - 40, y)
            self.cell(38, s, "مبانيك", align="R")
            self.set_font("Tajawal", "", s * 0.62)
            self.set_text_color(*MUTED)
            self.set_xy(x - 40, y + s * 0.72)
            self.cell(38, s * 0.5, "منصة المطوّر العقاري · جدوى", align="R")


def cover(p: Guide):
    p.cover = True
    p.add_page()
    p.set_fill_color(*INK)
    p.rect(0, 0, p.w, p.h, style="F")
    p.set_fill_color(*GOLD)
    p.rect(0, 0, 6, p.h, style="F")
    # الشعاران
    p.mabaniq_mark(p.w - 16 - 16, 30, 16)
    logo = SAMPLES / "almukhatat-logo.png"
    p.image(str(logo), x=16, y=28, w=48)
    p.set_font("Tajawal", "", 9)
    p.set_text_color(200, 205, 215)
    p.set_xy(16, 48)
    p.cell(48, 5, "شركة المخطط العقارية", align="C")
    # العنوان
    p.set_xy(16, 95)
    p.set_font("Tajawal", "B", 30)
    p.set_text_color(255, 255, 255)
    p.multi_cell(p.cw, 16, TITLE, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.set_font("Tajawal", "", 18)
    p.set_text_color(*GOLD)
    p.multi_cell(p.cw, 11, SUBTITLE, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.ln(6)
    p.set_font("Tajawal", "", 12.5)
    p.set_text_color(225, 228, 235)
    p.multi_cell(p.cw, 8, f"«{TAGLINE}»", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.ln(10)
    p.set_font("Tajawal", "", 10.5)
    p.set_text_color(200, 205, 215)
    p.multi_cell(p.cw, 6.5, "دليل ترويجي مصوَّر — لقطات حقيقية من المنصة بمشاريع الشركة ومخططاتها وترويستها (الإصدار 0.13.0)", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    # الصورة
    f = crop("maab-render-02", 0.5, True, SAMPLES / "maab-render-02.jpg")
    p.image(str(f), x=16, y=170, w=p.cw)
    p.set_font("Tajawal", "", 8)
    p.set_text_color(170, 176, 190)
    p.set_xy(16, 170 + p.cw * 0.5 + 1)
    p.cell(p.cw, 5, "التصور النهائي لمشروع مآب — من كتيّب الشركة", align="R")
    # التاريخ
    p.set_font("Tajawal", "B", 11)
    p.set_text_color(*GOLD)
    p.set_xy(16, 278)
    p.cell(p.cw, 6, DATE_LINE, align="R")
    p.set_font("Tajawal", "", 9.5)
    p.set_text_color(200, 205, 215)
    p.set_xy(16, 285)
    p.cell(p.cw, 6, "إعداد: جدوى للدراسات والتطوير — مسقط، سلطنة عُمان", align="R")
    p.cover = False


def page_text(p: Guide, sec, title, lead, bullets=None):
    p.sec = sec
    p.add_page()
    p.h1(title)
    if lead:
        p.lead(lead)
    if bullets:
        p.bullets(bullets)


def build_guide_pdf(out: Path):
    p = Guide()
    cover(p)
    # عن الدليل
    page_text(p, "مقدمة", INTRO["title"], INTRO["lead"], INTRO["bullets"])
    p.ln(4)
    # الشعاران جنبًا إلى جنب
    y = p.get_y() + 4
    p.set_fill_color(*PALE)
    p.rect(p.l_margin, y, p.cw, 46, style="F", round_corners=True, corner_radius=3)
    p.mabaniq_mark(p.w - p.r_margin - 24, y + 14, 16)
    p.image(str(SAMPLES / "almukhatat-logo.png"), x=p.l_margin + 14, y=y + 10, w=42)
    p.set_font("Tajawal", "B", 14)
    p.set_text_color(*GOLD)
    p.set_xy(p.l_margin, y + 16)
    p.cell(p.cw, 10, "×", align="C")
    p.set_y(y + 50)
    p.set_font("Tajawal", "", 9.5)
    p.set_text_color(*MUTED)
    p.multi_cell(p.cw, 5.5, f"{TAGLINE}. رابط بيئة العرض: {LIVE} — المطوّر «المخطط العقارية» في قائمة الدخول.", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # لماذا الآن
    page_text(p, "لماذا الآن", WHY["title"], WHY["lead"])
    for i, (h, t) in enumerate(WHY["cards"], 1):
        y = p.get_y()
        p.set_fill_color(*PALE)
        hh = 30
        p.rect(p.l_margin, y, p.cw, hh, style="F", round_corners=True, corner_radius=2.5)
        p.set_fill_color(*GOLD)
        p.rect(p.w - p.r_margin - 2.2, y, 2.2, hh, style="F")
        p.set_xy(p.l_margin + 4, y + 4)
        p.set_font("Tajawal", "B", 12.5)
        p.set_text_color(*INK)
        p.cell(p.cw - 10, 7, f"{i}. {h}", align="R")
        p.set_xy(p.l_margin + 4, y + 12)
        p.set_font("Tajawal", "", 10)
        p.multi_cell(p.cw - 10, 5.6, t, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        p.set_y(y + hh + 4)
    p.ln(3)
    p.set_font("Tajawal", "B", 11)
    p.set_text_color(*GREEN)
    p.multi_cell(p.cw, 6.5, WHY["close"], align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.ln(4)
    p.figure(fig("24b-marketing-board-full", "مثال: لوحة التسويق تصنّف المشاريع الستة من بياناتها الحية وتقترح إجراءً لكل مشروع.", 0.62), max_h=100)

    # المنصة في صفحة واحدة
    page_text(p, "نظرة عامة", OVERVIEW["title"], OVERVIEW["lead"])
    cols = OVERVIEW["columns"]
    n = len(cols)
    gap = 3
    w = (p.cw - gap * (n - 1)) / n
    y0 = p.get_y()
    xr = p.w - p.r_margin
    hh = 44
    for h, items in cols:
        x = xr - w
        p.set_fill_color(*PALE)
        p.rect(x, y0, w, hh, style="F", round_corners=True, corner_radius=2.5)
        p.set_fill_color(*GOLD)
        p.rect(x, y0, w, 1.6, style="F")
        p.set_xy(x + 2, y0 + 3)
        p.set_font("Tajawal", "B", 10.2)
        p.set_text_color(*INK)
        p.cell(w - 4, 6, h, align="R")
        p.set_xy(x + 2, y0 + 11)
        p.set_font("Tajawal", "", 8.8)
        p.multi_cell(w - 4, 4.9, "\n".join("• " + i for i in items), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        xr -= w + gap
    p.set_y(y0 + hh + 6)
    p.bullets(["كل مطوّر (مستأجر) معزول بصفوفه على مستوى قاعدة البيانات، وكل كتابة تمر بصلاحية في الخادم وسطر تدقيق.",
               "الواجهة عربية من اليمين إلى اليسار بأرقام غربية، مع إنجليزية بضغطة زر، وخط عربي ذاتي الاستضافة بلا أي خدمة خارجية."])
    p.figure(OVERVIEW["figures"][0], max_h=95)

    # الجولة
    for s in TOUR:
        page_text(p, s["sec"], s["title"], s["lead"], s.get("bullets"))
        if s.get("side"):
            p.figures_side(s["figures"], max_h=118)
        else:
            figs = s["figures"]
            remaining = p.h - p.b_margin - p.get_y()
            per = (remaining - 12 * len(figs)) / len(figs)
            for f in figs:
                p.figure(f, max_h=per)
        if s.get("figures2"):
            p.figure(s["figures2"][0], max_h=p.h - p.b_margin - p.get_y() - 12)
        if s.get("figures2_side"):
            p.figures_side(s["figures2_side"], max_h=p.h - p.b_margin - p.get_y() - 14)

    # الاحتياجات
    page_text(p, "الانطلاق", NEEDS["title"], NEEDS["lead"])
    for i, (h, t) in enumerate(NEEDS["items"], 1):
        y = p.get_y()
        p.set_font("Tajawal", "B", 10.8)
        p.set_text_color(*INK)
        p.set_fill_color(*GOLD)
        p.set_text_color(255, 255, 255)
        p.set_xy(p.w - p.r_margin - 8, y)
        p.cell(8, 7, str(i), align="C", fill=True)
        p.set_text_color(*INK)
        p.set_xy(p.l_margin, y)
        p.cell(p.cw - 10, 7, h, align="R")
        p.set_xy(p.l_margin, y + 7)
        p.set_font("Tajawal", "", 9.6)
        p.set_text_color(*MUTED)
        p.multi_cell(p.cw - 10, 5.2, t, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        p.ln(3)

    # صيغتا التعاون
    page_text(p, "صيغتا التعاون", MODELS["title"], MODELS["lead"])
    widths = (0.2, 0.4, 0.4)
    ws = [p.cw * x for x in widths]
    y = p.get_y()
    xr = p.w - p.r_margin
    p.set_fill_color(*INK)
    p.set_text_color(255, 255, 255)
    p.set_font("Tajawal", "B", 10)
    for hname, wd in zip(MODELS["heads"], ws):
        p.set_xy(xr - wd, y)
        p.cell(wd, 9, hname, align="C", fill=True)
        xr -= wd
    y += 9
    for ri, row in enumerate(MODELS["rows"]):
        p.set_font("Tajawal", "", 9.4)
        hs = []
        for cell, wd in zip(row, ws):
            hs.append(p.multi_cell(wd - 3, 5, cell or " ", align="R", dry_run=True, output="HEIGHT") if cell else 5)
        rh = max(max(hs) + 4, 10)
        xr = p.w - p.r_margin
        p.set_fill_color(*(PALE if ri % 2 == 0 else (255, 255, 255)))
        p.rect(p.l_margin, y, p.cw, rh, style="F")
        for ci, (cell, wd) in enumerate(zip(row, ws)):
            p.set_xy(xr - wd + 1.5, y + 2)
            p.set_font("Tajawal", "B" if ci == 0 else "", 9.4)
            p.set_text_color(*INK)
            if cell:
                p.multi_cell(wd - 3, 5, cell, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            else:
                p.set_draw_color(*LINE)
                p.set_line_width(0.3)
                p.set_dash_pattern(dash=1.2, gap=1.2)
                p.rect(xr - wd + 4, y + 2.5, wd - 8, rh - 5)
                p.set_dash_pattern()
            xr -= wd
        p.set_draw_color(*LINE)
        p.line(p.l_margin, y + rh, p.w - p.r_margin, y + rh)
        y += rh
    p.set_y(y + 5)
    p.set_font("Tajawal", "", 9.5)
    p.set_text_color(*MUTED)
    p.multi_cell(p.cw, 5.5, "الخانات المنقّطة تُملأ في الاجتماع. في الحالتين: ترخيص واحد لمطوّر واحد، والبيانات ملك الشركة، ودليل التشغيل (RUNBOOK) ودليل الأمان ضمن التسليم.", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # الصدق والخاتمة
    page_text(p, "بصراحة", LIMITS["title"], None, LIMITS["items"])
    p.set_font("Tajawal", "B", 10.5)
    p.set_text_color(*GREEN)
    p.multi_cell(p.cw, 6.5, LIMITS["close"], align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.ln(8)
    p.set_draw_color(*GOLD)
    p.line(p.l_margin, p.get_y(), p.w - p.r_margin, p.get_y())
    p.ln(6)
    p.h1(CLOSE["title"], 17)
    p.lead(CLOSE["lead"])
    p.bullets(CLOSE["bullets"])
    p.ln(4)
    p.figure(fig("maab-render-03", "مشروع مآب — المدخل والمحلات (من كتيّب الشركة).", 0.45, True), max_h=80) if False else None
    f = {"path": crop("maab-render-03", 0.42, False, SAMPLES / "maab-render-03.jpg"), "caption": "مشروع مآب — المدخل والمحلات (من كتيّب الشركة)."}
    p.figure(f, max_h=p.h - p.b_margin - p.get_y() - 12)
    p.output(str(out))
    print("PDF", out.name, p.page_no(), "صفحة")


# ──────────────────────────────────────────────────────────────────────────────────────────────────── الشرائح

SLIDES = [
    {"kind": "cover"},
    {"title": "المشكلة", "sub": "ثلاث مشكلات يعيشها مطوّر بأكثر من 39 مشروعًا",
     "bullets": [c[0] + " — " + c[1] for c in WHY["cards"]], "fig": None},
    {"title": "المنصة", "sub": "منصة واحدة تدير دورة البيع العقاري كاملة",
     "bullets": ["1 · الأرض والتراخيص ⟵ 2 · البيع والإنشاء ⟵ 3 · التسليم والتشغيل", "عبر الدورة: السيولة والضمان، التقارير، سجل التدقيق، الإدارة والأمان",
                 "عربية أولًا · RTL · هجري أولًا · تمويل إسلامي فقط", "كل مطوّر معزول على مستوى قاعدة البيانات"], "fig": fig("02-dashboard", "", 0.62)},
    {"title": "شركتكم داخل المنصة", "sub": "مشاريعكم ومخططاتكم وترويستكم — كما هي",
     "bullets": ["مآب · مرتيل · مساكن جوار · ملاذ · مركز داود للأعمال · مساكن الفخامة 11", "مخطط الطابق المتكرر بعلامات الوحدات ونماذج 01–05 من كتيّب مآب",
                 "الأسعار ونِسب البيع افتراضية حتى تصلنا جداولكم"], "fig": fig("05-plans-typical-floor-markers", "", 0.62)},
    {"title": "من العرض إلى العقد", "sub": "رحلة العميل بمستندات بترويستكم",
     "bullets": ["عرض سعر بخطة سداد غير ربوية ⟵ حجز ⟵ تحقق من الهوية ⟵ عقد موقَّع", "فاتورة وإيصال PDF لكل قسط ودفعة، بشعاركم وختمكم ورمز تحقق وQR",
                 "الإرسال: طباعة، بريد، أو واتساب برابط موقَّع"], "fig": fig("QT-2026-00001-quote-p1", "", 0.95, web="web-assets/QT-2026-00001-quote-p1.jpg")},
    {"title": "تطبيق العميل", "sub": "وحدتي · الدفعات · الصيانة · المستندات · موقعي على المخطط",
     "bullets": ["يرى العميل تقدم البناء وصوره وموعد التسليم", "جدول أقساطه ودفعه الإلكتروني وإيصالاته", "عقده ومخطط طابقه وعلامة وحدته"], "fig": fig("40-client-home", "", 1.0), "phone": True},
    {"title": "التحصيل والمالية", "sub": "رادار السيولة · المتأخرات · المطابقة البنكية · حسابات الضمان",
     "bullets": ["تنبؤ شهري لكل حساب ضمان وذروة العجز وسببها", "عملاء معرّضون للتعثر ⟵ إعادة جدولة قبل التأخر", "غرامة التأخير تبرع لا إيراد؛ لا فوائد في أي خطة"], "fig": fig("15-finance-radar", "", 0.62)},
    {"title": "التسويق والتقارير", "sub": "لوحة تصنّف المشاريع، حملات بعرض غير ربوي، إعلانات من الاستوديو، عشرة تقارير جاهزة",
     "bullets": ["المشروع الذي يحتاج تدخلًا يظهر بإشاراته وإجراءاته", "إعلان على تصوّركم الحقيقي بنص عربي مركَّب بلا أشخاص", "تقارير PDF/CSV برسوم وجدولة بالبريد"], "fig": fig("ad-maab-launch-square", "", 1.0, web="web-assets/ad-maab-launch-square.jpg"), "square": True},
    {"title": "الحوكمة والأمان", "sub": "ما تطمئن إليه الإدارة",
     "bullets": ["سجل تدقيق مسلسل ببصمة لا يُعدَّل", "تحقق ثنائي، جلسات بأجهزتها، أدوار وصلاحيات في الخادم", "بيانات شخصية مشفّرة؛ تحقق عام من كل مستند برمز QR"], "fig": fig("28-audit-log", "", 0.62)},
    {"title": "ما يلزم للانطلاق", "sub": "من الشركة",
     "bullets": [i[0] for i in NEEDS["items"]], "fig": None, "two_col": True},
    {"title": "صيغتا التعاون", "sub": "بلا أرقام في هذه الشريحة — تُترك للاجتماع",
     "table": True},
    {"kind": "end"},
]


def build_slides_pdf(out: Path):
    p = Guide(landscape=True)
    p.set_margins(14, 14, 14)
    p.set_auto_page_break(auto=False)
    for i, s in enumerate(SLIDES, 1):
        p.cover = True
        p.add_page()
        if s.get("kind") == "cover":
            p.set_fill_color(*INK)
            p.rect(0, 0, p.w, p.h, style="F")
            p.set_fill_color(*GOLD)
            p.rect(0, p.h - 5, p.w, 5, style="F")
            f = crop("maab-render-02", 0.72, True, SAMPLES / "maab-render-02.jpg")
            p.image(str(f), x=14, y=30, w=120)
            p.mabaniq_mark(p.w - 14 - 14, 24, 14)
            p.image(str(SAMPLES / "almukhatat-logo.png"), x=p.w - 14 - 14 - 60 - 36, y=22, w=36)
            p.set_xy(140, 70)
            p.set_font("Tajawal", "B", 26)
            p.set_text_color(255, 255, 255)
            p.multi_cell(p.w - 154, 14, TITLE, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            p.set_x(140)
            p.set_font("Tajawal", "", 16)
            p.set_text_color(*GOLD)
            p.multi_cell(p.w - 154, 9, SUBTITLE, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            p.set_x(140)
            p.set_font("Tajawal", "", 11)
            p.set_text_color(200, 205, 215)
            p.multi_cell(p.w - 154, 7, f"عرض الاجتماع الأول · {DATE_LINE}\nجدوى للدراسات والتطوير", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            continue
        if s.get("kind") == "end":
            p.set_fill_color(*INK)
            p.rect(0, 0, p.w, p.h, style="F")
            p.set_xy(14, 60)
            p.set_font("Tajawal", "B", 28)
            p.set_text_color(255, 255, 255)
            p.multi_cell(p.w - 28, 15, "نقترح اجتماع عرض حي على بيانات مآب", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            p.set_font("Tajawal", "", 14)
            p.set_text_color(*GOLD)
            p.multi_cell(p.w - 28, 9, "ساعة واحدة في مقر الشركة · نستلم قائمة الاحتياجات · نتفق على الصيغة والجدول", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            p.ln(8)
            p.set_font("Tajawal", "", 12)
            p.set_text_color(200, 205, 215)
            p.multi_cell(p.w - 28, 8, f"{LIVE}\nجدوى للدراسات والتطوير — مسقط · jadwa.om", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            continue
        # شريحة عادية
        p.set_fill_color(*GOLD)
        p.rect(p.w - 14 - 3, 14, 3, 22, style="F")
        p.set_xy(14, 14)
        p.set_font("Tajawal", "B", 22)
        p.set_text_color(*INK)
        p.cell(p.w - 28 - 6, 12, s["title"], align="R")
        p.set_xy(14, 26)
        p.set_font("Tajawal", "", 11.5)
        p.set_text_color(*MUTED)
        p.cell(p.w - 28 - 6, 8, s["sub"], align="R")
        p.set_font("Tajawal", "", 8)
        p.set_xy(14, p.h - 12)
        p.cell(p.w - 28, 5, f"{i} / {len(SLIDES)} · بيانات العرض افتراضية", align="L")
        p.set_xy(14, p.h - 12)
        p.cell(p.w - 28, 5, "مبانيك × المخطط العقارية", align="R")
        if s.get("table"):
            ws = [(p.w - 28) * x for x in (0.2, 0.4, 0.4)]
            y = 44
            xr = p.w - 14
            p.set_fill_color(*INK)
            p.set_text_color(255, 255, 255)
            p.set_font("Tajawal", "B", 11)
            for hname, wd in zip(MODELS["heads"], ws):
                p.set_xy(xr - wd, y)
                p.cell(wd, 10, hname, align="C", fill=True)
                xr -= wd
            y += 10
            for ri, row in enumerate(MODELS["rows"]):
                rh = 16
                xr = p.w - 14
                p.set_fill_color(*(PALE if ri % 2 == 0 else (255, 255, 255)))
                p.rect(14, y, p.w - 28, rh, style="F")
                for ci, (cell, wd) in enumerate(zip(row, ws)):
                    p.set_xy(xr - wd + 2, y + 2)
                    p.set_font("Tajawal", "B" if ci == 0 else "", 10)
                    p.set_text_color(*INK)
                    if cell:
                        p.multi_cell(wd - 4, 5.5, cell, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    else:
                        p.set_draw_color(*LINE)
                        p.set_dash_pattern(dash=1.2, gap=1.2)
                        p.rect(xr - wd + 5, y + 3, wd - 10, rh - 6)
                        p.set_dash_pattern()
                    xr -= wd
                y += rh
            continue
        if s.get("two_col"):
            items = s["bullets"]
            half = (len(items) + 1) // 2
            colw = (p.w - 28 - 8) / 2
            for ci, chunk in enumerate((items[:half], items[half:])):
                x = p.w - 14 - colw - ci * (colw + 8)
                y = 48
                for j, it in enumerate(chunk, 1 + ci * half):
                    p.set_fill_color(*GOLD)
                    p.set_text_color(255, 255, 255)
                    p.set_font("Tajawal", "B", 11)
                    p.set_xy(x + colw - 10, y)
                    p.cell(10, 10, str(j), align="C", fill=True)
                    p.set_xy(x, y)
                    p.set_font("Tajawal", "B", 12.5)
                    p.set_text_color(*INK)
                    p.multi_cell(colw - 12, 10, it, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    y += 18
            continue
        # نص + صورة
        has_fig = s.get("fig") is not None
        tw = (p.w - 28) * (0.46 if has_fig else 1)
        p.set_xy(p.w - 14 - tw, 46)
        y = 46
        for it in s["bullets"]:
            p.set_fill_color(*GOLD)
            p.ellipse(p.w - 14 - 3.4, y + 3.4, 2.2, 2.2, style="F")
            p.set_xy(p.w - 14 - tw, y)
            p.set_font("Tajawal", "", 13 if has_fig else 15)
            p.set_text_color(*INK)
            h = p.multi_cell(tw - 7, 7.6, it, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT, dry_run=True, output="HEIGHT")
            p.set_xy(p.w - 14 - tw, y)
            p.multi_cell(tw - 7, 7.6, it, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            y += h + 5
        if has_fig:
            f = s["fig"]
            im = Image.open(f["path"])
            iw, ih = im.size
            box_w, box_h = p.w - 28 - tw - 8, p.h - 46 - 18
            w = box_w
            h = w * ih / iw
            if h > box_h:
                h = box_h
                w = h * iw / ih
            x = 14 + (box_w - w) / 2
            p.set_draw_color(*LINE)
            p.rect(x - 0.5, 46 - 0.5, w + 1, h + 1)
            p.image(str(f["path"]), x=x, y=46, w=w, h=h)
    p.output(str(out))
    print("PDF", out.name, p.page_no(), "شريحة")


# ──────────────────────────────────────────────────────────────────────────────────────────────────── HTML


def esc(t):
    return html.escape(t).replace("**", "")


def build_html(out: Path):
    def figure_html(f, cls=""):
        return f'<figure class="{cls}"><img src="{f["web"]}" alt="{esc(f["caption"])}" loading="lazy"><figcaption>{esc(f["caption"])}</figcaption></figure>'

    def section(id_, kicker, title, lead, bullets=None, figs=None, side=False, extra=""):
        b = "".join(f"<li>{esc(x)}</li>" for x in (bullets or []))
        fg = "".join(figure_html(f) for f in (figs or []))
        return (f'<section id="{id_}"><div class="kicker">{esc(kicker)}</div><h2>{esc(title)}</h2>'
                + (f'<p class="lead">{esc(lead)}</p>' if lead else "") + (f"<ul>{b}</ul>" if b else "")
                + (f'<div class="figs {"side" if side else ""}">{fg}</div>' if fg else "") + extra + "</section>")

    toc = [("intro", INTRO["title"]), ("why", "لماذا الآن"), ("overview", OVERVIEW["title"])] + [(f"t{i}", s["title"]) for i, s in enumerate(TOUR)] \
        + [("needs", NEEDS["title"]), ("models", MODELS["title"]), ("limits", LIMITS["title"]), ("close", CLOSE["title"])]
    parts = []
    parts.append(section("intro", "مقدمة", INTRO["title"], INTRO["lead"], INTRO["bullets"]))
    cards = "".join(f'<div class="card"><h3>{i}. {esc(h)}</h3><p>{esc(t)}</p></div>' for i, (h, t) in enumerate(WHY["cards"], 1))
    parts.append(section("why", "لماذا الآن", WHY["title"], WHY["lead"], extra=f'<div class="cards">{cards}</div><p class="green">{esc(WHY["close"])}</p>'))
    cols = "".join(f'<div class="col"><h3>{esc(h)}</h3><ul>{"".join(f"<li>{esc(i)}</li>" for i in items)}</ul></div>' for h, items in OVERVIEW["columns"])
    parts.append(section("overview", "نظرة عامة", OVERVIEW["title"], OVERVIEW["lead"], extra=f'<div class="cols">{cols}</div><div class="figs">{figure_html(OVERVIEW["figures"][0])}</div>'))
    for i, s in enumerate(TOUR):
        extra = f'<div class="figs">{figure_html(s["figures2"][0])}</div>' if s.get("figures2") else ""
        if s.get("figures2_side"):
            extra += f'<div class="figs side">{"".join(figure_html(f) for f in s["figures2_side"])}</div>'
        parts.append(section(f"t{i}", s["sec"], s["title"], s["lead"], s.get("bullets"), s["figures"], s.get("side", False), extra))
    needs = "".join(f'<li><b>{esc(h)}</b><span>{esc(t)}</span></li>' for h, t in NEEDS["items"])
    parts.append(section("needs", "الانطلاق", NEEDS["title"], NEEDS["lead"], extra=f'<ol class="needs">{needs}</ol>'))
    rows = "".join("<tr>" + "".join(f'<{"th" if ci == 0 else "td"}>{esc(c) if c else "<span class=blank></span>"}</{"th" if ci == 0 else "td"}>' for ci, c in enumerate(r)) + "</tr>" for r in MODELS["rows"])
    heads = "".join(f"<th>{esc(h)}</th>" for h in MODELS["heads"])
    parts.append(section("models", "صيغتا التعاون", MODELS["title"], MODELS["lead"], extra=f'<table><thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table><p class="muted">الخانات الفارغة تُملأ في الاجتماع. في الحالتين: ترخيص واحد لمطوّر واحد، والبيانات ملك الشركة، ودليل التشغيل ودليل الأمان ضمن التسليم.</p>'))
    parts.append(section("limits", "بصراحة", LIMITS["title"], None, LIMITS["items"], extra=f'<p class="green">{esc(LIMITS["close"])}</p>'))
    parts.append(section("close", "الخطوة التالية", CLOSE["title"], CLOSE["lead"], CLOSE["bullets"], [{"web": "web-assets/maab-render-03.jpg", "caption": "مشروع مآب — المدخل والمحلات (من كتيّب الشركة)."}]))
    nav = "".join(f'<a href="#{i}">{esc(t)}</a>' for i, t in toc)
    doc = f"""<!doctype html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>مبانيك للمخطط العقارية</title>
<meta name="description" content="دليل ترويجي مصوَّر لمنصة مبانيك بمشاريع شركة المخطط العقارية — من الحجز إلى التسليم">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Kufi+Arabic:wght@400;500;700&display=swap">
<script>document.documentElement.setAttribute("dir","rtl");document.documentElement.setAttribute("lang","ar");</script>
<style>
:root{{--ink:#172030;--gold:#d4a64a;--muted:#6e7887;--line:#d6dae2;--pale:#f7f8fa;--bg:#ffffff;--card:#ffffff;--green:#247854}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--ink:#e8ebf0;--muted:#a3abb8;--line:#2d3545;--pale:#1b2230;--bg:#0f1521;--card:#161d2b;--green:#6fd3a0}}}}
:root[data-theme="dark"]{{--ink:#e8ebf0;--muted:#a3abb8;--line:#2d3545;--pale:#1b2230;--bg:#0f1521;--card:#161d2b;--green:#6fd3a0}}
*{{box-sizing:border-box}}html{{direction:rtl}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Noto Kufi Arabic","Tajawal",system-ui,sans-serif;line-height:1.85;direction:rtl;text-align:start}}
.wrap{{max-width:1080px;margin:0 auto;padding:0 16px 60px}}
header.hero{{background:#172030;color:#fff;padding:48px 16px 40px;border-block-end:6px solid var(--gold)}}
header.hero .wrap{{padding-block-end:0}}
.logos{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-block-end:28px}}
.mark{{display:flex;align-items:center;gap:12px}}.mark .m{{width:52px;height:52px;border-radius:12px;background:var(--gold);color:#172030;font-weight:700;font-size:30px;display:grid;place-items:center}}
.mark b{{font-size:22px}}.mark small{{display:block;color:#aab2c0;font-size:12px}}
.logos img{{height:52px;background:#fff;border-radius:8px;padding:4px}}
header h1{{font-size:clamp(26px,4vw,40px);margin:0 0 6px;line-height:1.4}}header .sub{{color:var(--gold);font-size:clamp(17px,2.4vw,22px);margin:0 0 14px}}
header .tag{{font-size:15px;color:#dfe3ea;margin:0 0 20px}}header .date{{color:var(--gold);font-weight:700}}header .meta{{color:#aab2c0;font-size:13px}}
nav.toc{{position:sticky;top:0;background:var(--bg);border-block-end:1px solid var(--line);z-index:5;overflow-x:auto;white-space:nowrap;padding:8px 16px;direction:rtl}}
nav.toc a{{display:inline-block;margin-inline-end:14px;color:var(--muted);text-decoration:none;font-size:13px}}nav.toc a:hover{{color:var(--gold)}}
section{{padding:36px 0 8px;border-block-end:1px solid var(--line)}}
.kicker{{color:var(--gold);font-weight:700;font-size:13px;letter-spacing:.02em}}h2{{font-size:clamp(21px,3vw,28px);margin:4px 0 10px;line-height:1.5}}
.lead{{font-size:17px;margin:0 0 12px}}ul{{padding-inline-start:22px;margin:0 0 16px}}li{{margin:6px 0}}li::marker{{color:var(--gold)}}
.figs{{display:grid;gap:18px;margin:14px 0 24px}}.figs.side{{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}}
figure{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px}}figure img{{width:100%;height:auto;display:block;border-radius:6px}}
figcaption{{color:var(--muted);font-size:13px;margin-block-start:8px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:12px 0}}
.card{{background:var(--pale);border-inline-start:4px solid var(--gold);border-radius:8px;padding:12px 16px}}.card h3{{margin:0 0 6px;font-size:17px}}.card p{{margin:0;color:var(--muted)}}
.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:10px 0 18px}}.col{{background:var(--pale);border-block-start:4px solid var(--gold);border-radius:8px;padding:10px 14px}}
.col h3{{margin:0 0 6px;font-size:15px}}.col ul{{margin:0;padding-inline-start:18px;font-size:14px}}
.green{{color:var(--green);font-weight:700;font-size:16px}}.muted{{color:var(--muted);font-size:14px}}
ol.needs{{padding-inline-start:24px}}ol.needs li{{margin:10px 0}}ol.needs b{{display:block;font-size:16px}}ol.needs span{{color:var(--muted)}}
table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:15px}}th,td{{border:1px solid var(--line);padding:10px 12px;text-align:start;vertical-align:top}}
thead th{{background:#172030;color:#fff;text-align:center}}tbody th{{background:var(--pale);width:20%}}.blank{{display:block;height:26px;border:1px dashed var(--line);border-radius:6px}}
footer{{color:var(--muted);font-size:13px;padding:24px 16px;text-align:center}}
code,.ltr{{direction:ltr;unicode-bidi:isolate;display:inline-block}}
</style></head>
<body>
<header class="hero"><div class="wrap">
<div class="logos"><div class="mark"><div class="m">م</div><div><b>مبانيك</b><small>منصة المطوّر العقاري · جدوى</small></div></div><img src="web-assets/almukhatat-logo.png" alt="شعار شركة المخطط العقارية"></div>
<h1>{esc(TITLE)}</h1><p class="sub">{esc(SUBTITLE)}</p><p class="tag">«{esc(TAGLINE)}»</p>
<p class="date">{esc(DATE_LINE)}</p><p class="meta">دليل ترويجي مصوَّر — لقطات حقيقية من المنصة بمشاريع الشركة ومخططاتها وترويستها (الإصدار 0.13.0) · إعداد: جدوى للدراسات والتطوير</p>
</div></header>
<nav class="toc">{nav}</nav>
<main class="wrap">{"".join(parts)}</main>
<footer>جدوى للدراسات والتطوير · مبانيك 0.13.0 · {esc(DATE_LINE)} · كل الأرقام في هذا الدليل افتراضية · بيئة العرض: <span class="ltr">{LIVE}</span></footer>
</body></html>"""
    out.write_text(doc, encoding="utf-8")
    print("HTML", out.name, len(doc) // 1024, "KB")


if __name__ == "__main__":
    import shutil
    shutil.copy(SAMPLES / "maab-render-03.jpg", PKG / "web-assets" / "maab-render-03.jpg")
    build_guide_pdf(PKG / "mabaniq-almukhatat-guide.pdf")
    build_slides_pdf(PKG / "mabaniq-almukhatat-slides.pdf")
    build_html(PKG / "index.html")
