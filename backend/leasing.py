"""Mabaniq 0.21.0 — integrated leasing, core (design docs/DESIGN-leasing-accounting-hr-modules.md §3, phase 2a).

What lives here: the portfolio register (owners, meters, derived unit state), lessees with a blacklist, leases with yearly escalation and a free
preparation period, the payment schedule, the `rent_payments` ledger (partial / advance / reversal), post-dated cheques and their life cycle, arrears
ageing, reminders, and the data the three PDFs (lease, rent receipt, cheque receipt) are drawn from.

Rules kept on purpose:
* `rent_payments` is append-only — a refund or a bounced cheque is a negative row that points at the row it reverses. `rent_dues.paid` / `paid_date`
  stay as a *cached* total written ONLY by `refresh_due()`, so every older screen / report keeps working and a test can compare cache and ledger.
* Nothing is guessed: an unknown payment method stays NULL, an unknown date stays empty.
* Numbers (lease, receipt, cheque receipt) come from `counters` — one UPDATE per number, so concurrent requests never share one.
* Money has three decimals (baisa). No fees, interest or penalties are ever computed here (late-payment charity is phase 2b and only by contract).
"""
from __future__ import annotations

import calendar
import datetime as dt
from fractions import Fraction

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import ledger, pii
from .auth import need
from .common import ACTOR, act_as, audit, db, now_s, rows, today
from .db import TENANT, connect, tenants
from .modules import one

router = APIRouter()

METHODS = ("cash", "cheque", "transfer", "card", "other")
METHOD_LABEL = {"cash": "نقدًا", "cheque": "شيك", "transfer": "تحويل بنكي", "card": "بطاقة", "other": "أخرى"}
CHEQUE_STATUS = {"held": "محفوظ لدى الشركة", "deposited": "مودَع في البنك", "cleared": "تم صرفه", "bounced": "مرتجع", "returned": "أُعيد للمستأجر", "cancelled": "ملغى"}
LEASE_STATUS = {"draft": "مسودة", "active": "ساري", "expired": "منتهٍ", "renewed": "مُجدَّد", "terminated": "مُنهى", "evicted": "إخلاء"}
UNIT_STATE = {"leased": "مؤجَّرة", "prep": "فترة تجهيز", "vacant": "شاغرة", "maintenance": "صيانة", "not_leasable": "غير قابلة للتأجير"}
USES = ("residential", "commercial", "office", "warehouse", "land")
EPS = 0.0005  # half a baisa: the tolerance of every "paid in full" comparison
# an unpaid *deposit* is not arrears; every other kind of due is
NOT_DEPOSIT = "COALESCE(kind,'rent')<>'deposit'"


# ----------------------------------------------------------------------------------------------------- small helpers
def addm(d: dt.date, m: int) -> dt.date:
    y, mo = divmod(d.month - 1 + m, 12)
    y, mo = d.year + y, mo + 1
    return dt.date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def r3(v) -> float:
    return round(float(v or 0) + 0.0, 3)


def _date(s, what="التاريخ") -> dt.date:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        raise HTTPException(400, f"{what} غير صالح") from None


def next_no(c, key: str) -> int:
    """Gapless-per-key counter; the UPDATE takes the row lock, so two requests never read the same value."""
    c.execute("INSERT OR IGNORE INTO counters(k,n) VALUES(?,0)", (key,))
    c.execute("UPDATE counters SET n=n+1 WHERE k=?", (key,))
    return c.execute("SELECT n FROM counters WHERE k=?", (key,)).fetchone()["n"]


def event(c, lease_id: int, kind: str, detail: str = "", by: str | None = None) -> None:
    c.execute("INSERT INTO lease_events(lease_id,kind,at,by_user,detail) VALUES(?,?,?,?,?)", (lease_id, kind, now_s(), by or ACTOR.get(), detail))


# ----------------------------------------------------------------------------------------------------- schedule
def build_schedule(start: dt.date, months: int, rents: list[float], frequency: int, prep_days: int = 0) -> list[dict]:
    """The dues of a lease. `rents[i]` is the annual rent of contract year i+1; rent is charged from `start + prep_days` (the preparation period is
    free: 30 days = exactly one month); the last period is proportional to the months left (rule M9); a period that straddles two contract years is
    priced month by month at each year's rate. Exact (Fraction) arithmetic, rounded to the baisa, the last due absorbing the rounding."""
    if frequency not in (1, 2, 3, 4, 6, 12):
        raise ValueError("عدد الدفعات السنوية يجب أن يقسم 12")
    if not 1 <= months <= 120:
        raise ValueError("مدة العقد بين شهر و120 شهرًا")
    if len(rents) < -(-months // 12):
        raise ValueError("يلزم إيجار لكل سنة من سنوات العقد")
    prep = Fraction(prep_days, 30)
    if prep >= months:
        raise ValueError("فترة التجهيز تغطي كل مدة العقد")
    step = 12 // frequency
    rent_start = start + dt.timedelta(days=prep_days)

    def charge(a: Fraction, b: Fraction) -> Fraction:
        tot, j = Fraction(0), int(a)
        while Fraction(j) < b:
            lo, hi = max(a, Fraction(j)), min(b, Fraction(j + 1))
            if hi > lo:
                tot += Fraction(str(rents[j // 12])) / 12 * (hi - lo)
            j += 1
        return tot

    periods, a, k = [], prep, 0
    while a < months:
        b = min(a + step, Fraction(months))
        periods.append((k, a, b))
        a, k = b, k + 1
    out = [{"due": (rent_start if k == 0 else addm(rent_start, k * step)).isoformat(), "amount": r3(charge(a, b)), "year_no": int(a // 12) + 1,
            "label": f"الدفعة {k + 1} من {len(periods)}"} for k, a, b in periods]
    total = r3(charge(prep, Fraction(months)))
    out[-1]["amount"] = r3(total - sum(d["amount"] for d in out[:-1]))
    return out


def _terms(months: int, annual_rent: float | None, rents: list[float] | None, escalation_pct: float) -> list[float]:
    years = -(-months // 12)
    if rents:
        if len(rents) < years:
            raise HTTPException(400, f"يلزم إيجار لكل سنة من سنوات العقد ({years})")
        out = [r3(x) for x in rents[:years]]
    else:
        if not annual_rent:
            raise HTTPException(400, "الإيجار السنوي مطلوب")
        out, cur = [], float(annual_rent)
        for _ in range(years):
            out.append(r3(cur))
            cur = cur * (1 + escalation_pct / 100)
    if any(x <= 0 or x > 10_000_000 for x in out):
        raise HTTPException(400, "الإيجار السنوي بين 0 و10,000,000 ر.ع")
    return out


# ----------------------------------------------------------------------------------------------------- the ledger
def refresh_due(c, due_id: int) -> float:
    """The one writer of the cached rent_dues.paid / paid_date: recomputed from the ledger."""
    s = c.execute("SELECT COALESCE(SUM(amount),0) t, MAX(CASE WHEN amount>0 THEN paid_on END) d FROM rent_payments WHERE due_id=?", (due_id,)).fetchone()
    paid = r3(s["t"])
    c.execute("UPDATE rent_dues SET paid=?, paid_date=? WHERE id=?", (paid, s["d"] if paid > 0 else None, due_id))
    return paid


def outstanding(c, lease_id: int) -> list[dict]:
    return rows(c.execute("SELECT id, due, amount, paid, kind, label FROM rent_dues WHERE lease_id=? AND amount-paid>? ORDER BY due, id", (lease_id, EPS)))


def apply_payment(c, lease_id: int, amount: float, paid_on: dt.date, method: str | None, reference: str | None, by: str, due_id: int | None = None,
                  cheque_id: int | None = None, note: str | None = None, import_key: str | None = None, receipted: bool = True) -> dict:
    """Record a receipt. With `due_id` the amount settles that due (partial allowed); without it, it is spread over the oldest unpaid dues first
    (an advance payment covers several). One receipt number for the whole movement."""
    amount = r3(amount)
    if amount <= 0:
        raise HTTPException(400, "المبلغ يجب أن يكون أكبر من صفر")
    if method is not None and method not in METHODS:
        raise HTTPException(400, "طريقة السداد غير معروفة")
    if paid_on > today():
        raise HTTPException(400, "تاريخ السداد لا يكون في المستقبل")
    lease = one(c, "SELECT * FROM leases WHERE id=?", (lease_id,), "العقد غير موجود")
    if lease["status"] in ("draft",):
        raise HTTPException(409, "العقد مسودة — وقّعه أولًا")
    if due_id is not None:
        d = one(c, "SELECT * FROM rent_dues WHERE id=? AND lease_id=?", (due_id, lease_id), "الاستحقاق غير موجود في هذا العقد")
        todo = [dict(d)]
    else:
        todo = outstanding(c, lease_id)
    left, plan = amount, []
    for d in todo:
        room = r3(d["amount"] - d["paid"])
        if room <= EPS:
            continue
        take = r3(min(left, room))
        plan.append((d["id"], take, d["due"], d.get("kind")))
        left = r3(left - take)
        if left <= EPS:
            break
    if left > EPS or not plan:
        raise HTTPException(409, "المبلغ يتجاوز المتبقي على " + ("هذا الاستحقاق" if due_id is not None else "العقد"))
    receipt = f"RC-{paid_on.year}-{next_no(c, f'receipt:{paid_on.year}'):05d}" if receipted else None
    ids = []
    for i, (did, take, due_date, dkind) in enumerate(plan):
        ids.append(c.execute("INSERT INTO rent_payments(due_id,lease_id,amount,paid_on,method,reference,cheque_id,receipt_no,recorded_by,note,created,import_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                             (did, lease_id, take, paid_on.isoformat(), method, reference, cheque_id, receipt, by, note, now_s(), f"{import_key}:{i}" if import_key else None)).lastrowid)
        refresh_due(c, did)
        from .leasing_ops import charity_accrue  # late-payment charity, only when the lease carries the clause (phase 2b)
        charity_accrue(c, lease, did, due_date, dkind, take, paid_on)
    audit(c, "تحصيل إيجار", f"{receipt or 'بلا إيصال (استيراد)'} · عقد {lease['number'] or lease_id} · {amount:,.3f} ر.ع · {METHOD_LABEL.get(method, 'طريقة غير موثَّقة')}")
    ledger.autopost_quiet(c, lease_id, only={"dues", "payments"})  # 0.23.0: the receipt reaches the books in the same transaction (a no-op until accounting is activated)
    return {"receipt_no": receipt, "payment_ids": ids, "first_id": ids[0], "applied": [{"due_id": d[0], "amount": d[1]} for d in plan], "amount": amount}


def reverse_payment(c, payment_id: int, reason: str, by: str) -> dict:
    p = one(c, "SELECT * FROM rent_payments WHERE id=?", (payment_id,), "الحركة غير موجودة")
    if p["amount"] <= 0:
        raise HTTPException(409, "هذه حركة عكسية أصلًا")
    if c.execute("SELECT 1 FROM rent_payments WHERE reverses_id=?", (payment_id,)).fetchone():
        raise HTTPException(409, "عُكست هذه الحركة سابقًا")
    rid = c.execute("INSERT INTO rent_payments(due_id,lease_id,amount,paid_on,method,reference,cheque_id,receipt_no,recorded_by,reverses_id,note,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (p["due_id"], p["lease_id"], -p["amount"], today().isoformat(), p["method"], p["reference"], p["cheque_id"], None, by, payment_id, reason, now_s())).lastrowid
    refresh_due(c, p["due_id"])
    from .leasing_ops import charity_reverse
    charity_reverse(c, p)
    audit(c, "عكس حركة تحصيل", f"{p['receipt_no'] or payment_id} · {p['amount']:,.3f} ر.ع · {reason}")
    ledger.autopost_quiet(c, p["lease_id"], only={"payments"})
    return {"id": rid}


def ledger_mismatches(c) -> list[dict]:
    """Dues whose cached total differs from the ledger (rows that have no ledger rows at all are reported too, when paid > 0)."""
    return rows(c.execute("""SELECT d.id, d.paid cached, COALESCE((SELECT SUM(amount) FROM rent_payments WHERE due_id=d.id),0) ledger FROM rent_dues d
                             WHERE ABS(d.paid - COALESCE((SELECT SUM(amount) FROM rent_payments WHERE due_id=d.id),0)) > 0.0005"""))


# ----------------------------------------------------------------------------------------------------- start-up healing
def ensure_core(c) -> dict:
    """Idempotent, run at every start-up under the seed lock: the own-company owner, lease numbers and first-year terms, expired leases, and the carry-over of
    every pre-0.21 payment into the ledger (design §8.2) — checked afterwards (ledger total = cached total)."""
    out = {"owner": 0, "numbered": 0, "terms": 0, "payments": 0, "methods": 0, "documented": 0}
    if type(c).__name__ == "PgConn":
        c.execute("SELECT pg_advisory_xact_lock(7340130)")
    if not c.has_table("rent_payments"):
        return out
    own = c.execute("SELECT id FROM owners WHERE kind='own' ORDER BY id LIMIT 1").fetchone()
    if not own:
        name = (c.execute("SELECT v FROM settings WHERE k='brand:name'").fetchone() or {"v": None})["v"] or "الشركة"
        oid = c.execute("INSERT INTO owners(name,kind) VALUES(?,?)", (name, "own")).lastrowid
        out["owner"] = 1
    else:
        oid = own["id"]
    c.execute("UPDATE units SET owner_id=? WHERE owner_id IS NULL AND COALESCE(retained,0)=1", (oid,))
    for l in c.execute("SELECT id, start FROM leases WHERE number IS NULL ORDER BY id").fetchall():
        y = (l["start"] or today().isoformat())[:4]
        c.execute("UPDATE leases SET number=? WHERE id=?", (f"LS-{y}-{next_no(c, f'lease:{y}'):04d}", l["id"]))
        out["numbered"] += 1
    for l in c.execute("""SELECT id, start, "end", annual_rent FROM leases l WHERE annual_rent IS NOT NULL
                          AND NOT EXISTS (SELECT 1 FROM lease_terms t WHERE t.lease_id=l.id)""").fetchall():
        c.execute("INSERT INTO lease_terms(lease_id,year_no,from_date,to_date,annual_rent) VALUES(?,?,?,?,?)", (l["id"], 1, l["start"], l["end"], l["annual_rent"]))
        out["terms"] += 1
    c.execute("UPDATE leases SET source='seed' WHERE created_by IS NULL AND COALESCE(source,'manual')='manual'")  # rows made by the seed or before 0.21 (the API always stamps created_by)
    out["documented"] = apply_documented_terms(c)
    c.execute("UPDATE leases SET rent_start=start WHERE rent_start IS NULL")
    c.execute("UPDATE leases SET status='expired' WHERE status='active' AND \"end\" < ?", (today().isoformat(),))
    known = documented_methods()
    for d in c.execute("""SELECT d.id, d.lease_id, d.paid, d.paid_date, d.due, u.code FROM rent_dues d JOIN leases l ON l.id=d.lease_id JOIN units u ON u.id=l.unit_id
                          WHERE d.paid > 0 AND NOT EXISTS (SELECT 1 FROM rent_payments p WHERE p.due_id=d.id)""").fetchall():
        m = known.get((d["code"], d["due"], d["paid_date"]))
        c.execute("INSERT INTO rent_payments(due_id,lease_id,amount,paid_on,method,reference,receipt_no,recorded_by,note,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (d["id"], d["lease_id"], d["paid"], d["paid_date"] or d["due"], m, "ترحيل 0009", None, "النظام",
                   "حركة مرحَّلة — الطريقة من تقرير الإيجار المعتمد" if m else "حركة مرحَّلة من المخبَّأ القديم — الطريقة غير موثَّقة", now_s()))
        out["payments"] += 1
        out["methods"] += 1 if m else 0
    bad = ledger_mismatches(c)
    if bad:
        raise RuntimeError(f"leasing.ensure_core: ledger and cached totals differ for dues {[b['id'] for b in bad][:5]}")
    c.commit()
    return out


_METHOD_OF = {"تحويل": "transfer", "شيك": "cheque", "نقد": "cash", "نقدًا": "cash", "نقدا": "cash", "بطاقة": "card"}


def apply_documented_terms(c) -> int:
    """Real-data developers (workbook of the purchased units): the year-2 rent and the parking bays the workbook states are written as `lease_terms` /
    `units.parking_bays`, and the still-unpaid 2027 dues the seed had priced at the year-1 rent are corrected to it (only seed rows, only when
    untouched). A year-3 rent of 0 means "not stated" and creates nothing."""
    from .tenant_profiles import profile
    p = profile(TENANT.get())
    n = 0
    for tower, _fl, unit, _area, lessee, y1, y2, _y3, parking in (p or {}).get("wb_units", []):
        if not lessee:
            continue
        l = c.execute("""SELECT l.id, l.\"end\", l.source FROM leases l JOIN units u ON u.id=l.unit_id WHERE u.code=? ORDER BY l.id LIMIT 1""", (f"MQT-T{tower}-{unit}",)).fetchone()
        if not l:
            continue
        c.execute("UPDATE units SET parking_bays=? WHERE code=? AND parking_bays IS NULL AND ?>0", (parking, f"MQT-T{tower}-{unit}", parking))
        if y2 and y2 != y1 and l["end"] >= "2027-01-01" and not c.execute("SELECT 1 FROM lease_terms WHERE lease_id=? AND year_no=2", (l["id"],)).fetchone():
            c.execute("INSERT INTO lease_terms(lease_id,year_no,from_date,to_date,annual_rent,note) VALUES(?,?,?,?,?,?)",
                      (l["id"], 2, "2027-01-01", l["end"], y2 * 12, "من جدول الوحدات المملوكة"))
            if l["source"] == "seed":
                n += c.execute("UPDATE rent_dues SET amount=?, year_no=2 WHERE lease_id=? AND due>='2027-01-01' AND paid=0 AND amount=? AND COALESCE(kind,'rent')='rent'",
                               (y2, l["id"], y1)).rowcount
    return n


def documented_methods() -> dict:
    """Real-data developers: {(unit code, due, paid on): method} read from the approved rent report kept in the profile (`ist_units`). Nothing else is guessed."""
    from .tenant_profiles import profile
    p = profile(TENANT.get())
    out = {}
    for unit, _tp, _fl, _pos, _use, _st, _rent, paid, _unpaid, _lessee, _start, _note in (p or {}).get("ist_units", []):
        for due, _amount, paid_on, method in paid:
            if _METHOD_OF.get(method):
                out[(f"IST-A-{unit}", due, paid_on)] = _METHOD_OF[method]
    return out


# ----------------------------------------------------------------------------------------------------- portfolio
def _units_state(c) -> list[dict]:
    t = today().isoformat()
    out = []
    for u in c.execute("""SELECT u.id, u.code, u.type, u.area, u.use, u.lease_state, u.owner_id, u.parking_bays, u.status, p.name project, p.id project_id,
                                 o.name owner FROM units u JOIN projects p ON p.id=u.project_id LEFT JOIN owners o ON o.id=u.owner_id
                          WHERE COALESCE(u.retained,0)=1 ORDER BY p.id, u.code""").fetchall():
        x = dict(u)
        cur = c.execute("""SELECT l.id, l.number, l.start, l."end", l.rent_start, l.annual_rent, l.status, t.name tenant, t.id tenant_id FROM leases l
                           JOIN tenants_l t ON t.id=l.tenant_id WHERE l.unit_id=? AND l.status='active' AND l.start<=? AND l."end">=? ORDER BY l.start DESC LIMIT 1""",
                        (u["id"], t, t)).fetchone()
        last = c.execute("""SELECT MAX(COALESCE(terminated_at, "end")) e FROM leases WHERE unit_id=? AND status IN ('active','expired','terminated','evicted','renewed')""", (u["id"],)).fetchone()
        x["lease"] = dict(cur) if cur else None
        if x["lease_state"] in ("maintenance", "not_leasable"):
            x["state"] = x["lease_state"]
        elif cur:
            x["state"] = "prep" if (cur["rent_start"] or cur["start"]) > t else "leased"
        elif x["lease_state"] == "prep":
            x["state"] = "prep"
        else:
            x["state"] = "vacant"
        x["state_label"] = UNIT_STATE[x["state"]]
        x["vacant_since"] = (dt.date.fromisoformat(last["e"][:10]) + dt.timedelta(days=1)).isoformat() if x["state"] == "vacant" and last and last["e"] else None
        x["vacant_days"] = (today() - dt.date.fromisoformat(x["vacant_since"])).days if x["vacant_since"] else None
        x["meters"] = rows(c.execute("SELECT id, kind, number, provider, shared FROM unit_meters WHERE unit_id=? ORDER BY id", (u["id"],)))
        out.append(x)
    return out


def aging(c) -> dict:
    t = today()
    edges = [(0, 30), (31, 60), (61, 90), (91, 180), (181, 10 ** 6)]
    labels = ["1–30 يومًا", "31–60 يومًا", "61–90 يومًا", "91–180 يومًا", "أكثر من 180 يومًا"]
    buckets = [{"label": lb, "from": a, "to": b, "amount": 0.0, "count": 0} for lb, (a, b) in zip(labels, edges, strict=True)]
    per = {}
    for d in c.execute("""SELECT d.id, d.due, d.amount, d.paid, d.lease_id, l.number, u.code unit, t.name tenant, t.id tenant_id FROM rent_dues d JOIN leases l ON l.id=d.lease_id
                          JOIN units u ON u.id=l.unit_id JOIN tenants_l t ON t.id=l.tenant_id
                          WHERE d.due < ? AND d.amount-d.paid > ? AND COALESCE(d.kind,'rent')<>'deposit' AND l.status NOT IN ('draft')""", (t.isoformat(), EPS)).fetchall():
        days = (t - dt.date.fromisoformat(d["due"])).days
        left = r3(d["amount"] - d["paid"])
        b = next(b for b in buckets if days <= b["to"])
        b["amount"] = r3(b["amount"] + left)
        b["count"] += 1
        k = per.setdefault(d["lease_id"], {"lease_id": d["lease_id"], "number": d["number"], "unit": d["unit"], "tenant": d["tenant"], "tenant_id": d["tenant_id"],
                                           "amount": 0.0, "oldest_days": 0, "buckets": [0.0] * 5})
        k["amount"] = r3(k["amount"] + left)
        k["oldest_days"] = max(k["oldest_days"], days)
        i = buckets.index(b)
        k["buckets"][i] = r3(k["buckets"][i] + left)
    return {"buckets": buckets, "total": r3(sum(b["amount"] for b in buckets)), "leases": sorted(per.values(), key=lambda x: -x["amount"])}


def overview(c) -> dict:
    us = _units_state(c)
    t = today()
    soon = lambda n: c.execute("SELECT COUNT(*) FROM leases WHERE status='active' AND \"end\">=? AND \"end\"<=?", (t.isoformat(), (t + dt.timedelta(days=n)).isoformat())).fetchone()[0]  # noqa: E731
    month = t.isoformat()[:7]
    exp_month = c.execute(f"SELECT COALESCE(SUM(amount),0) FROM rent_dues WHERE due LIKE ? AND {NOT_DEPOSIT}", (month + "%",)).fetchone()[0]
    col_month = c.execute("SELECT COALESCE(SUM(amount),0) FROM rent_payments WHERE paid_on LIKE ?", (month + "%",)).fetchone()[0]
    leased = [u for u in us if u["state"] in ("leased", "prep")]
    ag = aging(c)
    return {"units": len(us), "leased": len(leased), "vacant": sum(1 for u in us if u["state"] == "vacant"),
            "maintenance": sum(1 for u in us if u["state"] in ("maintenance", "not_leasable")),
            "occupancy": round(len(leased) / len(us) * 100) if us else 0,
            "annual_rent": r3(sum(u["lease"]["annual_rent"] or 0 for u in leased if u["lease"])),
            "arrears": ag["total"], "aging": ag["buckets"], "expiring": {"30": soon(30), "60": soon(60), "90": soon(90)},
            "month": {"expected": r3(exp_month), "collected": r3(col_month)},
            "cheques": {"held_due": c.execute("SELECT COUNT(*) FROM cheques WHERE status='held' AND due_date<=?", (t.isoformat(),)).fetchone()[0],
                        "deposited": c.execute("SELECT COUNT(*) FROM cheques WHERE status='deposited'").fetchone()[0],
                        "bounced": c.execute("SELECT COUNT(*) FROM cheques WHERE status='bounced'").fetchone()[0]}}


@router.get("/api/lea/overview")
def api_overview(_=Depends(need("leasing"))):
    return overview(db())


@router.get("/api/lea/units")
def api_units(_=Depends(need("leasing"))):
    return {"units": _units_state(db()), "states": UNIT_STATE, "uses": list(USES)}


class UnitPatch(BaseModel):
    owner_id: int | None = None
    lease_state: str | None = Field(default=None, pattern=r"^(prep|maintenance|not_leasable|none)$")
    parking_bays: int | None = Field(default=None, ge=0, le=50)
    use: str | None = Field(default=None, pattern=r"^(residential|commercial|office|warehouse|land)$")
    retained: bool | None = None


@router.post("/api/lea/units/{uid}")
def api_unit_patch(uid: int, b: UnitPatch, _=Depends(act_as("leasing"))):
    c = db()
    u = one(c, "SELECT * FROM units WHERE id=?", (uid,), "الوحدة غير موجودة")
    if b.owner_id is not None:
        one(c, "SELECT 1 FROM owners WHERE id=? AND active=1", (b.owner_id,), "المالك غير موجود")
        c.execute("UPDATE units SET owner_id=? WHERE id=?", (b.owner_id, uid))
    if b.lease_state is not None:
        c.execute("UPDATE units SET lease_state=? WHERE id=?", (None if b.lease_state == "none" else b.lease_state, uid))
    if b.parking_bays is not None:
        c.execute("UPDATE units SET parking_bays=? WHERE id=?", (b.parking_bays, uid))
    if b.use is not None:
        c.execute("UPDATE units SET use=? WHERE id=?", (b.use, uid))
    if b.retained is not None:
        if b.retained and u["status"] == "s":
            raise HTTPException(409, "وحدة مباعة لا تدخل محفظة التأجير")
        if not b.retained and c.execute("SELECT 1 FROM leases WHERE unit_id=? AND status IN ('active','draft')", (uid,)).fetchone():
            raise HTTPException(409, "على الوحدة عقد ساري أو مسودة")
        c.execute("UPDATE units SET retained=? WHERE id=?", (int(b.retained), uid))
        if b.retained and not u["owner_id"] and b.owner_id is None:
            own = c.execute("SELECT id FROM owners WHERE kind='own' ORDER BY id LIMIT 1").fetchone()
            c.execute("UPDATE units SET owner_id=? WHERE id=?", (own["id"] if own else None, uid))
    audit(c, "تعديل وحدة تأجير", f"{u['code']}")
    c.commit()
    return {"ok": True}


class MeterIn(BaseModel):
    kind: str = Field(pattern=r"^(water|electricity|gas|other)$")
    number: str = Field(min_length=1, max_length=40)
    provider: str = Field(default="", max_length=60)
    shared: bool = False


@router.post("/api/lea/units/{uid}/meters")
def api_meter_add(uid: int, b: MeterIn, _=Depends(act_as("leasing"))):
    c = db()
    one(c, "SELECT 1 FROM units WHERE id=?", (uid,), "الوحدة غير موجودة")
    mid = c.execute("INSERT INTO unit_meters(unit_id,kind,number,provider,shared) VALUES(?,?,?,?,?)", (uid, b.kind, b.number, b.provider, int(b.shared))).lastrowid
    audit(c, "إضافة عدّاد", f"وحدة {uid} · {b.kind} {b.number}")
    c.commit()
    return {"id": mid}


@router.delete("/api/lea/meters/{mid}")
def api_meter_del(mid: int, _=Depends(act_as("leasing"))):
    c = db()
    one(c, "SELECT 1 FROM unit_meters WHERE id=?", (mid,), "العدّاد غير موجود")
    c.execute("DELETE FROM unit_meters WHERE id=?", (mid,))
    audit(c, "حذف عدّاد", f"عدّاد {mid}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- owners
class OwnerIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    kind: str = Field(default="third_party", pattern=r"^(own|third_party)$")
    id_number: str = Field(default="", max_length=30)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=120)
    iban: str = Field(default="", max_length=40)
    mgmt_fee_pct: float = Field(default=0, ge=0, le=50)
    mgmt_basis: str = Field(default="collected", pattern=r"^(collected|invoiced)$")
    notes: str = Field(default="", max_length=500)


@router.get("/api/lea/owners")
def api_owners(_=Depends(need("leasing"))):
    c = db()
    out = []
    for o in c.execute("SELECT * FROM owners ORDER BY kind, id").fetchall():
        x = dict(o)
        x["id_number"], x["iban"] = pii.mask(x["id_number"]), pii.mask(x["iban"])
        x["units"] = c.execute("SELECT COUNT(*) FROM units WHERE owner_id=?", (o["id"],)).fetchone()[0]
        out.append(x)
    return out


@router.post("/api/lea/owners")
def api_owner_add(b: OwnerIn, _=Depends(act_as("leasing"))):
    c = db()
    if b.kind == "own" and c.execute("SELECT 1 FROM owners WHERE kind='own'").fetchone():
        raise HTTPException(409, "للشركة مالك واحد من نوع «مملوك»")
    oid = c.execute("INSERT INTO owners(name,kind,id_number,phone,email,iban,mgmt_fee_pct,mgmt_basis,notes) VALUES(?,?,?,?,?,?,?,?,?)",
                    (b.name, b.kind, pii.enc(b.id_number), b.phone, b.email, pii.enc(b.iban), b.mgmt_fee_pct, b.mgmt_basis, b.notes)).lastrowid
    audit(c, "إضافة مالك", f"{b.name} · {b.kind} · عمولة {b.mgmt_fee_pct}٪")
    c.commit()
    return {"id": oid}


@router.post("/api/lea/owners/{oid}")
def api_owner_edit(oid: int, b: OwnerIn, _=Depends(act_as("leasing"))):
    c = db()
    one(c, "SELECT 1 FROM owners WHERE id=?", (oid,), "المالك غير موجود")
    c.execute("UPDATE owners SET name=?, id_number=?, phone=?, email=?, iban=?, mgmt_fee_pct=?, mgmt_basis=?, notes=? WHERE id=?",
              (b.name, pii.enc(b.id_number), b.phone, b.email, pii.enc(b.iban), b.mgmt_fee_pct, b.mgmt_basis, b.notes, oid))
    audit(c, "تعديل مالك", f"{b.name}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- lessees
class TenantIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    phone: str = Field(default="", max_length=30, pattern=r"^[0-9+ ()-]*$")
    id_number: str = Field(default="", max_length=30, pattern=r"^[A-Za-z0-9]*$")
    kind: str = Field(default="individual", pattern=r"^(individual|company)$")
    cr_number: str = Field(default="", max_length=30)
    tax_no: str = Field(default="", max_length=30)
    rep_name: str = Field(default="", max_length=120)
    rep_title: str = Field(default="", max_length=60)
    rep_id_number: str = Field(default="", max_length=30)
    contact_name: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=250)
    nationality: str = Field(default="", max_length=40)
    id_expiry: str = Field(default="", max_length=10)
    rating: str = Field(default="", pattern=r"^[A-D]?$")
    rating_note: str = Field(default="", max_length=250)


def _tenant_cols(b: TenantIn) -> tuple:
    return (b.name, b.phone, pii.enc(b.id_number), b.kind, b.cr_number, b.tax_no, b.rep_name, b.rep_title, pii.enc(b.rep_id_number), b.contact_name, b.email,
            b.address, b.nationality, b.id_expiry or None, b.rating or None, b.rating_note)


TENANT_SQL_COLS = "name,phone,id_number,kind,cr_number,tax_no,rep_name,rep_title,rep_id_number,contact_name,email,address,nationality,id_expiry,rating,rating_note"


def _tenant_out(t, full=False) -> dict:
    x = dict(t)
    if full:
        x["id_number"], x["rep_id_number"] = pii.dec(x.get("id_number")), pii.dec(x.get("rep_id_number"))
    else:
        x["id_number"], x["rep_id_number"] = pii.mask(x.get("id_number")), pii.mask(x.get("rep_id_number"))
    return x


@router.get("/api/lea/tenants")
def api_tenants(q: str = Query("", max_length=60), blacklisted: int | None = None, _=Depends(need("leasing"))):
    c = db()
    sql, args = "SELECT * FROM tenants_l WHERE 1=1", []
    if q:
        sql += " AND (name LIKE ? OR phone LIKE ? OR cr_number LIKE ?)"
        args += [f"%{q}%"] * 3
    if blacklisted is not None:
        sql += " AND COALESCE(blacklisted,0)=?"
        args.append(int(blacklisted))
    out = []
    for t in c.execute(sql + " ORDER BY name LIMIT 300", args).fetchall():
        x = _tenant_out(t)
        r = c.execute("SELECT COUNT(*) n, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) a FROM leases WHERE tenant_id=?", (t["id"],)).fetchone()
        x["leases"], x["active"] = r["n"], r["a"] or 0
        out.append(x)
    return out


@router.post("/api/lea/tenants")
def api_tenant_add(b: TenantIn, _=Depends(act_as("leasing"))):
    c = db()
    tid = c.execute(f"INSERT INTO tenants_l({TENANT_SQL_COLS}) VALUES({','.join('?' * 16)})", _tenant_cols(b)).lastrowid
    audit(c, "إضافة مستأجر", b.name)
    c.commit()
    return {"id": tid}


@router.get("/api/lea/tenants/{tid}")
def api_tenant(tid: int, _=Depends(need("leasing"))):
    c = db()
    t = one(c, "SELECT * FROM tenants_l WHERE id=?", (tid,), "المستأجر غير موجود")
    x = _tenant_out(t, full=True)
    x["leases"] = rows(c.execute("""SELECT l.id, l.number, l.status, l.start, l."end", l.annual_rent, u.code unit, p.name project FROM leases l JOIN units u ON u.id=l.unit_id
                                    JOIN projects p ON p.id=u.project_id WHERE l.tenant_id=? ORDER BY l.start DESC""", (tid,)))
    audit(c, "فتح ملف مستأجر", t["name"])
    c.commit()
    return x


@router.post("/api/lea/tenants/{tid}")
def api_tenant_edit(tid: int, b: TenantIn, _=Depends(act_as("leasing"))):
    c = db()
    one(c, "SELECT 1 FROM tenants_l WHERE id=?", (tid,), "المستأجر غير موجود")
    c.execute("UPDATE tenants_l SET name=?, phone=?, id_number=?, kind=?, cr_number=?, tax_no=?, rep_name=?, rep_title=?, rep_id_number=?, contact_name=?, email=?, "
              "address=?, nationality=?, id_expiry=?, rating=?, rating_note=? WHERE id=?", (*_tenant_cols(b), tid))
    audit(c, "تعديل مستأجر", b.name)
    c.commit()
    return {"ok": True}


class BlackIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


@router.post("/api/lea/tenants/{tid}/blacklist")
def api_blacklist(tid: int, b: BlackIn, u=Depends(act_as("leasing"))):
    c = db()
    t = one(c, "SELECT name FROM tenants_l WHERE id=?", (tid,), "المستأجر غير موجود")
    c.execute("UPDATE tenants_l SET blacklisted=1, blacklist_reason=?, blacklisted_by=?, blacklisted_at=? WHERE id=?", (b.reason, u["name"], now_s(), tid))
    audit(c, "إدراج مستأجر في القائمة السوداء", f"{t['name']} · {b.reason}")
    c.commit()
    return {"ok": True}


@router.post("/api/lea/tenants/{tid}/unblacklist")
def api_unblacklist(tid: int, b: BlackIn, u=Depends(act_as("leasing"))):
    c = db()
    t = one(c, "SELECT name FROM tenants_l WHERE id=?", (tid,), "المستأجر غير موجود")
    c.execute("UPDATE tenants_l SET blacklisted=0, blacklist_reason=NULL WHERE id=?", (tid,))
    audit(c, "رفع مستأجر من القائمة السوداء", f"{t['name']} · {b.reason}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- leases
class LeaseNew(BaseModel):
    unit_id: int
    tenant_id: int | None = None
    tenant: TenantIn | None = None
    start: dt.date
    months: int = Field(ge=1, le=120)
    annual_rent: float | None = Field(default=None, gt=0, le=10_000_000)
    rents: list[float] | None = Field(default=None, max_length=10)
    escalation_pct: float = Field(default=0, ge=0, le=50)
    frequency: int = Field(default=12, ge=1, le=12)
    prep_free_days: int = Field(default=0, ge=0, le=180)
    deposit: float = Field(default=0, ge=0, le=1_000_000)
    charity_clause: bool = False
    kind: str | None = Field(default=None, pattern=r"^(residential|commercial|office|warehouse|land)$")
    municipality_ref: str = Field(default="", max_length=60)
    override_reason: str = Field(default="", max_length=300)
    sign: bool = False


def _plan(b: LeaseNew) -> tuple[list[float], list[dict]]:
    rents = _terms(b.months, b.annual_rent, b.rents, b.escalation_pct)
    try:
        return rents, build_schedule(b.start, b.months, rents, b.frequency, b.prep_free_days)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.post("/api/lea/leases/preview")
def api_lease_preview(b: LeaseNew, _=Depends(need("leasing"))):
    rents, sch = _plan(b)
    return {"rents": rents, "schedule": sch, "total": r3(sum(d["amount"] for d in sch)), "end": (addm(b.start, b.months) - dt.timedelta(days=1)).isoformat(),
            "rent_start": (b.start + dt.timedelta(days=b.prep_free_days)).isoformat()}


def _overlap(c, unit_id: int, start: dt.date, end: dt.date, skip: int | None = None) -> bool:
    return bool(c.execute("""SELECT 1 FROM leases WHERE unit_id=? AND status='active' AND start<=? AND "end">=? AND id<>?""",
                          (unit_id, end.isoformat(), start.isoformat(), skip or 0)).fetchone())


def create_lease(c, b: LeaseNew, u: dict, source="manual", bill_deposit=True, number: str | None = None) -> int:
    unit = one(c, "SELECT * FROM units WHERE id=? AND retained=1", (b.unit_id,), "الوحدة ليست ضمن محفظة التأجير")
    rents, sch = _plan(b)
    end = addm(b.start, b.months) - dt.timedelta(days=1)
    if _overlap(c, b.unit_id, b.start, end):
        raise HTTPException(409, "يوجد عقد إيجار ساري على الوحدة")
    if b.tenant_id:
        ten = one(c, "SELECT * FROM tenants_l WHERE id=?", (b.tenant_id,), "المستأجر غير موجود")
        tid = ten["id"]
    elif b.tenant:
        ten, tid = None, None
    else:
        raise HTTPException(400, "حدّد المستأجر")
    if ten and ten["blacklisted"]:
        if not (u["role"] == "admin" and len(b.override_reason.strip()) >= 5):
            raise HTTPException(409, "المستأجر في القائمة السوداء — يتجاوزها المدير بسبب موثَّق")
        audit(c, "تجاوز القائمة السوداء", f"{ten['name']} · {b.override_reason}")
    if tid is None:
        tid = c.execute(f"INSERT INTO tenants_l({TENANT_SQL_COLS}) VALUES({','.join('?' * 16)})", _tenant_cols(b.tenant)).lastrowid
    year = b.start.year
    number = number or f"LS-{year}-{next_no(c, f'lease:{year}'):04d}"  # an imported lease keeps the number it already has
    lid = c.execute("""INSERT INTO leases(unit_id,tenant_id,start,"end",annual_rent,frequency,deposit,status,municipality_ref,number,kind,prep_free_days,rent_start,months,
                                           deposit_state,charity_clause,source,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (b.unit_id, tid, b.start.isoformat(), end.isoformat(), rents[0], b.frequency, r3(b.deposit), "draft", b.municipality_ref, number, b.kind or unit["use"],
                     b.prep_free_days, (b.start + dt.timedelta(days=b.prep_free_days)).isoformat(), b.months, ("held" if bill_deposit else "recorded") if b.deposit else None, int(b.charity_clause), source,
                     u["name"])).lastrowid
    for i, r in enumerate(rents):
        f, t = addm(b.start, 12 * i), min(addm(b.start, 12 * (i + 1)) - dt.timedelta(days=1), end)
        c.execute("INSERT INTO lease_terms(lease_id,year_no,from_date,to_date,annual_rent) VALUES(?,?,?,?,?)", (lid, i + 1, f.isoformat(), t.isoformat(), r))
    event(c, lid, "create", f"مسودة · {b.months} شهرًا · {rents[0]:,.3f} ر.ع سنويًا", u["name"])
    audit(c, "عقد إيجار جديد (مسودة)", f"{number} · وحدة {unit['code']} · {rents[0]:,.3f} ر.ع سنويًا (يلزم توثيقه لدى البلدية)")
    return lid


def sign_lease(c, lid: int, u: dict, signed_at: dt.date | None = None) -> None:
    l = one(c, "SELECT * FROM leases WHERE id=?", (lid,), "العقد غير موجود")
    if l["status"] != "draft":
        raise HTTPException(409, "العقد ليس مسودة")
    ten = one(c, "SELECT * FROM tenants_l WHERE id=?", (l["tenant_id"],), "المستأجر غير موجود")
    start, end = dt.date.fromisoformat(l["start"]), dt.date.fromisoformat(l["end"])
    if _overlap(c, l["unit_id"], start, end, lid):
        raise HTTPException(409, "يوجد عقد إيجار ساري على الوحدة")
    if ten["blacklisted"] and u["role"] != "admin":
        raise HTTPException(409, "المستأجر في القائمة السوداء")
    terms = [t["annual_rent"] for t in c.execute("SELECT annual_rent FROM lease_terms WHERE lease_id=? ORDER BY year_no", (lid,)).fetchall()]
    try:
        sch = build_schedule(start, l["months"] or 12, terms, l["frequency"] or 12, l["prep_free_days"] or 0)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    for d in sch:
        c.execute("INSERT INTO rent_dues(lease_id,due,amount,kind,year_no,label) VALUES(?,?,?,?,?,?)", (lid, d["due"], d["amount"], "rent", d["year_no"], d["label"]))
    if (l["deposit"] or 0) > 0 and l["deposit_state"] == "held":  # "recorded" = the figure is on the lease but not billed (old API)
        c.execute("INSERT INTO rent_dues(lease_id,due,amount,kind,year_no,label) VALUES(?,?,?,?,?,?)", (lid, l["start"], l["deposit"], "deposit", 1, "التأمين"))
    c.execute("UPDATE leases SET status='active', signed_at=? WHERE id=?", ((signed_at or today()).isoformat(), lid))
    event(c, lid, "sign", f"وُقِّع العقد · {len(sch)} دفعة", u["name"])
    if l["renewed_from"]:  # a signed renewal closes the lease it continues; its deposit moves with the tenant (no second deposit due is billed)
        c.execute("UPDATE leases SET status='renewed', deposit_state=CASE WHEN COALESCE(deposit,0)>0 THEN 'transferred' ELSE deposit_state END WHERE id=? AND status IN ('active','expired')", (l["renewed_from"],))
        event(c, l["renewed_from"], "renewed", f"جُدِّد بالعقد {l['number']}", u["name"])
    audit(c, "توقيع عقد إيجار", f"{l['number']} · {len(sch)} دفعة")


@router.post("/api/lea/leases")
def api_lease_create(b: LeaseNew, u=Depends(act_as("leasing"))):
    c = db()
    lid = create_lease(c, b, u)
    if b.sign:
        sign_lease(c, lid, u)
    c.commit()
    return {"id": lid, "status": "active" if b.sign else "draft"}


@router.post("/api/lea/leases/{lid}/sign")
def api_lease_sign(lid: int, u=Depends(act_as("leasing"))):
    c = db()
    sign_lease(c, lid, u)
    c.commit()
    return {"ok": True}


@router.post("/api/lea/leases/{lid}/cancel")
def api_lease_cancel(lid: int, b: BlackIn, u=Depends(act_as("leasing"))):
    """A draft that was never signed has no financial effect: it is cancelled, not deleted (the number stays used)."""
    c = db()
    l = one(c, "SELECT * FROM leases WHERE id=?", (lid,), "العقد غير موجود")
    if l["status"] != "draft":
        raise HTTPException(409, "يُلغى فقط ما لم يُوقَّع")
    c.execute("UPDATE leases SET status='terminated', termination_kind='cancelled_draft', termination_note=?, terminated_at=? WHERE id=?", (b.reason, today().isoformat(), lid))
    event(c, lid, "cancel", b.reason, u["name"])
    audit(c, "إلغاء مسودة عقد", f"{l['number']} · {b.reason}")
    c.commit()
    return {"ok": True}


def lease_detail(c, lid: int) -> dict:
    l = dict(one(c, """SELECT l.*, u.code unit, u.type unit_type, u.area, u.use, u.parking_bays, u.owner_id, p.name project, p.location FROM leases l JOIN units u ON u.id=l.unit_id
                       JOIN projects p ON p.id=u.project_id WHERE l.id=?""", (lid,), "العقد غير موجود"))
    l["tenant"] = _tenant_out(one(c, "SELECT * FROM tenants_l WHERE id=?", (l["tenant_id"],)), full=True)
    o = c.execute("SELECT id, name, kind FROM owners WHERE id=?", (l["owner_id"],)).fetchone()
    l["owner"] = dict(o) if o else None
    l["terms"] = rows(c.execute("SELECT year_no, from_date, to_date, annual_rent FROM lease_terms WHERE lease_id=? ORDER BY year_no", (lid,)))
    dues = rows(c.execute("SELECT * FROM rent_dues WHERE lease_id=? ORDER BY due, id", (lid,)))
    pays = rows(c.execute("SELECT * FROM rent_payments WHERE lease_id=? ORDER BY id", (lid,)))
    chq = rows(c.execute("SELECT * FROM cheques WHERE lease_id=? ORDER BY due_date, id", (lid,)))
    t = today().isoformat()
    for d in dues:
        d["balance"] = r3(d["amount"] - d["paid"])
        d["state"] = "paid" if d["balance"] <= EPS else "late" if d["due"] < t else "upcoming"
        d["payments"] = [p for p in pays if p["due_id"] == d["id"]]
        d["cheque"] = next((q for q in chq if q["due_id"] == d["id"] and q["status"] in ("held", "deposited")), None)
    l["dues"], l["payments"], l["cheques"] = dues, pays, chq
    rent_dues = [d for d in dues if (d["kind"] or "rent") != "deposit"]
    l["totals"] = {"billed": r3(sum(d["amount"] for d in rent_dues)), "paid": r3(sum(d["paid"] for d in rent_dues)),
                   "balance": r3(sum(d["balance"] for d in rent_dues)), "arrears": r3(sum(d["balance"] for d in rent_dues if d["state"] == "late")),
                   "deposit_paid": r3(sum(d["paid"] for d in dues if d["kind"] == "deposit"))}
    l["events"] = rows(c.execute("SELECT kind, at, by_user, detail FROM lease_events WHERE lease_id=? ORDER BY id DESC", (lid,)))
    l["status_label"] = LEASE_STATUS.get(l["status"], l["status"])
    return l


@router.get("/api/lea/leases")
def api_leases(status: str | None = None, q: str = Query("", max_length=60), _=Depends(need("leasing"))):
    c = db()
    sql = """SELECT l.id, l.number, l.status, l.start, l."end", l.annual_rent, l.frequency, l.unit_id, u.code unit, t.name tenant, t.id tenant_id,
                    COALESCE((SELECT SUM(amount-paid) FROM rent_dues d WHERE d.lease_id=l.id AND d.due<? AND d.amount-d.paid>0.0005 AND COALESCE(d.kind,'rent')<>'deposit'),0) arrears
             FROM leases l JOIN units u ON u.id=l.unit_id JOIN tenants_l t ON t.id=l.tenant_id WHERE 1=1"""
    args: list = [today().isoformat()]
    if status:
        sql += " AND l.status=?"
        args.append(status)
    if q:
        sql += " AND (l.number LIKE ? OR u.code LIKE ? OR t.name LIKE ?)"
        args += [f"%{q}%"] * 3
    out = rows(c.execute(sql + ' ORDER BY l."end" DESC LIMIT 500', args))
    for x in out:
        x["arrears"] = r3(x["arrears"])
        x["status_label"] = LEASE_STATUS.get(x["status"], x["status"])
        x["days_left"] = (dt.date.fromisoformat(x["end"]) - today()).days if x["status"] == "active" else None
    return out


@router.get("/api/lea/leases/{lid}")
def api_lease(lid: int, _=Depends(need("leasing"))):
    return lease_detail(db(), lid)


# ----------------------------------------------------------------------------------------------------- payments
class PayIn(BaseModel):
    lease_id: int
    amount: float = Field(gt=0, le=10_000_000)
    paid_on: dt.date | None = None
    method: str | None = Field(default=None, pattern=r"^(cash|cheque|transfer|card|other)$")
    reference: str = Field(default="", max_length=80)
    due_id: int | None = None
    note: str = Field(default="", max_length=250)


@router.post("/api/lea/payments")
def api_pay(b: PayIn, u=Depends(act_as("leasing"))):
    c = db()
    r = apply_payment(c, b.lease_id, b.amount, b.paid_on or today(), b.method, b.reference or None, u["name"], b.due_id, None, b.note or None)
    c.commit()
    return r


@router.post("/api/lea/payments/{pid}/reverse")
def api_pay_reverse(pid: int, b: BlackIn, u=Depends(act_as("leasing"))):
    c = db()
    r = reverse_payment(c, pid, b.reason, u["name"])
    c.commit()
    return r


@router.get("/api/lea/payments")
def api_payments(lease_id: int | None = None, limit: int = Query(100, ge=1, le=500), _=Depends(need("leasing"))):
    c = db()
    sql = """SELECT p.*, l.number lease_no, u.code unit, t.name tenant FROM rent_payments p JOIN leases l ON l.id=p.lease_id JOIN units u ON u.id=l.unit_id
             JOIN tenants_l t ON t.id=l.tenant_id"""
    out = rows(c.execute(sql + (" WHERE p.lease_id=?" if lease_id else "") + " ORDER BY p.id DESC LIMIT ?", ((lease_id, limit) if lease_id else (limit,))))
    for x in out:
        x["method_label"] = METHOD_LABEL.get(x["method"], "غير موثَّقة")
    return out


@router.get("/api/lea/aging")
def api_aging(_=Depends(need("leasing"))):
    return aging(db())


@router.get("/api/lea/tenants/{tid}/statement")
def api_statement(tid: int, _=Depends(need("leasing"))):
    c = db()
    t = one(c, "SELECT * FROM tenants_l WHERE id=?", (tid,), "المستأجر غير موجود")
    out = []
    for l in c.execute("SELECT id, number, status, start, \"end\" FROM leases WHERE tenant_id=? ORDER BY start", (tid,)).fetchall():
        d = lease_detail(c, l["id"])
        out.append({"lease_id": l["id"], "number": l["number"], "unit": d["unit"], "status": l["status"], "totals": d["totals"],
                    "entries": sorted([{"date": x["due"], "kind": "due", "label": x["label"] or "إيجار", "debit": x["amount"], "credit": 0} for x in d["dues"]]
                                      + [{"date": p["paid_on"], "kind": "payment", "label": f"{p['receipt_no'] or 'حركة عكسية'}", "debit": 0, "credit": p["amount"]} for p in d["payments"]],
                                      key=lambda e: (e["date"], e["kind"]))})
    return {"tenant": t["name"], "leases": out, "balance": r3(sum(x["totals"]["balance"] for x in out))}


# ----------------------------------------------------------------------------------------------------- cheques
class ChequeIn(BaseModel):
    lease_id: int
    due_id: int | None = None
    number: str = Field(min_length=1, max_length=30)
    bank: str = Field(min_length=2, max_length=60)
    branch: str = Field(default="", max_length=60)
    amount: float = Field(gt=0, le=10_000_000)
    due_date: dt.date
    received_on: dt.date | None = None
    drawer: str = Field(default="", max_length=120)


@router.get("/api/lea/cheques")
def api_cheques(status: str | None = None, _=Depends(need("leasing"))):
    c = db()
    sql = """SELECT q.*, l.number lease_no, u.code unit, t.name tenant FROM cheques q JOIN leases l ON l.id=q.lease_id JOIN units u ON u.id=l.unit_id
             JOIN tenants_l t ON t.id=l.tenant_id WHERE q.direction='in'"""
    out = rows(c.execute(sql + (" AND q.status=?" if status else "") + " ORDER BY q.due_date, q.id", ((status,) if status else ())))
    for x in out:
        x["status_label"] = CHEQUE_STATUS.get(x["status"], x["status"])
    return out


@router.post("/api/lea/cheques")
def api_cheque_add(b: ChequeIn, u=Depends(act_as("leasing"))):
    """Receiving a cheque records custody only — nothing is paid until it clears."""
    c = db()
    l = one(c, "SELECT * FROM leases WHERE id=?", (b.lease_id,), "العقد غير موجود")
    if l["status"] == "draft":
        raise HTTPException(409, "العقد مسودة — وقّعه أولًا")
    if b.due_id is not None:
        d = one(c, "SELECT * FROM rent_dues WHERE id=? AND lease_id=?", (b.due_id, b.lease_id), "الاستحقاق غير موجود في هذا العقد")
        if b.amount > r3(d["amount"] - d["paid"]) + EPS:
            raise HTTPException(409, "قيمة الشيك تتجاوز المتبقي على الاستحقاق")
    if c.execute("SELECT 1 FROM cheques WHERE number=? AND bank=? AND status NOT IN ('cancelled','returned')", (b.number, b.bank)).fetchone():
        raise HTTPException(409, "شيك بالرقم والبنك نفسيهما مسجَّل")
    rec = b.received_on or today()
    no = f"CQ-{rec.year}-{next_no(c, f'chqrcpt:{rec.year}'):05d}"
    cid = c.execute("""INSERT INTO cheques(direction,lease_id,due_id,number,bank,branch,amount,due_date,received_on,status,drawer,receipt_no,created_by)
                       VALUES('in',?,?,?,?,?,?,?,?,?,?,?,?)""", (b.lease_id, b.due_id, b.number, b.bank, b.branch, r3(b.amount), b.due_date.isoformat(), rec.isoformat(), "held",
                                                               b.drawer, no, u["name"])).lastrowid
    event(c, b.lease_id, "cheque_in", f"شيك {b.number} · {b.bank} · {b.amount:,.3f}", u["name"])
    audit(c, "استلام شيك", f"{no} · {b.number} · {b.bank} · {b.amount:,.3f} ر.ع · يستحق {b.due_date}")
    c.commit()
    return {"id": cid, "receipt_no": no}


class ChequeAct(BaseModel):
    on: dt.date | None = None
    reason: str = Field(default="", max_length=300)


def _cheque(c, cid: int):
    return one(c, "SELECT * FROM cheques WHERE id=? AND direction='in'", (cid,), "الشيك غير موجود")


@router.post("/api/lea/cheques/{cid}/deposit")
def api_cheque_deposit(cid: int, b: ChequeAct, u=Depends(act_as("leasing"))):
    c = db()
    q = _cheque(c, cid)
    if q["status"] != "held":
        raise HTTPException(409, "يُودَع الشيك المحفوظ فقط")
    c.execute("UPDATE cheques SET status='deposited', deposited_on=? WHERE id=?", ((b.on or today()).isoformat(), cid))
    event(c, q["lease_id"], "cheque_deposit", f"شيك {q['number']}", u["name"])
    audit(c, "إيداع شيك", f"{q['number']} · {q['bank']}")
    c.commit()
    return {"ok": True}


@router.post("/api/lea/cheques/{cid}/clear")
def api_cheque_clear(cid: int, b: ChequeAct, u=Depends(act_as("leasing"))):
    """Clearing is the moment of payment: the ledger row is written here and nowhere earlier."""
    c = db()
    q = _cheque(c, cid)
    if q["status"] != "deposited":
        raise HTTPException(409, "يُصرف الشيك المودَع فقط")
    on = b.on or today()
    r = apply_payment(c, q["lease_id"], q["amount"], on, "cheque", f"شيك {q['number']} · {q['bank']}", u["name"], q["due_id"], cid)
    c.execute("UPDATE cheques SET status='cleared', cleared_on=? WHERE id=?", (on.isoformat(), cid))
    event(c, q["lease_id"], "cheque_clear", f"شيك {q['number']} · إيصال {r['receipt_no']}", u["name"])
    c.commit()
    return r


@router.post("/api/lea/cheques/{cid}/bounce")
def api_cheque_bounce(cid: int, b: BlackIn, u=Depends(act_as("leasing"))):
    """A bounced cheque reopens the due (any payment it made is reversed); no fee, interest or penalty is charged."""
    c = db()
    q = _cheque(c, cid)
    if q["status"] not in ("deposited", "cleared"):
        raise HTTPException(409, "يرتجع الشيك المودَع أو المصروف فقط")
    for p in c.execute("SELECT id FROM rent_payments WHERE cheque_id=? AND amount>0 AND NOT EXISTS (SELECT 1 FROM rent_payments r WHERE r.reverses_id=rent_payments.id)", (cid,)).fetchall():
        reverse_payment(c, p["id"], f"شيك مرتجع: {b.reason}", u["name"])
    c.execute("UPDATE cheques SET status='bounced', bounce_reason=? WHERE id=?", (b.reason, cid))
    event(c, q["lease_id"], "cheque_bounce", f"شيك {q['number']} · {b.reason}", u["name"])
    audit(c, "ارتجاع شيك", f"{q['number']} · {q['bank']} · {b.reason}")
    c.execute("INSERT OR IGNORE INTO notifications(audience,channel,title,body,status,created,dedupe) VALUES(?,?,?,?,?,?,?)",
              ("staff", "app", "شيك مرتجع", f"الشيك {q['number']} ({q['bank']}) ارتجع: {b.reason}", "queued", now_s(), f"cheque-bounce:{cid}"))
    c.commit()
    return {"ok": True}


@router.post("/api/lea/cheques/{cid}/return")
def api_cheque_return(cid: int, b: BlackIn, u=Depends(act_as("leasing"))):
    c = db()
    q = _cheque(c, cid)
    if q["status"] not in ("held", "bounced"):
        raise HTTPException(409, "يُعاد للمستأجر الشيك المحفوظ أو المرتجع فقط")
    c.execute("UPDATE cheques SET status='returned', bounce_reason=COALESCE(bounce_reason, ?) WHERE id=?", (b.reason, cid))
    event(c, q["lease_id"], "cheque_return", f"شيك {q['number']} · {b.reason}", u["name"])
    audit(c, "إعادة شيك للمستأجر", f"{q['number']} · {b.reason}")
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- reminders (background + manual)
def reminders(c, before_days: int = 7) -> int:
    """Staff notifications, one per (due, stage) thanks to the unique `dedupe` key: coming up, due today, late 3+/15+/45+ days; leases ending in 90/60/30
    days; post-dated cheques that reached their date. The channel to the lessee (WhatsApp / SMS) needs an approved provider — not wired here."""
    t, n = today(), 0

    def put(title, body, key):
        return c.execute("INSERT OR IGNORE INTO notifications(audience,channel,title,body,status,created,dedupe) VALUES(?,?,?,?,?,?,?)",
                         ("staff", "app", title, body, "queued", now_s(), key)).rowcount

    for d in c.execute(f"""SELECT d.id, d.due, d.amount, d.paid, d.label, l.number, u.code unit, t.name tenant FROM rent_dues d JOIN leases l ON l.id=d.lease_id
                          JOIN units u ON u.id=l.unit_id JOIN tenants_l t ON t.id=l.tenant_id
                          WHERE l.status='active' AND d.amount-d.paid>{EPS} AND COALESCE(d.kind,'rent')<>'deposit'""").fetchall():
        days = (dt.date.fromisoformat(d["due"]) - t).days
        stage = ("pre" if 0 < days <= before_days else "due" if days == 0 else "late45" if days <= -45 else "late15" if days <= -15 else "late3" if days <= -3 else None)
        if stage:
            title = {"pre": "إيجار يستحق قريبًا", "due": "إيجار مستحق اليوم", "late3": "إيجار متأخر", "late15": "إيجار متأخر أكثر من 15 يومًا", "late45": "إيجار متأخر أكثر من 45 يومًا"}[stage]
            n += put(title, f"{d['unit']} · {d['tenant']}: {r3(d['amount'] - d['paid']):,.3f} ر.ع — الاستحقاق {d['due']}", f"rent:{d['id']}:{stage}")
    for l in c.execute("""SELECT l.id, l."end", l.number, u.code unit, t.name tenant FROM leases l JOIN units u ON u.id=l.unit_id JOIN tenants_l t ON t.id=l.tenant_id
                          WHERE l.status='active'""").fetchall():
        left = (dt.date.fromisoformat(l["end"]) - t).days
        for lim in (30, 60, 90):
            if 0 <= left <= lim:
                n += put(f"عقد ينتهي خلال {lim} يومًا", f"{l['number']} · {l['unit']} · {l['tenant']} — ينتهي {l['end']}", f"lease-end:{l['id']}:{lim}")
                break
    for q in c.execute("""SELECT q.id, q.number, q.bank, q.amount, q.due_date FROM cheques q WHERE q.status='held' AND q.due_date<=?""", (t.isoformat(),)).fetchall():
        n += put("شيك حان موعد إيداعه", f"شيك {q['number']} ({q['bank']}) بقيمة {q['amount']:,.3f} ر.ع — الاستحقاق {q['due_date']}", f"cheque-due:{q['id']}")
    c.execute("UPDATE leases SET status='expired' WHERE status='active' AND \"end\" < ?", (t.isoformat(),))
    return n


@router.post("/api/lea/reminders/run")
def api_reminders(_=Depends(act_as("leasing"))):
    c = db()
    n = reminders(c)
    audit(c, "تشغيل تذكيرات الإيجار", f"{n} تنبيه جديد")
    c.commit()
    return {"created": n}


def reminders_due_all() -> int:
    """Background tick: once a day per tenant whose leasing module is on."""
    n = 0
    for tn in tenants():
        tok = TENANT.set(tn)
        try:
            c = connect()
            try:
                from . import registry
                if "leasing" not in registry.enabled_modules(c) or not c.has_table("rent_payments"):
                    continue
                last = c.execute("SELECT v FROM settings WHERE k='lea:reminders_last_run'").fetchone()
                if not last or last["v"][:10] < today().isoformat():
                    n += reminders(c)
                    from .leasing_ops import daily
                    daily(c)
                    ledger.autopost_quiet(c)  # 0.23.0: dues that fell due today become receivable + revenue
                    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ("lea:reminders_last_run", now_s()))
                    c.commit()
            finally:
                c.close()
        finally:
            TENANT.reset(tok)
    return n


# ----------------------------------------------------------------------------------------------------- document data (drawn by pdfgen)
def lease_doc_row(c, lid: int) -> dict:
    d = lease_detail(c, lid)
    d["parking"] = d.get("parking_bays")
    d["meters"] = rows(c.execute("SELECT kind, number, provider, shared FROM unit_meters WHERE unit_id=? ORDER BY id", (d["unit_id"],)))
    d["approved"] = (c.execute("SELECT v FROM settings WHERE k='lea:template_approved'").fetchone() or {"v": "0"})["v"] == "1"
    return d


def receipt_doc_row(c, pid: int) -> dict:
    p = one(c, "SELECT * FROM rent_payments WHERE id=?", (pid,), "الإيصال غير موجود")
    if not p["receipt_no"]:
        raise HTTPException(404, "لا إيصال لهذه الحركة (مرحَّلة أو عكسية)")
    first = c.execute("SELECT MIN(id) m FROM rent_payments WHERE receipt_no=?", (p["receipt_no"],)).fetchone()["m"]
    rowsx = rows(c.execute("""SELECT p.*, d.label, d.due, d.amount due_amount, d.paid due_paid, d.kind FROM rent_payments p JOIN rent_dues d ON d.id=p.due_id
                              WHERE p.receipt_no=? ORDER BY d.due""", (p["receipt_no"],)))
    l = lease_detail(c, p["lease_id"])
    return {"receipt": p["receipt_no"], "first_id": first, "at": p["paid_on"], "amount": r3(sum(x["amount"] for x in rowsx)), "method": p["method"],
            "method_label": METHOD_LABEL.get(p["method"], "غير موثَّقة"), "reference": p["reference"], "lines": rowsx, "lease": l, "recorded_by": p["recorded_by"],
            "balance": l["totals"]["balance"]}


def cheque_doc_row(c, cid: int) -> dict:
    q = dict(_cheque(c, cid))
    q["lease"] = lease_detail(c, q["lease_id"])
    q["status_label"] = CHEQUE_STATUS.get(q["status"], q["status"])
    return q


@router.post("/api/lea/template-approved")
def api_template_approved(b: BlackIn, u=Depends(act_as("admin"))):
    """The owner lifts the «needs legal review» footer of the lease form after the legal / Sharia adviser approved it (audited)."""
    c = db()
    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ("lea:template_approved", "1"))
    audit(c, "اعتماد نموذج عقد الإيجار", b.reason)
    c.commit()
    return {"ok": True}


__all__ = ["router", "build_schedule", "apply_payment", "reverse_payment", "ensure_core", "reminders_due_all", "ledger_mismatches", "NOT_DEPOSIT"]
