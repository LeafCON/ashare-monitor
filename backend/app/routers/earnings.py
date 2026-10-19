"""Earnings Calendar endpoints — upcoming and recent earnings for watched symbols.

Uses Yahoo Finance quoteSummary API via curl_cffi (browser impersonation)
with proper cookie/crumb authentication.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlertSetting, EarningsAnalysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/earnings", tags=["earnings"])

# ── Cache ─────────────────────────────────────────────────────────────────────
_earnings_cache: Dict[str, Any] = {}
_cache_ts: float = 0
_CACHE_TTL = 300  # 5 minutes

# Crumb cache
_crumb_cache: Dict[str, Any] = {"crumb": None, "session": None, "ts": 0}
_CRUMB_TTL = 600  # 10 minutes


class EarningsItem(BaseModel):
    symbol: str
    name: str
    report_date: Optional[str] = None
    days_until: Optional[int] = None
    estimate_eps: Optional[float] = None
    actual_eps: Optional[float] = None
    estimate_revenue: Optional[float] = None
    actual_revenue: Optional[float] = None
    beat_miss: Optional[str] = None  # "beat", "miss", "met", None


def _get_crumb_session():
    """Get a curl_cffi session with valid Yahoo Finance cookie and crumb."""
    global _crumb_cache
    now = time.time()

    if now - _crumb_cache["ts"] < _CRUMB_TTL and _crumb_cache["crumb"] and _crumb_cache["session"]:
        return _crumb_cache["session"], _crumb_cache["crumb"]

    from curl_cffi import requests as cffi_requests
    session = cffi_requests.Session(impersonate="chrome")

    try:
        # Step 1: Get cookies by visiting Yahoo Finance
        session.get("https://finance.yahoo.com/quote/AAPL", timeout=15)

        # Step 2: Get crumb
        resp = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        if resp.status_code == 200:
            crumb = resp.text.strip()
            _crumb_cache = {"crumb": crumb, "session": session, "ts": now}
            logger.info(f"Yahoo Finance crumb obtained: {crumb[:10]}...")
            return session, crumb
    except Exception as e:
        logger.warning(f"Crumb fetch error: {e}")

    # Fallback: return session without crumb
    return session, None


def _fetch_earnings_data(symbols: List[Dict[str, str]]) -> Dict[str, List[EarningsItem]]:
    """Fetch earnings data using Yahoo Finance quoteSummary API via curl_cffi."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    session, crumb = _get_crumb_session()
    today = datetime.now().date()
    upcoming: List[EarningsItem] = []
    recent: List[EarningsItem] = []

    def fetch_one(sym_info):
        symbol = sym_info["symbol"]
        name = sym_info["name"]
        items_upcoming = []
        items_recent = []

        try:
            url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
            params = {"modules": "calendarEvents,earningsHistory"}
            if crumb:
                params["crumb"] = crumb

            resp = session.get(url, params=params, timeout=15)

            if resp.status_code != 200:
                logger.debug(f"Earnings API {resp.status_code} for {symbol}")
                return items_upcoming, items_recent

            data = resp.json()
            result = data.get("quoteSummary", {}).get("result", [])
            if not result:
                return items_upcoming, items_recent

            info = result[0]

            # ── Calendar Events (upcoming earnings) ──
            cal = info.get("calendarEvents", {}).get("earnings", {})
            earnings_dates = cal.get("earningsDate", [])
            estimate_eps_val = cal.get("earningsAverage", {}).get("raw")
            estimate_rev_val = cal.get("revenueAverage", {}).get("raw")

            for ed_obj in earnings_dates:
                raw_ts = ed_obj.get("raw")
                if raw_ts:
                    ed = datetime.fromtimestamp(raw_ts, tz=timezone.utc).date()
                    days_until = (ed - today).days
                    if -7 <= days_until <= 90:
                        items_upcoming.append(EarningsItem(
                            symbol=symbol,
                            name=name,
                            report_date=str(ed),
                            days_until=days_until,
                            estimate_eps=estimate_eps_val,
                            estimate_revenue=estimate_rev_val,
                        ))

            # ── Earnings History (recent beat/miss) ──
            hist = info.get("earningsHistory", {}).get("history", [])
            for entry in hist[-4:]:  # Last 4 quarters
                q_date = entry.get("quarter", {}).get("raw")
                actual_raw = entry.get("epsActual", {}).get("raw")
                estimate_raw = entry.get("epsEstimate", {}).get("raw")
                surprise_pct = entry.get("surprisePercent", {}).get("raw")  # e.g. 0.0366

                if q_date:
                    report_date = datetime.fromtimestamp(q_date, tz=timezone.utc).date()
                else:
                    report_date = None

                beat_miss = None
                if actual_raw is not None and estimate_raw is not None:
                    if actual_raw > estimate_raw:
                        beat_miss = "beat"
                    elif actual_raw < estimate_raw:
                        beat_miss = "miss"
                    else:
                        beat_miss = "met"

                # 显示日期：优先用 quarter（财季截止），备注这是财季日期
                items_recent.append(EarningsItem(
                    symbol=symbol,
                    name=name,
                    report_date=str(report_date) if report_date else None,
                    actual_eps=actual_raw,
                    estimate_eps=estimate_raw,
                    beat_miss=beat_miss,
                ))

        except Exception as e:
            logger.warning(f"Earnings fetch error for {symbol}: {e}")

        return items_upcoming, items_recent

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_one, s): s for s in symbols}
        for future in as_completed(futures, timeout=60):
            try:
                up, rec = future.result()
                upcoming.extend(up)
                recent.extend(rec)
            except Exception as e:
                logger.warning(f"Earnings thread error: {e}")

    # Sort
    upcoming.sort(key=lambda x: x.report_date or "9999")
    recent.sort(key=lambda x: x.report_date or "0000", reverse=True)

    return {"upcoming": upcoming, "recent": recent[:20]}


def _get_watched_symbols(db: Session) -> List[Dict[str, str]]:
    """Get unique symbols from alert_settings (primary only, skip CN stocks for earnings)."""
    alerts = db.query(AlertSetting).filter(AlertSetting.is_primary == True).all()
    seen = set()
    symbols = []
    for a in alerts:
        if a.symbol not in seen:
            # Skip CN stocks (they don't have earnings on Yahoo Finance)
            if a.symbol.endswith('.SS') or a.symbol.endswith('.SZ'):
                continue
            seen.add(a.symbol)
            symbols.append({"symbol": a.symbol, "name": a.name or a.symbol})
    return symbols


@router.get("/upcoming")
def get_upcoming_earnings(db: Session = Depends(get_db)):
    """Get upcoming earnings dates for watched symbols (next 30-90 days)."""
    global _earnings_cache, _cache_ts

    now = time.time()
    if now - _cache_ts < _CACHE_TTL and "upcoming" in _earnings_cache:
        return _earnings_cache["upcoming"]

    symbols = _get_watched_symbols(db)
    if not symbols:
        return []

    data = _fetch_earnings_data(symbols)
    _earnings_cache = data
    _cache_ts = now

    return data.get("upcoming", [])


class EarningsAnalysisCreate(BaseModel):
    symbol: str
    fiscal_quarter: str
    report_date: Optional[str] = None
    eps_actual: Optional[float] = None
    eps_estimate: Optional[float] = None
    eps_surprise_pct: Optional[float] = None
    revenue_actual: Optional[float] = None
    revenue_estimate: Optional[float] = None
    revenue_surprise_pct: Optional[float] = None
    guidance: Optional[str] = None
    verdict: Optional[str] = None
    short_term: Optional[str] = None
    analysis: Optional[str] = None
    holding_advice: Optional[str] = None
    price_reaction_pct: Optional[float] = None


@router.get("/analysis")
def get_earnings_analysis(db: Session = Depends(get_db)):
    """Get all 老李 earnings analysis records, latest first."""
    records = db.query(EarningsAnalysis).order_by(EarningsAnalysis.report_date.desc()).all()
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "fiscal_quarter": r.fiscal_quarter,
            "report_date": r.report_date,
            "eps_actual": r.eps_actual,
            "eps_estimate": r.eps_estimate,
            "eps_surprise_pct": r.eps_surprise_pct,
            "revenue_actual": r.revenue_actual,
            "revenue_estimate": r.revenue_estimate,
            "revenue_surprise_pct": r.revenue_surprise_pct,
            "guidance": r.guidance,
            "verdict": r.verdict,
            "short_term": r.short_term,
            "analysis": r.analysis,
            "holding_advice": r.holding_advice,
            "price_reaction_pct": r.price_reaction_pct,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in records
    ]


@router.post("/analysis")
def upsert_earnings_analysis(payload: EarningsAnalysisCreate, db: Session = Depends(get_db)):
    """Insert or update an earnings analysis record (upsert by symbol+fiscal_quarter)."""
    existing = db.query(EarningsAnalysis).filter(
        EarningsAnalysis.symbol == payload.symbol,
        EarningsAnalysis.fiscal_quarter == payload.fiscal_quarter,
    ).first()

    if existing:
        for k, v in payload.dict(exclude_none=True).items():
            setattr(existing, k, v)
    else:
        existing = EarningsAnalysis(**payload.dict())
        db.add(existing)

    db.commit()
    db.refresh(existing)
    return {"ok": True, "id": existing.id}


@router.get("/recent")
def get_recent_earnings(db: Session = Depends(get_db)):
    """Get recent earnings results (beat/miss) for watched symbols."""
    global _earnings_cache, _cache_ts

    now = time.time()
    if now - _cache_ts < _CACHE_TTL and "recent" in _earnings_cache:
        return _earnings_cache["recent"]

    symbols = _get_watched_symbols(db)
    if not symbols:
        return []

    data = _fetch_earnings_data(symbols)
    _earnings_cache = data
    _cache_ts = now

    return data.get("recent", [])
