"""0.30.0 — التحديث الجزئي بدلالة PATCH صريحة (docs/DESIGN-partial-update.md).

القاعدة: غير المُرسَل لا يُمس · الفارغ/null المُرسَل يُفرَّغ الاختياري ويُرفض الإلزامي بالعربية · المُرسَل بقيمته الحالية ليس تغييرًا:
`changed: []` بلا UPDATE ولا سطر تدقيق ولا commit · البيانات الشخصية والمشفّرة لا قيمة لها في التدقيق ولا في الرد.
الاختبارات لا تكتب SQL خاصًا بمحرك إلا للتنظيف عبر maintenance، فتعمل كما هي على SQLite وPostgreSQL.
"""
import contextlib
import datetime as dt
import os
import struct
import tempfile
import time
import zlib

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "pu.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"
os.environ["MABANIQ_TENANTS"] = "almukhatat:المخطط العقارية;bayan:بيان عمان;almaqsura:المقصورة العقارية;view:رؤية العقارية"

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import BaseModel, ConfigDict  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import pii  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import TENANT, connect, init  # noqa: E402
from backend.partial import Col, diff  # noqa: E402

CSRF = "csrf-pu-" + "p" * 30


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
def _client(tenant):
    from backend import observability as O
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:    # the start-up creates the organisation and its users before we sign in
        yield login_as(c, "admin", tenant)


@pytest.fixture()
def jd():
    with _client("jadwa") as c:
        yield c


@pytest.fixture()
def by():
    with _client("bayan") as c:
        yield c


def _sql(sql, args=(), tenant="bayan", maint=False):
    """Raw SQL as the tenant — only for what the API cannot do (rewind a date, flip a verified flag, remove the rows a test made)."""
    tok = TENANT.set(tenant)
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


def last_audit(c) -> dict:
    r = c.get("/api/audit", params={"limit": 1}).json()
    return r[0] if r else {"id": 0, "action": "", "detail": ""}


# ====================================================================================================== الدالة نفسها (نقيّة)
class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = None
    ref: str | None = None
    expires: dt.date | None = None
    fee: float | None = None
    live: bool | None = None
    iban: str | None = None
    note: str | None = None
    articles: str | None = None


SPEC = {
    "status": Col("الحالة", required=True),
    "ref": Col("الرقم المرجعي"),
    "expires": Col("تاريخ الانتهاء", kind="date"),
    "fee": Col("الرسم", kind="num"),
    "live": Col("فعّال", required=True, kind="bool"),
    "iban": Col("الآيبان", secret=True),
    "note": Col("ملاحظة", personal=True, check=lambda v: None if len(v) >= 3 else "الملاحظة قصيرة"),
    "articles": Col("المواد", quiet=True),
}
CUR = {"status": "issued", "ref": "A-1", "expires": "2027-01-01", "fee": 5, "live": 1, "iban": None, "note": None, "articles": "x"}


def test_a_field_that_was_not_sent_is_never_touched():
    p = diff(CUR, Body(ref="B-2"), SPEC)
    assert p.changed == ["ref"] and p.changes[0].old == "A-1" and p.changes[0].new == "B-2"


def test_an_empty_or_null_optional_field_is_cleared_and_whitespace_counts_as_empty():
    p = diff(CUR, Body(ref="   ", expires=None), SPEC)
    assert p.changed == ["ref", "expires"] and all(x.new is None and x.db is None for x in p.changes)


def test_a_required_field_refuses_to_be_emptied_in_arabic_naming_it():
    for bad in (Body(status=""), Body(status=None), Body(status="  "), Body(live=None)):
        with pytest.raises(HTTPException) as e:
            diff(CUR, bad, SPEC)
        assert e.value.status_code == 400 and "إلزامي" in e.value.detail and ("الحالة" in e.value.detail or "فعّال" in e.value.detail)


def test_sending_the_current_values_is_not_a_change_even_in_another_spelling():
    same = Body(status=" issued ", ref="A-1", expires=dt.date(2027, 1, 1), fee=5.0, live=True)
    p = diff(CUR, same, SPEC)
    assert p.changed == [] and not p and p.public() == [] and p.detail() == ""
    assert diff({**CUR, "live": None}, Body(live=False), SPEC).changed == []      # NULL in a flag column means 0
    assert diff({**CUR, "expires": "2027-01-01T10:00:00"}, Body(expires=dt.date(2027, 1, 1)), SPEC).changed == []   # a date compares by day


def test_a_value_the_column_rejects_is_refused_with_its_own_message_but_only_when_not_empty():
    with pytest.raises(HTTPException) as e:
        diff(CUR, Body(note="ab"), SPEC)
    assert e.value.detail == "الملاحظة قصيرة"
    assert diff({**CUR, "note": "قديمة"}, Body(note=""), SPEC).changed == ["note"]     # clearing skips the check


def test_personal_secret_and_quiet_columns_never_show_a_value_in_the_audit_line_or_the_reply():
    p = diff(CUR, Body(note="سرّ شخصي", iban="OM01SECRET", articles="y"), SPEC)
    assert p.changed == ["iban", "note", "articles"]            # in the order of the spec, not of the request
    text = p.detail() + repr(p.public())
    assert "سرّ شخصي" not in text and "OM01SECRET" not in text and "«x»" not in text
    pub = {x["field"]: x for x in p.public()}
    assert pub["note"] == {"field": "note", "label": "ملاحظة", "personal": True} and pub["iban"]["personal"] and pub["articles"] == {"field": "articles", "label": "المواد", "quiet": True}


def test_a_secret_column_is_compared_opened_and_written_sealed():
    sealed = pii.enc("OM01SAME")
    assert diff({**CUR, "iban": sealed}, Body(iban="OM01SAME"), SPEC).changed == []        # the ciphertext differs on every encryption; the opened value does not
    p = diff({**CUR, "iban": sealed}, Body(iban="OM02OTHER"), SPEC)
    assert p.changed == ["iban"] and p.changes[0].db.startswith(pii.PREFIX) and pii.dec(p.changes[0].db) == "OM02OTHER"
    assert diff({**CUR, "iban": sealed}, Body(iban=""), SPEC).changes[0].db is None


def test_values_the_server_derives_are_diffed_labelled_and_win_over_the_client():
    p = diff(CUR, Body(ref="A-1"), {**SPEC, "issued": Col("تاريخ الصدور", kind="date")}, extra={"issued": "2026-11-03", "ref": "FORCED"})
    assert p.changed == ["issued", "ref"] and p.value("ref") == "FORCED"
    assert "تاريخ الصدور: «بلا» ⟵ «2026-11-03»" in p.detail()


def test_the_audit_text_shows_from_and_to_with_empty_as_a_word_and_flags_as_yes_no():
    p = diff(CUR, Body(ref="", live=False, fee=7), SPEC)
    assert p.detail() == "الرقم المرجعي: «A-1» ⟵ «بلا»؛ الرسم: «5» ⟵ «7»؛ فعّال: «نعم» ⟵ «لا»"


def test_a_dict_body_works_like_a_model_and_only_its_keys_count_as_sent():
    p = diff(CUR, {"ref": "Z"}, SPEC)
    assert p.changed == ["ref"]


# ====================================================================================================== الترخيص
def _permit(c, prefer=("in_review", "submitted", "rejected", "issued")):
    P = c.get("/api/permits").json()
    return next((p for s in prefer for p in P if p["status"] == s), P[0])


def _restore_permit(p):
    _sql("UPDATE permits SET status=?, ref=?, applied=?, issued=?, expires=? WHERE id=?", (p["status"], p["ref"], p["applied"], p["issued"], p["expires"], p["id"]), "jadwa")


def test_permit_optional_fields_clear_required_refuses_and_the_same_values_change_nothing(jd):
    p0 = _permit(jd)
    pid = p0["id"]
    try:
        r = jd.patch(f"/api/permits/{pid}", json={"ref": "T-77", "expires": "2031-06-30"})
        assert r.status_code == 200 and r.json()["changed"] == ["ref", "expires"], r.text
        now = next(x for x in jd.get("/api/permits").json() if x["id"] == pid)
        assert now["ref"] == "T-77" and now["expires"] == "2031-06-30" and now["status"] == p0["status"]       # the status was not sent: untouched
        # clearing: null and "" both empty the optional fields (the COALESCE/NULLIF defect of 0.29)
        r = jd.patch(f"/api/permits/{pid}", json={"ref": "", "expires": None})
        assert r.json()["changed"] == ["ref", "expires"]
        ch = {x["field"]: x for x in r.json()["changes"]}
        assert ch["ref"]["old"] == "T-77" and ch["ref"]["new"] is None and ch["expires"]["label"] == "تاريخ الانتهاء"
        now = next(x for x in jd.get("/api/permits").json() if x["id"] == pid)
        assert not now["ref"] and now["expires"] is None
        a = last_audit(jd)
        assert a["action"] == "تحديث ترخيص" and "الرقم المرجعي: «T-77» ⟵ «بلا»" in a["detail"] and "تاريخ الانتهاء: «2031-06-30» ⟵ «بلا»" in a["detail"]
        # the same values again: nothing changes, nothing is written
        before = last_audit(jd)["id"]
        r = jd.patch(f"/api/permits/{pid}", json={"ref": "", "expires": None})
        assert r.status_code == 200 and r.json()["changed"] == [] and r.json()["changes"] == []
        assert last_audit(jd)["id"] == before
        # the required status
        for bad in ({"status": None}, {"status": ""}):
            r = jd.patch(f"/api/permits/{pid}", json=bad)
            assert r.status_code == 400 and "الحالة" in r.json()["detail"] and "إلزامي" in r.json()["detail"], r.text
        assert jd.patch(f"/api/permits/{pid}", json={"status": "expired"}).status_code == 400      # the system's states are not the clerk's to set
        assert jd.patch(f"/api/permits/{pid}", json={"bogus": 1}).status_code == 422                 # a mistyped field is refused, not silently ignored
        assert jd.patch("/api/permits/99999999", json={"ref": "x"}).status_code == 404
    finally:
        _restore_permit(p0)


def test_permit_issue_date_moves_only_on_the_transition_and_the_old_post_route_still_works(jd):
    p0 = _permit(jd, prefer=("in_review", "submitted", "rejected"))
    pid = p0["id"]
    today = dt.date.today().isoformat()
    try:
        r = jd.patch(f"/api/permits/{pid}", json={"status": "issued"})
        assert r.status_code == 200 and "status" in r.json()["changed"] and "issued" in r.json()["changed"], r.text
        assert next(x for x in jd.get("/api/permits").json() if x["id"] == pid)["issued"] == today
        _sql("UPDATE permits SET issued='2020-01-01' WHERE id=?", (pid,), "jadwa")
        r = jd.patch(f"/api/permits/{pid}", json={"status": "issued", "ref": "RE-SAVE-1"})      # saving an issued permit again
        assert r.json()["changed"] == ["ref"]
        assert next(x for x in jd.get("/api/permits").json() if x["id"] == pid)["issued"] == "2020-01-01"      # …did not move its issue date to today
        r = jd.post(f"/api/permits/{pid}", json={"status": "in_review", "ref": "", "expires": None})        # the 0.29 payload, the 0.29 route
        assert r.status_code == 200 and "status" in r.json()["changed"]
        assert next(x for x in jd.get("/api/permits").json() if x["id"] == pid)["status"] == "in_review"
    finally:
        _restore_permit(p0)


def test_permit_edit_needs_the_permits_permission(jd):
    pid = _permit(jd)["id"]
    with _client("jadwa") as s:
        login_as(s, "sales", "jadwa")
        assert s.patch(f"/api/permits/{pid}", json={"ref": "nope"}).status_code == 403


# ====================================================================================================== وحدة التأجير
def test_unit_owner_and_parking_can_be_cleared_and_a_unit_in_the_portfolio_keeps_an_owner(by):
    cand = by.get("/api/lea/units/candidates").json()
    if not cand:
        pytest.skip("this tenant has no unit outside the leasing portfolio")
    uid = cand[0]["id"]
    try:
        r = by.post(f"/api/lea/units/{uid}", json={"retained": True, "use": "residential", "parking_bays": 2})
        assert r.status_code == 200 and {"retained", "parking_bays"} <= set(r.json()["changed"]), r.text
        row = next(u for u in by.get("/api/lea/units").json()["units"] if u["id"] == uid)
        assert row["owner_id"] is not None and row["parking_bays"] == 2                       # the company owner was assigned on entry
        r = by.patch(f"/api/lea/units/{uid}", json={"parking_bays": None})
        assert r.json()["changed"] == ["parking_bays"]
        assert next(u for u in by.get("/api/lea/units").json()["units"] if u["id"] == uid)["parking_bays"] is None
        before = last_audit(by)["id"]
        assert by.patch(f"/api/lea/units/{uid}", json={"parking_bays": None, "use": "residential", "retained": True}).json()["changed"] == []
        assert last_audit(by)["id"] == before
        r = by.patch(f"/api/lea/units/{uid}", json={"owner_id": None})
        assert r.status_code == 400 and "مالك" in r.json()["detail"]
        for bad in ({"use": ""}, {"use": None}, {"retained": None}):
            r = by.patch(f"/api/lea/units/{uid}", json=bad)
            assert r.status_code == 400 and "إلزامي" in r.json()["detail"], (bad, r.text)
        assert by.patch(f"/api/lea/units/{uid}", json={"use": "castle"}).status_code == 400
        assert by.patch(f"/api/lea/units/{uid}", json={"lease_state": "prep"}).json()["changed"] == ["lease_state"]
        assert by.patch(f"/api/lea/units/{uid}", json={"lease_state": "none"}).json()["changed"] == ["lease_state"]       # the old sentinel still clears
        assert by.patch(f"/api/lea/units/{uid}", json={"lease_state": None}).json()["changed"] == []                      # …and null is the same as «none»
    finally:
        by.post(f"/api/lea/units/{uid}", json={"retained": False})


# ====================================================================================================== المالك (هوية وآيبان مشفّران)
def _owner(c, **kw):
    body = {"name": "مالك اختبار التحديث", "kind": "third_party", "id_number": "ID-9988776", "phone": "99112233", "email": "own.pu@example.test", "iban": "OM81BANK000099887766",
            "mgmt_fee_pct": 4, "mgmt_basis": "collected", "notes": "ملاحظة أولى"}
    body.update(kw)
    r = c.post("/api/lea/owners", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _owner_row(c, oid):
    return next(o for o in c.get("/api/lea/owners").json() if o["id"] == oid)


def test_owner_masked_identity_is_kept_unless_sent_and_cleared_only_by_an_explicit_empty(by):
    oid = _owner(by)
    r = by.patch(f"/api/lea/owners/{oid}", json={"phone": "98765432"})
    assert r.status_code == 200 and r.json()["changed"] == ["phone"]
    ch = r.json()["changes"][0]
    assert ch["personal"] is True and "old" not in ch and "new" not in ch                          # a personal value is never echoed
    o = _owner_row(by, oid)
    assert o["id_number"] and o["iban"] and o["id_number"].endswith("6")                          # not sent ⟵ untouched (masked, last four digits)
    a = last_audit(by)
    assert a["action"] == "تعديل مالك" and "الهاتف (قيمة محجوبة)" in a["detail"] and "98765432" not in a["detail"] and "99112233" not in a["detail"]
    before = last_audit(by)["id"]
    assert by.patch(f"/api/lea/owners/{oid}", json={"phone": "98765432", "iban": "OM81BANK000099887766", "mgmt_fee_pct": 4.0}).json()["changed"] == []      # the same opened IBAN is no change
    assert last_audit(by)["id"] == before
    r = by.patch(f"/api/lea/owners/{oid}", json={"iban": ""})                                       # an explicit empty clears (it could not before)
    assert r.json()["changed"] == ["iban"]
    o = _owner_row(by, oid)
    assert not o["iban"] and o["id_number"]
    assert "OM81" not in last_audit(by)["detail"]
    for bad, field in (({"name": ""}, "الاسم"), ({"name": None}, "الاسم"), ({"mgmt_fee_pct": None}, "عمولة"), ({"mgmt_basis": ""}, "أساس")):
        r = by.patch(f"/api/lea/owners/{oid}", json=bad)
        assert r.status_code == 400 and field in r.json()["detail"], (bad, r.text)
    assert by.patch(f"/api/lea/owners/{oid}", json={"mgmt_basis": "weird"}).status_code == 400
    assert by.patch(f"/api/lea/owners/{oid}", json={"mgmt_fee_pct": 51}).status_code == 422
    r = by.post(f"/api/lea/owners/{oid}", json={"name": "مالك اختبار التحديث", "phone": "98765432", "mgmt_fee_pct": 6, "mgmt_basis": "invoiced"})      # the 0.29 route and a partial body
    assert r.status_code == 200 and sorted(r.json()["changed"]) == ["mgmt_basis", "mgmt_fee_pct"]
    assert _owner_row(by, oid)["email"] == "own.pu@example.test"                                    # …no longer wipes what it did not carry


# ====================================================================================================== المستأجر
def _tenant(c, **kw):
    body = {"name": "مستأجر اختبار التحديث", "kind": "individual", "phone": "91234567", "id_number": "TID778899", "nationality": "عُماني", "id_expiry": "2030-05-01",
            "rating": "B", "rating_note": "جيد", "address": "مسقط"}
    body.update(kw)
    r = c.post("/api/lea/tenants", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_tenant_edit_changes_only_what_was_sent_clears_with_empty_and_keeps_personal_data_out_of_the_audit(by):
    tid = _tenant(by)
    r = by.patch(f"/api/lea/tenants/{tid}", json={"phone": "92223344"})
    assert r.status_code == 200 and r.json()["changed"] == ["phone"]
    a = last_audit(by)       # before the read below: opening a tenant file writes its own audit line
    assert a["action"] == "تعديل مستأجر" and "92223344" not in a["detail"] and "91234567" not in a["detail"] and "الهاتف (قيمة محجوبة)" in a["detail"]
    t = by.get(f"/api/lea/tenants/{tid}").json()
    assert t["nationality"] == "عُماني" and t["rating"] == "B" and t["id_number"] == "TID778899" and t["address"] == "مسقط"      # the rest survived a one-field edit
    before = last_audit(by)["id"]
    assert by.patch(f"/api/lea/tenants/{tid}", json={"name": "مستأجر اختبار التحديث", "kind": "individual", "id_number": "TID778899", "id_expiry": "2030-05-01", "rating": "B"}).json()["changed"] == []
    assert last_audit(by)["id"] == before
    r = by.patch(f"/api/lea/tenants/{tid}", json={"id_expiry": None, "rating": "", "address": "", "id_number": ""})
    assert sorted(r.json()["changed"]) == ["address", "id_expiry", "id_number", "rating"]
    t = by.get(f"/api/lea/tenants/{tid}").json()
    assert not t["id_expiry"] and not t["rating"] and not t["address"] and not t["id_number"]
    pub = {x["field"]: x for x in r.json()["changes"]}
    assert pub["rating"]["old"] == "B" and pub["rating"]["new"] is None and pub["id_number"]["personal"]
    for bad, word in (({"name": ""}, "الاسم"), ({"name": None}, "الاسم"), ({"kind": ""}, "النوع")):
        r = by.patch(f"/api/lea/tenants/{tid}", json=bad)
        assert r.status_code == 400 and word in r.json()["detail"] and "إلزامي" in r.json()["detail"], (bad, r.text)
    assert by.patch(f"/api/lea/tenants/{tid}", json={"name": "اب"}).status_code == 400
    assert by.patch(f"/api/lea/tenants/{tid}", json={"rating": "E"}).status_code == 400
    assert by.patch(f"/api/lea/tenants/{tid}", json={"id_expiry": "غدًا"}).status_code == 400
    assert by.patch(f"/api/lea/tenants/{tid}", json={"phone": "٩٩abc"}).status_code == 400
    r = by.post(f"/api/lea/tenants/{tid}", json={"name": "مستأجر اختبار التحديث", "kind": "company", "cr_number": "CR-1"})            # the 0.29 route, partial
    assert r.status_code == 200 and sorted(r.json()["changed"]) == ["cr_number", "kind"]
    assert by.get(f"/api/lea/tenants/{tid}").json()["phone"] == "92223344"


# ====================================================================================================== الحساب والمورّد
def test_account_patch_clears_optional_fields_refuses_the_required_and_reports_changes(by):
    if by.get("/api/acc/accounts").status_code != 200:
        pytest.skip("accounting is not available for this tenant")
    code = "PU" + str(int(time.time() * 1000) % 10**9)
    _sql("INSERT INTO acc_accounts(code,name,name_en,type,postable,normal,note) VALUES(?,?,?,?,?,?,?)", (code, "حساب اختبار التحديث", "PU", "asset", 1, "debit", "ملاحظة"), "bayan")
    try:
        aid = next(x["id"] for x in by.get("/api/acc/accounts").json() if x["code"] == code)
        r = by.patch(f"/api/acc/accounts/{aid}", json={"note": None, "name_en": "PU Test"})
        assert r.status_code == 200 and sorted(r.json()["changed"]) == ["name_en", "note"], r.text
        assert [x["label"] for x in r.json()["changes"]] == ["الاسم الإنجليزي", "ملاحظة"]
        before = last_audit(by)["id"]
        assert by.patch(f"/api/acc/accounts/{aid}", json={"note": "", "name_en": "PU Test", "active": True, "name": "حساب اختبار التحديث"}).json()["changed"] == []
        assert last_audit(by)["id"] == before
        for bad in ({"name": ""}, {"name": None}, {"active": None}):
            r = by.patch(f"/api/acc/accounts/{aid}", json=bad)
            assert r.status_code == 400 and "إلزامي" in r.json()["detail"], (bad, r.text)
        assert by.patch(f"/api/acc/accounts/{aid}", json={"name": "ا"}).status_code == 400
        assert by.patch(f"/api/acc/accounts/{aid}", json={"vat_class": "standard"}).json()["changed"] == ["vat_class"]
        assert by.patch(f"/api/acc/accounts/{aid}", json={"vat_class": ""}).json()["changed"] == ["vat_class"]
        assert by.patch(f"/api/acc/accounts/{aid}", json={"active": False}).json()["changed"] == ["active"]
        assert by.patch("/api/acc/accounts/99999999", json={"note": "x"}).status_code == 404
    finally:
        _sql("DELETE FROM acc_accounts WHERE code=?", (code,), "bayan", maint=True)


def test_vendor_tax_number_sets_clears_and_reports_no_change(by):
    if by.get("/api/acc/accounts").status_code != 200:
        pytest.skip("accounting is not available for this tenant")
    v = by.post("/api/acc/vendors", json={"name": "مورّد اختبار التحديث", "trade": "تشطيبات"})
    assert v.status_code == 200, v.text
    vid = v.json()["id"]
    assert by.patch(f"/api/acc/vendors/{vid}", json={"tax_no": "OM110099"}).json()["changed"] == ["tax_no"]
    before = last_audit(by)["id"]
    assert by.patch(f"/api/acc/vendors/{vid}", json={"tax_no": " OM110099 "}).json()["changed"] == []
    assert last_audit(by)["id"] == before
    assert by.patch(f"/api/acc/vendors/{vid}", json={"tax_no": ""}).json()["changed"] == ["tax_no"]
    assert by.patch(f"/api/acc/vendors/{vid}", json={}).json()["changed"] == []
    assert by.patch("/api/acc/vendors/99999999", json={"tax_no": "x"}).status_code == 404


# ====================================================================================================== المخطط
def _png(w=4, h=4) -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes([200, 30, 30]) * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_plan_patch_clears_the_floor_and_keeps_internal_drawings_private(jd):
    pid = jd.get("/api/projects").json()[0]["id"]
    up = jd.post("/api/plans", data={"project_id": str(pid), "kind": "floor", "title": "مخطط اختبار التحديث", "building": "ب1", "floor": "3"}, files={"file": ("f.png", _png(), "image/png")})
    assert up.status_code == 200, up.text
    plan_id = up.json()["id"]
    try:
        r = jd.patch(f"/api/plans/{plan_id}", json={"floor": None})
        assert r.status_code == 200 and r.json()["changed"] == ["floor"] and r.json()["floor"] is None and r.json()["building"] == "ب1"
        before = last_audit(jd)["id"]
        assert jd.patch(f"/api/plans/{plan_id}", json={"floor": None, "building": "ب1", "title": "مخطط اختبار التحديث", "public": True}).json()["changed"] == []
        assert last_audit(jd)["id"] == before
        assert jd.patch(f"/api/plans/{plan_id}", json={"building": ""}).json()["changed"] == ["building"]
        for bad in ({"title": ""}, {"title": None}, {"public": None}):
            r = jd.patch(f"/api/plans/{plan_id}", json=bad)
            assert r.status_code == 400 and "إلزامي" in r.json()["detail"], (bad, r.text)
        assert jd.patch(f"/api/plans/{plan_id}", json={"title": "ا"}).status_code == 400
        assert jd.post(f"/api/plans/{plan_id}", json={"unit_type": "نموذج أ"}).json()["changed"] == ["unit_type"]        # the 0.29 route
    finally:
        jd.post(f"/api/plans/{plan_id}/remove")
    st = jd.post("/api/plans", data={"project_id": str(pid), "kind": "structural", "title": "أساسات اختبار التحديث"}, files={"file": ("s.png", _png(), "image/png")}).json()
    try:
        r = jd.patch(f"/api/plans/{st['id']}", json={"public": True})
        assert r.status_code == 200 and r.json()["public"] == 0 and r.json()["changed"] == []         # structural drawings never become public
    finally:
        jd.post(f"/api/plans/{st['id']}/remove")


# ====================================================================================================== البريد والترويسة والسياسة والوثيقة
def test_resaving_the_same_email_keeps_its_verification_and_the_audit_never_holds_the_address(by):
    addr = f"pu.{int(time.time())}@example.test"
    try:
        r = by.post("/api/me/email", json={"email": addr})
        assert r.status_code == 200 and r.json()["changed"] == ["email"] and r.json()["email_verified"] is False
        assert addr not in last_audit(by)["detail"] and last_audit(by)["action"] == "تحديث البريد الإلكتروني"
        _sql("UPDATE users SET email_verified=1 WHERE username='admin'", (), "bayan")
        before = last_audit(by)["id"]
        r = by.post("/api/me/email", json={"email": addr.upper()})           # same address, another spelling
        assert r.json()["changed"] == [] and r.json()["email_verified"] is True and r.json()["email"] == addr
        assert last_audit(by)["id"] == before
        assert by.get("/api/me/identity").json()["email_verified"] is True        # the verification survived
        r = by.post("/api/me/email", json={"email": "pu.other@example.test"})
        assert r.json()["changed"] == ["email"] and r.json()["email_verified"] is False
    finally:
        by.post("/api/me/email", json={"email": ""})


def test_brand_saves_only_what_changed_and_clears_with_an_empty_string(by):
    cur = by.get("/api/admin/brand").json()
    try:
        r = by.post("/api/admin/brand", json={"vat": "OM-PU-1", "address": "عنوان اختبار التحديث"})
        assert r.status_code == 200 and sorted(r.json()["changed"]) == ["address", "vat"] and r.json()["vat"] == "OM-PU-1"
        before = last_audit(by)["id"]
        r = by.post("/api/admin/brand", json={"vat": "OM-PU-1", "address": "عنوان اختبار التحديث"})
        assert r.json()["changed"] == [] and last_audit(by)["id"] == before
        r = by.post("/api/admin/brand", json={"vat": ""})
        assert r.json()["changed"] == ["vat"] and by.get("/api/admin/brand").json()["vat"] == ""
        a = last_audit(by)
        assert a["action"] == "تحديث هوية المستندات" and "الرقم الضريبي: «OM-PU-1» ⟵ «بلا»" in a["detail"]
    finally:
        by.post("/api/admin/brand", json={"vat": cur["vat"], "address": cur["address"]})


def test_policy_draft_edit_reports_changes_and_writes_nothing_when_nothing_changed(by):
    code = "PU" + str(int(time.time()) % 10**7)
    art = [{"no": "1", "title": "الأولى", "text": "نص المادة الأولى"}]
    r = by.post("/api/policies", json={"code": code, "title": "سياسة اختبار التحديث", "category": "hr", "articles": art, "summary": "ملخص"})
    if r.status_code in (401, 403, 404):
        pytest.skip("policies are not available for this tenant")
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    try:
        assert by.patch(f"/api/policies/{pid}", json={"title": "سياسة اختبار التحديث"}).json()["changed"] == []
        before = last_audit(by)["id"]
        assert by.patch(f"/api/policies/{pid}", json={"summary": "ملخص", "articles": art}).json()["changed"] == []
        assert last_audit(by)["id"] == before
        r = by.patch(f"/api/policies/{pid}", json={"summary": "", "articles": [{"no": "1", "title": "الأولى", "text": "نص معدَّل"}]})
        assert sorted(r.json()["changed"]) == ["body", "summary"]
        a = last_audit(by)
        assert "المواد (عُدِّل)" in a["detail"] and "نص معدَّل" not in a["detail"] and "الملخص: «ملخص» ⟵ «بلا»" in a["detail"]
        assert by.patch(f"/api/policies/{pid}", json={"title": ""}).status_code in (400, 422)
    finally:
        by.post(f"/api/policies/{pid}/retire")      # a draft is never deleted: it is retired


def test_employee_document_patch_keeps_what_was_not_sent_and_encrypts_the_number(by):
    emp = by.post("/api/hr/employees", json={"name": "موظف اختبار التحديث", "omani": True, "hire_date": "2024-01-01", "gender": "male", "email": f"pu{int(time.time())}@example.test"})
    if emp.status_code != 200:
        pytest.skip("HR is not available for this tenant")
    eid = emp.json()["id"]
    try:
        did = by.post(f"/api/hr/employees/{eid}/documents", json={"kind": "passport", "number": "P1234567", "issued": "2023-01-01", "expires": "2033-01-01", "note": "أصلي"}).json()["id"]
        r = by.patch(f"/api/hr/documents/{did}", json={"note": "بعد التعديل"})
        assert r.status_code == 200 and r.json()["changed"] == ["note"]
        docs = by.get(f"/api/hr/employees/{eid}/documents").json()
        d = next(x for x in docs if x["id"] == did)
        assert d["expires"] == "2033-01-01" and d["issued"] == "2023-01-01" and d["note"] == "بعد التعديل"      # the PATCH no longer wipes the dates it did not carry
        before = last_audit(by)["id"]
        assert by.patch(f"/api/hr/documents/{did}", json={"number": "P1234567", "expires": "2033-01-01"}).json()["changed"] == []
        assert last_audit(by)["id"] == before
        r = by.patch(f"/api/hr/documents/{did}", json={"number": "P7654321"})
        assert r.json()["changed"] == ["number"] and "P7654321" not in last_audit(by)["detail"] and "P1234567" not in last_audit(by)["detail"]
        r = by.patch(f"/api/hr/documents/{did}", json={"expires": None})
        assert r.status_code == 400 and "نهاية صلاحية" in r.json()["detail"]                                    # a passport needs an expiry
        assert by.patch(f"/api/hr/documents/{did}", json={"expires": "2020-01-01"}).status_code == 400            # before it was issued
        assert by.patch(f"/api/hr/documents/{did}", json={"kind": ""}).status_code == 400
        assert by.patch(f"/api/hr/documents/{did}", json={"note": ""}).json()["changed"] == ["note"]
    finally:
        _sql("DELETE FROM employee_documents WHERE employee_id=?", (eid,), "bayan", maint=True)
        _sql("DELETE FROM employees WHERE id=?", (eid,), "bayan", maint=True)


def test_hr_department_position_and_employee_edits_report_labels_and_write_nothing_when_unchanged(by):
    tag = str(int(time.time()))
    parent = by.post("/api/hr/departments", json={"name": f"قسم أعلى {tag}"})
    if parent.status_code != 200:
        pytest.skip("HR is not available for this tenant")
    pdid = parent.json()["id"]
    did = by.post("/api/hr/departments", json={"name": f"قسم اختبار {tag}", "parent_id": pdid}).json()["id"]
    posid = by.post("/api/hr/positions", json={"title": f"مسمى اختبار {tag}", "department_id": did, "grade": "G3", "headcount": 2}).json()["id"]
    emp = by.post("/api/hr/employees", json={"name": "موظف اختبار التسميات", "omani": True, "hire_date": "2024-01-01", "gender": "male", "email": f"lbl{tag}@example.test"})
    eid = emp.json()["id"]
    try:
        before = last_audit(by)["id"]
        assert by.patch(f"/api/hr/departments/{did}", json={"name": f"قسم اختبار {tag}", "parent_id": pdid, "active": True}).json()["changed"] == []
        assert last_audit(by)["id"] == before
        r = by.patch(f"/api/hr/departments/{did}", json={"parent_id": None})        # the upper department is optional: null clears it
        assert r.json()["changed"] == ["parent_id"] and r.json()["changes"][0]["label"] == "القسم الأعلى"
        for bad in ({"name": ""}, {"name": None}, {"active": None}):
            r = by.patch(f"/api/hr/departments/{did}", json=bad)
            assert r.status_code == 400 and "إلزامي" in r.json()["detail"], (bad, r.text)
        assert by.patch(f"/api/hr/departments/{did}", json={"name": f"قسم أعلى {tag}"}).status_code == 409         # taken
        before = last_audit(by)["id"]
        assert by.patch(f"/api/hr/positions/{posid}", json={"grade": "G3", "headcount": 2}).json()["changed"] == []
        assert last_audit(by)["id"] == before
        r = by.patch(f"/api/hr/positions/{posid}", json={"grade": ""})
        assert r.json()["changed"] == ["grade"] and r.json()["changes"][0] == {"field": "grade", "label": "الدرجة", "old": "G3", "new": None}
        for bad in ({"title": ""}, {"headcount": None}, {"active": None}):
            r = by.patch(f"/api/hr/positions/{posid}", json=bad)
            assert r.status_code == 400 and "إلزامي" in r.json()["detail"], (bad, r.text)
        r = by.patch(f"/api/hr/employees/{eid}", json={"phone": "93334444"})
        assert r.json()["changed"] == ["phone"] and r.json()["changes"] == [{"field": "phone", "label": "الهاتف", "personal": True}]
        assert by.patch(f"/api/hr/employees/{eid}", json={"phone": "93334444"}).json()["changed"] == []
    finally:
        _sql("DELETE FROM employees WHERE id=?", (eid,), "bayan", maint=True)
        _sql("DELETE FROM positions WHERE id=?", (posid,), "bayan", maint=True)
        _sql("DELETE FROM departments WHERE id=?", (did,), "bayan", maint=True)
        _sql("DELETE FROM departments WHERE id=?", (pdid,), "bayan", maint=True)
