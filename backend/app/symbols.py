"""A-share / US ticker normalization.

Stored symbols stay compatible with the original app:
Shanghai ``600519.SS``, Shenzhen ``000001.SZ``, Beijing ``830000.BJ``.
"""

from __future__ import annotations


def normalize_symbol(symbol: str, market: str | None = None) -> tuple[str, str]:
    """Return ``(symbol, market)`` with market ``cn`` or ``us``."""
    raw = (symbol or "").strip().upper().replace(" ", "")
    market = (market or "us").lower()
    if market not in ("cn", "us"):
        market = "us"

    if raw.endswith((".SS", ".SZ", ".BJ")):
        return raw, "cn"

    for prefix, suffix in (("SH", ".SS"), ("SZ", ".SZ"), ("BJ", ".BJ")):
        code = raw[len(prefix):]
        if raw.startswith(prefix) and code.isdigit() and len(code) == 6:
            return f"{code}{suffix}", "cn"

    if raw.isdigit() and len(raw) == 6:
        if raw.startswith(("5", "6", "9")):
            return f"{raw}.SS", "cn"
        if raw.startswith(("4", "8")):
            return f"{raw}.BJ", "cn"
        return f"{raw}.SZ", "cn"

    return raw, market


def display_code(symbol: str) -> str:
    """``600519.SS`` -> ``600519``."""
    text = (symbol or "").upper()
    for suffix in (".SS", ".SZ", ".BJ"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def sina_code(symbol: str) -> str | None:
    """``600519.SS`` -> ``sh600519``. Non A-share symbols return None."""
    text = (symbol or "").upper()
    if text.endswith(".SS"):
        return "sh" + text[:-3]
    if text.endswith(".SZ"):
        return "sz" + text[:-3]
    if text.endswith(".BJ"):
        return "bj" + text[:-3]
    return None


def market_group(market: str | None) -> str:
    return "A股" if (market or "").lower() == "cn" else "美股"
