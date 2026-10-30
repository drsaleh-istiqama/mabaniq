"""0.27.0 — the rest of the employee's life: recruitment with erasure of candidates who were not hired, the annual appraisal with its confidentiality, training with certificate
expiry, and discipline that cannot exist without an approved bylaw. Every leak path answers 403/404."""
import datetime as dt
import io
import os
import tempfile

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "hrlife.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "bayan:بيان عمان;almaqsura:المقصورة العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect, init  # noqa: E402

CSRF = "csrf-life-" + "f" * 30
TODAY = dt.date.today()
PS = (TODAY.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
PERIOD = PS.strftime("%Y-%m")
HR_TABLES = ("disciplinary_cases", "penalty_rules", "training_records", "training_courses", "appraisals", "appraisal_cycles", "interviews", "candidates", "job_openings", "terminations", "eosb_rules",
             "loan_installments", "employee_loans", "payroll_adjustments", "payslips", "payroll_runs", "salary_lines", "salary_structures", "pay_components", "hr_rates", "hr_requests", "attendance",
             "holidays", "leave_requests", "leave_balances", "leave_types", "employee_documents", "employees", "positions", "departments")


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


def _sql(sql, args=()):
    tok = TENANT.set("bayan")
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
        c.execute(f"DELETE FROM documents WHERE ref_type IN ('employee','candidate'){sc}")
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
def _user(cl, name, role):
    login_as(cl, "admin")
    if _sql("SELECT 1 FROM users WHERE username=?", (name,)):
        return name
    r = cl.post("/api/users", json={"username": name, "name": f"مستخدم {name}", "role": role})
    assert r.status_code == 200, r.text
    _sql("UPDATE users SET must_change=0 WHERE username=?", (name,))
    return name


def _emp(cl, name, hire=None, **kw):
    login_as(cl, "admin")
    body = {"name": name, "omani": True, "hire_date": hire or (TODAY - dt.timedelta(days=500)).isoformat(), "gender": "male", **kw}
    r = cl.post("/api/hr/employees", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _acct(cl, eid):
    login_as(cl, "admin")
    un = cl.post(f"/api/hr/employees/{eid}/account").json()["username"]
    _sql("UPDATE users SET must_change=0 WHERE username=?", (un,))
    return un


# ----------------------------------------------------------------------------------------------------- recruitment
def test_recruitment_flows_to_a_hire_and_the_cv_moves_into_the_employee_file(cl):
    login_as(cl, "admin")
    dept = cl.post("/api/hr/departments", json={"name": "المشتريات"}).json()["id"]
    pos = cl.post("/api/hr/positions", json={"title": "مسؤول مشتريات", "department_id": dept}).json()["id"]
    oid = cl.post("/api/hr/recruitment/openings", json={"title": "مسؤول مشتريات", "department_id": dept, "position_id": pos, "headcount": 1}).json()["id"]
    assert cl.post("/api/hr/recruitment/candidates", json={"opening_id": oid, "name": "مرشح مبكر"}).status_code == 409  # not open yet
    assert cl.post(f"/api/hr/recruitment/openings/{oid}/status", json={"status": "open"}).status_code == 200
    cid = cl.post("/api/hr/recruitment/candidates", json={"opening_id": oid, "name": "علي بن حمد", "phone": "99001122", "email": "ali@example.test"}).json()["id"]
    assert cl.post("/api/hr/recruitment/candidates", json={"opening_id": oid, "name": "علي مكرر", "email": "ALI@example.test"}).status_code == 409
    up = cl.post(f"/api/hr/recruitment/candidates/{cid}/cv", files={"file": ("cv.pdf", io.BytesIO(b"%PDF-1.4 cv"), "application/pdf")})
    assert up.status_code == 200, up.text
    did = up.json()["document_id"]
    login_as(cl, "finance")
    assert cl.get(f"/api/documents/{did}").status_code == 403 and cl.get("/api/hr/recruitment/candidates").status_code == 403  # the CV is not for the generic documents permission
    login_as(cl, "admin")
    assert cl.post(f"/api/hr/recruitment/candidates/{cid}/stage", json={"stage": "offer"}).status_code == 409  # cannot skip the stages
    assert cl.post(f"/api/hr/recruitment/candidates/{cid}/stage", json={"stage": "screening"}).status_code == 200
    assert cl.post(f"/api/hr/recruitment/candidates/{cid}/interviews", json={"scheduled_at": f"{TODAY} 10:00", "kind": "in_person", "interviewer": "المدير"}).status_code == 200
    assert cl.get(f"/api/hr/recruitment/candidates/{cid}").json()["stage"] == "interview"
    assert cl.post(f"/api/hr/recruitment/candidates/{cid}/stage", json={"stage": "offer"}).status_code == 409  # no interview done yet
    iid = cl.get(f"/api/hr/recruitment/candidates/{cid}").json()["interviews"][0]["id"]
    assert cl.post(f"/api/hr/recruitment/interviews/{iid}/result", json={"score": 4, "notes": "جيد"}).status_code == 200
    assert cl.post(f"/api/hr/recruitment/candidates/{cid}/stage", json={"stage": "offer"}).status_code == 200
    h = cl.post(f"/api/hr/recruitment/candidates/{cid}/hire", json={"hire_date": TODAY.isoformat(), "omani": True, "gender": "male"})
    assert h.status_code == 200 and h.json()["opening_filled"] is True, h.text
    emp = cl.get(f"/api/hr/employees/{h.json()['id']}").json()
    assert emp["name"] == "علي بن حمد" and emp["department"] == "المشتريات" and emp["position"] == "مسؤول مشتريات"
    assert _sql("SELECT ref_type FROM documents WHERE id=?", (did,))[0]["ref_type"] == "employee", "the CV moved into the employee file"
    cd = cl.get(f"/api/hr/recruitment/candidates/{cid}").json()
    assert cd["stage"] == "hired" and cd["phone"] is None and cd["email"] is None and cd["cv_document_id"] is None
    assert cl.get("/api/hr/recruitment/openings").json()[0]["status"] == "filled"


def test_a_candidate_who_was_not_hired_is_erased_after_the_retention_period(cl):
    login_as(cl, "admin")
    oid = cl.post("/api/hr/recruitment/openings", json={"title": "وظيفة اختبار المحو"}).json()["id"]
    cl.post(f"/api/hr/recruitment/openings/{oid}/status", json={"status": "open"})
    a = cl.post("/api/hr/recruitment/candidates", json={"opening_id": oid, "name": "مرفوض قديم", "phone": "91", "email": "old@example.test", "notes": "ملاحظات خاصة"}).json()["id"]
    b = cl.post("/api/hr/recruitment/candidates", json={"opening_id": oid, "name": "مرفوض حديث", "phone": "92"}).json()["id"]
    up = cl.post(f"/api/hr/recruitment/candidates/{a}/cv", files={"file": ("cv.pdf", io.BytesIO(b"%PDF-1.4 old"), "application/pdf")}).json()["document_id"]
    assert cl.post(f"/api/hr/recruitment/candidates/{a}/stage", json={"stage": "rejected"}).status_code == 400  # a reason is mandatory
    for x in (a, b):
        assert cl.post(f"/api/hr/recruitment/candidates/{x}/stage", json={"stage": "rejected", "reason": "لا تناسب المتطلبات"}).status_code == 200
    old = (dt.datetime.now() - dt.timedelta(days=200)).isoformat(timespec="seconds")
    _sql("UPDATE candidates SET stage_at=? WHERE id=?", (old, a))
    assert cl.post("/api/hr/recruitment/purge", json={"days": 10}).status_code == 422  # never below 30 days
    assert cl.post("/api/hr/recruitment/purge", json={"days": 180}).json() == {"erased": 1}
    x, y = cl.get(f"/api/hr/recruitment/candidates/{a}").json(), cl.get(f"/api/hr/recruitment/candidates/{b}").json()
    assert x["anonymized"] == 1 and x["phone"] is None and x["email"] is None and x["notes"] is None and "محذوف" in x["name"] and x["cv_document_id"] is None
    assert not _sql("SELECT 1 FROM documents WHERE id=?", (up,)), "the CV file record is gone too"
    assert y["anonymized"] == 0 and y["name"] == "مرفوض حديث", "a recent rejection is kept"
    assert cl.post("/api/hr/recruitment/purge", json={"days": 180}).json() == {"erased": 0}


# ----------------------------------------------------------------------------------------------------- appraisals
def _cycle(cl):
    login_as(cl, "admin")
    cid = cl.post("/api/hr/appraisal-cycles", json={"name": f"تقييم {TODAY.year}", "year": TODAY.year, "start_date": f"{TODAY.year}-01-01", "end_date": TODAY.isoformat()}).json()["id"]
    return cid


def test_the_appraisal_runs_self_manager_hr_and_the_employee_sees_the_manager_only_after_it_is_final(cl):
    boss = _emp(cl, "مدير التقييم")
    worker = _emp(cl, "الموظف المُقيَّم", manager_id=boss)
    newbie = _emp(cl, "حديث التعيين", hire=(TODAY - dt.timedelta(days=20)).isoformat())
    ub, uw = _acct(cl, boss), _acct(cl, worker)
    cid = _cycle(cl)
    assert cl.post(f"/api/hr/appraisal-cycles/{cid}/open").json() == {"added": 2}, "a person with under 90 days of service is not appraised"
    assert cl.post(f"/api/hr/appraisal-cycles/{cid}/open").json() == {"added": 0}
    assert newbie
    login_as(cl, uw)
    ap = cl.get("/api/hr/me/appraisals").json()[0]
    aid = ap["id"]
    goals = [{"title": "تسليم التقارير في موعدها", "weight": 60, "self_score": 4}, {"title": "خفض الأخطاء", "weight": 40, "self_score": 3}]
    comps = [{"name": k["name"], "self_score": 4} for k in ap["competencies"]]
    bad = cl.put(f"/api/hr/me/appraisals/{aid}/self", json={"goals": [{**goals[0], "weight": 50}, goals[1]], "competencies": comps, "submit": True})
    assert bad.status_code == 400 and "100" in bad.text  # weights must total 100
    assert cl.put(f"/api/hr/me/appraisals/{aid}/self", json={"goals": goals, "competencies": comps, "self_comment": "عام جيد", "submit": False}).json()["status"] == "self"
    assert cl.put(f"/api/hr/me/appraisals/{aid}/self", json={"goals": goals, "competencies": comps, "self_comment": "عام جيد", "submit": True}).json()["status"] == "manager"
    assert cl.put(f"/api/hr/me/appraisals/{aid}/self", json={"goals": goals, "competencies": comps, "submit": True}).status_code == 409  # sent: no more edits
    # the manager reviews; nobody else (even a colleague with the manager permission) can
    other = _acct(cl, _emp(cl, "زميل خارج الخط"))
    login_as(cl, other)
    assert cl.put(f"/api/hr/team/appraisals/{aid}/review", json={"goal_scores": [5, 3], "competency_scores": [4] * 5, "submit": True}).status_code == 404
    login_as(cl, ub)
    team = cl.get("/api/hr/team-appraisals").json()
    assert [t["id"] for t in team] == [aid] and team[0]["goals"][0]["self_score"] == 4
    short = cl.put(f"/api/hr/team/appraisals/{aid}/review", json={"goal_scores": [5], "competency_scores": [4] * 5, "submit": True})
    assert short.status_code == 400
    ok = cl.put(f"/api/hr/team/appraisals/{aid}/review", json={"goal_scores": [5, 3], "competency_scores": [4] * 5, "manager_comment": "أداء قوي ومنتظم", "submit": True})
    assert ok.json()["status"] == "hr", ok.text
    # confidentiality: before HR finalises the employee sees none of the manager's opinion
    login_as(cl, uw)
    mine = cl.get("/api/hr/me/appraisals").json()[0]
    assert mine["manager_comment"] is None and mine["overall"] is None and all("mgr_score" not in g for g in mine["goals"])
    assert cl.post(f"/api/hr/me/appraisals/{aid}/ack", json={}).status_code == 409
    login_as(cl, "admin")
    row = cl.get(f"/api/hr/appraisals/{aid}").json()
    assert row["overall"] == 4.14 and row["rating"] == "يتجاوز التوقعات", "0.7 × (60×5+40×3)/100 + 0.3 × 4"
    assert cl.post(f"/api/hr/appraisals/{aid}/finalize", json={"decision": "raise", "hr_comment": "يُدرس في ميزانية العام القادم"}).json()["status"] == "final"
    login_as(cl, uw)
    final = cl.get("/api/hr/me/appraisals").json()[0]
    assert final["overall"] == 4.14 and final["decision"] == "raise" and final["manager_comment"] == "أداء قوي ومنتظم"
    assert cl.post(f"/api/hr/me/appraisals/{aid}/ack", json={"comment": "شكرًا"}).json()["status"] == "ack"
    login_as(cl, "admin")
    closed = cl.post(f"/api/hr/appraisal-cycles/{cid}/close", json={})
    assert closed.status_code == 409  # the manager's own appraisal is still open
    assert cl.post(f"/api/hr/appraisal-cycles/{cid}/close", json={"force": True}).json()["incomplete"] == 1


def test_nobody_reviews_or_finalises_his_own_appraisal_and_a_leaver_manager_hands_over_to_hr(cl):
    gone = _emp(cl, "مدير غادر")
    worker = _emp(cl, "موظف بلا مدير فعّال", manager_id=gone)
    uw = _acct(cl, worker)
    cid = _cycle(cl)
    cl.post(f"/api/hr/appraisal-cycles/{cid}/open")
    login_as(cl, "admin")
    # the manager leaves: his reports must first be given another manager (the API refuses otherwise), so reassign then clear
    cl.patch(f"/api/hr/employees/{worker}", json={"manager_id": None})
    cl.post(f"/api/hr/employees/{gone}/status", json={"status": "terminated", "date": TODAY.isoformat(), "note": "استقالة"})
    login_as(cl, uw)
    aid = next(a["id"] for a in cl.get("/api/hr/me/appraisals").json())
    comps = [{"name": k["name"], "self_score": 3} for k in cl.get("/api/hr/me/appraisals").json()[0]["competencies"]]
    goals = [{"title": "هدف وحيد", "weight": 100, "self_score": 3}]
    # his appraisal was generated while the manager link existed, then the manager left → the review falls to HR
    assert cl.put(f"/api/hr/me/appraisals/{aid}/self", json={"goals": goals, "competencies": comps, "submit": True}).status_code == 200
    login_as(cl, "admin")
    assert cl.put(f"/api/hr/appraisals/{aid}/review", json={"goal_scores": [3], "competency_scores": [3] * 5, "manager_comment": "راجعته الموارد البشرية", "submit": True}).json()["status"] == "hr"
    # an HR officer who is himself an employee cannot finalise his own appraisal
    hr_user = _user(cl, "hrt-officer", "hr")
    me_emp = _emp(cl, "موظف موارد يقيَّم")
    login_as(cl, "admin")
    cl.post(f"/api/hr/employees/{me_emp}/link-user", json={"user_id": _sql("SELECT id FROM users WHERE username=?", (hr_user,))[0]["id"]})
    cl.post(f"/api/hr/appraisal-cycles/{cid}/open")
    own = _sql("SELECT id FROM appraisals WHERE employee_id=?", (me_emp,))[0]["id"]
    _sql("UPDATE appraisals SET status='hr' WHERE id=?", (own,))
    login_as(cl, hr_user)
    assert cl.post(f"/api/hr/appraisals/{own}/finalize", json={"decision": "none", "hr_comment": "ذاتي"}).status_code == 403


# ----------------------------------------------------------------------------------------------------- training
def test_training_certificates_expire_into_the_alerts_and_the_mandatory_list_shows_who_is_missing(cl):
    a, b = _emp(cl, "متدرب أول"), _emp(cl, "متدرب ثانٍ")
    login_as(cl, "admin")
    cid = cl.post("/api/hr/training/courses", json={"title": "السلامة والصحة المهنية", "provider": "جهة معتمدة", "hours": 8, "cert_valid_months": 12, "mandatory": True}).json()["id"]
    assert cl.post("/api/hr/training/courses", json={"title": "السلامة والصحة المهنية"}).status_code == 409
    done = (TODAY - dt.timedelta(days=350)).isoformat()  # a year's certificate with ~15 days left
    r = cl.post("/api/hr/training/records", json={"course_id": cid, "employee_id": a, "status": "completed", "completed_on": done, "score": 90, "certificate_no": "C-1"})
    assert r.status_code == 200 and r.json()["cert_expires"] > TODAY.isoformat(), "the expiry is computed from the course's validity"
    assert cl.post("/api/hr/training/records", json={"course_id": cid, "employee_id": a, "status": "completed"}).status_code == 400  # a completion needs its date
    alerts = [x for x in cl.get("/api/hr/alerts").json() if x["source"] == "training"]
    assert len(alerts) == 1 and alerts[0]["level"] == "critical" and "السلامة" in alerts[0]["label"]
    comp = {(x["number"], x["state"]) for x in cl.get("/api/hr/training/compliance").json()}
    assert ("EMP-0001", "expiring") in comp and ("EMP-0002", "missing") in comp
    # a renewed certificate silences the old one
    cl.post("/api/hr/training/records", json={"course_id": cid, "employee_id": a, "status": "completed", "completed_on": TODAY.isoformat()})
    assert not [x for x in cl.get("/api/hr/alerts").json() if x["source"] == "training"]
    ua = _acct(cl, a)
    login_as(cl, ua)
    mine = cl.get("/api/hr/me/training").json()
    assert len(mine["records"]) == 2 and mine["mandatory_missing"] == []
    ub = _acct(cl, b)
    login_as(cl, ub)
    assert cl.get("/api/hr/me/training").json()["mandatory_missing"] == ["السلامة والصحة المهنية"]
    assert cl.get("/api/hr/training/records").status_code == 403 and cl.get("/api/hr/training/compliance").status_code == 403


# ----------------------------------------------------------------------------------------------------- discipline
def _rule(cl, code="م-1", kind="warning", max_days=0, approve=True):
    login_as(cl, "admin")
    rid = cl.post("/api/hr/discipline/rules", json={"code": code, "name": "التأخر المتكرر", "kind": kind, "max_days": max_days, "source": "لائحة الجزاءات المعتمدة — المادة 5"}).json()["id"]
    if approve:
        login_as(cl, _user(cl, "hrt-officer", "hr"))
        assert cl.post(f"/api/hr/discipline/rules/{rid}/approve", json={"valid_from": "2020-01-01"}).status_code == 200
        login_as(cl, "admin")
    return rid


def test_no_penalty_without_an_approved_bylaw_a_statement_and_a_second_person(cl):
    e = _emp(cl, "المخالف")
    login_as(cl, "admin")
    draft = _rule(cl, "م-9", approve=False)
    case = cl.post("/api/hr/discipline/cases", json={"employee_id": e, "incident_date": (TODAY - dt.timedelta(days=3)).isoformat(), "description": "تأخر متكرر عن الدوام دون إذن"}).json()
    did = case["id"]
    assert case["number"].startswith(f"DC-{TODAY.year}-")
    assert cl.post(f"/api/hr/discipline/cases/{did}/propose", json={"rule_id": draft}).status_code == 409  # no statement yet
    assert cl.post(f"/api/hr/discipline/cases/{did}/statement", json={"statement": "ذكر أن السبب ظرف عائلي"}).status_code == 200
    r = cl.post(f"/api/hr/discipline/cases/{did}/propose", json={"rule_id": draft})
    assert r.status_code == 409 and "لائحة معتمدة" in r.text, "an article that nobody approved cannot ground a penalty"
    rule = _rule(cl, "م-1", approve=False)
    assert cl.post(f"/api/hr/discipline/rules/{rule}/approve", json={"valid_from": "2020-01-01"}).status_code == 403  # the creator does not approve
    login_as(cl, _user(cl, "hrt-officer", "hr"))
    assert cl.post(f"/api/hr/discipline/rules/{rule}/approve", json={"valid_from": TODAY.isoformat()}).status_code == 200
    login_as(cl, "admin")
    late = cl.post(f"/api/hr/discipline/cases/{did}/propose", json={"rule_id": rule})
    assert late.status_code == 409 and "سارية" in late.text, "an article newer than the incident does not apply to it"
    old = _rule(cl, "م-2")
    p = cl.post(f"/api/hr/discipline/cases/{did}/propose", json={"rule_id": old})
    assert p.status_code == 200, p.text
    assert cl.post(f"/api/hr/discipline/cases/{did}/issue").status_code == 403  # the proposer does not issue
    login_as(cl, "hrt-officer")
    assert cl.post(f"/api/hr/discipline/cases/{did}/issue").json()["status"] == "issued"
    # a deduction needs a bound and a month
    ded = _rule(cl, "م-3", kind="deduction", max_days=2)
    c2 = cl.post("/api/hr/discipline/cases", json={"employee_id": e, "incident_date": (TODAY - dt.timedelta(days=2)).isoformat(), "description": "غياب عن العمل بلا إذن مسبق"}).json()["id"]
    cl.post(f"/api/hr/discipline/cases/{c2}/statement", json={"statement": "لا عذر"})
    assert cl.post(f"/api/hr/discipline/cases/{c2}/propose", json={"rule_id": ded, "penalty_days": 5, "apply_period": PERIOD}).status_code == 400  # above the article's maximum
    assert cl.post(f"/api/hr/discipline/cases/{c2}/propose", json={"rule_id": ded, "penalty_days": 1}).status_code == 400  # a month is required
    assert cl.post(f"/api/hr/discipline/cases/{c2}/close", json={"note": "سُوّيت ودّيًا"}).status_code == 200


def test_the_employee_sees_only_issued_notices_and_appeals_and_the_issuer_does_not_decide_the_appeal(cl):
    e, other = _emp(cl, "صاحب الإنذار"), _emp(cl, "موظف آخر")
    ue, uo = _acct(cl, e), _acct(cl, other)
    rule = _rule(cl, "م-1")
    login_as(cl, "admin")
    mk = lambda d: cl.post("/api/hr/discipline/cases", json={"employee_id": e, "incident_date": (TODAY - dt.timedelta(days=d)).isoformat(), "description": "مخالفة ما للتعليمات المعتمدة"}).json()["id"]  # noqa: E731
    open_case, issued = mk(5), mk(4)
    cl.post(f"/api/hr/discipline/cases/{issued}/statement", json={"statement": "أقوال الموظف"})
    cl.post(f"/api/hr/discipline/cases/{issued}/propose", json={"rule_id": rule})
    login_as(cl, "hrt-officer")
    cl.post(f"/api/hr/discipline/cases/{issued}/issue")
    login_as(cl, ue)
    mine = cl.get("/api/hr/me/discipline").json()
    assert [x["id"] for x in mine] == [issued] and mine[0]["can_appeal"] and open_case, "a case still being studied is not shown to him"
    assert cl.get("/api/hr/discipline/cases").status_code == 403
    login_as(cl, uo)
    assert cl.get("/api/hr/me/discipline").json() == []
    assert cl.post(f"/api/hr/me/discipline/{issued}/appeal", json={"text": "أتظلم من هذا الإنذار لأسباب كثيرة"}).status_code == 404  # not his case
    login_as(cl, ue)
    assert cl.post(f"/api/hr/me/discipline/{issued}/appeal", json={"text": "قصير"}).status_code == 422
    assert cl.post(f"/api/hr/me/discipline/{issued}/appeal", json={"text": "أتظلم لأن الواقعة كانت بإذن شفهي من مديري"}).json()["status"] == "appealed"
    login_as(cl, "hrt-officer")
    assert cl.post(f"/api/hr/discipline/cases/{issued}/appeal-decision", json={"decision": "upheld"}).status_code == 403  # he issued it
    login_as(cl, "admin")
    assert cl.post(f"/api/hr/discipline/cases/{issued}/appeal-decision", json={"decision": "revoked"}).status_code == 200
    login_as(cl, ue)
    assert cl.get("/api/hr/me/discipline").json()[0]["status"] == "revoked"
    # an accused person who is also an HR user decides nothing in his own case
    login_as(cl, "admin")
    me_emp = _emp(cl, "موظف الموارد المتهم")
    cl.post(f"/api/hr/employees/{me_emp}/link-user", json={"user_id": _sql("SELECT id FROM users WHERE username='hrt-officer'")[0]["id"]})
    mine_case = cl.post("/api/hr/discipline/cases", json={"employee_id": me_emp, "incident_date": TODAY.isoformat(), "description": "واقعة بحق موظف الموارد نفسه"}).json()["id"]
    login_as(cl, "hrt-officer")
    assert cl.post(f"/api/hr/discipline/cases/{mine_case}/statement", json={"statement": "أقوالي"}).status_code == 403
    assert cl.post("/api/hr/discipline/cases", json={"employee_id": me_emp, "incident_date": TODAY.isoformat(), "description": "قضية على نفسي لا تُفتح"}).status_code == 403


def test_an_issued_deduction_is_valued_by_payroll_from_the_salary_and_cannot_be_revoked_once_applied(cl):
    e = _emp(cl, "عليه خصم", omani=False, hire="2024-01-01")
    login_as(cl, "admin")
    for k, v in (("pasi_employee_pct", 7), ("pasi_employer_pct", 10.5), ("pasi_ceiling", 3000)):
        cl.post("/api/hr/payroll/rates", json={"key": k, "value": v, "valid_from": "2000-01-01", "note": "قيمة اختبار لا مرجع لها"})
    cl.post("/api/hr/payroll/structures", json={"employee_id": e, "effective_from": "2024-01-01", "basic": 300, "lines": []})
    rule = _rule(cl, "م-3", kind="deduction", max_days=3)
    ue = _acct(cl, e)
    login_as(cl, "admin")
    did = cl.post("/api/hr/discipline/cases", json={"employee_id": e, "incident_date": (TODAY - dt.timedelta(days=20)).isoformat(), "description": "غياب عن العمل بلا عذر مقبول"}).json()["id"]
    cl.post(f"/api/hr/discipline/cases/{did}/statement", json={"statement": "لم يقدّم عذرًا"})
    assert cl.post(f"/api/hr/discipline/cases/{did}/propose", json={"rule_id": rule, "penalty_days": 2, "apply_period": PERIOD}).status_code == 200
    login_as(cl, "hrt-officer")
    cl.post(f"/api/hr/discipline/cases/{did}/issue")
    login_as(cl, "admin")
    rid = cl.post("/api/hr/payroll/runs", json={"period": PERIOD}).json()["id"]
    cl.post(f"/api/hr/payroll/runs/{rid}/compute")
    s = next(x for x in cl.get(f"/api/hr/payroll/runs/{rid}").json()["payslips"] if x["number"] == "EMP-0001")
    assert s["adj_ded"] == 20 and s["net"] == 280 and any(w["kind"] == "discipline" for w in s["warnings"]), "300 / 30 × 2 days"
    login_as(cl, _user(cl, "hrt-pay2", "payroll"))
    assert cl.post(f"/api/hr/payroll/runs/{rid}/approve").status_code == 200
    assert _sql("SELECT applied_run_id FROM disciplinary_cases WHERE id=?", (did,))[0]["applied_run_id"] == rid
    login_as(cl, ue)
    assert cl.post(f"/api/hr/me/discipline/{did}/appeal", json={"text": "أتظلم من الخصم لأن الغياب كان بإذن"}).status_code == 200
    login_as(cl, "admin")
    r = cl.post(f"/api/hr/discipline/cases/{did}/appeal-decision", json={"decision": "revoked"})
    assert r.status_code == 409 and "تسوية" in r.text, "the money already left the payslip: refund through an earning adjustment"
