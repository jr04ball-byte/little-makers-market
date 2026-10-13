"""Settings, loaded from environment variables or a secrets file kept outside the repo.

Lookup order for the secrets file: $LMM_SECRETS_FILE, ~/.secrets/little-makers-market.env, ./.env
Values in the secrets file win over the environment; on Render there is no file, so its env vars are used.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_file() -> None:
    candidates = [os.environ.get("LMM_SECRETS_FILE"),
                  Path.home() / ".secrets" / "little-makers-market.env",
                  ROOT / ".env"]
    for c in candidates:
        if c and Path(c).is_file():
            for line in Path(c).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"')
            return


_load_file()

PAYPAL_ENV = os.environ.get("PAYPAL_ENV", "sandbox")
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID", "")
PAYPAL_API = "https://api-m.sandbox.paypal.com" if PAYPAL_ENV == "sandbox" else "https://api-m.paypal.com"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "anthropic/claude-sonnet-5.5")
AI_FAST_MODEL = os.environ.get("AI_FAST_MODEL", "anthropic/claude-haiku-5.5")

_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")  # set automatically on Render
PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or (
    f"https://{_render_host}" if _render_host else "http://localhost:8000")
PUBLIC_URL = PUBLIC_URL.rstrip("/")
SEED_DEMO = os.environ.get("SEED_DEMO", "") == "1"  # build the demo markets on first boot
DATA_DIR = Path(os.environ.get("LMM_DATA_DIR", ROOT / "data"))
MEDIA_DIR = DATA_DIR / "media"
DB_PATH = DATA_DIR / "market.db"
CURRENCY = "USD"

DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
