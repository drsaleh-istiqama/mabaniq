# مبانيك 0.14.0 — صفحة الهبوط العامة وطلب العرض الحي
30 ربيع الآخر 1448هـ · 2026-10-11 · المنفِّذ: claude بطلب د. صالح الزهيمي (جدوى) · يبني على 0.13.1

## صفحة الهبوط (`/` و`/en`)
- **كان:** `/` يحوّل الزائر غير المسجَّل إلى `/login`؛ المنصة كلها `noindex`.
- **صار:** الزائر يرى صفحة هبوط عربية RTL على `/` ونسخة إنجليزية LTR على `/en` (hreflang متبادل)؛ المسجَّل يبقى يُحوَّل إلى لوحته.
  بنية الصفحة: عنوان القيمة + «اطلب عرضًا حيًّا» ⟵ المشكلات الثلاث ⟵ دورة التطوير الثلاثية ⟵ ثماني ميزات بلقطات حقيقية من المطوّر التجريبي العام ⟵
  لماذا مبانيك ⟵ صيغتا التعاون بلا أسعار ⟵ عشرة أسئلة شائعة ⟵ نموذج الطلب ⟵ تذييل.
- مدخلان جديدان في Vite (`web/landing.html`، `web/landing-en.html`) يولّدهما `tools/build_landing.py` من محتوى واحد؛ `landing.css` بخصائص منطقية؛ `landing.js`
  بلا سكربت مضمّن. 14 صورة (JPEG ≤ 200 KB) من `tools/landing_shoot.mjs` و`tools/landing_assets.py`. `scripts/size-check.mjs` يفحص مدخلي الهبوط والصور.
- `scripts/check-web.mjs`: يسمح بـ`dir="ltr" lang="en"` للملف `*-en.html` وحده، ويستثني كتل JSON-LD من فحص السكربت المضمّن (بيانات لا تُنفَّذ).

## SEO التقني (`backend/landing.py`)
- canonical · hreflang · Open Graph · Twitter Card · JSON-LD (`Organization`، `SoftwareApplication`، `FAQPage`) — كلها تُشتق من `MABANIQ_PUBLIC_URL`
  عبر العنصر النائب `__PUBLIC_URL__` الذي يستبدله الخادم عند الطلب (لا نطاق ثابت — قرار المالك 4 معلّق).
- `robots.txt` و`sitemap.xml` (أربعة عناوين ببدائل اللغة)؛ صورة OG مولَّدة برمجيًا 1200×630 (`/og.png`، `/og-en.png`) بلا أشخاص ولا نماذج صور.
- `X-Robots-Tag: index, follow` على الصفحات العامة فقط؛ الوسيط يضيف `noindex, nofollow` لكل ما سواها (كان يفرضه على الكل).
- تحقق Search Console: `/google<token>.html` من `MABANIQ_GSC_TOKEN`، و`/BingSiteAuth.xml` من `MABANIQ_BING_TOKEN` (404 حين فارغان).

## طلب العرض الحي (`POST /api/public/demo-request`)
- Pydantic بحدود، honeypot (`website`)، دلو معدل مستقل `MABANIQ_RATE_DEMO=5/3600` لكل عنوان، فحص الأصل ونوع المحتوى كما في بقية `/api`.
- جدول جديد `demo_requests` (ترحيل `0007`) **بلا `org_id` وبلا RLS** — الاستثناء الوحيد، موثَّق في رأس الترحيل وفي pgTAP (`01_rls_isolation.sql`: يُستثنى من
  الفحوص العامة ويحصل على ستة فحوص خاصة: لا `org_id`، لا RLS، INSERT نعم، UPDATE على `mailed` فقط).
- بريد إلى `MABANIQ_SALES_EMAIL` عبر `mail.send` (صندوق الصادر في العرض)؛ سطر تدقيق بلا بيانات شخصية؛ لا يُنشئ حسابًا.
- قاعدة احتفاظ جديدة: `MABANIQ_RETENTION_DEMO_REQUESTS_DAYS=365` (تُنفَّذ مرة في مرور مطوّر المشغّل).

## سياسة الخصوصية (`/privacy`، `/en/privacy`)
- صفحة عامة مولَّدة من الخادم تعيد استعمال ورقة أنماط الهبوط: إشعار العملاء (`PRIVACY_NOTICE` نفسه، بلا تغيير في إصداره) + قسم نموذج الطلب (ما يُجمع،
  لماذا، أين، كم يومًا) + الكوكيز (لا كوكي ولا تحليلات على الصفحات العامة) + الأمان.

## الاختبارات والتوثيق
- `tests/test_landing.py` (12 اختبارًا) · pgTAP +6 · `e2e/landing.spec.js` · `test_api.py::test_requires_login` حُدِّث (الزائر يرى الهبوط لا تحويلًا).
- `docs/LANDING.md` (جديد) · `docs/RUNBOOK.md` §7 «ما بعد النشر» · `docs/SECURITY_HEADERS.md` · `docs/ACCEPTANCE.md` البند 21 · `.env.example`.
