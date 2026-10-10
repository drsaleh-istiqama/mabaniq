"""مبانيك | Mabaniq — واجهة برمجية REST (FastAPI)."""
import asyncio
import contextlib
import datetime as dt
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth as A
from . import cache, dbx, pii, retention
from . import engines as E
from . import observability as O
from .auth import need
from .config import settings
from .db import TENANT, backup, connect, tenants, valid_tenant
from .seed import seed

O.setup_logging()

FRONT = Path(__file__).resolve().parent.parent / "frontend" / "dist"  # Unit 3: Vite build output (sources live in web/)


@asynccontextmanager
async def lifespan(_app):
    errs = settings.validate()  # Unit 0: fail fast — an incomplete production configuration never serves a request
    if errs:
        raise RuntimeError("إعدادات الإنتاج ناقصة: " + " | ".join(errs))
    pii.prod_checks()  # 0.5.0 — M6: لا إقلاع في الإنتاج بلا أسرار صريحة
    if not (FRONT / "index.html").exists():
        raise RuntimeError("الواجهة غير مبنية: شغّل `npm ci && npm run build` (الوحدة 3 — المصادر في web/ والمخرجات في frontend/dist)")
    O.init_sentry()  # Unit 4: optional, DSN from the environment only
    O.log.info("startup", extra={"event": "startup"})
    for t in tenants():
        seed(tenant=t)
    stop = asyncio.Event()
    task = asyncio.create_task(retention.scheduler(stop)) if settings.retention_enabled else None  # Unit 4: PDPL retention
    try:
        yield
    finally:
        stop.set()
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        dbx.close_pools()


PROD = os.environ.get("MABANIQ_ENV", "demo") == "prod"
VERSION = settings.version
app = FastAPI(title="Mabaniq API", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# ------------------------------------------------------------------ الصحة والإصدار (بلا مصادقة، بلا قاعدة بيانات في /health)
@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION}


@app.get("/ready")
def ready():
    checks = {}
    try:
        c = connect()
        c.execute("SELECT 1").fetchone()
        c.close()
        checks["database"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["database"] = f"error: {type(e).__name__}"
    try:
        pii.secret("pii.key", "MABANIQ_PII_KEY", lambda: "")  # raises in prod when missing
        checks["secrets"] = "ok"
    except RuntimeError:
        checks["secrets"] = "missing"
    checks["config"] = "ok" if not settings.validate() else "invalid"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)


@app.get("/version")
def version():
    return settings.public()


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint(request: Request):
    """Unit 4: Prometheus text format. Exposed only when MABANIQ_METRICS_TOKEN is set, and only to its bearer."""
    token = O.settings.metrics_token
    if not token:
        raise HTTPException(404)
    auth = request.headers.get("authorization", "")
    if not (auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], token)):
        raise HTTPException(401, "رمز المقاييس غير صحيح")
    return Response(O.metrics.render(dbx.pool_stats()), media_type="text/plain; version=0.0.4; charset=utf-8", headers={"Cache-Control": "no-store"})


from .common import ACTOR, act_as, audit, db  # noqa: E402


def expire_holds(c):
    """تحرير الحجوزات المبدئية التي انتهت مهلتها (72 ساعة) تلقائيًا."""
    today = dt.date.today().isoformat()
    for b in c.execute("SELECT id,unit_id FROM bookings WHERE status='pending' AND expires<?", (today,)).fetchall():
        c.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (b["id"],))
        c.execute("UPDATE units SET status='a' WHERE id=?", (b["unit_id"],))
        audit(c, "تحرير حجز منتهي", f"booking {b['id']}", "النظام")
    c.commit()


# ------------------------------------------------------------------ قراءة
def _cached_json(key: str, compute):
    """Unit 4: the heavy dashboards are cached per tenant as *serialised* JSON — FastAPI's encoder on a few thousand rows costs
    more than the query once the computation itself is shared; any write of the tenant invalidates (cache.bump)."""
    body = cache.get(TENANT.get(), key, lambda: json.dumps(jsonable_encoder(compute()), ensure_ascii=False, separators=(",", ":")).encode(),
                     settings.cache_ttl)
    return Response(content=body, media_type="application/json")


@app.get("/api/projects")
def projects(_=Depends(need("view"))):
    return _cached_json("projects", _projects)


def _projects():
    c = db()
    out = []
    for p in c.execute("SELECT * FROM projects ORDER BY id"):
        k = E.kpis(c, p["id"])
        sold = c.execute("SELECT COUNT(*) FROM units WHERE project_id=? AND status!='a'", (p["id"],)).fetchone()[0]
        out.append({**dict(p), **k, "sold_pct": round(100 * sold / k["total_units"])})
    return out


@app.get("/api/kpis")
def kpis(project_id: int | None = None, _=Depends(need("view"))):
    c = db()
    expire_holds(c)
    k = E.kpis(c, project_id)
    k["cash_gap"] = E.cash_radar(c)["gap"]
    return k


@app.get("/api/units")
def units(project_id: int, building: str | None = None, _=Depends(need("inventory"))):
    c = db()
    q, a = "SELECT * FROM units WHERE project_id=?", [project_id]
    if building:
        q += " AND building=?"
        a.append(building)
    rows = [dict(r) for r in c.execute(q + " ORDER BY building, floor DESC, pos", a)]
    hot = {(s["view"], s["type"]): s["suggested_change"] for s in E.pricing(c, project_id)}
    for r in rows:
        r["ai_change"] = hot.get((r["view"], r["type"]), 0) if r["status"] == "a" else 0
    return rows


@app.get("/api/units/{code}")
def unit(code: str, _=Depends(need("inventory"))):
    c = db()
    u = c.execute("SELECT * FROM units WHERE code=?", (code,)).fetchone()
    if not u:
        raise HTTPException(404, "الوحدة غير موجودة")
    res = dict(u)
    res["suggestion"] = E.unit_suggestion(c, u)
    b = c.execute("""SELECT b.*, cu.name cname, cu.phone FROM bookings b JOIN customers cu ON cu.id=b.customer_id
                     WHERE b.unit_id=? AND b.status!='cancelled' ORDER BY b.id DESC""", (u["id"],)).fetchone()
    if b:
        ins = [dict(i) for i in c.execute("SELECT * FROM installments WHERE booking_id=? ORDER BY seq", (b["id"],))]
        res["booking"] = {**dict(b), "installments": ins,
                          "paid": sum(i["paid_amount"] for i in ins), "total": sum(i["amount"] for i in ins)}
    return res


@app.get("/api/pricing/{project_id}")
def pricing(project_id: int, _=Depends(need("inventory"))):
    return E.pricing(db(), project_id)


@app.get("/api/leads")
def leads(_=Depends(need("leads"))):
    c = db()
    return [dict(r) for r in c.execute("""SELECT l.*, p.name pname FROM leads l JOIN projects p ON p.id=l.project_id
                                          ORDER BY l.score DESC""")]


@app.get("/api/leads/{lead_id}/matches")
def matches(lead_id: int, _=Depends(need("leads"))):
    return E.match_units(db(), lead_id)


@app.get("/api/risk")
def risk(_=Depends(need("finance"))):
    return E.default_risk(db())


@app.get("/api/cash")
def cash(plan: bool = False, _=Depends(need("view"))):
    return _cached_json(f"cash:{int(plan)}", lambda: E.cash_radar(db(), plan))


@app.get("/api/ipcs")
def ipcs(_=Depends(need("construction"))):
    c = db()
    out = []
    for i in c.execute("""SELECT i.*, k.name contractor, p.name pname FROM ipcs i JOIN contractors k ON k.id=i.contractor_id
                          JOIN projects p ON p.id=i.project_id ORDER BY i.status DESC, i.id DESC"""):
        out.append({**dict(i), "verification": E.verify_ipc(c, i["id"])})
    return out


@app.get("/api/decisions")
def decisions(_=Depends(need("view"))):
    # Unit 4: whole-portfolio computation (~130 ms) shared by every dashboard for a few seconds; any write of the tenant invalidates it
    return _cached_json("decisions", lambda: E.decisions(db()))


@app.get("/api/audit")
def audit_log(limit: int = Query(30, ge=1, le=500), _=Depends(need("audit"))):
    return [dict(r) for r in db().execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]


@app.get("/api/search")
def search(q: str, _=Depends(need("inventory"))):
    q = q[:60]
    c = db()
    like = f"%{q}%"
    res = [{"type": "unit", "label": r["code"], "sub": f"{r['type']} · {r['view']}", "ref": r["code"]}
           for r in c.execute("SELECT * FROM units WHERE code LIKE ? LIMIT 6", (like,))]
    res += [{"type": "lead", "label": r["name"], "sub": r["interest"], "ref": r["id"]}
            for r in c.execute("SELECT * FROM leads WHERE name LIKE ? LIMIT 6", (like,))]
    res += [{"type": "customer", "label": r["name"], "sub": r["code"], "ref": r["code"]}
            for r in c.execute("""SELECT cu.name, u.code FROM customers cu JOIN bookings b ON b.customer_id=cu.id
                                  JOIN units u ON u.id=b.unit_id WHERE cu.name LIKE ? AND b.status!='cancelled' LIMIT 6""", (like,))]
    return res


# ------------------------------------------------------------------ كتابة
class BookingIn(BaseModel):
    unit_code: str = Field(max_length=30)
    customer_name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=6, max_length=20, pattern=r"^[0-9+ ()-]+$")
    plan: str = Field(pattern="^(milestone|6040|murabaha)$")
    lead_id: int | None = None
    broker_id: int | None = None


@app.post("/api/bookings")
def book(b: BookingIn, _=Depends(act_as("book"))):
    c = db()
    u = c.execute("SELECT u.*, p.handover FROM units u JOIN projects p ON p.id=u.project_id WHERE u.code=?",
                  (b.unit_code,)).fetchone()
    if not u:
        raise HTTPException(404, "الوحدة غير موجودة")
    if u["status"] != "a" or u["retained"]:
        raise HTTPException(409, "الوحدة غير متاحة")
    if b.broker_id and not c.execute("SELECT 1 FROM brokers WHERE id=? AND active=1", (b.broker_id,)).fetchone():
        raise HTTPException(404, "الوسيط غير موجود")
    from .paperwork import create_booking  # Unit 6: one path for manual bookings and quotation conversions
    res = create_booking(c, u, b.customer_name, b.phone, b.plan, b.lead_id, b.broker_id)
    audit(c, "حجز مبدئي", f"{b.unit_code} لـ {b.customer_name} ({b.plan})")
    c.commit()
    return res


@app.post("/api/bookings/{bid}/confirm")
def confirm(bid: int, _=Depends(act_as("confirm"))):
    c = db()
    b = c.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
    if not b or b["status"] != "pending":
        raise HTTPException(409, "الحجز غير قابل للتأكيد")
    kyc = c.execute("SELECT kyc_status FROM customers WHERE id=?", (b["customer_id"],)).fetchone()
    if kyc["kyc_status"] != "verified":
        raise HTTPException(409, "لا يُؤكد البيع قبل اعتماد التحقق من هوية العميل (KYC)")
    first = c.execute("SELECT * FROM installments WHERE booking_id=? AND seq=1", (bid,)).fetchone()
    # 0.4.1 — M3: العربون يمر بمسار السداد الموحّد (دفتر المدفوعات + إيصال + فاتورة) بدل تعديل القسط مباشرةً،
    # حتى يتطابق كشف الضمان مع المطابقة البنكية وتصدير ERPNext. idempotent عبر gateway_ref.
    receipt = None
    if first["paid_amount"] < first["amount"] - 1:
        from .modules import create_intent, record_payment
        intent_id, due = create_intent(c, first["id"], provider="عربون عند التأكيد")
        receipt = record_payment(c, intent_id, f"deposit_{bid}", due, ACTOR.get())["receipt"]
    c.execute("UPDATE bookings SET status='confirmed', expires=NULL WHERE id=?", (bid,))
    c.execute("UPDATE units SET status='s' WHERE id=?", (b["unit_id"],))
    create_commission(c, bid)
    audit(c, "تأكيد بيع", f"booking {bid} بعد سداد العربون {first['amount']:,.0f}" + (f" · إيصال {receipt}" if receipt else " (مسدَّد مسبقًا)"))
    c.commit()
    return {"ok": True, "receipt": receipt}


@app.post("/api/bookings/{bid}/cancel")
def cancel(bid: int, _=Depends(act_as("book"))):
    c = db()
    b = c.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
    if not b or b["status"] != "pending":
        raise HTTPException(409, "لا يُلغى إلا الحجز المبدئي")
    c.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (bid,))
    c.execute("UPDATE units SET status='a' WHERE id=?", (b["unit_id"],))
    audit(c, "إلغاء حجز", f"booking {bid}")
    c.commit()
    return {"ok": True}


class StageIn(BaseModel):
    stage: int = Field(ge=0, le=4)


@app.post("/api/leads/{lead_id}/stage")
def lead_stage(lead_id: int, s: StageIn, _=Depends(act_as("leads"))):
    c = db()
    if not c.execute("SELECT 1 FROM leads WHERE id=?", (lead_id,)).fetchone():
        raise HTTPException(404, "العميل غير موجود")
    c.execute("UPDATE leads SET stage=?, interactions=interactions+1, last_contact=? WHERE id=?",
              (s.stage, dt.date.today().isoformat(), lead_id))
    E.rescore_leads(c)
    audit(c, "تحديث مرحلة عميل", f"lead {lead_id} → {s.stage}")
    c.commit()
    return dict(c.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())


class DecisionIn(BaseModel):
    key: str
    action: str = Field(pattern="^(approve|dismiss)$")


@app.post("/api/decisions/act")
def act(dcs: DecisionIn, u=Depends(act_as("decide"))):
    c = db()
    item = next((x for x in E.decisions(c) if x["key"] == dcs.key), None)
    if not item:
        raise HTTPException(404, "القرار غير موجود")
    if item["done"]:
        raise HTTPException(409, "اتُّخذ القرار مسبقًا")
    if dcs.action == "approve":
        p = item["payload"]
        if item["kind"] == "price":
            n = c.execute("UPDATE units SET price=ROUND(price*(1+?)/100)*100 WHERE project_id=? AND status='a' AND view=? AND type=?",
                          (p["change"], item["project_id"], p["view"], p["type"])).rowcount
            detail = f"تعديل سعر {n} وحدة بنسبة {p['change']*100:.0f}٪"
        elif item["kind"] == "reschedule":
            for bid in p["booking_ids"]:
                c.execute("UPDATE customers SET rescheduled=1 WHERE id=(SELECT customer_id FROM bookings WHERE id=?)", (bid,))
            detail = f"إرسال عروض إعادة جدولة إلى {len(p['booking_ids'])} عملاء"
        elif item["kind"] == "ipc":
            if "approve_ipc" not in u["perms"]:
                raise HTTPException(403, "اعتماد المستخلصات من صلاحية الإدارة")
            return approve_ipc(p["ipc_id"], c)
        else:
            detail = "اعتماد خطة معالجة السيولة"
    else:
        detail = "تجاهل التوصية"
    c.execute("INSERT INTO decisions_log VALUES(?,?,?)", (dcs.key, dcs.action, dt.datetime.now().isoformat(timespec="seconds")))
    audit(c, "قرار: " + item["title"], detail)
    c.commit()
    return {"ok": True, "detail": detail}


@app.post("/api/ipcs/{ipc_id}/approve")
def approve_ipc_ep(ipc_id: int, _=Depends(act_as("approve_ipc"))):
    return approve_ipc(ipc_id)


def approve_ipc(ipc_id: int, c=None):
    c = c or db()
    i = c.execute("SELECT * FROM ipcs WHERE id=?", (ipc_id,)).fetchone()
    if not i or i["status"] != "pending":
        raise HTTPException(409, "المستخلص غير معلق")
    v = E.verify_ipc(c, ipc_id)
    c.execute("UPDATE ipcs SET status='approved', approved_pct=? WHERE id=?", (v["verified_pct"], ipc_id))
    c.execute("INSERT OR IGNORE INTO decisions_log VALUES(?,?,?)", (f"ipc:{ipc_id}", "approve", dt.datetime.now().isoformat(timespec="seconds")))
    audit(c, "اعتماد مستخلص", f"المستخلص {i['no']} بنسبة {v['verified_pct']}٪ ({v['verified_amount']:,.0f} ر.ع)")
    c.commit()
    return {"ok": True, "detail": f"اعتُمد بنسبة {v['verified_pct']}٪", "amount": v["verified_amount"]}


class AskIn(BaseModel):
    q: str = Field(min_length=1, max_length=500)


@app.post("/api/assistant")
def ask(a: AskIn, _=Depends(need("view"))):
    return E.assistant(db(), a.q)


@app.post("/api/reset")
def reset(_=Depends(act_as("admin"))):
    if PROD:
        raise HTTPException(403, "إعادة البيانات معطلة في بيئة الإنتاج")
    backup(db(), "before-reset")
    seed(force=True)
    return {"ok": True}


# ------------------------------------------------------------------ الهوية
class LoginIn(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=4, max_length=200)
    otp: str | None = Field(default=None, max_length=12)  # رمز TOTP من 6 أرقام أو رمز استرداد xxxx-xxxx (الوحدة 2)
    tenant: str = Field(default="jadwa", max_length=32, pattern=r"^[a-z][a-z0-9-]{1,30}$")


def _secure(request):
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


@app.get("/api/tenants")
def tenant_list():
    return [{"code": k, "name": v} for k, v in tenants().items()]


@app.post("/api/auth/login")
def do_login(body: LoginIn, request: Request, response: Response):
    if not valid_tenant(body.tenant):
        raise HTTPException(401, "اسم المستخدم أو كلمة المرور غير صحيحة")
    TENANT.set(body.tenant)
    token, user = A.login(body.username, body.password, A.client_ip(request), body.otp, request.headers.get("user-agent", ""))
    sec = _secure(request)
    response.set_cookie(A.COOKIE, token, httponly=True, samesite="lax", secure=sec, max_age=A.SESSION_HOURS * 3600, path="/")
    response.set_cookie(A.TENANT_COOKIE, body.tenant, httponly=True, samesite="lax", secure=sec, max_age=A.SESSION_HOURS * 3600, path="/")
    # 0.5.0 — M7: رمز CSRF مزدوج — كوكي يقرؤه السكربت ويعيده في ترويسة X-CSRF-Token مع كل طلب مُعدِّل
    response.set_cookie(A.CSRF_COOKIE, A.new_csrf(), httponly=False, samesite="lax", secure=sec, max_age=A.SESSION_HOURS * 3600, path="/")
    return user


class PwIn(BaseModel):
    current: str = Field(min_length=4, max_length=200)
    new: str = Field(min_length=10, max_length=200)


@app.post("/api/auth/password")
def change_pw(p: PwIn, request: Request, u=Depends(A.current)):
    c = A.conn()
    row = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    if not A.check_pw(p.current, row["pw"]):
        raise HTTPException(400, "كلمة المرور الحالية غير صحيحة")
    if p.new == p.current:
        raise HTTPException(400, "اختر كلمة مرور مختلفة")
    err = A.policy_errors(p.new, u["username"])
    if err:
        raise HTTPException(400, err)
    c.execute("UPDATE users SET pw=?, must_change=0, pw_changed=? WHERE id=?", (A.hash_pw(p.new), dt.datetime.now().isoformat(timespec="seconds"), u["id"]))
    A.kill_sessions(c, u["id"], A.token_hash(request))  # إنهاء كل الجلسات الأخرى
    audit(c, "تغيير كلمة المرور", u["username"], u["name"])
    c.commit()
    if u["role"] == "admin":
        fa = pii.data_dir() / "first-admin-password.txt"
        if fa.exists():
            fa.unlink()  # 0.5.0 — M6
    return {"ok": True}


@app.post("/api/auth/2fa/setup")
def totp_setup(u=Depends(A.current)):
    c = A.conn()
    if u["totp_enabled"]:
        raise HTTPException(409, "التحقق الثنائي مفعّل مسبقًا")
    sec = A.new_totp_secret()
    c.execute("UPDATE users SET totp_secret=? WHERE id=?", (sec, u["id"]))
    c.commit()
    return {"secret": sec, "uri": f"otpauth://totp/Mabaniq:{u['username']}?secret={sec}&issuer=Mabaniq"}


class OtpIn(BaseModel):
    otp: str = Field(pattern=r"^\d{6}$")


@app.post("/api/auth/2fa/enable")
def totp_enable(o: OtpIn, request: Request, u=Depends(A.current)):
    c = A.conn()
    row = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    ctr = A.totp_verify(row["totp_secret"], o.otp, row["totp_last"])
    if ctr is None:
        raise HTTPException(400, "الرمز غير صحيح")
    c.execute("UPDATE users SET totp_enabled=1, totp_last=? WHERE id=?", (ctr, u["id"]))
    codes = A.new_recovery_codes(c, u["id"])  # الوحدة 2: رموز استرداد تُعرض مرة واحدة
    A.kill_sessions(c, u["id"], A.token_hash(request))  # رفع مستوى الحماية = إنهاء الجلسات الأخرى (تدوير)
    audit(c, "تفعيل التحقق الثنائي", f"{u['username']} · أُصدرت {len(codes)} رموز استرداد · أُنهيت الجلسات الأخرى", u["name"])
    c.commit()
    return {"ok": True, "recovery_codes": codes, "note": "احفظ رموز الاسترداد في مكان آمن؛ كل رمز يُستعمل مرة واحدة بدل رمز التطبيق عند فقدان الجهاز."}


@app.post("/api/auth/2fa/recovery")
def totp_recovery_regen(o: OtpIn, u=Depends(A.current)):
    """إعادة إصدار رموز الاسترداد (تُبطل القديمة) — يتطلب رمز TOTP حاليًا."""
    c = A.conn()
    row = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    if not row["totp_enabled"] or A.totp_verify(row["totp_secret"], o.otp, row["totp_last"]) is None:
        raise HTTPException(400, "الرمز غير صحيح أو التحقق الثنائي غير مفعّل")
    codes = A.new_recovery_codes(c, u["id"])
    audit(c, "إعادة إصدار رموز الاسترداد", u["username"], u["name"])
    c.commit()
    return {"recovery_codes": codes}


# ------------------------------------------------------------------ الجلسات والأجهزة (الوحدة 2)
@app.get("/api/me/sessions")
def my_sessions(request: Request, u=Depends(A.current)):
    c = A.conn()
    return {"idle_minutes": A.IDLE_MINUTES, "absolute_hours": A.SESSION_HOURS, "sessions": A.sessions_of(c, u["id"], A.token_hash(request))}


class RevokeIn(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")
    others: bool = False


@app.post("/api/me/sessions/revoke")
def my_sessions_revoke(r: RevokeIn, request: Request, u=Depends(A.current)):
    """إنهاء جلسة بعينها أو كل الجلسات الأخرى (الخروج من كل الأجهزة) — الجلسة الحالية تبقى."""
    c = A.conn()
    if not r.id and not r.others:
        raise HTTPException(400, "حدّد جلسة أو اطلب إنهاء الجلسات الأخرى")
    n = A.revoke_sessions(c, u["id"], r.id, A.token_hash(request)) if r.others else A.revoke_sessions(c, u["id"], r.id)
    audit(c, "إنهاء جلسات", f"{u['username']} · {n} جلسة" + (f" ({r.id})" if r.id else " (كل الأجهزة الأخرى)"), u["name"])
    c.commit()
    return {"revoked": n}


@app.get("/api/users/{uid}/sessions")
def user_sessions(uid: int, _=Depends(need("users"))):
    c = A.conn()
    return A.sessions_of(c, uid)


@app.post("/api/users/{uid}/sessions/revoke")
def user_sessions_revoke(uid: int, u=Depends(act_as("users"))):
    """إلغاء فوري لكل جلسات مستخدم (جهاز مفقود، مغادرة موظف)."""
    c = A.conn()
    t = c.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    if not t:
        raise HTTPException(404, "المستخدم غير موجود")
    n = A.revoke_sessions(c, uid)
    audit(c, "إنهاء كل جلسات مستخدم", f"{t['username']} · {n} جلسة")
    c.commit()
    return {"revoked": n}


@app.post("/api/users/{uid}/2fa/reset")
def user_2fa_reset(uid: int, u=Depends(act_as("users"))):
    """فقد الموظف جهاز المصادقة ورموز الاسترداد: المدير يعيد ضبط التحقق الثنائي وينهي الجلسات؛ في الإنتاج يُلزم بإعادة التفعيل عند الدخول."""
    c = A.conn()
    t = c.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    if not t:
        raise HTTPException(404, "المستخدم غير موجود")
    c.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL, totp_last=0, recovery_codes=NULL WHERE id=?", (uid,))
    A.revoke_sessions(c, uid)
    audit(c, "إعادة ضبط التحقق الثنائي", t["username"])
    c.commit()
    return {"ok": True}


@app.post("/api/auth/2fa/disable")
def totp_disable(o: OtpIn, u=Depends(A.current)):
    c = A.conn()
    row = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    if A.prod() and u["role"] in A.TWO_FA_REQUIRED:
        raise HTTPException(403, "التحقق الثنائي إلزامي لهذا الدور")
    if A.totp_verify(row["totp_secret"], o.otp, row["totp_last"]) is None:
        raise HTTPException(400, "الرمز غير صحيح")
    c.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE id=?", (u["id"],))
    audit(c, "إيقاف التحقق الثنائي", u["username"], u["name"])
    c.commit()
    return {"ok": True}


@app.post("/api/auth/logout")
def do_logout(request: Request, response: Response):
    A.logout(request.cookies.get(A.COOKIE))
    response.delete_cookie(A.COOKIE, path="/")
    response.delete_cookie(A.CSRF_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(u=Depends(A.current)):
    return u


# ------------------------------------------------------------------ بوابة العميل
def my_bookings(c, u):
    return c.execute("""SELECT b.*, u.code, u.type, u.area, u.view, u.floor, p.id pid, p.name pname, p.location,
                               p.build_pct, p.handover
                        FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id
                        WHERE b.customer_id=? AND b.status!='cancelled' ORDER BY b.id""", (u["customer_id"],)).fetchall()


def owned(c, u, booking_id):
    b = next((x for x in my_bookings(c, u) if x["id"] == booking_id), None)
    if not b:
        raise HTTPException(404, "الحجز غير موجود")
    return b


MILESTONES = [("الأساسات", 15), ("الهيكل الخرساني", 40), ("البلوك والتمديدات", 60), ("التشطيبات", 85), ("الواجهات", 95), ("التسليم", 100)]


@app.get("/api/portal")
def portal(u=Depends(need("portal"))):
    c = db()
    out = []
    for b in my_bookings(c, u):
        ins = [dict(i) for i in c.execute("SELECT * FROM installments WHERE booking_id=? ORDER BY seq", (b["id"],))]
        paid, total = sum(i["paid_amount"] for i in ins), sum(i["amount"] for i in ins)
        nxt = next((i for i in ins if i["paid_amount"] < i["amount"] - 1), None)
        lastipc = c.execute("""SELECT i.id FROM ipcs i WHERE project_id=? ORDER BY i.id DESC LIMIT 1""", (b["pid"],)).fetchone()
        photos = E.verify_ipc(c, lastipc["id"]).get("evidence_photos", 0) if lastipc else 0
        out.append({
            "booking_id": b["id"], "unit": b["code"], "type": b["type"], "area": b["area"], "view": b["view"], "floor": b["floor"],
            "project": b["pname"], "location": b["location"], "build_pct": b["build_pct"], "handover": b["handover"],
            "status": b["status"], "price": b["price"], "plan": b["plan"],
            "milestones": [{"name": n, "pct": p, "done": b["build_pct"] >= p} for n, p in MILESTONES],
            "evidence_photos": photos,
            "installments": ins, "paid": paid, "total": total, "next": nxt,
            "service": [dict(r) for r in c.execute("SELECT * FROM service_requests WHERE booking_id=? ORDER BY id DESC", (b["id"],))],
            "resale": [dict(r) for r in c.execute("SELECT * FROM resale WHERE booking_id=? ORDER BY id DESC", (b["id"],))],
            "market_estimate": E.resale_estimate(c, b["id"]),
        })
    cu = c.execute("SELECT consent_at, consent_version FROM customers WHERE id=?", (u["customer_id"],)).fetchone()
    return {"customer": u["name"], "bookings": out, "consent_at": cu["consent_at"] if cu else None,
            "consent_required": PRIVACY_NOTICE["version"] if not cu or cu["consent_version"] != PRIVACY_NOTICE["version"] else None}


PRIVACY_NOTICE = {
    "version": "1.0", "effective": "2026-10-09", "controller": "المطوّر (المتحكم) عبر منصة مبانيك (المعالج)",
    "purposes": ["تنفيذ عقد الحجز والبيع وتحصيل الأقساط", "التحقق من الهوية ومكافحة غسل الأموال", "خدمة ما بعد البيع والضمان واتحاد الملاك",
                 "الالتزامات النظامية (الضريبة، حساب الضمان، نقل الملكية)"],
    "data": ["الاسم والهاتف والبريد", "وثيقة الهوية ورقمها وتاريخ انتهائها (مشفَّرة)", "تاريخ الميلاد والجنسية", "سجل السداد والعقود والمراسلات"],
    "retention": "مدة العقد ثم المدة التي يفرضها القانون للسجلات المالية والعقارية؛ وما عداها يُحذف أو يُخفى هويته عند الطلب",
    "rights": ["الاطلاع ونسخة من البيانات", "التصحيح", "الحذف أو إخفاء الهوية لما لا يلزم حفظه نظامًا", "سحب الموافقة لما لا يقوم على العقد أو القانون"],
    "law": "قانون حماية البيانات الشخصية الصادر بالمرسوم السلطاني 6/2022 ولائحته التنفيذية",
    "contact": "مسؤول حماية البيانات لدى المطوّر — يُستكمل عند التشغيل الفعلي",
}


@app.get("/api/privacy/notice")
def privacy_notice():
    return PRIVACY_NOTICE


class ConsentIn(BaseModel):
    version: str = Field(pattern=r"^[0-9.]{1,10}$")
    accept: bool


@app.post("/api/portal/consent")
def portal_consent(k: ConsentIn, request: Request, u=Depends(need("portal"))):
    """0.5.0 — M5: الموافقة يسجّلها العميل بنفسه من تطبيقه (لا الموظف نيابةً عنه)، مع الإصدار والعنوان والوقت."""
    if not k.accept:
        raise HTTPException(400, "يلزم الإقرار بقراءة إشعار الخصوصية والموافقة عليه")
    if k.version != PRIVACY_NOTICE["version"]:
        raise HTTPException(409, "إصدار الإشعار تغيّر — أعد قراءته")
    c = db()
    c.execute("UPDATE customers SET consent_at=?, consent_version=?, consent_source=? WHERE id=?",
              (dt.datetime.now().isoformat(timespec="seconds"), k.version, f"تطبيق العميل · {A.client_ip(request)}", u["customer_id"]))
    audit(c, "موافقة على إشعار الخصوصية", f"عميل {u['customer_id']} · الإصدار {k.version}", u["name"] + " (عميل)")
    c.commit()
    return {"ok": True}


class PayIn(BaseModel):
    installment_id: int


@app.post("/api/portal/pay")
def portal_pay(p: PayIn, u=Depends(need("portal"))):
    """دفع تجريبي (Sandbox): يسجّل السداد ويصدر إيصالًا. بوابة الدفع الحقيقية تُربط لاحقًا."""
    c = db()
    i = c.execute("SELECT * FROM installments WHERE id=?", (p.installment_id,)).fetchone()
    if not i:
        raise HTTPException(404, "القسط غير موجود")
    owned(c, u, i["booking_id"])
    due = i["amount"] - i["paid_amount"]
    if due <= 1:
        raise HTTPException(409, "القسط مسدَّد")
    first_unpaid = c.execute("SELECT id FROM installments WHERE booking_id=? AND paid_amount<amount-1 ORDER BY seq LIMIT 1",
                             (i["booking_id"],)).fetchone()
    if first_unpaid["id"] != i["id"]:
        raise HTTPException(409, "يُسدَّد القسط الأقدم أولًا")
    if PROD:
        raise HTTPException(403, "الدفع المباشر التجريبي غير متاح في الإنتاج")
    from .modules import create_intent, simulate_gateway
    pid, amt = create_intent(c, i["id"])
    res = simulate_gateway(c, pid, amt)
    c.commit()
    return res


class ServiceIn(BaseModel):
    booking_id: int
    category: str = Field(pattern="^(سباكة|كهرباء|تكييف|ملاحظة تشطيب|أخرى)$")
    description: str = Field(min_length=5, max_length=500)


@app.post("/api/portal/service")
def portal_service(s: ServiceIn, u=Depends(need("portal"))):
    c = db()
    owned(c, u, s.booking_id)
    today = dt.date.today().isoformat()
    rid = c.execute("INSERT INTO service_requests(booking_id,category,description,status,created,updated) VALUES(?,?,?,?,?,?)",
                    (s.booking_id, s.category, s.description, "new", today, today)).lastrowid
    audit(c, "طلب صيانة جديد", f"#{rid} {s.category}", u["name"] + " (عميل)")
    c.commit()
    return {"ok": True, "id": rid}


class ResaleIn(BaseModel):
    booking_id: int
    ask_price: float = Field(gt=0, le=50_000_000)


@app.post("/api/portal/resale")
def portal_resale(r: ResaleIn, u=Depends(need("portal"))):
    c = db()
    b = owned(c, u, r.booking_id)
    if b["status"] != "confirmed":
        raise HTTPException(409, "إعادة البيع متاحة بعد تأكيد الشراء")
    if c.execute("SELECT 1 FROM resale WHERE booking_id=? AND status!='rejected'", (r.booking_id,)).fetchone():
        raise HTTPException(409, "يوجد طلب إعادة بيع قائم")
    paid = c.execute("SELECT SUM(paid_amount)/SUM(amount) FROM installments WHERE booking_id=?", (r.booking_id,)).fetchone()[0] or 0
    if paid < .3:
        raise HTTPException(409, "تُتاح إعادة البيع بعد سداد 30٪ من قيمة الوحدة")
    fee = round(r.ask_price * .02)
    rid = c.execute("INSERT INTO resale(booking_id,ask_price,fee,status,created) VALUES(?,?,?,?,?)",
                    (r.booking_id, r.ask_price, fee, "pending", dt.date.today().isoformat())).lastrowid
    audit(c, "طلب إعادة بيع", f"{b['code']} بسعر {r.ask_price:,.0f} ر.ع (رسوم نقل {fee:,.0f})", u["name"] + " (عميل)")
    c.commit()
    return {"ok": True, "id": rid, "fee": fee}


# ------------------------------------------------------------------ مكتب الخدمة (الموظفون)
@app.get("/api/service")
def service_list(_=Depends(need("service"))):
    c = db()
    return {
        "requests": [dict(r) for r in c.execute("""SELECT s.*, u.code unit, cu.name customer, p.name project FROM service_requests s
            JOIN bookings b ON b.id=s.booking_id JOIN units u ON u.id=b.unit_id JOIN customers cu ON cu.id=b.customer_id
            JOIN projects p ON p.id=u.project_id ORDER BY s.status='done', s.id DESC""")],
        "resale": [dict(r) for r in c.execute("""SELECT r.*, u.code unit, u.price list_price, cu.name customer FROM resale r
            JOIN bookings b ON b.id=r.booking_id JOIN units u ON u.id=b.unit_id JOIN customers cu ON cu.id=b.customer_id
            ORDER BY r.status!='pending', r.id DESC""")],
    }


class SvcStatusIn(BaseModel):
    status: str = Field(pattern="^(in_progress|done)$")
    note: str = Field(default="", max_length=300)


@app.post("/api/service/{rid}/status")
def service_status(rid: int, s: SvcStatusIn, _=Depends(act_as("service"))):
    c = db()
    if not c.execute("SELECT 1 FROM service_requests WHERE id=?", (rid,)).fetchone():
        raise HTTPException(404, "الطلب غير موجود")
    c.execute("UPDATE service_requests SET status=?, note=?, updated=? WHERE id=?", (s.status, s.note, dt.date.today().isoformat(), rid))
    audit(c, "تحديث طلب صيانة", f"#{rid} → {s.status}")
    c.commit()
    return {"ok": True}


class ResaleActIn(BaseModel):
    action: str = Field(pattern="^(listed|rejected)$")


@app.post("/api/resale/{rid}")
def resale_act(rid: int, r: ResaleActIn, _=Depends(act_as("decide"))):
    c = db()
    x = c.execute("SELECT * FROM resale WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not x:
        raise HTTPException(409, "الطلب غير معلق")
    c.execute("UPDATE resale SET status=? WHERE id=?", (r.action, rid))
    audit(c, "قرار إعادة بيع", f"#{rid} → {'نُشر في السوق الثانوي' if r.action == 'listed' else 'رُفض'}")
    c.commit()
    return {"ok": True}


# ------------------------------------------------------------------ الواجهة
NOCACHE = {"Cache-Control": "no-store"}
CSRF_EXEMPT = {"/api/auth/login", "/api/auth/logout", "/api/pay/webhook", "/api/auth/password/forgot", "/api/auth/password/reset", "/api/auth/email/request"}


@app.get("/")
def index(request: Request):
    u = A.session_user(request)
    if not u:
        return RedirectResponse("/login", 303)
    if u["role"] == "customer":
        return RedirectResponse("/app", 303)
    if u["role"] == "broker":
        return RedirectResponse("/broker", 303)
    return FileResponse(FRONT / "index.html", headers=NOCACHE)


@app.get("/login")
def login_page():
    return FileResponse(FRONT / "login.html", headers=NOCACHE)


@app.get("/app")
def customer_app(request: Request):
    u = A.session_user(request)
    if not u or u["role"] != "customer":
        return RedirectResponse("/login", 303)
    return FileResponse(FRONT / "client.html", headers=NOCACHE)


@app.get("/broker")
def broker_app(request: Request):
    u = A.session_user(request)
    if not u or u["role"] != "broker":
        return RedirectResponse("/login", 303)
    return FileResponse(FRONT / "broker.html", headers=NOCACHE)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # تحديد المطوّر (Tenant) من الكوكي — قيمة غير صالحة تُعامل كجلسة غير موجودة
    t = request.cookies.get(A.TENANT_COOKIE) or "jadwa"
    if not valid_tenant(t):
        t = "__none__"
    TENANT.set(t if t != "__none__" else "jadwa")
    if t == "__none__":
        request.scope["headers"] = [(k, v) for k, v in request.scope["headers"] if k != b"cookie"]
    from .common import close_all
    from .db import OPEN
    conns = []
    OPEN.set(conns)
    try:
        return await _inner(request, call_next)
    finally:
        close_all(conns)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
            cache.bump(TENANT.get())  # Unit 4: a write makes every cached dashboard of this developer stale at once


async def _inner(request: Request, call_next):
    limited = O.rate_limit(request)  # Unit 0: token bucket per client ip (login / webhook / all api)
    if limited is not None:
        return limited
    # حماية CSRF: أي طلب يغيّر البيانات يجب أن يأتي من نفس الأصل
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin") or request.headers.get("referer")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if origin and urlparse(origin).netloc != host:
            return JSONResponse({"detail": "طلب من مصدر غير موثوق"}, status_code=403)
        # 0.5.0 — M7: أي طلب مُعدِّل بجلسة كوكي يجب أن يحمل رمز CSRF المطابق (باستثناء الدخول، وإشعار البوابة الموقَّع، وواجهة المفاتيح)
        p = request.url.path
        if p.startswith("/api/") and p not in CSRF_EXEMPT and not p.startswith("/api/v1/") and request.cookies.get(A.COOKIE) and not A.csrf_ok(request):
            return JSONResponse({"detail": "رمز CSRF مفقود أو غير مطابق — أعد تسجيل الدخول"}, status_code=403)
        upload = request.url.path in ("/api/documents", "/api/plans")  # multipart uploads (Unit 6: plans)
        ctype = request.headers.get("content-type", "")
        ok_type = ctype.startswith("multipart/form-data") if upload else ctype.startswith("application/json")
        if not ok_type and request.url.path.startswith("/api/") and int(request.headers.get("content-length") or 0) > 0:
            return JSONResponse({"detail": "نوع المحتوى غير مدعوم"}, status_code=415)
        if int(request.headers.get("content-length") or 0) > (5_300_000 if upload else 64_000):
            return JSONResponse({"detail": "حجم الطلب كبير"}, status_code=413)
    r = await call_next(request)
    if "content-security-policy" not in r.headers:
        # 0.5.0 — M7: لا سكربتات مضمّنة؛ كل الشيفرة في ملفات /static والمعالجات بالتفويض (data-call)
        # Unit 3: no external hosts at all — fonts self-hosted; <style> elements only from our files; inline style="" attributes
        # remain allowed via style-src-attr (documented debt in docs/SECURITY_HEADERS.md), never 'unsafe-inline' on style-src itself
        r.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self'; style-src-elem 'self'; style-src-attr 'unsafe-inline'; "
                                                "font-src 'self'; img-src 'self' data:; connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
                                                "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
    r.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"  # سنتان؛ preload قرار مالك
    r.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), bluetooth=()"
    r.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    r.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        r.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/static/assets/"):
        r.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # Unit 3: hashed file names from Vite
    elif request.url.path.startswith("/static/"):
        r.headers["Cache-Control"] = "public, max-age=3600, must-revalidate"
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "same-origin"
    r.headers["X-Robots-Tag"] = "noindex, nofollow"
    return r


from .modules import create_commission
from .modules import router as modules_router  # noqa: E402
from .modules2 import router as modules2_router  # noqa: E402

app.include_router(modules_router)
app.include_router(modules2_router)
from .identity import router as identity_router  # noqa: E402
from .marketing import router as marketing_router  # noqa: E402
from .paperwork import router as paperwork_router  # noqa: E402
from .plans import router as plans_router  # noqa: E402
from .reports import router as reports_router  # noqa: E402

app.include_router(identity_router)
app.include_router(paperwork_router)
app.include_router(plans_router)
app.include_router(reports_router)
app.include_router(marketing_router)
app.mount("/static", StaticFiles(directory=FRONT), name="static")
app.add_middleware(O.ObservabilityMiddleware)  # الأبعد خارجيًا: معرّف الطلب وسجل الوصول وتحويل الأعطال إلى JSON 500
