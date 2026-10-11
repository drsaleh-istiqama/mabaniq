-- 0007_landing_demo_requests.sql — 0.14.0: public landing page → live-demo requests (backend/landing.py).
--
-- ⚠ DOCUMENTED RLS EXCEPTION. `demo_requests` is the ONLY application table without `org_id` and without row-level
-- security, on purpose: a visitor of the public landing page is not (yet) a developer organisation, so there is no
-- tenant to attribute the row to. The table is a platform-operator inbox (Jadwa), written by one bounded public endpoint
-- (`POST /api/public/demo-request`: honeypot, own rate bucket, Pydantic limits), mailed to MABANIQ_SALES_EMAIL and
-- deleted by the retention rule after MABANIQ_RETENTION_DEMO_REQUESTS_DAYS. It is never joined to tenant data and no
-- tenant-scoped endpoint reads it. The pgTAP suite (db/tests/01_rls_isolation.sql) lists it as the one explicit exception
-- and asserts the narrower privileges below instead of the usual org policy.
CREATE TABLE demo_requests(
  id bigserial PRIMARY KEY,
  created text NOT NULL,                 -- ISO timestamp (local), the retention rule compares against it
  name text NOT NULL, company text NOT NULL, email text NOT NULL, phone text NOT NULL,
  projects integer DEFAULT 0, message text, lang text DEFAULT 'ar',
  ip_hash text, user_agent text,         -- sha256 prefix of the client ip (abuse triage, not reversible) + truncated UA
  mailed integer DEFAULT 0,              -- 1 once the notification reached SMTP/outbox
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz
);
CREATE INDEX ix_demo_requests_created ON demo_requests(created);
CREATE TRIGGER set_updated_at BEFORE UPDATE ON demo_requests FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at();
-- append-only inbox for the app role: INSERT, SELECT, DELETE (retention) — UPDATE only on the delivery flag
GRANT SELECT, INSERT, DELETE ON demo_requests TO mabaniq_app;
GRANT UPDATE (mailed, updated_at) ON demo_requests TO mabaniq_app;
GRANT USAGE, SELECT ON SEQUENCE demo_requests_id_seq TO mabaniq_app;
COMMENT ON TABLE demo_requests IS '0.14.0 public landing page inbox — no org_id, no RLS by design (see migration 0007 header); retention MABANIQ_RETENTION_DEMO_REQUESTS_DAYS';
