"""تهيئة مخرجات الحزمة الترويجية للمقصورة العقارية على **بياناتها الحقيقية** (0.18.1) من منصة تعمل محليًا، وتنزيل ما يصدر منها.

يُشغَّل بعد إقلاع المنصة محليًا (`MABANIQ_TENANTS` يضم `almaqsura` — الملف الحقيقي يُبذر تلقائيًا):
    MABANIQ_BASE=http://127.0.0.1:8802 MABANIQ_DEMO_PASSWORD=<سر محلي> python deliverables/promo-almaqsura/tools/prepare_demo.py
المتغيّر MABANIQ_DEMO_PASSWORD يُقرأ من البيئة ولا يُكتب في أي مخرَج.

قاعدة هذه النسخة: **لا يُضاف إلى بيانات الشركة شيء** — لا عرض سعر ولا عميل ولا حملة ولا تحصيل وهمي. ما يُنتج هنا:
  • حقائق للإنفوجرافيك والدليل تُحسب من المنصة (المشاريع، الوحدات، العقود، الإشغال، الإيجار السنوي، المتأخرات وأعلى المتأخرين).
  • تقارير جاهزة PDF بترويسة الشركة (المحفظة، المخزون والتسعير) ومعاينة PNG لصفحتها الأولى.
  • لا إعلانات: قوالب الاستوديو تحتاج صورة للعقار ونصوصها (إطلاق/آخر الوحدات/قريبًا) لا تصدق على أرض معروضة بلا سعر — تُنتج حين تصل صورة الأرض وسعرها.
المعرّفات تُستخرج برموز المشاريع (IST/MQT/SAD/AZB) لا بأرقام ثابتة.
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

BASE = os.environ.get("MABANIQ_BASE", "http://127.0.0.1:8802")
TENANT = "almaqsura"
PW = os.environ.get("MABANIQ_DEMO_PASSWORD") or sys.exit("MABANIQ_DEMO_PASSWORD غير معيَّن")
OUT = Path(__file__).resolve().parents[1]
DOCS, ADS, REPORTS, PREV = OUT / "docs", OUT / "ads", OUT / "reports", OUT / "docs" / "preview"


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

    def download(self, path, dest: Path):
        with self._req(path) as r:
            dest.write_bytes(r.read())
        print(f"  ↓ {dest.name} ({dest.stat().st_size // 1024} KB)")


def preview(pdf: Path, dest: Path):
    """الصفحة الأولى من PDF صورةً PNG (للدليل والنسخة HTML)."""
    import pymupdf
    pix = pymupdf.open(str(pdf))[0].get_pixmap(dpi=110)
    pix.save(str(dest))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    # مخرجات النسخة التوضيحية السابقة (عرض سعر/عقد/فاتورة/إيصال وإعلانات على تصورات) لم تعد صادقة — تُمحى وتُعاد من الصفر
    for d in (DOCS, ADS, REPORTS):
        shutil.rmtree(d, ignore_errors=True)
    for d in (DOCS, ADS, REPORTS, PREV):
        d.mkdir(parents=True, exist_ok=True)

    admin = Session("admin")
    state = {}
    projects = {p["code"]: p for p in admin.get("/api/projects")}
    state["projects"] = {k: {"id": v["id"], "name": v["name"], "kind": v["kind"], "total_units": v.get("total_units")} for k, v in projects.items()}
    for want in ("IST", "MQT", "SAD", "AZB"):
        if want not in projects:
            raise SystemExit(f"المشروع {want} غير موجود — هل بُذر الملف الحقيقي (0.18.1)؟")

    # ١) حقائق تُحسب من المنصة
    units_by = {k: admin.get(f"/api/units?project_id={p['id']}") for k, p in projects.items()}
    L = admin.get("/api/leasing")
    active = [l for l in L["leases"] if l["status"] == "active"]
    leased_codes = {l["unit"] for l in active}
    per_project = {}
    for k, us in units_by.items():
        retained = [u for u in us if u.get("retained")]
        per_project[k] = {"units": len(us), "retained": len(retained), "leased": sum(1 for u in retained if u["code"] in leased_codes),
                          "use": sorted({u.get("use") or "" for u in us})}
    arrears_top = sorted(((l["unit"], l["tenant"], l["arrears"]) for l in L["leases"] if l["arrears"]), key=lambda x: -x[2])
    state["facts"] = {"projects": len(projects), "units": sum(len(u) for u in units_by.values()), "leases": len(L["leases"]), "active_leases": len(active),
                      "retained": len(L["units"]), "occupancy": L["occupancy"], "annual_rent": L["annual_rent"], "arrears": L["arrears"],
                      "renewals_90d": sum(1 for l in L["leases"] if l.get("renewal_alert")), "per_project": per_project, "arrears_top": arrears_top[:8]}
    # وحدة الدليل: محل W (الخوير، 400 ر.ع) وعقد أعلى المتأخرات (مكتب 5) ووحدة البرجين المؤجرة الأكبر
    state["focus"] = {"shop": "IST-A-SW", "arrears_lease": arrears_top[0][0] if arrears_top else None,
                      "tower_unit": max((u for u in units_by["MQT"] if u["code"] in leased_codes), key=lambda u: u.get("area") or 0)["code"]}
    print("حقائق:", json.dumps(state["facts"], ensure_ascii=False)[:400])

    # ٢) تقارير جاهزة بصيغة PDF برسوم وترويسة الشركة (ما له معنى على محفظة تأجير: المحفظة والمخزون)
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
