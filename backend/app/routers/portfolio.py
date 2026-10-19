"""Portfolio & holdings endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PortfolioOut
from ..services.portfolio_service import get_holdings

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioOut)
def portfolio(db: Session = Depends(get_db)):
    """Get current portfolio holdings with P&L."""
    return get_holdings(db)
