"""Mabaniq — data retention (Unit 4, PDPL data minimisation).

One documented policy, applied the same way by the scheduler (lifespan task, once per `MABANIQ_RETENTION_HOURS`), by
`POST /api/admin/retention/run` and by tests. Every run writes one audit line with the counts. What it never touches:
`audit` (append-only by trigger), financial ledgers (payments, installments, invoices, charity_dues …), contracts,
customers' identity data (erasure goes through `privacy_requests`, which has legal-hold blockers).

Rule set (days are settings, see `.env.example`):
  login_attempts / auth_failures   older than RETENTION_LOGIN_DAYS        → deleted   (security telemetry only)
  sessions expired, reset_tokens   expired/used more than SESSIONS_DAYS ago → deleted   (nothing to recover from them)
  notifications                    older than NOTIFICATIONS_DAYS           → deleted   (reminders already delivered)
  pay_intents still 'pending'      older than PAY_INTENT_DAYS              → status 'expired' (kept — financial trail)
  wa_messages                      older than MESSAGES_DAYS                → phone masked to the last 4 digits (content kept for audit)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time

from .config import settings
from .db import TENANT, audit_insert, connect, tenants
from .observability import log

LAST_RUN_KEY = "retention:last_run"


def policy() -> dict:
    r = settings.retention
    return {"enabled": settings.retention_enabled, "every_hours": settings.retention_hours,
            "login_telemetry_days": r["login"], "expired_sessions_days": r["sessions"], "notifications_days": r["notifications"],
            "pending_pay_intents_days": r["pay_intents"], "messages_phone_mask_days": r["messages"],
            "never": ["audit", "payments", "installments", "invoices", "refunds", "charity_dues", "sale_contracts", "customers (via privacy_requests only)"]}


def _mask_phone(p: str | None) -> str:
    p = p or ""
    return ("•" * max(0, len(p) - 4)) + p[-4:] if len(p) > 4 else "••••"


def run(c, now: float | None = None, actor: str = "النظام") -> dict:
    """Apply the policy on the connection's tenant. Returns the counts; commits once."""
    r = settings.retention
    now = now or time.time()
    today = dt.datetime.fromtimestamp(now)
    day = 86400.0
    iso = lambda days: (today - dt.timedelta(days=days)).isoformat(timespec="seconds")  # noqa: E731
    counts: dict[str, int] = {}

    counts["login_attempts"] = c.execute("DELETE FROM login_attempts WHERE at < ?", (now - r["login"] * day,)).rowcount
    counts["auth_failures"] = c.execute("DELETE FROM auth_failures WHERE at < ?", (now - r["login"] * day,)).rowcount
    counts["sessions"] = c.execute("DELETE FROM sessions WHERE expires < ?", (now - r["sessions"] * day,)).rowcount
    counts["reset_tokens"] = c.execute("DELETE FROM reset_tokens WHERE expires < ? OR used=1", (now - r["sessions"] * day,)).rowcount
    counts["notifications"] = c.execute("DELETE FROM notifications WHERE created < ?", (iso(r["notifications"]),)).rowcount
    counts["pay_intents_expired"] = c.execute("UPDATE pay_intents SET status='expired' WHERE status='pending' AND created < ?",
                                              (iso(r["pay_intents"]),)).rowcount
    old_msgs = c.execute("SELECT id, phone FROM wa_messages WHERE at < ? AND phone NOT LIKE '•%'", (iso(r["messages"]),)).fetchall()
    for m in old_msgs:
        c.execute("UPDATE wa_messages SET phone=? WHERE id=?", (_mask_phone(m["phone"]), m["id"]))
    counts["wa_messages_masked"] = len(old_msgs)

    total = sum(counts.values())
    summary = " · ".join(f"{k}={v}" for k, v in counts.items())
    audit_insert(c, actor, "تطبيق سياسة الاحتفاظ", summary)
    c.execute("INSERT OR REPLACE INTO settings VALUES(?, ?)", (LAST_RUN_KEY, today.isoformat(timespec="seconds")))
    c.commit()
    log.info("retention", extra={"event": "retention", "user": actor, "path": TENANT.get(), "status": total})
    return {"tenant": TENANT.get(), "at": today.isoformat(timespec="seconds"), "counts": counts, "total": total}


def last_run(c) -> str | None:
    row = c.execute("SELECT v FROM settings WHERE k=?", (LAST_RUN_KEY,)).fetchone()
    return row["v"] if row else None


def due(c, now: float | None = None) -> bool:
    lr = last_run(c)
    if not lr:
        return True
    return (dt.datetime.fromtimestamp(now or time.time()) - dt.datetime.fromisoformat(lr)) >= dt.timedelta(hours=settings.retention_hours)


def run_all_due() -> list[dict]:
    """Every tenant whose last run is older than the interval. Used by the scheduler."""
    out = []
    for t in tenants():
        tok = TENANT.set(t)
        try:
            c = connect()
            try:
                if due(c):
                    out.append(run(c))
            finally:
                c.close()
        except Exception:  # noqa: BLE001 — a failing tenant must not stop the others; the error goes to the log with the tenant
            log.exception("retention failed", extra={"event": "retention_error", "path": t})
        finally:
            TENANT.reset(tok)
    return out


async def scheduler(stop: asyncio.Event) -> None:
    """Lifespan task: first pass shortly after start-up, then every 15 minutes checks whether a tenant is due."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=30)
        return
    except TimeoutError:
        pass
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_all_due)
        except Exception:  # noqa: BLE001
            log.exception("retention scheduler", extra={"event": "retention_error"})
        try:
            await asyncio.wait_for(stop.wait(), timeout=15 * 60)
        except TimeoutError:
            continue
