"""Portfolio & holdings endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlertSetting, MarketType, PortfolioOut, PriceCache, TradeAction, Transaction, gen_id, utcnow
from ..services.eastmoney import KNOWN_SECIDS
from ..services.portfolio_service import get_holdings
from ..services.price_service import fetch_price
from ..symbols import normalize_symbol

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class HoldingInput(BaseModel):
    symbol: str
    name: str = ""
    shares: float
    cost_price: float
    market: str = "cn"


def _remember_symbol(db: Session, symbol: str, name: str, market: str, secid: str | None) -> None:
    existing = db.query(AlertSetting).filter(
        AlertSetting.symbol == symbol,
        AlertSetting.is_primary == True,  # noqa: E712
    ).first()
    if existing:
        if name:
            existing.name = name
        if secid:
            existing.secid = secid
        return
    db.add(AlertSetting(
        symbol=symbol,
        name=name or symbol,
        market=MarketType(market),
        secid=secid,
        enabled=True,
        is_primary=True,
    ))


def _cache_price(db: Session, symbol: str, name: str) -> None:
    quote = fetch_price(symbol)
    if not quote or quote.get("error") or quote.get("price") is None:
        return
    db.merge(PriceCache(
        symbol=symbol,
        name=name or quote.get("name") or symbol,
        price=quote["price"],
        previous_close=quote.get("previous_close"),
        change=quote.get("change"),
        change_pct=quote.get("change_pct"),
        volume=quote.get("volume"),
        currency=quote.get("currency") or ("CNY" if symbol.endswith((".SS", ".SZ", ".BJ")) else "HKD" if symbol.endswith(".HK") else "USD"),
        updated_at=utcnow(),
    ))


@router.get("", response_model=PortfolioOut)
def portfolio(db: Session = Depends(get_db)):
    """Get current portfolio holdings with P&L."""
    return get_holdings(db)


@router.post("/holdings", response_model=PortfolioOut)
def set_holding(payload: HoldingInput, db: Session = Depends(get_db)):
    """Set a position directly. This does not move the cash accounts."""
    if payload.shares < 0 or payload.cost_price < 0:
        raise HTTPException(status_code=400, detail="股数和成本价不能为负数")
    symbol, market = normalize_symbol(payload.symbol, payload.market)
    name = (payload.name or "").strip()
    secid = KNOWN_SECIDS.get(symbol) or (f"116.{symbol[:-3]}" if symbol.endswith(".HK") else None)
    db.query(Transaction).filter(Transaction.symbol == symbol).delete()
    if payload.shares > 0:
        db.add(Transaction(
            id=gen_id(),
            date=utcnow(),
            symbol=symbol,
            name=name or symbol,
            action=TradeAction.buy,
            price=payload.cost_price,
            shares=payload.shares,
            amount=round(payload.shares * payload.cost_price, 4),
            fee=0,
            notes="手动持仓",
        ))
        _remember_symbol(db, symbol, name, market, secid)
        _cache_price(db, symbol, name)
    db.commit()
    return get_holdings(db)


@router.delete("/holdings/{symbol}", response_model=PortfolioOut)
def clear_holding(symbol: str, db: Session = Depends(get_db)):
    """Remove a manually recorded position."""
    normalized, _market = normalize_symbol(symbol, "us")
    db.query(Transaction).filter(Transaction.symbol == normalized).delete()
    db.commit()
    return get_holdings(db)

