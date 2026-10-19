"""Asset Snapshot endpoints — historical net worth tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AssetSnapshot, CashAccount, PriceCache
from ..services.portfolio_service import get_holdings
from ..services.exchange_service import get_usd_to_cny

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])


class SnapshotOut(BaseModel):
    date: str
    total_assets_usd: float
    stock_value_usd: float
    cash_usd: float
    cash_cny: float
    details: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/history", response_model=List[SnapshotOut])
def get_snapshot_history(days: int = Query(90, ge=1, le=365), db: Session = Depends(get_db)):
    """Get asset snapshot history for the past N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    snapshots = (
        db.query(AssetSnapshot)
        .filter(AssetSnapshot.date >= cutoff)
        .order_by(AssetSnapshot.date.asc())
        .all()
    )

    result = []
    for s in snapshots:
        result.append(SnapshotOut(
            date=s.date.strftime("%Y-%m-%d") if hasattr(s.date, 'strftime') else str(s.date)[:10],
            total_assets_usd=s.total_assets_usd or 0,
            stock_value_usd=s.stock_value_usd or 0,
            cash_usd=s.cash_usd or 0,
            cash_cny=s.cash_cny or 0,
            details=s.details,
        ))

    return result


def take_daily_snapshot():
    """Take a daily asset snapshot. Called by scheduler at 16:00 CST."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        today = datetime.now(timezone.utc).date()

        # Check if snapshot already exists for today
        existing = (
            db.query(AssetSnapshot)
            .filter(AssetSnapshot.date >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc))
            .filter(AssetSnapshot.date < datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1))
            .first()
        )
        if existing:
            logger.info(f"Snapshot already exists for {today}, skipping")
            return

        # Calculate current total assets
        portfolio = get_holdings(db)
        cash_accounts = db.query(CashAccount).all()
        cash_map = {acc.currency: acc.balance for acc in cash_accounts}
        cash_usd = cash_map.get("USD", 0.0)
        cash_cny = cash_map.get("CNY", 0.0)

        stock_value_usd = 0.0
        stock_value_cny = 0.0
        details_parts = []

        if portfolio and portfolio.holdings:
            for h in portfolio.holdings:
                cached = db.query(PriceCache).filter(PriceCache.symbol == h.symbol).first()
                if cached and cached.currency == "CNY":
                    stock_value_cny += h.market_value
                else:
                    stock_value_usd += h.market_value
                details_parts.append(f"{h.symbol}:{h.market_value:.0f}")

        usd_to_cny = get_usd_to_cny()
        total_assets_usd = (
            stock_value_usd
            + cash_usd
            + (stock_value_cny / usd_to_cny)
            + (cash_cny / usd_to_cny)
        )

        snapshot = AssetSnapshot(
            date=datetime.now(timezone.utc),
            total_assets_usd=round(total_assets_usd, 2),
            stock_value_usd=round(stock_value_usd + stock_value_cny / usd_to_cny, 2),
            cash_usd=round(cash_usd, 2),
            cash_cny=round(cash_cny, 2),
            details="; ".join(details_parts) if details_parts else None,
        )
        db.add(snapshot)
        db.commit()
        logger.info(f"📸 Daily snapshot: ${total_assets_usd:.2f}")

    except Exception as e:
        logger.error(f"Snapshot error: {e}")
    finally:
        db.close()


@router.post("/take")
def manual_snapshot():
    """Manually trigger a daily snapshot."""
    try:
        take_daily_snapshot()
        return {"status": "ok", "message": "Snapshot taken"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
