"""Unit tests for the SMA-crossover strategy (Milestone 3).

Hand-picked close series (short=2, long=3) make each cross deterministic.
No network, no exchange.
"""

from __future__ import annotations

import pandas as pd
import pytest

from trading_bot.strategy import Signal, SmaCrossoverStrategy, build_strategy


def _df(closes):
    return pd.DataFrame({"close": closes})


@pytest.fixture
def strat():
    return SmaCrossoverStrategy(short_window=2, long_window=3)


def test_buy_on_cross_up(strat):
    # fast SMA crosses above slow SMA on the last candle
    assert strat.generate_signal(_df([10, 8, 6, 4, 5, 14])) is Signal.BUY


def test_sell_on_cross_down(strat):
    assert strat.generate_signal(_df([10, 12, 14, 16, 15, 6])) is Signal.SELL


def test_hold_when_trend_continues(strat):
    # steady uptrend: fast stays above slow, no crossing -> HOLD
    assert strat.generate_signal(_df([1, 2, 3, 4, 5, 6])) is Signal.HOLD


def test_hold_when_not_enough_data(strat):
    assert strat.generate_signal(_df([1, 2, 3])) is Signal.HOLD


def test_missing_close_column_raises(strat):
    with pytest.raises(ValueError):
        strat.generate_signal(pd.DataFrame({"price": [1, 2, 3, 4]}))


def test_indicators_columns(strat):
    out = strat.compute_indicators(_df([1, 2, 3, 4, 5]))
    assert {"sma_short", "sma_long"}.issubset(out.columns)
    # last fast SMA = mean(4,5)=4.5 ; last slow SMA = mean(3,4,5)=4.0
    assert out["sma_short"].iloc[-1] == 4.5
    assert out["sma_long"].iloc[-1] == 4.0


def test_invalid_windows_raise():
    with pytest.raises(ValueError):
        SmaCrossoverStrategy(short_window=5, long_window=3)


def test_build_strategy_from_settings(make_settings):
    s = make_settings()  # defaults: sma_crossover, 20/50
    strategy = build_strategy(s)
    assert isinstance(strategy, SmaCrossoverStrategy)
    assert (strategy.short_window, strategy.long_window) == (20, 50)


def test_build_unknown_strategy_raises(make_settings):
    s = make_settings(strategy={"name": "magic", "short_window": 2, "long_window": 3})
    with pytest.raises(ValueError):
        build_strategy(s)
