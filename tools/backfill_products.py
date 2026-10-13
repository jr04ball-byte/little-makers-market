"""One-off: give creations made before the mug/pillow/blanket update their mockups and full product list.

    python tools/backfill_products.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from app import catalog, config, db, media  # noqa: E402
from app.main import make_products  # noqa: E402

db.init()
for c in db.rows("SELECT * FROM creations"):
    folder = config.MEDIA_DIR / c["id"]
    if not (folder / "cutout.png").exists():
        continue
    if not (folder / "mug.jpg").exists():
        media.home_mockups(Image.open(folder / "cutout.png").convert("RGBA"), folder)
    kinds = {p["kind"] for p in db.rows("SELECT kind FROM products WHERE creation_id = ?", c["id"])}
    if set(catalog.ORDER) - kinds and c["title"]:
        listing = (db.loads(c["analysis"], {}) or {}).get("listing", {})
        make_products(c["id"], listing, c["character_name"] or c["kind"] or "Creation")
        print("updated", c["title"])
