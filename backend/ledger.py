"""Mabaniq 0.23.0 — accounting core: the ledger engine (design docs/DESIGN-leasing-accounting-hr-modules.md §4, phase 3a).

What lives here: the chart of accounts seed, cost centres, periods, the single writer of journals (`post`), reversal, and the posting rules that carry the
leasing events to the ledger. The HTTP surface is `accounting.py`.

Rules kept on purpose:
* A journal is written as a draft, its lines are added, and only then does it become `posted` — the database refuses that step unless debit = credit with at
  least two lines, and refuses any later change (PostgreSQL trigger + SQLite mirror). A mistake is corrected by a reversing journal, never by an edit.
* Nothing is guessed: a receipt whose method was never recorded goes to its own account (`receipts_unclassified`), not to cash or bank by assumption.
* Events before `acc_start` are never posted — they are the opening balance (a documented trial balance), not a re-construction.
* Posting is idempotent: every automatic journal carries a unique `source_key`; the sweep (`autopost`) posts what is missing and nothing twice. A change to a
  source that was already carried (a rent due cut by a payment plan or a termination) posts only the difference (`acc_source_state`).
* Agency: the rent of a unit managed for a third-party owner is the owner's money — the company books the cash and a liability to the owner
  (`ap_owners`), and its own revenue is the management commission only.
* Late-payment charity is a liability (`charity_payable`) that is paid out to a charity — never revenue.
* VAT: lines carry a `vat_class` (rent: residential exempt, other uses standard) but no VAT amount is split in this phase (design §4.5, phase 3b).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from fastapi import HTTPException

from .common import ACTOR, audit, now_s, rows, today
from .db import setting

EPS = 0.0005
COA_FILE = Path(__file__).resolve().parent / "assets" / "coa_om.json"
DEPOSIT_OFFSET = "خصم من التأمين"  # the reference leasing_ops puts on a payment that settles a due out of the deposit


class LedgerError(Exception):
    """A posting that cannot be made now (missing account, closed period, unbalanced lines). Carries an Arabic message."""


def r3(v) -> float:
    return round(float(v or 0) + 0.0, 3)


# ----------------------------------------------------------------------------------------------------- activation
def module_on(c) -> bool:
    from . import registry
    return "accounting" in registry.enabled_modules(c)


def start_date(c) -> str | None:
    if not c.has_table("acc_journals"):
        return None
    return setting(c, "acc_start") or None


def active(c) -> str | None:
    """The date accounting starts from, when the module is on and activated; else None (nothing is posted)."""
    s = start_date(c)
    return s if s and module_on(c) else None


def ensure_chart(c) -> int:
    """Seed the Omani default chart once (an organisation that already has accounts keeps its own)."""
    if c.execute("SELECT 1 FROM acc_accounts LIMIT 1").fetchone():
        return 0
    data = json.loads(COA_FILE.read_text(encoding="utf-8"))
    ids: dict[str, int] = {}
    for a in data["accounts"]:
        normal = a.get("normal") or ("debit" if a["type"] in ("asset", "expense") else "credit")
        ids[a["code"]] = c.execute(
            "INSERT INTO acc_accounts(code,name,name_en,type,parent_id,postable,normal,system_key,vat_class,cash_class,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (a["code"], a["name"], a.get("name_en"), a["type"], ids.get(a.get("parent")), a.get("postable", 1), normal, a.get("system_key"), a.get("vat_class"),
             a.get("cash_class"), a.get("note"))).lastrowid
    return len(ids)


def activate(c, start: dt.date, by: str) -> dict:
    """Switch accounting on from `start`. The date can be moved only while nothing has been posted."""
    cur = start_date(c)
    if cur and cur != start.isoformat() and c.execute("SELECT 1 FROM acc_journals WHERE status IN ('posted','reversed') LIMIT 1").fetchone():
        raise HTTPException(409, "لا يُغيَّر تاريخ بدء المحاسبة بعد ترحيل قيود")
    seeded = ensure_chart(c)
    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ("acc_start", start.isoformat()))
    for pr in c.execute("SELECT id FROM projects").fetchall():
        cost_center_for_project(c, pr["id"])
    audit(c, "تفعيل المحاسبة", f"تاريخ البدء {start.isoformat()} · {seeded} حسابًا مبذورًا")
    return {"start": start.isoformat(), "accounts_seeded": seeded}


# ----------------------------------------------------------------------------------------------------- lookups
class Ctx:
    """Per-run caches so a sweep over thousands of events does not re-query the same account, cost centre or lease."""

    def __init__(self, c):
        self.c = c
        self._acc: dict[str, int] = {}
        self._cc: dict[int, int | None] = {}
        self._lease: dict[int, dict] = {}

    def acct(self, key_or_id) -> int:
        if isinstance(key_or_id, int):
            return key_or_id
        if key_or_id not in self._acc:
            r = self.c.execute("SELECT id, active, postable FROM acc_accounts WHERE system_key=?", (key_or_id,)).fetchone()
            if not r:
                raise LedgerError(f"لا حساب مربوط بالمفتاح «{key_or_id}» في دليل الحسابات")
            if not r["active"] or not r["postable"]:
                raise LedgerError(f"الحساب المربوط بالمفتاح «{key_or_id}» موقوف أو غير قابل للترحيل")
            self._acc[key_or_id] = r["id"]
        return self._acc[key_or_id]

    def cc(self, project_id) -> int | None:
        if not project_id:
            return None
        if project_id not in self._cc:
            self._cc[project_id] = cost_center_for_project(self.c, project_id)
        return self._cc[project_id]

    def lease(self, lease_id: int) -> dict:
        if lease_id not in self._lease:
            r = self.c.execute("""SELECT l.id, l.number, l.tenant_id, l.unit_id, u.project_id, u.owner_id, COALESCE(u.use,'residential') use, o.kind owner_kind, t.name tenant
                                  FROM leases l JOIN units u ON u.id=l.unit_id LEFT JOIN owners o ON o.id=u.owner_id LEFT JOIN tenants_l t ON t.id=l.tenant_id
                                  WHERE l.id=?""", (lease_id,)).fetchone()
            d = dict(r) if r else {}
            d["managed"] = bool(d.get("owner_id") and d.get("owner_kind") not in (None, "own"))
            self._lease[lease_id] = d
        return self._lease[lease_id]


def cost_center_for_project(c, project_id: int) -> int | None:
    r = c.execute("SELECT id FROM acc_cost_centers WHERE kind='project' AND ref_id=?", (project_id,)).fetchone()
    if r:
        return r["id"]
    p = c.execute("SELECT id, name FROM projects WHERE id=?", (project_id,)).fetchone()
    if not p:
        return None
    return c.execute("INSERT INTO acc_cost_centers(code,name,kind,ref_id) VALUES(?,?,?,?)", (f"P{p['id']:03d}", p["name"], "project", p["id"])).lastrowid


def period_for(c, d: dt.date) -> dict:
    r = c.execute("SELECT * FROM acc_periods WHERE year=? AND month=?", (d.year, d.month)).fetchone()
    if not r:
        c.execute("INSERT INTO acc_periods(year,month) VALUES(?,?)", (d.year, d.month))
        r = c.execute("SELECT * FROM acc_periods WHERE year=? AND month=?", (d.year, d.month)).fetchone()
    return dict(r)


def _open_period(c, d: dt.date) -> int:
    p = period_for(c, d)
    if p["status"] != "open":
        raise LedgerError(f"الفترة {d.year}-{d.month:02d} مقفلة")
    return p["id"]


def next_number(c, d: dt.date) -> str:
    """JV-<year>-<seq>: gapless per year — the counter row is locked by the UPDATE and rolls back with the journal."""
    key = f"jv:{d.year}"
    c.execute("INSERT OR IGNORE INTO counters(k,n) VALUES(?,0)", (key,))
    c.execute("UPDATE counters SET n=n+1 WHERE k=?", (key,))
    return f"JV-{d.year}-{c.execute('SELECT n FROM counters WHERE k=?', (key,)).fetchone()['n']:05d}"


# ----------------------------------------------------------------------------------------------------- the writer
def _norm_lines(ctx: Ctx, lines: list[dict]) -> list[dict]:
    out = []
    for ln in lines:
        d, k = r3(ln.get("debit")), r3(ln.get("credit"))
        if d < 0 or k < 0:
            raise LedgerError("مبلغ سالب في سطر قيد")
        if d > EPS and k > EPS:
            raise LedgerError("سطر القيد إما مدين أو دائن لا الاثنان")
        if d <= EPS and k <= EPS:
            continue
        out.append({"account_id": ctx.acct(ln["account"]), "debit": d, "credit": k, "cost_center_id": ln.get("cc"), "party_type": ln.get("party_type"),
                    "party_id": ln.get("party_id"), "vat_class": ln.get("vat_class"), "memo": ln.get("memo")})
    if len(out) < 2:
        raise LedgerError("القيد يحتاج سطرين على الأقل")
    diff = r3(sum(x["debit"] for x in out) - sum(x["credit"] for x in out))
    if abs(diff) > EPS:
        raise LedgerError(f"القيد غير متوازن (الفرق {diff:,.3f})")
    return out


def insert_draft(c, ctx: Ctx, *, d: dt.date, memo: str, lines: list[dict], kind: str, by: str, source_kind=None, source_ref=None, source_key=None,
                 reversal_of=None) -> int:
    ls = _norm_lines(ctx, lines)
    total = r3(sum(x["debit"] for x in ls))
    pid = period_for(c, d)["id"]
    jid = c.execute("""INSERT INTO acc_journals(jdate,period_id,memo,kind,source_kind,source_ref,source_key,status,created_by,reversal_of,total) VALUES(?,?,?,?,?,?,?,'draft',?,?,?)""",
                    (d.isoformat(), pid, memo, kind, source_kind, source_ref, source_key, by, reversal_of, total)).lastrowid
    for i, x in enumerate(ls, 1):
        c.execute("""INSERT INTO acc_lines(journal_id,line_no,account_id,cost_center_id,debit,credit,party_type,party_id,vat_class,memo) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (jid, i, x["account_id"], x["cost_center_id"], x["debit"], x["credit"], x["party_type"], x["party_id"], x["vat_class"], x["memo"]))
    return jid


def finalize(c, jid: int, by: str, approved_by: str | None = None) -> str:
    """draft/pending → posted. The period must be open; the database checks the balance and then freezes the journal."""
    j = c.execute("SELECT * FROM acc_journals WHERE id=?", (jid,)).fetchone()
    d = dt.date.fromisoformat(j["jdate"])
    _open_period(c, d)
    number = next_number(c, d)
    c.execute("UPDATE acc_journals SET status='posted', number=?, posted_by=?, posted_at=?, approved_by=COALESCE(?,approved_by) WHERE id=?", (number, by, now_s(), approved_by, jid))
    return number


def post(c, *, date: dt.date, lines: list[dict], memo: str, source_kind: str | None = None, source_ref: str | None = None, source_key: str | None = None,
         kind: str = "auto", by: str | None = None, ctx: Ctx | None = None) -> int | None:
    """Write one balanced journal and post it. Returns the journal id, or None when `source_key` has already been posted (idempotent)."""
    by = by or ACTOR.get() or "النظام"
    ctx = ctx or Ctx(c)
    if source_key and c.execute("SELECT 1 FROM acc_journals WHERE source_key=?", (source_key,)).fetchone():
        return None
    _open_period(c, date)
    jid = insert_draft(c, ctx, d=date, memo=memo, lines=lines, kind=kind, by=by, source_kind=source_kind, source_ref=source_ref, source_key=source_key)
    finalize(c, jid, by)
    return jid


def reverse(c, jid: int, on: dt.date, reason: str, by: str) -> int:
    """Post the mirror image of a posted journal and mark the original reversed; the original is never touched otherwise."""
    j = c.execute("SELECT * FROM acc_journals WHERE id=?", (jid,)).fetchone()
    if not j or j["status"] != "posted":
        raise HTTPException(409, "يُعكس القيد المرحَّل فقط")
    if on < dt.date.fromisoformat(j["jdate"]):
        raise HTTPException(400, "تاريخ العكس لا يسبق تاريخ القيد")
    ctx = Ctx(c)
    ls = [{"account": x["account_id"], "debit": x["credit"], "credit": x["debit"], "cc": x["cost_center_id"], "party_type": x["party_type"], "party_id": x["party_id"],
           "vat_class": x["vat_class"], "memo": x["memo"]} for x in rows(c.execute("SELECT * FROM acc_lines WHERE journal_id=? ORDER BY line_no", (jid,)))]
    try:
        _open_period(c, on)
        rid = insert_draft(c, ctx, d=on, memo=f"عكس {j['number']} — {reason}", lines=ls, kind="reversal", by=by, reversal_of=jid)
    except LedgerError as e:
        raise HTTPException(409, str(e)) from None
    finalize(c, rid, by, approved_by=by)
    c.execute("UPDATE acc_journals SET status='reversed', reversed_by=? WHERE id=?", (rid, jid))
    audit(c, "عكس قيد", f"{j['number']} ← {c.execute('SELECT number FROM acc_journals WHERE id=?', (rid,)).fetchone()['number']} · {reason}")
    return rid


# ----------------------------------------------------------------------------------------------------- posting rules (leasing events)
CATEGORY_KEYS = (("صيانة", "exp_maint"), ("إصلاح", "exp_maint"), ("سباك", "exp_maint"), ("كهرب", "exp_utilities"), ("ماء", "exp_utilities"), ("مياه", "exp_utilities"),
                 ("مرافق", "exp_utilities"), ("نظاف", "exp_clean"), ("بستن", "exp_clean"), ("أمن", "exp_security"), ("حراس", "exp_security"), ("تكافل", "exp_takaful"),
                 ("تسويق", "exp_marketing"), ("إعلان", "exp_marketing"))


def expense_key(category: str | None) -> str:
    for word, key in CATEGORY_KEYS:
        if word in (category or ""):
            return key
    return "exp_property_other"


def _cash_key(method, reference) -> str:
    if method == "other" and (reference or "").startswith(DEPOSIT_OFFSET):
        return "deposits_held"  # the due was settled out of the tenant's deposit: no cash moved
    return {"cash": "cash", "transfer": "bank_main", "card": "bank_main", "cheque": "bank_main", "other": "bank_main"}.get(method, "receipts_unclassified")


def _agency(L: dict, dkind) -> bool:
    """True when the money belongs to a third-party owner (rent of a managed unit); every other kind of due is the company's."""
    return bool(L.get("managed")) and (dkind or "rent") == "rent"


def _vat_class(L: dict) -> str:
    return "exempt" if L.get("use") == "residential" else "standard"


def _plan_originals(c) -> dict[int, float]:
    out: dict[int, float] = {}
    for p in c.execute("SELECT original FROM payment_plans").fetchall():
        for o in json.loads(p["original"] or "[]"):
            out[int(o["due_id"])] = float(o["amount"])
    return out


def sync_dues(c, ctx: Ctx, start: str, as_of: dt.date, lease_id: int | None, dry: bool, res: dict) -> None:
    """Rent and other dues become receivable + revenue on their due date. Only the difference to what was already carried is posted."""
    originals = _plan_originals(c)
    q = """SELECT d.id, d.lease_id, d.due, d.amount, d.kind, d.plan_id, COALESCE(s.posted,0) posted, COALESCE(s.n,0) n, (s.id IS NOT NULL) has_state
           FROM rent_dues d JOIN leases l ON l.id=d.lease_id LEFT JOIN acc_source_state s ON s.source_kind='due' AND s.source_ref=CAST(d.id AS TEXT)
           WHERE COALESCE(d.kind,'rent')<>'deposit' AND d.due>=? AND d.due<=? AND l.status<>'draft' AND COALESCE(l.termination_kind,'')<>'cancelled_draft'"""
    args: list = [start, as_of.isoformat()]
    if lease_id:
        q += " AND d.lease_id=?"
        args.append(lease_id)
    for d in c.execute(q, args).fetchall():
        L = ctx.lease(d["lease_id"])
        if not L or _agency(L, d["kind"]):
            continue
        target = 0.0 if d["plan_id"] else r3(originals.get(d["id"], d["amount"]))
        delta = r3(target - d["posted"])
        if abs(delta) <= EPS:
            continue
        res["pending"]["dues"] += 1
        if dry:
            continue
        rev = {"rent": "rev_rent", "service": "rev_recoveries"}.get(d["kind"] or "rent", "rev_other")
        party = {"party_type": "tenant", "party_id": L["tenant_id"]}
        a, b = ("ar_tenants", rev) if delta > 0 else (rev, "ar_tenants")
        amt = abs(delta)
        memo = f"استحقاق {d['kind'] or 'rent'} — عقد {L['number']} — {L['tenant']}" + ("" if delta > 0 else " (تخفيض)")
        try:
            post(c, date=dt.date.fromisoformat(d["due"]), memo=memo, source_kind="due", source_ref=str(d["id"]), source_key=f"due:{d['id']}#{d['n'] + 1}", ctx=ctx,
                 lines=[dict(account=a, debit=amt, cc=ctx.cc(L["project_id"]), **(party if a == "ar_tenants" else {}), vat_class=_vat_class(L) if a == rev else None),
                        dict(account=b, credit=amt, cc=ctx.cc(L["project_id"]), **(party if b == "ar_tenants" else {}), vat_class=_vat_class(L) if b == rev else None)])
        except LedgerError as e:
            res["errors"].append(f"استحقاق {d['id']}: {e}")
            continue
        if d["has_state"]:
            c.execute("UPDATE acc_source_state SET posted=?, n=n+1 WHERE source_kind='due' AND source_ref=?", (target, str(d["id"])))
        else:
            c.execute("INSERT INTO acc_source_state(source_kind,source_ref,posted,n) VALUES('due',?,?,1)", (str(d["id"]), target))
        res["posted"]["dues"] += 1


def sync_payments(c, ctx: Ctx, start: str, lease_id: int | None, dry: bool, res: dict) -> None:
    q = """SELECT p.*, d.kind dkind FROM rent_payments p LEFT JOIN rent_dues d ON d.id=p.due_id
           WHERE p.paid_on>=? AND NOT EXISTS (SELECT 1 FROM acc_journals j WHERE j.source_key='payment:'||p.id)"""
    args: list = [start]
    if lease_id:
        q += " AND p.lease_id=?"
        args.append(lease_id)
    for p in c.execute(q + " ORDER BY p.id", args).fetchall():
        res["pending"]["payments"] += 1
        if dry:
            continue
        L = ctx.lease(p["lease_id"])
        if not L:
            continue
        cash = _cash_key(p["method"], p["reference"])
        if p["dkind"] == "deposit":
            other, party = "deposits_held", {"party_type": "tenant", "party_id": L["tenant_id"]}
        elif _agency(L, p["dkind"]):
            other, party = "ap_owners", {"party_type": "owner", "party_id": L["owner_id"]}
        else:
            other, party = "ar_tenants", {"party_type": "tenant", "party_id": L["tenant_id"]}
        amt = r3(abs(p["amount"]))
        a, b = (cash, other) if p["amount"] > 0 else (other, cash)
        memo = f"{'تحصيل' if p['amount'] > 0 else 'عكس تحصيل'} {p['receipt_no'] or ''} — عقد {L['number']} — {L['tenant']}".replace("  ", " ")
        try:
            post(c, date=dt.date.fromisoformat(p["paid_on"]), memo=memo, source_kind="payment", source_ref=str(p["id"]), source_key=f"payment:{p['id']}", ctx=ctx,
                 lines=[dict(account=a, debit=amt, cc=ctx.cc(L["project_id"]), **(party if a == other else {})),
                        dict(account=b, credit=amt, cc=ctx.cc(L["project_id"]), **(party if b == other else {}))])
        except LedgerError as e:
            res["errors"].append(f"حركة تحصيل {p['id']}: {e}")
            continue
        res["posted"]["payments"] += 1


def sync_charity(c, ctx: Ctx, start: str, dry: bool, res: dict) -> None:
    """Late-payment charity: collected ⟵ liability to the charity; disbursed ⟵ liability settled. Never revenue."""
    for d in c.execute("SELECT * FROM charity_dues WHERE rent_due_id IS NOT NULL AND status IN ('collected','disbursed') ORDER BY id").fetchall():
        L = ctx.lease(d["lease_id"]) if d["lease_id"] else {}
        amt = r3(d["amount"])
        if amt <= EPS:
            continue
        steps = [("collected", d["collected_at"], "bank_charity", "charity_payable", f"تحصيل تبرع تأخير — {d['collected_ref'] or ''}")]
        if d["status"] == "disbursed":
            steps.append(("disbursed", d["disbursed_at"], "charity_payable", "bank_charity", f"صرف تبرع تأخير إلى {d['beneficiary'] or ''} — {d['disbursed_ref'] or ''}"))
        for step, at, dr, cr, memo in steps:
            key = f"charity:{d['id']}:{step}"
            day = (at or "")[:10] or today().isoformat()
            if day < start or c.execute("SELECT 1 FROM acc_journals WHERE source_key=?", (key,)).fetchone():
                continue
            res["pending"]["charity"] += 1
            if dry:
                continue
            try:
                post(c, date=dt.date.fromisoformat(day), memo=memo, source_kind="charity", source_ref=str(d["id"]), source_key=key, ctx=ctx,
                     lines=[dict(account=dr, debit=amt, cc=ctx.cc(L.get("project_id"))), dict(account=cr, credit=amt, cc=ctx.cc(L.get("project_id")))])
            except LedgerError as e:
                res["errors"].append(f"تبرع {d['id']}: {e}")
                continue
            res["posted"]["charity"] += 1


def sync_expenses(c, ctx: Ctx, start: str, dry: bool, res: dict) -> None:
    for e in c.execute("""SELECT e.*, o.kind owner_kind FROM property_expenses e LEFT JOIN owners o ON o.id=e.owner_id
                          WHERE e.spent_on>=? AND COALESCE(e.status,'posted')='posted' AND NOT EXISTS (SELECT 1 FROM acc_journals j WHERE j.source_key='expense:'||e.id)
                          ORDER BY e.id""", (start,)).fetchall():
        res["pending"]["expenses"] += 1
        if dry:
            continue
        agency = bool(e["owner_id"]) and e["owner_kind"] not in (None, "own") and e["charge_owner"]
        debit = "ap_owners" if agency else expense_key(e["category"])
        dparty = {"party_type": "owner", "party_id": e["owner_id"]} if agency else {}
        vparty = {"party_type": "vendor", "party_id": e["vendor_id"]} if e["vendor_id"] else {}
        amt = r3(e["amount"])
        try:
            post(c, date=dt.date.fromisoformat(e["spent_on"]), memo=f"مصروف عقار — {e['category'] or ''} {e['description'] or ''}".strip(), source_kind="expense",
                 source_ref=str(e["id"]), source_key=f"expense:{e['id']}", ctx=ctx,
                 lines=[dict(account=debit, debit=amt, cc=ctx.cc(e["project_id"]), **dparty), dict(account="ap_vendors", credit=amt, cc=ctx.cc(e["project_id"]), **vparty)])
        except LedgerError as err:
            res["errors"].append(f"مصروف {e['id']}: {err}")
            continue
        res["posted"]["expenses"] += 1


def sync_statements(c, ctx: Ctx, start: str, dry: bool, res: dict) -> None:
    """Owner statements: the commission is the company's revenue (taken from the owner's funds); the transfer pays the owner out."""
    for s in c.execute("""SELECT s.*, o.kind owner_kind FROM owner_statements s JOIN owners o ON o.id=s.owner_id WHERE o.kind<>'own' ORDER BY s.id""").fetchall():
        party = {"party_type": "owner", "party_id": s["owner_id"]}
        com = r3(s["commission"])
        day = (s["issued_at"] or "")[:10]
        key = f"stmt:{s['id']}"
        if abs(com) > EPS and day >= start and not c.execute("SELECT 1 FROM acc_journals WHERE source_key=?", (key,)).fetchone():
            res["pending"]["statements"] += 1
            if not dry:
                a, b = ("ap_owners", "rev_mgmt_fee") if com > 0 else ("rev_mgmt_fee", "ap_owners")
                try:
                    post(c, date=dt.date.fromisoformat(day), memo=f"عمولة إدارة — كشف {s['number']}", source_kind="statement", source_ref=str(s["id"]), source_key=key, ctx=ctx,
                         lines=[dict(account=a, debit=abs(com), **(party if a == "ap_owners" else {})), dict(account=b, credit=abs(com), **(party if b == "ap_owners" else {}))])
                    res["posted"]["statements"] += 1
                except LedgerError as e:
                    res["errors"].append(f"كشف {s['number']}: {e}")
        tkey = f"stmt-transfer:{s['id']}"
        net, tday = r3(s["net"]), (s["transferred_on"] or "")[:10]
        if s["status"] == "transferred" and net > EPS and tday >= start and not c.execute("SELECT 1 FROM acc_journals WHERE source_key=?", (tkey,)).fetchone():
            res["pending"]["statements"] += 1
            if not dry:
                try:
                    post(c, date=dt.date.fromisoformat(tday), memo=f"تحويل صافي المالك — كشف {s['number']} — {s['transfer_ref'] or ''}", source_kind="statement",
                         source_ref=str(s["id"]), source_key=tkey, ctx=ctx,
                         lines=[dict(account="ap_owners", debit=net, **party), dict(account="bank_main", credit=net)])
                    res["posted"]["statements"] += 1
                except LedgerError as e:
                    res["errors"].append(f"تحويل كشف {s['number']}: {e}")


def sync_deposits(c, ctx: Ctx, start: str, dry: bool, res: dict) -> None:
    """Deposit settlement: what the deposit still held is released — refunded in cash, or kept against documented deductions that were not dues."""
    for l in c.execute("SELECT * FROM leases WHERE deposit_settled_at IS NOT NULL AND deposit_state IN ('returned','partly_settled','settled')").fetchall():
        key = f"deposit:{l['id']}"
        day = (l["deposit_settled_at"] or "")[:10]
        if day < start or c.execute("SELECT 1 FROM acc_journals WHERE source_key=?", (key,)).fetchone():
            continue
        res["pending"]["deposits"] += 1
        if dry:
            continue
        L = ctx.lease(l["id"])
        refund, deducted = r3(l["deposit_refund"]), r3(l["deposit_deducted"])
        offset = r3(c.execute("SELECT COALESCE(SUM(amount),0) FROM rent_payments WHERE lease_id=? AND method='other' AND reference LIKE ?", (l["id"], DEPOSIT_OFFSET + "%")).fetchone()[0])
        other = max(r3(deducted - offset), 0.0)
        party = {"party_type": "tenant", "party_id": L["tenant_id"]}
        if refund + other <= EPS:
            continue
        try:
            post(c, date=dt.date.fromisoformat(day), memo=f"تسوية تأمين — عقد {L['number']} — {L['tenant']}", source_kind="deposit", source_ref=str(l["id"]), source_key=key, ctx=ctx,
                 lines=[dict(account="deposits_held", debit=r3(refund + other), cc=ctx.cc(L["project_id"]), **party), dict(account="bank_main", credit=refund, cc=ctx.cc(L["project_id"])),
                        dict(account="rev_recoveries", credit=other, cc=ctx.cc(L["project_id"]))])
        except LedgerError as e:
            res["errors"].append(f"تسوية تأمين {l['id']}: {e}")
            continue
        res["posted"]["deposits"] += 1


SECTIONS = ("dues", "payments", "charity", "expenses", "statements", "deposits")


def autopost(c, lease_id: int | None = None, dry: bool = False, as_of: dt.date | None = None, only: set[str] | None = None) -> dict:
    """Carry every leasing event the ledger is missing to the ledger. Safe to call at any time and from inside a business transaction: it posts nothing
    twice and never raises for a posting problem — the problem is returned in `errors` and the event stays «unposted» (counted in `pending`)."""
    res = {"active": False, "posted": dict.fromkeys(SECTIONS, 0), "pending": dict.fromkeys(SECTIONS, 0), "errors": []}
    start = active(c)
    if not start:
        return res
    res["active"] = True
    ctx = Ctx(c)
    as_of = as_of or today()
    want = set(only) if only else set(SECTIONS)
    if "dues" in want:
        sync_dues(c, ctx, start, as_of, lease_id, dry, res)
    if "payments" in want:
        sync_payments(c, ctx, start, lease_id, dry, res)
    if lease_id is None:
        for name, fn in (("charity", sync_charity), ("expenses", sync_expenses), ("statements", sync_statements), ("deposits", sync_deposits)):
            if name in want:
                fn(c, ctx, start, dry, res)
    return res


def autopost_quiet(c, lease_id: int | None = None, only: set[str] | None = None) -> None:
    """The hook the business code calls inside its own transaction: it must never break the business operation."""
    try:
        if start_date(c):
            autopost(c, lease_id, only=only)
    except LedgerError:
        pass
