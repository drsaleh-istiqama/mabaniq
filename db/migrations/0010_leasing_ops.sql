-- 0010_leasing_ops.sql — 0.22.0: leasing operations (backend/leasing_ops.py, backend/importer.py). Additive only: new columns on leases / rent_dues / units /
-- tenants_l / rent_payments / charity_dues, plus the hand-over, notice, payment-plan, maintenance, expense, owner-statement, scope and import tables.
ALTER TABLE leases ADD COLUMN IF NOT EXISTS deposit_deducted double precision;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS deposit_refund double precision;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS deposit_settled_at text;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS deposit_settled_by text;
ALTER TABLE rent_dues ADD COLUMN IF NOT EXISTS plan_id bigint;
ALTER TABLE units ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE units ADD COLUMN IF NOT EXISTS import_batch text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE rent_payments ADD COLUMN IF NOT EXISTS import_key text;
ALTER TABLE charity_dues ADD COLUMN IF NOT EXISTS rent_due_id bigint;
ALTER TABLE charity_dues ADD COLUMN IF NOT EXISTS lease_id bigint;
CREATE UNIQUE INDEX IF NOT EXISTS ux_charity_rent_due ON charity_dues(org_id, rent_due_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_rent_payments_import ON rent_payments(org_id, import_key);

CREATE TABLE lease_handovers(
  id bigserial PRIMARY KEY, lease_id bigint REFERENCES leases(id), kind text NOT NULL, at text, by_user text, condition text, keys bigint, notes text,
  deductions text, created text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE meter_readings(
  id bigserial PRIMARY KEY, handover_id bigint REFERENCES lease_handovers(id), meter_id bigint, reading double precision NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE arrears_notices(
  id bigserial PRIMARY KEY, lease_id bigint REFERENCES leases(id), seq bigint, number text NOT NULL, kind text, issued text, cure_by text, amount double precision,
  sent_via text, sent_at text, created_by text, note text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, number)
);
CREATE TABLE payment_plans(
  id bigserial PRIMARY KEY, lease_id bigint REFERENCES leases(id), agreed_on text, status text DEFAULT 'active', note text, approved_by text, total double precision, original text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE vendors(
  id bigserial PRIMARY KEY, name text NOT NULL, cr_number text, phone text, email text, trade text, iban text, active bigint DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE maint_requests(
  id bigserial PRIMARY KEY, unit_id bigint REFERENCES units(id), lease_id bigint, source text DEFAULT 'staff', requester text, category text, description text,
  priority text DEFAULT 'normal', status text DEFAULT 'new', created text, updated text, sla_due text, closed_at text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE maint_orders(
  id bigserial PRIMARY KEY, request_id bigint REFERENCES maint_requests(id), vendor_id bigint, scheduled text, cost double precision, charge_to text DEFAULT 'owner',
  tenant_due_id bigint, basis text, doc_ref text, done_at text, expense_id bigint, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE property_expenses(
  id bigserial PRIMARY KEY, project_id bigint, unit_id bigint, owner_id bigint, category text, amount double precision NOT NULL, spent_on text NOT NULL, vendor_id bigint,
  order_id bigint, charge_owner bigint DEFAULT 1, charge_tenant bigint DEFAULT 0, description text, status text DEFAULT 'posted', doc_ref text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE owner_statements(
  id bigserial PRIMARY KEY, owner_id bigint REFERENCES owners(id), period text NOT NULL, seq bigint DEFAULT 1, kind text DEFAULT 'statement', number text NOT NULL,
  collected double precision, expenses double precision, commission double precision, net double precision, status text DEFAULT 'issued', issued_at text, issued_by text,
  transferred_on text, transfer_ref text, detail text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, number), UNIQUE (org_id, owner_id, period, seq)
);
CREATE TABLE user_scopes(
  id bigserial PRIMARY KEY, user_id bigint NOT NULL, project_id bigint, owner_id bigint, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE import_batches(
  id bigserial PRIMARY KEY, kind text NOT NULL, filename text, sha256 text, rows_ok bigint, rows_err bigint, rows_conflict bigint, by_user text, at text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX IF NOT EXISTS ix_handovers_lease ON lease_handovers(lease_id);
CREATE INDEX IF NOT EXISTS ix_notices_lease ON arrears_notices(lease_id);
CREATE INDEX IF NOT EXISTS ix_plans_lease ON payment_plans(lease_id);
CREATE INDEX IF NOT EXISTS ix_maint_unit ON maint_requests(unit_id);
CREATE INDEX IF NOT EXISTS ix_expenses_owner ON property_expenses(owner_id, spent_on);
CREATE INDEX IF NOT EXISTS ix_scopes_user ON user_scopes(user_id);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['lease_handovers','meter_readings','arrears_notices','payment_plans','vendors','maint_requests','maint_orders','property_expenses',
                               'owner_statements','user_scopes','import_batches']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE lease_handovers_id_seq, meter_readings_id_seq, arrears_notices_id_seq, payment_plans_id_seq, vendors_id_seq, maint_requests_id_seq,
  maint_orders_id_seq, property_expenses_id_seq, owner_statements_id_seq, user_scopes_id_seq, import_batches_id_seq TO mabaniq_app;
-- numbered legal / financial papers are never deleted: a notice or an issued owner statement is corrected by a new one
REVOKE DELETE ON arrears_notices FROM mabaniq_app;
REVOKE DELETE ON owner_statements FROM mabaniq_app;
REVOKE DELETE ON import_batches FROM mabaniq_app;
