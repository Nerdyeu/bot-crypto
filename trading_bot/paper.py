"""Paper trading — Milestone 6.

Real-time simulation: real market prices (read-only from the exchange) but a
purely virtual portfolio. Orders are SIMULATED — no real money moves. This is
the default, safest operating mode.

The wiring per cycle (``step``) is:

    candles (exchange, read-only)
        -> signal (strategy)
        -> risk check (risk)
        -> simulated order (PaperBroker)

The loop stops if the kill-switch engages. Everything is dependency-injected so
``step`` is unit-testable with a mocked exchange (no network).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from trading_bot.config import Settings
from trading_bot.logger import get_logger
from trading_bot.risk import OrderRequest, OrderSide, RiskManager
from trading_bot.strategy import Signal, Strategy

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


class PaperTrader:
    def __init__(
        self,
        settings: Settings,
        exchange,
        strategy: Strategy,
        risk: RiskManager,
        broker: PaperBroker,
        candles: Optional[int] = None,
    ) -> None:
        self.settings = settings
        self.exchange = exchange
        self.strategy = strategy
        self.risk = risk
        self.broker = broker
        self.candles = candles or (settings.strategy.long_window + 5)

    def step(self, now: Optional[datetime] = None) -> dict:
        now = now or datetime.now(timezone.utc)
        df = self.exchange.fetch_ohlcv(limit=self.candles)
        if df is None or df.empty:
            return {"action": "hold", "reason": "no_data"}

        price = float(df["close"].iloc[-1])
        signal = self.strategy.generate_signal(df)
        equity = self.broker.equity(price)
        symbol = self.settings.symbol
        cfg = self.risk.cfg

        # --- Manage an open position (exits first) ---------------------------
        if self.broker.in_position:
            reason = None
            if price <= (self.broker.stop_loss or 0):
                reason = "stop_loss"
            elif price >= (self.broker.take_profit or float("inf")):
                reason = "take_profit"
            elif signal is Signal.SELL:
                reason = "signal"
            if reason:
                order = OrderRequest(symbol, OrderSide.SELL, self.broker.position_qty, price,
                                     stop_loss=self.broker.stop_loss, reason=reason)
                if self.risk.check_order(order, equity=equity, free_balance=self.broker.cash, now=now):
                    pnl = self.broker.sell(price)
                    log.info("PAPER SELL %s qty=%.8f @ %.2f (%s) pnl=%+.2f equity=%.2f",
                             symbol, order.quantity, price, reason, pnl, self.broker.equity(price))
                    return {"action": "sell", "reason": reason, "price": price, "pnl": pnl}
            return {"action": "hold", "price": price}

        # --- Maybe open a new position --------------------------------------
        if signal is Signal.BUY:
            quantity = (equity * cfg.max_position_pct) / price
            stop = price * (1 - cfg.stop_loss_pct)
            take_profit = price * (1 + cfg.take_profit_pct)
            order = OrderRequest(symbol, OrderSide.BUY, quantity, price, stop_loss=stop, reason="signal")
            decision = self.risk.check_order(order, equity=equity, free_balance=self.broker.cash, now=now)
            if decision:
                self.broker.buy(price, quantity, stop_loss=stop, take_profit=take_profit)
                self.risk.register_trade()
                log.info("PAPER BUY %s qty=%.8f @ %.2f stop=%.2f tp=%.2f equity=%.2f",
                         symbol, quantity, price, stop, take_profit, self.broker.equity(price))
                return {"action": "buy", "price": price, "quantity": quantity}
            return {"action": "blocked", "rule": decision.rule, "price": price}

        return {"action": "hold", "price": price}

    def run(self, poll_seconds: float = 60.0, max_iterations: Optional[int] = None) -> None:
        log.info("Paper trading started (poll=%ss, symbol=%s, capital=%.2f).",
                 poll_seconds, self.settings.symbol, self.broker.initial_cash)
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            try:
                self.step()
            except Exception as exc:  # keep the loop alive on transient errors
                log.error("Paper step failed: %s", exc)
            if self.risk.kill_switch_engaged:
                log.error("Kill-switch engaged — stopping paper trader.")
                break
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break
            time.sleep(poll_seconds)


def build_paper_trader(settings: Settings) -> PaperTrader:
    from trading_bot.alerts import make_alert_hook
    from trading_bot.exchange import ExchangeClient
    from trading_bot.strategy import build_strategy

    risk = RiskManager(settings.risk, settings.initial_capital, alert_hook=make_alert_hook(settings))
    return PaperTrader(
        settings=settings,
        exchange=ExchangeClient(settings),
        strategy=build_strategy(settings),
        risk=risk,
        broker=PaperBroker(settings.initial_capital),
    )
