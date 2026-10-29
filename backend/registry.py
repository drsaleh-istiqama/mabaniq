"""Mabaniq 0.20.0 — module registry: which parts of the platform each developer organisation has.

A *module* is a switchable slice of the product (sales, leasing, construction, …). Switching one off hides its screens, makes its API
paths answer the same 404 as an unknown path, removes its permissions from every role and drops its widgets from the dashboard — it
never deletes data. The registry is code (names, dependencies, permissions, path prefixes); the *state* is per developer:

  licensed  — what the platform operator (Jadwa) allows: profile key `licensed` / env `MABANIQ_LICENSES="code:bundle;code2:a+b+c"`
  enabled   — what the organisation's administrator switched on, inside the licence: table `org_modules`
              (no rows yet ⟵ the profile's `modules`, else everything licensed — existing developers keep today's behaviour)

Design: docs/DESIGN-leasing-accounting-hr-modules.md §2.
"""
from __future__ import annotations

from collections import OrderedDict

from . import config

# key → title, one-line description, hard dependencies, permissions the module owns, API path prefixes, availability
MODULES: OrderedDict[str, dict] = OrderedDict([
    ("sales", dict(title="المبيعات", desc="الحجز وعروض الأسعار وعقود البيع والأقساط والتحقق من الهوية والوسطاء والسوق الثانوي وقمع العملاء",
                   deps=("finance",), perms=("book", "kyc", "brokers", "confirm", "broker_portal", "leads"),
                   prefixes=("/api/bookings", "/api/quotes", "/api/customers", "/api/kyc", "/api/brokers", "/api/broker", "/api/commissions",
                             "/api/discounts", "/api/resale", "/api/resale-settlements", "/api/installments", "/api/receipts", "/api/pricing",
                             "/api/leads", "/api/wa", "/api/pay"))),
    ("leasing", dict(title="الإيجارات", desc="العقود والمستأجرون والتحصيل والشيكات والمتأخرات والصيانة وكشوف الملاك",
                     deps=("finance",), perms=("leasing", "leasing_approve", "leasing_pm"), prefixes=("/api/leasing", "/api/leases", "/api/rent-dues", "/api/lea", "/api/pm"))),
    ("construction", dict(title="الإنشاء", desc="المستخلصات والتحقق من الإنجاز وأوامر التغيير والجودة وتقارير الموقع",
                          deps=("finance",), perms=("construction", "approve_ipc"),
                          prefixes=("/api/ipcs", "/api/change-orders", "/api/ncrs", "/api/site-reports", "/api/construction"))),
    ("marketing", dict(title="التسويق", desc="الحملات واستوديو الإعلانات وتنبيهات السوق",
                       deps=("sales",), perms=("market",),
                       prefixes=("/api/campaigns", "/api/creatives", "/api/marketing", "/api/market"))),
    ("finance", dict(title="المالية", desc="الفواتير وحسابات الضمان ورادار السيولة والمطابقة البنكية والتعثر وتبرعات التأخير",
                     deps=(), perms=("finance", "decide", "invoices"),
                     prefixes=("/api/cash", "/api/escrow", "/api/bank", "/api/invoices", "/api/charity", "/api/penalties", "/api/risk",
                               "/api/export"))),
    ("accounting", dict(title="المحاسبة", desc="دليل الحسابات والقيود المزدوجة والذمم والبنوك والضريبة والأصول والموازنات والقوائم المالية",
                        deps=("finance",), perms=(), prefixes=(), available=False)),
    ("hr", dict(title="الموارد البشرية", desc="الموظفون والإجازات والحضور والرواتب والتأمينات ونهاية الخدمة والتوظيف والتقييم",
                deps=(), perms=(), prefixes=(), available=False)),
    ("land", dict(title="الأراضي والتراخيص", desc="دراسات الجدوى للأراضي وتراخيص الجهات",
                  deps=(), perms=("land", "permits"), prefixes=("/api/lands", "/api/permits"))),
    ("handover", dict(title="التسليم وما بعد البيع", desc="التسليم والعيوب والتمليك واتحاد الملاك وخدمة العملاء",
                      deps=("sales",), perms=("handover", "oa", "service"),
                      prefixes=("/api/handover", "/api/snags", "/api/titles", "/api/oa", "/api/service"))),
    ("reports", dict(title="التقارير", desc="التقارير الجاهزة ومنشئ التقارير والجدولة بالبريد",
                     deps=(), perms=("reports",), prefixes=("/api/reports",))),
    ("assistant", dict(title="المساعد الذكي", desc="الأسئلة بلغة طبيعية على بيانات الوحدات المفعَّلة",
                       deps=(), perms=(), prefixes=("/api/assistant",))),
])
for _k, _m in MODULES.items():
    _m.setdefault("available", True)

# paths owned by *either* of two modules (facility maintenance serves sold buildings and leased ones)
SHARED_PREFIXES = {"/api/fm": ("handover", "leasing"), "/api/work-orders": ("handover", "leasing")}

# permissions that belong to no module: always present for the roles that hold them
CORE_PERMS = frozenset({"view", "inventory", "users", "audit", "admin", "docs", "notify", "portal"})

PERM_MODULE = {p: k for k, m in MODULES.items() for p in m["perms"]}

# decision kinds (engines.decisions) → the module that owns them
DECISION_MODULE = {"price": "sales", "reschedule": "sales", "ipc": "construction", "cash": "finance", "lease_renew": "leasing", "lease_arrears": "leasing"}

BUNDLES = OrderedDict([
    ("leasing_only", dict(title="تأجير فقط", modules=("leasing", "finance", "reports", "assistant"), price=None)),
    ("develop_sell", dict(title="تطوير وبيع", modules=("sales", "construction", "marketing", "land", "handover", "finance", "reports", "assistant"), price=None)),
    ("develop_lease", dict(title="تطوير + تأجير", modules=("sales", "construction", "marketing", "land", "handover", "leasing", "finance", "reports", "assistant"), price=None)),
    ("enterprise", dict(title="مؤسسة كاملة", modules=tuple(MODULES), price=None)),  # accounting/hr join automatically once available
])


def available() -> list[str]:
    return [k for k, m in MODULES.items() if m["available"]]


def route_module(path: str):
    """→ None (core: never gated) or a tuple of module keys, any one of which switches the path on."""
    for pre, mods in SHARED_PREFIXES.items():
        if path == pre or path.startswith(pre + "/"):
            return mods
    best = None
    for k, m in MODULES.items():
        for pre in m["prefixes"]:
            if (path == pre or path.startswith(pre + "/")) and (best is None or len(pre) > best[0]):
                best = (len(pre), k)
    return (best[1],) if best else None


def _expand(spec) -> set[str]:
    """A bundle name, a list of module keys, or `a+b+c` → a set of known, available module keys."""
    if not spec:
        return set()
    if isinstance(spec, str):
        spec = BUNDLES[spec]["modules"] if spec in BUNDLES else spec.split("+")
    return {k for k in spec if k in MODULES and MODULES[k]["available"]}


def licensed(tenant: str) -> set[str]:
    """What the operator allows this developer. Env wins, then the profile, else everything available (today's behaviour)."""
    for part in config.licenses_env().split(";"):
        code, _, spec = part.strip().partition(":")
        if code.strip().lower() == tenant and spec.strip():
            return _expand(spec.strip())
    from .tenant_profiles import profile
    p = profile(tenant) or {}
    if p.get("licensed") or p.get("bundle"):
        return _expand(p.get("licensed") or p.get("bundle"))
    return set(available())


def default_enabled(tenant: str) -> set[str]:
    from .tenant_profiles import profile
    p = profile(tenant) or {}
    want = _expand(p.get("modules") or p.get("bundle")) if (p.get("modules") or p.get("bundle")) else set(available())
    return want & licensed(tenant)


def _close(selected: set[str]) -> set[str]:
    """Drop every module whose dependencies are not all on (repeat until stable)."""
    cur = set(selected)
    while True:
        bad = {k for k in cur if any(d not in cur for d in MODULES[k]["deps"])}
        if not bad:
            return cur
        cur -= bad


def enabled_modules(c, tenant: str | None = None) -> set[str]:
    """The modules that are on for the developer behind connection `c` (`core` is implicit and never listed)."""
    from .db import TENANT
    t = tenant or TENANT.get()
    lic = licensed(t)
    rows = c.execute("SELECT module, enabled FROM org_modules").fetchall() if c.has_table("org_modules") else []
    if not rows:
        return _close(default_enabled(t))
    state = {r["module"]: bool(r["enabled"]) for r in rows}
    on = {k for k in available() if k in lic and state.get(k, k in default_enabled(t))}
    return _close(on)


def effective_perms(perms, enabled: set[str]) -> list[str]:
    """A role's permissions minus those owned by a module that is off."""
    return sorted(p for p in perms if p in CORE_PERMS or PERM_MODULE.get(p) is None or PERM_MODULE[p] in enabled)


def describe(c, tenant: str | None = None) -> list[dict]:
    from .db import TENANT
    t = tenant or TENANT.get()
    lic, on = licensed(t), enabled_modules(c, t)
    return [{"key": k, "title": m["title"], "desc": m["desc"], "deps": list(m["deps"]), "available": m["available"],
             "licensed": k in lic, "enabled": k in on,
             "needed_by": [x for x, mm in MODULES.items() if k in mm["deps"] and x in on]} for k, m in MODULES.items()]
