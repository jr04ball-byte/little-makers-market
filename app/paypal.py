"""PayPal client.

Orders, captures/refunds and Subscriptions go through PayPal's official, APIMatic-generated
**PayPal Server SDK** (`paypal-server-sdk`, import `paypalserversdk`). The SDK does not cover Payouts,
Catalog Products or webhook verification, so those few calls use the REST API directly (`call`).

Every function returns the response as a plain dict of PayPal's JSON (read from the SDK's raw
`ApiResponse.text`), because SDK models drop fields they don't declare — e.g. a capture's
`seller_receivable_breakdown`, which the money split needs.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx
from apimatic_core.exceptions.auth_validation_exception import AuthValidationException
from paypalserversdk.api_helper import APIHelper
from paypalserversdk.configuration import Environment
from paypalserversdk.exceptions.api_exception import ApiException
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.models.amount_breakdown import AmountBreakdown
from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
from paypalserversdk.models.billing_cycle import BillingCycle
from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
from paypalserversdk.models.frequency import Frequency
from paypalserversdk.models.item import Item
from paypalserversdk.models.item_category import ItemCategory
from paypalserversdk.models.money import Money
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.models.payment_preferences import PaymentPreferences
from paypalserversdk.models.payment_source import PaymentSource
from paypalserversdk.models.paypal_experience_user_action import PaypalExperienceUserAction
from paypalserversdk.models.paypal_wallet import PaypalWallet
from paypalserversdk.models.paypal_wallet_context_shipping_preference import PaypalWalletContextShippingPreference
from paypalserversdk.models.paypal_wallet_experience_context import PaypalWalletExperienceContext
from paypalserversdk.models.plan_request import PlanRequest
from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest
from paypalserversdk.models.refund_request import RefundRequest
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

from . import config


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"PayPal API error {status}: {body}")
        self.status, self.body = status, body


# ------------------------------------------------------------------ PayPal Server SDK client (built once, reused)

_sdk: PaypalServersdkClient | None = None


def sdk() -> PaypalServersdkClient:
    global _sdk
    if _sdk is None:
        _sdk = PaypalServersdkClient(
            client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
                o_auth_client_id=config.PAYPAL_CLIENT_ID, o_auth_client_secret=config.PAYPAL_CLIENT_SECRET),
            # never rely on the generated default environment; choose it explicitly
            environment=Environment.PRODUCTION if config.PAYPAL_ENV == "live" else Environment.SANDBOX,
            timeout=30,
            # SDK defaults: retries off; when on, only GET/PUT are retried. Our POSTs carry
            # PayPal-Request-Id so a retried POST cannot double-charge.
            max_retries=2,
        )
    return _sdk


def _run(fn, options: dict) -> dict:
    """Call an SDK operation (options-dict shape) and return PayPal's raw JSON as a dict."""
    try:
        result = fn(options)
    except ApiException as e:  # typed ErrorException is a subclass; we only need status + body
        try:
            body = json.loads(e.response.text) if e.response and e.response.text else e.reason
        except ValueError:
            body = e.response.text
        raise PayPalError(e.response_code, body) from None
    except AuthValidationException as e:  # credentials rejected before any request was sent
        raise PayPalError(401, str(e)) from None
    return json.loads(result.text) if result.text else {}


def _money(cents: int) -> Money:
    return Money(currency_code=config.CURRENCY, value=f"{cents / 100:.2f}")


# ------------------------------------------------------------------ orders (SDK: OrdersController)

def create_order(items: list[dict], *, reference_id: str, custom_id: str, description: str,
                 brand_name: str = "Little Makers Market", return_url: str | None = None,
                 cancel_url: str | None = None, shipping: bool = False) -> dict:
    """items: [{name, description, sku, unit_cents, quantity, category}] (category DIGITAL_GOODS or PHYSICAL_GOODS)."""
    total = sum(i["unit_cents"] * i["quantity"] for i in items)
    experience = dict(
        brand_name=brand_name[:127],
        # the SDK's model defaults are GET_FROM_FILE / CONTINUE; set what we actually want
        shipping_preference=(PaypalWalletContextShippingPreference.GET_FROM_FILE if shipping
                             else PaypalWalletContextShippingPreference.NO_SHIPPING),
        user_action=PaypalExperienceUserAction.PAY_NOW,
    )
    if return_url:
        experience.update(return_url=return_url, cancel_url=cancel_url or return_url)
    body = OrderRequest(
        intent=CheckoutPaymentIntent.CAPTURE,
        purchase_units=[PurchaseUnitRequest(
            reference_id=reference_id,
            custom_id=custom_id,
            description=description[:127],
            soft_descriptor="LITTLEMAKERS",
            amount=AmountWithBreakdown(currency_code=config.CURRENCY, value=f"{total / 100:.2f}",
                                       breakdown=AmountBreakdown(item_total=_money(total))),
            items=[Item(
                name=i["name"][:127],
                unit_amount=_money(i["unit_cents"]),
                quantity=str(i["quantity"]),
                description=(i.get("description") or "")[:127],
                sku=(i.get("sku") or "")[:127],
                category=ItemCategory.PHYSICAL_GOODS if i.get("category") == "PHYSICAL_GOODS" else ItemCategory.DIGITAL_GOODS,
            ) for i in items],
        )],
        payment_source=PaymentSource(paypal=PaypalWallet(experience_context=PaypalWalletExperienceContext(**experience))),
    )
    return _run(sdk().orders.create_order, {"body": body, "paypal_request_id": str(uuid.uuid4()),
                                            "prefer": "return=representation"})


def capture_order(order_id: str) -> dict:
    return _run(sdk().orders.capture_order, {"id": order_id, "paypal_request_id": f"cap-{order_id}",
                                             "prefer": "return=representation"})


def get_order(order_id: str) -> dict:
    return _run(sdk().orders.get_order, {"id": order_id})


def approve_link(order: dict) -> str | None:
    return next((l["href"] for l in order.get("links", []) if l["rel"] in ("payer-action", "approve")), None)


# ------------------------------------------------------------------ refunds (SDK: PaymentsController)

def refund_capture(capture_id: str, cents: int | None = None, note: str = "") -> dict:
    body = RefundRequest(**({"note_to_payer": note[:255]} if note else {}),
                         **({"amount": _money(cents)} if cents is not None else {}))
    return _run(sdk().payments.refund_captured_payment, {"capture_id": capture_id, "body": body,
                                                         "paypal_request_id": str(uuid.uuid4()),
                                                         "prefer": "return=representation"})


# ------------------------------------------------------------------ subscriptions (SDK: SubscriptionsController)

def create_monthly_plan(product_id: str, name: str, cents: int) -> dict:
    body = PlanRequest(
        product_id=product_id, name=name[:127], status="ACTIVE",
        description="A new creation from your little maker every month"[:127],
        billing_cycles=[BillingCycle(tenure_type="REGULAR", sequence=1, total_cycles=0,
                                     frequency=Frequency(interval_unit="MONTH", interval_count=1))],
        payment_preferences=PaymentPreferences(auto_bill_outstanding=True, payment_failure_threshold=2),
    )
    # SDK 2.4.0's PricingScheme model emits pricing_model/price, but the live Subscriptions API rejects
    # pricing_model=FIXED and requires fixed_price. Serialize the model and add the field the API expects.
    payload = json.loads(APIHelper.json_serialize(body))
    payload["billing_cycles"][0]["pricing_scheme"] = {"fixed_price": money(cents)}
    return _run(sdk().subscriptions.create_billing_plan, {"body": payload, "paypal_request_id": str(uuid.uuid4()),
                                                          "prefer": "return=representation"})


def get_subscription(sub_id: str) -> dict:
    return _run(sdk().subscriptions.get_subscription, {"id": sub_id})


# ------------------------------------------------------------------ REST for what the SDK doesn't cover

_token: dict[str, Any] = {"value": None, "expires": 0.0}


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


def send_payouts(batch_id: str, subject: str, items: list[dict]) -> dict:
    """Payouts API. items: [{receiver (email), cents, note, ref}]"""
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


def create_product(name: str, description: str, home_url: str | None = None) -> dict:
    """Catalog Products API (needed before a subscription plan)."""
    body = {"name": name[:127], "description": description[:256], "type": "DIGITAL", "category": "TOYS_AND_GAMES"}
    if home_url and home_url.startswith("https://"):
        body["home_url"] = home_url
    return call("POST", "/v1/catalogs/products", body, idempotency_key=str(uuid.uuid4()))


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
