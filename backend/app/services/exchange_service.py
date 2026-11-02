"""Exchange rate service — centralized USD/CNY rate with 5-minute cache."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_FALLBACK_RATE = 7.2
_CACHE_TTL = 300  # 5 minutes

_cache_value: float = _FALLBACK_RATE
_cache_time: float = 0
_refreshing = False


def _refresh() -> None:
    global _cache_value, _cache_time, _refreshing
    try:
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(impersonate="chrome")
        resp = session.get(
            "https://query2.finance.yahoo.com/v8/finance/chart/CNY=X",
            params={"range": "1d", "interval": "1d"},
            timeout=4,
        )
        if resp.status_code == 200:
            meta = ((resp.json().get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
            rate = meta.get("regularMarketPrice")
            if rate and 5 < rate < 10:
                _cache_value = round(rate, 4)
                _cache_time = time.time()
                logger.info(f"FX rate updated: USD/CNY = {_cache_value}")
    except Exception as exc:
        logger.warning(f"FX rate fetch error: {exc}")
        if _cache_time == 0:
            _cache_time = time.time()
    finally:
        _refreshing = False


def get_usd_to_cny() -> float:
    """Return the last rate immediately. A refresh never blocks the page."""
    import threading
    global _refreshing
    now = time.time()
    if (_cache_time == 0 or now - _cache_time >= _CACHE_TTL) and not _refreshing:
        _refreshing = True
        threading.Thread(target=_refresh, daemon=True).start()
    return _cache_value
