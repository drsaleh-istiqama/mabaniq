-- 0017_policies.sql — 0.29.0: the policy and regulation register (backend/policies.py). Additive only.
-- A policy is a numbered set of articles with a version, an owner, an effective date and a review period. A new version is a NEW row (supersedes_id points at the one it replaces);
-- approving it retires the previous approved version. The person who prepared a version never approves it. An acknowledgement ("I have read this") is one row per person per version.
-- Neither table is ever deleted from by the application: a draft that is dropped is retired, a retired version stays as history.
CREATE TABLE policies(
  id bigserial PRIMARY KEY, code text NOT NULL, title text NOT NULL,
  category text NOT NULL CHECK (category IN ('hr','governance','finance','leasing','sales','operations','compliance')),
  owner_role text, summary text, body text NOT NULL DEFAULT '[]', version bigint NOT NULL DEFAULT 1 CHECK (version >= 1),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','retired')),
  effective_from text, review_months bigint NOT NULL DEFAULT 12 CHECK (review_months >= 1), ack_required bigint NOT NULL DEFAULT 1,
  basis text, supersedes_id bigint REFERENCES policies(id), created_by text, approved_by text, approved_at text, retired_by text, retired_at text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, code, version)
);
CREATE INDEX ix_policies_code ON policies(code);

CREATE TABLE policy_acks(
  id bigserial PRIMARY KEY, policy_id bigint NOT NULL REFERENCES policies(id), version bigint NOT NULL, username text NOT NULL, name text, employee_id bigint, acked_at text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, policy_id, username)
);
CREATE INDEX ix_policy_acks_policy ON policy_acks(policy_id);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['policies','policy_acks']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE policies_id_seq, policy_acks_id_seq TO mabaniq_app;
REVOKE DELETE ON policies FROM mabaniq_app;
REVOKE DELETE ON policy_acks FROM mabaniq_app;
