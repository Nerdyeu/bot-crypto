"""Order orchestration & live-trading lock — Milestone 7.

This module ties everything together for each cycle::

    candles (exchange) -> signal (strategy) -> risk check (risk) -> order (broker)

It is broker-agnostic: the same :class:`TradingEngine` drives a simulated
:class:`~trading_bot.paper.PaperBroker` or a real-money :class:`LiveBroker`.

The four-factor live lock
-------------------------
A REAL order is only ever placed when ALL of these hold (enforced by
:func:`confirm_live_trading`):

    1. CLI ``--mode live``
    2. environment ``TRADING_MODE=live``
    3. CLI flag ``--i-understand-the-risks``
    4. an interactive typed confirmation at launch

Plus: API credentials must be present (and must NOT have withdrawal permission).
If any factor is missing the bot refuses to trade live and exits.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional, Protocol

from trading_bot.config import Settings
from trading_bot.exchange import ExchangeClient, ExchangeClientError
from trading_bot.logger import get_logger
from trading_bot import ui
from trading_bot.risk import OrderRequest, OrderSide, RiskManager
from trading_bot.strategy import Signal, Strategy

log = get_logger("executor")

_REASON_FR = {"stop_loss": "stop-loss", "take_profit": "take-profit", "signal": "signal"}


class LiveTradingError(RuntimeError):
    """Raised when live trading is requested but a safety factor is missing."""


class Broker(Protocol):
    """Structural interface shared by PaperBroker and LiveBroker."""

    position_qty: float
    stop_loss: Optional[float]
    take_profit: Optional[float]

    @property
    def cash(self) -> float: ...          # free quote-currency balance
    @property
    def in_position(self) -> bool: ...
    def equity(self, price: float) -> float: ...
    def buy(self, price: float, quantity: float, stop_loss: float, take_profit: float) -> None: ...
    def sell(self, price: float) -> float: ...


class TradingEngine:
    """One trading cycle, broker-agnostic. Used by both paper and live."""

    def __init__(
        self,
        settings: Settings,
        exchange: ExchangeClient,
        strategy: Strategy,
        risk: RiskManager,
        broker: Broker,
        label: str = "ORDER",
        candles: Optional[int] = None,
    ) -> None:
        self.settings = settings
        self.exchange = exchange
        self.strategy = strategy
        self.risk = risk
        self.broker = broker
        self.label = label
        self.candles = candles or (settings.strategy.long_window + 5)

    def step(self, now: Optional[datetime] = None) -> dict:
        now = now or datetime.now(timezone.utc)
        df = self.exchange.fetch_ohlcv(limit=self.candles)
        if df is None or df.empty:
            return {"action": "hold", "reason": "no_data"}

        price = float(df["close"].iloc[-1])
        signal = self.strategy.generate_signal(df)
        free_quote = self.broker.cash
        equity = free_quote + self.broker.position_qty * price
        symbol = self.settings.symbol
        cfg = self.risk.cfg

        # --- Manage an open position (exits first) --------------------------
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
                if self.risk.check_order(order, equity=equity, free_balance=free_quote, now=now):
                    pnl = self.broker.sell(price)
                    log.info("%s  %s  VENTE %s %s @ %s  ·  %s  ·  résultat %s  ·  capital %s",
                             now.strftime("%H:%M:%S"), self.label, ui.amount(order.quantity),
                             self.settings.base_currency, ui.money(price),
                             _REASON_FR.get(reason, reason), ui.money(pnl, sign=True),
                             ui.money(self.broker.equity(price)))
                    return {"action": "sell", "reason": reason, "price": price, "pnl": pnl}
            return {"action": "hold", "price": price}

        # --- Maybe open a new position --------------------------------------
        if signal is Signal.BUY:
            quantity = (equity * cfg.max_position_pct) / price
            stop = price * (1 - cfg.stop_loss_pct)
            take_profit = price * (1 + cfg.take_profit_pct)
            order = OrderRequest(symbol, OrderSide.BUY, quantity, price, stop_loss=stop, reason="signal")
            decision = self.risk.check_order(order, equity=equity, free_balance=free_quote, now=now)
            if decision:
                self.broker.buy(price, quantity, stop_loss=stop, take_profit=take_profit)
                self.risk.register_trade()
                log.info("%s  %s  ACHAT %s %s @ %s  ·  stop %s / tp %s  ·  capital %s",
                         now.strftime("%H:%M:%S"), self.label, ui.amount(quantity),
                         self.settings.base_currency, ui.money(price), ui.money(stop),
                         ui.money(take_profit), ui.money(self.broker.equity(price)))
                return {"action": "buy", "price": price, "quantity": quantity}
            return {"action": "blocked", "rule": decision.rule, "price": price}

        return {"action": "hold", "price": price}

    def run(self, poll_seconds: float = 60.0, max_iterations: Optional[int] = None) -> None:
        log.info("Surveillance %s démarrée — %s, un cycle toutes les %ss. "
                 "(silencieux tant qu'il n'y a pas de trade ; Ctrl+C pour arrêter)",
                 self.label, self.settings.symbol, poll_seconds)
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            try:
                self.step()
            except Exception as exc:  # keep the loop alive on transient errors
                log.error("%s step failed: %s", self.label, exc)
            if self.risk.kill_switch_engaged:
                log.error("Kill-switch engaged — stopping %s trader.", self.label)
                break
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break
            time.sleep(poll_seconds)


# --------------------------------------------------------------------------- #
# Live broker (real money)
# --------------------------------------------------------------------------- #
def _filled_amount(order: dict, requested: float) -> float:
    amt = order.get("filled") if isinstance(order, dict) else None
    return float(amt) if amt else float(requested)


def _avg_price(order: dict, fallback: float) -> float:
    if isinstance(order, dict):
        price = order.get("average") or order.get("price")
        if price:
            return float(price)
    return float(fallback)


class LiveBroker:
    """Real-money broker. Long-only spot, one position at a time.

    Stops/take-profits are managed by the bot (checked each cycle), not as
    exchange-side orders, to keep V1 simple and exchange-agnostic.
    """

    def __init__(self, exchange: ExchangeClient, symbol: str, quote_currency: str,
                 fee_pct: float = 0.0) -> None:
        self.exchange = exchange
        self.symbol = symbol
        self.quote = quote_currency
        self.fee_pct = fee_pct
        self.position_qty = 0.0
        self.entry_price: Optional[float] = None
        self.stop_loss: Optional[float] = None
        self.take_profit: Optional[float] = None
        self.cost_basis = 0.0

    @property
    def cash(self) -> float:
        return self.exchange.get_free_balance(self.quote)

    @property
    def in_position(self) -> bool:
        return self.position_qty > 0

    def equity(self, price: float) -> float:
        return self.cash + self.position_qty * price

    def buy(self, price: float, quantity: float, stop_loss: float, take_profit: float) -> None:
        order = self.exchange.create_market_order(self.symbol, OrderSide.BUY, quantity)
        filled = _filled_amount(order, quantity)
        fill_price = _avg_price(order, price)
        self.position_qty += filled
        self.entry_price = fill_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.cost_basis = filled * fill_price

    def sell(self, price: float) -> float:
        if not self.in_position:
            return 0.0
        qty = self.position_qty
        order = self.exchange.create_market_order(self.symbol, OrderSide.SELL, qty)
        fill_price = _avg_price(order, price)
        pnl = qty * fill_price * (1 - self.fee_pct) - self.cost_basis
        self.position_qty = 0.0
        self.entry_price = self.stop_loss = self.take_profit = None
        self.cost_basis = 0.0
        return pnl


# --------------------------------------------------------------------------- #
# The four-factor live lock
# --------------------------------------------------------------------------- #
def confirm_live_trading(
    settings: Settings,
    *,
    mode: str,
    understand_risks: bool,
    input_fn=input,
) -> None:
    """Raise :class:`LiveTradingError` unless every safety factor is satisfied."""
    if mode != "live":
        raise LiveTradingError("live executor requires --mode live.")
    if settings.trading_mode != "live":
        raise LiveTradingError("environment TRADING_MODE=live is required for real orders.")
    if not understand_risks:
        raise LiveTradingError("the --i-understand-the-risks flag is required for real orders.")
    if not settings.has_credentials:
        raise LiveTradingError(
            "API credentials are required for live trading (EXCHANGE_API_KEY / "
            "EXCHANGE_API_SECRET) — and they must NOT have withdrawal permission."
        )

    log.warning("Reminder: your API keys must have NO withdrawal permission.")
    if not settings.use_sandbox:
        log.warning("USE_SANDBOX=false — orders will hit the REAL exchange with REAL funds.")

    answer = input_fn(
        f'Type "I UNDERSTAND" to start LIVE trading on '
        f"{settings.exchange_id} {settings.symbol}: "
    )
    if answer.strip() != "I UNDERSTAND":
        raise LiveTradingError("typed confirmation not given — aborting live trading.")


def build_live_executor(settings: Settings) -> TradingEngine:
    from trading_bot.alerts import make_alert_hook
    from trading_bot.strategy import build_strategy

    exchange = ExchangeClient(settings)
    broker = LiveBroker(exchange, settings.symbol, settings.quote_currency)
    risk = RiskManager(settings.risk, settings.initial_capital, alert_hook=make_alert_hook(settings))
    strategy = build_strategy(settings)
    return TradingEngine(settings, exchange, strategy, risk, broker, label="LIVE")
