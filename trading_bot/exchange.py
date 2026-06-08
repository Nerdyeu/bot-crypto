"""Exchange access layer (ccxt wrapper) — Milestone 2 (READ-ONLY).

A thin, well-tested wrapper around ``ccxt`` so the rest of the bot never imports
``ccxt`` directly. This isolates the exchange behind a small interface that can be
fully mocked in tests (no network, no real exchange).

What this layer does (read-only):
    * connect to the configured exchange (testnet/sandbox when available),
    * fetch the current ticker / price for a symbol,
    * fetch account balance (requires API credentials),
    * fetch OHLCV candles as a pandas ``DataFrame``.

Order placement (Milestone 7):
    * ``create_market_order`` places a REAL market order. It is intentionally the
      only write method, is NOT retried (to avoid accidental double-submits), and
      is only ever called by the live executor *after* the four-factor live lock
      and the risk checks have passed.

Resilience: transient network errors are retried with exponential backoff (reads
only).
Authentication / bad-request errors fail fast with a clear message. All
underlying ``ccxt`` exceptions are wrapped in :class:`ExchangeClientError`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, List, Optional

import ccxt
import pandas as pd

from trading_bot.config import Settings
from trading_bot.logger import get_logger

log = get_logger("exchange")

# Column layout of a ccxt OHLCV row is [timestamp, open, high, low, close, volume].
_OHLCV_PRICE_COLUMNS = ["open", "high", "low", "close", "volume"]


class ExchangeClientError(RuntimeError):
    """Any failure in the exchange wrapper. Wraps the underlying ccxt error."""


@dataclass(frozen=True)
class Ticker:
    """A minimal, typed view of a ccxt ticker."""

    symbol: str
    last: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    timestamp: Optional[int]  # epoch milliseconds


class ExchangeClient:
    """Read-only wrapper around a ccxt exchange.

    Parameters
    ----------
    settings:
        Validated :class:`~trading_bot.config.Settings`.
    exchange:
        An optional pre-built exchange instance. When provided it is used as-is
        (this is how tests inject a mock). When ``None`` a real ccxt exchange is
        created lazily on first use.
    max_retries:
        Number of attempts for transient network errors.
    backoff_base:
        Base seconds for exponential backoff (attempt N waits
        ``backoff_base * 2**(N-1)``). Set to ``0`` in tests to avoid sleeping.
    """

    def __init__(
        self,
        settings: Settings,
        exchange: Optional[Any] = None,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ) -> None:
        self.settings = settings
        self._exchange = exchange
        self.max_retries = max(1, int(max_retries))
        self.backoff_base = max(0.0, float(backoff_base))

    # ------------------------------------------------------------------ #
    # Construction / connection
    # ------------------------------------------------------------------ #
    @property
    def name(self) -> str:
        return self.settings.exchange_id

    @property
    def exchange(self) -> Any:
        """The underlying ccxt exchange, created lazily on first access."""
        if self._exchange is None:
            self._exchange = self._create_exchange()
        return self._exchange

    def _create_exchange(self) -> Any:
        try:
            exchange_class = getattr(ccxt, self.settings.exchange_id)
        except AttributeError as exc:
            raise ExchangeClientError(
                f"Unknown exchange id '{self.settings.exchange_id}'. "
                "See ccxt.exchanges for the list of valid ids."
            ) from exc

        config: dict[str, Any] = {"enableRateLimit": True}
        if self.settings.has_credentials:
            config["apiKey"] = self.settings.exchange_api_key
            config["secret"] = self.settings.exchange_api_secret
            if self.settings.exchange_api_password:
                config["password"] = self.settings.exchange_api_password

        exchange = exchange_class(config)

        if self.settings.use_sandbox:
            try:
                exchange.set_sandbox_mode(True)
                log.info("Sandbox/testnet mode ENABLED for %s.", self.name)
            except ccxt.NotSupported:
                log.warning(
                    "Exchange %s does not support sandbox mode; using LIVE endpoints "
                    "(read-only at this milestone).",
                    self.name,
                )
        else:
            log.warning("Sandbox DISABLED — talking to the LIVE %s endpoints.", self.name)

        return exchange

    def _with_retry(self, label: str, func, *args, **kwargs):
        """Call ``func`` with retries on transient network errors.

        * :class:`ccxt.AuthenticationError` and other :class:`ccxt.ExchangeError`
          subclasses fail fast (retrying would not help).
        * :class:`ccxt.NetworkError` (timeouts, DDoS protection, exchange not
          available, ...) is retried with exponential backoff.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                return func(*args, **kwargs)
            except ccxt.AuthenticationError as exc:
                raise ExchangeClientError(
                    f"Authentication failed during {label}: {exc}. Check your API "
                    "key/secret and that they match the environment (testnet vs live)."
                ) from exc
            except ccxt.NetworkError as exc:
                if attempt >= self.max_retries:
                    raise ExchangeClientError(
                        f"{label} failed after {self.max_retries} attempt(s) "
                        f"due to network error: {exc}"
                    ) from exc
                wait = self.backoff_base * (2 ** (attempt - 1))
                log.warning(
                    "Network error during %s (attempt %d/%d): %s — retrying in %.1fs",
                    label, attempt, self.max_retries, exc, wait,
                )
                if wait:
                    time.sleep(wait)
            except ccxt.ExchangeError as exc:
                raise ExchangeClientError(f"{label} failed: {exc}") from exc

    def load_markets(self, reload: bool = False) -> dict:
        return self._with_retry("load_markets", self.exchange.load_markets, reload)

    def verify_connection(self) -> bool:
        """Load markets to confirm connectivity. Returns True or raises."""
        markets = self.load_markets()
        log.info(
            "Connected to %s — %d markets available (sandbox=%s).",
            self.name, len(markets), self.settings.use_sandbox,
        )
        if self.settings.symbol not in markets:
            log.warning(
                "Configured symbol %s was not found on %s.",
                self.settings.symbol, self.name,
            )
        return True

    # ------------------------------------------------------------------ #
    # Market data (public — no credentials required)
    # ------------------------------------------------------------------ #
    def fetch_ticker(self, symbol: Optional[str] = None) -> Ticker:
        symbol = symbol or self.settings.symbol
        raw = self._with_retry(
            f"fetch_ticker({symbol})", self.exchange.fetch_ticker, symbol
        )
        return Ticker(
            symbol=symbol,
            last=raw.get("last"),
            bid=raw.get("bid"),
            ask=raw.get("ask"),
            timestamp=raw.get("timestamp"),
        )

    def get_price(self, symbol: Optional[str] = None) -> float:
        """Return the last traded price for ``symbol`` (defaults to config)."""
        ticker = self.fetch_ticker(symbol)
        if ticker.last is None:
            raise ExchangeClientError(f"No 'last' price available for {ticker.symbol}.")
        return float(ticker.last)

    def fetch_ohlcv(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 500,
        since: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles as a DataFrame indexed by UTC datetime.

        Columns: ``open, high, low, close, volume`` (floats), plus the original
        ``timestamp`` (epoch ms).
        """
        symbol = symbol or self.settings.symbol
        timeframe = timeframe or self.settings.timeframe
        raw = self._with_retry(
            f"fetch_ohlcv({symbol},{timeframe})",
            self.exchange.fetch_ohlcv,
            symbol,
            timeframe,
            since,
            limit,
        )
        return self._ohlcv_to_dataframe(raw)

    @staticmethod
    def _ohlcv_to_dataframe(raw: List[list]) -> pd.DataFrame:
        df = pd.DataFrame(raw, columns=["timestamp", *_OHLCV_PRICE_COLUMNS])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("datetime")
        if not df.empty:
            df[_OHLCV_PRICE_COLUMNS] = df[_OHLCV_PRICE_COLUMNS].astype(float)
        return df

    # ------------------------------------------------------------------ #
    # Account data (private — requires credentials)
    # ------------------------------------------------------------------ #
    def fetch_balance(self) -> dict:
        if not self.settings.has_credentials:
            raise ExchangeClientError(
                "fetch_balance requires API credentials. Set EXCHANGE_API_KEY and "
                "EXCHANGE_API_SECRET in your environment / .env file."
            )
        return self._with_retry("fetch_balance", self.exchange.fetch_balance)

    def get_free_balance(self, currency: Optional[str] = None) -> float:
        """Return the free (available) balance for ``currency``.

        Defaults to the quote currency of the configured symbol (e.g. USDT).
        """
        currency = (currency or self.settings.quote_currency).upper()
        balance = self.fetch_balance()
        free = balance.get("free", {}) or {}
        return float(free.get(currency, 0.0) or 0.0)

    # ------------------------------------------------------------------ #
    # Order placement (WRITE) — the only method that moves real money
    # ------------------------------------------------------------------ #
    def create_market_order(self, symbol: str, side, amount: float) -> dict:
        """Place a REAL market order. Single attempt — never retried.

        Order submission is deliberately NOT wrapped in the retry helper: a
        network error after the exchange has accepted the order could otherwise
        cause a duplicate fill. This is only called by the live executor once the
        live lock and risk checks have passed.
        """
        side_str = (side.value if hasattr(side, "value") else str(side)).lower()
        if side_str not in ("buy", "sell"):
            raise ExchangeClientError(f"invalid order side: {side!r}")
        if amount <= 0:
            raise ExchangeClientError(f"order amount must be positive, got {amount}.")

        log.warning("PLACING REAL %s MARKET ORDER: %s amount=%s", side_str.upper(), symbol, amount)
        try:
            return self.exchange.create_order(symbol, "market", side_str, amount)
        except ccxt.AuthenticationError as exc:
            raise ExchangeClientError(f"Authentication failed placing order: {exc}") from exc
        except ccxt.BaseError as exc:
            raise ExchangeClientError(f"create_market_order failed: {exc}") from exc
