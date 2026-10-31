"""0.29.0 — the policy and regulation register: a draft is prepared by one person and approved by another, a new version retires the one in force, staff read only what is approved and
acknowledge it once per version, the administrator sees who has not, text with markup is stored as text, and one organisation never sees another's policies."""
import os
import re
import tempfile
from pathlib import Path

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "pol.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "bayan:بيان عمان;almaqsura:المقصورة العقارية"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect, init  # noqa: E402

CSRF = "csrf-pol-" + "p" * 30
ART = [{"no": "1", "title": "الغرض", "text": "تنظّم هذه السياسة موضوعها في المنشأة."}, {"no": "2", "title": "النطاق", "text": "تسري على جميع العاملين."}]


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


def _sql(sql, args=(), tenant="bayan"):
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


def _wipe():
    for t in ("bayan", "almaqsura"):
        tok = TENANT.set(t)
        try:
            c = connect()
            pg = getattr(c, "dialect", "sqlite") == "postgres"
            sc = " AND org_id = current_setting('app.org_id', true)" if pg else ""
            c.maintenance()
            for tb in ("policy_acks", "policies"):
                c.execute(c.wipe_sql(tb))
            c.execute(f"DELETE FROM settings WHERE k LIKE 'demo_org:%'{sc}")
            c.execute(f"DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'polt-%' OR username LIKE 'emp%'){sc}")
            c.execute(f"UPDATE users SET employee_id=NULL WHERE username LIKE 'emp%'{sc}")
            c.execute(f"DELETE FROM users WHERE username LIKE 'polt-%' OR username LIKE 'emp%'{sc}")
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
            _sql("DELETE FROM login_attempts", tenant=t)
        yield c


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    _wipe()


def _user(cl, name, role):
    login_as(cl, "admin")
    r = cl.post("/api/users", json={"username": name, "name": f"مستخدم {name}", "role": role})
    assert r.status_code == 200, r.text
    _sql("UPDATE users SET must_change=0 WHERE username=?", (name,))
    return name


def _draft(cl, code="POL-T-01", who="admin", **kw):
    login_as(cl, who)
    body = {"code": code, "title": "سياسة اختبارية", "category": "hr", "articles": ART, "summary": "ملخص", "basis": "نموذج افتراضي للتجربة"}
    body.update(kw)
    r = cl.post("/api/policies", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _approve(cl, pid, who, day="2026-01-01"):
    login_as(cl, who)
    return cl.post(f"/api/policies/{pid}/approve", json={"effective_from": day})


def test_a_draft_is_approved_by_someone_else_and_a_new_version_retires_the_one_in_force(cl):
    hr = _user(cl, "polt-hr", "hr")
    pid = _draft(cl, "POL-L-01", "admin")
    assert _approve(cl, pid, "admin").status_code == 403                          # the preparer never approves
    assert _approve(cl, pid, hr, "not-a-date").status_code == 400
    assert _approve(cl, pid, hr).status_code == 200
    assert _approve(cl, pid, hr).status_code == 409                               # only a draft is approved
    login_as(cl, "admin")
    assert cl.patch(f"/api/policies/{pid}", json={"title": "تغيير"}).status_code == 409   # an approved text is never edited
    v2 = cl.post(f"/api/policies/{pid}/new-version")
    assert v2.status_code == 200 and v2.json()["version"] == 2
    assert cl.post(f"/api/policies/{pid}/new-version").status_code == 409         # only the one in force is copied …
    assert cl.post(f"/api/policies/{v2.json()['id']}/new-version").status_code == 409   # … and a draft is not
    assert cl.patch(f"/api/policies/{v2.json()['id']}", json={"articles": ART + [{"no": "3", "title": "الجزاء", "text": "مادة جديدة."}], "title": "سياسة اختبارية — منقّحة"}).status_code == 200
    assert _approve(cl, v2.json()["id"], hr, "2026-06-01").status_code == 200
    login_as(cl, "admin")
    old = cl.get(f"/api/policies/{pid}").json()
    new = cl.get(f"/api/policies/{v2.json()['id']}").json()
    assert old["status"] == "retired" and new["status"] == "approved" and len(new["articles"]) == 3
    assert [v["version"] for v in new["versions"]] == [2, 1]
    assert new["supersedes_id"] == pid and new["effective_from"] == "2026-06-01"


def test_staff_see_only_what_is_approved_and_acknowledge_once_per_version(cl):
    hr = _user(cl, "polt-hr2", "hr")
    approved = _draft(cl, "POL-A-01", "admin")
    _approve(cl, approved, hr)
    draft = _draft(cl, "POL-A-02", "admin", category="finance")
    login_as(cl, "sales")
    codes = [p["code"] for p in cl.get("/api/policies").json()]
    assert codes == ["POL-A-01"]
    assert cl.get(f"/api/policies/{draft}").status_code == 404
    assert cl.post(f"/api/policies/{draft}/ack").status_code == 404                 # a draft cannot be acknowledged
    assert cl.post("/api/policies", json={"code": "X-1", "title": "عنوان", "category": "hr", "articles": ART}).status_code == 403
    assert cl.post(f"/api/policies/{approved}/retire").status_code == 403
    assert cl.get("/api/policies/summary").json()["my_pending"] == 1
    assert cl.post(f"/api/policies/{approved}/ack").status_code == 200
    assert cl.post(f"/api/policies/{approved}/ack").status_code == 409             # once per version
    assert cl.get("/api/policies/summary").json()["my_pending"] == 0
    assert cl.get(f"/api/policies/{approved}/acks").status_code == 403
    login_as(cl, "admin")
    acks = cl.get(f"/api/policies/{approved}/acks").json()
    assert [a["username"] for a in acks["acknowledged"]] == ["sales"]
    assert "sales" not in [p["username"] for p in acks["pending"]] and any(p["username"] == "admin" for p in acks["pending"])
    # a new version asks everybody again
    v2 = cl.post(f"/api/policies/{approved}/new-version").json()["id"]
    _approve(cl, v2, hr, "2026-09-01")
    login_as(cl, "sales")
    assert cl.get("/api/policies/summary").json()["my_pending"] == 1
    assert cl.post(f"/api/policies/{v2}/ack").status_code == 200


def test_the_employee_portal_reads_and_acknowledges_but_never_prepares(cl):
    hr = _user(cl, "polt-hr3", "hr")
    pid = _draft(cl, "POL-E-01", "admin")
    _approve(cl, pid, hr)
    login_as(cl, "admin")
    eid = cl.post("/api/hr/employees", json={"name": "موظف السياسات", "omani": True, "hire_date": "2024-01-01", "gender": "male"}).json()["id"]
    un = cl.post(f"/api/hr/employees/{eid}/account").json()["username"]
    _sql("UPDATE users SET must_change=0 WHERE username=?", (un,))
    login_as(cl, un)
    assert [p["code"] for p in cl.get("/api/policies").json()] == ["POL-E-01"]
    assert cl.post(f"/api/policies/{pid}/ack").status_code == 200
    assert cl.post("/api/policies", json={"code": "E-2", "title": "عنوان", "category": "hr", "articles": ART}).status_code == 403
    assert _approve(cl, pid, un).status_code == 403
    for outsider in ("broker", "customer"):
        row = _sql("SELECT username FROM users WHERE role=? LIMIT 1", (outsider,))
        if row:
            login_as(cl, row[0][0])
            assert cl.get("/api/policies").status_code == 403


def test_markup_in_a_policy_is_stored_as_text_and_the_screen_escapes_it(cl):
    evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    pid = _draft(cl, "POL-X-01", "admin", title="عنوان " + evil, articles=[{"no": "1", "title": evil, "text": evil}])
    login_as(cl, "admin")
    r = cl.get(f"/api/policies/{pid}")
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["articles"][0]["text"] == evil
    js = (Path(__file__).resolve().parent.parent / "web" / "app.js").read_text(encoding="utf-8")
    body = js[js.index("EXT.polView"):]
    body = body[:body.index("\n};\n")]
    assert "esc(" in body
    assert not re.search(r"\$\{(a|x|p)\.(text|title)\}", body)                  # no article field is interpolated without esc()


def test_input_is_bounded_and_codes_are_unique(cl):
    login_as(cl, "admin")
    ok = {"code": "POL-V-01", "title": "سياسة التحقق", "category": "hr", "articles": ART}
    assert cl.post("/api/policies", json=ok).status_code == 200
    assert cl.post("/api/policies", json=ok).status_code == 409
    assert cl.post("/api/policies", json={**ok, "code": "pol-v-01"}).status_code == 409           # the code is compared in capitals
    assert cl.post("/api/policies", json={**ok, "code": "POL-V-02", "category": "nonsense"}).status_code == 422
    assert cl.post("/api/policies", json={**ok, "code": "POL-V-03", "articles": []}).status_code == 422
    assert cl.post("/api/policies", json={**ok, "code": "POL-V-04", "articles": [{"text": "x" * 4001}]}).status_code == 422
    assert cl.post("/api/policies", json={**ok, "code": "bad code!"}).status_code == 422
    assert cl.post("/api/policies", json={**ok, "code": "POL-V-05", "extra": 1}).status_code == 422
    assert cl.get("/api/policies?category=hr&q=التحقق").json()[0]["code"] == "POL-V-01"
    assert cl.get("/api/policies?status=bogus").status_code == 422


def test_one_organisation_never_sees_anothers_policies(cl):
    pid = _draft(cl, "POL-O-01", "admin")
    login_as(cl, "admin", "almaqsura")
    assert cl.get("/api/policies").json() == []
    assert cl.get(f"/api/policies/{pid}").status_code == 404
    assert cl.post(f"/api/policies/{pid}/retire").status_code == 404
    login_as(cl, "admin", "bayan")
    assert [p["code"] for p in cl.get("/api/policies").json()] == ["POL-O-01"]
    assert cl.post(f"/api/policies/{pid}/retire").status_code == 200                              # a dropped draft is retired, not deleted
    assert _sql("SELECT status FROM policies WHERE id=?", (pid,))[0][0] == "retired"


def test_the_seed_texts_quote_the_organisations_own_figures_and_never_invent_missing_ones():
    from backend.seed_org_pol_gov import gov_policies
    from backend.seed_org_pol_hr import hr_policies
    facts = {"leave": {"annual": {"days_per_year": 30, "day_count": "working", "paid": 1}}, "rates": {"pasi_employee_pct": 7.0, "pasi_employer_pct": 11.5, "pasi_ceiling": 3000.0, "day_divisor": 30.0},
             "eosb": {"expat": {"tiers": [{"to_years": 3, "days_per_year": 15}, {"to_years": None, "days_per_year": 30}], "cap_months": None}},
             "penalties": [{"code": "D-1", "name": "تأخر متكرر", "description": "التأخر المتكرر عن الدوام", "kind": "deduction", "max_days": 1.0}], "weekend": {4, 5}, "work_start": "08:30", "late_grace": 10}
    by = {p["code"]: " ".join(t + " " + x for t, x in p["arts"]) for p in hr_policies("منشأة", facts, True)}
    assert "30 يوم عمل" in by["POL-HR-03"] and "7٪" in by["POL-HR-04"] and "11.5٪" in by["POL-HR-04"] and "3000 ر.ع" in by["POL-HR-04"]
    assert "15 يومًا" in by["POL-HR-10"] and "30 يومًا" in by["POL-HR-10"] and "D-1" in by["POL-HR-09"] and "08:30" in by["POL-HR-02"] and "الجمعة، السبت" in by["POL-HR-02"]
    assert "قاعدة نهاية الخدمة لم تُدخَل" in by["POL-HR-10"]                       # the Omani rule was not entered: the text says so instead of inventing one
    empty = {"leave": {}, "rates": {}, "eosb": {}, "penalties": [], "weekend": set(), "work_start": "", "late_grace": 15}
    bare = {p["code"]: " ".join(t + " " + x for t, x in p["arts"]) for p in hr_policies("منشأة", empty, False)}
    assert "تُحدَّد القيمة في إعدادات الموارد البشرية" in bare["POL-HR-03"] and "تُحدَّد القيمة في إعدادات الموارد البشرية" in bare["POL-HR-04"]
    items = hr_policies("منشأة", facts, False) + gov_policies("منشأة", facts, False)
    assert len({p["code"] for p in items}) == len(items) >= 26
    assert all(2 <= len(p["arts"]) <= 14 and all(len(x) <= 4000 and len(t) <= 120 for t, x in p["arts"]) for p in items)


def test_the_policy_phase_fills_an_organisation_once_through_the_register_itself(cl):
    from backend import seed_org
    _sql("DELETE FROM settings WHERE k LIKE 'demo_org:%'")
    out = seed_org.ensure_org_demo("bayan", phases=("pol",))
    assert out["pol"]["policies"] >= 26 and out["pol"]["drafts"] == 2 and out["pol"]["versions"] == 2
    st = dict(_sql("SELECT status, COUNT(*) FROM policies GROUP BY status"))
    assert st["draft"] == 2 and st["retired"] == 1 and st["approved"] >= 24
    code = _sql("SELECT p.code FROM policies p WHERE p.status='retired'")[0][0]
    assert _sql("SELECT COUNT(*) FROM policies WHERE code=?", (code,))[0][0] == 2                  # the retired first version sits beside the approved second
    assert _sql("SELECT COUNT(*) FROM policies WHERE status='approved' AND approved_by=created_by")[0][0] == 0   # nobody approved their own
    assert _sql("SELECT COUNT(*) FROM policy_acks")[0][0] > 0
    again = seed_org.ensure_org_demo("bayan", phases=("pol",))
    assert again["pol"] == "done" and _sql("SELECT COUNT(*) FROM policies")[0][0] == out["pol"]["policies"] + out["pol"]["versions"]
    login_as(cl, "sales")
    seen = cl.get("/api/policies").json()
    assert seen and all(p["status"] == "approved" for p in seen) and len(seen) == st["approved"]
    login_as(cl, "admin", "almaqsura")
    assert cl.get("/api/policies").json() == []                                                  # the other organisation was not touched
