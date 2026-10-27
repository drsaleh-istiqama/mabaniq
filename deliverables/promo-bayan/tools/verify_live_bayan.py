"""تحقق حي من مطوّر بيان على https://mabaneek.com — يقرأ كلمة المرور من MABANIQ_LIVE_PW ولا يطبعها ولا يكتبها.
يستعمل حساب admin (كلمة العرض). لا يكتب شيئًا في المنصة: قراءة فقط."""
import http.cookiejar, json, os, sys, urllib.request, urllib.error

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("MABANIQ_LIVE_BASE", "https://mabaneek.com")
PW = os.environ.get("MABANIQ_LIVE_PW") or sys.exit("MABANIQ_LIVE_PW غير معيَّن في هذه الطرفية")
USER = os.environ.get("MABANIQ_LIVE_USER", "admin")

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def req(path, data=None):
    csrf = next((c.value for c in cj if c.name == "mbq_csrf"), "")
    h = {"X-CSRF-Token": csrf}
    if data is not None:
        h["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    return op.open(urllib.request.Request(BASE + path, data, h), timeout=30)


def get(path):
    with req(path) as r:
        return json.loads(r.read())


try:
    with req("/api/auth/login", {"username": USER, "password": PW, "tenant": "bayan"}) as r:
        me = json.loads(r.read())
except urllib.error.HTTPError as e:
    print(f"فشل الدخول إلى بيان بحساب {USER}: HTTP {e.code}")
    import time
    time.sleep(2)
    for t in ("almukhatat", "jadwa"):  # تشخيص: هل الكلمة صحيحة على مطوّر آخر؟ (لا تُطبع الكلمة)
        for u in (USER,):
            try:
                with req("/api/auth/login", {"username": u, "password": PW, "tenant": t}) as r2:
                    r2.read()
                print(f"  نفس الكلمة مقبولة على {t}/{u} ⟵ الكلمة صحيحة؛ حساب {USER} في بيان غير مقبول (لم يُبذر بعد أو كلمته مختلفة)")
                sys.exit(1)
            except urllib.error.HTTPError as e2:
                print(f"  {t}/{u}: HTTP {e2.code}")
    sys.exit("  الكلمة مرفوضة على كل المطوّرين ⟵ غالبًا ليست قيمة MABANIQ_DEMO_PASSWORD الحالية على خدمة mabaniq-api")
print(f"دخول {USER} إلى بيان: نجح — الدور {me.get('role_label')}؛ must_change={me.get('must_change')}")

try:
    ps = get("/api/projects")
except urllib.error.HTTPError as e:
    sys.exit(f"المشاريع: HTTP {e.code} {e.read()[:120]!r}")
codes = {p["code"]: p for p in ps}
print("المشاريع:", ", ".join(f"{c}={p['name']}" for c, p in codes.items()))
expect = {"MSK", "ALA", "MQR", "SHB", "AMR", "QRM"}
print("  الرموز المتوقعة كلها موجودة:", expect <= set(codes), "| تسرّب RAY/SEB/KHD/MAB:", bool({"RAY", "SEB", "KHD", "MAB"} & set(codes)))

units = {c: get(f"/api/units?project_id={p['id']}") for c, p in codes.items() if c in expect}
print("الوحدات:", {c: len(u) for c, u in units.items()})
print("  مساحات: محلات", sum("محل" in u["type"] for u in units["MSK"]), "مكاتب", sum("مكتب" in u["type"] for u in units["MSK"]),
      "| use=commercial لكل وحدات مساحات:", all(u["use"] == "commercial" for u in units["MSK"]))

for c in ("MSK", "ALA", "SHB", "QRM", "AMR"):
    plans = get(f"/api/plans?project_id={codes[c]['id']}")
    kinds = sorted({p["kind"] for p in plans})
    print(f"المخططات {c}: {len(plans)} {kinds}")
    if c == "MSK":
        gf = next((p for p in plans if p["kind"] == "floor" and p.get("floor") == 0), None)
        marks = len(gf["markers"]) if gf else 0
        print("  علامات مخطط الطابق الأرضي:", marks)
        if gf:
            with req(f"/api/documents/{gf['document_id']}") as r:
                body = r.read()
                print(f"  تنزيل مخطط الطابق الأرضي: HTTP {r.status} {r.headers.get('content-type')} {len(body) // 1024} KB")

b = get("/api/admin/brand")
print("الترويسة:", b.get("name"), "|", b.get("phone"), "|", b.get("email"), "| شعار مرفوع:", bool(b.get("logo_doc")))
if b.get("logo_doc"):
    with req(f"/api/documents/{b['logo_doc']}") as r:
        body = r.read()
        print(f"  ملف الشعار: HTTP {r.status} {r.headers.get('content-type')} {len(body) // 1024} KB")

L = get("/api/leasing")
print(f"التأجير: وحدات المحفظة {len(L['units'])} · عقود {len(L['leases'])} · إشغال {L['occupancy']}٪ · إيجار سنوي {L['annual_rent']:,.0f} · متأخرات {L['arrears']:,.0f}")
by = {x["unit"]: x for x in L["leases"]}
msk = [u for u in by if u.startswith("MSK-")]
print("  عقود مساحات:", sorted(msk))
print("  متأخر:", [u for u, x in by.items() if x["arrears"] > 0], "| تنبيه تجديد:", [u for u, x in by.items() if x.get("renewal_alert")])
print("  وحدة MSK-M-012 (شاغرة محتفظ بها):", "في المحفظة" if any(u["code"] == "MSK-M-012" for u in L["units"]) else "غير موجودة")

try:
    a = get("/api/tenants")
    print("المطوّرون في شاشة الدخول:", [t["code"] for t in a])
except Exception as e:  # noqa: BLE001
    print("tenants:", e)
print("تم — لا كتابة في المنصة.")
