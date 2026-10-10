"""Mabaniq — ad creative generator (Unit 7): teaser / launch / offer / last-units / progress / ready-to-move visuals.

Composition is programmatic (no image model): the developer's letterhead, the project's real data (name, location, unit
types, starting price, payment plan, handover, progress) and the staff's own headline/offer are laid out with fpdf2 +
HarfBuzz shaping and self-hosted Tajawal, on an optional background photo (an uploaded render or any PNG/JPEG document).
The page is rendered in pixels (1 pt = 1 px) and rasterised with PyMuPDF to PNG for WhatsApp/social; the PDF is kept for print.
No people are generated or depicted; Arabic text is never produced by an image model (house rule).
"""
from __future__ import annotations

import io
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from .pdfgen import FONTS, hijri, money

SIZES = {"square": (1080, 1080, "مربع (إنستغرام/واتساب)"), "story": (1080, 1920, "قصة (ستوري)"), "wide": (1200, 628, "عريض (فيسبوك/لينكدإن/موقع)")}
TEMPLATES = {
    "teaser": {"label": "تشويقي — قريبًا", "badge": "قريبًا", "headline": "{project}", "sub": "{location}", "cta": "سجّل اهتمامك الآن"},
    "launch": {"label": "إطلاق المبيعات", "badge": "الإطلاق", "headline": "انطلقت مبيعات {project}", "sub": "{types} · الأسعار تبدأ من {price_from}", "cta": "احجز وحدتك قبل نفاد الإطلاق"},
    "offer": {"label": "عرض خاص", "badge": "عرض محدود", "headline": "{offer}", "sub": "{project} · {location}", "cta": "العرض ساري حتى {until}"},
    "last_units": {"label": "آخر الوحدات", "badge": "آخر {available} وحدات", "headline": "آخر الوحدات في {project}", "sub": "{types} · {location}", "cta": "تواصل اليوم قبل نفادها"},
    "progress": {"label": "تقدم البناء", "badge": "إنجاز {build_pct}٪", "headline": "{project} يقترب من التسليم", "sub": "التسليم المتوقع {handover}", "cta": "اشترِ على الخارطة بثقة"},
    "ready": {"label": "جاهزة للسكن", "badge": "جاهزة للتسليم الفوري", "headline": "استلم مفتاحك في {project}", "sub": "{types} · {location}", "cta": "احجز موعد معاينة"},
}
PALETTES = {"gold": ((15, 23, 36), (212, 166, 74), (255, 255, 255)), "green": ((12, 38, 32), (76, 195, 138), (255, 255, 255)),
            "blue": ((14, 27, 51), (106, 166, 245), (255, 255, 255)), "sand": ((245, 240, 230), (156, 110, 20), (26, 20, 5))}


def fill(text: str, ctx: dict) -> str:
    out = text
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", str(v if v not in (None, "") else "—"))
    return out


class Ad(FPDF):
    def __init__(self, w: int, h: int):
        super().__init__(unit="pt", format=(w, h))
        self.add_font("Tajawal", "", str(FONTS / "Tajawal-Regular.ttf"))
        self.add_font("Tajawal", "B", str(FONTS / "Tajawal-Bold.ttf"))
        self.set_text_shaping(use_shaping_engine=True, direction="rtl", script="arab", language="ar")
        self.set_auto_page_break(False)
        self.set_margins(0, 0, 0)

    def header(self):
        pass

    def footer(self):
        pass


def compose(project: dict, brand: dict, template: str, size: str, headline: str | None = None, subline: str | None = None, cta: str | None = None,
            offer: str | None = None, until: str | None = None, bg_path: str | None = None, palette: str = "gold") -> tuple[bytes, bytes | None]:
    """→ (pdf bytes, png bytes or None when PyMuPDF is unavailable)."""
    t = TEMPLATES[template]
    w, h, _ = SIZES[size]
    dark, accent, ink = PALETTES.get(palette, PALETTES["gold"])
    light_bg = sum(dark) > 500
    ctx = {"project": project.get("name"), "location": project.get("location"), "types": project.get("types") or "", "price_from": money(project.get("price_from"), 0) if project.get("price_from") else "—",
           "available": project.get("available"), "build_pct": int(project.get("build_pct") or 0), "handover": hijri(project.get("handover")) if project.get("handover") else "—",
           "offer": offer or "عرض خاص", "until": hijri(until) if until else "إشعار آخر", "developer": brand.get("name") or ""}
    head = fill(headline or t["headline"], ctx)
    sub = fill(subline or t["sub"], ctx)
    call = fill(cta or t["cta"], ctx)
    badge = fill(t["badge"], ctx)

    p = Ad(w, h)
    p.add_page()
    p.set_fill_color(*dark)
    p.rect(0, 0, w, h, style="F")
    if bg_path:
        try:
            p.image(bg_path, x=0, y=0, w=w, h=h)  # cover (stretched to the frame; staff pick an image of the right ratio)
            with p.local_context(fill_opacity=0.58):
                p.set_fill_color(*dark)
                p.rect(0, 0, w, h, style="F")
        except Exception:  # noqa: BLE001
            pass
    # accent bands
    p.set_fill_color(*accent)
    p.rect(0, 0, w, 10, style="F")
    p.rect(w - 14, 0, 14, h, style="F")
    pad = int(w * 0.07)
    # logo + developer name (top right)
    y = pad
    if brand.get("logo_path"):
        try:
            p.image(brand["logo_path"], x=w - pad - 90, y=y, h=90)
            y += 100
        except Exception:  # noqa: BLE001
            pass
    p.set_text_color(*ink)
    p.set_font("Tajawal", "B", int(w * 0.03))
    p.set_xy(pad, y)
    p.cell(w - 2 * pad, int(w * 0.04), brand.get("name") or "", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    # badge
    bw, bh = int(w * 0.34), int(w * 0.06)
    p.set_fill_color(*accent)
    p.rect(w - pad - bw, h * 0.30 - bh, bw, bh, style="F", round_corners=True, corner_radius=bh / 2)
    p.set_text_color(*(dark if not light_bg else (255, 255, 255)))
    p.set_font("Tajawal", "B", int(bh * 0.5))
    p.set_xy(w - pad - bw, h * 0.30 - bh)
    p.cell(bw, bh, badge, align="C")
    # headline
    p.set_text_color(*ink)
    p.set_font("Tajawal", "B", int(w * 0.085))
    p.set_xy(pad, h * 0.30 + int(w * 0.02))
    p.multi_cell(w - 2 * pad, int(w * 0.10), head, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    # subline
    p.set_font("Tajawal", "", int(w * 0.04))
    p.set_text_color(*accent) if not light_bg else p.set_text_color(*accent)
    p.set_x(pad)
    p.multi_cell(w - 2 * pad, int(w * 0.055), sub, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    # facts row
    facts = []
    if project.get("types"):
        facts.append(project["types"])
    if project.get("price_from"):
        facts.append("تبدأ من " + money(project["price_from"], 0))
    if project.get("plan_label"):
        facts.append(project["plan_label"] + " · بلا فوائد")
    if facts and template in ("offer", "last_units", "progress", "ready"):  # launch already states types and price in its subline
        p.set_font("Tajawal", "", int(w * 0.03))
        p.set_text_color(*ink)
        p.set_x(pad)
        p.multi_cell(w - 2 * pad, int(w * 0.045), " · ".join(facts), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    # CTA pill bottom
    cw, ch = int(w * 0.6), int(w * 0.075)
    cy = h - pad - ch - int(w * 0.06)
    p.set_fill_color(*ink) if not light_bg else p.set_fill_color(*dark)
    p.rect(w - pad - cw, cy, cw, ch, style="F", round_corners=True, corner_radius=ch / 2)
    p.set_text_color(*dark) if not light_bg else p.set_text_color(*ink)
    p.set_font("Tajawal", "B", int(ch * 0.42))
    p.set_xy(w - pad - cw, cy)
    p.cell(cw, ch, call, align="C")
    # footer line
    p.set_font("Tajawal", "", int(w * 0.022))
    p.set_text_color(*accent)
    p.set_xy(pad, h - pad - int(w * 0.03))
    foot = " · ".join(x for x in (brand.get("phone"), brand.get("email"), "عبر منصة مبانيك") if x)
    p.cell(w - 2 * pad, int(w * 0.03), foot, align="R")
    pdf = bytes(p.output())
    try:
        import pymupdf
        d = pymupdf.open(stream=io.BytesIO(pdf), filetype="pdf")
        png = d[0].get_pixmap(dpi=72, alpha=False).tobytes("png")
    except Exception:  # noqa: BLE001
        png = None
    return pdf, png


def preview_png(pdf: bytes, dpi: int = 36) -> bytes | None:
    try:
        import pymupdf
        return pymupdf.open(stream=io.BytesIO(pdf), filetype="pdf")[0].get_pixmap(dpi=dpi, alpha=False).tobytes("png")
    except Exception:  # noqa: BLE001
        return None


__all__ = ["compose", "SIZES", "TEMPLATES", "PALETTES", "Path"]
