"""Offline tests for app/paypal.py's PayPal Server SDK usage.

Pattern from the APIMatic PayPal Server SDK context plugin (python-testing): hand the SDK our own
requests.Session with a stub adapter (routed by URL, so the OAuth token request succeeds) and assert the
outgoing request through an HttpCallBack catcher. The SDK's own serialization and error mapping still run.
"""
import json

import pytest
import requests
from requests.adapters import HTTPAdapter
from requests.models import Response

from paypalserversdk.configuration import Environment
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.http.http_call_back import HttpCallBack
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

from app import paypal

TOKEN_PATH = "/v1/oauth2/token"  # from OAuthAuthorizationController's request builder


class Catcher(HttpCallBack):
    """Keeps every request: the token POST also passes through the callback."""

    def __init__(self):
        self.requests = []

    def on_before_request(self, request):
        self.requests.append(request)

    def on_after_response(self, response):
        pass

    def last(self, path_part):
        return next(r for r in reversed(self.requests) if path_part in r.query_url)


class StubAdapter(HTTPAdapter):
    def __init__(self, routes):
        super().__init__()
        self.routes = routes  # [(path_part, status, body)]

    def send(self, request, **kwargs):
        r = Response()
        r.request, r.url = request, request.url
        r.headers["Content-Type"] = "application/json"
        if TOKEN_PATH in request.url:
            r.status_code = 200
            r._content = json.dumps({"access_token": "test-token", "token_type": "Bearer", "expires_in": 3600}).encode()
            return r
        for part, status, body in self.routes:
            if part in request.url:
                r.status_code, r._content = status, json.dumps(body).encode()
                return r
        r.status_code, r._content = 404, b'{"name": "RESOURCE_NOT_FOUND"}'
        return r


@pytest.fixture
def stub(monkeypatch):
    def make(*routes):
        session = requests.Session()
        session.mount("https://", StubAdapter(list(routes)))
        catcher = Catcher()
        client = PaypalServersdkClient(
            client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
                o_auth_client_id="id", o_auth_client_secret="secret"),
            environment=Environment.SANDBOX, http_client_instance=session, http_call_back=catcher, max_retries=0)
        monkeypatch.setattr(paypal, "_sdk", client)
        return catcher
    return make


def test_create_order_sends_pay_now_without_shipping_for_digital_goods(stub):
    catcher = stub(("/v2/checkout/orders", 200, {"id": "ORDER1", "status": "PAYER_ACTION_REQUIRED",
                                                 "links": [{"rel": "payer-action", "href": "https://pay"}]}))
    order = paypal.create_order(
        [{"name": "Sparky 3D plush", "unit_cents": 500, "quantity": 2, "sku": "p1", "description": None}],
        reference_id="shop1", custom_id="ord1", description="Test", return_url="http://localhost/thanks")
    assert order["id"] == "ORDER1" and paypal.approve_link(order) == "https://pay"

    req = catcher.last("/v2/checkout/orders")
    assert req.http_method == "POST"
    assert req.headers.get("PayPal-Request-Id")  # idempotency key on every create
    body = json.loads(req.parameters)
    unit = body["purchase_units"][0]
    assert body["intent"] == "CAPTURE"
    assert unit["amount"] == {"currency_code": "USD", "value": "10.00",
                              "breakdown": {"item_total": {"currency_code": "USD", "value": "10.00"}}}
    assert unit["items"][0]["category"] == "DIGITAL_GOODS" and unit["items"][0]["quantity"] == "2"
    ctx = body["payment_source"]["paypal"]["experience_context"]
    assert ctx["user_action"] == "PAY_NOW"          # SDK default would be CONTINUE
    assert ctx["shipping_preference"] == "NO_SHIPPING"  # SDK default would be GET_FROM_FILE


def test_capture_error_becomes_paypal_error_with_parsed_body(stub):
    stub(("/capture", 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_NOT_APPROVED"}]}))
    with pytest.raises(paypal.PayPalError) as e:
        paypal.capture_order("ORDER1")
    assert e.value.status == 422
    assert e.value.body["details"][0]["issue"] == "ORDER_NOT_APPROVED"


def test_capture_keeps_fields_the_sdk_model_would_drop(stub):
    stub(("/capture", 201, {"id": "ORDER1", "status": "COMPLETED", "purchase_units": [{"payments": {"captures": [
        {"id": "CAP1", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "10.00"},
         "seller_receivable_breakdown": {"net_amount": {"currency_code": "USD", "value": "9.21"}}}]}}]}))
    res = paypal.capture_order("ORDER1")
    cap = res["purchase_units"][0]["payments"]["captures"][0]
    assert cap["seller_receivable_breakdown"]["net_amount"]["value"] == "9.21"


def test_monthly_plan_uses_fixed_price(stub):
    catcher = stub(("/v1/billing/plans", 201, {"id": "P-1", "status": "ACTIVE"}))
    assert paypal.create_monthly_plan("PROD-1", "Club", 900)["id"] == "P-1"
    scheme = json.loads(catcher.last("/v1/billing/plans").parameters)["billing_cycles"][0]["pricing_scheme"]
    assert scheme == {"fixed_price": {"currency_code": "USD", "value": "9.00"}}


def test_refund_sends_amount_and_note(stub):
    catcher = stub(("/refund", 201, {"id": "R1", "status": "COMPLETED"}))
    assert paypal.refund_capture("CAP1", 400, "sorry")["status"] == "COMPLETED"
    body = json.loads(catcher.last("/v2/payments/captures/CAP1/refund").parameters)
    assert body == {"amount": {"currency_code": "USD", "value": "4.00"}, "note_to_payer": "sorry"}
