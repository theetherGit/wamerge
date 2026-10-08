import io
import os
import zipfile

import pytest

from conftest import make_android, run

Image = pytest.importorskip("PIL.Image")


def anim(path, durations, colours, size=(512, 512)):
    frames = [Image.new("RGBA", size, c) for c in colours]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0)


def build(tmp_path):
    d = tmp_path / "android-raw/WhatsApp/Media/WhatsApp Stickers"
    os.makedirs(d)
    os.makedirs(tmp_path / "android-decrypted")
    make_android(tmp_path / "android-decrypted/msgstore.db")
    for i in range(4):
        Image.new("RGBA", (300, 200), (i * 40, 10, 200, 255)).save(d / f"STK-{i}.webp")
    os.link(d / "STK-1.webp", d / "STK-copy.webp") if hasattr(os, "link") else None
    grad = [Image.linear_gradient("L").resize((512, 512)).convert("RGBA") for _ in range(3)]
    for k, g in enumerate(grad):
        g.putpixel((0, 0), (k * 50, 0, 0, 255))
    # a healthy animation, one with a zero-time frame, one with a flat black last frame
    # kmin/kmax=1 stores every frame whole, which is the form that needs no repair
    grad[0].save(d / "STK-ok.webp", save_all=True, append_images=grad[1:], duration=[100, 100, 100], loop=0,
                 kmin=1, kmax=1)
    grad[0].save(d / "STK-zero.webp", save_all=True, append_images=grad[1:], duration=[100, 0, 100], loop=0)
    black = Image.new("RGBA", (512, 512), (0, 0, 0, 255))
    grad[0].save(d / "STK-flash.webp", save_all=True, append_images=[grad[1], grad[2]] * 6 + [black],
                 duration=[60] * 14, loop=0)
    return d


def frames(data):
    im = Image.open(io.BytesIO(data))
    out = []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        extrema = im.convert("RGBA").getextrema()        # decoding the frame fills in its duration
        out.append((im.info.get("duration"), extrema))
    return out


def test_packs_are_built_and_valid(tmp_path):
    build(tmp_path)
    r = run(tmp_path, "stickers", "android-raw", "android-decrypted/msgstore.db", "output/stickers", "--all")
    assert r.returncode == 0, r.stdout + r.stderr
    packs = sorted(os.listdir(tmp_path / "output/stickers/wastickers"))
    assert packs == ["animated-01.wastickers", "static-01.wastickers"]
    z = zipfile.ZipFile(tmp_path / "output/stickers/wastickers/static-01.wastickers")
    names = z.namelist()
    assert {"title.txt", "author.txt", "tray.png"} <= set(names)
    stickers = [n for n in names if n.endswith(".webp")]
    assert len(stickers) == 4                                   # the duplicate file is collapsed
    for n in stickers:
        data = z.read(n)
        assert Image.open(io.BytesIO(data)).size == (512, 512) and len(data) <= 100 * 1024
    assert Image.open(io.BytesIO(z.read("tray.png"))).size == (96, 96)


def test_animated_stickers_are_repaired(tmp_path):
    build(tmp_path)
    r = run(tmp_path, "stickers", "android-raw", "android-decrypted/msgstore.db", "output/stickers", "--all")
    assert "rebuilt for compatibility: 2" in r.stdout, r.stdout
    z = zipfile.ZipFile(tmp_path / "output/stickers/wastickers/animated-01.wastickers")
    # a sticker with nothing wrong is copied byte for byte
    healthy = open(tmp_path / "android-raw/WhatsApp/Media/WhatsApp Stickers/STK-ok.webp", "rb").read()
    assert healthy in [z.read(n) for n in z.namelist() if n.endswith(".webp")]
    all_frames = [frames(z.read(n)) for n in z.namelist() if n.endswith(".webp")]
    assert len(all_frames) == 3
    for fr in all_frames:
        assert len(fr) >= 2
        for duration, extrema in fr:
            assert duration >= 8                                   # WhatsApp's minimum
            assert not all(hi - lo <= 2 for lo, hi in extrema)     # no flat-colour frame left
    for n in z.namelist():
        if n.endswith(".webp"):
            assert len(z.read(n)) <= 500 * 1024


def test_default_selection_needs_sent_stickers(tmp_path):
    build(tmp_path)
    r = run(tmp_path, "stickers", "android-raw", "android-decrypted/msgstore.db", "output/stickers")
    assert r.returncode != 0 and "--all" in r.stderr


def test_cli_help_and_unknown_step(tmp_path):
    r = run(tmp_path, "--help")
    assert r.returncode == 0 and "extract" in r.stdout and "install" in r.stdout
    r = run(tmp_path, "nonsense")
    assert r.returncode == 2
    r = run(tmp_path, "merge", "--help")
    assert r.returncode == 0 and "Stage 1 merge" in r.stdout
