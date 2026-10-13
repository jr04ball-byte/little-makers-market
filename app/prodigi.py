"""Prodigi Print API v4 client — prints and ships the physical products (sandbox in this demo:
orders are accepted and tracked but never charged, printed or shipped)."""
from __future__ import annotations

import os

import httpx

from . import config

API_KEY = os.environ.get("PRODIGI_API_KEY", "")
BASE = "https://api.prodigi.com/v4.0" if os.environ.get("PRODIGI_ENV") == "live" else "https://api.sandbox.prodigi.com/v4.0"


class ProdigiError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(API_KEY)


def _call(method: str, path: str, json: dict | None = None) -> dict:
    r = httpx.request(method, BASE + path, json=json, headers={"X-API-Key": API_KEY}, timeout=45)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text}
    if r.status_code >= 400:
        raise ProdigiError(f"Prodigi {r.status_code}: {body}")
    return body


def recipient_from_paypal(pu: dict, payer: dict) -> dict | None:
    """Build a Prodigi recipient from the PayPal purchase unit's shipping address."""
    ship = pu.get("shipping") or {}
    a = ship.get("address") or {}
    if not a.get("address_line_1"):
        return None
    name = (ship.get("name") or {}).get("full_name") or " ".join(
        filter(None, [payer.get("name", {}).get("given_name"), payer.get("name", {}).get("surname")])) or "Customer"
    return {"name": name, "email": payer.get("email_address"),
            "address": {"line1": a.get("address_line_1"), "line2": a.get("address_line_2"),
                        "townOrCity": a.get("admin_area_2"), "stateOrCounty": a.get("admin_area_1"),
                        "postalOrZipCode": a.get("postal_code"), "countryCode": a.get("country_code", "US")}}


def create_order(reference: str, recipient: dict, items: list[dict]) -> dict:
    """items: [{reference, sku, copies, attributes, asset_url}] -> Prodigi order dict."""
    body = {
        "merchantReference": reference,
        "idempotencyKey": reference,  # a retried capture/webhook can't create a second print order
        "shippingMethod": "Budget",
        "recipient": recipient,
        "items": [{"merchantReference": i["reference"], "sku": i["sku"], "copies": i["copies"], "sizing": "fillPrintArea",
                   "attributes": i.get("attributes") or {}, "assets": [{"printArea": "default", "url": i["asset_url"]}]}
                  for i in items],
        "metadata": {"source": "Little Makers Market"},
    }
    if config.PUBLIC_URL.startswith("https://"):
        body["callbackUrl"] = f"{config.PUBLIC_URL}/api/prodigi/callback"
    return _call("POST", "/orders", body)["order"]


def get_order(order_id: str) -> dict:
    return _call("GET", f"/orders/{order_id}")["order"]


def describe(order: dict) -> str:
    """One friendly line for the dashboard."""
    st = order.get("status", {})
    stage = st.get("stage", "?")
    issues = st.get("issues") or []
    if issues:
        return f"{stage} — needs attention: {issues[0].get('errorCode', 'issue')}"
    shipped = [s for s in order.get("shipments", []) if s.get("tracking", {}).get("url")]
    if shipped:
        return f"Shipped — tracking {shipped[0]['tracking'].get('number', '')}"
    return {"InProgress": "Sent to the print shop", "Complete": "Shipped", "Cancelled": "Cancelled"}.get(stage, stage)
