"""Mabaniq — report PDF (Unit 7): KPI tiles, native charts (bar, stacked, line, pie) and tables drawn with fpdf2 primitives.
Scales are computed from the data (no fake axes), labels use Western digits, every chart fits the page width, and long tables
continue over pages. Used by `reports.export` and the scheduled e-mail job."""
from __future__ import annotations

import math

from fpdf.enums import XPos, YPos

from .pdfgen import GOLD, INK, LINE, MUTED, Doc, hijri, money

PALETTE = [(212, 166, 74), (106, 166, 245), (76, 195, 138), (242, 122, 115), (46, 84, 135), (160, 120, 200), (120, 120, 120)]


def fmt(v, kind: str = "num") -> str:
    if v is None or v == "":
        return "—"
    if kind == "money":
        return money(float(v), 0)
    if kind == "pct":
        return f"{float(v):g}٪"
    if kind == "date":
        return str(v)[:10]
    if kind == "bool":
        return "نعم" if v else "لا"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


def _axis_label(v: float, kind: str) -> str:
    if kind == "money":
        return f"{v / 1e6:g} م" if v >= 1e6 else f"{v / 1e3:g} ألف" if v >= 1e3 else f"{v:g}"
    if kind == "pct":
        return f"{v:g}٪"
    return f"{v:g}"


def kpis(p: Doc, items: list[dict]):
    if not items:
        return
    n = min(len(items), 4)
    w = (p.w - 32) / n
    y = p.get_y()
    for i, it in enumerate(items[:n]):
        x = p.w - 16 - (i + 1) * w
        p.set_draw_color(*LINE)
        p.rect(x + 1, y, w - 2, 18, style="D")
        p.set_xy(x + 3, y + 1.5)
        p.set_font("Tajawal", "", 8)
        p.set_text_color(*MUTED)
        p.cell(w - 6, 4.5, str(it.get("label", "")), align="R", new_x=XPos.LEFT, new_y=YPos.NEXT)
        p.set_x(x + 3)
        p.set_font("Tajawal", "B", 12)
        p.set_text_color(*INK)
        p.cell(w - 6, 8, fmt(it.get("value"), it.get("format", "num")), align="R")
    p.set_y(y + 22)


def _chart_frame(p: Doc, title: str, h: float) -> tuple[float, float, float, float]:
    if p.get_y() + h + 14 > p.h - 30:
        p.add_page()
    p.set_font("Tajawal", "B", 10)
    p.set_text_color(*INK)
    p.cell(0, 7, title, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    x0, y0, w = 16, p.get_y() + 1, p.w - 32
    return x0, y0, w, h


def _legend(p: Doc, series: list[dict], y: float):
    x = p.w - 16
    p.set_font("Tajawal", "", 7.5)
    for i, s in enumerate(series):
        col = PALETTE[i % len(PALETTE)]
        lab = str(s.get("name", ""))
        tw = p.get_string_width(lab) + 8
        x -= tw
        p.set_fill_color(*col)
        p.rect(x + tw - 4, y + 1, 3, 3, style="F")
        p.set_xy(x, y - 0.5)
        p.set_text_color(*MUTED)
        p.cell(tw - 5, 5, lab, align="R")
        x -= 4
    p.set_y(y + 6)


def bars(p: Doc, ch: dict, stacked: bool = False, h: float = 58):
    labels, series = ch.get("labels") or [], ch.get("series") or []
    if not labels or not series:
        return
    x0, y0, w, h = _chart_frame(p, ch.get("title", ""), h)
    kind = ch.get("format", "num")
    plot_x, plot_w, plot_y, plot_h = x0 + 14, w - 16, y0 + 2, h - 14
    if stacked:
        vmax = max(sum(float(s["data"][i] or 0) for s in series) for i in range(len(labels)))
    else:
        vmax = max(float(v or 0) for s in series for v in s["data"]) if series else 1
    vmax = _nice_max(vmax)
    # grid + axis
    p.set_draw_color(*LINE)
    p.set_line_width(0.2)
    p.set_font("Tajawal", "", 6.5)
    p.set_text_color(*MUTED)
    for g in range(5):
        yy = plot_y + plot_h - plot_h * g / 4
        p.line(plot_x, yy, plot_x + plot_w, yy)
        p.set_xy(x0 - 2, yy - 2)
        p.cell(14, 4, _axis_label(vmax * g / 4, kind), align="L")
    n = len(labels)
    gw = plot_w / n
    bw = gw * 0.7 / (1 if stacked else len(series))
    for i, lab in enumerate(labels):
        gx = plot_x + plot_w - (i + 1) * gw  # right-to-left categories
        base = plot_y + plot_h
        for si, s in enumerate(series):
            v = float(s["data"][i] or 0) if i < len(s["data"]) else 0
            bh = plot_h * v / vmax if vmax else 0
            p.set_fill_color(*PALETTE[si % len(PALETTE)])
            if stacked:
                p.rect(gx + gw * 0.15, base - bh, bw, bh, style="F")
                base -= bh
            else:
                p.rect(gx + gw * 0.15 + si * bw, base - bh, bw - 0.6, bh, style="F")
        p.set_xy(gx, plot_y + plot_h + 1)
        p.set_font("Tajawal", "", 6 if n > 8 else 7)
        p.set_text_color(*MUTED)
        p.cell(gw, 4, str(lab)[:14 if n > 8 else 22], align="C")
    _legend(p, series, plot_y + plot_h + 6)
    p.ln(2)


def line(p: Doc, ch: dict, h: float = 58):
    labels, series = ch.get("labels") or [], ch.get("series") or []
    if not labels or not series:
        return
    x0, y0, w, h = _chart_frame(p, ch.get("title", ""), h)
    kind = ch.get("format", "num")
    plot_x, plot_w, plot_y, plot_h = x0 + 14, w - 16, y0 + 2, h - 14
    allv = [float(v or 0) for s in series for v in s["data"]]
    vmax = _nice_max(max(allv) if allv else 1)
    vmin = min(0.0, min(allv) if allv else 0)
    rng = (vmax - vmin) or 1
    p.set_draw_color(*LINE)
    p.set_line_width(0.2)
    p.set_font("Tajawal", "", 6.5)
    p.set_text_color(*MUTED)
    for g in range(5):
        val = vmin + rng * g / 4
        yy = plot_y + plot_h - plot_h * (val - vmin) / rng
        p.line(plot_x, yy, plot_x + plot_w, yy)
        p.set_xy(x0 - 2, yy - 2)
        p.cell(14, 4, _axis_label(val, kind), align="L")
    n = len(labels)
    step = plot_w / max(n - 1, 1)
    for si, s in enumerate(series):
        p.set_draw_color(*PALETTE[si % len(PALETTE)])
        p.set_line_width(0.6)
        pts = []
        for i in range(n):
            v = float(s["data"][i] or 0) if i < len(s["data"]) else 0
            x = plot_x + plot_w - i * step
            y = plot_y + plot_h - plot_h * (v - vmin) / rng
            pts.append((x, y))
        for a, b in zip(pts, pts[1:]):
            p.line(a[0], a[1], b[0], b[1])
        p.set_fill_color(*PALETTE[si % len(PALETTE)])
        for x, y in pts:
            p.ellipse(x - 0.8, y - 0.8, 1.6, 1.6, style="F")
    every = max(1, n // 8)
    for i, lab in enumerate(labels):
        if i % every:
            continue
        x = plot_x + plot_w - i * step
        p.set_xy(x - 10, plot_y + plot_h + 1)
        p.set_font("Tajawal", "", 6.5)
        p.set_text_color(*MUTED)
        p.cell(20, 4, str(lab)[:10], align="C")
    _legend(p, series, plot_y + plot_h + 6)
    p.ln(2)


def pie(p: Doc, ch: dict, h: float = 52):
    labels, series = ch.get("labels") or [], ch.get("series") or []
    if not labels or not series or not series[0].get("data"):
        return
    data = [max(float(v or 0), 0) for v in series[0]["data"]]
    total = sum(data)
    if total <= 0:
        return
    x0, y0, w, h = _chart_frame(p, ch.get("title", ""), h)
    kind = ch.get("format", "num")
    r = (h - 8) / 2
    cx, cy = x0 + w - r - 4, y0 + 2 + r
    start = 90.0
    for i, v in enumerate(data[:8]):
        sweep = 360 * v / total
        p.set_fill_color(*PALETTE[i % len(PALETTE)])
        p.set_draw_color(255, 255, 255)
        p.set_line_width(0.4)
        if sweep >= 359.9:
            p.ellipse(cx - r, cy - r, 2 * r, 2 * r, style="FD")
        elif sweep > 0.2:
            p.solid_arc(cx, cy, r, r, start, start + sweep, style="FD", clockwise=True)
        start += sweep
    # legend table at the left of the pie
    p.set_font("Tajawal", "", 7.5)
    ly = y0 + 2
    for i, (lab, v) in enumerate(zip(labels[:8], data[:8])):
        p.set_fill_color(*PALETTE[i % len(PALETTE)])
        lx = cx - r - 8
        p.rect(lx - 3, ly + 1, 3, 3, style="F")
        p.set_xy(x0, ly - 0.5)
        p.set_text_color(*INK)
        p.cell(lx - 6 - x0, 5, f"{lab}: {fmt(v, kind)} ({100 * v / total:.0f}٪)", align="R")
        ly += 5.5
    p.set_y(max(ly, cy + r) + 3)


def table(p: Doc, t: dict, max_rows: int = 60):
    cols = t.get("columns") or []
    data = (t.get("rows") or [])[:max_rows]
    if not cols:
        return
    if p.get_y() > p.h - 50:
        p.add_page()
    p.set_font("Tajawal", "B", 10)
    p.set_text_color(*INK)
    p.cell(0, 7, t.get("title", ""), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.set_font("Tajawal", "", 7.5)
    p.set_draw_color(*LINE)
    from fpdf.fonts import FontFace
    with p.table(text_align="RIGHT", borders_layout="HORIZONTAL_LINES", line_height=5.5, headings_style=FontFace(emphasis="BOLD", fill_color=(240, 242, 245), color=INK),
                 first_row_as_headings=True, padding=1) as tb:
        hr = tb.row()
        for col in cols:
            hr.cell(str(col["label"]))
        for r in data:
            row = tb.row()
            for col in cols:
                row.cell(fmt(r.get(col["key"]), col.get("type", "text")))
    if len(t.get("rows") or []) > max_rows:
        p.set_font("Tajawal", "", 7.5)
        p.set_text_color(*MUTED)
        p.cell(0, 5, f"… و{len(t['rows']) - max_rows} صفًا آخر في ملف CSV", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.ln(3)


def render_report(brand: dict, doc: dict, by: str = "") -> bytes:
    """A4 portrait: heading, KPI tiles, charts (two per row when small), tables; footer with the generation stamp."""
    p = Doc(brand, "report", doc.get("title", "تقرير"), "", "")
    p.add_page()
    p.heading(doc.get("title", "تقرير"), f"{doc.get('subtitle', '')} · أُنشئ في {hijri(doc.get('generated', '')[:10]) if doc.get('generated') else '—'}{' · ' + by if by else ''}")
    kpis(p, doc.get("kpis") or [])
    for ch in doc.get("charts") or []:
        kind = ch.get("type", "bar")
        if kind in ("bar",):
            bars(p, ch)
        elif kind == "stacked":
            bars(p, ch, stacked=True)
        elif kind == "line":
            line(p, ch)
        elif kind == "pie":
            pie(p, ch)
    for t in doc.get("tables") or []:
        table(p, t)
    notes = [n for n in (doc.get("notes") or []) if n]
    if notes:
        p.set_font("Tajawal", "", 8)
        p.set_text_color(*MUTED)
        for n in notes:
            p.multi_cell(0, 4.6, "• " + str(n), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.set_draw_color(*GOLD)
    return bytes(p.output())
