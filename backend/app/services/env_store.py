"""Read and write the local .env without printing secret values."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT / ".env"

# API field -> (env name, secret). Secrets are never returned in full.
FIELDS: dict[str, tuple[str, bool]] = {
    "telegram_bot_token": ("TELEGRAM_BOT_TOKEN", True),
    "telegram_chat_id": ("TELEGRAM_CHAT_ID", False),
    "telegram_thread_id": ("TELEGRAM_THREAD_ID", False),
    "alert_dry_run": ("ALERT_DRY_RUN", False),
    "binance_api_key": ("BINANCE_API_KEY", True),
    "binance_api_secret": ("BINANCE_API_SECRET", True),
    "stock_broker_api_base": ("STOCK_BROKER_API_BASE", False),
    "stock_broker_api_key": ("STOCK_BROKER_API_KEY", True),
    "stock_broker_api_secret": ("STOCK_BROKER_API_SECRET", True),
    "stock_broker_markets": ("STOCK_BROKER_MARKETS", False),
    "stock_broker_quote_balance": ("STOCK_BROKER_QUOTE_BALANCE", False),
    "agent_symbols": ("AGENT_SYMBOLS", False),
    "jev_api_key": ("JEV_API_KEY", True),
    "agent_kill": ("AGENT_KILL", False),
    "reflex_mode": ("REFLEX_MODE", False),
    "reflex_api_url": ("REFLEX_API_URL", False),
    "reflex_api_key": ("REFLEX_API_KEY", True),
    "llama_server_url": ("LLAMA_SERVER_URL", False),
    "reflex_local_model": ("REFLEX_LOCAL_MODEL", False),
    "vision_api_url": ("VISION_API_URL", False),
    "vision_api_key": ("VISION_API_KEY", True),
    "vision_model": ("VISION_MODEL", False),
}

SECRET_FIELDS = {name for name, (_, secret) in FIELDS.items() if secret}


def _clean(value: str | None) -> str:
    return "" if value is None else str(value).strip()


def hint(value: str) -> str:
    text = _clean(value)
    if not text:
        return ""
    if len(text) <= 4:
        return "••••"
    return "••••" + text[-4:]


def _file_values(path: Path | None = None) -> dict[str, str]:
    target = path or ENV_PATH
    if not target.exists():
        return {}
    values: dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _clean(value.strip().strip('"').strip("'"))
    return values


def hydrate_environ(path: Path | None = None) -> None:
    """Fill empty process variables from the .env file. Never replaces a real value."""
    for key, value in _file_values(path).items():
        if value and not _clean(os.getenv(key, "")):
            os.environ[key] = value


def read_env(name: str, default: str = "") -> str:
    hydrate_environ()
    current = _clean(os.getenv(name, ""))
    if current:
        return current
    return _clean(default)


def truthy(name: str, default: str = "false") -> bool:
    return read_env(name, default).lower() in {"1", "true", "yes", "on"}


def apply_updates(updates: dict[str, str], path: Path | None = None) -> None:
    """Write whitelisted keys. Empty secret values are ignored by the caller."""
    target = path or ENV_PATH
    allowed = {env for env, _ in FIELDS.values()}
    clean = {key: _clean(value) for key, value in updates.items() if key in allowed}
    if not clean:
        return
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    lines = existing.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in clean:
            out.append(f"{key}={_escape(clean[key])}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in clean.items():
        if key not in seen:
            out.append(f"{key}={_escape(value)}")
    text = "\n".join(out)
    if text and not text.endswith("\n"):
        text += "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    for key, value in clean.items():
        os.environ[key] = value


def _escape(value: str) -> str:
    if any(ch in value for ch in " #\t\"'"):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value
