"""0.25.0 — human resources, the core: structure, the employee file (encrypted at rest, opened only by HR and the employee), documents with expiry alerts, leave with a
two-stage approval and balances that cannot drift, holidays and attendance, the employee portal and the manager's team. Every leak path answers 403/404."""
import datetime as dt
import io
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "hr.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "bayan:بيان عمان;almaqsura:المقصورة العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect, init  # noqa: E402

CSRF = "csrf-hr-" + "f" * 30
TODAY = dt.date.today()
HR_TABLES = ("hr_requests", "attendance", "holidays", "leave_requests", "leave_balances", "leave_types", "employee_documents", "employees", "positions", "departments")


def login_as(c, user, tenant="bayan"):
    tok = TENANT.set(tenant)
    try:
        c.cookies.set(A.COOKIE, A.issue_session(user))
    finally:
        TENANT.reset(tok)
    c.cookies.set(A.TENANT_COOKIE, tenant)
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


def _sql(sql, args=(), maint=False):
    tok = TENANT.set("bayan")
    try:
        c = connect()
        try:
            pg = getattr(c, "dialect", "sqlite") == "postgres"
            if maint:
                c.maintenance()
            r = c.execute(sql, args)
            out = r.fetchall() if sql.lstrip().upper().startswith("SELECT") else None
            c.commit()
            if maint:
                c.end_maintenance()
                if not pg:
                    init(c)
            return out
        finally:
            c.close()
    finally:
        TENANT.reset(tok)


def _wipe():
    tok = TENANT.set("bayan")
    try:
        c = connect()
        pg = getattr(c, "dialect", "sqlite") == "postgres"
        sc = " AND org_id = current_setting('app.org_id', true)" if pg else ""
        c.maintenance()
        c.execute(f"UPDATE users SET employee_id=NULL WHERE employee_id IS NOT NULL{sc}")
        c.execute(f"DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'emp%' OR username LIKE 'hrt-%'){sc}")
        c.execute(f"DELETE FROM users WHERE username LIKE 'emp%' OR username LIKE 'hrt-%'{sc}")
        c.execute(c.wipe_sql("departments").replace("DELETE FROM departments", "UPDATE departments SET head_employee_id=NULL"))
        for t in HR_TABLES:
            c.execute(c.wipe_sql(t))
        c.execute(f"DELETE FROM settings WHERE k LIKE 'hr:%'{sc}")
        c.execute(f"DELETE FROM counters WHERE k LIKE 'hr:%'{sc}")
        c.execute(f"DELETE FROM documents WHERE ref_type='employee'{sc}")
        c.execute(f"DELETE FROM notifications WHERE dedupe LIKE 'hrexp:%'{sc}")
        c.commit()
        c.end_maintenance()
        if not pg:
            init(c)
        c.close()
    finally:
        TENANT.reset(tok)


@pytest.fixture()
def cl():
    from backend import observability as O
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        _wipe()
        for t in ("jadwa", "bayan", "almaqsura"):
            tok = TENANT.set(t)
            try:
                d = connect()
                d.execute("DELETE FROM login_attempts")
                d.commit()
                d.close()
            finally:
                TENANT.reset(tok)
        yield c


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    _wipe()


# ----------------------------------------------------------------------------------------------------- helpers
def _sunday(back_days=14):
    """A Sunday at least `back_days` in the past — the weekend is Friday + Saturday, so Sunday → Thursday is five working days."""
    d = TODAY - dt.timedelta(days=back_days)
    while d.weekday() != 6:
        d -= dt.timedelta(days=1)
    return d


def _emp(cl, name="موظف اختبار", **kw):
    login_as(cl, "admin")
    body = {"name": name, "omani": True, "hire_date": (TODAY - dt.timedelta(days=800)).isoformat(), "gender": "male", "email": f"{os.getpid()}{abs(hash(name)) % 99999}@example.test"}
    body.update(kw)
    r = cl.post("/api/hr/employees", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _account(cl, eid):
    login_as(cl, "admin")
    r = cl.post(f"/api/hr/employees/{eid}/account")
    assert r.status_code == 200, r.text
    un = r.json()["username"]
    _sql("UPDATE users SET must_change=0 WHERE username=?", (un,))
    return un


def _hr_user(cl, name="hrt-officer"):
    login_as(cl, "admin")
    r = cl.post("/api/users", json={"username": name, "name": "موظف موارد بشرية للاختبار", "role": "hr"})
    assert r.status_code == 200, r.text
    _sql("UPDATE users SET must_change=0 WHERE username=?", (name,))
    return name


def _leave(cl, key="annual", frm=None, days=5, reason="", **kw):
    frm = frm or _sunday()
    to = frm + dt.timedelta(days=days - 1)
    return cl.post("/api/hr/me/leave", json={"type_key": key, "from_date": frm.isoformat(), "to_date": to.isoformat(), "reason": reason, **kw})


# ----------------------------------------------------------------------------------------------------- structure and the file
def test_structure_and_the_employee_file_with_encrypted_fields_that_only_hr_opens(cl):
    login_as(cl, "admin")
    d = cl.post("/api/hr/departments", json={"name": "الإدارة المالية"}).json()["id"]
    assert cl.post("/api/hr/departments", json={"name": "الإدارة المالية"}).status_code == 409
    sub = cl.post("/api/hr/departments", json={"name": "المحاسبة", "parent_id": d}).json()["id"]
    assert cl.patch(f"/api/hr/departments/{d}", json={"parent_id": sub}).status_code == 409  # a department cannot sit under its own branch
    p = cl.post("/api/hr/positions", json={"title": "محاسب", "department_id": sub, "headcount": 1}).json()["id"]
    assert cl.post("/api/hr/positions", json={"title": "محاسب", "department_id": sub}).status_code == 409

    e1 = cl.post("/api/hr/employees", json={"name": "سالم المحاسب", "omani": True, "hire_date": "2024-01-10", "id_number": "12345678", "dob": "1990-05-01", "iban": "OM810180000001299123456",
                                            "social_ins_no": "SI-778", "emergency_contact": "أخوه 99123456", "department_id": sub, "position_id": p, "gender": "male"})
    assert e1.status_code == 200 and e1.json()["number"] == "EMP-0001" and e1.json()["warnings"] == [], e1.text
    e2 = cl.post("/api/hr/employees", json={"name": "ناصر المحاسب", "omani": False, "nationality": "هندي", "hire_date": "2024-02-01", "department_id": sub, "position_id": p, "manager_id": e1.json()["id"]})
    assert e2.status_code == 200 and e2.json()["number"] == "EMP-0002" and "تجاوز العدد المعتمد" in e2.json()["warnings"][0]
    assert cl.post("/api/hr/employees", json={"name": "مكرر الهوية", "hire_date": "2024-03-01", "id_number": "12345678"}).status_code == 409
    assert cl.post("/api/hr/employees", json={"name": "تعاقد بلا نهاية", "hire_date": "2024-03-01", "contract_type": "fixed"}).status_code == 400
    assert cl.post("/api/hr/employees", json={"name": "حقل غريب", "hire_date": "2024-03-01", "salary": 900}).status_code == 422  # no salary field exists in this phase

    e1id, e2id = e1.json()["id"], e2.json()["id"]
    assert cl.patch(f"/api/hr/employees/{e1id}", json={"manager_id": e2id}).status_code == 409  # the manager line cannot circle back

    raw = _sql("SELECT id_number, dob, iban, social_ins_no, emergency_contact FROM employees WHERE id=?", (e1id,))[0]
    assert all(str(v).startswith("enc:v1:") for v in raw), "identity, birth, bank, insurance and emergency contact are ciphertext at rest"
    lst = cl.get("/api/hr/employees").json()
    assert {x["number"] for x in lst} == {"EMP-0001", "EMP-0002"} and not any(k in lst[0] for k in ("id_number", "iban", "dob", "social_ins_no", "emergency_contact"))
    det = cl.get(f"/api/hr/employees/{e1id}").json()
    assert (det["id_number"], det["iban"], det["dob"]) == ("12345678", "OM810180000001299123456", "1990-05-01")
    assert any(r["action"] == "فتح ملف موظف" and "EMP-0001" in r["detail"] for r in _sql("SELECT action, detail FROM audit ORDER BY id DESC LIMIT 5"))
    same = cl.patch(f"/api/hr/employees/{e1id}", json={"id_number": "12345678", "iban": "OM810180000001299123456"})
    assert same.status_code == 200 and same.json()["changed"] == [], "writing the same sensitive value is not a change"
    ch = cl.patch(f"/api/hr/employees/{e1id}", json={"phone": "99000111", "iban": "OM000000000000000000001"})
    assert sorted(ch.json()["changed"]) == ["iban", "phone"]
    detail = [r["detail"] for r in _sql("SELECT detail FROM audit WHERE action='تعديل ملف موظف' ORDER BY id DESC LIMIT 1")][0]
    assert "iban" in detail and "OM0000" not in detail, "the audit line names the field, never its value"
    s = cl.get("/api/hr/summary").json()
    assert s["headcount"] == 2 and s["omani"] == 1 and s["omani_pct"] == 50.0
    tree = cl.get("/api/hr/tree").json()
    assert tree["departments"][0]["children"][0]["name"] == "المحاسبة" and len(tree["departments"][0]["children"][0]["people"]) == 2


def test_only_the_people_roles_open_the_hr_screens(cl):
    e = _emp(cl)
    for who in ("sales", "finance", "engineer", "investor1"):
        login_as(cl, who)
        assert cl.get("/api/hr/employees").status_code == 403, who
        assert cl.get(f"/api/hr/employees/{e}").status_code == 403, who
        assert cl.get("/api/hr/me").status_code == 403, who
    login_as(cl, "almaqsura", "almaqsura") if False else None
    login_as(cl, "admin", "almaqsura")
    assert cl.get("/api/hr/employees").status_code == 404  # the leasing-only bundle has no HR module: the path answers like an unknown one
    me = login_as(cl, "admin").get("/api/me").json()
    assert "hr" in me["modules"] and {"hr", "hr_payroll"} <= set(me["perms"])


def test_an_hr_officer_manages_people_but_has_no_payroll_permission_and_needs_two_factor_in_production(cl):
    name = _hr_user(cl)
    login_as(cl, name)
    me = cl.get("/api/me").json()
    assert "hr" in me["perms"] and "hr_payroll" not in me["perms"] and me["role"] == "hr"
    assert cl.post("/api/hr/employees", json={"name": "بواسطة الموارد", "omani": True, "hire_date": "2025-01-01"}).status_code == 200
    assert A.TWO_FA_REQUIRED >= {"hr"}
    # the generic documents permission does not open an employee's scans
    login_as(cl, "finance")
    assert cl.get("/api/documents", params={"ref_type": "employee", "ref_id": 1}).status_code == 403


# ----------------------------------------------------------------------------------------------------- the login of an employee
def test_an_employee_account_is_created_once_sees_only_his_own_file_and_is_closed_by_termination(cl):
    e1, e2 = _emp(cl, "الموظف الأول", phone="91111111", id_number="111"), _emp(cl, "الموظف الثاني", id_number="222")
    u1 = _account(cl, e1)
    _account(cl, e2)
    assert cl.post(f"/api/hr/employees/{e1}/account").status_code == 409  # one login per file
    login_as(cl, u1)
    me = cl.get("/api/me").json()
    assert me["role"] == "employee" and me["employee_id"] == e1 and set(me["perms"]) == {"hr_self", "hr_manager", "policies"}
    mine = cl.get("/api/hr/me").json()
    assert mine["number"] == "EMP-0001" and mine["id_number"] == "111" and "created_by" not in mine
    # nothing of the colleague, and none of the HR screens
    assert cl.get(f"/api/hr/employees/{e2}").status_code == 403
    assert cl.get("/api/hr/employees").status_code == 403 and cl.get("/api/hr/summary").status_code == 403 and cl.get("/api/hr/alerts").status_code == 403
    assert cl.get("/api/hr/leave/requests").status_code == 403 and cl.get("/api/hr/requests").status_code == 403
    assert cl.post("/api/hr/employees", json={"name": "x", "hire_date": "2024-01-01"}).status_code == 403
    assert cl.get("/api/acc/status").status_code == 403 and cl.get("/api/lea/scopes").status_code == 403
    # contact details are his to change; identity and bank are not
    assert cl.patch("/api/hr/me", json={"phone": "92222222"}).json()["changed"] == ["phone"]
    assert cl.patch("/api/hr/me", json={"iban": "OM1"}).status_code == 422
    # termination closes the login
    login_as(cl, "admin")
    assert cl.post(f"/api/hr/employees/{e1}/status", json={"status": "terminated", "date": TODAY.isoformat()}).status_code == 400  # a reason is mandatory
    assert cl.post(f"/api/hr/employees/{e1}/status", json={"status": "terminated", "date": TODAY.isoformat(), "note": "استقالة"}).status_code == 200
    assert _sql("SELECT active FROM users WHERE username=?", (u1,))[0]["active"] == 0
    assert cl.patch(f"/api/hr/employees/{e1}", json={"phone": "1"}).status_code == 409
    assert cl.post(f"/api/hr/employees/{e1}/status", json={"status": "active"}).status_code == 409  # terminated is final: a new file for a re-hire
    reset = cl.post(f"/api/hr/employees/{e2}/account/reset").json()
    assert reset["temporary_password"] and reset["username"].startswith("emp")


# ----------------------------------------------------------------------------------------------------- documents and expiry
def test_documents_alert_at_ninety_and_thirty_days_and_a_replaced_document_stops_alerting(cl):
    e = _emp(cl, "صاحب الوثائق", contract_type="fixed", contract_end=(TODAY + dt.timedelta(days=60)).isoformat())
    assert cl.post(f"/api/hr/employees/{e}/documents", json={"kind": "passport"}).status_code == 400  # a passport needs an expiry
    old = cl.post(f"/api/hr/employees/{e}/documents", json={"kind": "passport", "number": "P1234567", "expires": (TODAY - dt.timedelta(days=5)).isoformat()}).json()["id"]
    cl.post(f"/api/hr/employees/{e}/documents", json={"kind": "resident_card", "number": "RC-1", "expires": (TODAY + dt.timedelta(days=20)).isoformat()})
    cl.post(f"/api/hr/employees/{e}/documents", json={"kind": "health_insurance", "expires": (TODAY + dt.timedelta(days=80)).isoformat()})
    cl.post(f"/api/hr/employees/{e}/documents", json={"kind": "work_permit", "expires": (TODAY + dt.timedelta(days=200)).isoformat()})
    raw = _sql("SELECT number FROM employee_documents WHERE kind='passport'")[0]["number"]
    assert str(raw).startswith("enc:v1:")
    al = {a["label"]: a for a in cl.get("/api/hr/alerts").json()}
    assert al["جواز السفر"]["level"] == "expired" and al["البطاقة المدنية / الإقامة"]["level"] == "critical" and al["التأمين الصحي"]["level"] == "soon"
    assert al["نهاية العقد"]["level"] == "soon" and "تصريح العمل" not in al
    first = cl.post(f"/api/hr/employees/{e}/documents", json={"kind": "passport", "number": "P7654321", "expires": (TODAY + dt.timedelta(days=3000)).isoformat()})
    assert first.status_code == 200
    assert "جواز السفر" not in {a["label"] for a in cl.get("/api/hr/alerts").json()}, "the renewed passport replaces the old one"
    # the daily job queues each crossing once
    from backend import hr
    tok = TENANT.set("bayan")
    try:
        c = connect()
        n1 = hr.alerts_run(c)
        c.commit()
        n2 = hr.alerts_run(c)
        c.commit()
        c.close()
    finally:
        TENANT.reset(tok)
    assert n1 == 3 and n2 == 0, (n1, n2)
    assert cl.delete(f"/api/hr/documents/{old}").status_code == 200
    # the scan must belong to the same employee
    assert cl.post(f"/api/hr/employees/{e}/documents", json={"kind": "contract", "document_id": 999999}).status_code == 400


# ----------------------------------------------------------------------------------------------------- leave
def test_leave_balance_workflow_and_the_days_come_back_on_cancellation(cl):
    boss = _emp(cl, "المدير المباشر")
    worker = _emp(cl, "الموظف العامل", manager_id=boss)
    ub, uw = _account(cl, boss), _account(cl, worker)
    sun = _sunday()
    login_as(cl, "admin")
    # a mid-week holiday takes a day out of the count: Sunday → Thursday is 5 working days, minus the holiday = 4
    assert cl.post("/api/hr/holidays", json={"day": (sun + dt.timedelta(days=2)).isoformat(), "name": "عطلة اختبار"}).status_code == 200
    assert cl.post("/api/hr/holidays", json={"day": (sun + dt.timedelta(days=2)).isoformat(), "name": "مكررة"}).status_code == 409
    types = {t["key"]: t for t in cl.get("/api/hr/leave/types").json()}
    assert types["annual"]["provisional"] == 1 and "مختص" in types["annual"]["note"], "the platform's figures are marked provisional until someone confirms them"

    login_as(cl, uw)
    before = {b["type_key"]: b for b in cl.get("/api/hr/me").json()["balances"]}["annual"]
    assert before["taken"] == 0 and before["entitled"] > 0
    r = _leave(cl, "annual", sun, 5)  # Sun..Thu
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    mine = cl.get("/api/hr/me/leave").json()[0]
    assert mine["days"] == 4 and mine["status"] == "pending" and mine["stage"] == "manager"
    assert _leave(cl, "annual", sun + dt.timedelta(days=1), 2).status_code == 409  # overlaps the pending request
    bal = {b["type_key"]: b for b in cl.get("/api/hr/me").json()["balances"]}["annual"]
    assert bal["taken"] == 0 and bal["available"] == before["remaining"] - 4, "pending days are reserved but not yet taken"
    # nobody decides his own request; a colleague outside the line cannot see it
    other = _emp(cl, "زميل خارج السلسلة")
    uo = _account(cl, other)
    login_as(cl, uo)
    assert cl.post(f"/api/hr/leave/requests/{rid}/decide", json={"action": "approve"}).status_code == 404
    assert cl.post(f"/api/hr/leave/requests/{rid}/cancel", json={}).status_code == 404
    login_as(cl, uw)
    assert cl.post(f"/api/hr/leave/requests/{rid}/decide", json={"action": "approve"}).status_code == 403
    # the manager sees the request in his team list and approves it: balance goes down, the attendance sheet shows the days as leave
    login_as(cl, ub)
    team = cl.get("/api/hr/team/leave", params={"status": "pending"}).json()
    assert [t["id"] for t in team] == [rid]
    assert cl.post(f"/api/hr/leave/requests/{rid}/decide", json={"action": "reject"}).status_code == 400  # a reason is required
    ok = cl.post(f"/api/hr/leave/requests/{rid}/decide", json={"action": "approve"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved", ok.text
    login_as(cl, uw)
    after = {b["type_key"]: b for b in cl.get("/api/hr/me").json()["balances"]}["annual"]
    assert after["taken"] == 4 and after["remaining"] == before["remaining"] - 4
    marks = _sql("SELECT day, status, source FROM attendance WHERE employee_id=? ORDER BY day", (worker,))
    assert len(marks) == 4 and all(m["status"] == "leave" and m["source"] == "leave" for m in marks)
    # started leave: the employee cannot cancel it himself; HR can, with a reason, and the days return
    assert cl.post(f"/api/hr/leave/requests/{rid}/cancel", json={}).status_code == 409
    login_as(cl, "admin")
    assert cl.post(f"/api/hr/leave/requests/{rid}/cancel", json={}).status_code == 400
    assert cl.post(f"/api/hr/leave/requests/{rid}/cancel", json={"reason": "عودة مبكرة"}).status_code == 200
    login_as(cl, uw)
    back = {b["type_key"]: b for b in cl.get("/api/hr/me").json()["balances"]}["annual"]
    assert back["taken"] == 0 and back["remaining"] == before["remaining"]
    assert _sql("SELECT COUNT(*) n FROM attendance WHERE employee_id=?", (worker,))[0]["n"] == 0


def test_special_types_need_hr_after_the_manager_and_one_off_types_are_given_once(cl):
    boss = _emp(cl, "رئيس القسم")
    worker = _emp(cl, "طالب الحج", manager_id=boss, gender="male")
    ub, uw = _account(cl, boss), _account(cl, worker)
    login_as(cl, uw)
    sun = _sunday()
    assert _leave(cl, "maternity", sun, 10).status_code == 409  # female-only
    rid = _leave(cl, "hajj", sun, 5).json()["id"]
    login_as(cl, ub)
    r = cl.post(f"/api/hr/leave/requests/{rid}/decide", json={"action": "approve"})
    assert r.json() == {"status": "pending", "stage": "hr"}
    # the manager cannot finish it and a hajj leave needs its proof before HR can approve
    assert cl.post(f"/api/hr/leave/requests/{rid}/decide", json={"action": "approve"}).status_code == 403
    login_as(cl, "admin")
    assert cl.post(f"/api/hr/leave/requests/{rid}/decide", json={"action": "approve"}).status_code == 409  # needs an attachment
    up = cl.post(f"/api/hr/leave/requests/{rid}/attachment", files={"file": ("p.pdf", io.BytesIO(b"%PDF-1.4 proof"), "application/pdf")})
    assert up.status_code == 200, up.text
    assert cl.post(f"/api/hr/leave/requests/{rid}/decide", json={"action": "approve"}).json()["status"] == "approved"
    login_as(cl, uw)
    assert _leave(cl, "hajj", sun + dt.timedelta(days=30), 3).status_code == 409  # once in the whole service


def test_hr_leave_for_an_employee_cannot_be_approved_by_the_same_person_for_his_own_file(cl):
    hr_name = _hr_user(cl)
    me = _emp(cl, "موظف الموارد")
    login_as(cl, "admin")
    assert cl.post(f"/api/hr/employees/{me}/link-user", json={"user_id": _sql("SELECT id FROM users WHERE username=?", (hr_name,))[0]["id"]}).status_code == 200
    login_as(cl, hr_name)
    assert cl.get("/api/me").json()["employee_id"] == me
    rid = _leave(cl, "annual", _sunday(), 2).json()["id"]
    assert cl.post(f"/api/hr/leave/requests/{rid}/decide", json={"action": "approve"}).status_code == 403  # his own request
    login_as(cl, "admin")  # another person can
    assert cl.post(f"/api/hr/leave/requests/{rid}/decide", json={"action": "approve"}).status_code == 200


def test_the_balance_cannot_be_overdrawn_and_adjustments_need_a_note_and_a_different_person(cl):
    e = _emp(cl, "رصيد محدود")
    u = _account(cl, e)
    login_as(cl, "admin")
    assert cl.post("/api/hr/leave/adjust", json={"employee_id": e, "type_key": "annual", "year": _sunday().year, "delta": -9999, "note": "x" * 5}).status_code == 422
    ent = {b["type_key"]: b for b in cl.get(f"/api/hr/employees/{e}/leave-balances", params={"year": _sunday().year}).json()}["annual"]["remaining"]
    cl.post("/api/hr/leave/adjust", json={"employee_id": e, "type_key": "annual", "year": _sunday().year, "delta": -(ent - 2), "note": "رصيد افتتاحي من النظام السابق"})
    login_as(cl, u)
    assert _leave(cl, "annual", _sunday(), 5).status_code == 409  # 4 working days wanted, 2 left
    ok = _leave(cl, "annual", _sunday(), 3)  # Sun..Tue = 3 working days, but only 2 are left unless a holiday intervenes
    assert ok.status_code == 409 and "الرصيد المتاح" in ok.text
    assert _leave(cl, "annual", _sunday(), 2).status_code == 200
    login_as(cl, "admin")
    over = cl.post("/api/hr/leave/adjust", json={"employee_id": e, "type_key": "annual", "year": _sunday().year, "delta": -50, "note": "تعديل كبير"})
    assert over.status_code == 409 and "سالبًا" in over.text


def test_leave_types_are_versions_with_an_effective_date_and_only_gender_and_service_rules_apply(cl):
    e = _emp(cl, "موظف جديد", hire_date=(TODAY - dt.timedelta(days=40)).isoformat())
    u = _account(cl, e)
    login_as(cl, "admin")
    new = cl.post("/api/hr/leave/types", json={"key": "annual", "name": "الإجازة السنوية", "days_per_year": 24, "accrual": "monthly", "valid_from": "2030-01-01", "min_service_months": 6})
    assert new.status_code == 200
    assert cl.post("/api/hr/leave/types", json={"key": "annual", "name": "نسخة مكررة", "days_per_year": 1, "valid_from": "2030-01-01"}).status_code == 409
    versions = [t for t in cl.get("/api/hr/leave/types").json() if t["key"] == "annual"]
    assert [v["valid_from"] for v in versions] == ["2030-01-01", "2000-01-01"] and versions[1]["current"] and not versions[0]["current"] and versions[0]["provisional"] == 0
    tid = next(t["id"] for t in cl.get("/api/hr/leave/types").json() if t["key"] == "sick" and t["current"])
    assert cl.post(f"/api/hr/leave/types/{tid}/confirm").status_code == 200
    assert next(t for t in cl.get("/api/hr/leave/types").json() if t["key"] == "sick")["provisional"] == 0
    login_as(cl, u)
    types = {t["key"] for t in cl.get("/api/hr/me/leave-types").json()}
    assert "annual" in types and "maternity" not in types and "paternity" in types  # a man sees paternity, not maternity


# ----------------------------------------------------------------------------------------------------- attendance
def test_attendance_manual_and_imported_never_overwrite_leave_or_hand_marked_days(cl):
    e = _emp(cl, "الحضور")
    login_as(cl, "admin")
    sun = _sunday(21)
    d1, d2, d3 = sun, sun + dt.timedelta(days=1), sun + dt.timedelta(days=2)
    assert cl.post("/api/hr/attendance", json={"employee_id": e, "day": d1.isoformat(), "check_in": "08:05", "check_out": "15:00"}).json()["status"] == "present"
    assert cl.post("/api/hr/attendance", json={"employee_id": e, "day": d2.isoformat(), "check_in": "08:40"}).json()["status"] == "late"
    assert cl.post("/api/hr/attendance", json={"employee_id": e, "day": (TODAY + dt.timedelta(days=2)).isoformat(), "status": "present"}).status_code == 400
    assert cl.post("/api/hr/attendance", json={"employee_id": e, "day": d1.isoformat(), "check_in": "9:00", "check_out": "8:00"}).status_code == 400
    # approved leave on d3 owns that day
    rid = cl.post("/api/hr/leave/requests", json={"employee_id": e, "type_key": "bereavement", "from_date": d3.isoformat(), "to_date": d3.isoformat(), "approve": True})
    assert rid.status_code == 200 and rid.json()["status"] == "approved", rid.text
    assert cl.post("/api/hr/attendance", json={"employee_id": e, "day": d3.isoformat(), "status": "present"}).status_code == 409
    csv = ("رقم الموظف,التاريخ,الدخول,الخروج,الحالة\n"
           f"EMP-0001,{d1},08:00,15:00,\n"       # hand-marked → skipped
           f"EMP-0001,{d3},08:00,15:00,\n"       # leave → skipped
           f"EMP-0001,{sun + dt.timedelta(days=3)},08:10,15:00,\n"  # new
           "EMP-9999,2024-01-01,08:00,15:00,\n"  # unknown employee
           f"EMP-0001,{sun + dt.timedelta(days=4)},,,\n")        # nothing to record
    dry = cl.post("/api/hr/attendance/import?dry=true", files={"file": ("a.csv", io.BytesIO(csv.encode("utf-8-sig")), "text/csv")}).json()
    assert dry["dry"] and (dry["new"], dry["skipped_manual"], dry["error_count"]) == (1, 2, 2)
    assert _sql("SELECT COUNT(*) n FROM attendance WHERE source='import'")[0]["n"] == 0, "a dry run writes nothing"
    real = cl.post("/api/hr/attendance/import", files={"file": ("a.csv", io.BytesIO(csv.encode("utf-8-sig")), "text/csv")}).json()
    again = cl.post("/api/hr/attendance/import", files={"file": ("a.csv", io.BytesIO(csv.encode("utf-8-sig")), "text/csv")}).json()
    assert real["new"] == 1 and again["new"] == 0 and again["duplicate"] == 1
    month = sun.strftime("%Y-%m")
    m = {r["number"]: r for r in cl.get("/api/hr/attendance/month", params={"month": month}).json()}["EMP-0001"]
    assert m["present"] + m["late"] >= 2 and m["leave"] == 1
    day = cl.get("/api/hr/attendance", params={"day": d1.isoformat()}).json()
    assert day[0]["status"] == "present"
    assert cl.put("/api/hr/settings", json={"weekend": [4, 5], "work_start": "07:30", "late_grace": 5}).status_code == 200
    assert cl.get("/api/hr/settings").json() == {"weekend": [4, 5], "work_start": "07:30", "late_grace": 5}


# ----------------------------------------------------------------------------------------------------- the manager's team and the employee's other requests
def test_a_manager_sees_only_his_own_reports_and_no_identity_numbers(cl):
    boss = _emp(cl, "مدير الفريق")
    mine = _emp(cl, "مرؤوس مباشر", manager_id=boss, id_number="9876")
    stranger = _emp(cl, "ليس من فريقه", id_number="5555")
    ub = _account(cl, boss)
    login_as(cl, ub)
    team = cl.get("/api/hr/team").json()
    assert [t["id"] for t in team] == [mine] and "id_number" not in team[0] and "iban" not in team[0]
    card = cl.get(f"/api/hr/team/{mine}").json()
    assert card["name"] == "مرؤوس مباشر" and "id_number" not in card
    assert cl.get(f"/api/hr/team/{stranger}").status_code == 404
    assert cl.get(f"/api/hr/employees/{mine}").status_code == 403  # the HR file is not his
    login_as(cl, _account(cl, stranger))
    assert cl.get("/api/hr/team").json() == [] and cl.get(f"/api/hr/team/{mine}").status_code == 404


def test_requests_for_a_letter_or_an_advance_are_decided_by_hr_but_never_by_the_requester(cl):
    e = _emp(cl, "طالب الخطاب")
    u = _account(cl, e)
    login_as(cl, u)
    assert cl.post("/api/hr/me/requests", json={"kind": "advance", "details": "سلفة طارئة"}).status_code == 400  # an amount is required
    assert cl.post("/api/hr/me/requests", json={"kind": "letter", "details": "خطاب تعريف", "amount": 5}).status_code == 400
    q = cl.post("/api/hr/me/requests", json={"kind": "advance", "details": "سلفة طارئة", "amount": 150}).json()["id"]
    assert cl.get("/api/hr/me/requests").json()[0]["status"] == "pending"
    assert cl.post(f"/api/hr/requests/{q}/decide", json={"status": "approved"}).status_code == 403
    login_as(cl, "admin")
    assert cl.post(f"/api/hr/requests/{q}/decide", json={"status": "rejected"}).status_code == 400
    assert cl.post(f"/api/hr/requests/{q}/decide", json={"status": "approved", "note": "تُحوَّل إلى قرض حسن عند تشغيل الرواتب"}).status_code == 200
    assert cl.get("/api/hr/requests", params={"status": "approved"}).json()[0]["amount"] == 150


def test_scans_of_one_employee_are_not_served_to_another(cl):
    a, b = _emp(cl, "صاحب الملف"), _emp(cl, "زميله")
    login_as(cl, "admin")
    up = cl.post("/api/documents", data={"ref_type": "employee", "ref_id": str(a), "title": "جواز", "category": "هوية"}, files={"file": ("p.pdf", io.BytesIO(b"%PDF-1.4 passport"), "application/pdf")})
    assert up.status_code == 200, up.text
    did = up.json()["id"]
    dd = cl.post(f"/api/hr/employees/{a}/documents", json={"kind": "passport", "expires": (TODAY + dt.timedelta(days=900)).isoformat(), "document_id": did}).json()["id"]
    assert cl.post(f"/api/hr/employees/{b}/documents", json={"kind": "passport", "expires": (TODAY + dt.timedelta(days=900)).isoformat(), "document_id": did}).status_code == 400
    ua, ub_ = _account(cl, a), _account(cl, b)
    login_as(cl, ua)
    assert cl.get(f"/api/hr/me/documents/{dd}/file").status_code == 200
    assert cl.get(f"/api/documents/{did}").status_code == 403  # the generic route stays closed to the employee role
    login_as(cl, ub_)
    assert cl.get(f"/api/hr/me/documents/{dd}/file").status_code == 404
