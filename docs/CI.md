# التكامل المستمر (CI) — مبانيك

الملف: `.github/workflows/ci.yml`. يعمل على GitHub `drsaleh-istiqama/mabaniq` منذ 2026-10-09. كل «نجح» في
`docs/ACCEPTANCE.md` يعني: نجح محليًا بالأمر نفسه الذي يشغّله CI.

| الوظيفة | ما تفعله | متى تُسقط البناء |
| --- | --- | --- |
| `quality` | `ruff check backend tests` · `npm run check` (كل `web/*.js` يُحلَّل، لا `onclick=` ولا `<script>` مضمّن، `dir="rtl" lang="ar"` على الجذر، لا أرقام هندية في المصادر) · `npm run build` + `npm run size` (ميزانية JS الأولي ≤ 200 kB gzip) · `pip-audit` · `npm audit --audit-level=high` | أي خطأ lint، أي فحص ويب، تجاوز الميزانية، أي CVE معروف |
| `test` | `pytest -q tests` على SQLite (بعد `npm run build` — الخادم يرفض الإقلاع بلا `frontend/dist`) · `python -m backend.selfcheck` · **ويتأكد أن selfcheck يفشل** عند `MABANIQ_ENV=prod` بلا أسرار | أي اختبار؛ أو نجاح الإنتاج بلا أسرار (خلل في fail-fast) |
| `test-pg` | `pytest` ضد PostgreSQL 17 (خدمة) عبر `MABANIQ_DATABASE_URL` ثم **pgTAP** (`python db/run_pgtap.py`: RLS مفعّلة ومفروضة وسياسة وعمود `org_id` على كل جدول + عزل سلوكي بين مطوّرين) | حاجز منذ الوحدة 1 |
| `e2e` | **Playwright** في Chromium على خادم مؤقت (SQLite، كلمة عرض معروفة): المسار الحرج حجز ⟵ KYC ⟵ تأكيد ⟵ عقد ⟵ توقيع ⟵ حساب عميل ⟵ دخول العميل وتغيير كلمة المرور ⟵ سداد من البوابة ⟵ خطاب صرف بنكي ⟵ شهادة تسليم، + CSP/الحزمة المُجزَّأة + تبديل اللغة (`e2e/critical-path.spec.js`) | أي خطوة؛ الآثار (trace) تُرفع عند الفشل |
| `image` | `docker build` بـ`GIT_SHA` ثم تشغيل الحاوية والتحقق من `/health` و`/version` | فشل البناء أو عدم الاستجابة خلال 60 ثانية |

## التشغيل محليًا بنفس الأوامر

```bash
ruff check backend tests
npm ci && npm run check && npm run build && npm run size
python -m pytest -q tests
npm run e2e                     # Playwright (محليًا Chrome المثبَّت؛ في CI Chromium)
python -m backend.selfcheck
MABANIQ_ENV=prod python -m backend.selfcheck; echo "exit=$? (يجب ألا يكون 0)"
docker build -f deploy/Dockerfile -t mabaniq:local .
```

## النشر (لاحقًا — `deploy.yml`)

يُضاف بعد قرار الاستضافة (قرار المالك 3): `main` أخضر ⟵ staging تلقائيًا؛ وسم `v*` ⟵ production بموافقة
يدوية في GitHub Environments؛ أسرار كل بيئة في Environments لا في المستودع؛ النسخة الاحتياطية اليدوية قبل أي
ترحيل يغيّر بيانات (`docs/RUNBOOK.md`).
