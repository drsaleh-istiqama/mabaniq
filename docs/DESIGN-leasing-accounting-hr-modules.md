# تصميم: الإيجارات المتكاملة · المحاسبة · الموارد البشرية · وحدات قابلة للتخصيص

> **الحالة:** مسودة تصميم v1 — 2026-10-28 — بتوجيه المالك د. صالح الزهيمي. **لا شيفرة قبل مراجعة هذه الوثيقة وردّ المالك على الأسئلة المفتوحة (`docs/OWNER_DECISIONS.md` §«الإيجارات والمحاسبة والموارد البشرية»).**
> كل قيمة مؤقتة هنا مُعلَنة ومُعزولة في إعداد/جدول لتتغيّر بلا تعديل شيفرة.

## 0. الأساس الذي نبني عليه (قُرئ فعليًا من المستودع)

| البند | الحقيقة المقروءة | الأثر على التصميم |
| --- | --- | --- |
| الإصدار | `backend/config.py::VERSION = "0.19.1"` (لا 0.18.2 كما في نص التكليف؛ 0.19.0 رؤية العقارية و0.19.1 إصلاح الحجز موجودان **غير مدفوعين**: خمسة التزامات أمام `origin/main`) | مراحل هذا العمل تبدأ من **0.20.0** لا 0.19.x؛ أول دفع سيحمل معه 0.19.0/0.19.1 أيضًا (انظر سؤال الدفع) |
| الترحيل التالي | آخر ملف `0007_landing_demo_requests.sql` | نبدأ بـ`0008` كما طُلب |
| طبقة البيانات | محركان: PostgreSQL (ملفات `db/migrations/*.sql`) وSQLite (`backend/db.py::SCHEMA` + `MIGRATIONS` للأعمدة) | كل جدول/عمود يُكتب **مرتين** (ملف ترحيل + `SCHEMA`/`MIGRATIONS`) ويُضاف إلى `seed.ALL_TABLES` وقائمة REVOKE وpgTAP |
| التأجير الحالي | `tenants_l(name,phone,id_number)` · `leases(unit_id,tenant_id,start,end,annual_rent,frequency,deposit,status,municipality_ref)` · `rent_dues(lease_id,due,amount,paid,paid_date)` · `units.retained` يحدّد «محفظة التأجير» · الشاشة فرعية في `post.lease` | نبقي الجداول ونوسّعها (لا حذف ولا إعادة تسمية)، ونفصل الدفعات عن الاستحقاقات |
| المالية | فواتير `invoices` تُصدَر بـ`issue_invoice` (تسلسل = `COUNT(*)+1` — **غير آمن للتزامن**، يُصلَح في المرحلة 3)، `payments` للأقساط، `bank_lines`، `charity_dues` (مربوط بـ`installment_id` فقط) | تبرع التأخير يُعمَّم ليخدم الإيجار؛ ترقيم المستندات يصير بجدول عدّادات |
| الصلاحيات | `auth.ROLES/PERMS` ثابتة في الشيفرة؛ `need()/need_any()/act_as()`؛ الواجهة `SCREEN_PERM/SCREEN_ANY` في `web/app.js` + `data-s` في `index.html` | الوحدات تُرشِّح `PERMS` وقت التشغيل؛ الشاشات تختفي تلقائيًا لأن `canS` يبني على الصلاحيات |
| المطوّرون | `MABANIQ_TENANTS` + `tenant_profiles.PROFILES`؛ «المقصورة» `real_only` ببذر `seed_real` | حقل جديد `modules` في ملف التعريف؛ البذر الحقيقي **لا يُعاد** بعد أول إدخال يدوي (انظر §8.3) |
| الوثائق | `paperwork.py` (يقرر من يرى ويرسل) + `pdfgen.py` (يرسم) + `doc_issues` (رمز تحقق/QR) | أنواع مستندات جديدة تتبع القاعدة المكتوبة في `CLAUDE.md` (مُصيِّر + فرع `render()` + `STAFF_PERMS` + فحص ملكية البوابة + اختبار) |
| Excel | لا `openpyxl` في `requirements.txt` (CSV بـBOM فقط) | إضافة `openpyxl` (إصدار مثبَّت) للتصدير/الاستيراد — **قرار طفيف يُعلَن** |

**ما لا نغيّره:** استقلال المنصة (FastAPI لا Frappe — قرار المالك 2)، RLS على `org_id`، CSP بلا سكربتات مضمّنة، الأرقام الغربية، التمويل الإسلامي فقط، «ما لم يُوثَّق يبقى فارغًا».

---

## 1. المبادئ الحاكمة

1. **وحدة = حدّ قابل للإطفاء كاملًا:** شاشات، مسارات API، صلاحيات، مؤشرات، مهام خلفية، أدوات المساعد، تقارير. إطفاؤها **لا يحذف بيانات**؛ يُخفيها ويرفض مسارها بـ404 موحّدة.
2. **المحاسبة حدث لا إدخال:** كل حدث مالي في المنصة (فاتورة، تحصيل، مصروف…) يُنتج قيدًا مزدوجًا **في المعاملة نفسها**؛ لا قيد يُنشأ بعد الواقعة بمهمة خلفية.
3. **دفاتر لا تُحذف ولا تُعدَّل:** `acc_lines` و`rent_payments` وما شابه — لا DELETE ولا UPDATE للدور `mabaniq_app`؛ التصحيح بقيد عكسي/حركة معاكسة (امتداد قاعدة 0003).
4. **القواعد بيانات لا شيفرة:** نسب التأمينات، أرصدة الإجازات، قاعدة مكافأة نهاية الخدمة، نسب الضريبة، عمولة المدير — كلها جداول/إعدادات بتاريخ سريان، وقيمها الأولية **مؤقتة تحتاج مراجعة مختص** (لا أدّعي دقتها).
5. **التوافق الخلفي:** المطوّرون القائمون (jadwa، nahda، almukhatat، bayan، view) يبقون على «المؤسسة الكاملة» بلا تغيير مرئي حتى يضبطهم المالك؛ المقصورة وحدها تُضبط على `leasing + finance + reports + assistant`.
6. **لا اختراع بيانات:** القيم المجهولة NULL؛ الاستيراد لا يملأ فراغًا بتخمين؛ أرصدة افتتاحية المحاسبة تأتي من مصدر موثَّق أو تُترك صفرًا مع علامة.

---

## 2. سجل الوحدات (المرحلة 1 — 0.20.0)

### 2.1 الوحدات وتبعياتها

| المفتاح | الاسم | تبعيات إلزامية | ما يخصّها اليوم من الصلاحيات (`PERMS`) |
| --- | --- | --- | --- |
| `core` (دائمة، لا تُطفأ) | النواة: العقارات/الوحدات (سجل)، المستخدمون، التدقيق، المستندات، الإشعارات، الإدارة | — | `view` `inventory` `users` `audit` `admin` `docs` `notify` |
| `sales` | المبيعات: حجز، عروض أسعار، عقود بيع، أقساط، KYC، وسطاء، سوق ثانوي | `finance` | `book` `kyc` `brokers` `confirm` `broker_portal` |
| `leasing` | الإيجارات (هذه الوثيقة §3) | `finance` | `leasing` + جديدة |
| `construction` | الإنشاء والمستخلصات والجودة | `finance` | `construction` `approve_ipc` |
| `marketing` | حملات وإعلانات وعملاء محتملون | `sales` | `leads` `market` |
| `finance` | الفواتير، حسابات الضمان، رادار السيولة، المطابقة، التعثر، تبرعات التأخير | — | `finance` `decide` `invoices` |
| `accounting` | المحاسبة الشاملة (§4) | `finance` | جديدة |
| `hr` | الموارد البشرية والرواتب (§5) | — (`accounting` اختيارية لتوليد القيود) | جديدة |
| `land` | الأراضي والجدوى والتراخيص | — | `land` `permits` |
| `handover` | التسليم وما بعد البيع واتحاد الملاك والخدمات | `sales` | `handover` `oa` `service` |
| `assistant` | المساعد الذكي | — | (يشتق من وحدات أخرى) |
| `reports` | التقارير والمنشئ والجدولة | — (تعرض ما تتيحه الوحدات المفعَّلة) | `reports` |

ملاحظات: (أ) `finance` تبقى الوحدة التي تشمل ما هو موجود اليوم؛ `accounting` وحدة جديدة فوقها. (ب) `handover` جُزِّئت من `post` لأن مؤسسة تأجير فقط لا تحتاج التسليم والتمليك والاتحاد (لكن `fm` الصيانة المرفقية تنتقل لـ`leasing`). (ج) `inventory` (سجل الوحدات والمخططات) في النواة لأنه مشترك بين البيع والتأجير. (د) التبعية «ناعمة» حيث يلزم: `hr→accounting` (توليد قيود الرواتب إن فُعِّلت المحاسبة)، `reports→*`.

### 2.2 التخزين

```sql
-- 0008_modules.sql (يُكتب مرة لـPG ومرة في db.SCHEMA)
org_modules(module text, enabled int NOT NULL, licensed int NOT NULL DEFAULT 1,
            changed_at text, changed_by text, PRIMARY KEY (org_id, module))  -- PG: org_id ضمن المفتاح
module_log  -- لا جدول: كل تفعيل/تعطيل سطر في audit ("تفعيل وحدة"/"تعطيل وحدة") بسلسلة البصمات
```

* **الغياب = الافتراضي:** مطوّر بلا صفوف ⟵ كل الوحدات المرخَّصة افتراضيًا مفعَّلة (توافق خلفي). عند أول تعديل يُكتب الوضع كاملًا.
* **الترخيص ≠ التفعيل:** `licensed` يقرّره مشغّل المنصة (جدوى) عبر ملف التعريف أو متغير بيئة `MABANIQ_LICENSES="almaqsura:leasing_only;…"`؛ مدير المطوّر يفعّل/يعطّل **ضمن المرخَّص** فقط.
* **الباقات** (`backend/registry.py::BUNDLES`، بيانات لا شيفرة، الأسعار حقول فارغة): `leasing_only` = leasing+finance+reports+assistant(+accounting/hr كإضافات)، `develop_sell` = sales+construction+marketing+land+handover+finance+reports+assistant، `develop_lease` = develop_sell+leasing، `enterprise` = الكل.
* **ملف التعريف:** مفتاح اختياري `"modules": [...]` أو `"bundle": "leasing_only"`؛ المقصورة: `["leasing","finance","reports","assistant"]` (والباقي مرخَّص عند الطلب).

### 2.3 الإنفاذ (دفاعًا بعمق)

1. **السجل في الشيفرة:** `backend/registry.py`: `MODULES` (عنوان، تبعيات، `perms`، `screens`، `route_prefixes`، `jobs`، `ready_reports`، `assistant_tools`).
2. **مسارات API:** يُضاف إلى الوسيط `@app.middleware("http")` القائم (app.py ~823) فحصٌ يربط المسار بوحدته بالبادئة؛ الوحدة معطّلة ⟵ **404 بجسم FastAPI نفسه** `{"detail":"Not Found"}` (لا يُكشف أن الوحدة موجودة ومعطّلة). المسارات غير المربوطة تُعامَل **نواة** — ويحرس **اختبارٌ** أن كل مسار في `app.routes` له وحدة صريحة (فيفشل الاختبار إن أُضيف مسار بلا انتماء).
3. **الصلاحيات:** `effective_perms(role, enabled)` = `PERMS[role] ∩ (perms وحدات مفعَّلة ∪ perms النواة)`. يستعملها `need/need_any/act_as` و`/api/me` (فتُخفي الواجهة الشاشات والأزرار تلقائيًا)، فلا يكفي إخفاء الواجهة.
4. **الشريط الجانبي والتبويبات:** سمة `data-mod` على العناصر في `index.html`؛ `app.js` يقرأ `me.modules`. شاشات جديدة تنتمي لوحداتها.
5. **اللوحة وصندوق القرارات:** `/api/decisions` و`/api/dashboard` يتحوّلان إلى **سجل أدوات (widgets) حسب الوحدة**؛ مؤسسة تأجير فقط لا ترى مؤشر مبيعات ولا قرار تسعير. (التفصيل §7.)
6. **المهام الخلفية:** `jobs.tick` يتخطى مهام الوحدات المعطّلة (تنبيهات التسويق، تذكيرات الأقساط…).
7. **المساعد والتقارير:** مرشِّح الوحدات على `assistant.TOOLS` وعلى `reports.READY/DATASETS`.
8. **الإدارة:** شاشة «الوحدات والترخيص» في `adm`: جدول الوحدات (مرخَّصة؟ مفعَّلة؟ تبعيات)، باقات جاهزة بنقرة، تخصيص يدوي؛ رفض التعطيل إن وُجد معتمِد مفعَّل (409 بالقائمة)، وعرض «تفعيل مع التبعيات». **لا تُطفأ إلا بمدير بتحقق ثنائي** (النمط القائم لـ`TWO_FA_REQUIRED`). صفحة «الترخيص» تسرد الوحدات المرخَّصة وتاريخ كل تغيير من `audit`.

### 2.4 الترحيل وعدم الكسر
* القاعدة القائمة بلا صفوف `org_modules` ⟵ سلوك اليوم نفسه. المقصورة: يُكتب وضعها عند الإقلاع (idempotent، بقفل استشاري كباقي خطوات الإقلاع).
* بيانات الوحدات المعطّلة تبقى؛ إعادة التفعيل تعيدها كما كانت.
* اختبارات: مصفوفة (باقة × مسار نموذجي ⟵ 200/404)؛ `/api/me.perms` مرشَّحة؛ حارس المسارات غير المربوطة؛ مؤسسة تأجير فقط لا تحوي أي مفتاح مبيعات في `/api/dashboard`؛ تدقيق التفعيل؛ تعطيل وحدة مطلوبة ⟵ 409.

---

## 3. الإيجارات المتكاملة (المرحلة 2 — 0.21.0 ثم 0.22.0)

### 3.1 النموذج (توسعة الجداول القائمة + جداول جديدة)

**الملاك والعقارات والوحدات**
* `owners(id, name, kind own|third_party, id_number*, phone, email, iban*, mgmt_fee_pct, mgmt_basis collected|invoiced, active, notes)` — `own` صف واحد افتراضي (شركة المطوّر). `third_party` = إدارة أملاك الغير بعمولة (مثل البراعة 5٪). (* مشفّر `pii` حيث شخصي).
* `units` ⟵ أعمدة جديدة: `owner_id`، `lease_state` تجاوز يدوي فقط (`prep|maintenance|not_leasable|NULL`) — **الحالة المعروضة مشتقة**: مؤجَّرة (عقد ساري) · محجوزة بفترة تجهيز · شاغرة · صيانة · غير قابلة للتأجير · وتُحسب `vacant_since`. `use` الموجود (residential/commercial) يتسع إلى `office|warehouse|land` (قيمة نصية، لا قيد CHECK)، `parking_bays`.
* `unit_meters(id, unit_id, kind water|electricity|gas|other, number, provider, shared int)` و`common_facilities(id, project_id, name, kind, notes)`.
* **اشتقاق «محفظة التأجير»:** `units.retained=1` يبقى علامة المحفظة (توافق)، وتُضاف `units.leasable` افتراضيًا = `retained`.

**المستأجرون** (`tenants_l` موسَّعة)
* `kind individual|company`، `cr_number`، `tax_no`، `rep_name`، `rep_title`، `rep_id_number*`، `contact_name`، `email`، `address`، `nationality`، `id_expiry`، `rating` (A–D بسيط يدوي + سبب)، `blacklisted int`, `blacklist_reason`, `blacklisted_by`, `blacklisted_at`, `import_batch`. الهوية/الممثل مشفّران (`pii.ENCRYPTED_COLUMNS`) وتُضاف لقواعد الاحتفاظ/الخصوصية (تصدير/حذف مع حاجز: لا حذف مستأجر بعقد/دين).
* **تاريخ المستأجر عبر الوحدات:** استعلام (لا جدول) على `leases`.
* **القائمة السوداء:** لا تُنشأ عقودٌ جديدة لمستأجر محظور إلا بتجاوز مدير موثَّق السبب؛ السبب إلزامي ويُدقَّق.

**العقود** (`leases` موسَّعة)
`number` (LS-سنة-تسلسل من جدول عدّادات)، `kind`، `signed_at`، `prep_free_days` (فترة تجهيز مجانية)، `start` (بداية العقد) و`rent_start` (بداية الاحتساب بعد التجهيز)، `deposit` (موجود) + `deposit_state held|partly_settled|returned|forfeited_to_charity?`⟵ **لا مصادرة تقديرية**: التسوية بخصومات موثَّقة فقط، `charity_clause int` (تبرع التأخير بشرط العقد)، `municipality_ref` (موجود) + `municipality_fee`, `municipality_date`، `renewed_from`، `terminated_at`, `termination_kind early|expiry|eviction`, `termination_note`, `status draft|active|expired|renewed|terminated|evicted`, `manager_user_id?` (لا)، `source manual|import|seed`.
* `lease_terms(lease_id, year_no, from, to, annual_rent, note)` — **الزيادات السنوية المجدولة** (السنة 1/2/3 كما في عقود البرجين)؛ `leases.annual_rent` يبقى = إيجار السنة الأولى (توافق).
* `lease_events(id, lease_id, kind renew|terminate|evict|amend|note|handover_in|handover_out, at, by, detail json)` سجل زمني.

**الدفعات والتحصيل**
* `rent_dues` موسَّعة: `kind rent|deposit|fee|service|utility|other`, `year_no`, `label`, `plan_id` (إن أُعيدت جدولتها)، `status` مشتقة. `paid`/`paid_date` تبقى **مخبّأة محسوبة** من الحركات (توافق مع الشيفرة والتقارير القائمة).
* **`rent_payments`** (دفتر مالي، لا DELETE/UPDATE): `id, due_id, lease_id, amount, paid_on, method cash|cheque|transfer|card|other|NULL, reference, cheque_id, receipt_no, recorded_by, reverses_id, note`. تسجيل بتاريخ فعلي (سابق مسموح بسبب)، دفعات **جزئية** (حركات متعددة لاستحقاق)، **مقدَّمة** (على عدة استحقاقات تُوزَّع الأقدم أولًا)، **ارتجاع** بحركة عكسية. الطريقة تبقى NULL للتاريخ غير الموثَّق (لا يُخترع).
* **`cheques`**: `id, direction in|out, lease_id, due_id, number, bank, branch, amount, due_date, received_on, status held|deposited|cleared|bounced|returned|cancelled, deposited_on, cleared_on, bounce_reason, drawer, payee, vendor_id, journal_id`. دورة: `held ⟵ deposited ⟵ cleared` (**عندها فقط** تُسجَّل `rent_payment`)، أو `bounced` (يُفتح الاستحقاق، إشعار، ولا فائدة ولا غرامة). `direction=out` تستعمله المحاسبة لاحقًا (§4).
* **الإيصال** مستند `rent_receipt` لكل حركة دفع (رقم وQR كباقي المستندات)، وإيصال استلام شيك (`cheque_receipt`) يثبت الاستلام لا السداد.

**المتأخرات والتحصيل**
* **تعمير:** 0–30/31–60/61–90/91–180/>180 من `rent_dues` غير المسددة (تقرير + مؤشر).
* **تذكيرات:** عبر `notifications` (قبل الاستحقاق N أيام وبعده، `dedupe` موجود)، قابلة للضبط؛ تعمل في `jobs.tick` ضمن وحدة التأجير.
* **إنذارات رسمية مرقّمة:** `arrears_notices(id, lease_id, seq, number NOT NULL UNIQUE, kind reminder|formal|final, issued, cure_by, amount, doc_issue_id, sent_via, sent_at)` ومستند PDF `arrears_notice` بصيغة مُعدّة سلفًا **تحتاج اعتماد المستشار القانوني**.
* **خطة سداد:** `payment_plans(id, lease_id, agreed_on, status, note, approved_by)` + بنودها استحقاقات جديدة بـ`plan_id`؛ **بلا فوائد ولا رسوم**؛ تتطلب موافقة من يملك `leasing_approve`.
* **تبرع التأخير:** `charity_dues` تُعمَّم (`installment_id` يصير اختياريًا، + `rent_due_id`, `lease_id`) ولا يُحتسب إلا حين `leases.charity_clause=1` وبالنسبة/السماح الموجودين (`late_penalty_monthly`, `late_grace_days`)، ولا يدخل الإيرادات (يتجه لحساب خيري مستقل في §4.6).

**الصيانة والمصاريف**
* `vendors(id, name, cr_number, phone, email, trade, iban*, active)` (تستعمله المحاسبة لاحقًا كمورّدين).
* `maint_requests(id, unit_id, lease_id, source tenant|staff, requester, category, description, priority, status new|triaged|assigned|in_progress|done|closed|rejected, created, updated, sla_due, closed_at, rating?)`، `maint_orders(id, request_id, vendor_id, scheduled, cost, charge_to owner|company|tenant, tenant_due_id, doc_ref, done_at)` (تحميل المستأجر ينشئ استحقاق `kind=service` بموافقة موثَّقة وسند من العقد).
* `property_expenses(id, project_id, unit_id, owner_id, category, amount, spent_on, vendor_id, order_id, charge_owner int, charge_tenant int, cost_center_id NULL حتى المحاسبة, doc_id, status)`.
* `fm_assets/work_orders` الحاليان (للمرافق الشاملة) يُنسبان إلى `leasing` عند عدم وجود `handover`.

**المالك الخارجي والمدير العقاري**
* **عمولة الإدارة:** `owners.mgmt_fee_pct` (٪ من المحصَّل — كالبراعة 5٪).
* **كشف المالك الشهري** `owner_statements(id, owner_id, period 'YYYY-MM', collected, expenses, commission, net, status draft|issued|transferred, issued_at, transferred_on, transfer_ref, doc_issue_id)`: **المحصَّل − المصاريف المحمَّلة على المالك − العمولة = صافي التحويل**؛ يُصدر PDF `owner_statement` ويُقفل بعد الإصدار (تصحيح بكشف تعديل).
* **حساب المدير العقاري:** دور جديد `property_manager` (خارجي) بصلاحيات `leasing_collect` و`leasing_view` **مقيَّدة بنطاق** `user_scopes(user_id, project_id)` أو `owner_id` — يسجّل التحصيل ويرى ما في نطاقه فقط، ولا يرى بقية المحفظة ولا يعدّل العقود. التفعيل اختياري بقرار المالك (سؤال).

**بوابة المستأجر** (دور جديد `lessee`، `users.tenant_id`): عقدي، دفعاتي وإيصالاتي، كشف حسابي، طلب صيانة وتتبعه، طلب تجديد. تمتد `client.html`/`app` القائم بشاشات جديدة ونقاط `/api/portal/lease/*` بفحص ملكية لكل صف (نمط `portal_doc`).

### 3.2 دورة حياة العقد

```
مسودة ─توقيع الطرفين─▶ ساري ──(كل شهر)── تحصيل/شيكات ──▶ تذكير ─▶ إنذار ─▶ خطة سداد
   │                      │
   │                      ├─ تجديد ──▶ عقد جديد (renewed_from) + تُغلق الحالي «renewed»
   │                      ├─ إنهاء مبكر ──▶ تسليم/استلام + قراءات عدادات + تسوية التأمين
   │                      ├─ إخلاء (تخلّف) ──▶ إنذار نهائي ثم قرار مدير ثم محضر استلام
   │                      └─ انتهاء ──▶ تنبيه 90/60/30 ثم تجديد أو تسليم
   └─ إلغاء قبل التوقيع (لا أثر مالي)
```
* **الشغور:** عند إغلاق العقد تبدأ `vacant_since` ويُحسب `vacant_days` ومؤشر الشغور في التقارير.
* **محضر التسليم والاستلام** `lease_handovers(id, lease_id, kind in|out, at, by, condition json, keys int, notes, deductions json, doc_issue_id)` + `meter_readings(id, handover_id, meter_id, reading)` — يحتوي مستند PDF موقَّع ببصمة؛ التسوية: التأمين − خصومات موثَّقة (من المحضر والمستندات) = المردود، بقيد في المحاسبة عند تفعيلها.
* **جدول الدفعات الآلي:** عند التوقيع يُولَّد من `lease_terms` والدورية (يقسم 12) و`prep_free_days` (لا استحقاق قبل `rent_start`)، والدفعة الأخيرة بالنسبة (قاعدة M9 القائمة)، وإن كان بشيكات مؤجلة تُنشأ `cheques` مرتبطة بكل استحقاق.
* **إنهاء مبكر:** يحسب الاستحقاقات القادمة المُلغاة؛ بلا غرامات إيرادًا؛ أي مبلغ إنهاء يُتفق عليه يُدخل يدويًا كاستحقاق `fee` بقرار مدير.

### 3.3 نموذج عقد الإيجار PDF
مستند `lease` جديد في `pdfgen/paperwork`: ترويسة المطوّر، التاريخ **الهجري أولًا**، أطراف العقد (المؤجِّر/المالك/الوكيل، المستأجر)، العين المؤجرة (الوحدة والمساحة والعدادات والمواقف)، المدة والتجهيز، الإيجار وجدول الزيادات والدفعات والشيكات، التأمين وتسويته، شرط تبرع التأخير (إن فُعِّل)، مرجع توثيق البلدية، التسليم والاستلام، الإنهاء والتجديد، توقيعات. **ذيل ظاهر:** «نموذج يحتاج اعتماد المستشار الشرعي والقانوني قبل الاستعمال» (يُرفع الوسم بإعداد `lease_template_approved` من المدير بعد الاعتماد، مع تدقيق).

### 3.4 الاستيراد
`backend/importer.py` + شاشة «الاستيراد»: قوالب **Excel/CSV** (ملف مرجعي يُنزَّل من الشاشة) لـ: العقارات والوحدات، المستأجرين، العقود، الدفعات والمدفوعات، الشيكات. المسار: **رفع ⟵ فحص مسبق (dry-run) بلا كتابة ⟵ تقرير أخطاء (صف/عمود/سبب، تحذيرات منفصلة عن أخطاء) ⟵ تأكيد ⟵ تنفيذ بمعاملة واحدة**.
* **مفاتيح طبيعية للمطابقة:** الوحدة `units.code`، المستأجر (`id_number`/`cr_number` أو الاسم+الهاتف)، العقد `leases.number`.
* **لا يمحو ولا يعيد بذرًا:** يُدرج الجديد ويحدّث فقط الصفوف التي `source='import'` وبنفس `import_batch` السابق أو الحقول الفارغة؛ أي تعارض مع صف `manual` يُسجَّل «متعارض — يحتاج قرارًا» ولا يُطبَّق. `import_batches(id, kind, filename, sha256, rows_ok, rows_err, by, at)` + سجل تدقيق.
* **حدود:** 5MB، 5,000 صف، صيغ ومعادلات ممنوعة (تُقرأ القيم فقط)، حقن CSV (`=`/`@`) يُعقَّم في التصدير.

### 3.5 التقارير (تُضاف إلى `reports.READY` + مجموعات `DATASETS`)
تقرير إيجار شهري (بديل تقرير المدير العقاري: المحصَّل بالطريقة، المتأخرات، المصاريف، العمولة، الصافي) · الإشغال والعائد لكل عقار · تعمير المتأخرات · العقود المنتهية خلال 30/60/90 · الشيكات المؤجلة المستحقة/المرتجعة · كشف حساب مستأجر · كشف المالك. كلها بـCSV/PDF كباقي التقارير.

### 3.6 المرحلتان الفرعيتان
* **0.21.0 — جوهر الإيجار:** السجل الموسَّع (مُلاك/وحدات/عدّادات/مستأجرون/قائمة سوداء)، العقود بالزيادات والتجهيز، توليد الجدول، الحركات والإيصالات والدفعات الجزئية والمقدَّمة، الشيكات ودورتها، شاشة `lea` جديدة (استبدال `post.lease`)، مستند العقد والإيصال، تعمير المتأخرات، تذكيرات، ترحيل بيانات المقصورة.
* **0.22.0 — العمليات:** التجديد/الإنهاء/الإخلاء ومحضر التسليم والعدادات وتسوية التأمين، الإنذارات وخطط السداد وتبرع التأخير للإيجار، الصيانة والمصاريف وتحميل المستأجر، الملاك والكشوف وعمولة الإدارة ودور المدير العقاري، الاستيراد، تقارير الإيجار الكاملة.

---

## 4. المحاسبة (المرحلة 3 — 0.23.0 ثم 0.24.0)

### 4.1 النموذج
* `acc_accounts(id, code UNIQUE(org), name, name_en, type asset|liability|equity|revenue|expense, parent_id, postable int, normal debit|credit, system_key NULL, active, vat_class NULL, note)` — شجري. **القالب العُماني الافتراضي** (ملف بيانات `backend/assets/coa_om.json`، يُبذر مرة ويُعدَّل بعدها): أصول متداولة (صندوق، بنوك، شيكات تحت التحصيل، ذمم مستأجرين/مشترين، ضريبة مدخلات، مدفوعات مقدمة)، أصول ثابتة وإهلاك متراكم، مخزون عقاري/أعمال قيد التنفيذ، التزامات (ذمم دائنة، تأمينات مستأجرين، دفعات مقدمة من عملاء، أرصدة ضمان، ضريبة مخرجات، مستحقات رواتب، التزامات تمويل، تبرعات تأخير مستحقة)، حقوق ملكية، إيرادات (بيع، إيجار، عمولة إدارة، أخرى)، مصروفات (تشغيل، صيانة، رواتب، تسويق، إهلاك، تكافل…). **`system_key`** يربط أحداث المنصة بالحسابات (`ar_tenants`، `rev_rent`، `vat_out`، `deposits_held`، `charity_payable`…) ويمكن إعادة ربطه من الشاشة.
* `acc_cost_centers(id, code, name, kind property|project|dept|other, ref_id, parent_id, active)` — تُنشأ تلقائيًا للمشاريع/العقارات والأقسام.
* `acc_periods(id, year, month, status open|closed, closed_by, closed_at)`؛ السنة المالية من إعداد `fiscal_year_start` (مؤقتًا 1 يناير).
* `acc_journals(id, number UNIQUE, date, period_id, memo, source kind, source_ref, status draft|pending|posted|reversed, created_by, approved_by, posted_at, reversal_of, total)` و`acc_lines(id, journal_id, line_no, account_id, cost_center_id, debit, credit, party_type, party_id, vat_class, memo)` — **دفتر لا يُعدَّل** (REVOKE + محفّز يمنع UPDATE/DELETE بعد `posted`)، **توازن** مفروض: فحص في الشيفرة + `CONSTRAINT TRIGGER` مؤجَّل على PG + اختبار.
* المرفقات: جدول `documents` الحالي بـ`ref_type='journal'`.
* `counters(name, scope, value)` — **ترقيم مضمون غير متزامن** (يُصلح `COUNT(*)+1` في الفواتير وكل المستندات الجديدة) مع قفل صف/استشاري.

### 4.2 توليد القيود من الأحداث (`backend/ledger.py`)
`post(c, kind, ref, date, lines, memo)` يُستدعى **داخل معاملة الحدث نفسها**. جدول الأحداث (الحد الأدنى):

| الحدث | القيد |
| --- | --- |
| فاتورة إيجار/بيع | مدين ذمم المستأجر/المشتري · دائن إيراد (+ ضريبة مخرجات) |
| تحصيل إيجار (حركة) | مدين صندوق/بنك (حسب الطريقة) · دائن ذمم المستأجر؛ الشيك: مدين «شيكات تحت التحصيل» ثم عند الإيداع/الصرف بنك |
| تأمين مستأجر | مدين بنك · دائن «تأمينات مستأجرين»؛ التسوية: عكسه + خصومات إلى مصروف/إيراد صيانة |
| مصروف عقار | مدين مصروف (مركز كلفة) · دائن ذمم مورّد/صندوق |
| عمولة إدارة | مدين حساب المالك الخارجي · دائن إيراد عمولة |
| تبرع تأخير | مدين صندوق/بنك · دائن «تبرعات مستحقة» (التزام لا إيراد)، والصرف مدين الالتزام دائن بنك الخيري |
| مستخلص مقاول | مدين أعمال قيد التنفيذ · دائن ذمم مقاول (+ احتجاز 10٪ التزام) |
| صرف من حساب ضمان | مدين التزام الضمان/الذمم · دائن بنك الضمان |
| رواتب (المرحلة 4) | مدين مصروف رواتب (مراكز الأقسام) · دائن مستحقات/تأمينات/سلف |
| إهلاك | مدين مصروف إهلاك · دائن مجمّع إهلاك |

* **قيود يدوية:** مسودة ⟵ اعتماد (فصل المهام: المُنشئ ≠ المعتمِد، إلا مدير عام) ⟵ ترحيل؛ مرفقات إلزامية فوق حد قابل للضبط.
* **ما قبل التفعيل:** `acc_start` (تاريخ بدء المحاسبة) — الأحداث قبله لا تُرحَّل؛ **الأرصدة الافتتاحية** بقيد افتتاحي واحد مستورَد من ميزان مراجعة موثَّق، لا مُخمَّن.
* **تعطيل الوحدة:** مصدر الحدث المعطَّل لا يرحِّل؛ وتفعيل `accounting` لاحقًا يعرض «حركات سابقة لم تُرحَّل» بأمر ترحيل مجمّع اختياري.

### 4.3 الذمم
* **مدينة:** مشتقة من `acc_lines` بحسب `party_type/party_id` (مستأجرون ومشترون): كشوف حساب، تعمير، تسويات.
* **دائنة:** `ap_bills(id, number, vendor_id, bill_date, due_date, net, vat_class, vat, total, status draft|approved|partly_paid|paid|void, journal_id, doc_id)`، `ap_payments(id, bill_id, amount, paid_on, method, bank_account_id, cheque_id, reference, journal_id)`، **أوامر الدفع** `payment_orders` بموافقتين فوق حد، **الشيكات الصادرة** عبر `cheques direction=out`.

### 4.4 البنوك والصناديق
`bank_accounts(id, name, bank, iban*, kind bank|cash|escrow|charity, account_id, currency 'OMR', islamic int NOT NULL DEFAULT 1, project_id)`؛ `bank_lines` (القائمة) تُضاف إليها `bank_account_id` وتتسع المطابقة: استيراد كشف CSV/XLSX لكل حساب، مطابقة آلية بالمبلغ/التاريخ/المرجع واقتراحات، إقفال مطابقة شهري. **حساب غير إسلامي مرفوض** عند الإنشاء (حقل إلزامي + رسالة) — القاعدة 2026-10-04.

### 4.5 الضريبة (VAT عُمانية 5٪)
`vat_class standard|zero|exempt|out_of_scope` على الحسابات والأسطر والمنتجات؛ **الإيجار السكني معفى والتجاري خاضع 5٪** (افتراض مؤقت يؤكده مستشار ضريبي — سؤال مفتوح)؛ الأرقام الضريبية `customers.tax_no`, `tenants_l.tax_no`, `vendors.tax_no`؛ **إقرار ربع سنوي** `vat_returns(id, year, quarter, box_values json, output_vat, input_vat, net, status draft|filed, filed_on, ref)` يُجمَّع من الأسطر ويُصدَّر PDF/CSV (الحقول وفق نموذج الهيئة تُراجع).

### 4.6 التمويل الإسلامي والتبرعات
* `fin_contracts(id, kind murabaha|ijara|installment|salam?…, counterparty, principal, markup_total, start, end, schedule json, status)`: **هامش ربح معلوم مسبقًا** يُسجَّل كربح مؤجَّل يُطفأ مع الأقساط — **لا فوائد متراكمة ولا سعر فائدة متغير** (يُرفض في النموذج). التأمين = **تكافل** (فئة مصروف `takaful`، ويمنع الاسم «تأمين تقليدي» في إنشاء الأصناف).
* تبرع التأخير: حساب التزام `charity_payable` + حساب بنك خيري مستقل (`bank_accounts.kind='charity'`)، **لا يظهر في الإيرادات** ويُفصح عنه في قائمة الدخل كحاشية.

### 4.7 الأصول الثابتة والموازنات والفترات والقوائم
* `fixed_assets(id, code, name, category, cost, acquired, life_months, salvage, method straight_line, cost_center_id, account_cost, account_accum, account_expense, status active|disposed, disposed_on, proceeds)`، `depreciation_runs(id, period, asset_id, amount, journal_id)` — تشغيل شهري مجمّع idempotent.
* `acc_budgets(id, year, cost_center_id, account_id, month, amount)` (الاسم يتفادى تعارض `budgets` القائم للإنشاء) + تقرير الموازنة مقابل الفعلي بانحراف ونسبة.
* **إقفال الفترات:** `acc_periods.status=closed` يمنع الترحيل بتاريخ في فترة مغلقة (إلا قيد تسوية بإعادة فتح موثَّقة بتدقيق)؛ إقفال السنة بقيد ترحيل الأرباح إلى حقوق الملكية.
* **القوائم:** ميزان مراجعة، دفتر أستاذ، كشف حساب، ميزانية عمومية، قائمة الدخل، التدفقات النقدية (غير مباشرة من الحسابات + تصنيف تشغيل/استثمار/تمويل بـ`cash_class` على الحسابات)، التغير في حقوق الملكية. **التصدير:** PDF بترويسة المطوّر (`pdfgen`)، CSV بـBOM، XLSX (`openpyxl`).
* **تكامل زِمام/ERPNext لاحقًا:** `GET /api/accounting/export/erpnext` يُخرج قيود Journal Entry وشجرة الحسابات JSON/CSV بترتيب حقول ERPNext؛ لا تكامل حي ولا تبعية.

### 4.8 المرحلتان الفرعيتان
* **0.23.0 — النواة المحاسبية:** الدليل والمراكز والفترات، المحرك `ledger.post` وربط أحداث التأجير والفواتير والمصاريف والعمولة والتبرع، القيود اليدوية بالاعتماد والمرفقات، دفتر الأستاذ وميزان المراجعة، ترقيم العدّادات، أرصدة افتتاحية.
* **0.24.0 — الاكتمال:** الذمم المدينة/الدائنة، الموردون والمشتريات وأوامر الدفع، البنوك والمطابقة والشيكات الصادرة، إقرار الضريبة، الأصول والإهلاك، الموازنات، إقفال الفترات، القوائم الأربع وتصديرها، التمويل الإسلامي، تصدير ERPNext، ربط المستخلصات وحسابات الضمان.

---

## 5. الموارد البشرية (المرحلة 4 — 0.25.0 ثم 0.26.0)

### 5.1 النموذج والخصوصية
* `departments(id, name, parent_id, head_employee_id, cost_center_id)`، `positions(id, title, department_id, grade, headcount)`، `employees(id, number UNIQUE, name, name_en, nationality, id_number*, dob*, gender*, marital*, phone, email, address, department_id, position_id, manager_id, hire_date, contract_type permanent|fixed|part, probation_end, status active|on_leave|terminated, bank_name, iban*, social_ins_no*, pasi_applies, emergency_contact*, user_id, photo_doc)`، `employee_documents(id, employee_id, kind passport|resident_card|work_permit|labour_card|health_insurance|contract|certificate|other, number*, issued, expires, document_id)` + **تنبيه انتهاء** (90/30 يوم) عبر `jobs.tick`.
* **الخصوصية:** كل الحقول الحساسة (*) مشفَّرة في `pii.ENCRYPTED_COLUMNS`؛ صلاحيات جديدة: `hr` (إدارة)، `hr_payroll` (الرواتب فقط)، `hr_self` (الموظف نفسه)، `hr_manager` (فريقه)؛ **الراتب مرئي لـ`hr_payroll` وللموظف نفسه فقط**؛ كل فتح لملف موظف يُدقَّق. قاعدة احتفاظ صريحة (سجلات العمل تُحفظ المدة القانونية بعد انتهاء الخدمة — «محفوظة لأن…» في RUNBOOK §5).
* الدور `employee` (بوابة): `users.employee_id`؛ بوابته: بياناتي، إجازاتي، قسائمي، طلباتي (إجازة/خطاب/سلفة).

### 5.2 الحضور والإجازات
* `leave_types(id, key annual|sick|emergency|hajj|maternity|paternity|marriage|bereavement|unpaid|study|…, name, paid int, days_per_year, accrual monthly|annual, carry_over_max, needs_doc, gender_only, min_service_months, rules json, valid_from)` — **أنواع وأرصدة قابلة للضبط بتاريخ سريان**؛ القيم الأولية **مؤقتة** حتى يؤكدها مختص بقانون العمل.
* `leave_balances(employee_id, leave_type_id, year, entitled, taken, carried, adjusted)`، `leave_requests(id, employee_id, type_id, from, to, days, reason, status draft|pending|approved|rejected|cancelled, approver_id, decided_at, doc_id)` بسير عمل: موظف ⟵ مدير مباشر ⟵ الموارد البشرية (للأنواع الخاصة).
* `attendance(id, employee_id, day, check_in, check_out, status present|absent|late|leave|holiday|remote, source manual|import|device, note)` + استيراد CSV؛ `holidays(day, name)` (الأعياد الرسمية بالتقويم الهجري/الميلادي مدخلة يدويًا).

### 5.3 الرواتب
* `salary_structures(id, employee_id, effective_from, basic, currency 'OMR', note)` + `salary_lines(structure_id, component_id, amount|pct)`، `pay_components(id, key, name, kind earning|deduction|employer_cost, taxable?, pasi_base int, rule json)`.
* `payroll_runs(id, period 'YYYY-MM', status draft|computed|approved|paid|posted, computed_at, approved_by, paid_on, wps_document_id, journal_id)`، `payslips(id, run_id, employee_id, basic, earnings json, deductions json, pasi_employee, pasi_employer, loans, advances, absence_ded, net, status)` — التحرير قبل الاعتماد فقط؛ الدفتر بعده لا يُعدَّل (REVOKE).
* **الحماية الاجتماعية (PASI) للعُمانيين:** نسب العامل/صاحب العمل وسقف الأجر الخاضع **في جدول `hr_rates(key, value, valid_from, note)` وتبدأ بقيم مؤقتة موسومة «تحتاج تحقّقًا»** — لا أعتمد رقمًا من الذاكرة. نتيجة الحساب تُعرض مفصّلة بصيغتها.
* **ملف حماية الأجور (WPS):** مولِّد ملف بصيغة البنك (`hr_wps_format` إعداد؛ الصيغة الدقيقة تعتمد البنك — سؤال مفتوح) من `payslips` المعتمدة، مع فحص ناقص (IBAN، حساب مطابق) وتقرير أخطاء قبل التصدير.
* **سلف وقروض حسنة:** `employee_loans(id, employee_id, kind advance|qard_hasan, amount, installments, start, status)` و`loan_installments` تُخصم تلقائيًا من القسيمة؛ **بلا فائدة ولا رسوم** (الحقل غير موجود أصلًا).
* **مكافأة نهاية الخدمة:** `eosb_rules(valid_from, nationality_group, tiers json, cap?)` حاسبة تعرض خطواتها، **قيم الأساس مؤقتة تحتاج مراجعة قانونية**؛ تُحتسب عند إنهاء الخدمة وتُحجز كمخصص (ترحيل شهري اختياري إلى المحاسبة).
* **القيود:** `payroll_runs.posted` ⟵ `ledger.post('payroll', …)` (مصروف رواتب بمراكز الأقسام، مستحقات رواتب، التزام تأمينات، سلف) إن كانت `accounting` مفعَّلة؛ وإلا يُحفظ «غير مرحَّل» ويُرحَّل عند التفعيل.

### 5.4 بقية دورة الموظف (0.26.0)
التوظيف (`job_openings`, `candidates`, `interviews`, مراحل ومرفقات CV)، التقييم السنوي (`appraisal_cycles`, `appraisals` بأهداف وكفاءات وقرار)، التدريب (`training_courses`, `training_records` وانتهاء الشهادات)، الإنذارات والجزاءات وفق **لائحة معتمدة** (`disciplinary_cases` مرتبطة ببند لائحة `penalty_rules`؛ بلا لائحة معتمدة يُمنع إصدار جزاء)، إنهاء الخدمة والمخالصة (`terminations(employee_id, date, kind, eosb, leave_payout, loans_due, clearance json, doc)` — قائمة إخلاء طرف + مخالصة PDF).

### 5.5 المرحلتان الفرعيتان
* **0.25.0:** الهيكل والموظفون والوثائق وتنبيهاتها، الإجازات وأرصدتها وسير الاعتماد، الحضور، بوابة الموظف الأساسية.
* **0.26.0:** الرواتب (الهيكل، المسير، PASI، القسائم PDF، WPS، السلف والقروض الحسنة، مكافأة نهاية الخدمة، قيود المحاسبة)، التوظيف، التقييم، التدريب، الجزاءات، إنهاء الخدمة.

---

## 6. المرحلة 5 — البوابات والتقارير والمساعد (0.27.0)
* **البوابات:** المستأجر والموظف (كاملتان)، تحسين بوابة المدير العقاري.
* **التقارير:** دمج كل ما سبق في `reports.READY` + `DATASETS` (إيجار، محاسبة، موارد بشرية) مرشَّحة بالوحدات والصلاحيات؛ جدولة بريدية للتقارير الجديدة.
* **المساعد:** أدوات جديدة (`t_leasing` موسّعة: متأخرات بالعمر، شيكات مستحقة، شواغر؛ `t_accounting`: رصيد حساب، ميزان؛ `t_hr`: رصيد إجازة، انتهاء وثائق) تُسجَّل في سجل الوحدات فتتوفر فقط للمفعَّلة؛ بلا بيانات رواتب إلا لـ`hr_payroll`.
* **اللوحة:** إعادة بناء `/api/dashboard` على سجل الأدوات (§7).

---

## 7. ما يتغيّر في الموجود (جدول التأثير)

| الموجود | التغيير |
| --- | --- |
| `auth.PERMS/ROLES` | أدوار جديدة: `accountant`, `hr`, `property_manager`, `lessee`, `employee`؛ صلاحيات جديدة؛ `effective_perms()` |
| `app.py` الوسيط | بوّابة الوحدات؛ `/api/me` يعيد `modules`؛ `/api/modules` (قراءة/تعديل) و`/api/license` |
| `/api/decisions`, `engines.decisions` | تُقسَّم كتل القرارات بمفتاح وحدة؛ المؤسسة بلا `sales` لا ترى قرارات تسعير/حجز؛ قرارات التأجير الجديدة (تجديد قادم، شيك مرتجع، شاغر طويل) |
| اللوحة `ov` (`web/app.js`) | تُبنى من widgets حسب الوحدات؛ المؤشرات الحالية تنتقل لوحدتها |
| `modules2.leasing`، `lease_create`، `rent_pay` | تبقى نقاط التوافق (`POST /api/leases` قديمة تعمل وتُحوَّل داخليًا إلى المسار الجديد)؛ `rent_pay` ينشئ `rent_payment` بتاريخ اليوم وطريقة NULL |
| `charity_dues` | تعميم للإيجار (أعمدة اختيارية) + ترحيل بلا فقد |
| `invoices.issue_invoice` | ترقيم من `counters`؛ تحميل ضريبة حسب `vat_class`؛ ربط `ledger.post` |
| `bank_lines` | `bank_account_id` + مطابقة موسّعة |
| `pdfgen/paperwork` | أنواع: `lease`, `rent_receipt`, `cheque_receipt`, `arrears_notice`, `handover_report`, `owner_statement`, `tenant_statement`, `payslip`, `financial_statements`, `leave_letter`, `settlement` |
| `reports.READY` | وسم وحدة لكل تقرير + تقارير جديدة |
| `retention.py` / `pii.py` | قواعد وأعمدة مشفّرة جديدة (مستأجرون، موظفون، ملفات) |
| `seed.ALL_TABLES`, REVOKE, pgTAP | كل جدول جديد يُضاف (RLS على `org_id`، سياسة، منح، محفّزات `updated_at`) |
| `tenant_profiles` | مفتاح `modules`/`bundle`؛ المقصورة؛ لا تعديل يدوي للتأجير بعد الآن (يُستبدل بالاستيراد §3.4) |
| `post.lease` (واجهة) | تُستبدل بشاشة `lea` (تحويل `#post`→تبويب التأجير إلى `#lea` للتوافق) |

---

## 8. الترحيل وسلامة البيانات

### 8.1 ملفات الترحيل (PostgreSQL؛ ما يقابلها في `db.SCHEMA/MIGRATIONS`)
`0008_modules.sql` · `0009_leasing_core.sql` · `0010_leasing_ops.sql` · `0011_accounting_core.sql` · `0012_accounting_full.sql` · `0013_hr_core.sql` · `0014_hr_payroll.sql` · (مرحلة 5 بلا جداول غالبًا). كل ملف: جداول بـ`org_id`+RLS+منح+محفّز `updated_at`، فهارس، و`ALTER TABLE … ADD COLUMN IF NOT EXISTS` للتوسعات، ويُجرَّب على PG نظيف وPG مرقّى من 0007 مع بيانات.

### 8.2 ترحيل بيانات التأجير القائمة (في 0009 + خطوة إقلاع idempotent)
1. `leases.number` يُولَّد للقديم؛ `lease_terms` سنة أولى من `annual_rent`.
2. لكل `rent_dues.paid>0` حركة `rent_payments` (المبلغ=`paid`, التاريخ=`paid_date`, الطريقة NULL «غير موثَّقة»، `reference='ترحيل 0009'`)، ثم يُتحقق أن مجموع الحركات = `paid` المخبَّأ لكل استحقاق (فرق صفر).
3. **المقصورة:** يُستعاد من مصدر التقرير ما سقط من البذر (طريقة السداد والتاريخ لكل دفعة أغسطس) بخطوة `backfill_payment_methods` idempotent تقرأ من `tenant_profiles` — لا اختراع.
4. `units.owner_id` للمحفظة القائمة = مالك `own` (الشركة)؛ وحدات «جمعية الاستقامة» في المقصورة تُسجَّل كمالك `third_party` **فقط إن أكّد المالك** (سؤال) وإلا تبقى مملوكة للشركة المضيفة.

### 8.3 حماية الإدخال اليدوي من إعادة البذر
* `/api/reset` والبذر الحقيقي (`seed_real`) على مطوّر `real_only`: يُضاف علم `real_locked` في `settings` عند **أول كتابة يدوية** (عقد/دفعة/استيراد)؛ بعده `reset` يرفض (409) إلا بعبارة تأكيد وبعد نسخة احتياطية تلقائية. الإقلاع لا يعيد البذر أصلًا إذا وُجدت بيانات (موجود اليوم)، والعلم يمنع الاستثناء.
* الاستيراد لا يستدعي البذر أبدًا.

### 8.4 النشر
Railway يبني من `main` تلقائيًا؛ لذلك **كل مرحلة**: فرع/التزام محلي ⟵ pytest (SQLite) + pytest (PG: `MABANIQ_DATABASE_URL=postgresql://postgres@127.0.0.1:54330/mabaniq_test`، مع استثناء `tests/test_assistant.py` لأنه يضبط `MABANIQ_DB` قهرًا) + pgTAP (`CREATE EXTENSION pgtap` ثم `python db/run_pgtap.py` بـ`PYTHONIOENCODING=utf-8`) + ruff + `npm run check/build/size` + e2e للمسار الجديد ⟵ **عندئذ فقط الدفع** ⟵ تحقق حيّ: `/version`، دخول admin لـ`almaqsura` (كلمة المرور من `railway variables --json` دون طباعتها)، فتح الشاشات الجديدة، `/api/me.modules`.

---

## 9. معايير القبول لكل مرحلة (تُسجَّل في `docs/ACCEPTANCE.md` بالأمر الذي أثبتها)

| المرحلة | معيار قابل للقياس |
| --- | --- |
| 1 / 0.20.0 | حارس المسارات أخضر (لا مسار بلا وحدة)؛ مصفوفة الباقات تعطي 200/404 المتوقعة؛ مؤسسة تأجير فقط: `/api/me.perms` لا يحوي `book/kyc/construction`، و`/api/dashboard` بلا مفاتيح مبيعات؛ تفعيل/تعطيل في `audit`؛ المطوّرون القائمون بلا تغيير في نتائج اختباراتهم |
| 2a / 0.21.0 | مجموع `rent_payments` = `rent_dues.paid` لكل استحقاق بعد الترحيل؛ دفعة جزئية ومقدَّمة وارتجاع شيك ببقاء الرصيد صحيحًا؛ جدول عقد بثلاث سنوات بزيادات وتجهيز 30 يومًا يطابق حسابًا يدويًا؛ PDF العقد والإيصال بالهجري أولًا وأرقام غربية وQR صالح؛ pgTAP: RLS على كل جدول جديد + لا DELETE على `rent_payments` |
| 2b / 0.22.0 | كشف مالك: المحصَّل − المصاريف − العمولة = الصافي على بيانات اختبار؛ استيراد: dry-run لا يكتب، إعادة التنفيذ لا تكرّر، تعارض مع `manual` يُبلَّغ ولا يُطبَّق؛ مدير عقاري بنطاق لا يرى خارج نطاقه (اختبار تسرب)؛ التجديد/الإنهاء/التسليم بتسوية تأمين صحيحة |
| 3a / 0.23.0 | كل أحداث التأجير والفواتير تنتج قيدًا متوازنًا (اختبار خصائص: Σمدين=Σدائن لكل قيد)؛ ميزان المراجعة يتوازن؛ لا UPDATE/DELETE على `acc_lines` من الدور؛ ترقيم متزامن بلا فجوات/تكرار بستة خيوط |
| 3b / 0.24.0 | الميزانية: الأصول = الالتزامات + حقوق الملكية على بيانات اختبار؛ إقرار ضريبة يطابق مجاميع الأسطر؛ ترحيل في فترة مغلقة مرفوض؛ إهلاك شهري idempotent؛ حساب بنك غير إسلامي مرفوض |
| 4a / 0.25.0 | صلاحيات الراتب: موظف عادي لا يرى راتب غيره (اختبار تسرب)؛ رصيد الإجازة يخصم عند الاعتماد ويعود عند الإلغاء؛ تنبيه انتهاء وثيقة |
| 4b / 0.26.0 | مسير شهري تجريبي: Σصافي + استقطاعات = إجمالي؛ ملف WPS يمر مدقّق البنية؛ القيد المحاسبي للرواتب متوازن؛ قسط سلفة يُخصم ويُنهي الرصيد |
| 5 / 0.27.0 | أدوات المساعد تختفي بتعطيل وحدتها؛ بوابتا المستأجر والموظف: فحص ملكية على كل نقطة؛ Lighthouse/حجم الحزمة ضمن الميزانية الحالية |

لكل مرحلة: تحديث `PROGRESS.md` (رأس الاستئناف + جدول الوحدات)، `docs/ACCEPTANCE.md`، `README.md`، `CHANGELOG-<الإصدار>.md`، `docs/RUNBOOK.md` عند ما يلزم تشغيليًا، ثم تسجيل الخزنة (`wiki/knowledge/mabaniq-platform-review-v0.4.md` صفّ جديد، `log.md`، `curated.json`، التزام، `vault-git-bundle`).

---

## 10. المخاطر والقرارات الفنية المعلنة

| المخاطر | المعالجة |
| --- | --- |
| حجم العمل كبير ويمسّ الموجود | مراحل صغيرة مدفوعة بعد اختبارات المحركين؛ التوافق الخلفي نقطة قبول في كل مرحلة |
| تعارض `rent_dues.paid` المخبَّأ مع الحركات | الكتابة الوحيدة عبر دالة واحدة `leasing.apply_payment`؛ اختبار خاصية يقارن المخبَّأ بمجموع الحركات |
| ترقيم `COUNT(*)+1` في الفواتير يتصادم تحت التزامن | `counters` + قفل؛ اختبار متزامن |
| SQLite يقفل الكتابة عند فشل بعد INSERT | الفحوص قبل أي INSERT (درس 0.19.1)؛ اتصال واحد لكل طلب |
| خطوات الإقلاع المتزامنة (درسا 0.9.0/0.13.0) | كل بذر/ترحيل بيانات تحت قفل استشاري وidempotent |
| قواعد العمل والضريبة والتأمينات قد تتغير | جداول بتاريخ سريان؛ قيم مؤقتة موسومة؛ مراجعة مختص قبل الإنتاج |
| خصوصية بيانات الموظفين والمستأجرين | تشفير، صلاحيات بنطاق، تدقيق فتح الملف، قواعد احتفاظ، اختبارات تسرب |
| التحميل على Railway (ذاكرة مؤقتة 10 ث) | تُبطَل بالطلبات المعدِّلة كالمعتاد؛ تقارير ثقيلة تُحصَّل في المهمة الخلفية |
| `openpyxl` تبعية جديدة | تثبيت إصدار مضى عليه أسبوعان فأكثر؛ بلا صيغ؛ يُعلن في CHANGELOG |
| ما يخرج عن نطاق التنفيذ الآن | تكامل بنكي حي، توقيع إلكتروني موثَّق، بوابة دفع حقيقية، ربط مباشر بنظام البلدية/وزارة العمل — يبقى ملفات/روابط يدوية |

---

## 11. ترتيب العمل المقترح بعد اعتماد التصميم

1. **المرحلة 1 (0.20.0):** `registry.py`، `org_modules` + `0008`، البوابة والصلاحيات الفعّالة، شاشة الوحدات والترخيص، اللوحة/القرارات بالـwidgets، المقصورة بالباقة، اختبارات، نشر وتحقق حيّ.
2. **المرحلة 2a ثم 2b**، **3a ثم 3b**، **4a ثم 4b**، **5** — كل واحدة بدورة: كتابة ⟵ اختبار المحركين ⟵ pgTAP ⟵ وثائق ⟵ دفع ⟵ تحقق حيّ ⟵ تسجيل الخزنة.

> قبل المرحلة 1 يقول المساعد للمالك: «المرحلة القادمة تنفيذ — اختر النموذج الأدنى من قائمة النموذج».

---

## 12. انحرافات التنفيذ عن التصميم (تُحدَّث مع كل مرحلة)

### المرحلة 3أ — 0.23.0 (2026-10-29)
| التصميم | ما نُفِّذ | السبب |
| --- | --- | --- |
| ربط الأحداث بـ`ledger.post` داخل معاملة كل حدث | نقطة واحدة `ledger.autopost` تُستدعى من مواضع الأحداث (`apply_payment`، العكس، التبرع، المصروف، الكشف، تسوية التأمين) ومن المهمة اليومية ومن زر «ترحيل الآن»؛ كل قيد بمفتاح مصدر فريد فلا تكرار | يغطي ما بين التفعيل والبدء، ويُصلح نفسه بعد أي انقطاع، ولا يكسر العملية التجارية إن تعذّر الترحيل (يُعرض غير مرحَّل) |
| فاتورة الإيجار ⟵ ذمم + إيراد | يُرحَّل الاستحقاق عند **تاريخ استحقاقه** (أساس الاستحقاق)، ويُرحَّل الفرق فقط إن تغيّر المبلغ لاحقًا (جدول `acc_source_state`)؛ أقساط خطة السداد لا تُرحَّل إيرادًا (هي الدين نفسه) | الإنهاء المبكر والخطط يعدّلان `rent_dues.amount`؛ الفرق يمنع عكس إيراد مستحق أو تكراره |
| شيكات تحت التحصيل | لا تُقيَّد قبل الصرف؛ الحركة تُقيَّد عند تسجيل التحصيل (الصرف) | الشيك المحفوظ أو المودَع ليس نقدًا بعد، ولا حركة تحصيل له في الدفتر |
| بنوك متعددة | حساب بنكي جاري واحد `bank_main` وحساب للتبرعات `bank_charity`؛ `bank_accounts` في 3ب | لا مطابقة بنكية بعد |
| الضريبة | تُحمل فئة الضريبة على السطر (سكني معفى، غيره خاضع) ولا يُفصل مبلغ ضريبة | لم تُصدَر فواتير ضريبية للإيجار (ل17)؛ الفصل في 3ب |
| المبيعات | لا تُرحَّل أحداث البيع (حجز، أقساط، فواتير) في 3أ | سياسة الاعتراف بإيراد البيع على الخارطة وحسابات الضمان قرار مالك (ل28) |
| ترقيم القيد | يُمنح الرقم `JV-سنة-تسلسل` عند الترحيل لا عند المسودة، من `counters` | لا فجوات من مسودات تُحذف |
| إقفال الفترات | الإقفال وإعادة الفتح بسبب مدقَّق دخلا 3أ (لا ينتظران 3ب) | الحارس يلزم أصلًا في رفض الترحيل بتاريخ فترة مقفلة |
| الأملاك المُدارة | مقبوضات إيجار الوحدة التي لمالك طرف ثالث لا تُرحَّل إيرادًا: تُقيَّد التزامًا للمالك `ap_owners`؛ والعمولة إيراد عند إصدار الكشف؛ والتحويل يسدّد الالتزام | الشركة وكيلة لا مالكة (ل27) |
| الصلاحيات | `accounting` (إنشاء/قراءة) و`accounting_approve` (التفعيل، الاعتماد، الإقفال، الافتتاحي، الحسابات) ودور `accountant` | فصل المهام |

### المرحلة 2ب — 0.22.0 (2026-10-29)
| التصميم | ما نُفِّذ | السبب |
| --- | --- | --- |
| إلغاء دفعات قادمة بالإنهاء | يُخفَّض الاستحقاق إلى ما سُدِّد ويبقى بصفر ووسم «أُلغيت بإنهاء العقد»؛ لا حذف | `rent_dues` بلا DELETE لدور التطبيق (ترحيل 0003)؛ ولا تُلغى أقساط خطط السداد لأنها ديون سابقة لا إيجار |
| الفترة الجارية عند الإنهاء | تبقى كاملة إلا إن طلب الموظف «بالأيام المستعملة» (`prorate_last`) | سياسة تحتاج قرار المالك (ل18) |
| صلاحيات `leasing_collect/view/approve` | صلاحيتان فقط: `leasing_approve` (المدير العام: الإخلاء والخطط وإصدار الكشوف وصرف التبرع والتحميل على المستأجر والمبالغ المتفق عليها والاستيراد) و`leasing_pm` (المدير العقاري)؛ الباقي بـ`leasing` | الأدوار الحالية لا تحتاج تفصيلًا أدق (ل20) |
| دور `property_manager` بصلاحيات مقيَّدة بنطاق | مساراته منفصلة `/api/pm/*` وبصلاحية `leasing_pm` وحدها، والنطاق جملة SQL واحدة (`PM_UNIT`) على `user_scopes`؛ خارج النطاق 404 | تقليل مساحة التسرب: لا يستعمل أي مسار مكتبي ولا يحتاج كل مسار تعديلًا |
| تبرع التأخير | يُحتسب عند السداد المتأخر على المسدَّد (كأقساط البيع)، لا يوميًا على الرصيد | يتوافق مع المحرك القائم والمعدلات القائمة (ل21) |
| كشف المالك المقفل | الكشف الثاني للشهر نفسه يصدر **تعديليًا بالفرق** فقط | مجموع الكشوف = صافي الشهر الحقيقي دون تعديل كشف صادر |
| الاستيراد | خمسة أنواع، التأكيد بإعادة رفع الملف مع بصمته (بلا حالة على الخادم) | لا ملفات معلّقة على الخادم؛ البصمة تضمن أن المنفَّذ هو المفحوص |
| مرفق نص الإنذار | صيغة موحَّدة جاهزة بتنبيه «تحتاج اعتماد المستشار القانوني» | قرار ل10 |
| إيصال المدير العقاري | رقم الإيصال يعود في الاستجابة بلا PDF | لا نافذة مستندات خارجية قبل بوابة المستأجر (المرحلة 5) |

### المرحلة 2أ — 0.21.0 (2026-10-29)
| التصميم | ما نُفِّذ | السبب |
| --- | --- | --- |
| مسار الواجهة | بادئة جديدة `/api/lea/*` (مصنَّفة ضمن الإيجارات) وبقاء `/api/leasing` و`/api/leases` و`/api/rent-dues` | توافق خلفي؛ الشاشة القديمة والواجهات الخارجية تعمل |
| `receipt_no` لكل حركة | رقم إيصال واحد للحركة الواحدة (تُوزَّع المقدَّمة على عدة صفوف بالرقم نفسه) وسجل تحقق واحد للإيصال | إيصال واحد لكل تحصيل لا لكل استحقاق |
| تحصيل يصدر فاتورة | `rent_pay` القديم يصدر فاتورة كما قبل؛ المسار الجديد `/api/lea/payments` **لا يصدر فاتورة** بل إيصالًا | الضريبة على الإيجار التجاري قرار ل3 يعالجه المحاسبة (المرحلة 3) |
| الحركات المرحَّلة | تحمل `reference='ترحيل 0009'` بلا `receipt_no` فلا إيصال لها؛ الطريقة من التقرير المعتمد حين يذكرها وإلا NULL | لا نخترع ما لم يُوثَّق |
| تأمين | استحقاق `deposit` يُفوتَر **فقط** في المسار الجديد؛ المسار القديم يسجّل الرقم (`deposit_state='recorded'`) | يُبقي سلوك واجهة `POST /api/leases` القديمة |
| الاستحقاقات | `NOT_DEPOSIT` يُستثنى من كل حساب متأخرات (اللوحة والقرارات والمساعد والتعمير) | التأمين ليس إيجارًا مستحقًا |
| الترحيل | الدفتر يُملأ في خطوة إقلاع idempotent (لا داخل ملف SQL) | يلتئم أي استرجاع من نسخة احتياطية؛ ولأن الدفتر لا يُعدَّل فالطريقة تُكتب لحظة الإدخال |
| شروط المقصورة الموثَّقة | إيجار السنة الثانية والمواقف من جدول الوحدات المملوكة يصيران `lease_terms` و`units.parking_bays`، وتُصحَّح استحقاقات 2027 غير المسدَّدة (صفوف البذر فقط) | البذر السابق سعّر 2027 بإيجار السنة الأولى؛ المصدر يذكر الثانية |
| إنهاء مسودة | `POST /api/lea/leases/{id}/cancel` يضع المسودة `terminated` (`cancelled_draft`) ولا يحذفها | الرقم يبقى مستعملًا (ترقيم بلا فجوات) |
| الصلاحيات | كل `/api/lea/*` بصلاحية `leasing` الواحدة؛ تفصيل `leasing_collect/view/approve` ودور المدير العقاري في 2ب | لا دور خارجي قبل نطاق `user_scopes` |

### المرحلة 1 — 0.20.0 (2026-10-28)
| التصميم | ما نُفِّذ | السبب |
| --- | --- | --- |
| `org_modules(module, enabled, licensed, …)` | `org_modules(module, enabled, changed_at, changed_by)` — **الترخيص ليس عمودًا** | الترخيص يقرره المشغّل (ملف التعريف أو `MABANIQ_LICENSES`)؛ عمود في قاعدة المؤسسة كان سيتيح لمديرها رفعه بنفسه عبر أي ثغرة كتابة |
| صلاحية `leads` للتسويق | صلاحية `leads` (والعملاء المحتملون و`/api/leads` و`/api/wa`) ضمن **المبيعات**؛ التسويق يملك `market` والحملات والاستوديو | قمع العملاء جزء من دورة البيع، ومؤسسة تبيع بلا تسويق تحتاجه |
| `accounting`/`hr` وحدتان في السجل | مسجَّلتان بـ`available=False` ولا يقبلهما `POST /api/modules` (400) | لا واجهة ولا مسارات لهما قبل مرحلتيهما؛ تظهران «قيد التطوير» في الترخيص |
| الوسيط (middleware) يغلق المسار | تبعية عامة `FastAPI(dependencies=[module_gate])` | تعمل داخل نظام الاعتماد نفسه فتستعمل اتصال الطلب المسجَّل وتحجب قبل المصادقة؛ ملاحظة: طريقة غير مدعومة على مسار (GET على POST فقط) تعطي 405 لكل المؤسسات سواء فُعِّلت الوحدة أم لا فلا تكشف شيئًا |
| `/api/decisions` موزَّعة بوحدات | كل نوع قرار يملكه وحدة (`registry.DECISION_MODULE`) + قراران جديدان للتأجير (`lease_renew`، `lease_arrears`) | مؤسسة التأجير تحتاج صندوق قرارات يخصها |
| تقارير/مساعد | `reports.READY_MODULE/DATASET_MODULE` و`assistant.TOOL_MODULE` | الصلاحيات وحدها لا تكفي (`view` و`inventory` من النواة) |
| الواجهة | `SCREEN_MOD` للشاشات و`SUBM` للتبويبات الفرعية؛ ضبط تلقائي لأول تبويب متاح في «التسليم والأملاك» | مؤسسة تأجير بلا تسليم كانت تفتح على تبويب «نقل الملكية» وتستدعي مسارًا محجوبًا |
| اختبارات المقصورة | `test_tenant_profile` يتوقع الآن 404 لعروض الأسعار والتسعير ولوحة التسويق (وحدات مطفأة) | نتيجة مقصودة لحزمة التأجير؛ مسار «سعر فارغ ⟵ 400» مغطى في اختبار رؤية |
