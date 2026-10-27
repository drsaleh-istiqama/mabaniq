"""تهيئة بيانات الدليل الترويجي على بيئة عرض محلية للمطوّر «المقصورة العقارية» وتنزيل المستندات الصادرة من المنصة.

يُشغَّل بعد إقلاع المنصة محليًا (`MABANIQ_TENANTS` يضم `almaqsura`):
    python deliverables/promo-almaqsura/tools/prepare_demo.py --ads
المتغيّر MABANIQ_DEMO_PASSWORD يُقرأ من البيئة ولا يُكتب في أي مخرَج. كل ما يُنشأ هنا افتراضي (عرض سعر لعميل متخيَّل، حملة، إعلان).
المعرّفات تُستخرج برموز المشاريع (MSK/ALA/…) لا بأرقام ثابتة.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("MABANIQ_BASE", "http://127.0.0.1:8800")
TENANT = "almaqsura"
PW = os.environ.get("MABANIQ_DEMO_PASSWORD") or sys.exit("MABANIQ_DEMO_PASSWORD غير معيَّن")
OUT = Path(__file__).resolve().parents[1]
DOCS, ADS, REPORTS, PREV = OUT / "docs", OUT / "ads", OUT / "reports", OUT / "docs" / "preview"
for d in (DOCS, ADS, REPORTS, PREV):
    d.mkdir(parents=True, exist_ok=True)


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
    admin, sales = Session("admin"), Session("sales")
    state = {}
    projects = {p["code"]: p for p in admin.get("/api/projects")}
    msk, ala = projects["MQC"], projects["RWQ"]
    state["projects"] = {k: {"id": v["id"], "name": v["name"]} for k, v in projects.items()}

    # ١) عرض سعر (افتراضي) لمكتب متاح في مجمع المقصورة بخطة مرابحة
    quotes = admin.get("/api/quotes")
    q = next((x for x in quotes if x.get("customer_name") == "شركة الواحة للاستشارات الإدارية"), None)
    if not q:
        units = admin.get(f"/api/units?project_id={msk['id']}")
        free = [u for u in units if u["status"] == "a" and not u.get("retained")]
        unit = next((u for u in free if "مكتب" in u["type"]), free[0])
        q = sales.post("/api/quotes", {"unit_code": unit["code"], "customer_name": "شركة الواحة للاستشارات الإدارية", "phone": "+968 99000000",
                                       "email": "customer@example.com", "plan": "murabaha", "discount_pct": 0.02, "valid_days": 14,
                                       "notes": "عرض افتراضي لأغراض الدليل الترويجي — التمويل بالمرابحة عبر بنك إسلامي، بلا فوائد"})
    state["quote"] = q
    print("عرض السعر:", q.get("number"), q.get("unit_code") or "")

    # ٢) حملة لأروقة الموالح (بطيء البيع) بعرض غير ربوي
    camps = admin.get("/api/campaigns")
    camp = next((c for c in camps if c["name"].startswith("أروقة الموالح — ")), None)
    if not camp:
        camp = admin.post("/api/campaigns", {"project_id": ala["id"], "name": "أروقة الموالح — شقق ومحلات على الرواق في الموالح الجنوبية", "objective": "slow",
                                             "channels": ["whatsapp", "email", "instagram", "brokers"], "audience": "leads_warm", "budget": 1800,
                                             "offer_text": "تقسيط مباشر من المطوّر حتى التسليم بلا أي زيادة على السعر + سنة إعفاء من رسوم الخدمات لمن يحجز قبل نهاية الشهر",
                                             "message": "أروقة الموالح في الموالح الجنوبية: شقق من غرفة إلى ثلاث غرف ومحلات على الرواق، بأقساط مباشرة من المطوّر بلا زيادة وخصم على الدفعة الأولى",
                                             "notes": "حملة افتراضية للدليل الترويجي"})
    state["campaign"] = camp
    print("الحملة:", camp.get("id"), camp.get("name"))

    # ٣) إعلانان من الاستوديو على تصور مجمع المقصورة التجاري الحقيقي (قالب الإطلاق + آخر الوحدات، مقاس مربع)
    plans = admin.get(f"/api/plans?project_id={msk['id']}")
    doc_of = {p["filename"]: p["document_id"] for p in plans}
    creatives = admin.get("/api/creatives")
    want = [("launch", "square", "mqc-render-courtyard-day.jpg", "murabaha", "16 محلًا حول فناء داخلي · 24 مكتبًا · 12 شقة · الخوض السابعة"),
            ("last_units", "square", "mqc-render-courtyard-02.jpg", None, "الخوض السابعة · محلات ومكاتب للبيع أو الإيجار")]
    if "--ads" in sys.argv or not creatives:
        for tpl, size, bgf, plan, subline in want:
            cr = admin.post("/api/creatives", {"project_id": msk["id"], "template": tpl, "size": size, "palette": "green", "bg_document_id": doc_of[bgf],
                                               "plan": plan, "subline": subline, "cta": "احجز معاينتك اليوم"})
            creatives.insert(0, cr)
    seen = set()
    for c in creatives:  # الأحدث لكل (قالب، مقاس)
        key = (c["template"], c["size"])
        if c.get("document_id") and key not in seen:
            seen.add(key)
            admin.download(f"/api/documents/{c['document_id']}", ADS / f"ad-mqc-{c['template']}-{c['size']}.png")
    state["creatives"] = [{k: c.get(k) for k in ("id", "template", "size", "headline", "document_id")} for c in creatives]

    # ٤) التنبيهات التسويقية
    try:
        admin.post("/api/marketing/alerts/run", {})
    except SystemExit as e:
        print("  (تنبيهات)", e)

    # ٥) المستندات PDF بترويسة الشركة: عرض السعر، عقد العميل الأول، فاتورة وإيصال — ومعاينة PNG للصفحة الأولى
    portal = Session("client1")
    pdocs = portal.get("/api/portal/docs")
    files = {}
    files["quote"] = (q["number"], DOCS / f"{q['number']}-quote.pdf", f"/api/docs/quote/{q['id']}.pdf")
    con = pdocs["contracts"][0]
    files["contract"] = (con["number"], DOCS / f"{con['number']}-contract.pdf", f"/api/docs/contract/{con['booking_id']}.pdf")
    # العميل الأول قد لا يحمل فاتورة أو إيصالًا بعد (بحسب جدول أقساطه)؛ عندها تؤخذ آخر فاتورة/إيصال من المطوّر نفسه
    inv = (pdocs["invoices"] or admin.get("/api/invoices")["invoices"][:1] or [None])[0]
    if not inv:
        raise SystemExit("لا فواتير لدى المطوّر")
    files["invoice"] = (inv["number"], DOCS / f"{inv['number']}-invoice.pdf", f"/api/docs/invoice/{inv['id']}.pdf")
    rec = pdocs["receipts"][0] if pdocs["receipts"] else None
    if not rec:  # إيصال من أول دفعة مسجَّلة لدى أي عميل آخر عبر بوابته
        for un in ("client2", "client3"):
            try:
                rr = Session(un).get("/api/portal/docs")["receipts"]
            except Exception:  # noqa: BLE001
                rr = []
            if rr:
                rec = rr[0]
                break
    if not rec:
        raise SystemExit("لا إيصالات في بوابات العملاء التجريبيين")
    files["receipt"] = (rec["receipt"], DOCS / f"{rec['receipt']}-receipt.pdf", f"/api/docs/receipt/{rec['id']}.pdf")
    for kind, (num, dest, path) in files.items():
        admin.download(path, dest)
        preview(dest, PREV / f"{num}-{kind}-p1.png")
    state["docs"] = {k: v[0] for k, v in files.items()} | {"customer": portal.get("/api/portal")["customer"]}
    state["quote"] = admin.get(f"/api/quotes/{q['id']}")  # بعد الإصدار: التفاصيل تحمل رمز التحقق

    # ٦) تقارير جاهزة بصيغة PDF برسوم
    for key in ("portfolio", "collections", "sales"):
        try:
            with admin._req("/api/reports/export", {"format": "pdf", "kind": "ready", "ref": key, "params": {}}) as r:
                (REPORTS / f"report-{key}.pdf").write_bytes(r.read())
            preview(REPORTS / f"report-{key}.pdf", PREV / f"report-{key}-p1.png")
            print(f"  ↓ report-{key}.pdf")
        except urllib.error.HTTPError as e:
            print("  تقرير", key, e.code, e.read()[:200])

    # ٧) حقائق للإنفوجرافيك (تُحسب من المنصة لا تُكتب يدويًا)
    n_units = sum(len(admin.get(f"/api/units?project_id={p['id']}")) for p in projects.values())
    n_plans = sum(len(admin.get(f"/api/plans?project_id={p['id']}")) for p in projects.values())
    L = admin.get("/api/leasing")
    state["facts"] = {"projects": len(projects), "units": n_units, "plans": n_plans, "leases": len(L["leases"]), "retained": len(L["units"]),
                      "occupancy": L["occupancy"], "annual_rent": L["annual_rent"], "arrears": L["arrears"]}
    print("حقائق:", state["facts"])

    (OUT / "tools" / "demo-state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("تم. الحالة في tools/demo-state.json")


if __name__ == "__main__":
    main()
