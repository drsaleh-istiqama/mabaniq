#!/usr/bin/env python
"""تجميع فيديو مبانيك لبيان عمان (3 دقائق) — 24 إطارًا/ث، 1920×1080.
   python assemble.py --plan        يطبع الجدول الزمني فقط (بلا تصيير)
   python assemble.py               تصيير كامل ⟵ out/bayan-promo.mp4 + SRT + timeline.json
   REUSE_SEGS=1                     يعيد استعمال المقاطع المصيَّرة في seg/ إن وُجدت
مدد المشاهد تُشتق من مدد ملفات الراوي (audio/n*.mp3) فتصلح لأي صوت؛ لقطات المنصة الحقيقية تتمدد/تنضغط لتملأ الباقي
(بسرعة بين 0.7 و2.2، ولا ارتداد ولا عكس للمقاطع المولَّدة: تشغيل للأمام فقط).
"""
import json, math, os, subprocess, sys
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
S = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
FPS, XF = S["fps"], S["xfade"]
SUBLANG = os.environ.get("SUBLANG", "ar")  # ar: ترجمة عربية · en: ترجمة إنجليزية أسفل الشاشة
CAPS = S["captions_en"] if SUBLANG == "en" else S["captions"]
SFX = "-en" if SUBLANG == "en" else ""
SEG = HERE / "seg"; OUT = HERE / "out"; OV = HERE / ("ov_en" if SUBLANG == "en" else "ov")
for d in (SEG, OUT, OV): d.mkdir(exist_ok=True)
PLAN = "--plan" in sys.argv
MAX_SPEED = float(os.environ.get("MAX_SPEED", "1.5"))


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print("✗", " ".join(map(str, cmd))[:300]); print(r.stderr[-1500:]); sys.exit(1)
    return r.stdout


def dur(p):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]).strip())


def path(src):
    p = Path(src)
    return p if p.is_absolute() else (ROOT / src if src.startswith("backend") else HERE / src)


# ───────────── الجدول الزمني
ndur = {k: dur(HERE / "audio" / f"{k}.mp3") for k in S["captions"]}
t = 0.0; plan = []
for sc in S["scenes"]:
    segs = [dict(x) for x in sc["segs"]]
    fill = next((i for i, x in enumerate(segs) if x["t"] == "real"), len(segs) - 1)
    for i, sg in enumerate(segs):
        if i == fill: continue
        if sg["t"] == "clip": sg["d"] = round(sg["d"] if sg.get("d") else dur(HERE / sg["src"]) / sg.get("speed", 0.8), 3)
        else: sg["d"] = sg["dur"]
    fixed = sum(x["d"] for i, x in enumerate(segs) if i != fill)
    before = sum(x["d"] for x in segs[:fill])
    a_end = sc["offset"] + ndur[sc["narr"]]
    says = [(sc["narr"], sc["offset"])]
    if sc.get("narr2"):
        # السطر الثاني يبدأ عند لقطة المنصة التي يصفها (beat بثواني المصدر) بحدّ أقصى 2.5 ث صمتًا بعد الأول
        rng = segs[fill].get("ranges") or [[0, 1e9]]
        trimmed_before = sum(max(0, min(sc["beat"], hi) - lo) for lo, hi in rng)
        beat_est = before + trimmed_before / 1.0
        b0 = max(a_end + 0.5, min(beat_est - 1.0, a_end + 2.5))
        says.append((sc["narr2"], round(b0, 3)))
        a_end = b0 + ndur[sc["narr2"]]
    target = a_end + sc["tail"]
    floor = segs[fill].get("min", 3.0)
    segs[fill]["d"] = round(max(target - fixed, floor), 3)
    total = sum(x["d"] for x in segs)
    plan.append({"id": sc["id"], "start": round(t, 3), "dur": round(total, 3),
                 "says": [{"n": n, "at": round(t + at, 3), "dur": round(ndur[n], 3)} for n, at in says], "segs": segs})
    t += total
TOTAL = round(t, 3)
for p in plan:
    print(f"S{p['id']:>2} @{p['start']:7.2f}  dur {p['dur']:5.1f}  say " + " | ".join(f"{x['n']} {x['at']:.1f}→{x['at'] + x['dur']:.1f}" for x in p["says"]) + "  " + " + ".join(f"{x['t']}:{x['d']:.1f}" for x in p["segs"]))
print(f"المجموع {TOTAL:.1f} ث")
(HERE / "timeline.json").write_text(json.dumps({"total": TOTAL, "scenes": plan}, ensure_ascii=False, indent=1), encoding="utf-8")
if PLAN: sys.exit(0)

# ───────────── تصيير المقاطع
flat = [(p["id"], sg) for p in plan for sg in p["segs"]]
segfiles = []
VF_NORM = f"scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x124E42,fps={FPS},format=yuv420p,setsar=1"
ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]
used = {}
for k, (sid, sg) in enumerate(flat):
    f = SEG / f"seg_{k:02d}_s{sid}_{sg['t']}.mp4"; segfiles.append(f)
    last = k == len(flat) - 1
    d = sg["d"] + (0 if last else XF); n = math.ceil(d * FPS)
    key = sg["src"]
    if sg["t"] in ("clip", "real") or sg["t"] == "still":
        used[key] = used.get(key, 0) + 1
        assert used[key] == 1, f"تكرار لقطة: {key}"  # منع تكرار أي لقطة
    if f.exists() and os.environ.get("REUSE_SEGS"): continue
    src = path(sg["src"])
    if sg["t"] == "still":
        vf = (f"scale=3840:2160:force_original_aspect_ratio=increase:flags=lanczos,crop=3840:2160,"
              f"zoompan=z='1+0.07*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s=1920x1080:fps={FPS},format=yuv420p")
        run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-i", str(src), "-vf", vf, "-frames:v", str(n), *ENC, str(f)])
    elif sg["t"] == "card":
        run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-i", str(src), "-vf", VF_NORM, "-t", f"{d:.3f}", *ENC, str(f)])
    elif sg["t"] == "clip":
        sp = sg.get("speed", 0.8)
        vf = f"setpts=PTS/{sp},{VF_NORM},tpad=stop_mode=clone:stop_duration=3"
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-vf", vf, "-t", f"{d:.3f}", *ENC, str(f)])
    elif sg["t"] == "real":
        sd = dur(src)
        rng = sg.get("ranges") or [[0, sd]]
        trimmed = sum(b - a for a, b in rng)
        sp = min(2.0, max(0.75, trimmed / sg["d"]))
        sg["speed"] = round(sp, 3)
        sel = "+".join(f"between(t,{a},{b})" for a, b in rng)
        zoom = (",zoompan=z='1+0.00045*on':x='(iw-iw/zoom)*0.5':y='(ih-ih/zoom)*0.30':d=1:s=1920x1080:fps=" + str(FPS)) if sg.get("kb") else ""
        vf = f"select='{sel}',setpts=N/(24*TB),setpts=PTS/{sp:.4f},{VF_NORM},tpad=stop_mode=clone:stop_duration=8{zoom},format=yuv420p"
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-vf", vf, "-t", f"{d:.3f}", *ENC, str(f)])
    elif sg["t"] == "phone":
        rec = HERE / "rec" / sg["src"] / "list.ffconcat"
        vf = (f"fps={FPS},scale=-2:960:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x124E42,format=yuv420p,tpad=stop_mode=clone:stop_duration=6")
        run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(rec), "-vf", vf, "-t", f"{d:.3f}", *ENC, str(f)])
    print("▶", f.name, f"{d:.1f}s", flush=True)

# ───────────── xfade
inputs = []
for f in segfiles: inputs += ["-i", str(f)]
fc = []; cur = "[0:v]"; start = 0.0
for k in range(1, len(segfiles)):
    start += flat[k - 1][1]["d"]
    fc.append(f"{cur}[{k}:v]xfade=transition=fade:duration={XF}:offset={start:.3f}[x{k}]"); cur = f"[x{k}]"
base = HERE / "base.mp4"
if not (base.exists() and os.environ.get("REUSE_SEGS")):
    run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", cur, *ENC, str(base)])
print("▶ base", dur(base))

# ───────────── طبقة الترجمة والشارات (فيديو RGBA واحد من PNG بمدد)
def card(n): return Image.open(HERE / "cards" / ("en" if SUBLANG == "en" and n.startswith("sub_") else "") / f"{n}.png").convert("RGBA")
badge_demo, badge_gen = card("badge-demo"), card("badge-gen")
events = []  # (start, end, [pngs])
cap_iv = []
for p in plan:
    for sy in p["says"]:
        lines = CAPS[sy["n"]]; w = [len(x) for x in lines]; tot = sum(w); a = sy["at"]
        for i, ln in enumerate(lines):
            b = a + sy["dur"] * w[i] / tot
            cap_iv.append((a, b, f"sub_{sy['n']}_{i}")); a = b
badge_iv = []
for p in plan:
    s0 = p["start"]
    for sg in p["segs"]:
        if sg.get("demo"): badge_iv.append((s0, s0 + sg["d"], "demo"))
        elif sg.get("gen"): badge_iv.append((s0, s0 + sg["d"], "gen"))
        s0 += sg["d"]
pts = sorted({0.0, TOTAL, *[x for a, b, _ in cap_iv for x in (a, b)], *[x for a, b, _ in badge_iv for x in (a, b)]})
pts = [x for x in pts if x <= TOTAL]
lines_out = ["ffconcat version 1.0"]
blank = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0)); blank.save(OV / "blank.png")
srt = []
for i in range(len(pts) - 1):
    a, b = pts[i], pts[i + 1]; mid = (a + b) / 2; im = blank.copy(); tag = []
    for x, y, n in cap_iv:
        if x <= mid < y: im = Image.alpha_composite(im, card(n)); tag.append(n)
    for x, y, n in badge_iv:
        if x <= mid < y: im = Image.alpha_composite(im, badge_demo if n == "demo" else badge_gen); tag.append(n)
    name = "ov_" + "_".join(tag) if tag else "blank"
    if name != "blank" and not (OV / f"{name}.png").exists(): im.save(OV / f"{name}.png")
    lines_out += [f"file '{name}.png'", f"duration {b - a:.4f}"]
lines_out.append("file 'blank.png'")
(OV / "ov.ffconcat").write_text("\n".join(lines_out) + "\n", encoding="utf-8")
ovmov = HERE / "overlay.mov"
run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(OV / "ov.ffconcat"), "-vf", f"fps={FPS},format=rgba", "-c:v", "png", "-t", f"{TOTAL:.3f}", str(ovmov)])
print("▶ overlay", dur(ovmov))

# ───────────── SRT
def ts(x): h = int(x // 3600); m = int(x % 3600 // 60); s = x % 60; return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s % 1) * 1000)):03d}"
with open(OUT / f"bayan-promo{SFX}.srt", "w", encoding="utf-8") as fh:
    for i, (a, b, n) in enumerate(cap_iv, 1):
        _, nid, idx = n.split("_"); fh.write(f"{i}\n{ts(a)} --> {ts(b)}\n{CAPS[nid][int(idx)]}\n\n")

# ───────────── الصوت: الراوي فقط (بلا موسيقى — بطلب د. صالح 2026-10-27)
ain = []; af = []
evs = [sy for p in plan for sy in p["says"]]
for i, sy in enumerate(evs):
    ain += ["-i", str(HERE / "audio" / f"{sy['n']}.mp3")]
    af.append(f"[{i + 2}:a]adelay={int(sy['at'] * 1000)}|{int(sy['at'] * 1000)},apad[n{i}]")
nm = len(evs)
mix_n = "".join(f"[n{i}]" for i in range(nm))
af.append(f"{mix_n}amix=inputs={nm}:normalize=0:duration=longest,atrim=0:{TOTAL:.3f}[nar]")
af.append("[nar]alimiter=limit=0.95[aout]")
final = OUT / f"bayan-promo{SFX}.mp4"
run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(base), "-i", str(ovmov), *ain,
     "-filter_complex", f"[0:v][1:v]overlay=format=auto[v];" + ";".join(af),
     "-map", "[v]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
     "-c:a", "aac", "-b:a", "192k", "-t", f"{TOTAL:.3f}", "-movflags", "+faststart", str(final)])
print("✔", final, dur(final))
