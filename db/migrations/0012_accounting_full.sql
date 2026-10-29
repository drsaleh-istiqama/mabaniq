-- 0012_accounting_full.sql — 0.24.0: accounting, completion (backend/acc_ap.py, acc_bank.py, acc_assets.py, acc_reports.py). Additive only.
-- Payables with approved payment orders, bank accounts and statement reconciliation, VAT returns, fixed assets and depreciation, budgets, Islamic financing
-- contracts (a fixed, known mark-up — there is no rate column anywhere), and the year-end close.
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS tax_no text;

CREATE TABLE bank_accounts(
  id bigserial PRIMARY KEY, name text NOT NULL, bank text, iban text, kind text NOT NULL DEFAULT 'bank' CHECK (kind IN ('bank','cash','escrow','charity')),
  account_id bigint NOT NULL REFERENCES acc_accounts(id), currency text NOT NULL DEFAULT 'OMR', islamic bigint NOT NULL DEFAULT 1 CHECK (islamic = 1), project_id bigint,
  active bigint NOT NULL DEFAULT 1, note text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE UNIQUE INDEX ux_bank_accounts_gl ON bank_accounts(org_id, account_id);

CREATE TABLE ap_bills(
  id bigserial PRIMARY KEY, number text, vendor_id bigint NOT NULL REFERENCES vendors(id), bill_date text NOT NULL, due_date text, vendor_ref text, description text,
  net double precision NOT NULL DEFAULT 0, vat_class text NOT NULL DEFAULT 'out_of_scope', vat double precision NOT NULL DEFAULT 0, total double precision NOT NULL DEFAULT 0,
  paid double precision NOT NULL DEFAULT 0, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','partly_paid','paid','void')),
  journal_id bigint, void_journal_id bigint, created_by text, approved_by text, approved_at text, void_reason text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, number)
);
CREATE INDEX ix_ap_bills_vendor ON ap_bills(vendor_id);

CREATE TABLE ap_bill_lines(
  id bigserial PRIMARY KEY, bill_id bigint NOT NULL REFERENCES ap_bills(id), line_no bigint NOT NULL, account_id bigint NOT NULL REFERENCES acc_accounts(id),
  cost_center_id bigint REFERENCES acc_cost_centers(id), description text, amount double precision NOT NULL CHECK (amount > 0),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX ix_ap_bill_lines_bill ON ap_bill_lines(bill_id);

CREATE TABLE ap_payments(
  id bigserial PRIMARY KEY, bill_id bigint NOT NULL REFERENCES ap_bills(id), vendor_id bigint NOT NULL REFERENCES vendors(id), amount double precision NOT NULL, paid_on text NOT NULL,
  method text NOT NULL, bank_account_id bigint REFERENCES bank_accounts(id), cheque_id bigint, reference text, order_id bigint, journal_id bigint, reverses_id bigint, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX ix_ap_payments_bill ON ap_payments(bill_id);

CREATE TABLE payment_orders(
  id bigserial PRIMARY KEY, number text, bill_id bigint NOT NULL REFERENCES ap_bills(id), vendor_id bigint NOT NULL REFERENCES vendors(id), amount double precision NOT NULL CHECK (amount > 0),
  method text NOT NULL, bank_account_id bigint NOT NULL REFERENCES bank_accounts(id), reference text, cheque_number text, cheque_due text,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','executed','rejected')), created_by text, approver1 text, approver1_at text, approver2 text, approver2_at text,
  reject_note text, executed_at text, payment_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, number)
);

CREATE TABLE bank_stmt_lines(
  id bigserial PRIMARY KEY, bank_account_id bigint NOT NULL REFERENCES bank_accounts(id), line_date text NOT NULL, description text, reference text, amount double precision NOT NULL,
  balance double precision, acc_line_id bigint, status text NOT NULL DEFAULT 'unmatched' CHECK (status IN ('unmatched','matched','ignored')), import_key text NOT NULL, file_sha text,
  matched_by text, matched_at text, note text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, bank_account_id, import_key)
);
CREATE UNIQUE INDEX ux_bank_stmt_acc_line ON bank_stmt_lines(org_id, acc_line_id) WHERE acc_line_id IS NOT NULL;

CREATE TABLE bank_recons(
  id bigserial PRIMARY KEY, bank_account_id bigint NOT NULL REFERENCES bank_accounts(id), period_end text NOT NULL, statement_balance double precision NOT NULL, book_balance double precision NOT NULL,
  in_transit double precision NOT NULL DEFAULT 0, not_in_books double precision NOT NULL DEFAULT 0, difference double precision NOT NULL DEFAULT 0, closed_by text, closed_at text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, bank_account_id, period_end)
);

CREATE TABLE vat_returns(
  id bigserial PRIMARY KEY, year bigint NOT NULL, quarter bigint NOT NULL CHECK (quarter BETWEEN 1 AND 4), output_vat double precision NOT NULL DEFAULT 0, input_vat double precision NOT NULL DEFAULT 0,
  net double precision NOT NULL DEFAULT 0, box_values text, status text NOT NULL DEFAULT 'filed' CHECK (status IN ('draft','filed')), filed_on text, ref text, created_by text, journal_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, year, quarter)
);

CREATE TABLE fixed_assets(
  id bigserial PRIMARY KEY, code text NOT NULL, name text NOT NULL, category text, cost double precision NOT NULL CHECK (cost > 0), acquired text NOT NULL, life_months bigint NOT NULL CHECK (life_months > 0),
  salvage double precision NOT NULL DEFAULT 0, method text NOT NULL DEFAULT 'straight_line' CHECK (method = 'straight_line'), cost_center_id bigint REFERENCES acc_cost_centers(id),
  account_cost bigint NOT NULL REFERENCES acc_accounts(id), account_accum bigint NOT NULL REFERENCES acc_accounts(id), account_expense bigint NOT NULL REFERENCES acc_accounts(id),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disposed')), disposed_on text, proceeds double precision, disposal_journal_id bigint, note text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, code)
);

CREATE TABLE depreciation_runs(
  id bigserial PRIMARY KEY, period text NOT NULL, asset_id bigint NOT NULL REFERENCES fixed_assets(id), amount double precision NOT NULL, journal_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, asset_id, period)
);

CREATE TABLE acc_budgets(
  id bigserial PRIMARY KEY, year bigint NOT NULL, cost_center_id bigint REFERENCES acc_cost_centers(id), account_id bigint NOT NULL REFERENCES acc_accounts(id),
  month bigint NOT NULL CHECK (month BETWEEN 1 AND 12), amount double precision NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE UNIQUE INDEX ux_acc_budgets ON acc_budgets(org_id, year, COALESCE(cost_center_id, 0), account_id, month);

CREATE TABLE fin_contracts(
  id bigserial PRIMARY KEY, kind text NOT NULL CHECK (kind IN ('murabaha','ijara','installment','istisna')), counterparty text NOT NULL, principal double precision NOT NULL CHECK (principal > 0),
  markup_total double precision NOT NULL CHECK (markup_total >= 0), start_date text NOT NULL, end_date text, bank_account_id bigint REFERENCES bank_accounts(id), status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','closed')), drawdown_journal_id bigint, note text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);

CREATE TABLE fin_installments(
  id bigserial PRIMARY KEY, contract_id bigint NOT NULL REFERENCES fin_contracts(id), no bigint NOT NULL, due text NOT NULL, amount double precision NOT NULL, margin double precision NOT NULL,
  paid_on text, payment_journal_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, contract_id, no)
);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['bank_accounts','ap_bills','ap_bill_lines','ap_payments','payment_orders','bank_stmt_lines','bank_recons','vat_returns','fixed_assets','depreciation_runs','acc_budgets',
                               'fin_contracts','fin_installments']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE bank_accounts_id_seq, ap_bills_id_seq, ap_bill_lines_id_seq, ap_payments_id_seq, payment_orders_id_seq, bank_stmt_lines_id_seq, bank_recons_id_seq, vat_returns_id_seq,
  fixed_assets_id_seq, depreciation_runs_id_seq, acc_budgets_id_seq, fin_contracts_id_seq, fin_installments_id_seq TO mabaniq_app;
-- ledgers: supplier payments are never edited (a correction is a negative row), and the filed returns, bank reconciliations, depreciation runs and bank accounts are never deleted
REVOKE UPDATE, DELETE ON ap_payments FROM mabaniq_app;
REVOKE DELETE ON vat_returns FROM mabaniq_app;
REVOKE DELETE ON bank_recons FROM mabaniq_app;
REVOKE DELETE ON depreciation_runs FROM mabaniq_app;
REVOKE DELETE ON bank_accounts FROM mabaniq_app;
REVOKE DELETE ON payment_orders FROM mabaniq_app;
