"""Order routing for every market. A market with no trading interface waits."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import urllib.parse

import requests

BINANCE = os.getenv("BINANCE_API_BASE", "https://api.binance.com")


def credentials() -> tuple[str, str]:
    return os.getenv("BINANCE_API_KEY", "").strip(), os.getenv("BINANCE_API_SECRET", "").strip()


def stock_credentials() -> tuple[str, str, str]:
    return (
        os.getenv("STOCK_BROKER_API_BASE", "").strip().rstrip("/"),
        os.getenv("STOCK_BROKER_API_KEY", "").strip(),
        os.getenv("STOCK_BROKER_API_SECRET", "").strip(),
    )


def market_of_symbol(symbol: str) -> str:
    text = (symbol or "").upper()
    if text.endswith(".HK"):
        return "hk"
    if text.endswith((".SS", ".SZ", ".BJ")):
        return "cn"
    if text.endswith(("USDT", "USDC")):
        return "crypto"
    return "us"


def venue_ready(market: str) -> bool:
    if market == "crypto":
        key, secret = credentials()
        return bool(key and secret)
    base, key, secret = stock_credentials()
    allowed = {item.strip() for item in os.getenv("STOCK_BROKER_MARKETS", "cn,hk,us").split(",") if item.strip()}
    return bool(base and key and secret and market in allowed)


def _signed_binance(path: str, params: dict, method: str) -> dict:
    key, secret = credentials()
    if not key or not secret:
        raise RuntimeError("BINANCE_API_KEY and BINANCE_API_SECRET are missing")
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = urllib.parse.urlencode(params)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{BINANCE}{path}?{query}&signature={signature}"
    response = requests.request(method, url, headers={"X-MBX-APIKEY": key}, timeout=10)
    body = response.json()
    if response.status_code >= 400:
        raise RuntimeError(body.get("msg") or response.text[:200])
    return body


def fetch_book(symbol: str) -> tuple[list, list, int]:
    sent = int(time.time() * 1000)
    response = requests.get(f"{BINANCE}/api/v3/depth", params={"symbol": symbol, "limit": 20}, timeout=10)
    response.raise_for_status()
    data = response.json()
    bids = [(float(price), float(qty), sent) for price, qty in data.get("bids") or []]
    asks = [(float(price), float(qty), sent) for price, qty in data.get("asks") or []]
    return bids, asks, sent


def account_quote(asset: str = "USDT") -> float:
    body = _signed_binance("/api/v3/account", {}, "GET")
    for row in body.get("balances") or []:
        if row.get("asset") == asset:
            return float(row.get("free") or 0)
    return 0.0


def submit_market(symbol: str, side: str, quote_qty: float, market: str) -> dict:
    if market == "crypto":
        params = {
            "symbol": symbol,
            "side": "BUY" if side == "buy" else "SELL",
            "type": "MARKET",
            "quoteOrderQty": f"{quote_qty:.2f}",
        }
        return _signed_binance("/api/v3/order", params, "POST")
    base, key, secret = stock_credentials()
    if not base or not key or not secret:
        raise RuntimeError("stock broker interface is missing")
    payload = {
        "symbol": symbol,
        "side": side,
        "quote_qty": round(quote_qty, 2),
        "market": market,
        "timestamp": int(time.time() * 1000),
    }
    query = urllib.parse.urlencode(payload)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    response = requests.post(
        f"{base}/order",
        json={**payload, "signature": signature},
        headers={"Authorization": f"Bearer {key}"},
        timeout=10,
    )
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text[:200]}
    if response.status_code >= 400:
        raise RuntimeError(str(body)[:200])
    return body
