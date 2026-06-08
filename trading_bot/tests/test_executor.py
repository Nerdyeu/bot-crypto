"""Unit tests for the executor: the four-factor live lock and LiveBroker.

No network, no real orders — the exchange is mocked.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from trading_bot.executor import (
    LiveBroker,
    LiveTradingError,
    build_live_executor,
    confirm_live_trading,
)
from trading_bot.risk import OrderSide

YES = lambda _prompt: "I UNDERSTAND"  # noqa: E731


@pytest.fixture
def live_settings(make_settings):
    return make_settings(
        trading_mode="live",
        exchange_api_key="key",
        exchange_api_secret="secret",
    )


# --------------------------------------------------------------------------- #
# The four-factor lock
# --------------------------------------------------------------------------- #
def test_confirm_success_when_all_factors_present(live_settings):
    # Should not raise.
    confirm_live_trading(live_settings, mode="live", understand_risks=True, input_fn=YES)


def test_requires_cli_mode_live(live_settings):
    with pytest.raises(LiveTradingError):
        confirm_live_trading(live_settings, mode="paper", understand_risks=True, input_fn=YES)


def test_requires_env_trading_mode_live(make_settings):
    s = make_settings(exchange_api_key="k", exchange_api_secret="s")  # trading_mode=paper
    with pytest.raises(LiveTradingError):
        confirm_live_trading(s, mode="live", understand_risks=True, input_fn=YES)


def test_requires_understand_risks_flag(live_settings):
    with pytest.raises(LiveTradingError):
        confirm_live_trading(live_settings, mode="live", understand_risks=False, input_fn=YES)


def test_requires_credentials(make_settings):
    s = make_settings(trading_mode="live")  # no keys
    with pytest.raises(LiveTradingError):
        confirm_live_trading(s, mode="live", understand_risks=True, input_fn=YES)


def test_requires_typed_confirmation(live_settings):
    with pytest.raises(LiveTradingError):
        confirm_live_trading(live_settings, mode="live", understand_risks=True,
                             input_fn=lambda _p: "nope")


# --------------------------------------------------------------------------- #
# LiveBroker (real orders, but exchange mocked)
# --------------------------------------------------------------------------- #
def test_live_broker_cash_reads_balance():
    ex = Mock()
    ex.get_free_balance.return_value = 500.0
    lb = LiveBroker(ex, "BTC/USDT", "USDT")
    assert lb.cash == 500.0
    ex.get_free_balance.assert_called_once_with("USDT")


def test_live_broker_buy_places_order_and_sets_state():
    ex = Mock()
    ex.create_market_order.return_value = {"filled": 0.1, "average": 100.0}
    lb = LiveBroker(ex, "BTC/USDT", "USDT")
    lb.buy(price=100.0, quantity=0.1, stop_loss=98.0, take_profit=104.0)
    ex.create_market_order.assert_called_once()
    symbol_arg, side_arg, amount_arg = ex.create_market_order.call_args.args
    assert symbol_arg == "BTC/USDT" and side_arg is OrderSide.BUY and amount_arg == pytest.approx(0.1)
    assert lb.in_position and lb.position_qty == pytest.approx(0.1)
    assert lb.stop_loss == 98.0 and lb.cost_basis == pytest.approx(10.0)


def test_live_broker_sell_places_order_and_resets():
    ex = Mock()
    ex.create_market_order.return_value = {"filled": 0.1, "average": 100.0}
    lb = LiveBroker(ex, "BTC/USDT", "USDT")
    lb.buy(price=100.0, quantity=0.1, stop_loss=98.0, take_profit=104.0)
    pnl = lb.sell(price=100.0)
    assert pnl == pytest.approx(0.0)
    assert not lb.in_position and lb.position_qty == 0.0
    assert ex.create_market_order.call_count == 2


def test_build_live_executor(live_settings):
    engine = build_live_executor(live_settings)
    assert engine.label == "LIVE"
    assert isinstance(engine.broker, LiveBroker)
