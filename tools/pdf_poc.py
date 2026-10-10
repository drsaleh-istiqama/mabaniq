"""Proof of concept: Arabic RTL PDF with fpdf2 + uharfbuzz shaping, Tajawal, Hijri date, QR matrix."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fpdf import FPDF  # noqa: E402
import qrcode  # noqa: E402
from hijridate import Gregorian  # noqa: E402

FONTS = os.path.join(os.path.dirname(__file__), "..", "backend", "assets", "fonts")
pdf = FPDF(unit="mm", format="A4")
pdf.add_font("Tajawal", "", os.path.join(FONTS, "Tajawal-Regular.ttf"))
pdf.add_font("Tajawal", "B", os.path.join(FONTS, "Tajawal-Bold.ttf"))
pdf.set_text_shaping(use_shaping_engine=True, direction="rtl", script="arab", language="ar")
pdf.add_page()
pdf.set_font("Tajawal", "B", 20)
pdf.cell(0, 12, "عرض سعر رقم QT-2026-0001", align="R", new_x="LMARGIN", new_y="NEXT")
h = Gregorian(2026, 10, 10).to_hijri()
pdf.set_font("Tajawal", "", 12)
pdf.cell(0, 8, f"التاريخ: {h.day} {h.month_name('ar')} {h.year}هـ الموافق 2026-10-10م", align="R", new_x="LMARGIN", new_y="NEXT")
pdf.multi_cell(0, 7, "هذا عرض سعر لوحدة سكنية (شقة 3 غرف وصالة) في مشروع أبراج الريحان بالمعبيلة، بسعر 85,000 ر.ع، صالح حتى 2026-10-17. السداد وفق خطة 60/40 بلا أي فائدة أو زيادة لقاء الأجل.", align="R")
with pdf.table(text_align=("RIGHT", "RIGHT", "RIGHT"), col_widths=(3, 2, 2)) as t:
    for row in (("القسط", "تاريخ الاستحقاق", "المبلغ (ر.ع)"), ("عربون الحجز", "2026-10-10", "8,500"), ("دفعة أثناء البناء 1", "2027-01-10", "8,500")):
        r = t.row()
        for c in row:
            r.cell(c)
qr = qrcode.QRCode(box_size=1, border=1)
qr.add_data("https://mabaniq.example/verify/ABCD1234")
qr.make()
m = qr.get_matrix()
x0, y0, s = 20, pdf.get_y() + 8, 0.9
pdf.set_fill_color(0, 0, 0)
for yy, row in enumerate(m):
    for xx, v in enumerate(row):
        if v:
            pdf.rect(x0 + xx * s, y0 + yy * s, s, s, style="F")
out = os.path.join(os.path.dirname(__file__), "..", ".local", "poc.pdf")
os.makedirs(os.path.dirname(out), exist_ok=True)
pdf.output(out)
print("ok", os.path.getsize(out), out)
