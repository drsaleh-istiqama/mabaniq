"""Mabaniq 0.24.0 — bank statement import and reconciliation, outgoing cheques (design §4.4, phase 3b).

A statement is read by the same safe reader as the lease import (no formulas, size limits) and every line gets a fingerprint, so importing the same file twice
adds nothing. A statement line is matched to ONE ledger line of the bank's own GL account (same signed amount, within a few days); an ambiguous match is left for
a person. The reconciliation of a period closes only when it balances:  book balance = statement balance + ledger items the bank has not shown yet
− bank items the books do not have yet. Nothing is ever auto-posted from the statement — a bank charge or credit not in the books is booked by a journal.
"""
from __future__ import annotations

import datetime as dt
import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from . import ledger
from .acc_ap import _active
from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .importer import read_table

router = APIRouter()
r3 = ledger.r3
EPS = ledger.EPS
WINDOW_DAYS = 5


def _bank(c, bid: int) -> dict:
    b = c.execute("SELECT * FROM bank_accounts WHERE id=?", (bid,)).fetchone()
    if not b:
        raise HTTPException(404, "الحساب البنكي غير موجود")
    return dict(b)


def _num(v, col) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        raise HTTPException(400, f"قيمة غير رقمية في عمود {col}: {v}") from None


@router.post("/api/acc/banks/{bid}/import")
async def api_stmt_import(bid: int, file: UploadFile = File(...), u=Depends(act_as("accounting"))):
    """Add the lines of a bank statement (xlsx/csv: date, description, reference, amount — or debit/credit columns — and optionally the balance)."""
    c = db()
    _active(c)
    _bank(c, bid)
    data = await file.read(5_000_001)
    sha = hashlib.sha256(data).hexdigest()
    table = read_table(file.filename or "", data, "bank_stmt")
    new = dup = 0
    seen: dict[str, int] = {}
    for rn, r in table:
        try:
            day = dt.date.fromisoformat(str(r["date"])[:10])
        except ValueError:
            raise HTTPException(400, f"تاريخ غير صالح في الصف {rn}") from None
        if r.get("amount") not in (None, ""):
            amt = _num(r["amount"], "المبلغ")
        else:  # a statement with a debit (money out) and a credit (money in) column
            amt = r3((_num(r["credit"], "دائن") if r.get("credit") not in (None, "") else 0) - (_num(r["debit"], "مدين") if r.get("debit") not in (None, "") else 0))
        if abs(amt) <= EPS:
            raise HTTPException(400, f"مبلغ صفري أو ناقص في الصف {rn}")
        base = hashlib.sha256(f"{day}|{amt:.3f}|{r.get('reference') or ''}|{r.get('description') or ''}".encode()).hexdigest()[:24]
        seen[base] = seen.get(base, 0) + 1  # two identical lines on one day are two lines — the Nth occurrence has its own key
        key = f"{base}:{seen[base]}"
        if c.execute("SELECT 1 FROM bank_stmt_lines WHERE bank_account_id=? AND import_key=?", (bid, key)).fetchone():
            dup += 1
            continue
        c.execute("INSERT INTO bank_stmt_lines(bank_account_id,line_date,description,reference,amount,balance,import_key,file_sha) VALUES(?,?,?,?,?,?,?,?)",
                  (bid, day.isoformat(), r.get("description"), None if r.get("reference") is None else str(r["reference"]), r3(amt),
                   _num(r["balance"], "الرصيد") if r.get("balance") not in (None, "") else None, key, sha))
        new += 1
    audit(c, "استيراد كشف بنكي", f"{file.filename} · جديد {new} · مكرر {dup}")
    c.commit()
    return {"new": new, "duplicate": dup, "sha256": sha}


def _gl_candidates(c, bank: dict, upto: str | None = None) -> list[dict]:
    """Posted ledger lines of the bank's GL account not yet matched to a statement line — signed: money in positive."""
    q = """SELECT l.id, j.jdate, j.number, COALESCE(l.memo, j.memo) memo, (l.debit - l.credit) amount FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id
           WHERE l.account_id=? AND j.status IN ('posted','reversed') AND NOT EXISTS (SELECT 1 FROM bank_stmt_lines s WHERE s.acc_line_id=l.id)"""
    args: list = [bank["account_id"]]
    if upto:
        q += " AND j.jdate<=?"
        args.append(upto)
    return [dict(x) | {"amount": r3(x["amount"])} for x in c.execute(q + " ORDER BY j.jdate, l.id", args).fetchall()]


@router.get("/api/acc/banks/{bid}/lines")
def api_stmt_lines(bid: int, status: str | None = None, limit: int = Query(300, ge=1, le=1000), _=Depends(need("accounting"))):
    c = db()
    _bank(c, bid)
    q = """SELECT s.*, j.number journal_number FROM bank_stmt_lines s LEFT JOIN acc_lines l ON l.id=s.acc_line_id LEFT JOIN acc_journals j ON j.id=l.journal_id WHERE s.bank_account_id=?"""
    args: list = [bid]
    if status:
        q += " AND s.status=?"
        args.append(status)
    return rows(c.execute(q + " ORDER BY s.line_date DESC, s.id DESC LIMIT ?", (*args, limit)))


@router.post("/api/acc/banks/{bid}/auto-match")
def api_auto_match(bid: int, u=Depends(act_as("accounting"))):
    """Match each unmatched statement line to the one ledger line with the same signed amount within ±5 days. Several equal candidates ⟵ left for a person."""
    c = db()
    bank = _bank(c, bid)
    cands = _gl_candidates(c, bank)
    used: set[int] = set()
    matched = ambiguous = 0
    for s in c.execute("SELECT * FROM bank_stmt_lines WHERE bank_account_id=? AND status='unmatched' ORDER BY line_date, id", (bid,)).fetchall():
        d0 = dt.date.fromisoformat(s["line_date"])
        near = [x for x in cands if x["id"] not in used and abs(x["amount"] - s["amount"]) <= EPS and abs((dt.date.fromisoformat(x["jdate"]) - d0).days) <= WINDOW_DAYS]
        if len(near) == 1:
            c.execute("UPDATE bank_stmt_lines SET acc_line_id=?, status='matched', matched_by=?, matched_at=? WHERE id=?", (near[0]["id"], u["name"], now_s(), s["id"]))
            used.add(near[0]["id"])
            matched += 1
        elif len(near) > 1:
            ambiguous += 1
    audit(c, "مطابقة بنكية آلية", f"{bank['name']} · طابق {matched} · ملتبس {ambiguous}")
    c.commit()
    return {"matched": matched, "ambiguous": ambiguous}


@router.get("/api/acc/banks/{bid}/suggest/{sid}")
def api_suggest(bid: int, sid: int, _=Depends(need("accounting"))):
    """Ledger lines that could match a statement line: the same amount first, then the nearest in date."""
    c = db()
    bank = _bank(c, bid)
    s = c.execute("SELECT * FROM bank_stmt_lines WHERE id=? AND bank_account_id=?", (sid, bid)).fetchone()
    if not s:
        raise HTTPException(404, "سطر الكشف غير موجود")
    d0 = dt.date.fromisoformat(s["line_date"])
    c_ = _gl_candidates(c, bank)
    c_.sort(key=lambda x: (abs(x["amount"] - s["amount"]) > EPS, abs((dt.date.fromisoformat(x["jdate"]) - d0).days)))
    return c_[:15]


class MatchIn(BaseModel):
    acc_line_id: int


@router.post("/api/acc/banks/{bid}/lines/{sid}/match")
def api_match(bid: int, sid: int, b: MatchIn, u=Depends(act_as("accounting"))):
    c = db()
    bank = _bank(c, bid)
    s = c.execute("SELECT * FROM bank_stmt_lines WHERE id=? AND bank_account_id=? AND status<>'matched'", (sid, bid)).fetchone()
    if not s:
        raise HTTPException(409, "سطر الكشف غير موجود أو مطابَق")
    x = next((y for y in _gl_candidates(c, bank) if y["id"] == b.acc_line_id), None)
    if not x:
        raise HTTPException(409, "سطر الدفتر غير متاح للمطابقة (مطابَق أو ليس على هذا الحساب)")
    if abs(x["amount"] - s["amount"]) > EPS:
        raise HTTPException(409, f"المبلغان مختلفان (الكشف {s['amount']:,.3f} · الدفتر {x['amount']:,.3f}) — سجّل الفرق بقيد")
    c.execute("UPDATE bank_stmt_lines SET acc_line_id=?, status='matched', matched_by=?, matched_at=? WHERE id=?", (b.acc_line_id, u["name"], now_s(), sid))
    c.commit()
    return {"ok": True}


@router.post("/api/acc/banks/{bid}/lines/{sid}/unmatch")
def api_unmatch(bid: int, sid: int, u=Depends(act_as("accounting"))):
    c = db()
    _bank(c, bid)
    s = c.execute("SELECT * FROM bank_stmt_lines WHERE id=? AND bank_account_id=? AND status IN ('matched','ignored')", (sid, bid)).fetchone()
    if not s:
        raise HTTPException(409, "لا سطر مطابَق بهذا الرقم")
    if c.execute("SELECT 1 FROM bank_recons WHERE bank_account_id=? AND period_end>=?", (bid, s["line_date"])).fetchone():
        raise HTTPException(409, "السطر داخل مطابقة مغلقة")
    c.execute("UPDATE bank_stmt_lines SET acc_line_id=NULL, status='unmatched', matched_by=NULL, matched_at=NULL WHERE id=?", (sid,))
    c.commit()
    return {"ok": True}


class IgnoreIn(BaseModel):
    note: str = Field(min_length=3, max_length=200)


@router.post("/api/acc/banks/{bid}/lines/{sid}/ignore")
def api_ignore(bid: int, sid: int, b: IgnoreIn, u=Depends(act_as("accounting_approve"))):
    """A statement line that must not be matched (a duplicate the bank sent twice) — needs a reason and a manager."""
    c = db()
    _bank(c, bid)
    if not c.execute("SELECT 1 FROM bank_stmt_lines WHERE id=? AND bank_account_id=? AND status='unmatched'", (sid, bid)).fetchone():
        raise HTTPException(409, "لا سطر غير مطابَق بهذا الرقم")
    c.execute("UPDATE bank_stmt_lines SET status='ignored', note=?, matched_by=?, matched_at=? WHERE id=?", (b.note, u["name"], now_s(), sid))
    c.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- reconciliation of a period
def recon_state(c, bank: dict, end: str, statement_balance: float) -> dict:
    book = r3(c.execute("""SELECT COALESCE(SUM(l.debit - l.credit),0) FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id
                           WHERE l.account_id=? AND j.status IN ('posted','reversed') AND j.jdate<=?""", (bank["account_id"], end)).fetchone()[0])
    in_transit = _gl_candidates(c, bank, end)  # in the books, not (yet) on the statement: deposits in transit / cheques not yet cashed
    not_in_books = rows(c.execute("SELECT * FROM bank_stmt_lines WHERE bank_account_id=? AND status='unmatched' AND line_date<=? ORDER BY line_date", (bank["id"], end)))
    t, n = r3(sum(x["amount"] for x in in_transit)), r3(sum(x["amount"] for x in not_in_books))
    diff = r3(book - (statement_balance + t - n))
    return {"bank_account_id": bank["id"], "period_end": end, "book_balance": book, "statement_balance": r3(statement_balance), "in_transit": t, "not_in_books": n,
            "difference": diff, "balanced": abs(diff) <= EPS, "in_transit_items": in_transit, "not_in_books_items": not_in_books}


@router.get("/api/acc/banks/{bid}/recon")
def api_recon(bid: int, end: str, statement_balance: float, _=Depends(need("accounting"))):
    c = db()
    try:
        dt.date.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "التاريخ غير صالح") from None
    return recon_state(c, _bank(c, bid), end, statement_balance)


class ReconClose(BaseModel):
    end: dt.date
    statement_balance: float


@router.post("/api/acc/banks/{bid}/recon/close")
def api_recon_close(bid: int, b: ReconClose, u=Depends(act_as("accounting_approve"))):
    """Close a reconciliation: only when it balances to the baisa. The matched lines up to that date are then frozen against un-matching."""
    c = db()
    bank = _bank(c, bid)
    st = recon_state(c, bank, b.end.isoformat(), b.statement_balance)
    if not st["balanced"]:
        raise HTTPException(409, f"المطابقة لا تتوازن (الفرق {st['difference']:,.3f}) — سجّل ما ينقص في الدفاتر أو طابق ما تبقّى")
    if c.execute("SELECT 1 FROM bank_recons WHERE bank_account_id=? AND period_end=?", (bid, b.end.isoformat())).fetchone():
        raise HTTPException(409, "أُغلقت مطابقة هذا التاريخ")
    c.execute("INSERT INTO bank_recons(bank_account_id,period_end,statement_balance,book_balance,in_transit,not_in_books,difference,closed_by,closed_at) VALUES(?,?,?,?,?,?,?,?,?)",
              (bid, b.end.isoformat(), st["statement_balance"], st["book_balance"], st["in_transit"], st["not_in_books"], st["difference"], u["name"], now_s()))
    audit(c, "إغلاق مطابقة بنكية", f"{bank['name']} · حتى {b.end}")
    c.commit()
    return {"ok": True}


@router.get("/api/acc/banks/{bid}/recons")
def api_recons(bid: int, _=Depends(need("accounting"))):
    c = db()
    _bank(c, bid)
    return rows(c.execute("SELECT * FROM bank_recons WHERE bank_account_id=? ORDER BY period_end DESC", (bid,)))


# ----------------------------------------------------------------------------------------------------- outgoing cheques
@router.get("/api/acc/cheques-out")
def api_cheques_out(_=Depends(need("accounting"))):
    return rows(db().execute("""SELECT q.id, q.number, q.bank, q.amount, q.due_date, q.received_on issued_on, q.cleared_on, q.status, q.payee, q.vendor_id FROM cheques q
                                WHERE q.direction='out' ORDER BY q.id DESC LIMIT 300"""))


class ClearedIn(BaseModel):
    on: dt.date | None = None


@router.post("/api/acc/cheques-out/{cid}/cleared")
def api_cheque_cleared(cid: int, b: ClearedIn, u=Depends(act_as("accounting"))):
    """The bank paid an issued cheque. The books already carry the payment from the day it was issued; this records only that it left the account."""
    c = db()
    q = c.execute("SELECT * FROM cheques WHERE id=? AND direction='out' AND status='issued'", (cid,)).fetchone()
    if not q:
        raise HTTPException(409, "لا شيك صادر بهذه الحالة")
    day = b.on or today()
    if day > today():
        raise HTTPException(400, "تاريخ الصرف لا يكون في المستقبل")
    c.execute("UPDATE cheques SET status='cleared', cleared_on=? WHERE id=?", (day.isoformat(), cid))
    audit(c, "صرف شيك صادر", f"{q['number']} · {q['amount']:,.3f} ر.ع")
    c.commit()
    return {"ok": True}
