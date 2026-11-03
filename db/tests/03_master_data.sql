-- pgTAP: 0.31.0 master data — the stop flag, the contractor columns, the buildings register, the price-change ledger and the partial unique indexes (migration 0018).
-- Runs inside one transaction (the runner rolls back). Needs: migrations applied, extension pgtap, role mabaniq_app.
BEGIN;
SELECT plan(8 + 4 + 2 + 3 + 5 + 4 + 2 + 4);

-- 1) the stop flag exists on the eight tables, and the contractor gained its columns (8 + 4)
SELECT has_column('public', t, 'active', format('%s.active exists', t))
  FROM unnest(ARRAY['projects','units','customers','lands','permits','contractors','contracts_c','schedule_tasks']) AS t;
SELECT has_column('public', 'contractors', c, format('contractors.%s exists', c)) FROM unnest(ARRAY['phone','email','trade','notes']) AS c;

-- 2) the two new tables exist (2); neither has its rows deleted by the app role; the price ledger is also closed to UPDATE (3)
SELECT has_table('public', 'buildings', 'buildings exists (migration 0018)');
SELECT has_table('public', 'unit_price_changes', 'unit_price_changes exists (migration 0018)');
SELECT ok(NOT has_table_privilege('mabaniq_app', 'buildings', 'DELETE'), 'mabaniq_app has no DELETE on buildings (a building is stopped, never deleted)');
SELECT ok(NOT has_table_privilege('mabaniq_app', 'unit_price_changes', 'DELETE'), 'mabaniq_app has no DELETE on unit_price_changes');
SELECT ok(NOT has_table_privilege('mabaniq_app', 'unit_price_changes', 'UPDATE'), 'mabaniq_app has no UPDATE on unit_price_changes (a correction is a new row)');

-- 3) behaviour as organisation A (6)
SET ROLE mabaniq_app;
SELECT set_config('app.org_id', 'tap_m_a', true);
INSERT INTO projects(code,name,location,kind,build_pct,planned_monthly_sales,handover) VALUES('TAP-M','مشروع أ','مسقط','tower',0,0,'2027-01-01');
SELECT is((SELECT active FROM projects WHERE code='TAP-M'), 1::bigint, 'a new project is active by default');
INSERT INTO buildings(project_id, name) SELECT id, 'B1' FROM projects WHERE code='TAP-M';
SELECT throws_like($$INSERT INTO buildings(project_id, name) SELECT id, 'B1' FROM projects WHERE code='TAP-M'$$, '%duplicate key%', 'a building name is unique within its project');
INSERT INTO units(project_id, code, building, status) SELECT id, 'TAP-M-1', 'B1', 'a' FROM projects WHERE code='TAP-M';
INSERT INTO unit_price_changes(unit_id, old_price, new_price, reason, basis, changed_by, changed_at) SELECT id, NULL, 100, 'tap', 'free', 'tap', '2026-11-03' FROM units WHERE code='TAP-M-1';
SELECT is((SELECT count(*) FROM unit_price_changes), 1::bigint, 'the price-change ledger accepts an INSERT');
SELECT throws_like($$UPDATE unit_price_changes SET new_price = 1$$, '%permission denied%', 'the ledger refuses an UPDATE from the app role');
SELECT throws_like($$DELETE FROM unit_price_changes$$, '%permission denied%', 'the ledger refuses a DELETE from the app role');

-- 4) behaviour as organisation B: sees nothing of A, may reuse A's building name on its own project (4)
SELECT set_config('app.org_id', 'tap_m_b', true);
SELECT is((SELECT count(*) FROM buildings), 0::bigint, 'org B sees none of org A''s buildings');
INSERT INTO projects(code,name,location,kind,build_pct,planned_monthly_sales,handover) VALUES('TAP-M','مشروع ب','صلالة','villa',0,0,'2027-01-01');
SELECT lives_ok($$INSERT INTO buildings(project_id, name) SELECT id, 'B1' FROM projects WHERE code='TAP-M'$$, 'org B may use the same building name on its own project');
SELECT is((SELECT count(*) FROM unit_price_changes), 0::bigint, 'org B sees none of org A''s price changes');
SELECT throws_like($$INSERT INTO buildings(project_id, name, org_id) SELECT id, 'X', 'tap_m_a' FROM projects WHERE code='TAP-M'$$, '%row-level security%', 'cannot insert a building for another organisation');

-- 5) the partial unique indexes exist (2) and hold (6): one commercial register per contractor, one active contract per project
SELECT ok(EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='ux_contractors_cr'), 'ux_contractors_cr exists');
SELECT ok(EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='ux_contracts_c_one_active'), 'ux_contracts_c_one_active exists');
SELECT set_config('app.org_id', 'tap_m_a', true);
INSERT INTO contractors(name, cr_number) VALUES ('مقاول أ', 'CR-TAP-1');
SELECT throws_like($$INSERT INTO contractors(name, cr_number) VALUES ('مقاول مكرر', 'CR-TAP-1')$$, '%duplicate key%', 'a commercial register belongs to one contractor');
SELECT lives_ok($$INSERT INTO contractors(name) VALUES ('مقاول بلا سجل 1'), ('مقاول بلا سجل 2')$$, 'contractors without a register do not collide');
INSERT INTO contracts_c(project_id, contractor_id, value, retention_pct, delay_penalty_per_day, start, finish)
  SELECT p.id, k.id, 1000, 0.1, 5, '2026-01-01', '2027-01-01' FROM projects p, contractors k WHERE p.code='TAP-M' AND k.cr_number='CR-TAP-1';
SELECT throws_like($$INSERT INTO contracts_c(project_id, contractor_id, value, retention_pct, delay_penalty_per_day, start, finish)
                     SELECT p.id, k.id, 2000, 0.1, 5, '2026-01-01', '2027-01-01' FROM projects p, contractors k WHERE p.code='TAP-M' AND k.cr_number='CR-TAP-1'$$,
                   '%duplicate key%', 'a project has one active contractor contract');
SELECT lives_ok($$INSERT INTO contracts_c(project_id, contractor_id, value, retention_pct, delay_penalty_per_day, start, finish, active)
                  SELECT p.id, k.id, 3000, 0.1, 5, '2025-01-01', '2025-12-31', 0 FROM projects p, contractors k WHERE p.code='TAP-M' AND k.cr_number='CR-TAP-1'$$,
                'a terminated contract does not block history');

SELECT * FROM finish();
ROLLBACK;
