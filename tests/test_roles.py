"""0.32.0 — الأدوار والصلاحيات كبيانات (docs/DESIGN-roles-permissions.md).

الافتراضي مطابق للكود حرفيًا · سحب صلاحية يسري على جلسة المستخدم الحالية عند أول طلب · دور مخصص بدورة حياة كاملة · حواجز القفل الذاتي · عزل الأدوار بين مطوّرين ·
إبطال الذاكرة بعدّاد القاعدة عبر نسختين مستقلتين (عاملان) · التدقيق من ⟵ إلى · ترقية الكتالوج لا تعيد منح ما سُحب. لا SQL خاص بمحرك إلا لما لا يصنعه الـAPI.
"""
import contextlib
import json
import os
import tempfile
import time

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "roles.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "almukhatat:المخطط العقارية;bayan:بيان عمان;almaqsura:المقصورة العقارية;view:رؤية العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import roles as R  # noqa: E402
from backend.app import app  # noqa: E402
from backend.auth import ALL_STAFF, PERMS, ROLES  # noqa: E402
from backend.db import TENANT, connect  # noqa: E402

CSRF = "csrf-rl-" + "r" * 30


def login_as(c, user, tenant):
    tok = TENANT.set(tenant)
    try:
        c.cookies.set(A.COOKIE, A.issue_session(user))
    finally:
        TENANT.reset(tok)
    c.cookies.set(A.TENANT_COOKIE, tenant)
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


@contextlib.contextmanager
def _client(tenant="jadwa", user="admin"):
    from backend import observability as O
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        yield login_as(c, user, tenant)


@pytest.fixture()
def jd():
    with _client("jadwa") as c:
        yield c


def _sql(sql, args=(), tenant="jadwa"):
    tok = TENANT.set(tenant)
    try:
        c = connect()
        try:
            r = c.execute(sql, args)
            out = r.fetchall() if sql.lstrip().upper().startswith("SELECT") else None
            c.commit()
            return out
        finally:
            c.close()
    finally:
        TENANT.reset(tok)


def last_audit(c) -> dict:
    r = c.get("/api/audit", params={"limit": 1}).json()
    return r[0] if r else {"id": 0, "action": "", "detail": "", "actor": ""}


def role(c, code) -> dict:
    return next(r for r in c.get("/api/roles").json()["roles"] if r["code"] == code)


def change(c, code, grant=(), revoke=()):
    return c.post(f"/api/roles/{code}/perms", json={"grant": list(grant), "revoke": list(revoke)})


def make_user(c, username, role_code, tenant="jadwa"):
    r = c.post("/api/users", json={"username": username, "name": "مستخدم اختبار الأدوار", "role": role_code})
    assert r.status_code == 200, r.text
    _sql("UPDATE users SET must_change=0 WHERE username=?", (username,), tenant)
    return next(u for u in c.get("/api/users").json() if u["username"] == username)


def tag() -> str:
    return str(int(time.time() * 1000) % 10**8)


# ====================================================================================================== الافتراضي مطابق للكود
def test_the_default_matrix_is_exactly_what_the_code_always_said(jd):
    r = jd.get("/api/roles").json()
    assert {p["perm"] for p in r["perms"]} == set(ALL_STAFF)
    assert all(p["label"] and p["section"] in {s["key"] for s in r["sections"]} for p in r["perms"])
    assert [s["title"] for s in r["sections"]][:2] == ["عام", "المخزون والبيانات الأساسية"]
    by_code = {x["code"]: x for x in r["roles"]}
    assert set(by_code) >= set(ROLES)
    for code in ROLES:
        assert set(by_code[code]["perms"]) == set(PERMS[code]), code                                       # a developer who never touched it sees today's behaviour
        assert by_code[code]["label"] == ROLES[code]
    assert by_code["sales"]["editable"] and by_code["sales"]["deletable"] is False and by_code["sales"]["builtin"]
    for fixed in ("customer", "broker", "lessee", "employee", "property_manager"):
        assert by_code[fixed]["editable"] is False and by_code[fixed]["kind"] == "portal", fixed
    assert by_code["admin"]["two_fa"] and by_code["payroll"]["two_fa"] and not by_code["sales"]["two_fa"]
    assert r["must_keep"] == {"admin": ["admin", "users"]}
    with _client("jadwa", "sales") as s:
        assert s.get("/api/roles").status_code == 403                                                          # only whoever holds `users` sees the matrix


# ====================================================================================================== الأثر الفوري
def test_withdrawing_a_permission_takes_effect_on_the_users_existing_session_and_giving_it_back_restores_it(jd):
    with _client("jadwa", "sales") as s:
        me = s.get("/api/me").json()
        assert "leads" in me["perms"] and "book" in me["perms"]
        assert s.get("/api/leads").status_code == 200
        before = last_audit(jd)["id"]
        r = change(jd, "sales", revoke=["leads"])
        assert r.status_code == 200 and r.json()["removed"] == ["leads"] and r.json()["changed"] == ["leads"], r.text
        try:
            assert s.get("/api/leads").status_code == 403                                                      # the same session, the very next request
            assert "leads" not in s.get("/api/me").json()["perms"]
            a = last_audit(jd)
            assert a["id"] > before and a["action"] == "تعديل صلاحيات دور" and "«مبيعات»" in a["detail"] and "سُحبت: العملاء المحتملون والحملات" in a["detail"] and "مدير المنصة" in a["actor"]
            again = last_audit(jd)["id"]
            assert change(jd, "sales", revoke=["leads"]).json()["changed"] == [] and last_audit(jd)["id"] == again      # nothing to withdraw: nothing written
        finally:
            assert change(jd, "sales", grant=["leads"]).status_code == 200
        assert s.get("/api/leads").status_code == 200
        assert "أُضيفت: العملاء المحتملون والحملات" in last_audit(jd)["detail"]
    assert set(role(jd, "sales")["perms"]) == set(PERMS["sales"])


def test_without_book_a_sales_user_cannot_book_and_with_it_he_can(jd):
    pid = jd.get("/api/projects").json()[0]["id"]
    unit = next(u for u in jd.get("/api/units", params={"project_id": pid}).json() if u["status"] == "a" and not u["retained"])
    body = {"unit_code": unit["code"], "customer_name": "عميل اختبار الأدوار", "phone": "+968 9555 7001", "plan": "milestone"}
    with _client("jadwa", "sales") as s:
        assert change(jd, "sales", revoke=["book"]).status_code == 200
        try:
            assert s.post("/api/bookings", json=body).status_code == 403
        finally:
            assert change(jd, "sales", grant=["book"]).status_code == 200
        r = s.post("/api/bookings", json=body)
        assert r.status_code == 200, r.text
        assert s.post(f"/api/bookings/{r.json()['booking_id']}/cancel").status_code == 200                      # leave the unit as it was


# ====================================================================================================== دور مخصص
def test_a_custom_role_is_made_from_a_copy_given_a_user_moved_renamed_and_deleted(jd):
    label = "مسؤول مبيعات أول " + tag()
    r = jd.post("/api/roles", json={"label": label, "copy_from": "sales"})
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    uname, uid = "rl." + tag(), None
    try:
        assert code.startswith("custom_") and set(role(jd, code)["perms"]) == set(PERMS["sales"])
        assert role(jd, code)["deletable"] and not role(jd, code)["builtin"] and role(jd, code)["users"] == 0
        assert last_audit(jd)["action"] == "دور جديد" and label in last_audit(jd)["detail"] and "منسوخ من «مبيعات»" in last_audit(jd)["detail"]
        assert jd.post("/api/roles", json={"label": label}).status_code == 409                                  # the name is taken
        assert jd.post("/api/roles", json={"label": "ab"}).status_code == 422
        assert jd.post("/api/roles", json={"label": "دور من بوابة", "copy_from": "customer"}).status_code == 403    # a portal role is never a template
        assert jd.post("/api/roles", json={"label": "دور من مجهول", "copy_from": "nope"}).status_code == 404
        r = change(jd, code, grant=["finance", "reports"])
        assert r.status_code == 200 and sorted(r.json()["added"]) == ["finance", "reports"], r.text
        u = make_user(jd, uname, code)
        uid = u["id"]
        assert u["role"] == code and u["role_label"] == label                                                   # the list carries the server's label
        assert role(jd, code)["users"] == 1
        with _client("jadwa", uname) as cu:
            me = cu.get("/api/me").json()
            assert me["role"] == code and me["role_label"] == label and {"finance", "reports"} <= set(me["perms"]) and set(PERMS["sales"]) <= set(me["perms"])
            assert cu.get("/api/leads").status_code == 200
            assert change(jd, code, revoke=["leads"]).status_code == 200
            assert cu.get("/api/leads").status_code == 403                                                      # …and loses it at once
        d = jd.delete(f"/api/roles/{code}")
        assert d.status_code == 409 and "1" in d.json()["detail"] and "انقلهم" in d.json()["detail"]            # a role with users is not deleted
        assert jd.post("/api/users", json={"username": uname + "x", "name": "مستخدم بدور مجهول", "role": "custom_999"}).status_code == 422
        assert jd.post(f"/api/users/{uid}/role", json={"role": "sales"}).json()["changed"] == ["role"]           # move him
        assert "«" + label + "» ⟵ «مبيعات»" in last_audit(jd)["detail"] and last_audit(jd)["action"] == "تغيير دور مستخدم"
        assert jd.post(f"/api/users/{uid}/role", json={"role": "sales"}).json()["changed"] == []
        assert next(x for x in jd.get("/api/users").json() if x["id"] == uid)["role_label"] == ROLES["sales"]
        assert jd.post(f"/api/users/{uid}/role", json={"role": "customer"}).status_code == 400                   # not a staff role
        assert jd.post(f"/api/users/{uid}/role", json={"role": "custom_999"}).status_code == 400
        assert jd.patch(f"/api/roles/{code}", json={"label": label + " ب"}).json()["changed"] == ["label"]
        assert role(jd, code)["label"].endswith(" ب")
        assert jd.patch("/api/roles/sales", json={"label": "اسم جديد للمبيعات"}).status_code == 403             # the built-in names are fixed
        assert jd.delete(f"/api/roles/{code}").status_code == 200
        assert last_audit(jd)["action"] == "حذف دور"
        assert code not in {x["code"] for x in jd.get("/api/roles").json()["roles"]}
        assert jd.delete("/api/roles/sales").status_code == 403 and jd.delete("/api/roles/customer").status_code == 403
        assert jd.delete(f"/api/roles/{code}").status_code == 404
        assert _sql("SELECT COUNT(*) n FROM role_perms WHERE role_code=?", (code,))[0]["n"] == 0                # its permissions went with it
    finally:
        if uid:
            jd.post(f"/api/users/{uid}/active", json={"active": False})
        jd.delete(f"/api/roles/{code}")


# ====================================================================================================== الحواجز
def test_the_general_manager_keeps_admin_and_users_and_portal_roles_are_fixed(jd):
    for p in ("admin", "users"):
        r = change(jd, "admin", revoke=[p])
        assert r.status_code == 409 and "المدير العام" in r.json()["detail"], (p, r.text)
    assert {"admin", "users"} <= set(role(jd, "admin")["perms"])
    assert change(jd, "customer", grant=["view"]).status_code == 403
    assert change(jd, "broker", revoke=["broker_portal"]).status_code == 403
    assert change(jd, "nonexistent", grant=["view"]).status_code == 404
    assert change(jd, "sales", grant=["portal"]).status_code == 400                                              # a portal permission is not grantable to staff
    assert change(jd, "sales", grant=["nonexistent_perm"]).status_code == 400
    r = jd.post("/api/roles/sales/perms", json={"grant": ["view"], "revoke": ["view"]})
    assert r.status_code == 400 and "معًا" in r.json()["detail"]
    assert jd.post("/api/roles/sales/perms", json={"grant": ["view"], "oops": 1}).status_code == 422
    assert set(role(jd, "sales")["perms"]) == set(PERMS["sales"])


def test_the_last_active_manager_cannot_be_stopped_demoted_or_stripped_of_the_admin_permission():
    t = tag()
    code = deleg = me = None
    with _client("nahda") as a:                                                                                    # a developer with exactly one manager
        admins = [u for u in a.get("/api/users").json() if u["role"] == "admin" and u["active"]]
        assert len(admins) == 1, admins
        me = admins[0]
        code = a.post("/api/roles", json={"label": "مسؤول مستخدمين " + t}).json()["code"]
        assert change(a, code, grant=["users", "view"]).status_code == 200
        deleg = make_user(a, "rl.d" + t, code, "nahda")                                                            # holds `users` but not `admin`
    try:
        with _client("nahda", deleg["username"]) as d:
            r = d.post(f"/api/users/{me['id']}/active", json={"active": False})
            assert r.status_code == 409 and "آخر مدير" in r.json()["detail"], r.text                             # the only manager is not stopped by a delegate
            r = d.post(f"/api/users/{me['id']}/role", json={"role": "sales"})
            assert r.status_code == 409 and "آخر مدير" in r.json()["detail"], r.text                             # nor demoted
        with _client("nahda") as a:
            assert change(a, code, grant=["admin"]).status_code == 200                                             # now the delegate role is a manager role too
        with _client("nahda", deleg["username"]) as d:
            assert d.post(f"/api/users/{me['id']}/active", json={"active": False}).status_code == 200            # a second manager exists: the first may be stopped
            r = change(d, code, revoke=["admin"])
            assert r.status_code == 409 and "آخر مدير" in r.json()["detail"], r.text                             # …and now the delegate role holds the last `admin`
            assert d.post(f"/api/users/{deleg['id']}/role", json={"role": "sales"}).status_code == 409
            assert d.post(f"/api/users/{me['id']}/active", json={"active": True}).status_code == 200              # restore the first manager
        with _client("nahda") as a:
            assert change(a, code, revoke=["admin"]).status_code == 200                                            # two managers again: the delegate role may lose it
    finally:
        with _client("nahda") as a:
            if me:
                a.post(f"/api/users/{me['id']}/active", json={"active": True})
            if deleg:
                a.post(f"/api/users/{deleg['id']}/role", json={"role": "sales"})
                a.post(f"/api/users/{deleg['id']}/active", json={"active": False})
            if code:
                a.delete(f"/api/roles/{code}")


# ====================================================================================================== العزل والذاكرة والترقية
def test_roles_belong_to_one_developer_and_do_not_leak_to_another(jd):
    with _client("nahda") as other, _client("jadwa", "sales") as s_j, _client("nahda", "sales") as s_n:
        assert change(jd, "sales", revoke=["leads"]).status_code == 200
        try:
            assert s_j.get("/api/leads").status_code == 403
            assert "leads" in role(other, "sales")["perms"] and s_n.get("/api/leads").status_code == 200       # the other developer's sales role is untouched
            label = "دور جدوى فقط " + tag()
            code = jd.post("/api/roles", json={"label": label}).json()["code"]
            try:
                assert label not in {r["label"] for r in other.get("/api/roles").json()["roles"]}
            finally:
                jd.delete(f"/api/roles/{code}")
        finally:
            assert change(jd, "sales", grant=["leads"]).status_code == 200


def test_the_cache_is_invalidated_by_the_databases_counter_so_another_worker_sees_a_change_at_its_first_request(jd):
    w1, w2 = R.RolesCache(), R.RolesCache()          # two uvicorn workers: two caches that share nothing but the database
    tok = TENANT.set("jadwa")
    try:
        c = connect()
        try:
            assert "leads" in w1.get(c)["sales"]["perms"] and "leads" in w2.get(c)["sales"]["perms"]
            assert (w1.loads, w2.loads) == (1, 1)
            w1.get(c), w2.get(c)
            assert (w1.loads, w2.loads) == (1, 1), "an unchanged counter must not reload"
        finally:
            c.close()
        assert change(jd, "sales", revoke=["leads"]).status_code == 200            # the edit goes through the process-wide cache and bumps the counter in the database
        try:
            c = connect()
            try:
                assert "leads" not in w2.get(c)["sales"]["perms"] and w2.loads == 2          # the other worker reloaded because the counter moved — no timer, no shared memory
                assert "leads" not in w1.get(c)["sales"]["perms"] and w1.loads == 2
            finally:
                c.close()
        finally:
            assert change(jd, "sales", grant=["leads"]).status_code == 200
    finally:
        TENANT.reset(tok)


def test_a_permission_new_to_the_catalog_is_given_once_to_the_roles_the_code_names_and_what_was_withdrawn_stays_withdrawn(jd):
    assert change(jd, "finance", revoke=["invoices"]).status_code == 200                                          # a manager's deliberate choice
    try:
        known = json.loads(_sql("SELECT v FROM settings WHERE k='roles:known'")[0]["v"])
        assert "masterdata" in known
        # pretend this developer was seeded before `masterdata` existed
        _sql("UPDATE settings SET v=? WHERE k='roles:known'", (json.dumps([p for p in known if p != "masterdata"]),))
        _sql("DELETE FROM role_perms WHERE perm='masterdata'")
        _sql("DELETE FROM settings WHERE k='roles:ver'")
        r = jd.get("/api/roles").json()
        by = {x["code"]: x for x in r["roles"]}
        assert "masterdata" in by["admin"]["perms"] and "masterdata" in by["finance"]["perms"]                  # given back to the roles the code names…
        assert "masterdata" not in by["sales"]["perms"] and "masterdata" not in by["engineer"]["perms"]
        assert "invoices" not in by["finance"]["perms"]                                                        # …and the withdrawn one was not re-granted
        assert "masterdata" in json.loads(_sql("SELECT v FROM settings WHERE k='roles:known'")[0]["v"])
        again = jd.get("/api/roles").json()
        assert {x["code"]: sorted(x["perms"]) for x in again["roles"]} == {x["code"]: sorted(x["perms"]) for x in r["roles"]}      # a second read changes nothing
    finally:
        assert change(jd, "finance", grant=["invoices"]).status_code == 200
    assert set(role(jd, "finance")["perms"]) == set(PERMS["finance"])


def test_a_role_made_by_hand_survives_a_catalog_upgrade_with_exactly_its_permissions(jd):
    code = jd.post("/api/roles", json={"label": "دور يدوي " + tag()}).json()["code"]
    try:
        assert change(jd, code, grant=["view", "book"]).status_code == 200
        _sql("DELETE FROM settings WHERE k='roles:ver'")                                                       # force a re-seed
        assert sorted(role(jd, code)["perms"]) == ["book", "view"]
    finally:
        jd.delete(f"/api/roles/{code}")


# ====================================================================================================== التحقق الثنائي ومستخدمو الأدوار القديمة
def test_two_factor_follows_the_privilege_and_the_five_mandatory_roles_are_unchanged(jd, monkeypatch):
    by = {x["code"]: x for x in jd.get("/api/roles").json()["roles"]}
    assert {k for k, v in by.items() if v["two_fa"]} == set(A.TWO_FA_REQUIRED)                  # the defaults reproduce the old fixed list exactly
    for code in ROLES:                                                                          # …and so does the derived rule, role by role
        assert (code in A.TWO_FA_REQUIRED) == bool(code in A.TWO_FA_REQUIRED or R.SENSITIVE & set(PERMS[code])), code
        assert (code in A.TWO_FA_REQUIRED) == bool(R.SENSITIVE & set(PERMS[code])), code
    assert {"admin", "users", "hr_payroll", "accounting_approve"} <= R.SENSITIVE and not ({"view", "reports", "book", "docs"} & R.SENSITIVE)
    code = jd.post("/api/roles", json={"label": "مسؤول اعتماد " + tag(), "copy_from": "sales"}).json()["code"]
    uname = "rl.f" + tag()
    make_user(jd, uname, code)

    def needs_2fa(cu) -> bool:                                                                  # the rule only bites in production — and only for this read (the admin's own session would be held back too)
        with monkeypatch.context() as m:
            m.setattr(A, "prod", lambda: True)
            return cu.get("/api/me").json()["needs_2fa"]
    try:
        with _client("jadwa", uname) as cu:
            assert role(jd, code)["two_fa"] is False and needs_2fa(cu) is False
            assert change(jd, code, grant=["accounting_approve"]).status_code == 200
            assert role(jd, code)["two_fa"] is True
            assert needs_2fa(cu) is True                                                        # the very next request: a sensitive permission brings its protection
            assert change(jd, code, revoke=["accounting_approve"]).status_code == 200
            assert needs_2fa(cu) is False
        assert change(jd, "payroll", revoke=["hr_payroll"]).status_code == 200
        try:
            assert role(jd, "payroll")["two_fa"] is True                                        # a built-in mandatory role never drops out by losing permissions
        finally:
            assert change(jd, "payroll", grant=["hr_payroll"]).status_code == 200
    finally:
        uid = next(x["id"] for x in jd.get("/api/users").json() if x["username"] == uname)
        jd.post(f"/api/users/{uid}/active", json={"active": False})
        jd.post(f"/api/users/{uid}/role", json={"role": "sales"})
        jd.delete(f"/api/roles/{code}")


def test_user_creation_still_takes_the_old_built_in_roles_and_refuses_portal_and_unknown_ones(jd):
    t = tag()
    for i, r in enumerate(("property_manager", "investor")):                                    # what the old pattern accepted keeps working
        u = make_user(jd, f"rl.{i}{t}", r)
        assert u["role"] == r and u["role_label"] == ROLES[r]
        jd.post(f"/api/users/{u['id']}/active", json={"active": False})
    for bad in ("customer", "broker", "lessee", "employee", "superuser", "custom_999", "ADMIN"):
        r = jd.post("/api/users", json={"username": f"rl.x{t}", "name": "مستخدم بدور مرفوض", "role": bad})
        assert r.status_code == 422, (bad, r.status_code)


def test_the_policy_register_expects_a_custom_role_that_carries_the_policies_permission(jd):
    code = jd.post("/api/roles", json={"label": "قارئ سياسات " + tag()}).json()["code"]
    tok = TENANT.set("jadwa")
    try:
        c = connect()
        try:
            assert code not in R.roles_with(c, "policies")
            assert change(jd, code, grant=["policies"]).status_code == 200
            assert code in R.roles_with(c, "policies") and "employee" in R.roles_with(c, "policies") and "customer" not in R.roles_with(c, "policies")
        finally:
            c.close()
    finally:
        TENANT.reset(tok)
        jd.delete(f"/api/roles/{code}")
