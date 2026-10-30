-- 0014_hr_payroll.sql — 0.26.0: payroll (backend/hr_payroll.py, hr_end.py). Additive only.
-- Salary structures with an effective date, a monthly payroll run that is computed, then approved by a second person and frozen, payslips, social-insurance (PASI)
-- rates that are NEVER guessed (an unset rate blocks approval), interest-free staff advances and qard hasan loans (there is no rate / fee column anywhere),
-- an end-of-service calculator driven by a rule the organisation enters, and the settlement of a leaver. Nothing here is visible without `hr_payroll`
-- (or, for his own payslip, the employee himself).

-- a rate or a convention with an effective date; `value` NULL = not yet entered (the calculation refuses to guess)
CREATE TABLE hr_rates(
  id bigserial PRIMARY KEY, key text NOT NULL, value double precision, valid_from text NOT NULL, provisional bigint NOT NULL DEFAULT 1, note text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, key, valid_from)
);

CREATE TABLE pay_components(
  id bigserial PRIMARY KEY, key text NOT NULL, name text NOT NULL, kind text NOT NULL CHECK (kind IN ('earning','deduction')), pasi_base bigint NOT NULL DEFAULT 0,
  system bigint NOT NULL DEFAULT 0, active bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, key)
);

CREATE TABLE salary_structures(
  id bigserial PRIMARY KEY, employee_id bigint NOT NULL REFERENCES employees(id), effective_from text NOT NULL, basic double precision NOT NULL CHECK (basic >= 0), currency text NOT NULL DEFAULT 'OMR',
  note text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, employee_id, effective_from)
);
CREATE TABLE salary_lines(
  id bigserial PRIMARY KEY, structure_id bigint NOT NULL REFERENCES salary_structures(id), component_id bigint NOT NULL REFERENCES pay_components(id), amount double precision NOT NULL CHECK (amount >= 0),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, structure_id, component_id)
);

CREATE TABLE payroll_runs(
  id bigserial PRIMARY KEY, period text NOT NULL, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','computed','approved','paid')),
  headcount bigint NOT NULL DEFAULT 0, gross double precision NOT NULL DEFAULT 0, net double precision NOT NULL DEFAULT 0, pasi_employee double precision NOT NULL DEFAULT 0, pasi_employer double precision NOT NULL DEFAULT 0,
  blockers bigint NOT NULL DEFAULT 0, created_by text, computed_by text, computed_at text, approved_by text, approved_at text, paid_on text, bank_account_id bigint REFERENCES bank_accounts(id),
  journal_id bigint, payment_journal_id bigint, wps_sha text, wps_at text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, period)
);

CREATE TABLE payslips(
  id bigserial PRIMARY KEY, run_id bigint NOT NULL REFERENCES payroll_runs(id), employee_id bigint NOT NULL REFERENCES employees(id), basic double precision NOT NULL DEFAULT 0, factor double precision NOT NULL DEFAULT 1,
  earnings text, gross double precision NOT NULL DEFAULT 0, absence_days double precision NOT NULL DEFAULT 0, absence_ded double precision NOT NULL DEFAULT 0, adj_earn double precision NOT NULL DEFAULT 0,
  adj_ded double precision NOT NULL DEFAULT 0, pasi_base double precision NOT NULL DEFAULT 0, pasi_employee double precision NOT NULL DEFAULT 0, pasi_employer double precision NOT NULL DEFAULT 0,
  loan_ded double precision NOT NULL DEFAULT 0, net double precision NOT NULL DEFAULT 0, warnings text, cost_center_id bigint REFERENCES acc_cost_centers(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, run_id, employee_id)
);
CREATE INDEX ix_payslips_emp ON payslips(employee_id);

CREATE TABLE payroll_adjustments(
  id bigserial PRIMARY KEY, employee_id bigint NOT NULL REFERENCES employees(id), period text NOT NULL, kind text NOT NULL CHECK (kind IN ('earning','deduction')), name text NOT NULL,
  amount double precision NOT NULL CHECK (amount > 0), note text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX ix_payroll_adj_period ON payroll_adjustments(period);

-- no rate, fee or profit column exists on a staff loan: an advance or a qard hasan is repaid at exactly the amount lent
CREATE TABLE employee_loans(
  id bigserial PRIMARY KEY, employee_id bigint NOT NULL REFERENCES employees(id), kind text NOT NULL CHECK (kind IN ('advance','qard_hasan')), amount double precision NOT NULL CHECK (amount > 0),
  installments bigint NOT NULL CHECK (installments >= 1), start_period text NOT NULL, status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','paid','cancelled')),
  reason text, request_id bigint, created_by text, approved_by text, approved_at text, disbursed_on text, bank_account_id bigint REFERENCES bank_accounts(id), disburse_journal_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX ix_employee_loans_emp ON employee_loans(employee_id);
CREATE TABLE loan_installments(
  id bigserial PRIMARY KEY, loan_id bigint NOT NULL REFERENCES employee_loans(id), no bigint NOT NULL, period text NOT NULL, amount double precision NOT NULL CHECK (amount > 0),
  status text NOT NULL DEFAULT 'due' CHECK (status IN ('due','deducted','waived','settled')), payslip_id bigint REFERENCES payslips(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, loan_id, no)
);

-- an end-of-service rule the organisation enters: tiers = [{"to_years": 3, "days_per_year": 15}, {"to_years": null, "days_per_year": 30}] of the basic wage; none is seeded
CREATE TABLE eosb_rules(
  id bigserial PRIMARY KEY, grp text NOT NULL CHECK (grp IN ('omani','expat')), valid_from text NOT NULL, tiers text NOT NULL, cap_months double precision, note text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, grp, valid_from)
);

CREATE TABLE terminations(
  id bigserial PRIMARY KEY, employee_id bigint NOT NULL REFERENCES employees(id), end_date text NOT NULL, kind text NOT NULL CHECK (kind IN ('resignation','termination','end_of_contract','retirement','death','other')),
  note text, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','paid')), service_years double precision NOT NULL DEFAULT 0, last_basic double precision NOT NULL DEFAULT 0,
  eosb_amount double precision NOT NULL DEFAULT 0, eosb_steps text, leave_days double precision NOT NULL DEFAULT 0, leave_payout double precision NOT NULL DEFAULT 0, loans_due double precision NOT NULL DEFAULT 0,
  other_dues double precision NOT NULL DEFAULT 0, other_deductions double precision NOT NULL DEFAULT 0, net double precision NOT NULL DEFAULT 0, warnings text, clearance text,
  created_by text, approved_by text, approved_at text, paid_on text, bank_account_id bigint REFERENCES bank_accounts(id), journal_id bigint, payment_journal_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, employee_id)
);

-- an approved payslip is frozen: once its run leaves draft/computed the database refuses to change or delete it
CREATE OR REPLACE FUNCTION mabaniq_payslip_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE st text; rid bigint;
BEGIN
  IF current_setting('app.maintenance', true) = '1' THEN RETURN COALESCE(NEW, OLD); END IF;
  rid := CASE WHEN TG_OP = 'INSERT' THEN NEW.run_id ELSE OLD.run_id END;
  SELECT status INTO st FROM payroll_runs WHERE id = rid;
  IF st IS DISTINCT FROM 'draft' AND st IS DISTINCT FROM 'computed' THEN RAISE EXCEPTION 'an approved payslip is immutable'; END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER payslip_guard BEFORE INSERT OR UPDATE OR DELETE ON payslips FOR EACH ROW EXECUTE FUNCTION mabaniq_payslip_guard();

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['hr_rates','pay_components','salary_structures','salary_lines','payroll_runs','payslips','payroll_adjustments','employee_loans','loan_installments','eosb_rules','terminations']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE hr_rates_id_seq, pay_components_id_seq, salary_structures_id_seq, salary_lines_id_seq, payroll_runs_id_seq, payslips_id_seq, payroll_adjustments_id_seq,
  employee_loans_id_seq, loan_installments_id_seq, eosb_rules_id_seq, terminations_id_seq TO mabaniq_app;
-- the payroll history is kept (a payslip is deleted only while its run is still being computed — the guard above): runs, loans, installments, structures, terminations and rules are never deleted (a correction is a new row or a status)
REVOKE DELETE ON payroll_runs FROM mabaniq_app;
REVOKE DELETE ON salary_structures FROM mabaniq_app;
REVOKE DELETE ON employee_loans FROM mabaniq_app;
REVOKE DELETE ON loan_installments FROM mabaniq_app;
REVOKE DELETE ON eosb_rules FROM mabaniq_app;
REVOKE DELETE ON terminations FROM mabaniq_app;
REVOKE DELETE ON hr_rates FROM mabaniq_app;
