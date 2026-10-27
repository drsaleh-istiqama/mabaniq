# -*- coding: utf-8 -*-
"""يستخرج أرقام صفحات الأبواب والمهام من PDF الدليل ليُدرَج في جدول المحتويات (تمريرة ثانية).
    python find_pages.py <pdf> <pages.json>"""
import json
import sys
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ops_content as C  # noqa: E402

pdf, out = sys.argv[1], sys.argv[2]
d = pymupdf.open(pdf)
res = {}
for i, p in enumerate(d):
    txt = p.get_text()
    import re
    for m in re.finditer(r"@@([A-Za-z0-9.]+)@@", txt):
        res.setdefault(m.group(1), i + 1)
Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("pages:", len(res), "من", len(d))
