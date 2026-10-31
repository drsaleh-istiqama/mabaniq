"""Mabaniq 0.29.0 — leasing operations of a full-demo developer (phase `lea` of backend/seed_org.py).

On top of the leases the profile already carries, this builds one lease for every situation a lettings office meets, so each screen and report has something real to show:
expiring soon · expired with take-back report and deposit settlement · arrears with numbered notices and a payment plan · renewed · post-dated cheques (held, deposited,
cleared, bounced, returned) · early termination · the late-payment charity clause · a second arrears case · a lease about to start (preparation period) · a unit under
maintenance · and three units managed for a third-party owner with monthly owner statements. Around them: meters and hand-over reports, maintenance requests in every
state with work orders, property expenses, common facilities, a blacklisted former lessee.

Everything is called through the leasing modules' own endpoint functions as synthetic staff (see seed_org.py) — receipts, cheques, notices and plans obey their rules,
and the ledger postings follow (accounting is active from 1 January by the `acc_base` phase). A lease is found by its `municipality_ref = DEMO-<tag>`, so a re-run skips it.
Every lease starts on or after the accounting start, so no deposit or receipt precedes the ledger. Figures are illustrative.
"""
from __future__ import annotations

import datetime as dt

from .seed_org_acc import DEMO, _addm, _do, _exec, _one, _projects, _rows

# per tenant: (monthly rent per m² commercial, residential), default area, lessees by scenario tag, the external owner
_T = {
    "bayan": dict(rate=(6.5, 3.2), area=82.0, company=True,
                  owner="شركة آفاق للاستثمار العقاري (مالك خارجي)",
                  names={"EXP": "شركة بوابة الشرق للسفر والسياحة", "EXPIRED": "مكتب الإتقان للمحاسبة والتدقيق", "PLAN": "شركة ركائز للمقاولات العامة", "RENEW": "عيادة الشفاء التخصصية",
                         "CHEQUE": "شركة إيوان للتصميم الداخلي", "TERM": "مؤسسة الواحة للخدمات اللوجستية", "CHARITY": "شركة نبراس للتقنية والحلول الرقمية", "ARR2": "مكتب المدار للخدمات الهندسية",
                         "FUTURE": "مطعم ركن الضيافة", "TP1": "صيدلية النسيم", "TP2": "مكتب الرؤية للاستشارات الإدارية", "TP3": "شركة الريف للتجارة العامة", "BLACK": "مؤسسة العاصفة للتجارة"}),
    "almukhatat": dict(rate=(5.5, 3.0), area=64.0, company=False,
                       owner="شركة نخيل الباطنة للاستثمار (مالك خارجي)",
                       names={"EXP": "سالم بن حمد الحارثي", "EXPIRED": "راجيش كومار", "PLAN": "ماجد بن علي الكلباني", "RENEW": "هدى بنت سعيد الراشدية", "CHEQUE": "شركة الإقامة المتميزة للشقق المفروشة",
                              "TERM": "دانيال أوكونكو", "CHARITY": "فيصل بن راشد المعمري", "ARR2": "ليلى بنت ناصر الهنائية", "FUTURE": "نادية بنت خليل البلوشية",
                              "TP1": "عبدالله بن مبارك الغافري", "TP2": "نورة بنت محمد الصقرية", "TP3": "فهد بن سيف الرواحي", "BLACK": "طارق بن عيسى الفارسي"}),
}
BANKS = ["بنك نزوى", "ميثاق للصيرفة الإسلامية", "بنك مسقط", "البنك الوطني العُماني", "بنك ظفار"]


def _tp(ctx):
    return _T.get(ctx.tenant, _T["bayan"])


def _tenant_in(ctx, tag: str, rating: str = "B"):
    from .leasing import TenantIn
    t = _tp(ctx)
    name = t["names"][tag]
    n = len(ctx.tenant) * 7 + sum(map(ord, tag))
    if t["company"] or "شركة" in name or "مؤسسة" in name or "مكتب" in name or "عيادة" in name or "مطعم" in name or "صيدلية" in name:
        return TenantIn(name=name, kind="company", cr_number=f"1{200000 + n * 37}", tax_no=f"OM{1300000 + n * 11}", rep_name="المفوَّض بالتوقيع", rep_title="المدير المفوَّض",
                        contact_name="مسؤول العلاقة", phone=f"9{1000000 + n * 931 % 8999999:07d}", email="", address="سلطنة عُمان", nationality="عُماني", rating=rating, rating_note=DEMO)
    return TenantIn(name=name, kind="individual", id_number=f"{20000000 + n * 7919 % 79999999}", phone=f"9{2000000 + n * 877 % 7999999:07d}", nationality="عُماني" if "بن" in name or "بنت" in name else "هندي",
                    rating=rating, rating_note=DEMO)


# ----------------------------------------------------------------------------------------------------------------------- units
def _free_units(ctx) -> list[dict]:
    """Retained units with no lease at all, then (after marking more units as retained) enough others."""
    return _rows(ctx, """SELECT u.id, u.code, u.area, u.use, u.project_id FROM units u WHERE COALESCE(u.retained,0)=1 AND NOT EXISTS (SELECT 1 FROM leases l WHERE l.unit_id=u.id) ORDER BY u.id""")


def _retain_more(ctx, n: int) -> None:
    """Mark `n` more unsold units retained for leasing, taking them round-robin from the projects so the portfolio is varied."""
    from . import leasing
    cand = _rows(ctx, """SELECT u.id, u.project_id, p.code FROM units u JOIN projects p ON p.id=u.project_id WHERE u.status='a' AND COALESCE(u.retained,0)=0 AND u.owner_id IS NULL
                         AND p.completed=0 AND p.kind='tower' AND p.code NOT IN ('QRM','AMR') ORDER BY p.id, u.floor, u.pos, u.id""")
    by: dict = {}
    for x in cand:
        by.setdefault(x["project_id"], []).append(x)
    order, i = [], 0
    while len(order) < n and any(by.values()):
        for k in list(by):
            if by[k]:
                order.append(by[k].pop(0))
                if len(order) >= n:
                    break
        i += 1
        if i > 500:
            break
    for x in order[:n]:
        _do(ctx, "finance", leasing.api_unit_patch, x["id"], leasing.UnitPatch(retained=True))


def _annual(ctx, unit: dict, factor: float = 1.0) -> float:
    t = _tp(ctx)
    res = unit.get("use") in ("residential", "hotel")
    rate = t["rate"][1] if res else t["rate"][0]
    return round(((unit.get("area") or t["area"]) * rate * 12 * factor) / 50) * 50.0


# ----------------------------------------------------------------------------------------------------------------------- helpers
def _lease(ctx, tag, unit, months, start, annual, freq=12, deposit=True, charity=False, prep=0, tenant_tag=None, rating="B"):
    from . import leasing
    ref = f"DEMO-{tag}"
    if _one(ctx, "SELECT 1 x FROM leases WHERE municipality_ref=?", (ref,)):
        return None
    b = leasing.LeaseNew(unit_id=unit["id"], tenant=_tenant_in(ctx, tenant_tag or tag, rating), start=start, months=months, annual_rent=annual, frequency=freq,
                         deposit=round(annual / 12, 3) if deposit else 0, charity_clause=charity, prep_free_days=prep, municipality_ref=ref, sign=True)
    r = _do(ctx, "finance", leasing.api_lease_create, b)
    if not r:
        return None
    ctx.add("leases")
    return r["id"]


def _dues(ctx, lid):
    return _rows(ctx, "SELECT id, due, amount, paid, COALESCE(kind,'rent') kind FROM rent_dues WHERE lease_id=? ORDER BY CASE WHEN COALESCE(kind,'rent')='deposit' THEN 0 ELSE 1 END, due, id", (lid,))


def _pay(ctx, lid, d, on, method, ref=""):
    from . import leasing
    left = round(d["amount"] - d["paid"], 3)
    if left <= 0.0005 or on > ctx.today:
        return None
    r = _do(ctx, "finance", leasing.api_pay, leasing.PayIn(lease_id=lid, amount=left, paid_on=on, method=method, reference=ref, due_id=d["id"], note=DEMO))
    if r:
        ctx.add("receipts")
    return r


def _settle(ctx, lid, skip=(), late=None, only_first=None, until=None):
    """Pay the dues that are due: the deposit and every rent due ≤ today, in order, on their due date plus a small deterministic delay. `skip` = rent-due indexes left unpaid;
    `late` = {index: days late}; `only_first` = stop after that many rent dues."""
    methods = ["transfer", "transfer", "cheque", "cash", "transfer"]
    k = -1
    for n, d in enumerate(_dues(ctx, lid)):
        if d["kind"] != "deposit":
            k += 1
            if only_first is not None and k >= only_first:
                break
        if d["kind"] != "deposit" and k in skip:
            continue
        due = dt.date.fromisoformat(d["due"])
        if due > ctx.today or (until and due > until):
            continue
        delay = (late or {}).get(k, 0) if d["kind"] != "deposit" else 0
        on = min(due + dt.timedelta(days=delay + ((n * 2) % 3 if not late else 0)), ctx.today)
        _pay(ctx, lid, d, on, methods[n % len(methods)], f"حوالة {lid}-{n}" if methods[n % len(methods)] == "transfer" else "")


def _meters(ctx, unit_id):
    from . import leasing
    have = _rows(ctx, "SELECT id, kind FROM unit_meters WHERE unit_id=?", (unit_id,))
    if not have:
        for kind, prov in (("electricity", "مزوّد الكهرباء"), ("water", "مزوّد المياه")):
            _do(ctx, "finance", leasing.api_meter_add, unit_id, leasing.MeterIn(kind=kind, number=f"{unit_id:04d}-{kind[:1].upper()}-{3100 + unit_id * 3}", provider=prov))
        have = _rows(ctx, "SELECT id, kind FROM unit_meters WHERE unit_id=?", (unit_id,))
    return have


def _handover(ctx, lid, unit_id, kind, at, base=1000.0, deductions=None):
    from . import leasing_ops as OPS
    ms = _meters(ctx, unit_id)
    readings = [OPS.ReadingIn(meter_id=m["id"], reading=round(base + (0 if kind == "in" else (410 if m["kind"] == "electricity" else 95)), 1)) for m in ms]
    cond = {"الجدران والدهان": "سليمة" if kind == "in" else "تحتاج دهانًا", "الأرضيات": "سليمة", "الأبواب والأقفال": "سليمة", "التكييف": "يعمل", "الإنارة": "سليمة"}
    return _do(ctx, "finance", OPS.api_handover, lid, OPS.HandoverIn(kind=kind, at=at, keys=3, condition=cond, notes=f"محضر {DEMO}", readings=readings, deductions=deductions or []))


# ----------------------------------------------------------------------------------------------------------------------- phase
def run(ctx) -> dict:
    from . import leasing
    from . import leasing_ops as OPS
    T = ctx.today
    tp = _tp(ctx)
    free = _free_units(ctx)
    need = 13
    if len(free) < need:
        _retain_more(ctx, need - len(free))
        free = _free_units(ctx)
    if len(free) < 6:
        return ctx.counts            # nothing to build on (a tiny profile): leave the phase empty rather than half-done
    U = {tag: u for tag, u in zip(["EXP", "EXPIRED", "PLAN", "RENEW", "CHEQUE", "TERM", "CHARITY", "ARR2", "FUTURE", "MAINT", "TP1", "TP2", "TP3"], free, strict=False)}
    ids: dict = {}

    # --- the external owner and the three units managed for it
    owner = _one(ctx, "SELECT id FROM owners WHERE name=?", (tp["owner"],))
    if not owner:
        r = _do(ctx, "finance", leasing.api_owner_add, leasing.OwnerIn(name=tp["owner"], kind="third_party", mgmt_fee_pct=5.0, mgmt_basis="collected", phone="24500000",
                                                                       notes=f"مالك وحدات تُدار لحسابه بعمولة إدارة 5٪ من المحصَّل — {DEMO}"))
        owner = {"id": r["id"]} if r else None
        ctx.add("owners")
    for tag in ("TP1", "TP2", "TP3"):
        if tag in U and owner:
            _do(ctx, "finance", leasing.api_unit_patch, U[tag]["id"], leasing.UnitPatch(owner_id=owner["id"]))
    if "MAINT" in U:
        _do(ctx, "finance", leasing.api_unit_patch, U["MAINT"]["id"], leasing.UnitPatch(lease_state="maintenance"))

    # --- the situations
    def need_u(tag):
        return U.get(tag)

    if (u := need_u("EXP")):        # ends in 45 days, quarterly, everything due is paid
        end = T + dt.timedelta(days=45)
        ids["EXP"] = _lease(ctx, "EXP", u, 9, _addm(end + dt.timedelta(days=1), -9), _annual(ctx, u), freq=4)
    if (u := need_u("EXPIRED")):    # ended 50 days ago, quarterly, paid
        end = T - dt.timedelta(days=50)
        ids["EXPIRED"] = _lease(ctx, "EXPIRED", u, 6, _addm(end + dt.timedelta(days=1), -6), _annual(ctx, u, .95), freq=4)
    if (u := need_u("PLAN")):       # quarterly; the first paid, the next two not
        ids["PLAN"] = _lease(ctx, "PLAN", u, 12, _addm(T, -8), _annual(ctx, u, 1.05), freq=4)
    if (u := need_u("RENEW")):      # a 6-month lease that ended 4 days ago and is renewed for a year
        end = T - dt.timedelta(days=4)
        ids["RENEW"] = _lease(ctx, "RENEW", u, 6, _addm(end + dt.timedelta(days=1), -6), _annual(ctx, u, .9), freq=4)
    if (u := need_u("CHEQUE")):     # monthly, paid by cheques
        ids["CHEQUE"] = _lease(ctx, "CHEQUE", u, 12, _addm(T, -4), _annual(ctx, u, 1.1), freq=12)
    if (u := need_u("TERM")):       # monthly, ended early
        ids["TERM"] = _lease(ctx, "TERM", u, 12, _addm(T, -5), _annual(ctx, u), freq=12)
    if (u := need_u("CHARITY")):    # quarterly with the late-payment charity clause
        ids["CHARITY"] = _lease(ctx, "CHARITY", u, 12, _addm(T, -7), _annual(ctx, u, 1.15), freq=4, charity=True)
    if (u := need_u("ARR2")):       # monthly, two paid then nothing
        ids["ARR2"] = _lease(ctx, "ARR2", u, 12, _addm(T, -4), _annual(ctx, u, .85), freq=12)
    if (u := need_u("FUTURE")):     # starts in 20 days with 30 days of preparation
        ids["FUTURE"] = _lease(ctx, "FUTURE", u, 12, T + dt.timedelta(days=20), _annual(ctx, u, 1.0), freq=12, prep=30)
    for i, tag in enumerate(("TP1", "TP2", "TP3")):
        if (u := need_u(tag)) and owner:
            ids[tag] = _lease(ctx, tag, u, 12, _addm(T, -5) + dt.timedelta(days=i), _annual(ctx, u, .9 + .05 * i), freq=12)

    # --- receipts
    if ids.get("EXP"):
        _settle(ctx, ids["EXP"])
    if ids.get("EXPIRED"):
        _settle(ctx, ids["EXPIRED"])
    if ids.get("PLAN"):
        _settle(ctx, ids["PLAN"], only_first=1)
    if ids.get("RENEW"):
        _settle(ctx, ids["RENEW"])
    if ids.get("TERM"):
        _settle(ctx, ids["TERM"], until=T - dt.timedelta(days=25))
    if ids.get("CHARITY"):
        _settle(ctx, ids["CHARITY"], skip={2}, late={1: 20})
    if ids.get("ARR2"):
        _settle(ctx, ids["ARR2"], only_first=2)
    for tag in ("TP1", "TP2", "TP3"):
        if ids.get(tag):
            _settle(ctx, ids[tag])
    if ids.get("CHEQUE"):
        _cheques(ctx, ids["CHEQUE"])

    # --- the ended and the renewed
    with ctx.request():
        c = ctx.conn()
        leasing.ensure_core(c)           # flips a lease whose end has passed to «expired»
    if ids.get("EXPIRED"):
        u = U["EXPIRED"]
        e = _one(ctx, "SELECT start, \"end\" FROM leases WHERE id=?", (ids["EXPIRED"],))
        _meters(ctx, u["id"])
        first = _handover(ctx, ids["EXPIRED"], u["id"], "in", dt.date.fromisoformat(e["start"]), 1000.0)
        out = _handover(ctx, ids["EXPIRED"], u["id"], "out", dt.date.fromisoformat(e["end"]) + dt.timedelta(days=1), 1000.0,
                        [OPS.DeductionIn(label="إعادة دهان الجدران", amount=85.0, ref="فاتورة دهان رقم 2210"), OPS.DeductionIn(label="استبدال مفتاح مفقود", amount=12.5, ref="محضر الاستلام")])
        if first and out:
            _do(ctx, "finance", OPS.api_deposit_settle, ids["EXPIRED"], OPS.SettleIn(note=DEMO))
    if ids.get("RENEW"):
        r = _do(ctx, "finance", OPS.api_renew, ids["RENEW"], OPS.RenewIn(months=12, escalation_pct=3.0, sign=True))
        if r:
            ctx.add("renewals")
            _settle(ctx, r["id"])
    if ids.get("TERM"):
        r = _do(ctx, "finance", OPS.api_terminate, ids["TERM"], OPS.TerminateIn(on=T - dt.timedelta(days=25), note="إنهاء مبكر باتفاق الطرفين — انتقال المستأجر إلى موقع آخر"))
        if r:
            u = U["TERM"]
            _handover(ctx, ids["TERM"], u["id"], "in", _addm(T, -5), 2000.0)
            _handover(ctx, ids["TERM"], u["id"], "out", T - dt.timedelta(days=24), 2000.0)
            _do(ctx, "finance", OPS.api_deposit_settle, ids["TERM"], OPS.SettleIn(deductions=[], note="تسوية كاملة بلا خصومات"))

    # --- hand-over reports of running leases (meters first)
    for tag in ("EXP", "PLAN", "CHEQUE", "CHARITY", "TP1"):
        if ids.get(tag):
            l = _one(ctx, "SELECT start FROM leases WHERE id=?", (ids[tag],))
            _handover(ctx, ids[tag], U[tag]["id"], "in", dt.date.fromisoformat(l["start"]), 500.0)

    # --- arrears: notices, a plan
    if ids.get("PLAN"):
        pl = ids["PLAN"]
        n1 = _do(ctx, "finance", OPS.api_notice, pl, OPS.NoticeIn(kind="reminder", note="تذكير ودّي بالمتأخرات"))
        if n1:
            _do(ctx, "finance", OPS.api_notice_sent, n1["id"], OPS.SentIn(via="whatsapp", on=T - dt.timedelta(days=1)))
            ctx.add("notices")
        n2 = _do(ctx, "finance", OPS.api_notice, pl, OPS.NoticeIn(kind="formal", cure_days=15, note="إنذار رسمي بالسداد"))
        if n2:
            _do(ctx, "finance", OPS.api_notice_sent, n2["id"], OPS.SentIn(via="registered", on=T))
            ctx.add("notices")
        open_dues = [d for d in _dues(ctx, pl) if d["kind"] == "rent" and dt.date.fromisoformat(d["due"]) < T and d["amount"] - d["paid"] > 0.0005]
        if open_dues:
            owed = round(sum(d["amount"] - d["paid"] for d in open_dues), 3)
            parts = [round(owed / 3, 3)] * 2
            parts.append(round(owed - sum(parts), 3))
            plan = OPS.PlanIn(due_ids=[d["id"] for d in open_dues], note=f"جدولة المتأخرات على ثلاثة أقساط شهرية — {DEMO}",
                              installments=[OPS.PlanItem(due=T + dt.timedelta(days=7 + 30 * i), amount=a) for i, a in enumerate(parts)])
            if _do(ctx, "admin", OPS.api_plan, pl, plan):
                ctx.add("plans")
    if ids.get("ARR2"):
        n = _do(ctx, "finance", OPS.api_notice, ids["ARR2"], OPS.NoticeIn(kind="reminder", note="تذكير بالسداد"))
        if n:
            _do(ctx, "finance", OPS.api_notice_sent, n["id"], OPS.SentIn(via="email", on=T))
            ctx.add("notices")
    if ids.get("CHARITY"):
        n = _do(ctx, "finance", OPS.api_notice, ids["CHARITY"], OPS.NoticeIn(kind="reminder", note="تذكير بالسداد"))
        if n:
            ctx.add("notices")
        for d in _rows(ctx, "SELECT id FROM charity_dues WHERE lease_id=? AND status='due'", (ids["CHARITY"],)):
            if _do(ctx, "finance", OPS.api_charity_collect, d["id"], OPS.CharityRef(reference="تحصيل نقدي بإيصال تبرع 1")):
                _do(ctx, "admin", OPS.api_charity_disburse, d["id"], OPS.CharityRef(reference="حوالة إلى الجهة الخيرية", beneficiary="جهة خيرية معتمدة (افتراضي للتجربة)"))
                ctx.add("charity")

    # --- a blacklisted former lessee
    if not _one(ctx, "SELECT 1 x FROM tenants_l WHERE name=?", (tp["names"]["BLACK"],)):
        r = _do(ctx, "finance", leasing.api_tenant_add, _tenant_in(ctx, "BLACK", "D"))
        if r:
            _do(ctx, "admin", leasing.api_blacklist, r["id"], leasing.BlackIn(reason="تأخر متكرر عن السداد وإخلاء بعد إنذار نهائي — سجل افتراضي للتجربة"))
            ctx.add("blacklisted")

    _maintenance(ctx, U, ids)
    _expenses(ctx, U, ids, owner)
    _facilities(ctx)
    _statements(ctx, owner)
    _do(ctx, "finance", leasing.api_reminders)
    return ctx.counts


def _cheques(ctx, lid):
    from . import leasing
    T = ctx.today
    dues = [d for d in _dues(ctx, lid) if d["kind"] == "rent"]
    bank = BANKS
    seq = 410000 + lid * 100

    def add(d, status_flow, i):
        left = round(d["amount"] - d["paid"], 3)
        if left <= 0.0005:
            return None
        due = dt.date.fromisoformat(d["due"])
        r = _do(ctx, "finance", leasing.api_cheque_add, leasing.ChequeIn(lease_id=lid, due_id=d["id"], number=str(seq + i), bank=bank[i % len(bank)], amount=left, due_date=due,
                                                                        received_on=min(due - dt.timedelta(days=5), T), drawer="المستأجر"))
        if not r:
            return None
        ctx.add("cheques")
        cid = r["id"]
        if status_flow in ("deposit", "clear", "bounce"):
            _do(ctx, "finance", leasing.api_cheque_deposit, cid, leasing.ChequeAct(on=min(due, T)))
        if status_flow == "clear":
            _do(ctx, "finance", leasing.api_cheque_clear, cid, leasing.ChequeAct(on=min(due + dt.timedelta(days=1), T)))
        if status_flow == "bounce":
            _do(ctx, "finance", leasing.api_cheque_bounce, cid, leasing.BlackIn(reason="رصيد غير كافٍ في حساب الساحب"))
        if status_flow == "return":
            _do(ctx, "finance", leasing.api_cheque_return, cid, leasing.BlackIn(reason="أُعيد للمستأجر بطلبه واستُبدل بتحويل بنكي"))
        return cid

    # dues[0] paid in cash with the deposit; the next two by cheques that cleared; the third bounced; the fourth (today) is held; later ones are post-dated
    if dues:
        _settle_first = _dues(ctx, lid)
        for d in _settle_first:
            if d["kind"] == "deposit" or d["id"] == dues[0]["id"]:
                _pay(ctx, lid, d, min(dt.date.fromisoformat(d["due"]), T), "cash" if d["kind"] != "deposit" else "transfer")
    plan = ["clear", "clear", "bounce", "hold", "hold", "hold", "return", "hold"]
    for i, d in enumerate(dues[1:]):
        add(d, plan[i] if i < len(plan) else "hold", i)


# ----------------------------------------------------------------------------------------------------------------------- maintenance, expenses, facilities, statements
def _vendor(ctx, trade_part: str):
    r = _one(ctx, "SELECT id FROM vendors WHERE COALESCE(active,1)=1 AND trade LIKE ? ORDER BY id", (f"%{trade_part}%",))
    return r["id"] if r else None


def _maintenance(ctx, U, ids):
    from . import leasing_mgmt as M
    if _one(ctx, "SELECT 1 x FROM maint_requests WHERE requester LIKE ?", (f"%{DEMO}%",)):
        return
    T = ctx.today
    flows = [  # unit tag, category, description, priority, steps
        ("EXP", "سباكة", "تسرّب مياه من السقف المستعار قرب دورة المياه", "high", ("order:سباك:owner:165", "progress", "done", "close")),
        ("PLAN", "تكييف", "ضعف في التبريد وصوت مرتفع من وحدة التكييف الداخلية", "normal", ("order:تكييف:owner:120", "progress")),
        ("TP1", "كهرباء", "انقطاع الكهرباء عن لوحة الوحدة", "urgent", ("triage", "order:كهرب:company:90", "done")),
        ("CHEQUE", "زجاج وأبواب", "كسر في زجاج الواجهة الداخلية نتيجة الاستعمال", "normal", ("order:صيانة:tenant:210", "tenantdone")),
        ("CHARITY", "نظافة", "تراكم مخلفات في المدخل المشترك للطابق", "low", ()),
        ("ARR2", "تكييف", "الوحدة لا تبرّد في فترة الظهيرة", "normal", ("triage",)),
        ("TP2", "دهان", "طلب إعادة دهان الجدران بلون مختلف", "low", ("reject",)),
        ("TP3", "سباكة", "خلل في خلاط الماء بالمغسلة", "normal", ("order:سباك:owner:35", "done")),
        ("RENEW", "كهرباء", "استبدال مفاتيح إنارة تالفة", "normal", ("order:كهرب:owner:48", "progress")),
        ("EXPIRED", "نظافة", "تنظيف عميق بعد انتهاء العقد", "normal", ("order:نظاف:company:75", "done", "close")),
    ]
    for tag, cat, desc, prio, steps in flows:
        u = U.get(tag)
        if not u:
            continue
        r = _do(ctx, "finance", M.api_maint_add, M.MaintIn(unit_id=u["id"], category=cat, description=desc, priority=prio, source="tenant" if tag in ("EXP", "ARR2") else "staff",
                                                           requester=f"{DEMO}"))
        if not r:
            continue
        mid = r["id"]
        ctx.add("maintenance")
        oid = None
        for st in steps:
            if st == "triage":
                _do(ctx, "finance", M.api_maint_status, mid, M.MaintStatus(status="triaged"))
            elif st.startswith("order:"):
                _, trade, charge, cost = st.split(":")
                o = _do(ctx, "finance", M.api_order_add, mid, M.OrderIn(vendor_id=_vendor(ctx, trade) or _vendor(ctx, "صيانة"), scheduled=T + dt.timedelta(days=2), cost=float(cost),
                                                                       charge_to=charge, basis="البند 12 من العقد ومحضر المعاينة" if charge == "tenant" else ""))
                oid = o["id"] if o else None
            elif st == "progress":
                _do(ctx, "finance", M.api_maint_status, mid, M.MaintStatus(status="in_progress"))
            elif st == "done" and oid:
                _do(ctx, "finance", M.api_order_done, oid, M.OrderDone(done_at=T - dt.timedelta(days=3), doc_ref=f"أمر عمل {oid}"))
            elif st == "tenantdone" and oid:
                _do(ctx, "admin", M.api_order_done, oid, M.OrderDone(done_at=T - dt.timedelta(days=2), doc_ref=f"أمر عمل {oid}"))
            elif st == "close":
                _do(ctx, "finance", M.api_maint_status, mid, M.MaintStatus(status="closed"))
            elif st == "reject":
                _do(ctx, "finance", M.api_maint_status, mid, M.MaintStatus(status="rejected", note="الطلب تحسيني ولا يدخل في التزامات المؤجر"))


def _expenses(ctx, U, ids, owner):
    from . import leasing_mgmt as M
    if _one(ctx, "SELECT 1 x FROM property_expenses WHERE doc_ref LIKE 'DEMO-%'"):
        return
    T = ctx.today
    plist = _projects(ctx)
    p1, p2 = plist[0], plist[min(1, len(plist) - 1)]
    rows_ = []
    for k in range(1, 5):                      # the last four months
        d = _addm(T.replace(day=1), -k) + dt.timedelta(days=14)
        rows_ += [(p1["id"], None, "نظافة المرافق المشتركة", 590.0 - 20 * k, d, "نظاف", False), (p1["id"], None, "حراسة وأمن", 750.0, d, "أمن", False),
                  (p2["id"], None, "كهرباء ومياه المرافق المشتركة", 260.0 + 15 * k, d, None, False)]
    rows_ += [(p1["id"], None, "تكافل المباني", 1450.0, _addm(T.replace(day=1), -5) + dt.timedelta(days=9), None, False),
              (p2["id"], None, "تسويق وإعلان الوحدات الشاغرة", 480.0, T - dt.timedelta(days=21), "إعلان", False)]
    if U.get("TP1") and owner:
        rows_ += [(None, U["TP1"]["id"], "صيانة مصعد المبنى — حصة الوحدة", 110.0, _addm(T.replace(day=1), -1) + dt.timedelta(days=11), "صيانة", True),
                  (None, U["TP2"]["id"], "كهرباء ومياه مشتركة — حصة الوحدة", 64.5, _addm(T.replace(day=1), -1) + dt.timedelta(days=12), None, True)]
    for i, (pid, uid, cat, amt, day, vendor, charge_owner) in enumerate(rows_):
        if day < dt.date(T.year, 1, 1) or day > T:
            continue
        r = _do(ctx, "finance", M.api_expense_add, M.ExpenseIn(project_id=pid, unit_id=uid, category=cat, amount=round(amt, 3), spent_on=day, vendor_id=_vendor(ctx, vendor) if vendor else None,
                                                              charge_owner=charge_owner, description=f"{cat} — {DEMO}", doc_ref=f"DEMO-EXP-{i + 1:03d}"))
        if r:
            ctx.add("expenses")


def _facilities(ctx):
    done = 0
    for p in _projects(ctx):
        if p["code"] in ("QRM",):
            continue
        for name, kind in (("المدخل الرئيسي واللوبي", "lobby"), ("مواقف السيارات", "parking"), ("المصاعد", "elevators"), ("المولد الاحتياطي", "generator"), ("غرفة الحراسة", "security")):
            if not _one(ctx, "SELECT 1 x FROM common_facilities WHERE project_id=? AND name=?", (p["id"], name)):
                _exec(ctx, "INSERT INTO common_facilities(project_id,name,kind,notes) VALUES(?,?,?,?)", (p["id"], name, kind, DEMO))
                done += 1
        if done > 24:
            break
    ctx.add("facilities", done)


def _statements(ctx, owner):
    from . import leasing_mgmt as M
    T = ctx.today
    own = _one(ctx, "SELECT id FROM owners WHERE kind='own' ORDER BY id LIMIT 1")
    for k in (2, 1):                           # the two last full months
        d = _addm(T.replace(day=1), -k)
        period = f"{d.year}-{d.month:02d}"
        for who in ([owner["id"]] if owner else []) + ([own["id"]] if own and k == 1 else []):
            if _one(ctx, "SELECT 1 x FROM owner_statements WHERE owner_id=? AND period=?", (who, period)):
                continue
            r = _do(ctx, "admin", M.api_statement_issue, who, M.StatementIn(period=period))
            if r:
                ctx.add("statements")
                if owner and who == owner["id"] and r.get("net", 0) > 0.0005:
                    _do(ctx, "admin", M.api_statement_transferred, r["id"], M.TransferIn(on=min(T, d.replace(day=28) + dt.timedelta(days=9)), ref=f"حوالة {period} {DEMO}"))
