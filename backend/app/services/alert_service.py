"""Alert checks and Telegram delivery.

Scheduled alerts follow ALERT_DRY_RUN. The dashboard can force a dry print
or a real Telegram send. Auto-order is a switch that defaults off. This
process never clicks a trading client and never stores a trading password.
Without a broker adapter, enabling the switch only records an intent.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import yaml
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from ..models import AlertHistory, AlertSetting, AppSetting, OrderIntent, PriceCache
from ..symbols import display_code, market_group

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")
CST = ZoneInfo("Asia/Shanghai")

_PLACEHOLDERS = {"", "none", "null"}


def _clean(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if text.lower() in _PLACEHOLDERS or text.upper().startswith("YOUR_"):
        return ""
    return text


def _load_yaml() -> dict:
    try:
        with open(ROOT / "config.yaml", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception as exc:
        logger.error("Failed to load config.yaml: %s", exc)
        return {}


def runtime_config() -> dict:
    cfg = _load_yaml()
    telegram = cfg.get("telegram") or {}
    alert = cfg.get("alert") or {}
    monitor = cfg.get("monitor") or {}
    token = _clean(os.getenv("TELEGRAM_BOT_TOKEN")) or _clean(telegram.get("bot_token"))
    chat_id = _clean(os.getenv("TELEGRAM_CHAT_ID")) or _clean(telegram.get("chat_id"))
    thread = _clean(os.getenv("TELEGRAM_THREAD_ID")) or _clean(telegram.get("thread_id"))
    dry_env = os.getenv("ALERT_DRY_RUN", "true").strip().lower()
    return {
        "bot_token": token,
        "chat_id": chat_id,
        "thread_id": thread,
        "dry_run": dry_env in {"1", "true", "yes", "on"},
        "cooldown": int(alert.get("cooldown", 3600)),
        "max_per_day": int(alert.get("max_per_day", 30)),
        "change_alert_pct": float(monitor.get("change_alert_pct", 3.0)),
    }


def telegram_configured() -> bool:
    cfg = runtime_config()
    return bool(cfg["bot_token"] and cfg["chat_id"])


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _day_start_utc() -> datetime:
    now = datetime.now(CST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc)


def alerts_today(db: Session) -> int:
    start = _day_start_utc().replace(tzinfo=None)
    rows = db.query(AlertHistory).all()
    count = 0
    aware_start = _day_start_utc()
    for row in rows:
        if row.triggered_at and _as_utc(row.triggered_at) >= aware_start:
            count += 1
        elif row.triggered_at and row.triggered_at >= start:
            count += 1
    return count


def auto_order_enabled(db: Session) -> bool:
    row = db.query(AppSetting).filter(AppSetting.key == "auto_order").first()
    if row is None:
        return os.getenv("TRADING_AUTO_ORDER", "false").strip().lower() in {"1", "true", "yes", "on"}
    return row.value.strip().lower() in {"1", "true", "yes", "on"}


def set_auto_order(db: Session, enabled: bool) -> bool:
    row = db.query(AppSetting).filter(AppSetting.key == "auto_order").first()
    if row is None:
        row = AppSetting(key="auto_order", value="true" if enabled else "false")
        db.add(row)
    else:
        row.value = "true" if enabled else "false"
    db.commit()
    return enabled


def _in_cooldown(db: Session, symbol: str, alert_type: str, seconds: int) -> bool:
    row = (
        db.query(AlertHistory)
        .filter(AlertHistory.symbol == symbol, AlertHistory.alert_type == alert_type)
        .order_by(AlertHistory.triggered_at.desc())
        .first()
    )
    if not row or not row.triggered_at:
        return False
    return datetime.now(timezone.utc) - _as_utc(row.triggered_at) < timedelta(seconds=seconds)


def format_signal(symbol: str, name: str, price: float, change_pct: float | None, rule: str, group: str) -> str:
    pct = f"{change_pct:+.2f}%" if change_pct is not None else "-"
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"[信号] {display_code(symbol)} {name} 现价{price:.2f} 涨跌{pct} "
        f"| 规则:{rule} | 分组:{group} | 请手动确认 | 时间:{now}"
    )


def send_telegram_alert(message: str, *, force_live: bool = False) -> bool:
    """Send one Telegram message. Dry-run prints and returns False."""
    cfg = runtime_config()
    if cfg["dry_run"] and not force_live:
        logger.info("[只打印] %s", message)
        return False
    if not cfg["bot_token"] or not cfg["chat_id"]:
        logger.error("Telegram bot_token or chat_id is missing")
        return False
    payload: dict[str, Any] = {"chat_id": cfg["chat_id"], "text": message}
    if cfg["thread_id"].isdigit():
        payload["message_thread_id"] = int(cfg["thread_id"])
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
            json=payload,
            timeout=30,
        )
        data = resp.json()
        if data.get("ok"):
            logger.info("Telegram sent msg_id=%s", data.get("result", {}).get("message_id"))
            return True
        logger.error("Telegram API error: %s", data.get("description", "unknown"))
        return False
    except Exception as exc:
        logger.error("Telegram alert exception: %s", exc)
        return False


def _record_order_intent(db: Session, symbol: str, side: str, price: float, auto: bool, note: str) -> None:
    db.add(OrderIntent(
        symbol=symbol,
        side=side,
        price=price,
        auto_order=auto,
        status="manual_pending" if not auto else "not_submitted",
        note=note,
        created_at=datetime.now(timezone.utc),
    ))


def _emit(
    db: Session,
    alert: AlertSetting,
    alert_type: str,
    rule: str,
    price: float,
    change_pct: float | None,
    side: str,
    cfg: dict,
    auto: bool,
) -> bool:
    group = market_group(alert.market.value if alert.market else None)
    if alert.label:
        group = f"{group}/{alert.label}"
    message = format_signal(alert.symbol, alert.name or alert.symbol, price, change_pct, rule, group)
    if auto:
        message += " | 自动下单未执行：未接入券商，未保存密码，未点击交易软件"
        _record_order_intent(db, alert.symbol, side, price, True, "未接入券商，未提交委托")
    else:
        _record_order_intent(db, alert.symbol, side, price, False, "请手动确认后自行下单")
    sent = send_telegram_alert(message)
    db.add(AlertHistory(
        symbol=alert.symbol,
        alert_type=alert_type,
        message=message,
        price=price,
        triggered_at=datetime.now(timezone.utc),
        sent=sent,
    ))
    alert.last_triggered_at = datetime.now(timezone.utc)
    db.commit()
    return True


def check_alerts(db: Session) -> int:
    cfg = runtime_config()
    auto = auto_order_enabled(db)
    triggered = 0
    now_utc = datetime.now(timezone.utc)
    alerts = db.query(AlertSetting).filter(AlertSetting.enabled == True).all()  # noqa: E712

    for alert in alerts:
        if alert.expires_at and _as_utc(alert.expires_at) < now_utc:
            continue
        if alerts_today(db) >= cfg["max_per_day"]:
            logger.info("Daily alert cap %s reached", cfg["max_per_day"])
            break
        cached = db.query(PriceCache).filter(PriceCache.symbol == alert.symbol).first()
        if not cached or cached.price is None:
            continue
        price = cached.price
        change_pct = cached.change_pct

        if alert.target_buy and price <= alert.target_buy and not _in_cooldown(db, alert.symbol, "price_cross_down", cfg["cooldown"]):
            rule = f"price_cross<={alert.target_buy:g}"
            if _emit(db, alert, "price_cross_down", rule, price, change_pct, "buy", cfg, auto):
                triggered += 1

        if alert.target_sell and price >= alert.target_sell and not _in_cooldown(db, alert.symbol, "price_cross_up", cfg["cooldown"]):
            rule = f"price_cross>={alert.target_sell:g}"
            if _emit(db, alert, "price_cross_up", rule, price, change_pct, "sell", cfg, auto):
                triggered += 1

        if alert.stop_loss and price <= alert.stop_loss and not _in_cooldown(db, alert.symbol, "stop_loss", cfg["cooldown"]):
            rule = f"stop_loss<={alert.stop_loss:g}"
            if _emit(db, alert, "stop_loss", rule, price, change_pct, "sell", cfg, auto):
                triggered += 1

        threshold = alert.pct_threshold if alert.pct_threshold is not None else cfg["change_alert_pct"]
        is_primary = getattr(alert, "is_primary", True)
        if (
            is_primary
            and threshold
            and change_pct is not None
            and abs(change_pct) >= float(threshold)
            and not _in_cooldown(db, alert.symbol, "pct_change", cfg["cooldown"])
        ):
            rule = f"pct_change>={float(threshold):g}" if change_pct > 0 else f"pct_change<=-{float(threshold):g}"
            side = "sell" if change_pct > 0 else "buy"
            if _emit(db, alert, "pct_change", rule, price, change_pct, side, cfg, auto):
                triggered += 1

    return triggered
