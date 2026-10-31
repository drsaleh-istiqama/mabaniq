"""Mabaniq 0.29.0 — the `sales` phase of the demo organisation (backend/seed_org.py): sales, marketing and customer operations.

The demo developers already carry bookings, instalments, contracts, handovers and leads. What is still empty are the *workflows around them*: price quotations in every state,
marketing campaigns with creatives, attributed leads and measured sends, late-payment donations (the charity condition that replaces a penalty), a termination with its refund,
a completed assignment (resale) settlement, decisions taken on the dashboard's recommendations, official PDFs registered for verification, shared links, and an external property
manager confined to one project.

Everything is made by calling the platform's own functions as synthetic staff (see the docstring of seed_org.py): a quote through `paperwork.quote_create`, a campaign through
`marketing.campaign_create`, a donation through the sandbox payment path (`create_intent` + `simulate_gateway`, which is what accrues `charity_dues`), a refund through
`modules.terminate`, and so on. A rule that refuses is skipped and counted. Nothing is sent outside the platform: campaigns and documents go out by the WhatsApp channel, which only
records the click-to-chat message and a share link; no e-mail is sent (the e-mail path would reach a real mailbox on a configured server).

Each step is guarded by its own marker (`demo_org:sales:<step>` in `settings`) so a rerun adds nothing. All names, phones and amounts are invented.
"""
from __future__ import annotations

import datetime as dt
import secrets

from starlette.requests import Request

from . import marketing, modules, paperwork
from .common import ACTOR, db
from .config import settings
from .seed_org import Ctx

BUYERS = ("هلال بن محمد الكيومي", "فوزية بنت سعيد المعولية", "ناصر بن خليفة الرواحي", "جميلة بنت أحمد البلوشية", "سلطان بن راشد العلوي", "زينب بنت علي اللواتية", "منصور بن سالم الحوسني",
          "عفاف بنت خميس الهنائية", "خالد بن عبدالله الجرداني", "أمل بنت يوسف الصقرية", "طارق بن حمد المقيمي", "سعاد بنت ناصر الريامية", "بدر بن علي الشكيلي", "لبنى بنت مبارك السعدية")
LEAD_CHANNELS = ("واتساب", "إنستغرام", "موقع الشركة", "معرض عقاري", "توصية عميل", "اتصال مباشر")
OFFERS = ("تأجيل الدفعة الثانية ستين يومًا بلا أي رسوم إضافية", "إعفاء من رسوم نقل الملكية لأول عشرة حجوزات", "باقة تشمل موقف سيارة مغطى مع الوحدة",
          "خطة سداد مرنة حتى موعد التسليم بلا أي زيادة على السعر", "تشطيب إضافي مجاني للمطبخ للوحدات المحجوزة هذا الشهر")
# objective → creative template, size, headline, subline, cta
CREATIVES = {
    "launch": [("launch", "square", "انطلاقة جديدة", "وحدات بمخططات مدروسة وسداد على مراحل الإنشاء", "احجز وحدتك اليوم"),
               ("teaser", "story", "قريبًا", "مشروع يليق بك", "سجّل اهتمامك")],
    "retarget": [("offer", "square", "عرض محدود", "فرصة أخيرة للحجز بشروط ميسّرة", "تواصل معنا"), ("last_units", "story", "آخر الوحدات", "عدد محدود من الوحدات المتاحة", "احجز الآن")],
    "near_complete": [("ready", "square", "جاهز للتسليم", "تملّك فورًا ومعاينة فعلية للوحدات", "احجز معاينة"), ("progress", "wide", "تقدّم البناء", "إنجاز مستمر وفق الجدول المعلن", "تابع المشروع")],
    "referral": [("progress", "square", "شكرًا لثقتكم", "برنامج إحالة لملاك المشروع", "أحِل صديقًا")],
    "broker": [("launch", "wide", "فرصة للوسطاء", "مخططات وإعلانات جاهزة للتوزيع", "تواصل مع فريق المبيعات")],
    "slow": [("offer", "square", "فرص مميزة", "شروط ميسّرة على الوحدات المتبقية", "اكتشف العرض")],
}


def _as(u: dict) -> dict:
    ACTOR.set(f"{u['name']} ({u['role_label']})")
    return u


def _q(ctx: Ctx, sql: str, args: tuple = ()) -> list:
    with ctx.request():
        return [dict(r) for r in db().execute(sql, args).fetchall()]


def _step_done(ctx: Ctx, step: str) -> bool:
    return bool(_q(ctx, "SELECT 1 FROM settings WHERE k=?", (f"demo_org:sales:{step}",)))


def _mark(ctx: Ctx, step: str) -> None:
    with ctx.request():
        c = db()
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"demo_org:sales:{step}", dt.datetime.now().isoformat(timespec="seconds")))
        c.commit()


def _request() -> Request:
    """A request object for the functions that build links from it (the public address is the configured one, else a placeholder host)."""
    host = (settings.public_url or "https://localhost").split("://")[-1].strip("/")
    return Request({"type": "http", "method": "POST", "path": "/", "query_string": b"", "scheme": "https", "server": (host, 443), "client": ("127.0.0.1", 0),
                    "headers": [(b"host", host.encode()), (b"x-forwarded-proto", b"https")]})


def _phone(ctx: Ctx) -> str:
    return f"+968 9999 {ctx.rnd.randint(1000, 9999)}"


def run(ctx: Ctx) -> None:
    steps = (("campaigns", _campaigns), ("quotes", _quotes), ("charity", _charity), ("refunds", _refunds), ("resale", _resale), ("decisions", _decisions),
             ("documents", _documents), ("manager", _manager))
    for name, fn in steps:
        if _step_done(ctx, name):
            continue
        fn(ctx)
        _mark(ctx, name)


# ----------------------------------------------------------------------------------------------------------------------- campaigns, creatives, sends, attributed leads
def _campaigns(ctx: Ctx) -> None:
    admin = ctx.user("admin")
    sales = _as(_sales_user(ctx))
    today = ctx.today
    projects = _q(ctx, "SELECT id, code, name, kind, build_pct, completed FROM projects ORDER BY id")
    have_units = {r["project_id"] for r in _q(ctx, "SELECT DISTINCT project_id FROM units WHERE status='a' AND retained=0")}
    projects = [p for p in projects if p["id"] in have_units][:5]
    objectives = []
    for i, p in enumerate(projects):
        if p["completed"] or (p["build_pct"] or 0) >= 85:
            objectives.append("near_complete")
        elif (p["build_pct"] or 0) < 15:
            objectives.append("launch")
        else:
            objectives.append(("retarget", "slow", "launch", "offer")[i % 4])
    if len(objectives) >= 3:
        objectives[-1] = "referral"
    if len(objectives) >= 4:
        objectives[-2] = "broker"
    names = {"launch": "حملة إطلاق", "retarget": "إعادة استهداف عملاء", "near_complete": "حملة جاهزة للسكن", "referral": "برنامج إحالة ملاك", "broker": "تفعيل الوسطاء", "slow": "تنشيط المبيعات", "offer": "عرض محدود"}
    audience = {"launch": "leads_new", "retarget": "leads_stale", "near_complete": "leads_warm", "referral": "customers", "broker": "brokers", "slow": "leads_warm", "offer": "leads_all"}
    channels = {"launch": ["whatsapp", "instagram", "brokers"], "retarget": ["whatsapp", "email"], "near_complete": ["whatsapp", "google", "openday"], "referral": ["whatsapp"],
                "broker": ["brokers", "whatsapp"], "slow": ["whatsapp", "instagram", "snapchat"], "offer": ["whatsapp", "google"]}
    final = {0: "active", 1: "active", 2: "active", 3: "done", 4: "paused"}
    existing = {r["name"] for r in _q(ctx, "SELECT name FROM campaigns")}
    ids: list = []
    for i, (p, obj) in enumerate(zip(projects, objectives)):
        name = f"{names[obj]} — {p['name']}"
        if name in existing:
            continue
        offer = OFFERS[i % len(OFFERS)]
        msg = f"{p['name']}: {offer}. للتفاصيل تواصل مع فريق المبيعات."
        if marketing._forbidden_offer(offer) or marketing._forbidden_offer(msg):
            continue
        start = today - dt.timedelta(days=45 - i * 8)
        r = ctx.tryc(marketing.campaign_create, marketing.CampaignIn(project_id=p["id"], name=name, objective=obj, channels=channels[obj], audience=audience[obj],
                                                                      budget=float(1500 + 700 * i), start_date=start.isoformat(), end_date=(start + dt.timedelta(days=60)).isoformat(),
                                                                      offer_text=offer, message=msg, notes="حملة افتراضية للتجربة"), u=sales)
        if not r:
            continue
        cid = r["id"]
        ids.append(cid)
        ctx.add("campaigns")
        # leads that came through the campaign (attributed by its UTM code), then creatives, then the send
        for j in range(ctx.rnd.randint(3, 6)):
            ctx.tryc(marketing.lead_create, marketing.LeadIn(name=ctx.rnd.choice(BUYERS), phone=_phone(ctx), project_id=p["id"], channel=ctx.rnd.choice(LEAD_CHANNELS),
                                                            interest="استفسار عن الوحدات المتاحة", budget=float(ctx.rnd.randint(40, 160) * 1000), campaign_id=cid), u=sales)
            ctx.add("campaign_leads")
        first_creative = None
        for tpl, size, head, sub, cta in CREATIVES[obj]:
            cr = ctx.tryc(marketing.creative_create, marketing.CreativeIn(project_id=p["id"], campaign_id=cid, template=tpl, size=size, palette=("green", "gold", "blue", "sand")[i % 4],
                                                                         headline=head, subline=sub, cta=cta, offer=offer, until=(today + dt.timedelta(days=30)).isoformat()), u=sales)
            if cr:
                ctx.add("creatives")
                first_creative = first_creative or cr["id"]
        sent = ctx.tryc(marketing.campaign_send, cid, marketing.SendIn(channel="whatsapp", creative_id=first_creative, limit=12), _request(), u=sales)
        if sent:
            ctx.add("campaign_sends", sent["sent"])
        want = final.get(i, "active")
        if want != "active":
            ctx.tryc(marketing.campaign_status, cid, marketing.StatusIn(status=want), u=sales)
    ctx.tryc(marketing.alerts_run, u=_as(admin))   # the market-movement alerts the dashboard shows
    ctx.add("campaigns_total", len(ids))


def _sales_user(ctx: Ctx) -> dict:
    """The sales officer: the `sales` role (the demo has no such ACTORS key, so it is built the same way `Ctx.user` builds the others)."""
    from .auth import PERMS, ROLES
    return {"id": 0, "username": "seed.sales", "name": "مسؤول المبيعات", "role": "sales", "role_label": ROLES["sales"], "perms": sorted(PERMS["sales"]), "customer_id": None,
            "employee_id": None, "lessee_id": None, "modules": [], "broker_id": None, "must_change": False, "totp_enabled": True, "needs_2fa": False, "tenant": ctx.tenant}


# ----------------------------------------------------------------------------------------------------------------------- quotations
def _quotes(ctx: Ctx) -> None:
    sales = _as(_sales_user(ctx))
    today = ctx.today
    units = _q(ctx, """SELECT u.code, u.project_id FROM units u WHERE u.status='a' AND u.retained=0 AND u.price IS NOT NULL
                       AND u.project_id IN (SELECT id FROM projects WHERE handover IS NOT NULL AND COALESCE(completed,0)=0) ORDER BY u.id""")
    if not units:
        return
    by_project: dict[int, list] = {}
    for u in units:
        by_project.setdefault(u["project_id"], []).append(u["code"])
    pool = [code for codes in zip(*[v[:6] for v in by_project.values()]) for code in codes] or [u["code"] for u in units[:10]]
    leads = _q(ctx, "SELECT id, name, phone, project_id FROM leads ORDER BY id DESC LIMIT 40")
    # state → (how many, plan rotation); expired and converted ones are decided after the issue
    plans = ("milestone", "6040", "murabaha")
    made = []
    for i, code in enumerate(pool[:11]):
        lead = next((x for x in leads if x["project_id"] == next((u["project_id"] for u in units if u["code"] == code), None)), None) if i % 2 == 0 else None
        name = lead["name"] if lead and len(lead["name"]) >= 3 else BUYERS[i % len(BUYERS)]
        r = ctx.tryc(paperwork.quote_create, paperwork.QuoteIn(unit_code=code, customer_name=name, phone=lead["phone"] if lead else _phone(ctx), plan=plans[i % 3],
                                                                discount_pct=(0.0, 0.01, 0.02)[i % 3], valid_days=(7, 14, 10, 30)[i % 4], lead_id=lead["id"] if lead else None,
                                                                notes="عرض افتراضي للتجربة"), _request(), u=sales)
        if r:
            made.append(r)
            ctx.add("quotes")
    if len(made) < 6:
        return
    # timeline: two quotes that lapsed, so the list shows an expired state (created and validity moved back; the status itself is derived by the platform)
    with ctx.request():
        c = db()
        for q, ago in ((made[-1], 30), (made[-2], 24)):
            c.execute("UPDATE quotes SET created=?, valid_until=? WHERE id=?", ((today - dt.timedelta(days=ago)).isoformat(), (today - dt.timedelta(days=ago - 7)).isoformat(), q["id"]))
        for k, q in enumerate(made[:-2]):
            c.execute("UPDATE quotes SET created=? WHERE id=?", ((today - dt.timedelta(days=k % 6)).isoformat(), q["id"]))
        c.commit()
    for q in made[:2]:                                    # accepted: they became bookings
        if ctx.tryc(paperwork.quote_convert, q["id"], u=sales):
            ctx.add("quotes_converted")
    if len(made) > 4 and ctx.tryc(paperwork.quote_cancel, made[3]["id"], u=sales):
        ctx.add("quotes_cancelled")


# ----------------------------------------------------------------------------------------------------------------------- late-payment donations (the charity condition)
def _charity(ctx: Ctx) -> None:
    fin = _as(ctx.user("finance"))
    cand = _q(ctx, """SELECT i.id, i.due_date FROM installments i JOIN bookings b ON b.id=i.booking_id
                      WHERE b.status='confirmed' AND i.paid_amount<i.amount-1 AND i.due_date<?
                        AND i.seq=(SELECT MIN(seq) FROM installments x WHERE x.booking_id=b.id AND x.paid_amount<x.amount-1)
                      ORDER BY i.amount LIMIT 5""", ((ctx.today - dt.timedelta(days=25)).isoformat(),))
    for r in cand[:4]:
        def pay(iid=r["id"]):
            try:
                c = db()
                pid, due = modules.create_intent(c, iid)
                modules.simulate_gateway(c, pid, due)
                c.commit()
                return True
            except Exception as e:  # noqa: BLE001 — a rule (already paid, secret missing…) refuses this one; the rest go on
                if hasattr(e, "status_code"):
                    raise
                return None
        if ctx.tryc(pay):
            ctx.add("late_payments")
    dues = _q(ctx, "SELECT id FROM charity_dues WHERE status='due' ORDER BY id")
    ctx.add("charity_dues", len(_q(ctx, "SELECT id FROM charity_dues")))
    for d in dues[:2]:
        ctx.tryc(modules.charity_collect, d["id"], modules.CharityRef(reference=f"TRF-{ctx.today:%y%m}-{d['id']:03d}"), _=fin)
    if dues[:1]:
        ctx.tryc(modules.charity_disburse, dues[0]["id"], modules.CharityRef(reference=f"DSB-{ctx.today:%y%m}-{dues[0]['id']:03d}", beneficiary="جهة خيرية معتمدة من هيئة الرقابة الشرعية (اسم افتراضي للتجربة)"), _=fin)


# ----------------------------------------------------------------------------------------------------------------------- a termination and its refund
def _refunds(ctx: Ctx) -> None:
    admin = _as(ctx.user("admin"))
    cand = _q(ctx, """SELECT b.id FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id
                      WHERE b.status='confirmed' AND COALESCE(p.completed,0)=0
                        AND NOT EXISTS (SELECT 1 FROM handovers h WHERE h.booking_id=b.id AND h.status='done')
                        AND (SELECT COALESCE(SUM(i.paid_amount),0) FROM installments i WHERE i.booking_id=b.id) > b.price * 0.2
                      ORDER BY b.id DESC LIMIT 2""")   # paid more than the deduction, so the refund is a real amount
    for r in cand:
        if ctx.tryc(modules.terminate, r["id"], modules.TermIn(reason="طلب العميل فسخ العقد لتغيّر ظروفه المالية — يُطبَّق الخصم وفق سياسة الفسخ في العقد"), _=admin):
            ctx.add("refunds")


# ----------------------------------------------------------------------------------------------------------------------- an assignment (resale) completed and settled
def _resale(ctx: Ctx) -> None:
    fin = _as(ctx.user("finance"))
    offer = _q(ctx, "SELECT o.id FROM resale_offers o JOIN resale r ON r.id=o.resale_id WHERE o.status='open' AND r.status='listed' ORDER BY o.price DESC LIMIT 1")
    if not offer:
        return
    out = ctx.tryc(modules.market_accept, offer[0]["id"], _=fin)
    if out:
        ctx.add("resale_assigned")
        if ctx.tryc(modules.resale_settle, out["settlement_id"], modules.SettleIn(reference=f"TRF-RS-{ctx.today:%y%m}-{out['settlement_id']:03d}"), u=fin):
            ctx.add("resale_settled")


# ----------------------------------------------------------------------------------------------------------------------- decisions on the dashboard's recommendations
def _decisions(ctx: Ctx) -> None:
    from .app import DecisionIn, act
    from .engines import decisions
    from .orgmodules import visible_decisions
    admin = _as(ctx.user("admin"))
    with ctx.request():
        c = db()
        items = [x for x in visible_decisions(c, decisions(c)) if not x["done"]]
    taken = {"price": ["approve", "approve", "dismiss"], "reschedule": ["approve"], "lease": ["approve"], "cash": ["dismiss"]}
    for it in items:
        kind = "lease" if it["kind"].startswith("lease_") else it["kind"]
        todo = taken.get(kind)
        if not todo:
            continue
        action = todo.pop(0)
        if ctx.tryc(act, DecisionIn(key=it["key"], action=action), u=admin):
            ctx.add("decisions")


# ----------------------------------------------------------------------------------------------------------------------- official PDFs, verification registry, shared links
def _documents(ctx: Ctx) -> None:
    sales, fin = _as(_sales_user(ctx)), ctx.user("finance")
    quotes = _q(ctx, "SELECT id FROM quotes ORDER BY id LIMIT 3")
    contracts = _q(ctx, "SELECT booking_id id FROM sale_contracts ORDER BY id DESC LIMIT 3")
    invoices = _q(ctx, "SELECT id FROM invoices ORDER BY id DESC LIMIT 3")
    receipts = _q(ctx, "SELECT id FROM payments ORDER BY id DESC LIMIT 3")
    for kind, rows_, who in (("quote", quotes, sales), ("contract", contracts, fin), ("invoice", invoices, fin), ("receipt", receipts, fin)):
        for r in rows_:
            if ctx.tryc(paperwork.doc_pdf, kind, r["id"], _request(), 0, u=_as(who)):
                ctx.add("documents_issued")
    # sent to the customer by WhatsApp: only the click-to-chat message and the share link are recorded — nothing leaves the platform
    for kind, rows_, who in (("quote", quotes[:1], sales), ("contract", contracts[:1], fin), ("invoice", invoices[:1], fin), ("receipt", receipts[:1], fin)):
        for r in rows_:
            if ctx.tryc(paperwork.doc_send, kind, r["id"], paperwork.SendIn(channel="whatsapp"), _request(), u=_as(who)):
                ctx.add("documents_sent")


# ----------------------------------------------------------------------------------------------------------------------- an external property manager, confined to one project
def _manager(ctx: Ctx) -> None:
    from . import leasing_mgmt
    from .auth import hash_pw
    admin = _as(ctx.user("admin"))
    proj = _q(ctx, "SELECT DISTINCT u.project_id FROM leases l JOIN units u ON u.id=l.unit_id ORDER BY u.project_id LIMIT 1")
    if not proj:
        return
    mgr = _q(ctx, "SELECT id FROM users WHERE role='property_manager' ORDER BY id LIMIT 1")
    if mgr:
        uid = mgr[0]["id"]
    else:   # no trial login for the role yet: a locked file (inactive, unusable password) so the scope can be shown; a real login is a pilot account
        with ctx.request():
            c = db()
            uid = c.execute("INSERT INTO users(username,name,role,pw,active,must_change) VALUES(?,?,?,?,0,1)",
                            ("pm.demo", "مدير عقاري خارجي (حساب تجريبي مُقفَل)", "property_manager", hash_pw(secrets.token_urlsafe(24)))).lastrowid
            c.commit()
        ctx.add("property_manager")
    if not _q(ctx, "SELECT 1 FROM user_scopes WHERE user_id=?", (uid,)):
        if ctx.tryc(leasing_mgmt.api_scope_add, leasing_mgmt.ScopeIn(user_id=uid, project_id=proj[0]["project_id"]), u=admin):
            ctx.add("manager_scopes")
