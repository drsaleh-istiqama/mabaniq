"""Mabaniq 0.29.0 — seed phase `pol`: the policy register of a full-demo developer (see seed_org.py for the contract).

~28 default policies and regulations (texts in seed_org_pol_hr.py / seed_org_pol_gov.py) go in through the register's own endpoint functions as two different people — a policy is
prepared by one of the HR officer / general manager and approved by the other — so the maker ≠ checker rule is exercised, not bypassed. A few are deliberately left in other states so the
screen shows every one: a draft (remote work), a policy with a retired first version and an approved second (code of conduct), a policy with a revision waiting as a draft (procurement), and two
whose review date has passed. Acknowledgements are then recorded for a plausible share of the staff (employees found in the file, by their portal login name), older policies more
than newer ones; the timestamps are moved back to the effective date, since they would otherwise all read "today".

The texts quote the organisation's own figures (leave days, insurance rates, end-of-service rule, bylaw articles, working hours) read from its tables, so they cannot contradict the other
screens. Illustrative only — every record says "نموذج افتراضي للتجربة — يراجعه مختص قانوني قبل الاعتماد الفعلي" in its basis.
"""
from __future__ import annotations

import datetime as dt
import json

from . import hr_leave, policies
from .seed_org import Skip
from .seed_org_pol_gov import gov_policies
from .seed_org_pol_hr import hr_policies

DISCLAIMER = "نموذج افتراضي للتجربة — يراجعه مختص قانوني قبل الاعتماد الفعلي"
ACK_DEFAULT = ("hr", "compliance", "governance")
HR_MAKER = ("hr", "admin")   # (preparer, approver) for HR-owned policies …
OTHER_MAKER = ("admin", "hr")  # … and for everything else (only these two roles carry `policies_admin`)


def _facts(c, today: dt.date) -> dict:
    iso = today.isoformat()
    leave = {r["key"]: dict(r) for r in c.execute("SELECT * FROM leave_types WHERE active=1 AND valid_from<=? ORDER BY valid_from", (iso,)).fetchall()}
    rates = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM hr_rates WHERE valid_from<=? ORDER BY valid_from", (iso,)).fetchall() if r["value"] is not None}
    eosb = {}
    for r in c.execute("SELECT grp, tiers, cap_months FROM eosb_rules WHERE valid_from<=? ORDER BY valid_from", (iso,)).fetchall():
        try:
            eosb[r["grp"]] = {"tiers": json.loads(r["tiers"]), "cap_months": r["cap_months"]}
        except ValueError:
            continue
    pens = [dict(r) for r in c.execute("SELECT code, name, description, kind, max_days FROM penalty_rules WHERE status='approved' ORDER BY code").fetchall()]
    return {"leave": leave, "rates": rates, "eosb": eosb, "penalties": pens, "weekend": hr_leave.weekend(c), "work_start": hr_leave.work_start(c), "late_grace": hr_leave.late_grace(c)}


def _article_models(arts) -> list:
    return [policies.Article(no=str(i), title=t[:120], text=x[:4000]) for i, (t, x) in enumerate(arts, 1)]


def _model(p: dict, arts) -> policies.PolicyIn:
    return policies.PolicyIn(code=p["code"], title=p["title"], category=p["category"], owner_role=p["owner"][:80], summary=p["summary"][:600], articles=_article_models(arts),
                             basis=f"{p['basis']} — {DISCLAIMER}"[:400], review_months=p.get("review", 12), ack_required=p.get("ack", p["category"] in ACK_DEFAULT))


def _row(ctx, sql, args=()):
    with ctx.request():
        c = ctx.conn()
        return c.execute(sql, args).fetchone()


def _exec(ctx, sql, args=()):
    with ctx.request():
        c = ctx.conn()
        c.execute(sql, args)
        c.commit()


def _backdate(ctx, pid: int, effective: dt.date) -> None:
    """A policy approved 'today' with an effective date months ago reads oddly: move the approval two days before the effective date."""
    _exec(ctx, "UPDATE policies SET approved_at=? WHERE id=?", ((effective - dt.timedelta(days=2)).isoformat() + "T09:00:00", pid))


def _one_policy(ctx, p: dict) -> None:
    maker_k, checker_k = HR_MAKER if p["category"] == "hr" else OTHER_MAKER
    maker, checker = ctx.act(maker_k), ctx.user(checker_k)
    eff = ctx.today - dt.timedelta(days=p.get("days_ago", 200))
    have = _row(ctx, "SELECT id, status, version FROM policies WHERE code=? ORDER BY version DESC LIMIT 1", (p["code"],))
    if have:   # re-run after a partial first run: a policy that exists is left as it is
        return
    first_arts = p.get("v1_arts") or p["arts"]
    pid = ctx.call(policies.api_create, _model(p, first_arts), maker)["id"]
    ctx.add("policies")
    if p.get("draft"):
        ctx.add("drafts")
        return
    first_eff = ctx.today - dt.timedelta(days=p["v1_days_ago"]) if p.get("v1_days_ago") else eff
    ctx.act(checker_k)
    ctx.call(policies.api_approve, pid, policies.ApproveIn(effective_from=first_eff.isoformat()), checker)
    _backdate(ctx, pid, first_eff)
    if p.get("v1_arts") or p.get("v2_draft"):   # a second version: a draft revision, or a revision that has already replaced the first
        ctx.act(maker_k)
        nid = ctx.call(policies.api_new_version, pid, maker)["id"]
        arts2 = p.get("v2_arts") or p["arts"]
        ctx.call(policies.api_edit, nid, policies.PolicyPatch(articles=_article_models(arts2)), maker)
        ctx.add("versions")
        if p.get("v2_draft"):
            ctx.add("drafts")
            return
        ctx.act(checker_k)
        ctx.call(policies.api_approve, nid, policies.ApproveIn(effective_from=eff.isoformat()), checker)
        _backdate(ctx, nid, eff)
        _exec(ctx, "UPDATE policies SET retired_at=? WHERE id=?", ((eff - dt.timedelta(days=2)).isoformat() + "T09:00:00", pid))


def _people(ctx) -> list[dict]:
    """Who 'reads the policies': the active employees (their portal login name if they have one, else the name the portal would give them); the staff actors if there are none."""
    with ctx.request():
        c = ctx.conn()
        rows = c.execute("""SELECT e.id, e.number, e.name, u.username FROM employees e LEFT JOIN users u ON u.employee_id=e.id WHERE e.status!='terminated' ORDER BY e.number""").fetchall()
    out = [{"employee_id": r["id"], "name": r["name"], "username": r["username"] or "emp" + r["number"].split("-")[-1].lower()} for r in rows]
    if out:
        return out
    from .seed_org import ACTORS
    return [{"employee_id": None, "name": name, "username": un} for un, name, _role in ACTORS.values()]


def _acks(ctx) -> None:
    people = _people(ctx)
    with ctx.request():
        c = ctx.conn()
        approved = [dict(r) for r in c.execute("SELECT id, code, version, effective_from FROM policies WHERE status='approved' AND ack_required=1 ORDER BY id").fetchall()]
        done = {r["policy_id"] for r in c.execute("SELECT DISTINCT policy_id FROM policy_acks").fetchall()}
    base = ctx.user("hr")
    for pol in approved:
        if pol["id"] in done:
            continue
        eff = dt.date.fromisoformat(pol["effective_from"])
        age = max(0, (ctx.today - eff).days)
        cover = max(0.3, 0.97 - age / 700) if age > 14 else 0.25   # a policy that came into force last week has been read by few
        for pe in people:
            if ctx.rnd.random() > cover:
                continue
            u = {**base, "username": pe["username"], "name": pe["name"], "employee_id": pe["employee_id"], "perms": ["policies"]}
            try:
                ctx.call(policies.api_ack, pol["id"], u)
            except Skip:
                continue
            day = min(ctx.today, eff + dt.timedelta(days=ctx.rnd.randint(1, 12)))
            _exec(ctx, "UPDATE policy_acks SET acked_at=? WHERE policy_id=? AND username=?", (f"{day.isoformat()}T{ctx.rnd.randint(8, 16):02d}:{ctx.rnd.randint(0, 59):02d}:00", pol["id"], pe["username"]))
            ctx.add("acks")


def run(ctx) -> dict:
    from .tenant_profiles import profile
    org = (profile(ctx.tenant) or {}).get("brand", {}).get("name") or ctx.tenant
    commercial = ctx.tenant == "bayan"            # Bayan: offices, shops and leasing; Mukhatat: apartments, villas and off-plan sales
    with ctx.request():
        c = ctx.conn()
        facts = _facts(c, ctx.today)
    items = hr_policies(org, facts, commercial) + gov_policies(org, facts, commercial)
    for p in items:
        _one_policy(ctx, p)
    _acks(ctx)
    return ctx.counts
