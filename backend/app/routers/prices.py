"""Price endpoints — current prices from cache."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PriceCache, PriceOut

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("", response_model=List[PriceOut])
def list_prices(db: Session = Depends(get_db)):
    """Get all cached prices."""
    return db.query(PriceCache).order_by(PriceCache.symbol).all()


@router.get("/quick")
def list_prices_quick(db: Session = Depends(get_db)):
    """Get lightweight price snapshot (symbol/price/change/change_pct/updated_at only)."""
    rows = db.query(PriceCache).order_by(PriceCache.symbol).all()
    return [
        {
            "symbol": r.symbol,
            "price": r.price,
            "change": r.change,
            "change_pct": r.change_pct,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


@router.get("/{symbol}", response_model=PriceOut)
def get_price(symbol: str, db: Session = Depends(get_db)):
    """Get cached price for a single symbol."""
    cached = db.query(PriceCache).filter(PriceCache.symbol == symbol.upper()).first()
    if not cached:
        from ..services.price_service import fetch_price
        from datetime import datetime, timezone
        data = fetch_price(symbol)
        if "error" in data:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=data["error"])
        cached = PriceCache(
            symbol=data["symbol"],
            name=data.get("name", ""),
            price=data["price"],
            previous_close=data.get("previous_close"),
            change=data.get("change"),
            change_pct=data.get("change_pct"),
            volume=data.get("volume"),
            currency=data.get("currency", "USD"),
            updated_at=datetime.now(timezone.utc),
        )
        db.merge(cached)
        db.commit()
    return cached
