"""Landing-page document renders (0.14.0): a quote and an invoice issued by the platform for the GENERIC demo developer `jadwa`,
rendered to JPEG (first page) into web/img/landing/. Demo data only — no client name, no real person.

    MABANIQ_DEMO_PASSWORD=<test value> python tools/landing_assets.py

Runs against a platform started locally (MABANIQ_BASE, default http://127.0.0.1:8800). Creates one quote on the first run (sales
account, an available unit of the first project, murabaha plan — no interest), then downloads the quote PDF and the first invoice
of client1 and rasterises page 1 with PyMuPDF (≤ 200 KB each). The password is read from the environment only.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pymupdf

BASE = os.environ.get("MABANIQ_BASE", "http://127.0.0.1:8800")
TENANT = "jadwa"
PW = os.environ.get("MABANIQ_DEMO_PASSWORD") or sys.exit("MABANIQ_DEMO_PASSWORD غير معيَّن")
OUT = Path(__file__).resolve().parents[1] / "web" / "img" / "landing"
OUT.mkdir(parents=True, exist_ok=True)
MAX_KB = 200


class Session:
    def __init__(self, user: str):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        body = json.dumps({"username": user, "password": PW, "tenant": TENANT}).encode()
        self.op.open(urllib.request.Request(BASE + "/api/auth/login", body, {"Content-Type": "application/json"}))
        self.csrf = next((c.value for c in self.cj if c.name == "mbq_csrf"), "")

    def _req(self, path, data=None):
        h = {"X-CSRF-Token": self.csrf}
        if data is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(data).encode()
        return self.op.open(urllib.request.Request(BASE + path, data, h))

    def get(self, path):
        with self._req(path) as r:
            return json.loads(r.read())

    def post(self, path, obj):
        try:
            with self._req(path, obj) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise SystemExit(f"POST {path} → {e.code}: {e.read()[:300].decode('utf-8', 'replace')}")

    def pdf(self, path) -> bytes:
        with self._req(path) as r:
            return r.read()


def render(pdf: bytes, dest: Path, width: int = 1000) -> None:
    """Page 1 without the footer strip (it carries the verification URL of the local instance, not a public one)."""
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    page = doc[0]
    zoom = width / page.rect.width
    clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.9)
    for q in (85, 75, 65, 55):
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, clip=clip)
        dest.write_bytes(pix.tobytes("jpeg", jpg_quality=q))
        if dest.stat().st_size / 1024 <= MAX_KB:
            break
    print(f"  ↓ {dest.name} ({dest.stat().st_size // 1024} KB, {pix.width}×{pix.height})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    admin, sales = Session("admin"), Session("sales")
    # letterhead of the generic demo developer (demo data, no real company): shown on the rendered documents
    admin.post("/api/admin/brand", {"name": "جدوى للتطوير — بيانات تجريبية", "address": "مسقط، سلطنة عُمان", "phone": "+968 2400 0000",
                              "email": "demo@example.com", "signatory": "مدير المبيعات", "signatory_title": "المفوَّض بالتوقيع"})
    quotes = admin.get("/api/quotes")
    q = next((x for x in quotes if x.get("customer_name") == "عميل تجريبي"), None)
    if not q:
        projects = admin.get("/api/projects")
        units = admin.get(f"/api/units?project_id={projects[0]['id']}")
        unit = next(u for u in units if u["status"] == "a")
        q = sales.post("/api/quotes", {"unit_code": unit["code"], "customer_name": "عميل تجريبي", "phone": "+968 90000000",
                                       "email": "demo@example.com", "plan": "murabaha", "discount_pct": 0.0, "valid_days": 14,
                                       "notes": "عرض تجريبي لصفحة الهبوط — بيانات افتراضية"})
    print("عرض السعر:", q.get("number"))
    render(admin.pdf(f"/api/docs/quote/{q['id']}.pdf"), OUT / "doc-quote.jpg")
    portal = Session("client1")
    pdocs = portal.get("/api/portal/docs")
    inv = pdocs["invoices"][0]
    render(admin.pdf(f"/api/docs/invoice/{inv['id']}.pdf"), OUT / "doc-invoice.jpg")
    print("تم.")


if __name__ == "__main__":
    main()
