"""SQLAlchemy ORM models + Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import (
    Column, String, Float, DateTime, Enum as SAEnum, Boolean, Text, Integer,
)
from .database import Base


# ── Helpers ───────────────────────────────────────────────────────────────────

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def gen_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Enums ─────────────────────────────────────────────────────────────────────

class TradeAction(str, Enum):
    buy = "buy"
    sell = "sell"


class MarketType(str, Enum):
    us = "us"
    cn = "cn"


class CurrencyType(str, Enum):
    usd = "USD"
    cny = "CNY"


# ══════════════════════════════════════════════════════════════════════════════
#  ORM Models (SQLAlchemy)
# ══════════════════════════════════════════════════════════════════════════════

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(12), primary_key=True, default=gen_id)
    date = Column(DateTime, nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=False, default="")
    action = Column(SAEnum(TradeAction), nullable=False)
    price = Column(Float, nullable=False)
    shares = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    fee = Column(Float, nullable=False, default=0.0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class AlertSetting(Base):
    __tablename__ = "alert_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=False, default="")
    market = Column(SAEnum(MarketType), nullable=False, default=MarketType.us)
    target_buy = Column(Float, nullable=True)
    target_sell = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    enabled = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=True)   # True = main level, False = sub-level
    label = Column(String(100), nullable=True)    # Optional label e.g. "$280买入档"
    amount = Column(String(200), nullable=True)   # Buy/sell amount description e.g. "$15,000" or "减仓30%"
    pct_threshold = Column(Float, nullable=True)          # 单标的涨跌幅阈值，空则不启用该规则
    secid = Column(String(32), nullable=True)            # 行情源证券编号，如 105.AAPL / 100.SPX
    expires_at = Column(DateTime, nullable=True)          # 90天后过期
    last_triggered_at = Column(DateTime, nullable=True)   # 最近触发时间
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    alert_type = Column(String(30), nullable=False)  # target_buy, target_sell, stop_loss, big_change
    message = Column(Text, nullable=False)
    price = Column(Float, nullable=False)
    triggered_at = Column(DateTime, default=utcnow)
    sent = Column(Boolean, default=False)


class PriceCache(Base):
    """Recent price snapshots for dashboard display."""
    __tablename__ = "price_cache"

    symbol = Column(String(20), primary_key=True)
    name = Column(String(100), default="")
    price = Column(Float, nullable=False)
    previous_close = Column(Float, nullable=True)
    change = Column(Float, nullable=True)
    change_pct = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    market_cap = Column(Float, nullable=True)
    currency = Column(String(10), default="USD")
    updated_at = Column(DateTime, default=utcnow)


class QuantSignal(Base):
    """Quantitative fundamental signals for valuation analysis."""
    __tablename__ = "quant_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(DateTime, nullable=False)
    metric = Column(String(30), nullable=False)   # pe_ttm / pb / roe / gross_margin / revenue_growth
    value = Column(Float, nullable=True)
    percentile = Column(Float, nullable=True)      # 历史分位（0-100），越低越便宜
    updated_at = Column(DateTime, default=utcnow)


class AssetSnapshot(Base):
    """Daily snapshot of total assets for historical tracking."""
    __tablename__ = "asset_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, index=True)
    total_assets_usd = Column(Float, nullable=False, default=0.0)
    stock_value_usd = Column(Float, nullable=False, default=0.0)
    cash_usd = Column(Float, nullable=False, default=0.0)
    cash_cny = Column(Float, nullable=False, default=0.0)
    details = Column(Text, nullable=True)  # JSON or semicolon-separated holding details
    created_at = Column(DateTime, default=utcnow)


class CashAccount(Base):
    """Cash accounts for different currencies."""
    __tablename__ = "cash_accounts"

    currency = Column(String(10), primary_key=True)  # USD, CNY
    balance = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class EarningsAnalysis(Base):
    """老李财报分析结论，财报发布后写入，前端展示。"""
    __tablename__ = "earnings_analysis"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    fiscal_quarter = Column(String(20), nullable=False)   # e.g. "FY2026 Q4"
    report_date = Column(String(20), nullable=True)       # 实际发布日期 e.g. "2026-02-25"
    # EPS
    eps_actual = Column(Float, nullable=True)
    eps_estimate = Column(Float, nullable=True)
    eps_surprise_pct = Column(Float, nullable=True)       # (actual-estimate)/estimate * 100
    # Revenue
    revenue_actual = Column(Float, nullable=True)         # in billions USD
    revenue_estimate = Column(Float, nullable=True)
    revenue_surprise_pct = Column(Float, nullable=True)
    # Guidance
    guidance = Column(Text, nullable=True)                # 下季度指引文字
    # 老李判断
    verdict = Column(String(20), nullable=True)           # "beat" / "miss" / "met"
    short_term = Column(String(20), nullable=True)        # "bullish" / "bearish" / "neutral"
    analysis = Column(Text, nullable=True)                # 完整分析文字（markdown）
    holding_advice = Column(Text, nullable=True)          # 对持仓的建议
    # 股价反应
    price_reaction_pct = Column(Float, nullable=True)     # 财报后次日涨跌幅
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    """Small key/value settings. auto_order defaults off."""
    __tablename__ = "app_settings"

    key = Column(String(50), primary_key=True)
    value = Column(String(200), nullable=False, default="")


class OrderIntent(Base):
    """A signal's order note. Status not_submitted means nothing was sent to a broker."""
    __tablename__ = "order_intents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)
    price = Column(Float, nullable=False)
    auto_order = Column(Boolean, default=False)
    status = Column(String(30), nullable=False, default="manual_pending")
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class CashLog(Base):
    """Cash adjustment history log."""
    __tablename__ = "cash_logs"

    id = Column(String(12), primary_key=True, default=gen_id)
    currency = Column(String(10), nullable=False)
    amount = Column(Float, nullable=False)       # 正=存入 负=取出
    balance_after = Column(Float, nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ══════════════════════════════════════════════════════════════════════════════
#  Pydantic Schemas (API request/response)
# ══════════════════════════════════════════════════════════════════════════════

# ── Transaction ───────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    symbol: str
    name: str = ""
    action: TradeAction
    price: float
    shares: float
    date: Optional[datetime] = None
    fee: float = 0.0
    notes: Optional[str] = None


class TransactionOut(BaseModel):
    id: str
    date: datetime
    symbol: str
    name: str
    action: TradeAction
    price: float
    shares: float
    amount: float
    fee: float
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Alert ─────────────────────────────────────────────────────────────────────

class AlertSettingCreate(BaseModel):
    symbol: str
    name: str = ""
    market: MarketType = MarketType.us
    target_buy: Optional[float] = None
    target_sell: Optional[float] = None
    stop_loss: Optional[float] = None
    pct_threshold: Optional[float] = None
    enabled: bool = True
    is_primary: bool = True
    label: Optional[str] = None
    amount: Optional[str] = None


class AlertSettingUpdate(BaseModel):
    name: Optional[str] = None
    market: Optional[MarketType] = None
    target_buy: Optional[float] = None
    target_sell: Optional[float] = None
    stop_loss: Optional[float] = None
    pct_threshold: Optional[float] = None
    enabled: Optional[bool] = None
    is_primary: Optional[bool] = None
    label: Optional[str] = None
    amount: Optional[str] = None


class AlertSettingOut(BaseModel):
    id: int
    symbol: str
    name: str
    market: MarketType
    target_buy: Optional[float]
    target_sell: Optional[float]
    stop_loss: Optional[float]
    pct_threshold: Optional[float]
    enabled: bool
    is_primary: bool
    label: Optional[str]
    amount: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AlertHistoryOut(BaseModel):
    id: int
    symbol: str
    alert_type: str
    message: str
    price: float
    triggered_at: datetime
    sent: bool

    class Config:
        from_attributes = True


# ── Portfolio ─────────────────────────────────────────────────────────────────

class HoldingOut(BaseModel):
    symbol: str
    name: str
    shares: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    pnl_pct: float
    currency: str = "USD"
    market_value_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0


class PortfolioOut(BaseModel):
    holdings: List[HoldingOut]
    total_cost: float
    total_value: float
    total_pnl: float
    total_pnl_pct: float


# ── Price ─────────────────────────────────────────────────────────────────────

class PriceOut(BaseModel):
    symbol: str
    name: str
    price: float
    previous_close: Optional[float]
    change: Optional[float]
    change_pct: Optional[float]
    volume: Optional[float]
    currency: str
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Cash Account ──────────────────────────────────────────────────────────────

class CashAccountOut(BaseModel):
    currency: str
    balance: float
    updated_at: datetime

    class Config:
        from_attributes = True


class CashAccountUpdate(BaseModel):
    currency: CurrencyType
    amount: float = Field(..., description="正数表示存入，负数表示取出")
    notes: Optional[str] = None


class TotalAssetsOut(BaseModel):
    """Total assets summary including stocks and cash."""
    total_assets_usd: float  # All assets converted to USD
    stock_value_usd: float   # US stocks value in USD
    stock_value_cny: float   # CN stocks value in CNY
    cash_usd: float           # USD cash balance
    cash_cny: float           # CNY cash balance
    usd_to_cny: float         # Exchange rate used


class CashAccountHistory(BaseModel):
    """Cash account history record for tracking changes."""
    id: str
    currency: str
    amount: float
    balance_after: float
    reason: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Quant Signal ───────────────────────────────────────────────────────────────

class QuantSignalOut(BaseModel):
    id: int
    symbol: str
    date: datetime
    metric: str
    value: Optional[float]
    percentile: Optional[float]
    updated_at: datetime

    class Config:
        from_attributes = True


class QuantSignalSummary(BaseModel):
    """Summary of latest signals for a single symbol."""
    symbol: str
    name: str
    market: str
    metrics: dict  # metric_name -> {value, percentile}
    score: Optional[float] = None  # composite score 0-100


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardOut(BaseModel):
    prices: List[PriceOut]
    portfolio: PortfolioOut
    cash_accounts: List[CashAccountOut]
    total_assets: TotalAssetsOut
    recent_alerts: List[AlertHistoryOut]
    recent_transactions: List[TransactionOut]
