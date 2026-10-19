"""Quote provider.

A-shares use public HTTP quotes (Sina, then Tencent). US symbols keep the
original Yahoo Finance path when curl_cffi is installed. Providers are
replaceable: ``fetch_prices_batch`` is the only entry the monitor uses.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

import requests

from ..symbols import sina_code

logger = logging.getLogger(__name__)

_last_http_at = 0.0
_MIN_INTERVAL = 0.8
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn",
}


def _throttle() -> None:
    global _last_http_at
    wait = _MIN_INTERVAL - (time.time() - _last_http_at)
    if wait > 0:
        time.sleep(wait)
    _last_http_at = time.time()


def _get(url: str) -> str:
    last_error = "request failed"
    for attempt in range(3):
        try:
            _throttle()
            resp = requests.get(url, headers=_HTTP_HEADERS, timeout=12)
            resp.raise_for_status()
            return resp.content.decode("gbk", errors="replace")
        except Exception as exc:
            last_error = str(exc)
            logger.warning("quote request failed (%s/3): %s", attempt + 1, exc)
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(last_error)


def _parse_sina_line(line: str) -> Dict[str, Any] | None:
    if '="' not in line:
        return None
    left, right = line.split('="', 1)
    code = left.rsplit("_", 1)[-1].strip()
    payload = right.strip().rstrip(";").strip('"')
    if not payload:
        return None
    parts = payload.split(",")
    if len(parts) < 10:
        return None
    try:
        price = float(parts[3] or 0)
        previous = float(parts[2] or 0)
    except ValueError:
        return None
    if price <= 0:
        return None
    change = round(price - previous, 4) if previous else None
    change_pct = round(change / previous * 100, 2) if previous and change is not None else None
    volume = None
    try:
        volume = float(parts[8]) if parts[8] else None
    except ValueError:
        volume = None
    return {
        "sina": code,
        "name": parts[0],
        "price": round(price, 4),
        "previous_close": round(previous, 4) if previous else None,
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
        "currency": "CNY",
    }


def _fetch_sina(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    mapping = {sina_code(sym): sym for sym in symbols}
    mapping.pop(None, None)
    if not mapping:
        return {}
    url = "https://hq.sinajs.cn/list=" + ",".join(mapping)
    text = _get(url)
    found: Dict[str, Dict[str, Any]] = {}
    for line in text.splitlines():
        parsed = _parse_sina_line(line)
        if not parsed:
            continue
        symbol = mapping.get(parsed["sina"])
        if not symbol:
            continue
        parsed["symbol"] = symbol
        found[symbol] = parsed
    return found


def _fetch_tencent(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    mapping = {sina_code(sym): sym for sym in symbols}
    mapping.pop(None, None)
    if not mapping:
        return {}
    url = "https://qt.gtimg.cn/q=" + ",".join(mapping)
    text = _get(url)
    found: Dict[str, Dict[str, Any]] = {}
    for line in text.splitlines():
        if '="' not in line or "~" not in line:
            continue
        left, right = line.split('="', 1)
        key = left.strip().removeprefix("v_")
        symbol = mapping.get(key)
        parts = right.strip().rstrip(";").strip('"').split("~")
        if not symbol or len(parts) < 33:
            continue
        try:
            price = float(parts[3] or 0)
            previous = float(parts[4] or 0)
        except ValueError:
            continue
        if price <= 0:
            continue
        change = round(price - previous, 4) if previous else None
        try:
            change_pct = float(parts[32])
        except ValueError:
            change_pct = round(change / previous * 100, 2) if previous and change is not None else None
        volume = None
        try:
            lots = float(parts[6]) if parts[6] else None
            volume = lots * 100 if lots is not None else None
        except ValueError:
            volume = None
        found[symbol] = {
            "symbol": symbol,
            "name": parts[1] or symbol,
            "price": round(price, 4),
            "previous_close": round(previous, 4) if previous else None,
            "change": change,
            "change_pct": change_pct,
            "volume": volume,
            "currency": "CNY",
        }
    return found


def fetch_cn_prices(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Batch A-share quotes. Sina first, Tencent fills the gaps."""
    results: Dict[str, Dict[str, Any]] = {}
    try:
        results.update(_fetch_sina(symbols))
    except Exception as exc:
        logger.warning("Sina quotes unavailable: %s", exc)
    missing = [sym for sym in symbols if sym not in results]
    if missing:
        try:
            results.update(_fetch_tencent(missing))
        except Exception as exc:
            logger.warning("Tencent quotes unavailable: %s", exc)
    for sym in symbols:
        results.setdefault(sym, {"symbol": sym, "error": "no quote"})
    return results


def _fetch_yahoo(symbol: str) -> Dict[str, Any]:
    try:
        from curl_cffi import requests as cffi_requests
    except Exception as exc:
        return {"symbol": symbol, "error": f"Yahoo provider unavailable: {exc}"}

    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        resp = cffi_requests.get(
            url,
            params={"range": "2d", "interval": "1d"},
            impersonate="chrome",
            timeout=15,
        )
        if resp.status_code != 200:
            return {"symbol": symbol, "error": f"HTTP {resp.status_code}"}
        chart = resp.json().get("chart", {})
        results = chart.get("result") or []
        if not results:
            return {"symbol": symbol, "error": "No data returned"}
        meta = results[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        previous = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None:
            return {"symbol": symbol, "error": "No price data available"}
        change = round(price - previous, 4) if previous else None
        change_pct = round(change / previous * 100, 2) if previous and change is not None else None
        return {
            "symbol": symbol,
            "name": meta.get("longName") or meta.get("shortName") or symbol,
            "price": round(price, 4),
            "previous_close": round(previous, 4) if previous else None,
            "change": change,
            "change_pct": change_pct,
            "volume": meta.get("regularMarketVolume"),
            "market_cap": None,
            "currency": meta.get("currency", "USD"),
        }
    except Exception as exc:
        logger.error("Failed to fetch %s: %s", symbol, exc)
        return {"symbol": symbol, "error": str(exc)}


def fetch_price(symbol: str) -> Dict[str, Any]:
    symbol = symbol.strip()
    if sina_code(symbol):
        return fetch_cn_prices([symbol]).get(symbol, {"symbol": symbol, "error": "no quote"})
    return _fetch_yahoo(symbol)


def fetch_cn_price(symbol: str) -> Dict[str, Any]:
    return fetch_price(symbol)


def fetch_prices_batch(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch many symbols. A-shares go out as one HTTP batch."""
    cn = [sym for sym in symbols if sina_code(sym)]
    other = [sym for sym in symbols if sym not in cn]
    results: Dict[str, Dict[str, Any]] = {}
    if cn:
        results.update(fetch_cn_prices(cn))
    for sym in other:
        results[sym] = _fetch_yahoo(sym)
        time.sleep(0.3)
    return results
