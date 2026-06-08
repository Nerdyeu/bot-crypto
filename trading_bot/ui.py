"""Pretty console output helpers — keeps screens clean and readable.

These build plain strings (no logging, no color codes) that are then emitted via
the logger. Color is applied by the console formatter based on level, so these
strings stay clean in the log file too.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple, Union

WIDTH = 56
_RULE = "━"
_LABEL_WIDTH = 22

# A row is either a "label/value" pair, a plain string (sub-line), or None (gap).
Row = Union[Tuple[str, str], str, None]


def rule(width: int = WIDTH) -> str:
    return _RULE * width


def money(value: float, currency: str = "", sign: bool = False) -> str:
    fmt = "{:+,.2f}" if sign else "{:,.2f}"
    text = fmt.format(value)
    return f"{text} {currency}".strip()


def pct(value: float, sign: bool = False) -> str:
    return f"{value:+.2f}%" if sign else f"{value:.2f}%"


def amount(value: float) -> str:
    """Trim trailing zeros from a crypto quantity (up to 8 decimals)."""
    return f"{value:.8f}".rstrip("0").rstrip(".") or "0"


def block(title: str, rows: Iterable[Row], width: int = WIDTH) -> str:
    lines = [rule(width), f"  {title}", rule(width)]
    for row in rows:
        if row is None:
            lines.append("")
        elif isinstance(row, tuple):
            label, value = row
            lines.append(f"  {label:<{_LABEL_WIDTH}}{value}")
        else:
            lines.append(f"  {row}")
    lines.append(rule(width))
    return "\n".join(lines)
