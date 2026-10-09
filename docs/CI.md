# التكامل المستمر (CI) — مبانيك

الملف: `.github/workflows/ci.yml`. **لم يُشغَّل على GitHub بعد** (لا remote — قرار المالك 10). كل «نجح» في
`docs/ACCEPTANCE.md` يعني: نجح محليًا بالأمر نفسه الذي يشغّله CI.

| الوظيفة | ما تفعله | متى تُسقط البناء |
| --- | --- | --- |
| `quality` | `ruff check backend tests` · `node --check` لكل سكربت ثابت · لا `onclick=` ولا `<script>` مضمّن في HTML · `pip-audit` | أي خطأ lint، أي سكربت لا يُحلَّل، أي معالج مضمّن، أي CVE معروف |
| `test` | `pytest -q tests` على SQLite · `python -m backend.selfcheck` · **ويتأكد أن selfcheck يفشل** عند `MABANIQ_ENV=prod` بلا أسرار | أي اختبار؛ أو نجاح الإنتاج بلا أسرار (خلل في fail-fast) |
| `test-pg` | `pytest` ضد PostgreSQL 17 (خدمة) عبر `MABANIQ_DATABASE_URL` ثم **pgTAP** (`python db/run_pgtap.py`: RLS مفعّلة ومفروضة وسياسة وعمود `org_id` على كل جدول + عزل سلوكي بين مطوّرين) | `continue-on-error: true` حتى تكتمل الوحدة 1، ثم يصبح حاجزًا |
| `image` | `docker build` بـ`GIT_SHA` ثم تشغيل الحاوية والتحقق من `/health` و`/version` | فشل البناء أو عدم الاستجابة خلال 60 ثانية |

## التشغيل محليًا بنفس الأوامر

```bash
ruff check backend tests
for f in frontend/*.js; do node --check "$f"; done
python -m pytest -q tests
python -m backend.selfcheck
MABANIQ_ENV=prod python -m backend.selfcheck; echo "exit=$? (يجب ألا يكون 0)"
docker build -f deploy/Dockerfile -t mabaniq:local .
```

## النشر (لاحقًا — `deploy.yml`)

يُضاف بعد قرار الاستضافة (قرار المالك 3): `main` أخضر ⟵ staging تلقائيًا؛ وسم `v*` ⟵ production بموافقة
يدوية في GitHub Environments؛ أسرار كل بيئة في Environments لا في المستودع؛ النسخة الاحتياطية اليدوية قبل أي
ترحيل يغيّر بيانات (`docs/RUNBOOK.md`).
