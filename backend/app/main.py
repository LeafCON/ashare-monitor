"""
Portfolio Monitor — FastAPI application entry point.

Includes:
- REST API for portfolio, transactions, alerts, prices
- Background price monitor with APScheduler
- Static file serving for the frontend SPA
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .database import init_db, SessionLocal
from .models import PriceCache, AlertSetting, MarketType, CashLog
from .services.price_service import fetch_price, fetch_cn_price, fetch_prices_batch
from .services.alert_service import check_alerts

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("portfolio-monitor")


# ── Default watchlist (seeded on first run) ──────────────────────────────────

DEFAULT_WATCHLIST = [
    {"symbol": "600519.SS", "name": "贵州茅台", "market": "cn"},
    {"symbol": "000858.SZ", "name": "五粮液", "market": "cn"},
    {"symbol": "601318.SS", "name": "中国平安", "market": "cn"},
    {"symbol": "600036.SS", "name": "招商银行", "market": "cn"},
    {"symbol": "000001.SZ", "name": "平安银行", "market": "cn"},
    {"symbol": "300750.SZ", "name": "宁德时代", "market": "cn"},
    {"symbol": "002594.SZ", "name": "比亚迪", "market": "cn"},
    {"symbol": "601899.SS", "name": "紫金矿业", "market": "cn"},
    {"symbol": "510300.SS", "name": "沪深300ETF", "market": "cn"},
]


# ── Background price updater ─────────────────────────────────────────────────

def update_prices():
    """Fetch latest prices for all alert symbols and update cache.

    Only fetches prices for unique real ticker symbols (deduplicating
    primary and sub-level alerts that share the same symbol).
    """
    db = SessionLocal()
    try:
        alerts = db.query(AlertSetting).all()
        if not alerts:
            return

        # Deduplicate: only fetch each real symbol once.
        # Prefer primary alert's name for display.
        symbol_info: dict[str, dict] = {}
        for a in alerts:
            sym = a.symbol
            if sym not in symbol_info:
                symbol_info[sym] = {
                    "name": a.name,
                    "market": a.market.value,
                    "secid": getattr(a, "secid", None),
                }
            elif getattr(a, "is_primary", True):
                symbol_info[sym] = {
                    "name": a.name,
                    "market": a.market.value,
                    "secid": getattr(a, "secid", None) or symbol_info[sym].get("secid"),
                }

        all_symbols = list(symbol_info.keys())
        logger.info(f"Updating prices for {len(all_symbols)} symbols: {', '.join(all_symbols)}")

        # Batch fetch all at once
        batch_results = fetch_prices_batch(
            all_symbols,
            {sym: info.get("secid") for sym, info in symbol_info.items()},
        )

        updated = 0
        for symbol, data in batch_results.items():
            if "error" in data:
                logger.warning(f"Price fetch error for {symbol}: {data['error']}")
                continue

            # Use the name from alert settings (better than ticker symbol)
            display_name = symbol_info.get(symbol, {}).get("name", data.get("name", ""))

            cached = PriceCache(
                symbol=data["symbol"],
                name=display_name,
                price=data["price"],
                previous_close=data.get("previous_close"),
                change=data.get("change"),
                change_pct=data.get("change_pct"),
                volume=data.get("volume"),
                market_cap=data.get("market_cap"),
                currency=data.get("currency", "USD"),
                updated_at=datetime.now(timezone.utc),
            )
            db.merge(cached)
            updated += 1

        db.commit()
        logger.info(f"Updated {updated}/{len(all_symbols)} prices")

        # Check alerts after price update
        triggered = check_alerts(db)
        if triggered:
            logger.info(f"Triggered {triggered} alerts")

    except Exception as e:
        logger.error(f"Price update cycle error: {e}")
    finally:
        db.close()


def seed_default_alerts():
    """Seed default watchlist into alert_settings if empty."""
    db = SessionLocal()
    try:
        count = db.query(AlertSetting).count()
        if count == 0:
            items = _CONFIG.get("watchlist") or DEFAULT_WATCHLIST
            for item in items:
                alert = AlertSetting(
                    symbol=item["symbol"],
                    name=item["name"],
                    market=MarketType(item["market"]),
                    enabled=True,
                )
                db.add(alert)
            db.commit()
            logger.info(f"Seeded {len(items)} default watchlist items")
        from .services.eastmoney import INDEX_WATCHLIST
        for item in INDEX_WATCHLIST:
            exists = db.query(AlertSetting).filter(
                AlertSetting.symbol == item["symbol"],
                AlertSetting.is_primary == True,  # noqa: E712
            ).first()
            if exists:
                if not exists.secid:
                    exists.secid = item["secid"]
                continue
            db.add(AlertSetting(
                symbol=item["symbol"],
                name=item["name"],
                market=MarketType(item["market"]),
                secid=item["secid"],
                enabled=True,
                is_primary=True,
            ))
        from .services.eastmoney import HK_WATCHLIST
        for item in HK_WATCHLIST:
            exists = db.query(AlertSetting).filter(
                AlertSetting.symbol == item["symbol"],
                AlertSetting.is_primary == True,  # noqa: E712
            ).first()
            if exists:
                if not exists.secid:
                    exists.secid = item["secid"]
                continue
            db.add(AlertSetting(
                symbol=item["symbol"],
                name=item["name"],
                market=MarketType(item["market"]),
                secid=item["secid"],
                enabled=True,
                is_primary=True,
            ))
        db.commit()
    finally:
        db.close()


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Startup
    init_db()
    seed_default_alerts()

    # Add backend/scripts/ to sys.path once (used by quant refresh)
    import sys
    scripts_dir = str(Path(__file__).parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    # Start background scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    price_interval = _CONFIG.get("monitor", {}).get("interval_active", 60)
    scheduler.add_job(update_prices, "interval", seconds=price_interval, id="price_updater",
                      max_instances=1,
                      next_run_time=datetime.now())  # Run immediately on start
    
    # Quant signals refresh — daily at 16:00 CST (08:00 UTC)
    def refresh_quant_signals():
        try:
            from fetch_fundamentals import refresh_all_signals
            refresh_all_signals()
        except Exception as e:
            logger.error(f"Quant signal refresh error: {e}")

    scheduler.add_job(refresh_quant_signals, "cron", hour=8, minute=0, id="quant_refresh")

    # Daily asset snapshot at 16:00 CST (08:00 UTC)
    def daily_snapshot():
        try:
            from .routers.snapshots import take_daily_snapshot
            take_daily_snapshot()
        except Exception as e:
            logger.error(f"Daily snapshot error: {e}")

    scheduler.add_job(daily_snapshot, "cron", hour=8, minute=5, id="daily_snapshot")
    
    scheduler.start()
    logger.info(f"🚀 Portfolio Monitor started — price updater running every {price_interval}s, quant refresh daily at 16:00 CST, daily snapshot at 16:05 CST")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Portfolio Monitor shutting down")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Portfolio Monitor",
    description="股票监控与交易记录系统",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend and reverse proxy origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://gu.kdp.cool",
        "http://localhost:8802",
        "http://127.0.0.1:8802",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Telegram InitData 验证中间件 ──────────────────────────────────────────────

import hashlib
import hmac
import re as _re
import urllib.parse
import yaml as _yaml

# ── Load config once at module level ──────────────────────────────────────────
def _load_config() -> dict:
    try:
        cfg_path = Path(__file__).parent.parent.parent / "config.yaml"
        with open(cfg_path) as f:
            return _yaml.safe_load(f) or {}
    except Exception:
        return {}

_CONFIG = _load_config()

def _get_bot_token() -> str:
    return _CONFIG.get("telegram", {}).get("bot_token", "")

def _verify_telegram_init_data(init_data: str, bot_token: str) -> bool:
    """验证 Telegram WebApp initData 签名。"""
    try:
        parsed = urllib.parse.parse_qs(init_data, keep_blank_values=True)
        hash_value = parsed.get("hash", [None])[0]
        if not hash_value:
            return False
        # 构造 data-check-string
        fields = {k: v[0] for k, v in parsed.items() if k != "hash"}
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        # HMAC-SHA256
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, hash_value)
    except Exception:
        return False

# 不需要验证的路径前缀
_PUBLIC_PATHS = {"/health", "/api/health", "/assets", "/favicon"}

class TelegramAuthMiddleware(BaseHTTPMiddleware):
    """只允许携带有效 Telegram initData 的请求访问 API。
    静态资源和 health check 不受限。
    localhost 访问直接放行（内网调试用）。
    """
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        host = request.headers.get("host", "")

        # localhost 或 IP 直连放行（内网/VPN 直接访问无需 Telegram 鉴权）
        host_only = host.split(":")[0]
        _is_ip = _re.match(r'^(\d{1,3}\.){3}\d{1,3}$', host_only)
        if "localhost" in host_only or "127.0.0.1" in host_only or _is_ip:
            return await call_next(request)

        # 静态资源放行
        if any(path.startswith(p) for p in _PUBLIC_PATHS) or not path.startswith("/api"):
            return await call_next(request)

        # 验证 Telegram initData
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        bot_token = _get_bot_token()

        # 有 initData 且验签通过 → 放行
        if init_data and bot_token and _verify_telegram_init_data(init_data, bot_token):
            return await call_next(request)

        # 有 initData 但验签失败
        if init_data:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=403, content={"detail": "Invalid Telegram signature"})

        # 无 initData
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=403, content={"detail": "Telegram authentication required"})

app.add_middleware(TelegramAuthMiddleware)

# Register API routers
from .routers import portfolio, transactions, alerts, prices, dashboard, cash, watchlist, quant, earnings, snapshots, macro, market, search
app.include_router(dashboard.router)
app.include_router(portfolio.router)
app.include_router(transactions.router)
app.include_router(alerts.router)
app.include_router(prices.router)
app.include_router(cash.router)
app.include_router(watchlist.router)
app.include_router(quant.router)
app.include_router(earnings.router)
app.include_router(snapshots.router)
app.include_router(macro.router)
app.include_router(market.router)
app.include_router(search.router)

# ── Static files (frontend) ──────────────────────────────────────────────────

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"


@app.api_route("/health", methods=["GET", "HEAD"])
@app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "service": "portfolio-monitor"}


# Serve frontend SPA
if FRONTEND_DIR.exists():
    # Hashed asset files — can be cached forever by CDN/browser
    class CachedStaticFiles(StaticFiles):
        """StaticFiles with aggressive caching for hashed filenames."""
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            # Assets have content hash in filename, safe to cache long-term
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    app.mount("/assets", CachedStaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"])
    async def serve_spa(full_path: str):
        """Serve the SPA — any non-API route gets index.html."""
        # Skip API routes
        if full_path.startswith("api/") or full_path.startswith("health"):
            raise HTTPException(status_code=404, detail="Not found")
        file_path = FRONTEND_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        # index.html should not be cached by CDN (always serve fresh)
        return FileResponse(
            FRONTEND_DIR / "index.html",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )
