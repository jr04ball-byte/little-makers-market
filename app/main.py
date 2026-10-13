"""Little Makers Market — web server (FastAPI).

Run locally:  .venv/Scripts/python -m uvicorn app.main:app --reload
"""
from __future__ import annotations

import io
import re
import time

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from . import agents, ai, config, db, media, money, paypal

WEB = config.ROOT / "web"
app = FastAPI(title="Little Makers Market")
db.init()


@app.on_event("startup")
def _seed_demo_once():
    if config.SEED_DEMO and not db.rows("SELECT id FROM shops LIMIT 1"):
        import threading

        from . import seed
        threading.Thread(target=seed.main, name="seed-demo", daemon=True).start()


@app.exception_handler(paypal.PayPalError)
def _paypal_error(_: Request, e: paypal.PayPalError):
    return JSONResponse({"error": "PayPal said no", "detail": e.body}, status_code=502)


# ------------------------------------------------------------------ helpers

def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "shop"


def shop_by_slug(slug: str) -> dict:
    s = db.row("SELECT * FROM shops WHERE slug = ?", slug)
    if not s:
        raise HTTPException(404, "Shop not found")
    return s


def media_url(rel: str | None) -> str | None:
    return f"/media/{rel}" if rel else None


def creation_view(c: dict, with_products: bool = True) -> dict:
    out = {k: c[k] for k in ("id", "shop_id", "maker_id", "status", "character_name", "kind", "title", "story")}
    out["quirks"] = db.loads(c["quirks"], [])
    out["analysis"] = db.loads(c["analysis"], {})
    out["answers"] = db.loads(c["answers"], {})
    for k in ("drawing", "cutout", "model", "stl", "sticker", "print"):
        out[k] = media_url(c[k])
    maker = db.row("SELECT id, nickname, age, emoji FROM makers WHERE id = ?", c["maker_id"])
    out["maker"] = maker
    if with_products:
        out["products"] = db.rows("SELECT * FROM products WHERE creation_id = ? AND active = 1 ORDER BY price_cents", c["id"])
    return out


# ------------------------------------------------------------------ shops & makers

class ShopIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    kind: str = "family"
    owner_name: str = ""
    owner_email: str = ""
    blurb: str = ""
    cause_name: str = ""
    cause_email: str = ""
    cause_pct: int = Field(0, ge=0, le=100)
    goal_cents: int = 0


@app.post("/api/shops")
def create_shop(s: ShopIn):
    if s.kind not in ("family", "fundraiser"):
        raise HTTPException(400, "kind must be family or fundraiser")
    slug = slugify(s.name)
    if db.row("SELECT id FROM shops WHERE slug = ?", slug):
        slug = f"{slug}-{int(time.time()) % 10000}"
    shop = {"id": db.new_id("shop"), "slug": slug, **s.model_dump(), "created": time.time()}
    db.insert("shops", shop)
    db.log_event(shop["id"], "shop", f"{s.name} opened its market")
    return shop


@app.get("/api/shops")
def list_shops():
    return db.rows("SELECT id, slug, name, kind, blurb, cause_name FROM shops ORDER BY created DESC")


@app.get("/api/shops/{slug}")
def get_shop(slug: str, all: bool = False):
    s = shop_by_slug(slug)
    makers = db.rows("SELECT * FROM makers WHERE shop_id = ? ORDER BY created", s["id"])
    q = "SELECT * FROM creations WHERE shop_id = ?" + ("" if all else " AND status = 'published'") + " ORDER BY created DESC"
    creations = [creation_view(c) for c in db.rows(q, s["id"])]
    return {"shop": s, "makers": [money.maker_with_balance(m) for m in makers], "creations": creations,
            "stats": money.shop_stats(s["id"])}


class MakerIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=24)
    age: int | None = Field(None, ge=2, le=17)
    emoji: str = "🎨"
    family_name: str = ""
    payout_email: str = ""
    goal_name: str = ""
    goal_cents: int = 0
    save_pct: int = 50
    spend_pct: int = 30
    give_pct: int = 20


@app.post("/api/shops/{slug}/makers")
def add_maker(slug: str, m: MakerIn):
    s = shop_by_slug(slug)
    if m.save_pct + m.spend_pct + m.give_pct != 100:
        raise HTTPException(400, "save + spend + give must add up to 100")
    maker = {"id": db.new_id("mkr"), "shop_id": s["id"], **m.model_dump(), "created": time.time()}
    db.insert("makers", maker)
    return maker


# ------------------------------------------------------------------ creations (the maker wizard)

@app.post("/api/creations")
def new_creation(shop: str = Form(...), maker_id: str = Form(...), photo: UploadFile = File(...)):
    s = shop_by_slug(shop)
    maker = db.row("SELECT * FROM makers WHERE id = ? AND shop_id = ?", maker_id, s["id"])
    if not maker:
        raise HTTPException(404, "Maker not found")
    data = photo.file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Photo is too big (15 MB max)")
    try:
        img = media.normalize_photo(Image.open(io.BytesIO(data)))
    except UnidentifiedImageError:
        raise HTTPException(400, "That file isn't a picture")

    analysis = ai.analyze_drawing(img)
    if not analysis.get("is_drawing", True) or not analysis.get("safe", True):
        return JSONResponse({"rejected": True, "reason": analysis.get("safety_note") or
                             "This doesn't look like a kid's drawing we can sell."}, status_code=422)

    cid = db.new_id("art")
    files = media.build_all(img, config.MEDIA_DIR / cid)
    db.insert("creations", {"id": cid, "shop_id": s["id"], "maker_id": maker_id, "status": "draft",
                            "kind": analysis.get("kind"), "quirks": analysis.get("quirks", []),
                            "analysis": analysis, "created": time.time(), **files})
    return creation_view(db.row("SELECT * FROM creations WHERE id = ?", cid))


class AnswersIn(BaseModel):
    answers: dict[str, str]


@app.post("/api/creations/{cid}/answers")
def answer_questions(cid: str, body: AnswersIn):
    c = db.row("SELECT * FROM creations WHERE id = ?", cid)
    if not c:
        raise HTTPException(404)
    maker = db.row("SELECT * FROM makers WHERE id = ?", c["maker_id"])
    img = Image.open(config.MEDIA_DIR / c["drawing"])
    listing = ai.write_listing(img, db.loads(c["analysis"], {}), body.answers, maker["nickname"], maker["age"])
    db.update("creations", cid, {"answers": body.answers, "character_name": listing.get("character_name"),
                                 "title": listing.get("title"), "story": listing.get("story"),
                                 "analysis": {**db.loads(c["analysis"], {}), "listing": listing}})
    with db.tx() as con:
        con.execute("DELETE FROM products WHERE creation_id = ?", (cid,))
    for kind, physical in (("plush3d", 0), ("sticker", 1), ("print", 1)):
        p = listing.get("products", {}).get(kind) or {}
        price = int(p.get("price_cents") or {"plush3d": 500, "sticker": 400, "print": 1800}[kind])
        db.insert("products", {"id": db.new_id("prd"), "creation_id": cid, "kind": kind,
                               "name": p.get("name") or kind, "description": p.get("description", ""),
                               "price_cents": max(100, min(price, 5000)), "physical": physical})
    return creation_view(db.row("SELECT * FROM creations WHERE id = ?", cid))


class ProductPatch(BaseModel):
    price_cents: int | None = Field(None, ge=100, le=10000)
    active: bool | None = None


@app.patch("/api/products/{pid}")
def patch_product(pid: str, p: ProductPatch):
    data = {k: v for k, v in p.model_dump().items() if v is not None}
    if data:
        db.update("products", pid, data)
    return db.row("SELECT * FROM products WHERE id = ?", pid)


@app.post("/api/creations/{cid}/publish")
def publish(cid: str):
    c = db.row("SELECT * FROM creations WHERE id = ?", cid)
    if not c or not c["title"]:
        raise HTTPException(400, "Finish the questions first")
    db.update("creations", cid, {"status": "published"})
    db.log_event(c["shop_id"], "publish", f"New in the shop: {c['title']}", {"creation_id": cid})
    return creation_view(db.row("SELECT * FROM creations WHERE id = ?", cid))


@app.get("/api/creations/{cid}")
def get_creation(cid: str):
    c = db.row("SELECT * FROM creations WHERE id = ?", cid)
    if not c:
        raise HTTPException(404)
    out = creation_view(c)
    s = db.row("SELECT slug, name, kind, cause_name, cause_pct FROM shops WHERE id = ?", c["shop_id"])
    out["shop"] = s
    return out


# ------------------------------------------------------------------ checkout (PayPal Orders v2)

class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(1, ge=1, le=20)


class CheckoutIn(BaseModel):
    items: list[CartItem]
    message: str = Field("", max_length=200)   # a note to the little maker
    channel: str = "web"                         # web | agent
    agent_name: str = ""


@app.post("/api/checkout/orders")
def checkout_create(body: CheckoutIn):
    return money.create_checkout(body.items, body.message, body.channel, body.agent_name)


@app.post("/api/checkout/orders/{paypal_order_id}/capture")
def checkout_capture(paypal_order_id: str):
    return money.capture_checkout(paypal_order_id)


@app.get("/api/config")
def public_config():
    return {"paypal_client_id": config.PAYPAL_CLIENT_ID, "currency": config.CURRENCY, "env": config.PAYPAL_ENV}


# ------------------------------------------------------------------ Grandparent Club (PayPal Subscriptions)

@app.post("/api/shops/{slug}/club")
def club_plan(slug: str):
    return {"plan_id": money.ensure_club_plan(shop_by_slug(slug))}


class ClubJoin(BaseModel):
    subscription_id: str
    subscriber_name: str = ""


@app.post("/api/shops/{slug}/club/joined")
def club_joined(slug: str, j: ClubJoin):
    return money.record_club_join(shop_by_slug(slug), j.subscription_id, j.subscriber_name)


# ------------------------------------------------------------------ payouts & dashboard

@app.post("/api/shops/{slug}/payouts")
def run_payouts(slug: str):
    return money.pay_out_shop(shop_by_slug(slug))


@app.get("/api/shops/{slug}/dashboard")
def dashboard(slug: str):
    s = shop_by_slug(slug)
    return {"shop": s, "stats": money.shop_stats(s["id"]),
            "orders": db.rows("SELECT * FROM orders WHERE shop_id = ? ORDER BY created DESC LIMIT 200", s["id"]),
            "ledger": db.rows("SELECT l.*, m.nickname FROM ledger l LEFT JOIN makers m ON m.id = l.maker_id "
                              "WHERE l.shop_id = ? ORDER BY l.created DESC LIMIT 500", s["id"]),
            "payouts": db.rows("SELECT * FROM payouts WHERE shop_id = ? ORDER BY created DESC", s["id"]),
            "subscriptions": db.rows("SELECT * FROM subscriptions WHERE shop_id = ? ORDER BY created DESC", s["id"]),
            "events": db.rows("SELECT * FROM events WHERE shop_id = ? ORDER BY created DESC LIMIT 50", s["id"]),
            "makers": [money.maker_with_balance(m) for m in db.rows("SELECT * FROM makers WHERE shop_id = ?", s["id"])]}


class ChatIn(BaseModel):
    messages: list[dict]


@app.post("/api/shops/{slug}/assistant")
def assistant(slug: str, body: ChatIn):
    return agents.chat(shop_by_slug(slug), body.messages)


# ------------------------------------------------------------------ webhooks

@app.post("/api/paypal/webhook")
async def webhook(request: Request):
    event = await request.json()
    verified = paypal.verify_webhook(dict(request.headers), event) if config.PAYPAL_WEBHOOK_ID else False
    if config.PAYPAL_WEBHOOK_ID and not verified:
        raise HTTPException(400, "Signature check failed")
    money.handle_webhook(event)
    return {"ok": True}


# ------------------------------------------------------------------ pages & files

app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

@app.get("/thanks")
def thanks_page():
    return FileResponse(WEB / "thanks.html")


@app.get("/")
def home():
    return FileResponse(WEB / "index.html")


@app.get("/studio/{slug}")
def studio_page(slug: str):
    return FileResponse(WEB / "studio.html")


@app.get("/shop/{slug}")
def shop_page(slug: str):
    return FileResponse(WEB / "shop.html")


@app.get("/art/{cid}")
def art_page(cid: str):
    return FileResponse(WEB / "art.html")


@app.get("/dashboard/{slug}")
def dashboard_page(slug: str):
    return FileResponse(WEB / "dashboard.html")
