"""Portfolio service — calculates holdings, average cost, P&L from transactions."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Transaction, PriceCache, TradeAction,
    HoldingOut, PortfolioOut,
)
from ..symbols import quote_currency
from .exchange_service import get_usd_to_cny

logger = logging.getLogger(__name__)


def get_holdings(db: Session) -> PortfolioOut:
    """Calculate current holdings from all transactions."""
    transactions = (
        db.query(Transaction)
        .order_by(Transaction.date.asc())
        .all()
    )

    # Aggregate by symbol: track shares and total cost
    positions: Dict[str, dict] = defaultdict(lambda: {
        "shares": 0.0,
        "total_cost": 0.0,
        "name": "",
        "manual_value": None,
    })

    for tx in transactions:
        pos = positions[tx.symbol]
        pos["name"] = tx.name or tx.symbol

        if tx.action == TradeAction.buy:
            pos["total_cost"] += tx.amount + tx.fee
            pos["shares"] += tx.shares
            if getattr(tx, "manual_value", None) is not None:
                pos["manual_value"] = tx.manual_value
        elif tx.action == TradeAction.sell:
            if pos["shares"] > 0:
                # Reduce cost proportionally
                cost_per_share = pos["total_cost"] / pos["shares"] if pos["shares"] > 0 else 0
                pos["total_cost"] -= cost_per_share * tx.shares
                pos["shares"] -= tx.shares
                pos["total_cost"] = max(0, pos["total_cost"])  # Safety floor

    # Build holdings with current prices
    holdings: List[HoldingOut] = []
    total_cost = 0.0
    total_value = 0.0

    for symbol, pos in positions.items():
        if pos["shares"] <= 0:
            continue

        # Get latest cached price
        cached = db.query(PriceCache).filter(PriceCache.symbol == symbol).first()
        current_price = cached.price if cached else 0.0
        listed = quote_currency(symbol)
        if listed:
            currency = listed
        elif cached and cached.currency:
            currency = cached.currency
        else:
            currency = "USD"

        by_amount = pos["manual_value"] is not None
        if by_amount:
            market_value = float(pos["manual_value"])
            current_price = market_value
        else:
            market_value = current_price * pos["shares"]
        if not by_amount:
            avg_cost = pos["total_cost"] / pos["shares"] if pos["shares"] > 0 else 0.0
        else:
            avg_cost = pos["total_cost"]
        unrealized_pnl = market_value - pos["total_cost"]
        pnl_pct = (unrealized_pnl / pos["total_cost"] * 100) if pos["total_cost"] > 0 else 0.0

        # Convert to USD for unified comparison
        usd_to_cny = get_usd_to_cny()
        if currency == "CNY":
            market_value_usd = market_value / usd_to_cny
            unrealized_pnl_usd = unrealized_pnl / usd_to_cny
        elif currency == "HKD":
            market_value_usd = market_value / 7.8
            unrealized_pnl_usd = unrealized_pnl / 7.8
        else:
            market_value_usd = market_value
            unrealized_pnl_usd = unrealized_pnl

        holdings.append(HoldingOut(
            symbol=symbol,
            name=pos["name"],
            shares=round(pos["shares"], 4),
            avg_cost=round(avg_cost, 4),
            current_price=round(current_price, 4),
            market_value=round(market_value, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            currency=currency,
            market_value_usd=round(market_value_usd, 2),
            unrealized_pnl_usd=round(unrealized_pnl_usd, 2),
            by_amount=by_amount,
        ))

        total_cost += pos["total_cost"]
        total_value += market_value

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0

    return PortfolioOut(
        holdings=holdings,
        total_cost=round(total_cost, 2),
        total_value=round(total_value, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl_pct, 2),
    )
