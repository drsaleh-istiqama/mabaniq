"""بورتريهات الشخصيات الأربع (قصّ من لقطات الشخصيات المولَّدة) ⟵ cards/p_*.png دائرية لبطاقات الفيديو."""
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE / "cards"; OUT.mkdir(exist_ok=True)
CROPS = {  # الاسم: (ملف المصدر، مربع القص)
    "owner": ("gen/sheetC.jpg", (260, 30, 660, 430)),
    "manager": ("gen/sheetA.jpg", (260, 40, 660, 440)),
    "tenant": ("gen/sheetB.jpg", (250, 30, 650, 430)),
    "accountant": ("gen/s4.jpg", (1120, 150, 1820, 850)),
}
for k, (src, box) in CROPS.items():
    im = Image.open(HERE / src).convert("RGB").crop(box).resize((420, 420), Image.LANCZOS)
    mask = Image.new("L", (420, 420), 0); ImageDraw.Draw(mask).ellipse((0, 0, 419, 419), fill=255)
    out = Image.new("RGBA", (420, 420), (0, 0, 0, 0)); out.paste(im, (0, 0), mask)
    out.save(OUT / f"p_{k}.png")
    print(k, "ok")
