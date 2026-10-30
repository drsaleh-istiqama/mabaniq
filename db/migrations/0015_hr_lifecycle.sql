-- 0015_hr_lifecycle.sql — 0.27.0: the rest of the employee's life (backend/hr_recruit.py, hr_perf.py, hr_disc.py). Additive only.
-- Recruitment (openings, candidates with a CV, interviews; a rejected candidate's data is erased after a retention period), the annual appraisal
-- (self → manager → HR → acknowledged), training with certificate expiry, and discipline: a penalty can be issued ONLY under a bylaw article that a second
-- person approved, and a deduction is applied by payroll as days of wage.

CREATE TABLE job_openings(
  id bigserial PRIMARY KEY, title text NOT NULL, department_id bigint REFERENCES departments(id), position_id bigint REFERENCES positions(id), headcount bigint NOT NULL DEFAULT 1 CHECK (headcount >= 1),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','open','closed','filled','cancelled')), opened_on text, closes_on text, description text, requirements text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE TABLE candidates(
  id bigserial PRIMARY KEY, opening_id bigint NOT NULL REFERENCES job_openings(id), name text NOT NULL, phone text, email text, source text,
  stage text NOT NULL DEFAULT 'applied' CHECK (stage IN ('applied','screening','interview','offer','hired','rejected','withdrawn')), rating bigint CHECK (rating BETWEEN 1 AND 5), notes text,
  cv_document_id bigint, reject_reason text, hired_employee_id bigint REFERENCES employees(id), anonymized bigint NOT NULL DEFAULT 0, stage_at text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX ix_candidates_opening ON candidates(opening_id);
CREATE TABLE interviews(
  id bigserial PRIMARY KEY, candidate_id bigint NOT NULL REFERENCES candidates(id), scheduled_at text NOT NULL, kind text NOT NULL DEFAULT 'in_person' CHECK (kind IN ('phone','in_person','online','technical')),
  interviewer text, status text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','done','cancelled')), score bigint CHECK (score BETWEEN 1 AND 5), notes text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX ix_interviews_candidate ON interviews(candidate_id);

CREATE TABLE appraisal_cycles(
  id bigserial PRIMARY KEY, name text NOT NULL, year bigint NOT NULL, start_date text NOT NULL, end_date text NOT NULL, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','open','closed')), created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, name)
);
CREATE TABLE appraisals(
  id bigserial PRIMARY KEY, cycle_id bigint NOT NULL REFERENCES appraisal_cycles(id), employee_id bigint NOT NULL REFERENCES employees(id), reviewer_id bigint REFERENCES employees(id),
  status text NOT NULL DEFAULT 'self' CHECK (status IN ('self','manager','hr','final','ack')), goals text, competencies text, self_comment text, manager_comment text, hr_comment text,
  overall double precision, rating text, decision text NOT NULL DEFAULT 'none' CHECK (decision IN ('none','promotion','raise','training','improvement_plan','no_action')),
  self_at text, manager_at text, hr_at text, hr_by text, ack_at text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, cycle_id, employee_id)
);

CREATE TABLE training_courses(
  id bigserial PRIMARY KEY, title text NOT NULL, provider text, hours double precision CHECK (hours >= 0), cert_valid_months bigint CHECK (cert_valid_months > 0), mandatory bigint NOT NULL DEFAULT 0,
  active bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, title)
);
CREATE TABLE training_records(
  id bigserial PRIMARY KEY, course_id bigint NOT NULL REFERENCES training_courses(id), employee_id bigint NOT NULL REFERENCES employees(id),
  status text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','completed','cancelled','no_show')), planned_on text, completed_on text, score double precision, certificate_no text, cert_expires text,
  document_id bigint, note text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true)
);
CREATE INDEX ix_training_records_emp ON training_records(employee_id);

-- a bylaw article: `source` names the approved bylaw it comes from; until a second person approves it no penalty can be issued under it
CREATE TABLE penalty_rules(
  id bigserial PRIMARY KEY, code text NOT NULL, name text NOT NULL, description text, kind text NOT NULL CHECK (kind IN ('warning','deduction','suspension')), max_days double precision NOT NULL DEFAULT 0 CHECK (max_days >= 0),
  source text NOT NULL, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','retired')), valid_from text, created_by text, approved_by text, approved_at text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, code)
);
CREATE TABLE disciplinary_cases(
  id bigserial PRIMARY KEY, number text NOT NULL, employee_id bigint NOT NULL REFERENCES employees(id), incident_date text NOT NULL, description text NOT NULL, rule_id bigint REFERENCES penalty_rules(id),
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','proposed','issued','appealed','revoked','closed')), statement text, witnesses text, penalty_days double precision NOT NULL DEFAULT 0 CHECK (penalty_days >= 0),
  apply_period text, proposed_by text, issued_by text, issued_at text, appeal_text text, appeal_at text, appeal_decision text CHECK (appeal_decision IN ('upheld','revoked')), appeal_decided_by text, appeal_decided_at text,
  applied_run_id bigint REFERENCES payroll_runs(id), closed_note text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, number)
);
CREATE INDEX ix_disc_emp ON disciplinary_cases(employee_id);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['job_openings','candidates','interviews','appraisal_cycles','appraisals','training_courses','training_records','penalty_rules','disciplinary_cases']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE job_openings_id_seq, candidates_id_seq, interviews_id_seq, appraisal_cycles_id_seq, appraisals_id_seq, training_courses_id_seq, training_records_id_seq,
  penalty_rules_id_seq, disciplinary_cases_id_seq TO mabaniq_app;
-- appraisals, disciplinary cases and bylaw articles are service history: never deleted (a case is closed or revoked, an article retired)
REVOKE DELETE ON appraisals FROM mabaniq_app;
REVOKE DELETE ON disciplinary_cases FROM mabaniq_app;
REVOKE DELETE ON penalty_rules FROM mabaniq_app;
