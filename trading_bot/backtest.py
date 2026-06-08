"""Backtesting — Milestone 4.

Replay historical OHLCV data through a strategy with NO trading connection and
produce a report: total return, max drawdown, number of trades, win rate.

Simulation model (intentionally simple and transparent, V1):
    * long-only, spot, all-in (one position at a time),
    * enter at the candle close on a BUY signal,
    * each position carries a stop-loss and take-profit (from risk config),
    * exits are checked intrabar using the candle high/low; if both the stop and
      the take-profit fall inside the same candle we assume the **stop** is hit
      first (worst case),
    * a SELL signal closes the position at the candle close,
    * optional flat per-trade fee.

This is for evaluation only — it never touches the network or an exchange.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from trading_bot.logger import get_logger
from trading_bot.strategy import Signal, Strategy

log = get_logger("backtest")


@dataclass
class BacktestReport:
    initial_equity: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    num_trades: int
    wins: int
    losses: int
    win_rate: float  # fraction in [0, 1]
    trade_pnls: List[float] = field(default_factory=list)

    def summary(self) -> str:
        from trading_bot import ui

        arrow = "▲" if self.total_return_pct >= 0 else "▼"
        rows = [
            ("Capital initial", ui.money(self.initial_equity)),
            ("Capital final", ui.money(self.final_equity)),
            ("Performance", f"{ui.pct(self.total_return_pct, sign=True)}   {arrow}"),
            ("Drawdown max", ui.pct(self.max_drawdown_pct)),
            ("Trades", f"{self.num_trades}   ({self.wins} gagnés / {self.losses} perdus)"),
            ("Taux de réussite", ui.pct(self.win_rate * 100)),
        ]
        return ui.block("RÉSULTAT DU BACKTEST", rows)


def load_ohlcv_csv(path: str) -> pd.DataFrame:
    """Load an OHLCV CSV. Requires at least a ``close`` column (case-insensitive)."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    if "close" not in df.columns:
        raise ValueError(f"CSV {path!r} must contain a 'close' column. Found: {list(df.columns)}")
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
        df = df.set_index("datetime")
    elif "timestamp" in df.columns:
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True, errors="coerce")
        df = df.set_index("datetime")
    return df


def run_backtest(
    data: pd.DataFrame,
    strategy: Strategy,
    *,
    initial_capital: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    fee_pct: float = 0.0,
) -> BacktestReport:
    if "close" not in data.columns:
        raise ValueError("data must contain a 'close' column.")

    closes = data["close"].astype(float).to_numpy()
    highs = (data["high"] if "high" in data.columns else data["close"]).astype(float).to_numpy()
    lows = (data["low"] if "low" in data.columns else data["close"]).astype(float).to_numpy()
    n = len(data)

    cash = float(initial_capital)
    position: Optional[dict] = None
    trade_pnls: List[float] = []
    equity_curve: List[float] = []

    for i in range(n):
        price = closes[i]
        signal = strategy.generate_signal(data.iloc[: i + 1])

        # 1) Manage an open position (exits first).
        if position is not None:
            exit_price: Optional[float] = None
            if lows[i] <= position["stop"]:          # stop assumed first if both hit
                exit_price = position["stop"]
            elif highs[i] >= position["tp"]:
                exit_price = position["tp"]
            elif signal is Signal.SELL:
                exit_price = price
            if exit_price is not None:
                proceeds = position["qty"] * exit_price * (1 - fee_pct)
                trade_pnls.append(proceeds - position["cost"])
                cash = proceeds
                position = None

        # 2) Maybe open a new position.
        if position is None and signal is Signal.BUY and price > 0:
            qty = (cash * (1 - fee_pct)) / price
            position = {
                "qty": qty,
                "cost": cash,
                "stop": price * (1 - stop_loss_pct),
                "tp": price * (1 + take_profit_pct),
            }
            cash = 0.0

        # 3) Mark-to-market equity for the drawdown curve.
        equity_curve.append(cash if position is None else position["qty"] * price)

    # Close any position still open at the final close.
    if position is not None:
        proceeds = position["qty"] * closes[-1] * (1 - fee_pct)
        trade_pnls.append(proceeds - position["cost"])
        cash = proceeds
        if equity_curve:
            equity_curve[-1] = cash

    final_equity = cash
    wins = sum(1 for p in trade_pnls if p > 0)
    num_trades = len(trade_pnls)

    return BacktestReport(
        initial_equity=float(initial_capital),
        final_equity=final_equity,
        total_return_pct=(final_equity / initial_capital - 1) * 100 if initial_capital else 0.0,
        max_drawdown_pct=_max_drawdown(equity_curve) * 100,
        num_trades=num_trades,
        wins=wins,
        losses=num_trades - wins,
        win_rate=(wins / num_trades) if num_trades else 0.0,
        trade_pnls=trade_pnls,
    )


def _max_drawdown(equity_curve: List[float]) -> float:
    peak = float("-inf")
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    return max_dd
