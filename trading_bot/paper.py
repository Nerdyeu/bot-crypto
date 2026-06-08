"""Paper trading — Milestone 6 (engine shared with the executor since M7).

Real-time simulation: real market prices (read-only from the exchange) but a
purely virtual portfolio. Orders are SIMULATED — no real money moves. This is
the default, safest operating mode.

The per-cycle wiring (candles -> signal -> risk check -> simulated order) lives
in :class:`trading_bot.executor.TradingEngine`; here we only provide the virtual
wallet (:class:`PaperBroker`) and a thin :class:`PaperTrader` that labels the
engine as ``PAPER``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from trading_bot.config import Settings
from trading_bot.executor import TradingEngine
from trading_bot.logger import get_logger

log = get_logger("paper")


@dataclass
class PaperBroker:
    """A virtual wallet. Long-only spot, one position at a time."""

    initial_cash: float
    fee_pct: float = 0.0
    cash: float = field(init=False)
    position_qty: float = 0.0
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    cost_basis: float = 0.0
    trade_pnls: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = float(self.initial_cash)

    @property
    def in_position(self) -> bool:
        return self.position_qty > 0

    def equity(self, price: float) -> float:
        return self.cash + self.position_qty * price

    def buy(self, price: float, quantity: float, stop_loss: float, take_profit: float) -> None:
        cost = quantity * price
        fee = cost * self.fee_pct
        if cost + fee > self.cash + 1e-9:
            raise ValueError(f"insufficient paper cash: need {cost + fee:.2f}, have {self.cash:.2f}")
        self.cash -= cost + fee
        self.position_qty += quantity
        self.entry_price = price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.cost_basis = cost + fee

    def sell(self, price: float) -> float:
        """Close the whole position at ``price``. Returns realised PnL."""
        if not self.in_position:
            return 0.0
        proceeds = self.position_qty * price * (1 - self.fee_pct)
        pnl = proceeds - self.cost_basis
        self.cash += proceeds
        self.trade_pnls.append(pnl)
        self.position_qty = 0.0
        self.entry_price = self.stop_loss = self.take_profit = None
        self.cost_basis = 0.0
        return pnl


class PaperTrader(TradingEngine):
    """The trading engine driving a virtual :class:`PaperBroker`."""

    def __init__(self, settings, exchange, strategy, risk, broker, candles=None) -> None:
        super().__init__(settings, exchange, strategy, risk, broker, label="PAPER", candles=candles)


def build_paper_trader(settings: Settings) -> PaperTrader:
    from trading_bot.alerts import make_alert_hook
    from trading_bot.exchange import ExchangeClient
    from trading_bot.risk import RiskManager
    from trading_bot.strategy import build_strategy

    risk = RiskManager(settings.risk, settings.initial_capital, alert_hook=make_alert_hook(settings))
    return PaperTrader(
        settings=settings,
        exchange=ExchangeClient(settings),
        strategy=build_strategy(settings),
        risk=risk,
        broker=PaperBroker(settings.initial_capital),
    )
