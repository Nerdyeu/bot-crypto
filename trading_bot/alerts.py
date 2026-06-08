"""Alerting hook — Milestone 6.

A minimal, pluggable alert sink used by the risk manager (kill-switch / daily
loss). By default an alert is just a log line (the risk manager already logs at
ERROR). If Telegram is configured (optional bonus), the message is also pushed
there — best-effort, never fatal.
"""

from __future__ import annotations

from typing import Callable

from trading_bot.config import Settings
from trading_bot.logger import get_logger

log = get_logger("alerts")


def make_alert_hook(settings: Settings) -> Callable[[str], None]:
    def hook(message: str) -> None:
        if settings.telegram_enabled:
            try:
                _send_telegram(settings, message)
                log.info("Alert pushed to Telegram.")
            except Exception as exc:  # never let alerting crash the bot
                log.warning("Telegram alert failed: %s", exc)

    return hook


def _send_telegram(settings: Settings, message: str) -> None:
    import requests  # imported lazily so the dependency is optional

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    resp = requests.post(
        url,
        data={"chat_id": settings.telegram_chat_id, "text": f"[trading_bot] {message}"},
        timeout=10,
    )
    resp.raise_for_status()
