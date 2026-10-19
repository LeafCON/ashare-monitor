"""Exchange rate service — centralized USD/CNY rate with 5-minute cache."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_FALLBACK_RATE = 7.2
_CACHE_TTL = 300  # 5 minutes

_cache_value: float = _FALLBACK_RATE
_cache_time: float = 0


def get_usd_to_cny() -> float:
    """Get real-time USD/CNY exchange rate from Yahoo Finance.

    Returns cached value if within 5 minutes. Falls back to 7.2 on error.
    """
    global _cache_value, _cache_time

    now = time.time()
    if now - _cache_time < _CACHE_TTL:
        return _cache_value

    try:
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(impersonate="chrome")
        url = "https://query2.finance.yahoo.com/v8/finance/chart/CNY=X"
        resp = session.get(url, params={"range": "1d", "interval": "1d"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})
            rate = meta.get("regularMarketPrice")
            if rate and 5 < rate < 10:  # Sanity check
                _cache_value = round(rate, 4)
                _cache_time = now
                logger.info(f"FX rate updated: USD/CNY = {_cache_value}")
    except Exception as e:
        logger.warning(f"FX rate fetch error: {e}")

    return _cache_value
