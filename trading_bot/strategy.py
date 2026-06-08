"""Trading strategy — Milestone 3.

Pure, network-free signal generation. The V1 strategy is a simple SMA crossover:

* **BUY**  when the fast SMA crosses *above* the slow SMA,
* **SELL** when the fast SMA crosses *below* the slow SMA,
* **HOLD** otherwise (including when there is not enough data yet).

Everything here is deterministic and fully unit-testable on known data — no
exchange, no network. Strategies share a small interface (:class:`Strategy`) so
the V1 can be swapped for another later without touching the rest of the bot.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

import pandas as pd

from trading_bot.config import Settings
from trading_bot.logger import get_logger

log = get_logger("strategy")

CLOSE = "close"


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Strategy(ABC):
    """Minimal strategy interface."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """Return a trading signal for the *latest* candle in ``data``.

        ``data`` must contain a ``close`` column ordered oldest -> newest.
        """


class SmaCrossoverStrategy(Strategy):
    """Fast/slow simple-moving-average crossover."""

    def __init__(self, short_window: int, long_window: int) -> None:
        if short_window < 1 or long_window < 2:
            raise ValueError("windows must be >= 1 (short) and >= 2 (long).")
        if short_window >= long_window:
            raise ValueError(
                f"short_window ({short_window}) must be < long_window ({long_window})."
            )
        self.short_window = short_window
        self.long_window = long_window

    @property
    def name(self) -> str:
        return f"sma_crossover(short={self.short_window}, long={self.long_window})"

    def compute_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of ``data`` with ``sma_short`` / ``sma_long`` columns."""
        if CLOSE not in data.columns:
            raise ValueError(f"data must contain a '{CLOSE}' column.")
        df = data.copy()
        df["sma_short"] = df[CLOSE].rolling(self.short_window).mean()
        df["sma_long"] = df[CLOSE].rolling(self.long_window).mean()
        return df

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        # Need two consecutive candles with a fully-formed slow SMA to detect a cross.
        if len(data) < self.long_window + 1:
            return Signal.HOLD

        df = self.compute_indicators(data)
        prev, curr = df.iloc[-2], df.iloc[-1]

        if prev[["sma_short", "sma_long"]].isna().any() or curr[["sma_short", "sma_long"]].isna().any():
            return Signal.HOLD

        crossed_up = prev["sma_short"] <= prev["sma_long"] and curr["sma_short"] > curr["sma_long"]
        crossed_down = prev["sma_short"] >= prev["sma_long"] and curr["sma_short"] < curr["sma_long"]

        if crossed_up:
            return Signal.BUY
        if crossed_down:
            return Signal.SELL
        return Signal.HOLD


_STRATEGIES = {"sma_crossover": SmaCrossoverStrategy}


def build_strategy(settings: Settings) -> Strategy:
    """Construct the configured strategy from validated settings."""
    name = settings.strategy.name
    if name not in _STRATEGIES:
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {sorted(_STRATEGIES)}."
        )
    if name == "sma_crossover":
        return SmaCrossoverStrategy(
            short_window=settings.strategy.short_window,
            long_window=settings.strategy.long_window,
        )
    raise ValueError(f"Strategy '{name}' is registered but has no builder.")  # pragma: no cover
