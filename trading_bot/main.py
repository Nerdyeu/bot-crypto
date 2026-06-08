"""Entry point and command-line interface — Milestone 1.

At this milestone ``main.py`` already:

* parses the CLI (``--mode`` etc.),
* loads and validates configuration (failing cleanly on bad config),
* configures logging,
* prints the startup banner (mode, exchange, capital, active risk limits), and
* supports a read-only ``--check-connection`` smoke test (Milestone 2) that
  fetches market status / price / balance without ever placing an order.

Execution modes:

* ``backtest`` — replay a CSV / fetched candles and print a report.
* ``paper``    — real-time simulation (default), no real money.
* ``live``     — real orders, only after the four-factor lock (see executor.py).

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
        "--csv",
        default=None,
        help="Backtest: path to an OHLCV CSV (must contain a 'close' column).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Backtest: number of candles to fetch when no --csv is given (default 500).",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=60.0,
        help="Paper mode: seconds between cycles (default 60).",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Paper mode: stop after N cycles (default: run until interrupted).",
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


def run_backtest_cli(log, settings: Settings, csv: Optional[str], limit: int) -> int:
    """Run a backtest from a CSV (preferred) or freshly fetched candles."""
    from trading_bot.backtest import load_ohlcv_csv, run_backtest
    from trading_bot.strategy import build_strategy

    if csv:
        try:
            data = load_ohlcv_csv(csv)
        except (FileNotFoundError, ValueError) as exc:
            log.error("Cannot load CSV %s: %s", csv, exc)
            return 2
        log.info("Loaded %d candles from %s", len(data), csv)
    else:
        try:
            from trading_bot.exchange import ExchangeClient

            data = ExchangeClient(settings).fetch_ohlcv(limit=limit)
            log.info("Fetched %d candles from %s", len(data), settings.exchange_id)
        except Exception as exc:  # network blocked, ccxt missing, etc.
            log.error("No --csv given and fetching candles failed: %s", exc)
            log.error("Provide historical data, e.g.: --mode backtest --csv path/to/data.csv")
            return 2

    strategy = build_strategy(settings)
    log.info("Strategy: %s", strategy.name)
    report = run_backtest(
        data,
        strategy,
        initial_capital=settings.initial_capital,
        stop_loss_pct=settings.risk.stop_loss_pct,
        take_profit_pct=settings.risk.take_profit_pct,
    )
    for line in report.summary().splitlines():
        log.info(line)
    return 0


def run_paper_cli(log, settings: Settings, poll: float, iterations: Optional[int]) -> int:
    """Run real-time paper trading (simulated orders, real prices)."""
    from trading_bot.paper import build_paper_trader

    trader = build_paper_trader(settings)
    try:
        trader.run(poll_seconds=poll, max_iterations=iterations)
    except KeyboardInterrupt:
        log.info("Paper trading stopped by user.")
    return 0


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
        return run_backtest_cli(log, settings, args.csv, args.limit)

    if args.mode == "paper":
        return run_paper_cli(log, settings, args.poll, args.iterations)

    if args.mode == "live":
        return run_live_cli(log, settings, args)

    return 0


def run_live_cli(log, settings: Settings, args) -> int:
    """Run live trading — only after the four-factor lock is satisfied."""
    from trading_bot.executor import (
        LiveTradingError,
        build_live_executor,
        confirm_live_trading,
    )

    try:
        confirm_live_trading(settings, mode=args.mode, understand_risks=args.understand_risks)
    except LiveTradingError as exc:
        log.error("LIVE TRADING REFUSED: %s", exc)
        return 1

    log.warning("LIVE TRADING CONFIRMED — real orders may now be placed.")
    executor = build_live_executor(settings)
    try:
        executor.run(poll_seconds=args.poll, max_iterations=args.iterations)
    except KeyboardInterrupt:
        log.info("Live trading stopped by user.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
