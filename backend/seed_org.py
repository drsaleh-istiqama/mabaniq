"""Mabaniq 0.29.0 — a working demo organisation: people, payroll, leave, books, leasing operations, policies.

The two *demo* developers (profile flag `org_demo`: بيان عمان and المخطط العقارية) already carry sales, construction and a few leases. This module fills
every other section so that a visitor can try the whole platform on them — HR, payroll, accounting, leasing operations, governance and policies — with
statistics and reports that are not empty. **Everything it creates is illustrative**: invented people, invented figures, default regulations written for the
trial. The text of a regulation is a starting draft for the organisation's own lawyer, never legal advice; each such row says so in its `source` / note.

How it works (the one rule that matters): the data goes in through the platform's *own* business functions — `hr.create_employee`, `hr_leave.create_request` /
`decide`, `hr_payroll.compute_run` / the run endpoints, `ledger.post`, … — called as synthetic staff users, never by writing the result tables directly.
That keeps every invariant honest (maker ≠ checker, frozen payslips, balanced journals, gapless numbers) and means a change in a module's rules cannot leave
this seed producing impossible data. Two payroll officers are used so a run is computed by one and approved by the other, exactly as in production.

Shape: `ensure_org_demo(tenant)` runs the phases in `PHASES` in order; a phase is skipped when its marker `demo_org:<phase>` is already in `settings`, and a phase that
fails is logged and left unmarked (it is retried at the next tick) without stopping the others. The job is driven by `jobs.tick` (30 s after start-up, then every
15 minutes) — never by the lifespan, so the start-up is not delayed. A phase module is optional: a missing one is skipped.

Phase module contract: `run(ctx) -> dict` (counts for the log). Phases are written to be re-runnable (get-or-create on natural keys), because a crash between a
phase's last commit and its marker would run it again.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import importlib
import random

from fastapi import HTTPException

from .observability import log
from .seed_org_data import ORGS

# marker, module, function — the order matters: the chart and bank accounts exist before payroll posts to them, people exist before leave / payroll
PHASES = (
    ("acc_base", "seed_org_acc", "run_base"),   # chart of accounts, periods, cost centres (one per project), bank accounts, vendors
    ("hr", "seed_org_hr", "run"),               # departments, positions, people, documents, leave, attendance, requests, recruitment, appraisal, training, discipline
    ("pay", "seed_org_pay", "run"),             # rates, components, structures, loans, closed and open payroll runs, end-of-service, a leaver
    ("lea", "seed_org_lea", "run"),             # leasing operations: cheques, maintenance, expenses, meters, notices, owner statements
    ("sales", "seed_org_sales", "run"),         # sales and customer operations: quotes, campaigns and creatives, charity dues, a refund, a resale settlement, decisions, shared documents, a property manager
    ("eng", "seed_org_eng", "run"),             # construction for every project that has none: contract, programme, budget, certificates, change orders, NCRs, site reports, licences
    ("acc_ops", "seed_org_acc", "run_ops"),     # AP bills and payments, fixed assets and depreciation, budgets, VAT return, bank reconciliation
    ("pol", "seed_org_pol", "run"),             # the policy register (regulations, policies) and the default bylaws behind them
    ("rep", "seed_org_rep", "run"),             # saved reports and schedules
)
VERSION = "v1"
MAX_FAILS = 3
LOCK = 7340131  # PostgreSQL advisory lock: one worker fills a tenant, the others find it taken and skip this tick

# default actor names; a profile may override them with `org_demo["actors"]`
ACTORS = {
    "admin": ("seed.admin", "المدير العام", "admin"),
    "hr": ("seed.hr", "مسؤول الموارد البشرية", "hr"),
    "payroll_a": ("seed.payroll.a", "مسؤول الرواتب", "payroll"),
    "payroll_b": ("seed.payroll.b", "مراجع الرواتب", "payroll"),
    "accountant": ("seed.accountant", "المحاسب", "accountant"),
    "finance": ("seed.finance", "المدير المالي", "finance"),
}


def demo_profile(tenant: str) -> dict | None:
    """The `org_demo` block of a tenant's profile, or None when the tenant is not one of the full-demo developers."""
    from .tenant_profiles import profile
    p = profile(tenant) or {}
    d = p.get("org_demo")
    return d if d else None


class Ctx:
    """What a phase needs: the tenant, today, a seeded random generator, the profile data, and a way to act as a synthetic staff user."""

    def __init__(self, tenant: str, today: dt.date, profile: dict):
        self.tenant = tenant
        self.today = today
        self.profile = profile
        self.rnd = random.Random(f"{tenant}:{profile.get('seed', 1)}")
        self.counts: dict = {}

    # -- people who act -----------------------------------------------------------------------------------------------------------
    def user(self, key: str) -> dict:
        """A synthetic staff user shaped like `auth.public()`: the permissions of the role, no employee link (so the self-service guards do not fire)."""
        from .auth import PERMS, ROLES
        un, name, role = ACTORS[key]
        ov = ORGS.get(self.tenant, {}).get("actors", {}).get(key)   # the profile names the login and the employee whose name is shown (seed_org_data.py)
        if ov:
            un = ov[0]
            row = next((e for e in ORGS[self.tenant]["employees"] if e[0] == ov[1]), None)
            name = row[1] if row else name
        return {"id": 0, "username": un, "name": name, "role": role, "role_label": ROLES[role], "perms": sorted(PERMS[role]), "customer_id": None,
                "employee_id": None, "lessee_id": None, "modules": [], "broker_id": None, "must_change": False, "totp_enabled": True, "needs_2fa": False, "tenant": self.tenant}

    def act(self, key: str) -> dict:
        """Become `key` for the audit trail (what `common.act_as` does for a request) and return its user dict."""
        from .common import ACTOR
        u = self.user(key)
        ACTOR.set(f"{u['name']} ({u['role_label']})")
        return u

    @contextlib.contextmanager
    def request(self):
        """One 'request': every connection opened inside is closed (and any half-written transaction rolled back) at the end — a handler that raises an
        HTTPException after a write must not leave the SQLite file locked for the next step."""
        from .common import close_all
        from .db import OPEN
        lst: list = []
        tok = OPEN.set(lst)
        try:
            yield
        finally:
            OPEN.reset(tok)
            close_all(lst)

    def call(self, fn, *a, **kw):
        """Call a module's endpoint function as a request would: returns its result, or raises `Skip(detail)` for an HTTPException (a business rule said no)."""
        with self.request():
            try:
                return fn(*a, **kw)
            except HTTPException as e:
                raise Skip(f"{getattr(fn, '__name__', fn)}: {e.status_code} {e.detail}") from e

    def tryc(self, fn, *a, **kw):
        """Like `call` but a refusal returns None and is counted — for rows that are nice to have, where the module's rule may legitimately refuse (a date on a holiday…)."""
        try:
            return self.call(fn, *a, **kw)
        except Skip as e:
            self.counts["skipped"] = self.counts.get("skipped", 0) + 1
            self.counts.setdefault("skipped_why", []).append(str(e)[:160])
            return None

    def add(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def conn(self):
        """A connection the caller closes (use inside `with ctx.request():` or close it yourself)."""
        from .db import connect
        return connect()


class Skip(Exception):
    """A module refused a seed row for a business reason (reported in the phase counts, never fatal)."""


# ----------------------------------------------------------------------------------------------------------------------- markers & lock
def _marker(c, phase: str):
    r = c.execute("SELECT v FROM settings WHERE k=?", (f"demo_org:{phase}",)).fetchone()
    return r["v"] if r else None


def _set_marker(c, phase: str, counts: dict) -> None:
    import json
    keep = {k: v for k, v in counts.items() if k != "skipped_why"}
    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"demo_org:{phase}", json.dumps({"v": VERSION, "at": dt.datetime.now().isoformat(timespec="seconds"), **keep}, ensure_ascii=False)))
    c.commit()


_FAILS: dict = {}   # (tenant, phase) → failures in this process; a phase that keeps failing is left alone instead of being retried every tick


def _fails(phase: str) -> int:
    from .db import TENANT
    return _FAILS.get((TENANT.get(), phase), 0)


def _fail(phase: str) -> None:
    from .db import TENANT
    _FAILS[(TENANT.get(), phase)] = _FAILS.get((TENANT.get(), phase), 0) + 1


def pending(tenant: str) -> list[str]:
    """Phases of `tenant` without a marker (empty for a tenant that is not a full-demo developer)."""
    if not demo_profile(tenant):
        return []
    from .db import TENANT, connect
    tok = TENANT.set(tenant)
    try:
        c = connect()
        try:
            from .db import init
            init(c)
            return [ph for ph, *_ in PHASES if _marker(c, ph) is None]
        finally:
            c.close()
    finally:
        TENANT.reset(tok)


def ensure_org_demo(tenant: str, phases: tuple | None = None) -> dict:
    """Run the phases a full-demo developer is still missing. Returns `{phase: counts | "skipped" | "failed: …"}`. Never raises."""
    prof = demo_profile(tenant)
    if not prof:
        return {}
    from .db import TENANT, connect
    out: dict = {}
    tok = TENANT.set(tenant)
    lock_conn = None
    try:
        from . import dbx
        if dbx.is_postgres():
            lock_conn = connect()
            if not lock_conn.execute("SELECT pg_try_advisory_lock(%d) ok" % LOCK).fetchone()["ok"]:
                lock_conn.close()
                return {"locked": "another worker is filling this tenant"}
        ctx = Ctx(tenant, dt.date.today(), prof)
        for phase, mod, fn in PHASES:
            if phases and phase not in phases:
                continue
            c = connect()
            try:
                done = _marker(c, phase)
            finally:
                c.close()
            if done:
                out[phase] = "done"
                continue
            if _fails(phase) >= MAX_FAILS:
                out[phase] = "given up after repeated failures (see the log)"
                continue
            try:
                module = importlib.import_module(f"{__package__}.{mod}")
            except ModuleNotFoundError as e:
                if e.name and e.name.endswith(mod):
                    out[phase] = "no module"
                    continue
                out[phase] = f"failed: {e}"
                log.exception("org_demo import", extra={"event": "org_demo_error", "phase": phase})
                continue
            ctx.counts = {}
            try:
                getattr(module, fn)(ctx)
            except Exception as e:  # noqa: BLE001 — one phase failing must not stop the others
                out[phase] = f"failed: {type(e).__name__}: {e}"
                _fail(phase)
                log.exception("org_demo phase", extra={"event": "org_demo_error", "phase": phase, "tenant": tenant})
                continue
            c = connect()
            try:
                _set_marker(c, phase, ctx.counts)
            finally:
                c.close()
            out[phase] = dict(ctx.counts)
            log.info("org_demo phase", extra={"event": "org_demo", "phase": phase, "tenant": tenant})
        if any(isinstance(v, dict) for v in out.values()):
            # the trial logins that are also employees (`emp:<key>` in the profile) can be linked only now that the people file exists
            from .tenant_profiles import ensure_pilot_accounts
            c = connect()
            try:
                ensure_pilot_accounts(c, tenant)
            finally:
                c.close()
    finally:
        if lock_conn is not None:
            with contextlib.suppress(Exception):
                lock_conn.execute("SELECT pg_advisory_unlock(%d)" % LOCK)
                lock_conn.close()
        TENANT.reset(tok)
    return out


def ensure_all() -> dict:
    """`jobs.tick` entry: every full-demo developer, only the phases still missing (cheap when all are marked)."""
    from .db import tenants
    return {t: r for t in tenants() if (r := ensure_org_demo(t))}
