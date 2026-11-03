-- 0018_master_data.sql — 0.31.0: البيانات الأساسية من الواجهة (backend/masterdata.py، docs/DESIGN-master-data-forms.md). إضافي فقط: لا حذف ولا تعديل لما طُبِّق.
-- (1) علم الإيقاف `active` على ثمانية جداول: الموقوف يخرج من القوائم الجارية ويُغلق أمام النشاط الجديد ويبقى تاريخه (لا حذف فعليًا).
-- (2) أعمدة المقاول التي لم تكن موجودة (هاتف، بريد، تخصص، ملاحظات).
-- (3) جدول `buildings`: سجل مباني المشروع (الربط بالوحدة ناعم بالاسم في `units.building` فلا يتغيّر أي استعلام قائم). يُملأ من أسماء الوحدات عند أول قراءة (تطبيقًا لا هنا،
--     لأن مالك القاعدة تسري عليه سياسة الأمان بالصف فلا يرى صفوف أي مطوّر بلا `app.org_id`).
-- (4) جدول `unit_price_changes`: دفتر تغيّر أسعار الوحدات الموثَّق — لا UPDATE ولا DELETE لدور التطبيق (التصحيح سجل جديد).
-- (5) فهرسان فريدان جزئيان: عقد مقاول فعّال واحد للمشروع، وسجل تجاري واحد للمقاول؛ يُنشأ كل منهما فقط إن خلت البيانات القائمة من تكرار (لا يُفشل النشر).
ALTER TABLE projects ADD COLUMN IF NOT EXISTS active bigint NOT NULL DEFAULT 1;
ALTER TABLE units ADD COLUMN IF NOT EXISTS active bigint NOT NULL DEFAULT 1;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS active bigint NOT NULL DEFAULT 1;
ALTER TABLE lands ADD COLUMN IF NOT EXISTS active bigint NOT NULL DEFAULT 1;
ALTER TABLE permits ADD COLUMN IF NOT EXISTS active bigint NOT NULL DEFAULT 1;
ALTER TABLE contractors ADD COLUMN IF NOT EXISTS active bigint NOT NULL DEFAULT 1;
ALTER TABLE contracts_c ADD COLUMN IF NOT EXISTS active bigint NOT NULL DEFAULT 1;
ALTER TABLE schedule_tasks ADD COLUMN IF NOT EXISTS active bigint NOT NULL DEFAULT 1;
ALTER TABLE contractors ADD COLUMN IF NOT EXISTS phone text;
ALTER TABLE contractors ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE contractors ADD COLUMN IF NOT EXISTS trade text;
ALTER TABLE contractors ADD COLUMN IF NOT EXISTS notes text;

CREATE TABLE buildings(
  id bigserial PRIMARY KEY, project_id bigint NOT NULL REFERENCES projects(id), name text NOT NULL,
  floors bigint CHECK (floors IS NULL OR (floors >= 1 AND floors <= 200)), notes text, active bigint NOT NULL DEFAULT 1, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, project_id, name)
);
CREATE INDEX ix_buildings_project ON buildings(project_id);

CREATE TABLE unit_price_changes(
  id bigserial PRIMARY KEY, unit_id bigint NOT NULL REFERENCES units(id), old_price double precision, new_price double precision NOT NULL,
  reason text NOT NULL, basis text NOT NULL CHECK (basis IN ('free','booking','lease')), changed_by text, changed_at text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX ix_unit_price_changes_unit ON unit_price_changes(unit_id);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['buildings','unit_price_changes']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE buildings_id_seq, unit_price_changes_id_seq TO mabaniq_app;
REVOKE DELETE ON buildings FROM mabaniq_app;                     -- a building is stopped (active=0), never deleted
REVOKE UPDATE, DELETE ON unit_price_changes FROM mabaniq_app;    -- the price-change ledger: a correction is a new row

-- one active contractor contract per project; one commercial register per contractor — only when the existing rows already satisfy it
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM contracts_c WHERE active = 1 GROUP BY org_id, project_id HAVING count(*) > 1) THEN
    CREATE UNIQUE INDEX IF NOT EXISTS ux_contracts_c_one_active ON contracts_c(org_id, project_id) WHERE active = 1;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM contractors WHERE cr_number IS NOT NULL AND cr_number <> '' GROUP BY org_id, cr_number HAVING count(*) > 1) THEN
    CREATE UNIQUE INDEX IF NOT EXISTS ux_contractors_cr ON contractors(org_id, cr_number) WHERE cr_number IS NOT NULL AND cr_number <> '';
  END IF;
END $$;
