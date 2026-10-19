"""Macro Indicators endpoint — VIX, 10Y Treasury, USD Index, S&P 500, NASDAQ."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/macro", tags=["macro"])

# ── Cache ─────────────────────────────────────────────────────────────────────
_macro_cache: List[Dict[str, Any]] = []
_cache_ts: float = 0
_CACHE_TTL = 60  # 60 seconds

MACRO_TICKERS = [
    {"symbol": "^VIX", "name": "VIX 恐慌指数", "short": "VIX"},
    {"symbol": "^TNX", "name": "美债10年利率", "short": "US10Y"},
    {"symbol": "DX-Y.NYB", "name": "美元指数", "short": "DXY"},
    {"symbol": "^GSPC", "name": "标普500", "short": "SPX"},
    {"symbol": "^IXIC", "name": "纳斯达克", "short": "NASDAQ"},
]


class MacroIndicator(BaseModel):
    symbol: str
    name: str
    short_name: str
    price: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    error: Optional[str] = None


def _fetch_macro_data() -> List[Dict[str, Any]]:
    """Fetch macro indicators using yfinance."""
    from curl_cffi import requests as cffi_requests

    session = cffi_requests.Session(impersonate="chrome")
    results = []

    YF_BASE = "https://query2.finance.yahoo.com/v8/finance/chart"

    for ticker_info in MACRO_TICKERS:
        symbol = ticker_info["symbol"]
        try:
            url = f"{YF_BASE}/{symbol}"
            params = {"range": "2d", "interval": "1d"}
            resp = session.get(url, params=params, timeout=10)

            if resp.status_code != 200:
                results.append({
                    "symbol": symbol,
                    "name": ticker_info["name"],
                    "short_name": ticker_info["short"],
                    "error": f"HTTP {resp.status_code}",
                })
                continue

            data = resp.json()
            chart = data.get("chart", {})

            if chart.get("error"):
                results.append({
                    "symbol": symbol,
                    "name": ticker_info["name"],
                    "short_name": ticker_info["short"],
                    "error": str(chart["error"]),
                })
                continue

            result = chart.get("result", [{}])[0]
            meta = result.get("meta", {})
            price = meta.get("regularMarketPrice")
            prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")

            change = None
            change_pct = None
            if price is not None and prev_close is not None and prev_close != 0:
                change = round(price - prev_close, 4)
                change_pct = round((change / prev_close) * 100, 2)

            results.append({
                "symbol": symbol,
                "name": ticker_info["name"],
                "short_name": ticker_info["short"],
                "price": round(price, 2) if price is not None else None,
                "change": change,
                "change_pct": change_pct,
            })

        except Exception as e:
            logger.warning(f"Macro fetch error for {symbol}: {e}")
            results.append({
                "symbol": symbol,
                "name": ticker_info["name"],
                "short_name": ticker_info["short"],
                "error": str(e),
            })

    return results


@router.get("", response_model=List[MacroIndicator])
def get_macro_indicators():
    """Get current macro indicators with daily change."""
    global _macro_cache, _cache_ts

    now = time.time()
    if now - _cache_ts < _CACHE_TTL and _macro_cache:
        return _macro_cache

    data = _fetch_macro_data()
    _macro_cache = data
    _cache_ts = now

    return data
