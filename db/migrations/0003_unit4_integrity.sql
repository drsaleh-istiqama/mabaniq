-- 0003_unit4_integrity.sql — Unit 4: `updated_at` maintained by trigger on every table, and the application role loses
-- DELETE on the financial ledgers (rows are corrected by compensating entries, never removed; demo reseed runs as the
-- session user in maintenance mode and is unaffected). `audit` stays as in 0001: append-only, no updated_at.
CREATE OR REPLACE FUNCTION mabaniq_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename NOT IN ('schema_migrations', 'audit') LOOP
    EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS updated_at timestamptz', t);
    EXECUTE format('DROP TRIGGER IF EXISTS set_updated_at ON %I', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION mabaniq_set_updated_at()', t);
  END LOOP;
END $$;

-- financial ledgers: no DELETE for the app role (the code never deletes from them; a correction is a new row)
REVOKE DELETE ON payments, installments, invoices, refunds, charity_dues, bank_lines, distributions, commissions,
                 resale_settlements, rent_dues, oa_charges, pay_intents, ipcs, ipc_items FROM mabaniq_app;
