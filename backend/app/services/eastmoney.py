"""Eastmoney public quotes and symbol search.

Used for US indices and US stocks. A-shares stay on Sina, which already
returns prices from this network. Yahoo Finance does not.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from ..symbols import normalize_symbol

logger = logging.getLogger(__name__)

HEADERS = {
    "Referer": "https://quote.eastmoney.com",
    "User-Agent": "Mozilla/5.0",
}

# Verified from push2 on this machine: SPX / NDX / DJIA / UDI return prices.
KNOWN_SECIDS = {
    "SPX": "100.SPX",
    "NDX": "100.NDX",
    "DJI": "100.DJIA",
    "DXY": "100.UDI",
    "UDI": "100.UDI",
}

INDEX_WATCHLIST = [
    {"symbol": "SPX", "name": "标普500", "market": "us", "secid": "100.SPX"},
    {"symbol": "NDX", "name": "纳斯达克", "market": "us", "secid": "100.NDX"},
    {"symbol": "DJI", "name": "道琼斯", "market": "us", "secid": "100.DJIA"},
    {"symbol": "DXY", "name": "美元指数", "market": "us", "secid": "100.UDI"},
]


def fetch_secids(pairs: list[tuple[str, str]]) -> dict[str, dict[str, Any]]:
    """pairs are (symbol, secid). Returns quotes keyed by symbol."""
    if not pairs:
        return {}
    secids = ",".join(secid for _, secid in pairs)
    by_secid = {secid: symbol for symbol, secid in pairs}
    try:
        response = requests.get(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            params={"fltt": "2", "fields": "f2,f3,f4,f12,f14", "secids": secids},
            headers=HEADERS,
            timeout=12,
        )
        response.raise_for_status()
        diff = ((response.json().get("data") or {}).get("diff")) or []
    except Exception as exc:
        logger.warning("Eastmoney quote failed: %s", exc)
        return {symbol: {"symbol": symbol, "error": str(exc)} for symbol, _ in pairs}

    found: dict[str, dict[str, Any]] = {}
    for row in diff:
        secid = None
        code = str(row.get("f12") or "")
        for candidate, symbol in by_secid.items():
            if candidate.endswith("." + code) or candidate.endswith(code):
                secid = candidate
                break
        if secid is None:
            continue
        symbol = by_secid[secid]
        price = row.get("f2")
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            continue
        if price_f <= 0:
            continue
        change = row.get("f4")
        change_pct = row.get("f3")
        try:
            change_f = float(change) if change not in (None, "-") else None
        except (TypeError, ValueError):
            change_f = None
        try:
            pct_f = float(change_pct) if change_pct not in (None, "-") else None
        except (TypeError, ValueError):
            pct_f = None
        previous = round(price_f - change_f, 4) if change_f is not None else None
        found[symbol] = {
            "symbol": symbol,
            "name": row.get("f14") or symbol,
            "price": round(price_f, 4),
            "previous_close": previous,
            "change": change_f,
            "change_pct": pct_f,
            "volume": None,
            "currency": "USD",
        }
    for symbol, _secid in pairs:
        found.setdefault(symbol, {"symbol": symbol, "error": "no quote"})
    return found


def search_symbols(query: str, limit: int = 8) -> list[dict[str, str]]:
    text = (query or "").strip()
    if not text:
        return []
    try:
        response = requests.get(
            "https://searchadapter.eastmoney.com/api/suggest/get",
            params={"input": text, "type": "14", "count": str(max(limit * 2, 8))},
            headers=HEADERS,
            timeout=12,
        )
        response.raise_for_status()
        rows = ((response.json().get("QuotationCodeTable") or {}).get("Data")) or []
    except Exception as exc:
        logger.warning("Symbol search failed: %s", exc)
        return []

    results = []
    seen = set()
    for row in rows:
        quote_id = str(row.get("QuoteID") or "")
        code = str(row.get("Code") or "").strip()
        name = str(row.get("Name") or "").strip()
        if not code or not name or not quote_id:
            continue
        if quote_id.startswith(("0.", "1.")):
            symbol, market = normalize_symbol(code, "cn")
        elif quote_id.startswith(("100.", "105.", "106.", "107.")):
            symbol, market = code.upper(), "us"
        else:
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        results.append({
            "symbol": symbol,
            "name": name,
            "market": market,
            "secid": quote_id,
        })
        if len(results) >= limit:
            break
    return results
