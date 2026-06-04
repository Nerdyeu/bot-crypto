"""Trading strategy — Milestone 3 (not yet implemented).

Responsibility
--------------
Pure, network-free signal generation. The V1 strategy is a simple SMA crossover
(fast SMA crossing the slow SMA). It will expose a clear interface::

    generate_signal(data) -> Signal   # BUY | SELL | HOLD

Being pure makes it fully unit-testable on known data with no exchange access,
and easy to replace with another strategy later.
"""

from __future__ import annotations

# TODO(Milestone 3): implement Signal enum + SmaCrossoverStrategy.generate_signal()
# and its unit tests in tests/test_strategy.py.
