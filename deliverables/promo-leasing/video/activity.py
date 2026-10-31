"""يستخرج من كل تسجيل منصة (out/r*.mp4) المقاطع النشطة: يحذف الجمود الطويل ويُبقي أول KEEP ثانية من كل جمود ليقرأه المشاهد.
   يكتب activity.json: {"r2": [[من، إلى], ...], ...}  (ثوانٍ في ملف المصدر)."""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEEP = 1.3
MIN_FREEZE = 1.8
out = {}
for f in sorted((HERE / "out").glob("r*.mp4")):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout)
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(f), "-vf", f"freezedetect=n=-55dB:d={MIN_FREEZE}", "-an", "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    starts = [float(x) for x in re.findall(r"freeze_start: ([0-9.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([0-9.]+)", err)]
    if len(starts) > len(ends): ends.append(dur)
    freezes = list(zip(starts, ends))
    keep = []; cur = 0.0
    for s, e in freezes:
        if s > cur: keep.append([cur, s])
        keep.append([s, min(s + KEEP, e)])   # أول لحظات الجمود تبقى للقراءة
        cur = e
    if cur < dur: keep.append([cur, dur])
    merged = []
    for a, b in keep:
        if b - a < 0.05: continue
        if merged and a - merged[-1][1] < 0.05: merged[-1][1] = b
        else: merged.append([round(a, 3), round(b, 3)])
    out[f.stem] = merged
    print(f.stem, f"{dur:.1f}s ←", f"{sum(b - a for a, b in merged):.1f}s نشطة", merged)
(HERE / "activity.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
