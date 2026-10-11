# صفحة الهبوط العامة — مبانيك (0.14.0)

> صفحة ترويجية عامة للمنصة تُخدم من الخادم نفسه على `/` (عربية RTL) و`/en` (إنجليزية LTR)، تُفهرسها محركات البحث، وتحوّل الزائر إلى
> **طلب عرض حي**. ليست موقعًا منفصلًا: الترويسات الأمنية والنشر التلقائي (GitHub ⟵ Railway) هي نفسها. القواعد الملزمة: عربية أولًا، RTL صريح،
> أرقام غربية، الهجري قبل الميلادي، لا أسعار، لا أسماء عملاء، لا أرقام مخترعة، لا أشخاص في الصور، لا مضيف خارجي، لا إضعاف لـCSP.

## 1. البنية

| الطبقة | الملف | الدور |
| --- | --- | --- |
| المحتوى + القالب | `tools/build_landing.py` | **المصدر الوحيد** للنصين العربي والإنجليزي (`CONTENT`) والهيكل؛ يولّد `web/landing.html` و`web/landing-en.html` (مُتتبَّعان في git حتى يبنيهما Vite داخل الحاوية بلا بايثون) |
| الأنماط والسكربت | `web/landing.css` · `web/landing.js` | خصائص منطقية (`inline-start/end`) فالملف الواحد يخدم RTL وLTR؛ السكربت: نموذج الطلب عبر `fetch` + قائمة الهاتف. لا سكربت مضمّن ولا `onclick` |
| الصور | `web/img/landing/*.jpg` · `web/img/favicon.svg` | لقطات من المطوّر التجريبي العام `jadwa` فقط (JPEG ≤ 200 KB) + صفحة أولى من عرض سعر وفاتورة صادرَين من المنصة بترويسة تجريبية |
| الخادم | `backend/landing.py` | `/en` · `/privacy` · `/en/privacy` · `/robots.txt` · `/sitemap.xml` · `/og.png` · `/og-en.png` · `/google<token>.html` · `/BingSiteAuth.xml` · `POST /api/public/demo-request`؛ و`/` في `app.py` يستدعي `landing.page` للزائر غير المسجَّل |
| القاعدة | `db/migrations/0007_landing_demo_requests.sql` + `backend/db.py` (SQLite) | جدول `demo_requests` **بلا `org_id` وبلا RLS** (استثناء موثَّق في رأس الترحيل وفي pgTAP `01_rls_isolation.sql`) |
| الاحتفاظ | `backend/retention.py` | `demo_requests` أقدم من `MABANIQ_RETENTION_DEMO_REQUESTS_DAYS` (365) تُحذف؛ تُنفَّذ مرة في مرور مطوّر المشغّل |
| الاختبارات | `tests/test_landing.py` (12) · `db/tests/01_rls_isolation.sql` (+6) · `e2e/landing.spec.js` | المسارات، SEO، الترويسات، النموذج (نجاح/honeypot/حدّ/حدود)، الاحتفاظ؛ pgTAP للاستثناء؛ Playwright للمتصفح |

**ترتيب القراءة في الصفحة:** عنوان القيمة + زر «اطلب عرضًا حيًّا» ⟵ المشكلات الثلاث ⟵ دورة التطوير الثلاثية ⟵ الميزات الثماني بلقطات ⟵ لماذا مبانيك
⟵ صيغتا التعاون (بلا أسعار) ⟵ أسئلة شائعة (10) ⟵ نموذج الطلب ⟵ تذييل.

**ما يعتمد على النطاق لا يُكتب ثابتًا:** الصفحة المبنية تحمل العنصر النائب `__PUBLIC_URL__` في canonical وhreflang وOpen Graph وJSON-LD، ويستبدله
الخادم عند كل طلب بـ`MABANIQ_PUBLIC_URL` (أو أصل الطلب إن لم يُضبط). `sitemap.xml` و`robots.txt` يُولَّدان من المتغيّر نفسه. حين يُحسم النطاق
(قرار المالك 4) يكفي ضبط المتغيّر.

## 2. المتغيرات الجديدة

| المتغيّر | الافتراضي | الدور |
| --- | --- | --- |
| `MABANIQ_PUBLIC_URL` | (أصل الطلب) | الأصل العام المطلق لكل روابط SEO (كان موجودًا للهوية الخارجية) |
| `MABANIQ_SALES_EMAIL` | (المرسِل SMTP، وإلا صندوق الصادر في العرض) | إلى أين يُرسل طلب العرض الحي |
| `MABANIQ_RATE_DEMO` | `5/3600` | دلو مستقل لكل عنوان IP على `POST /api/public/demo-request` (ترويسة `X-RateLimit-Bucket: demo`) |
| `MABANIQ_RETENTION_DEMO_REQUESTS_DAYS` | `365` | حذف طلبات العرض القديمة |
| `MABANIQ_GSC_TOKEN` | (فارغ = 404) | تحقق Google Search Console بملف HTML: يقبل الرمز وحده أو اسم الملف `google<token>.html` |
| `MABANIQ_BING_TOKEN` | (فارغ = 404) | تحقق Bing Webmaster عبر `/BingSiteAuth.xml` |

## 3. نموذج طلب العرض الحي

- الحقول: الاسم (2–80)، الشركة (2–120)، البريد (نمط)، الهاتف (نمط)، عدد المشاريع (0–1000)، رسالة اختيارية (≤ 1000)، اللغة، وحقل honeypot
  مخفي `website` (أي قيمة فيه ⟵ ردّ «نجاح» بلا تخزين).
- الحماية: CSRF لا ينطبق (لا جلسة) لكن فحص الأصل (`Origin` = المضيف) ونوع المحتوى JSON والحجم ≤ 64 KB يبقون؛ دلو معدل مستقل؛ Pydantic بحدود.
- التخزين: صف في `demo_requests` (البريد بأحرف صغيرة، بصمة IP مختصرة لا العنوان، UA مقتطع) ⟵ سطر تدقيق **بلا بيانات شخصية** (`#id · اللغة · عدد المشاريع`)
  في سجل مطوّر المشغّل ⟵ بريد عبر `mail.send` (SMTP أو `data/outbox/`) ⟵ `mailed=1`. فشل البريد لا يُفقد الطلب (يُسجَّل في السجل).
- **لا يُنشئ حسابًا**، ولا يُقرأ من أي مسار مُستأجر. القراءة اليوم من القاعدة مباشرة (أو من بريد المبيعات)؛ لوحة إدارة للطلبات ليست في هذا الإصدار.

## 4. SEO التقني

`<title>` ووصف لكل لغة · H1 واحد · canonical · `hreflang` (ar/en/x-default) · Open Graph + Twitter Card بصورة مولَّدة برمجيًا 1200×630
(`backend/landing.py::og_png`: fpdf2 + HarfBuzz + Tajawal، بلا أشخاص ولا نماذج صور، تُرسم مرة لكل عملية) · JSON-LD ثلاث كتل
(`Organization` لجدوى، `SoftwareApplication` لمبانيك، `FAQPage`) · `robots.txt` (يسمح بالعام ويمنع `/api/`، `/app`، `/broker`، `/login`،
`/verify/`، `/d/`، `/auth/`، الصحة والمقاييس — ولا يمنع `/static/` لأن Google يحتاج CSS/JS للعرض) · `sitemap.xml` بأربعة عناوين وبدائل اللغة ·
`X-Robots-Tag: index, follow` على الصفحات العامة فقط (الباقي `noindex, nofollow` كما كان) · نص بديل وأبعاد صريحة وتحميل كسول لكل صورة
بعد الأولى · خط Tajawal ذاتي بـ`font-display: swap`.

**JSON-LD وCSP:** كتل `<script type="application/ld+json">` بيانات لا تُنفَّذ، فليست ضمن `script-src`. `scripts/check-web.mjs`
و`tests/test_landing.py` يستثنيانها فقط ويرفضان أي `<script>` مضمّن آخر. CSP لم تتغيّر.

## 5. كيف تُحدَّث النصوص واللقطات

```bash
# 1) النصوص: عدّل CONTENT في tools/build_landing.py (العربية ثم الإنجليزية)، ثم:
python tools/build_landing.py && npm run check && npm run build && npm run size
# 2) اللقطات: شغّل المنصة محليًا (SQLite، كلمة عرض اختبارية) ثم:
MABANIQ_DEMO_PASSWORD=<test> python tools/landing_assets.py    # عرض سعر + فاتورة ⟵ web/img/landing/doc-*.jpg
MABANIQ_DEMO_PASSWORD=<test> node tools/landing_shoot.mjs       # 12 لقطة JPEG ≤ 200 KB من المطوّر jadwa (Chrome عبر Playwright)
python tools/build_landing.py && npm run build                   # الأبعاد تُقرأ من الملفات نفسها
# 3) حدّث LASTMOD في backend/landing.py حين يتغيّر المحتوى (sitemap <lastmod>)، وتاريخ «آخر تحديث» في build_landing.py (UPDATED).
# 4) الاختبارات قبل الدفع:
python -m pytest -q tests && npm run e2e && ruff check backend tests
```

قواعد اللقطات: المطوّر `jadwa` فقط (بيانات تجريبية بلا اسم عميل)، الوضع الفاتح، 1440×900 للموظف و430×900 ×2 للعميل، JPEG بجودة تنزل حتى
تحت 200 KB، ولا لقطة لشاشة الدخول. ترويسة المستندات التجريبية «جدوى للتطوير — بيانات تجريبية» يضبطها `landing_assets.py`، والصفحة تُقصّ قبل
ذيلها (رابط التحقق المحلي).

## 6. الأداء (Lighthouse، هاتف)

`npx -y lighthouse@13 http://127.0.0.1:8800/ --preset=... --form-factor=mobile` على Chrome المحلي؛ الملخص في `docs/lighthouse-landing.json`
(الدرجات الأربع + التدقيقات غير الكاملة). الميزانيات: JS الأولي ≤ 200 kB gzip (الفعلي ≈ 1 kB)، كل صورة ≤ 200 KB (`npm run size` يحرسهما).

## 7. ما لم يُنفَّذ عمدًا (بقرار مكتوب لاحقًا)

- لا تحليلات خارجية (Google Analytics/Tag Manager) ولا Google Fonts: أي مضيف خارجي = تغيير CSP + تحديث سياسة الخصوصية + قرار مالك.
- لا لوحة لإدارة طلبات العرض داخل المنصة؛ ولا تكامل CRM.
- لا صفحات هبوط لكل مشروع/مطوّر (الصفحة للمنصة نفسها).
