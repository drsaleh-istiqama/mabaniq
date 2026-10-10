-- 0005_paperwork_plans.sql — Unit 6: quotations, issued-document registry, deliveries, share links, building plans.
CREATE TABLE quotes(
  id bigserial PRIMARY KEY, number text, unit_id bigint REFERENCES units(id), customer_name text, phone text, email text, plan text,
  list_price double precision, discount_pct double precision DEFAULT 0, price double precision, valid_until text, status text DEFAULT 'issued',
  schedule text, notes text, created text, created_by text, booking_id bigint, lead_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, number)
);
CREATE TABLE doc_issues(
  id bigserial PRIMARY KEY, kind text NOT NULL, ref_id bigint NOT NULL, number text, verify_code text NOT NULL, sha256 text, issued text, issued_by text, revised text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, kind, ref_id), UNIQUE (org_id, verify_code)
);
CREATE TABLE doc_sends(
  id bigserial PRIMARY KEY, kind text, ref_id bigint, channel text, recipient text, sent_by text, at text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE share_links(
  token_hash text PRIMARY KEY, kind text, ref_id bigint, expires double precision, created double precision, created_by text, opened integer DEFAULT 0, last_open text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE plans(
  id bigserial PRIMARY KEY, project_id bigint REFERENCES projects(id), building text, floor integer, unit_type text, kind text NOT NULL, title text,
  document_id bigint REFERENCES documents(id), markers text DEFAULT '[]', public integer DEFAULT 1, created text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX IF NOT EXISTS ix_quotes_unit ON quotes(unit_id);
CREATE INDEX IF NOT EXISTS ix_plans_project ON plans(project_id);
CREATE INDEX IF NOT EXISTS ix_share_links_exp ON share_links(expires);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['quotes','doc_issues','doc_sends','share_links','plans']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE quotes_id_seq, doc_issues_id_seq, doc_sends_id_seq, plans_id_seq TO mabaniq_app;
-- the issued-document registry is append-only for the app role except the content-hash refresh (UPDATE); never DELETE
REVOKE DELETE ON doc_issues, doc_sends FROM mabaniq_app;
