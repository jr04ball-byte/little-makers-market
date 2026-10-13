"""Puff engine: turns a flat kid's drawing into a soft, plush-like 3D model.

The character is cut off the paper, its outline is "inflated" like a balloon
(thick where the drawing is wide, round where it is thin, e.g. stick legs), and
the original crayon art is wrapped on the front and back. Every quirk of the
drawing is kept because the shape *is* the drawing's outline.

CPU only (numpy, scipy, scikit-image, trimesh), so it runs on a plain web host.

    python puff.py <drawing.png> <out.glb> [--mask-out mask.png]
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageFilter
from scipy import ndimage
from skimage import measure

WORK_RES = 256          # size of the inflation grid (longest side, pixels)
TEX_RES = 1024          # texture size baked into the .glb
PUFF = 0.6              # how fat the plush is (cross-section height vs width)
MAX_FACES = 30000
MIN_HALF_THICKNESS = 2.2  # grid cells; keeps stick legs printable


_session = None


def cut_out(img: Image.Image) -> np.ndarray:
    """Boolean mask of the main character, using rembg on the drawing.

    REMBG_MODEL=u2netp (5 MB) suits small cloud instances; u2net (176 MB) is a bit cleaner.
    """
    import os

    from rembg import new_session, remove

    global _session
    if _session is None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.enable_cpu_mem_arena = False  # without this the arena keeps ~250 MB after each run
        opts.enable_mem_pattern = False
        opts.intra_op_num_threads = int(os.environ.get("REMBG_THREADS", "2"))
        opts.inter_op_num_threads = 1
        _session = new_session(os.environ.get("REMBG_MODEL", "u2net"), providers=["CPUExecutionProvider"],
                               sess_opts=opts)
    rgba = remove(img.convert("RGB"), session=_session, post_process_mask=True)
    return np.asarray(rgba)[:, :, 3] > 127


def clean_mask(mask: np.ndarray) -> np.ndarray:
    mask = ndimage.binary_closing(mask, iterations=2)
    mask = ndimage.binary_fill_holes(mask)
    labels, n = ndimage.label(mask)
    if n == 0:
        raise ValueError("Couldn't find a character in the picture.")
    sizes = ndimage.sum(mask, labels, range(1, n + 1))
    keep = np.isin(labels, 1 + np.flatnonzero(sizes >= sizes.max() * 0.08))
    return keep


def height_field(mask: np.ndarray) -> np.ndarray:
    """Half-thickness of the plush at each pixel."""
    d = ndimage.distance_transform_edt(mask)
    dmax = max(d.max(), 1.0)
    h = PUFF * np.sqrt(d * dmax)          # balloon-like: round edges, gently domed middle
    h = np.where(mask, np.maximum(h, MIN_HALF_THICKNESS), 0.0)
    h = ndimage.gaussian_filter(h, 1.2)
    return h


def puff(drawing: Image.Image, mask: np.ndarray | None = None) -> tuple[trimesh.Trimesh, np.ndarray]:
    drawing = drawing.convert("RGB")
    if mask is None:
        mask = cut_out(drawing)
    mask = clean_mask(mask)

    # crop to the character with a margin, then work on a small grid
    ys, xs = np.nonzero(mask)
    pad = int(0.04 * max(mask.shape))
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad, mask.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad, mask.shape[1])
    tex = drawing.crop((x0, y0, x1, y1))
    m = mask[y0:y1, x0:x1]
    scale = WORK_RES / max(m.shape)
    gw, gh = max(int(m.shape[1] * scale), 8), max(int(m.shape[0] * scale), 8)
    small = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).resize((gw, gh), Image.BILINEAR)) > 127
    small = np.pad(small, 2)

    h = height_field(small)
    zmax = int(np.ceil(h.max())) + 2
    zs = np.arange(-zmax, zmax + 1, 1.0)
    # signed field: positive inside the plush
    vol = h[:, :, None] - np.abs(zs[None, None, :])
    verts, faces, _, _ = measure.marching_cubes(vol, level=0.5)  # >0 so the empty z=0 plane is not a surface
    # verts are (row, col, zi) -> x right, y up, z towards viewer (glTF convention)
    row, col, zi = verts[:, 0], verts[:, 1], verts[:, 2]
    x = col - 2
    y = -(row - 2)
    z = zs[0] + zi
    mesh = trimesh.Trimesh(np.column_stack([x, y, z]), faces[:, ::-1], process=True)
    trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53, iterations=8)
    if len(mesh.faces) > MAX_FACES:  # keeps the .glb light enough for phones
        mesh = mesh.simplify_quadric_decimation(face_count=MAX_FACES)

    # planar projection of the drawing onto front (and mirrored onto back)
    u = np.clip(mesh.vertices[:, 0] / (gw - 1), 0, 1)
    v = np.clip(1 + mesh.vertices[:, 1] / (gh - 1), 0, 1)
    tex = bleed(tex, Image.fromarray(m.astype(np.uint8) * 255)).resize((TEX_RES, int(TEX_RES * tex.height / tex.width)))
    buf = io.BytesIO()
    tex.save(buf, "JPEG", quality=88)  # trimesh keeps JPEGs as JPEG inside the .glb (PNG would be ~4x bigger)
    tex = Image.open(io.BytesIO(buf.getvalue()))
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.column_stack([u, v]),
                                                material=trimesh.visual.material.PBRMaterial(
                                                    baseColorTexture=tex, roughnessFactor=0.9, metallicFactor=0.0))

    # centre on the ground, longest side = 1 unit
    mesh.apply_translation(-mesh.bounds.mean(axis=0))
    mesh.apply_translation([0, -mesh.bounds[0][1], 0])
    mesh.apply_scale(1.0 / max(mesh.extents))
    return mesh, small


def bleed(tex: Image.Image, mask: Image.Image) -> Image.Image:
    """Grow the character's edge colours outward so the puffy sides aren't paper-white."""
    mask = mask.resize(tex.size)
    edge = tex.copy()
    for r in (3, 7, 15):
        grown = Image.composite(tex, edge.filter(ImageFilter.MinFilter(r)), mask)
        edge = Image.composite(tex, grown, mask)
    # outline colour (the kid's marker) for everything outside the character
    outside = Image.new("RGB", tex.size, (45, 45, 50))
    ring = mask.filter(ImageFilter.MaxFilter(9))
    return Image.composite(edge, outside, ring)


def to_glb_bytes(mesh: trimesh.Trimesh) -> bytes:
    return mesh.export(file_type="glb")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("drawing")
    ap.add_argument("out")
    ap.add_argument("--mask-out")
    ap.add_argument("--stl", help="Also write a printable STL here (height in mm via --mm)")
    ap.add_argument("--mm", type=float, default=80.0)
    a = ap.parse_args()
    mesh, small = puff(Image.open(a.drawing))
    Path(a.out).write_bytes(to_glb_bytes(mesh))
    if a.mask_out:
        Image.fromarray(small.astype(np.uint8) * 255).save(a.mask_out)
    if a.stl:
        m = mesh.copy()
        m.apply_scale(a.mm)
        m.export(a.stl)
    print(f"{a.out}: {len(mesh.faces)} triangles, watertight={mesh.is_watertight}")


if __name__ == "__main__":
    main()
