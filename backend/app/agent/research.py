"""Public quotes only. Missing fields stay missing."""

from __future__ import annotations

from datetime import datetime, timezone

import requests

SESSION = requests.Session()
SESSION.trust_env = False


def _get(url: str, params: dict | None = None) -> dict | None:
    try:
        response = SESSION.get(url, params=params, timeout=4)
        response.raise_for_status()
        body = response.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def public_facts() -> list[dict]:
    """BTC and ETH quotes from Binance's public endpoints. Nothing else is filled in."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    for symbol, label in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")):
        quote = _get("https://api.binance.com/api/v3/ticker/24hr", {"symbol": symbol})
        if not quote or quote.get("lastPrice") is None:
            rows.append({"name": f"{label} 现价", "missing": True, "source": "https://api.binance.com/api/v3/ticker/24hr"})
            continue
        rows.append({
            "name": f"{label} 现价",
            "value": quote.get("lastPrice"),
            "source": "Binance public ticker/24hr",
            "as_of": now,
        })
        rows.append({
            "name": f"{label} 24h 涨跌幅",
            "value": str(quote.get("priceChangePercent")) + "%",
            "source": "Binance public ticker/24hr",
            "as_of": now,
        })
    funding = _get("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})
    if funding and funding.get("lastFundingRate") is not None:
        rows.append({
            "name": "BTC 永续资金费率",
            "value": funding.get("lastFundingRate"),
            "source": "Binance public premiumIndex",
            "as_of": now,
        })
    else:
        rows.append({"name": "BTC 永续资金费率", "missing": True, "source": "https://fapi.binance.com/fapi/v1/premiumIndex"})
    return rows
