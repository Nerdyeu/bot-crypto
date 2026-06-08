"""Unit tests for the read-only exchange wrapper (Milestone 2).

A ``unittest.mock.Mock`` stands in for the ccxt exchange, so these tests never
open a socket. Real ccxt exception classes are used to exercise the retry/abort
logic. ``backoff_base=0`` keeps the tests instant (no real sleeping).
"""

from __future__ import annotations

from unittest.mock import Mock

import ccxt
import pytest

from trading_bot.exchange import ExchangeClient, ExchangeClientError, Ticker


@pytest.fixture
def settings(make_settings):
    return make_settings()  # defaults: paper, sandbox on, no credentials


@pytest.fixture
def settings_creds(make_settings):
    return make_settings(exchange_api_key="key", exchange_api_secret="secret")


def _client(settings, exchange, **kw):
    kw.setdefault("backoff_base", 0.0)
    return ExchangeClient(settings, exchange=exchange, **kw)


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #
def test_get_price_returns_last(settings):
    ex = Mock()
    ex.fetch_ticker.return_value = {"last": 123.5, "bid": 123.0, "ask": 124.0, "timestamp": 111}
    client = _client(settings, ex)
    assert client.get_price() == 123.5
    ex.fetch_ticker.assert_called_once_with("BTC/USDT")  # default symbol from config


def test_fetch_ticker_is_typed(settings):
    ex = Mock()
    ex.fetch_ticker.return_value = {"last": 100, "bid": 99, "ask": 101, "timestamp": 5}
    t = _client(settings, ex).fetch_ticker("ETH/USDT")
    assert isinstance(t, Ticker)
    assert (t.symbol, t.last, t.bid, t.ask) == ("ETH/USDT", 100, 99, 101)


def test_get_price_missing_last_raises(settings):
    ex = Mock()
    ex.fetch_ticker.return_value = {"last": None}
    with pytest.raises(ExchangeClientError):
        _client(settings, ex).get_price()


def test_fetch_ohlcv_returns_dataframe(settings):
    raw = [
        [1700000000000, 1.0, 2.0, 0.5, 1.5, 10.0],
        [1700003600000, 1.5, 2.5, 1.0, 2.0, 12.0],
    ]
    ex = Mock()
    ex.fetch_ohlcv.return_value = raw
    df = _client(settings, ex).fetch_ohlcv(limit=2)

    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df.index.name == "datetime"
    assert str(df.index.tz) == "UTC"
    assert df["close"].dtype == float
    # default symbol/timeframe forwarded; ccxt order is (symbol, timeframe, since, limit)
    ex.fetch_ohlcv.assert_called_once_with("BTC/USDT", "1h", None, 2)


def test_fetch_ohlcv_empty(settings):
    ex = Mock()
    ex.fetch_ohlcv.return_value = []
    df = _client(settings, ex).fetch_ohlcv()
    assert df.empty
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


# --------------------------------------------------------------------------- #
# Account data (credential gating)
# --------------------------------------------------------------------------- #
def test_fetch_balance_requires_credentials(settings):
    ex = Mock()
    with pytest.raises(ExchangeClientError):
        _client(settings, ex).fetch_balance()
    ex.fetch_balance.assert_not_called()  # never even hit the exchange


def test_get_free_balance_with_credentials(settings_creds):
    ex = Mock()
    ex.fetch_balance.return_value = {"free": {"USDT": 250.0, "BTC": 0.01}}
    client = _client(settings_creds, ex)
    assert client.get_free_balance() == 250.0      # default quote currency (USDT)
    assert client.get_free_balance("BTC") == 0.01


# --------------------------------------------------------------------------- #
# Resilience: retry on transient errors, fail fast otherwise
# --------------------------------------------------------------------------- #
def test_network_error_then_success(settings):
    ex = Mock()
    ex.fetch_ticker.side_effect = [ccxt.NetworkError("blip"), {"last": 42}]
    client = _client(settings, ex, max_retries=3)
    assert client.get_price() == 42
    assert ex.fetch_ticker.call_count == 2


def test_network_error_exhausts_retries(settings):
    ex = Mock()
    ex.fetch_ticker.side_effect = ccxt.NetworkError("down")
    client = _client(settings, ex, max_retries=3)
    with pytest.raises(ExchangeClientError):
        client.get_price()
    assert ex.fetch_ticker.call_count == 3


def test_authentication_error_is_not_retried(settings):
    ex = Mock()
    ex.fetch_ticker.side_effect = ccxt.AuthenticationError("bad key")
    client = _client(settings, ex, max_retries=3)
    with pytest.raises(ExchangeClientError):
        client.get_price()
    assert ex.fetch_ticker.call_count == 1


def test_exchange_error_is_not_retried(settings):
    ex = Mock()
    ex.fetch_ohlcv.side_effect = ccxt.BadSymbol("nope")
    client = _client(settings, ex, max_retries=3)
    with pytest.raises(ExchangeClientError):
        client.fetch_ohlcv()
    assert ex.fetch_ohlcv.call_count == 1


def test_verify_connection(settings):
    ex = Mock()
    ex.load_markets.return_value = {"BTC/USDT": {}, "ETH/USDT": {}}
    assert _client(settings, ex).verify_connection() is True
    ex.load_markets.assert_called_once()
