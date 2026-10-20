"""Decision status for A-shares, Hong Kong, US stocks, and crypto."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..agent.live import market_status, scan
from ..agent.nightly import review
from ..agent.reflex import HF_MODEL_ID, load_reflex
from ..agent.risk import MAX_DAILY_LOSS, MAX_DRAWDOWN, MAX_POSITION_FRACTION, armed, kill_switch_on
from ..database import get_db

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/status")
def status():
    reflex = load_reflex()
    markets = market_status()
    return {
        "armed": armed(),
        "kill_switch": kill_switch_on(),
        "backend": getattr(reflex, "backend", "unknown"),
        "hf_model": HF_MODEL_ID,
        "markets": markets,
        "live_orders": any(item["ready"] for item in markets.values()) and armed(),
        "waiting": all(item["waiting"] for item in markets.values()),
        "max_drawdown": MAX_DRAWDOWN,
        "max_daily_loss": MAX_DAILY_LOSS,
        "max_position_fraction": MAX_POSITION_FRACTION,
    }


@router.get("/review")
def nightly():
    return review()


@router.post("/tick")
def tick(db: Session = Depends(get_db)):
    """Judge every market. Send only where that market's trading interface is configured."""
    return scan(db)
