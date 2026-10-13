"""Where the money goes: checkout, the save/spend/give + fundraiser split, Grandparent Club, payouts, webhooks."""
from __future__ import annotations

import time

from fastapi import HTTPException

from . import catalog, config, db, media, paypal, prodigi

PAID_BUCKETS = ("save", "spend", "give")


def dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


# ------------------------------------------------------------------ balances & stats

def maker_with_balance(m: dict) -> dict:
    r = db.rows("SELECT bucket, SUM(cents) AS c FROM ledger WHERE maker_id = ? GROUP BY bucket", m["id"])
    b = {x["bucket"]: x["c"] or 0 for x in r}
    earned = sum(b.get(k, 0) for k in PAID_BUCKETS)
    return {**m, "earned_cents": earned, "buckets": {k: b.get(k, 0) for k in PAID_BUCKETS},
            "unpaid_cents": earned + b.get("payout", 0)}


def shop_stats(shop_id: str) -> dict:
    o = db.row("SELECT COUNT(*) n, COALESCE(SUM(total_cents),0) gross FROM orders WHERE shop_id = ? AND status = 'COMPLETED'", shop_id)
    cause = db.row("SELECT COALESCE(SUM(cents),0) c FROM ledger WHERE shop_id = ? AND bucket = 'cause'", shop_id)["c"]
    agent = db.row("SELECT COUNT(*) n FROM orders WHERE shop_id = ? AND status = 'COMPLETED' AND channel = 'agent'", shop_id)["n"]
    club = db.row("SELECT COUNT(*) n FROM subscriptions WHERE shop_id = ? AND status = 'ACTIVE'", shop_id)["n"]
    return {"orders": o["n"], "gross_cents": o["gross"], "cause_cents": cause, "agent_orders": agent, "club_members": club}


# ------------------------------------------------------------------ checkout

def create_checkout(items, message: str = "", channel: str = "web", agent_name: str = "") -> dict:
    if not items:
        raise HTTPException(400, "Cart is empty")
    lines, shop_id, titles = [], None, []
    for it in items:
        p = db.row("SELECT p.*, c.title, c.shop_id, c.status FROM products p JOIN creations c ON c.id = p.creation_id "
                   "WHERE p.id = ? AND p.active = 1", it.product_id)
        if not p or p["status"] != "published":
            raise HTTPException(404, f"Product {it.product_id} is not for sale")
        if shop_id and p["shop_id"] != shop_id:
            raise HTTPException(400, "One shop per checkout")
        shop_id = p["shop_id"]
        titles.append(p["title"])
        lines.append({"product_id": p["id"], "creation_id": p["creation_id"], "name": f"{p['title']} — {p['name']}",
                      "description": p["description"], "sku": p["id"], "unit_cents": p["price_cents"],
                      "quantity": it.quantity, "kind": p["kind"],
                      "category": "PHYSICAL_GOODS" if p["physical"] else "DIGITAL_GOODS"})
    shop = db.row("SELECT * FROM shops WHERE id = ?", shop_id)
    oid = db.new_id("ord")
    physical = any(l["category"] == "PHYSICAL_GOODS" for l in lines)
    desc = f"{shop['name']}: " + ", ".join(dict.fromkeys(titles))
    if shop["kind"] == "fundraiser" and shop["cause_pct"]:
        desc = f"{shop['cause_pct']}% supports {shop['cause_name']}. " + desc
    order = paypal.create_order(lines, reference_id=shop_id, custom_id=oid, description=desc, brand_name=shop["name"],
                                return_url=f"{config.PUBLIC_URL}/thanks?shop={shop['slug']}",
                                cancel_url=f"{config.PUBLIC_URL}/shop/{shop['slug']}", shipping=physical)
    total = sum(l["unit_cents"] * l["quantity"] for l in lines)
    db.insert("orders", {"id": oid, "paypal_order_id": order["id"], "shop_id": shop_id, "items": lines,
                         "total_cents": total, "status": order["status"], "channel": channel,
                         "agent_name": agent_name, "message": message, "created": time.time()})
    return {"id": order["id"], "status": order["status"], "approve_url": paypal.approve_link(order), "total_cents": total}


def capture_checkout(paypal_order_id: str) -> dict:
    o = db.row("SELECT * FROM orders WHERE paypal_order_id = ?", paypal_order_id)
    if not o:
        raise HTTPException(404, "Unknown order")
    if o["status"] == "COMPLETED":
        return {"status": "COMPLETED", "celebrations": celebrations_for(o)}
    res = paypal.capture_order(paypal_order_id)
    return record_capture(o, res)


def record_capture(o: dict, res: dict) -> dict:
    pu = res["purchase_units"][0]
    cap = pu["payments"]["captures"][0]
    payer = res.get("payer", {})
    name = " ".join(filter(None, [payer.get("name", {}).get("given_name"), payer.get("name", {}).get("surname")]))
    db.update("orders", o["id"], {"status": res["status"], "capture_id": cap["id"], "buyer_name": name,
                                  "buyer_email": payer.get("email_address"), "captured": time.time()})
    if res["status"] == "COMPLETED" and cap["status"] in ("COMPLETED", "PENDING"):
        gross = int(round(float(cap["amount"]["value"]) * 100))
        net = cap.get("seller_receivable_breakdown", {}).get("net_amount")
        net_cents = int(round(float(net["value"]) * 100)) if net else gross
        split_order(o, gross, net_cents)
        fulfill(o, res)
        first = (name.split(" ")[0] if name else "Someone")
        db.log_event(o["shop_id"], "sale", f"{first} bought {len(db.loads(o['items'], []))} item(s) for {dollars(gross)}"
                     + (f" via {o['agent_name'] or 'an AI agent'}" if o["channel"] == "agent" else ""),
                     {"order_id": o["id"]})
    o = db.row("SELECT * FROM orders WHERE id = ?", o["id"])
    return {"status": o["status"], "buyer": name, "celebrations": celebrations_for(o)}


def split_order(o: dict, gross: int, net: int) -> None:
    """PayPal's fee comes off first; then the cause share (fundraisers); the rest is the kid's save/spend/give."""
    shop = db.row("SELECT * FROM shops WHERE id = ?", o["shop_id"])
    items = db.loads(o["items"], [])
    now = time.time()
    for it in items:
        line_gross = it["unit_cents"] * it["quantity"]
        share = round(net * line_gross / gross) if gross else 0
        # the print shop is paid first: making + shipping the physical item
        share = max(0, share - catalog.PRODUCTS.get(it.get("kind"), {}).get("cost_cents", 0) * it["quantity"])
        c = db.row("SELECT maker_id, title FROM creations WHERE id = ?", it["creation_id"])
        maker = db.row("SELECT * FROM makers WHERE id = ?", c["maker_id"])
        cause = round(share * (shop["cause_pct"] or 0) / 100) if shop["kind"] == "fundraiser" else 0
        if cause:
            db.insert("ledger", {"order_id": o["id"], "shop_id": shop["id"], "maker_id": maker["id"], "bucket": "cause",
                                 "cents": cause, "note": f"{c['title']} → {shop['cause_name']}", "created": now})
        kid = share - cause
        parts = {"save": round(kid * maker["save_pct"] / 100), "give": round(kid * maker["give_pct"] / 100)}
        parts["spend"] = kid - parts["save"] - parts["give"]
        for bucket, cents in parts.items():
            if cents:
                db.insert("ledger", {"order_id": o["id"], "shop_id": shop["id"], "maker_id": maker["id"],
                                     "bucket": bucket, "cents": cents, "note": c["title"], "created": now})


def celebrations_for(o: dict) -> list[dict]:
    """What each little maker hears when their art sells (shown on the thank-you screen)."""
    out = []
    by_maker: dict[str, dict] = {}
    for l in db.rows("SELECT * FROM ledger WHERE order_id = ?", o["id"]):
        by_maker.setdefault(l["maker_id"], {"save": 0, "spend": 0, "give": 0, "cause": 0})[l["bucket"]] += l["cents"]
    for mid, b in by_maker.items():
        m = maker_with_balance(db.row("SELECT * FROM makers WHERE id = ?", mid))
        earned = b["save"] + b["spend"] + b["give"]
        goal = ""
        if m["goal_name"] and m["goal_cents"]:
            pct = min(100, round(100 * m["buckets"]["save"] / m["goal_cents"]))
            goal = f" Your {m['goal_name']} fund is {pct}% there!"
        line = (f"{m['emoji'] or '🎨'} {m['nickname']}, your art just earned {dollars(earned)}! "
                f"{dollars(b['save'])} saved, {dollars(b['spend'])} to spend, {dollars(b['give'])} to give.{goal}")
        if b["cause"]:
            line += f" Plus {dollars(b['cause'])} for the fundraiser."
        out.append({"maker": m["nickname"], "line": line, "buckets": b})
    return out


def refund_order(order_id: str, reason: str = "") -> dict:
    o = db.row("SELECT * FROM orders WHERE id = ? OR paypal_order_id = ?", order_id, order_id)
    if not o or not o["capture_id"]:
        raise HTTPException(404, "Order not found or not paid")
    r = paypal.refund_capture(o["capture_id"], note=reason or "Refund from Little Makers Market")
    reverse_ledger(o)
    if o.get("fulfillment_id") and prodigi.enabled():  # stop the print job if it hasn't shipped
        try:
            prodigi._call("POST", f"/orders/{o['fulfillment_id']}/actions/cancel")
            db.update("orders", o["id"], {"fulfillment_status": "Cancelled (refunded)"})
        except prodigi.ProdigiError as e:
            db.log_event(o["shop_id"], "print", f"Couldn't cancel the print order: {str(e)[:120]}")
    db.update("orders", o["id"], {"status": "REFUNDED"})
    return r


def reverse_ledger(o: dict) -> None:
    if db.row("SELECT id FROM ledger WHERE order_id = ? AND note LIKE 'refund:%'", o["id"]):
        return
    for l in db.rows("SELECT * FROM ledger WHERE order_id = ? AND cents > 0", o["id"]):
        db.insert("ledger", {"order_id": o["id"], "shop_id": l["shop_id"], "maker_id": l["maker_id"],
                             "bucket": l["bucket"], "cents": -l["cents"], "note": f"refund: {l['note']}", "created": time.time()})


# ------------------------------------------------------------------ Grandparent Club (Subscriptions)

def ensure_club_plan(shop: dict) -> str:
    if shop["club_plan_id"]:
        return shop["club_plan_id"]
    prod = paypal.create_product(f"{shop['name']} Grandparent Club",
                                 "A brand-new creation from your little makers every month: 3D plush, sticker and story.",
                                 home_url=f"{config.PUBLIC_URL}/shop/{shop['slug']}")
    plan = paypal.create_monthly_plan(prod["id"], f"{shop['name']} Grandparent Club", shop["club_cents"] or 900)
    db.update("shops", shop["id"], {"club_plan_id": plan["id"]})
    return plan["id"]


def record_club_join(shop: dict, subscription_id: str, name: str = "") -> dict:
    sub = paypal.get_subscription(subscription_id)
    if sub.get("plan_id") != shop["club_plan_id"]:
        raise HTTPException(400, "Subscription is for a different plan")
    if not db.row("SELECT id FROM subscriptions WHERE paypal_subscription_id = ?", subscription_id):
        subscriber = sub.get("subscriber", {}).get("name", {})
        name = name or " ".join(filter(None, [subscriber.get("given_name"), subscriber.get("surname")]))
        db.insert("subscriptions", {"id": db.new_id("sub"), "shop_id": shop["id"], "paypal_subscription_id": subscription_id,
                                    "subscriber_name": name, "status": sub.get("status"), "created": time.time()})
        db.log_event(shop["id"], "club", f"{(name or 'A new member').split(' ')[0]} joined the Grandparent Club")
    return {"status": sub.get("status")}


# ------------------------------------------------------------------ payouts (PayPal Payouts)

def pay_out_shop(shop: dict) -> dict:
    items, ledger_rows = [], []
    for m in db.rows("SELECT * FROM makers WHERE shop_id = ?", shop["id"]):
        m = maker_with_balance(m)
        if m["unpaid_cents"] >= 100 and m["payout_email"]:
            items.append({"receiver": m["payout_email"], "cents": m["unpaid_cents"], "ref": m["id"],
                          "note": f"{m['nickname']}'s art earnings from {shop['name']}. Save {m['save_pct']}% / "
                                  f"spend {m['spend_pct']}% / give {m['give_pct']}%."})
            ledger_rows.append({"maker_id": m["id"], "bucket": "payout", "cents": -m["unpaid_cents"]})
    if shop["kind"] == "fundraiser" and shop["cause_email"]:
        owed = db.row("SELECT COALESCE(SUM(cents),0) c FROM ledger WHERE shop_id = ? AND bucket IN ('cause','cause_payout')",
                      shop["id"])["c"]
        if owed >= 100:
            items.append({"receiver": shop["cause_email"], "cents": owed, "ref": f"cause-{shop['id']}",
                          "note": f"Fundraiser proceeds for {shop['cause_name']}"})
            ledger_rows.append({"maker_id": None, "bucket": "cause_payout", "cents": -owed})
    if not items:
        return {"sent": False, "reason": "Nothing to pay out yet (or missing payout emails)."}
    batch_ref = db.new_id("pay")
    res = paypal.send_payouts(batch_ref, f"Your Little Makers Market earnings from {shop['name']}", items)
    batch_id = res.get("batch_header", {}).get("payout_batch_id")
    now = time.time()
    for r in ledger_rows:
        db.insert("ledger", {"order_id": None, "shop_id": shop["id"], "note": f"payout {batch_id}", "created": now, **r})
    total = sum(i["cents"] for i in items)
    db.insert("payouts", {"id": batch_ref, "shop_id": shop["id"], "paypal_batch_id": batch_id, "items": items,
                          "status": res.get("batch_header", {}).get("batch_status"), "total_cents": total, "created": now})
    db.log_event(shop["id"], "payout", f"Paid out {dollars(total)} to {len(items)} recipient(s)")
    return {"sent": True, "batch_id": batch_id, "total_cents": total, "recipients": len(items)}


# ------------------------------------------------------------------ webhooks

def handle_webhook(event: dict) -> None:
    kind = event.get("event_type", "")
    res = event.get("resource", {})
    if kind == "PAYMENT.CAPTURE.COMPLETED":
        oid = res.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        o = db.row("SELECT * FROM orders WHERE paypal_order_id = ?", oid) if oid else None
        if o and o["status"] != "COMPLETED":  # captured elsewhere (e.g. an agent-initiated order)
            record_capture(o, paypal.get_order(oid))
    elif kind in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        cap_id = next((l["href"].rsplit("/", 1)[-1] for l in res.get("links", []) if l.get("rel") == "up"), None)
        o = db.row("SELECT * FROM orders WHERE capture_id = ?", cap_id) if cap_id else None
        if o:
            reverse_ledger(o)
            db.update("orders", o["id"], {"status": "REFUNDED"})
    elif kind.startswith("BILLING.SUBSCRIPTION."):
        sid = res.get("id")
        if sid:
            with db.tx() as con:
                con.execute("UPDATE subscriptions SET status = ? WHERE paypal_subscription_id = ?", (res.get("status"), sid))
    elif kind == "PAYMENT.SALE.COMPLETED" and res.get("billing_agreement_id"):
        sub = db.row("SELECT * FROM subscriptions WHERE paypal_subscription_id = ?", res["billing_agreement_id"])
        if sub:
            split_club_payment(sub, int(round(float(res["amount"]["total"]) * 100)))


def split_club_payment(sub: dict, cents: int) -> None:
    makers = db.rows("SELECT * FROM makers WHERE shop_id = ?", sub["shop_id"])
    if not makers:
        return
    each = cents // len(makers)
    for m in makers:
        parts = {"save": round(each * m["save_pct"] / 100), "give": round(each * m["give_pct"] / 100)}
        parts["spend"] = each - parts["save"] - parts["give"]
        for b, c in parts.items():
            db.insert("ledger", {"order_id": None, "shop_id": sub["shop_id"], "maker_id": m["id"], "bucket": b,
                                 "cents": c, "note": "Grandparent Club", "created": time.time()})
    db.log_event(sub["shop_id"], "club", f"Grandparent Club payment of {dollars(cents)} shared by {len(makers)} makers")


# ------------------------------------------------------------------ print-on-demand fulfillment (Prodigi)

def fulfill(o: dict, capture: dict) -> None:
    """Send the physical items of a paid order to the print shop. Never breaks the payment flow."""
    lines = [l for l in db.loads(o["items"], []) if catalog.PRODUCTS.get(l.get("kind"), {}).get("physical")]
    if not lines or not prodigi.enabled():
        return
    pu = (capture.get("purchase_units") or [{}])[0]
    recipient = prodigi.recipient_from_paypal(pu, capture.get("payer", {}))
    if not recipient:  # capture responses don't always echo the address; the order does
        full = paypal.get_order(o["paypal_order_id"])
        recipient = prodigi.recipient_from_paypal((full.get("purchase_units") or [{}])[0], full.get("payer", {}))
    if not recipient:
        db.update("orders", o["id"], {"fulfillment_status": "Waiting for a shipping address"})
        return
    try:
        items = []
        for l in lines:
            spec = catalog.PRODUCTS[l["kind"]]
            path = media.print_file(l["creation_id"], l["kind"])
            items.append({"reference": l["product_id"], "sku": spec["sku"], "copies": l["quantity"],
                          "attributes": spec.get("attributes"),
                          "asset_url": f"{config.PUBLIC_URL}/media/{path.relative_to(config.MEDIA_DIR).as_posix()}"})
        order = prodigi.create_order(o["id"], recipient, items)
        status = prodigi.describe(order)
        db.update("orders", o["id"], {"fulfillment_id": order["id"], "fulfillment_status": status,
                                      "ship_to": f"{recipient['address']['townOrCity']}, {recipient['address']['stateOrCounty']}"})
        db.log_event(o["shop_id"], "print", f"{len(lines)} item(s) sent to the print shop (Prodigi {order['id']})")
    except Exception as e:  # payment already succeeded; surface the problem instead of failing the request
        db.update("orders", o["id"], {"fulfillment_status": f"Print order failed: {str(e)[:120]}"})
        db.log_event(o["shop_id"], "print", "Print order failed — retry from the dashboard")


def refresh_fulfillment(prodigi_id: str) -> str | None:
    o = db.row("SELECT * FROM orders WHERE fulfillment_id = ?", prodigi_id)
    if not o or not prodigi.enabled():
        return None
    status = prodigi.describe(prodigi.get_order(prodigi_id))
    if status != o["fulfillment_status"]:
        db.update("orders", o["id"], {"fulfillment_status": status})
    return status
