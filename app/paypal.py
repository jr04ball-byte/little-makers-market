"""Thin PayPal REST client (Orders v2, Payments, Payouts, Catalog/Subscriptions, Webhooks)."""
from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from . import config

_token: dict[str, Any] = {"value": None, "expires": 0.0}


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"PayPal API error {status}: {body}")
        self.status, self.body = status, body


def _access_token() -> str:
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    r = httpx.post(f"{config.PAYPAL_API}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                   auth=(config.PAYPAL_CLIENT_ID, config.PAYPAL_CLIENT_SECRET), timeout=30)
    if r.status_code != 200:
        raise PayPalError(r.status_code, r.text)
    d = r.json()
    _token.update(value=d["access_token"], expires=time.time() + d["expires_in"])
    return d["access_token"]


def call(method: str, path: str, json: Any = None, params: dict | None = None,
         idempotency_key: str | None = None, prefer_full: bool = True) -> Any:
    headers = {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"}
    if prefer_full:
        headers["Prefer"] = "return=representation"
    if idempotency_key:
        headers["PayPal-Request-Id"] = idempotency_key
    r = httpx.request(method, f"{config.PAYPAL_API}{path}", json=json, params=params, headers=headers, timeout=45)
    if r.status_code >= 400:
        try:
            body = r.json()
        except ValueError:
            body = r.text
        raise PayPalError(r.status_code, body)
    return r.json() if r.content else {}


def money(cents: int) -> dict:
    return {"currency_code": config.CURRENCY, "value": f"{cents / 100:.2f}"}


# ------------------------------------------------------------------ orders

def create_order(items: list[dict], *, reference_id: str, custom_id: str, description: str,
                 brand_name: str = "Little Makers Market", return_url: str | None = None,
                 cancel_url: str | None = None, shipping: bool = False) -> dict:
    """items: [{name, description, sku, unit_cents, quantity, category}] (category DIGITAL_GOODS or PHYSICAL_GOODS)."""
    total = sum(i["unit_cents"] * i["quantity"] for i in items)
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": reference_id,
            "custom_id": custom_id,
            "description": description[:127],
            "soft_descriptor": "LITTLEMAKERS",
            "amount": {**money(total), "breakdown": {"item_total": money(total)}},
            "items": [{
                "name": i["name"][:127],
                "description": (i.get("description") or "")[:127],
                "sku": (i.get("sku") or "")[:127],
                "unit_amount": money(i["unit_cents"]),
                "quantity": str(i["quantity"]),
                "category": i.get("category", "DIGITAL_GOODS"),
            } for i in items],
        }],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": brand_name[:127],
            "shipping_preference": "GET_FROM_FILE" if shipping else "NO_SHIPPING",
            "user_action": "PAY_NOW",
            **({"return_url": return_url, "cancel_url": cancel_url or return_url} if return_url else {}),
        }}},
    }
    return call("POST", "/v2/checkout/orders", body, idempotency_key=str(uuid.uuid4()))


def capture_order(order_id: str) -> dict:
    return call("POST", f"/v2/checkout/orders/{order_id}/capture", {}, idempotency_key=f"cap-{order_id}")


def get_order(order_id: str) -> dict:
    return call("GET", f"/v2/checkout/orders/{order_id}")


def approve_link(order: dict) -> str | None:
    return next((l["href"] for l in order.get("links", []) if l["rel"] in ("payer-action", "approve")), None)


def refund_capture(capture_id: str, cents: int | None = None, note: str = "") -> dict:
    body: dict = {"note_to_payer": note[:255]} if note else {}
    if cents is not None:
        body["amount"] = money(cents)
    return call("POST", f"/v2/payments/captures/{capture_id}/refund", body, idempotency_key=str(uuid.uuid4()))


# ------------------------------------------------------------------ payouts

def send_payouts(batch_id: str, subject: str, items: list[dict]) -> dict:
    """items: [{receiver (email), cents, note, ref}]"""
    body = {
        "sender_batch_header": {"sender_batch_id": batch_id, "email_subject": subject[:255],
                                "email_message": "Earnings from Little Makers Market"},
        "items": [{"recipient_type": "EMAIL", "receiver": i["receiver"],
                   "amount": {"value": f"{i['cents'] / 100:.2f}", "currency": config.CURRENCY},  # Payouts v1 uses "currency"
                   "note": i.get("note", "")[:4000], "sender_item_id": i.get("ref", "")[:63]} for i in items],
    }
    return call("POST", "/v1/payments/payouts", body, prefer_full=False)


def get_payout_batch(batch_id: str) -> dict:
    return call("GET", f"/v1/payments/payouts/{batch_id}", prefer_full=False)


# ------------------------------------------------------------------ subscriptions (Grandparent Club)

def create_product(name: str, description: str, home_url: str | None = None) -> dict:
    body = {"name": name[:127], "description": description[:256], "type": "DIGITAL", "category": "TOYS_AND_GAMES"}
    if home_url and home_url.startswith("https://"):
        body["home_url"] = home_url
    return call("POST", "/v1/catalogs/products", body, idempotency_key=str(uuid.uuid4()))


def create_monthly_plan(product_id: str, name: str, cents: int) -> dict:
    body = {
        "product_id": product_id, "name": name[:127], "status": "ACTIVE",
        "description": "A new creation from your little maker every month"[:127],
        "billing_cycles": [{"frequency": {"interval_unit": "MONTH", "interval_count": 1},
                            "tenure_type": "REGULAR", "sequence": 1, "total_cycles": 0,
                            "pricing_scheme": {"fixed_price": money(cents)}}],
        "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 2},
    }
    return call("POST", "/v1/billing/plans", body, idempotency_key=str(uuid.uuid4()))


def get_subscription(sub_id: str) -> dict:
    return call("GET", f"/v1/billing/subscriptions/{sub_id}", prefer_full=False)


# ------------------------------------------------------------------ webhooks

def verify_webhook(headers: dict, event: dict) -> bool:
    if not config.PAYPAL_WEBHOOK_ID:
        return False
    h = {k.lower(): v for k, v in headers.items()}
    body = {
        "auth_algo": h.get("paypal-auth-algo"), "cert_url": h.get("paypal-cert-url"),
        "transmission_id": h.get("paypal-transmission-id"), "transmission_sig": h.get("paypal-transmission-sig"),
        "transmission_time": h.get("paypal-transmission-time"), "webhook_id": config.PAYPAL_WEBHOOK_ID,
        "webhook_event": event,
    }
    return call("POST", "/v1/notifications/verify-webhook-signature", body, prefer_full=False).get(
        "verification_status") == "SUCCESS"
