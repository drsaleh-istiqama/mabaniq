# -*- coding: utf-8 -*-
"""تهيئة نسخة محلية **معزولة** من مطوّر «رؤية العقارية» لتمثيل توضيحي في فيديو مبانيك (لا تمسّ الإنتاج ولا قاعدة الشركة).

يضيف **بيانات افتراضية** فوق مشاريع رؤية الحقيقية (الوحدات والنِّسب كما نُشرت): أسعار ومساحات، مشترين، حجوزات، عقود، أقساط، مقاولون ومستخلصات،
مواعيد تسليم — كلها «تمثيل توضيحي» توسَم على الشاشة. لا تُشغَّل على بيئة فيها بيانات حقيقية.

    MABANIQ_BASE=http://127.0.0.1:8804 MABANIQ_DEMO_PASSWORD=<سر محلي> MABANIQ_SIM_DB=<مجلد القاعدة> python sim_prepare.py
"""
import datetime as dt
import http.cookiejar
import json
import os
import random
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("MABANIQ_BASE", "http://127.0.0.1:8804")
PW = os.environ.get("MABANIQ_DEMO_PASSWORD") or sys.exit("MABANIQ_DEMO_PASSWORD غير معيَّن")
DBDIR = Path(os.environ.get("MABANIQ_SIM_DB") or sys.exit("MABANIQ_SIM_DB غير معيَّن"))
HERE = Path(__file__).resolve().parent
OUT = HERE / "sim"
OUT.mkdir(exist_ok=True)
TODAY = dt.date.today()


def add_months(d: dt.date, m: int) -> dt.date:
    y, mo = divmod(d.month - 1 + m, 12)
    return dt.date(d.year + y, mo + 1, min(d.day, 28))


class Session:
    def __init__(self, user):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        body = json.dumps({"username": user, "password": PW, "tenant": "view"}).encode()
        self.op.open(urllib.request.Request(BASE + "/api/auth/login", body, {"Content-Type": "application/json"}))
        self.csrf = next((c.value for c in self.cj if c.name == "mbq_csrf"), "")

    def req(self, path, data=None):
        h = {"X-CSRF-Token": self.csrf}
        if data is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(data).encode()
        return self.op.open(urllib.request.Request(BASE + path, data, h))

    def get(self, path):
        with self.req(path) as r:
            return json.loads(r.read())

    def post(self, path, obj=None):
        try:
            with self.req(path, obj if obj is not None else {}) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise SystemExit(f"POST {path} → {e.code}: {e.read()[:300].decode('utf-8', 'replace')}")

    def pdf(self, path, dest):
        with self.req(path) as r:
            Path(dest).write_bytes(r.read())


admin = Session("admin")  # أول دخول يبذر المطوّر
projects = {p["code"]: p for p in admin.get("/api/projects")}
assert set(projects) == {"BRK", "SLH", "KYN", "VHT", "VBZ", "VGD"}, set(projects)

# ───────────────────────── ١) أسعار ومساحات ومواعيد تسليم ومقاولون ومستخلصات (مباشرة في قاعدة النسخة المعزولة)
db = sqlite3.connect(DBDIR / "tenant_view.db")
db.row_factory = sqlite3.Row
rnd = random.Random(2026)
PPM = {"BRK": {"مكتب": 560, "محل تجاري": 1250}, "SLH": {"شقة": 690, "محل تجاري": 1250}, "KYN": {"شقة": 660, "محل تجاري": 1200},
       "VHT": {"مكتب": 520, "صالة عرض": 1100}, "VBZ": {"محل تجاري": 1100, "صالة عرض": 1000}, "VGD": {"شقة": 640, "محل تجاري": 1300}}
AREA = {"مكتب": (52, 135), "شقة": (68, 128), "محل تجاري": (36, 95), "صالة عرض": (170, 190)}
for code, p in projects.items():
    for u in db.execute("SELECT id, type FROM units WHERE project_id=?", (p["id"],)).fetchall():
        tp = u["type"]
        tp = tp if tp in AREA else ("شقة" if code in ("SLH", "KYN") else "محل تجاري")  # الوحدة غير المصنَّفة تُعامل كأقرب نوع للمشروع
        lo, hi = AREA[tp]
        area = round(rnd.uniform(lo, hi) * 2) / 2
        ppm = PPM[code].get(tp) or list(PPM[code].values())[0]
        price = round(area * ppm * rnd.uniform(0.97, 1.05) / 100) * 100
        db.execute("UPDATE units SET area=?, price=?, view=? WHERE id=?", (area, price, "تمثيل توضيحي", u["id"]))
HAND = {"VHT": 20, "SLH": 12, "KYN": 12, "VGD": 6, "VBZ": 3}
for code, m in HAND.items():
    db.execute("UPDATE projects SET handover=? WHERE code=?", (add_months(TODAY, m).isoformat(), code))
    pid = projects[code]["id"]
    db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"escrow:{pid}", str({"VHT": 140000, "SLH": 410000, "KYN": 300000, "VGD": 520000, "VBZ": 90000}[code])))

k = {}
for i, nm in enumerate(("شركة البناء المتحد", "مؤسسة الإنشاءات الحديثة", "الخليج للمقاولات"), 1):
    k[i] = db.execute("INSERT INTO contractors(name,cr_number) VALUES(?,?)", (nm, str(1_100_000 + i * 7919))).lastrowid
STAGES = [("التصاريح والتجهيز", .05), ("الحفر والأساسات", .12), ("الهيكل الخرساني", .30), ("البلوك والتمديدات", .18),
          ("التشطيبات الداخلية", .20), ("الواجهات والأعمال الخارجية", .10), ("الاختبار والتسليم", .05)]
for (code, kid), months in zip((("SLH", 1), ("VGD", 2), ("VHT", 3)), (30, 24, 36)):
    p = projects[code]
    value = db.execute("SELECT SUM(price) FROM units WHERE project_id=?", (p["id"],)).fetchone()[0] * .72
    ho = add_months(TODAY, HAND[code])
    start = add_months(ho, -months)
    build = p["build_pct"]
    db.execute("INSERT INTO contracts_c(project_id,contractor_id,value,retention_pct,delay_penalty_per_day,start,finish) VALUES(?,?,?,?,?,?,?)",
               (p["id"], k[kid], round(value, -3), .10, round(value * .0005, -1), start.isoformat(), ho.isoformat()))
    acc, prev = 0.0, None
    for nm, w in STAGES:
        s0, e0 = add_months(start, round(months * acc)), add_months(start, round(months * (acc + w)))
        lo, hi = acc * 100, (acc + w) * 100
        pct = 100 if build >= hi else 0 if build <= lo else round((build - lo) / (hi - lo) * 100)
        prev = db.execute("INSERT INTO schedule_tasks(project_id,name,planned_start,planned_end,actual_start,actual_end,pct,depends_on,weight) VALUES(?,?,?,?,?,?,?,?,?)",
                          (p["id"], nm, s0.isoformat(), e0.isoformat(), s0.isoformat() if pct > 0 else None, e0.isoformat() if pct == 100 else None, pct, prev, w)).lastrowid
        acc += w
    for cat, share in (("أعمال إنشائية", .62), ("كهروميكانيك", .18), ("تشطيبات", .12), ("استشارات وإشراف", .04), ("احتياطي طوارئ", .04)):
        db.execute("INSERT INTO budgets(project_id,category,amount) VALUES(?,?,?)", (p["id"], cat, round(value * share, -3)))
    full = db.execute("SELECT SUM(price) FROM units WHERE project_id=?", (p["id"],)).fetchone()[0]
    remaining = full * .72 * (1 - build / 100)
    span = max(1, min(12, HAND[code]))
    for m in range(1, 13):
        amt = remaining / span if m <= span else 25000
        db.execute("INSERT INTO cost_schedule(project_id,month,amount,label) VALUES(?,?,?,?)",
                   (p["id"], add_months(TODAY.replace(day=1), m).strftime("%Y-%m"), round(amt, -3), "مستخلصات وتشغيل" if m <= span else "صيانة الضمان"))


def ipc(code, kid, no, stage, claimed, value, status, approved, items):
    iid = db.execute("INSERT INTO ipcs(project_id,contractor_id,no,stage,claimed_pct,stage_value,status,approved_pct,created) VALUES(?,?,?,?,?,?,?,?,?)",
                     (projects[code]["id"], k[kid], no, stage, claimed, value, status, approved, (TODAY - dt.timedelta(days=rnd.randint(1, 5))).isoformat())).lastrowid
    for it, w, v, ev in items:
        db.execute("INSERT INTO ipc_items(ipc_id,item,weight,verified_pct,evidence) VALUES(?,?,?,?,?)", (iid, it, w, v, ev))


ipc("SLH", 1, 2, "الحفر والأساسات", 100, 380000, "approved", 100, [])
ipc("SLH", 1, 3, "الهيكل الخرساني", 55, 640000, "pending", None,
    [("أعمدة وسقف الطوابق 1–3", .5, 80, 18), ("أعمدة وسقف الطابق 4", .3, 0, 6), ("أعمدة وسقف الطابق 5", .2, 0, 3)])
ipc("VGD", 2, 5, "التشطيبات الداخلية", 70, 880000, "pending", None,
    [("تشطيب الطوابق 1–3", .6, 100, 22), ("تشطيب الطابق 4", .3, 33, 9), ("تشطيب الطابق 5", .1, 0, 0)])
ipc("VHT", 3, 1, "الحفر والأساسات", 10, 520000, "approved", 10, [])
db.commit()
db.close()
print("✓ أسعار/مساحات/مواعيد/مقاولون/مستخلصات")

# ───────────────────────── ٢) مشترون وحجوزات وعقود وأقساط عبر واجهات المنصة نفسها
FIRST = ["خالد", "مريم", "سالم", "نورة", "يوسف", "سعيد", "فاطمة", "أحمد", "هلال", "ناصر", "عائشة", "محمد", "حمد", "سلطان", "بدر", "ريم"]
LAST = ["البلوشي", "الحارثي", "الكندي", "الرواحي", "العامري", "السيابي", "المعمري", "الغافري", "البوسعيدي", "الريامي", "المقبالي", "الهاشمي"]
PLANS = ["milestone", "6040", "murabaha", "milestone"]
sales = Session("sales")
fin = Session("finance")
made = []


def sell(code, name, plan, sign=True):
    r = sales.post("/api/bookings", {"unit_code": code, "customer_name": name, "phone": f"+968 9{rnd.randint(1000000, 9999999)}", "plan": plan})
    bid, cid = r["booking_id"], r["customer_id"]
    k_ = sales.post(f"/api/customers/{cid}/kyc", {"id_type": "بطاقة مدنية", "id_number": str(rnd.randint(10000000, 99999999)), "nationality": "عماني",
                                                 "id_expiry": (TODAY + dt.timedelta(days=900)).isoformat(), "dob": "1986-04-12", "pep": False,
                                                 "source_of_funds": "راتب وأعمال خاصة", "consent_signed": True})
    if k_["status"] != "verified":
        admin.post(f"/api/customers/{cid}/kyc/decide", {"action": "verified", "note": "اعتماد إداري لحالة تمثيلية"})
    fin.post(f"/api/bookings/{bid}/confirm")
    sales.post(f"/api/bookings/{bid}/contract")
    if sign:
        sales.post(f"/api/bookings/{bid}/contract/sign-inperson", {"typed_name": name, "accept": True})
    made.append((code, name, bid, cid))
    return bid, cid


def pick(n):
    return f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"


names = set()
for code in ("SLH-A-20", "SLH-A-21", "SLH-A-22", "VHT-O-10", "VHT-O-11", "VHT-O-12", "VHT-O-13", "VHT-O-14", "VGD-A-45"):
    while True:
        nm = pick(0)
        if nm not in names:
            names.add(nm)
            break
    sell(code, nm, rnd.choice(PLANS), sign=code not in ("VHT-O-14",))
# حجزان معلَّقان بانتظار التحقق (يظهران في شاشة «التحقق والعقود»)
for code, nm in (("VHT-O-15", "شركة الأفق للاستشارات"), ("SLH-A-23", "هلال بن سالم المقبالي")):
    r = sales.post("/api/bookings", {"unit_code": code, "customer_name": nm, "phone": f"+968 9{rnd.randint(1000000, 9999999)}", "plan": "milestone"})
    made.append((code, nm, r["booking_id"], r["customer_id"]))
# عرضا سعر ببصمة ورمز تحقق
quotes = []
for code, nm, plan in (("VHT-O-17", "شركة الأفق للاستشارات", "milestone"), ("SLH-A-24", "نورة بنت حمد الرواحي", "murabaha")):
    q = sales.post("/api/quotes", {"unit_code": code, "customer_name": nm, "phone": f"+968 9{rnd.randint(1000000, 9999999)}", "plan": plan, "discount_pct": 0.02, "valid_days": 14})
    quotes.append(q)
    print("  عرض", q.get("number"), code)
print("✓ حجوزات:", len(made), "· عروض:", len(quotes))
(OUT / "sim-state.json").write_text(json.dumps({"made": made, "quotes": quotes}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
