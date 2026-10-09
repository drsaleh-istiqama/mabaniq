"""مبانيك — الوحدات الموسّعة (الجزء ٢): التسليم والعيوب ونقل الملكية، إدارة المرافق، اتحاد الملاك، التأجير،
المستندات، الإشعارات، وكيل واتساب، تقارير الممولين والمستثمرين، الخصوصية، إدارة المستخدمين، النسخ الاحتياطي، مفاتيح API."""
import datetime as dt
import hashlib
import json
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import auth as A
from . import engines as E
from . import engines_ext as X
from . import pii
from .auth import need, need_any
from .common import act_as, audit, db, now_s, rows, today
from .db import TENANT, audit_verify, backup, data_dir, setting_f
from .modules import DecideIn, booking_full, issue_invoice, one, paid_ratio, portal_owned

router = APIRouter()


def _add_months(d, m):
    y, mo = divmod(d.month - 1 + m, 12)
    return dt.date(d.year + y, mo + 1, min(d.day, 28))


# ======================================================================= التسليم والعيوب
@router.get("/api/handover")
def handover_list(_=Depends(need_any("handover", "service"))):
    c = db()
    out = []
    for h in c.execute("""SELECT h.*, u.code unit, cu.name customer, p.name project FROM handovers h JOIN bookings b ON b.id=h.booking_id
                         JOIN units u ON u.id=b.unit_id JOIN customers cu ON cu.id=b.customer_id JOIN projects p ON p.id=u.project_id
                         ORDER BY h.status='done', h.appointment"""):
        x = dict(h)
        x["snags"] = rows(c.execute("SELECT * FROM snags WHERE booking_id=? ORDER BY status='fixed', id", (h["booking_id"],)))
        x["paid_ratio"] = round(paid_ratio(c, h["booking_id"]) * 100, 1)
        out.append(x)
    return out


class ApptIn(BaseModel):
    appointment: dt.date


@router.post("/api/bookings/{bid}/handover/schedule")
def handover_schedule(bid: int, a: ApptIn, _=Depends(act_as("handover"))):
    c = db()
    one(c, "SELECT 1 FROM bookings WHERE id=? AND status='confirmed'", (bid,), "الحجز غير مؤكد", 409)
    if a.appointment < today():
        raise HTTPException(400, "الموعد في الماضي")
    c.execute("INSERT INTO handovers(booking_id,appointment,status) VALUES(?,?,'scheduled') "
              "ON CONFLICT(booking_id) DO UPDATE SET appointment=excluded.appointment", (bid, a.appointment.isoformat()))
    audit(c, "جدولة تسليم", f"حجز {bid} ← {a.appointment}")
    c.commit()
    return {"ok": True}


class SnagIn(BaseModel):
    booking_id: int
    item: str = Field(min_length=3, max_length=150)
    location: str = Field(default="", max_length=40)


@router.post("/api/snags")
def snag_add(s: SnagIn, _=Depends(act_as("handover"))):
    c = db()
    one(c, "SELECT 1 FROM bookings WHERE id=?", (s.booking_id,))
    sid = c.execute("INSERT INTO snags(booking_id,item,location,status,raised) VALUES(?,?,?,?,?)",
                    (s.booking_id, s.item, s.location, "open", today().isoformat())).lastrowid
    audit(c, "تسجيل ملاحظة تسليم", f"حجز {s.booking_id} · {s.item}")
    c.commit()
    return {"id": sid}


@router.post("/api/snags/{sid}/fix")
def snag_fix(sid: int, _=Depends(act_as("handover"))):
    c = db()
    one(c, "SELECT 1 FROM snags WHERE id=? AND status='open'", (sid,), "الملاحظة مغلقة", 409)
    c.execute("UPDATE snags SET status='fixed', closed=? WHERE id=?", (today().isoformat(), sid))
    audit(c, "إغلاق ملاحظة تسليم", f"#{sid}")
    c.commit()
    return {"ok": True}


BANK_LETTER_CATEGORY = "خطاب صرف بنكي"  # فئة المستند التي تثبت التزام البنك بصرف قسط التمويل عند التسليم (M2)


class HandIn(BaseModel):
    electricity: float = Field(ge=0, le=10_000_000)
    water: float = Field(ge=0, le=10_000_000)
    keys: int = Field(ge=1, le=20)


@router.post("/api/bookings/{bid}/handover/complete")
def handover_complete(bid: int, h: HandIn, _=Depends(act_as("handover"))):
    """شروط التسليم: سداد ١٠٠٪ (أو قسط تمويل البنك وحده غير مسدَّد مع خطاب صرف بنكي مرفق)، إغلاق كل الملاحظات، وعقد موقَّع."""
    c = db()
    b = one(c, "SELECT * FROM bookings WHERE id=? AND status='confirmed'", (bid,), "الحجز غير مؤكد", 409)
    blockers = []
    unpaid = c.execute("SELECT label, amount-paid_amount due FROM installments WHERE booking_id=? AND paid_amount<amount-1", (bid,)).fetchall()
    own = [u for u in unpaid if "تمويل البنك" not in u["label"]]
    bank = [u for u in unpaid if "تمويل البنك" in u["label"]]
    if own:
        blockers.append(f"أقساط غير مسددة: {len(own)} ({sum(u['due'] for u in own):,.0f} ر.ع)")
    bank_letter = None
    if bank:
        # 0.4.1 — M2: قسط تمويل البنك لا يُعفى من شرط التسليم بمجرد عنوانه؛ يلزم خطاب صرف بنكي مرفق كمستند على الحجز
        bank_letter = c.execute("SELECT id, title, at FROM documents WHERE ref_type='booking' AND ref_id=? AND category=? ORDER BY id DESC LIMIT 1",
                                (bid, BANK_LETTER_CATEGORY)).fetchone()
        if not bank_letter:
            blockers.append(f"قسط تمويل البنك ({sum(u['due'] for u in bank):,.0f} ر.ع) غير مسدَّد ولا يوجد خطاب صرف بنكي مرفق "
                            f"(ارفع المستند على الحجز بالفئة «{BANK_LETTER_CATEGORY}»)")
    n_open = c.execute("SELECT COUNT(*) FROM snags WHERE booking_id=? AND status='open'", (bid,)).fetchone()[0]
    if n_open:
        blockers.append(f"ملاحظات تسليم مفتوحة: {n_open}")
    k = c.execute("SELECT customer_signed_at, status FROM sale_contracts WHERE booking_id=?", (bid,)).fetchone()
    if not k or not k["customer_signed_at"]:
        blockers.append("عقد البيع غير موقَّع")
    kyc = c.execute("SELECT kyc_status FROM customers WHERE id=?", (b["customer_id"],)).fetchone()
    if not kyc or kyc["kyc_status"] != "verified":
        blockers.append("هوية المالك الحالي غير موثقة (KYC) — تلزم بعد التنازل أيضًا")  # 0.5.0 — M8
    if c.execute("SELECT 1 FROM resale_settlements WHERE booking_id=? AND status='open'", (bid,)).fetchone() or (k and k["status"] == "assigned_pending_kyc"):
        blockers.append("ملحق التنازل لم يُوقَّع بعد وتسوية التنازل مفتوحة")
    if blockers:
        raise HTTPException(409, "لا يمكن التسليم: " + "؛ ".join(blockers))
    cert = f"HC-{bid:05d}-{secrets.token_hex(2).upper()}"
    t = today()
    wu = _add_months(t, int(setting_f(c, "warranty_months", 12)))
    su = t.replace(year=t.year + int(setting_f(c, "structural_years", 10)))
    c.execute("""INSERT INTO handovers(booking_id,status,certificate_no,handed_at,warranty_until,structural_until,meter_readings,keys)
                 VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(booking_id) DO UPDATE SET status='done', certificate_no=excluded.certificate_no,
                 handed_at=excluded.handed_at, warranty_until=excluded.warranty_until, structural_until=excluded.structural_until,
                 meter_readings=excluded.meter_readings, keys=excluded.keys""",
              (bid, "done", cert, t.isoformat(), wu.isoformat(), su.isoformat(),
               json.dumps({"كهرباء": h.electricity, "ماء": h.water}, ensure_ascii=False), h.keys))
    c.execute("UPDATE bookings SET handed_over=? WHERE id=?", (t.isoformat(), bid))
    c.execute("INSERT OR IGNORE INTO titles(booking_id,status) VALUES(?,?)", (bid, "ready"))
    audit(c, "تسليم وحدة", f"حجز {bid} · شهادة {cert} · ضمان حتى {wu}"
          + (f" · بموجب خطاب صرف بنكي (مستند {bank_letter['id']}: {bank_letter['title']})" if bank_letter else ""))
    c.commit()
    return {"certificate": cert, "warranty_until": wu.isoformat(), "structural_until": su.isoformat()}


# ======================================================================= نقل الملكية
TITLE_STATUS = {"ready": "جاهز للتقديم", "submitted": "مقدَّم للوزارة", "issued": "صدر سند الملكية"}


@router.get("/api/titles")
def titles(_=Depends(need_any("handover", "finance"))):
    c = db()
    return rows(c.execute("""SELECT t.*, u.code unit, cu.name customer, b.price FROM titles t JOIN bookings b ON b.id=t.booking_id
                            JOIN units u ON u.id=b.unit_id JOIN customers cu ON cu.id=b.customer_id ORDER BY t.id DESC"""))


class TitleIn(BaseModel):
    status: str = Field(pattern="^(submitted|issued)$")
    deed_no: str = Field(default="", max_length=40)


@router.post("/api/titles/{tid}")
def title_update(tid: int, t: TitleIn, _=Depends(act_as("handover"))):
    c = db()
    r = one(c, "SELECT * FROM titles WHERE id=?", (tid,))
    if t.status == "issued" and not t.deed_no:
        raise HTTPException(400, "أدخل رقم سند الملكية")
    if t.status == "submitted":
        b = c.execute("SELECT price FROM bookings WHERE id=?", (r["booking_id"],)).fetchone()
        fee = round(b["price"] * setting_f(c, "title_fee_pct", .03))
        c.execute("UPDATE titles SET status='submitted', applied=?, fee=? WHERE id=?", (today().isoformat(), fee, tid))
    else:
        c.execute("UPDATE titles SET status='issued', deed_no=?, issued=? WHERE id=?", (t.deed_no, today().isoformat(), tid))
    audit(c, "نقل ملكية", f"حجز {r['booking_id']} ← {TITLE_STATUS[t.status]}")
    c.commit()
    return {"ok": True}


# ======================================================================= إدارة المرافق (FM)
@router.get("/api/fm")
def fm(_=Depends(need_any("service", "handover"))):
    c = db()
    t = today()
    assets = []
    for a in c.execute("SELECT f.*, p.name project FROM fm_assets f JOIN projects p ON p.id=f.project_id"):
        x = dict(a)
        nxt = dt.date.fromisoformat(a["last_service"]) + dt.timedelta(days=a["interval_days"])
        x["next_service"] = nxt.isoformat()
        x["overdue"] = nxt < t
        assets.append(x)
    return {"assets": assets,
            "work_orders": rows(c.execute("""SELECT w.*, f.name asset FROM work_orders w JOIN fm_assets f ON f.id=w.asset_id
                                            ORDER BY w.status='done', w.due""")),
            "warranty_claims": rows(c.execute("""SELECT s.*, u.code unit FROM service_requests s JOIN bookings b ON b.id=s.booking_id
                                                JOIN units u ON u.id=b.unit_id JOIN handovers h ON h.booking_id=b.id
                                                WHERE h.status='done' AND s.created<=h.warranty_until"""))}


class WOIn(BaseModel):
    cost: float = Field(default=0, ge=0, le=1_000_000)


@router.post("/api/work-orders/{wid}/done")
def wo_done(wid: int, w: WOIn, _=Depends(act_as("service"))):
    c = db()
    wo = one(c, "SELECT * FROM work_orders WHERE id=? AND status='open'", (wid,), "أمر العمل مغلق", 409)
    t = today()
    c.execute("UPDATE work_orders SET status='done', done=?, cost=? WHERE id=?", (t.isoformat(), w.cost, wid))
    a = c.execute("SELECT * FROM fm_assets WHERE id=?", (wo["asset_id"],)).fetchone()
    c.execute("UPDATE fm_assets SET last_service=? WHERE id=?", (t.isoformat(), a["id"]))
    c.execute("INSERT INTO work_orders(asset_id,kind,title,due,status,cost) VALUES(?,?,?,?,?,?)",
              (a["id"], "preventive", f"صيانة دورية: {a['name']}", (t + dt.timedelta(days=a["interval_days"])).isoformat(), "open", 0))
    audit(c, "إنجاز أمر صيانة", f"{wo['title']} · تكلفة {w.cost:,.0f}")
    c.commit()
    return {"ok": True}


# ======================================================================= اتحاد الملاك
def _oa_weights(c, project_id):
    r = rows(c.execute("""SELECT b.id booking_id, u.area, cu.name owner, cu.id customer_id FROM bookings b JOIN units u ON u.id=b.unit_id
                         JOIN customers cu ON cu.id=b.customer_id WHERE u.project_id=? AND b.status='confirmed'""", (project_id,)))
    total = sum(x["area"] for x in r) or 1
    for x in r:
        x["share"] = x["area"] / total
    return r, total


@router.get("/api/oa/{project_id}")
def oa(project_id: int, _=Depends(need_any("oa", "service"))):
    c = db()
    p = one(c, "SELECT * FROM projects WHERE id=?", (project_id,), "المشروع غير موجود")
    year = today().year + 1
    budget = rows(c.execute("SELECT line, amount FROM oa_budget WHERE project_id=? AND year=?", (project_id, year)))
    owners, area = _oa_weights(c, project_id)
    charges = rows(c.execute("""SELECT o.*, u.code unit, cu.name owner FROM oa_charges o JOIN bookings b ON b.id=o.booking_id
                               JOIN units u ON u.id=b.unit_id JOIN customers cu ON cu.id=b.customer_id WHERE o.project_id=? AND o.year=?""",
                             (project_id, year)))
    motions = []
    for m in c.execute("SELECT * FROM oa_motions WHERE project_id=? ORDER BY id DESC", (project_id,)):
        x = dict(m)
        v = c.execute("""SELECT COALESCE(SUM(CASE WHEN vote='yes' THEN weight END),0) yes, COALESCE(SUM(CASE WHEN vote='no' THEN weight END),0) no,
                                COALESCE(SUM(weight),0) cast_w, COUNT(*) n FROM oa_votes WHERE motion_id=?""", (m["id"],)).fetchone()
        x.update({"yes": round(v["yes"] * 100, 1), "no": round(v["no"] * 100, 1), "turnout": round(v["cast_w"] * 100, 1), "votes": v["n"],
                  "quorum_met": v["cast_w"] >= .5, "passed": v["cast_w"] >= .5 and v["yes"] > v["no"]})
        motions.append(x)
    return {"project": p["name"], "year": year, "budget": budget, "budget_total": sum(b["amount"] for b in budget),
            "owners": len(owners), "total_area": area, "rate_per_sqm": round(sum(b["amount"] for b in budget) / area, 2) if area else 0,
            "charges": charges, "collected": sum(x["paid"] for x in charges), "billed": sum(x["amount"] for x in charges),
            "motions": motions, "rule": "رسوم الخدمات وحقوق التصويت موزعة حسب نسبة مساحة كل وحدة من إجمالي المساحات المملوكة؛ النصاب ٥٠٪."}


@router.post("/api/oa/{project_id}/bill")
def oa_bill(project_id: int, _=Depends(act_as("oa"))):
    c = db()
    year = today().year + 1
    if c.execute("SELECT 1 FROM oa_charges WHERE project_id=? AND year=?", (project_id, year)).fetchone():
        raise HTTPException(409, "صدرت مطالبات هذه السنة مسبقًا")
    total = c.execute("SELECT COALESCE(SUM(amount),0) FROM oa_budget WHERE project_id=? AND year=?", (project_id, year)).fetchone()[0]
    if not total:
        raise HTTPException(409, "لا توجد ميزانية معتمدة")
    owners, _a = _oa_weights(c, project_id)
    for o in owners:
        amt = round(total * o["share"], 1)
        c.execute("INSERT INTO oa_charges(project_id,booking_id,year,amount,issued) VALUES(?,?,?,?,?)", (project_id, o["booking_id"], year, amt, today().isoformat()))
        issue_invoice(c, "service_charge", "oa", o["booking_id"], o["owner"], amt, setting_f(c, "vat_standard", .05), f"رسوم خدمات مشتركة {year}",
                      customer_id=o["customer_id"])
    audit(c, "إصدار مطالبات اتحاد الملاك", f"مشروع {project_id} · {len(owners)} مالك · {total:,.0f} ر.ع")
    c.commit()
    return {"owners": len(owners), "total": total}


class VoteIn(BaseModel):
    booking_id: int
    vote: str = Field(pattern="^(yes|no|abstain)$")


@router.post("/api/portal/oa/{motion_id}/vote")
def oa_vote(motion_id: int, v: VoteIn, u=Depends(need("portal"))):
    c = db()
    portal_owned(c, u, v.booking_id)
    m = one(c, "SELECT * FROM oa_motions WHERE id=? AND status='open'", (motion_id,), "التصويت مغلق", 409)
    if m["closes"] < today().isoformat():
        raise HTTPException(409, "انتهت مدة التصويت")
    owners, _a = _oa_weights(c, m["project_id"])
    me = next((o for o in owners if o["booking_id"] == v.booking_id), None)
    if not me:
        raise HTTPException(403, "التصويت للملاك في هذا المشروع فقط")
    if c.execute("SELECT 1 FROM oa_votes WHERE motion_id=? AND booking_id=?", (motion_id, v.booking_id)).fetchone():
        raise HTTPException(409, "صوّتَّ مسبقًا على هذا البند")
    c.execute("INSERT INTO oa_votes VALUES(?,?,?,?,?)", (motion_id, v.booking_id, v.vote, me["share"], now_s()))
    audit(c, "تصويت اتحاد الملاك", f"بند {motion_id} · وزن {me['share']*100:.2f}٪", f"{u['name']} (مالك)")
    c.commit()
    return {"ok": True, "weight": round(me["share"] * 100, 2)}


# ======================================================================= التأجير (الوحدات المحتفظ بها)
@router.get("/api/leasing")
def leasing(_=Depends(need("leasing"))):
    c = db()
    t = today()
    units = rows(c.execute("SELECT u.id, u.code, u.type, u.area, p.name project FROM units u JOIN projects p ON p.id=u.project_id WHERE u.retained=1"))
    leases = []
    for l in c.execute("""SELECT l.*, u.code unit, t.name tenant, t.phone FROM leases l JOIN units u ON u.id=l.unit_id
                         JOIN tenants_l t ON t.id=l.tenant_id ORDER BY l.end"""):
        x = dict(l)
        x["dues"] = rows(c.execute("SELECT * FROM rent_dues WHERE lease_id=? ORDER BY due", (l["id"],)))
        x["arrears"] = round(sum(d["amount"] - d["paid"] for d in x["dues"] if d["due"] <= t.isoformat()))
        days = (dt.date.fromisoformat(l["end"]) - t).days
        x["renewal_alert"] = f"ينتهي خلال {days} يومًا" if 0 <= days <= 90 else None
        leases.append(x)
    leased = {l["unit_id"] for l in leases if l["status"] == "active"}
    annual = sum(l["annual_rent"] for l in leases if l["status"] == "active")
    return {"units": units, "leases": leases, "occupancy": round(len(leased) / len(units) * 100) if units else 0,
            "annual_rent": annual, "arrears": sum(l["arrears"] for l in leases)}


class LeaseIn(BaseModel):
    unit_id: int
    tenant_name: str = Field(min_length=3, max_length=80)
    tenant_phone: str = Field(min_length=6, max_length=20, pattern=r"^[0-9+ ()-]+$")
    tenant_id_number: str = Field(min_length=5, max_length=20, pattern=r"^[A-Za-z0-9]+$")
    start: dt.date
    months: int = Field(ge=1, le=60)
    annual_rent: float = Field(gt=0, le=1_000_000)
    frequency: int = Field(pattern=None, ge=1, le=12)


@router.post("/api/leases")
def lease_create(l: LeaseIn, _=Depends(act_as("leasing"))):
    c = db()
    one(c, "SELECT 1 FROM units WHERE id=? AND retained=1", (l.unit_id,), "الوحدة ليست ضمن محفظة التأجير")
    if c.execute("SELECT 1 FROM leases WHERE unit_id=? AND status='active' AND end>=?", (l.unit_id, l.start.isoformat())).fetchone():
        raise HTTPException(409, "يوجد عقد إيجار ساري على الوحدة")
    if 12 % l.frequency:
        raise HTTPException(400, "عدد الدفعات السنوية يجب أن يقسم ١٢")
    tid = c.execute("INSERT INTO tenants_l(name,phone,id_number) VALUES(?,?,?)", (l.tenant_name, l.tenant_phone, pii.enc(l.tenant_id_number))).lastrowid
    end = _add_months(l.start, l.months)
    lid = c.execute("INSERT INTO leases(unit_id,tenant_id,start,end,annual_rent,frequency,deposit,status) VALUES(?,?,?,?,?,?,?,?)",
                    (l.unit_id, tid, l.start.isoformat(), end.isoformat(), l.annual_rent, l.frequency, round(l.annual_rent / 12), "active")).lastrowid
    step = 12 // l.frequency
    for k in range(0, l.months, step):
        period = min(step, l.months - k)  # 0.5.0 — M9: الدفعة الأخيرة بنسبة ما تبقى من المدة لا دفعة كاملة
        c.execute("INSERT INTO rent_dues(lease_id,due,amount) VALUES(?,?,?)", (lid, _add_months(l.start, k).isoformat(), round(l.annual_rent / 12 * period, 1)))
    audit(c, "عقد إيجار جديد", f"وحدة {l.unit_id} · {l.tenant_name} · {l.annual_rent:,.0f} ر.ع سنويًا (يلزم توثيقه لدى البلدية)")
    c.commit()
    return {"id": lid}


@router.post("/api/rent-dues/{did}/pay")
def rent_pay(did: int, _=Depends(act_as("leasing"))):
    c = db()
    d = one(c, "SELECT * FROM rent_dues WHERE id=? AND paid<amount", (did,), "الدفعة مسددة", 409)
    c.execute("UPDATE rent_dues SET paid=amount, paid_date=? WHERE id=?", (today().isoformat(), did))
    t = c.execute("SELECT t.name FROM leases l JOIN tenants_l t ON t.id=l.tenant_id WHERE l.id=?", (d["lease_id"],)).fetchone()
    issue_invoice(c, "rent", "rent", did, t["name"], d["amount"], X.vat_rate(c, "residential"), "إيجار")
    audit(c, "تحصيل إيجار", f"دفعة {did} · {d['amount']:,.0f} ر.ع")
    c.commit()
    return {"ok": True}


# ======================================================================= المستندات (رفع آمن)
ALLOWED = {"application/pdf": (b"%PDF", ".pdf"), "image/png": (b"\x89PNG", ".png"), "image/jpeg": (b"\xff\xd8\xff", ".jpg")}
MAX_DOC = 5 * 1024 * 1024
REF_TYPES = "^(booking|customer|project|permit|ipc|lease|land)$"


def _docs_dir() -> Path:
    d = data_dir() / "docs_store" / TENANT.get()
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/api/documents")
async def doc_upload(ref_type: str = Form(..., pattern=REF_TYPES), ref_id: int = Form(...),
                     title: str = Form(..., min_length=2, max_length=100), category: str = Form("عام", max_length=40),
                     file: UploadFile = File(...), u=Depends(act_as("docs"))):
    data = await file.read(MAX_DOC + 1)
    if len(data) > MAX_DOC:
        raise HTTPException(413, "الحد الأقصى ٥ ميجابايت")
    kind = next((m for m, (magic, _e) in ALLOWED.items() if data.startswith(magic)), None)
    if not kind:  # نعتمد البصمة الفعلية للملف لا الامتداد ولا نوع المحتوى المرسل
        raise HTTPException(415, "الأنواع المسموحة: PDF وPNG وJPEG فقط")
    sha = hashlib.sha256(data).hexdigest()
    stored = secrets.token_hex(16) + ALLOWED[kind][1]
    (_docs_dir() / stored).write_bytes(data)
    c = db()
    safe_name = re.sub(r"[^\w.\- \u0600-\u06FF]", "_", file.filename or "file")[:80]
    did = c.execute("INSERT INTO documents(ref_type,ref_id,title,category,filename,mime,size,sha256,stored,uploaded_by,at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (ref_type, ref_id, title, category, safe_name, kind, len(data), sha, stored, u["name"], now_s())).lastrowid
    audit(c, "رفع مستند", f"{title} ({ref_type} {ref_id}) · {len(data)//1024} KB · sha256 {sha[:12]}")
    c.commit()
    return {"id": did, "sha256": sha}


@router.get("/api/documents")
def doc_list(ref_type: str = Query(..., pattern=REF_TYPES), ref_id: int = Query(...), _=Depends(need("docs"))):
    c = db()
    return rows(c.execute("SELECT id,title,category,filename,mime,size,sha256,uploaded_by,at FROM documents WHERE ref_type=? AND ref_id=?",
                          (ref_type, ref_id)))


def _send_doc(d):
    path = _docs_dir() / d["stored"]
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != d["sha256"]:
        raise HTTPException(409, "تعذّر التحقق من سلامة الملف")
    return FileResponse(path, media_type=d["mime"], filename=d["filename"],
                        headers={"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.get("/api/documents/{did}")
def doc_get(did: int, _=Depends(need("docs"))):
    c = db()
    return _send_doc(one(c, "SELECT * FROM documents WHERE id=?", (did,)))


@router.get("/api/portal/documents/{did}")
def portal_doc(did: int, u=Depends(need("portal"))):
    c = db()
    d = one(c, "SELECT * FROM documents WHERE id=? AND ref_type='booking'", (did,))
    portal_owned(c, u, d["ref_id"])
    return _send_doc(d)


# ======================================================================= الإشعارات (تذكير الأقساط وغيرها)
@router.post("/api/notifications/run")
def notify_run(_=Depends(act_as("notify"))):
    """يولّد تذكيرات: قبل الاستحقاق بـ٧ أيام، يوم الاستحقاق، وبعد التأخر بـ١٥ يومًا. منع التكرار عبر مفتاح فريد."""
    c = db()
    t = today()
    n = 0
    for i in c.execute("""SELECT i.*, b.customer_id, u.code unit FROM installments i JOIN bookings b ON b.id=i.booking_id JOIN units u ON u.id=b.unit_id
                         WHERE b.status='confirmed' AND i.paid_amount<i.amount-1"""):
        d = (dt.date.fromisoformat(i["due_date"]) - t).days
        kind = "pre7" if d == 7 or 0 < d <= 7 else "due" if d == 0 else "late15" if -45 <= d <= -15 else None
        if not kind:
            continue
        title = {"pre7": "تذكير بقسط قادم", "due": "قسط مستحق اليوم", "late15": "قسط متأخر"}[kind]
        body = f"{i['label']} للوحدة {i['unit']}: {i['amount'] - i['paid_amount']:,.0f} ر.ع — الاستحقاق {i['due_date']}"
        cur = c.execute("INSERT OR IGNORE INTO notifications(audience,customer_id,channel,title,body,status,created,dedupe) VALUES(?,?,?,?,?,?,?,?)",
                        ("customer", i["customer_id"], "whatsapp+app", title, body, "queued", now_s(), f"inst:{i['id']}:{kind}"))
        n += cur.rowcount
    for p in c.execute("SELECT id, kind, expires FROM permits WHERE expires IS NOT NULL"):
        if 0 <= (dt.date.fromisoformat(p["expires"]) - t).days <= 60:
            n += c.execute("INSERT OR IGNORE INTO notifications(audience,channel,title,body,status,created,dedupe) VALUES(?,?,?,?,?,?,?)",
                           ("staff", "app", "ترخيص يقترب من الانتهاء", f"{p['kind']} ينتهي {p['expires']}", "queued", now_s(), f"permit:{p['id']}")).rowcount
    audit(c, "تشغيل الإشعارات", f"{n} إشعار جديد")
    c.commit()
    return {"created": n, "note": "القناة الفعلية (واتساب/SMS) تعمل بعد ربط مزوّد معتمد؛ الإشعارات تظهر الآن في تطبيق العميل."}


@router.get("/api/notifications")
def notify_list(_=Depends(need("notify"))):
    c = db()
    return rows(c.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 100"))


# ======================================================================= وكيل واتساب
class WaIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20, pattern=r"^[0-9+ ()-]+$")
    text: str = Field(min_length=1, max_length=600)


def wa_reply(c, phone, text) -> dict:
    it = X.wa_intent(text)
    digits = "".join(ch for ch in phone if ch.isdigit())[-8:]
    lead = next((l for l in c.execute("SELECT * FROM leads") if "".join(ch for ch in l["phone"] if ch.isdigit())[-8:] == digits), None)
    cust = next((x for x in c.execute("SELECT * FROM customers") if "".join(ch for ch in x["phone"] or "" if ch.isdigit())[-8:] == digits), None)
    actions = []
    if it["intent"] == "human":
        reply = "تم تحويل محادثتك إلى أحد مستشارينا، وسيتواصل معك خلال ساعات العمل. شكرًا لصبرك."
        actions.append("handoff")
    elif it["intent"] == "payment":
        if cust:
            reply = "حرصًا على خصوصيتك، يمكنك الاطلاع على أقساطك وسدادها مباشرة من تطبيق مبانيك بعد تسجيل الدخول. هل ترغب أن يتصل بك قسم التحصيل؟"
        else:
            reply = "لم نجد حسابًا مرتبطًا بهذا الرقم. يرجى التواصل من الرقم المسجل في عقدك."
    elif it["intent"] == "maintenance":
        reply = "نأسف للإزعاج. يمكنك تسجيل طلب الصيانة من تطبيق مبانيك مع صورة للمشكلة، وسيتابعه الفريق فورًا."
    elif it["intent"] == "viewing":
        if not lead:
            pid = c.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
            lid = c.execute("""INSERT INTO leads(name,phone,interest,project_id,channel,stage,interactions,budget,created,last_contact,score)
                               VALUES(?,?,?,?,?,?,?,?,?,?,0)""", ("عميل واتساب", phone, "طلب معاينة", pid, "واتساب", 1, 1, 0,
                                                                today().isoformat(), today().isoformat())).lastrowid
            lead = c.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
        slot = dt.datetime.combine(today() + dt.timedelta(days=1), dt.time(17, 0))
        c.execute("INSERT INTO viewings(lead_id,project_id,at,status,source) VALUES(?,?,?,?,?)",
                  (lead["id"], lead["project_id"], slot.isoformat(timespec="minutes"), "proposed", "whatsapp"))
        reply = f"يسعدنا استقبالك. اقترحنا موعد معاينة غدًا الساعة ٥ مساءً. ردّ بكلمة «تأكيد» أو اقترح وقتًا آخر."
        actions.append("viewing_proposed")
    elif it["intent"] in ("availability", "greeting"):
        q = "SELECT u.code, u.type, u.view, u.price, p.name project, p.kind FROM units u JOIN projects p ON p.id=u.project_id WHERE u.status='a' AND u.retained=0"
        a = []
        if it.get("kind"):
            q += " AND p.kind=?"
            a.append(it["kind"])
        if it["budget"]:
            q += " AND u.price<=?"
            a.append(it["budget"] * 1.05)
        if it["bedrooms"]:
            q += " AND u.type LIKE ?"
            a.append("%" + {1: "غرفة وصالة", 2: "غرفتان", 3: "٣ غرف", 4: "٤ غرف", 5: "٥ غرف"}.get(it["bedrooms"], "") + "%")
        res = c.execute(q + " ORDER BY u.price DESC LIMIT 40", a).fetchall()
        if it["intent"] == "greeting" and not (it["budget"] or it["bedrooms"] or it.get("kind")):
            reply = "وعليكم السلام ومرحبًا بك في مبانيك 🌿 أخبرني: هل تبحث عن شقة أم فيلا؟ وكم عدد الغرف والميزانية التقريبية؟"
        elif res:
            picks = res[:3]
            lines = [f"• {r['project']} — {r['type']}، إطلالة {r['view']}، من {r['price']:,.0f} ر.ع" for r in picks]
            reply = f"وجدت {len(res)} وحدة مناسبة، أبرزها:\n" + "\n".join(lines) + "\nهل ترغب بحجز موعد معاينة؟"
            if lead:
                c.execute("UPDATE leads SET interactions=interactions+1, last_contact=?, budget=COALESCE(NULLIF(?,0),budget), bedrooms=COALESCE(?,bedrooms) WHERE id=?",
                          (today().isoformat(), it["budget"] or 0, it["bedrooms"], lead["id"]))
            actions.append("matched")
        else:
            reply = "لا تتوفر حاليًا وحدة مطابقة تمامًا. يمكنني إشعارك فور توفر وحدة ضمن ميزانيتك، أو اقتراح بدائل قريبة. ما رأيك؟"
    else:
        reply = "شكرًا لتواصلك مع مبانيك. يمكنني مساعدتك في: الوحدات المتاحة والأسعار، حجز معاينة، الأقساط، أو الصيانة."
    for d, b in (("in", text), ("out", reply)):
        c.execute("INSERT INTO wa_messages(phone,direction,body,at,lead_id,engine) VALUES(?,?,?,?,?,?)",
                  (phone, d, b, now_s(), lead["id"] if lead else None, "rules-ar-v1"))
    return {"intent": it, "reply": reply, "actions": actions, "known_customer": bool(cust),
            "engine": "محرك قواعد عربي (rules-ar-v1) — يُستبدل بنموذج لغوي عند ربط واتساب للأعمال"}


@router.post("/api/wa/simulate")
def wa_simulate(w: WaIn, _=Depends(act_as("leads"))):
    c = db()
    r = wa_reply(c, w.phone, w.text)
    c.commit()
    return r


@router.get("/api/wa/conversations")
def wa_conv(_=Depends(need("leads"))):
    c = db()
    return rows(c.execute("SELECT * FROM wa_messages ORDER BY id DESC LIMIT 100"))


# ======================================================================= تقارير الممولين والمستثمرين
@router.get("/api/reports/lender")
def lender_report(_=Depends(need("reports"))):
    c = db()
    out = []
    for p in c.execute("SELECT * FROM projects"):
        k = E.kpis(c, p["id"])
        cash = E.project_cash(c, p["id"])
        n = k["total_units"]
        sold = c.execute("SELECT COUNT(*) FROM units WHERE project_id=? AND status='s'", (p["id"],)).fetchone()[0]
        due = c.execute("""SELECT COALESCE(SUM(i.amount),0), COALESCE(SUM(i.paid_amount),0) FROM installments i JOIN bookings b ON b.id=i.booking_id
                          JOIN units u ON u.id=b.unit_id WHERE u.project_id=? AND b.status='confirmed' AND i.due_date<=?""",
                        (p["id"], today().isoformat())).fetchone()
        remaining_cost = sum(r["outflow"] for r in cash["series"])
        receivable = c.execute("""SELECT COALESCE(SUM(i.amount-i.paid_amount),0) FROM installments i JOIN bookings b ON b.id=i.booking_id
                                 JOIN units u ON u.id=b.unit_id WHERE u.project_id=? AND b.status='confirmed'""", (p["id"],)).fetchone()[0]
        unsold_value = c.execute("SELECT COALESCE(SUM(price),0) FROM units WHERE project_id=? AND status='a'", (p["id"],)).fetchone()[0]
        lastipc = c.execute("SELECT claimed_pct, approved_pct, status, id FROM ipcs WHERE project_id=? ORDER BY no DESC LIMIT 1", (p["id"],)).fetchone()
        gap = 0
        if lastipc and lastipc["status"] == "pending":
            gap = lastipc["claimed_pct"] - E.verify_ipc(c, lastipc["id"]).get("verified_pct", lastipc["claimed_pct"])
        cov = (cash["opening"] + receivable + unsold_value * .6) / remaining_cost if remaining_cost else 9.9
        row = {"project": p["name"], "build_pct": p["build_pct"], "sold_pct": round(sold / n * 100), "collection_rate": round(due[1] / due[0] * 100, 1) if due[0] else 100,
               "receivable": round(receivable), "unsold_value": round(unsold_value), "remaining_cost_12m": round(remaining_cost),
               "coverage": round(cov, 2), "cash_gap": cash["gap"], "claimed_vs_verified": round(gap, 1), "handover": p["handover"]}
        row["flags"] = X.lender_flags(row)
        row["rating"] = "أخضر" if not row["flags"] else "أصفر" if len(row["flags"]) == 1 else "أحمر"
        out.append(row)
    return {"as_of": today().isoformat(), "projects": out,
            "method": "التغطية = (رصيد الضمان + الذمم المتبقية + ٦٠٪ من قيمة غير المباع) ÷ التكلفة المتبقية خلال ١٢ شهرًا"}


@router.get("/api/reports/investor")
def investor_report(_=Depends(need("reports"))):
    c = db()
    out = []
    for p in c.execute("SELECT * FROM projects"):
        gdv = c.execute("SELECT COALESCE(SUM(price),0) FROM units WHERE project_id=?", (p["id"],)).fetchone()[0]
        sold_v = c.execute("SELECT COALESCE(SUM(b.price),0) FROM bookings b JOIN units u ON u.id=b.unit_id WHERE u.project_id=? AND b.status='confirmed'",
                           (p["id"],)).fetchone()[0]
        k = c.execute("SELECT value FROM contracts_c WHERE project_id=?", (p["id"],)).fetchone()
        co = c.execute("SELECT COALESCE(SUM(cost),0) FROM change_orders WHERE project_id=? AND status='approved'", (p["id"],)).fetchone()[0]
        # التكلفة = عقد المقاول + أوامر التغيير المعتمدة + الأرض والتكاليف غير المباشرة والتسويق (١٨٪ من قيمة المبيعات)
        cost = (k["value"] + co + gdv * .18) if k else gdv * .72
        dist = c.execute("SELECT COALESCE(SUM(amount),0) FROM distributions WHERE project_id=?", (p["id"],)).fetchone()[0]
        out.append({"project": p["name"], "gdv": round(gdv), "sold_value": round(sold_v), "est_cost": round(cost),
                    "est_profit": round(gdv - cost), "margin": round((gdv - cost) / gdv * 100, 1) if gdv else 0,
                    "distributions": round(dist), "build_pct": p["build_pct"]})
    return {"as_of": today().isoformat(), "projects": out, "note": "التكلفة = عقد المقاول + أوامر التغيير المعتمدة + تقدير الأرض والتكاليف غير المباشرة والتسويق (١٨٪ من قيمة المبيعات) إلى حين ربط الحسابات الفعلية."}


# ======================================================================= بوابة العميل: إضافات
@router.get("/api/portal/extra")
def portal_extra(u=Depends(need("portal"))):
    c = db()
    bids = [r["id"] for r in c.execute("SELECT id FROM bookings WHERE customer_id=? AND status!='cancelled'", (u["customer_id"],))]
    out = {"notifications": rows(c.execute("SELECT title, body, created FROM notifications WHERE customer_id=? ORDER BY id DESC LIMIT 20", (u["customer_id"],))),
           "contracts": [], "handover": [], "invoices": [], "motions": [], "documents": []}
    # 0.4.1 — M1: المطابقة بمعرّف العميل حصرًا؛ المطابقة بالاسم كانت تُظهر فواتير عميل آخر يحمل الاسم نفسه
    out["invoices"] = rows(c.execute("SELECT number, net, vat, total, issued, note FROM invoices WHERE customer_id=? ORDER BY id DESC LIMIT 30",
                                     (u["customer_id"],)))
    for b in bids:
        k = c.execute("SELECT booking_id, number, status, customer_signed_at FROM sale_contracts WHERE booking_id=?", (b,)).fetchone()
        if k:
            out["contracts"].append(dict(k))
        h = c.execute("SELECT * FROM handovers WHERE booking_id=?", (b,)).fetchone()
        if h:
            x = dict(h)
            x["snags"] = rows(c.execute("SELECT item, location, status FROM snags WHERE booking_id=?", (b,)))
            out["handover"].append(x)
        out["documents"] += rows(c.execute("SELECT id, title, category, at FROM documents WHERE ref_type='booking' AND ref_id=?", (b,)))
        bk = c.execute("SELECT u.project_id FROM bookings b JOIN units u ON u.id=b.unit_id WHERE b.id=?", (b,)).fetchone()
        for m in c.execute("SELECT * FROM oa_motions WHERE project_id=? AND status='open'", (bk["project_id"],)):
            voted = c.execute("SELECT vote FROM oa_votes WHERE motion_id=? AND booking_id=?", (m["id"], b)).fetchone()
            if c.execute("SELECT status FROM bookings WHERE id=?", (b,)).fetchone()["status"] == "confirmed":
                out["motions"].append({**dict(m), "booking_id": b, "my_vote": voted["vote"] if voted else None})
    return out


class PIIn(BaseModel):
    installment_id: int


@router.post("/api/portal/pay/intent")
def portal_intent(p: PIIn, u=Depends(need("portal"))):
    from .modules import create_intent
    c = db()
    i = one(c, "SELECT booking_id FROM installments WHERE id=?", (p.installment_id,), "القسط غير موجود")
    portal_owned(c, u, i["booking_id"])
    pid, due = create_intent(c, p.installment_id)
    c.commit()
    return {"intent": pid, "amount": due, "provider": "sandbox",
            "note": "في الإنتاج يُحوَّل العميل إلى صفحة البوابة المعتمدة (مثل Thawani أو بوابة البنك)، ولا تمر بيانات البطاقة عبر مبانيك."}


class PConfirm(BaseModel):
    intent: str = Field(pattern=r"^pi_[A-Za-z0-9_-]{8,40}$")


@router.post("/api/portal/pay/sandbox-complete")
def portal_sandbox_complete(p: PConfirm, u=Depends(need("portal"))):
    from .modules import simulate_gateway
    if A.prod():
        raise HTTPException(403, "غير متاح في الإنتاج")
    c = db()
    pi = one(c, "SELECT * FROM pay_intents WHERE id=?", (p.intent,), "عملية الدفع غير موجودة")
    i = c.execute("SELECT booking_id FROM installments WHERE id=?", (pi["installment_id"],)).fetchone()
    portal_owned(c, u, i["booking_id"])
    res = simulate_gateway(c, p.intent, pi["amount"])
    c.commit()
    return res


# ======================================================================= الخصوصية (قانون حماية البيانات الشخصية)
class PrivIn(BaseModel):
    kind: str = Field(pattern="^(export|erase|correct)$")
    note: str = Field(default="", max_length=300)


@router.post("/api/portal/privacy")
def privacy_request(p: PrivIn, u=Depends(need("portal"))):
    c = db()
    rid = c.execute("INSERT INTO privacy_requests(customer_id,kind,status,created,note) VALUES(?,?,?,?,?)",
                    (u["customer_id"], p.kind, "open", now_s(), p.note)).lastrowid
    audit(c, "طلب خصوصية", f"عميل {u['customer_id']} · {p.kind}", f"{u['name']} (عميل)")
    c.commit()
    return {"id": rid, "note": "يُعالج الطلب خلال المدة النظامية. البيانات المرتبطة بعقود وسجلات مالية تُحفظ للمدة التي يفرضها القانون."}


@router.get("/api/portal/privacy/export")
def privacy_export(u=Depends(need("portal"))):
    c = db()
    cu = dict(c.execute("SELECT * FROM customers WHERE id=?", (u["customer_id"],)).fetchone())
    cu["id_number"], cu["dob"] = pii.dec(cu.get("id_number")), pii.dec(cu.get("dob"))
    bk = rows(c.execute("SELECT id, plan, price, status, created FROM bookings WHERE customer_id=?", (u["customer_id"],)))
    for b in bk:
        b["installments"] = rows(c.execute("SELECT label, due_date, amount, paid_amount, paid_date FROM installments WHERE booking_id=?", (b["id"],)))
    audit(c, "تصدير بيانات شخصية", f"عميل {u['customer_id']}", f"{u['name']} (عميل)")
    c.commit()
    return {"generated": now_s(), "customer": cu, "bookings": bk}


@router.get("/api/privacy")
def privacy_list(_=Depends(need("admin"))):
    c = db()
    return rows(c.execute("SELECT p.*, cu.name FROM privacy_requests p JOIN customers cu ON cu.id=p.customer_id ORDER BY p.status!='open', p.id DESC"))


class PrivDecide(BaseModel):
    action: str = Field(pattern="^(complete|reject)$")
    note: str = Field(min_length=3, max_length=300)


def erasure_blockers(c, cid: int) -> list[str]:
    """ما يمنع الحذف نظامًا: التزامات تعاقدية أو مالية قائمة، أو مدة احتفاظ قانونية بالسجلات المالية."""
    out = []
    if c.execute("SELECT 1 FROM bookings WHERE customer_id=? AND status IN ('pending','confirmed') AND handed_over IS NULL", (cid,)).fetchone():
        out.append("حجز أو عقد بيع قائم لم يُسلَّم")
    if c.execute("SELECT 1 FROM installments i JOIN bookings b ON b.id=i.booking_id WHERE b.customer_id=? AND i.paid_amount<i.amount-1 AND b.status='confirmed'", (cid,)).fetchone():
        out.append("أقساط غير مسدَّدة")
    if c.execute("SELECT 1 FROM oa_charges o JOIN bookings b ON b.id=o.booking_id WHERE b.customer_id=? AND o.paid<o.amount", (cid,)).fetchone():
        out.append("رسوم اتحاد ملاك مستحقة")
    return out


@router.post("/api/privacy/{rid}/process")
def privacy_process(rid: int, d: PrivDecide, u=Depends(act_as("admin"))):
    """0.5.0 — M5: سير عمل تنفيذ طلبات الخصوصية. الحذف = إخفاء هوية لا محو السجل المالي (الاحتفاظ القانوني)،
    ويُرفض تلقائيًا ما دامت التزامات قائمة، مع ذكر السبب للعميل."""
    c = db()
    r = one(c, "SELECT * FROM privacy_requests WHERE id=? AND status='open'", (rid,), "الطلب غير مفتوح", 409)
    if d.action == "complete" and r["kind"] == "erase":
        bl = erasure_blockers(c, r["customer_id"])
        if bl:
            raise HTTPException(409, "لا يمكن الحذف الآن: " + "؛ ".join(bl) + " — يُحتفظ بالبيانات للمدة النظامية ويُعاد الطلب بعد زوال السبب")
        c.execute("""UPDATE customers SET name=?, phone=NULL, email=NULL, id_number=NULL, dob=NULL, id_type=NULL, nationality=NULL, id_expiry=NULL,
                     source_of_funds=NULL, kyc_note=NULL, erased_at=? WHERE id=?""", (f"عميل محذوف #{r['customer_id']}", now_s(), r["customer_id"]))
        c.execute("UPDATE leads SET name='عميل محذوف', phone='' WHERE phone IN (SELECT phone FROM customers WHERE id=?)", (r["customer_id"],))
        # تعطيل حساب الدخول — على الاتصال نفسه (جدول users في قاعدة المطوّر نفسها؛ اتصال ثانٍ يتعارض مع قفل الكتابة)
        c.execute("UPDATE users SET active=0 WHERE customer_id=?", (r["customer_id"],))
        c.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE customer_id=?)", (r["customer_id"],))
    st = "done" if d.action == "complete" else "rejected"
    c.execute("UPDATE privacy_requests SET status=?, decided_at=?, decided_by=?, decision_note=? WHERE id=?", (st, now_s(), u["name"], d.note, rid))
    c.execute("INSERT OR IGNORE INTO notifications(audience,customer_id,channel,title,body,status,created,dedupe) VALUES(?,?,?,?,?,?,?,?)",
              ("customer", r["customer_id"], "app", "قرار في طلب الخصوصية", f"طلبك ({r['kind']}) {'نُفِّذ' if st == 'done' else 'رُفض'}: {d.note}", "queued", now_s(), f"priv:{rid}"))
    audit(c, "قرار طلب خصوصية", f"#{rid} ({r['kind']}) ← {st}: {d.note}")
    c.commit()
    return {"ok": True, "status": st}


# ======================================================================= إدارة المستخدمين
@router.get("/api/users")
def users(_=Depends(need("users"))):
    c = A.conn()
    return rows(c.execute("SELECT id, username, name, role, active, must_change, totp_enabled, pw_changed FROM users ORDER BY id"))


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern=r"^[a-z][a-z0-9._-]+$")
    name: str = Field(min_length=3, max_length=60)
    role: str = Field(pattern="^(admin|sales|finance|engineer|investor)$")


@router.post("/api/users")
def user_create(n: UserIn, _=Depends(act_as("users"))):
    c = A.conn()
    if c.execute("SELECT 1 FROM users WHERE username=?", (n.username,)).fetchone():
        raise HTTPException(409, "اسم المستخدم مستخدم")
    temp = A.temp_password()
    c.execute("INSERT INTO users(username,name,role,pw,must_change) VALUES(?,?,?,?,1)", (n.username, n.name, n.role, A.hash_pw(temp)))
    audit(c, "إنشاء مستخدم", f"{n.username} ({A.ROLES[n.role]})")
    c.commit()
    return {"username": n.username, "temporary_password": temp, "note": "تُعرض مرة واحدة فقط، ويُلزم المستخدم بتغييرها عند أول دخول."}


@router.post("/api/users/{uid}/reset")
def user_reset(uid: int, u=Depends(act_as("users"))):
    c = A.conn()
    t = one(c, "SELECT * FROM users WHERE id=?", (uid,))
    temp = A.temp_password()
    c.execute("UPDATE users SET pw=?, must_change=1 WHERE id=?", (A.hash_pw(temp), uid))
    A.kill_sessions(c, uid)
    audit(c, "إعادة تعيين كلمة مرور", t["username"])
    c.commit()
    return {"username": t["username"], "temporary_password": temp}


class ActiveIn(BaseModel):
    active: bool


@router.post("/api/users/{uid}/active")
def user_active(uid: int, a: ActiveIn, u=Depends(act_as("users"))):
    c = A.conn()
    if uid == u["id"]:
        raise HTTPException(400, "لا يمكنك تعطيل حسابك")
    t = one(c, "SELECT * FROM users WHERE id=?", (uid,))
    c.execute("UPDATE users SET active=? WHERE id=?", (int(a.active), uid))
    if not a.active:
        A.kill_sessions(c, uid)
    audit(c, "تفعيل/تعطيل مستخدم", f"{t['username']} ← {'مفعّل' if a.active else 'معطّل'}")
    c.commit()
    return {"ok": True}


# ======================================================================= النسخ الاحتياطي وسلامة السجل
@router.post("/api/admin/backup")
def do_backup(_=Depends(act_as("admin"))):
    c = db()
    name = backup(c)
    audit(c, "نسخة احتياطية", name)
    c.commit()
    return {"file": name}


@router.get("/api/audit/verify")
def verify_audit(_=Depends(need("audit"))):
    return audit_verify(db())


# ======================================================================= مفاتيح API للتكامل (قراءة فقط)
@router.post("/api/admin/api-keys")
def key_create(_=Depends(act_as("admin"))):
    c = db()
    raw = "mbq_" + secrets.token_urlsafe(32)
    c.execute("INSERT INTO api_keys(name,key_hash,prefix,created) VALUES(?,?,?,?)",
              ("تكامل", hashlib.sha256(raw.encode()).hexdigest(), raw[:10], now_s()))
    audit(c, "إنشاء مفتاح API", raw[:10] + "…")
    c.commit()
    return {"key": raw, "note": "يُعرض مرة واحدة. صلاحية قراءة فقط لنقطة /api/v1/*."}


def api_key_dep(request: Request):
    raw = request.headers.get("x-api-key", "")
    if not raw:
        raise HTTPException(401, "مفتاح API مطلوب")
    c = db()
    k = c.execute("SELECT id FROM api_keys WHERE key_hash=? AND active=1", (hashlib.sha256(raw.encode()).hexdigest(),)).fetchone()
    if not k:
        raise HTTPException(401, "مفتاح API غير صالح")
    c.execute("UPDATE api_keys SET last_used=? WHERE id=?", (now_s(), k["id"]))
    c.commit()
    return True


@router.get("/api/v1/inventory")
def v1_inventory(_=Depends(api_key_dep)):
    c = db()
    return rows(c.execute("""SELECT u.code, p.name project, u.type, u.area, u.view, u.price FROM units u JOIN projects p ON p.id=u.project_id
                            WHERE u.status='a' AND u.retained=0 ORDER BY p.id, u.code"""))
