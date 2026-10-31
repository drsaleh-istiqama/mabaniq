"""Mabaniq 0.29.0 — the books of a full-demo developer (phases `acc_base` and `acc_ops` of backend/seed_org.py).

Everything goes through the accounting module's own endpoints functions as synthetic staff users (see seed_org.py): the accountant drafts, the administrator approves
(maker ≠ checker is the module's rule, kept), a payment order above the dual-control limit gets two different approvers, nothing is written into the ledger tables
directly. Two reference tables with no logic of their own are written with plain SQL: the bank statement lines (an *import*, as the real flow reads a file) and the
first bank-account row (so the main current account is the first one, which is where payroll takes its money from).

`run_base` — before HR and payroll: the chart, accounting activated from 1 January of the current year, an opening balance, cost centres (one per project is made by the
activation itself, plus the company's departments), bank accounts (Islamic only), suppliers.
`run_ops` — after payroll and leasing: supplier bills with approval and payment, fixed assets and their depreciation, the year's budget, manual journals in every state,
Islamic financing contracts with instalments, the leasing sweep into the ledger, a closed bank reconciliation, VAT returns, and the closing of the old months.

All figures are illustrative ("افتراضي للتجربة"). No interest anywhere: financing is murabaha / ijara with a fixed mark-up.
"""
from __future__ import annotations

import calendar
import datetime as dt
import inspect

R3 = 3
DEMO = "افتراضي للتجربة"

# ----------------------------------------------------------------------------------------------------------------------- data
_PROFILE = {
    # opening balance (bank, investment property, capital, retained earnings), amount scale, supplier names (maintenance, cleaning, security, AC/electrical, marketing, audit, IT, furniture, vehicles)
    "bayan": dict(scale=1.0, bank=185000.0, prop=640000.0, capital=700000.0, retained=125000.0,
                  vendors=[("شركة الإتقان للصيانة والمقاولات", "صيانة عامة"), ("مؤسسة نقاء للنظافة", "نظافة"), ("شركة الدرع لخدمات الأمن والحراسة", "أمن وحراسة"),
                           ("مؤسسة تيار لأعمال الكهرباء والتكييف", "كهرباء وتكييف"), ("شركة الأفق للإعلان والتسويق", "تسويق وإعلان"), ("مكتب الميزان للتدقيق والمحاسبة", "أتعاب مهنية"),
                           ("شركة المدار لتقنية المعلومات", "أنظمة وأجهزة"), ("مؤسسة الواحة لتوريد الأثاث المكتبي", "أثاث ومعدات"), ("مؤسسة الصدارة لبيع المركبات", "مركبات")]),
    "almukhatat": dict(scale=0.8, bank=160000.0, prop=520000.0, capital=600000.0, retained=80000.0,
                       vendors=[("شركة الرواد للصيانة والمقاولات", "صيانة عامة"), ("مؤسسة نظافة المدينة", "نظافة"), ("شركة الحصن للأمن والحراسة", "أمن وحراسة"),
                                ("مؤسسة سلام لأعمال السباكة والتكييف", "سباكة وتكييف"), ("شركة بريق للتسويق والإعلان", "تسويق وإعلان"), ("مكتب المنار للتدقيق والمحاسبة", "أتعاب مهنية"),
                                ("شركة ربط لتقنية المعلومات", "أنظمة وأجهزة"), ("مؤسسة الإتقان للأثاث والمعدات", "أثاث ومعدات"), ("معرض النخبة للسيارات", "مركبات")]),
}
DEPT_CC = [("G-ADM", "الإدارة العامة"), ("D-SAL", "المبيعات والتسويق"), ("D-HRM", "الموارد البشرية والشؤون الإدارية"), ("D-FIN", "المالية والمحاسبة"),
           ("D-ENG", "الهندسة والمشاريع"), ("D-LEA", "التأجير وإدارة الأملاك")]

# bills: (day offset from the accounting start, vendor index, lines [(account, base amount, cost centre: "P1"/"P2"/dept code, description)], vat, ref, payment, asset)
# payment: None (left open) | ("full"|"half", method, days after the bill) | ("dual", ...)
BILLS = [
    (12, 3, [("5110", 1380.0, "P1", "عقد صيانة أنظمة التكييف — الربع الأول")], "standard", "INV-1041", ("full", "transfer", 25), None),
    (20, 1, [("5120", 590.0, "P1", "نظافة المرافق المشتركة — الربع الأول"), ("5120", 440.0, "P2", "نظافة المرافق المشتركة — الربع الأول")], "standard", "INV-3307", ("full", "transfer", 20), None),
    (33, 2, [("5140", 2250.0, "P1", "خدمة الحراسة والأمن — الربع الأول")], "standard", "INV-2208", ("full", "transfer", 30), None),
    (41, 5, [("5250", 1200.0, "G-ADM", "أتعاب تدقيق الحسابات السنوية")], "standard", "INV-0092", ("full", "transfer", 14), None),
    (58, 6, [("1520", 1980.0, "G-ADM", "أجهزة حاسب محمولة وملحقاتها (6 أجهزة)")], "standard", "INV-5516", ("full", "transfer", 10), ("FA-001", "أجهزة حاسب محمولة", "أجهزة وأنظمة", 36, 0.0)),
    (73, 7, [("1520", 2640.0, "G-ADM", "أثاث مكتبي لمقر الإدارة")], "standard", "INV-7124", ("full", "cheque", 21), ("FA-002", "أثاث مكتبي — مقر الإدارة", "أثاث ومعدات", 60, 0.0)),
    (84, 8, [("1520", 9500.0, "G-ADM", "سيارة خدمة للمشاريع (دفع نقدي بالتحويل)")], "standard", "INV-8801", ("full", "transfer", 5), ("FA-003", "سيارة خدمة للمشاريع", "مركبات", 60, 1500.0)),
    (96, 4, [("5220", 3100.0, "D-SAL", "حملة إطلاق المرحلة الثانية — إعلانات خارجية ورقمية")], "standard", "INV-6603", ("full", "transfer", 28), None),
    (121, 3, [("5110", 1380.0, "P1", "عقد صيانة أنظمة التكييف — الربع الثاني")], "standard", "INV-1098", ("full", "transfer", 22), None),
    (135, 1, [("5120", 590.0, "P1", "نظافة المرافق المشتركة — الربع الثاني"), ("5120", 440.0, "P2", "نظافة المرافق المشتركة — الربع الثاني")], "standard", "INV-3361", ("full", "transfer", 18), None),
    (150, 2, [("5140", 2250.0, "P1", "خدمة الحراسة والأمن — الربع الثاني")], "standard", "INV-2263", ("full", "transfer", 26), None),
    (168, 3, [("5110", 2860.0, "P2", "تركيب مولد احتياطي للمرافق المشتركة")], "standard", "INV-1144", ("half", "transfer", 15), None),
    (190, 4, [("5220", 6300.0, "D-SAL", "حملة موسم الصيف — لوحات وإعلانات رقمية وفعاليات")], "standard", "INV-6671", ("dual", "transfer", 12), None),
    (215, 1, [("5120", 1060.0, "P1", "نظافة المرافق المشتركة — الربع الثالث")], "standard", "INV-3410", ("full", "transfer", 16), None),
    (232, 2, [("5140", 2250.0, "P1", "خدمة الحراسة والأمن — الربع الثالث")], "standard", "INV-2317", None, None),
    (255, 3, [("5110", 1380.0, "P1", "عقد صيانة أنظمة التكييف — الربع الثالث")], "standard", "INV-1190", None, None),
    (268, 5, [("5250", 850.0, "G-ADM", "استشارة ضريبية وقانونية")], "standard", "INV-0131", None, None),
    (9999, 6, [("5230", 640.0, "G-ADM", "اشتراك سنوي في خدمات سحابية وبرمجيات")], "zero", "INV-5588", None, None),
]
# manual journals: (day offset, memo, [(account, debit, credit)], state) — state: "approved" | "pending" | "draft"
JOURNALS = [
    (27, "رسوم بنكية وعمولات حوالات — الربع الأول", [("5230", 38.5, 0), ("1121", 0, 38.5)], "approved"),
    (44, "رسوم تجديد السجل التجاري وتراخيص النشاط", [("5230", 195.0, 0), ("1121", 0, 195.0)], "approved"),
    (6, "قسط تكافل المباني السنوي مدفوعًا مقدمًا", [("1250", 900.0, 0), ("1121", 0, 900.0)], "approved"),
    (160, "عمولة إدارة أملاك محصَّلة عن وحدات مالك خارجي", [("1121", 460.0, 0), ("4130", 0, 460.0)], "approved"),
    (205, "رسوم بنكية وعمولات حوالات — الربع الثاني", [("5230", 41.25, 0), ("1121", 0, 41.25)], "approved"),
    (240, "إطفاء جزء من التكافل المدفوع مقدمًا — تسعة أشهر", [("5150", 675.0, 0), ("1250", 0, 675.0)], "approved"),
    # unit sales are not posted to the books automatically yet (docs: sales ledger link is an open decision) — the demo books carry the sold units' revenue as dated manual entries so the profit and loss is not only rent against payroll
    (42, "إثبات إيراد مبيعات وحدات — دفعة فبراير (قيد يدوي لحين ربط المبيعات بالدفاتر)", [("1121", 58500.0, 0), ("4120", 0, 58500.0)], "approved"),
    (88, "إثبات إيراد مبيعات وحدات — دفعة مارس (قيد يدوي لحين ربط المبيعات بالدفاتر)", [("1121", 61250.0, 0), ("4120", 0, 61250.0)], "approved"),
    (131, "إثبات إيراد مبيعات وحدات — دفعة مايو (قيد يدوي لحين ربط المبيعات بالدفاتر)", [("1121", 47800.0, 0), ("4120", 0, 47800.0)], "approved"),
    (176, "إثبات إيراد مبيعات وحدات — دفعة يونيو (قيد يدوي لحين ربط المبيعات بالدفاتر)", [("1121", 69300.0, 0), ("4120", 0, 69300.0)], "approved"),
    (221, "إثبات إيراد مبيعات وحدات — دفعة أغسطس (قيد يدوي لحين ربط المبيعات بالدفاتر)", [("1121", 52900.0, 0), ("4120", 0, 52900.0)], "approved"),
    (-4, "ضيافة وفعاليات تسويقية — بانتظار الاعتماد", [("5220", 275.0, 0), ("1121", 0, 275.0)], "pending"),
    (-2, "تسوية فروقات صندوق المصروفات النثرية — مسودة", [("5230", 12.25, 0), ("1110", 0, 12.25)], "draft"),
]


# ----------------------------------------------------------------------------------------------------------------------- helpers
def _kw(fn, u):
    return {"u": u} if "u" in inspect.signature(fn).parameters else {"_": u}


def _do(ctx, key, fn, *a):
    """Call an endpoint function as the synthetic user `key`; a refusal is counted and returns None."""
    return ctx.tryc(fn, *a, **_kw(fn, ctx.act(key)))


def _rows(ctx, sql, args=()):
    with ctx.request():
        c = ctx.conn()
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def _one(ctx, sql, args=()):
    r = _rows(ctx, sql, args)
    return r[0] if r else None


def _exec(ctx, sql, args=()):
    with ctx.request():
        c = ctx.conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def _addm(d: dt.date, m: int) -> dt.date:
    y, mo = divmod(d.month - 1 + m, 12)
    y, mo = d.year + y, mo + 1
    return dt.date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def _start(ctx) -> dt.date:
    return dt.date(ctx.today.year, 1, 1)


def _at(ctx, off: int) -> dt.date:
    """A day `off` days after the accounting start, never in the future (a negative offset counts back from today)."""
    s, t = _start(ctx), ctx.today
    d = t + dt.timedelta(days=off) if off < 0 else s + dt.timedelta(days=min(off, max((t - s).days - 2, 0)))
    return min(max(d, s), t)


def _m(x: float, scale: float) -> float:
    return round(x * scale, 3)


def _tp(ctx) -> dict:
    return _PROFILE.get(ctx.tenant, _PROFILE["bayan"])


def _admin2(ctx) -> dict:
    """The second approver of a payment order above the dual-control limit (the module requires two different people, none of them the creator)."""
    from .common import ACTOR
    u = dict(ctx.user("admin"), username="seed.admin2", name="نائب المدير العام")
    ACTOR.set(f"{u['name']} ({u['role_label']})")
    return u


def _projects(ctx) -> list[dict]:
    return _rows(ctx, "SELECT id, code, name, kind FROM projects ORDER BY id")


def _cc(ctx, ref: str, plist: list[dict]) -> int | None:
    """Cost centre id for "P1"/"P2" (the first two projects of the developer) or a department code."""
    if ref in ("P1", "P2"):
        p = plist[min(int(ref[1]) - 1, len(plist) - 1)]
        r = _one(ctx, "SELECT id FROM acc_cost_centers WHERE kind='project' AND ref_id=?", (p["id"],))
    else:
        r = _one(ctx, "SELECT id FROM acc_cost_centers WHERE code=?", (ref,))
    return r["id"] if r else None


# ----------------------------------------------------------------------------------------------------------------------- phase 1: base
def run_base(ctx) -> dict:
    from . import acc_ap, accounting, ledger
    p = _tp(ctx)
    start = _start(ctx)
    # the chart exists and the main current account is registered FIRST (the leasing/payroll code takes "the first active bank account")
    with ctx.request():
        c = ctx.conn()
        ledger.ensure_chart(c)
        main = c.execute("SELECT id FROM acc_accounts WHERE system_key='bank_main'").fetchone()
        if main and not c.execute("SELECT 1 FROM bank_accounts WHERE account_id=?", (main["id"],)).fetchone():
            c.execute("INSERT INTO bank_accounts(name,bank,kind,account_id,note) VALUES(?,?,?,?,?)",
                      ("الحساب الجاري الرئيسي — بنك نزوى (نافذة إسلامية)", "بنك نزوى", "bank", main["id"], DEMO))
        c.commit()
    with ctx.request():
        c = ctx.conn()
        active = ledger.start_date(c)
    if not active:
        _do(ctx, "admin", accounting.api_activate, accounting.ActivateIn(start=start, confirm=True))
        ctx.add("activated")
    if not _one(ctx, "SELECT 1 x FROM acc_journals WHERE kind='opening' AND status='posted'"):
        r = _do(ctx, "admin", accounting.api_opening, accounting.OpeningIn(
            lines=[accounting.OpeningLine(code="1121", debit=p["bank"]), accounting.OpeningLine(code="1510", debit=p["prop"]),
                   accounting.OpeningLine(code="3100", credit=p["capital"]), accounting.OpeningLine(code="3300", credit=p["retained"])],
            source=f"ميزان افتتاحي {DEMO} — لا يمثّل أرصدة فعلية"))
        ctx.add("opening", 1 if r else 0)
    for code, name in DEPT_CC:
        if not _one(ctx, "SELECT 1 x FROM acc_cost_centers WHERE code=?", (code,)):
            _do(ctx, "admin", accounting.api_cc_add, accounting.CostCenterIn(code=code, name=name, kind="dept"))
            ctx.add("cost_centers")
    plist = _projects(ctx)
    banks = [("حساب التحصيل — ميثاق للصيرفة الإسلامية", "ميثاق للصيرفة الإسلامية", "bank", None)]
    sel = next((x for x in plist if x["kind"] == "tower" and x["code"] not in ("QRM", "AMR")), plist[0])
    banks.append((f"حساب الضمان — {sel['name']}", "بنك نزوى", "escrow", sel["id"]))
    for name, bank, kind, pid in banks:
        if not _one(ctx, "SELECT 1 x FROM bank_accounts WHERE name=?", (name,)):
            _do(ctx, "admin", acc_ap.api_bank_add, acc_ap.BankIn(name=name, bank=bank, kind=kind, islamic=True, project_id=pid))
            ctx.add("banks")
    for i, (name, trade) in enumerate(p["vendors"]):
        if not _one(ctx, "SELECT 1 x FROM vendors WHERE name=?", (name,)):
            _do(ctx, "accountant", acc_ap.api_vendor_add, acc_ap.VendorIn(name=name, trade=trade, cr_number=str(1140000 + 137 * (i + 1) + len(ctx.tenant) * 11),
                                                                           tax_no=f"OM{1100000 + 311 * (i + 1)}", phone=f"2451{2000 + 37 * i:04d}", email=""))
            ctx.add("vendors")
    return ctx.counts


# ----------------------------------------------------------------------------------------------------------------------- phase 2: operations
def _bills(ctx, p, plist):
    from . import acc_ap, acc_assets
    vend = {i: r for i, (n, _t) in enumerate(p["vendors"]) if (r := _one(ctx, "SELECT id FROM vendors WHERE name=?", (n,)))}
    bank = _one(ctx, "SELECT id FROM bank_accounts WHERE kind='bank' AND active=1 ORDER BY id")
    if not bank:
        return
    for off, vi, lines, vat, ref, pay, asset in BILLS:
        if vi not in vend:
            continue
        ref = f"{ref}-{ctx.tenant[:2].upper()}"
        ex = _one(ctx, "SELECT id, status FROM ap_bills WHERE vendor_ref=?", (ref,))
        day = _at(ctx, off if off != 9999 else -3)
        if ex:
            bid, status = ex["id"], ex["status"]
        else:
            bl = [acc_ap.BillLine(account=a, amount=_m(v, p["scale"]), cost_center_id=_cc(ctx, cc, plist), description=d) for a, v, cc, d in lines]
            r = _do(ctx, "accountant", acc_ap.api_bill_add, acc_ap.BillIn(vendor_id=vend[vi]["id"], bill_date=day, due_date=day + dt.timedelta(days=30), vendor_ref=ref,
                                                                         description=lines[0][3], vat_class=vat, lines=bl))
            if not r:
                continue
            bid, status = r["id"], "draft"
            ctx.add("bills")
        if status == "draft":
            if not _do(ctx, "admin", acc_ap.api_bill_approve, bid):
                continue
            status = "approved"
        if asset and not _one(ctx, "SELECT 1 x FROM fixed_assets WHERE code=?", (asset[0],)):
            cost = _m(sum(v for a, v, *_ in lines if a == "1520"), p["scale"])
            _do(ctx, "admin", acc_assets.api_asset_add, acc_assets.AssetIn(code=asset[0], name=asset[1], category=asset[2], cost=cost, acquired=day, life_months=asset[3],
                                                                              salvage=_m(asset[4], p["scale"]), cost_center_id=_cc(ctx, "G-ADM", plist), note=DEMO))
            ctx.add("assets")
        if not pay or status not in ("approved", "partly_paid"):
            continue
        if _one(ctx, "SELECT 1 x FROM payment_orders WHERE bill_id=?", (bid,)):
            continue
        how, method, lag = pay
        b = _one(ctx, "SELECT total, paid FROM ap_bills WHERE id=?", (bid,))
        amount = round(b["total"] / 2, 3) if how == "half" else round(b["total"] - b["paid"], 3)
        paid_on = min(day + dt.timedelta(days=lag), ctx.today)
        o = _do(ctx, "accountant", acc_ap.api_order_add, acc_ap.OrderIn(bill_id=bid, amount=amount, method=method, bank_account_id=bank["id"], reference=f"تحويل {ref}",
                                                                          cheque_number=f"{ref}-CQ" if method == "cheque" else "",
                                                                          cheque_due=paid_on + dt.timedelta(days=14) if method == "cheque" else None))
        if not o:
            continue
        if not _do(ctx, "admin", acc_ap.api_order_approve, o["id"]):
            continue
        if how == "dual" or amount >= 5000:     # above the dual-control limit: a second, different approver
            ctx.tryc(acc_ap.api_order_approve, o["id"], u=_admin2(ctx))
        r = _do(ctx, "accountant", acc_ap.api_order_execute, o["id"], acc_ap.ExecIn(paid_on=paid_on))
        if r:
            ctx.add("bill_payments")
            if r.get("cheque_id") and paid_on + dt.timedelta(days=14) <= ctx.today:
                from .acc_bank import ClearedIn, api_cheque_cleared
                _do(ctx, "accountant", api_cheque_cleared, r["cheque_id"], ClearedIn(on=paid_on + dt.timedelta(days=14)))


def _depreciation(ctx):
    from . import acc_assets
    first = _one(ctx, "SELECT MIN(acquired) a FROM fixed_assets")
    if not first or not first["a"]:
        return
    d = dt.date.fromisoformat(first["a"]).replace(day=1)
    d = _addm(d, 1)
    while d < ctx.today.replace(day=1):
        r = _do(ctx, "accountant", acc_assets.api_dep_run, acc_assets.DepRun(period=f"{d.year}-{d.month:02d}"))
        if r and r.get("assets"):
            ctx.add("depreciation_runs")
        d = _addm(d, 1)


def _budget(ctx, p, plist):
    from . import acc_assets
    if _one(ctx, "SELECT 1 x FROM acc_budgets WHERE year=?", (ctx.today.year,)):
        return
    roll = _one(ctx, "SELECT COALESCE(SUM(annual_rent),0) s FROM leases WHERE status IN ('active','expired','renewed')")["s"] / 12
    pay = _one(ctx, "SELECT AVG(gross) g FROM payroll_runs WHERE status IN ('approved','paid')")
    cells = []
    for m in range(1, 13):
        cells.append(acc_assets.BudgetLine(account="4110", month=m, amount=round(roll * (0.92 + 0.01 * m), 3)))
        cells.append(acc_assets.BudgetLine(account="5110", cost_center_id=_cc(ctx, "P1", plist), month=m, amount=_m(650, p["scale"])))
        cells.append(acc_assets.BudgetLine(account="5110", cost_center_id=_cc(ctx, "P2", plist), month=m, amount=_m(380, p["scale"])))
        cells.append(acc_assets.BudgetLine(account="5120", cost_center_id=_cc(ctx, "P1", plist), month=m, amount=_m(340, p["scale"])))
        cells.append(acc_assets.BudgetLine(account="5140", cost_center_id=_cc(ctx, "P1", plist), month=m, amount=_m(750, p["scale"])))
        cells.append(acc_assets.BudgetLine(account="5220", cost_center_id=_cc(ctx, "D-SAL", plist), month=m, amount=_m(1100 if m != 6 else 6300, p["scale"])))
        cells.append(acc_assets.BudgetLine(account="5230", cost_center_id=_cc(ctx, "G-ADM", plist), month=m, amount=_m(900, p["scale"])))
        cells.append(acc_assets.BudgetLine(account="5240", month=m, amount=_m(310, p["scale"])))
        if pay and pay["g"]:
            cells.append(acc_assets.BudgetLine(account="5210", month=m, amount=round(pay["g"] * 1.03, 3)))
    if _do(ctx, "admin", acc_assets.api_budget_set, acc_assets.BudgetIn(year=ctx.today.year, lines=cells)):
        ctx.add("budget_cells", len(cells))


def _journals(ctx):
    from . import accounting
    for off, memo, lines, state in JOURNALS:
        if _one(ctx, "SELECT 1 x FROM acc_journals WHERE memo=?", (memo,)):
            continue
        day = _at(ctx, off if off < 0 else off)
        b = accounting.JournalIn(date=day, memo=memo, lines=[accounting.LineIn(account=a, debit=d, credit=c_, memo=DEMO) for a, d, c_ in lines])
        r = _do(ctx, "accountant", accounting.api_journal_add, b)
        if not r:
            continue
        ctx.add("manual_journals")
        if sum(d for _, d, _c in lines) >= 1000:   # a manual entry above the attachment limit needs its voucher before it can be submitted
            _voucher(ctx, r["id"], memo)
        if state in ("pending", "approved"):
            _do(ctx, "accountant", accounting.api_journal_submit, r["id"])
        if state == "approved":
            _do(ctx, "admin", accounting.api_journal_approve, r["id"])


def _voucher(ctx, jid: int, memo: str) -> None:
    from .modules2 import store_upload
    from .seed_org_hr import _mini_pdf
    with ctx.request():
        c = ctx.conn()
        store_upload(c, _mini_pdf("Illustrative voucher - demo data only"), "demo-voucher.pdf", "journal", jid, "سند القيد: " + memo[:60], "محاسبة", "التعبئة التجريبية")
        c.commit()


def _financing(ctx, plist):
    from . import acc_assets
    bank = _one(ctx, "SELECT id FROM bank_accounts WHERE kind='bank' AND active=1 ORDER BY id")
    if not bank:
        return
    specs = [("murabaha", "بنك نزوى — مرابحة لتمويل مركبات المشاريع", 36000.0 * _tp(ctx)["scale"], 2880.0 * _tp(ctx)["scale"], 7, 12),
             ("ijara", "ميثاق للصيرفة الإسلامية — إجارة معدات مكتبية منتهية بالتمليك", 12000.0 * _tp(ctx)["scale"], 960.0 * _tp(ctx)["scale"], 4, 24)]
    for kind, who, principal, markup, back, n in specs:
        if _one(ctx, "SELECT 1 x FROM fin_contracts WHERE counterparty=?", (who,)):
            continue
        start = max(_addm(ctx.today.replace(day=1), -back), _start(ctx))
        total = round(principal + markup, 3)
        each = round(total / n, 3)
        ins = [acc_assets.InstallmentIn(due=_addm(start, i + 1), amount=each if i < n - 1 else round(total - each * (n - 1), 3)) for i in range(n)]
        r = _do(ctx, "admin", acc_assets.api_finance_add, acc_assets.FinanceIn(kind=kind, counterparty=who, principal=round(principal, 3), markup_total=round(markup, 3),
                                                                                  start_date=start, bank_account_id=bank["id"], installments=ins, note=f"{DEMO} — هامش ثابت معلوم، بلا فوائد"))
        if not r:
            continue
        ctx.add("financing")
        for i, it in enumerate(ins, 1):
            if it.due <= ctx.today - dt.timedelta(days=2):
                if _do(ctx, "accountant", acc_assets.api_finance_pay, r["id"], i, acc_assets.FinPay(paid_on=it.due)):
                    ctx.add("financing_payments")


def _reconcile(ctx):
    from . import acc_bank
    bank = _one(ctx, "SELECT * FROM bank_accounts WHERE kind='bank' AND active=1 ORDER BY id")
    if not bank:
        return
    end = ctx.today.replace(day=1) - dt.timedelta(days=1)
    if end < _start(ctx) or _one(ctx, "SELECT 1 x FROM bank_recons WHERE bank_account_id=? AND period_end=?", (bank["id"], end.isoformat())):
        return
    gl = _rows(ctx, """SELECT l.id, j.jdate, j.number, COALESCE(l.memo, j.memo) memo, (l.debit - l.credit) amount FROM acc_lines l JOIN acc_journals j ON j.id=l.journal_id
                       WHERE l.account_id=? AND j.status IN ('posted','reversed') AND j.jdate<=? ORDER BY j.jdate, l.id""", (bank["account_id"], end.isoformat()))
    if len(gl) < 6:
        return
    held = {x["id"] for x in gl[-2:]}                       # the last two items are "in transit" — the bank has not shown them yet
    link: dict[str, int] = {}
    with ctx.request():
        c = ctx.conn()
        for x in gl:
            if x["id"] in held:
                continue
            key = f"seed:{x['id']}"
            c.execute("INSERT INTO bank_stmt_lines(bank_account_id,line_date,description,reference,amount,import_key,file_sha) VALUES(?,?,?,?,?,?,?)",
                      (bank["id"], x["jdate"], (x["memo"] or "")[:120], x["number"], round(x["amount"], 3), key, "seed"))
            link[key] = x["id"]
        c.execute("INSERT INTO bank_stmt_lines(bank_account_id,line_date,description,reference,amount,import_key,file_sha) VALUES(?,?,?,?,?,?,?)",
                  (bank["id"], (end - dt.timedelta(days=1)).isoformat(), "رسوم خدمات مصرفية — لم تُقيَّد بعد", "FEE", -5.25, "seed:fee", "seed"))
        c.commit()
    _do(ctx, "accountant", acc_bank.api_auto_match, bank["id"])
    for s in _rows(ctx, "SELECT id, import_key FROM bank_stmt_lines WHERE bank_account_id=? AND status='unmatched' AND import_key LIKE 'seed:%'", (bank["id"],)):
        if s["import_key"] in link:
            _do(ctx, "accountant", acc_bank.api_match, bank["id"], s["id"], acc_bank.MatchIn(acc_line_id=link[s["import_key"]]))
    with ctx.request():
        c = ctx.conn()
        bal = acc_bank.recon_state(c, dict(bank), end.isoformat(), 0.0)["difference"]
    if _do(ctx, "admin", acc_bank.api_recon_close, bank["id"], acc_bank.ReconClose(end=end, statement_balance=bal)):
        ctx.add("bank_recons")


def _vat(ctx):
    from . import acc_assets
    y = ctx.today.year
    for q in (1, 2, 3, 4):
        if acc_assets.quarter_range(y, q)[1] >= ctx.today.isoformat():
            break
        if q == 3:       # the last finished quarter is left unfiled, as the open item of the month
            break
        if not _one(ctx, "SELECT 1 x FROM vat_returns WHERE year=? AND quarter=?", (y, q)):
            if _do(ctx, "admin", acc_assets.api_vat_file, y, q, acc_assets.VatFile(ref=f"إقرار تجريبي {y}-ر{q} — {DEMO}")):
                ctx.add("vat_returns")


def _close_periods(ctx):
    from . import accounting
    last = _addm(ctx.today.replace(day=1), -2)             # the month before last stays open: the books are closed with one month's grace
    d = _start(ctx)
    while d <= last:
        p = _one(ctx, "SELECT status FROM acc_periods WHERE year=? AND month=?", (d.year, d.month))
        if not p or p["status"] != "closed":
            if _do(ctx, "admin", accounting.api_period_close, d.year, d.month):
                ctx.add("closed_periods")
        d = _addm(d, 1)


def run_ops(ctx) -> dict:
    from . import accounting
    p = _tp(ctx)
    plist = _projects(ctx)
    _bills(ctx, p, plist)
    _depreciation(ctx)
    _budget(ctx, p, plist)
    _journals(ctx)
    _financing(ctx, plist)
    r = _do(ctx, "accountant", accounting.api_sync)          # the leasing events of the whole year reach the ledger (idempotent)
    if r:
        ctx.add("sync_posted", sum((r.get("posted") or {}).values()))
        ctx.add("sync_errors", len(r.get("errors") or []))
    _reconcile(ctx)
    _vat(ctx)
    _close_periods(ctx)
    return ctx.counts
