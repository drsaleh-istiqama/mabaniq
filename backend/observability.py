"""Mabaniq — observability and abuse controls (Unit 0).

- JSON structured logging with a per-request id (`X-Request-ID`, propagated when the proxy sends one).
- One access-log line per request: method, path, status, duration, client ip, user (when known).
- Unhandled exceptions become a JSON 500 that carries only the request id; the stack goes to the log.
- Token-bucket rate limiting per client ip for the login endpoint, the payment webhook and all of /api/*.
  State is in-process (one bucket set per worker); Unit 1 moves it to the database so several instances share it.
"""
from __future__ import annotations

import contextvars
import json
import logging
import secrets
import sys
import threading
import time
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
log = logging.getLogger("mabaniq")


# ---------------------------------------------------------------- logging
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z", "level": record.levelname,
             "logger": record.name, "msg": record.getMessage(), "request_id": REQUEST_ID.get()}
        for k in ("method", "path", "status", "ms", "ip", "user", "event"):
            if hasattr(record, k):
                d[k] = getattr(record, k)
        if record.exc_info:
            d["exc"] = "".join(traceback.format_exception(*record.exc_info))[-4000:]
        return json.dumps(d, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{time.strftime('%H:%M:%S')} {record.levelname:5s} [{REQUEST_ID.get()}] {record.getMessage()}"
        if hasattr(record, "status"):
            base += f" → {record.status} {getattr(record, 'ms', '')}ms"
        if record.exc_info:
            base += "\n" + "".join(traceback.format_exception(*record.exc_info))
        return base


def setup_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_mabaniq_configured", False):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter() if settings.log_json else PlainFormatter())
    root.handlers[:] = [h]
    root.setLevel(settings.log_level)
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).disabled = True  # our access log replaces it
    root._mabaniq_configured = True  # type: ignore[attr-defined]


# ---------------------------------------------------------------- rate limiting
class RateLimiter:
    """Token bucket per (bucket, key). Thread-safe; memory bounded by periodic sweep."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[tuple[str, str], tuple[float, float]] = {}  # (tokens, last_ts)
        self._last_sweep = time.monotonic()

    def reset(self) -> None:
        with self._lock:
            self._state.clear()

    def allow(self, bucket: str, key: str, limit: int, per_seconds: int) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        rate = limit / per_seconds
        with self._lock:
            if now - self._last_sweep > 300:
                self._state = {k: v for k, v in self._state.items() if now - v[1] < 2 * per_seconds}
                self._last_sweep = now
            tokens, last = self._state.get((bucket, key), (float(limit), now))
            tokens = min(float(limit), tokens + (now - last) * rate)
            if tokens >= 1:
                self._state[(bucket, key)] = (tokens - 1, now)
                return True, 0
            self._state[(bucket, key)] = (tokens, now)
            return False, max(1, int((1 - tokens) / rate) + 1)


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "?"
    if settings.trust_proxy and peer in ("127.0.0.1", "::1"):
        return request.headers.get("cf-connecting-ip") or (request.headers.get("x-forwarded-for") or peer).split(",")[0].strip()
    return peer


def rate_limit(request: Request):
    """Returns a 429 response when the client exceeded its budget, else None."""
    p = request.url.path
    if not p.startswith("/api/"):
        return None
    ip = client_ip(request)
    checks = [("api", ip, *settings.rate_api)]
    if p == "/api/auth/login" and request.method == "POST":
        checks.append(("login", ip, *settings.rate_login))
    if p == "/api/pay/webhook":
        checks.append(("webhook", ip, *settings.rate_webhook))
    for bucket, key, limit, per in checks:
        ok, retry = limiter.allow(bucket, key, limit, per)
        if not ok:
            log.warning("rate limited", extra={"event": "rate_limit", "path": p, "ip": ip})
            return JSONResponse({"detail": "طلبات كثيرة — حاول لاحقًا", "request_id": REQUEST_ID.get()}, status_code=429,
                                headers={"Retry-After": str(retry), "X-RateLimit-Bucket": bucket})
    return None


# ---------------------------------------------------------------- middleware
class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        if not rid or len(rid) > 64 or not rid.replace("-", "").replace("_", "").isalnum():
            rid = secrets.token_hex(8)
        token = REQUEST_ID.set(rid)
        t0 = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:  # noqa: BLE001 — logged with the request id, never shown to the client
                log.exception("unhandled error", extra={"method": request.method, "path": request.url.path, "ip": client_ip(request)})
                response = JSONResponse({"detail": "خطأ داخلي — أبلغ الدعم برقم الطلب", "request_id": rid}, status_code=500)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            response.headers["X-Request-ID"] = rid
            user = getattr(request.state, "user", None)
            log.info("access", extra={"method": request.method, "path": request.url.path, "status": response.status_code, "ms": ms,
                                      "ip": client_ip(request), "user": user["username"] if user else None})
            return response
        finally:
            REQUEST_ID.reset(token)
