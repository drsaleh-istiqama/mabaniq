-- 0002_unit2_identity.sql — Unit 2: sessions with device/idle metadata, recovery codes, database-backed login budget.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS created double precision;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_seen double precision;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ip text;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ua text;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS label text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS recovery_codes text;

CREATE TABLE login_attempts(
  id bigserial PRIMARY KEY, k text, at double precision,
  created_at timestamptz NOT NULL DEFAULT now(),
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX IF NOT EXISTS ix_login_attempts ON login_attempts(k, at);
CREATE INDEX IF NOT EXISTS ix_login_attempts_org ON login_attempts(org_id);
ALTER TABLE login_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE login_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY login_attempts_org ON login_attempts USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON login_attempts TO mabaniq_app;
GRANT USAGE, SELECT ON SEQUENCE login_attempts_id_seq TO mabaniq_app;
