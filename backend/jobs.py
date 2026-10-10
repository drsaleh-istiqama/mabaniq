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
    return out
