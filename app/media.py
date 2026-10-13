"""Turns an uploaded drawing into shop media: cutout, plush 3D (.glb + printable .stl), sticker and print mockups."""
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
