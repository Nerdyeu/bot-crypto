"""Configuration loading and validation — Milestone 1.

Design principles
-----------------
* **No secrets in code.** Every value comes from environment variables or a
  local ``.env`` file (which is git-ignored). The ``.env.example`` file documents
  every variable.
* **Safe by default.** If nothing is configured the bot runs in ``paper`` mode
  with conservative risk limits and refuses to place real orders.
* **Fail fast and clearly.** Invalid or missing configuration raises
  :class:`ConfigError` with a human-readable message instead of crashing deep
  inside the trading loop.

Two distinct "mode" concepts (kept separate on purpose)
-------------------------------------------------------
* ``trading_mode`` (env var ``TRADING_MODE``): the **safety gate**. It may only
  be ``paper`` or ``live``. ``live`` is the *only* value that even permits real
  orders, and even then only in combination with the ``--i-understand-the-risks``
  CLI flag and a typed confirmation (wired up in Milestone 7).
* The CLI ``--mode`` (``backtest`` | ``paper`` | ``live``): the **execution
  mode** chosen at launch. See ``main.py``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ``ccxt`` style symbols look like ``BTC/USDT``. Timeframes look like ``1m`` /
# ``4h`` / ``1d``. We validate the shape without importing ccxt so that config
# stays dependency-light and unit-testable without any network library.
_SYMBOL_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")
_TIMEFRAME_RE = re.compile(r"^\d+[mhdwM]$")  # 1m, 5m, 15m, 1h, 4h, 1d, 1w, 1M
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigError(RuntimeError):
    """Raised when configuration is missing, malformed, or unsafe."""


class RiskSettings(BaseModel):
    """Hard risk guardrails.

    Every value is bounded here so that an obviously-wrong configuration
    (e.g. a 500% position size, or a negative loss limit) is rejected at startup
    rather than discovered the hard way. The actual *enforcement* of these
    limits before each order lives in ``risk.py`` (Milestone 5).
    """

    max_position_pct: float = Field(
        0.02, gt=0, le=1,
        description="Max fraction of equity risked on a single trade (0.02 = 2%).",
    )
    max_daily_loss_pct: float = Field(
        0.05, gt=0, le=1,
        description="Halt trading for the rest of the day once daily loss exceeds this fraction (0.05 = 5%).",
    )
    kill_switch_floor_pct: float = Field(
        0.80, gt=0, lt=1,
        description="Disable the bot entirely if equity falls below this fraction of the initial capital (0.80 = 80%).",
    )
    max_trades_per_day: int = Field(
        10, ge=1, le=10_000,
        description="Hard cap on the number of trades opened per day.",
    )
    min_balance: float = Field(
        50.0, ge=0,
        description="Refuse to trade if the quote-currency balance drops below this amount.",
    )
    stop_loss_pct: float = Field(
        0.02, gt=0, le=1,
        description="Mandatory stop-loss distance from entry (0.02 = 2%). Every position must carry a stop.",
    )
    take_profit_pct: float = Field(
        0.04, gt=0, le=5,
        description="Take-profit distance from entry (0.04 = 4%).",
    )


class StrategySettings(BaseModel):
    """Parameters for the (pluggable) strategy.

    The V1 strategy is a simple SMA crossover. Keeping its parameters here makes
    them configurable and keeps ``strategy.py`` free of magic numbers.
    """

    name: str = Field("sma_crossover", description="Strategy identifier.")
    short_window: int = Field(20, ge=1, le=10_000, description="Fast SMA period.")
    long_window: int = Field(50, ge=2, le=10_000, description="Slow SMA period.")

    @model_validator(mode="after")
    def _windows_must_be_ordered(self) -> "StrategySettings":
        if self.short_window >= self.long_window:
            raise ValueError(
                f"strategy.short_window ({self.short_window}) must be strictly less "
                f"than strategy.long_window ({self.long_window})."
            )
        return self


class Settings(BaseSettings):
    """Top-level, fully-validated configuration for the bot.

    Loaded from environment variables and an optional ``.env`` file. Nested
    settings use a double-underscore delimiter, e.g. ``RISK__MAX_POSITION_PCT``
    or ``STRATEGY__SHORT_WINDOW``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Safety gate -------------------------------------------------------
    trading_mode: Literal["paper", "live"] = Field(
        "paper",
        description="Safety gate. 'live' is the ONLY value that permits real orders.",
    )

    # --- Exchange ----------------------------------------------------------
    exchange_id: str = Field("binance", description="ccxt exchange id, e.g. 'binance'.")
    use_sandbox: bool = Field(
        True, description="Use the exchange testnet/sandbox when available."
    )
    exchange_api_key: Optional[str] = Field(default=None, repr=False)
    exchange_api_secret: Optional[str] = Field(default=None, repr=False)
    exchange_api_password: Optional[str] = Field(
        default=None,
        repr=False,
        description="API passphrase, required by some exchanges (kucoin, coinbase, okx, ...).",
    )

    # --- Market ------------------------------------------------------------
    symbol: str = Field("BTC/USDT", description="Trading pair in ccxt format BASE/QUOTE.")
    timeframe: str = Field("1h", description="Candle timeframe, e.g. 1m, 15m, 1h, 4h, 1d.")

    # --- Capital -----------------------------------------------------------
    initial_capital: float = Field(
        1000.0, gt=0,
        description="Starting equity (quote currency). Used by paper trading and as the risk baseline.",
    )

    # --- Logging / alerts --------------------------------------------------
    log_level: str = Field("INFO")
    log_dir: str = Field("logs")
    log_file: str = Field("trading_bot.log")
    telegram_bot_token: Optional[str] = Field(default=None, repr=False)
    telegram_chat_id: Optional[str] = Field(default=None, repr=False)

    # --- Data --------------------------------------------------------------
    data_dir: str = Field("trading_bot/data", description="Folder for historical CSVs used by backtests.")

    # --- Grouped configs ---------------------------------------------------
    risk: RiskSettings = Field(default_factory=RiskSettings)
    strategy: StrategySettings = Field(default_factory=StrategySettings)

    # ------------------------------------------------------------------ #
    # Field validators
    # ------------------------------------------------------------------ #
    @field_validator("exchange_id")
    @classmethod
    def _normalise_exchange(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("exchange_id must not be empty.")
        return value

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not _SYMBOL_RE.match(value):
            raise ValueError(
                f"symbol '{value}' is not a valid ccxt pair. Expected BASE/QUOTE, e.g. 'BTC/USDT'."
            )
        return value

    @field_validator("timeframe")
    @classmethod
    def _validate_timeframe(cls, value: str) -> str:
        value = value.strip()
        if not _TIMEFRAME_RE.match(value):
            raise ValueError(
                f"timeframe '{value}' is invalid. Expected e.g. 1m, 5m, 15m, 1h, 4h, 1d, 1w, 1M."
            )
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"log_level '{value}' is invalid. Choose one of {sorted(_VALID_LOG_LEVELS)}."
            )
        return value

    # ------------------------------------------------------------------ #
    # Derived helpers
    # ------------------------------------------------------------------ #
    @property
    def base_currency(self) -> str:
        return self.symbol.split("/")[0]

    @property
    def quote_currency(self) -> str:
        return self.symbol.split("/")[1]

    @property
    def log_path(self) -> str:
        import os

        return os.path.join(self.log_dir, self.log_file)

    @property
    def has_credentials(self) -> bool:
        return bool(self.exchange_api_key and self.exchange_api_secret)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def require_live_credentials(self) -> None:
        """Ensure API credentials exist before any real-money activity.

        Called from the live-mode activation path (Milestone 7). Raises
        :class:`ConfigError` with actionable guidance if keys are missing.
        """
        if not self.has_credentials:
            raise ConfigError(
                "Live trading requires EXCHANGE_API_KEY and EXCHANGE_API_SECRET to be set "
                "in your environment / .env file. Refusing to continue without credentials."
            )

    def safe_summary(self) -> dict:
        """Return a dict safe to log: secrets are masked, never printed."""

        def mask(value: Optional[str]) -> str:
            if not value:
                return "<not set>"
            return f"set (••••{value[-4:]})" if len(value) >= 4 else "set"

        return {
            "trading_mode": self.trading_mode,
            "exchange_id": self.exchange_id,
            "use_sandbox": self.use_sandbox,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "initial_capital": self.initial_capital,
            "quote_currency": self.quote_currency,
            "api_key": mask(self.exchange_api_key),
            "api_secret": mask(self.exchange_api_secret),
            "telegram_alerts": "enabled" if self.telegram_enabled else "disabled",
            "risk": self.risk.model_dump(),
            "strategy": self.strategy.model_dump(),
        }


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Configuration is invalid:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ())) or "(root)"
        lines.append(f"  - {loc}: {err.get('msg')}")
    lines.append("See .env.example for the full list of supported variables.")
    return "\n".join(lines)


def load_settings(env_file: Optional[str] = ".env") -> Settings:
    """Load and validate settings, converting pydantic errors into ``ConfigError``.

    Parameters
    ----------
    env_file:
        Path to a ``.env`` file, or ``None`` to ignore any ``.env`` on disk and
        read configuration strictly from the process environment (used in tests).
    """
    try:
        if env_file is None:
            return Settings(_env_file=None)  # type: ignore[call-arg]
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached settings loaded from the default ``.env``."""
    return load_settings()
