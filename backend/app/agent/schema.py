"""Typed decision schema. The model fills it. Code gates it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Regime = Literal["trending", "mean_reverting", "high_vol", "crisis"]
Direction = Literal["long", "short", "neutral"]
RiskState = Literal["safe", "near_limit", "reduce"]
Action = Literal["buy", "sell", "hold"]


class MarketSnapshot(BaseModel):
    """Compact numeric state. Every timestamp must be <= decision time."""

    symbol: str
    decision_ts: int
    mid: float
    spread_bps: float
    imbalance: float = Field(ge=-1, le=1)
    realized_vol: float = Field(ge=0)
    inventory: float
    drawdown: float = Field(ge=0)
    daily_loss: float = Field(ge=0)
    position_fraction: float = Field(ge=0)


class ReflexDecision(BaseModel):
    regime: Regime
    direction: Direction
    direction_confidence: float = Field(ge=0, le=1)
    toxic_flow: float = Field(ge=0, le=1)
    setup_quality: int = Field(ge=0, le=3)
    risk_state: RiskState
    probability: float = Field(ge=0, le=1)
    action: Action
    backend: str
    latency_ms: float = 0


class PolicyOrder(BaseModel):
    fire: bool
    action: Action
    size_fraction: float = 0
    reason: str
    escalated: bool = False
