"""Exchange access layer (ccxt wrapper) — Milestone 2 (not yet implemented).

Responsibility
--------------
A thin, well-tested wrapper around ``ccxt`` that the rest of the bot uses
instead of talking to ``ccxt`` directly. This isolates the exchange so it can be
mocked in tests and swapped without touching strategy/risk code.

Planned (read-only first, Milestone 2):
    * connect to the configured exchange (testnet/sandbox when available)
    * fetch the current price / ticker for a symbol
    * fetch account balance
    * fetch OHLCV candles

Order placement is added later and gated behind the risk + live safeguards.
"""

from __future__ import annotations

# TODO(Milestone 2): implement read-only ExchangeClient (price, balance, OHLCV).
