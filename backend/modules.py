"""مبانيك — الوحدات الموسّعة (الجزء 1): الأرض والجدوى، التراخيص، الإنشاء، التحقق من الهوية، العقود والتوقيع،
الخصومات، الوسطاء، السوق الثانوي، المالية (فواتير، غرامات، فسخ، بوابة دفع، مطابقة بنكية، حساب الضمان، تصدير ERPNext)."""
import base64
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import engines_ext as X
from . import pii
from .auth import ROLES, check_pw, hash_pw, need, need_any, temp_password
from .common import act_as, audit, db, now_s, rows, today
from .db import setting, setting_f

router = APIRouter()
PLAN_LABEL = {"milestone": "مرتبطة بمراحل الإنجاز", "6040": "60/40", "murabaha": "تمويل مرابحة بنكي"}


def one(c, sql, args=(), msg="غير موجود", code=404):
    r = c.execute(sql, args).fetchone()
    if not r:
        raise HTTPException(code, msg)
    return r


def booking_full(c, bid):
    return one(c, """SELECT b.*, u.code, u.type, u.area, u.view, u.floor, u.use, u.project_id, p.name project, p.location,
                            p.handover, cu.name customer, cu.id_type, cu.id_number, cu.nationality, cu.kyc_status, cu.phone
                     FROM bookings b JOIN units u ON u.id=b.unit_id JOIN projects p ON p.id=u.project_id
                     JOIN customers cu ON cu.id=b.customer_id WHERE b.id=?""", (bid,), "الحجز غير موجود")


def portal_owned(c, u, bid):
    b = c.execute("SELECT * FROM bookings WHERE id=? AND customer_id=? AND status!='cancelled'", (bid, u["customer_id"])).fetchone()
    if not b:
        raise HTTPException(404, "الحجز غير موجود")
    return b


def paid_ratio(c, bid):
    r = c.execute("SELECT SUM(paid_amount), SUM(amount) FROM installments WHERE booking_id=?", (bid,)).fetchone()
    return (r[0] or 0) / r[1] if r[1] else 0


# ======================================================================= الأرض والجدوى
@router.get("/api/lands")
def lands(_=Depends(need("land"))):
    c = db()
    out = rows(c.execute("SELECT * FROM lands ORDER BY id"))
    for x in out:
        x["studies"] = rows(c.execute("SELECT id,name,results,created,by FROM feasibility WHERE land_id=? ORDER BY id DESC", (x["id"],)))
        for s in x["studies"]:
            s["results"] = json.loads(s["results"])
            s["results"].pop("cashflow", None)
    return out


class FeasIn(BaseModel):
    name: str = Field(default="سيناريو أساسي", max_length=60)
    sell_price_sqm: float = Field(gt=100, le=5000)
    build_cost_sqm: float = Field(gt=50, le=3000)
    efficiency: float = Field(default=.82, ge=.5, le=.95)
    soft_cost_pct: float = Field(default=.12, ge=0, le=.4)
    presale_pct: float = Field(default=.6, ge=0, le=1)
    finance_rate: float = Field(default=.065, ge=0, le=.25)
    months: int = Field(default=30, ge=6, le=72)


@router.post("/api/lands/{land_id}/feasibility")
def run_feasibility(land_id: int, f: FeasIn, u=Depends(act_as("land"))):
    c = db()
    land = dict(one(c, "SELECT * FROM lands WHERE id=?", (land_id,), "الأرض غير موجودة"))
    res = X.feasibility(land, f.model_dump())
    sid = c.execute("INSERT INTO feasibility(land_id,name,inputs,results,created,by) VALUES(?,?,?,?,?,?)",
                    (land_id, f.name, f.model_dump_json(), json.dumps(res, ensure_ascii=False), now_s(), u["name"])).lastrowid
    audit(c, "دراسة جدوى", f"{land['name']} · {f.name} · هامش {res['margin']}٪ · {res['verdict']}")
    c.commit()
    return {"id": sid, **res}


# ======================================================================= التراخيص والجهات الحكومية
PERMIT_STATUS = {"not_started": "لم يبدأ", "submitted": "مقدَّم", "in_review": "قيد المراجعة", "issued": "صادر", "rejected": "مرفوض", "expired": "منتهٍ"}


@router.get("/api/permits")
def permits(_=Depends(need_any("permits", "view"))):
    c = db()
    t = today()
    out = []
    for r in c.execute("SELECT pm.*, p.name project FROM permits pm JOIN projects p ON p.id=pm.project_id ORDER BY p.id, pm.id"):
        x = dict(r)
        x["status_label"] = PERMIT_STATUS.get(x["status"], x["status"])
        x["alert"] = None
        if x["expires"]:
            days = (dt.date.fromisoformat(x["expires"]) - t).days
            if days < 0:
                x["alert"] = f"منتهي منذ {-days} يومًا"
            elif days <= 60:
                x["alert"] = f"ينتهي خلال {days} يومًا — ابدأ التجديد"
        if x["status"] in ("submitted", "in_review") and x["applied"] and (t - dt.date.fromisoformat(x["applied"])).days > 30:
            x["alert"] = "معلق منذ أكثر من 30 يومًا — تابع مع الجهة"
        out.append(x)
    return out


class PermitIn(BaseModel):
    status: str = Field(pattern="^(submitted|in_review|issued|rejected)$")
    ref: str = Field(default="", max_length=40)
    expires: dt.date | None = None


@router.post("/api/permits/{pid}")
def permit_update(pid: int, p: PermitIn, _=Depends(act_as("permits"))):
    c = db()
    r = one(c, "SELECT * FROM permits WHERE id=?", (pid,))
    c.execute("UPDATE permits SET status=?, ref=COALESCE(NULLIF(?,''),ref), applied=COALESCE(applied,?), issued=?, expires=COALESCE(?,expires) WHERE id=?",
              (p.status, p.ref, today().isoformat(), today().isoformat() if p.status == "issued" else r["issued"],
               p.expires.isoformat() if p.expires else None, pid))
    audit(c, "تحديث ترخيص", f"{r['kind']} ← {PERMIT_STATUS[p.status]}")
    c.commit()
    return {"ok": True}


# ======================================================================= الإنشاء
@router.get("/api/construction/{project_id}")
def construction(project_id: int, _=Depends(need("construction"))):
    c = db()
    p = one(c, "SELECT * FROM projects WHERE id=?", (project_id,), "المشروع غير موجود")
    tasks = rows(c.execute("SELECT * FROM schedule_tasks WHERE project_id=? ORDER BY id", (project_id,)))
    sched = X.schedule_analysis(tasks, today())
    k = c.execute("SELECT cc.*, k.name contractor FROM contracts_c cc JOIN contractors k ON k.id=cc.contractor_id WHERE project_id=?",
                  (project_id,)).fetchone()
    cos = rows(c.execute("SELECT * FROM change_orders WHERE project_id=? ORDER BY no", (project_id,)))
    approved_co = sum(x["cost"] for x in cos if x["status"] == "approved")
    co_days = sum(x["days"] for x in cos if x["status"] == "approved")
    budget = rows(c.execute("SELECT category, amount FROM budgets WHERE project_id=?", (project_id,)))
    total_budget = sum(b["amount"] for b in budget)
    ipcs = rows(c.execute("SELECT * FROM ipcs WHERE project_id=? ORDER BY no", (project_id,)))
    certified = sum((i["approved_pct"] or 0) / 100 * i["stage_value"] for i in ipcs if i["status"] == "approved")
    retention = certified * (k["retention_pct"] if k else .1)
    committed = (k["value"] if k else 0) + approved_co
    contingency = next((b["amount"] for b in budget if "احتياطي" in b["category"]), 0)
    eac = committed + sum(x["cost"] for x in cos if x["status"] == "pending")
    reasons = sched["reasons"] + [
        f"قيمة العقد {k['value']:,.0f} + أوامر تغيير معتمدة {approved_co:,.0f} = التزام {committed:,.0f} ر.ع" if k else "لا يوجد عقد مقاول",
        f"استُهلك {approved_co / contingency * 100:.0f}٪ من احتياطي الطوارئ" if contingency else ""]
    penalty = 0
    if k and sched["forecast_delay_days"] > co_days:
        penalty = (sched["forecast_delay_days"] - co_days) * k["delay_penalty_per_day"]
        reasons.append(f"تأخير غير مبرر {sched['forecast_delay_days'] - co_days} يومًا بعد خصم تمديدات أوامر التغيير ({co_days} يومًا) "
                       f"← غرامة تأخير محتملة على المقاول {penalty:,.0f} ر.ع")
    return {"project": dict(p), "schedule": sched, "contract": dict(k) if k else None, "change_orders": cos,
            "budget": budget, "total_budget": total_budget, "committed": committed, "eac": eac,
            "certified": round(certified), "retention_held": round(retention), "delay_penalty": round(penalty),
            "extension_days": co_days, "site_reports": rows(c.execute("SELECT * FROM site_reports WHERE project_id=? ORDER BY day DESC LIMIT 10", (project_id,))),
            "ncrs": rows(c.execute("SELECT * FROM ncrs WHERE project_id=? ORDER BY status='closed', id DESC", (project_id,))),
            "reasons": [r for r in reasons if r]}


class COIn(BaseModel):
    project_id: int
    title: str = Field(min_length=3, max_length=120)
    reason: str = Field(min_length=3, max_length=120)
    cost: float = Field(ge=-5_000_000, le=5_000_000)
    days: int = Field(ge=0, le=365)


@router.post("/api/change-orders")
def co_create(o: COIn, _=Depends(act_as("construction"))):
    c = db()
    one(c, "SELECT 1 FROM projects WHERE id=?", (o.project_id,))
    no = (c.execute("SELECT MAX(no) FROM change_orders WHERE project_id=?", (o.project_id,)).fetchone()[0] or 0) + 1
    cid = c.execute("INSERT INTO change_orders(project_id,no,title,reason,cost,days,status,requested) VALUES(?,?,?,?,?,?,?,?)",
                    (o.project_id, no, o.title, o.reason, o.cost, o.days, "pending", today().isoformat())).lastrowid
    audit(c, "طلب أمر تغيير", f"#{no} {o.title} · {o.cost:,.0f} ر.ع · {o.days} يومًا")
    c.commit()
    return {"id": cid, "no": no}


class DecideIn(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")


@router.post("/api/change-orders/{cid}/decide")
def co_decide(cid: int, d: DecideIn, u=Depends(act_as("approve_ipc"))):
    c = db()
    co = one(c, "SELECT * FROM change_orders WHERE id=? AND status='pending'", (cid,), "الأمر غير معلق", 409)
    st = "approved" if d.action == "approve" else "rejected"
    c.execute("UPDATE change_orders SET status=?, decided=?, decided_by=? WHERE id=?", (st, today().isoformat(), u["name"], cid))
    if st == "approved" and co["days"]:
        last = c.execute("SELECT id, planned_end FROM schedule_tasks WHERE project_id=? ORDER BY id DESC LIMIT 1", (co["project_id"],)).fetchone()
        if last:
            c.execute("UPDATE schedule_tasks SET planned_end=? WHERE id=?",
                      ((dt.date.fromisoformat(last["planned_end"]) + dt.timedelta(days=co["days"])).isoformat(), last["id"]))
    audit(c, "قرار أمر تغيير", f"#{co['no']} {co['title']} ← {'معتمد' if st == 'approved' else 'مرفوض'}")
    c.commit()
    return {"ok": True}


class SiteIn(BaseModel):
    project_id: int
    workers: int = Field(ge=0, le=5000)
    weather: str = Field(max_length=30)
    work_done: str = Field(min_length=3, max_length=300)
    issues: str = Field(default="", max_length=300)
    photos: int = Field(default=0, ge=0, le=500)


@router.post("/api/site-reports")
def site_report(s: SiteIn, u=Depends(act_as("construction"))):
    c = db()
    one(c, "SELECT 1 FROM projects WHERE id=?", (s.project_id,))
    c.execute("INSERT INTO site_reports(project_id,day,workers,weather,work_done,issues,photos,by) VALUES(?,?,?,?,?,?,?,?)",
              (s.project_id, today().isoformat(), s.workers, s.weather, s.work_done, s.issues, s.photos, u["name"]))
    audit(c, "تقرير موقع يومي", f"مشروع {s.project_id} · {s.workers} عامل")
    c.commit()
    return {"ok": True}


class NcrIn(BaseModel):
    project_id: int
    title: str = Field(min_length=3, max_length=150)
    severity: str = Field(pattern="^(minor|major|critical)$")
    location: str = Field(default="", max_length=40)


@router.post("/api/ncrs")
def ncr_create(n: NcrIn, _=Depends(act_as("construction"))):
    c = db()
    one(c, "SELECT 1 FROM projects WHERE id=?", (n.project_id,))
    c.execute("INSERT INTO ncrs(project_id,title,severity,status,raised,location) VALUES(?,?,?,?,?,?)",
              (n.project_id, n.title, n.severity, "open", today().isoformat(), n.location))
    audit(c, "تقرير عدم مطابقة", f"{n.title} ({n.severity})")
    c.commit()
    return {"ok": True}


@router.post("/api/ncrs/{nid}/close")
def ncr_close(nid: int, _=Depends(act_as("construction"))):
    c = db()
    n = one(c, "SELECT * FROM ncrs WHERE id=? AND status='open'", (nid,), "التقرير مغلق", 409)
    c.execute("UPDATE ncrs SET status='closed', closed=? WHERE id=?", (today().isoformat(), nid))
    audit(c, "إغلاق عدم مطابقة", n["title"])
    c.commit()
    return {"ok": True}


# ======================================================================= التحقق من الهوية (KYC/AML)
@router.get("/api/kyc")
def kyc_queue(_=Depends(need("kyc"))):
    c = db()
    out = rows(c.execute("""SELECT cu.id, cu.name, cu.phone, cu.id_type, cu.id_number, cu.nationality, cu.id_expiry, cu.kyc_status,
                                   cu.kyc_risk, cu.kyc_note, cu.consent_at, b.id booking_id, u.code unit, b.status booking_status
                            FROM customers cu JOIN bookings b ON b.customer_id=cu.id JOIN units u ON u.id=b.unit_id
                            WHERE b.status='pending' OR cu.kyc_status IN ('review','rejected') ORDER BY cu.kyc_status='verified', cu.id DESC"""))
    for x in out:  # 0.5.0 — M5: القوائم تعرض الرقم مخفيًا؛ الرقم الكامل بطلب صريح مسجَّل
        x["id_number_masked"] = pii.mask(x.pop("id_number"))
    return out


@router.get("/api/customers/{cid}/kyc")
def kyc_detail(cid: int, u=Depends(act_as("kyc"))):
    """بيانات الهوية كاملة — كل اطلاع يُسجَّل في سجل التدقيق باسم المطّلع (PDPL: سجل الوصول)."""
    c = db()
    cu = dict(one(c, "SELECT id, name, phone, id_type, id_number, nationality, id_expiry, dob, pep, source_of_funds, email, kyc_status, kyc_risk, kyc_note, consent_at, consent_source FROM customers WHERE id=?", (cid,), "العميل غير موجود"))
    cu["id_number"], cu["dob"] = pii.dec(cu["id_number"]), pii.dec(cu["dob"])
    audit(c, "اطلاع على بيانات هوية", f"عميل {cid}")
    c.commit()
    return cu


class KycIn(BaseModel):
    id_type: str = Field(pattern="^(بطاقة مدنية|جواز سفر|بطاقة مقيم)$")
    id_number: str = Field(min_length=5, max_length=20, pattern=r"^[A-Za-z0-9]+$")
    nationality: str = Field(min_length=2, max_length=30)
    id_expiry: dt.date
    dob: dt.date | None = None
    pep: bool = False
    source_of_funds: str = Field(min_length=2, max_length=60)
    email: str | None = Field(default=None, max_length=80, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    consent_signed: bool = False  # 0.5.0 — M5: وقّع العميل إقرار الخصوصية ورقيًا بحضور الموظف (وإلا تُؤخذ الموافقة من تطبيقه)


@router.post("/api/customers/{cid}/kyc")
def kyc_submit(cid: int, k: KycIn, _=Depends(act_as("kyc"))):
    c = db()
    cu = dict(one(c, "SELECT * FROM customers WHERE id=?", (cid,), "العميل غير موجود"))
    cu.update({"id_type": k.id_type, "id_number": k.id_number, "nationality": k.nationality, "id_expiry": k.id_expiry.isoformat(),
               "pep": int(k.pep), "source_of_funds": k.source_of_funds})
    res = X.kyc_screen(c, cu, today())
    c.execute("""UPDATE customers SET id_type=?, id_number=?, nationality=?, id_expiry=?, dob=?, pep=?, source_of_funds=?, email=?,
                 kyc_status=?, kyc_risk=?, kyc_note=?, kyc_at=? WHERE id=?""",
              (k.id_type, pii.enc(k.id_number), k.nationality, k.id_expiry.isoformat(), pii.enc(k.dob.isoformat()) if k.dob else None, int(k.pep),
               k.source_of_funds, k.email, res["status"], res["risk"], "؛ ".join(res["flags"]), now_s(), cid))
    if k.consent_signed:  # الموافقة لا تُفترض؛ إما إقرار ورقي يشهده الموظف أو موافقة من تطبيق العميل
        c.execute("UPDATE customers SET consent_at=COALESCE(consent_at,?), consent_version=COALESCE(consent_version,'1.0'), consent_source=COALESCE(consent_source,?) WHERE id=?",
                  (now_s(), "إقرار ورقي بحضور " + _["name"], cid))
    audit(c, "تحقق من الهوية", f"عميل {cid} ← {res['status']} · مخاطر {res['risk']}")
    c.commit()
    return res


class KycDecideIn(BaseModel):
    action: str = Field(pattern="^(verified|rejected)$")
    note: str = Field(min_length=5, max_length=200)


@router.post("/api/customers/{cid}/kyc/decide")
def kyc_decide(cid: int, d: KycDecideIn, _=Depends(act_as("admin"))):
    """حالات المخاطر المرتفعة (تطابق قوائم/شخص معرّض سياسيًا) لا يعتمدها إلا المدير، مع تسجيل المبرر."""
    c = db()
    one(c, "SELECT 1 FROM customers WHERE id=? AND kyc_status='review'", (cid,), "لا توجد حالة مراجعة", 409)
    c.execute("UPDATE customers SET kyc_status=?, kyc_note=kyc_note||' | قرار الإدارة: '||? WHERE id=?", (d.action, d.note, cid))
    audit(c, "قرار عناية معززة", f"عميل {cid} ← {d.action}: {d.note}")
    c.commit()
    return {"ok": True}


# ======================================================================= عقد البيع والتوقيع الإلكتروني
def _contract_settings(c, b):
    vr = X.vat_rate(c, b["use"] or "residential")
    return {"developer": json.loads(setting(c, "tenant_name", '"جدوى"')) if setting(c, "tenant_name") else "المطوّر",
            "escrow_ref": f"ESC-{b['project_id']:03d}", "plan_label": PLAN_LABEL.get(b["plan"], b["plan"]),
            "vat_note": "معفاة/بنسبة صفرية للبيع السكني الأول (حسب الإعداد — تُؤكد مع المستشار الضريبي)" if vr == 0 else f"{vr*100:.0f}٪ تضاف على كل دفعة",
            "grace": setting_f(c, "late_grace_days", 15), "penalty": setting_f(c, "late_penalty_monthly", .01),
            "cancel": setting_f(c, "cancel_deduction_pct", .1), "warranty": setting_f(c, "warranty_months", 12),
            "structural": setting_f(c, "structural_years", 10), "resale_min": setting_f(c, "resale_min_paid", .3),
            "resale_fee": setting_f(c, "resale_fee_pct", .02)}


@router.post("/api/bookings/{bid}/contract")
def contract_generate(bid: int, _=Depends(act_as("book"))):
    c = db()
    b = dict(booking_full(c, bid))
    if b["status"] == "cancelled":
        raise HTTPException(409, "الحجز ملغى")
    if b["kyc_status"] != "verified":
        raise HTTPException(409, "يلزم استكمال التحقق من هوية العميل قبل إصدار العقد")
    if not c.execute("SELECT consent_at FROM customers WHERE id=?", (b["customer_id"],)).fetchone()["consent_at"]:
        raise HTTPException(409, "لا يُصدر العقد قبل تسجيل موافقة العميل على إشعار الخصوصية (من تطبيقه أو إقرارًا ورقيًا مُثبتًا في التحقق)")  # 0.5.0 — M5
    ex = c.execute("SELECT * FROM sale_contracts WHERE booking_id=?", (bid,)).fetchone()
    if ex and ex["customer_signed_at"]:
        raise HTTPException(409, "العقد موقَّع ولا يمكن إعادة إصداره")
    b["id_number"] = pii.dec(b.get("id_number"))  # 0.5.0 — M5
    s = _contract_settings(c, b)
    s["number"], s["date"] = f"SPA-{bid:05d}", today().isoformat()
    sched = rows(c.execute("SELECT label, amount, due_date FROM installments WHERE booking_id=? ORDER BY seq", (bid,)))
    body = X.contract_text(b, sched, s)
    h = hashlib.sha256(body.encode()).hexdigest()
    c.execute("DELETE FROM sale_contracts WHERE booking_id=?", (bid,))
    c.execute("INSERT INTO sale_contracts(booking_id,number,body,sha256,status,created) VALUES(?,?,?,?,?,?)",
              (bid, s["number"], body, h, "awaiting_signature", now_s()))
    audit(c, "إصدار عقد بيع", f"{s['number']} · بصمة {h[:12]}")
    c.commit()
    return {"number": s["number"], "sha256": h, "body": body}


def _contract_view(r):
    x = dict(r)
    x["integrity_ok"] = hashlib.sha256(x["body"].encode()).hexdigest() == x["sha256"] if x["customer_sig"] != "migrated" else True
    return x


@router.get("/api/bookings/{bid}/contract")
def contract_get(bid: int, _=Depends(need("book"))):
    c = db()
    return _contract_view(one(c, "SELECT * FROM sale_contracts WHERE booking_id=?", (bid,), "لا يوجد عقد"))


class SignIn(BaseModel):
    typed_name: str = Field(min_length=3, max_length=80)
    accept: bool
    password: str | None = Field(default=None, max_length=200)


def _sign(c, bid, s: SignIn, request: Request, method: str, actor: str):
    k = one(c, "SELECT * FROM sale_contracts WHERE booking_id=?", (bid,), "لا يوجد عقد")
    if k["customer_signed_at"]:
        raise HTTPException(409, "العقد موقَّع مسبقًا")
    if not s.accept:
        raise HTTPException(400, "يلزم الإقرار بقراءة العقد والموافقة عليه")
    b = booking_full(c, bid)
    if X._norm(s.typed_name) != X._norm(b["customer"]):
        raise HTTPException(400, "الاسم المكتوب لا يطابق اسم المشتري في العقد")
    if hashlib.sha256(k["body"].encode()).hexdigest() != k["sha256"]:
        raise HTTPException(409, "تعذّر التحقق من سلامة نص العقد")
    ip = request.client.host if request.client else "?"
    sig = hashlib.sha256(f"{k['sha256']}|{b['customer']}|{now_s()}|{ip}|{method}".encode()).hexdigest()
    c.execute("UPDATE sale_contracts SET customer_signed_at=?, customer_sig=?, status='customer_signed' WHERE booking_id=?", (now_s(), sig, bid))
    audit(c, "توقيع إلكتروني للعقد", f"{k['number']} · {method} · بصمة النص {k['sha256'][:12]} · توقيع {sig[:12]}", actor)
    c.commit()
    return {"ok": True, "signature": sig}


@router.post("/api/bookings/{bid}/contract/sign-inperson")
def contract_sign_inperson(bid: int, s: SignIn, request: Request, u=Depends(act_as("book"))):
    c = db()
    return _sign(c, bid, s, request, f"حضوري بحضور {u['name']}", f"{u['name']} (شاهد)")


@router.get("/api/portal/contract/{bid}")
def portal_contract(bid: int, u=Depends(need("portal"))):
    c = db()
    portal_owned(c, u, bid)
    return _contract_view(one(c, "SELECT * FROM sale_contracts WHERE booking_id=?", (bid,), "لا يوجد عقد"))


@router.post("/api/portal/contract/{bid}/sign")
def portal_sign(bid: int, s: SignIn, request: Request, u=Depends(need("portal"))):
    """التوقيع عن بعد: يتطلب إعادة إدخال كلمة المرور (مصادقة قوية لحظة التوقيع) + كتابة الاسم + الإقرار."""
    from .auth import conn
    c = db()
    portal_owned(c, u, bid)
    row = conn().execute("SELECT pw FROM users WHERE id=?", (u["id"],)).fetchone()
    if not s.password or not check_pw(s.password, row["pw"]):
        raise HTTPException(401, "يلزم تأكيد كلمة المرور للتوقيع")
    return _sign(c, bid, s, request, "عن بعد عبر تطبيق العميل", f"{u['name']} (عميل)")


# ======================================================================= الخصومات بمستويات اعتماد
class DiscIn(BaseModel):
    pct: float = Field(gt=0, le=.25)
    reason: str = Field(min_length=5, max_length=200)


def _apply_discount(c, bid, pct):
    b = c.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
    cut = b["price"] * pct
    unpaid = c.execute("SELECT id, amount-paid_amount due FROM installments WHERE booking_id=? AND paid_amount<amount ORDER BY seq DESC", (bid,)).fetchall()
    left = cut
    for i in unpaid:  # يُخصم من آخر الأقساط أولًا
        take = min(left, i["due"])
        c.execute("UPDATE installments SET amount=amount-? WHERE id=?", (round(take), i["id"]))
        left -= take
        if left <= 0:
            break
    c.execute("UPDATE bookings SET price=price-?, list_price=COALESCE(list_price,price) WHERE id=?", (round(cut - left), bid))
    return round(cut - left)


@router.post("/api/bookings/{bid}/discount")
def discount(bid: int, d: DiscIn, u=Depends(act_as("book"))):
    c = db()
    one(c, "SELECT * FROM bookings WHERE id=? AND status!='cancelled'", (bid,))
    k = c.execute("SELECT customer_signed_at FROM sale_contracts WHERE booking_id=?", (bid,)).fetchone()
    if k and k["customer_signed_at"]:
        raise HTTPException(409, "لا يُعدّل السعر بعد توقيع العقد — يلزم ملحق عقد")
    limit = 1.0 if u["role"] == "admin" else setting_f(c, f"discount_limit:{u['role']}", 0)
    if d.pct <= limit:
        amt = _apply_discount(c, bid, d.pct)
        c.execute("INSERT INTO discount_requests(booking_id,pct,reason,status,requested_by,decided_by,created) VALUES(?,?,?,?,?,?,?)",
                  (bid, d.pct, d.reason, "approved", u["name"], u["name"] + " (ضمن صلاحيته)", now_s()))
        audit(c, "خصم ضمن الصلاحية", f"حجز {bid} · {d.pct*100:.1f}٪ = {amt:,.0f} ر.ع · {d.reason}")
        c.commit()
        return {"status": "approved", "amount": amt}
    c.execute("INSERT INTO discount_requests(booking_id,pct,reason,status,requested_by,created) VALUES(?,?,?,?,?,?)",
              (bid, d.pct, d.reason, "pending", u["name"], now_s()))
    audit(c, "طلب خصم يتجاوز الصلاحية", f"حجز {bid} · {d.pct*100:.1f}٪ (حد الصلاحية {limit*100:.0f}٪)")
    c.commit()
    return {"status": "pending", "limit": limit}


@router.get("/api/discounts")
def discounts(_=Depends(need_any("decide", "book"))):
    c = db()
    return rows(c.execute("""SELECT d.*, u.code unit, b.price FROM discount_requests d JOIN bookings b ON b.id=d.booking_id
                            JOIN units u ON u.id=b.unit_id ORDER BY d.status!='pending', d.id DESC LIMIT 50"""))


@router.post("/api/discounts/{did}/decide")
def discount_decide(did: int, d: DecideIn, u=Depends(act_as("admin"))):
    c = db()
    r = one(c, "SELECT * FROM discount_requests WHERE id=? AND status='pending'", (did,), "الطلب غير معلق", 409)
    amt = _apply_discount(c, r["booking_id"], r["pct"]) if d.action == "approve" else 0
    c.execute("UPDATE discount_requests SET status=?, decided_by=? WHERE id=?", ("approved" if amt else "rejected", u["name"], did))
    audit(c, "قرار خصم", f"طلب {did} ← {'معتمد ' + format(amt, ',.0f') + ' ر.ع' if amt else 'مرفوض'}")
    c.commit()
    return {"ok": True, "amount": amt}


# ======================================================================= الوسطاء والعمولات
@router.get("/api/brokers")
def brokers(_=Depends(need("brokers"))):
    c = db()
    out = []
    for b in c.execute("SELECT * FROM brokers ORDER BY id"):
        x = dict(b)
        s = c.execute("""SELECT COUNT(*) n, COALESCE(SUM(amount),0) total, COALESCE(SUM(CASE WHEN status='due' THEN amount END),0) due,
                                COALESCE(SUM(CASE WHEN status='paid' THEN amount END),0) paid FROM commissions WHERE broker_id=?""", (b["id"],)).fetchone()
        x.update(dict(s))
        x["leads"] = c.execute("SELECT COUNT(*) FROM leads WHERE broker_id=?", (b["id"],)).fetchone()[0]
        x["commissions"] = rows(c.execute("""SELECT cm.*, u.code unit, b.price FROM commissions cm JOIN bookings b ON b.id=cm.booking_id
                                            JOIN units u ON u.id=b.unit_id WHERE cm.broker_id=? ORDER BY cm.id DESC""", (b["id"],)))
        out.append(x)
    return out


class BrokerIn(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    license_no: str = Field(min_length=3, max_length=30)
    phone: str = Field(min_length=6, max_length=20, pattern=r"^[0-9+ ()-]+$")
    rate: float = Field(ge=0, le=.05)


@router.post("/api/brokers")
def broker_add(b: BrokerIn, _=Depends(act_as("admin"))):
    c = db()
    bid = c.execute("INSERT INTO brokers(name,license_no,phone,rate) VALUES(?,?,?,?)", (b.name, b.license_no, b.phone, b.rate)).lastrowid
    audit(c, "تسجيل وسيط", f"{b.name} · ترخيص {b.license_no}")
    c.commit()
    return {"id": bid}


@router.post("/api/commissions/{cid}/pay")
def commission_pay(cid: int, _=Depends(act_as("finance"))):
    c = db()
    cm = one(c, "SELECT * FROM commissions WHERE id=? AND status='due'", (cid,), "العمولة غير مستحقة", 409)
    if paid_ratio(c, cm["booking_id"]) < .2:
        raise HTTPException(409, "تُصرف العمولة بعد تحصيل 20٪ من ثمن الوحدة")
    c.execute("UPDATE commissions SET status='paid', paid_at=? WHERE id=?", (today().isoformat(), cid))
    audit(c, "صرف عمولة وسيط", f"عمولة {cid} · {cm['amount']:,.0f} ر.ع")
    c.commit()
    return {"ok": True}


def create_commission(c, booking_id):
    b = c.execute("SELECT broker_id, price FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if b and b["broker_id"]:
        br = c.execute("SELECT rate FROM brokers WHERE id=?", (b["broker_id"],)).fetchone()
        c.execute("INSERT OR IGNORE INTO commissions(broker_id,booking_id,amount,status) VALUES(?,?,?,?)",
                  (b["broker_id"], booking_id, round(b["price"] * (br["rate"] if br else .02)), "due"))


# ---- بوابة الوسيط
@router.get("/api/broker/portal")
def broker_portal(u=Depends(need("broker_portal"))):
    c = db()
    bid = u["broker_id"]
    br = one(c, "SELECT * FROM brokers WHERE id=?", (bid,))
    inv = rows(c.execute("""SELECT p.name project, u.type, u.view, COUNT(*) available, MIN(u.price) from_price
                           FROM units u JOIN projects p ON p.id=u.project_id WHERE u.status='a' AND u.retained=0
                           GROUP BY p.id, u.type, u.view ORDER BY p.id"""))
    return {"broker": {"name": br["name"], "license_no": br["license_no"], "rate": br["rate"]},
            "leads": rows(c.execute("SELECT id, name, interest, stage, created FROM leads WHERE broker_id=? ORDER BY id DESC", (bid,))),
            "commissions": rows(c.execute("""SELECT cm.amount, cm.status, cm.paid_at, u.code unit FROM commissions cm JOIN bookings b ON b.id=cm.booking_id
                                            JOIN units u ON u.id=b.unit_id WHERE cm.broker_id=?""", (bid,))),
            "inventory": inv}


@router.get("/api/broker/projects")
def broker_projects(_=Depends(need("broker_portal"))):
    return rows(db().execute("SELECT id, name FROM projects WHERE completed=0 OR completed IS NULL ORDER BY id"))


class BLeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=6, max_length=20, pattern=r"^[0-9+ ()-]+$")
    project_id: int
    interest: str = Field(default="", max_length=80)
    budget: float = Field(default=0, ge=0, le=10_000_000)


def _phone(p):
    return "".join(ch for ch in p if ch.isdigit())[-8:]


@router.post("/api/broker/leads")
def broker_lead(l: BLeadIn, u=Depends(need("broker_portal"))):
    """حماية ملكية العميل: إذا كان رقم الهاتف مسجلًا مسبقًا (من أي قناة) يُرفض التسجيل لمنع تنازع العمولات."""
    c = db()
    one(c, "SELECT 1 FROM projects WHERE id=?", (l.project_id,), "المشروع غير موجود")
    for r in c.execute("SELECT phone FROM leads"):
        if _phone(r["phone"]) == _phone(l.phone):
            raise HTTPException(409, "العميل مسجل مسبقًا لدى المطوّر — لا تُستحق عمولة على تسجيل مكرر")
    lid = c.execute("""INSERT INTO leads(name,phone,interest,project_id,channel,stage,interactions,budget,created,last_contact,score,broker_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,0,?)""", (l.name, l.phone, l.interest, l.project_id, "وسيط", 0, 1, l.budget,
                                                         today().isoformat(), today().isoformat(), u["broker_id"])).lastrowid
    audit(c, "تسجيل عميل من وسيط", f"lead {lid}", f"{u['name']} (وسيط)")
    c.commit()
    return {"id": lid}


# ======================================================================= السوق الثانوي
@router.get("/api/market")
def market(_=Depends(need_any("market", "decide"))):
    c = db()
    out = []
    for r in c.execute("""SELECT r.*, u.code unit, u.type, u.area, u.view, u.price list_price, p.name project, cu.name seller
                         FROM resale r JOIN bookings b ON b.id=r.booking_id JOIN units u ON u.id=b.unit_id
                         JOIN projects p ON p.id=u.project_id JOIN customers cu ON cu.id=b.customer_id
                         WHERE r.status IN ('listed','sold') ORDER BY r.status, r.id DESC"""):
        x = dict(r)
        x["offers"] = rows(c.execute("SELECT * FROM resale_offers WHERE resale_id=? ORDER BY price DESC", (r["id"],)))
        out.append(x)
    return out


class OfferIn(BaseModel):
    buyer_name: str = Field(min_length=3, max_length=80)
    buyer_phone: str = Field(min_length=6, max_length=20, pattern=r"^[0-9+ ()-]+$")
    price: float = Field(gt=0, le=50_000_000)


@router.post("/api/market/{rid}/offers")
def market_offer(rid: int, o: OfferIn, _=Depends(act_as("market"))):
    c = db()
    one(c, "SELECT 1 FROM resale WHERE id=? AND status='listed'", (rid,), "الوحدة غير معروضة", 409)
    oid = c.execute("INSERT INTO resale_offers(resale_id,buyer_name,buyer_phone,price,status,created) VALUES(?,?,?,?,?,?)",
                    (rid, o.buyer_name, o.buyer_phone, o.price, "open", now_s())).lastrowid
    audit(c, "عرض شراء في السوق الثانوي", f"إعلان {rid} · {o.price:,.0f} ر.ع")
    c.commit()
    return {"id": oid}


@router.post("/api/market/offers/{oid}/accept")
def market_accept(oid: int, _=Depends(act_as("decide"))):
    """إتمام التنازل: ينتقل العقد والأقساط المتبقية للمشتري الجديد، وتُصدر فاتورة رسوم التنازل للبائع."""
    c = db()
    o = one(c, "SELECT * FROM resale_offers WHERE id=? AND status='open'", (oid,), "العرض غير متاح", 409)
    r = one(c, "SELECT * FROM resale WHERE id=? AND status='listed'", (o["resale_id"],), "الإعلان غير متاح", 409)
    b = c.execute("SELECT * FROM bookings WHERE id=?", (r["booking_id"],)).fetchone()
    old = c.execute("SELECT name FROM customers WHERE id=?", (b["customer_id"],)).fetchone()["name"]
    new_c = c.execute("INSERT INTO customers(name,phone,created,kyc_status) VALUES(?,?,?,?)",
                      (o["buyer_name"], o["buyer_phone"], today().isoformat(), "pending")).lastrowid
    # 0.5.0 — M8: تسوية مالية صريحة بين البائع والمشتري، والحجز يُعلَّم «منقول بانتظار التحقق» حتى يُوثَّق المشتري ويُوقَّع ملحق التنازل
    sp = c.execute("SELECT COALESCE(SUM(paid_amount),0) paid, COALESCE(SUM(amount-paid_amount),0) unpaid FROM installments WHERE booking_id=?", (b["id"],)).fetchone()
    equity = round(o["price"] - sp["unpaid"])  # ما يدفعه المشتري للبائع: سعر التنازل − ما يتحمله من أقساط متبقية للمطوّر
    sid = c.execute("""INSERT INTO resale_settlements(resale_id,booking_id,seller_customer_id,buyer_customer_id,price,seller_paid,unpaid_installments,
                      equity_due_to_seller,fee,status,created) VALUES(?,?,?,?,?,?,?,?,?,'open',?)""",
                    (r["id"], b["id"], b["customer_id"], new_c, o["price"], sp["paid"], sp["unpaid"], equity, r["fee"], now_s())).lastrowid
    c.execute("UPDATE bookings SET customer_id=? WHERE id=?", (new_c, b["id"]))
    c.execute("UPDATE resale SET status='sold' WHERE id=?", (r["id"],))
    c.execute("UPDATE resale_offers SET status=CASE WHEN id=? THEN 'accepted' ELSE 'closed' END WHERE resale_id=?", (oid, r["id"]))
    c.execute("UPDATE sale_contracts SET status='assigned_pending_kyc' WHERE booking_id=?", (b["id"],))
    issue_invoice(c, "resale_fee", "resale", r["id"], old, r["fee"], setting_f(c, "vat_standard", .05),
                  f"رسوم تنازل عن عقد الوحدة (حجز {b['id']})", customer_id=b["customer_id"])
    audit(c, "إتمام تنازل (سوق ثانوي)", f"حجز {b['id']} من {old} إلى {o['buyer_name']} بسعر {o['price']:,.0f} · رسوم {r['fee']:,.0f} · "
                                         f"تسوية #{sid}: للبائع {equity:,.0f} ر.ع ويتحمل المشتري {sp['unpaid']:,.0f} ر.ع أقساطًا متبقية")
    c.commit()
    return {"ok": True, "new_customer_id": new_c, "settlement_id": sid, "equity_due_to_seller": equity, "unpaid_assumed_by_buyer": sp["unpaid"],
            "next_steps": ["التحقق من هوية المشتري (KYC) — لا تسليم ولا عقد قبله", "توقيع ملحق التنازل", f"تحصيل {equity:,.0f} ر.ع من المشتري للبائع وتسجيل التسوية",
                           "إنشاء حساب دخول للمشتري عبر /api/customers/{id}/account"]}


@router.get("/api/resale-settlements")
def resale_settlements(_=Depends(need_any("finance", "market"))):
    c = db()
    return rows(c.execute("""SELECT s.*, u.code unit, sc.name seller, bc.name buyer, bc.kyc_status buyer_kyc FROM resale_settlements s
                            JOIN bookings b ON b.id=s.booking_id JOIN units u ON u.id=b.unit_id
                            JOIN customers sc ON sc.id=s.seller_customer_id JOIN customers bc ON bc.id=s.buyer_customer_id ORDER BY s.status, s.id DESC"""))


class SettleIn(BaseModel):
    reference: str = Field(min_length=3, max_length=60)


@router.post("/api/resale-settlements/{sid}/settle")
def resale_settle(sid: int, s: SettleIn, u=Depends(act_as("finance"))):
    c = db()
    st = one(c, "SELECT * FROM resale_settlements WHERE id=? AND status='open'", (sid,), "التسوية غير مفتوحة", 409)
    c.execute("UPDATE resale_settlements SET status='settled', settled_at=?, reference=?, settled_by=? WHERE id=?", (now_s(), s.reference, u["name"], sid))
    audit(c, "تسوية تنازل", f"#{sid} · {st['equity_due_to_seller']:,.0f} ر.ع للبائع · مرجع {s.reference}")
    c.commit()
    return {"ok": True}


class AccountIn(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern=r"^[a-z][a-z0-9._-]+$")


@router.post("/api/customers/{cid}/account")
def customer_account(cid: int, a: AccountIn, _=Depends(act_as("users"))):
    """0.5.0 — M8: إنشاء حساب دخول لعميل قائم (مثل مشترٍ في السوق الثانوي) بكلمة مرور مؤقتة تُعرض مرة واحدة."""
    c = db()
    cu = one(c, "SELECT * FROM customers WHERE id=?", (cid,), "العميل غير موجود")
    if c.execute("SELECT 1 FROM users WHERE username=? OR customer_id=?", (a.username, cid)).fetchone():
        raise HTTPException(409, "اسم المستخدم مستخدم أو للعميل حساب قائم")
    temp = temp_password()
    c.execute("INSERT INTO users(username,name,role,pw,customer_id,must_change) VALUES(?,?,?,?,?,1)", (a.username, cu["name"], "customer", hash_pw(temp), cid))
    audit(c, "إنشاء حساب عميل", f"{a.username} للعميل {cid} ({ROLES['customer']})")
    c.commit()
    return {"username": a.username, "temporary_password": temp}


# ======================================================================= المالية: الفواتير
def issue_invoice(c, kind, ref_type, ref_id, customer, net, rate, note="", customer_id=None):
    """تصدر فاتورة. `customer_id` هو مفتاح الربط ببوابة العميل (0.4.1 — M1)؛ الاسم للعرض فقط ولا يُستخدم للمطابقة."""
    seq = (c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] or 0) + 1
    number = f"INV-{today():%Y}-{seq:06d}"
    vat = round(net * rate, 3)
    c.execute("INSERT INTO invoices(number,kind,ref_type,ref_id,customer,net,vat_rate,vat,total,issued,note,customer_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              (number, kind, ref_type, ref_id, customer, round(net, 3), rate, vat, round(net + vat, 3), now_s(), note, customer_id))
    return number


@router.get("/api/invoices")
def invoices(_=Depends(need("invoices"))):
    c = db()
    inv = rows(c.execute("SELECT * FROM invoices ORDER BY id DESC LIMIT 200"))
    s = c.execute("SELECT COUNT(*) n, COALESCE(SUM(net),0) net, COALESCE(SUM(vat),0) vat FROM invoices").fetchone()
    return {"invoices": inv, "summary": dict(s),
            "note": "معالجة ضريبة القيمة المضافة للبيع السكني والتجاري قابلة للضبط من الإعدادات، ويجب تأكيدها مع مستشار ضريبي معتمد."}


# ======================================================================= المالية: الغرامات والفسخ
CHARITY_NOTE = ("شرط التبرع: مبلغ التأخير يلتزم به المشتري تبرعًا لجهة خيرية تعتمدها هيئة الرقابة الشرعية، ويُحفظ في حساب أمانة منفصل، "
                "ولا يُقيَّد إيرادًا للمطوّر ولا يُستعمل في تغطية مصروفاته — ويُفصح عنه في القوائم المالية.")


def charity_accrue(c, inst, paid_now: float, customer_id: int, today_d) -> float:
    """0.5.0 — M4: عند سداد قسط متأخر يُحتسب مبلغ تبرع التأخير على ما سُدِّد متأخرًا ويُقيَّد في دفتر التبرعات (لا إيرادًا)."""
    if setting(c, "late_penalty_treatment", "charity") != "charity" or inst["penalty_waived"]:
        return 0
    rate, grace = setting_f(c, "late_penalty_monthly", .01), int(setting_f(c, "late_grace_days", 15))
    late = (today_d - dt.date.fromisoformat(inst["due_date"])).days
    if late <= grace or paid_now <= 1:
        return 0
    amt = round(paid_now * rate * (late - grace) / 30, 1)
    if amt <= 0:
        return 0
    c.execute("""INSERT INTO charity_dues(installment_id,customer_id,amount,rate,late_days,computed_at,status) VALUES(?,?,?,?,?,?,'due')
                 ON CONFLICT(installment_id) DO UPDATE SET amount=charity_dues.amount+excluded.amount, late_days=excluded.late_days, computed_at=excluded.computed_at""",
              (inst["id"], customer_id, amt, rate, late, now_s()))
    return amt


@router.get("/api/penalties")
def penalties(_=Depends(need("finance"))):
    c = db()
    rate, grace = setting_f(c, "late_penalty_monthly", .01), int(setting_f(c, "late_grace_days", 15))
    out, total = [], 0
    for i in c.execute("""SELECT i.*, u.code unit, cu.name customer FROM installments i JOIN bookings b ON b.id=i.booking_id
                         JOIN units u ON u.id=b.unit_id JOIN customers cu ON cu.id=b.customer_id
                         WHERE b.status='confirmed' AND i.paid_amount<i.amount-1 AND i.due_date<?""", (today().isoformat(),)):
        p = X.penalty_for(dict(i), today(), rate, grace)
        if p["late_days"] > 0:
            out.append({"installment_id": i["id"], "unit": i["unit"], "customer": i["customer"], "label": i["label"],
                        "unpaid": round(i["amount"] - i["paid_amount"]), "late_days": p["late_days"], "penalty": p["amount"], "waived": p["waived"]})
            total += p["amount"]
    out.sort(key=lambda x: -x["late_days"])
    ch = c.execute("""SELECT COALESCE(SUM(CASE WHEN status='due' THEN amount END),0) due, COALESCE(SUM(CASE WHEN status='collected' THEN amount END),0) collected,
                              COALESCE(SUM(CASE WHEN status='disbursed' THEN amount END),0) disbursed FROM charity_dues""").fetchone()
    return {"rate": rate, "grace_days": grace, "total": round(total), "items": out,
            "treatment": setting(c, "late_penalty_treatment", "charity"), "treatment_label": "شرط التبرع — لجهة خيرية، ليس إيرادًا",
            "note": CHARITY_NOTE, "charity": dict(ch)}


@router.get("/api/charity")
def charity_list(_=Depends(need("finance"))):
    c = db()
    return {"note": CHARITY_NOTE, "items": rows(c.execute("""SELECT d.*, cu.name customer, i.label, u.code unit FROM charity_dues d JOIN installments i ON i.id=d.installment_id
                                                            JOIN bookings b ON b.id=i.booking_id JOIN units u ON u.id=b.unit_id JOIN customers cu ON cu.id=d.customer_id
                                                            ORDER BY d.status, d.id DESC"""))}


class CharityRef(BaseModel):
    reference: str = Field(min_length=3, max_length=60)
    beneficiary: str = Field(default="", max_length=80)


@router.post("/api/charity/{did}/collect")
def charity_collect(did: int, r: CharityRef, _=Depends(act_as("finance"))):
    c = db()
    d = one(c, "SELECT * FROM charity_dues WHERE id=? AND status='due'", (did,), "المبلغ ليس مستحقًا", 409)
    c.execute("UPDATE charity_dues SET status='collected', collected_at=?, collected_ref=? WHERE id=?", (now_s(), r.reference, did))
    audit(c, "تحصيل تبرع تأخير (أمانة)", f"#{did} · {d['amount']:,.1f} ر.ع · مرجع {r.reference} — لا يُقيَّد إيرادًا")
    c.commit()
    return {"ok": True}


@router.post("/api/charity/{did}/disburse")
def charity_disburse(did: int, r: CharityRef, _=Depends(act_as("finance"))):
    c = db()
    if not r.beneficiary:
        raise HTTPException(400, "اذكر الجهة الخيرية المستفيدة")
    d = one(c, "SELECT * FROM charity_dues WHERE id=? AND status='collected'", (did,), "المبلغ غير محصَّل بعد", 409)
    c.execute("UPDATE charity_dues SET status='disbursed', disbursed_at=?, beneficiary=?, disbursed_ref=? WHERE id=?", (now_s(), r.beneficiary, r.reference, did))
    audit(c, "صرف تبرع تأخير لجهة خيرية", f"#{did} · {d['amount']:,.1f} ر.ع إلى {r.beneficiary} · مرجع {r.reference}")
    c.commit()
    return {"ok": True}


@router.post("/api/installments/{iid}/waive")
def waive(iid: int, _=Depends(act_as("decide"))):
    c = db()
    one(c, "SELECT 1 FROM installments WHERE id=?", (iid,))
    c.execute("UPDATE installments SET penalty_waived=1 WHERE id=?", (iid,))
    c.execute("UPDATE charity_dues SET status='waived' WHERE installment_id=? AND status='due'", (iid,))
    audit(c, "إعفاء من تبرع التأخير", f"قسط {iid}")
    c.commit()
    return {"ok": True}


@router.get("/api/bookings/{bid}/termination")
def termination_preview(bid: int, _=Depends(need("finance"))):
    c = db()
    b = one(c, "SELECT * FROM bookings WHERE id=? AND status='confirmed'", (bid,), "الحجز غير مؤكد", 409)
    paid = c.execute("SELECT SUM(paid_amount) FROM installments WHERE booking_id=?", (bid,)).fetchone()[0] or 0
    return X.termination(b["price"], paid, setting_f(c, "cancel_deduction_pct", .1))


class TermIn(BaseModel):
    reason: str = Field(min_length=5, max_length=200)


@router.post("/api/bookings/{bid}/terminate")
def terminate(bid: int, t: TermIn, _=Depends(act_as("admin"))):
    c = db()
    b = one(c, "SELECT * FROM bookings WHERE id=? AND status='confirmed'", (bid,), "الحجز غير مؤكد", 409)
    if c.execute("SELECT 1 FROM handovers WHERE booking_id=? AND status='done'", (bid,)).fetchone():
        raise HTTPException(409, "لا يُفسخ عقد وحدة مسلَّمة من هنا")
    paid = c.execute("SELECT SUM(paid_amount) FROM installments WHERE booking_id=?", (bid,)).fetchone()[0] or 0
    res = X.termination(b["price"], paid, setting_f(c, "cancel_deduction_pct", .1))
    c.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (bid,))
    c.execute("UPDATE units SET status='a' WHERE id=?", (b["unit_id"],))
    c.execute("UPDATE sale_contracts SET status='terminated' WHERE booking_id=?", (bid,))
    c.execute("UPDATE commissions SET status=CASE WHEN status='paid' THEN 'clawback' ELSE 'void' END WHERE booking_id=?", (bid,))
    c.execute("INSERT INTO refunds(booking_id,paid,deducted,refund,status,created) VALUES(?,?,?,?,?,?)",
              (bid, res["paid"], res["deduction"], res["refund"], "due", now_s()))
    audit(c, "فسخ عقد", f"حجز {bid} · مسدد {res['paid']:,.0f} · خصم {res['deduction']:,.0f} · مسترد {res['refund']:,.0f} · {t.reason}")
    c.commit()
    return res


# ======================================================================= بوابة الدفع (Sandbox بمواصفات حقيقية)
def gateway_secret(c) -> bytes:
    """0.5.0 — M6: السر من البيئة أو ملف أسرار بصلاحية 600 — لا يُخزَّن في قاعدة البيانات. أي نسخة قديمة في settings تُحذف."""
    if c.execute("SELECT 1 FROM settings WHERE k='pay_secret'").fetchone():
        c.execute("DELETE FROM settings WHERE k='pay_secret'")
        c.commit()
    return pii.secret("pay_secret", "MABANIQ_PAY_SECRET").encode()


def sign_payload(c, raw: bytes) -> str:
    return hmac.new(gateway_secret(c), raw, hashlib.sha256).hexdigest()


def record_payment(c, intent_id: str, gateway_ref: str, amount: float, actor: str):
    """مسار واحد لتسجيل أي دفعة (بوابة/تحويل/نقد): idempotent عبر gateway_ref، ويصدر إيصالًا وفاتورة."""
    if c.execute("SELECT 1 FROM payments WHERE gateway_ref=?", (gateway_ref,)).fetchone():
        r = c.execute("SELECT receipt, amount FROM payments WHERE gateway_ref=?", (gateway_ref,)).fetchone()
        return {"ok": True, "duplicate": True, "receipt": r["receipt"], "amount": r["amount"]}
    pi = one(c, "SELECT * FROM pay_intents WHERE id=?", (intent_id,), "عملية الدفع غير موجودة")
    if pi["status"] != "pending":
        raise HTTPException(409, "عملية الدفع مغلقة")
    if abs(pi["amount"] - amount) > .01:
        raise HTTPException(400, "المبلغ لا يطابق عملية الدفع")
    i = c.execute("SELECT * FROM installments WHERE id=?", (pi["installment_id"],)).fetchone()
    now = dt.datetime.now()
    receipt = f"MBQ-{now:%y%m%d}-{i['id']:05d}-{secrets.token_hex(2).upper()}"
    bk = c.execute("SELECT customer_id FROM bookings WHERE id=?", (i["booking_id"],)).fetchone()
    donation = charity_accrue(c, i, min(amount, i["amount"] - i["paid_amount"]), bk["customer_id"], now.date())
    c.execute("UPDATE installments SET paid_amount=CASE WHEN paid_amount+?<amount THEN paid_amount+? ELSE amount END, paid_date=? WHERE id=?",
              (amount, amount, now.date().isoformat(), i["id"]))
    c.execute("INSERT INTO payments(installment_id,amount,at,method,receipt,gateway_ref) VALUES(?,?,?,?,?,?)",
              (i["id"], amount, now.isoformat(timespec="seconds"), pi["provider"], receipt, gateway_ref))
    c.execute("UPDATE pay_intents SET status='paid' WHERE id=?", (intent_id,))
    b = booking_full(c, i["booking_id"])
    inv = issue_invoice(c, "installment", "installment", i["id"], b["customer"], amount, X.vat_rate(c, b["use"] or "residential"),
                        f"{i['label']} — الوحدة {b['code']}", customer_id=b["customer_id"])
    audit(c, "سداد قسط", f"{i['label']} · {amount:,.0f} ر.ع · إيصال {receipt} · فاتورة {inv}" + (f" · تبرع تأخير مستحق {donation:,.1f} ر.ع (أمانة)" if donation else ""), actor)
    return {"ok": True, "receipt": receipt, "invoice": inv, "amount": amount, "charity_due": donation}


def create_intent(c, installment_id, provider="sandbox"):
    i = one(c, "SELECT * FROM installments WHERE id=?", (installment_id,), "القسط غير موجود")
    due = round(i["amount"] - i["paid_amount"], 3)
    if due <= 1:
        raise HTTPException(409, "القسط مسدَّد")
    first = c.execute("SELECT id FROM installments WHERE booking_id=? AND paid_amount<amount-1 ORDER BY seq LIMIT 1", (i["booking_id"],)).fetchone()
    if first["id"] != i["id"]:
        raise HTTPException(409, "يُسدَّد القسط الأقدم أولًا")
    pid = "pi_" + secrets.token_urlsafe(12)
    c.execute("INSERT INTO pay_intents(id,installment_id,amount,status,created,provider) VALUES(?,?,?,?,?,?)",
              (pid, i["id"], due, "pending", now_s(), provider))
    return pid, due


@router.post("/api/pay/webhook")
async def pay_webhook(request: Request):
    """نقطة استقبال إشعارات بوابة الدفع: توقيع HMAC-SHA256 إلزامي في الرأس X-Mabaniq-Signature، ومقاومة لإعادة الإرسال."""
    raw = await request.body()
    c = db()
    sig = request.headers.get("x-mabaniq-signature", "")
    if not hmac.compare_digest(sig, sign_payload(c, raw)):
        raise HTTPException(401, "توقيع غير صالح")
    try:
        ev = json.loads(raw)
        ts = int(ev["ts"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "حمولة غير صالحة") from None
    if abs(dt.datetime.now().timestamp() - ts) > 300:
        raise HTTPException(401, "انتهت صلاحية الإشعار")
    if ev.get("type") != "payment.succeeded":
        return {"ignored": True}
    res = record_payment(c, ev["intent"], ev["ref"], float(ev["amount"]), "بوابة الدفع")
    c.commit()
    return res


def simulate_gateway(c, intent_id, amount):
    """محاكاة البوابة في البيئة التجريبية: تبني إشعارًا موقّعًا وتمرره لنفس مسار التحقق."""
    ev = {"type": "payment.succeeded", "intent": intent_id, "ref": "sbx_" + secrets.token_hex(8), "amount": amount,
          "ts": int(dt.datetime.now().timestamp())}
    raw = json.dumps(ev).encode()
    assert hmac.compare_digest(sign_payload(c, raw), sign_payload(c, raw))
    return record_payment(c, ev["intent"], ev["ref"], ev["amount"], "بوابة الدفع (تجريبية)")


# ======================================================================= المطابقة البنكية
class BankLine(BaseModel):
    day: dt.date
    amount: float = Field(gt=0, le=50_000_000)
    reference: str = Field(default="", max_length=60)


class BankIn(BaseModel):
    lines: list[BankLine] = Field(min_length=1, max_length=500)


@router.post("/api/bank/import")
def bank_import(b: BankIn, _=Depends(act_as("finance"))):
    c = db()
    matched = 0
    for ln in b.lines:
        m = None
        if ln.reference:
            m = c.execute("SELECT id FROM payments WHERE reconciled=0 AND (receipt=? OR gateway_ref=?)", (ln.reference, ln.reference)).fetchone()
        if not m:
            lo, hi = (ln.day - dt.timedelta(days=3)).isoformat(), (ln.day + dt.timedelta(days=3)).isoformat()
            m = c.execute("""SELECT id FROM payments WHERE reconciled=0 AND ABS(amount-?)<0.01 AND substr(at,1,10) BETWEEN ? AND ?
                             ORDER BY id LIMIT 1""", (ln.amount, lo, hi)).fetchone()
        if m:
            c.execute("UPDATE payments SET reconciled=1 WHERE id=?", (m["id"],))
            matched += 1
        c.execute("INSERT INTO bank_lines(day,amount,reference,matched_payment,imported) VALUES(?,?,?,?,?)",
                  (ln.day.isoformat(), ln.amount, ln.reference, m["id"] if m else None, now_s()))
    audit(c, "استيراد كشف بنكي", f"{len(b.lines)} سطر · مطابق {matched}")
    c.commit()
    return {"imported": len(b.lines), "matched": matched, "unmatched": len(b.lines) - matched}


def ledger_gap(c) -> float:
    """0.4.1 — M3: الفرق بين المسدَّد في الأقساط ودفتر المدفوعات؛ الصحيح صفر دائمًا."""
    a = c.execute("SELECT COALESCE(SUM(paid_amount),0) FROM installments").fetchone()[0]
    b = c.execute("SELECT COALESCE(SUM(amount),0) FROM payments").fetchone()[0]
    return round(a - b, 3)


@router.get("/api/bank")
def bank(_=Depends(need("finance"))):
    c = db()
    gap = ledger_gap(c)
    return {"lines": rows(c.execute("SELECT * FROM bank_lines ORDER BY id DESC LIMIT 100")),
            "unreconciled_payments": rows(c.execute("SELECT id, receipt, amount, at, method FROM payments WHERE reconciled=0 ORDER BY id DESC LIMIT 50")),
            "ledger_gap": gap, "ledger_ok": abs(gap) < 1,
            "ledger_note": "المسدَّد في الأقساط − دفتر المدفوعات؛ أي قيمة غير صفرية تعني سدادًا قُيِّد خارج المسار الموحّد ويجب تحقيقه."}


# ======================================================================= كشف حساب الضمان
@router.get("/api/escrow/{project_id}")
def escrow(project_id: int, _=Depends(need_any("finance", "reports"))):
    c = db()
    p = one(c, "SELECT * FROM projects WHERE id=?", (project_id,), "المشروع غير موجود")
    opening = setting_f(c, f"escrow:{project_id}", 0)
    paid = c.execute("""SELECT COALESCE(SUM(i.paid_amount),0) FROM installments i JOIN bookings b ON b.id=i.booking_id
                       JOIN units u ON u.id=b.unit_id WHERE u.project_id=?""", (project_id,)).fetchone()[0]
    ipcs = rows(c.execute("SELECT no, stage, approved_pct, stage_value, created FROM ipcs WHERE project_id=? AND status='approved'", (project_id,)))
    k = c.execute("SELECT retention_pct FROM contracts_c WHERE project_id=?", (project_id,)).fetchone()
    ret = k["retention_pct"] if k else .1
    released = sum(i["approved_pct"] / 100 * i["stage_value"] * (1 - ret) for i in ipcs)
    refunds = c.execute("""SELECT COALESCE(SUM(r.refund),0) FROM refunds r JOIN bookings b ON b.id=r.booking_id JOIN units u ON u.id=b.unit_id
                          WHERE u.project_id=?""", (project_id,)).fetchone()[0]
    dist = c.execute("SELECT COALESCE(SUM(amount),0) FROM distributions WHERE project_id=?", (project_id,)).fetchone()[0]
    return {"project": p["name"], "account": f"ESC-{project_id:03d}", "buyer_receipts_to_date": round(paid),
            "contractor_releases": round(released), "retention_held": round(sum(i["approved_pct"] / 100 * i["stage_value"] * ret for i in ipcs)),
            "refunds": round(refunds), "distributions": round(dist), "available_balance_model": round(opening),
            "certified_ipcs": ipcs,
            "rule": "لا يُصرف من حساب الضمان إلا مقابل مستخلص معتمد بنسبة مثبتة، ويُحتجز 10٪ ضمان حسن تنفيذ حتى نهاية فترة الصيانة."}


# ======================================================================= تصدير إلى ERPNext
@router.get("/api/export/erpnext")
def erpnext_export(fmt: str = Query("json", pattern="^(json|csv)$"), _=Depends(need("invoices"))):
    """قيود يومية بصيغة Journal Entry في ERPNext (حسابات عامة قابلة لإعادة التسمية)."""
    c = db()
    entries = []
    for p in c.execute("""SELECT pay.*, u.code unit, pr.name project, cu.name customer FROM payments pay JOIN installments i ON i.id=pay.installment_id
                         JOIN bookings b ON b.id=i.booking_id JOIN units u ON u.id=b.unit_id JOIN projects pr ON pr.id=u.project_id
                         JOIN customers cu ON cu.id=b.customer_id ORDER BY pay.id"""):
        entries.append({"doctype": "Journal Entry", "posting_date": p["at"][:10], "voucher_type": "Bank Entry", "cheque_no": p["receipt"],
                        "cheque_date": p["at"][:10], "user_remark": f"تحصيل {p['unit']} — {p['customer']}",
                        "accounts": [{"account": f"Escrow Bank - {p['project']}", "debit_in_account_currency": p["amount"]},
                                     {"account": "Customer Advances (Off-plan)", "party_type": "Customer", "party": p["customer"],
                                      "credit_in_account_currency": p["amount"], "project": p["project"]}]})
    # 0.5.0 — M4: تبرعات التأخير قيود أمانة منفصلة — لا تمر بحساب إيراد
    for d in c.execute("""SELECT d.*, pr.name project FROM charity_dues d JOIN installments i ON i.id=d.installment_id JOIN bookings b ON b.id=i.booking_id
                         JOIN units u ON u.id=b.unit_id JOIN projects pr ON pr.id=u.project_id WHERE d.status IN ('collected','disbursed') ORDER BY d.id"""):
        entries.append({"doctype": "Journal Entry", "posting_date": (d["collected_at"] or "")[:10], "voucher_type": "Bank Entry", "cheque_no": d["collected_ref"],
                        "cheque_date": (d["collected_at"] or "")[:10], "user_remark": "تبرع تأخير (شرط التبرع) — أمانة لجهة خيرية، ليس إيرادًا",
                        "accounts": [{"account": f"Escrow Bank - {d['project']}", "debit_in_account_currency": d["amount"]},
                                     {"account": "Charity Payable - Late Payment Donations (Trust)", "credit_in_account_currency": d["amount"]}]})
        if d["status"] == "disbursed":
            entries.append({"doctype": "Journal Entry", "posting_date": (d["disbursed_at"] or "")[:10], "voucher_type": "Bank Entry", "cheque_no": d["disbursed_ref"],
                            "cheque_date": (d["disbursed_at"] or "")[:10], "user_remark": f"صرف تبرع تأخير إلى {d['beneficiary']}",
                            "accounts": [{"account": "Charity Payable - Late Payment Donations (Trust)", "debit_in_account_currency": d["amount"]},
                                         {"account": f"Escrow Bank - {d['project']}", "credit_in_account_currency": d["amount"]}]})
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["posting_date", "voucher", "account", "debit", "credit", "party", "remark"])
        for e in entries:
            for a in e["accounts"]:
                w.writerow([e["posting_date"], e["cheque_no"], a["account"], a.get("debit_in_account_currency", 0),
                            a.get("credit_in_account_currency", 0), a.get("party", ""), e["user_remark"]])
        return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="mabaniq-erpnext-journal.csv"'})
    return {"count": len(entries), "entries": entries}


def b64(s: str) -> bytes:
    return base64.b64decode(s, validate=True)
