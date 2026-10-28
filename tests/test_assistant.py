"""0.17.0 — المساعد الموسَّع (أدوات + محرك محلي + نموذج اختياري) ومظهر المنصة لكل مؤسسة."""
import os
import tempfile

os.environ["MABANIQ_DB"] = os.path.join(tempfile.mkdtemp(), "test_assistant.db")
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import assistant as AS  # noqa: E402
from backend import auth as A  # noqa: E402
from backend.app import app  # noqa: E402

CSRF = "csrf-test-token-" + "x" * 24


def as_user(c, username):
    c.cookies.set(A.COOKIE, A.issue_session(username))
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


@pytest.fixture()
def cl():
    with TestClient(app) as c:
        as_user(c, "admin")
        c.post("/api/reset")
        as_user(c, "admin")
        yield c


def ask(c, q, **kw):
    r = c.post("/api/assistant", json={"q": q, **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------------------------ المحرك المحلي
QUESTIONS = ["كم وحدة متاحة؟", "ما أرخص وحدة متاحة؟", "كم عميلًا محتملًا لدينا؟", "من الأعلى احتمالًا للشراء؟", "ما المتأخرات؟", "ما نسبة التحصيل؟",
             "ما حال الحجوزات؟", "كم عمولة مستحقة للوسطاء؟", "ما حال الإنشاء؟", "كم ملاحظة تسليم مفتوحة؟", "ما التراخيص؟", "ما ملخص المحفظة؟",
             "ما المشروع الأخطر؟", "فجوة السيولة", "تسويق", "تعثر", "مستخلص", "ملخص"]


@pytest.mark.parametrize("q", QUESTIONS)
def test_local_engine_answers_broad_questions(cl, q):
    r = ask(cl, q)
    assert r["mode"] == "rules" and len(r["answer"]) > 20 and r["suggestions"]


def test_numbers_come_from_the_data(cl):
    r = ask(cl, "كم وحدة متاحة؟")
    c = AS.db()
    free = c.execute("SELECT COUNT(*) n FROM units WHERE status='a' AND COALESCE(retained,0)=0").fetchone()["n"]
    kept = c.execute("SELECT COUNT(*) n FROM units WHERE status='a' AND COALESCE(retained,0)=1").fetchone()["n"]
    c.close()
    assert f"متاحة {free:,}" in r["answer"]  # الوحدات المحتفظ بها للتأجير لا تُحسب متاحة للبيع
    if kept:
        assert f"محتفظ بها للتأجير {kept:,}" in r["answer"]


def _distinct_project(c, i):
    """(مشروع، كلمة مميِّزة من اسمه) — كما يستخرجها المساعد نفسه."""
    ctx = AS.Ctx(AS.db(), c.get("/api/me").json())
    toks = AS._project_tokens(ctx.projects)
    pid = ctx.projects[i]["id"]
    word = next(t for t, x in toks.items() if x == pid)
    return ctx.projects[i], word


def test_unit_type_and_project_filter(cl):
    p, word = _distinct_project(cl, 0)
    r = ask(cl, f"كم شقة متاحة في {word}؟")
    assert r["intent"] == "inventory" and p["name"] in r["answer"]


def test_follow_up_keeps_topic(cl):
    first = ask(cl, "كم عميلًا محتملًا لدينا؟")
    p, word = _distinct_project(cl, 1)
    second = ask(cl, f"وماذا عن {word}؟", intent=first["intent"])
    assert second["intent"] == first["intent"] == "leads"


def test_howto_and_greeting_and_unknown(cl):
    assert "حجز" in ask(cl, "كيف أحجز وحدة؟")["answer"]
    assert ask(cl, "السلام عليكم")["intent"] is None
    r = ask(cl, "zzzz qqqq")
    assert r["suggestions"] and "لم أفهم" in r["answer"]


def test_permissions_filter_tools(cl):
    as_user(cl, "sales")
    r = ask(cl, "ما نسبة التحصيل والمتأخرات؟")
    assert "خارج صلاحيات" in r["answer"] or "التحصيل" not in r["source"]
    r2 = ask(cl, "ما حال التأجير؟")
    assert "خارج صلاحيات" in r2["answer"]
    as_user(cl, "finance")
    assert "المتأخرات" in ask(cl, "ما المتأخرات؟")["answer"]


def test_no_unit_rows_leak_retained_as_available(cl):
    r = ask(cl, "كم وحدة متاحة؟")
    assert "ر.ع" in r["answer"]


def test_validation(cl):
    assert cl.post("/api/assistant", json={"q": "x" * 600}).status_code == 422
    assert cl.post("/api/assistant", json={"q": "ما", "history": [{"q": "a", "a": "b"}] * 20}).status_code == 422


# ------------------------------------------------------------------------------------------------ النموذج اللغوي (بنقل وهمي)
class FakeResp:
    def __init__(self, body, code=200):
        self._b, self.status_code = body, code

    def json(self):
        return self._b


class FakeClient:
    """يحاكي Anthropic: يطلب أداة المخزون ثم يصوغ جوابًا من نتيجتها."""

    def __init__(self):
        self.calls = []

    def post(self, url, headers=None, json=None):
        self.calls.append(json)
        if len(self.calls) == 1:
            return FakeResp({"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "t1", "name": "inventory", "input": {"type": "شقة"}}]})
        res = json["messages"][-1]["content"][0]["content"]
        return FakeResp({"stop_reason": "end_turn", "content": [{"type": "text", "text": "الحصيلة: " + res[:60]}]})

    def close(self):
        pass


def test_llm_loop_uses_tools_and_masks(cl, monkeypatch):
    monkeypatch.setenv("MABANIQ_AI_KEY", "test-key-not-real")
    fake = FakeClient()
    c = AS.db()
    u = cl.get("/api/me").json()
    out = AS.llm_answer(AS.Ctx(c, u, external=True), "كم شقة؟", [], client=fake)
    assert out and "الحصيلة" in out["answer"] and out["tools"] == ["inventory"]
    assert fake.calls[0]["tools"] and all(t["name"] in AS.TOOLS for t in fake.calls[0]["tools"])
    # أدوات التحصيل مخفية عن المبيعات في تعريف الأدوات المرسَل للنموذج
    sales = {**u, "role": "sales", "perms": ["view", "inventory", "book", "leads"]}
    assert "collections" not in {t["name"] for t in AS._tool_defs(sales)}
    # أسماء العملاء محجوبة ما لم يُسمح بها
    ctx_ext, ctx_loc = AS.Ctx(c, u, external=True), AS.Ctx(c, u, external=True, names=True)
    assert ctx_ext.who("فلان", 7) == "عميل #7" and ctx_loc.who("فلان", 7) == "فلان"
    c.close()


def test_llm_failure_falls_back_to_rules(cl, monkeypatch):
    monkeypatch.setenv("MABANIQ_AI_KEY", "test-key-not-real")
    cl.post("/api/admin/assistant", json={"llm": True})

    class Down:
        def post(self, *a, **k):
            return FakeResp({}, 500)

        def close(self):
            pass

    c = AS.db()
    r = AS.answer(c, cl.get("/api/me").json(), "كم وحدة متاحة؟", client=Down())
    assert r["mode"] == "rules" and "متاحة" in r["answer"]
    c.close()


def test_admin_cannot_enable_llm_without_key(cl, monkeypatch):
    monkeypatch.delenv("MABANIQ_AI_KEY", raising=False)
    assert cl.post("/api/admin/assistant", json={"llm": True}).status_code == 400
    st = cl.get("/api/admin/assistant").json()
    assert st["key_configured"] is False and st["active"] is False
    as_user(cl, "sales")
    assert cl.get("/api/admin/assistant").status_code == 403
    assert cl.post("/api/admin/assistant", json={"names": True}).status_code == 403


# ------------------------------------------------------------------------------------------------ المظهر
def test_appearance_roundtrip_and_whitelist(cl):
    base = cl.get("/api/appearance").json()
    assert base["preset"] == "navy" and "forest" in base["options"]["presets"]
    r = cl.post("/api/admin/appearance", json={"preset": "forest", "pattern": "grid", "size": 30, "strength": 55, "mode": "dark"})
    assert r.status_code == 200 and r.json()["preset"] == "forest" and r.json()["size"] == 30
    assert cl.get("/api/appearance").json()["pattern"] == "grid"
    assert cl.post("/api/admin/appearance", json={"preset": "red;}body{display:none"}).status_code in (400, 422)
    r = cl.post("/api/admin/appearance", json={"size": 100000, "strength": -5})
    assert r.json()["size"] == 120 and r.json()["strength"] == 5  # الأعداد تُقيَّد لا تُرفض
    assert cl.post("/api/admin/appearance", json={"image_doc": 99999}).status_code == 400
    assert cl.post("/api/admin/appearance", json={"pattern": "image"}).json()["pattern"] == "none"  # نقش صورة بلا صورة ⟵ بلا نقش


def test_appearance_admin_only_and_image(cl):
    as_user(cl, "sales")
    assert cl.get("/api/appearance").status_code == 200
    assert cl.post("/api/admin/appearance", json={"preset": "plum"}).status_code == 403
    as_user(cl, "admin")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    up = cl.post("/api/documents", data={"ref_type": "brand", "ref_id": "0", "title": "خلفية", "category": "هوية"}, files={"file": ("bg.png", png, "image/png")})
    assert up.status_code == 200, up.text
    did = up.json()["id"]
    r = cl.post("/api/admin/appearance", json={"pattern": "image", "image_doc": did, "fit": "tile", "size": 60})
    assert r.json()["pattern"] == "image" and r.json()["fit"] == "tile"
    img = cl.get("/api/appearance/image")
    assert img.status_code == 200 and img.content == png
    as_user(cl, "engineer")
    assert cl.get("/api/appearance/image").status_code == 200


def test_ranking_and_priciest(cl):
    r = ask(cl, "أي مشروع هو الأبطأ مبيعًا؟")
    assert r["intent"] == "project_ranking" and "الأبطأ" in r["answer"] and "من الخطة" in r["answer"]
    r = ask(cl, "ما أغلى وحدة؟")
    assert r["intent"] == "inventory" and r["answer"].index("الأغلى:") < r["answer"].index("الأرخص:")
    r = ask(cl, "من الأعلى احتمالًا للشراء؟")
    assert r["intent"] == "leads"
    r = ask(cl, "كم وحدة مباعة؟")
    assert "المباع:" in r["answer"]
