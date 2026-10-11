"""Build the public landing pages (0.14.0): one content source → web/landing.html (Arabic, RTL, served on /) and
web/landing-en.html (English, LTR, served on /en). Run after editing CONTENT or replacing screenshots:

    python tools/build_landing.py && npm run check && npm run build

Rules baked in (docs/LANDING.md): Arabic first, explicit dir/lang on <html>, Western digits only, Hijri before Gregorian,
no prices, no client names, no invented numbers, no people in images, JSON-LD (Organization · SoftwareApplication · FAQPage),
canonical/hreflang/OG with the `__PUBLIC_URL__` placeholder that backend/landing.py replaces from MABANIQ_PUBLIC_URL at request
time. Images are read from web/img/landing/ (tools/landing_shoot.mjs + tools/landing_assets.py) with their real dimensions.
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

# ─────────────────────────────────────────────────────────────────────────── content
CONTENT = {
    "ar": {
        "dir": "rtl", "other_lang": "en", "other_label": "English", "other_href": "/en", "home": "/", "privacy": "/privacy",
        "title": "مبانيك | منصة إدارة التطوير العقاري — من الحجز إلى التسليم",
        "description": "مبانيك منصة واحدة تدير دورة البيع العقاري كاملة للمطوّر: المخزون، عروض الأسعار والعقود، التحصيل والسيولة، تطبيق العميل، التسويق والتقارير. عربية أولًا، هجري أولًا، تمويل إسلامي فقط.",
        "og_image": "/og.png",
        "nav": [("#features", "الميزات"), ("#why", "لماذا مبانيك"), ("#models", "صيغتا التعاون"), ("#faq", "الأسئلة الشائعة")],
        "login": "تسجيل الدخول", "cta": "اطلب عرضًا حيًّا", "cta2": "استكشف الميزات", "menu": "القائمة", "skip": "انتقل إلى المحتوى",
        "hero": {
            "eyebrow": "منصة إدارة التطوير العقاري · منتج جدوى للدراسات والتطوير",
            "h1": "منصة واحدة تدير دورة البيع العقاري كاملة — من الحجز إلى التسليم",
            "lead": "المخزون والتسعير، عروض الأسعار والعقود والمستندات بترويستك، التحصيل والسيولة، تطبيق للعميل، التسويق والتقارير، وسجل تدقيق لا يُمحى — في منصة عربية أولًا، بالتقويم الهجري أولًا، وبتمويل إسلامي فقط.",
            "note": "اللقطات في هذه الصفحة حقيقية من بيئة العرض، ببيانات تجريبية لا تخص أي شركة.",
            "img": ("dashboard", "لوحة القيادة في مبانيك: المؤشرات الأربعة وصندوق القرارات مرتّبًا بالأولوية والأثر المالي"),
        },
        "problems": {
            "h2": "ثلاث مشكلات يعيشها كل مطوّر مع كل مشروع جديد",
            "lead": "مع كل مشروع تتضاعف الملفات والمحادثات، ويتأخر الوصول إلى الحقيقة الواحدة: من حجز ماذا، ومن دفع كم، وأي مشروع يحتاج تدخلًا اليوم.",
            "cards": [
                ("تشتّت الحجوزات والتحصيل", "جداول متفرقة، مجموعات واتساب، وصور إيصالات: الحجز في مكان والدفعة في مكان آخر، والمطابقة البنكية في نهاية الشهر عملٌ يدوي."),
                ("المشروع المتعثّر بيعيًا يُكتشف متأخرًا", "لا يظهر تباطؤ البيع إلا حين تُراجع الأرقام يدويًا؛ والتسعير والحملة والوسطاء قرارات تُتخذ بلا إشارة مبكرة."),
                ("العميل لا يرى وحدته ولا مستنداته", "يسأل عن تقدم البناء وعقده وإيصالاته وموعد قسطه القادم، فيُجاب عبر مكالمة كل مرة."),
            ],
            "close": "مبانيك تضع الثلاثة في مكان واحد: مخزون حي، تحصيل مرتبط بالعقد، تطبيق للعميل، ولوحة تخبر الإدارة بما يحتاج قرارها اليوم.",
        },
        "cycle": {
            "h2": "دورة التطوير الثلاثية في منصة واحدة",
            "lead": "تتبع المنصة دورة التطوير العقاري من الأرض إلى التشغيل، وتعمل فوقها طبقتان مشتركتان: المالية والتحصيل، والحوكمة والتقارير.",
            "stages": [
                ("1 · الأرض والتراخيص", ["الأراضي ودراسات الجدوى", "التراخيص والجهات الحكومية"]),
                ("2 · البيع والإنشاء", ["المخزون والتسعير والمخططات", "العملاء المحتملون والتسويق", "عروض الأسعار والحجز والعقود", "الإنشاء والمستخلصات"]),
                ("3 · التسليم والتشغيل", ["التسليم والعيوب ونقل الملكية", "اتحاد الملاك وإدارة المرافق", "خدمة العملاء والتأجير"]),
            ],
            "cross": ("عبر الدورة:", ["السيولة والتعثر", "الفواتير وحساب الضمان", "التقارير والتحليلات", "سجل التدقيق", "الإدارة والأمان", "هوية المستندات"]),
        },
        "features_h2": "الميزات بلقطات حقيقية",
        "features_lead": "كل ما تراه هنا يعمل اليوم على بيئة العرض ومغطّى باختبارات آلية. البيانات تجريبية.",
        "features": [
            {"h3": "لوحة القيادة: ما يحتاج قرارك اليوم",
             "p": "اللوحة لا تعرض أرقامًا فقط؛ تقترح قرارات مرتّبة بالأولوية والأثر المالي: فجوة سيولة متوقعة في حساب ضمان مشروع، مستخلص لا تدعمه أدلة الإنجاز، عميل يحتاج إعادة جدولة، أو شريحة يُنصح برفع سعرها.",
             "ul": ["مؤشرات المبيعات والتحصيل وفجوة السيولة والمخزون المتاح", "كل قرار يحمل مصدره (رادار السيولة، التحقق من الإنجاز، نموذج التعثر، التسعير الديناميكي) وحالته", "اعتماد القرار يغيّر البيانات ويُسجَّل في التدقيق"],
             "imgs": [("dashboard", "لوحة القيادة: المؤشرات وصندوق القرارات")]},
            {"h3": "المخزون والتسعير والمخططات",
             "p": "مخطط المبنى بطوابقه ووحداته بحالتها (متاحة، محجوزة، مباعة) ونموذجها، وتحته أداء الشرائح: الطلب النسبي على كل نموذج وإطلالة وتوصية محرّك التسعير.",
             "ul": ["مخططات الطوابق ونماذج الوحدات تُرفع كمستندات ببصمة محتوى، مع علامات مواقع الوحدات", "التسعير الديناميكي يقترح تعديلات محدودة على الشرائح مرتفعة الطلب", "الضغط على أي وحدة يفتح بطاقتها وموقعها على المخطط"],
             "imgs": [("inventory", "المخزون والتسعير: مخطط المبنى بحالات الوحدات وأداء الشرائح")]},
            {"h3": "عروض الأسعار والعقود والمستندات بترويسة المطوّر",
             "p": "عرض سعر مرقّم بخطة سداد غير ربوية يتحوّل إلى حجز بضغطة، ثم التحقق من الهوية والعقد الموقَّع، والفاتورة والإيصال لكل قسط ودفعة — كلها PDF بترويستك وشعارك وختمك ورمز تحقق وQR.",
             "ul": ["الهجري أولًا، أرقام غربية، جدول دفعات صريح، وصفحة تحقق عامة لكل مستند بلا بيانات شخصية", "الإرسال طباعةً أو بريدًا بمرفق أو برابط واتساب موقَّع", "لا يُخزَّن المستند ملفًا؛ يُولَّد من القاعدة عند الطلب والسجل يحفظ بصمته"],
             "imgs": [("doc-quote", "عرض سعر صادر من المنصة بترويسة المطوّر وجدول دفعات بلا فوائد"), ("doc-invoice", "فاتورة صادرة من المنصة بترويسة المطوّر")], "layout": "two"},
            {"h3": "تطبيق العميل",
             "p": "تطبيق ويب للهاتف يدخله العميل بحسابه: وحدتي (تقدم البناء وصوره وموعد التسليم)، الدفعات (جدول الأقساط والقسط القادم)، الصيانة، إعادة البيع بموافقة المطوّر، والمزيد (العقد، الفواتير، الإيصالات، المخططات).",
             "ul": ["يرى العميل مخطط طابقه وعلامة وحدته وحدها", "تغيير كلمة المرور إلزامي عند أول دخول، والخروج من كل الأجهزة بضغطة", "تصدير بياناته الشخصية وطلبات الخصوصية من التطبيق مباشرة"],
             "imgs": [("client-home", "تطبيق العميل: وحدتي وتقدم البناء"), ("client-payments", "تطبيق العميل: الدفعات وجدول الأقساط")], "layout": "phones"},
            {"h3": "التحصيل والسيولة",
             "p": "تنبؤ شهري بالتدفقات لكل حساب ضمان مع المحرّكات وذروة العجز المتوقعة، وقائمة العملاء المعرّضين للتعثر واقتراح إعادة الجدولة قبل التأخر لا بعده.",
             "ul": ["المتأخرات بأعمارها وقائمة الأقساط المتأخرة بالعميل والوحدة", "التأخير لا يولّد غرامة إيرادًا؛ يُقيَّد تبرعًا بشرط التبرع في العقد ويمكن إعفاؤه", "الفواتير وضريبة القيمة المضافة، والمطابقة البنكية باستيراد الكشف، وحساب ضمان لكل مشروع"],
             "imgs": [("finance", "السيولة والتعثر: التنبؤ الشهري لحسابات الضمان"), ("billing", "الفواتير والضمان والمطابقة البنكية")], "layout": "two"},
            {"h3": "التسويق والاستوديو",
             "p": "لوحة تصنّف كل مشروع من بياناته الحية (إطلاق، مستقر، ضعيف البيع، شبه مكتمل، مكتمل) بإشاراته وإجراءات مقترحة، وحملات بعرض غير ربوي ورمز تتبع يقيس العملاء الواردين وكلفة العميل.",
             "ul": ["استوديو إعلانات بستة قوالب وثلاثة مقاسات من بيانات المشروع وترويستك، بنص عربي مركَّب برمجيًا وبلا أشخاص", "المنصة ترفض أي عرض بفائدة", "تنبيهات تسويقية من حركة السوق تُسجَّل تلقائيًا"],
             "imgs": [("marketing", "لوحة التسويق: تصنيف المشاريع بإشاراتها"), ("ad-studio", "استوديو الإعلانات داخل المنصة")], "layout": "two"},
            {"h3": "التقارير والتحليلات",
             "p": "عشرة تقارير جاهزة بالنقر (المحفظة، أداء المبيعات، قمع العملاء، عروض الأسعار، الوسطاء، التحصيل والمتأخرات، السيولة، المخزون، الإنشاء، التسليم) بمعاملات ورسوم، ومنشئ تقارير على مجموعات بيانات معتمدة بلا SQL.",
             "ul": ["تصدير CSV وPDF برسوم مرسومة أصليًا", "حفظ التقارير وجدولتها بالبريد", "تصدير القيود بصيغة ERPNext"],
             "imgs": [("report", "تقرير لوحة المحفظة داخل المنصة")]},
            {"h3": "الأمان والحوكمة",
             "p": "كل فعل سطر في سجل تدقيق مسلسل ببصمة لا يستطيع أحد تعديله؛ بيانات الهوية مشفّرة في القاعدة؛ وكل مطوّر معزول بصفوفه على مستوى قاعدة البيانات لا على مستوى التطبيق.",
             "ul": ["أدوار جاهزة (مدير عام، مبيعات، مالية، مهندس، مستثمر، وسيط، عميل) وكل دور يرى ما يخصه", "تحقق ثنائي برموز استرداد، جلسات بأجهزتها وإنهاؤها عن بُعد، ودخول بحساب Google للحسابات القائمة", "ترويسات أمان موثَّقة، لا سكربتات مضمّنة ولا مضيف خارجي"],
             "imgs": [("audit", "سجل التدقيق المسلسل"), ("security", "أماني: التحقق الثنائي والجلسات")], "layout": "two"},
        ],
        "why": {
            "h2": "لماذا مبانيك",
            "lead": "قواعد بيتية لا تتغيّر بتغيّر العميل.",
            "items": [
                ("عربية أولًا", "واجهة من اليمين إلى اليسار بمصطلحات السوق العقاري، ونسخة إنجليزية للهيكل العام."),
                ("هجري أولًا", "كل تاريخ يواجه العميل يُكتب بالتقويم الهجري ثم الميلادي."),
                ("تمويل إسلامي فقط", "لا فوائد في أي خطة سداد أو عرض؛ غرامة التأخير تبرع بشرط التبرع، لا إيراد."),
                ("عزل كل مطوّر في قاعدة البيانات", "عزل الصفوف مفروض من محرك قاعدة البيانات نفسه، لا من شيفرة التطبيق."),
                ("سجل تدقيق لا يُمحى", "سلسلة بصمات لكل فعل؛ لا تعديل ولا حذف، حتى من مدير النظام."),
            ],
        },
        "models": {
            "h2": "صيغتا التعاون",
            "lead": "الفرق الجوهري بين الصيغتين: من يشغّل، ومن يملك، وكيف تصل التحديثات. الأرقام تُترك للاجتماع.",
            "cards": [
                ("اشتراك", "اشتراك على منصة جدوى المستضافة", ["ترخيص استخدام؛ الشيفرة والتشغيل لدى جدوى", "مطوّر معزول بصفوفه على قاعدة مشتركة؛ البيانات ملك الشركة وتُصدَّر عند الطلب", "تحديثات مستمرة وتلقائية مع كل إصدار", "النسخ الاحتياطي والدعم والتدريب ضمن الاشتراك"]),
                ("نسخة خاصة", "نسخة خاصة على بنية الشركة", ["نسخة مرخَّصة تُنشر على خوادم الشركة (حاويات + PostgreSQL)", "قاعدة بيانات خاصة بالكامل داخل بنية الشركة", "التحديثات بحسب اتفاق الصيانة", "دليل التشغيل ودليل الأمان ضمن التسليم"]),
            ],
            "note": "في الحالتين: ترخيص واحد لمطوّر واحد، والبيانات ملك الشركة.",
        },
        "faq": {
            "h2": "أسئلة شائعة",
            "items": [
                ("هل المنصة جاهزة للاستخدام الآن؟", "المنصة تعمل على بيئة عرض سحابية ببيانات تجريبية، وكل الميزات المعروضة في هذه الصفحة مُختبرة آليًا. التشغيل الفعلي لمطوّر يبدأ بعد اجتماع العرض الحي وتهيئة بياناته (المشاريع، الوحدات، خطط السداد، الترويسة)."),
                ("هل أحتاج إلى تثبيت أي برنامج؟", "لا. مبانيك تطبيق ويب يعمل من المتصفح على الحاسوب والهاتف، للموظفين والعملاء والوسطاء. النسخة الخاصة تُنشر على خوادم الشركة بحاويات جاهزة."),
                ("كيف تُعزل بيانات شركتي عن المطوّرين الآخرين؟", "بعزل الصفوف على مستوى قاعدة البيانات (Row-Level Security): المحرك نفسه يمنع أي استعلام من رؤية صفوف مطوّر آخر، ولا يعتمد ذلك على شيفرة التطبيق. والنسخة الخاصة تعطيك قاعدة مستقلة بالكامل."),
                ("هل تدعم المنصة التمويل الإسلامي؟", "التمويل الإسلامي فقط: لا فوائد في أي خطة سداد أو عرض تسويقي، والمنصة ترفض الصياغات الربوية. التأخر في السداد يُعالَج بشرط التبرع (تبرع لجهة خيرية لا إيراد للمطوّر)، وصياغته النهائية تُعتمد من المستشار الشرعي للشركة."),
                ("هل تصدر المستندات بهوية شركتي؟", "نعم. عروض الأسعار والعقود والفواتير والإيصالات تصدر PDF بترويستك وشعارك وختمك وتوقيعك المعتمد، وكل مستند يحمل رمز تحقق وQR إلى صفحة تحقق عامة لا تُظهر أي بيانات شخصية."),
                ("ماذا يرى العميل؟", "تطبيق ويب للهاتف: وحدته وتقدم بنائها، جدول أقساطه وقسطه القادم، عقده وفواتيره وإيصالاته، مخطط طابقه وموقع وحدته، طلبات الصيانة بعد التسليم، والتصويت في اتحاد الملاك."),
                ("هل تتكامل مع النظام المحاسبي؟", "تُصدَّر القيود بصيغة ERPNext وتُصدَّر التقارير CSV وPDF. التكاملات الأخرى (بوابة دفع عُمانية، واتساب للأعمال، بريد الشركة) تُفعَّل عند التشغيل الفعلي بحسب حسابات الشركة."),
                ("ما لغة المنصة؟", "العربية أولًا من اليمين إلى اليسار، مع نسخة إنجليزية للهيكل العام وشاشة الدخول وتطبيق العميل. التواريخ بالهجري ثم الميلادي، والأرقام غربية."),
                ("أين تُستضاف البيانات؟", "في صيغة الاشتراك على استضافة سحابية مُدارة بقاعدة PostgreSQL مع تمرين استرجاع مُجرَّب للنسخ الاحتياطية؛ وفي النسخة الخاصة على بنية الشركة نفسها. تُعرض مواصفات الاستضافة والنسخ في اجتماع العرض."),
                ("كيف أحصل على عرض حي؟", "املأ نموذج «اطلب عرضًا حيًّا» أدناه، وسيتواصل معك فريق جدوى خلال يومي عمل لتحديد موعد اجتماع لمدة ساعة نعرض فيه المنصة حيّة على بيانات مشابهة لمشاريعك."),
            ],
        },
        "demo": {
            "h2": "اطلب عرضًا حيًّا",
            "lead": "اجتماع لمدة ساعة نعرض فيه المنصة حيّة ونستلم احتياجات شركتك ونتفق على الصيغة والجدول الزمني للانطلاق.",
            "side": ["لا يُنشأ حساب من هذا النموذج ولا تُشارك بياناتك مع طرف ثالث", "نردّ خلال يومي عمل", "العرض بالعربية، ويمكن بالإنجليزية"],
            "name": "الاسم", "company": "الشركة", "email": "البريد الإلكتروني", "phone": "رقم الهاتف", "projects": "عدد المشاريع الحالية",
            "message": "رسالة (اختياري)", "message_ph": "ما الذي تريد رؤيته في العرض؟", "send": "أرسل الطلب",
            "consent": "بإرسال الطلب توافق على",
            "privacy": "سياسة الخصوصية.",
        },
        "footer": {
            "org": "جدوى للدراسات والتطوير", "org_url": "https://jadwa.om", "place": "مسقط، سلطنة عُمان",
            "links": [("/privacy", "سياسة الخصوصية"), ("/login", "تسجيل الدخول"), ("/en", "English")],
            "updated": f"آخر تحديث: {UPDATED['hijri']} الموافق {UPDATED['iso']}م",
        },
        "ld_org_name": "جدوى للدراسات والتطوير", "ld_app_name": "مبانيك", "ld_app_desc": "منصة إدارة التطوير العقاري من الحجز إلى التسليم",
    },
    "en": {
        "dir": "ltr", "other_lang": "ar", "other_label": "العربية", "other_href": "/", "home": "/en", "privacy": "/en/privacy",
        "title": "Mabaniq | Real-estate development platform — from booking to handover",
        "description": "Mabaniq is one platform for a developer's whole sales cycle: inventory, quotes and contracts, collections and cash flow, a customer app, marketing and reports. Arabic-first, Hijri-first, Islamic finance only.",
        "og_image": "/og-en.png",
        "nav": [("#features", "Features"), ("#why", "Why Mabaniq"), ("#models", "Engagement"), ("#faq", "FAQ")],
        "login": "Sign in", "cta": "Request a live demo", "cta2": "Explore the features", "menu": "Menu", "skip": "Skip to content",
        "hero": {
            "eyebrow": "Real-estate development platform · a Jadwa for Studies & Development product",
            "h1": "One platform for the whole property sales cycle — from booking to handover",
            "lead": "Inventory and pricing, quotes, contracts and documents on your letterhead, collections and cash flow, a customer app, marketing and reports, and an audit log that cannot be erased — Arabic-first, Hijri-first, Islamic finance only.",
            "note": "Screenshots on this page are real, taken from the demo environment with sample data that belongs to no company.",
            "img": ("dashboard", "The Mabaniq dashboard: four indicators and the decision box ordered by priority and financial impact"),
        },
        "problems": {
            "h2": "Three problems every developer lives with on every new project",
            "lead": "With every project the files and chats multiply, and the single truth gets harder to reach: who booked what, who paid how much, and which project needs attention today.",
            "cards": [
                ("Scattered bookings and collections", "Spreadsheets, WhatsApp groups and photos of receipts: the booking lives in one place, the payment in another, and bank reconciliation is a manual month-end job."),
                ("A slow-selling project is noticed too late", "A sales slowdown only shows when someone reviews the numbers by hand; pricing, campaigns and brokers are decided without an early signal."),
                ("The customer cannot see their unit or documents", "They ask about construction progress, their contract, receipts and the next instalment — and get a phone call every time."),
            ],
            "close": "Mabaniq puts all three in one place: live inventory, collections tied to the contract, an app for the customer, and a dashboard that tells management what needs a decision today.",
        },
        "cycle": {
            "h2": "The three-stage development cycle in one platform",
            "lead": "The platform follows the development cycle from land to operations, with two shared layers on top: finance and collections, governance and reports.",
            "stages": [
                ("1 · Land and permits", ["Land and feasibility studies", "Permits and government bodies"]),
                ("2 · Sales and construction", ["Inventory, pricing and plans", "Leads and marketing", "Quotes, bookings and contracts", "Construction and payment certificates"]),
                ("3 · Handover and operations", ["Handover, snags and title transfer", "Owners' association and facilities", "Customer service and leasing"]),
            ],
            "cross": ("Across the cycle:", ["Cash flow and default risk", "Invoices and escrow", "Reports and analytics", "Audit log", "Administration and security", "Document identity"]),
        },
        "features_h2": "Features, with real screenshots",
        "features_lead": "Everything shown here runs today on the demo environment and is covered by automated tests. The data is sample data.",
        "features": [
            {"h3": "Dashboard: what needs your decision today",
             "p": "The dashboard does not just show numbers; it proposes decisions ordered by priority and financial impact: an expected cash gap in a project's escrow account, a payment certificate the progress evidence does not support, a customer who needs rescheduling, or a segment worth repricing.",
             "ul": ["Sales, collections, cash gap and available inventory at a glance", "Every decision carries its source (cash radar, progress verification, default model, dynamic pricing) and its status", "Approving a decision changes the data and is written to the audit log"],
             "imgs": [("dashboard", "Dashboard: indicators and the decision box")]},
            {"h3": "Inventory, pricing and plans",
             "p": "The building map floor by floor, every unit with its status (available, reserved, sold) and type, and below it segment performance: relative demand per type and view with the pricing engine's recommendation.",
             "ul": ["Floor plans and unit-type drawings are uploaded as hash-verified documents, with unit position markers", "Dynamic pricing proposes bounded adjustments on high-demand segments", "Clicking a unit opens its card and its position on the plan"],
             "imgs": [("inventory", "Inventory and pricing: the building map with unit statuses and segment performance")]},
            {"h3": "Quotes, contracts and documents on the developer's letterhead",
             "p": "A numbered quote with an interest-free payment plan converts to a booking in one click, then identity verification, the signed contract, and an invoice and receipt for every instalment and payment — all PDF with your letterhead, logo, stamp, a verification code and a QR.",
             "ul": ["Hijri first, Western digits, an explicit payment schedule, and a public verification page per document with no personal data", "Delivered by print, e-mail attachment or a signed WhatsApp link", "Documents are never stored as files; they are generated from the database on demand and the registry keeps their hash"],
             "imgs": [("doc-quote", "A quote issued by the platform on the developer's letterhead with an interest-free schedule"), ("doc-invoice", "An invoice issued by the platform on the developer's letterhead")], "layout": "two"},
            {"h3": "Customer app",
             "p": "A mobile web app the customer signs into: My unit (construction progress, photos, expected handover), Payments (instalment schedule and the next one due), Maintenance, Resale with the developer's approval, and More (contract, invoices, receipts, plans).",
             "ul": ["The customer sees their floor plan with their own unit marked", "Password change is enforced on first sign-in; sign out of all devices in one tap", "Personal-data export and privacy requests straight from the app"],
             "imgs": [("client-home", "Customer app: my unit and construction progress"), ("client-payments", "Customer app: payments and the instalment schedule")], "layout": "phones"},
            {"h3": "Collections and cash flow",
             "p": "A monthly cash forecast per escrow account with its drivers and the expected peak shortfall, and the list of customers at risk of default with a rescheduling proposal before they fall behind, not after.",
             "ul": ["Ageing of arrears and the list of overdue instalments by customer and unit", "Late payment never becomes revenue; it is recorded as a charity obligation under the contract's charity clause and can be waived", "Invoices and VAT, bank reconciliation by statement import, and an escrow account per project"],
             "imgs": [("finance", "Cash flow and default risk: the monthly forecast per escrow account"), ("billing", "Invoices, escrow and bank reconciliation")], "layout": "two"},
            {"h3": "Marketing and the ad studio",
             "p": "A board that classifies every project from its live data (launch, steady, slow-selling, nearly sold out, sold out) with signals and suggested actions, plus campaigns with an interest-free offer and a tracking code that measures incoming leads and cost per lead.",
             "ul": ["An ad studio with six templates and three sizes built from the project's data and your letterhead, with programmatic Arabic text and no people", "The platform refuses any interest-bearing offer", "Marketing alerts from market movement are recorded automatically"],
             "imgs": [("marketing", "Marketing board: project classification with signals"), ("ad-studio", "The ad studio inside the platform")], "layout": "two"},
            {"h3": "Reports and analytics",
             "p": "Ten ready reports one click away (portfolio, sales performance, lead funnel, quotes, brokers, collections and arrears, cash flow, inventory, construction, handover) with parameters and charts, and a report builder on approved datasets with no SQL.",
             "ul": ["CSV and PDF export with natively drawn charts", "Save reports and schedule them by e-mail", "Journal export in ERPNext format"],
             "imgs": [("report", "The portfolio report inside the platform")]},
            {"h3": "Security and governance",
             "p": "Every action is a line in a hash-chained audit log nobody can edit; identity data is encrypted in the database; and every developer is isolated at the database row level, not in application code.",
             "ul": ["Ready roles (general manager, sales, finance, engineer, investor, broker, customer) — each sees only what concerns it", "Two-factor authentication with recovery codes, sessions per device with remote revocation, and Google sign-in for existing accounts", "Documented security headers, no inline scripts and no external hosts"],
             "imgs": [("audit", "The hash-chained audit log"), ("security", "My security: two-factor authentication and sessions")], "layout": "two"},
        ],
        "why": {
            "h2": "Why Mabaniq",
            "lead": "House rules that do not change from one client to the next.",
            "items": [
                ("Arabic first", "A right-to-left interface in the vocabulary of the property market, with an English version of the shell."),
                ("Hijri first", "Every customer-facing date is written in the Hijri calendar, then Gregorian."),
                ("Islamic finance only", "No interest in any payment plan or offer; late payment is a charity obligation, never revenue."),
                ("Every developer isolated in the database", "Row isolation is enforced by the database engine itself, not by application code."),
                ("An audit log that cannot be erased", "A hash chain for every action; no edits, no deletions, not even by the administrator."),
            ],
        },
        "models": {
            "h2": "Two ways to work together",
            "lead": "The essential difference: who operates, who owns, and how updates arrive. Figures are left for the meeting.",
            "cards": [
                ("Subscription", "Subscription on the Jadwa-hosted platform", ["Usage licence; code and operations stay with Jadwa", "Your organisation isolated by rows on a shared database; the data belongs to your company and is exported on request", "Continuous, automatic updates with every release", "Backups, support and training included"]),
                ("Private copy", "A private copy on the company's infrastructure", ["A licensed copy deployed on the company's servers (containers + PostgreSQL)", "A fully private database inside the company's infrastructure", "Updates according to the maintenance agreement", "The operations runbook and security guide are part of the delivery"]),
            ],
            "note": "In both cases: one licence per developer, and the data belongs to the company.",
        },
        "faq": {
            "h2": "Frequently asked questions",
            "items": [
                ("Is the platform ready to use now?", "The platform runs on a cloud demo environment with sample data, and every feature on this page is covered by automated tests. Live operation for a developer starts after the demo meeting and the set-up of its data (projects, units, payment plans, letterhead)."),
                ("Do I need to install anything?", "No. Mabaniq is a web application that runs in the browser on desktop and mobile, for staff, customers and brokers. The private copy is deployed on the company's servers with ready containers."),
                ("How is my company's data isolated from other developers?", "By row-level security in the database: the engine itself prevents any query from seeing another developer's rows, independent of application code. The private copy gives you a fully separate database."),
                ("Does the platform support Islamic finance?", "Islamic finance only: no interest in any payment plan or marketing offer, and the platform refuses interest-bearing wording. Late payment is handled by a charity clause (a donation to a charity, not revenue for the developer); its final wording is approved by the company's Sharia advisor."),
                ("Are documents issued under my company's identity?", "Yes. Quotes, contracts, invoices and receipts are issued as PDF with your letterhead, logo, stamp and authorised signature, and every document carries a verification code and a QR to a public verification page that shows no personal data."),
                ("What does the customer see?", "A mobile web app: their unit and its construction progress, their instalment schedule and next payment, their contract, invoices and receipts, their floor plan and unit position, maintenance requests after handover, and owners' association votes."),
                ("Does it integrate with the accounting system?", "Journals are exported in ERPNext format, and reports as CSV and PDF. Other integrations (an Omani payment gateway, WhatsApp Business, the company's e-mail) are enabled at go-live with the company's own accounts."),
                ("What language is the platform in?", "Arabic first, right to left, with an English version of the shell, the sign-in screen and the customer app. Dates are Hijri then Gregorian, digits are Western."),
                ("Where is the data hosted?", "In the subscription model on managed cloud hosting with a PostgreSQL database and a rehearsed backup-restore drill; in the private copy on the company's own infrastructure. Hosting and backup specifications are presented in the demo meeting."),
                ("How do I get a live demo?", "Fill in the “Request a live demo” form below. The Jadwa team will contact you within two working days to schedule a one-hour meeting where we show the platform live on data similar to your projects."),
            ],
        },
        "demo": {
            "h2": "Request a live demo",
            "lead": "A one-hour meeting where we show the platform live, collect your company's needs and agree on the engagement model and a go-live timeline.",
            "side": ["No account is created from this form and your data is not shared with third parties", "We reply within two working days", "The demo is in Arabic, and can be in English"],
            "name": "Name", "company": "Company", "email": "E-mail", "phone": "Phone", "projects": "Number of current projects",
            "message": "Message (optional)", "message_ph": "What would you like to see in the demo?", "send": "Send request",
            "consent": "By sending the request you agree to the",
            "privacy": "privacy policy.",
        },
        "footer": {
            "org": "Jadwa for Studies & Development", "org_url": "https://jadwa.om", "place": "Muscat, Sultanate of Oman",
            "links": [("/en/privacy", "Privacy policy"), ("/login", "Sign in"), ("/", "العربية")],
            "updated": f"Last updated: {UPDATED['hijri']} ({UPDATED['iso']})",
        },
        "ld_org_name": "Jadwa for Studies & Development", "ld_app_name": "Mabaniq", "ld_app_desc": "Real-estate development platform from booking to handover",
    },
}


# ─────────────────────────────────────────────────────────────────────────── helpers
def e(s: str) -> str:
    return html.escape(str(s), quote=True)


def jpeg_size(path: Path) -> tuple[int, int]:
    """Width/height from the JPEG SOF marker (no image library needed at build time)."""
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
        seg = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + seg
    raise ValueError(f"no SOF marker in {path}")


def img(name: str, alt: str, eager: bool = False) -> str:
    p = IMG / f"{name}.jpg"
    w, h = jpeg_size(p)
    extra = ' loading="eager" fetchpriority="high"' if eager else ' loading="lazy" decoding="async"'
    return f'<div class="shot"><div class="shot-bar" aria-hidden="true"><i></i><i></i><i></i></div><img src="./img/landing/{name}.jpg" alt="{e(alt)}" width="{w}" height="{h}"{extra}></div>'


def ld_json(obj: dict) -> str:
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + "</script>"


# ─────────────────────────────────────────────────────────────────────────── page
def render(lang: str) -> str:
    c = CONTENT[lang]
    base = PH
    nav = "".join(f'<a href="{href}">{e(label)}</a>' for href, label in c["nav"])
    hero_img = img(c["hero"]["img"][0], c["hero"]["img"][1], eager=True)
    problems = "".join(f'<div class="card"><div class="n">{i + 1}</div><h3>{e(t)}</h3><p class="muted">{e(b)}</p></div>' for i, (t, b) in enumerate(c["problems"]["cards"]))
    stages = "".join(f'<div class="stage"><b>{e(t)}</b><ul>{"".join(f"<li>{e(x)}</li>" for x in items)}</ul></div>' for t, items in c["cycle"]["stages"])
    cross_t, cross_items = c["cycle"]["cross"]
    cross = f'<div class="cross"><b>{e(cross_t)}</b>' + "".join(f"<span>{e(x)}</span>" for x in cross_items) + "</div>"
    feats = []
    for i, f in enumerate(c["features"]):
        layout = f.get("layout", "")
        pics = "".join(img(n, a) for n, a in f["imgs"])
        feats.append(f'<article class="feat{" flip" if i % 2 else ""}"><div class="feat-txt"><h3>{e(f["h3"])}</h3><p>{e(f["p"])}</p>'
                     f'<ul>{"".join(f"<li>{e(x)}</li>" for x in f["ul"])}</ul></div><div class="feat-img {layout}">{pics}</div></article>')
    why = "".join(f'<div class="card"><div class="ic" aria-hidden="true">◆</div><h3>{e(t)}</h3><p class="muted">{e(b)}</p></div>' for t, b in c["why"]["items"])
    models = "".join(f'<div class="card"><span class="tag">{e(tag)}</span><h3>{e(t)}</h3><ul>{"".join(f"<li>{e(x)}</li>" for x in items)}</ul></div>' for tag, t, items in c["models"]["cards"])
    faq = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in c["faq"]["items"])
    d = c["demo"]
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
    # JSON-LD: Organization (Jadwa) · SoftwareApplication (Mabaniq) · FAQPage
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
            f'<meta property="og:type" content="website"><meta property="og:site_name" content="Mabaniq | مبانيك"><meta property="og:locale" content="{"ar_OM" if lang == "ar" else "en_US"}">\n'
            f'<meta property="og:title" content="{e(c["title"])}"><meta property="og:description" content="{e(c["description"])}">\n'
            f'<meta property="og:url" content="{base}{c["home"]}"><meta property="og:image" content="{base}{c["og_image"]}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">\n'
            f'<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{e(c["title"])}"><meta name="twitter:description" content="{e(c["description"])}"><meta name="twitter:image" content="{base}{c["og_image"]}">\n'
            f'<meta name="theme-color" content="#0F1724">\n<link rel="icon" type="image/svg+xml" href="./img/favicon.svg">\n<link rel="stylesheet" href="./fonts.css">\n<link rel="stylesheet" href="./landing.css">\n'
            f'{ld_json(ld_org)}\n{ld_json(ld_app)}\n{ld_json(ld_faq)}\n</head>\n')
    body = (f'<body class="lp">\n<a class="skip" href="#main">{e(c["skip"])}</a>\n'
            f'<header class="nav"><div class="wrap nav-in"><a class="brand" href="{c["home"]}"><span class="mk" aria-hidden="true">{"م" if lang == "ar" else "M"}</span><span>{"مبانيك" if lang == "ar" else "Mabaniq"}</span></a>'
            f'<button class="menu-btn" id="menu" aria-label="{e(c["menu"])}" aria-expanded="false" aria-controls="navLinks">☰</button>'
            f'<nav class="nav-links" id="navLinks" aria-label="{e(c["menu"])}">{nav}<a href="{c["other_href"]}" hreflang="{c["other_lang"]}" lang="{c["other_lang"]}">{e(c["other_label"])}</a>'
            f'<a class="btn btn-ghost" href="/login">{e(c["login"])}</a><a class="btn" href="#demo">{e(c["cta"])}</a></nav></div></header>\n'
            f'<main id="main">\n<section class="hero"><div class="wrap hero-grid"><div><span class="eyebrow">{e(c["hero"]["eyebrow"])}</span><h1>{e(c["hero"]["h1"])}</h1>'
            f'<p class="lead">{e(c["hero"]["lead"])}</p><div class="cta-row"><a class="btn btn-lg" href="#demo">{e(c["cta"])}</a><a class="btn btn-ghost btn-lg" href="#features">{e(c["cta2"])}</a></div>'
            f'<p class="note">{e(c["hero"]["note"])}</p></div><div>{hero_img}</div></div></section>\n'
            f'<section class="sec" id="problems"><div class="wrap"><div class="sec-head"><h2>{e(c["problems"]["h2"])}</h2><p>{e(c["problems"]["lead"])}</p></div><div class="grid">{problems}</div><p class="close">{e(c["problems"]["close"])}</p></div></section>\n'
            f'<section class="sec alt" id="cycle"><div class="wrap"><div class="sec-head"><h2>{e(c["cycle"]["h2"])}</h2><p>{e(c["cycle"]["lead"])}</p></div><div class="cycle">{stages}</div>{cross}</div></section>\n'
            f'<section class="sec" id="features"><div class="wrap"><div class="sec-head"><h2>{e(c["features_h2"])}</h2><p>{e(c["features_lead"])}</p></div>{"".join(feats)}</div></section>\n'
            f'<section class="sec dark" id="why"><div class="wrap"><div class="sec-head"><h2>{e(c["why"]["h2"])}</h2><p>{e(c["why"]["lead"])}</p></div><div class="why">{why}</div></div></section>\n'
            f'<section class="sec" id="models"><div class="wrap"><div class="sec-head"><h2>{e(c["models"]["h2"])}</h2><p>{e(c["models"]["lead"])}</p></div><div class="models">{models}</div><p class="muted" style="margin-top:16px">{e(c["models"]["note"])}</p></div></section>\n'
            f'<section class="sec alt" id="faq"><div class="wrap"><div class="sec-head"><h2>{e(c["faq"]["h2"])}</h2></div><div class="faq">{faq}</div></div></section>\n'
            f'<section class="sec" id="demo"><div class="wrap demo-grid"><div class="demo-side"><h2>{e(d["h2"])}</h2><p class="muted">{e(d["lead"])}</p><ul>{"".join(f"<li>{e(x)}</li>" for x in d["side"])}</ul></div>{form}</div></section>\n'
            f'</main>\n<footer class="foot"><div class="wrap foot-grid"><div><a href="{ft["org_url"]}" rel="noopener">{e(ft["org"])}</a> · {e(ft["place"])}<br><span>{e(ft["updated"])}</span></div>'
            f'<nav class="foot-links" aria-label="footer">{foot_links}</nav></div></footer>\n<script type="module" src="./landing.js"></script>\n</body>\n</html>\n')
    return head + body


def main() -> None:
    for lang, name in (("ar", "landing.html"), ("en", "landing-en.html")):
        out = WEB / name
        out.write_text(render(lang), encoding="utf-8", newline="\n")
        print(f"{name}: {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
