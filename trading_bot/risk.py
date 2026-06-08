"""Risk management — Milestone 5 (the single most important module).

The :class:`RiskManager` validates EVERY order before it can be executed and
blocks it if any rule is violated. All limits come from ``RiskSettings`` (config)
and are also bounded there, so an unsafe config is rejected at startup.

Rules enforced for **entry** (BUY) orders:
    * kill-switch (latched): equity below a floor disables the bot entirely,
    * max daily loss: halt trading for the rest of the day when breached,
    * minimum balance to trade,
    * max trades per day,
    * mandatory stop-loss (and it must sit below the entry for a long),
    * max position size (fraction of equity).

**Exit** (SELL) orders are always allowed once basic sanity holds — closing a
position reduces exposure and must never be blocked by a risk limit.

When a rule blocks an order it logs a clear reason. The kill-switch and the
daily-loss halt also fire an optional ``alert_hook`` (e.g. Telegram later).
When in doubt, the safe choice is to STOP.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Callable, Optional

from trading_bot.config import RiskSettings
from trading_bot.logger import get_logger

log = get_logger("risk")

AlertHook = Callable[[str], None]


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    stop_loss: Optional[float] = None
    reason: str = ""

    @property
    def notional(self) -> float:
        return self.quantity * self.price

    @property
    def is_entry(self) -> bool:
        return self.side is OrderSide.BUY


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""
    rule: str = ""

    def __bool__(self) -> bool:
        return self.allowed


class RiskManager:
    def __init__(
        self,
        settings: RiskSettings,
        initial_capital: float,
        alert_hook: Optional[AlertHook] = None,
    ) -> None:
        self.cfg = settings
        self.initial_capital = float(initial_capital)
        self._alert: AlertHook = alert_hook or (lambda _msg: None)

        self._day: Optional[date] = None
        self._trades_today = 0
        self._daily_start_equity = float(initial_capital)
        self.kill_switch_engaged = False

    # ------------------------------------------------------------------ #
    # State management
    # ------------------------------------------------------------------ #
    def _roll_day(self, now: datetime, equity: float) -> None:
        today = now.date()
        if self._day is None or today != self._day:
            self._day = today
            self._trades_today = 0
            self._daily_start_equity = equity  # baseline for the daily-loss limit

    def register_trade(self) -> None:
        """Call after an order is actually placed, to count it for the day."""
        self._trades_today += 1

    def reset_kill_switch(self) -> None:
        """Manual re-arm (operator action). Logged for the audit trail."""
        log.warning("Kill-switch manually reset.")
        self.kill_switch_engaged = False

    @property
    def trades_today(self) -> int:
        return self._trades_today

    def _block(self, reason: str, rule: str) -> RiskDecision:
        log.warning("ORDER BLOCKED [%s]: %s", rule, reason)
        return RiskDecision(False, reason, rule)

    def _alert_and_block(self, reason: str, rule: str) -> RiskDecision:
        log.error("RISK ALERT [%s]: %s", rule, reason)
        self._alert(reason)
        return RiskDecision(False, reason, rule)

    # ------------------------------------------------------------------ #
    # The gate
    # ------------------------------------------------------------------ #
    def check_order(
        self,
        order: OrderRequest,
        *,
        equity: float,
        free_balance: float,
        now: Optional[datetime] = None,
    ) -> RiskDecision:
        now = now or datetime.now(timezone.utc)
        self._roll_day(now, equity)

        # 0) Basic sanity (applies to every order).
        if order.quantity <= 0 or order.price <= 0:
            return self._block(
                f"non-positive quantity/price (qty={order.quantity}, price={order.price})",
                "sanity",
            )

        # Exits reduce exposure: always allowed once sane.
        if not order.is_entry:
            return RiskDecision(True, "exit order allowed", "exit")

        # 1) Kill-switch (latched): once engaged, nothing opens until reset.
        if self.kill_switch_engaged:
            return self._block("kill-switch engaged — bot disabled until reset.", "kill_switch")

        floor = self.initial_capital * self.cfg.kill_switch_floor_pct
        if equity < floor:
            self.kill_switch_engaged = True
            return self._alert_and_block(
                f"KILL-SWITCH: equity {equity:.2f} fell below floor {floor:.2f} "
                f"({self.cfg.kill_switch_floor_pct:.0%} of initial {self.initial_capital:.2f}). "
                "Bot disabled.",
                "kill_switch",
            )

        # 2) Daily loss limit (halt for the rest of the day).
        daily_loss = self._daily_start_equity - equity
        daily_limit = self._daily_start_equity * self.cfg.max_daily_loss_pct
        if daily_limit > 0 and daily_loss >= daily_limit:
            return self._alert_and_block(
                f"DAILY LOSS LIMIT: lost {daily_loss:.2f} today "
                f"(limit {daily_limit:.2f} = {self.cfg.max_daily_loss_pct:.0%}). "
                "No new trades until tomorrow.",
                "daily_loss",
            )

        # 3) Minimum balance to trade.
        if free_balance < self.cfg.min_balance:
            return self._block(
                f"free balance {free_balance:.2f} below minimum {self.cfg.min_balance:.2f}.",
                "min_balance",
            )

        # 4) Max trades per day.
        if self._trades_today >= self.cfg.max_trades_per_day:
            return self._block(
                f"max trades per day reached ({self._trades_today}/{self.cfg.max_trades_per_day}).",
                "max_trades",
            )

        # 5) Mandatory stop-loss, and it must protect a long position.
        if order.stop_loss is None or order.stop_loss <= 0:
            return self._block("every position must carry a stop-loss.", "stop_loss")
        if order.stop_loss >= order.price:
            return self._block(
                f"stop-loss {order.stop_loss:.4f} must be below entry {order.price:.4f} for a long.",
                "stop_loss",
            )

        # 6) Max position size (fraction of equity).
        max_notional = equity * self.cfg.max_position_pct
        if order.notional > max_notional + 1e-9:
            return self._block(
                f"position notional {order.notional:.2f} exceeds max {max_notional:.2f} "
                f"({self.cfg.max_position_pct:.0%} of equity {equity:.2f}).",
                "position_size",
            )

        return RiskDecision(True, "ok")
