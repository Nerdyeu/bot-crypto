"""Order orchestration — Milestone 7 (not yet implemented).

Responsibility
--------------
Glue the pieces together for each cycle::

    signal (strategy) -> risk check (risk) -> order (exchange/paper)

The executor also owns the live-mode lock: a real order is only ever placed when
ALL of the following are true:

    1. CLI ``--mode live``
    2. environment ``TRADING_MODE=live``
    3. CLI flag ``--i-understand-the-risks``
    4. an interactive typed confirmation at launch

Every real order is logged (timestamp, pair, side, size, price, reason) to both
the log file and the console.
"""

from __future__ import annotations

# TODO(Milestone 7): implement Executor + the four-factor live-trading lock.
