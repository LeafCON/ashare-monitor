"""Alert settings & history endpoints.

Supports multi-level alerts: each symbol can have a primary alert (is_primary=True)
and multiple sub-level alerts (is_primary=False) for different price targets.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AlertSetting, AlertHistory, PriceCache, MarketType,
    AlertSettingCreate, AlertSettingUpdate, AlertSettingOut, AlertHistoryOut,
)
from ..symbols import normalize_symbol

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class TradingSwitch(BaseModel):
    auto_order: bool = False


@router.get("/notify-status")
def notify_status(db: Session = Depends(get_db)):
    """Push mode and the auto-order switch. Never returns the bot token."""
    from ..services.alert_service import alerts_today, auto_order_enabled, runtime_config, telegram_configured
    cfg = runtime_config()
    return {
        "dry_run": cfg["dry_run"],
        "telegram_configured": telegram_configured(),
        "cooldown_minutes": round(cfg["cooldown"] / 60),
        "max_per_day": cfg["max_per_day"],
        "change_alert_pct": cfg["change_alert_pct"],
        "sent_today": alerts_today(db),
        "auto_order": auto_order_enabled(db),
        "broker_connected": False,
    }


@router.put("/trading")
def update_trading(payload: TradingSwitch, db: Session = Depends(get_db)):
    """Turn the auto-order switch on or off. Default is off. No broker call is made."""
    from ..services.alert_service import set_auto_order
    enabled = set_auto_order(db, payload.auto_order)
    return {
        "auto_order": enabled,
        "broker_connected": False,
        "detail": "已关闭，信号只提醒，请手动确认。" if not enabled else "已打开开关，但未接入券商，不会提交委托，也不会保存交易密码。",
    }


@router.post("/test-send")
def test_alert_send(mode: str = Query("dry", pattern="^(dry|live)$")):
    """mode=dry 只打印；mode=live 才请求 Telegram。"""
    from ..services.alert_service import format_signal, send_telegram_alert, telegram_configured
    text = format_signal("600519.SS", "贵州茅台", 0, 0, "test", "A股")
    text = text.replace("现价0.00", "现价(测试)").replace("涨跌+0.00%", "涨跌(测试)")
    if mode == "dry":
        import logging
        logging.getLogger(__name__).info("[只打印] %s", text)
        return {"sent": False, "dry_run": True, "printed": True, "text": text}
    if not telegram_configured():
        return {"sent": False, "dry_run": False, "printed": False, "text": text, "detail": "未配置 Telegram。请在 .env 填写后再真发。"}
    sent = send_telegram_alert(text, force_live=True)
    return {
        "sent": sent,
        "dry_run": False,
        "printed": False,
        "text": text,
        "detail": None if sent else "Telegram 拒绝了这次发送",
    }


# ── Grouped response schema ──────────────────────────────────────────────────

class AlertGroupOut(BaseModel):
    """A stock symbol with its primary alert and sub-level alerts."""
    symbol: str
    name: str
    market: str
    current_price: Optional[float] = None
    change_pct: Optional[float] = None
    primary: Optional[AlertSettingOut] = None
    levels: List[AlertSettingOut] = []


# ── Alert Settings ────────────────────────────────────────────────────────────

@router.get("", response_model=List[AlertSettingOut])
def list_alerts(db: Session = Depends(get_db)):
    """List all alert settings (flat list)."""
    return db.query(AlertSetting).order_by(AlertSetting.symbol, AlertSetting.is_primary.desc()).all()


@router.get("/grouped", response_model=List[AlertGroupOut])
def list_alerts_grouped(db: Session = Depends(get_db)):
    """List alerts grouped by stock symbol, with current prices."""
    alerts = db.query(AlertSetting).order_by(AlertSetting.symbol, AlertSetting.is_primary.desc()).all()

    # Group by symbol
    groups: Dict[str, AlertGroupOut] = {}
    for alert in alerts:
        sym = alert.symbol
        if sym not in groups:
            cached = db.query(PriceCache).filter(PriceCache.symbol == sym).first()
            groups[sym] = AlertGroupOut(
                symbol=sym,
                name=alert.name or sym,
                market=alert.market.value,
                current_price=cached.price if cached else None,
                change_pct=cached.change_pct if cached else None,
            )

        alert_out = AlertSettingOut.model_validate(alert)
        if getattr(alert, 'is_primary', True):
            groups[sym].primary = alert_out
            # Use primary's name as the group name
            groups[sym].name = alert.name or sym
        else:
            groups[sym].levels.append(alert_out)

    return list(groups.values())


@router.post("", response_model=AlertSettingOut, status_code=201)
def create_alert(payload: AlertSettingCreate, db: Session = Depends(get_db)):
    """Create an alert setting.

    If is_primary=True and a primary alert for the same symbol already exists,
    the existing one is updated instead.
    For sub-level alerts (is_primary=False), a new record is always created.
    """
    symbol, inferred = normalize_symbol(payload.symbol, payload.market.value)
    market = MarketType.cn if inferred == "cn" else payload.market

    if payload.is_primary:
        existing = db.query(AlertSetting).filter(
            AlertSetting.symbol == symbol,
            AlertSetting.is_primary == True,
        ).first()

        if existing:
            for field, value in payload.model_dump(exclude_unset=True).items():
                if field == "symbol":
                    value = symbol
                if field == "market":
                    value = market
                setattr(existing, field, value)
            db.commit()
            db.refresh(existing)
            return existing

    alert = AlertSetting(
        symbol=symbol,
        name=payload.name,
        market=market,
        target_buy=payload.target_buy,
        target_sell=payload.target_sell,
        stop_loss=payload.stop_loss,
        pct_threshold=payload.pct_threshold,
        enabled=payload.enabled,
        is_primary=payload.is_primary,
        label=payload.label,
        amount=payload.amount,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@router.put("/{alert_id}", response_model=AlertSettingOut)
def update_alert(alert_id: int, payload: AlertSettingUpdate, db: Session = Depends(get_db)):
    """Update alert settings. Explicitly set fields to null to clear them."""
    alert = db.query(AlertSetting).filter(AlertSetting.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(alert, field, value)
    db.commit()
    db.refresh(alert)
    return alert


@router.delete("/{alert_id}", status_code=204)
def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    """Delete an alert setting."""
    alert = db.query(AlertSetting).filter(AlertSetting.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    db.delete(alert)
    db.commit()


# ── Alert History ─────────────────────────────────────────────────────────────

@router.get("/history", response_model=List[AlertHistoryOut])
def alert_history(
    symbol: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """Get alert history."""
    q = db.query(AlertHistory).order_by(AlertHistory.triggered_at.desc())
    if symbol:
        q = q.filter(AlertHistory.symbol == symbol.upper())
    return q.limit(limit).all()
