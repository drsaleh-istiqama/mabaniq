"""إبطال ذاكرة الأدوار عبر عمليتين حقيقيتين تتشاركان قاعدة واحدة (مكافئ عاملي uvicorn): لا تحكم لإحداهما في ذاكرة الأخرى.

التشغيل من جذر المستودع: `python tools/roles_two_processes_check.py` (SQLite في مجلد مؤقت)، أو على PostgreSQL فارغة جاهزة:
`TWO_PG_URL=postgresql://user@host:port/db python tools/roles_two_processes_check.py` (الترحيلات تُطبَّق عند الإقلاع). لا يمسّ أي بيانات حقيقية.

العملية أ (8861) يعدّل عليها المدير؛ العملية ب (8862) يستعملها مستخدم المبيعات. بعد كل تعديل على أ يجب أن تعكسه ب عند أول طلب لها، دون مهلة ولا إعادة تشغيل.
يطبع نتيجة كل خطوة ويخرج بكود 1 عند أول إخفاق.
"""
import os
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PW = "E2e-Demo-Pass-2026"
CSRF = "csrf-two-proc-" + "x" * 20
tmp = tempfile.mkdtemp(prefix="mbq-two-")
ENV = {**os.environ, "MABANIQ_DB": os.path.join(tmp, "two.db"), "MABANIQ_DEMO_PASSWORD": PW, "MABANIQ_FORCE_PW_CHANGE": "0", "MABANIQ_LOG_JSON": "0",
       "MABANIQ_RATE_LOGIN": "60/60", "MABANIQ_LOGIN_BUDGET": "60", "PYTHONIOENCODING": "utf-8"}
if os.environ.get("TWO_PG_URL"):                       # same check on PostgreSQL: both processes share the one database (row-level security per developer)
    ENV["MABANIQ_DATABASE_URL"] = os.environ["TWO_PG_URL"]
    print("engine: PostgreSQL", flush=True)
else:
    print("engine: SQLite", flush=True)
procs, logs = [], []


def start(port):
    log = open(os.path.join(tmp, f"srv{port}.log"), "wb")
    logs.append(log)
    p = subprocess.Popen([PY, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"], cwd=ROOT, env=ENV, stdout=log, stderr=log)  # noqa: S603 — fixed arguments
    procs.append(p)
    for _ in range(120):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return p
        except Exception:
            time.sleep(0.5)
    raise SystemExit(f"server {port} did not start; see {tmp}")


def client(port, user):
    base = f"http://127.0.0.1:{port}"
    r = httpx.post(base + "/api/auth/login", json={"username": user, "password": PW}, headers={"x-csrf-token": CSRF}, cookies={"mbq_csrf": CSRF}, timeout=30)
    assert r.status_code == 200, (user, port, r.status_code, r.text[:200])
    jar = {ck.name: ck.value for ck in r.cookies.jar}                 # the response's own cookies: the session and the rotated double-submit token
    return httpx.Client(base_url=base, timeout=30, cookies=jar, headers={"x-csrf-token": jar.get("mbq_csrf", CSRF)})


def step(name, ok, extra=""):
    print(("OK   " if ok else "FAIL ") + name + (" — " + extra if extra else ""), flush=True)
    if not ok:
        raise SystemExit(1)


try:
    start(8861)          # first alone: it creates and seeds the database
    start(8862)          # then the second, on the same file: its cache starts empty and shares nothing with the first
    admin_a = client(8861, "admin")
    sales_b = client(8862, "sales")
    sales_a = client(8861, "sales")
    me_b = sales_b.get("/api/me").json()
    step("B sees the default sales permissions", "leads" in me_b["perms"] and sales_b.get("/api/leads").status_code == 200, f"{len(me_b['perms'])} permissions")
    step("A sees them too", "leads" in sales_a.get("/api/me").json()["perms"])

    r = admin_a.post("/api/roles/sales/perms", json={"revoke": ["leads"]})
    step("admin on A withdraws `leads` from sales", r.status_code == 200 and r.json()["removed"] == ["leads"], r.text[:120])
    codes = [sales_b.get("/api/leads").status_code for _ in range(5)]
    step("B (another process, warm cache) refuses the very next requests", set(codes) == {403}, str(codes))
    step("B's /api/me no longer lists it", "leads" not in sales_b.get("/api/me").json()["perms"])
    step("A refuses too", sales_a.get("/api/leads").status_code == 403)

    r = admin_a.post("/api/roles/sales/perms", json={"grant": ["leads"]})
    step("admin on A gives it back", r.status_code == 200 and r.json()["added"] == ["leads"])
    codes = [sales_b.get("/api/leads").status_code for _ in range(5)]
    step("B accepts again at once", set(codes) == {200}, str(codes))

    # a custom role made on B, used on A — and a second change from the other side
    admin_b = client(8862, "admin")
    r = admin_b.post("/api/roles", json={"label": "دور من العملية ب", "copy_from": "sales"})
    code = r.json()["code"]
    step("a custom role is created on B", r.status_code == 200 and code.startswith("custom_"))
    roles_a = {x["code"] for x in admin_a.get("/api/roles").json()["roles"]}
    step("A lists it at its first request", code in roles_a)
    r = admin_a.post("/api/users", json={"username": "two.proc", "name": "مستخدم عمليتين", "role": code})
    step("A creates a user with the role made on B", r.status_code == 200, r.text[:100])
    step("the user's label is the custom role's name on both sides", any(u["username"] == "two.proc" and u["role_label"] == "دور من العملية ب" for u in admin_b.get("/api/users").json()))
    r = admin_b.post(f"/api/roles/{code}/perms", json={"grant": ["finance"]})
    step("B grants `finance` to the custom role", r.status_code == 200)
    step("A's role list shows `finance` at once", "finance" in next(x for x in admin_a.get("/api/roles").json()["roles"] if x["code"] == code)["perms"])
    print("ALL OK")
finally:
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=15)
        except Exception:
            p.kill()
    for f in logs:
        f.close()
