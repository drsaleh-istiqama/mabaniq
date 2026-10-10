-- 0004_identity_external.sql — 0.10.0: sign-in by e-mail, e-mail links, password recovery, Google sign-in.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified integer DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub text;
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_org_email ON users(org_id, lower(email)) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_org_google ON users(org_id, google_sub) WHERE google_sub IS NOT NULL;

-- one-time hashed tokens for recovery links and e-mail sign-in links
CREATE TABLE auth_tokens(
  token_hash text PRIMARY KEY, user_id bigint REFERENCES users(id) ON DELETE CASCADE, kind text NOT NULL,
  expires double precision, used integer DEFAULT 0, created double precision, ip text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX IF NOT EXISTS ix_auth_tokens_user ON auth_tokens(user_id, kind);
CREATE INDEX IF NOT EXISTS ix_auth_tokens_org ON auth_tokens(org_id);
ALTER TABLE auth_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_tokens FORCE ROW LEVEL SECURITY;
CREATE POLICY auth_tokens_org ON auth_tokens USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_tokens TO mabaniq_app;
CREATE TRIGGER set_updated_at BEFORE UPDATE ON auth_tokens FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at();
