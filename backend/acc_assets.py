"""Mabaniq 0.24.0 — VAT returns, fixed assets and depreciation, budgets, Islamic financing contracts (design §4.5–4.7, phase 3b).

* VAT (Oman 5 %): a quarter's return is computed from the ledger (output VAT − input VAT) and filed once; filing posts the settlement so the quarter's VAT accounts
  clear to «payable to the authority» (or «refundable»). Rent VAT is not split in the ledger yet (owner decision ل29), and the return says so.
* Fixed assets: straight line, monthly, idempotent per period; depreciation starts the month after acquisition and never exceeds cost − salvage.
* Financing: murabaha / ijara / instalment / istisna with a FIXED, known mark-up. There is no rate, no compounding and no variable price anywhere in the model
  (extra fields are refused); the mark-up sits in a deferred-margin account and is recognised with each instalment.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import ledger
from .acc_ap import _active
from .auth import need
from .common import act_as, audit, db, rows, today

router = APIRouter()
r3 = ledger.r3
EPS = ledger.EPS
POSTED = "j.status IN ('posted','reversed')"


def _acct(c, ref) -> int:
    r = c.execute("SELECT id, postable, active FROM acc_accounts WHERE " + ("id=?" if isinstance(ref, int) else "code=?"), (ref,)).fetchone()
    if not r or not r["postable"] or not r["active"]:
        raise HTTPException(400, f"الحساب {ref} غير قابل للترحيل")
    return r["id"]


def _key_acct(c, key: str) -> int:
    r = c.execute("SELECT id FROM acc_accounts WHERE system_key=?", (key,)).fetchone()
    if not r:
        raise HTTPException(409, f"لا حساب مربوط بالمفتاح «{key}»")
    return r["id"]


def _post(c, **kw) -> int:
    try:
        return ledger.post(c, **kw)
    except ledger.LedgerError as e:
        raise HTTPException(409, str(e)) from None


# ----------------------------------------------------------------------------------------------------- VAT
def quarter_range(year: int, q: int) -> tuple[str, str]:
    m0 = 3 * (q - 1) + 1
    return dt.date(year, m0, 1).isoformat(), dt.date(year, m0 + 2, calendar.monthrange(year, m0 + 2)[1]).isoformat()


def vat_compute(c, year: int, q: int) -> dict:
    frm, to = quarter_range(year, q)
    base = f"""FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id JOIN acc_accounts a ON a.id=l.account_id
               WHERE {POSTED} AND j.jdate>=? AND j.jdate<=? AND COALESCE(j.source_kind,'')<>'vatfile'"""
    out_v = r3(c.execute(f"SELECT COALESCE(SUM(l.credit - l.debit),0) {base} AND a.system_key='vat_out'", (frm, to)).fetchone()[0])
    in_v = r3(c.execute(f"SELECT COALESCE(SUM(l.debit - l.credit),0) {base} AND a.system_key='vat_in'", (frm, to)).fetchone()[0])

    def bases(types, sign, cls):
        col = "(l.credit - l.debit)" if sign == "cr" else "(l.debit - l.credit)"
        ph = ",".join("?" * len(types))
        return r3(c.execute(f"SELECT COALESCE(SUM({col}),0) {base} AND a.type IN ({ph}) AND l.vat_class=?", (frm, to, *types, cls)).fetchone()[0])
    boxes = {"sales_standard": bases(("revenue",), "cr", "standard"), "sales_zero": bases(("revenue",), "cr", "zero"), "sales_exempt": bases(("revenue",), "cr", "exempt"),
             "purchases_standard": bases(("expense", "asset"), "dr", "standard"), "purchases_zero": bases(("expense", "asset"), "dr", "zero"),
             "purchases_exempt": bases(("expense", "asset"), "dr", "exempt"), "output_vat": out_v, "input_vat": in_v}
    warns = []
    rent_std = r3(c.execute(f"SELECT COALESCE(SUM(l.credit - l.debit),0) {base} AND a.system_key='rev_rent' AND l.vat_class='standard'", (frm, to)).fetchone()[0])
    if rent_std > EPS and out_v <= EPS:
        warns.append(f"إيراد إيجار تجاري خاضع ({rent_std:,.3f} ر.ع) بلا ضريبة مخرجات مفصولة في الدفاتر — قرار ل29 معلّق؛ لا تُقدَّم هذه القيمة للهيئة دون مراجعة مستشار ضريبي")
    row = c.execute("SELECT * FROM vat_returns WHERE year=? AND quarter=?", (year, q)).fetchone()
    return {"year": year, "quarter": q, "from": frm, "to": to, "output_vat": out_v, "input_vat": in_v, "net": r3(out_v - in_v), "boxes": boxes, "warnings": warns,
            "filed": dict(row) if row else None}


@router.get("/api/acc/vat/{year}/{quarter}")
def api_vat(year: int, quarter: int, _=Depends(need("accounting"))):
    if not 1 <= quarter <= 4:
        raise HTTPException(400, "الربع من 1 إلى 4")
    return vat_compute(db(), year, quarter)


@router.get("/api/acc/vat")
def api_vat_list(_=Depends(need("accounting"))):
    return rows(db().execute("SELECT * FROM vat_returns ORDER BY year DESC, quarter DESC"))


class VatFile(BaseModel):
    ref: str = Field(min_length=3, max_length=80)  # the authority's acknowledgement reference


@router.post("/api/acc/vat/{year}/{quarter}/file")
def api_vat_file(year: int, quarter: int, b: VatFile, u=Depends(act_as("accounting_approve"))):
    """File the quarter: store the figures and post the settlement (output VAT and input VAT cleared against «payable to the authority» / «refundable»)."""
    c = db()
    _active(c)
    if not 1 <= quarter <= 4:
        raise HTTPException(400, "الربع من 1 إلى 4")
    v = vat_compute(c, year, quarter)
    if v["filed"]:
        raise HTTPException(409, "قُدِّم إقرار هذا الربع سابقًا")
    end = dt.date.fromisoformat(v["to"])
    if end >= today():
        raise HTTPException(409, "لا يُقدَّم إقرار ربع لم ينتهِ بعد")
    jid = None
    if abs(v["output_vat"]) > EPS or abs(v["input_vat"]) > EPS:
        lines = []
        if v["output_vat"] > EPS:
            lines.append(dict(account="vat_out", debit=v["output_vat"]))
        elif v["output_vat"] < -EPS:
            lines.append(dict(account="vat_out", credit=-v["output_vat"]))
        if v["input_vat"] > EPS:
            lines.append(dict(account="vat_in", credit=v["input_vat"]))
        elif v["input_vat"] < -EPS:
            lines.append(dict(account="vat_in", debit=-v["input_vat"]))
        net = v["net"]
        lines.append(dict(account="vat_payable", credit=net) if net > EPS else dict(account="vat_refundable", debit=-net))
        jid = _post(c, date=end, lines=lines, memo=f"تسوية ضريبة القيمة المضافة {year}-ر{quarter} — {b.ref}", source_kind="vatfile", source_ref=f"{year}-{quarter}",
                    source_key=f"vat:{year}-{quarter}", by=u["name"], kind="auto")
    c.execute("INSERT INTO vat_returns(year,quarter,output_vat,input_vat,net,box_values,status,filed_on,ref,created_by,journal_id) VALUES(?,?,?,?,?,?,'filed',?,?,?,?)",
              (year, quarter, v["output_vat"], v["input_vat"], v["net"], json.dumps(v["boxes"], ensure_ascii=False), today().isoformat(), b.ref, u["name"], jid))
    audit(c, "إقرار ضريبة القيمة المضافة", f"{year}-ر{quarter} · الصافي {v['net']:,.3f} ر.ع · {b.ref}")
    c.commit()
    return {"journal_id": jid, "net": v["net"]}


# ----------------------------------------------------------------------------------------------------- fixed assets
class AssetIn(BaseModel):
    code: str = Field(min_length=2, max_length=20, pattern=r"^[0-9A-Za-z\-\.]+$")
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(default="", max_length=60)
    cost: float = Field(gt=0, le=1_000_000_000)
    acquired: dt.date
    life_months: int = Field(ge=1, le=600)
    salvage: float = Field(default=0, ge=0)
    cost_center_id: int | None = None
    account_cost: int | str | None = None
    account_accum: int | str | None = None
    account_expense: int | str | None = None
    note: str = Field(default="", max_length=300)


@router.get("/api/acc/assets")
def api_assets(_=Depends(need("accounting"))):
    c = db()
    out = rows(c.execute("""SELECT f.*, COALESCE((SELECT SUM(amount) FROM depreciation_runs d WHERE d.asset_id=f.id),0) accumulated FROM fixed_assets f ORDER BY f.code"""))
    for x in out:
        x["accumulated"] = r3(x["accumulated"])
        x["book_value"] = r3(x["cost"] - x["accumulated"])
        x["monthly"] = r3((x["cost"] - x["salvage"]) / x["life_months"])
    return out


@router.post("/api/acc/assets")
def api_asset_add(b: AssetIn, u=Depends(act_as("accounting_approve"))):
    """Register an asset. The purchase itself is booked by the bill / journal that paid for it; the register only decides how it is written off."""
    c = db()
    _active(c)
    if b.salvage >= b.cost:
        raise HTTPException(400, "القيمة التخريدية يجب أن تقل عن التكلفة")
    if c.execute("SELECT 1 FROM fixed_assets WHERE code=?", (b.code,)).fetchone():
        raise HTTPException(409, "رمز الأصل مستعمل")
    ac = _acct(c, b.account_cost) if b.account_cost else _key_acct(c, "equipment")
    aa = _acct(c, b.account_accum) if b.account_accum else _key_acct(c, "accum_dep")
    ae = _acct(c, b.account_expense) if b.account_expense else _key_acct(c, "exp_depreciation")
    aid = c.execute("""INSERT INTO fixed_assets(code,name,category,cost,acquired,life_months,salvage,cost_center_id,account_cost,account_accum,account_expense,note,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (b.code, b.name, b.category or None, r3(b.cost), b.acquired.isoformat(), b.life_months, r3(b.salvage), b.cost_center_id, ac, aa, ae, b.note or None, u["name"])).lastrowid
    audit(c, "أصل ثابت جديد", f"{b.code} {b.name} · {b.cost:,.3f} ر.ع")
    c.commit()
    return {"id": aid}


class DepRun(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")


def _dep_amount(c, a, period_first: dt.date) -> float:
    """Depreciation of one asset for the month starting `period_first`: none in/before the month of acquisition, never past cost − salvage."""
    acq = dt.date.fromisoformat(a["acquired"])
    if (acq.year, acq.month) >= (period_first.year, period_first.month):
        return 0.0
    done = r3(c.execute("SELECT COALESCE(SUM(amount),0) FROM depreciation_runs WHERE asset_id=?", (a["id"],)).fetchone()[0])
    room = r3(a["cost"] - a["salvage"] - done)
    return r3(min(r3((a["cost"] - a["salvage"]) / a["life_months"]), room)) if room > EPS else 0.0


@router.post("/api/acc/depreciation/run")
def api_dep_run(b: DepRun, u=Depends(act_as("accounting"))):
    """One monthly run (idempotent): assets already run for the period are skipped, so running it twice posts nothing twice."""
    c = db()
    start = _active(c)
    y, m = int(b.period[:4]), int(b.period[5:])
    if not 1 <= m <= 12:
        raise HTTPException(400, "شهر غير صالح")
    first = dt.date(y, m, 1)
    if first > today().replace(day=1):
        raise HTTPException(400, "لا يُشغَّل إهلاك شهر لم يبدأ")
    day = min(dt.date(y, m, calendar.monthrange(y, m)[1]), today())
    if day.isoformat() < start:
        raise HTTPException(400, f"الشهر يسبق بدء المحاسبة ({start})")
    lines, run = [], []
    for a in c.execute("SELECT * FROM fixed_assets WHERE status='active' ORDER BY code").fetchall():
        if c.execute("SELECT 1 FROM depreciation_runs WHERE asset_id=? AND period=?", (a["id"], b.period)).fetchone():
            continue
        amt = _dep_amount(c, a, first)
        if amt <= EPS:
            continue
        run.append((a["id"], amt))
        lines += [dict(account=a["account_expense"], debit=amt, cc=a["cost_center_id"], memo=a["name"]), dict(account=a["account_accum"], credit=amt, cc=a["cost_center_id"], memo=a["name"])]
    if not run:
        return {"period": b.period, "assets": 0, "total": 0.0}
    n = c.execute("SELECT COUNT(*) FROM acc_journals WHERE source_key LIKE ?", (f"dep:{b.period}%",)).fetchone()[0]
    jid = _post(c, date=day, lines=lines, memo=f"إهلاك شهر {b.period}", source_kind="depreciation", source_ref=b.period, source_key=f"dep:{b.period}" + (f":{n + 1}" if n else ""), by=u["name"], kind="auto")
    for aid, amt in run:
        c.execute("INSERT INTO depreciation_runs(period,asset_id,amount,journal_id) VALUES(?,?,?,?)", (b.period, aid, amt, jid))
    audit(c, "تشغيل الإهلاك", f"{b.period} · {len(run)} أصل · {r3(sum(x[1] for x in run)):,.3f} ر.ع")
    c.commit()
    return {"period": b.period, "assets": len(run), "total": r3(sum(x[1] for x in run)), "journal_id": jid}


class Dispose(BaseModel):
    on: dt.date
    proceeds: float = Field(default=0, ge=0, le=1_000_000_000)
    bank_account_id: int | None = None


@router.post("/api/acc/assets/{aid}/dispose")
def api_asset_dispose(aid: int, b: Dispose, u=Depends(act_as("accounting_approve"))):
    """Sell / scrap an asset: cost and accumulated depreciation leave the books, proceeds enter the bank, and the difference is a gain or a loss."""
    c = db()
    start = _active(c)
    a = c.execute("SELECT * FROM fixed_assets WHERE id=? AND status='active'", (aid,)).fetchone()
    if not a:
        raise HTTPException(409, "لا أصل نشط بهذا الرقم")
    if b.on > today() or b.on.isoformat() < max(a["acquired"], start):
        raise HTTPException(400, "تاريخ البيع غير صالح")
    acc = r3(c.execute("SELECT COALESCE(SUM(amount),0) FROM depreciation_runs WHERE asset_id=?", (aid,)).fetchone()[0])
    nbv = r3(a["cost"] - acc)
    lines = [dict(account=a["account_cost"], credit=a["cost"], cc=a["cost_center_id"])]
    if acc > EPS:
        lines.append(dict(account=a["account_accum"], debit=acc, cc=a["cost_center_id"]))
    if b.proceeds > EPS:
        if not b.bank_account_id:
            raise HTTPException(400, "حدّد الحساب البنكي الذي دخلته العوائد")
        bank = c.execute("SELECT account_id FROM bank_accounts WHERE id=? AND active=1", (b.bank_account_id,)).fetchone()
        if not bank:
            raise HTTPException(400, "الحساب البنكي غير موجود")
        lines.append(dict(account=bank["account_id"], debit=b.proceeds))
    diff = r3(b.proceeds - nbv)
    if diff > EPS:
        lines.append(dict(account="gain_disposal", credit=diff))
    elif diff < -EPS:
        lines.append(dict(account="loss_disposal", debit=-diff))
    jid = _post(c, date=b.on, lines=lines, memo=f"بيع/إخراج أصل {a['code']} {a['name']}", source_kind="disposal", source_ref=str(aid), source_key=f"disposal:{aid}", by=u["name"], kind="auto")
    c.execute("UPDATE fixed_assets SET status='disposed', disposed_on=?, proceeds=?, disposal_journal_id=? WHERE id=?", (b.on.isoformat(), r3(b.proceeds), jid, aid))
    audit(c, "إخراج أصل ثابت", f"{a['code']} · القيمة الدفترية {nbv:,.3f} · العوائد {b.proceeds:,.3f}")
    c.commit()
    return {"journal_id": jid, "book_value": nbv, "gain_loss": diff}


# ----------------------------------------------------------------------------------------------------- budgets
class BudgetLine(BaseModel):
    account: int | str
    cost_center_id: int | None = None
    month: int = Field(ge=1, le=12)
    amount: float = Field(ge=0, le=1_000_000_000)


class BudgetIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    lines: list[BudgetLine] = Field(min_length=1, max_length=2000)


@router.post("/api/acc/budgets")
def api_budget_set(b: BudgetIn, u=Depends(act_as("accounting_approve"))):
    """Set (replace) budget cells — one per account × cost centre × month."""
    c = db()
    _active(c)
    n = 0
    for x in b.lines:
        aid = _acct(c, x.account)
        c.execute("DELETE FROM acc_budgets WHERE year=? AND COALESCE(cost_center_id,0)=? AND account_id=? AND month=?", (b.year, x.cost_center_id or 0, aid, x.month))
        if x.amount > 0:
            c.execute("INSERT INTO acc_budgets(year,cost_center_id,account_id,month,amount) VALUES(?,?,?,?,?)", (b.year, x.cost_center_id, aid, x.month, r3(x.amount)))
            n += 1
    audit(c, "موازنة", f"{b.year} · {n} خلية")
    c.commit()
    return {"cells": n}


@router.get("/api/acc/budget-report")
def api_budget_report(year: int, to_month: int = Query(12, ge=1, le=12), cc: int | None = None, _=Depends(need("accounting"))):
    """Budget vs actual up to `to_month`, per account (revenue: actual = credit − debit; expense: debit − credit). Variance is favourable when positive."""
    c = db()
    frm, to = dt.date(year, 1, 1).isoformat(), dt.date(year, to_month, calendar.monthrange(year, to_month)[1]).isoformat()
    bq, bargs = "SELECT account_id, SUM(amount) b FROM acc_budgets WHERE year=? AND month<=?", [year, to_month]
    aq = f"""SELECT l.account_id, SUM(l.debit - l.credit) a FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id WHERE {POSTED} AND j.jdate>=? AND j.jdate<=?
             AND COALESCE(j.source_kind,'')<>'yearclose'"""
    aargs = [frm, to]
    if cc:
        bq += " AND cost_center_id=?"
        bargs.append(cc)
        aq += " AND l.cost_center_id=?"
        aargs.append(cc)
    bud = {r["account_id"]: r["b"] for r in c.execute(bq + " GROUP BY account_id", bargs).fetchall()}
    act = {r["account_id"]: r["a"] for r in c.execute(aq + " GROUP BY l.account_id", aargs).fetchall()}
    out = []
    for a in c.execute("SELECT id, code, name, type FROM acc_accounts WHERE type IN ('revenue','expense') AND postable=1 ORDER BY code").fetchall():
        if a["id"] not in bud and a["id"] not in act:
            continue
        bg = r3(bud.get(a["id"], 0))
        raw = act.get(a["id"], 0) or 0
        ac = r3(raw if a["type"] == "expense" else -raw)
        var = r3(bg - ac) if a["type"] == "expense" else r3(ac - bg)
        out.append({"code": a["code"], "name": a["name"], "type": a["type"], "budget": bg, "actual": ac, "variance": var, "pct": round(100 * ac / bg, 1) if bg > EPS else None})
    return {"year": year, "to_month": to_month, "cost_center": cc, "rows": out,
            "totals": {t: {"budget": r3(sum(x["budget"] for x in out if x["type"] == t)), "actual": r3(sum(x["actual"] for x in out if x["type"] == t))} for t in ("revenue", "expense")}}


# ----------------------------------------------------------------------------------------------------- Islamic financing
class InstallmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    due: dt.date
    amount: float = Field(gt=0, le=1_000_000_000)


class FinanceIn(BaseModel):
    """No rate, no compounding, no variable price: the mark-up is one fixed, known amount. Any extra field (a «rate», a «margin_pct»…) is refused."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["murabaha", "ijara", "installment", "istisna"]
    counterparty: str = Field(min_length=2, max_length=120)
    principal: float = Field(gt=0, le=1_000_000_000)
    markup_total: float = Field(ge=0, le=1_000_000_000)
    start_date: dt.date
    bank_account_id: int
    installments: list[InstallmentIn] = Field(min_length=1, max_length=360)
    note: str = Field(default="", max_length=300)


@router.get("/api/acc/finance")
def api_finance(_=Depends(need("accounting"))):
    c = db()
    out = rows(c.execute("""SELECT f.*, (SELECT COUNT(*) FROM fin_installments i WHERE i.contract_id=f.id) n, (SELECT COUNT(*) FROM fin_installments i WHERE i.contract_id=f.id AND i.paid_on IS NOT NULL) paid_n,
                            (SELECT COALESCE(SUM(amount),0) FROM fin_installments i WHERE i.contract_id=f.id AND i.paid_on IS NULL) remaining FROM fin_contracts f ORDER BY f.id DESC"""))
    for x in out:
        x["remaining"] = r3(x["remaining"])
        x["installments"] = rows(c.execute("SELECT * FROM fin_installments WHERE contract_id=? ORDER BY no", (x["id"],)))
    return out


@router.post("/api/acc/finance")
def api_finance_add(b: FinanceIn, u=Depends(act_as("accounting_approve"))):
    """Record a financing contract and its drawdown: bank ← principal, the known mark-up waits in deferred margin, the liability is principal + mark-up."""
    c = db()
    start = _active(c)
    total = r3(b.principal + b.markup_total)
    if abs(r3(sum(i.amount for i in b.installments)) - total) > EPS:
        raise HTTPException(409, f"مجموع الأقساط يجب أن يساوي الأصل + الهامش ({total:,.3f}) تمامًا")
    if b.start_date.isoformat() < start or b.start_date > today():
        raise HTTPException(400, "تاريخ بدء التمويل غير صالح")
    bank = c.execute("SELECT * FROM bank_accounts WHERE id=? AND active=1", (b.bank_account_id,)).fetchone()
    if not bank:
        raise HTTPException(400, "الحساب البنكي غير موجود")
    ins = sorted(b.installments, key=lambda x: x.due)
    margins, left = [], r3(b.markup_total)
    for i, it in enumerate(ins):
        m = left if i == len(ins) - 1 else r3(b.markup_total * it.amount / total)
        margins.append(m)
        left = r3(left - m)
    lines = [dict(account=bank["account_id"], debit=b.principal), dict(account="islamic_fin_liab", credit=total)]
    if b.markup_total > EPS:
        lines.append(dict(account="fin_deferred_margin", debit=b.markup_total))
    fid = c.execute("INSERT INTO fin_contracts(kind,counterparty,principal,markup_total,start_date,end_date,bank_account_id,note,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
                    (b.kind, b.counterparty, r3(b.principal), r3(b.markup_total), b.start_date.isoformat(), ins[-1].due.isoformat(), b.bank_account_id, b.note or None, u["name"])).lastrowid
    jid = _post(c, date=b.start_date, lines=lines, memo=f"تمويل {b.kind} — {b.counterparty}", source_kind="finance", source_ref=str(fid), source_key=f"fin-draw:{fid}", by=u["name"], kind="auto")
    c.execute("UPDATE fin_contracts SET drawdown_journal_id=? WHERE id=?", (jid, fid))
    for n, (it, m) in enumerate(zip(ins, margins), 1):
        c.execute("INSERT INTO fin_installments(contract_id,no,due,amount,margin) VALUES(?,?,?,?,?)", (fid, n, it.due.isoformat(), r3(it.amount), m))
    audit(c, "عقد تمويل إسلامي", f"{b.kind} · {b.counterparty} · الأصل {b.principal:,.3f} + الهامش {b.markup_total:,.3f}")
    c.commit()
    return {"id": fid, "journal_id": jid, "total": total}


class FinPay(BaseModel):
    paid_on: dt.date | None = None
    bank_account_id: int | None = None


@router.post("/api/acc/finance/{fid}/installments/{no}/pay")
def api_finance_pay(fid: int, no: int, b: FinPay, u=Depends(act_as("accounting"))):
    """Pay one instalment: the liability falls by the instalment, the bank falls, and that instalment's share of the mark-up moves from deferred margin to expense."""
    c = db()
    _active(c)
    f = c.execute("SELECT * FROM fin_contracts WHERE id=?", (fid,)).fetchone()
    i = c.execute("SELECT * FROM fin_installments WHERE contract_id=? AND no=?", (fid, no)).fetchone()
    if not f or not i or i["paid_on"]:
        raise HTTPException(409, "القسط غير موجود أو مسدَّد")
    day = b.paid_on or today()
    if day > today():
        raise HTTPException(400, "تاريخ السداد لا يكون في المستقبل")
    bank = c.execute("SELECT account_id FROM bank_accounts WHERE id=?", (b.bank_account_id or f["bank_account_id"],)).fetchone()
    if not bank:
        raise HTTPException(400, "الحساب البنكي غير موجود")
    lines = [dict(account="islamic_fin_liab", debit=i["amount"]), dict(account=bank["account_id"], credit=i["amount"])]
    if i["margin"] > EPS:
        lines += [dict(account="exp_finance_margin", debit=i["margin"]), dict(account="fin_deferred_margin", credit=i["margin"])]
    jid = _post(c, date=day, lines=lines, memo=f"قسط {no} — تمويل {f['kind']} {f['counterparty']}", source_kind="finance", source_ref=f"{fid}:{no}", source_key=f"fin-pay:{fid}:{no}", by=u["name"], kind="auto")
    c.execute("UPDATE fin_installments SET paid_on=?, payment_journal_id=? WHERE id=?", (day.isoformat(), jid, i["id"]))
    if not c.execute("SELECT 1 FROM fin_installments WHERE contract_id=? AND paid_on IS NULL", (fid,)).fetchone():
        c.execute("UPDATE fin_contracts SET status='closed' WHERE id=?", (fid,))
    audit(c, "سداد قسط تمويل", f"{f['counterparty']} · قسط {no} · {i['amount']:,.3f} ر.ع")
    c.commit()
    return {"journal_id": jid}

