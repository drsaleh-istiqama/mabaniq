"""Build the public landing pages (0.14.x): one content source → web/landing.html (Arabic, RTL, served on /) and
web/landing-en.html (English, LTR, served on /en). Run after editing CONTENT or replacing screenshots:

    python tools/build_landing.py && npm run check && npm run build

Rules baked in (docs/LANDING.md): Arabic first, explicit dir/lang on <html>, Western digits only, Hijri before Gregorian,
no prices, no client names, no invented numbers (the fact chips are counts of what the product ships), no people in images,
the approved Mabaneek logo (web/img/logo-*.{png,svg}) and its green identity, short copy with icons/diagrams instead of long
paragraphs, JSON-LD (Organization · SoftwareApplication · FAQPage), canonical/hreflang/OG with the `__PUBLIC_URL__` placeholder
that backend/landing.py replaces from MABANIQ_PUBLIC_URL at request time. Screenshots come from web/img/landing/
(tools/landing_shoot.mjs + tools/landing_assets.py) with their real dimensions.
"""
from __future__ import annotations

import html
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
IMG = WEB / "img" / "landing"
PH = "__PUBLIC_URL__"
UPDATED = {"hijri": "30 ربيع الآخر 1448هـ", "iso": "2026-10-11"}

# ─────────────────────────────────────────────────────────────────────────── inline icons (stroke, currentColor)
ICONS = {
    "building": '<path d="M4 21V5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v16"/><path d="M14 10h5a1 1 0 0 1 1 1v10"/><path d="M8 8h2M8 12h2M8 16h2M17 14h1M17 18h1M2 21h20"/>',
    "scatter": '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="8" r="2"/><circle cx="9" cy="17" r="2"/><circle cx="17" cy="17" r="2"/><path d="M8 7l8 1M10 15l5 1M7 8l2 7"/>',
    "trend": '<path d="M3 17l5-5 4 4 8-8"/><path d="M15 8h5v5"/><path d="M3 21h18"/>',
    "phone": '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    "quote": '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h6M9 16h6"/>',
    "book": '<path d="M4 6a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2z"/><path d="M4 6v14M9 8h6"/>',
    "id": '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="12" r="2"/><path d="M6 17c0-1.7 1.3-3 3-3s3 1.3 3 3M15 10h3M15 14h3"/>',
    "sign": '<path d="M4 20h16"/><path d="M4 16c3-6 6-7 8-5s3 3 6-2"/><path d="M16 4l4 4-9 9H7v-4z"/>',
    "coins": '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
    "key": '<circle cx="8" cy="14" r="4"/><path d="M11 11l9-9M16 6l3 3M14 8l2 2"/>',
    "dashboard": '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="10" width="8" height="11" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/>',
    "grid": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16M4 15h16M10 4v16M15 4v16"/>',
    "doc": '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h6M9 16h4"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "megaphone": '<path d="M3 11v2a2 2 0 0 0 2 2h2l6 4V5L7 9H5a2 2 0 0 0-2 2z"/><path d="M17 9a4 4 0 0 1 0 6"/>',
    "report": '<path d="M5 3h14v18H5z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "lang": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "balance": '<path d="M12 3v18M4 7h16M6 7l-3 7a3 3 0 0 0 6 0zM18 7l-3 7a3 3 0 0 0 6 0z"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "history": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "cloud": '<path d="M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9a4 4 0 0 1 0 9z"/>',
    "server": '<rect x="4" y="4" width="16" height="6" rx="1.5"/><rect x="4" y="14" width="16" height="6" rx="1.5"/><path d="M8 7h.01M8 17h.01"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "land": '<path d="M3 20l6-9 4 5 3-3 5 7z"/><path d="M3 20h18"/><circle cx="17" cy="7" r="2"/>',
    "crane": '<path d="M4 21h16M8 21V8l8-4v17"/><path d="M8 8h12M18 8v4"/>',
}


def icon(name: str, cls: str = "ic") -> str:
    return f'<span class="{cls}" aria-hidden="true"><svg viewBox="0 0 24 24">{ICONS[name]}</svg></span>'


# ─────────────────────────────────────────────────────────────────────────── content
CONTENT = {
    "ar": {
        "dir": "rtl", "other_lang": "en", "other_label": "English", "other_href": "/en", "home": "/", "privacy": "/privacy", "logo": "logo-ar",
        "title": "مبانيك | منصة إدارة التطوير العقاري — من الحجز إلى التسليم",
        "description": "مبانيك منصة واحدة تدير دورة البيع العقاري كاملة للمطوّر: المخزون، عروض الأسعار والعقود، التحصيل والسيولة، تطبيق العميل، التسويق والتقارير. عربية أولًا، هجري أولًا، تمويل إسلامي فقط.",
        "og_image": "/og.png",
        "nav": [("#features", "الميزات"), ("#journey", "رحلة العميل"), ("#why", "لماذا مبانيك"), ("#faq", "الأسئلة")],
        "login": "تسجيل الدخول", "cta": "اطلب عرضًا حيًّا", "cta2": "استكشف الميزات", "menu": "القائمة", "skip": "انتقل إلى المحتوى",
        "hero": {
            "eyebrow": "منصة إدارة التطوير العقاري · منتج جدوى للدراسات والتطوير",
            "h1": "منصة واحدة تدير دورة البيع العقاري كاملة — من الحجز إلى التسليم",
            "lead": "مخزون حي، عروض أسعار وعقود ومستندات بترويستك، تحصيل وسيولة، تطبيق للعميل، وتقارير — عربية أولًا، هجري أولًا، وتمويل إسلامي فقط.",
            "facts": [("10", "تقارير جاهزة"), ("6", "قوالب إعلانات"), ("4", "مستندات PDF بترويستك"), ("7", "أدوار جاهزة")],
            "note": "اللقطات حقيقية من بيئة العرض ببيانات تجريبية لا تخص أي شركة.",
            "img": ("dashboard", "لوحة القيادة في مبانيك: المؤشرات الأربعة وصندوق القرارات مرتّبًا بالأولوية"),
            "float": "صندوق القرارات يخبرك بما يحتاج قرارك اليوم",
        },
        "problems": {
            "h2": "ثلاث مشكلات يعيشها كل مطوّر",
            "lead": "مع كل مشروع جديد تتضاعف الملفات والمحادثات، وتبتعد الحقيقة الواحدة.",
            "cards": [("scatter", "حجوزات وتحصيل مشتّت", "جداول وواتساب وصور إيصالات؛ والمطابقة البنكية عملٌ يدوي آخر الشهر."),
                      ("trend", "التعثر البيعي يُكتشف متأخرًا", "لا إشارة مبكرة لتباطؤ البيع؛ التسعير والحملة والوسطاء قرارات بلا بيانات."),
                      ("phone", "العميل لا يرى وحدته", "يسأل عن تقدم البناء وعقده وقسطه القادم، ويُجاب بمكالمة كل مرة.")],
            "close": "مبانيك تضع الثلاثة في مكان واحد، ولوحة تخبر الإدارة بما يحتاج قرارها اليوم.",
        },
        "journey": {
            "h2": "رحلة العميل في ست خطوات",
            "lead": "كل خطوة تولّد مستندها وتُقيَّد في سجل التدقيق، ويرى العميل أثرها في تطبيقه.",
            "steps": [("quote", "عرض سعر", "مرقّم بخطة سداد بلا فوائد"), ("book", "حجز", "يحوّل العرض بضغطة ويُنشئ الأقساط"),
                      ("id", "تحقق من الهوية", "KYC وتقييم مخاطر"), ("sign", "عقد موقَّع", "بترويستك وبصمة محتوى"),
                      ("coins", "تحصيل وفواتير", "فاتورة وإيصال لكل دفعة"), ("key", "تسليم وشهادة", "لا تسليم بلا شروطه")],
        },
        "cycle": {
            "h2": "دورة التطوير الثلاثية في منصة واحدة",
            "lead": "من الأرض إلى التشغيل، وفوقها طبقتان مشتركتان: المالية والحوكمة.",
            "stages": [("land", "الأرض والتراخيص", ["الأراضي", "دراسات الجدوى", "التراخيص"]),
                       ("crane", "البيع والإنشاء", ["المخزون والتسعير", "العملاء والتسويق", "العروض والعقود", "المستخلصات"]),
                       ("key", "التسليم والتشغيل", ["التسليم والعيوب", "اتحاد الملاك", "خدمة العملاء", "التأجير"])],
            "cross": ("عبر الدورة:", ["السيولة والتعثر", "الفواتير والضمان", "التقارير", "سجل التدقيق", "الإدارة والأمان"]),
        },
        "features_h2": "الميزات بلقطات حقيقية",
        "features_lead": "كل ما تراه يعمل اليوم على بيئة العرض ومغطّى باختبارات آلية.",
        "features": [
            {"icon": "dashboard", "h3": "لوحة القيادة", "p": "لا أرقامًا فقط؛ قرارات مرتّبة بالأولوية والأثر المالي، كلٌّ بمصدره وحالته.",
             "chips": ["رادار السيولة", "التحقق من الإنجاز", "نموذج التعثر", "التسعير الديناميكي"], "imgs": [("dashboard", "لوحة القيادة: المؤشرات وصندوق القرارات")]},
            {"icon": "grid", "h3": "المخزون والمخططات", "p": "مخطط المبنى بحالات الوحدات، وأداء الشرائح مع توصية التسعير، ومخططات الطوابق بعلامات الوحدات.",
             "chips": ["متاحة · محجوزة · مباعة", "علامات على المخطط", "تسعير ديناميكي"], "imgs": [("inventory", "المخزون والتسعير: مخطط المبنى بحالات الوحدات")]},
            {"icon": "doc", "h3": "عروض الأسعار والعقود والمستندات", "p": "عرض سعر وعقد وفاتورة وإيصال PDF بترويستك وشعارك وختمك، بالهجري أولًا، مع رمز تحقق وQR.",
             "chips": ["طباعة", "بريد بمرفق", "رابط واتساب موقَّع", "صفحة تحقق عامة"],
             "imgs": [("doc-quote", "عرض سعر صادر من المنصة بترويسة المطوّر"), ("doc-invoice", "فاتورة صادرة من المنصة بترويسة المطوّر")], "layout": "two"},
            {"icon": "phone", "h3": "تطبيق العميل", "p": "وحدتي وتقدم البناء، الدفعات والقسط القادم، الصيانة، إعادة البيع، والمستندات — من هاتفه.",
             "chips": ["مخطط طابقه", "خروج من كل الأجهزة", "طلبات الخصوصية"],
             "imgs": [("client-home", "تطبيق العميل: وحدتي وتقدم البناء"), ("client-payments", "تطبيق العميل: الدفعات")], "layout": "phones"},
            {"icon": "coins", "h3": "التحصيل والسيولة", "p": "تنبؤ شهري لكل حساب ضمان، ومتأخرات بأعمارها، وإعادة جدولة قبل التعثر لا بعده.",
             "chips": ["حساب ضمان لكل مشروع", "مطابقة بنكية", "ضريبة القيمة المضافة", "شرط التبرع بدل الغرامة"],
             "imgs": [("finance", "السيولة والتعثر: التنبؤ الشهري"), ("billing", "الفواتير والضمان والمطابقة البنكية")], "layout": "two"},
            {"icon": "megaphone", "h3": "التسويق والاستوديو", "p": "تصنيف كل مشروع من بياناته الحية، حملات بعرض غير ربوي ورمز تتبع، وإعلانات مركَّبة من بيانات المشروع.",
             "chips": ["6 قوالب × 3 مقاسات", "كلفة العميل", "تنبيهات السوق"],
             "imgs": [("marketing", "لوحة التسويق"), ("ad-studio", "استوديو الإعلانات")], "layout": "two"},
            {"icon": "report", "h3": "التقارير والتحليلات", "p": "عشرة تقارير جاهزة بالنقر، ومنشئ تقارير بلا SQL، وتصدير CSV وPDF برسوم، وجدولة بالبريد.",
             "chips": ["المحفظة", "التحصيل والمتأخرات", "قمع العملاء", "تصدير ERPNext"], "imgs": [("report", "تقرير لوحة المحفظة")]},
            {"icon": "shield", "h3": "الأمان والحوكمة", "p": "سجل تدقيق مسلسل ببصمة لا يُعدَّل، بيانات هوية مشفّرة، وعزل كل مطوّر على مستوى قاعدة البيانات.",
             "chips": ["تحقق ثنائي", "جلسات بأجهزتها", "دخول Google", "CSP بلا مضيف خارجي"],
             "imgs": [("audit", "سجل التدقيق"), ("security", "أماني: التحقق الثنائي والجلسات")], "layout": "two"},
        ],
        "why": {
            "h2": "لماذا مبانيك", "lead": "قواعد بيتية لا تتغيّر بتغيّر العميل.",
            "items": [("lang", "عربية أولًا", "واجهة من اليمين إلى اليسار بمصطلحات السوق، وإنجليزية للهيكل."),
                      ("moon", "هجري أولًا", "كل تاريخ يواجه العميل بالهجري ثم الميلادي."),
                      ("balance", "تمويل إسلامي فقط", "لا فوائد في أي خطة أو عرض؛ التأخير تبرع لا إيراد."),
                      ("lock", "عزل في قاعدة البيانات", "صفوف كل مطوّر معزولة بمحرك القاعدة لا بشيفرة التطبيق."),
                      ("history", "سجل تدقيق لا يُمحى", "سلسلة بصمات لكل فعل؛ لا تعديل ولا حذف.")],
        },
        "models": {
            "h2": "صيغتا التعاون", "lead": "من يشغّل، ومن يملك، وكيف تصل التحديثات. الأرقام تُترك للاجتماع.",
            "cards": [("cloud", "اشتراك", "على منصة جدوى المستضافة", ["ترخيص استخدام؛ التشغيل لدى جدوى", "عزل بصفوفك؛ بياناتك ملكك وتُصدَّر عند الطلب", "تحديثات تلقائية مع كل إصدار", "النسخ والدعم والتدريب ضمن الاشتراك"]),
                      ("server", "نسخة خاصة", "على بنية الشركة", ["نسخة مرخَّصة على خوادمكم (حاويات + PostgreSQL)", "قاعدة بيانات خاصة بالكامل", "التحديثات بحسب اتفاق الصيانة", "دليل التشغيل والأمان ضمن التسليم"])],
            "note": "في الحالتين: ترخيص واحد لمطوّر واحد، والبيانات ملك الشركة.",
        },
        "faq": {
            "h2": "أسئلة شائعة",
            "items": [("هل المنصة جاهزة الآن؟", "تعمل على بيئة عرض سحابية ببيانات تجريبية وكل الميزات مُختبرة آليًا؛ التشغيل الفعلي يبدأ بعد اجتماع العرض وتهيئة بياناتك."),
                      ("هل أحتاج تثبيتًا؟", "لا؛ تطبيق ويب للموظفين والعملاء والوسطاء. النسخة الخاصة تُنشر على خوادمكم بحاويات جاهزة."),
                      ("كيف تُعزل بياناتي؟", "بعزل الصفوف على مستوى قاعدة البيانات (RLS): المحرك يمنع رؤية صفوف مطوّر آخر. والنسخة الخاصة قاعدة مستقلة."),
                      ("هل تدعم التمويل الإسلامي؟", "التمويل الإسلامي فقط؛ لا فوائد في أي خطة أو عرض، والتأخير يُعالَج بشرط التبرع الذي يعتمد صياغته مستشاركم الشرعي."),
                      ("هل المستندات بهويتي؟", "نعم: ترويستك وشعارك وختمك وتوقيعك المعتمد، ورمز تحقق وQR إلى صفحة عامة بلا بيانات شخصية."),
                      ("ماذا يرى العميل؟", "وحدته وتقدم البناء، أقساطه، عقده وفواتيره وإيصالاته، مخطط طابقه، الصيانة، والتصويت في اتحاد الملاك."),
                      ("هل تتكامل مع المحاسبة؟", "تصدير القيود بصيغة ERPNext والتقارير CSV/PDF؛ بوابة الدفع وواتساب للأعمال وبريد الشركة تُفعَّل عند التشغيل بحساباتكم."),
                      ("كيف أحصل على عرض؟", "املأ النموذج أدناه؛ يتواصل فريق جدوى خلال يومي عمل لاجتماع ساعة نعرض فيه المنصة حيّة.")],
        },
        "demo": {
            "h2": "اطلب عرضًا حيًّا", "lead": "اجتماع لمدة ساعة: نعرض المنصة حيّة، ونستلم احتياجاتك، ونتفق على الصيغة والجدول.",
            "side": [("check", "لا يُنشأ حساب ولا تُشارك بياناتك مع طرف ثالث"), ("clock", "نردّ خلال يومي عمل"), ("lang", "العرض بالعربية، ويمكن بالإنجليزية")],
            "name": "الاسم", "company": "الشركة", "email": "البريد الإلكتروني", "phone": "رقم الهاتف", "projects": "عدد المشاريع الحالية",
            "message": "رسالة (اختياري)", "message_ph": "ما الذي تريد رؤيته في العرض؟", "send": "أرسل الطلب",
            "consent": "بإرسال الطلب توافق على", "privacy": "سياسة الخصوصية.",
        },
        "footer": {"org": "جدوى للدراسات والتطوير", "org_url": "https://jadwa.om", "place": "مسقط، سلطنة عُمان",
                   "links": [("/privacy", "سياسة الخصوصية"), ("/login", "تسجيل الدخول"), ("/en", "English")],
                   "updated": f"آخر تحديث: {UPDATED['hijri']} الموافق {UPDATED['iso']}م"},
        "ld_org_name": "جدوى للدراسات والتطوير", "ld_app_name": "مبانيك | Mabaneek", "ld_app_desc": "منصة إدارة التطوير العقاري من الحجز إلى التسليم",
    },
    "en": {
        "dir": "ltr", "other_lang": "ar", "other_label": "العربية", "other_href": "/", "home": "/en", "privacy": "/en/privacy", "logo": "logo-full",
        "title": "Mabaneek | Real-estate development platform — from booking to handover",
        "description": "Mabaneek is one platform for a developer's whole sales cycle: inventory, quotes and contracts, collections and cash flow, a customer app, marketing and reports. Arabic-first, Hijri-first, Islamic finance only.",
        "og_image": "/og-en.png",
        "nav": [("#features", "Features"), ("#journey", "Customer journey"), ("#why", "Why Mabaneek"), ("#faq", "FAQ")],
        "login": "Sign in", "cta": "Request a live demo", "cta2": "Explore the features", "menu": "Menu", "skip": "Skip to content",
        "hero": {
            "eyebrow": "Real-estate development platform · a Jadwa for Studies & Development product",
            "h1": "One platform for the whole property sales cycle — from booking to handover",
            "lead": "Live inventory, quotes, contracts and documents on your letterhead, collections and cash flow, a customer app and reports — Arabic-first, Hijri-first, Islamic finance only.",
            "facts": [("10", "ready reports"), ("6", "ad templates"), ("4", "PDF documents on your letterhead"), ("7", "ready roles")],
            "note": "Screenshots are real, from the demo environment, with sample data that belongs to no company.",
            "img": ("dashboard", "The Mabaneek dashboard: four indicators and the decision box ordered by priority"),
            "float": "The decision box tells you what needs a decision today",
        },
        "problems": {
            "h2": "Three problems every developer lives with",
            "lead": "With every new project the files and chats multiply and the single truth drifts away.",
            "cards": [("scatter", "Scattered bookings and collections", "Spreadsheets, WhatsApp and photos of receipts; bank reconciliation is a manual month-end job."),
                      ("trend", "Slow sales are noticed too late", "No early signal of a slowdown; pricing, campaigns and brokers are decided without data."),
                      ("phone", "The customer cannot see their unit", "They ask about progress, their contract and the next instalment — and get a call every time.")],
            "close": "Mabaneek puts all three in one place, with a dashboard that tells management what needs a decision today.",
        },
        "journey": {
            "h2": "The customer journey in six steps",
            "lead": "Every step issues its document, lands in the audit log, and shows in the customer's app.",
            "steps": [("quote", "Quote", "numbered, interest-free plan"), ("book", "Booking", "converts the quote, creates instalments"),
                      ("id", "Identity check", "KYC and risk rating"), ("sign", "Signed contract", "your letterhead, content hash"),
                      ("coins", "Collections", "invoice and receipt per payment"), ("key", "Handover", "no handover without its conditions")],
        },
        "cycle": {
            "h2": "The three-stage development cycle in one platform",
            "lead": "From land to operations, with two shared layers on top: finance and governance.",
            "stages": [("land", "Land and permits", ["Land", "Feasibility", "Permits"]),
                       ("crane", "Sales and construction", ["Inventory and pricing", "Leads and marketing", "Quotes and contracts", "Payment certificates"]),
                       ("key", "Handover and operations", ["Handover and snags", "Owners' association", "Customer service", "Leasing"])],
            "cross": ("Across the cycle:", ["Cash flow and default risk", "Invoices and escrow", "Reports", "Audit log", "Administration and security"]),
        },
        "features_h2": "Features, with real screenshots",
        "features_lead": "Everything you see runs today on the demo environment and is covered by automated tests.",
        "features": [
            {"icon": "dashboard", "h3": "Dashboard", "p": "Not just numbers: decisions ordered by priority and financial impact, each with its source and status.",
             "chips": ["Cash radar", "Progress verification", "Default model", "Dynamic pricing"], "imgs": [("dashboard", "Dashboard: indicators and the decision box")]},
            {"icon": "grid", "h3": "Inventory and plans", "p": "The building map with unit statuses, segment performance with a pricing recommendation, and floor plans with unit markers.",
             "chips": ["Available · reserved · sold", "Markers on the plan", "Dynamic pricing"], "imgs": [("inventory", "Inventory and pricing: the building map")]},
            {"icon": "doc", "h3": "Quotes, contracts and documents", "p": "Quote, contract, invoice and receipt as PDF with your letterhead, logo and stamp, Hijri first, with a verification code and QR.",
             "chips": ["Print", "E-mail attachment", "Signed WhatsApp link", "Public verification page"],
             "imgs": [("doc-quote", "A quote issued on the developer's letterhead"), ("doc-invoice", "An invoice issued on the developer's letterhead")], "layout": "two"},
            {"icon": "phone", "h3": "Customer app", "p": "My unit and construction progress, payments and the next instalment, maintenance, resale and documents — from the phone.",
             "chips": ["Their floor plan", "Sign out everywhere", "Privacy requests"],
             "imgs": [("client-home", "Customer app: my unit"), ("client-payments", "Customer app: payments")], "layout": "phones"},
            {"icon": "coins", "h3": "Collections and cash flow", "p": "A monthly forecast per escrow account, arrears by age, and rescheduling before default, not after.",
             "chips": ["Escrow per project", "Bank reconciliation", "VAT", "Charity clause, not penalties"],
             "imgs": [("finance", "Cash flow and default risk"), ("billing", "Invoices, escrow and reconciliation")], "layout": "two"},
            {"icon": "megaphone", "h3": "Marketing and the ad studio", "p": "Every project classified from live data, campaigns with an interest-free offer and a tracking code, and ads composed from project data.",
             "chips": ["6 templates × 3 sizes", "Cost per lead", "Market alerts"],
             "imgs": [("marketing", "Marketing board"), ("ad-studio", "Ad studio")], "layout": "two"},
            {"icon": "report", "h3": "Reports and analytics", "p": "Ten ready reports one click away, a report builder with no SQL, CSV and PDF export with charts, and e-mail scheduling.",
             "chips": ["Portfolio", "Collections and arrears", "Lead funnel", "ERPNext export"], "imgs": [("report", "The portfolio report")]},
            {"icon": "shield", "h3": "Security and governance", "p": "A hash-chained audit log nobody can edit, encrypted identity data, and developer isolation at the database level.",
             "chips": ["Two-factor", "Sessions per device", "Google sign-in", "CSP without external hosts"],
             "imgs": [("audit", "Audit log"), ("security", "My security: two-factor and sessions")], "layout": "two"},
        ],
        "why": {
            "h2": "Why Mabaneek", "lead": "House rules that do not change from one client to the next.",
            "items": [("lang", "Arabic first", "A right-to-left interface in the market's vocabulary, English for the shell."),
                      ("moon", "Hijri first", "Every customer-facing date in the Hijri calendar, then Gregorian."),
                      ("balance", "Islamic finance only", "No interest in any plan or offer; late payment is charity, never revenue."),
                      ("lock", "Isolation in the database", "Each developer's rows are isolated by the engine, not by application code."),
                      ("history", "An audit log that cannot be erased", "A hash chain for every action; no edits, no deletions.")],
        },
        "models": {
            "h2": "Two ways to work together", "lead": "Who operates, who owns, and how updates arrive. Figures are left for the meeting.",
            "cards": [("cloud", "Subscription", "on the Jadwa-hosted platform", ["Usage licence; operations stay with Jadwa", "Row isolation; your data is yours and exported on request", "Automatic updates with every release", "Backups, support and training included"]),
                      ("server", "Private copy", "on the company's infrastructure", ["A licensed copy on your servers (containers + PostgreSQL)", "A fully private database", "Updates per the maintenance agreement", "Runbook and security guide in the delivery"])],
            "note": "In both cases: one licence per developer, and the data belongs to the company.",
        },
        "faq": {
            "h2": "Frequently asked questions",
            "items": [("Is the platform ready now?", "It runs on a cloud demo environment with sample data and every feature is covered by automated tests; live operation starts after the demo meeting and your data set-up."),
                      ("Do I need to install anything?", "No; a web application for staff, customers and brokers. The private copy is deployed on your servers with ready containers."),
                      ("How is my data isolated?", "By row-level security in the database: the engine prevents seeing another developer's rows. The private copy is a separate database."),
                      ("Does it support Islamic finance?", "Islamic finance only; no interest in any plan or offer, and late payment is handled by a charity clause whose wording your Sharia advisor approves."),
                      ("Are documents in my identity?", "Yes: your letterhead, logo, stamp and authorised signature, plus a verification code and QR to a public page with no personal data."),
                      ("What does the customer see?", "Their unit and progress, instalments, contract, invoices and receipts, floor plan, maintenance, and owners' association votes."),
                      ("Does it integrate with accounting?", "Journal export in ERPNext format and CSV/PDF reports; a payment gateway, WhatsApp Business and company e-mail are enabled at go-live with your accounts."),
                      ("How do I get a demo?", "Fill in the form below; the Jadwa team contacts you within two working days for a one-hour live session.")],
        },
        "demo": {
            "h2": "Request a live demo", "lead": "A one-hour meeting: we show the platform live, collect your needs and agree on the model and timeline.",
            "side": [("check", "No account is created and your data is not shared with third parties"), ("clock", "We reply within two working days"), ("lang", "The demo is in Arabic, and can be in English")],
            "name": "Name", "company": "Company", "email": "E-mail", "phone": "Phone", "projects": "Number of current projects",
            "message": "Message (optional)", "message_ph": "What would you like to see in the demo?", "send": "Send request",
            "consent": "By sending the request you agree to the", "privacy": "privacy policy.",
        },
        "footer": {"org": "Jadwa for Studies & Development", "org_url": "https://jadwa.om", "place": "Muscat, Sultanate of Oman",
                   "links": [("/en/privacy", "Privacy policy"), ("/login", "Sign in"), ("/", "العربية")],
                   "updated": f"Last updated: {UPDATED['hijri']} ({UPDATED['iso']})"},
        "ld_org_name": "Jadwa for Studies & Development", "ld_app_name": "Mabaneek", "ld_app_desc": "Real-estate development platform from booking to handover",
    },
}


# ─────────────────────────────────────────────────────────────────────────── helpers
def e(s: str) -> str:
    return html.escape(str(s), quote=True)


def jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise ValueError(f"no SOF marker in {path}")


def png_size(path: Path) -> tuple[int, int]:
    return struct.unpack(">II", path.read_bytes()[16:24])


def img(name: str, alt: str, eager: bool = False) -> str:
    p = IMG / f"{name}.jpg"
    w, h = jpeg_size(p)
    extra = ' loading="eager" fetchpriority="high"' if eager else ' loading="lazy" decoding="async"'
    return f'<div class="shot"><div class="shot-bar" aria-hidden="true"><i></i><i></i><i></i></div><img src="./img/landing/{name}.jpg" alt="{e(alt)}" width="{w}" height="{h}"{extra}></div>'


def ld_json(obj: dict) -> str:
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + "</script>"


def chips(items) -> str:
    return '<ul class="chips">' + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul>"


# ─────────────────────────────────────────────────────────────────────────── page
def render(lang: str) -> str:
    c = CONTENT[lang]
    base = PH
    brand_ar = lang == "ar"
    brand_txt = "مبانيك" if brand_ar else "Mabaneek"
    nav = "".join(f'<a href="{href}">{e(label)}</a>' for href, label in c["nav"])
    lw, lh = png_size(WEB / "img" / f"{c['logo']}.png")
    hero = c["hero"]
    facts = '<ul class="facts">' + "".join(f"<li><b>{e(n)}</b>{e(t)}</li>" for n, t in hero["facts"]) + "</ul>"
    problems = "".join(f'<div class="card"><div class="icb">{icon(i)}</div><h3>{e(t)}</h3><p class="muted">{e(b)}</p></div>' for i, t, b in c["problems"]["cards"])
    steps = "".join(f'<div class="step"><div class="icb">{icon(i)}</div><b>{e(t)}</b><small>{e(s)}</small></div>' for i, t, s in c["journey"]["steps"])
    stages = "".join(f'<div class="stage"><div class="bar"></div><div class="in"><div class="num">{n + 1}</div><b>{e(t)}</b>{chips(items)}</div></div>'
                     for n, (_i, t, items) in enumerate(c["cycle"]["stages"]))
    cross_t, cross_items = c["cycle"]["cross"]
    cross = f'<div class="cross"><b>{e(cross_t)}</b>' + "".join(f"<span>{e(x)}</span>" for x in cross_items) + "</div>"
    feats = []
    for i, f in enumerate(c["features"]):
        pics = "".join(img(n, a) for n, a in f["imgs"])
        feats.append(f'<article class="feat{" flip" if i % 2 else ""}"><div class="feat-txt"><h3>{icon(f["icon"])}{e(f["h3"])}</h3><p>{e(f["p"])}</p>{chips(f["chips"])}</div>'
                     f'<div class="feat-img {f.get("layout", "")}">{pics}</div></article>')
    why = "".join(f'<div class="card"><div class="icb">{icon(i)}</div><h3>{e(t)}</h3><p class="muted">{e(b)}</p></div>' for i, t, b in c["why"]["items"])
    models = "".join(f'<div class="card{" alt2" if n else ""}"><div class="icb">{icon(i)}</div><span class="tag">{e(tag)}</span><h3>{e(t)}</h3><ul>{"".join(f"<li>{e(x)}</li>" for x in items)}</ul></div>'
                     for n, (i, tag, t, items) in enumerate(c["models"]["cards"]))
    faq = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in c["faq"]["items"])
    d = c["demo"]
    side = "".join(f"<li>{icon(i)}<span>{e(t)}</span></li>" for i, t in d["side"])
    form = (f'<form class="form" id="demoForm" novalidate autocomplete="on"><div class="row"><div><label for="dName">{e(d["name"])}</label>'
            f'<input id="dName" name="name" required minlength="2" maxlength="80" autocomplete="name"></div>'
            f'<div><label for="dCompany">{e(d["company"])}</label><input id="dCompany" name="company" required minlength="2" maxlength="120" autocomplete="organization"></div></div>'
            f'<div class="row"><div><label for="dEmail">{e(d["email"])}</label><input id="dEmail" name="email" type="email" required maxlength="120" autocomplete="email" dir="ltr"></div>'
            f'<div><label for="dPhone">{e(d["phone"])}</label><input id="dPhone" name="phone" type="tel" required minlength="6" maxlength="24" autocomplete="tel" dir="ltr" pattern="\\+?[0-9][0-9 \\(\\)\\-]{{5,23}}"></div></div>'
            f'<label for="dProjects">{e(d["projects"])}</label><input id="dProjects" name="projects" type="number" min="0" max="1000" value="1" inputmode="numeric">'
            f'<label for="dMessage">{e(d["message"])}</label><textarea id="dMessage" name="message" maxlength="1000" placeholder="{e(d["message_ph"])}"></textarea>'
            f'<div class="hp" aria-hidden="true"><label for="dWebsite">Website</label><input id="dWebsite" name="website" tabindex="-1" autocomplete="off"></div>'
            f'<p class="hint">{e(d["consent"])} <a href="{c["privacy"]}">{e(d["privacy"])}</a></p>'
            f'<button class="btn btn-lg" type="submit">{e(d["send"])}</button><div class="msg" id="demoMsg" role="status" aria-live="polite" tabindex="-1"></div></form>')
    ft = c["footer"]
    foot_links = "".join(f'<a href="{href}">{e(label)}</a>' for href, label in ft["links"])
    ld_org = {"@context": "https://schema.org", "@type": "Organization", "name": c["ld_org_name"], "url": ft["org_url"],
              "address": {"@type": "PostalAddress", "addressLocality": "Muscat", "addressCountry": "OM"}}
    ld_app = {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": c["ld_app_name"], "description": c["ld_app_desc"],
              "applicationCategory": "BusinessApplication", "operatingSystem": "Web", "inLanguage": lang, "url": f"{base}{c['home']}",
              "image": f"{base}{c['og_image']}", "author": {"@type": "Organization", "name": c["ld_org_name"], "url": ft["org_url"]}}
    ld_faq = {"@context": "https://schema.org", "@type": "FAQPage",
              "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in c["faq"]["items"]]}
    head = (f'<!DOCTYPE html>\n<html lang="{lang}" dir="{c["dir"]}">\n<head>\n<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f'<title>{e(c["title"])}</title>\n<meta name="description" content="{e(c["description"])}">\n'
            f'<link rel="canonical" href="{base}{c["home"]}">\n<link rel="alternate" hreflang="ar" href="{base}/">\n<link rel="alternate" hreflang="en" href="{base}/en">\n'
            f'<link rel="alternate" hreflang="x-default" href="{base}/">\n'
            f'<meta property="og:type" content="website"><meta property="og:site_name" content="Mabaneek | مبانيك"><meta property="og:locale" content="{"ar_OM" if brand_ar else "en_US"}">\n'
            f'<meta property="og:title" content="{e(c["title"])}"><meta property="og:description" content="{e(c["description"])}">\n'
            f'<meta property="og:url" content="{base}{c["home"]}"><meta property="og:image" content="{base}{c["og_image"]}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">\n'
            f'<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{e(c["title"])}"><meta name="twitter:description" content="{e(c["description"])}"><meta name="twitter:image" content="{base}{c["og_image"]}">\n'
            f'<meta name="theme-color" content="#124E42">\n<link rel="icon" type="image/svg+xml" href="./img/favicon.svg">\n'
            f'<link rel="preload" as="font" type="font/woff2" crossorigin href="./fonts/tajawal-{"arabic" if brand_ar else "latin"}-700-normal.woff2">\n'
            f'<link rel="preload" as="font" type="font/woff2" crossorigin href="./fonts/tajawal-{"arabic" if brand_ar else "latin"}-400-normal.woff2">\n'
            f'<link rel="stylesheet" href="./fonts.css">\n<link rel="stylesheet" href="./landing.css">\n'
            f'{ld_json(ld_org)}\n{ld_json(ld_app)}\n{ld_json(ld_faq)}\n</head>\n')
    brand = f'<a class="brand" href="{c["home"]}"><img src="./img/logo-mark.svg" alt="" width="40" height="40"><span>{brand_txt}</span></a>'
    body = (f'<body class="lp">\n<a class="skip" href="#main">{e(c["skip"])}</a>\n'
            f'<header class="nav"><div class="wrap nav-in">{brand}'
            f'<button class="menu-btn" id="menu" aria-label="{e(c["menu"])}" aria-expanded="false" aria-controls="navLinks">☰</button>'
            f'<nav class="nav-links" id="navLinks" aria-label="{e(c["menu"])}">{nav}<a href="{c["other_href"]}" hreflang="{c["other_lang"]}" lang="{c["other_lang"]}">{e(c["other_label"])}</a>'
            f'<a class="btn btn-ghost" href="/login">{e(c["login"])}</a><a class="btn" href="#demo">{e(c["cta"])}</a></nav></div></header>\n'
            f'<main id="main">\n<section class="hero"><div class="wrap hero-grid"><div>'
            f'<img class="logo" src="./img/{c["logo"]}.png" alt="{brand_txt} — {"الشعار" if brand_ar else "logo"}" width="{lw}" height="{lh}" loading="eager" fetchpriority="high">'
            f'<span class="eyebrow">{e(hero["eyebrow"])}</span><h1>{e(hero["h1"])}</h1>'
            f'<p class="lead">{e(hero["lead"])}</p><div class="cta-row"><a class="btn btn-lg" href="#demo">{e(c["cta"])}</a><a class="btn btn-ghost btn-lg" href="#features">{e(c["cta2"])}</a></div>'
            f'{facts}<p class="note">{e(hero["note"])}</p></div><div class="hero-visual">{img(hero["img"][0], hero["img"][1], eager=True)}<div class="float"><span class="dot"></span>{e(hero["float"])}</div></div></div></section>\n'
            f'<section class="sec" id="problems"><div class="wrap"><div class="sec-head center"><h2>{e(c["problems"]["h2"])}</h2><p>{e(c["problems"]["lead"])}</p></div><div class="grid">{problems}</div><p class="close">{icon("check")}<span>{e(c["problems"]["close"])}</span></p></div></section>\n'
            f'<section class="sec tint" id="journey"><div class="wrap"><div class="sec-head center"><h2>{e(c["journey"]["h2"])}</h2><p>{e(c["journey"]["lead"])}</p></div><div class="journey">{steps}</div></div></section>\n'
            f'<section class="sec" id="cycle"><div class="wrap"><div class="sec-head center"><h2>{e(c["cycle"]["h2"])}</h2><p>{e(c["cycle"]["lead"])}</p></div><div class="cycle">{stages}</div>{cross}</div></section>\n'
            f'<section class="sec alt" id="features"><div class="wrap"><div class="sec-head center"><h2>{e(c["features_h2"])}</h2><p>{e(c["features_lead"])}</p></div>{"".join(feats)}</div></section>\n'
            f'<section class="sec dark" id="why"><div class="wrap"><div class="sec-head center"><h2>{e(c["why"]["h2"])}</h2><p>{e(c["why"]["lead"])}</p></div><div class="why">{why}</div></div></section>\n'
            f'<section class="sec" id="models"><div class="wrap"><div class="sec-head center"><h2>{e(c["models"]["h2"])}</h2><p>{e(c["models"]["lead"])}</p></div><div class="models">{models}</div><p class="muted" style="margin-top:16px;text-align:center">{e(c["models"]["note"])}</p></div></section>\n'
            f'<section class="sec tint" id="faq"><div class="wrap"><div class="sec-head center"><h2>{e(c["faq"]["h2"])}</h2></div><div class="faq">{faq}</div></div></section>\n'
            f'<section class="sec" id="demo"><div class="wrap demo-grid"><div class="demo-side"><h2>{e(d["h2"])}</h2><p class="muted">{e(d["lead"])}</p><ul>{side}</ul></div>{form}</div></section>\n'
            f'</main>\n<footer class="foot"><div class="wrap foot-grid"><div><span class="brand"><img src="./img/logo-mark.svg" alt="" width="36" height="36" loading="lazy"><span>{brand_txt}</span></span>'
            f'<div style="margin-top:8px"><a href="{ft["org_url"]}" rel="noopener">{e(ft["org"])}</a> · {e(ft["place"])}<br><span>{e(ft["updated"])}</span></div></div>'
            f'<nav class="foot-links" aria-label="footer">{foot_links}</nav></div></footer>\n<script type="module" src="./landing.js"></script>\n</body>\n</html>\n')
    return head + body


def main() -> None:
    for lang, name in (("ar", "landing.html"), ("en", "landing-en.html")):
        out = WEB / name
        out.write_text(render(lang), encoding="utf-8", newline="\n")
        print(f"{name}: {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
