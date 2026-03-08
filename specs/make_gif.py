"""
make_gif.py
───────────
Converts the PNG frames rendered by render_boom_dance.py into an
animated GIF.  Requires Pillow:

    pip3 install Pillow

Run from the project root (or anywhere):
    python3 specs/make_gif.py

Output: boom-dance-rendered.gif  (next to robot.html)
"""

import os
import sys
import glob

# ── CONFIG ────────────────────────────────────────────────────────────────────

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES_DIR = os.path.join(ROOT, "frames_boom_dance")
OUTPUT_GIF = os.path.join(ROOT, "boom-dance-rendered.gif")

GIF_WIDTH   = 240   # px  (height is scaled proportionally) — lower = smaller file
FPS         = 12    # output fps  (12 = use every other frame, half the size of 24)
FRAME_SKIP  = 2     # use every Nth rendered frame  (2 → halves frame count)
COLORS      = 64    # palette depth (64–256) — lower = smaller file, less colour detail
LOOP        = 0     # 0 = loop forever


# ── HELPERS ───────────────────────────────────────────────────────────────────

def log(msg): print(f"[make_gif] {msg}")


# ── CHECK FRAMES ──────────────────────────────────────────────────────────────

frame_paths = sorted(glob.glob(os.path.join(FRAMES_DIR, "frame_*.png")))
if not frame_paths:
    log(f"ERROR: No frames found in {FRAMES_DIR}")
    log("Run  blender --background --python specs/render_boom_dance.py  first.")
    sys.exit(1)

log(f"Found {len(frame_paths)} frames in {FRAMES_DIR}")


# ── IMPORT PILLOW ─────────────────────────────────────────────────────────────

try:
    from PIL import Image
except ImportError:
    log("Pillow not found. Installing…")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image
    log("Pillow installed successfully.")


# ── LOAD + RESIZE FRAMES ──────────────────────────────────────────────────────

log("Loading and resizing frames…")
frames = []

for path in frame_paths[::FRAME_SKIP]:
    img = Image.open(path).convert("RGB")
    w, h   = img.size
    new_h  = int(h * GIF_WIDTH / w)
    img    = img.resize((GIF_WIDTH, new_h), Image.LANCZOS)

    # Quantise to a fixed palette (required for animated GIF)
    img_p  = img.quantize(colors=COLORS, method=Image.Quantize.MEDIANCUT)
    frames.append(img_p)

log(f"Resized to {GIF_WIDTH}×{new_h} px  ({len(frames)} frames)")


# ── WRITE GIF ─────────────────────────────────────────────────────────────────

duration_ms = int(1000 / FPS)   # ms per frame

log(f"Writing GIF ({duration_ms} ms/frame = {FPS} fps)…")

frames[0].save(
    OUTPUT_GIF,
    save_all      = True,
    append_images = frames[1:],
    loop          = LOOP,
    duration      = duration_ms,
    optimize      = True,
)

size_kb = os.path.getsize(OUTPUT_GIF) // 1024
log(f"Done → {OUTPUT_GIF}  ({size_kb} KB)")
log("Tip: if the file is too large, raise SKIP in render_boom_dance.py (e.g. SKIP=2)")
