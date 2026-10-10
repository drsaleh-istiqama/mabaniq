"""Mabaniq — project marketing (Unit 7): marketing board, campaigns, ad creatives, market-movement alerts.

* **Board** — every project is classified from live data (launch · steady · near_complete · slow · completed · sold_out)
  with the signals behind the verdict (pace vs plan, demand ratio from the pricing engine, lead flow, conversion, stock age,
  unsold value) and a catalogue of professional actions for that state. Nothing here changes prices — pricing decisions stay in
  the inventory screen; marketing proposes.
* **Campaigns** — objective, channel mix, audience segment (leads by stage/project, past customers for referrals, brokers),
  budget and dates, an offer that is never an interest-bearing one, a UTM code for attribution (`leads.campaign_id`), and
  measured results: leads, quotes, bookings, cost per lead, value.
* **Creatives** — `adgen.compose` renders teaser/launch/offer/last-units/progress/ready visuals as PNG + PDF stored in the
  validated document store; they are downloadable, attachable to e-mail and shareable through signed links (WhatsApp).
* **Sending** — e-mail to recipients who have an address; WhatsApp as click-to-chat links per recipient (no Business API yet,
  stated in the response); every send is recorded in `campaign_sends` and the audit log.
* **Alerts** — rules over the same signals, evaluated on demand and persisted daily by the background tick as staff
  notifications (deduplicated per rule, project and week).
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import adgen, mail
from . import engines as E
from .auth import need, need_any
from .common import act_as, audit, db, now_s, rows, today
from .db import TENANT, connect, tenants
from .modules import PLAN_LABEL, one

router = APIRouter()
READ = ("leads", "inventory", "reports", "finance")
WRITE = "leads"
STATUS_LABEL = {"launch": "إطلاق", "steady": "مستقر", "near_complete": "شبه مكتمل", "slow": "ضعيف البيع", "completed": "مكتمل بمتبقٍ", "sold_out": "مُباع بالكامل"}
ACTIONS = {
    "launch": [("حملة إطلاق متعددة القنوات", "واتساب + إنستغرام + الوسطاء خلال أول 30 يومًا مع رسالة واحدة وعرض إطلاق واضح"),
               ("خطة سداد مرنة للإطلاق", "تقسيط أطول أو عربون أقل بلا أي فائدة — الحافز في الهيكل لا في الربا"),
               ("يوم مفتوح/معاينة النموذج", "دعوة العملاء المحتملين من مرحلة «مؤهَّل» فأعلى مع عرض سعر جاهز لكل زائر"),
               ("تفعيل الوسطاء", "عمولة إطلاق مؤقتة وتزويدهم بالمخططات والإعلانات الجاهزة")],
    "steady": [("محتوى تقدم البناء الشهري", "إعلان «إنجاز X٪» يحافظ على الزخم ويطمئن المشترين على الخارطة"),
               ("برنامج إحالة للملاك", "مكافأة غير نقدية أو خصم على رسوم الخدمة لكل إحالة تتحوّل إلى حجز"),
               ("رعاية العملاء المتوقفين", "تواصل مع من لم يُتابَع خلال 14 يومًا بعرض سعر محدّث")],
    "near_complete": [("حملة «جاهزة للسكن»", "تركيز على التسليم القريب والمعاينة الفعلية للوحدات المكتملة"),
                      ("باقة الوحدات المتبقية", "موقف/مخزن/تشطيب إضافي مع الوحدة بدل خفض السعر"),
                      ("تمويل مرابحة مع بنك شريك", "تسهيل التملك عبر خطة مرابحة بنكية للجاهز"),
                      ("استهداف المستأجرين في المنطقة", "رسالة «من الإيجار إلى التملك» بحساب القسط مقابل الإيجار")],
    "slow": [("مراجعة التسعير بحسب الشرائح", "محرك التسعير يحدد الشرائح الراكدة؛ المراجعة من شاشة المخزون لا من هنا"),
             ("حوافز هيكلية غير ربوية", "تأجيل دفعة، أو تقسيط حتى التسليم، أو إعفاء من رسوم نقل الملكية"),
             ("إعادة استهداف العملاء المتوقفين", "حملة بريد/واتساب لمن توقفوا في مرحلتي المعاينة والتفاوض"),
             ("تحليل سبب الضعف", "شريحة بعينها؟ إطلالة؟ سعر المتر مقارنة بالجوار؟ قبل أي خصم"),
             ("دفعة وسطاء مركّزة", "عمولة مؤقتة أعلى على الشرائح الراكدة فقط")],
    "completed": [("حملة «تملّك فورًا»", "الوحدات الجاهزة بسند ملكية وتسليم خلال أيام"),
                  ("عرض الوحدات المتبقية للمستثمرين", "عائد الإيجار التقديري وتأجير مُدار عبر المنصة")],
    "sold_out": [("توثيق النجاح", "محتوى «بيع بالكامل» يدعم إطلاق المشروع التالي")],
}


# ---------------------------------------------------------------- signals + board
def project_signals(c, p) -> dict:
    t = today()
    d30 = (t - dt.timedelta(days=30)).isoformat()
    d90 = (t - dt.timedelta(days=90)).isoformat()
    units = c.execute("SELECT COUNT(*) total, SUM(CASE WHEN status='a' THEN 1 ELSE 0 END) available, SUM(CASE WHEN status='a' THEN price ELSE 0 END) unsold_value, MIN(price) min_price FROM units WHERE project_id=?", (p["id"],)).fetchone()
    pace30 = c.execute("SELECT COUNT(*) FROM bookings b JOIN units u ON u.id=b.unit_id WHERE u.project_id=? AND b.status!='cancelled' AND b.created>=?", (p["id"], d30)).fetchone()[0]
    pace90 = c.execute("SELECT COUNT(*) FROM bookings b JOIN units u ON u.id=b.unit_id WHERE u.project_id=? AND b.status!='cancelled' AND b.created>=?", (p["id"], d90)).fetchone()[0]
    first = c.execute("SELECT MIN(b.created) FROM bookings b JOIN units u ON u.id=b.unit_id WHERE u.project_id=?", (p["id"],)).fetchone()[0]
    leads30 = c.execute("SELECT COUNT(*) FROM leads WHERE project_id=? AND created>=?", (p["id"], d30)).fetchone()[0]
    leads_prev = c.execute("SELECT COUNT(*) FROM leads WHERE project_id=? AND created>=? AND created<?", (p["id"], (t - dt.timedelta(days=60)).isoformat(), d30)).fetchone()[0]
    leads90 = c.execute("SELECT COUNT(*) FROM leads WHERE project_id=? AND created>=?", (p["id"], d90)).fetchone()[0]
    stale = c.execute("SELECT COUNT(*) FROM leads WHERE project_id=? AND stage BETWEEN 1 AND 3 AND (last_contact IS NULL OR last_contact<?)", (p["id"], (t - dt.timedelta(days=14)).isoformat())).fetchone()[0]
    quotes30 = c.execute("SELECT COUNT(*) FROM quotes q JOIN units u ON u.id=q.unit_id WHERE u.project_id=? AND q.created>=?", (p["id"], d30)).fetchone()[0]
    segs = E.pricing(c, p["id"]) or []
    demand = round(sum(s["demand_ratio"] for s in segs) / len(segs), 2) if segs else 0
    cuts = sum(1 for s in segs if s["suggested_change"] < 0)
    raises = sum(1 for s in segs if s["suggested_change"] > 0)
    total = units["total"] or 0
    avail = units["available"] or 0
    sold_pct = round(100 * (total - avail) / total, 1) if total else 0
    planned = float(p["planned_monthly_sales"] or 0)
    pace_ratio = round(pace30 / planned, 2) if planned else None
    days_on_market = (t - dt.date.fromisoformat(first[:10])).days if first else 0
    conv90 = round(100 * pace90 / leads90, 1) if leads90 else None
    build = float(p["build_pct"] or 0)
    flags = []
    if total and avail == 0:
        status = "sold_out"
    else:
        status = "steady"
        if p["completed"] or build >= 100:
            status = "completed"
        elif build >= 80:
            status = "near_complete"
        if build < 15 or days_on_market < 90:
            status = "launch" if status == "steady" else status
        if avail and planned and pace30 < 0.6 * planned and days_on_market >= 60:
            status = "slow"
            flags.append(f"وتيرة البيع {pace30} شهريًا مقابل {planned:g} مخططة")
        if cuts >= 2:
            flags.append(f"{cuts} شرائح يقترح محرك التسعير خفضها/تحفيزها")
        if raises >= 2:
            flags.append(f"{raises} شرائح طلبها مرتفع (فرصة رفع سعر أو إطلاق مرحلة)")
        if leads_prev and leads30 < 0.5 * leads_prev:
            flags.append(f"تراجع العملاء الجدد: {leads30} مقابل {leads_prev} في الشهر السابق")
        if stale >= 5:
            flags.append(f"{stale} عملاء متوقفون بلا تواصل منذ 14 يومًا")
        if status == "near_complete" and sold_pct < 80:
            flags.append(f"المشروع قارب الاكتمال و{100 - sold_pct:g}٪ من وحداته غير مباعة")
    return {"project_id": p["id"], "project": p["name"], "location": p["location"], "kind": p["kind"], "status": status, "status_label": STATUS_LABEL[status],
            "total": total, "available": avail, "sold_pct": sold_pct, "build_pct": build, "unsold_value": units["unsold_value"] or 0, "price_from": units["min_price"],
            "pace30": pace30, "pace90": pace90, "planned_monthly": planned, "pace_ratio": pace_ratio, "days_on_market": days_on_market, "leads30": leads30, "leads_prev": leads_prev,
            "stale_leads": stale, "quotes30": quotes30, "conversion90": conv90, "demand_ratio": demand, "cut_segments": cuts, "raise_segments": raises, "handover": p["handover"],
            "flags": flags, "actions": [{"title": a, "detail": d} for a, d in ACTIONS[status]]}


@router.get("/api/marketing/board")
def board(u=Depends(need_any(*READ))):
    c = db()
    out = [project_signals(c, p) for p in rows(c.execute("SELECT * FROM projects ORDER BY id"))]
    camp = {r["project_id"]: r["n"] for r in rows(c.execute("SELECT project_id, COUNT(*) n FROM campaigns WHERE status='active' GROUP BY project_id"))}
    for s in out:
        s["active_campaigns"] = camp.get(s["project_id"], 0)
    summary = {k: sum(1 for s in out if s["status"] == k) for k in STATUS_LABEL}
    return {"projects": out, "summary": summary, "status_labels": STATUS_LABEL}


# ---------------------------------------------------------------- campaigns
OBJECTIVES = {"launch": "إطلاق", "near_complete": "جاهزة للسكن", "slow": "تنشيط مشروع ضعيف البيع", "retarget": "إعادة استهداف", "referral": "إحالة", "broker": "تفعيل الوسطاء", "offer": "عرض محدود", "awareness": "وعي بالعلامة"}
CHANNELS = {"whatsapp": "واتساب", "email": "بريد", "sms": "رسائل نصية", "instagram": "إنستغرام", "snapchat": "سناب شات", "tiktok": "تيك توك", "google": "إعلانات بحث", "brokers": "الوسطاء", "openday": "يوم مفتوح", "outdoor": "لوحات/معارض"}
SEGMENTS = {"leads_new": "عملاء محتملون جدد (جديد/مؤهَّل)", "leads_warm": "عملاء في المعاينة/التفاوض", "leads_stale": "عملاء متوقفون 14 يومًا", "leads_all": "كل العملاء المحتملين للمشروع",
            "customers": "ملاك/مشترون حاليون (إحالة)", "brokers": "الوسطاء النشطون", "quotes_open": "أصحاب عروض الأسعار السارية"}


class CampaignIn(BaseModel):
    project_id: int
    name: str = Field(min_length=3, max_length=100)
    objective: str = Field(pattern="^(launch|near_complete|slow|retarget|referral|broker|offer|awareness)$")
    channels: list[str] = Field(default_factory=list, max_length=10)
    audience: str = Field(default="leads_all", pattern="^(leads_new|leads_warm|leads_stale|leads_all|customers|brokers|quotes_open)$")
    budget: float = Field(default=0, ge=0, le=10_000_000)
    start_date: str | None = None
    end_date: str | None = None
    offer_text: str | None = Field(default=None, max_length=300)
    message: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=600)


def _utm(c) -> str:
    for _ in range(20):
        code = "MK" + secrets.token_hex(3).upper()
        if not c.execute("SELECT 1 FROM campaigns WHERE utm=?", (code,)).fetchone():
            return code
    raise HTTPException(500, "تعذّر توليد رمز الحملة")


def _forbidden_offer(text: str | None) -> bool:
    t = (text or "").replace("ـ", "")
    return any(w in t for w in ("فائدة", "فوائد", "بفائدة", "نسبة فائدة", "ربا"))


def campaign_row(c, cid: int) -> dict:
    r = dict(one(c, "SELECT ca.*, p.name project FROM campaigns ca JOIN projects p ON p.id=ca.project_id WHERE ca.id=?", (cid,), "الحملة غير موجودة"))
    r["channels"] = json.loads(r["channels"] or "[]")
    r["channel_labels"] = [CHANNELS.get(x, x) for x in r["channels"]]
    r["objective_label"] = OBJECTIVES.get(r["objective"], r["objective"])
    r["audience_label"] = SEGMENTS.get(r["audience"], r["audience"])
    leads = rows(c.execute("SELECT id FROM leads WHERE campaign_id=?", (cid,)))
    lids = [x["id"] for x in leads]
    q = ",".join("?" * len(lids)) if lids else "NULL"
    bookings = c.execute(f"SELECT COUNT(*) n, COALESCE(SUM(price),0) v FROM bookings WHERE lead_id IN ({q}) AND status!='cancelled'", lids).fetchone() if lids else {"n": 0, "v": 0}
    quotes = c.execute(f"SELECT COUNT(*) FROM quotes WHERE lead_id IN ({q})", lids).fetchone()[0] if lids else 0
    sends = c.execute("SELECT COUNT(*) n, COUNT(DISTINCT recipient) r FROM campaign_sends WHERE campaign_id=?", (cid,)).fetchone()
    r["metrics"] = {"leads": len(lids), "quotes": quotes, "bookings": bookings["n"], "value": bookings["v"], "sends": sends["n"], "recipients": sends["r"],
                    "cpl": round(float(r["budget"] or 0) / len(lids), 1) if lids and r["budget"] else None,
                    "conversion": round(100 * bookings["n"] / len(lids), 1) if lids else None}
    r["creatives"] = rows(c.execute("SELECT id, template, size, headline, document_id, created FROM creatives WHERE campaign_id=? ORDER BY id DESC", (cid,)))
    return r


@router.get("/api/campaigns")
def campaigns_list(u=Depends(need_any(*READ))):
    c = db()
    return [campaign_row(c, r["id"]) for r in rows(c.execute("SELECT id FROM campaigns ORDER BY id DESC"))]


@router.get("/api/campaigns/meta")
def campaigns_meta(u=Depends(need_any(*READ))):
    return {"objectives": OBJECTIVES, "channels": CHANNELS, "segments": SEGMENTS, "templates": {k: v["label"] for k, v in adgen.TEMPLATES.items()},
            "sizes": {k: v[2] for k, v in adgen.SIZES.items()}, "palettes": list(adgen.PALETTES.keys())}


@router.post("/api/campaigns")
def campaign_create(body: CampaignIn, u=Depends(act_as(WRITE))):
    c = db()
    p = one(c, "SELECT id, name FROM projects WHERE id=?", (body.project_id,), "المشروع غير موجود")
    if _forbidden_offer(body.offer_text) or _forbidden_offer(body.message):
        raise HTTPException(400, "لا تُقبل عروض بفائدة ربوية — الحوافز هيكلية (تأجيل، تقسيط، إعفاء رسوم، باقات)")
    bad = [x for x in body.channels if x not in CHANNELS]
    if bad:
        raise HTTPException(400, f"قناة غير معروفة: {bad[0]}")
    utm = _utm(c)
    cid = c.execute("""INSERT INTO campaigns(project_id,name,objective,channels,audience,budget,start_date,end_date,offer_text,message,status,utm,created_by,created,notes)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (body.project_id, body.name, body.objective, json.dumps(body.channels), body.audience, body.budget, body.start_date, body.end_date, body.offer_text, body.message,
                     "draft", utm, u["name"], now_s(), body.notes)).lastrowid
    audit(c, "إنشاء حملة تسويقية", f"{body.name} ({OBJECTIVES[body.objective]}) للمشروع {p['name']} · {utm}")
    c.commit()
    return campaign_row(c, cid)


@router.get("/api/campaigns/{cid}")
def campaign_get(cid: int, u=Depends(need_any(*READ))):
    return campaign_row(db(), cid)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(draft|active|paused|done)$")


@router.post("/api/campaigns/{cid}/status")
def campaign_status(cid: int, body: StatusIn, u=Depends(act_as(WRITE))):
    c = db()
    r = campaign_row(c, cid)
    c.execute("UPDATE campaigns SET status=? WHERE id=?", (body.status, cid))
    audit(c, "تغيير حالة حملة", f"{r['name']} ⟵ {body.status}")
    c.commit()
    return campaign_row(c, cid)


def audience_rows(c, cid: int) -> list[dict]:
    r = campaign_row(c, cid)
    seg, pid, t = r["audience"], r["project_id"], today()
    if seg.startswith("leads"):
        cond = {"leads_new": "l.stage<=1", "leads_warm": "l.stage IN (2,3)", "leads_stale": "l.stage BETWEEN 1 AND 3 AND (l.last_contact IS NULL OR l.last_contact<?)", "leads_all": "1=1"}[seg]
        args = [pid] + ([(t - dt.timedelta(days=14)).isoformat()] if seg == "leads_stale" else [])
        return [{"kind": "lead", "id": x["id"], "name": x["name"], "phone": x["phone"], "email": x["email"], "stage": x["stage"]}
                for x in rows(c.execute(f"SELECT l.id, l.name, l.phone, l.email, l.stage FROM leads l WHERE l.project_id=? AND {cond} ORDER BY l.score DESC LIMIT 500", args))]
    if seg == "customers":
        return [{"kind": "customer", "id": x["id"], "name": x["name"], "phone": x["phone"], "email": x["email"]} for x in
                rows(c.execute("SELECT DISTINCT cu.id, cu.name, cu.phone, cu.email FROM customers cu JOIN bookings b ON b.customer_id=cu.id WHERE b.status!='cancelled' AND cu.erased_at IS NULL LIMIT 500"))]
    if seg == "brokers":
        return [{"kind": "broker", "id": x["id"], "name": x["name"], "phone": x["phone"], "email": None} for x in rows(c.execute("SELECT id, name, phone FROM brokers WHERE active=1"))]
    if seg == "quotes_open":
        return [{"kind": "quote", "id": x["id"], "name": x["customer_name"], "phone": x["phone"], "email": x["email"]} for x in
                rows(c.execute("SELECT q.id, q.customer_name, q.phone, q.email FROM quotes q JOIN units u ON u.id=q.unit_id WHERE u.project_id=? AND q.status='issued' AND q.valid_until>=?", (pid, t.isoformat())))]
    return []


@router.get("/api/campaigns/{cid}/audience")
def campaign_audience(cid: int, u=Depends(need_any(*READ))):
    a = audience_rows(db(), cid)
    return {"count": len(a), "with_email": sum(1 for x in a if x.get("email")), "with_phone": sum(1 for x in a if x.get("phone")), "recipients": a}


class SendIn(BaseModel):
    channel: str = Field(pattern="^(email|whatsapp)$")
    creative_id: int | None = None
    message: str | None = Field(default=None, max_length=1000)
    limit: int = Field(default=200, ge=1, le=500)


def _digits(phone: str | None) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


@router.post("/api/campaigns/{cid}/send")
def campaign_send(cid: int, body: SendIn, request: Request, u=Depends(act_as(WRITE))):
    c = db()
    camp = campaign_row(c, cid)
    if camp["status"] not in ("active", "draft"):
        raise HTTPException(409, "الحملة متوقفة أو منتهية")
    text = (body.message or camp["message"] or f"{camp['project']}: {camp['offer_text'] or camp['name']}").strip()
    if _forbidden_offer(text):
        raise HTTPException(400, "الرسالة تذكر فائدة ربوية")
    link = None
    attach = []
    if body.creative_id:
        cr = one(c, "SELECT * FROM creatives WHERE id=?", (body.creative_id,), "الإعلان غير موجود")
        d = one(c, "SELECT * FROM documents WHERE id=?", (cr["document_id"],))
        from .modules2 import _docs_dir
        attach = [(d["filename"], (_docs_dir() / d["stored"]).read_bytes(), d["mime"])]
        from .paperwork import _public_url
        token = secrets.token_urlsafe(24)
        import hashlib
        import time
        c.execute("INSERT INTO share_links(token_hash,kind,ref_id,expires,created,created_by) VALUES(?,?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), "file", d["id"], time.time() + 30 * 86400, time.time(), u["name"]))
        link = f"{_public_url(request)}/d/{TENANT.get()}/{token}"
    aud = audience_rows(c, cid)[: body.limit]
    utm_note = f" [{camp['utm']}]"
    results = {"channel": body.channel, "total": len(aud), "sent": 0, "skipped": 0, "items": []}
    for r in aud:
        if body.channel == "email":
            if not r.get("email"):
                results["skipped"] += 1
                continue
            if not mail.available():
                raise HTTPException(503, "خدمة البريد غير مهيّأة")
            mail.send(r["email"], f"{camp['project']} — {camp['name']}", f"مرحبًا {r['name']}،\n\n{text}{utm_note}", link, "عرض الإعلان", kind="campaign", attachments=attach)
            c.execute("INSERT INTO campaign_sends(campaign_id,channel,recipient,lead_id,creative_id,status,at,by_user) VALUES(?,?,?,?,?,?,?,?)",
                      (cid, "email", r["email"], r["id"] if r["kind"] == "lead" else None, body.creative_id, "sent", now_s(), u["name"]))
            results["sent"] += 1
        else:
            ph = _digits(r.get("phone"))
            if len(ph) < 8:
                results["skipped"] += 1
                continue
            msg = f"مرحبًا {r['name']}، {text}{(' ' + link) if link else ''}{utm_note}"
            c.execute("INSERT INTO wa_messages(phone,direction,body,at,lead_id,engine) VALUES(?,?,?,?,?,?)", (r.get("phone") or ph, "out", msg, now_s(), r["id"] if r["kind"] == "lead" else None, "campaign"))
            c.execute("INSERT INTO campaign_sends(campaign_id,channel,recipient,lead_id,creative_id,status,at,by_user) VALUES(?,?,?,?,?,?,?,?)",
                      (cid, "whatsapp", ph, r["id"] if r["kind"] == "lead" else None, body.creative_id, "queued", now_s(), u["name"]))
            results["items"].append({"name": r["name"], "phone": ph, "wa_url": f"https://wa.me/{ph}?text={urlquote(msg)}"})
            results["sent"] += 1
    if camp["status"] == "draft":
        c.execute("UPDATE campaigns SET status='active' WHERE id=?", (cid,))
    audit(c, "إرسال حملة", f"{camp['name']} عبر {body.channel}: {results['sent']} مستلمًا، تخطّي {results['skipped']}")
    c.commit()
    if body.channel == "whatsapp":
        results["note"] = "روابط «انقر للمراسلة» تُفتح من واتساب على جهازك واحدًا واحدًا؛ الإرسال الآلي الجماعي يحتاج حساب WhatsApp Business API (قرار مالك)."
    return results


# ---------------------------------------------------------------- creatives
class CreativeIn(BaseModel):
    project_id: int
    campaign_id: int | None = None
    template: str = Field(pattern="^(teaser|launch|offer|last_units|progress|ready)$")
    size: str = Field(default="square", pattern="^(square|story|wide)$")
    palette: str = Field(default="gold", pattern="^(gold|green|blue|sand)$")
    headline: str | None = Field(default=None, max_length=120)
    subline: str | None = Field(default=None, max_length=160)
    cta: str | None = Field(default=None, max_length=80)
    offer: str | None = Field(default=None, max_length=160)
    until: str | None = None
    bg_document_id: int | None = None
    plan: str | None = Field(default=None, pattern="^(milestone|6040|murabaha)$")


def project_facts(c, pid: int) -> dict:
    p = dict(one(c, "SELECT * FROM projects WHERE id=?", (pid,), "المشروع غير موجود"))
    u = c.execute("SELECT MIN(CASE WHEN status='a' THEN price END) price_from, SUM(CASE WHEN status='a' THEN 1 ELSE 0 END) available FROM units WHERE project_id=?", (pid,)).fetchone()
    types = [r["type"] for r in rows(c.execute("SELECT DISTINCT type FROM units WHERE project_id=? ORDER BY type", (pid,)))]
    p.update({"price_from": u["price_from"], "available": u["available"], "types": " · ".join(types[:3])})
    return p


@router.post("/api/creatives")
def creative_create(body: CreativeIn, u=Depends(act_as(WRITE))):
    from .modules2 import _docs_dir, store_upload
    from .paperwork import brand as brand_of
    c = db()
    if _forbidden_offer(body.offer) or _forbidden_offer(body.headline) or _forbidden_offer(body.subline):
        raise HTTPException(400, "لا تُقبل صياغات بفائدة ربوية")
    p = project_facts(c, body.project_id)
    if body.plan:
        p["plan_label"] = PLAN_LABEL.get(body.plan, body.plan)
    bg = None
    if body.bg_document_id:
        d = one(c, "SELECT * FROM documents WHERE id=? AND mime IN ('image/png','image/jpeg')", (body.bg_document_id,), "صورة الخلفية غير موجودة أو ليست صورة")
        bg = str(_docs_dir() / d["stored"])
    pdf, png = adgen.compose(p, brand_of(c), body.template, body.size, body.headline, body.subline, body.cta, body.offer, body.until, bg, body.palette)
    title = f"إعلان {adgen.TEMPLATES[body.template]['label']} — {p['name']}"
    pdf_id, _ = store_upload(c, pdf, f"ad-{body.template}-{body.size}.pdf", "creative", body.project_id, title, "إعلان", u["name"])
    png_id = None
    if png:
        png_id, _ = store_upload(c, png, f"ad-{body.template}-{body.size}.png", "creative", body.project_id, title, "إعلان", u["name"])
    crid = c.execute("""INSERT INTO creatives(project_id,campaign_id,template,size,headline,subline,cta,offer,bg_document_id,document_id,pdf_document_id,created_by,created)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (body.project_id, body.campaign_id, body.template, body.size, body.headline, body.subline, body.cta, body.offer, body.bg_document_id, png_id or pdf_id, pdf_id, u["name"], now_s())).lastrowid
    audit(c, "توليد إعلان", f"{title} ({body.size})")
    c.commit()
    return creative_row(c, crid)


def creative_row(c, crid: int) -> dict:
    r = dict(one(c, "SELECT cr.*, p.name project FROM creatives cr JOIN projects p ON p.id=cr.project_id WHERE cr.id=?", (crid,), "الإعلان غير موجود"))
    r["template_label"] = adgen.TEMPLATES.get(r["template"], {}).get("label", r["template"])
    r["png_url"] = f"/api/documents/{r['document_id']}" if r["document_id"] else None
    r["pdf_url"] = f"/api/documents/{r['pdf_document_id']}" if r["pdf_document_id"] else None
    return r


@router.get("/api/creatives")
def creatives_list(project_id: int | None = None, u=Depends(need_any(*READ))):
    c = db()
    q = "SELECT id FROM creatives" + (" WHERE project_id=?" if project_id else "") + " ORDER BY id DESC LIMIT 200"
    return [creative_row(c, r["id"]) for r in rows(c.execute(q, (project_id,) if project_id else ()))]


class CreativeSend(BaseModel):
    channel: str = Field(pattern="^(email|whatsapp)$")
    to: str = Field(min_length=5, max_length=120)
    message: str | None = Field(default=None, max_length=500)


@router.post("/api/creatives/{crid}/send")
def creative_send(crid: int, body: CreativeSend, request: Request, u=Depends(act_as(WRITE))):
    """One-off share of a creative (a lead asked for it, a broker needs it) — e-mail attachment or WhatsApp click-to-chat with a 30-day link."""
    import hashlib
    import time

    from .modules2 import _docs_dir
    from .paperwork import _public_url
    c = db()
    cr = creative_row(c, crid)
    d = one(c, "SELECT * FROM documents WHERE id=?", (cr["document_id"],))
    text = (body.message or f"{cr['project']} — {cr['headline'] or cr['template_label']}").strip()
    if body.channel == "email":
        from .identity import EMAIL_RE
        to = body.to.strip().lower()
        if not EMAIL_RE.match(to):
            raise HTTPException(400, "بريد غير صالح")
        if not mail.available():
            raise HTTPException(503, "خدمة البريد غير مهيّأة")
        res = mail.send(to, f"{cr['project']} — إعلان", text, kind="creative", attachments=[(d["filename"], (_docs_dir() / d["stored"]).read_bytes(), d["mime"])])
        audit(c, "إرسال إعلان بالبريد", f"#{crid} إلى {to}")
        c.commit()
        return {"ok": True, "channel": "email", "to": to, "delivered": res.get("delivered", False)}
    ph = _digits(body.to)
    if len(ph) < 8:
        raise HTTPException(400, "رقم غير صالح")
    token = secrets.token_urlsafe(24)
    c.execute("INSERT INTO share_links(token_hash,kind,ref_id,expires,created,created_by) VALUES(?,?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), "file", d["id"], time.time() + 30 * 86400, time.time(), u["name"]))
    link = f"{_public_url(request)}/d/{TENANT.get()}/{token}"
    c.execute("INSERT INTO wa_messages(phone,direction,body,at,engine) VALUES(?,?,?,?,?)", (body.to, "out", f"{text} {link}", now_s(), "creative"))
    audit(c, "إرسال إعلان عبر واتساب", f"#{crid} إلى {ph}")
    c.commit()
    return {"ok": True, "channel": "whatsapp", "to": ph, "wa_url": f"https://wa.me/{ph}?text={urlquote(text + ' ' + link)}", "link": link}


# ---------------------------------------------------------------- lead intake with attribution
class LeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=7, max_length=30)
    email: str | None = Field(default=None, max_length=120)
    project_id: int
    channel: str = Field(default="مباشر", max_length=40)
    interest: str = Field(default="", max_length=120)
    budget: float = Field(default=0, ge=0, le=10_000_000)
    bedrooms: int | None = Field(default=None, ge=0, le=10)
    campaign_id: int | None = None
    utm: str | None = Field(default=None, max_length=20)


@router.post("/api/leads")
def lead_create(body: LeadIn, u=Depends(act_as(WRITE))):
    """Manual intake (walk-in, call, campaign landing). `utm` or `campaign_id` attributes the lead to a campaign."""
    c = db()
    one(c, "SELECT 1 FROM projects WHERE id=?", (body.project_id,), "المشروع غير موجود")
    cid = body.campaign_id
    if body.utm and not cid:
        row = c.execute("SELECT id FROM campaigns WHERE utm=?", (body.utm.strip().upper(),)).fetchone()
        cid = row["id"] if row else None
    if cid and not c.execute("SELECT 1 FROM campaigns WHERE id=?", (cid,)).fetchone():
        raise HTTPException(404, "الحملة غير موجودة")
    email = (body.email or "").strip().lower() or None
    lid = c.execute("""INSERT INTO leads(name,phone,interest,project_id,channel,stage,interactions,budget,created,last_contact,score,broker_id,bedrooms,campaign_id,email)
                       VALUES(?,?,?,?,?,?,?,?,?,?,0,NULL,?,?,?)""", (body.name, body.phone, body.interest, body.project_id, body.channel, 0, 1, body.budget,
                                                                   today().isoformat(), today().isoformat(), body.bedrooms, cid, email)).lastrowid
    lead = c.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
    c.execute("UPDATE leads SET score=? WHERE id=?", (E.lead_score(lead), lid))
    audit(c, "تسجيل عميل محتمل", f"{body.name} · {body.channel}{' · حملة ' + str(cid) if cid else ''}")
    c.commit()
    return {"id": lid, "campaign_id": cid}


# ---------------------------------------------------------------- alerts
def compute_alerts(c) -> list[dict]:
    out = []
    t = today()
    week = t.strftime("%G-W%V")
    for p in rows(c.execute("SELECT * FROM projects ORDER BY id")):
        s = project_signals(c, p)
        pid = s["project_id"]
        def add(key, sev, title, detail, action, pid=pid, s=s):  # bound per iteration
            out.append({"key": f"{key}:{pid}", "dedupe": f"mkt:{key}:{pid}:{week}", "severity": sev, "project_id": pid, "project": s["project"], "title": title, "detail": detail, "action": action})
        if s["status"] == "slow":
            add("slow", "high", f"{s['project']}: وتيرة البيع دون المخطط", f"{s['pace30']} حجز في 30 يومًا مقابل {s['planned_monthly']:g} مخططة، متاح {s['available']} وحدة بقيمة {s['unsold_value']:,.0f} ر.ع",
                "افتح لوحة التسويق: حملة إعادة استهداف + مراجعة الشرائح الراكدة")
        if s["cut_segments"] >= 2:
            add("price_pressure", "medium", f"{s['project']}: ضغط سعري على {s['cut_segments']} شرائح", "محرك التسعير يقترح خفضًا/تحفيزًا لأكثر من شريحة — قبل الخفض جرّب حافزًا هيكليًا أو باقة", "المخزون والتسعير ⟵ الشرائح")
        if s["raise_segments"] >= 2:
            add("hot_demand", "low", f"{s['project']}: طلب مرتفع على {s['raise_segments']} شرائح", f"متوسط الطلب النسبي {s['demand_ratio']}× — فرصة رفع سعر أو إطلاق مرحلة/مشروع مشابه", "المخزون ⟵ اعتماد التوصيات")
        if s["leads_prev"] and s["leads30"] < 0.5 * s["leads_prev"]:
            add("lead_drop", "medium", f"{s['project']}: تراجع العملاء الجدد", f"{s['leads30']} هذا الشهر مقابل {s['leads_prev']} الشهر السابق", "راجع القنوات في تقرير القمع وفعّل حملة وعي")
        if s["stale_leads"] >= 5:
            add("stale_leads", "medium", f"{s['project']}: {s['stale_leads']} عملاء متوقفون", "بلا تواصل منذ 14 يومًا في مراحل المعاينة/التفاوض", "حملة إعادة استهداف عبر واتساب بعرض سعر محدّث")
        if s["status"] == "near_complete" and s["sold_pct"] < 80:
            add("near_complete_unsold", "high", f"{s['project']}: قارب الاكتمال و{100 - s['sold_pct']:g}٪ غير مباع", f"الإنجاز {s['build_pct']:g}٪ والتسليم {s['handover']}", "حملة «جاهزة للسكن» + معاينات ميدانية + باقة الوحدات المتبقية")
        if s["available"] and s["days_on_market"] > 180 and s["sold_pct"] < 40:
            add("aging_stock", "high", f"{s['project']}: مخزون متقادم", f"{s['days_on_market']} يومًا في السوق و{s['sold_pct']:g}٪ فقط مباع", "تحليل سبب الضعف ثم حملة مركّزة على الشرائح الراكدة")
        exp = c.execute("SELECT COUNT(*) FROM quotes q JOIN units u ON u.id=q.unit_id WHERE u.project_id=? AND q.status='issued' AND q.valid_until BETWEEN ? AND ?", (pid, t.isoformat(), (t + dt.timedelta(days=3)).isoformat())).fetchone()[0]
        if exp >= 3:
            add("quotes_expiring", "medium", f"{s['project']}: {exp} عروض أسعار تنتهي خلال 3 أيام", "موجة عروض على وشك الانتهاء", "تواصل متابعة مع أصحاب العروض السارية")
    camp_end = rows(c.execute("SELECT ca.id, ca.name, p.name project, ca.project_id FROM campaigns ca JOIN projects p ON p.id=ca.project_id WHERE ca.status='active' AND ca.end_date IS NOT NULL AND ca.end_date<?", (t.isoformat(),)))
    for ca in camp_end:
        out.append({"key": f"campaign_ended:{ca['id']}", "dedupe": f"mkt:campaign_ended:{ca['id']}:{week}", "severity": "low", "project_id": ca["project_id"], "project": ca["project"],
                    "title": f"حملة «{ca['name']}» تجاوزت تاريخ انتهائها", "detail": "ما زالت نشطة", "action": "أغلقها وراجع نتائجها في تبويب الحملات"})
    sev = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda a: (sev[a["severity"]], a["project"]))
    return out


@router.get("/api/marketing/alerts")
def alerts(u=Depends(need_any(*READ))):
    return compute_alerts(db())


def persist_alerts(c) -> int:
    n = 0
    for a in compute_alerts(c):
        if c.execute("SELECT 1 FROM notifications WHERE dedupe=?", (a["dedupe"],)).fetchone():
            continue
        c.execute("INSERT INTO notifications(audience,customer_id,channel,title,body,status,created,dedupe) VALUES(?,?,?,?,?,?,?,?)",
                  ("staff", None, "inapp", "تنبيه تسويقي: " + a["title"], f"{a['detail']} — {a['action']}", "new", now_s(), a["dedupe"]))
        n += 1
    if n:
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ("marketing:alerts_last_run", now_s()))
    c.commit()
    return n


@router.post("/api/marketing/alerts/run")
def alerts_run(u=Depends(act_as("notify"))):
    c = db()
    n = persist_alerts(c)
    audit(c, "تشغيل التنبيهات التسويقية", f"{n} تنبيهًا جديدًا")
    c.commit()
    return {"created": n}


def alerts_due_all() -> int:
    """Background tick: once a day per tenant."""
    n = 0
    for t in tenants():
        tok = TENANT.set(t)
        try:
            c = connect()
            try:
                last = c.execute("SELECT v FROM settings WHERE k='marketing:alerts_last_run'").fetchone()
                if not last or last["v"][:10] < today().isoformat():
                    n += persist_alerts(c)
                    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ("marketing:alerts_last_run", now_s()))
                    c.commit()
            finally:
                c.close()
        finally:
            TENANT.reset(tok)
    return n


__all__ = ["router", "project_signals", "compute_alerts", "persist_alerts", "alerts_due_all", "need"]
