-- pgTAP: Unit 4 integrity — updated_at trigger on every table, financial ledgers without DELETE for the app role.
BEGIN;
SELECT plan(
  (SELECT count(*)::int FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('schema_migrations','audit')) * 2
  + 16 + 3
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
                    'resale_settlements','rent_dues','oa_charges','pay_intents','ipcs','ipc_items','doc_issues','doc_sends']) AS x;

-- 3) behaviour: the trigger stamps updates; the app role is refused a ledger DELETE but may still insert
SET ROLE mabaniq_app;
SELECT set_config('app.org_id', 'tap_u4', true);
INSERT INTO settings(k, v) VALUES ('u4', 'a');
SELECT is((SELECT updated_at FROM settings WHERE k='u4'), NULL, 'updated_at is null on insert');
UPDATE settings SET v = 'b' WHERE k = 'u4';
SELECT isnt((SELECT updated_at FROM settings WHERE k='u4'), NULL, 'updated_at set by the trigger on update');
SELECT throws_like($$ DELETE FROM payments WHERE id = -1 $$, '%permission denied%', 'app role cannot DELETE from payments');
RESET ROLE;

SELECT * FROM finish();
ROLLBACK;
