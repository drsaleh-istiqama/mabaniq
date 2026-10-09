# ترويسات الأمان — مبانيك

المصدر الواحد: `backend/app.py::_inner` (يُختبر في `tests/test_unit0.py::test_security_headers_complete` و`tests/test_security.py`
و`python -m backend.selfcheck`). الخادم يرسلها على **كل** استجابة؛ لا يُعتمد على وسيط أمامي.

## سياسة أمان المحتوى (CSP)

```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
font-src https://fonts.gstatic.com;
img-src 'self' data:;
connect-src 'self';
object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
```

| التوجيه | لماذا هكذا |
| --- | --- |
| `script-src 'self'` | لا سكربتات مضمّنة ولا `eval` ولا مضيف خارجي. الإصدار 0.5.0 نقل سكربتات `login/client/broker` إلى ملفات وحوّل ٦٠ معالج `onclick` إلى `data-call`/`data-args` مع مستمع مفوَّض واحد (`J()` يحوّل الوسائط إلى JSON مهرَّب). |
| `style-src 'unsafe-inline'` + Google Fonts | **دَين مقبول مؤقتًا**: الواجهة الحالية تستعمل `style=` مضمّنًا وخط IBM Plex Sans Arabic من Google. الوحدة 3 (Vite) تستخرج الأنماط إلى ملفات وتستضيف الخط ذاتيًا ثم تصبح `style-src 'self'; font-src 'self'` كما في خارطة الاستقامة. |
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
| `Cache-Control` | `/api/*` و`/`, `/login`, `/app`, `/broker`: `no-store` · `/static/*`: `public, max-age=3600, must-revalidate` | الملفات الثابتة تحمل `?v=<الإصدار>`؛ ملفات بأسماء مُجزَّأة (immutable) في الوحدة 3. |
| `X-Request-ID` | معرّف الطلب (يُحترم إن أرسله الوكيل بصيغة آمنة ≤ 64 حرفًا) | يظهر في كل سطر سجل وفي رسائل 500. |
| المستندات المرفوعة (`/api/documents/{id}`) | `Content-Security-Policy: sandbox` + `nosniff` + `no-store` | عرض PDF/صور العملاء معزولًا. |

## الكوكيز

| الكوكي | الخصائص |
| --- | --- |
| `mbq_session` | `HttpOnly; SameSite=Lax; Secure` (عند HTTPS)؛ ١٢ ساعة؛ حد ٥ جلسات للمستخدم. |
| `mbq_tenant` | `HttpOnly; SameSite=Lax; Secure`. |
| `mbq_csrf` | **غير** HttpOnly عمدًا (يقرؤه السكربت ويعيده في `X-CSRF-Token`)؛ `SameSite=Lax; Secure`. |

## حدود المعدل (الوحدة 0)

دلو رموز لكل عنوان IP (الوكيل الموثوق على loopback فقط): الدخول `10/60s`، إشعار الدفع `60/60s`، كل `/api/*` `600/60s` — قابلة للضبط من البيئة. الرد 429 مع `Retry-After` و`X-RateLimit-Bucket`. الحالة في الذاكرة لكل عملية (الوحدة 1 تنقلها إلى القاعدة لتشاركها النسخ).

## ما بقي (الوحدة 3)

`style-src 'self'` · `font-src 'self'` · `upgrade-insecure-requests` عند HTTPS فقط · `Cache-Control: immutable` للملفات المُجزَّأة.
