"""Watchlist endpoints — convenience wrapper around AlertSettings.

Provides the /api/watchlist endpoints that the stock-portfolio skill expects:
  GET    /api/watchlist              — list watchlist (alert settings + current prices)
  POST   /api/watchlist              — add/update a watchlist item
  PUT    /api/watchlist/{symbol}     — update a watchlist item by symbol (explicit, allows clearing fields)
  DELETE /api/watchlist/{id}         — remove from watchlist by ID
  DELETE /api/watchlist/symbol/{sym} — remove from watchlist by symbol
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AlertSetting,
    AlertSettingCreate,
    AlertSettingOut,
    MarketType,
    PriceCache,
)
from ..symbols import normalize_symbol

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class WatchlistItemOut(BaseModel):
    """Watchlist item with current price info."""
    id: int
    symbol: str
    name: str
    market: MarketType
    target_buy: Optional[float] = None
    target_sell: Optional[float] = None
    stop_loss: Optional[float] = None
    enabled: bool
    # Price info (from cache, may be None if not yet fetched)
    current_price: Optional[float] = None
    change_pct: Optional[float] = None
    currency: Optional[str] = None

    class Config:
        from_attributes = True


class WatchlistAddRequest(BaseModel):
    """Request to add a stock to watchlist."""
    symbol: str
    name: str = ""
    market: MarketType = MarketType.us
    target_buy: Optional[float] = None
    target_sell: Optional[float] = None
    stop_loss: Optional[float] = None
    secid: Optional[str] = None
    enabled: bool = True


class WatchlistUpdateRequest(BaseModel):
    """Request to update a watchlist item. Only provided fields are updated.
    Use explicit null to clear a field (e.g. {"target_buy": null})."""
    name: Optional[str] = None
    target_buy: Optional[float] = None
    target_sell: Optional[float] = None
    stop_loss: Optional[float] = None
    enabled: Optional[bool] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[WatchlistItemOut])
def get_watchlist(db: Session = Depends(get_db)):
    """Get watchlist with current prices. Only returns primary alerts."""
    alerts = (
        db.query(AlertSetting)
        .filter(AlertSetting.is_primary == True)
        .order_by(AlertSetting.symbol)
        .all()
    )
    result = []
    for alert in alerts:
        cached = db.query(PriceCache).filter(PriceCache.symbol == alert.symbol).first()
        item = WatchlistItemOut(
            id=alert.id,
            symbol=alert.symbol,
            name=alert.name,
            market=alert.market,
            target_buy=alert.target_buy,
            target_sell=alert.target_sell,
            stop_loss=alert.stop_loss,
            enabled=alert.enabled,
            current_price=cached.price if cached else None,
            change_pct=cached.change_pct if cached else None,
            currency=cached.currency if cached else None,
        )
        result.append(item)
    return result


@router.post("", response_model=WatchlistItemOut, status_code=201)
def add_to_watchlist(payload: WatchlistAddRequest, db: Session = Depends(get_db)):
    """Add or update a stock in watchlist."""
    symbol, inferred = normalize_symbol(payload.symbol, payload.market.value if payload.market else "us")
    if inferred == "cn":
        payload.market = MarketType.cn
    existing = db.query(AlertSetting).filter(
        AlertSetting.symbol == symbol,
        AlertSetting.is_primary == True,
    ).first()

    if existing:
        # Update existing entry
        if payload.name:
            existing.name = payload.name
        if payload.market:
            existing.market = payload.market
        if payload.target_buy is not None:
            existing.target_buy = payload.target_buy
        if payload.target_sell is not None:
            existing.target_sell = payload.target_sell
        if payload.stop_loss is not None:
            existing.stop_loss = payload.stop_loss
        existing.enabled = payload.enabled
        if payload.secid:
            existing.secid = payload.secid
        db.commit()
        db.refresh(existing)
        alert = existing
    else:
        alert = AlertSetting(
            symbol=symbol,
            name=payload.name or symbol,
            market=payload.market,
            target_buy=payload.target_buy,
            target_sell=payload.target_sell,
            stop_loss=payload.stop_loss,
            secid=payload.secid,
            enabled=payload.enabled,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

    from ..services.price_service import fetch_prices_batch
    from ..models import PriceCache
    from datetime import datetime, timezone
    quote_map = fetch_prices_batch([alert.symbol], {alert.symbol: alert.secid} if alert.secid else None)
    quote = quote_map.get(alert.symbol) or {}
    if quote.get("price") is not None:
        db.merge(PriceCache(
            symbol=alert.symbol,
            name=alert.name or quote.get("name") or alert.symbol,
            price=quote["price"],
            previous_close=quote.get("previous_close"),
            change=quote.get("change"),
            change_pct=quote.get("change_pct"),
            volume=quote.get("volume"),
            currency=quote.get("currency") or ("CNY" if alert.market == MarketType.cn else "USD"),
            updated_at=datetime.now(timezone.utc),
        ))
        db.commit()

    # Attach cached price if available
    cached = db.query(PriceCache).filter(PriceCache.symbol == alert.symbol).first()
    return WatchlistItemOut(
        id=alert.id,
        symbol=alert.symbol,
        name=alert.name,
        market=alert.market,
        target_buy=alert.target_buy,
        target_sell=alert.target_sell,
        stop_loss=alert.stop_loss,
        enabled=alert.enabled,
        current_price=cached.price if cached else None,
        change_pct=cached.change_pct if cached else None,
        currency=cached.currency if cached else None,
    )


@router.put("/{symbol}", response_model=WatchlistItemOut)
def update_watchlist_item(
    symbol: str,
    payload: WatchlistUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update a watchlist item by symbol.

    Only fields present in the JSON body are updated.
    Send ``null`` explicitly to clear a price target, e.g. ``{"target_buy": null}``.
    """
    alert = (
        db.query(AlertSetting)
        .filter(AlertSetting.symbol == symbol.upper())
        .first()
    )
    if not alert:
        raise HTTPException(status_code=404, detail=f"Watchlist item not found: {symbol}")

    # Use model_fields_set (Pydantic v2) to know which fields the caller
    # explicitly included in the request body (including explicit nulls).
    provided = payload.model_fields_set
    if "name" in provided and payload.name is not None:
        alert.name = payload.name
    if "target_buy" in provided:
        alert.target_buy = payload.target_buy
    if "target_sell" in provided:
        alert.target_sell = payload.target_sell
    if "stop_loss" in provided:
        alert.stop_loss = payload.stop_loss
    if "enabled" in provided and payload.enabled is not None:
        alert.enabled = payload.enabled

    db.commit()
    db.refresh(alert)

    cached = db.query(PriceCache).filter(PriceCache.symbol == alert.symbol).first()
    return WatchlistItemOut(
        id=alert.id,
        symbol=alert.symbol,
        name=alert.name,
        market=alert.market,
        target_buy=alert.target_buy,
        target_sell=alert.target_sell,
        stop_loss=alert.stop_loss,
        enabled=alert.enabled,
        current_price=cached.price if cached else None,
        change_pct=cached.change_pct if cached else None,
        currency=cached.currency if cached else None,
    )


@router.delete("/symbol/{symbol}", status_code=204)
def remove_from_watchlist_by_symbol(symbol: str, db: Session = Depends(get_db)):
    """Remove a stock from watchlist by symbol."""
    alert = (
        db.query(AlertSetting)
        .filter(AlertSetting.symbol == symbol.upper())
        .first()
    )
    if not alert:
        raise HTTPException(
            status_code=404,
            detail=f"Watchlist item not found: {symbol}",
        )
    db.delete(alert)
    db.commit()


@router.delete("/{item_id}", status_code=204)
def remove_from_watchlist(item_id: int, db: Session = Depends(get_db)):
    """Remove a stock from watchlist by ID."""
    alert = db.query(AlertSetting).filter(AlertSetting.id == item_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    db.delete(alert)
    db.commit()
