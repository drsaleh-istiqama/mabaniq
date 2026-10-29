-- 0009_leasing_core.sql — 0.21.0: integrated leasing (backend/leasing.py). Extends tenants_l / leases / rent_dues / units in place
-- (nothing renamed or dropped), adds the owners, meters, lease terms, events, cheques and the immutable rent_payments ledger.
-- Existing payments are carried over by the idempotent start-up step leasing.ensure_core (design 8.2), not here, so a restored dump heals too.
ALTER TABLE units ADD COLUMN IF NOT EXISTS owner_id bigint;
ALTER TABLE units ADD COLUMN IF NOT EXISTS lease_state text;
ALTER TABLE units ADD COLUMN IF NOT EXISTS parking_bays bigint;

ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS kind text DEFAULT 'individual';
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS cr_number text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS tax_no text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS rep_name text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS rep_title text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS rep_id_number text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS contact_name text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS address text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS nationality text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS id_expiry text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS rating text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS rating_note text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS blacklisted bigint DEFAULT 0;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS blacklist_reason text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS blacklisted_by text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS blacklisted_at text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS import_batch text;

ALTER TABLE leases ADD COLUMN IF NOT EXISTS number text;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS kind text;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS signed_at text;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS prep_free_days bigint DEFAULT 0;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS rent_start text;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS months bigint;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS deposit_state text;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS charity_clause bigint DEFAULT 0;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS municipality_fee double precision;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS municipality_date text;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS renewed_from bigint;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS terminated_at text;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS termination_kind text;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS termination_note text;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS source text DEFAULT 'manual';
ALTER TABLE leases ADD COLUMN IF NOT EXISTS created_by text;
CREATE UNIQUE INDEX IF NOT EXISTS ux_leases_number ON leases(org_id, number);

ALTER TABLE rent_dues ADD COLUMN IF NOT EXISTS kind text DEFAULT 'rent';
ALTER TABLE rent_dues ADD COLUMN IF NOT EXISTS year_no bigint;
ALTER TABLE rent_dues ADD COLUMN IF NOT EXISTS label text;

CREATE TABLE counters(
  k text NOT NULL, n bigint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  PRIMARY KEY (org_id, k)
);
CREATE TABLE owners(
  id bigserial PRIMARY KEY, name text NOT NULL, kind text DEFAULT 'own', id_number text, phone text, email text, iban text,
  mgmt_fee_pct double precision DEFAULT 0, mgmt_basis text DEFAULT 'collected', active bigint DEFAULT 1, notes text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE unit_meters(
  id bigserial PRIMARY KEY, unit_id bigint REFERENCES units(id), kind text, number text, provider text, shared bigint DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE common_facilities(
  id bigserial PRIMARY KEY, project_id bigint REFERENCES projects(id), name text NOT NULL, kind text, notes text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE lease_terms(
  id bigserial PRIMARY KEY, lease_id bigint REFERENCES leases(id), year_no bigint NOT NULL, from_date text, to_date text, annual_rent double precision NOT NULL, note text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, lease_id, year_no)
);
CREATE TABLE lease_events(
  id bigserial PRIMARY KEY, lease_id bigint REFERENCES leases(id), kind text, at text, by_user text, detail text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE cheques(
  id bigserial PRIMARY KEY, direction text DEFAULT 'in', lease_id bigint REFERENCES leases(id), due_id bigint, number text, bank text, branch text,
  amount double precision NOT NULL, due_date text, received_on text, status text DEFAULT 'held', deposited_on text, cleared_on text, bounce_reason text,
  drawer text, payee text, vendor_id bigint, journal_id bigint, receipt_no text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
-- the payments ledger: rows are never updated or deleted (a refund / bounced cheque is a negative row pointing at reverses_id)
CREATE TABLE rent_payments(
  id bigserial PRIMARY KEY, due_id bigint REFERENCES rent_dues(id), lease_id bigint REFERENCES leases(id), amount double precision NOT NULL, paid_on text NOT NULL,
  method text, reference text, cheque_id bigint, receipt_no text, recorded_by text, reverses_id bigint, note text, created text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX IF NOT EXISTS ix_rent_payments_due ON rent_payments(due_id);
CREATE INDEX IF NOT EXISTS ix_rent_payments_receipt ON rent_payments(receipt_no);
CREATE INDEX IF NOT EXISTS ix_cheques_lease ON cheques(lease_id);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['counters','owners','unit_meters','common_facilities','lease_terms','lease_events','cheques','rent_payments']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE owners_id_seq, unit_meters_id_seq, common_facilities_id_seq, lease_terms_id_seq, lease_events_id_seq, cheques_id_seq, rent_payments_id_seq TO mabaniq_app;
-- ledgers: no UPDATE and no DELETE for the application role
REVOKE UPDATE, DELETE ON rent_payments FROM mabaniq_app;
