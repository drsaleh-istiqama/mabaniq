"""Mabaniq — building plans (Unit 6): architectural and structural drawings, unit-type plans, elevations, final renders.

Plans are uploaded files (PDF/PNG/JPEG through the same validated store as other documents) attached to a project, optionally
to a building and a floor, or to a unit type. A floor plan carries **markers**: the position of each unit on the drawing
(percent coordinates), so staff see occupancy on the real plan and a customer sees exactly where their apartment or shop is.
Visibility: everything except `structural` drawings is shown to customers for their own unit's project; structural drawings
and anything flagged non-public stay internal.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import auth as A
from .auth import need, need_any
from .common import act_as, audit, db, now_s, rows
from .modules import one

router = APIRouter()
KINDS = {"site": "المخطط العام للموقع", "floor": "مخطط طابق", "unit": "مخطط نموذج الوحدة", "elevation": "واجهة", "section": "قطاع",
         "render": "تصور نهائي", "structural": "مخطط إنشائي", "mep": "مخطط كهروميكانيكي"}
INTERNAL = {"structural", "mep"}


@router.get("/api/plans/kinds")
def plan_kinds(_=Depends(need("view"))):
    return [{"kind": k, "label": v, "internal": k in INTERNAL} for k, v in KINDS.items()]


@router.post("/api/plans")
async def plan_upload(project_id: int = Form(...), kind: str = Form(...), title: str = Form(..., min_length=2, max_length=100),
                      building: str = Form(""), floor: str = Form(""), unit_type: str = Form(""), public: int = Form(1),
                      file: UploadFile = File(...), u=Depends(act_as("docs"))):
    if kind not in KINDS:
        raise HTTPException(400, "نوع المخطط غير معروف")
    c = db()
    p = one(c, "SELECT id, name FROM projects WHERE id=?", (project_id,), "المشروع غير موجود")
    from .modules2 import MAX_DOC, store_upload
    data = await file.read(MAX_DOC + 1)
    did, _sha = store_upload(c, data, file.filename, "plan", project_id, title, KINDS[kind], u["name"])
    fl = int(floor) if str(floor).strip().lstrip("-").isdigit() else None
    pub = 0 if kind in INTERNAL else (1 if int(public) else 0)
    pid = c.execute("INSERT INTO plans(project_id,building,floor,unit_type,kind,title,document_id,markers,public,created,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (project_id, building.strip() or None, fl, unit_type.strip() or None, kind, title, did, "[]", pub, now_s(), u["name"])).lastrowid
    audit(c, "رفع مخطط", f"{KINDS[kind]} «{title}» للمشروع {p['name']}{' / ' + building if building else ''}{' / ط ' + str(fl) if fl is not None else ''}")
    c.commit()
    return plan_row(c, pid)


def plan_row(c, pid: int) -> dict:
    r = one(c, "SELECT pl.*, d.mime, d.filename, d.size FROM plans pl JOIN documents d ON d.id=pl.document_id WHERE pl.id=?", (pid,), "المخطط غير موجود")
    d = dict(r)
    d["markers"] = json.loads(d["markers"] or "[]")
    d["kind_label"] = KINDS.get(d["kind"], d["kind"])
    d["url"] = f"/api/documents/{d['document_id']}"
    return d


@router.get("/api/plans")
def plan_list(project_id: int, _=Depends(need("view"))):
    c = db()
    out = []
    for r in c.execute("SELECT id FROM plans WHERE project_id=? ORDER BY CASE kind WHEN 'site' THEN 0 WHEN 'floor' THEN 1 WHEN 'unit' THEN 2 ELSE 3 END, building, floor, id", (project_id,)):
        out.append(plan_row(c, r["id"]))
    return out


class MarkersIn(BaseModel):
    markers: list[dict] = Field(default_factory=list, max_length=400)


@router.post("/api/plans/{pid}/markers")
def plan_markers(pid: int, body: MarkersIn, u=Depends(act_as("inventory"))):
    """markers: [{unit_code, x, y}] — x/y in percent of the image. Unknown unit codes are rejected; one marker per unit."""
    c = db()
    pl = plan_row(c, pid)
    clean, seen = [], set()
    for m in body.markers:
        code = str(m.get("unit_code", "")).strip()
        try:
            x, y = float(m.get("x")), float(m.get("y"))
        except (TypeError, ValueError):
            raise HTTPException(400, "إحداثيات غير صالحة") from None
        if not (0 <= x <= 100 and 0 <= y <= 100):
            raise HTTPException(400, "الإحداثيات بالنسبة المئوية من 0 إلى 100")
        if code in seen:
            continue
        unit = c.execute("SELECT id FROM units WHERE code=? AND project_id=?", (code, pl["project_id"])).fetchone()
        if not unit:
            raise HTTPException(404, f"الوحدة {code} ليست في هذا المشروع")
        seen.add(code)
        clean.append({"unit_code": code, "x": round(x, 2), "y": round(y, 2)})
    c.execute("UPDATE plans SET markers=? WHERE id=?", (json.dumps(clean, ensure_ascii=False), pid))
    audit(c, "تحديد مواقع الوحدات على المخطط", f"{pl['title']} · {len(clean)} وحدة")
    c.commit()
    return plan_row(c, pid)


class PlanPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=100)
    public: bool | None = None
    building: str | None = Field(default=None, max_length=40)
    floor: int | None = None
    unit_type: str | None = Field(default=None, max_length=60)


@router.post("/api/plans/{pid}")
def plan_patch(pid: int, body: PlanPatch, u=Depends(act_as("docs"))):
    c = db()
    pl = plan_row(c, pid)
    if body.title is not None:
        c.execute("UPDATE plans SET title=? WHERE id=?", (body.title, pid))
    if body.public is not None:
        c.execute("UPDATE plans SET public=? WHERE id=?", (0 if pl["kind"] in INTERNAL else int(body.public), pid))
    for k in ("building", "floor", "unit_type"):
        v = getattr(body, k)
        if v is not None:
            c.execute(f"UPDATE plans SET {k}=? WHERE id=?", (v or None, pid))
    audit(c, "تعديل مخطط", pl["title"])
    c.commit()
    return plan_row(c, pid)


@router.post("/api/plans/{pid}/remove")
def plan_remove(pid: int, u=Depends(act_as("docs"))):
    c = db()
    pl = plan_row(c, pid)
    c.execute("DELETE FROM plans WHERE id=?", (pid,))
    audit(c, "إزالة مخطط", f"{pl['title']} (الملف يبقى في سجل المستندات)")
    c.commit()
    return {"ok": True}


@router.get("/api/units/{code}/plans")
def unit_plans(code: str, _=Depends(need_any("view", "inventory"))):
    """Plans relevant to one unit: its floor plan with its marker, its unit-type plan, the site plan and the renders."""
    c = db()
    u = one(c, "SELECT * FROM units WHERE code=?", (code,), "الوحدة غير موجودة")
    return _unit_plans(c, u, internal=True)


def _unit_plans(c, u, internal: bool) -> dict:
    out = {"unit": u["code"], "floor_plan": None, "unit_plan": None, "others": []}
    for r in c.execute("SELECT id FROM plans WHERE project_id=? ORDER BY id", (u["project_id"],)):
        pl = plan_row(c, r["id"])
        if not internal and (pl["kind"] in INTERNAL or not pl["public"]):
            continue
        mine = next((m for m in pl["markers"] if m["unit_code"] == u["code"]), None)
        same_bld = (pl["building"] or "") in ("", u["building"] or "")
        if pl["kind"] == "floor" and (mine or (same_bld and pl["floor"] == u["floor"])) and out["floor_plan"] is None:
            out["floor_plan"] = {**pl, "me": mine}
        elif pl["kind"] == "unit" and (pl["unit_type"] or "") in ("", u["type"]) and same_bld and out["unit_plan"] is None:
            out["unit_plan"] = pl
        elif pl["kind"] in ("site", "render", "elevation", "section") and same_bld:
            out["others"].append(pl)
    if not internal:
        for k in ("floor_plan", "unit_plan"):
            if out[k]:
                out[k]["url"] = f"/api/portal/plans/{out[k]['document_id']}"
                out[k]["markers"] = [m for m in out[k]["markers"] if m["unit_code"] == u["code"]]  # a customer sees only their own marker
        for o in out["others"]:
            o["url"] = f"/api/portal/plans/{o['document_id']}"
            o["markers"] = []
    return out


@router.get("/api/portal/plans")
def portal_plans(u=Depends(need("portal"))):
    c = db()
    out = []
    bookings = rows(c.execute("SELECT id, unit_id FROM bookings WHERE customer_id=? AND status!='cancelled' ORDER BY id", (u["customer_id"],)))
    for b in bookings:
        un = c.execute("SELECT * FROM units WHERE id=?", (b["unit_id"],)).fetchone()
        out.append({"booking_id": b["id"], **_unit_plans(c, un, internal=False)})
    return out


@router.get("/api/portal/plans/{did}")
def portal_plan_file(did: int, u=Depends(need("portal"))):
    c = db()
    pl = c.execute("SELECT * FROM plans WHERE document_id=? AND public=1", (did,)).fetchone()
    if not pl or pl["kind"] in INTERNAL:
        raise HTTPException(404, "المخطط غير متاح")
    if not c.execute("SELECT 1 FROM bookings b JOIN units un ON un.id=b.unit_id WHERE b.customer_id=? AND b.status!='cancelled' AND un.project_id=?",
                     (u["customer_id"], pl["project_id"])).fetchone():
        raise HTTPException(404, "المخطط غير متاح")
    from .modules2 import _send_doc
    d = one(c, "SELECT * FROM documents WHERE id=?", (did,))
    return _send_doc(d)


__all__ = ["router", "KINDS", "INTERNAL", "A", "rows"]
