# Little Makers Market

**Kids' drawings become plush 3D toys, stickers and prints that family can buy with PayPal — and AI agents can buy too.**

An AI maker agent turns one photo of a child's drawing into a complete PayPal shop in about a minute: it reads the drawing, asks the young artist two questions, keeps every quirk (three legs stay three legs), inflates the drawing into a printable plush 3D model, writes the listing and story, and opens checkout. Every sale is split automatically into the kid's **save / spend / give** jars — or shared with a church, school or team fundraiser.

> Work in progress for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/). Full setup, demo and architecture docs coming before submission.

## Quick start (sandbox)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
.venv/Scripts/pip install --no-deps paypal-agent-toolkit==1.11.0   # core toolkit only (skips its LangChain/CrewAI extras)
cp .env.example .env                             # add PayPal sandbox + OpenRouter keys
.venv/Scripts/python -m app.seed                 # optional: two demo markets (uses the AI, ~10 cents)
.venv/Scripts/python -m uvicorn app.main:app --reload
```

## How PayPal is used

| PayPal capability | Where | How |
| --- | --- | --- |
| Orders v2 (create, get, capture) | `app/paypal.py`, `web/art.html` | **PayPal Server SDK** (`paypal-server-sdk`, APIMatic-generated) + JS SDK buttons with PayPal, Venmo and Pay Later |
| Refunds | `app/paypal.py` | PayPal Server SDK (`PaymentsController`) |
| Subscriptions — Grandparent Club | `app/paypal.py`, `web/shop.html` | PayPal Server SDK (`SubscriptionsController`) + JS SDK subscription buttons |
| Payouts — kids' earnings and fundraiser causes | `app/money.py` | Payouts REST API (not in the Server SDK) |
| Invoicing, transactions, disputes, shipment tracking | `app/agents.py` | **PayPal Agent Toolkit** tools called by the AI shop assistant |
| Webhooks | `app/main.py`, `app/money.py` | signature verification + capture/refund/subscription events |

### Built with the APIMatic PayPal Context Plugin

The PayPal integration was written in Claude Code with APIMatic's
[PayPal Server SDK Context Plugin](https://github.com/paypaldev/server-sdk-context-plugin-preview)
(`npx context-plugins install https://github.com/paypaldev/server-sdk-context-plugin-preview`).
Following its Python skills we: pinned the SDK (`paypal-server-sdk==2.4.0`), built one long-lived
`PaypalServersdkClient` with an explicit environment, used the options-dict call shape, set the
experience-context fields whose generated defaults differ from what we need (`PAY_NOW`,
`NO_SHIPPING`), mapped `ApiException`/`AuthValidationException` separately, read raw `ApiResponse.text` so
fields the models don't declare (a capture's `seller_receivable_breakdown`) survive, and tested through
the SDK's `http_client_instance` + `http_call_back` seams (`tests/test_paypal_sdk.py`).

Finding along the way: in SDK 2.4.0 the `PricingScheme` model emits `pricing_model`/`price`, which the
live Subscriptions API rejects (it requires `fixed_price`); `create_monthly_plan` builds the plan with
the SDK models and patches that one field.

## Tests

```bash
.venv/Scripts/python -m pytest -q      # offline: SDK request shapes, error mapping, money split
```

## License

MIT
