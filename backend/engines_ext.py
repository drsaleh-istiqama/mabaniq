"""محركات الوحدات الموسّعة — حسابات شفافة تُرجع الأسباب مع كل نتيجة."""
import datetime as dt
import difflib
import re
import unicodedata

from .db import setting_f


# ================================================================ الجدوى
def irr(flows: list[float]) -> float | None:
    """معدل العائد الداخلي الشهري بطريقة التنصيف ثم تحويله سنويًا."""
    def npv(r):
        return sum(f / (1 + r) ** i for i, f in enumerate(flows))
    lo, hi = -0.99, 1.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (1 + mid) ** 12 - 1


def feasibility(land: dict, p: dict) -> dict:
    gfa = land["area"] * land["far"]
    sellable = gfa * p["efficiency"]
    revenue = sellable * p["sell_price_sqm"]
    construction = gfa * p["build_cost_sqm"]
    soft = construction * p["soft_cost_pct"]
    marketing = revenue * .03
    land_cost = land["price"] * 1.03  # شاملة رسوم التسجيل التقديرية
    months = int(p["months"])
    # تدفق نقدي شهري: الأرض في الشهر 0، الإنشاء على شكل S، المبيعات: نسبة مسبقة أثناء البناء والباقي عند التسليم
    flows = [-land_cost] + [0.0] * (months + 1)
    for m in range(1, months + 1):
        x = m / months
        w = 6 * x * (1 - x) / months  # منحنى S تقريبي
        flows[m] -= (construction + soft) * w / sum(6 * (k / months) * (1 - k / months) / months for k in range(1, months + 1))
        flows[m] -= marketing / months
        flows[m] += revenue * p["presale_pct"] * (1 / months) * .5  # تحصيل أثناء البناء (50٪ من قيمة المبيع المسبق)
    flows[months + 1] += revenue - revenue * p["presale_pct"] * .5
    peak, cum = 0.0, 0.0
    for f in flows:
        cum += f
        peak = min(peak, cum)
    finance = -peak * p["finance_rate"] * months / 12 * .55  # كلفة التمويل الإسلامي (ربح مرابحة/أجرة إجارة) — متوسط الاستخدام 55٪ من ذروة التمويل
    flows[months + 1] -= finance
    total_cost = land_cost + construction + soft + marketing + finance
    profit = revenue - total_cost
    margin = profit / revenue if revenue else 0
    annual_irr = irr(flows)
    npv10 = sum(f / (1 + .10 / 12) ** i for i, f in enumerate(flows))
    sens = []
    for dp in (-.10, 0, .10):
        row = []
        for dc in (-.10, 0, .10):
            rv = revenue * (1 + dp)
            tc = total_cost + (construction + soft) * dc
            row.append(round((rv - tc) / rv * 100, 1))
        sens.append({"price_change": dp, "margins": row})
    reasons = [f"المساحة الطابقية {gfa:,.0f} م² (معامل بناء {land['far']})، والقابلة للبيع {sellable:,.0f} م² بكفاءة {p['efficiency']*100:.0f}٪",
               f"ذروة الاحتياج التمويلي {-peak:,.0f} ر.ع، وكلفة التمويل الإسلامي التقديرية (ربح مرابحة/إجارة بمعدل {p['finance_rate']*100:.1f}٪ سنويًا) {finance:,.0f} ر.ع"]
    if margin >= .20 and (annual_irr or 0) >= .18:
        verdict = "مُجدٍ — يُوصى بالمضي"
    elif margin >= .12:
        verdict = "مُجدٍ بشروط — يحتاج تفاوضًا على سعر الأرض أو رفع نسبة البيع المسبق"
    else:
        verdict = "غير مُجدٍ بالافتراضات الحالية"
    worst = sens[0]["margins"][2]
    reasons.append(f"في أسوأ سيناريو (سعر −10٪ وتكلفة +10٪) يصبح الهامش {worst}٪")
    breakeven = total_cost / sellable if sellable else 0
    reasons.append(f"سعر التعادل {breakeven:,.0f} ر.ع/م² مقابل سعر بيع مفترض {p['sell_price_sqm']:,.0f}")
    return {"gfa": round(gfa), "sellable": round(sellable), "revenue": round(revenue), "land_cost": round(land_cost),
            "construction": round(construction), "soft": round(soft), "marketing": round(marketing), "finance": round(finance),
            "total_cost": round(total_cost), "profit": round(profit), "margin": round(margin * 100, 1),
            "irr": round(annual_irr * 100, 1) if annual_irr is not None else None, "npv10": round(npv10),
            "peak_funding": round(-peak), "breakeven_sqm": round(breakeven), "sensitivity": sens,
            "finance_mode": "تمويل إسلامي — مرابحة/إجارة (معدل الربح لا فائدة)",
            "verdict": verdict, "reasons": reasons, "cashflow": [round(f) for f in flows]}


# ================================================================ الجدول الزمني والتكاليف
def _d(s):
    return dt.date.fromisoformat(s) if s else None


def schedule_analysis(tasks: list[dict], today: dt.date) -> dict:
    planned_val = earned = 0.0
    out, delay_days = [], 0
    for t in tasks:
        ps, pe = _d(t["planned_start"]), _d(t["planned_end"])
        span = max(1, (pe - ps).days)
        plan_pct = 0 if today <= ps else 100 if today >= pe else round((today - ps).days / span * 100)
        planned_val += t["weight"] * plan_pct
        earned += t["weight"] * t["pct"]
        late = 0
        if t["pct"] < 100 and plan_pct > t["pct"]:
            late = round((plan_pct - t["pct"]) / 100 * span)
        delay_days = max(delay_days, late)
        status = "مكتمل" if t["pct"] >= 100 else "متأخر" if late > 7 else "جارٍ" if t["pct"] > 0 else "لم يبدأ"
        out.append({**t, "plan_pct": plan_pct, "late_days": late, "status": status, "critical": True})
    spi = round(earned / planned_val, 2) if planned_val else 1.0
    return {"tasks": out, "spi": spi, "forecast_delay_days": delay_days, "planned_pct": round(planned_val, 1),
            "actual_pct": round(earned, 1),
            "reasons": [f"مؤشر أداء الجدول SPI = {spi} ({'متأخر عن الخطة' if spi < .95 else 'ضمن الخطة'})",
                        "الأنشطة متسلسلة، فكل تأخير في نشاط جارٍ يقع على المسار الحرج ويؤخر التسليم"]}


# ================================================================ التحقق من الهوية (KYC/AML)
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = re.sub(r"[\u064B-\u0652\u0640]", "", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"\s+", " ", s).strip()


def kyc_screen(c, cust: dict, today: dt.date) -> dict:
    flags, risk = [], "منخفض"
    if not cust.get("id_number") or not cust.get("id_type"):
        flags.append("بيانات الهوية ناقصة")
    if cust.get("id_type") == "بطاقة مدنية" and not re.fullmatch(r"\d{6,10}", cust.get("id_number") or ""):
        flags.append("صيغة رقم البطاقة المدنية غير صحيحة")
    if cust.get("id_expiry") and _d(cust["id_expiry"]) < today:
        flags.append("وثيقة الهوية منتهية الصلاحية")
    hits = []
    for w in c.execute("SELECT name, source FROM watchlist"):
        ratio = difflib.SequenceMatcher(None, _norm(cust["name"]), _norm(w["name"])).ratio()
        if ratio >= .85:
            hits.append(f"{w['name']} ({w['source']}) — تطابق {ratio*100:.0f}٪")
    if hits:
        flags.append("تطابق محتمل مع قائمة الفحص: " + "؛ ".join(hits))
        risk = "مرتفع"
    if cust.get("pep"):
        flags.append("شخص معرّض سياسيًا — يلزم اعتماد إدارة عليا وعناية معززة")
        risk = "مرتفع"
    if cust.get("nationality") and cust["nationality"] != "عُماني" and risk == "منخفض":
        risk = "متوسط"
    if not cust.get("source_of_funds"):
        flags.append("مصدر الأموال غير محدد")
    blocking = [f for f in flags if "منتهية" in f or "ناقصة" in f or "غير صحيحة" in f]
    status = "rejected" if blocking else "review" if risk == "مرتفع" else "verified"
    return {"status": status, "risk": risk, "flags": flags,
            "reasons": flags or ["الهوية سارية، ولا تطابق مع قوائم الفحص، ومصدر الأموال محدد"]}


# ================================================================ عقد البيع
def contract_text(b: dict, sched: list[dict], s: dict) -> str:
    lines = [
        "بسم الله الرحمن الرحيم",
        f"عقد بيع وحدة عقارية على الخريطة رقم {s['number']}",
        f"حُرر هذا العقد إلكترونيًا بتاريخ {s['date']} بين:",
        f"الطرف الأول (البائع/المطوّر): {s['developer']}، المشروع المسجل برقم حساب ضمان {s['escrow_ref']}.",
        f"الطرف الثاني (المشتري): {b['customer']}، {b.get('id_type') or 'هوية'} رقم {b.get('id_number') or '—'}، الجنسية {b.get('nationality') or '—'}.",
        "",
        "البند 1 — محل العقد",
        f"الوحدة رقم {b['code']} في مشروع «{b['project']}» بولاية {b['location']}، النوع: {b['type']}، "
        f"المساحة التقريبية {b['area']:,.0f} م²، الطابق {b['floor']}، الإطلالة: {b['view']}.",
        "البند 2 — الثمن وطريقة السداد",
        f"الثمن الإجمالي {b['price']:,.0f} ريال عُماني، يُسدَّد وفق الجدول التالي (خطة: {s['plan_label']}):",
    ]
    for i in sched:
        lines.append(f"  - {i['label']}: {i['amount']:,.0f} ر.ع، تاريخ الاستحقاق {i['due_date']}")
    lines += [
        f"ضريبة القيمة المضافة: {s['vat_note']}.",
        "البند 3 — حساب الضمان",
        "تودع جميع دفعات المشتري في حساب ضمان المشروع، ولا يُصرف منها إلا مقابل نسب إنجاز معتمدة من الاستشاري.",
        "البند 4 — التسليم",
        f"يلتزم البائع بتسليم الوحدة في موعد أقصاه {b['handover']}، مع مهلة سماح 6 أشهر للظروف القاهرة.",
        "البند 5 — التأخر في السداد (شرط التبرع)",
        f"إذا تأخر المشتري عن سداد قسط أكثر من {int(s['grace'])} يومًا التزم بالتبرع بمبلغ قدره {s['penalty']*100:.1f}٪ شهريًا من القسط المتأخر "
        "لجهة خيرية تعتمدها هيئة الرقابة الشرعية للبائع، يُودَع في حساب أمانة منفصل ولا يعود منه شيء للبائع ولا يُعد تعويضًا له؛ "
        "وللبائع عند التأخر الجسيم المطالبة بالفسخ وفق البند 6.",
        "البند 5 مكرر — التزام الصيغة الشرعية",
        "لا تتضمن خطة السداد أي فائدة أو زيادة لقاء الأجل؛ والثمن ثابت لا يتغير بتغير مواعيد السداد، وخطط التمويل البنكي عبر صيغ متوافقة مع الشريعة (مرابحة/إجارة) بعقد مستقل مع البنك.",
        "البند 6 — الفسخ",
        f"إذا فُسخ العقد لإخلال المشتري، يُرد إليه ما سدده بعد خصم {s['cancel']*100:.0f}٪ من ثمن الوحدة كتعويض متفق عليه.",
        "البند 7 — الضمان",
        f"يضمن البائع عيوب التشطيب {int(s['warranty'])} شهرًا من تاريخ التسليم، والعيوب الإنشائية {int(s['structural'])} سنوات.",
        "البند 8 — نقل الملكية",
        "يلتزم البائع بإجراءات فرز الوحدة ونقل ملكيتها للمشتري بعد سداد كامل الثمن، ويتحمل المشتري رسوم التسجيل الرسمية.",
        "البند 9 — التنازل وإعادة البيع",
        f"يجوز للمشتري التنازل عن العقد بعد سداد {s['resale_min']*100:.0f}٪ من الثمن، بموافقة البائع ورسوم {s['resale_fee']*100:.0f}٪.",
        "البند 10 — القانون والاختصاص",
        "يخضع هذا العقد لقوانين سلطنة عُمان، ويُعتد بالتوقيع الإلكتروني وفق قانون المعاملات الإلكترونية.",
        "",
        "نموذج عقد للعرض التجريبي — يجب مراجعته واعتماده من مستشار قانوني قبل الاستخدام الفعلي.",
    ]
    return "\n".join(lines)


# ================================================================ الغرامات والفسخ
def penalty_for(inst: dict, today: dt.date, rate: float, grace: int) -> dict:
    due = _d(inst["due_date"])
    unpaid = inst["amount"] - inst["paid_amount"]
    late_days = (today - due).days
    if unpaid <= 1 or late_days <= grace or inst.get("penalty_waived"):
        return {"amount": 0, "late_days": max(0, late_days), "waived": bool(inst.get("penalty_waived"))}
    months = (late_days - grace) / 30
    return {"amount": round(unpaid * rate * months, 1), "late_days": late_days, "waived": False}


def termination(price: float, paid: float, pct: float) -> dict:
    ded = min(paid, round(price * pct))
    return {"paid": round(paid), "deduction": ded, "refund": round(paid - ded),
            "reasons": [f"المسدَّد {paid:,.0f} ر.ع", f"خصم الفسخ التعاقدي {pct*100:.0f}٪ من الثمن ({price*pct:,.0f} ر.ع) بحد أقصى المسدَّد"]}


# ================================================================ وكيل واتساب (محرك قواعد عربي)
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
NUM_WORDS = {"غرفة": 1, "غرفه": 1, "غرفتين": 2, "غرفتان": 2, "ثلاث": 3, "٣": 3, "اربع": 4, "أربع": 4, "خمس": 5}


def wa_intent(text: str) -> dict:
    t = _norm(text).translate(ARABIC_DIGITS)
    out = {"intent": "other", "bedrooms": None, "budget": None, "project_hint": None}
    if re.search(r"(موظف|انسان|شخص|اتصل|كلمني|مسؤول)", t):
        out["intent"] = "human"
    elif re.search(r"(قسط|دفعه|دفعات|مستحق|سداد|متاخر)", t):
        out["intent"] = "payment"
    elif re.search(r"(صيانه|عطل|تسرب|تكييف|كهرباء|سباكه)", t):
        out["intent"] = "maintenance"
    elif re.search(r"(زياره|معاينه|موعد|اشوف|اجي)", t):
        out["intent"] = "viewing"
    elif re.search(r"(سعر|اسعار|(?:^|\s)كم(?:\s|$)|بكم|متوفر|متاح|شقه|شقق|فيلا|فلل|وحده|غرف|ميزانيه)", t):
        out["intent"] = "availability"
    elif re.search(r"(السلام|مرحبا|هلا|صباح|مساء)", t):
        out["intent"] = "greeting"
    m = re.search(r"(\d)\s*غرف", t)
    if m:
        out["bedrooms"] = int(m.group(1))
    else:
        for w, n in NUM_WORDS.items():
            if _norm(w) in t and "غرف" in t:
                out["bedrooms"] = n
                break
    m = re.search(r"(\d{2,3})\s*(الف|الاف|k)", t)
    if m:
        out["budget"] = int(m.group(1)) * 1000
    else:
        m = re.search(r"(\d{5,7})", t)
        if m:
            out["budget"] = int(m.group(1))
    if "فيلا" in t or "فلل" in t:
        out["kind"] = "villa"
    elif "شقه" in t or "شقق" in t:
        out["kind"] = "tower"
    for hint in ("الخوض", "السيب", "المعبيله", "الريحان", "بوشر", "العذيبه", "الانصب"):
        if hint in t:
            out["project_hint"] = hint
    return out


# ================================================================ تقارير الممولين
def lender_flags(row: dict) -> list[str]:
    flags = []
    if row["coverage"] < 1.1:
        flags.append("تغطية التدفقات لتكلفة الإكمال أقل من 1.1× — يتطلب خطة معالجة")
    if row["sold_pct"] < 40:
        flags.append("المبيعات أقل من 40٪ — دون الحد المعتاد لسحب التمويل")
    if row["collection_rate"] < 85:
        flags.append("نسبة التحصيل أقل من 85٪")
    if row.get("cash_gap", 0) > 0:
        flags.append(f"عجز نقدي متوقع في حساب الضمان خلال 12 شهرًا بقيمة {row['cash_gap']:,.0f} ر.ع")
    if row["claimed_vs_verified"] > 5:
        flags.append("فرق بين نسبة الإنجاز المعلنة والمثبتة يتجاوز 5 نقاط")
    return flags


def vat_rate(c, use: str) -> float:
    return setting_f(c, "vat_commercial_sale" if use == "commercial" else "vat_residential_sale", 0.0)
