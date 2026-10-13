"""Turns an uploaded drawing into shop media: cutout, plush 3D (.glb + printable .stl), product mockups,
and the print-ready design files sent to the print shop."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from engine import puff

from . import config


def normalize_photo(img: Image.Image, max_side: int = 1600) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((max_side, max_side))
    return img


def build_all(drawing: Image.Image, out_dir: Path) -> dict:
    """Returns paths (relative to MEDIA_DIR) of every generated file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    drawing = normalize_photo(drawing)
    drawing.save(out_dir / "drawing.jpg", quality=92)

    mask = puff.clean_mask(puff.cut_out(drawing))
    cut = cutout_rgba(drawing, mask)
    cut.save(out_dir / "cutout.png")

    mesh, _ = puff.puff(drawing, mask)
    (out_dir / "plush.glb").write_bytes(puff.to_glb_bytes(mesh))
    printable = mesh.copy()
    printable.apply_scale(80.0)  # 80 mm tall keepsake
    printable.export(out_dir / "plush.stl")

    sticker_mockup(cut).save(out_dir / "sticker.png")
    print_mockup(drawing).save(out_dir / "print.jpg", quality=90)
    home_mockups(cut, out_dir)

    rel = lambda name: str((out_dir / name).relative_to(config.MEDIA_DIR)).replace("\\", "/")
    return {"drawing": rel("drawing.jpg"), "cutout": rel("cutout.png"), "model": rel("plush.glb"),
            "stl": rel("plush.stl"), "sticker": rel("sticker.png"), "print": rel("print.jpg")}


def cutout_rgba(drawing: Image.Image, mask: np.ndarray) -> Image.Image:
    alpha = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1))
    rgba = drawing.copy()
    rgba.putalpha(alpha)
    return rgba.crop(alpha.getbbox())


def sticker_mockup(cut: Image.Image, size: int = 900) -> Image.Image:
    """Die-cut vinyl sticker: thick white border, soft shadow, slight tilt, on a pastel card."""
    art = cut.copy()
    art.thumbnail((int(size * 0.7), int(size * 0.7)))
    pad = 60
    canvas = Image.new("RGBA", (art.width + pad * 2, art.height + pad * 2), (0, 0, 0, 0))
    canvas.paste(art, (pad, pad), art)
    a = canvas.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    border = a.filter(ImageFilter.MaxFilter(41)).filter(ImageFilter.GaussianBlur(2)).point(lambda v: 255 if v > 128 else 0)
    sticker = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    sticker.putalpha(border)
    sticker = Image.alpha_composite(sticker, canvas)
    shadow = Image.new("RGBA", canvas.size, (40, 30, 60, 0))
    shadow.putalpha(border.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.35)))
    bg = Image.new("RGBA", (size, size), (246, 238, 255, 255))
    d = ImageDraw.Draw(bg)
    for i in range(0, size, 36):  # faint dotted card texture
        for j in range(0, size, 36):
            d.ellipse((i + 16, j + 16, i + 19, j + 19), fill=(232, 220, 248, 255))
    tilt = -6
    shadow = shadow.rotate(tilt, expand=True, resample=Image.BICUBIC)
    sticker = sticker.rotate(tilt, expand=True, resample=Image.BICUBIC)
    ox, oy = (size - sticker.width) // 2, (size - sticker.height) // 2
    bg.alpha_composite(shadow, (ox + 10, oy + 16))
    bg.alpha_composite(sticker, (ox, oy))
    return bg.convert("RGB")


def print_mockup(drawing: Image.Image, size: int = 1000) -> Image.Image:
    """8x10 print in a light wood frame with a white mat, hanging on a soft wall."""
    wall = Image.new("RGB", (size, size), (238, 233, 226))
    art = drawing.copy()
    art.thumbnail((int(size * 0.5), int(size * 0.6)))
    mat = 46
    frame = 26
    fw, fh = art.width + 2 * (mat + frame), art.height + 2 * (mat + frame)
    fx, fy = (size - fw) // 2, (size - fh) // 2 - 10
    shadow = Image.new("L", (size, size), 0)
    ImageDraw.Draw(shadow).rectangle((fx + 14, fy + 22, fx + fw + 14, fy + fh + 22), fill=110)
    wall.paste((150, 140, 130), (0, 0), shadow.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(wall)
    d.rectangle((fx, fy, fx + fw, fy + fh), fill=(201, 164, 118))
    d.rectangle((fx + 6, fy + 6, fx + fw - 6, fy + fh - 6), outline=(176, 138, 94), width=3)
    d.rectangle((fx + frame, fy + frame, fx + fw - frame, fy + fh - frame), fill=(252, 251, 248))
    wall.paste(art, (fx + frame + mat, fy + frame + mat))
    d.rectangle((fx + frame + mat - 1, fy + frame + mat - 1, fx + frame + mat + art.width, fy + frame + mat + art.height),
                outline=(225, 222, 215), width=2)
    return wall


# ------------------------------------------------------------------ mug / pillow / blanket

PASTEL = (244, 238, 255)


def home_mockups(cut: Image.Image, out_dir: Path) -> None:
    """mug.jpg, pillow.jpg, blanket.jpg next to the other media (their paths are derived, not stored)."""
    mug_mockup(design("mug", cut)).save(out_dir / "mug.jpg", quality=88)
    pillow_mockup(design("pillow", cut, scale=0.4)).save(out_dir / "pillow.jpg", quality=88)
    blanket_mockup(design("blanket", cut, scale=0.12)).save(out_dir / "blanket.jpg", quality=88)


def _fit(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    k = min(box[0] / img.width, box[1] / img.height)
    return img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)


def bordered(cut: Image.Image, border: int) -> Image.Image:
    """The character with a white die-cut border, on transparent."""
    pad = border + 4
    c = Image.new("RGBA", (cut.width + 2 * pad, cut.height + 2 * pad), (0, 0, 0, 0))
    c.paste(cut, (pad, pad), cut)
    a = c.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    small = a.resize((max(1, c.width // 4), max(1, c.height // 4)))
    ring = small.filter(ImageFilter.MaxFilter(2 * max(1, border // 8) + 1)).resize(c.size)
    white = Image.new("RGBA", c.size, (255, 255, 255, 0))
    white.putalpha(ring.point(lambda v: 255 if v > 100 else 0))
    return Image.alpha_composite(white, c)


def design(kind: str, cut: Image.Image, drawing: Image.Image | None = None, scale: float = 1.0) -> Image.Image:
    """Print-ready artwork at the print shop's pixel size (times `scale` for previews)."""
    from .catalog import PRODUCTS
    w, h = (int(v * scale) for v in PRODUCTS[kind]["size"])
    if kind == "print":
        canvas = Image.new("RGB", (w, h), (252, 251, 248))
        art = _fit(drawing, (int(w * 0.88), int(h * 0.88)))
        canvas.paste(art, ((w - art.width) // 2, (h - art.height) // 2))
        return canvas
    if kind == "sticker":
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        art = bordered(_fit(cut, (int(w * 0.8), int(h * 0.8))), max(6, w // 40))
        canvas.paste(art, ((w - art.width) // 2, (h - art.height) // 2), art)
        return canvas
    canvas = Image.new("RGB", (w, h), PASTEL)
    if kind == "mug":  # wraps around the mug: the character on the front and on the back
        for cx in (w // 4, 3 * w // 4):
            art = _fit(cut, (int(w * 0.36), int(h * 0.8)))
            canvas.paste(art, (cx - art.width // 2, (h - art.height) // 2), art)
    elif kind == "pillow":
        art = _fit(cut, (int(w * 0.78), int(h * 0.78)))
        canvas.paste(art, ((w - art.width) // 2, (h - art.height) // 2), art)
    elif kind == "blanket":  # a soft pattern of little ones around one big character
        small = _fit(cut, (w // 7, h // 8))
        ghost = small.copy()
        ghost.putalpha(small.getchannel("A").point(lambda v: v * 45 // 255))
        for row, y in enumerate(range(0, h, max(1, h // 6))):
            for x in range(-(w // 10) if row % 2 else 0, w, max(1, w // 5)):
                canvas.paste(ghost, (x + w // 40, y + h // 40), ghost)
        art = _fit(cut, (int(w * 0.62), int(h * 0.55)))
        canvas.paste(art, ((w - art.width) // 2, (h - art.height) // 2), art)
    return canvas


def print_file(cid: str, kind: str) -> Path:
    """Generate (once) the full-resolution design sent to the print shop; returns its path."""
    out = config.MEDIA_DIR / cid / f"print-{kind}.jpg"
    if not out.exists():
        cut = Image.open(config.MEDIA_DIR / cid / "cutout.png").convert("RGBA")
        drawing = Image.open(config.MEDIA_DIR / cid / "drawing.jpg").convert("RGB")
        scale = 0.5 if kind == "blanket" else 1.0  # full 7875x9375 is overkill for fleece; the shop scales to fill
        design(kind, cut, drawing, scale).save(out, quality=92, dpi=(300, 300))
    return out


def _shadowed(bg: Image.Image, piece: Image.Image, mask: Image.Image, at: tuple[int, int], blur: int = 18,
              offset: tuple[int, int] = (10, 16)) -> None:
    sh = Image.new("RGBA", bg.size, (50, 40, 70, 0))
    m = Image.new("L", bg.size, 0)
    m.paste(mask, (at[0] + offset[0], at[1] + offset[1]))
    sh.putalpha(m.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * 0.35)))
    bg.alpha_composite(sh)
    p = piece.convert("RGBA")
    p.putalpha(mask)
    bg.alpha_composite(p, at)


def _card(size: int = 900, color: tuple = (248, 243, 236)) -> Image.Image:
    bg = Image.new("RGBA", (size, size), color + (255,))
    d = ImageDraw.Draw(bg)
    for i in range(0, size, 36):
        for j in range(0, size, 36):
            d.ellipse((i + 16, j + 16, i + 19, j + 19), fill=(236, 228, 218, 255))
    return bg


def mug_mockup(wrap: Image.Image, size: int = 900) -> Image.Image:
    bg = _card(size)
    bw, bh = int(size * 0.46), int(size * 0.5)
    x0, y0 = int(size * 0.2), int(size * 0.26)
    front = wrap.crop((0, 0, wrap.width // 2, wrap.height)).resize((bw, bh), Image.LANCZOS)
    xs = np.linspace(-1, 1, bw)  # cylinder shading: darker towards the edges
    shade = (1 - 0.28 * np.abs(xs) ** 3)[None, :, None]
    body = Image.fromarray((np.asarray(front, dtype=np.float32) * shade).clip(0, 255).astype(np.uint8))
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw - 1, bh - 1), radius=26, fill=255)
    d = ImageDraw.Draw(bg)
    hx = x0 + bw - 24
    d.ellipse((hx, y0 + bh * 0.18, hx + bw * 0.42, y0 + bh * 0.76), outline=(214, 210, 222, 255), width=36)
    d.ellipse((hx + 6, y0 + bh * 0.18 + 6, hx + bw * 0.42 - 6, y0 + bh * 0.76 - 6), outline=(246, 244, 250, 255), width=12)
    _shadowed(bg, body, mask, (x0, y0))
    d.ellipse((x0 + 2, y0 - 16, x0 + bw - 2, y0 + 18), fill=(236, 233, 240, 255), outline=(212, 207, 220, 255), width=3)
    return bg.convert("RGB")


def pillow_mockup(art: Image.Image, size: int = 900) -> Image.Image:
    bg = _card(size, (240, 236, 230))
    s = int(size * 0.7)
    face = art.resize((s, s), Image.LANCZOS)
    pts, n = [], 60
    for side in range(4):  # pinched-corner cushion outline: each side bulges out a little
        for i in range(n):
            t = i / n
            b = 0.035 * s * np.sin(np.pi * t)
            pts.append([(t * s, 0.02 * s - b), (s - 0.02 * s + b, t * s),
                        ((1 - t) * s, s - 0.02 * s + b), (0.02 * s - b, (1 - t) * s)][side])
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    yy, xx = np.mgrid[-1:1:complex(s), -1:1:complex(s)]
    shade = (1 - 0.22 * (xx ** 4 + yy ** 4))[:, :, None]
    face = Image.fromarray((np.asarray(face.convert("RGB"), dtype=np.float32) * shade).clip(0, 255).astype(np.uint8))
    _shadowed(bg, face, mask.filter(ImageFilter.GaussianBlur(1.5)), ((size - s) // 2, (size - s) // 2), blur=24)
    return bg.convert("RGB")


def blanket_mockup(art: Image.Image, size: int = 900) -> Image.Image:
    bg = _card(size, (233, 238, 242))
    w = int(size * 0.6)
    h = int(w * art.height / art.width)
    face = art.resize((w, h), Image.LANCZOS)
    noise = np.random.default_rng(3).normal(0, 4, (h, w, 1)).astype(np.float32)  # soft fleece texture
    face = Image.fromarray((np.asarray(face.convert("RGB"), dtype=np.float32) + noise).clip(0, 255).astype(np.uint8))
    fold = int(w * 0.22)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon([(0, 0), (w, 0), (w, h - fold), (w - fold, h), (0, h)], fill=255)
    at = ((size - w) // 2, (size - h) // 2)
    _shadowed(bg, face, mask, at, blur=26)
    fx, fy = at[0] + w, at[1] + h  # the folded-over corner
    ImageDraw.Draw(bg).polygon([(fx, fy - fold), (fx - fold, fy), (fx - fold, fy - fold)],
                               fill=(226, 218, 240, 255), outline=(205, 196, 222, 255))
    return bg.convert("RGB")
