# تقرير القبول — مبانيك v1 (رفع البنية)

> **التاريخ:** 2026-10-09 (توقيت مسقط). **النطاق:** الوحدة 0 من `PROGRESS.md`، والخط الأساس الموروث من 0.5.0.
> **كيف قيس كل شيء:** على جهاز التطوير (Windows 11) بالأوامر نفسها التي يشغّلها `.github/workflows/ci.yml`.
> **تنبيه صريح:** لم يُشغَّل CI على GitHub بعد (لا remote — قرار المالك 10)؛ كل «نجح» أدناه = نجح محليًا.

## معايير القبول (قابلة للقياس) وحالتها

| # | المعيار | الأمر | الحالة |
| --- | --- | --- | --- |
| 1 | كل اختبارات pytest تنجح على SQLite | `python -m pytest -q tests` | ✅ 73 اختبارًا (50 أصلية + 5 لـ0.4.1 + 12 لـ0.5.0 + 6 للوحدة 0) |
| 2 | كل اختبارات pytest تنجح على PostgreSQL 17 | `MABANIQ_DATABASE_URL=postgresql://postgres@127.0.0.1:54330/mabaniq_test python -m pytest tests` | ✅ 73 اختبارًا (118 ث على الكتلة المحلية) — `test-pg` حاجز في CI |
| 3 | pgTAP: RLS مفعّلة ومفروضة وسياسة وعمود `org_id` على كل جدول؛ الدور لا يتجاوز RLS ولا يملك UPDATE/DELETE على `audit`؛ قراءة عبر المطوّرين = 0 صف؛ تحديث عبرهم لا يمس شيئًا؛ إدراج لمطوّر آخر يُرفض | `python db/run_pgtap.py` | ✅ 250 تحققًا على 60 جدولًا |
| 4 | لا سكربت مضمّن ولا `onclick=` ولا مضيف سكربت خارجي؛ CSP `script-src 'self'` | `grep` في CI + `test_security.py::test_csp_has_no_inline_scripts` + selfcheck | ✅ |
| 5 | الترويسات الثماني على كل استجابة (HSTS سنتان، COOP، CORP، Permissions-Policy…) | `test_unit0.py::test_security_headers_complete` | ✅ |
| 6 | CSRF: جلسة صالحة بلا رمز مطابق ⟵ 403 على كل طلب مُعدِّل | `test_security.py::test_csrf_cross_origin_blocked`, `test_fixes_050.py::test_m7_*` | ✅ |
| 7 | الإنتاج يرفض الإقلاع بإعدادات ناقصة؛ `/ready` يعيد 503 عند غياب الأسرار | `MABANIQ_ENV=prod python -m backend.selfcheck` ⟵ RuntimeError يعدّد الناقص | ✅ |
| 8 | معرّف طلب على كل استجابة وفي كل سطر سجل وفي رسائل 500 بلا تسريب تفاصيل | `test_unit0.py::test_request_id_*`, `::test_unhandled_error_*` | ✅ |
| 9 | حدّ معدل لتسجيل الدخول متميز عن القفل (429 + `Retry-After`) | `test_unit0.py::test_login_rate_limit_distinct_from_lockout` | ✅ (حالة لكل عملية — الوحدة 1 تنقلها إلى القاعدة) |
| 10 | صفر ملاحظات lint؛ كل سكربت ثابت يُحلَّل | `ruff check backend tests` · `node --check frontend/*.js` | ✅ |
| 11 | لا ثغرات معروفة في الاعتمادات | `pip-audit -r requirements.txt` | ⚠️ لم يُشغَّل محليًا (يحتاج اتصالًا بقاعدة الثغرات) — يعمل في CI |
| 12 | صورة Docker تُبنى وتجيب `/health` | وظيفة `image` في CI · **Railway**: بناء `deploy/Dockerfile` ونشر على `mabaniq-api-production.up.railway.app` | ✅ (2026-10-09) الصورة بُنيت على Railway وأجابت `/health` و`/ready` (قاعدة PostgreSQL مُدارة، الأسرار، الإعدادات) و`/version` بـ`database: postgresql`؛ الترويسات الكاملة على الاستجابة الحية |
| 12ب | بيئة عرض مستضافة ببيانات تجريبية على PostgreSQL مع عزل المطوّرين | تسجيل دخول حي بكلمة العرض لمطوّرين مختلفين وقائمة مشاريع مختلفة | ✅ (2026-10-09) — انظر `docs/RUNBOOK.md` §1 |
| 13 | الثوابت المالية: فارق الدفتر 0، لا تسليم بلا شروطه، لا إيراد من التأخير، الفواتير بمعرّف العميل، الإيجار متناسب | `tests/test_fixes_041.py`, `tests/test_fixes_050.py` | ✅ |
| 14 | تمرين استرجاع نسخة احتياطية موثَّق | `docs/RUNBOOK.md` §4 | ⬜ الوحدة 4 |
| 15 | حمل: p95 لـ`/api/decisions` و`/api/cash` < 500 ملي ثانية مع 300 مستخدم و5 مطوّرين × 500 وحدة | k6 | ⬜ الوحدة 4 (القياس اليدوي الحالي: 134 و114 ملي ثانية لمستخدم واحد على 468 وحدة) |
| 16 | Playwright للمسار الحرج: حجز ⟵ KYC ⟵ موافقة ⟵ عقد ⟵ توقيع ⟵ سداد ⟵ خطاب بنكي ⟵ تسليم | — | ⬜ الوحدة 3 |

## حالة الوحدات

| الوحدة | الحالة | الدليل |
| --- | --- | --- |
| و0 الهيكل والأدوات | ✅ (CI مكتوب غير مُشغَّل؛ Docker غير مُجرَّب محليًا) | `backend/config.py`, `backend/observability.py`, `backend/selfcheck.py`, `tests/test_unit0.py`, `.github/workflows/ci.yml`, `deploy/Dockerfile`, `docker-compose.yml`, `docs/*` |
| و1 PostgreSQL + RLS | ✅ | `backend/dbx.py`, `db/migrations/0001_initial.sql` (676 سطرًا، مولَّد بـ`db/gen_pg_schema.py`), `db/tests/01_rls_isolation.sql`, `db/run_pgtap.py`؛ 512 استدعاء SQL تعمل على المحركين بلا تفريع في منطق الأعمال |
| و2 الهوية | ⬜ | |
| و3 الواجهة | ⬜ | |
| و4 التشغيل | ⬜ | |

## قرارات المالك المعلّقة

`docs/OWNER_DECISIONS.md` — أهمها للمسار: (2) المكدّس مستقل أم Frappe، (3) الاستضافة، (5) المستشار الشرعي، (6) مسؤول حماية البيانات، (10) GitHub.
