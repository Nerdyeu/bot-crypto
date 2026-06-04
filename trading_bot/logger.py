"""Logging configuration — Milestone 1.

A single place to configure logging for the whole bot:

* a rotating file handler (so logs never grow unbounded), and
* a console handler.

Every module obtains its logger via :func:`get_logger`, so all output is
namespaced under ``trading_bot.*`` and shares the same format. We never use
``print`` for operational output.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_ROOT_NAME = "trading_bot"
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_configured = False


def setup_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    log_file: str = "trading_bot.log",
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure the ``trading_bot`` logger tree (idempotent).

    Returns the package root logger. Calling this more than once will not add
    duplicate handlers; it only updates the level.
    """
    global _configured

    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(level)

    if not _configured:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, log_file)
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

        file_handler = RotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        # Don't propagate to the global root logger (avoids double logging).
        root.propagate = False
        _configured = True

    return root


def get_logger(name: str) -> logging.Logger:
    """Return a child logger namespaced under ``trading_bot``."""
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
