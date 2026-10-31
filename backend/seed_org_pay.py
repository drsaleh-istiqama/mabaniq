"""Mabaniq 0.29.0 — the `pay` phase of the demo organisation (backend/seed_org.py): salaries and six closed months of payroll.

Rates and the end-of-service rule are entered the way an administrator would (with a source note that says they are trial defaults), every employee gets a salary structure
from the day of the hire, and then the months are walked in order: adjustments → loans → a run created and computed by one payroll officer, approved by the other, and paid
from a bank account. The month in progress is computed and left waiting for its approval, and the leaver of the organisation is settled (end-of-service, remaining loan
instalments) before that run is built so he is not in it.

Order matters and mirrors production: a salary change dated inside a month that is already approved is refused by the platform, so a raise is entered after the previous
month is frozen and before its own month is computed. Whatever a rule refuses is skipped and counted (`ctx.tryc`), never forced.
"""
from __future__ import annotations

import calendar
import datetime as dt

from . import hr_end, hr_payroll
from .common import db
from .seed_org import Ctx
from .seed_org_data import ORGS
from .seed_org_hr import _as, _q

SRC_RATE = "افتراضي للتجربة — تُراجَع المعدلات النظامية للتأمينات الاجتماعية مع صندوق الحماية الاجتماعية قبل أي تشغيل فعلي"
SRC_EOSB = "قاعدة افتراضية للتجربة (15 يومًا من الأجر الأساسي عن كل سنة من أول ثلاث سنوات ثم 30 يومًا عن كل سنة بعدها) — يؤكدها مختص بقانون العمل قبل الاعتماد الفعلي"
SALES_NAMES = {"bayan": "عمولة مبيعات وتأجير", "almukhatat": "عمولة مبيعات"}


def _months(today: dt.date, n: int = 6) -> list[str]:
    first = today.replace(day=1)
    out = []
    for i in range(n, 0, -1):
        y, m = first.year, first.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        out.append(f"{y}-{m:02d}")
    return out


def _last_day(period: str) -> dt.date:
    y, m = int(period[:4]), int(period[5:])
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def run(ctx: Ctx) -> None:
    P = ORGS[ctx.tenant]
    ctx.act("payroll_a")
    _rates(ctx)
    emps = _all_emps(ctx)
    _structures(ctx, P, emps)
    _loans_pending(ctx, P, emps)
    months = _months(ctx.today)
    bank = _bank(ctx)
    _run_months(ctx, P, emps, months, bank)
    _settle(ctx, P, emps, bank)
    cur = f"{ctx.today.year}-{ctx.today.month:02d}"
    _request_loans(ctx, bank, cur)
    _adjustments(ctx, P, emps, cur, 6)
    _month_run(ctx, cur, bank, finish=False)
    ctx.add("closed_months", len(months))


def _request_loans(ctx: Ctx, bank, cur: str) -> None:
    """An advance the HR officer approved is handed to payroll: turn each approved, still-open advance request into a loan (payroll officer proposes, the other approves)."""
    a, b = _as(ctx.user("payroll_a")), ctx.user("payroll_b")
    for rq in _q(ctx, "SELECT id, employee_id, amount, details FROM hr_requests WHERE kind='advance' AND status='approved' AND amount IS NOT NULL"):
        if _q(ctx, "SELECT 1 FROM employee_loans WHERE request_id=?", (rq["id"],)):
            continue
        r = ctx.tryc(hr_payroll.api_loan_add, hr_payroll.LoanIn(employee_id=rq["employee_id"], kind="advance", amount=float(rq["amount"]), installments=3, start_period=cur,
                                                                reason=(rq.get("details") or "سلفة بطلب موظف")[:190], request_id=rq["id"]), u=a)
        if r:
            ctx.add("request_loans")
            ctx.tryc(hr_payroll.api_loan_approve, r["id"], hr_payroll.LoanApprove(disbursed_on=ctx.today.isoformat(), bank_account_id=bank), u=_as(b))


# ----------------------------------------------------------------------------------------------------------------------- helpers
def _all_emps(ctx: Ctx) -> dict:
    return {r["name"]: r for r in _q(ctx, "SELECT * FROM employees")}


def _bank(ctx: Ctx):
    r = _q(ctx, "SELECT id FROM bank_accounts WHERE active=1 ORDER BY id LIMIT 1")
    return r[0]["id"] if r else None


def _rates(ctx: Ctx) -> None:
    u = _as(ctx.user("payroll_a"))
    y = ctx.today.year
    with ctx.request():
        c = db()
        hr_payroll.ensure_setup(c)
    cur = {r["key"] for r in _q(ctx, "SELECT key FROM hr_rates WHERE value IS NOT NULL AND provisional=0")}
    for key, val in (("pasi_employee_pct", 7.0), ("pasi_employer_pct", 11.5), ("pasi_ceiling", 3000.0)):
        if key not in cur:
            ctx.tryc(hr_payroll.api_rate_add, hr_payroll.RateIn(key=key, value=val, valid_from=f"{y - 1}-01-01", note=SRC_RATE), u=u)
    if not _q(ctx, "SELECT 1 FROM eosb_rules LIMIT 1"):
        ctx.tryc(hr_end.api_rule_add, hr_end.RuleIn(grp="expat", valid_from=f"{y - 1}-01-01", tiers=[hr_end.TierIn(to_years=3, days_per_year=15), hr_end.TierIn(to_years=None, days_per_year=30)],
                                                     note=SRC_EOSB), u=u)


def _structures(ctx: Ctx, P: dict, emps: dict) -> None:
    u = _as(ctx.user("payroll_a"))
    comp = {r["key"]: r["id"] for r in _q(ctx, "SELECT id, key FROM pay_components")}
    have = {r["employee_id"] for r in _q(ctx, "SELECT DISTINCT employee_id FROM salary_structures")}
    rows = [(row[1], row[12], row[13], row[14]) for row in P["employees"]]
    hc = P["hire_candidate"]
    rows.append((hc[0], hc[4], hc[5], hc[6]))
    for name, basic, housing, transport in rows:
        e = emps.get(name)
        if not e or e["id"] in have:
            continue
        lines = [hr_payroll.LineIn(component_id=comp["housing"], amount=housing)] if housing else []
        if transport:
            lines.append(hr_payroll.LineIn(component_id=comp["transport"], amount=transport))
        if ctx.tryc(hr_payroll.api_structure_add, hr_payroll.StructureIn(employee_id=e["id"], effective_from=e["hire_date"], basic=float(basic), lines=lines, note="هيكل الراتب عند التعيين"), u=u):
            ctx.add("structures")


def _adjustments(ctx: Ctx, P: dict, emps: dict, period: str, idx: int) -> None:
    """The one-off earnings and deductions of a month: commissions for the sales side, a site allowance, a little overtime, two bonuses, a couple of small deductions."""
    u = _as(ctx.user("payroll_a"))
    rnd = ctx.rnd
    dept_of = {r["id"]: k for k, n in P["departments"] for r in _q(ctx, "SELECT id FROM departments WHERE name=?", (n,))}
    end = _last_day(period)
    for row in P["employees"]:
        e = emps.get(row[1])
        if not e or dt.date.fromisoformat(e["hire_date"]) > end or (e["terminated_on"] and e["terminated_on"] < period + "-01"):
            continue
        d = dept_of.get(e["department_id"])
        have_struct = _q(ctx, "SELECT 1 FROM salary_structures WHERE employee_id=? AND effective_from<=?", (e["id"], end.isoformat()))
        if not have_struct:
            continue
        add = lambda kind, name, amount, note="": ctx.tryc(hr_payroll.api_adjustment_add, hr_payroll.AdjIn(employee_id=e["id"], period=period, kind=kind, name=name, amount=round(amount, 3), note=note), u=u)  # noqa: E731, B023
        if d == "sales" and row[0] != P["leaver"] and rnd.random() < .75:
            add("earning", SALES_NAMES[ctx.tenant], rnd.randint(60, 380), "عمولة على الصفقات المغلقة خلال الشهر")
        if d == "proj" and "مراقب" in row[7]:
            add("earning", "بدل موقع", 45, "بدل العمل في مواقع المشاريع")
        if d in ("hr", "cx", "fin") and rnd.random() < .22:
            add("earning", "عمل إضافي", rnd.randint(15, 60), "ساعات إضافية معتمدة من المدير")
        if idx == 2 and row[0] in ("acc1", "eng2", "sale1") and rnd.random() < .9:
            add("earning", "مكافأة إنجاز", rnd.randint(120, 250), "مكافأة إنجاز مرحلة")
        if idx in (3, 4) and row[0] in ("driver", "recep", "clean", "book", "pro") and rnd.random() < .8:
            add("deduction", "استقطاع مكالمات شخصية", 8, "قيمة المكالمات الشخصية على هاتف الشركة")


def _loans_pending(ctx: Ctx, P: dict, emps: dict) -> None:
    """Loans are created now and approved month by month (see `_run_months`): remember them by name in a small table of intentions."""
    ctx._loans = []   # (creates_at_month_index, employee name, kind, amount, installments, reason)
    leaver = next(r for r in P["employees"] if r[0] == P["leaver"])
    senior = next(r for r in P["employees"] if r[0] == "pmgr")
    other = next(r for r in P["employees"] if r[0] in ("recep", "book"))
    ctx._loans = [(0, leaver[1], "advance", 400.0, 8, "سلفة لظرف عائلي طارئ"), (1, senior[1], "qard_hasan", 2400.0, 24, "قرض حسن لشراء مسكن — بلا أي زيادة على المبلغ"),
                  (2, other[1], "advance", 240.0, 4, "سلفة لسداد رسوم دراسية")]


def _run_loans(ctx: Ctx, emps: dict, idx: int, month: str, bank) -> None:
    a, b = _as(ctx.user("payroll_a")), ctx.user("payroll_b")
    for at, name, kind, amount, n, reason in getattr(ctx, "_loans", []):
        e = emps.get(name)
        if at != idx or not e or _q(ctx, "SELECT 1 FROM employee_loans WHERE employee_id=? AND reason=?", (e["id"], reason)):
            continue
        start = hr_payroll._next_period(month, 1)
        r = ctx.tryc(hr_payroll.api_loan_add, hr_payroll.LoanIn(employee_id=e["id"], kind=kind, amount=amount, installments=n, start_period=month if idx == 0 else start, reason=reason), u=a)
        if r:
            ctx.add("loans")
            ctx.tryc(hr_payroll.api_loan_approve, r["id"], hr_payroll.LoanApprove(disbursed_on=f"{month}-12", bank_account_id=bank), u=_as(b))


def _month_run(ctx: Ctx, period: str, bank, finish: bool) -> None:
    a, b = ctx.user("payroll_a"), ctx.user("payroll_b")
    r = _q(ctx, "SELECT id, status FROM payroll_runs WHERE period=?", (period,))
    if r:
        rid, status = r[0]["id"], r[0]["status"]
    else:
        out = ctx.tryc(hr_payroll.api_run_add, hr_payroll.RunIn(period=period), u=_as(a))
        if not out:
            return
        rid, status = out["id"], "draft"
    if status in ("draft", "computed"):
        if not ctx.tryc(hr_payroll.api_compute, rid, u=_as(a)):
            return
        status = "computed"
    if not finish:
        return
    if status == "computed":
        # the approver refreshes the run and refuses once if anything changed since the compute; a second try then passes
        ok = ctx.tryc(hr_payroll.api_approve, rid, 1, u=_as(b)) or ctx.tryc(hr_payroll.api_approve, rid, 1, u=_as(b))
        if not ok:
            return
        status = "approved"
    if status == "approved":
        paid_on = min(dt.date(int(period[:4]), int(period[5:]), 25), ctx.today).isoformat()
        if ctx.tryc(hr_payroll.api_pay, rid, hr_payroll.PayIn(paid_on=paid_on, bank_account_id=bank), u=_as(b)):
            ctx.add("runs_paid")


def _run_months(ctx: Ctx, P: dict, emps: dict, months: list[str], bank) -> None:
    raise_month = months[-1]
    raise_keys = P["raises"]
    names = {row[0]: row[1] for row in P["employees"]}
    comp = {r["key"]: r["id"] for r in _q(ctx, "SELECT id, key FROM pay_components")}
    u = _as(ctx.user("payroll_a"))
    for idx, month in enumerate(months):
        if month == raise_month:   # a raise dated in the last closed month, entered after the month before was frozen
            for k in raise_keys:
                e = emps.get(names.get(k, ""))
                row = next((r for r in P["employees"] if r[0] == k), None)
                if e and row and not _q(ctx, "SELECT 1 FROM salary_structures WHERE employee_id=? AND effective_from=?", (e["id"], month + "-01")):
                    nb = round(row[12] * 1.08 / 5) * 5
                    lines = [hr_payroll.LineIn(component_id=comp["housing"], amount=row[13])] if row[13] else []
                    if row[14]:
                        lines.append(hr_payroll.LineIn(component_id=comp["transport"], amount=row[14]))
                    ctx.tryc(hr_payroll.api_structure_add, hr_payroll.StructureIn(employee_id=e["id"], effective_from=month + "-01", basic=float(nb), lines=lines,
                                                                                 note="زيادة سنوية بحسب نتيجة تقييم الأداء"), u=u)
        _adjustments(ctx, P, emps, month, idx)
        _run_loans(ctx, emps, idx, month, bank)
        _month_run(ctx, month, bank, finish=True)


def _settle(ctx: Ctx, P: dict, emps: dict, bank) -> None:
    """The leaver: a draft settlement by one officer, the clearance ticked, the approval of the other (which ends the service), and the payment."""
    if _q(ctx, "SELECT 1 FROM terminations LIMIT 1"):
        return
    row = next(r for r in P["employees"] if r[0] == P["leaver"])
    e = emps.get(row[1])
    if not e:
        return
    end = ctx.today.replace(day=1) - dt.timedelta(days=1)
    a, b = ctx.user("payroll_a"), ctx.user("payroll_b")
    t = ctx.tryc(hr_end.api_term_add, hr_end.TermIn(employee_id=e["id"], end_date=end.isoformat(), kind="resignation", note="استقالة بإشعار مدته شهر وفق العقد", other_dues=0, other_deductions=0), u=_as(a))
    if not t:
        return
    tid = t["id"]
    cur = ctx.tryc(hr_end.api_term, tid, u=_as(a))
    if cur:
        ctx.tryc(hr_end.api_term_recalc, tid, hr_end.TermEdit(clearance=[{"item": x["item"], "done": True} for x in cur["clearance"]]), u=_as(a))
    if ctx.tryc(hr_end.api_term_approve, tid, u=_as(b)):
        ctx.tryc(hr_end.api_term_pay, tid, hr_end.TermPay(paid_on=(ctx.today - dt.timedelta(days=10)).isoformat(), bank_account_id=bank), u=_as(b))
        ctx.add("settlements")
