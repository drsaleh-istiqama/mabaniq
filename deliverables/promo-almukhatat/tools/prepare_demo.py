"""تهيئة بيانات الدليل الترويجي على بيئة عرض محلية للمطوّر «المخطط العقارية» وتنزيل المستندات الصادرة من المنصة.

يُشغَّل بعد إقلاع المنصة محليًا (`MABANIQ_TENANTS=almukhatat`):
    python deliverables/promo-almukhatat/tools/prepare_demo.py
المتغيّر MABANIQ_DEMO_PASSWORD يُقرأ من البيئة ولا يُكتب في أي مخرَج. كل ما يُنشأ هنا افتراضي (عرض سعر لعميل متخيَّل، حملة، إعلان).
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
TENANT = "almukhatat"
PW = os.environ.get("MABANIQ_DEMO_PASSWORD") or sys.exit("MABANIQ_DEMO_PASSWORD غير معيَّن")
OUT = Path(__file__).resolve().parents[1]
DOCS, ADS, REPORTS = OUT / "docs", OUT / "ads", OUT / "reports"
for d in (DOCS, ADS, REPORTS):
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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    admin, sales = Session("admin"), Session("sales")
    state = {}

    # ١) عرض سعر (افتراضي) لشقة فندقية متاحة في مآب بخطة مرابحة
    quotes = admin.get("/api/quotes")
    q = next((x for x in quotes if x.get("customer_name") == "عبدالله بن سعيد الحارثي"), None)
    if not q:
        units = admin.get("/api/units?project_id=1")
        unit = next(u for u in units if u["status"] == "a" and u["use"] == "hotel") if any(u["status"] == "a" and u["use"] == "hotel" for u in units) \
            else next(u for u in units if u["status"] == "a")
        q = sales.post("/api/quotes", {"unit_code": unit["code"], "customer_name": "عبدالله بن سعيد الحارثي", "phone": "+968 99000000",
                                       "email": "customer@example.com", "plan": "murabaha", "discount_pct": 0.02, "valid_days": 14,
                                       "notes": "عرض افتراضي لأغراض الدليل الترويجي — التمويل بالمرابحة عبر بنك إسلامي، بلا فوائد"})
    state["quote"] = q
    print("عرض السعر:", q.get("number"), q.get("unit_code") or "")

    # ٢) حملة لمشروع مرتيل (ضعيف البيع) بعرض غير ربوي
    camps = admin.get("/api/campaigns")
    camp = next((c for c in camps if c["name"].startswith("مرتيل — ")), None)
    if not camp:
        camp = admin.post("/api/campaigns", {"project_id": 2, "name": "مرتيل — مكاتب ومحلات على شارع نستو", "objective": "slow",
                                             "channels": ["whatsapp", "email", "instagram", "brokers"], "audience": "leads_warm", "budget": 1500,
                                             "offer_text": "تقسيط مباشر من المطوّر حتى التسليم بلا أي زيادة على السعر + خصم 3٪ على الدفعة الأولى لمن يحجز قبل نهاية الشهر",
                                             "message": "مرتيل في المعبيلة الجنوبية على شارع نستو: مكاتب من 50 م² ومحلات على الشارع مباشرة. تقسيط مباشر من المطوّر حتى التسليم بلا زيادة على السعر. احجز معاينتك.",
                                             "notes": "حملة افتراضية للدليل الترويجي"})
    state["campaign"] = camp
    print("الحملة:", camp.get("id"), camp.get("name"))

    # ٣) إعلانان من الاستوديو على تصور مآب الحقيقي (قالب الإطلاق + آخر الوحدات، مقاس مربع)
    plans = admin.get("/api/plans?project_id=1")
    doc_of = {p["filename"]: p["document_id"] for p in plans}
    creatives = admin.get("/api/creatives")
    want = [("launch", "square", "maab-render-02.jpg", "murabaha", "شقق بخمسة نماذج من 62.6 إلى 97.7 م² · شقق فندقية · محلات على شارع الجامعة"),
            ("last_units", "square", "maab-render-03.jpg", None, "الخوض — شارع جامعة السلطان قابوس · تسليم متوقع 2027"),
            ("progress", "wide", "maab-brochure-cover.jpg", None, None)]
    if "--ads" in sys.argv or not creatives:
        for tpl, size, bgf, plan, subline in want:
            cr = admin.post("/api/creatives", {"project_id": 1, "template": tpl, "size": size, "palette": "gold", "bg_document_id": doc_of[bgf],
                                               "plan": plan, "subline": subline, "cta": "احجز معاينتك اليوم"})
            creatives.insert(0, cr)
    seen = set()
    for c in creatives:  # الأحدث لكل (قالب، مقاس)
        key = (c["template"], c["size"])
        if c.get("document_id") and key not in seen:
            seen.add(key)
            admin.download(f"/api/documents/{c['document_id']}", ADS / f"ad-maab-{c['template']}-{c['size']}.png")
    state["creatives"] = [{k: c.get(k) for k in ("id", "template", "size", "headline", "document_id")} for c in creatives]

    # ٤) التنبيهات التسويقية
    try:
        admin.post("/api/marketing/alerts/run", {})
    except SystemExit as e:
        print("  (تنبيهات)", e)

    # ٥) المستندات PDF بترويسة الشركة: عرض السعر، عقد العميل الأول، فاتورة وإيصال
    portal = Session("client1")
    pdocs = portal.get("/api/portal/docs")
    admin.download(f"/api/docs/quote/{q['id']}.pdf", DOCS / f"{q['number']}-quote.pdf")
    con = pdocs["contracts"][0]
    admin.download(f"/api/docs/contract/{con['booking_id']}.pdf", DOCS / f"{con['number']}-contract.pdf")
    inv = pdocs["invoices"][0]
    admin.download(f"/api/docs/invoice/{inv['id']}.pdf", DOCS / f"{inv['number']}-invoice.pdf")
    rec = pdocs["receipts"][0]
    admin.download(f"/api/docs/receipt/{rec['id']}.pdf", DOCS / f"{rec['receipt']}-receipt.pdf")
    state["docs"] = {"quote": q["number"], "contract": con["number"], "invoice": inv["number"], "receipt": rec["receipt"], "customer": portal.get("/api/portal")["customer"]}

    # ٦) تقريران جاهزان بصيغة PDF برسوم
    for key in ("portfolio", "collections", "sales"):
        try:
            with admin._req("/api/reports/export", {"format": "pdf", "kind": "ready", "ref": key, "params": {}}) as r:
                (REPORTS / f"report-{key}.pdf").write_bytes(r.read())
            print(f"  ↓ report-{key}.pdf")
        except urllib.error.HTTPError as e:
            print("  تقرير", key, e.code, e.read()[:200])

    (OUT / "tools" / "demo-state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("تم. الحالة في tools/demo-state.json")


if __name__ == "__main__":
    main()
