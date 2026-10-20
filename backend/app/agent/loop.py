"""One decision tick. A passing gate is sent to Binance when keys exist."""

from __future__ import annotations

import json
from pathlib import Path

from .execute import submit_market, venue_ready
from .policy import decide_order
from .reflex import load_reflex
from .schema import MarketSnapshot, PolicyOrder

JOURNAL = Path(__file__).resolve().parents[3] / "data" / "agent_journal.jsonl"
MIN_NOTIONAL = 5.0


def apply_execution(order: PolicyOrder, symbol: str, quote_balance: float, market: str) -> dict:
    if not order.fire:
        return {"executed": False, "waiting": False, "detail": order.reason}
    if not venue_ready(market):
        return {
            "executed": False,
            "waiting": True,
            "detail": f"{market} 的交易接口还没配置，这一路等待，不发单",
        }
    quote_qty = quote_balance * order.size_fraction
    if quote_qty < MIN_NOTIONAL:
        return {"executed": False, "waiting": False, "detail": f"下单金额 {quote_qty:.2f} 低于 5 个报价货币的下限"}
    body = submit_market(symbol, order.action, quote_qty, market)
    return {"executed": True, "waiting": False, "detail": str(body.get("orderId") or body.get("status") or "submitted")}


def run_tick(snapshot: MarketSnapshot, quote_balance: float | None = None, market: str = "crypto") -> dict:
    reflex = load_reflex()
    decision = reflex.judge(snapshot)
    order = decide_order(decision)
    execution = apply_execution(order, snapshot.symbol, quote_balance or 0, market)
    record = {
        "snapshot": snapshot.model_dump(),
        "decision": decision.model_dump(),
        "order": order.model_dump(),
        "executed": execution["executed"],
        "waiting": execution["waiting"],
        "note": execution["detail"],
    }
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
