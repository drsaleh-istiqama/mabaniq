# -*- coding: utf-8 -*-
"""يقصّ لقطات ثابتة 16:9 (1920×1080) من تصورات رؤية المنشورة (نوافذ فوق مستوى الشارع، بلا أشخاص) لمشهد الافتتاح."""
from pathlib import Path
from PIL import Image
GAL = Path("C:/Users/Istiqama/AppData/Local/Temp/claude/C--DrSaleh/c58711b2-5a3d-466a-853d-68234e9172e5/scratchpad/view-video/gal")
OUT = Path(__file__).resolve().parent / "stills"
OUT.mkdir(exist_ok=True)
SHOTS = {"s1a": ("heights/01.jpeg", 1.0, 0.62), "s1b": ("kayan/14.jpg", 1.0, 0.40), "s1c": ("gardens/06.jpg", 1.0, 0.42)}
for name, (rel, fw, cy) in SHOTS.items():
    p = next((GAL / Path(rel).parent).glob(Path(rel).stem + ".*"))
    im = Image.open(p).convert("RGB")
    iw, ih = im.size
    ww = fw * iw
    hh = ww * 9 / 16
    x0 = (iw - ww) / 2
    y0 = min(max(cy * ih - hh / 2, 0), ih - hh)
    im.resize((1920, 1080), Image.LANCZOS, box=(x0, y0, x0 + ww, y0 + hh)).save(OUT / f"{name}.jpg", quality=92)
    print(name, p.name)
