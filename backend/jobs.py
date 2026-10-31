"""Mabaniq — background tick (Unit 7). One in-process scheduler loop (started by the lifespan task in `retention.scheduler`)
calls `tick()` every 15 minutes; each job decides for itself whether it is due and must be idempotent (several uvicorn
workers run the same loop). Jobs: retention policy (daily per tenant), scheduled report e-mails, marketing alerts (daily)."""
from __future__ import annotations

from .observability import log


def tick() -> dict:
    out = {}
    from . import retention
    try:
        out["retention"] = len(retention.run_all_due())
    except Exception:  # noqa: BLE001
        log.exception("tick: retention", extra={"event": "job_error"})
    try:
        from . import reports
        out["reports"] = reports.run_due_all()
    except Exception:  # noqa: BLE001
        log.exception("tick: reports", extra={"event": "job_error"})
    try:
        from . import marketing
        out["marketing_alerts"] = marketing.alerts_due_all()
    except Exception:  # noqa: BLE001
        log.exception("tick: marketing", extra={"event": "job_error"})
    try:
        from . import leasing
        out["lease_reminders"] = leasing.reminders_due_all()
    except Exception:  # noqa: BLE001
        log.exception("tick: leasing", extra={"event": "job_error"})
    try:
        from . import hr
        out["hr_alerts"] = hr.alerts_due_all()
    except Exception:  # noqa: BLE001
        log.exception("tick: hr", extra={"event": "job_error"})
    try:
        from . import seed_org
        out["org_demo"] = seed_org.ensure_all()  # 0.29.0: fills the full-demo developers' HR / payroll / books / policies once (phase markers make later ticks free)
    except Exception:  # noqa: BLE001
        log.exception("tick: org demo", extra={"event": "job_error"})
    return out
