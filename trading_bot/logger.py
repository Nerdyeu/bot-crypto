"""Logging configuration — Milestone 1 (clean console + detailed file).

Two outputs, two styles:

* **Console**: human-friendly. Just the message for INFO; WARNING/ERROR get a
  small marker and (when supported) color. No timestamps/module clutter.
* **File** (``logs/trading_bot.log``, rotating): full detail — timestamp, level
  and module — for debugging and the audit trail.

Every module obtains its logger via :func:`get_logger`. We never use ``print``.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_ROOT_NAME = "trading_bot"
_FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_configured = False


class _ConsoleFormatter(logging.Formatter):
    """Minimal, readable console formatter."""

    _TAG = {logging.DEBUG: "·", logging.WARNING: "!", logging.ERROR: "✖", logging.CRITICAL: "✖"}
    _COLOR = {
        logging.DEBUG: "\033[90m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }
    _RESET = "\033[0m"

    def __init__(self, use_color: bool) -> None:
        super().__init__()
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        tag = self._TAG.get(record.levelno)
        # INFO is the common case: print the message as-is (banners stay aligned).
        text = message if tag is None else f"{tag} {message}"
        color = self._COLOR.get(record.levelno) if self.use_color else None
        return f"{color}{text}{self._RESET}" if color else text


def _supports_color(stream) -> bool:
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if sys.platform == "win32":
        try:  # enable ANSI / virtual-terminal processing on modern Windows
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return True


def setup_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    log_file: str = "trading_bot.log",
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure the ``trading_bot`` logger tree (idempotent)."""
    global _configured

    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(level)

    if not _configured:
        stream = sys.stdout
        try:  # make the console UTF-8 safe (box/▲ glyphs) on every platform
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

        console = logging.StreamHandler(stream)
        console.setFormatter(_ConsoleFormatter(use_color=_supports_color(stream)))
        root.addHandler(console)

        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(file_handler)

        root.propagate = False
        _configured = True

    return root


def get_logger(name: str) -> logging.Logger:
    """Return a child logger namespaced under ``trading_bot``."""
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
