-- pgTAP: Unit 4 integrity — updated_at trigger on every table, financial ledgers without DELETE for the app role.
BEGIN;
SELECT plan(
  (SELECT count(*)::int FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('schema_migrations','audit')) * 2
  + 45 + 3 + 3 + 7 + 2 + 3 + 6 + 3 + 3
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
                    'resale_settlements','rent_dues','oa_charges','pay_intents','ipcs','ipc_items','doc_issues','doc_sends','rent_payments','arrears_notices','owner_statements','import_batches','acc_accounts','acc_cost_centers','acc_periods','bank_accounts','payment_orders','vat_returns','bank_recons','depreciation_runs','ap_payments','employees','leave_requests','hr_requests','leave_types','payroll_runs','salary_structures','employee_loans','loan_installments','eosb_rules','terminations','hr_rates','appraisals','disciplinary_cases','penalty_rules']) AS x;
-- 0.21.0: the rent payments ledger is also closed to UPDATE (a correction is a reversing row)
SELECT ok(NOT has_table_privilege('mabaniq_app', 'rent_payments', 'UPDATE'), 'mabaniq_app has no UPDATE on rent_payments');
-- 0.24.0: a supplier payment is a ledger row too
SELECT ok(NOT has_table_privilege('mabaniq_app', 'ap_payments', 'UPDATE'), 'mabaniq_app has no UPDATE on ap_payments');

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
-- 0.24.0: a bank account can only be Islamic (a conventional one is refused by the database as well as by the API)
SELECT throws_like($$ INSERT INTO bank_accounts(name, account_id, islamic) SELECT 'conv', id, 0 FROM acc_accounts WHERE code = 'T1' $$, '%check constraint%', 'a non-Islamic bank account is refused');
SELECT throws_like($$ UPDATE ap_payments SET amount = 0 WHERE id = -1 $$, '%permission denied%', 'app role cannot UPDATE ap_payments');
-- 0.25.0: the people file — an employee cannot be his own manager, a leave cannot end before it starts, one version of a leave type per effective date
INSERT INTO employees(number, name, hire_date) VALUES ('T-1', 'tap-employee', '2026-01-01');
INSERT INTO leave_types(key, name, valid_from) VALUES ('t', 'tap-type', '2000-01-01');
SELECT throws_like($$ UPDATE employees SET manager_id = id WHERE number = 'T-1' $$, '%check constraint%', 'an employee cannot be his own manager');
SELECT throws_like($$ INSERT INTO leave_requests(employee_id, type_id, type_key, from_date, to_date, days) SELECT e.id, t.id, 't', '2026-02-02', '2026-02-01', 1 FROM employees e, leave_types t WHERE e.number = 'T-1' AND t.key = 't' $$,
                   '%check constraint%', 'a leave cannot end before it starts');
SELECT throws_like($$ INSERT INTO leave_types(key, name, valid_from) VALUES ('t', 'dup', '2000-01-01') $$, '%duplicate key%', 'one version of a leave type per effective date');
-- 0.26.0: payroll — an approved payslip is frozen by the database, one run per month, and a staff loan has no rate, interest, fee or profit column at all
INSERT INTO payroll_runs(period, status) VALUES ('2026-01', 'computed');
SELECT lives_ok($$ INSERT INTO payslips(run_id, employee_id, net) SELECT r.id, e.id, 100 FROM payroll_runs r, employees e WHERE r.period = '2026-01' AND e.number = 'T-1' $$, 'a payslip of a computed run can be written');
SELECT lives_ok($$ UPDATE payroll_runs SET status = 'approved' WHERE period = '2026-01' $$, 'the run is approved');
SELECT throws_like($$ UPDATE payslips SET net = 1 WHERE net = 100 $$, '%immutable%', 'an approved payslip cannot be edited');
SELECT throws_like($$ DELETE FROM payslips WHERE net = 100 $$, '%immutable%', 'an approved payslip cannot be deleted');
SELECT throws_like($$ INSERT INTO payroll_runs(period) VALUES ('2026-01') $$, '%duplicate key%', 'one payroll run per month');
SELECT is((SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name IN ('employee_loans', 'loan_installments') AND column_name ~* '(rate|interest|fee|profit|markup)'), 0::bigint,
          'a staff loan has no rate, interest, fee or profit column');
-- 0.27.0: lifecycle — a candidate's rating is 1 to 5, one appraisal per person per cycle, and a bylaw article has a known status
INSERT INTO job_openings(title) VALUES ('tap-opening');
INSERT INTO appraisal_cycles(name, year, start_date, end_date) VALUES ('tap-cycle', 2026, '2026-01-01', '2026-12-31');
INSERT INTO appraisals(cycle_id, employee_id) SELECT k.id, e.id FROM appraisal_cycles k, employees e WHERE k.name = 'tap-cycle' AND e.number = 'T-1';
SELECT throws_like($$ INSERT INTO candidates(opening_id, name, rating) SELECT id, 'x', 6 FROM job_openings WHERE title = 'tap-opening' $$, '%check constraint%', 'a candidate rating is 1 to 5');
SELECT throws_like($$ INSERT INTO appraisals(cycle_id, employee_id) SELECT k.id, e.id FROM appraisal_cycles k, employees e WHERE k.name = 'tap-cycle' AND e.number = 'T-1' $$, '%duplicate key%', 'one appraisal per employee per cycle');
SELECT throws_like($$ INSERT INTO penalty_rules(code, name, kind, source, status) VALUES ('t', 't', 'warning', 'src', 'secret') $$, '%check constraint%', 'a bylaw article has a known status');
-- 0.28.0: portals — one login per tenant file; the tenant's acknowledgement of the privacy notice is a column of their own file
INSERT INTO tenants_l(name) VALUES ('tap-tenant');
INSERT INTO users(username, name, role, pw, lessee_id) SELECT 'tap-l1', 'x', 'lessee', 'x', id FROM tenants_l WHERE name = 'tap-tenant';
SELECT throws_like($$ INSERT INTO users(username, name, role, pw, lessee_id) SELECT 'tap-l2', 'x', 'lessee', 'x', id FROM tenants_l WHERE name = 'tap-tenant' $$, '%duplicate key%', 'one login per tenant file');
SELECT has_column('public', 'users', 'lessee_id', 'users.lessee_id links a login to a tenant file');
SELECT has_column('public', 'tenants_l', 'consent_at', 'tenants_l.consent_at holds the tenant''s own acknowledgement');
RESET ROLE;

SELECT * FROM finish();
ROLLBACK;
