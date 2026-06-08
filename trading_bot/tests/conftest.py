"""Shared pytest fixtures.

Tests must be deterministic and must NEVER touch a real exchange or the network.
The ``clean_env`` fixture guarantees configuration tests start from defaults even
if the developer has bot-related variables in their shell, and ``make_settings``
builds validated settings without reading any ``.env`` file.
"""

from __future__ import annotations

import os

import pytest

from trading_bot.config import Settings

# Env var prefixes the bot understands; cleared before every test for isolation.
_MANAGED_PREFIXES = (
    "TRADING_MODE", "EXCHANGE_", "USE_SANDBOX", "SYMBOL", "TIMEFRAME",
    "INITIAL_CAPITAL", "LOG_", "TELEGRAM_", "DATA_DIR", "RISK__", "STRATEGY__",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove any managed env vars so each test starts from known defaults."""
    for key in list(os.environ):
        if key.upper().startswith(_MANAGED_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def make_settings():
    """Factory returning validated Settings, ignoring any on-disk .env."""

    def _make(**overrides) -> Settings:
        return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]

    return _make
