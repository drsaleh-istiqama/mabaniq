"""Mabaniq 0.20.0 — module switches: the gate every API path passes, the administrator's endpoints, and the dashboard widgets.

`module_gate` is an application-wide dependency: a path owned by a module that is off answers the same 404 an unknown path would
(never 403 — the organisation is not told the module exists). `registry.route_module` owns the path→module map and
tests/test_modules_registry.py fails when a route is added without being classified.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import registry
from .auth import need
from .common import act_as, audit, db, now_s, rows, today
from .db import TENANT, connect

router = APIRouter()


def module_gate(request: Request) -> None:
    p = request.url.path
    if not p.startswith("/api/"):
        return
    owners = registry.route_module(p)
    if owners is None:
        return
    c = connect()  # registered in db.OPEN: closed with the request
    mods = registry.enabled_modules(c)
    request.state.mods = mods
    if not set(owners) & mods:
        raise HTTPException(404, "Not Found")


# ------------------------------------------------------------------ administrator
@router.get("/api/modules")
def modules_list(_=Depends(need("admin"))):
    c = db()
    return {"modules": registry.describe(c),
            "bundles": [{"key": k, "title": b["title"], "modules": [m for m in b["modules"] if registry.MODULES[m]["available"]], "price": b["price"]}
                        for k, b in registry.BUNDLES.items()]}


class ModulesIn(BaseModel):
    modules: list[str] = Field(max_length=20)
    with_deps: bool = False


@router.post("/api/modules")
def modules_set(body: ModulesIn, u=Depends(act_as("admin"))):
    """Set the complete list of modules that should be on. Data is never touched; a module that is off simply disappears."""
    c = db()
    tenant_lic = registry.licensed(TENANT.get())
    want = set(body.modules)
    unknown = [k for k in want if k not in registry.MODULES or not registry.MODULES[k]["available"]]
    if unknown:
        raise HTTPException(400, "وحدة غير معروفة أو غير متاحة بعد: " + "، ".join(unknown))
    if body.with_deps:
        grow = True
        while grow:
            add = {d for k in want for d in registry.MODULES[k]["deps"]} - want
            want |= add
            grow = bool(add)
    not_lic = sorted(k for k in want if k not in tenant_lic)
    if not_lic:
        raise HTTPException(403, "وحدات غير مشمولة بترخيص المؤسسة: " + "، ".join(registry.MODULES[k]["title"] for k in not_lic))
    missing = {k: [d for d in registry.MODULES[k]["deps"] if d not in want] for k in want}
    missing = {k: v for k, v in missing.items() if v}
    if missing:
        raise HTTPException(409, "؛ ".join(f"«{registry.MODULES[k]['title']}» تحتاج «{'، '.join(registry.MODULES[d]['title'] for d in v)}»"
                                          for k, v in missing.items()) + " — فعّلها معها")
    before = registry.enabled_modules(c)
    stamp, by = now_s(), u["name"]
    for k in registry.available():
        on = 1 if k in want else 0
        if c.execute("UPDATE org_modules SET enabled=?, changed_at=?, changed_by=? WHERE module=?", (on, stamp if (k in before) != (k in want) else None, by, k)).rowcount == 0:
            c.execute("INSERT INTO org_modules(module, enabled, changed_at, changed_by) VALUES(?,?,?,?)", (k, on, stamp, by))
    for k in registry.available():
        if (k in before) != (k in want):
            audit(c, "تفعيل وحدة" if k in want else "تعطيل وحدة", registry.MODULES[k]["title"])
    c.commit()
    return {"ok": True, "enabled": sorted(want), "changed": sorted(want ^ before)}


@router.get("/api/license")
def license_info(_=Depends(need("view"))):
    c = db()
    lic = registry.licensed(TENANT.get())
    log = rows(c.execute("SELECT at, actor, action, detail FROM audit WHERE action IN ('تفعيل وحدة','تعطيل وحدة') ORDER BY id DESC LIMIT 30"))
    return {"licensed": [{"key": k, "title": registry.MODULES[k]["title"]} for k in registry.MODULES if k in lic],
            "not_licensed": [{"key": k, "title": registry.MODULES[k]["title"]} for k in registry.available() if k not in lic],
            "soon": [{"key": k, "title": m["title"]} for k, m in registry.MODULES.items() if not m["available"]],
            "log": log}


# ------------------------------------------------------------------ decisions and dashboard
def visible_decisions(c, items: list[dict]) -> list[dict]:
    """Decisions whose owning module is off are not shown (and cannot be acted on)."""
    on = registry.enabled_modules(c)
    return [d for d in items if registry.DECISION_MODULE.get(d["kind"], "finance") in on]


def lease_summary(c) -> dict:
    t = today().isoformat()
    units = c.execute("SELECT COUNT(*) FROM units WHERE retained=1").fetchone()[0]
    leased = c.execute("""SELECT COUNT(DISTINCT l.unit_id) FROM leases l JOIN units u ON u.id=l.unit_id
                          WHERE l.status='active' AND u.retained=1""").fetchone()[0]
    annual = c.execute("SELECT COALESCE(SUM(annual_rent),0) FROM leases WHERE status='active'").fetchone()[0]
    arrears = c.execute("SELECT COALESCE(SUM(amount-paid),0) FROM rent_dues WHERE due<=? AND paid<amount AND COALESCE(kind,'rent')<>'deposit'", (t,)).fetchone()[0]
    soon = (today() + dt.timedelta(days=90)).isoformat()
    expiring = c.execute("SELECT COUNT(*) FROM leases WHERE status='active' AND \"end\">=? AND \"end\"<=?", (t, soon)).fetchone()[0]
    return {"units": units, "leased": leased, "occupancy": round(leased / units * 100) if units else 0,
            "annual_rent": round(annual), "arrears": round(arrears), "expiring_90": expiring}


def lease_properties(c) -> list[dict]:
    t = today().isoformat()
    out = []
    for p in c.execute("""SELECT p.id, p.name, p.location, COUNT(u.id) units FROM projects p JOIN units u ON u.project_id=p.id
                          WHERE u.retained=1 GROUP BY p.id, p.name, p.location ORDER BY p.id"""):
        leased = c.execute("""SELECT COUNT(DISTINCT l.unit_id), COALESCE(SUM(l.annual_rent),0) FROM leases l JOIN units u ON u.id=l.unit_id
                              WHERE u.project_id=? AND l.status='active'""", (p["id"],)).fetchone()
        arrears = c.execute("""SELECT COALESCE(SUM(d.amount-d.paid),0) FROM rent_dues d JOIN leases l ON l.id=d.lease_id
                               JOIN units u ON u.id=l.unit_id WHERE u.project_id=? AND d.due<=? AND d.paid<d.amount AND COALESCE(d.kind,'rent')<>'deposit'""", (p["id"], t)).fetchone()[0]
        out.append({"id": p["id"], "name": p["name"], "location": p["location"], "units": p["units"], "leased": leased[0],
                    "occupancy": round(leased[0] / p["units"] * 100) if p["units"] else 0,
                    "annual_rent": round(leased[1]), "arrears": round(arrears)})
    return out


def dashboard(c) -> dict:
    """Widgets of the modules that are on — an organisation that only leases sees no sales figure at all."""
    from . import engines as E
    on = registry.enabled_modules(c)
    tiles: list[dict] = []
    out: dict = {"modules": sorted(on), "tiles": tiles, "decisions": visible_decisions(c, E.decisions(c))}
    if "sales" in on:
        k = E.kpis(c, None)
        tiles += [{"id": "sales30", "label": "مبيعات آخر 30 يومًا", "value": k["sales_30d_value"], "unit": "omr", "sub": f"{k['sales_30d_count']} وحدة"},
                  {"id": "collection", "label": "نسبة التحصيل (90 يومًا)", "value": k["collection_rate"], "unit": "pct", "sub": "من الأقساط المستحقة"},
                  {"id": "stock", "label": "المخزون المتاح", "value": k["available"], "unit": "n", "sub": f"من {k['total_units']} وحدة"}]
    if "finance" in on:
        cr = E.cash_radar(c)
        tiles.append({"id": "cashgap", "label": "فجوة السيولة المتوقعة", "value": cr["gap"], "unit": "omr", "tone": "bad" if cr["gap"] else "ok",
                      "sub": cr["worst_project"] if cr["gap"] else "خلال 12 شهرًا",
                      "sub_month": cr["worst"]["month"] if cr["gap"] else None, "zero_text": "لا توجد"})
        out["cash"] = {"gap": cr["gap"], "projects": cr["projects"]}
    if "leasing" in on:
        s = lease_summary(c)
        tiles += [{"id": "occupancy", "label": "نسبة الإشغال", "value": s["occupancy"], "unit": "pct", "sub": f"{s['leased']} من {s['units']} وحدة مؤجَّرة"},
                  {"id": "annualrent", "label": "الإيجار السنوي (العقود السارية)", "value": s["annual_rent"], "unit": "omr", "sub": ""},
                  {"id": "arrears", "label": "متأخرات الإيجار", "value": s["arrears"], "unit": "omr", "tone": "bad" if s["arrears"] else "ok", "sub": "", "zero_text": "لا متأخرات"},
                  {"id": "expiring", "label": "عقود تنتهي خلال 90 يومًا", "value": s["expiring_90"], "unit": "n", "sub": ""}]
        out["lease_properties"] = lease_properties(c)
    out["develop"] = bool(on & {"sales", "construction", "land"})
    return out
