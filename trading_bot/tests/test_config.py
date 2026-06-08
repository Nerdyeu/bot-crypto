"""Unit tests for configuration loading & validation (Milestone 1).

These tests never touch the network or a real exchange. They drive
``load_settings(env_file=None)`` so a developer's local ``.env`` cannot leak in.
"""

from __future__ import annotations

import pytest

from trading_bot.config import ConfigError, load_settings

# Env isolation (clean_env) is provided by the shared conftest.py fixture.


def _load():
    # env_file=None => ignore any .env on disk, read process env only.
    return load_settings(env_file=None)


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
def test_defaults_are_safe():
    s = _load()
    assert s.trading_mode == "paper"          # never live by default
    assert s.exchange_id == "binance"
    assert s.use_sandbox is True
    assert s.symbol == "BTC/USDT"
    assert s.timeframe == "1h"
    assert s.initial_capital == 1000.0
    assert s.has_credentials is False
    # Risk defaults match the documented values.
    assert s.risk.max_position_pct == 0.02
    assert s.risk.max_daily_loss_pct == 0.05
    assert s.risk.kill_switch_floor_pct == 0.80
    assert s.risk.max_trades_per_day == 10
    assert s.risk.stop_loss_pct == 0.02


def test_derived_currencies():
    s = _load()
    assert s.base_currency == "BTC"
    assert s.quote_currency == "USDT"


# --------------------------------------------------------------------------- #
# Environment overrides (including nested with __ delimiter)
# --------------------------------------------------------------------------- #
def test_env_overrides(monkeypatch):
    monkeypatch.setenv("EXCHANGE_ID", "Kraken")          # normalised to lower
    monkeypatch.setenv("SYMBOL", "eth/usdt")             # normalised to upper
    monkeypatch.setenv("INITIAL_CAPITAL", "2500")
    monkeypatch.setenv("USE_SANDBOX", "false")
    monkeypatch.setenv("RISK__MAX_POSITION_PCT", "0.01")
    monkeypatch.setenv("STRATEGY__SHORT_WINDOW", "10")
    monkeypatch.setenv("STRATEGY__LONG_WINDOW", "30")

    s = _load()
    assert s.exchange_id == "kraken"
    assert s.symbol == "ETH/USDT"
    assert s.initial_capital == 2500.0
    assert s.use_sandbox is False
    assert s.risk.max_position_pct == 0.01
    assert s.strategy.short_window == 10
    assert s.strategy.long_window == 30


# --------------------------------------------------------------------------- #
# Validation failures
# --------------------------------------------------------------------------- #
def test_invalid_symbol_raises(monkeypatch):
    monkeypatch.setenv("SYMBOL", "BTCUSDT")  # missing the '/'
    with pytest.raises(ConfigError):
        _load()


def test_invalid_timeframe_raises(monkeypatch):
    monkeypatch.setenv("TIMEFRAME", "1hour")
    with pytest.raises(ConfigError):
        _load()


def test_invalid_log_level_raises(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    with pytest.raises(ConfigError):
        _load()


def test_invalid_trading_mode_raises(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "yolo")
    with pytest.raises(ConfigError):
        _load()


def test_position_pct_out_of_range_raises(monkeypatch):
    monkeypatch.setenv("RISK__MAX_POSITION_PCT", "2")  # > 100%
    with pytest.raises(ConfigError):
        _load()


def test_negative_capital_raises(monkeypatch):
    monkeypatch.setenv("INITIAL_CAPITAL", "-5")
    with pytest.raises(ConfigError):
        _load()


def test_strategy_windows_must_be_ordered(monkeypatch):
    monkeypatch.setenv("STRATEGY__SHORT_WINDOW", "50")
    monkeypatch.setenv("STRATEGY__LONG_WINDOW", "20")
    with pytest.raises(ConfigError):
        _load()


# --------------------------------------------------------------------------- #
# Live-credentials gate
# --------------------------------------------------------------------------- #
def test_live_without_credentials_raises(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    s = _load()  # loading is fine; the *gate* is explicit.
    with pytest.raises(ConfigError):
        s.require_live_credentials()


def test_live_with_credentials_ok(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("EXCHANGE_API_KEY", "abc123")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "secret999")
    s = _load()
    assert s.has_credentials is True
    s.require_live_credentials()  # must not raise


# --------------------------------------------------------------------------- #
# Secret hygiene
# --------------------------------------------------------------------------- #
def test_safe_summary_masks_secrets(monkeypatch):
    monkeypatch.setenv("EXCHANGE_API_KEY", "supersecretkey")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "supersecretsecret")
    s = _load()
    summary = s.safe_summary()
    rendered = str(summary)
    assert "supersecretkey" not in rendered
    assert "supersecretsecret" not in rendered
    assert summary["api_key"].startswith("set")
