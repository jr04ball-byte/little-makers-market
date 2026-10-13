"""What every creation can become, what it costs to make, and where it is made.

Physical items are printed and shipped by Prodigi (print-on-demand). Costs are Prodigi sandbox quotes
for one item shipped Budget to the US (Oct 2026) and are taken out before the kid's share is split.
"""
from __future__ import annotations

PRODUCTS: dict[str, dict] = {
    "plush3d": {"label": "3D plush — AR + printable file", "emoji": "🧸", "price_cents": 500, "cost_cents": 0,
                "physical": False},
    "sticker": {"label": "Die-cut vinyl sticker (3×4\")", "emoji": "⭐", "price_cents": 1500, "cost_cents": 1159,
                "physical": True, "sku": "M-STI-3X4", "size": (900, 1200)},
    "print": {"label": "8×10 fine-art print", "emoji": "🖼️", "price_cents": 2200, "cost_cents": 1585,
              "physical": True, "sku": "GLOBAL-FAP-8X10", "size": (2400, 3000)},
    "mug": {"label": "11oz ceramic mug", "emoji": "☕", "price_cents": 1900, "cost_cents": 1218,
            "physical": True, "sku": "GLOBAL-MUG-W", "size": (2670, 1110)},
    "pillow": {"label": "18×18\" faux-suede pillow", "emoji": "🛋️", "price_cents": 3800, "cost_cents": 2835,
               "physical": True, "sku": "GLOBAL-CUSH-18X18-SUE", "size": (2775, 2775)},
    "blanket": {"label": "50×60\" premium fleece blanket", "emoji": "🧣", "price_cents": 6400, "cost_cents": 4795,
                "physical": True, "sku": "GLOBAL-BLANKET-PREMIUM-FLEECE-50X60", "size": (7875, 9375)},
}

ORDER = ["plush3d", "sticker", "mug", "print", "pillow", "blanket"]

# Specialists we link to (family pays them directly — all accept PayPal)
SPECIALISTS = [
    {"kind": "plush", "name": "Budsies", "what": "A hand-sewn plush toy made from the original drawing (~$139, 6–8 weeks)",
     "url": "https://www.budsies.com/kids-drawings-stuffed-animals/"},
    {"kind": "figurine", "name": "Treatstock", "what": "A real 3D-printed figurine from our printable plush file",
     "url": "https://www.treatstock.com/"},
]
