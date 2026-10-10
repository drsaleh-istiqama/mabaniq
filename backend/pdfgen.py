"""Mabaniq — PDF documents (Unit 6): quotation, sale contract, invoice, receipt.

Rendered server-side with fpdf2 + HarfBuzz shaping (Arabic, RTL), self-hosted Tajawal (SIL OFL), Western digits
(owner decision ب), Hijri date first then Gregorian, the developer's letterhead (name, CR, VAT, address) and — when the
administrator uploaded them — logo, stamp and authorised signature images. Every document carries a verification code
and a QR to `/verify/<tenant>/<code>`; the code is registered with a content hash so a printed copy can be checked later.
No network access, no external fonts, no PII beyond what the document itself must show.
"""
from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import qrcode
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from hijridate import Gregorian

FONTS = Path(__file__).resolve().parent / "assets" / "fonts"
GOLD = (212, 166, 74)
INK = (23, 32, 48)
MUTED = (110, 120, 135)
LINE = (210, 214, 222)

KIND_TITLES = {"quote": "عرض سعر", "contract": "عقد بيع وحدة عقارية", "invoice": "فاتورة", "tax_invoice": "فاتورة ضريبية", "receipt": "إيصال استلام"}


def hijri(d: dt.date | str | None) -> str:
    """'29 ربيع الثاني 1448هـ الموافق 2026-10-10م' — Hijri first (owner rule), Western digits."""
    if not d:
        return "—"
    if isinstance(d, str):
        d = dt.date.fromisoformat(d[:10])
    h = Gregorian(d.year, d.month, d.day).to_hijri()
    return f"{h.day} {h.month_name('ar')} {h.year}هـ الموافق {d.isoformat()}م"


def money(v: float | None, dec: int = 3) -> str:
    return f"{(v or 0):,.{dec}f} ر.ع"


class Doc(FPDF):
    def __init__(self, brand: dict, kind: str, number: str, verify_url: str, verify_code: str):
        super().__init__(unit="mm", format="A4")
        self.brand, self.kind, self.number, self.verify_url, self.verify_code = brand, kind, number, verify_url, verify_code
        self.add_font("Tajawal", "", str(FONTS / "Tajawal-Regular.ttf"))
        self.add_font("Tajawal", "B", str(FONTS / "Tajawal-Bold.ttf"))
        self.set_text_shaping(use_shaping_engine=True, direction="rtl", script="arab", language="ar")
        self.set_auto_page_break(auto=True, margin=28)
        self.set_margins(16, 16, 16)
        self.alias_nb_pages()

    # ---- letterhead / footer
    def header(self):
        b = self.brand
        y0 = self.get_y()
        if b.get("logo_path"):
            try:
                self.image(b["logo_path"], x=self.w - 16 - 22, y=y0, h=16)
            except Exception:  # noqa: BLE001 — a broken image never blocks a document
                pass
            self.set_x(16)
        self.set_font("Tajawal", "B", 15)
        self.set_text_color(*INK)
        self.cell(self.w - 32 - 26, 8, b.get("name") or "المطوّر", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Tajawal", "", 8.5)
        self.set_text_color(*MUTED)
        line = " · ".join(x for x in (b.get("address"), f"س.ت {b['cr']}" if b.get("cr") else "", f"الرقم الضريبي {b['vat']}" if b.get("vat") else "",
                                      b.get("phone"), b.get("email")) if x)
        self.cell(self.w - 32 - 26, 5, line, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*GOLD)
        self.set_line_width(0.6)
        self.line(16, self.get_y() + 2, self.w - 16, self.get_y() + 2)
        self.ln(6)

    def footer(self):
        self.set_y(-22)
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.line(16, self.get_y(), self.w - 16, self.get_y())
        self.set_font("Tajawal", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"{KIND_TITLES.get(self.kind, '')} {self.number} · صدر إلكترونيًا من منصة مبانيك · رمز التحقق {self.verify_code} · صفحة {self.page_no()} من {{nb}}",
                  align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.cell(0, 4, self.verify_url, align="L")

    # ---- building blocks
    def heading(self, text: str, sub: str = ""):
        self.set_font("Tajawal", "B", 20)
        self.set_text_color(*INK)
        self.cell(0, 11, text, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if sub:
            self.set_font("Tajawal", "", 10)
            self.set_text_color(*MUTED)
            self.cell(0, 6, sub, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def kv(self, pairs: list[tuple[str, str]], cols: int = 2):
        """Label/value grid, right to left."""
        self.set_text_color(*INK)
        w = (self.w - 32) / cols
        rows = [pairs[i:i + cols] for i in range(0, len(pairs), cols)]
        for row in rows:
            y = self.get_y()
            x_right = self.w - 16
            for k, v in row:
                x = x_right - w
                if not k:
                    x_right -= w
                    continue
                self.set_xy(x, y)
                self.set_font("Tajawal", "", 8.5)
                self.set_text_color(*MUTED)
                self.cell(w - 3, 4.5, k, align="R", new_x=XPos.LEFT, new_y=YPos.NEXT)
                self.set_x(x)
                self.set_font("Tajawal", "B", 10.5)
                self.set_text_color(*INK)
                self.cell(w - 3, 6, str(v if v not in (None, "") else "—"), align="R")
                x_right -= w
            self.set_y(y + 12)
        self.ln(2)

    def grid(self, heads: list[str], rows: list[list[str]], widths: tuple | None = None, bold_last: bool = False):
        self.set_font("Tajawal", "", 9.5)
        self.set_text_color(*INK)
        self.set_draw_color(*LINE)
        from fpdf.fonts import FontFace
        with super().table(text_align="RIGHT", col_widths=widths, borders_layout="HORIZONTAL_LINES", line_height=7,
                           headings_style=FontFace(emphasis="BOLD", fill_color=(240, 242, 245), color=INK), first_row_as_headings=True, padding=1.5) as t:
            hr = t.row()
            for h in heads:
                hr.cell(h)
            for i, r in enumerate(rows):
                row = t.row()
                last = bold_last and i == len(rows) - 1
                for c in r:
                    row.cell(str(c), style=FontFace(emphasis="BOLD") if last else None)
        self.ln(3)

    def para(self, text: str, size: float = 9.5, muted: bool = False, bold: bool = False):
        self.set_font("Tajawal", "B" if bold else "", size)
        self.set_text_color(*(MUTED if muted else INK))
        self.multi_cell(0, 5.2, text, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def numbered(self, items: list[str]):
        for i, it in enumerate(items, 1):
            self.set_font("Tajawal", "", 9.3)
            self.set_text_color(*INK)
            self.multi_cell(0, 5.2, f"{i}. {it}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def signatures(self, left: tuple[str, str], right: tuple[str, str], evidence: str = ""):
        """Stamp + signature block. Right box: the developer (stamp/signature images when uploaded). Left box: the other party."""
        if self.get_y() > self.h - 80:
            self.add_page()
        y = self.get_y() + 4
        w = (self.w - 32 - 8) / 2
        xr, xl = self.w - 16 - w, 16
        self.set_draw_color(*LINE)
        self.set_line_width(0.3)
        for x, (who, name) in ((xr, right), (xl, left)):
            self.rect(x, y, w, 40, style="D")
            self.set_xy(x, y + 2)
            self.set_font("Tajawal", "B", 9.5)
            self.set_text_color(*INK)
            self.cell(w - 4, 5, who, align="R", new_x=XPos.LEFT, new_y=YPos.NEXT)
            self.set_x(x)
            self.set_font("Tajawal", "", 8.5)
            self.set_text_color(*MUTED)
            self.cell(w - 4, 5, name, align="R")
        b = self.brand
        if b.get("stamp_path"):
            try:
                self.image(b["stamp_path"], x=xr + 4, y=y + 10, h=28)
            except Exception:  # noqa: BLE001
                pass
        if b.get("sign_path"):
            try:
                self.image(b["sign_path"], x=xr + w - 40, y=y + 14, h=20)
            except Exception:  # noqa: BLE001
                pass
        if not b.get("stamp_path") and not b.get("sign_path"):
            self.set_xy(xr + 2, y + 24)
            self.set_font("Tajawal", "", 7.5)
            self.set_text_color(*MUTED)
            self.cell(w - 4, 4, "موضع الختم والتوقيع المعتمد", align="C")
        self.set_y(y + 42)
        if evidence:
            self.para(evidence, 8, muted=True)

    def verification(self):
        """QR + code box at the end."""
        if self.get_y() > self.h - 60:
            self.add_page()
        y = self.get_y() + 2
        qr = qrcode.QRCode(box_size=1, border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(self.verify_url)
        qr.make()
        m = qr.get_matrix()
        s = 24 / len(m)
        x0 = 16
        self.set_fill_color(0, 0, 0)
        for yy, row in enumerate(m):
            for xx, v in enumerate(row):
                if v:
                    self.rect(x0 + xx * s, y + yy * s, s, s, style="F")
        self.set_xy(16 + 28, y)
        self.set_font("Tajawal", "B", 9.5)
        self.set_text_color(*INK)
        self.cell(self.w - 32 - 28, 6, "التحقق من صحة المستند", align="R", new_x=XPos.LEFT, new_y=YPos.NEXT)
        self.set_x(16 + 28)
        self.set_font("Tajawal", "", 8.5)
        self.set_text_color(*MUTED)
        self.multi_cell(self.w - 32 - 28, 4.6, f"امسح الرمز أو افتح الرابط وأدخل رمز التحقق {self.verify_code}. يُظهر النظام نوع المستند ورقمه وتاريخ إصداره ومطابقة محتواه لما صدر فعلًا.",
                        align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_y(max(self.get_y(), y + 26))


# ---------------------------------------------------------------- renderers
def _common_end(p: Doc, left: tuple[str, str], right_name: str, evidence: str = ""):
    p.signatures(left, ("المطوّر", right_name), evidence)
    p.verification()


def render_quote(brand: dict, q: dict, verify_url: str) -> bytes:
    p = Doc(brand, "quote", q["number"], verify_url, q["verify_code"])
    p.add_page()
    p.heading(f"عرض سعر {q['number']}", f"تاريخ الإصدار: {hijri(q['created'])} · صالح حتى {hijri(q['valid_until'])}")
    p.kv([("العميل", q["customer_name"]), ("الهاتف", q.get("phone") or "—"), ("البريد", q.get("email") or "—"), ("أعدّه", q.get("created_by") or "—")])
    p.kv([("المشروع", q["project"]), ("الوحدة", q["code"]), ("النوع", q["type"]), ("المساحة", f"{q['area']:,.0f} م²"),
          ("المبنى / الطابق", f"{q.get('building') or '—'} / {q.get('floor') if q.get('floor') is not None else '—'}"), ("الموقع / الإطلالة", f"{q['location']} · {q['view']}"),
          ("خطة السداد", q["plan_label"]), ("", "")], cols=4)
    p.kv([("التسليم المتوقع", hijri(q["handover"]))], cols=1)
    rows = [["سعر القائمة", money(q["list_price"], 0)]]
    if q.get("discount_pct"):
        rows.append([f"خصم {q['discount_pct'] * 100:g}٪", "− " + money(q["list_price"] - q["price"], 0)])
    rows.append(["السعر المعروض", money(q["price"], 0)])
    p.grid(["البند", "القيمة"], rows, widths=(3, 2))
    p.para("جدول الدفعات المقترح (لا تتضمن أي فائدة أو زيادة لقاء الأجل؛ الثمن ثابت):", bold=True)
    p.grid(["#", "الدفعة", "تاريخ الاستحقاق", "المبلغ"], [[str(i), s["label"], hijri(s["due"]), money(s["amount"], 0)] for i, s in enumerate(q["schedule"], 1)], widths=(1, 4, 5, 3))
    p.para("الشروط:", bold=True)
    p.numbered([
        f"هذا العرض صالح حتى {q['valid_until']} ويخضع لتوافر الوحدة؛ لا يُعدّ حجزًا ولا يُرتّب حقًا في الوحدة قبل سداد عربون الحجز.",
        "الحجز مشروط باستكمال التحقق من هوية المشتري وفق متطلبات مكافحة غسل الأموال، وتوقيع عقد البيع.",
        "المبالغ تُسدَّد إلى حساب الضمان الخاص بالمشروع، ولا تُحتسب أي فائدة على الدفعات المؤجلة؛ وفي حال التأخر يُطبَّق شرط التبرع المبيّن في العقد.",
        "المساحات والمخططات إرشادية وتخضع للمساحة النهائية في سند الملكية بنسبة سماح لا تتجاوز ما يحدده العقد.",
        (q.get("notes") or "").strip() or "تُطبَّق أحكام عقد البيع النموذجي للمطوّر.",
    ])
    _common_end(p, ("العميل", q["customer_name"]), brand.get("name") or "المطوّر")
    return bytes(p.output())


def render_contract(brand: dict, k: dict, verify_url: str) -> bytes:
    p = Doc(brand, "contract", k["number"], verify_url, k["verify_code"])
    p.add_page()
    status = "موقَّع من العميل" if k.get("customer_signed_at") else "بانتظار توقيع العميل"
    p.heading(f"عقد بيع وحدة عقارية {k['number']}", f"تاريخ الإصدار: {hijri(k['created'])} · الحالة: {status}")
    p.kv([("المشتري", k["customer"]), ("الوحدة", k["code"]), ("المشروع", k["project"]), ("بصمة النص (SHA-256)", k["sha256"][:16] + "…")])
    for block in (k["body"] or "").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        head = block.splitlines()[0]
        if head.startswith("البند") or head.startswith("المادة"):
            p.set_font("Tajawal", "B", 10.5)
            p.set_text_color(*INK)
            p.multi_cell(0, 6, head, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            rest = "\n".join(block.splitlines()[1:]).strip()
            if rest:
                p.para(rest)
        else:
            p.para(block)
    ev = ""
    if k.get("customer_signed_at"):
        ev = f"توقيع إلكتروني: وقّع العميل في {k['customer_signed_at']} بطريقة «{k.get('customer_sig') or '—'}»؛ النص المطابق لبصمة SHA-256 {k['sha256']} هو النسخة المعتمدة، وأي نسخة تختلف عنها لا يُعتد بها."
    _common_end(p, ("المشتري", k["customer"]), brand.get("name") or "المطوّر", ev)
    return bytes(p.output())


def render_invoice(brand: dict, inv: dict, verify_url: str) -> bytes:
    kind = "tax_invoice" if (inv.get("vat") or 0) > 0 else "invoice"
    p = Doc(brand, kind, inv["number"], verify_url, inv["verify_code"])
    p.add_page()
    p.heading(f"{KIND_TITLES[kind]} {inv['number']}", f"تاريخ الإصدار: {hijri(inv['issued'])}")
    p.kv([("العميل", inv["customer"]), ("الوحدة / المرجع", inv.get("unit") or f"{inv['ref_type']} {inv['ref_id']}"), ("المشروع", inv.get("project") or "—"), ("نوع الفاتورة", inv.get("kind_label") or inv["kind"])])
    rows = [[inv.get("note") or inv.get("kind_label") or inv["kind"], money(inv["net"])],
            [f"ضريبة القيمة المضافة {inv['vat_rate'] * 100:g}٪" if inv.get("vat_rate") else "ضريبة القيمة المضافة (معفاة/صفرية)", money(inv.get("vat"))],
            ["الإجمالي المستحق", money(inv["total"])]]
    p.grid(["البيان", "المبلغ"], rows, widths=(4, 2))
    if inv.get("paid_note"):
        p.para(inv["paid_note"], muted=True)
    p.para("تُسدَّد المبالغ إلى حساب الضمان الخاص بالمشروع. هذه الفاتورة صادرة إلكترونيًا ولا تحتاج توقيعًا يدويًا؛ يُعتد بالنسخة التي يطابق محتواها رمز التحقق.", 8.5, muted=True)
    _common_end(p, ("العميل", inv["customer"]), brand.get("name") or "المطوّر")
    return bytes(p.output())


def render_receipt(brand: dict, r: dict, verify_url: str) -> bytes:
    p = Doc(brand, "receipt", r["receipt"], verify_url, r["verify_code"])
    p.add_page()
    p.heading(f"إيصال استلام {r['receipt']}", f"تاريخ الاستلام: {hijri(r['at'])}")
    p.kv([("استلمنا من", r["customer"]), ("مبلغًا وقدره", money(r["amount"])), ("طريقة السداد", r.get("method_label") or r.get("method") or "—"), ("مرجع البوابة", r.get("gateway_ref") or "—")])
    p.kv([("وذلك عن", r["label"]), ("الوحدة", r["code"]), ("المشروع", r["project"]), ("المتبقي على الوحدة بعد هذه الدفعة", money(r["remaining"]))])
    if r.get("invoice_number"):
        p.para(f"الفاتورة المرتبطة: {r['invoice_number']}", muted=True)
    p.para("أودع المبلغ في حساب الضمان الخاص بالمشروع. يصدر هذا الإيصال إلكترونيًا ويُعتد به مع رمز التحقق أدناه.", 8.5, muted=True)
    _common_end(p, ("المستلم", r.get("issued_by") or "المحاسب"), brand.get("name") or "المطوّر")
    return bytes(p.output())


def png_preview(pdf_bytes: bytes, dpi: int = 60) -> bytes | None:
    """Optional first-page thumbnail (PyMuPDF when installed — dev only)."""
    try:
        import pymupdf  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    d = pymupdf.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
    return d[0].get_pixmap(dpi=dpi).tobytes("png")
