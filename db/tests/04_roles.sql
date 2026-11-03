-- pgTAP: 0.32.0 roles as data — the two tables, the per-organisation uniqueness of a role code and of a (role, permission) pair, and their isolation between organisations (migration 0019).
-- RLS enabled/forced/one policy/org_id on both tables are counted by 01_rls_isolation (it walks every table). Runs inside one transaction (the runner rolls back).
BEGIN;
SELECT plan(5 + 3 + 3 + 3);

SELECT has_table('public', 'roles', 'roles exists (migration 0019)');
SELECT has_table('public', 'role_perms', 'role_perms exists (migration 0019)');
SELECT col_not_null('public', 'roles', 'code', 'roles.code is mandatory');
SELECT has_check('public', 'roles', 'roles.kind is constrained to staff / portal');
SELECT ok(has_table_privilege('mabaniq_app', 'role_perms', 'DELETE') AND has_table_privilege('mabaniq_app', 'roles', 'DELETE'), 'mabaniq_app may DELETE a custom role and its permissions');

-- organisation A (3)
SET ROLE mabaniq_app;
SELECT set_config('app.org_id', 'tap_r_a', true);
INSERT INTO roles(code, label, kind, builtin) VALUES ('custom_1', 'دور تجريبي أ', 'staff', 0);
INSERT INTO role_perms(role_code, perm) VALUES ('custom_1', 'book'), ('custom_1', 'leads');
SELECT is((SELECT count(*) FROM role_perms WHERE role_code='custom_1'), 2::bigint, 'org A holds its role and two permissions');
SELECT throws_like($$INSERT INTO roles(code, label) VALUES ('custom_1', 'مكرر')$$, '%duplicate key%', 'a role code is unique within an organisation');
SELECT throws_like($$INSERT INTO role_perms(role_code, perm) VALUES ('custom_1', 'book')$$, '%duplicate key%', 'a (role, permission) pair is unique within an organisation');

-- organisation B (3): sees nothing of A, may reuse the same code, and cannot write into A
SELECT set_config('app.org_id', 'tap_r_b', true);
SELECT is((SELECT count(*) FROM roles WHERE code='custom_1'), 0::bigint, 'org B sees none of org A''s roles');
SELECT lives_ok($$INSERT INTO roles(code, label, kind) VALUES ('custom_1', 'دور تجريبي ب', 'staff')$$, 'org B may use the same role code on its own');
SELECT throws_like($$INSERT INTO role_perms(role_code, perm, org_id) VALUES ('custom_1', 'book', 'tap_r_a')$$, '%row-level security%', 'cannot write a permission for another organisation');

-- the kind check and the isolation of permissions (3 + 2 counted above: 3 here)
SELECT throws_like($$INSERT INTO roles(code, label, kind) VALUES ('bad_kind', 'x', 'external')$$, '%violates check constraint%', 'a role kind outside staff / portal is refused');
SELECT is((SELECT count(*) FROM role_perms), 0::bigint, 'org B sees none of org A''s permissions');
SELECT set_config('app.org_id', 'tap_r_a', true);
SELECT is((SELECT label FROM roles WHERE code='custom_1'), 'دور تجريبي أ', 'org A reads only its own row under the shared code');

SELECT * FROM finish();
ROLLBACK;
