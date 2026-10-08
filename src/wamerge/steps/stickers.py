#!/usr/bin/env python3

"""Builds a sticker package from the old Android phone, ready for a sticker-maker app on the iPhone. Read-only on the Android copy.

    pip install pillow            (inside the .venv)
    wamerge stickers            # stickers YOU sent, most used first
    wamerge stickers --all      # every sticker, sent or received

Output: output/stickers/
    wastickers/*.wastickers      one file per pack, opens in Sticker Maker Studio
    static/pack-01 ... pack-NN   PNG, 512x512, transparent, 30 per pack
    animated/pack-01 ...         original animated .webp files, 30 per pack
    stickers.zip                 the same, zipped for AirDrop
"""

import hashlib
import io
import os
import shutil
import sqlite3
import sys
import zipfile
from collections import defaultdict

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is missing. Run:  source .venv/bin/activate && pip install pillow")

ALL = "--all" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
RAW = args[0] if len(args) > 0 else "android-raw"
AND = args[1] if len(args) > 1 else "android-decrypted/msgstore.db"
OUT = args[2] if len(args) > 2 else "output/stickers"
PACK = 30

folder = None
for root, dirs, _ in os.walk(RAW):
    for d in dirs:
        if d == "WhatsApp Stickers":
            folder = os.path.join(root, d)
            break
    if folder:
        break
if not folder:
    sys.exit(f"No 'WhatsApp Stickers' folder under {RAW}")

files = {}
for root, _, names in os.walk(folder):
    for n in names:
        if n.lower().endswith(".webp"):
            files[n] = os.path.join(root, n)
print(f"sticker files on disk: {len(files)}")

# How often each file was sent by you / received, from the Android history.
sent, received = defaultdict(int), defaultdict(int)
if os.path.exists(AND):
    db = sqlite3.connect(f"file:{os.path.abspath(AND)}?mode=ro", uri=True)
    for path, from_me, n in db.execute(
        """SELECT mm.file_path, m.from_me, count(*) FROM message_media mm
               JOIN message m ON m._id = mm.message_row_id
               WHERE m.message_type = 20 AND mm.file_path IS NOT NULL GROUP BY 1, 2"""
    ):
        name = os.path.basename(path)
        (sent if from_me else received)[name] += n
    db.close()

# Collapse identical files and total their usage.
by_hash = {}
for name, path in files.items():
    with open(path, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    e = by_hash.setdefault(h, {"path": path, "sent": 0, "received": 0})
    e["sent"] += sent.get(name, 0)
    e["received"] += received.get(name, 0)
print(
    f"distinct stickers: {len(by_hash)}  (sent by you at least once: "
    f"{sum(1 for e in by_hash.values() if e['sent'])})"
)

chosen = [e for e in by_hash.values() if ALL or e["sent"] > 0]
chosen.sort(key=lambda e: (-e["sent"], -e["received"], e["path"]))
if not chosen:
    sys.exit("Nothing selected. Try --all.")

if os.path.exists(OUT):
    shutil.rmtree(OUT)
counts = {"static": 0, "animated": 0, "unreadable": 0}
packs = {"static": {}, "animated": {}}  # kind -> pack number -> [source paths]
for e in chosen:
    try:
        im = Image.open(e["path"])
        animated = getattr(im, "n_frames", 1) > 1
        kind = "animated" if animated else "static"
        counts[kind] += 1
        n = counts[kind]
        packs[kind].setdefault((n - 1) // PACK + 1, []).append(e["path"])
        d = os.path.join(OUT, kind, f"pack-{(n - 1) // PACK + 1:02d}")
        os.makedirs(d, exist_ok=True)
        if animated:
            shutil.copyfile(e["path"], os.path.join(d, f"{n:04d}.webp"))
        else:
            im = im.convert("RGBA")
            im.thumbnail((512, 512), Image.LANCZOS)
            canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            canvas.paste(im, ((512 - im.width) // 2, (512 - im.height) // 2), im)
            canvas.save(os.path.join(d, f"{n:04d}.png"), optimize=True)
    except Exception:
        counts["unreadable"] += 1

# .wastickers files: a zip holding the stickers as 512x512 .webp, a 96x96 tray
# icon, and the pack title and author. Original files are used unchanged when
# they already meet WhatsApp's limits, so animated stickers stay animated.
LIMIT = {"static": 100 * 1024, "animated": 500 * 1024}


def anim_info(data):
    """(frames that cover only part of the canvas, frames with no display time)."""
    pos, partial, zero = 12, 0, 0
    while pos + 8 <= len(data):
        tag = data[pos : pos + 4]
        size = int.from_bytes(data[pos + 4 : pos + 8], "little")
        if tag == b"ANMF":
            p = data[pos + 8 : pos + 24]
            w = int.from_bytes(p[6:9], "little") + 1
            h = int.from_bytes(p[9:12], "little") + 1
            if (w, h) != (512, 512):
                partial += 1
            if int.from_bytes(p[12:15], "little") < 8:
                zero += 1
        pos += 8 + size + (size & 1)
    return partial, zero


def repair_animated(data):
    """Rebuild an animated sticker that some apps draw wrongly:
      - a frame that is one flat opaque colour while its neighbours are not
        (shows as a black flash),
      - frames with no display time (WhatsApp wants at least 8 ms),
      - frames stored as patches over the previous one (drawn as garbage by
        viewers that do not layer them correctly).
    Every frame is flattened to a full picture and saved as its own key frame.
    Returns (bytes, changed)."""
    im = Image.open(io.BytesIO(data))
    partial, zero = anim_info(data)
    frames, durs, flat = [], [], []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        f = im.convert("RGBA")
        frames.append(f)
        durs.append(im.info.get("duration") or 0)
        lo_hi = f.getextrema()
        flat.append(all(hi - lo <= 2 for lo, hi in lo_hi) and lo_hi[3][0] >= 250)
    bad = {i for i, x in enumerate(flat) if x}
    if len(bad) > max(1, len(frames) // 10):
        bad = set()  # flat frames are part of the design
    if not bad and not partial and not zero:
        return data, False
    keep = [i for i in range(len(frames)) if i not in bad and durs[i] >= 8]
    if len(keep) < 2:
        return data, False
    kd = [durs[i] for i in keep]
    for extra in ({"kmin": 1, "kmax": 1}, {}):  # all key frames first, then the default
        for q in (80, 65, 50, 35, 20):
            buf = io.BytesIO()
            frames[keep[0]].save(
                buf,
                "WEBP",
                save_all=True,
                append_images=[frames[i] for i in keep[1:]],
                duration=kd,
                loop=0,
                quality=q,
                method=4,
                **extra,
            )
            if buf.tell() <= LIMIT["animated"]:
                return buf.getvalue(), True
    return data, False


repaired = 0
wdir = os.path.join(OUT, "wastickers")
os.makedirs(wdir, exist_ok=True)
made = dropped = 0
for kind in ("static", "animated"):
    for num, paths in sorted(packs[kind].items()):
        items = []
        for p in paths:
            with open(p, "rb") as f:
                data = f.read()
            if kind == "animated":
                try:
                    data, changed = repair_animated(data)
                    repaired += 1 if changed else 0
                except Exception:
                    pass
            im = Image.open(io.BytesIO(data))
            if im.size != (512, 512) or len(data) > LIMIT[kind]:
                if kind == "animated":
                    dropped += 1  # cannot be shrunk without breaking the animation
                    continue
                im = im.convert("RGBA")
                im.thumbnail((512, 512), Image.LANCZOS)
                canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
                canvas.paste(im, ((512 - im.width) // 2, (512 - im.height) // 2), im)
                for q in (90, 75, 60, 40, 20):
                    buf = io.BytesIO()
                    canvas.save(buf, "WEBP", quality=q)
                    data = buf.getvalue()
                    if len(data) <= LIMIT[kind]:
                        break
            items.append(data)
        if len(items) < 3:  # WhatsApp needs at least 3 stickers in a pack
            dropped += len(items)
            continue
        tray = (
            Image.open(io.BytesIO(items[0]))
            .convert("RGBA")
            .resize((96, 96), Image.LANCZOS)
        )
        tbuf = io.BytesIO()
        tray.save(tbuf, "PNG", optimize=True)
        title = f"Old {'animated ' if kind == 'animated' else ''}stickers {num:02d}"
        with zipfile.ZipFile(
            os.path.join(wdir, f"{kind}-{num:02d}.wastickers"),
            "w",
            zipfile.ZIP_DEFLATED,
        ) as z:
            z.writestr("title.txt", title)
            z.writestr("author.txt", "Me")
            z.writestr("tray.png", tbuf.getvalue())
            for i, data in enumerate(items, start=1):
                z.writestr(f"sticker_{i:02d}.webp", data)
        made += 1
if repaired:
    print(f"animated stickers rebuilt for compatibility: {repaired}")
print(
    f".wastickers packs: {made} in {wdir}/"
    + (f"  (left out: {dropped} stickers)" if dropped else "")
)

shutil.make_archive(OUT.rstrip("/"), "zip", OUT)
shutil.move(OUT.rstrip("/") + ".zip", os.path.join(OUT, "stickers.zip"))
print(f"static:   {counts['static']} PNGs in {-(-counts['static'] // PACK)} packs")
print(f"animated: {counts['animated']} files in {-(-counts['animated'] // PACK)} packs")
if counts["unreadable"]:
    print(f"skipped (unreadable): {counts['unreadable']}")
print(f"ordered by how often you sent them; pack-01 holds your most used")
print(f"saved to {OUT}/ and {OUT}/stickers.zip")
