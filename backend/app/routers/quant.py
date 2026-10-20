"""Quant signal endpoints — fundamental valuation analysis."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..models import QuantSignal, QuantSignalOut, QuantSignalSummary, AlertSetting, PriceCache

logger = logging.getLogger("quant")

router = APIRouter(prefix="/api/quant", tags=["quant"])


def _get_symbol_mappings(db: Session) -> tuple[dict[str, str], dict[str, str]]:
    """Build symbol→name and symbol→market mappings from AlertSetting (primary only)."""
    alerts = db.query(AlertSetting).filter(AlertSetting.is_primary == True).all()
    names = {a.symbol: a.name for a in alerts}
    markets = {a.symbol: a.market.value for a in alerts}
    return names, markets

# Metric weights for composite score (lower percentile = cheaper = higher score)
METRIC_WEIGHTS = {
    "pe_ttm": 0.35,
    "pb": 0.25,
    "roe": 0.15,       # Higher is better (invert in scoring)
    "gross_margin": 0.10,  # Higher is better
    "revenue_growth": 0.15,  # Higher is better
}

# Metrics where higher = better (invert percentile for scoring)
HIGHER_IS_BETTER = {"roe", "gross_margin", "revenue_growth"}


def compute_composite_score(metrics: dict) -> Optional[float]:
    """Compute composite valuation score (0-100, lower = cheaper/better value).
    
    For PE/PB: lower percentile = cheaper = better value
    For ROE/margins/growth: higher percentile = better fundamentals
    
    Final score: 0 = very cheap, 100 = very expensive
    """
    if not metrics:
        return None
    
    weighted_sum = 0.0
    total_weight = 0.0
    
    for metric_name, weight in METRIC_WEIGHTS.items():
        if metric_name in metrics and metrics[metric_name].get("percentile") is not None:
            pct = metrics[metric_name]["percentile"]
            if metric_name in HIGHER_IS_BETTER:
                # Invert: high ROE/growth is good -> should lower the "expensiveness" score
                pct = 100 - pct
            weighted_sum += pct * weight
            total_weight += weight
    
    if total_weight == 0:
        return None
    
    return round(weighted_sum / total_weight, 1)


@router.get("/signals", response_model=List[QuantSignalSummary])
def get_all_signals(db: Session = Depends(get_db)):
    """Get latest quant signals for all symbols."""
    
    # Get all unique symbols with their latest data
    symbols = db.query(QuantSignal.symbol).distinct().all()
    symbol_list = [s[0] for s in symbols]
    
    if not symbol_list:
        return []
    
    # Dynamic symbol mappings from DB
    symbol_names, symbol_markets = _get_symbol_mappings(db)
    
    results = []
    for symbol in sorted(symbol_list):
        # Get latest entry for each metric
        metrics = {}
        for metric_name in ["pe_ttm", "pb", "roe", "gross_margin", "revenue_growth"]:
            latest = db.query(QuantSignal).filter(
                QuantSignal.symbol == symbol,
                QuantSignal.metric == metric_name,
            ).order_by(desc(QuantSignal.date)).first()
            
            if latest and latest.value is not None:
                metrics[metric_name] = {
                    "value": latest.value,
                    "percentile": latest.percentile,
                }
        
        if not metrics:
            continue
        
        score = compute_composite_score(metrics)
        
        results.append(QuantSignalSummary(
            symbol=symbol,
            name=symbol_names.get(symbol, symbol),
            market=symbol_markets.get(symbol, "us"),
            metrics=metrics,
            score=score,
        ))
    
    return results


@router.get("/signals/{symbol}", response_model=List[QuantSignalOut])
def get_symbol_signals(symbol: str, metric: Optional[str] = None, db: Session = Depends(get_db)):
    """Get historical signal data for a specific symbol."""
    symbol = symbol.upper()
    
    q = db.query(QuantSignal).filter(QuantSignal.symbol == symbol)
    if metric:
        q = q.filter(QuantSignal.metric == metric)
    
    signals = q.order_by(QuantSignal.date.asc()).all()
    
    if not signals:
        raise HTTPException(status_code=404, detail=f"No signals found for {symbol}")
    
    return signals


@router.post("/refresh")
def refresh_signals(db: Session = Depends(get_db)):
    """Manually trigger a data refresh — runs synchronously and returns result."""
    try:
        from fetch_fundamentals import refresh_all_signals
        count = refresh_all_signals()
        logger.info(f"Manual refresh completed: {count} signals updated")
        return {"status": "ok", "count": count, "message": f"Updated {count} signals"}
    except Exception as e:
        logger.error(f"Manual refresh failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


METRIC_FIELDS = {
    "pe_ttm": "value",
    "pb": "value",
    "roe": "value",
    "gross_margin": "value",
    "revenue_growth": "value",
    "pe_ttm_pct": "percentile",
    "pb_pct": "percentile",
    "roe_pct": "percentile",
    "gross_margin_pct": "percentile",
    "revenue_growth_pct": "percentile",
    "change_pct": "price",
}
OPS = {
    "lte": lambda left, right: left <= right,
    "gte": lambda left, right: left >= right,
}
ACTIONS = {"buy", "sell", "watch"}


def condition_hit(conditions: list, metrics: dict) -> bool:
    if not conditions:
        return False
    for item in conditions:
        metric = item.get("metric")
        op = OPS.get(item.get("op"))
        if metric not in METRIC_FIELDS or op is None:
            return False
        value = metrics.get(metric)
        if value is None:
            return False
        if not op(float(value), float(item.get("value"))):
            return False
    return True


def _clean_conditions(raw: list) -> list:
    cleaned = []
    for item in raw[:4]:
        metric = str(item.get("metric") or "")
        op = str(item.get("op") or "")
        if metric not in METRIC_FIELDS or op not in OPS:
            continue
        cleaned.append({"metric": metric, "op": op, "value": float(item.get("value"))})
    if not cleaned:
        raise HTTPException(status_code=400, detail="至少写一个条件")
    return cleaned


def _latest_metrics(db: Session) -> dict[str, dict]:
    found: dict[str, dict] = {}
    rows = db.query(QuantSignal).order_by(desc(QuantSignal.date)).all()
    for row in rows:
        bucket = found.setdefault(row.symbol, {})
        if row.metric not in bucket and row.value is not None:
            bucket[row.metric] = row.value
        pct_key = row.metric + "_pct"
        if pct_key not in bucket and row.percentile is not None:
            bucket[pct_key] = row.percentile
    for price in db.query(PriceCache).all():
        if price.change_pct is not None:
            found.setdefault(price.symbol, {})["change_pct"] = price.change_pct
    return found


def _strategy_out(row, metrics: dict[str, dict]) -> dict:
    import json
    conditions = json.loads(row.conditions or "[]")
    target = row.symbol.strip()
    hits = []
    if row.enabled:
        for symbol, values in metrics.items():
            if target and symbol != target:
                continue
            if condition_hit(conditions, values):
                hits.append(symbol)
    return {
        "id": row.id,
        "name": row.name,
        "symbol": row.symbol,
        "action": row.action,
        "conditions": conditions,
        "enabled": row.enabled,
        "hits": hits,
    }


class StrategyText(BaseModel):
    text: str
    api_url: str = ""
    api_model: str = ""
    api_key: str = ""


@router.post("/strategies/from-text")
def strategy_from_text(payload: StrategyText, db: Session = Depends(get_db)):
    from ..services.vision_holdings import complete_text, extract_strategy
    prompt = (
        "把下面的投资策略说明转成 JSON，只返回 JSON，不要解释。"
        '{"name":"","symbol":"","action":"buy|sell|watch","conditions":'
        '[{"metric":"pe_ttm_pct|pb_pct|roe|gross_margin|revenue_growth|change_pct","op":"lte|gte","value":0}]}。'
        "原文：\n" + (payload.text or "")[:4000]
    )
    try:
        data = extract_strategy(complete_text(prompt, payload.api_url, payload.api_model, payload.api_key))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc
    return create_strategy(StrategyIn(**data), db)


class StrategyIn(BaseModel):
    name: str
    symbol: str = ""
    action: str = "watch"
    conditions: list


@router.get("/strategies")
def list_strategies(db: Session = Depends(get_db)):
    from ..models import QuantStrategy
    metrics = _latest_metrics(db)
    rows = db.query(QuantStrategy).order_by(QuantStrategy.id.desc()).all()
    return [_strategy_out(row, metrics) for row in rows]


@router.post("/strategies", status_code=201)
def create_strategy(payload: StrategyIn, db: Session = Depends(get_db)):
    import json
    from ..models import QuantStrategy
    from ..symbols import normalize_symbol
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写策略名称")
    action = payload.action if payload.action in ACTIONS else "watch"
    symbol = ""
    if payload.symbol.strip():
        symbol, _market = normalize_symbol(payload.symbol)
    row = QuantStrategy(
        name=name[:80],
        symbol=symbol,
        action=action,
        conditions=json.dumps(_clean_conditions(payload.conditions), ensure_ascii=False),
        enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _strategy_out(row, _latest_metrics(db))


@router.delete("/strategies/{strategy_id}", status_code=204)
def delete_strategy(strategy_id: int, db: Session = Depends(get_db)):
    from ..models import QuantStrategy
    row = db.query(QuantStrategy).filter(QuantStrategy.id == strategy_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="策略不存在")
    db.delete(row)
    db.commit()


@router.put("/strategies/{strategy_id}")
def toggle_strategy(strategy_id: int, db: Session = Depends(get_db)):
    from ..models import QuantStrategy
    row = db.query(QuantStrategy).filter(QuantStrategy.id == strategy_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="策略不存在")
    row.enabled = not row.enabled
    db.commit()
    return _strategy_out(row, _latest_metrics(db))
