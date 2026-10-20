"""Local venue settings. Values stay in .env and are never returned in full."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..services.env_store import FIELDS, SECRET_FIELDS, apply_updates, hint, read_env, truthy

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_thread_id: Optional[str] = None
    alert_dry_run: Optional[bool] = None
    binance_api_key: Optional[str] = None
    binance_api_secret: Optional[str] = None
    stock_broker_api_base: Optional[str] = None
    stock_broker_api_key: Optional[str] = None
    stock_broker_api_secret: Optional[str] = None
    stock_broker_markets: Optional[str] = None
    stock_broker_quote_balance: Optional[str] = None
    agent_symbols: Optional[str] = None
    jev_api_key: Optional[str] = None
    agent_kill: Optional[bool] = None
    clear: list[str] = Field(default_factory=list)


def _status() -> dict:
    markets = read_env("STOCK_BROKER_MARKETS", "cn,hk,us") or "cn,hk,us"
    return {
        "telegram": {
            "token_set": bool(read_env("TELEGRAM_BOT_TOKEN")),
            "token_hint": hint(read_env("TELEGRAM_BOT_TOKEN")),
            "chat_id": read_env("TELEGRAM_CHAT_ID"),
            "thread_id": read_env("TELEGRAM_THREAD_ID"),
            "dry_run": truthy("ALERT_DRY_RUN", "true"),
        },
        "binance": {
            "key_set": bool(read_env("BINANCE_API_KEY")),
            "key_hint": hint(read_env("BINANCE_API_KEY")),
            "secret_set": bool(read_env("BINANCE_API_SECRET")),
        },
        "broker": {
            "base": read_env("STOCK_BROKER_API_BASE"),
            "key_set": bool(read_env("STOCK_BROKER_API_KEY")),
            "key_hint": hint(read_env("STOCK_BROKER_API_KEY")),
            "secret_set": bool(read_env("STOCK_BROKER_API_SECRET")),
            "markets": markets,
            "quote_balance": read_env("STOCK_BROKER_QUOTE_BALANCE", "0") or "0",
        },
        "agent": {
            "symbols": read_env("AGENT_SYMBOLS", "BTCUSDT,ETHUSDT") or "BTCUSDT,ETHUSDT",
            "jev_set": bool(read_env("JEV_API_KEY")),
            "kill": truthy("AGENT_KILL", "false"),
        },
    }


def _flag(value: bool) -> str:
    return "true" if value else "false"


@router.get("")
def get_settings():
    return _status()


@router.put("")
def update_settings(payload: SettingsUpdate):
    data = payload.model_dump(exclude_unset=True)
    clear = {item for item in data.pop("clear", []) if item in FIELDS}
    updates: dict[str, str] = {}
    for field in clear:
        updates[FIELDS[field][0]] = ""
    for field, value in data.items():
        if field not in FIELDS or value is None:
            continue
        if isinstance(value, bool):
            updates[FIELDS[field][0]] = _flag(value)
            continue
        text = str(value).strip()
        if field in SECRET_FIELDS and not text:
            continue
        if len(text) > 500:
            text = text[:500]
        updates[FIELDS[field][0]] = text
    apply_updates(updates)
    return _status()
