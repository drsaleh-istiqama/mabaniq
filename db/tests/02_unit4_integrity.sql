-- pgTAP: Unit 4 integrity — updated_at trigger on every table, financial ledgers without DELETE for the app role.
BEGIN;
SELECT plan(
  (SELECT count(*)::int FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('schema_migrations','audit')) * 2
  + 24 + 3 + 3 + 7
);

-- 1) every application table (audit excepted) has updated_at and the trigger
SELECT has_column('public', t.tablename, 'updated_at', format('%s.updated_at exists', t.tablename))
  FROM pg_tables t WHERE t.schemaname='public' AND t.tablename NOT IN ('schema_migrations','audit');
SELECT is((SELECT count(*) FROM pg_trigger tr JOIN pg_class c ON c.oid = tr.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname='public' AND c.relname = t.tablename AND tr.tgname='set_updated_at' AND NOT tr.tgisinternal), 1::bigint,
          format('set_updated_at trigger on %s', t.tablename))
  FROM pg_tables t WHERE t.schemaname='public' AND t.tablename NOT IN ('schema_migrations','audit');

-- 2) no DELETE on the ledgers for mabaniq_app (16 tables, incl. the issued-document registry since 0005)
SELECT ok(NOT has_table_privilege('mabaniq_app', x, 'DELETE'), format('mabaniq_app has no DELETE on %s', x))
  FROM unnest(ARRAY['payments','installments','invoices','refunds','charity_dues','bank_lines','distributions','commissions',
                    'resale_settlements','rent_dues','oa_charges','pay_intents','ipcs','ipc_items','doc_issues','doc_sends','rent_payments','arrears_notices','owner_statements','import_batches','acc_accounts','acc_cost_centers','acc_periods']) AS x;
-- 0.21.0: the rent payments ledger is also closed to UPDATE (a correction is a reversing row)
SELECT ok(NOT has_table_privilege('mabaniq_app', 'rent_payments', 'UPDATE'), 'mabaniq_app has no UPDATE on rent_payments');

-- 3) behaviour: the trigger stamps updates; the app role is refused a ledger DELETE but may still insert
SET ROLE mabaniq_app;
SELECT set_config('app.org_id', 'tap_u4', true);
INSERT INTO settings(k, v) VALUES ('u4', 'a');
SELECT is((SELECT updated_at FROM settings WHERE k='u4'), NULL, 'updated_at is null on insert');
UPDATE settings SET v = 'b' WHERE k = 'u4';
SELECT isnt((SELECT updated_at FROM settings WHERE k='u4'), NULL, 'updated_at set by the trigger on update');
SELECT throws_like($$ DELETE FROM payments WHERE id = -1 $$, '%permission denied%', 'app role cannot DELETE from payments');
SELECT throws_like($$ DELETE FROM rent_payments WHERE id = -1 $$, '%permission denied%', 'app role cannot DELETE from rent_payments');
SELECT throws_like($$ UPDATE rent_payments SET amount = 0 WHERE id = -1 $$, '%permission denied%', 'app role cannot UPDATE rent_payments');
-- 0.22.0: numbered notices and issued owner statements are never deleted (a correction is a new one)
SELECT throws_like($$ DELETE FROM owner_statements WHERE id = -1 $$, '%permission denied%', 'app role cannot DELETE from owner_statements');
-- 0.23.0: the double-entry ledger — the database itself refuses an unbalanced posting and any change to a posted journal
INSERT INTO acc_accounts(code, name, type, normal) VALUES ('T1', 't1', 'asset', 'debit'), ('T2', 't2', 'equity', 'credit');
INSERT INTO acc_journals(jdate, memo, kind, status, total) VALUES ('2026-01-01', 'tap-journal', 'manual', 'draft', 10);
INSERT INTO acc_lines(journal_id, line_no, account_id, debit, credit)
  SELECT j.id, 1, a.id, 10, 0 FROM acc_journals j, acc_accounts a WHERE j.memo = 'tap-journal' AND a.code = 'T1';
INSERT INTO acc_lines(journal_id, line_no, account_id, debit, credit)
  SELECT j.id, 2, a.id, 0, 5 FROM acc_journals j, acc_accounts a WHERE j.memo = 'tap-journal' AND a.code = 'T2';
SELECT throws_like($$ UPDATE acc_journals SET status = 'posted', number = 'JV-T-1' WHERE memo = 'tap-journal' $$, '%not balanced%', 'an unbalanced journal cannot be posted');
SELECT throws_like($$ INSERT INTO acc_lines(journal_id, line_no, account_id, debit, credit) SELECT j.id, 3, a.id, 3, 3 FROM acc_journals j, acc_accounts a WHERE j.memo = 'tap-journal' AND a.code = 'T2' $$,
                   '%check constraint%', 'a line is either debit or credit, never both');
INSERT INTO acc_lines(journal_id, line_no, account_id, debit, credit)
  SELECT j.id, 3, a.id, 0, 5 FROM acc_journals j, acc_accounts a WHERE j.memo = 'tap-journal' AND a.code = 'T2';
SELECT lives_ok($$ UPDATE acc_journals SET status = 'posted', number = 'JV-T-1' WHERE memo = 'tap-journal' $$, 'a balanced journal posts');
SELECT throws_like($$ UPDATE acc_journals SET memo = 'changed' WHERE memo = 'tap-journal' $$, '%immutable%', 'a posted journal cannot be edited');
SELECT throws_like($$ DELETE FROM acc_journals WHERE memo = 'tap-journal' $$, '%immutable%', 'a posted journal cannot be deleted');
SELECT throws_like($$ UPDATE acc_lines SET debit = 99 WHERE line_no = 1 AND journal_id IN (SELECT id FROM acc_journals WHERE memo = 'tap-journal') $$, '%immutable%', 'a posted line cannot be edited');
SELECT throws_like($$ DELETE FROM acc_accounts WHERE code = 'T1' $$, '%permission denied%', 'app role cannot DELETE from acc_accounts');
RESET ROLE;

SELECT * FROM finish();
ROLLBACK;
