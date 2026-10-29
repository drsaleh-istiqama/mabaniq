-- 0011_accounting_core.sql — 0.23.0: accounting core (backend/ledger.py, backend/accounting.py). Additive only: five new tables.
-- The journal is an immutable ledger: a posted journal and its lines can never be changed or deleted (guards below), the only legal update of a posted
-- journal is posted -> reversed. Balance (debit = credit, at least two lines) is enforced by the database at the moment a journal becomes posted.
CREATE TABLE acc_accounts(
  id bigserial PRIMARY KEY, code text NOT NULL, name text NOT NULL, name_en text, type text NOT NULL CHECK (type IN ('asset','liability','equity','revenue','expense')),
  parent_id bigint REFERENCES acc_accounts(id), postable bigint NOT NULL DEFAULT 1, normal text NOT NULL CHECK (normal IN ('debit','credit')), system_key text,
  active bigint NOT NULL DEFAULT 1, vat_class text, cash_class text, note text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, code)
);
CREATE UNIQUE INDEX ux_acc_accounts_key ON acc_accounts(org_id, system_key) WHERE system_key IS NOT NULL;

CREATE TABLE acc_cost_centers(
  id bigserial PRIMARY KEY, code text NOT NULL, name text NOT NULL, kind text NOT NULL DEFAULT 'other' CHECK (kind IN ('property','project','dept','other')),
  ref_id bigint, parent_id bigint REFERENCES acc_cost_centers(id), active bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, code)
);
CREATE UNIQUE INDEX ux_acc_cc_ref ON acc_cost_centers(org_id, kind, ref_id) WHERE ref_id IS NOT NULL;

CREATE TABLE acc_periods(
  id bigserial PRIMARY KEY, year bigint NOT NULL, month bigint NOT NULL CHECK (month BETWEEN 1 AND 12), status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  closed_by text, closed_at text, reopened_by text, reopened_at text, reopen_reason text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, year, month)
);

CREATE TABLE acc_journals(
  id bigserial PRIMARY KEY, number text, jdate text NOT NULL, period_id bigint REFERENCES acc_periods(id), memo text, kind text NOT NULL DEFAULT 'manual'
    CHECK (kind IN ('manual','auto','opening','reversal')),
  source_kind text, source_ref text, source_key text, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pending','posted','reversed')),
  created_by text, submitted_by text, approved_by text, posted_by text, posted_at text, reversal_of bigint, reversed_by bigint, reject_note text, total double precision NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, number)
);
CREATE UNIQUE INDEX ux_acc_journals_source ON acc_journals(org_id, source_key) WHERE source_key IS NOT NULL;
CREATE INDEX ix_acc_journals_date ON acc_journals(org_id, jdate);

CREATE TABLE acc_lines(
  id bigserial PRIMARY KEY, journal_id bigint NOT NULL REFERENCES acc_journals(id), line_no bigint NOT NULL, account_id bigint NOT NULL REFERENCES acc_accounts(id),
  cost_center_id bigint REFERENCES acc_cost_centers(id), debit double precision NOT NULL DEFAULT 0, credit double precision NOT NULL DEFAULT 0,
  party_type text, party_id bigint, vat_class text, memo text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  CHECK (debit >= 0 AND credit >= 0 AND ((debit > 0) <> (credit > 0)))
);
CREATE INDEX ix_acc_lines_journal ON acc_lines(journal_id);
CREATE INDEX ix_acc_lines_account ON acc_lines(account_id);
CREATE INDEX ix_acc_lines_party ON acc_lines(party_type, party_id);

-- how much of a source (a rent due) has already been carried to the ledger: a cache that lets a later change post only the difference
CREATE TABLE acc_source_state(
  id bigserial PRIMARY KEY, source_kind text NOT NULL, source_ref text NOT NULL, posted double precision NOT NULL DEFAULT 0, n bigint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
  org_id text NOT NULL DEFAULT current_setting('app.org_id', true),
  UNIQUE (org_id, source_kind, source_ref)
);

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['acc_accounts','acc_cost_centers','acc_periods','acc_journals','acc_lines','acc_source_state']) LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_org ON %I(org_id)', t, t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %s_org ON %I USING (org_id = current_setting(''app.org_id'', true)) WITH CHECK (org_id = current_setting(''app.org_id'', true))', t, t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO mabaniq_app', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;
GRANT USAGE, SELECT ON SEQUENCE acc_accounts_id_seq, acc_cost_centers_id_seq, acc_periods_id_seq, acc_journals_id_seq, acc_lines_id_seq, acc_source_state_id_seq TO mabaniq_app;
-- a period, a cost centre and an account that ever carried a posting are never deleted (deactivate instead)
REVOKE DELETE ON acc_accounts FROM mabaniq_app;
REVOKE DELETE ON acc_cost_centers FROM mabaniq_app;
REVOKE DELETE ON acc_periods FROM mabaniq_app;

-- the journal guard: drafts are free, a posted journal is frozen except posted -> reversed (status + reversed_by), balance is checked on posting
CREATE OR REPLACE FUNCTION mabaniq_acc_journal_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE diff double precision; n bigint;
BEGIN
  IF current_setting('app.maintenance', true) = '1' THEN RETURN COALESCE(NEW, OLD); END IF;
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN RAISE EXCEPTION 'a posted journal is immutable'; END IF;
    RETURN OLD;
  END IF;
  IF OLD.status IN ('posted', 'reversed') THEN
    IF NOT (OLD.status = 'posted' AND NEW.status = 'reversed' AND NEW.number IS NOT DISTINCT FROM OLD.number AND NEW.jdate = OLD.jdate AND NEW.total = OLD.total
            AND NEW.memo IS NOT DISTINCT FROM OLD.memo AND NEW.source_key IS NOT DISTINCT FROM OLD.source_key AND NEW.kind = OLD.kind) THEN
      RAISE EXCEPTION 'a posted journal is immutable';
    END IF;
  END IF;
  IF NEW.status = 'posted' AND OLD.status <> 'posted' THEN
    SELECT COALESCE(SUM(debit), 0) - COALESCE(SUM(credit), 0), COUNT(*) INTO diff, n FROM acc_lines WHERE journal_id = NEW.id;
    IF n < 2 OR abs(diff) > 0.0005 THEN RAISE EXCEPTION 'journal is not balanced'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER acc_journal_guard BEFORE UPDATE OR DELETE ON acc_journals FOR EACH ROW EXECUTE FUNCTION mabaniq_acc_journal_guard();

CREATE OR REPLACE FUNCTION mabaniq_acc_lines_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE st text; jid bigint;
BEGIN
  IF current_setting('app.maintenance', true) = '1' THEN RETURN COALESCE(NEW, OLD); END IF;
  jid := CASE WHEN TG_OP = 'INSERT' THEN NEW.journal_id ELSE OLD.journal_id END;
  SELECT status INTO st FROM acc_journals WHERE id = jid;
  IF st IS DISTINCT FROM 'draft' THEN RAISE EXCEPTION 'a posted journal is immutable'; END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER acc_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON acc_lines FOR EACH ROW EXECUTE FUNCTION mabaniq_acc_lines_guard();
