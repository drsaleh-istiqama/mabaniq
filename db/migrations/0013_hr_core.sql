-- 0013_hr_core.sql — 0.25.0: human resources, core (backend/hr.py, hr_leave.py, hr_self.py). Additive only.
-- Structure (departments, positions), the employee file (sensitive fields encrypted by the application), documents with expiry, leave types with an effective date,
-- balances and a two-stage approval, holidays, attendance, and the employee's own requests. Payroll arrives in 0014; nothing here holds a salary.
ALTER TABLE users ADD COLUMN IF NOT EXISTS employee_id bigint;

CREATE TABLE departments(
  id bigserial PRIMARY KEY, name text NOT NULL, parent_id bigint REFERENCES departments(id), head_employee_id bigint, cost_center_id bigint REFERENCES acc_cost_centers(id),
  active bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, name)
);

CREATE TABLE positions(
  id bigserial PRIMARY KEY, title text NOT NULL, department_id bigint REFERENCES departments(id), grade text, headcount bigint NOT NULL DEFAULT 1 CHECK (headcount >= 0),
  active bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE UNIQUE INDEX ux_positions_title ON positions(org_id, title, COALESCE(department_id, 0));

-- id_number, dob, iban, social_ins_no and emergency_contact hold `enc:v1:` ciphertext (pii.ENCRYPTED_COLUMNS). A file is never deleted: service ends with status 'terminated'.
CREATE TABLE employees(
  id bigserial PRIMARY KEY, number text NOT NULL, name text NOT NULL, name_en text, nationality text, omani bigint NOT NULL DEFAULT 0,
  id_number text, dob text, gender text CHECK (gender IN ('male','female')), marital text CHECK (marital IN ('single','married','divorced','widowed')),
  phone text, email text, address text,
  department_id bigint REFERENCES departments(id), position_id bigint REFERENCES positions(id), manager_id bigint REFERENCES employees(id) CHECK (manager_id IS DISTINCT FROM id),
  hire_date text NOT NULL, contract_type text NOT NULL DEFAULT 'permanent' CHECK (contract_type IN ('permanent','fixed','part')), contract_end text, probation_end text,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','on_leave','terminated')), terminated_on text, termination_note text,
  bank_name text, iban text, social_ins_no text, pasi_applies bigint NOT NULL DEFAULT 0, emergency_contact text,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, number)
);
CREATE INDEX ix_employees_dept ON employees(department_id);
CREATE INDEX ix_employees_manager ON employees(manager_id);
ALTER TABLE departments ADD CONSTRAINT fk_departments_head FOREIGN KEY (head_employee_id) REFERENCES employees(id);
ALTER TABLE users ADD CONSTRAINT fk_users_employee FOREIGN KEY (employee_id) REFERENCES employees(id);
CREATE UNIQUE INDEX ux_users_employee ON users(org_id, employee_id) WHERE employee_id IS NOT NULL;

CREATE TABLE employee_documents(
  id bigserial PRIMARY KEY, employee_id bigint NOT NULL REFERENCES employees(id),
  kind text NOT NULL CHECK (kind IN ('passport','resident_card','work_permit','labour_card','health_insurance','contract','certificate','other')),
  number text, issued text, expires text, document_id bigint, note text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX ix_employee_documents_emp ON employee_documents(employee_id);

-- one row per key per effective date; the row valid on a day is the latest `valid_from` on or before it. Values seeded by the platform are marked provisional.
CREATE TABLE leave_types(
  id bigserial PRIMARY KEY, key text NOT NULL, name text NOT NULL, paid bigint NOT NULL DEFAULT 1, days_per_year double precision NOT NULL DEFAULT 0 CHECK (days_per_year >= 0),
  accrual text NOT NULL DEFAULT 'annual' CHECK (accrual IN ('annual','monthly','event')), carry_over_max double precision NOT NULL DEFAULT 0 CHECK (carry_over_max >= 0),
  needs_doc bigint NOT NULL DEFAULT 0, needs_hr bigint NOT NULL DEFAULT 0, gender_only text CHECK (gender_only IN ('male','female')), min_service_months bigint NOT NULL DEFAULT 0,
  day_count text NOT NULL DEFAULT 'working' CHECK (day_count IN ('working','calendar')), allow_negative bigint NOT NULL DEFAULT 0, rules text,
  valid_from text NOT NULL, active bigint NOT NULL DEFAULT 1, provisional bigint NOT NULL DEFAULT 1, note text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, key, valid_from)
);

CREATE TABLE leave_balances(
  id bigserial PRIMARY KEY, employee_id bigint NOT NULL REFERENCES employees(id), type_key text NOT NULL, year bigint NOT NULL,
  entitled double precision NOT NULL DEFAULT 0, taken double precision NOT NULL DEFAULT 0, carried double precision NOT NULL DEFAULT 0, adjusted double precision NOT NULL DEFAULT 0, adj_note text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, employee_id, type_key, year)
);

CREATE TABLE leave_requests(
  id bigserial PRIMARY KEY, employee_id bigint NOT NULL REFERENCES employees(id), type_id bigint NOT NULL REFERENCES leave_types(id), type_key text NOT NULL,
  from_date text NOT NULL, to_date text NOT NULL, days double precision NOT NULL CHECK (days > 0), reason text,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','cancelled')), stage text NOT NULL DEFAULT 'manager' CHECK (stage IN ('manager','hr','done')),
  manager_by text, manager_at text, manager_note text, decided_by text, decided_at text, decision_note text, doc_id bigint,
  created_by text, cancelled_by text, cancelled_at text, cancel_reason text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  CHECK (to_date >= from_date)
);
CREATE INDEX ix_leave_requests_emp ON leave_requests(employee_id, from_date);

CREATE TABLE holidays(
  id bigserial PRIMARY KEY, day text NOT NULL, name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, day)
);

CREATE TABLE attendance(
  id bigserial PRIMARY KEY, employee_id bigint NOT NULL REFERENCES employees(id), day text NOT NULL, check_in text, check_out text,
  status text NOT NULL CHECK (status IN ('present','absent','late','leave','holiday','remote')), source text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','import','device','leave')), note text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, employee_id, day)
);

CREATE TABLE hr_requests(
  id bigserial PRIMARY KEY, employee_id bigint NOT NULL REFERENCES employees(id), kind text NOT NULL CHECK (kind IN ('letter','advance','other')), details text, amount double precision,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','done')), requested_at text, decided_by text, decided_at text, decision_note text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX ix_hr_requests_emp ON hr_requests(employee_id);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['departments','positions','employees','employee_documents','leave_types','leave_balances','leave_requests','holidays','attendance','hr_requests']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE departments_id_seq, positions_id_seq, employees_id_seq, employee_documents_id_seq, leave_types_id_seq, leave_balances_id_seq, leave_requests_id_seq,
  holidays_id_seq, attendance_id_seq, hr_requests_id_seq TO mabaniq_app;
-- service history is kept: an employee file, a leave request and an employee's request are never deleted (a cancellation / termination is a status), and a leave type is deactivated, not removed
REVOKE DELETE ON employees FROM mabaniq_app;
REVOKE DELETE ON leave_requests FROM mabaniq_app;
REVOKE DELETE ON hr_requests FROM mabaniq_app;
REVOKE DELETE ON leave_types FROM mabaniq_app;
