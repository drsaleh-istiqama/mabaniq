"""Mabaniq — organisation appearance (0.18.0): background palette, pattern, size and optional own image.

One JSON document per developer organisation in `settings` (`ui:appearance`); the tenant database already isolates organisations,
so no tenant column is needed. Everything is a *whitelist*: the browser only ever receives preset names and clamped numbers —
never raw CSS — because the platform's CSP forbids `<style>` and the values end up in CSS custom properties.

The palettes themselves live in `web/shell.css` (`html[data-bg=…]`); this module only validates the choice and serves it.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .auth import current
from .common import act_as, audit, db
from .db import setting

router = APIRouter()

KEY = "ui:appearance"

# palette id → Arabic label (the colour values are in shell.css so the browser can paint before any request returns)
PRESETS = {
    "navy": "كحلي (الافتراضي)",
    "graphite": "فحمي",
    "forest": "أخضر غابي",
    "midnight": "أزرق ليلي",
    "plum": "بنفسجي داكن",
    "bronze": "برونزي دافئ",
}
PATTERNS = {"none": "بلا نقش", "dots": "نقاط", "grid": "شبكة", "lines": "خطوط مائلة", "image": "صورة المؤسسة"}
FITS = {"cover": "تغطية الشاشة", "contain": "احتواء كامل", "tile": "تكرار (بلاط)"}
MODES = {"user": "يختار كل مستخدم", "dark": "داكن دائمًا", "light": "فاتح دائمًا"}

DEFAULT = {"preset": "navy", "pattern": "none", "size": 24, "strength": 30, "fit": "cover", "image_doc": 0, "mode": "user"}
LIMITS = {"size": (10, 120), "strength": (5, 100)}


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def sanitize(raw: dict | None) -> dict:
    """Merge a stored/posted document over DEFAULT, dropping anything outside the whitelists."""
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT)
    if raw.get("preset") in PRESETS:
        out["preset"] = raw["preset"]
    if raw.get("pattern") in PATTERNS:
        out["pattern"] = raw["pattern"]
    if raw.get("fit") in FITS:
        out["fit"] = raw["fit"]
    if raw.get("mode") in MODES:
        out["mode"] = raw["mode"]
    out["size"] = _clamp(raw.get("size"), *LIMITS["size"], DEFAULT["size"])
    out["strength"] = _clamp(raw.get("strength"), *LIMITS["strength"], DEFAULT["strength"])
    out["image_doc"] = _clamp(raw.get("image_doc"), 0, 10**9, 0)
    if out["pattern"] == "image" and not out["image_doc"]:
        out["pattern"] = "none"  # a picture pattern without a picture is meaningless
    return out


def load(c) -> dict:
    try:
        return sanitize(json.loads(setting(c, KEY) or "{}"))
    except (TypeError, ValueError):
        return dict(DEFAULT)


class AppearanceIn(BaseModel):
    preset: str | None = Field(default=None, max_length=20)
    pattern: str | None = Field(default=None, max_length=20)
    fit: str | None = Field(default=None, max_length=20)
    mode: str | None = Field(default=None, max_length=20)
    size: int | None = None
    strength: int | None = None
    image_doc: int | None = None


@router.get("/api/appearance")
def appearance_get(_=Depends(current)):
    return {**load(db()), "options": {"presets": PRESETS, "patterns": PATTERNS, "fits": FITS, "modes": MODES, "limits": LIMITS}}


@router.post("/api/admin/appearance")
def appearance_set(body: AppearanceIn, _=Depends(act_as("admin"))):
    c = db()
    cur = load(c)
    posted = {k: v for k, v in body.model_dump().items() if v is not None}
    for k, allowed in (("preset", PRESETS), ("pattern", PATTERNS), ("fit", FITS), ("mode", MODES)):
        if k in posted and posted[k] not in allowed:
            raise HTTPException(400, f"قيمة غير مسموحة للحقل «{k}»")
    did = posted.get("image_doc")
    if did and not c.execute("SELECT 1 FROM documents WHERE id=? AND ref_type='brand' AND mime IN ('image/png','image/jpeg')", (did,)).fetchone():
        raise HTTPException(400, f"المستند {did} ليس صورة مرفوعة ضمن هوية المؤسسة")
    new = sanitize({**cur, **posted})
    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (KEY, json.dumps(new, ensure_ascii=False)))
    audit(c, "تحديث مظهر المنصة", f"{new['preset']} · {new['pattern']} · {new['size']}px · {new['mode']}")
    c.commit()
    return {**new, "options": {"presets": PRESETS, "patterns": PATTERNS, "fits": FITS, "modes": MODES, "limits": LIMITS}}


@router.get("/api/appearance/image")
def appearance_image(doc: int | None = None, u=Depends(current)):
    """The organisation's own background picture — served to any signed-in staff user (the generic /api/documents needs `docs`).
    `?doc=<id>` lets an administrator preview an uploaded picture before saving it as the organisation's background."""
    import hashlib

    from .modules2 import _docs_dir
    c = db()
    did = doc if (doc and "admin" in u["perms"]) else load(c)["image_doc"]
    d = c.execute("SELECT stored, sha256, mime FROM documents WHERE id=? AND ref_type='brand'", (did,)).fetchone() if did else None
    if not d:
        raise HTTPException(404, "لا توجد صورة خلفية")
    path = _docs_dir() / d["stored"]
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != d["sha256"]:
        raise HTTPException(409, "تعذّر التحقق من سلامة الملف")
    return FileResponse(path, media_type=d["mime"], headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"})
