"""Macro indicators. Prices come from Eastmoney, which answers on this network."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.eastmoney import fetch_secids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/macro", tags=["macro"])

_macro_cache: List[Dict[str, Any]] = []
_cache_ts: float = 0
_CACHE_TTL = 60

MACRO_TICKERS = [
    {"symbol": "SPX", "name": "标普500", "short": "SPX", "secid": "100.SPX"},
    {"symbol": "NDX", "name": "纳斯达克", "short": "NASDAQ", "secid": "100.NDX"},
    {"symbol": "DJI", "name": "道琼斯", "short": "DJI", "secid": "100.DJIA"},
    {"symbol": "DXY", "name": "美元指数", "short": "DXY", "secid": "100.UDI"},
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
    pairs = [(item["symbol"], item["secid"]) for item in MACRO_TICKERS]
    quotes = fetch_secids(pairs)
    results = []
    for item in MACRO_TICKERS:
        quote = quotes.get(item["symbol"]) or {}
        if quote.get("price") is None:
            logger.warning("Macro quote missing for %s: %s", item["symbol"], quote.get("error"))
            continue
        results.append({
            "symbol": item["symbol"],
            "name": item["name"],
            "short_name": item["short"],
            "price": quote["price"],
            "change": quote.get("change"),
            "change_pct": quote.get("change_pct"),
        })
    return results


@router.get("", response_model=List[MacroIndicator])
def get_macro_indicators():
    """Current index levels. Cards without a price are omitted."""
    global _macro_cache, _cache_ts
    now = time.time()
    if now - _cache_ts < _CACHE_TTL and _macro_cache:
        return _macro_cache
    data = _fetch_macro_data()
    _macro_cache = data
    _cache_ts = now
    return data
