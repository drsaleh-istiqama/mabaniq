# أدلة التشغيل المصوّرة (0.29.0)

أحد عشر دليلًا بصيغة PDF: دليل مختصر للمدير العام وعشرة أدلة قطاعية. المصادر في `src/*.md`، والصور تُولَّد بـ`scripts/manuals/crawl.mjs`.

إعادة البناء (على قاعدة تجريبية محلية معبّأة):

1. شغّل الخادم على المؤسسة التجريبية (`MABANIQ_TENANTS=bayan:...`) واحصل على جلسة بـ`mint_session` أو بتسجيل الدخول.
2. `node scripts/manuals/crawl.mjs <base> <tenant> <token> deliverables/manuals/_shots` — صور كل قسم وتبويب ونافذة إجراء.
3. `node scripts/manuals/shot.mjs <user> <section> <out.png> --tab ... --click ...` — لقطة إضافية.
4. `python scripts/manuals/build_manuals.py` ثم `node scripts/manuals/topdf.mjs` — HTML ثم PDF في `html/` و`pdf/` (غير مُتتبَّعة في git؛ نسخ PDF النهائية في خزنة د. صالح `deliverables/mabaniq-manuals/`).

صيغة الكتابة موثَّقة في رأس `scripts/manuals/build_manuals.py`، وإحاطة الكتّاب في `BRIEF.md`، وسجل الفجوات المرصودة في `GAPS.md`.
