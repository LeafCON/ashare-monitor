"""Symbol normalization for A-shares, Hong Kong stocks, and US tickers.

Stored forms: ``600519.SS``, ``000001.SZ``, ``00700.HK``, ``AAPL``.
"""

from __future__ import annotations


def normalize_symbol(symbol: str, market: str | None = None) -> tuple[str, str]:
    """Return ``(symbol, market)`` with market ``cn``, ``hk``, or ``us``."""
    raw = (symbol or "").strip().upper().replace(" ", "")
    market = (market or "us").lower()
    if market not in ("cn", "hk", "us"):
        market = "us"

    if raw.endswith(".HK"):
        code = raw[:-3]
        if code.isdigit():
            code = code.zfill(5)
        return f"{code}.HK", "hk"

    if raw.endswith((".SS", ".SZ", ".BJ")):
        return raw, "cn"

    for prefix, suffix in (("SH", ".SS"), ("SZ", ".SZ"), ("BJ", ".BJ")):
        code = raw[len(prefix):]
        if raw.startswith(prefix) and code.isdigit() and len(code) == 6:
            return f"{code}{suffix}", "cn"

    if raw.startswith("HK") and raw[2:].isdigit() and len(raw[2:]) <= 5:
        return f"{raw[2:].zfill(5)}.HK", "hk"

    if raw.isdigit() and len(raw) == 6:
        if raw.startswith(("5", "6", "9")):
            return f"{raw}.SS", "cn"
        if raw.startswith(("4", "8")):
            return f"{raw}.BJ", "cn"
        return f"{raw}.SZ", "cn"

    if raw.isdigit() and 1 <= len(raw) <= 5:
        return f"{raw.zfill(5)}.HK", "hk"

    return raw, market


def display_code(symbol: str) -> str:
    """``600519.SS`` -> ``600519``, ``00700.HK`` -> ``00700``."""
    text = (symbol or "").upper()
    for suffix in (".SS", ".SZ", ".BJ", ".HK"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def sina_code(symbol: str) -> str | None:
    """``600519.SS`` -> ``sh600519``. Hong Kong and US symbols return None."""
    text = (symbol or "").upper()
    if text.endswith(".SS"):
        return "sh" + text[:-3]
    if text.endswith(".SZ"):
        return "sz" + text[:-3]
    if text.endswith(".BJ"):
        return "bj" + text[:-3]
    return None


def hk_secid(symbol: str) -> str | None:
    """``00700.HK`` -> ``116.00700``."""
    text = (symbol or "").upper()
    if not text.endswith(".HK"):
        return None
    code = text[:-3]
    if not code.isdigit():
        return None
    return "116." + code.zfill(5)


def market_group(market: str | None) -> str:
    return {"cn": "A股", "hk": "港股", "us": "美股"}.get((market or "").lower(), "美股")
