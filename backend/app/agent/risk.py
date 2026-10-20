"""Hard risk limits. The model cannot change these numbers."""

from __future__ import annotations

import os
from pathlib import Path

from .schema import MarketSnapshot

# Operator gates, not market facts. Chosen so a paper loop fails closed.
MAX_DRAWDOWN = 0.15
MAX_DAILY_LOSS = 0.05
MAX_POSITION_FRACTION = 0.10

ROOT = Path(__file__).resolve().parents[3]


def kill_switch_on() -> bool:
    if os.getenv("AGENT_KILL", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return (ROOT / "data" / "agent_kill").exists()


def armed() -> bool:
    """Orders are live unless the kill switch is on."""
    return not kill_switch_on()


def risk_state(snapshot: MarketSnapshot) -> str:
    if kill_switch_on() or snapshot.drawdown >= MAX_DRAWDOWN or snapshot.daily_loss >= MAX_DAILY_LOSS:
        return "reduce"
    if snapshot.drawdown >= MAX_DRAWDOWN * 0.8 or snapshot.position_fraction >= MAX_POSITION_FRACTION:
        return "near_limit"
    return "safe"
