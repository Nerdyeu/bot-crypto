"""Unit tests for the risk manager (Milestone 5) — one test per blocking rule.

No network, no exchange. Times are injected so day-rolling is deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_bot.config import RiskSettings
from trading_bot.risk import OrderRequest, OrderSide, RiskManager

DAY = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def mk_risk(**over) -> RiskSettings:
    base = dict(
        max_position_pct=0.02,
        max_daily_loss_pct=0.05,
        kill_switch_floor_pct=0.80,
        max_trades_per_day=3,
        min_balance=50.0,
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
    )
    base.update(over)
    return RiskSettings(**base)


def mk_order(qty=0.1, price=100.0, stop=98.0, side=OrderSide.BUY) -> OrderRequest:
    return OrderRequest(symbol="BTC/USDT", side=side, quantity=qty, price=price, stop_loss=stop)


def mgr(initial=1000.0, alerts=None, **over) -> RiskManager:
    return RiskManager(mk_risk(**over), initial_capital=initial, alert_hook=alerts)


def _check(m, order=None, equity=1000.0, free=1000.0, now=DAY):
    return m.check_order(order or mk_order(), equity=equity, free_balance=free, now=now)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_valid_order_allowed():
    assert _check(mgr()).allowed  # notional 10 <= 2% of 1000 = 20, stop below entry


# --------------------------------------------------------------------------- #
# One test per blocking rule
# --------------------------------------------------------------------------- #
def test_nonpositive_quantity_blocked():
    d = _check(mgr(), mk_order(qty=0))
    assert not d.allowed and d.rule == "sanity"


def test_position_size_blocked():
    d = _check(mgr(), mk_order(qty=0.5))  # notional 50 > 20
    assert not d.allowed and d.rule == "position_size"


def test_missing_stop_blocked():
    d = _check(mgr(), mk_order(stop=None))
    assert not d.allowed and d.rule == "stop_loss"


def test_stop_not_below_entry_blocked():
    d = _check(mgr(), mk_order(stop=101.0))
    assert not d.allowed and d.rule == "stop_loss"


def test_min_balance_blocked():
    d = _check(mgr(), free=10.0)
    assert not d.allowed and d.rule == "min_balance"


def test_max_trades_blocked():
    m = mgr(max_trades_per_day=3)
    for _ in range(3):
        assert _check(m).allowed
        m.register_trade()
    d = _check(m)
    assert not d.allowed and d.rule == "max_trades"


def test_daily_loss_blocked_and_alerts():
    alerts = []
    m = mgr(alerts=alerts.append, max_daily_loss_pct=0.05)
    assert _check(m, equity=1000.0).allowed          # baseline of the day = 1000
    d = _check(m, equity=940.0)                       # lost 60 > 50 (5%)
    assert not d.allowed and d.rule == "daily_loss"
    assert alerts  # alert hook fired


def test_kill_switch_engages_latches_and_alerts():
    alerts = []
    m = mgr(alerts=alerts.append, kill_switch_floor_pct=0.80)  # floor = 800
    d = _check(m, equity=750.0)
    assert not d.allowed and d.rule == "kill_switch"
    assert m.kill_switch_engaged and alerts
    # latched: still blocked even if equity recovers
    d2 = _check(m, equity=2000.0)
    assert not d2.allowed and d2.rule == "kill_switch"


# --------------------------------------------------------------------------- #
# State behaviour
# --------------------------------------------------------------------------- #
def test_new_day_resets_trade_count():
    m = mgr(max_trades_per_day=1)
    assert _check(m).allowed
    m.register_trade()
    assert not _check(m).allowed                      # maxed out today
    assert _check(m, now=DAY + timedelta(days=1)).allowed  # fresh day


def test_exit_allowed_even_when_entry_would_block():
    m = mgr()
    # oversized, no stop, zero balance — but it's an exit, so allowed
    d = _check(m, mk_order(qty=10, stop=None, side=OrderSide.SELL), free=0.0)
    assert d.allowed and d.rule == "exit"


def test_reset_kill_switch():
    m = mgr()
    _check(m, equity=10.0)  # engages
    assert m.kill_switch_engaged
    m.reset_kill_switch()
    assert not m.kill_switch_engaged
    assert _check(m, equity=1000.0).allowed
