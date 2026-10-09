"""Mabaniq — short-lived per-tenant cache for the heavy dashboard computations (Unit 4, acceptance 15).

`/api/decisions` and `/api/cash` recompute the whole portfolio (every project, installment and payment) on every call —
about 130–200 ms of CPU each. Three hundred staff refreshing dashboards is the same answer computed three hundred times.
The cache keeps one result per (tenant, key) for `TTL` seconds; **any mutating request of the tenant bumps the
generation**, so a decision taken, a payment posted or a reseed is visible on the next read. Authorisation runs before
the lookup (the dependency is still evaluated by FastAPI), so the cache never widens what a role can see.

Single flight: when an entry expires under load, exactly one thread recomputes it; the others get the previous value
(stale by at most one TTL) instead of all recomputing at once — the measured "thundering herd" was the whole tail
latency at 300 users. A write (generation bump) drops the entry, so stale-while-revalidate never serves a value from
before the tenant's last write. Per process (uvicorn workers do not share it); correctness never depends on sharing.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

TTL = 10.0
_lock = threading.Lock()
_gen: dict[str, int] = {}
_store: dict[tuple, tuple[float, int, object]] = {}
_inflight: dict[tuple, threading.Lock] = {}
hits = misses = stale_served = 0


def generation(tenant: str) -> int:
    return _gen.get(tenant, 0)


def bump(tenant: str) -> None:
    """Called after every mutating request (POST/PUT/PATCH/DELETE on /api/*) of the tenant."""
    with _lock:
        _gen[tenant] = _gen.get(tenant, 0) + 1
        for k in [k for k in _store if k[0] == tenant]:
            del _store[k]


def get(tenant: str, key: str, compute: Callable[[], object], ttl: float = TTL):
    global hits, misses, stale_served
    if ttl <= 0:
        return compute()
    k = (tenant, key)
    now = time.monotonic()
    g = generation(tenant)
    with _lock:
        hit = _store.get(k)
        if hit and hit[1] == g and now - hit[0] < ttl:
            hits += 1
            return hit[2]
        flight = _inflight.setdefault(k, threading.Lock())
    if not flight.acquire(blocking=False):
        # someone else is recomputing this key
        if hit and hit[1] == g:
            with _lock:
                stale_served += 1
            return hit[2]  # at most one TTL old, and from after the tenant's last write
        with flight:  # nothing to serve yet: wait for the first computation
            pass
        with _lock:
            fresh = _store.get(k)
            if fresh and fresh[1] == generation(tenant):
                hits += 1
                return fresh[2]
        return compute()
    try:
        value = compute()
        with _lock:
            misses += 1
            _store[k] = (time.monotonic(), g, value)
        return value
    finally:
        flight.release()


def clear() -> None:
    with _lock:
        _store.clear()
        _gen.clear()
        _inflight.clear()


def stats() -> dict:
    return {"entries": len(_store), "hits": hits, "misses": misses, "stale_served": stale_served}
