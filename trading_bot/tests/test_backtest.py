"""Unit tests for the backtest engine (Milestone 4).

A deterministic ``SequenceStrategy`` returns a pre-set signal per candle, so the
engine is tested independently of any real strategy. Entry happens at the close
of the candle whose signal is BUY. No network.
"""

from __future__ import annotations

import pandas as pd
import pytest

from trading_bot.backtest import run_backtest
from trading_bot.strategy import Signal, Strategy


class SequenceStrategy(Strategy):
    """Returns signals[i] for the i-th candle (i = len(data) - 1)."""

    def __init__(self, signals):
        self._signals = signals

    @property
    def name(self) -> str:
        return "sequence"

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        return self._signals[len(data) - 1]


def _candles(rows):
    # rows: list of (high, low, close)
    return pd.DataFrame(rows, columns=["high", "low", "close"])


def _run(data, signals, **kw):
    kw.setdefault("initial_capital", 1000.0)
    kw.setdefault("stop_loss_pct", 0.10)
    kw.setdefault("take_profit_pct", 0.20)
    return run_backtest(data, SequenceStrategy(signals), **kw)


def test_take_profit_win():
    data = _candles([(100, 100, 100), (130, 95, 110), (110, 105, 108)])
    rep = _run(data, [Signal.BUY, Signal.HOLD, Signal.HOLD])
    # enter @100 (qty 10), tp=120 hit in candle 1 -> exit 120 -> equity 1200
    assert rep.num_trades == 1
    assert rep.wins == 1 and rep.losses == 0
    assert rep.final_equity == pytest.approx(1200.0)
    assert rep.total_return_pct == pytest.approx(20.0)
    assert rep.win_rate == 1.0


def test_stop_loss_loss_and_drawdown():
    data = _candles([(100, 100, 100), (105, 85, 95), (96, 94, 95)])
    rep = _run(data, [Signal.BUY, Signal.HOLD, Signal.HOLD])
    # enter @100, stop=90 hit (low 85) -> exit 90 -> equity 900
    assert rep.num_trades == 1
    assert rep.losses == 1 and rep.wins == 0
    assert rep.final_equity == pytest.approx(900.0)
    assert rep.total_return_pct == pytest.approx(-10.0)
    assert rep.max_drawdown_pct == pytest.approx(10.0)


def test_sell_signal_exit_at_close():
    data = _candles([(100, 100, 100), (105, 98, 104), (104, 103, 104)])
    rep = _run(data, [Signal.BUY, Signal.HOLD, Signal.SELL])
    # no stop/tp hit; SELL closes @104 -> equity 1040
    assert rep.num_trades == 1
    assert rep.final_equity == pytest.approx(1040.0)


def test_no_trades_all_hold():
    data = _candles([(1, 1, 1), (2, 2, 2), (3, 3, 3)])
    rep = _run(data, [Signal.HOLD, Signal.HOLD, Signal.HOLD])
    assert rep.num_trades == 0
    assert rep.win_rate == 0.0
    assert rep.final_equity == pytest.approx(1000.0)
    assert rep.max_drawdown_pct == pytest.approx(0.0)


def test_open_position_closed_at_end():
    data = _candles([(100, 100, 100), (101, 99, 100)])
    rep = _run(data, [Signal.BUY, Signal.HOLD])
    # BUY @100, no exit -> force-closed at final close 100 -> breakeven
    assert rep.num_trades == 1
    assert rep.final_equity == pytest.approx(1000.0)


def test_fee_reduces_pnl():
    data = _candles([(100, 100, 100), (130, 95, 110)])
    rep = _run(data, [Signal.BUY, Signal.HOLD], fee_pct=0.01)
    # qty = 1000*0.99/100 = 9.9 ; exit @120 -> 9.9*120*0.99 = 1176.12
    assert rep.final_equity == pytest.approx(1176.12, rel=1e-6)


def test_missing_close_raises():
    with pytest.raises(ValueError):
        run_backtest(
            pd.DataFrame({"price": [1, 2, 3]}),
            SequenceStrategy([Signal.HOLD] * 3),
            initial_capital=1000.0,
            stop_loss_pct=0.1,
            take_profit_pct=0.2,
        )
