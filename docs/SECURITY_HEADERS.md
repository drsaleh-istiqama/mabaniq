# ترويسات الأمان — مبانيك

المصدر الواحد: `backend/app.py::_inner` (يُختبر في `tests/test_unit0.py::test_security_headers_complete` و`tests/test_security.py`
و`python -m backend.selfcheck`). الخادم يرسلها على **كل** استجابة؛ لا يُعتمد على وسيط أمامي.

## سياسة أمان المحتوى (CSP)

```
default-src 'self';
script-src 'self';
style-src 'self'; style-src-elem 'self'; style-src-attr 'unsafe-inline';
font-src 'self';
img-src 'self' data:;
connect-src 'self'; worker-src 'self'; manifest-src 'self';
object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
```

| التوجيه | لماذا هكذا |
| --- | --- |
| `script-src 'self'` | لا سكربتات مضمّنة ولا `eval` ولا مضيف خارجي. الإصدار 0.5.0 نقل سكربتات `login/client/broker` إلى ملفات وحوّل ٦٠ معالج `onclick` إلى `data-call`/`data-args` مع مستمع مفوَّض واحد (`J()` يحوّل الوسائط إلى JSON مهرَّب). |
| `style-src 'self'` · `font-src 'self'` | **منذ الوحدة 3 (0.8.0):** لا مضيف خارجي إطلاقًا — الأنماط في ملفات مُجزَّأة من Vite، وخط Tajawal مستضاف ذاتيًا (`web/fonts/*.woff2`، كما في الخارطة). `style-src-elem 'self'` يمنع أي `<style>` مضمّن. |
| `style-src-attr 'unsafe-inline'` | **دَين موثَّق:** الواجهة ما زالت تضبط أعراضًا ديناميكية بـ`style="width:…%"` (أشرطة التقدم، الخريطة الحرارية، ألوان الحالة). يسمح بسمات `style` فقط لا بعناصر `<style>` ولا بـ`eval`؛ لا يفتح بابًا لتنفيذ سكربت. يُزال حين تُنقل القيم الديناميكية إلى متغيرات CSS أو `el.style` من السكربت. |
| `img-src 'self' data:` | صور SVG مولَّدة بالشيفرة؛ لا صور خارجية. |
| `connect-src 'self'` | الواجهة لا تكلّم إلا نفس الأصل. أي مزوّد خارجي (بوابة دفع) يُضاف صراحةً مع اختبار. |
| `frame-ancestors 'none'` | التطبيق لا يُؤطَّر؛ `X-Frame-Options: DENY` للمتصفحات القديمة. |

قاعدة الشيفرة الجديدة: لا `<script>` مضمّن، لا `onclick=`، لا `javascript:`؛ المعالجات عبر `data-call`.

## بقية الترويسات

| الترويسة | القيمة | ملاحظة |
| --- | --- | --- |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` | سنتان. `preload` قرار مالك (يصعب التراجع عنه). |
| `Referrer-Policy` | `same-origin` | المسارات (أرقام الحجوزات) لا تغادر الأصل. |
| `X-Content-Type-Options` | `nosniff` | |
| `X-Frame-Options` | `DENY` | |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=(), bluetooth=()` | لا حاجة لأي منها في الواجهة الحالية. |
| `Cross-Origin-Opener-Policy` | `same-origin` | لا نوافذ منبثقة لتسجيل الدخول. |
| `Cross-Origin-Resource-Policy` | `same-origin` | |
| `X-Robots-Tag` | `noindex, nofollow` | منصة داخلية. |
| `Cache-Control` | `/api/*` و`/`, `/login`, `/app`, `/broker`: `no-store` · `/static/assets/*`: `public, max-age=31536000, immutable` · بقية `/static/*`: `public, max-age=3600, must-revalidate` | أسماء ملفات Vite تحمل بصمة المحتوى (`index-BVWribFC.js`)، فالصفحة (no-store) تشير دائمًا إلى النسخة الصحيحة والمتصفح لا يعيد تنزيل ما لم يتغير. |
| `X-Request-ID` | معرّف الطلب (يُحترم إن أرسله الوكيل بصيغة آمنة ≤ 64 حرفًا) | يظهر في كل سطر سجل وفي رسائل 500. |
| المستندات المرفوعة (`/api/documents/{id}`) | `Content-Security-Policy: sandbox` + `nosniff` + `no-store` | عرض PDF/صور العملاء معزولًا. |

## مسارات عامة بلا جلسة (0.11.0)

| المسار | ما يكشفه | الحماية |
| --- | --- | --- |
| `/verify/<المطوّر>/<الرمز>` | نوع المستند ورقمه وتاريخ إصداره وبصمة محتواه المختصرة وحالته — **لا أسماء ولا مبالغ ولا هواتف** | الرمز 12 خانة عشوائية؛ صفحة HTML بلا سكربت وبسمات `style` فقط (CSP كما هو) |
| `/d/<المطوّر>/<رمز المشاركة>` | ملف PDF واحد بعينه | رمز 32 بايت عشوائي مُجزَّأ في القاعدة، صلاحية 30 يومًا، يُحصى فتحه؛ يُنشأ فقط عند إرسال واتساب من موظف مخوَّل ويُسجَّل في التدقيق |
| `/api/docs/*.pdf` | مستندات الموظفين | صلاحية بحسب النوع (حجز/مالية/فواتير/KYC) · `/api/portal/docs/*.pdf` للعميل على مستنداته هو فقط |

## الكوكيز

| الكوكي | الخصائص |
| --- | --- |
| `mbq_session` | `HttpOnly; SameSite=Lax; Secure` (عند HTTPS)؛ ١٢ ساعة؛ حد ٥ جلسات للمستخدم. |
| `mbq_tenant` | `HttpOnly; SameSite=Lax; Secure`. |
| `mbq_oauth` | `HttpOnly; SameSite=Lax; Secure`؛ 10 دقائق؛ **مقصورة على المسار `/auth/google`**؛ تربط `state` الموقَّع بالمتصفح البادئ (callback من متصفح آخر يُرفض قبل أي اتصال بـGoogle). |
| `mbq_csrf` | **غير** HttpOnly عمدًا (يقرؤه السكربت ويعيده في `X-CSRF-Token`)؛ `SameSite=Lax; Secure`. |

## حدود المعدل (الوحدة 0)

دلو رموز لكل عنوان IP (الوكيل الموثوق على loopback فقط): الدخول `10/60s` (ويشمل منذ 0.10.0 طلبات استعادة كلمة المرور ورابط الدخول وتعيين كلمة المرور)، إشعار الدفع `60/60s`، كل `/api/*` `600/60s` — قابلة للضبط من البيئة. الرد 429 مع `Retry-After` و`X-RateLimit-Bucket`. الحالة في الذاكرة لكل عملية (الوحدة 1 تنقلها إلى القاعدة لتشاركها النسخ).

## ما بقي

`upgrade-insecure-requests` عند HTTPS فقط (الخادم خلف منصة تفرض HTTPS؛ يُضاف مع النطاق النهائي) · إزالة `style-src-attr 'unsafe-inline'` بنقل القيم الديناميكية إلى متغيرات CSS.
