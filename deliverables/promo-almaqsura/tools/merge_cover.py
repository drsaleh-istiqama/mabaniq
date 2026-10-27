"""يستبدل الصفحة الأولى من الدليل الإنجليزي بنسخة الغلاف بلا تذييل ثم يحذف الملف المؤقت."""
import sys
from pathlib import Path

import pymupdf

pdf = Path(sys.argv[1]); cover = pdf.with_name(pdf.stem + "-cover.pdf")
main, cv = pymupdf.open(str(pdf)), pymupdf.open(str(cover))
main.delete_page(0)
main.insert_pdf(cv, from_page=0, to_page=0, start_at=0)
tmp = pdf.with_name(pdf.stem + "-merged.pdf")
main.save(str(tmp), garbage=3, deflate=True)
main.close(); cv.close()
tmp.replace(pdf); cover.unlink()
print("merged cover; pages:", len(pymupdf.open(str(pdf))))
