"""Portfolio & holdings endpoints."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
    shares: float | None = None
    cost_price: float | None = None
    cost_amount: float | None = None
    market_amount: float | None = None
    mode: str = "shares"
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
    shares, price, manual_value, note = _position_numbers(payload)
    symbol, market = normalize_symbol(payload.symbol, payload.market)
    if len(symbol) > 20:
        symbol = symbol[:20]
    name = (payload.name or "").strip()
    secid = KNOWN_SECIDS.get(symbol) or (f"116.{symbol[:-3]}" if symbol.endswith(".HK") else None)
    db.query(Transaction).filter(Transaction.symbol == symbol).delete()
    if shares > 0:
        db.add(Transaction(
            id=gen_id(),
            date=utcnow(),
            symbol=symbol,
            name=name or symbol,
            action=TradeAction.buy,
            price=price,
            shares=shares,
            amount=round(shares * price, 4),
            fee=0,
            notes=note,
            manual_value=manual_value,
        ))
        _remember_symbol(db, symbol, name, market, secid)
        if manual_value is None:
            _cache_price(db, symbol, name)
    db.commit()
    return get_holdings(db)


def _position_numbers(payload: HoldingInput) -> tuple[float, float, float | None, str]:
    if payload.mode == "amount":
        cost = payload.cost_amount
        if cost is None or cost <= 0:
            raise HTTPException(status_code=400, detail="请填写持有金额")
        current = payload.market_amount if payload.market_amount and payload.market_amount > 0 else cost
        return 1.0, float(cost), float(current), "金额持仓"
    if payload.shares is None or payload.cost_price is None:
        raise HTTPException(status_code=400, detail="请填写股数和成本价")
    if payload.shares < 0 or payload.cost_price < 0:
        raise HTTPException(status_code=400, detail="股数和成本价不能为负数")
    return float(payload.shares), float(payload.cost_price), None, "手动持仓"


@router.get("/agents")
def local_agents():
    """AI servers and model files found on this computer."""
    from ..agent.discover import discover_agents
    return discover_agents()


class ShotPath(BaseModel):
    path: str
    agent: str = ""
    model: str = ""
    api_url: str = ""
    api_key: str = ""


_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


@router.post("/holdings/read-path")
def read_holding_path(payload: ShotPath):
    """Read a screenshot from a path the desktop window received. Browser drops do not include that path."""
    from pathlib import Path
    from ..services.vision_holdings import read_screenshot
    image = Path(payload.path)
    mime = _IMAGE_MIME.get(image.suffix.lower())
    if not mime:
        raise HTTPException(status_code=400, detail="请放入图片文件")
    if not image.is_file():
        raise HTTPException(status_code=400, detail="找不到这张图片")
    data = image.read_bytes()
    if len(data) > 6_000_000:
        raise HTTPException(status_code=400, detail="截图请小于 6MB")
    try:
        rows = read_screenshot(data, mime, payload.agent, payload.model, payload.api_url, payload.api_key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc
    return {"holdings": rows}


@router.post("/holdings/read-image")
async def read_holding_image(
    image: UploadFile = File(...),
    agent: str = Form(""),
    model: str = Form(""),
    api_url: str = Form(""),
    api_key: str = Form(""),
):
    """Turn a broker screenshot into holding rows. Nothing is saved until the user confirms."""
    from ..services.vision_holdings import read_screenshot, vision_config
    mime = image.content_type or "image/png"
    if not mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片")
    data = await image.read()
    cfg = vision_config()
    try:
        rows = read_screenshot(data, mime, agent, model, api_url, api_key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc
    return {"holdings": rows, "configured": bool(agent or cfg["key"])}


@router.delete("/holdings/{symbol}", response_model=PortfolioOut)
def clear_holding(symbol: str, db: Session = Depends(get_db)):
    """Remove a manually recorded position."""
    normalized, _market = normalize_symbol(symbol, "us")
    db.query(Transaction).filter(Transaction.symbol == normalized).delete()
    db.commit()
    return get_holdings(db)

