"""Unit tests for paper trading (Milestone 6). No network — exchange is mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import pandas as pd
import pytest

from trading_bot.paper import PaperBroker, PaperTrader
from trading_bot.risk import RiskManager
from trading_bot.strategy import Signal, Strategy

DAY = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class FixedSignal(Strategy):
    def __init__(self, signal):
        self.signal = signal

    @property
    def name(self):
        return "fixed"

    def generate_signal(self, data):
        return self.signal


# --------------------------------------------------------------------------- #
# PaperBroker
# --------------------------------------------------------------------------- #
def test_broker_buy_sell_cycle():
    b = PaperBroker(initial_cash=1000.0)
    b.buy(price=100.0, quantity=2.0, stop_loss=90.0, take_profit=120.0)
    assert b.in_position
    assert b.cash == pytest.approx(800.0)
    assert b.equity(100.0) == pytest.approx(1000.0)
    pnl = b.sell(price=110.0)
    assert pnl == pytest.approx(20.0)
    assert not b.in_position
    assert b.cash == pytest.approx(1020.0)
    assert b.trade_pnls == [pytest.approx(20.0)]


def test_broker_fee_applied():
    b = PaperBroker(initial_cash=1000.0, fee_pct=0.01)
    b.buy(price=100.0, quantity=2.0, stop_loss=90.0, take_profit=120.0)
    # cost 200 + fee 2 = 202 spent
    assert b.cash == pytest.approx(798.0)


def test_broker_rejects_overspend():
    b = PaperBroker(initial_cash=100.0)
    with pytest.raises(ValueError):
        b.buy(price=100.0, quantity=2.0, stop_loss=90.0, take_profit=120.0)


# --------------------------------------------------------------------------- #
# PaperTrader.step
# --------------------------------------------------------------------------- #
def _df(price):
    return pd.DataFrame({"close": [price] * 60})


def _trader(signal, broker, settings, price):
    ex = Mock()
    ex.fetch_ohlcv.return_value = _df(price)
    risk = RiskManager(settings.risk, settings.initial_capital)
    return PaperTrader(settings, ex, FixedSignal(signal), risk, broker)


def test_step_buys_on_signal(make_settings):
    s = make_settings()
    broker = PaperBroker(initial_cash=1000.0)
    res = _trader(Signal.BUY, broker, s, price=100.0).step(now=DAY)
    assert res["action"] == "buy"
    assert broker.in_position
    # default risk: 2% of 1000 = 20 notional -> qty 0.2 @ 100
    assert broker.position_qty == pytest.approx(0.2)


def test_step_exits_on_take_profit(make_settings):
    s = make_settings()
    broker = PaperBroker(initial_cash=1000.0)
    broker.buy(price=100.0, quantity=0.2, stop_loss=98.0, take_profit=104.0)
    res = _trader(Signal.HOLD, broker, s, price=104.0).step(now=DAY)
    assert res["action"] == "sell" and res["reason"] == "take_profit"
    assert not broker.in_position


def test_step_exits_on_stop_loss(make_settings):
    s = make_settings()
    broker = PaperBroker(initial_cash=1000.0)
    broker.buy(price=100.0, quantity=0.2, stop_loss=98.0, take_profit=104.0)
    res = _trader(Signal.HOLD, broker, s, price=97.0).step(now=DAY)
    assert res["action"] == "sell" and res["reason"] == "stop_loss"


def test_step_exits_on_sell_signal(make_settings):
    s = make_settings()
    broker = PaperBroker(initial_cash=1000.0)
    broker.buy(price=100.0, quantity=0.2, stop_loss=98.0, take_profit=104.0)
    res = _trader(Signal.SELL, broker, s, price=101.0).step(now=DAY)
    assert res["action"] == "sell" and res["reason"] == "signal"


def test_step_blocked_when_kill_switch(make_settings):
    s = make_settings()
    broker = PaperBroker(initial_cash=1000.0)
    trader = _trader(Signal.BUY, broker, s, price=100.0)
    trader.risk.kill_switch_engaged = True
    res = trader.step(now=DAY)
    assert res["action"] == "blocked" and res["rule"] == "kill_switch"
    assert not broker.in_position


def test_step_hold_on_empty_data(make_settings):
    s = make_settings()
    ex = Mock()
    ex.fetch_ohlcv.return_value = pd.DataFrame({"close": []})
    risk = RiskManager(s.risk, s.initial_capital)
    res = PaperTrader(s, ex, FixedSignal(Signal.BUY), risk, PaperBroker(1000.0)).step(now=DAY)
    assert res["action"] == "hold" and res["reason"] == "no_data"
