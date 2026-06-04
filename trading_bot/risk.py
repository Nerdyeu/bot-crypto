"""Risk management — Milestone 5 (not yet implemented).

Responsibility (the single most important module)
-------------------------------------------------
Validate EVERY order before it can be executed and block it if any rule is
violated. All limits are configurable (see ``RiskSettings`` in ``config.py``)
*and* bounded so an obviously-unsafe config is rejected at startup.

Rules to enforce (Milestone 5):
    * Max position size per trade (fraction of equity).
    * Max daily loss — halt trading for the day when breached.
    * Max total loss (kill-switch) — disable the bot and alert.
    * Mandatory stop-loss on every position.
    * Max trades per day.
    * Minimum balance to trade.

When a rule blocks an order, it must log a clear reason. When in doubt, the safe
choice is to STOP rather than trade.
"""

from __future__ import annotations

# TODO(Milestone 5): implement RiskManager.check_order(...) -> RiskDecision
# with one unit test per rule in tests/test_risk.py.
