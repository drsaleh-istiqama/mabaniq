# دليل التشغيل (RUNBOOK) — مبانيك

> الحالة: البيئة المحلية والحاوية عاملتان (الوحدة 0). staging/production تنتظران قرار الاستضافة
> (`docs/OWNER_DECISIONS.md` #3). كل ما هو غير مُجرَّب مكتوب هنا بصيغة «مقترح».

## 1. البيئات

| البيئة | القاعدة | الخدمة | من ينشر |
| --- | --- | --- | --- |
| `local` | SQLite تحت `data/` (قاعدة لكل مطوّر) — أو PostgreSQL عبر `docker compose` من الوحدة 1 | `uvicorn backend.app:app --port 8800` | المطوّر |
| **Railway «mabaniq» / production** (بيئة **عرض** حاليًا، 2026-10-09) | قالب PostgreSQL على Railway (`Postgres`) — `MABANIQ_DATABASE_URL=${{Postgres.DATABASE_URL}}`؛ `MABANIQ_ENV=demo` + بيانات تجريبية + `MABANIQ_DEMO_PASSWORD` | خدمة `mabaniq-api` من GitHub `drsaleh-istiqama/mabaniq` فرع `main` (Dockerfile: `deploy/Dockerfile` في إعدادات الخدمة، فحص `/health`)؛ النطاق `mabaniq-api-production.up.railway.app` | كل دفعة إلى `main` |
| `production` الفعلي (لاحقًا) | القاعدة نفسها أو مشروع منفصل، **بلا بيانات تجريبية**، نسخ يومية خارج الموقع | الحاوية نفسها + `MABANIQ_ENV=prod` (يشترط المفاتيح والنطاق النهائي) | وسم `v*` + موافقة |

**ملاحظات Railway:** يرفض البنّاء تعليمة `VOLUME` في Dockerfile، و`railway.json` (Config as Code) مهجور — الإعدادات في الخدمة نفسها (`dockerfilePath`, `healthcheckPath`) أو في `.railway/railway.ts` لاحقًا. مجلد `data/` داخل الحاوية مؤقت: الحالة الدائمة في PostgreSQL ومتغيرات البيئة فقط (مفتاح التشفير وسر الدفع وكلمة العرض). `uvicorn --proxy-headers --forwarded-allow-ips='*'` خلف وكيل Railway فقط.

قواعد ثابتة:

- `MABANIQ_ENV=prod` يرفض الإقلاع ما لم تُعيَّن `MABANIQ_PII_KEY` و`MABANIQ_PAY_SECRET` و`MABANIQ_DATABASE_URL`
  و`MABANIQ_APP_DOMAIN` (ليس example.org) و`MABANIQ_FORCE_PW_CHANGE=1` (`backend/config.py::validate`).
- في الإنتاج لا حسابات عرض: يُنشأ مدير واحد بكلمة مؤقتة في `data/first-admin-password.txt` (0600) يُحذف الملف عند
  أول تغيير لكلمة المرور. غيّرها فورًا وفعّل التحقق الثنائي (إلزامي للمدير والمالية في الإنتاج).
- الأسرار لا تُكتب في الحاوية ولا في git؛ تُمرَّر بيئةً من منصة الاستضافة.

## 2. التشغيل والفحص

```bash
python -m backend.selfcheck                    # قبل كل عرض/نشر: الإعدادات، /health، /ready، الترويسات، CSP، authz
curl -s http://127.0.0.1:8800/health           # حيّ؟ (لا يلمس القاعدة)
curl -s http://127.0.0.1:8800/ready            # جاهز؟ القاعدة + الأسرار + الإعدادات (503 إن لا)
curl -s http://127.0.0.1:8800/version          # الإصدار، البيئة، SHA، نوع القاعدة، حدود المعدل
```

السجلات أسطر JSON على stdout: `{"ts","level","request_id","method","path","status","ms","ip","user"}`. ابحث بمعرّف
الطلب الذي يراه المستخدم في رسالة الخطأ 500 (`request_id`).

## 3. الترحيلات

- PostgreSQL: كل تغيير مخطط ملف جديد `db/migrations/NNNN_name.sql`؛ لا يُعدَّل ملف طُبِّق على أي بيئة. تُطبَّق
  الملفات غير المسجَّلة في `schema_migrations` تلقائيًا عند أول اتصال في كل عملية (`dbx.apply_migrations`) **بدور
  الاتصال** (مالك القاعدة)، ثم ينزل كل اتصال إلى `mabaniq_app` ويعيّن `app.org_id`. في الإنتاج يُفضَّل تشغيل
  الترحيل خطوةً صريحة قبل النشر: `python -c "import psycopg,backend.dbx as d; d.apply_migrations(psycopg.connect('$MABANIQ_DATABASE_URL'))"`.
- قبل ترحيل يغيّر بيانات: نسخة احتياطية يدوية فورية (§4).
- SQLite (تطوير): `db.init` يضيف الأعمدة الناقصة من `MIGRATIONS`، و`pii.encrypt_existing` يشفّر أي حقل هوية مكشوف،
  و`gateway_secret` يحذف أي سر قديم من جدول الإعدادات.
- الكتلة المحلية: `C:\mabaniq\.local\pgdata` على 54330 (ثنائيات PostgreSQL 17 المحمولة في `C:\istiqama-map\.local\pg\bin`):
  `pg_ctl -D C:\mabaniq\.local\pgdata -l C:\mabaniq\.local\postgres.log start` · قاعدة `mabaniq_test` + `CREATE EXTENSION pgtap`.
  اختبارات: `MABANIQ_DATABASE_URL=postgresql://postgres@127.0.0.1:54330/mabaniq_test python -m pytest tests` ثم `python db/run_pgtap.py`.

## 4. النسخ الاحتياطي والاسترجاع

| الطبقة | الآن | المستهدف (الوحدة 4) |
| --- | --- | --- |
| نسخة منطقية | `POST /api/admin/backup` (SQLite `.backup` تحت `data/backups/`، آخر ١٤ نسخة، 0600) | `pg_dump` يومي إلى تخزين منفصل عن الخادم + فحص `pg_restore --list` |
| تمرين استرجاع | **لم يُجرَّب بعد** | شهريًا على قاعدة جديدة، مع مقارنة عدد الصفوف وسلامة سلسلة التدقيق (`/api/audit/verify`) |
| PITR | — | بحسب مزوّد الاستضافة (قرار المالك 3) |
| الأسرار | `data/secrets/` (demo) — **فقدانها = فقدان قراءة أرقام الهوية المشفَّرة** | نسخة من `MABANIQ_PII_KEY` في مدير أسرار منفصل |

إجراء الاسترجاع (SQLite): أوقف الخدمة ⟵ انسخ ملف النسخة إلى `data/mabaniq.db` ⟵ شغّل ⟵ `/ready` ⟵ `/api/audit/verify`
يجب أن يعيد `ok: true`.

## 5. الاحتفاظ بالبيانات (PDPL)

- طلبات الخصوصية: `GET /api/privacy` ⟵ `POST /api/privacy/{id}/process` (الحذف إخفاء هوية؛ يُرفض آليًا عند
  التزامات قائمة). **لا جدولة آلية بعد** للاحتفاظ؛ تُضاف في الوحدة 4 مع سياسة مكتوبة.
- سجل التدقيق append-only (محفّزات) ويحفظ «اطلاع على بيانات هوية» باسم المطّلع.

## 6. الحوادث

| العرض | التشخيص | الإجراء |
| --- | --- | --- |
| كل الطلبات 500 «database is locked» (SQLite) | اتصال مفتوح بمعاملة ناقصة (درس 2026-10-09) | أعد تشغيل الخدمة؛ راجع السجل بمعرّف الطلب الأول |
| 429 كثيرة لمستخدم واحد خلف NAT | حدود المعدل لكل IP | ارفع `MABANIQ_RATE_API` مؤقتًا؛ الحل الدائم حدود لكل حساب (الوحدة 2) |
| `/ready` 503 `secrets: missing` | بيئة الإنتاج بلا مفاتيح | عيّن المتغيرات وأعد التشغيل؛ لا تنشئ مفاتيح على الخادم يدويًا |
| تعذّر فك التشفير `⟨تعذّر فك التشفير — مفتاح مختلف⟩` | `MABANIQ_PII_KEY` تغيّر | استعد المفتاح الأصلي من مدير الأسرار؛ لا يوجد مسار إعادة تشفير بلا المفتاح القديم |
