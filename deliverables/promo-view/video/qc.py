import subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw
names = sys.argv[1:]
H = Path(__file__).resolve().parent
for n in names:
    mp4 = H / "out" / f"{n}.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(H / "rec" / n / "list.ffconcat"),
                    "-vf", "fps=24,scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p", "-c:v", "libx264", "-crf", "17", "-preset", "fast", str(mp4)], check=True)
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)], capture_output=True, text=True).stdout)
    cols, rows, w, h = 3, 2, 640, 360
    sh = Image.new("RGB", (cols * w, rows * (h + 14)), "white"); dr = ImageDraw.Draw(sh)
    for i in range(cols * rows):
        t = d * (i + 0.5) / (cols * rows)
        f = H / "qc" / f"{n}_{i}.jpg"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(mp4), "-frames:v", "1", "-vf", f"scale={w}:{h}", str(f)], check=True)
        x, y = (i % cols) * w, (i // cols) * (h + 14)
        sh.paste(Image.open(f), (x, y + 14)); dr.text((x + 3, y + 1), f"{n} t={t:.1f}s of {d:.1f}", fill="black")
    sh.save(H / "qc" / f"{n}_sheet.jpg", quality=80); print(n, round(d, 1), "s")
