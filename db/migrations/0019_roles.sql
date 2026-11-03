-- 0019_roles.sql — 0.32.0: الأدوار والصلاحيات كبيانات (backend/roles.py، docs/DESIGN-roles-permissions.md). إضافي فقط.
-- مجموعة الصلاحيات تبقى في الكود (الـendpoints تشير إليها)؛ هذان الجدولان يحملان ربط الأدوار بها لكل مطوّر. يُبذران من `auth.PERMS` عند أول قراءة (تطبيقًا لا هنا:
-- مالك القاعدة تسري عليه سياسة الصف فلا يرى بيانات أي مطوّر بلا `app.org_id`) فلا يتغيّر سلوك أي مطوّر قائم. الدور المخصص يُحذف (DELETE مسموح)؛ المدمج وأدوار البوابات تحميها الشيفرة.
CREATE TABLE roles(
  id bigserial PRIMARY KEY, code text NOT NULL, label text NOT NULL, kind text NOT NULL DEFAULT 'staff' CHECK (kind IN ('staff','portal')), builtin bigint NOT NULL DEFAULT 0, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, code)
);

CREATE TABLE role_perms(
  id bigserial PRIMARY KEY, role_code text NOT NULL, perm text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, role_code, perm)
);
CREATE INDEX ix_role_perms_role ON role_perms(role_code);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['roles','role_perms']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE roles_id_seq, role_perms_id_seq TO mabaniq_app;
