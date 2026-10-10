-- 0006_reports_marketing.sql — Unit 7: saved reports and schedules, campaigns, creatives, campaign sends; lead attribution.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS campaign_id bigint;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email text;

CREATE TABLE report_defs(
  id bigserial PRIMARY KEY, name text NOT NULL, kind text NOT NULL, ref text, spec text, params text, owner text, shared integer DEFAULT 1, created text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE report_schedules(
  id bigserial PRIMARY KEY, report_id bigint REFERENCES report_defs(id) ON DELETE CASCADE, cadence text, hour integer, recipients text, format text,
  active integer DEFAULT 1, next_run text, last_run text, last_error text, created_by text, created text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE campaigns(
  id bigserial PRIMARY KEY, project_id bigint REFERENCES projects(id), name text NOT NULL, objective text, channels text, audience text, budget double precision DEFAULT 0,
  start_date text, end_date text, offer_text text, message text, status text DEFAULT 'draft', utm text, created_by text, created text, notes text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, utm)
);
CREATE TABLE creatives(
  id bigserial PRIMARY KEY, project_id bigint REFERENCES projects(id), campaign_id bigint, template text, size text, headline text, subline text, cta text, offer text,
  bg_document_id bigint, document_id bigint, pdf_document_id bigint, created_by text, created text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE campaign_sends(
  id bigserial PRIMARY KEY, campaign_id bigint, channel text, recipient text, lead_id bigint, creative_id bigint, status text, at text, by_user text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX IF NOT EXISTS ix_leads_campaign ON leads(campaign_id);
CREATE INDEX IF NOT EXISTS ix_campaigns_project ON campaigns(project_id);
CREATE INDEX IF NOT EXISTS ix_sched_next ON report_schedules(next_run);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['report_defs','report_schedules','campaigns','creatives','campaign_sends']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE report_defs_id_seq, report_schedules_id_seq, campaigns_id_seq, creatives_id_seq, campaign_sends_id_seq TO mabaniq_app;
