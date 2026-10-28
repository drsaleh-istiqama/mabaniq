-- 0008_modules.sql — 0.20.0: per-organisation module switches (backend/registry.py).
-- No rows ⟵ the developer profile's default (existing developers keep every module). Rows survive a demo reseed.
CREATE TABLE org_modules(
  module text NOT NULL,
  enabled integer NOT NULL DEFAULT 1,
  changed_at text, changed_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  PRIMARY KEY (org_id, module)
);

CREATE INDEX IF NOT EXISTS ix_org_modules_org ON org_modules(org_id);
ALTER TABLE org_modules ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_modules FORCE ROW LEVEL SECURITY;
CREATE POLICY org_modules_org ON org_modules USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON org_modules TO mabaniq_app;
CREATE TRIGGER set_updated_at BEFORE UPDATE ON org_modules FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at();
