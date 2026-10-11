-- pgTAP: row-level security per developer organisation (Unit 1, acceptance criterion 3).
-- Runs inside one transaction (the runner rolls back). Needs: migrations applied, extension pgtap, role mabaniq_app.
-- The ONE documented exception (0.14.0, migration 0007): `demo_requests` — the public landing page's inbox — has no org_id and
-- no RLS by design (a visitor is not a tenant). It is excluded from the per-table checks below and gets its own, narrower checks.
BEGIN;
SELECT plan(
  (SELECT count(*)::int FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('schema_migrations','demo_requests')) * 4  -- enabled, forced, policy, org_id column
  + 10
  + 6   -- demo_requests: explicit exception checks
);

-- 1) every application table: RLS enabled + forced + one org policy + org_id column
SELECT is(c.relrowsecurity, true, format('RLS enabled on %s', c.relname))
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind='r' AND c.relname NOT IN ('schema_migrations','demo_requests');
SELECT is(c.relforcerowsecurity, true, format('RLS forced on %s (owner is not exempt)', c.relname))
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind='r' AND c.relname NOT IN ('schema_migrations','demo_requests');
SELECT is((SELECT count(*) FROM pg_policies p WHERE p.schemaname='public' AND p.tablename=t.tablename), 1::bigint,
          format('exactly one org policy on %s', t.tablename))
  FROM pg_tables t WHERE t.schemaname='public' AND t.tablename NOT IN ('schema_migrations','demo_requests');
SELECT has_column('public', t.tablename, 'org_id', format('%s.org_id exists', t.tablename))
  FROM pg_tables t WHERE t.schemaname='public' AND t.tablename NOT IN ('schema_migrations','demo_requests');

-- 1b) demo_requests (0.14.0): the documented public table — no tenant column, no RLS, append-only for the app role
SELECT has_table('public', 'demo_requests', 'demo_requests exists (migration 0007)');
SELECT hasnt_column('public', 'demo_requests', 'org_id', 'demo_requests has no org_id (public landing-page inbox, by design)');
SELECT is((SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname='demo_requests'),
          false, 'demo_requests has no RLS — the one documented exception');
SELECT ok(has_table_privilege('mabaniq_app', 'demo_requests', 'INSERT'), 'mabaniq_app may INSERT into demo_requests');
SELECT ok(NOT has_table_privilege('mabaniq_app', 'demo_requests', 'UPDATE'), 'mabaniq_app has no table-level UPDATE on demo_requests (append-only inbox)');
SELECT ok(has_column_privilege('mabaniq_app', 'demo_requests', 'mailed', 'UPDATE') AND NOT has_column_privilege('mabaniq_app', 'demo_requests', 'email', 'UPDATE'),
          'mabaniq_app may only flip the delivery flag');

-- 2) the app role cannot bypass RLS and has no UPDATE/DELETE on audit
SELECT is((SELECT rolbypassrls FROM pg_roles WHERE rolname='mabaniq_app'), false, 'mabaniq_app cannot bypass RLS');
SELECT is((SELECT rolsuper FROM pg_roles WHERE rolname='mabaniq_app'), false, 'mabaniq_app is not a superuser');
SELECT ok(NOT has_table_privilege('mabaniq_app', 'audit', 'UPDATE'), 'mabaniq_app has no UPDATE on audit');
SELECT ok(NOT has_table_privilege('mabaniq_app', 'audit', 'DELETE'), 'mabaniq_app has no DELETE on audit');

-- 3) behavioural isolation: rows written as org A are invisible and unwritable as org B
SET ROLE mabaniq_app;
SELECT set_config('app.org_id', 'tap_a', true);
INSERT INTO projects(code,name,location,kind,build_pct,planned_monthly_sales,handover) VALUES('TAP-A','مشروع أ','مسقط','tower',10,1,'2027-01-01');
INSERT INTO settings(k,v) VALUES('tap','a');
SELECT is((SELECT count(*) FROM projects WHERE code='TAP-A'), 1::bigint, 'org A sees its own project');

SELECT set_config('app.org_id', 'tap_b', true);
SELECT is((SELECT count(*) FROM projects WHERE code='TAP-A'), 0::bigint, 'org B sees none of org A''s projects');
SELECT is((SELECT count(*) FROM settings WHERE k='tap'), 0::bigint, 'org B sees none of org A''s settings');
-- the same natural key may exist in both organisations (composite uniqueness with org_id)
INSERT INTO projects(code,name,location,kind,build_pct,planned_monthly_sales,handover) VALUES('TAP-A','مشروع ب','صلالة','villa',5,1,'2027-06-01');
SELECT is((SELECT name FROM projects WHERE code='TAP-A'), 'مشروع ب', 'org B reads only its own row under the shared code');
-- an UPDATE from org B against org A's row touches nothing
UPDATE projects SET name='hijacked' WHERE code='TAP-A' AND name='مشروع أ';
SELECT set_config('app.org_id', 'tap_a', true);
SELECT is((SELECT name FROM projects WHERE code='TAP-A'), 'مشروع أ', 'org A row untouched by org B update');
-- an explicit cross-org INSERT is rejected by WITH CHECK
SELECT throws_like(
  $$INSERT INTO projects(code,name,location,kind,build_pct,planned_monthly_sales,handover,org_id) VALUES('TAP-X','x','x','tower',1,1,'2027-01-01','tap_b')$$,
  '%row-level security%', 'cannot insert a row for another organisation');

SELECT * FROM finish();
ROLLBACK;
