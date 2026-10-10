"""Unit 7 — reports (ready + custom builder + export + saved + schedules) and marketing (board, campaigns, creatives, sends, alerts)."""
import json
import os
import re
import struct
import tempfile
import zlib

os.environ.setdefault("MABANIQ_DB", os.path.join(tempfile.mkdtemp(), "u7.db"))
os.environ["MABANIQ_FORCE_PW_CHANGE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as A  # noqa: E402
from backend import mail  # noqa: E402
from backend import observability as O  # noqa: E402
from backend.app import app  # noqa: E402
from backend.db import connect  # noqa: E402

CSRF = "csrf-unit7-" + "m" * 30


def login_as(c, user):
    c.cookies.set(A.COOKIE, A.issue_session(user))
    c.cookies.set(A.CSRF_COOKIE, CSRF)
    c.headers["X-CSRF-Token"] = CSRF
    return c


@pytest.fixture()
def cl():
    O.limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        login_as(c, "admin")
        c.post("/api/reset")
        yield c


def png_bytes(w=6, h=6):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes((30, 60, 120)) * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


# ---------------------------------------------------------------- ready reports
def test_catalog_and_every_ready_report_renders(cl):
    cat = cl.get("/api/reports/catalog").json()
    keys = [r["key"] for r in cat["ready"]]
    assert {"portfolio", "sales", "collections", "cash", "inventory", "construction", "funnel", "brokers", "handover", "quotes"} <= set(keys)
    assert any(d["key"] == "installments" for d in cat["datasets"]) and cat["projects"]
    for k in keys:
        r = cl.get(f"/api/reports/ready/{k}")
        assert r.status_code == 200, (k, r.text)
        doc = r.json()
        assert doc["title"] and isinstance(doc["kpis"], list) and isinstance(doc["charts"], list) and isinstance(doc["tables"], list)
        for ch in doc["charts"]:
            assert ch["type"] in ("bar", "line", "pie", "stacked") and len(ch["labels"]) >= 1 and all(len(s["data"]) == len(ch["labels"]) for s in ch["series"]), (k, ch["title"])
        for t in doc["tables"]:
            assert t["columns"] and all(set(t["columns"][0].keys()) >= {"key", "label", "type"} for _ in [0])
    # parameters narrow the report
    pid = cat["projects"][0]["id"]
    one_p = cl.get(f"/api/reports/ready/portfolio?project_id={pid}").json()
    assert len(one_p["tables"][0]["rows"]) == 1 and one_p["params"]["project_id"] == str(pid)
    # permissions: engineer cannot read finance reports but can read the portfolio
    with TestClient(app, base_url="https://testserver") as eng:
        login_as(eng, "engineer")
        assert eng.get("/api/reports/ready/portfolio").status_code == 200
        assert eng.get("/api/reports/ready/collections").status_code == 403
        assert "collections" not in [r["key"] for r in eng.get("/api/reports/catalog").json()["ready"]]


def test_custom_builder_groups_filters_and_rejects_unknown_columns(cl):
    spec = {"dataset": "units", "group_by": [{"col": "status"}], "aggs": [{"fn": "count"}, {"fn": "sum", "col": "price"}, {"fn": "avg", "col": "area"}], "sort": [{"col": "count", "dir": "desc"}],
            "chart": {"type": "pie", "x": "status", "y": ["count"]}, "title": "الوحدات بحسب الحالة"}
    r = cl.post("/api/reports/custom/run", json=spec)
    assert r.status_code == 200, r.text
    doc = r.json()
    t = doc["tables"][0]
    assert [c["key"] for c in t["columns"]] == ["status", "count", "sum_price", "avg_area"]
    assert {row["status"] for row in t["rows"]} <= {"متاحة", "محجوزة", "مباعة"}  # enum labels applied
    assert sum(row["count"] for row in t["rows"]) == 468
    assert doc["charts"][0]["type"] == "pie" and len(doc["charts"][0]["labels"]) == len(t["rows"])
    # filters + date bucket
    spec2 = {"dataset": "bookings", "filters": [{"col": "status", "op": "ne", "value": "cancelled"}, {"col": "price", "op": "gte", "value": 50000}],
             "group_by": [{"col": "created", "bucket": "month"}], "aggs": [{"fn": "count", "label": "حجوزات"}, {"fn": "sum", "col": "price"}], "chart": {"type": "bar"}}
    d2 = cl.post("/api/reports/custom/run", json=spec2).json()
    assert d2["tables"][0]["columns"][0]["key"] == "created_month" and all(re.match(r"^\d{4}-\d{2}$", row["created_month"]) for row in d2["tables"][0]["rows"])
    assert d2["charts"] and d2["charts"][0]["series"][0]["name"] == "حجوزات"
    # plain row listing with a column subset, contains filter and limit
    d3 = cl.post("/api/reports/custom/run", json={"dataset": "units", "columns": ["code", "type", "price"], "filters": [{"col": "type", "op": "contains", "value": "فيلا"}], "limit": 5, "chart": {"type": "none"}}).json()
    assert len(d3["tables"][0]["rows"]) == 5 and all("فيلا" in r["type"] for r in d3["tables"][0]["rows"]) and set(d3["tables"][0]["rows"][0].keys()) == {"code", "type", "price"}
    # injection attempts fail closed
    assert cl.post("/api/reports/custom/run", json={"dataset": "units", "columns": ["price; DROP TABLE units"]}).status_code == 400
    assert cl.post("/api/reports/custom/run", json={"dataset": "units", "group_by": [{"col": "status"}], "aggs": [{"fn": "sum", "col": "type"}]}).status_code == 400
    assert cl.post("/api/reports/custom/run", json={"dataset": "nope"}).status_code == 404
    assert cl.post("/api/reports/custom/run", json={"dataset": "units", "filters": [{"col": "code", "op": "like", "value": "x"}]}).status_code == 422
    # permission on dataset
    with TestClient(app, base_url="https://testserver") as eng:
        login_as(eng, "engineer")
        assert eng.post("/api/reports/custom/run", json={"dataset": "payments"}).status_code == 403


def test_export_csv_pdf_saved_and_schedules(cl):
    csv_ = cl.post("/api/reports/export", json={"format": "csv", "kind": "ready", "ref": "sales"})
    assert csv_.status_code == 200 and csv_.content.startswith("﻿".encode()) and "المشروع" in csv_.content.decode("utf-8")
    pdf = cl.post("/api/reports/export", json={"format": "pdf", "kind": "ready", "ref": "portfolio"})
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-" and len(pdf.content) > 20000
    for key in ("sales", "collections", "funnel", "cash"):
        assert cl.post("/api/reports/export", json={"format": "pdf", "kind": "ready", "ref": key}).status_code == 200, key
    spec = {"dataset": "quotes", "group_by": [{"col": "status"}], "aggs": [{"fn": "count"}], "chart": {"type": "bar"}}
    assert cl.post("/api/reports/export", json={"format": "pdf", "kind": "custom", "spec": spec}).status_code == 200
    # save + run + schedule
    sid = cl.post("/api/reports/saved", json={"name": "مبيعات الربع", "kind": "ready", "ref": "sales", "params": {"from": "2026-01-01"}}).json()["id"]
    cid = cl.post("/api/reports/saved", json={"name": "حالات الوحدات", "kind": "custom", "spec": {"dataset": "units", "group_by": [{"col": "status"}], "aggs": [{"fn": "count"}]}}).json()["id"]
    saved = cl.get("/api/reports/saved").json()
    assert {s["id"] for s in saved} >= {sid, cid}
    run = cl.get(f"/api/reports/saved/{cid}/run").json()
    assert run["title"] == "حالات الوحدات" and run["saved_id"] == cid
    assert cl.post("/api/reports/saved", json={"name": "تقرير وهمي", "kind": "ready", "ref": "nope"}).status_code == 400
    sch = cl.post("/api/reports/schedules", json={"report_id": sid, "cadence": "weekly", "hour": 7, "recipients": "ceo@example.om, cfo@example.om", "format": "pdf"})
    assert sch.status_code == 200, sch.text
    assert cl.post("/api/reports/schedules", json={"report_id": sid, "cadence": "daily", "recipients": "not-an-email"}).status_code == 400
    lst = cl.get("/api/reports/schedules").json()
    assert lst and lst[0]["report_name"] == "مبيعات الربع" and lst[0]["next_run"]
    # due schedules are mailed by the tick (outbox in tests)
    from backend import reports as R
    db = connect()
    db.execute("UPDATE report_schedules SET next_run='2020-01-01T00:00'")
    db.commit()
    before = len(list(mail.outbox_dir().glob("*.json")))
    assert R.run_due_schedules(db) == 1
    files = sorted(mail.outbox_dir().glob("*.json"))
    assert len(files) == before + 2
    m = json.loads(files[-1].read_text(encoding="utf-8"))
    assert m["attachments"][0]["name"].endswith(".pdf") and m["kind"] == "report"
    assert db.execute("SELECT next_run FROM report_schedules WHERE id=?", (sch.json()["id"],)).fetchone()["next_run"] > "2026"
    assert cl.post(f"/api/reports/saved/{sid}/remove").json()["ok"]
    assert all(s["report_id"] != sid for s in cl.get("/api/reports/schedules").json())


# ---------------------------------------------------------------- marketing
def test_marketing_board_classifies_every_project_with_actions(cl):
    b = cl.get("/api/marketing/board").json()
    assert len(b["projects"]) == 5 and sum(b["summary"].values()) == 5
    for p in b["projects"]:
        assert p["status"] in b["status_labels"] and p["actions"] and "total" in p and "demand_ratio" in p
        assert isinstance(p["flags"], list)
    completed = next(p for p in b["projects"] if p["build_pct"] >= 100)
    assert completed["status"] in ("completed", "sold_out")
    with TestClient(app, base_url="https://testserver") as eng:
        login_as(eng, "engineer")
        assert eng.get("/api/marketing/board").status_code == 403


def test_campaign_lifecycle_audience_send_and_attribution(cl):
    meta = cl.get("/api/campaigns/meta").json()
    assert "whatsapp" in meta["channels"] and "slow" in meta["objectives"] and "teaser" in meta["templates"]
    b = cl.get("/api/marketing/board").json()
    proj = next(p for p in b["projects"] if p["available"] > 0)
    bad = cl.post("/api/campaigns", json={"project_id": proj["project_id"], "name": "عرض بفائدة", "objective": "offer", "offer_text": "تقسيط بفائدة 3٪"})
    assert bad.status_code == 400  # Islamic-finance rule
    r = cl.post("/api/campaigns", json={"project_id": proj["project_id"], "name": "حملة إعادة استهداف", "objective": "retarget", "channels": ["whatsapp", "email"], "audience": "leads_all",
                                         "budget": 1500, "start_date": "2026-10-01", "end_date": "2026-10-31", "offer_text": "تأجيل الدفعة الثانية 3 أشهر", "message": "عرض خاص لعملاء المشروع"})
    assert r.status_code == 200, r.text
    camp = r.json()
    assert camp["status"] == "draft" and camp["utm"].startswith("MK") and camp["channel_labels"] == ["واتساب", "بريد"]
    aud = cl.get(f"/api/campaigns/{camp['id']}/audience").json()
    assert aud["count"] >= 1 and aud["recipients"][0]["kind"] == "lead"
    # a lead attributed by UTM + a quote and a booking counted in the metrics
    lead = cl.post("/api/leads", json={"name": "عميل من الحملة", "phone": "+968 9777 8888", "email": "camp@example.om", "project_id": proj["project_id"], "channel": "إنستغرام", "utm": camp["utm"], "budget": 90000}).json()
    assert lead["campaign_id"] == camp["id"]
    pid = proj["project_id"]
    unit = next(u for u in cl.get(f"/api/units?project_id={pid}").json() if u["status"] == "a")
    q = cl.post("/api/quotes", json={"unit_code": unit["code"], "customer_name": "عميل من الحملة", "phone": "+968 9777 8888", "plan": "6040", "lead_id": lead["id"]}).json()
    cl.post(f"/api/quotes/{q['id']}/convert")
    m = cl.get(f"/api/campaigns/{camp['id']}").json()["metrics"]
    assert m["leads"] >= 1 and m["quotes"] >= 1 and m["bookings"] >= 1 and m["cpl"] is not None
    # send: whatsapp → click-to-chat links, email → outbox for those with e-mail; draft becomes active
    w = cl.post(f"/api/campaigns/{camp['id']}/send", json={"channel": "whatsapp", "limit": 5})
    assert w.status_code == 200 and w.json()["sent"] >= 1 and w.json()["items"][0]["wa_url"].startswith("https://wa.me/") and "Business" in w.json()["note"]
    before = len(list(mail.outbox_dir().glob("*.json")))
    e = cl.post(f"/api/campaigns/{camp['id']}/send", json={"channel": "email", "limit": 50}).json()
    assert e["sent"] >= 1 and len(list(mail.outbox_dir().glob("*.json"))) == before + e["sent"]
    assert cl.get(f"/api/campaigns/{camp['id']}").json()["status"] == "active"
    db = connect()
    assert db.execute("SELECT COUNT(*) FROM campaign_sends WHERE campaign_id=?", (camp["id"],)).fetchone()[0] == w.json()["sent"] + e["sent"]
    assert cl.post(f"/api/campaigns/{camp['id']}/status", json={"status": "done"}).json()["status"] == "done"
    assert cl.post(f"/api/campaigns/{camp['id']}/send", json={"channel": "whatsapp"}).status_code == 409
    with TestClient(app, base_url="https://testserver") as fin:
        login_as(fin, "finance")
        assert fin.get("/api/campaigns").status_code == 200
        assert fin.post("/api/campaigns", json={"project_id": pid, "name": "x3", "objective": "launch"}).status_code == 403


def test_creatives_generated_as_png_and_pdf_and_shareable(cl):
    pid = cl.get("/api/projects").json()[0]["id"]
    for template, size in (("teaser", "square"), ("launch", "story"), ("offer", "wide"), ("last_units", "square"), ("progress", "wide"), ("ready", "square")):
        r = cl.post("/api/creatives", json={"project_id": pid, "template": template, "size": size, "offer": "إعفاء من رسوم نقل الملكية", "until": "2026-12-31", "plan": "6040"})
        assert r.status_code == 200, (template, r.text)
        cr = r.json()
        assert cr["png_url"] and cr["pdf_url"] and cr["template_label"]
        png = cl.get(cr["png_url"])
        assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
        pdf = cl.get(cr["pdf_url"])
        assert pdf.content[:5] == b"%PDF-"
    # a background image (uploaded as a campaign asset) and a palette
    bg = cl.post("/api/documents", data={"ref_type": "campaign", "ref_id": "0", "title": "خلفية", "category": "إعلان"}, files={"file": ("bg.png", png_bytes(), "image/png")}).json()["id"]
    cr = cl.post("/api/creatives", json={"project_id": pid, "template": "launch", "size": "square", "bg_document_id": bg, "palette": "green", "headline": "إطلاق المرحلة الثانية"}).json()
    assert cr["bg_document_id"] == bg
    assert cl.post("/api/creatives", json={"project_id": pid, "template": "offer", "offer": "تمويل بفائدة 2٪"}).status_code == 400
    lst = cl.get(f"/api/creatives?project_id={pid}").json()
    assert len(lst) >= 7
    # one-off share: whatsapp link serves the PNG without login, e-mail attaches it
    w = cl.post(f"/api/creatives/{cr['id']}/send", json={"channel": "whatsapp", "to": "+968 9123 0000"}).json()
    assert w["wa_url"].startswith("https://wa.me/96891230000?text=")
    with TestClient(app) as anon:
        got = anon.get(w["link"].split("https://testserver", 1)[1])
        assert got.status_code == 200 and got.content[:8] == b"\x89PNG\r\n\x1a\n"
    e = cl.post(f"/api/creatives/{cr['id']}/send", json={"channel": "email", "to": "lead@example.om"}).json()
    assert e["ok"] and e["to"] == "lead@example.om"
    # PNG dimensions match the requested size
    w_, h_ = struct.unpack(">II", cl.get(lst[-1]["png_url"]).content[16:24])
    assert (w_, h_) in ((1080, 1080), (1080, 1920), (1200, 628))


def test_marketing_alerts_computed_and_persisted_once_per_week(cl):
    al = cl.get("/api/marketing/alerts").json()
    assert isinstance(al, list)
    for a in al:
        assert a["severity"] in ("high", "medium", "low") and a["project"] and a["action"] and a["dedupe"].startswith("mkt:")
    # force a slow-selling project: no plan pace → make a project old with high plan
    db = connect()
    pid = cl.get("/api/projects").json()[0]["id"]
    db.execute("UPDATE projects SET planned_monthly_sales=40, build_pct=50 WHERE id=?", (pid,))
    db.execute("UPDATE bookings SET created='2025-01-15' WHERE unit_id IN (SELECT id FROM units WHERE project_id=?)", (pid,))
    db.commit()
    al2 = cl.get("/api/marketing/alerts").json()
    assert any(a["key"] == f"slow:{pid}" for a in al2), [a["key"] for a in al2]
    board = cl.get("/api/marketing/board").json()
    assert next(p for p in board["projects"] if p["project_id"] == pid)["status"] == "slow"
    n1 = cl.post("/api/marketing/alerts/run").json()["created"]
    assert n1 >= 1
    assert cl.post("/api/marketing/alerts/run").json()["created"] == 0  # deduplicated for the week
    notes = cl.get("/api/notifications").json()
    assert any(str(n.get("title", "")).startswith("تنبيه تسويقي") for n in notes)
    from backend import jobs
    out = jobs.tick()
    assert set(out) >= {"retention", "reports", "marketing_alerts"}
