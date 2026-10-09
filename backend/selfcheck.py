"""`python -m backend.selfcheck` — pre-flight before a deployment or a demo (Unit 0).

Exit code 0 = everything green. Each line is one check so CI and humans read the same output.
"""
from __future__ import annotations

import os
import re
import sys

os.environ.setdefault("MABANIQ_LOG_JSON", "0")

from fastapi.testclient import TestClient  # noqa: E402

from .config import settings  # noqa: E402


def main() -> int:
    results: list[tuple[bool, str]] = []
    errs = settings.validate()
    results.append((not errs, "config: " + ("valid for %s" % settings.env if not errs else "; ".join(errs))))

    from .app import app  # imported late so config errors print first
    with TestClient(app, base_url="https://selfcheck.local") as c:
        h = c.get("/health").json()
        results.append((h.get("status") == "ok", f"health: {h}"))
        r = c.get("/ready")
        results.append((r.status_code == 200, f"ready: {r.status_code} {r.json()}"))
        v = c.get("/version").json()
        results.append((v.get("version") == settings.version, f"version: {v.get('version')} ({v.get('database')})"))
        page = c.get("/login")
        csp = page.headers.get("content-security-policy", "")
        results.append(("script-src 'self';" in csp and "unsafe-inline" not in csp.split("style-src")[0], "csp: script-src strict"))
        for hdr in ("strict-transport-security", "x-frame-options", "x-content-type-options", "referrer-policy", "permissions-policy",
                    "cross-origin-opener-policy", "cross-origin-resource-policy"):
            results.append((hdr in page.headers, f"header: {hdr}"))
        results.append((not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", page.text), "html: no inline scripts on /login"))
        results.append(("x-request-id" in page.headers, "observability: X-Request-ID on responses"))
        anon = c.post("/api/notifications/run")
        results.append((anon.status_code == 401, f"authz: anonymous write → {anon.status_code}"))

    ok = all(r[0] for r in results)
    for good, line in results:
        print(("✅ " if good else "❌ ") + line)
    print("selfcheck:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
