"""Mabaniq — profile-driven developer organisations (0.13.0).

A *profile* describes a real developer's portfolio (projects, buildings, unit mix, illustrative prices, letterhead and a set of
bundled sample images) so the demo seed can stand up a tenant that looks like that developer instead of the generic Jadwa
demo. The first profile is **المخطط العقارية (Al Mukhatat Real Estate)** — a pilot agreed with its CEO Dr. Dawood Al Hinai
(trial of the platform on his company's public material: almukhatat.com, the Maab brochure and @almukhatatreale).

Facts come from the company's public website/brochure; **prices, sold ratios, buyers, payments and schedules are illustrative**
(the company does not publish prices) and are flagged as such in the platform's documentation. No person appears in any asset.

The seed keeps its three internal *slots* (RAY = large tower mid-build, SEB = slow early tower, KHD = villas near handover) so
every later seed stage (permits, IPCs, resale, discounts, handovers…) still finds the project it expects; the profile maps each
slot to the real project code/name and may add further projects (slot MLZ here).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import tenants_extra

ASSETS = Path(__file__).resolve().parent / "assets" / "samples"


def tenants_from_env() -> dict:
    """`MABANIQ_TENANTS="code:الاسم;code2:الاسم"` — developer organisations added by configuration (persistent on Railway, where
    data/tenants.json is lost with the container). Codes follow the tenant slug rule (lowercase, digits, dash)."""
    out = {}
    for part in tenants_extra().split(";"):
        part = part.strip()
        if not part:
            continue
        code, _, name = part.partition(":")
        code = code.strip().lower()
        if code:
            out[code] = name.strip() or PROFILES.get(code, {}).get("display", code)
    return out


# ----------------------------------------------------------------------------------------------------------------------- profiles
# unit spec: (type label, area m², view/orientation, illustrative price per m² in OMR, use)
_MAAB_FLOOR = [("نموذج 01 — غرفتان وصالة", 97.70, "جبلي", 690, "residential"), ("نموذج 02 — غرفة وصالة", 67.10, "جبلي", 705, "residential"),
               ("نموذج 03 — غرفة وصالة", 63.60, "شارع الجامعة", 695, "residential"), ("نموذج 04 — غرفة وصالة", 67.00, "شارع الجامعة", 695, "residential"),
               ("نموذج 05 — غرفة وصالة", 62.60, "داخلي", 665, "residential"), ("شقة فندقية — غرفة وصالة", 63.60, "جبلي", 770, "hotel")]
_MAAB_SHOPS = [("محل تجاري", a, "شارع الجامعة", 1450, "commercial") for a in (25.28, 23.70, 23.70, 23.70, 25.28, 24.49)]
_MRT_RES = [("شقة 61 م² — غرفة وصالة", 61.25, "شارع نستو", 630, "residential"), ("شقة 78 م² — غرفتان وصالة", 78.0, "شارع نستو", 625, "residential"),
            ("شقة 95 م² — غرفتان وصالة", 95.0, "داخلي", 600, "residential"), ("شقة 112 م² — 3 غرف وصالة", 112.0, "داخلي", 600, "residential"),
            ("شقة 132 م² — 3 غرف وصالة", 132.6, "شارع نستو", 640, "residential")]
_MRT_OFF = [("مكتب", a, "شارع نستو" if i % 2 == 0 else "داخلي", 560, "commercial") for i, a in enumerate((50, 62, 75, 88, 100) * 3)]
_MRT_SHOPS = [("محل تجاري", a, "شارع نستو", 1300, "commercial") for a in (22, 24, 26, 28, 30, 32, 34, 38, 40, 44, 46)]
_MLZ_FLOOR = [("نموذج 1 — 3 غرف وصالة", 113.80, "الحديقة", 660, "residential"), ("نموذج 2 — غرفة وصالة", 63.0, "شارع النزهة", 680, "residential"),
              ("نموذج 3 — غرفة وصالة", 58.0, "شارع النزهة", 680, "residential"), ("نموذج 4 — غرفة وصالة", 58.70, "داخلي", 650, "residential"),
              ("نموذج 5 — غرفة وصالة", 60.0, "الحديقة", 665, "residential"), ("نموذج 6 — غرفة وصالة", 59.10, "داخلي", 650, "residential")]

PROFILES: dict[str, dict] = {
    "almukhatat": {
        "display": "المخطط العقارية",
        "seed": 2010,
        "brand": {"name": "شركة المخطط العقارية", "address": "المعبيلة الجنوبية، محافظة مسقط، سلطنة عُمان", "phone": "72700099",
                  "email": "contact@almukhatat.com", "signatory": "", "signatory_title": "رئيس مجلس الإدارة والرئيس التنفيذي"},
        # slot, code, name, location, kind, build %, planned monthly sales, handover (months from today), escrow balance (illustrative)
        "projects": [
            ("RAY", "MAB", "مشروع مآب", "الخوض — شارع جامعة السلطان قابوس", "tower", 58, 5, 10, "200000"),
            ("SEB", "MRT", "مشروع مرتيل", "المعبيلة الجنوبية — شارع نستو", "tower", 34, 4, 18, "150000"),
            ("KHD", "JWR", "مساكن جوار", "الموالح الجنوبية", "villa", 90, 3, 4, "80000"),
            ("MLZ", "MLZ", "مشروع ملاذ", "المعبيلة — شارع النزهة", "tower", 46, 4, 12, "120000"),
        ],
        # buildings: slot, building, floors (first, last), per-floor specs, floor uplift, sold probability by view
        "buildings": [
            ("RAY", "A", (0, 0), _MAAB_SHOPS, 0, {"شارع الجامعة": .5}),
            ("RAY", "A", (1, 7), _MAAB_FLOOR, .012, {"جبلي": .72, "شارع الجامعة": .6, "داخلي": .48}),
            ("SEB", "M", (0, 0), _MRT_SHOPS, 0, {"شارع نستو": .45}),
            ("SEB", "M", (1, 2), _MRT_OFF, .01, {"شارع نستو": .3, "داخلي": .22}),
            ("SEB", "M", (3, 7), _MRT_RES, .012, {"شارع نستو": .4, "داخلي": .3}),
            ("MLZ", "L", (1, 12), _MLZ_FLOOR, .01, {"الحديقة": .55, "شارع النزهة": .5, "داخلي": .42}),
        ],
        # villas: slot, building, count, (type, area, base price) by rule, views by position
        "villas": {"slot": "KHD", "building": "V", "count": 40,
                   "types": [("فيلا 3 غرف — 200 م²", 200, 98000), ("فيلا 4 غرف — 240 م²", 240, 118000)],
                   "views": {"زاوية": .85, "قرب المسجد": .78, "داخلية": .62}},
        "interests": {"RAY": ["نموذج 01 غرفتان وصالة", "شقة فندقية للاستثمار", "محل على شارع الجامعة", "عائد إيجاري"],
                      "SEB": ["مكتب 50 م²", "شقة 61 م²", "محل على شارع نستو", "مكتب بمدخل مستقل"],
                      "KHD": ["فيلا زاوية", "فيلا 4 غرف", "تمويل من بنك نزوى"],
                      "MLZ": ["نموذج 1 ثلاث غرف", "غرفة وصالة قرب مسقط مول", "شقة فندقية"]},
        "lead_mix": ["RAY", "RAY", "MLZ", "SEB", "KHD"],
        "cycle_names": {"AMR": ("مركز داود للأعمال", "الخوض السابعة"), "QRM": ("مساكن الفخامة 11", "بوشر")},
        # bundled sample assets → plans (kind, title, building, floor, unit_type, public) or brand logo
        "assets": [
            ("almukhatat/almukhatat-logo.png", "brand", "logo", None, None, None, 0),
            ("almukhatat/maab-site-map.jpg", "RAY", "site", "موقع المشروع — الخوض، شارع الجامعة", None, None, 1),
            ("almukhatat/maab-nearby.jpg", "RAY", "site", "المواقع القريبة (طريق مسقط السريع، جامعة السلطان قابوس، البندر لولو)", None, None, 1),
            ("almukhatat/maab-plan-shops-ground.jpg", "RAY", "floor", "مخطط المحلات التجارية — الطابق الأرضي", "A", 0, 1),
            ("almukhatat/maab-plan-typical-floor.jpg", "RAY", "floor", "مخطط الطابق المتكرر", "A", 1, 1),
            ("almukhatat/maab-plan-unit-01.jpg", "RAY", "unit", "نموذج الوحدة 01 — 97.70 م²", "A", None, "نموذج 01 — غرفتان وصالة", 1),
            ("almukhatat/maab-plan-units-02-03.jpg", "RAY", "unit", "نموذجا الوحدة 02 و03 — 67.10 و63.60 م²", "A", None, "نموذج 02 — غرفة وصالة", 1),
            ("almukhatat/maab-plan-units-04-05.jpg", "RAY", "unit", "نموذجا الوحدة 04 و05 — 67.00 و62.60 م²", "A", None, "نموذج 04 — غرفة وصالة", 1),
            ("almukhatat/maab-brochure-cover.jpg", "RAY", "render", "التصور النهائي للمبنى (غلاف الكتيّب)", None, None, 1),
            ("almukhatat/maab-render-01.jpg", "RAY", "render", "مآب — وجهة عصرية وفرصة استثمارية", None, None, 1),
            ("almukhatat/maab-render-02.jpg", "RAY", "render", "التصور النهائي — الواجهة الجبلية", None, None, 1),
            ("almukhatat/maab-render-03.jpg", "RAY", "render", "التصور النهائي — المدخل والمحلات", None, None, 1),
            ("almukhatat/maab-interior-living.jpg", "RAY", "render", "تصور داخلي — الصالة", None, None, 1),
            ("almukhatat/maab-interior-bedroom.jpg", "RAY", "render", "تصور داخلي — غرفة النوم", None, None, 1),
            ("almukhatat/maab-interior-kitchen-dining.jpg", "RAY", "render", "تصور داخلي — المطبخ وركن الطعام", None, None, 1),
            ("almukhatat/maab-interior-salon.jpg", "RAY", "render", "تصور داخلي — غرفة المعيشة بتشطيب فندقي", None, None, 1),
            ("almukhatat/maab-interior-kitchen.jpg", "RAY", "render", "تصور داخلي — المطبخ", None, None, 1),
            ("almukhatat/maab-interior-gym.jpg", "RAY", "render", "الصالة الرياضية", None, None, 1),
            ("almukhatat/maab-amenities.jpg", "RAY", "render", "الخدمات: صالة رياضية، بركة سباحة، صالة ألعاب أطفال", None, None, 1),
            ("almukhatat/malath-render-banner.jpg", "MLZ", "render", "مشروع ملاذ — استثمار في سكن المستقبل", None, None, 1),
            ("almukhatat/malath-interior-bedroom.jpg", "MLZ", "render", "تصور داخلي — غرفة النوم", None, None, 1),
        ],
        # markers on the typical floor plan (percent of the image, approximate — illustrative placement of floor-1 units)
        "markers": {"almukhatat/maab-plan-typical-floor.jpg": [("MAB-A-101", 64, 48), ("MAB-A-102", 62, 18), ("MAB-A-103", 24, 78),
                                                             ("MAB-A-104", 24, 20), ("MAB-A-105", 62, 80), ("MAB-A-106", 45, 82)]},
    },
}


def profile(tenant: str) -> dict | None:
    return PROFILES.get(tenant)


def profile_units(p: dict) -> list[tuple]:
    """→ [(slot, unit code, building, floor, pos, type, area, view, price, sold probability)] in the seed's tuple shape."""
    code_of = {slot: code for slot, code, *_ in p["projects"]}
    units = []
    for slot, bld, (f0, f1), specs, uplift, sold in p.get("buildings", []):
        code = code_of[slot]
        for f in range(f0, f1 + 1):
            for pos, (tp, ar, vw, ppm, use) in enumerate(specs, 1):
                units.append((slot, f"{code}-{bld}-{f}{pos:02d}", bld, f, pos, tp, ar, vw, ppm * ar * (1 + f * uplift), sold[vw], use))
    v = p.get("villas")
    if v:
        code = code_of[v["slot"]]
        views = list(v["views"].items())
        for i in range(1, v["count"] + 1):
            tp, ar, base = v["types"][0] if i % 3 else v["types"][1]
            vw, ps = views[0] if i % 5 in (1, 0) else views[1] if v["count"] // 3 <= i <= 2 * v["count"] // 3 else views[2]
            units.append((v["slot"], f"{code}-{v['building']}-{i:03d}", v["building"], 0, i, tp, ar, vw,
                          base * (1.06 if vw == views[0][0] else 1.03 if vw == views[1][0] else 1), ps, "residential"))
    return units


def apply_brand(c, p: dict) -> None:
    for k, v in p.get("brand", {}).items():
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"brand:{k}", v))
    c.execute("INSERT OR REPLACE INTO settings VALUES('tenant_name',?)", (json.dumps(p["display"], ensure_ascii=False),))


def ensure_assets(c, tenant: str, p: dict | None = None) -> int:
    """Materialise the profile's bundled sample images as validated documents (+ plans / letterhead logo). Idempotent and
    self-healing: runs at every start-up, so an ephemeral container (Railway without a volume) gets its files back after a
    redeploy, and a database seeded earlier gains assets added later. Returns the number of files written."""
    from .modules2 import _docs_dir
    p = p or profile(tenant)
    if not p or not p.get("assets"):
        return 0
    if type(c).__name__ == "PgConn":
        c.execute("SELECT pg_advisory_xact_lock(7340128)")  # several uvicorn workers start together — one materialises, the rest find it
    proj = {r["code"]: r["id"] for r in c.execute("SELECT id, code FROM projects").fetchall()}
    code_of = {slot: code for slot, code, *_ in p["projects"]}
    written = 0
    by_rel: dict[str, int] = {}
    for entry in p["assets"]:  # (file, slot|brand, kind, title, building, floor[, unit_type], public)
        rel, slot, kind, title, bld, fl = entry[:6]
        unit_type, public = (entry[6], entry[7]) if len(entry) == 8 else (None, entry[6])
        if kind == "logo":
            unit_type, public = None, 0
        src = ASSETS / rel
        if not src.exists():
            continue
        data = src.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        ext = ".png" if data.startswith(b"\x89PNG") else ".jpg"
        mime = "image/png" if ext == ".png" else "image/jpeg"
        ref_type = "brand" if slot == "brand" else "plan"
        ref_id = 0 if slot == "brand" else proj.get(code_of.get(slot, ""), 0)
        if not ref_id and slot != "brand":
            continue
        row = c.execute("SELECT id, stored FROM documents WHERE sha256=? AND ref_type=? AND ref_id=?", (sha, ref_type, ref_id)).fetchone()
        if row:
            did, stored = row["id"], row["stored"]
        else:
            stored = "sample-" + sha[:24] + ext
            did = c.execute("INSERT INTO documents(ref_type,ref_id,title,category,filename,mime,size,sha256,stored,uploaded_by,at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (ref_type, ref_id, title or "شعار المطوّر", "الهوية" if slot == "brand" else kind, Path(rel).name, mime, len(data), sha, stored,
                             "عيّنة المنصة", "1970-01-01 00:00")).lastrowid
        dest = _docs_dir() / stored
        if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest() != sha:
            dest.write_bytes(data)
            written += 1
        by_rel[rel] = did
        if slot == "brand":
            c.execute("INSERT OR REPLACE INTO settings VALUES('brand:logo_doc',?)", (str(did),))
        elif not c.execute("SELECT 1 FROM plans WHERE document_id=?", (did,)).fetchone():
            c.execute("INSERT INTO plans(project_id,building,floor,unit_type,kind,title,document_id,markers,public,created,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (ref_id, bld, fl, unit_type, kind, title, did, "[]", 1 if public else 0, "1970-01-01 00:00", "عيّنة المنصة"))
    for rel, marks in p.get("markers", {}).items():
        did = by_rel.get(rel)
        if not did:
            continue
        known = {r["code"] for r in c.execute("SELECT code FROM units").fetchall()}
        ms = [{"unit_code": u, "x": x, "y": y} for u, x, y in marks if u in known]
        c.execute("UPDATE plans SET markers=? WHERE document_id=? AND markers='[]'", (json.dumps(ms, ensure_ascii=False), did))
    c.commit()
    return written


__all__ = ["PROFILES", "ASSETS", "profile", "profile_units", "apply_brand", "ensure_assets", "tenants_from_env"]
