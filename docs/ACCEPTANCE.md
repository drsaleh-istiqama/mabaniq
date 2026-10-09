# تقرير القبول — مبانيك v1 (رفع البنية)

> **التاريخ:** 2026-10-10 (توقيت مسقط). **النطاق:** الوحدات 0–4 من `PROGRESS.md`، والخط الأساس الموروث من 0.5.0.
> **كيف قيس كل شيء:** على جهاز التطوير (Windows 11) بالأوامر نفسها التي يشغّلها `.github/workflows/ci.yml`؛ CI يعمل على GitHub `drsaleh-istiqama/mabaniq` منذ 2026-10-09، والنتائج الحية على Railway.
> **تنبيه صريح:** «نجح» = نجح محليًا بالأمر المذكور؛ ما يعتمد على بيئة المالك (النسخ المجدول، Sentry، حجم الحمل الكامل) مُعلَّم ⚠️.

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
| 9ب | قفل متدرّج: بعد 3 إخفاقات يُطلب انتظار متزايد (429 + `X-Lockout: graded`) ويستطيع صاحب الحساب الدخول بعد المهلة؛ لا قفل كامل يستغله الغير | `test_unit2.py::test_graded_cooldown_never_locks_the_account_out` | ✅ |
| 9ج | ميزانية الدخول في القاعدة (10/60 ث لكل عنوان) تعمل حتى بعد تصفير الدلو في الذاكرة | `test_unit2.py::test_login_budget_is_in_the_database` | ✅ |
| 9د | جلسات بجهاز وعنوان، مهلة خمول 60 دقيقة، إنهاء ذاتي (جلسة/كل الأجهزة) وإداري فوري | `test_unit2.py::test_session_inventory_and_revoke_others`, `::test_idle_timeout_*`, `::test_admin_revokes_*` | ✅ |
| 9هـ | رموز استرداد تُستهلك مرة، تدوير الجلسات عند تفعيل TOTP، إعادة ضبط إداري للتحقق الثنائي | `test_unit2.py::test_recovery_codes_and_rotation_and_admin_reset` | ✅ |
| 13 | الثوابت المالية: فارق الدفتر 0، لا تسليم بلا شروطه، لا إيراد من التأخير، الفواتير بمعرّف العميل، الإيجار متناسب | `tests/test_fixes_041.py`, `tests/test_fixes_050.py` | ✅ |
| 14 | تمرين استرجاع نسخة احتياطية موثَّق | `python scripts/backup/drill.py --source … --target mabaniq_drill --pgtap` (نسخ ⟵ استرجاع في قاعدة جديدة ⟵ صفوف كل جدول = البيان ⟵ ترحيلات متطابقة ⟵ سلسلة التدقيق ⟵ pgTAP على النسخة ⟵ حذف) · `docs/RUNBOOK.md` §4 | ✅ 2026-10-10 محليًا (62 جدولًا، 9,409 صفًا، pgTAP 391) · خطوة في وظيفة `test-pg` مع تقرير مرفوع |
| 14ب | سياسة احتفاظ PDPL مجدولة وموثَّقة، لا تمس الدفاتر ولا التدقيق، بسطر تدقيق لكل تشغيل | `tests/test_unit4.py::test_retention_*` · `docs/RUNBOOK.md` §5 | ✅ |
| 14ج | `updated_at` بمحفّز على كل جدول؛ لا DELETE للدور على 14 دفترًا ماليًا؛ مجمّع اتصالات يعيد الدور والمستأجر عند كل إرجاع | `db/tests/02_unit4_integrity.sql` (137 تحققًا) · `test_unit4.py::test_pool_*`, `::test_integrity_*` | ✅ |
| 14د | مقاييس Prometheus خلف رمز، بلا معرّفات في التسميات؛ Sentry اختياري بلا PII | `test_unit4.py::test_metrics_*` | ✅ |
| 15 | حمل: p95 لـ`/api/decisions` و`/api/cash` < 500 ملي ثانية مع 300 مستخدم و5 مطوّرين × 500 وحدة | `sh load-tests/run.sh postgres 300` (`load-tests/mix.js`، نتائج في `load-tests/results/`) | ✅ جزئيًا (2026-10-10، محليًا، PostgreSQL، مطوّر واحد × 468 وحدة): **بأربع عمليات p95 = 51 / 36 ms، 36,869 طلبًا، 0٪ فشل**؛ بعملية واحدة 584 / 561 ms (لا يحقق). ⚠️ حجم 5 مطوّرين × 500 وحدة والقياس على Railway لم يُجرَيا بعد — `load-tests/README.md` |
| 16 | Playwright للمسار الحرج: حجز ⟵ KYC ⟵ موافقة ⟵ عقد ⟵ توقيع ⟵ سداد ⟵ خطاب بنكي ⟵ تسليم | `e2e/critical-path.spec.js` (5 اختبارات متسلسلة في متصفح حقيقي: دخول الموظف من الواجهة، الحجز حتى التوقيع، إنشاء حساب العميل، دخول العميل وتغيير كلمة المرور الإلزامي وسداد «دفعة أولى» من البوابة، رفض التسليم بلا خطاب صرف ثم شهادة `HC-` وفارق دفتر 0، وتبديل اللغة) | ✅ محليًا (Chrome) 10 ث · وظيفة `e2e` في CI |
| 16ب | الواجهة: حزمة Vite مُجزَّأة immutable، لا سكربت مضمّن، `style-src 'self'`/`font-src 'self'` بلا Google Fonts، JS الأولي ≤ 200 kB gzip | `scripts/size-check.mjs` (31.0 kB gzip JS · 6.2 kB CSS · 55.7 kB خطوط ذاتية) · `tests/test_fixes_050.py::test_m7_*` · `test_unit0.py::test_security_headers_complete` | ✅ |
| 16ج | أرقام غربية في كل الواجهة (قرار المالك ب) — ثابت واحد `WD()` في طبقة التنسيق يطبّع نصوص الخادم أيضًا؛ لا رقم هندي في المصادر | `scripts/check-web.mjs` · `e2e` يفحص شريط المؤشرات | ✅ |

## حالة الوحدات

| الوحدة | الحالة | الدليل |
| --- | --- | --- |
| و0 الهيكل والأدوات | ✅ (CI مكتوب غير مُشغَّل؛ Docker غير مُجرَّب محليًا) | `backend/config.py`, `backend/observability.py`, `backend/selfcheck.py`, `tests/test_unit0.py`, `.github/workflows/ci.yml`, `deploy/Dockerfile`, `docker-compose.yml`, `docs/*` |
| و1 PostgreSQL + RLS | ✅ | `backend/dbx.py`, `db/migrations/0001_initial.sql` (676 سطرًا، مولَّد بـ`db/gen_pg_schema.py`), `db/tests/01_rls_isolation.sql`, `db/run_pgtap.py`؛ 512 استدعاء SQL تعمل على المحركين بلا تفريع في منطق الأعمال |
| و2 الهوية | ✅ | `backend/auth.py`, `db/migrations/0002_unit2_identity.sql`, `tests/test_unit2.py` |
| و3 الواجهة | ✅ (TypeScript مؤجَّل — انظر PROGRESS) | `web/` (المصادر) ⟵ `vite.config.js` ⟵ `frontend/dist` (المخرجات، غير مُتتبَّعة) · `web/i18n.js` + `web/locales/{ar,en}.json` · `web/fonts/` · `scripts/check-web.mjs` · `scripts/size-check.mjs` · `playwright.config.js` · `e2e/critical-path.spec.js` · `deploy/Dockerfile` مرحلتان |
| و4 التشغيل | ✅ (النسخ اليومي المجدول وDSN Sentry وحجم 5×500 بيد المالك/بيئته) | `backend/dbx.py` (مجمّع)، `backend/db.py` (`OPEN`)، `db/migrations/0003_unit4_integrity.sql`، `db/tests/02_unit4_integrity.sql`، `backend/retention.py`، `backend/cache.py`، `backend/observability.py` (`/metrics`، Sentry)، `scripts/backup/{dump,drill}.py`، `load-tests/`، `tests/test_unit4.py` |

## قرارات المالك المعلّقة

`docs/OWNER_DECISIONS.md` — أهمها للمسار: (2) المكدّس مستقل أم Frappe، (3) الاستضافة، (5) المستشار الشرعي، (6) مسؤول حماية البيانات، (10) GitHub.
