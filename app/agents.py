"""The parent's shop assistant: Claude + PayPal Agent Toolkit tools + Little Makers Market tools.

"Send Aunt Lisa an invoice for 3 Sparky stickers", "refund yesterday's order", "pay out Mia's earnings"…
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from paypal_agent_toolkit.shared.api import PayPalAPI
from paypal_agent_toolkit.shared.configuration import Context
from paypal_agent_toolkit.shared.tools import tools as PAYPAL_TOOLS

from . import ai, config, db, money

# PayPal Agent Toolkit tools the shop assistant may use (no destructive account-level actions)
TOOLKIT_METHODS = [
    "create_invoice", "send_invoice", "send_invoice_reminder", "list_invoices", "get_invoice",
    "generate_invoice_qr_code", "cancel_sent_invoice", "list_transactions", "get_order_details",
    "list_disputes", "get_dispute", "show_subscription_details", "create_shipment_tracking", "get_shipment_tracking",
]

_toolkit: PayPalAPI | None = None


def toolkit() -> PayPalAPI:
    global _toolkit
    if _toolkit is None:
        _toolkit = PayPalAPI(client_id=config.PAYPAL_CLIENT_ID, secret=config.PAYPAL_CLIENT_SECRET,
                             context=Context(sandbox=config.PAYPAL_ENV == "sandbox", source="LITTLE-MAKERS-MARKET"))
    return _toolkit


def _fn(name: str, description: str, schema: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description[:1024], "parameters": schema}}


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


OWN_TOOLS = [
    _fn("shop_overview", "Everything about this market: makers and their save/spend/give balances, creations with "
        "product ids and prices, recent orders (with ids, buyers, status) and totals.", _schema({})),
    _fn("set_price", "Change a product's price.", _schema({"product_id": {"type": "string"},
                                                          "price_dollars": {"type": "number"}}, ["product_id", "price_dollars"])),
    _fn("create_checkout_link", "Create a PayPal checkout link for specific products that the parent can text to a "
        "relative. Returns an approve_url.", _schema({"items": {"type": "array", "items": _schema(
            {"product_id": {"type": "string"}, "quantity": {"type": "integer"}}, ["product_id"])}}, ["items"])),
    _fn("refund_order", "Fully refund a paid order through PayPal (also takes the money back out of the kid's jars).",
        _schema({"order_id": {"type": "string"}, "reason": {"type": "string"}}, ["order_id"])),
    _fn("pay_out_earnings", "Send every maker's unpaid earnings (and a fundraiser's cause share) with PayPal Payouts.",
        _schema({})),
]


def tool_specs() -> list[dict]:
    specs = list(OWN_TOOLS)
    for t in PAYPAL_TOOLS:
        if t["method"] in TOOLKIT_METHODS:
            schema = t["args_schema"].model_json_schema()
            specs.append(_fn("paypal_" + t["method"], t["description"], schema))
    return specs


def overview(shop: dict) -> dict:
    makers = [money.maker_with_balance(m) for m in db.rows("SELECT * FROM makers WHERE shop_id = ?", shop["id"])]
    creations = []
    for c in db.rows("SELECT id, title, status, maker_id FROM creations WHERE shop_id = ?", shop["id"]):
        c["products"] = db.rows("SELECT id, kind, name, price_cents FROM products WHERE creation_id = ? AND active = 1", c["id"])
        creations.append(c)
    orders = db.rows("SELECT id, paypal_order_id, total_cents, status, buyer_name, channel, agent_name, created "
                     "FROM orders WHERE shop_id = ? ORDER BY created DESC LIMIT 25", shop["id"])
    return {"shop": {k: shop[k] for k in ("name", "kind", "cause_name", "cause_pct")},
            "makers": [{k: m[k] for k in ("id", "nickname", "goal_name", "goal_cents", "buckets", "unpaid_cents", "payout_email")}
                       for m in makers],
            "creations": creations, "orders": orders, "stats": money.shop_stats(shop["id"])}


def make_executor(shop: dict):
    def execute(name: str, args: dict) -> Any:
        if name == "shop_overview":
            return overview(shop)
        if name == "set_price":
            p = db.row("SELECT p.id FROM products p JOIN creations c ON c.id = p.creation_id WHERE p.id = ? AND c.shop_id = ?",
                       args["product_id"], shop["id"])
            if not p:
                return {"error": "No such product in this shop"}
            cents = max(100, min(int(round(float(args["price_dollars"]) * 100)), 10000))
            db.update("products", p["id"], {"price_cents": cents})
            return {"ok": True, "price_cents": cents}
        if name == "create_checkout_link":
            class It:  # same shape as the checkout API's CartItem
                def __init__(self, d): self.product_id, self.quantity = d["product_id"], int(d.get("quantity") or 1)
            return money.create_checkout([It(i) for i in args["items"]], channel="assistant")
        if name == "refund_order":
            o = db.row("SELECT * FROM orders WHERE (id = ? OR paypal_order_id = ?) AND shop_id = ?",
                       args["order_id"], args["order_id"], shop["id"])
            if not o:
                return {"error": "No such order in this shop"}
            r = money.refund_order(o["id"], args.get("reason", ""))
            return {"status": r.get("status"), "refund_id": r.get("id")}
        if name == "pay_out_earnings":
            return money.pay_out_shop(shop)
        if name.startswith("paypal_"):
            return toolkit().run(name[len("paypal_"):], args)
        return {"error": f"unknown tool {name}"}
    return execute


SHOP_ASSISTANT = """You are the shop assistant for "{name}", a Little Makers Market where kids' drawings are sold as 3D plush models, stickers and prints with PayPal (sandbox).
You talk to the parent or organizer. Be brief, warm and concrete. Use tools to act — never invent ids, prices or order numbers; call shop_overview first when you need them.
Money rules: prices are in US dollars. Refunds, payouts and sending invoices move money: do them only when the parent clearly asked for that exact action.
When creating a PayPal invoice, use the product names and prices from shop_overview; include the recipient's email if given.
After acting, say what happened in one or two sentences (include links such as approve_url or invoice links when you have them)."""


def chat(shop: dict, messages: list[dict]) -> dict:
    if not messages or messages[-1].get("role") != "user":
        raise HTTPException(400, "Send the conversation ending with the user's message")
    clean = [{"role": m["role"], "content": str(m["content"])[:4000]} for m in messages[-12:] if m.get("role") in ("user", "assistant")]
    text, trace = ai.run_agent(SHOP_ASSISTANT.format(name=shop["name"]), clean, tool_specs(), make_executor(shop))
    db.log_event(shop["id"], "assistant", f"Assistant: {messages[-1]['content'][:80]}", {"tools": [t["tool"] for t in trace]})
    return {"reply": text, "trace": [{"tool": t["tool"], "args": t["args"]} for t in trace]}
