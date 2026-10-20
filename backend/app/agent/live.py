"""Scan every market. A venue with no interface contributes a wait, not an order."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..models import AlertSetting, PriceCache
from .execute import account_quote, fetch_book, market_of_symbol, venue_ready
from .loop import run_tick
from .state_engine import build_snapshot

STATE = Path(__file__).resolve().parents[3] / "data" / "agent_state.json"
CST = ZoneInfo("Asia/Shanghai")
MARKETS = ("cn", "hk", "us", "crypto")


def market_status() -> dict:
    return {
        market: {"ready": venue_ready(market), "waiting": not venue_ready(market)}
        for market in MARKETS
    }


def _load_state() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state), encoding="utf-8")


def _equity_fields(market: str, symbol: str, mid: float) -> tuple[float, float, float]:
    if market != "crypto":
        quote = float(os.getenv("STOCK_BROKER_QUOTE_BALANCE", "0") or 0)
        return quote, 0.0, quote
    quote = account_quote("USDT")
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    base_free = account_quote(base)
    return quote, base_free, quote + base_free * mid


def _snapshot_from_price(symbol: str, price: float, market: str) -> object:
    sent = int(time.time() * 1000)
    decision_ts = sent + 1
    bid = price * 0.9995
    ask = price * 1.0005
    quote, base_free, equity = _equity_fields(market, symbol, price) if venue_ready(market) else (0.0, 0.0, 1.0)
    state = _load_state()
    book = state.setdefault(market, {})
    today = datetime.now(CST).date().isoformat()
    if book.get("day") != today:
        book["day"] = today
        book["day_start"] = equity
    peak = max(float(book.get("peak") or equity), equity)
    book["peak"] = peak
    _save_state(state)
    snapshot = build_snapshot(
        symbol=symbol,
        decision_ts=decision_ts,
        bids=[(bid, 1.0, sent)],
        asks=[(ask, 1.0, sent)],
        mids=[(price, sent)],
        inventory=base_free,
        equity=max(equity, 1.0),
        peak_equity=max(peak, 1.0),
        day_start_equity=max(float(book.get("day_start") or equity), 1.0),
        position_notional=base_free * price,
    )
    return snapshot, quote


def scan(db: Session) -> dict:
    rows = []
    seen = set()
    alerts = db.query(AlertSetting).filter(AlertSetting.is_primary == True).all()  # noqa: E712
    for alert in alerts:
        if alert.symbol in seen:
            continue
        seen.add(alert.symbol)
        market = alert.market.value if alert.market else market_of_symbol(alert.symbol)
        if not venue_ready(market):
            rows.append({"symbol": alert.symbol, "market": market, "waiting": True, "executed": False, "detail": "交易接口未配置"})
            continue
        cached = db.query(PriceCache).filter(PriceCache.symbol == alert.symbol).first()
        if not cached or not cached.price:
            rows.append({"symbol": alert.symbol, "market": market, "waiting": False, "executed": False, "detail": "还没有行情"})
            continue
        snapshot, quote = _snapshot_from_price(alert.symbol, cached.price, market)
        row = run_tick(snapshot, quote_balance=quote, market=market)
        row["market"] = market
        rows.append(row)

    crypto_symbols = [item.strip().upper() for item in os.getenv("AGENT_SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if item.strip()]
    if not venue_ready("crypto"):
        for symbol in crypto_symbols:
            rows.append({"symbol": symbol, "market": "crypto", "waiting": True, "executed": False, "detail": "交易接口未配置"})
    else:
        for symbol in crypto_symbols:
            bids, asks, sent = fetch_book(symbol)
            if not bids or not asks:
                rows.append({"symbol": symbol, "market": "crypto", "waiting": False, "executed": False, "detail": "订单簿为空"})
                continue
            mid = (bids[0][0] + asks[0][0]) / 2
            quote, base_free, equity = _equity_fields("crypto", symbol, mid)
            state = _load_state()
            book = state.setdefault("crypto", {})
            today = datetime.now(CST).date().isoformat()
            if book.get("day") != today:
                book["day"] = today
                book["day_start"] = equity
            peak = max(float(book.get("peak") or equity), equity)
            book["peak"] = peak
            _save_state(state)
            snapshot = build_snapshot(
                symbol=symbol,
                decision_ts=int(time.time() * 1000),
                bids=bids[:10],
                asks=asks[:10],
                mids=[(mid, sent)],
                inventory=base_free,
                equity=max(equity, 1.0),
                peak_equity=max(peak, 1.0),
                day_start_equity=max(float(book.get("day_start") or equity), 1.0),
                position_notional=base_free * mid,
            )
            row = run_tick(snapshot, quote_balance=quote, market="crypto")
            row["market"] = "crypto"
            rows.append(row)
    waiting = all(row.get("waiting") for row in rows) if rows else True
    return {"waiting": waiting, "results": rows}
