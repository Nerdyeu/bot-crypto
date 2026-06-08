"""Entry point and command-line interface — Milestone 1.

At this milestone ``main.py`` already:

* parses the CLI (``--mode`` etc.),
* loads and validates configuration (failing cleanly on bad config),
* configures logging,
* prints the startup banner (mode, exchange, capital, active risk limits), and
* supports a read-only ``--check-connection`` smoke test (Milestone 2) that
  fetches market status / price / balance without ever placing an order.

The actual execution modes are implemented in later milestones:

* ``backtest`` — Milestone 4
* ``paper``    — Milestone 6
* ``live``     — Milestone 7 (locked until then)

Run from the repository root::

    python -m trading_bot.main --mode paper
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from trading_bot.config import ConfigError, Settings, load_settings
from trading_bot.logger import get_logger, setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading_bot",
        description="Safety-first crypto trading bot. Default mode is paper (simulation).",
    )
    parser.add_argument(
        "--mode",
        choices=["backtest", "paper", "live"],
        default="paper",
        help="Execution mode. 'paper' (default) and 'backtest' never touch real money.",
    )
    parser.add_argument(
        "--i-understand-the-risks",
        action="store_true",
        dest="understand_risks",
        help="Required (together with TRADING_MODE=live) to even attempt live trading.",
    )
    parser.add_argument(
        "--check-connection",
        action="store_true",
        dest="check_connection",
        help="Read-only: connect to the exchange, print market status, current price "
        "(and balance if API keys are set), then exit. Never places orders.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the .env file (default: .env).",
    )
    return parser


def run_connection_check(log, settings: Settings) -> int:
    """Read-only exchange smoke test (Milestone 2). Places no orders."""
    try:
        from trading_bot.exchange import ExchangeClient, ExchangeClientError
    except ImportError as exc:  # ccxt / pandas not installed
        log.error("Exchange layer unavailable (is ccxt installed?): %s", exc)
        return 3

    client = ExchangeClient(settings)
    try:
        client.verify_connection()
        price = client.get_price()
        log.info("Last price of %s: %s %s", settings.symbol, price, settings.quote_currency)
        if settings.has_credentials:
            balance = client.get_free_balance()
            log.info("Free %s balance: %s", settings.quote_currency, balance)
        else:
            log.info("No API credentials set — skipping balance (public data only).")
        return 0
    except ExchangeClientError as exc:
        log.error("Connection check failed: %s", exc)
        return 3


def print_banner(log, settings: Settings, mode: str) -> None:
    """Log the startup banner with the active configuration and risk limits."""
    summary = settings.safe_summary()
    risk = settings.risk

    log.info("=" * 60)
    log.info("  trading_bot starting up")
    log.info("=" * 60)
    log.info("Execution mode (--mode) : %s", mode)
    log.info("Safety gate (TRADING_MODE): %s", summary["trading_mode"])
    log.info("Exchange                : %s (sandbox=%s)", summary["exchange_id"], summary["use_sandbox"])
    log.info("Symbol / timeframe      : %s / %s", summary["symbol"], summary["timeframe"])
    log.info("Initial capital         : %s %s", summary["initial_capital"], summary["quote_currency"])
    log.info("API credentials         : key=%s secret=%s", summary["api_key"], summary["api_secret"])
    log.info("Telegram alerts         : %s", summary["telegram_alerts"])
    log.info("-" * 60)
    log.info("Active risk limits:")
    log.info("  Max position size     : %.2f%% of equity", risk.max_position_pct * 100)
    log.info("  Max daily loss        : %.2f%% of equity", risk.max_daily_loss_pct * 100)
    log.info("  Kill-switch floor     : %.2f%% of initial capital", risk.kill_switch_floor_pct * 100)
    log.info("  Max trades / day      : %d", risk.max_trades_per_day)
    log.info("  Min balance to trade  : %s %s", risk.min_balance, summary["quote_currency"])
    log.info("  Stop-loss (mandatory) : %.2f%%", risk.stop_loss_pct * 100)
    log.info("  Take-profit           : %.2f%%", risk.take_profit_pct * 100)
    log.info("Strategy                : %s (short=%d, long=%d)",
             settings.strategy.name, settings.strategy.short_window, settings.strategy.long_window)
    log.info("=" * 60)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # 1) Load + validate config BEFORE doing anything else.
    try:
        settings = load_settings(args.env_file)
    except ConfigError as exc:
        # Logging isn't configured yet, so report to stderr and exit cleanly.
        print(f"[CONFIG ERROR]\n{exc}", file=sys.stderr)
        return 2

    # 2) Configure logging from the validated settings.
    setup_logging(settings.log_level, settings.log_dir, settings.log_file)
    log = get_logger("main")

    # 3) Startup banner.
    print_banner(log, settings, args.mode)

    # 3b) Optional read-only connectivity check (safe in any mode).
    if args.check_connection:
        return run_connection_check(log, settings)

    # 4) Dispatch (full implementations land in later milestones).
    if args.mode == "backtest":
        log.info("Backtest mode is not implemented yet (Milestone 4). Nothing to do.")
        return 0

    if args.mode == "paper":
        log.info("Paper mode is not implemented yet (Milestone 6). Nothing to do.")
        return 0

    if args.mode == "live":
        # Live trading is intentionally locked until the executor and all
        # safeguards are in place (Milestone 7). We refuse here regardless of
        # flags so it is impossible to place a real order at this stage.
        log.error(
            "Live mode is LOCKED until Milestone 7. Refusing to start. "
            "(safety gate TRADING_MODE=%s, --i-understand-the-risks=%s)",
            settings.trading_mode,
            args.understand_risks,
        )
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
