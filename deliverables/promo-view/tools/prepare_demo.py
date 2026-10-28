"""تهيئة مخرجات الحزمة الترويجية لرؤية العقارية على **بياناتها المنشورة** (0.19.0) من منصة تعمل محليًا، وتنزيل ما يصدر منها.

يُشغَّل بعد إقلاع المنصة محليًا (`MABANIQ_TENANTS=view` — الملف الحقيقي يُبذر تلقائيًا):
    MABANIQ_BASE=http://127.0.0.1:8803 MABANIQ_DEMO_PASSWORD=<سر محلي> python deliverables/promo-view/tools/prepare_demo.py
المتغيّر MABANIQ_DEMO_PASSWORD يُقرأ من البيئة ولا يُكتب في أي مخرَج.

قاعدة هذه النسخة: **لا يُضاف إلى بيانات الشركة شيء** — لا عرض سعر ولا عميل ولا حجز ولا حملة ولا تحصيل. ما يُنتج هنا:
  • حقائق للإنفوجرافيك والدليل تُحسب من المنصة (المشاريع، الوحدات، المباع والمتاح، الإنجاز).
  • تقارير جاهزة PDF بترويسة الشركة (المحفظة، المخزون) ومعاينة PNG لصفحتها الأولى.
  • لا مستندات بيع (عرض سعر/عقد) ولا إعلانات: كلاهما يحتاج سعرًا وصورة، والسعر غير منشور.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("MABANIQ_BASE", "http://127.0.0.1:8803")
TENANT = "view"
PW = os.environ.get("MABANIQ_DEMO_PASSWORD") or sys.exit("MABANIQ_DEMO_PASSWORD غير معيَّن")
OUT = Path(__file__).resolve().parents[1]
REPORTS, PREV = OUT / "reports", OUT / "docs" / "preview"


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


def preview(pdf: Path, dest: Path):
    import pymupdf
    pymupdf.open(str(pdf))[0].get_pixmap(dpi=110).save(str(dest))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for d in (REPORTS, PREV.parent):
        shutil.rmtree(d, ignore_errors=True)
    for d in (REPORTS, PREV):
        d.mkdir(parents=True, exist_ok=True)
    admin = Session("admin")
    projects = {p["code"]: p for p in admin.get("/api/projects")}
    for want in ("BRK", "SLH", "KYN", "VHT", "VBZ", "VGD"):
        if want not in projects:
            raise SystemExit(f"المشروع {want} غير موجود — هل بُذر ملف «رؤية» (0.19.0)؟")
    per = {}
    for k, p in projects.items():
        us = admin.get(f"/api/units?project_id={p['id']}")
        types = {}
        for u in us:
            t = types.setdefault(u["type"], {"total": 0, "sold": 0})
            t["total"] += 1
            t["sold"] += u["status"] != "a"
        per[k] = {"name": p["name"], "location": p["location"], "units": len(us), "sold": sum(u["status"] != "a" for u in us), "available": sum(u["status"] == "a" for u in us),
                  "sold_pct": p["sold_pct"], "build_pct": p["build_pct"], "types": types}
    tot_u, tot_s = sum(v["units"] for v in per.values()), sum(v["sold"] for v in per.values())
    state = {"facts": {"projects": len(per), "units": tot_u, "sold": tot_s, "available": tot_u - tot_s, "per_project": per}}
    print("حقائق:", json.dumps(state["facts"], ensure_ascii=False)[:500])
    for key in ("portfolio", "inventory"):
        try:
            with admin._req("/api/reports/export", {"format": "pdf", "kind": "ready", "ref": key, "params": {}}) as r:
                (REPORTS / f"report-{key}.pdf").write_bytes(r.read())
            preview(REPORTS / f"report-{key}.pdf", PREV / f"report-{key}-p1.png")
            print(f"  ↓ report-{key}.pdf")
        except urllib.error.HTTPError as e:
            print("  تقرير", key, e.code, e.read()[:200])
    (OUT / "tools" / "demo-state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("تم. الحالة في tools/demo-state.json")


if __name__ == "__main__":
    main()
