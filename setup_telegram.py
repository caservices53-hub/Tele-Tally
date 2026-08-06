"""Register the Version 1.0 Telegram webhook for a deployed site."""
from __future__ import annotations

import argparse
import os
import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("origin", help="Production HTTPS origin, for example https://example.com")
    args = parser.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN first.")
    if len(secret) < 32 or not all(ch.isalnum() or ch in "_-" for ch in secret):
        raise SystemExit("TELEGRAM_WEBHOOK_SECRET must be 32+ characters using A-Z, a-z, 0-9, _ or -.")
    origin = args.origin.rstrip("/")
    if not origin.startswith("https://"):
        raise SystemExit("Telegram requires a production HTTPS origin.")
    url = f"https://api.telegram.org/bot{token}/setWebhook"
    payload = {
        "url": f"{origin}/api/telegram/webhook",
        "secret_token": secret,
        "allowed_updates": ["message", "callback_query", "my_chat_member"],
        "drop_pending_updates": False,
    }
    response = httpx.post(url, json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise SystemExit(result.get("description", "Telegram rejected the webhook."))
    print("Telegram webhook registered successfully.")


if __name__ == "__main__":
    main()
