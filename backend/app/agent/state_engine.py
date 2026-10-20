"""Deterministic book snapshot. No future timestamps. The model never computes these."""

from __future__ import annotations

from typing import Iterable, Sequence

from .schema import MarketSnapshot


class FutureLeak(ValueError):
    pass


def _check_times(times: Iterable[int], decision_ts: int) -> None:
    for ts in times:
        if ts > decision_ts:
            raise FutureLeak(f"timestamp {ts} is after decision time {decision_ts}")


def build_snapshot(
    symbol: str,
    decision_ts: int,
    bids: Sequence[tuple[float, float, int]],
    asks: Sequence[tuple[float, float, int]],
    mids: Sequence[tuple[float, int]],
    inventory: float,
    equity: float,
    peak_equity: float,
    day_start_equity: float,
    position_notional: float,
) -> MarketSnapshot:
    _check_times((ts for _, _, ts in bids), decision_ts)
    _check_times((ts for _, _, ts in asks), decision_ts)
    _check_times((ts for _, ts in mids), decision_ts)
    if not bids or not asks:
        raise ValueError("both sides of the book are required")
    best_bid = max(bids, key=lambda row: row[0])
    best_ask = min(asks, key=lambda row: row[0])
    if best_ask[0] <= 0 or best_bid[0] <= 0 or best_ask[0] < best_bid[0]:
        raise ValueError("crossed or non-positive book")
    mid = (best_bid[0] + best_ask[0]) / 2
    spread_bps = (best_ask[0] - best_bid[0]) / mid * 10_000
    bid_size = sum(size for _, size, _ in bids)
    ask_size = sum(size for _, size, _ in asks)
    total = bid_size + ask_size
    imbalance = 0.0 if total <= 0 else (bid_size - ask_size) / total
    vol = _realized_vol([price for price, _ in mids])
    peak = max(peak_equity, equity, 1e-12)
    drawdown = max(0.0, (peak - equity) / peak)
    daily_loss = max(0.0, (day_start_equity - equity) / day_start_equity) if day_start_equity > 0 else 0.0
    position_fraction = abs(position_notional) / equity if equity > 0 else 1.0
    return MarketSnapshot(
        symbol=symbol,
        decision_ts=decision_ts,
        mid=mid,
        spread_bps=spread_bps,
        imbalance=max(-1.0, min(1.0, imbalance)),
        realized_vol=vol,
        inventory=inventory,
        drawdown=drawdown,
        daily_loss=daily_loss,
        position_fraction=position_fraction,
    )


def _realized_vol(prices: list[float]) -> float:
    if len(prices) < 2:
        return 0.0
    rets = []
    for prev, cur in zip(prices, prices[1:]):
        if prev > 0 and cur > 0:
            rets.append((cur - prev) / prev)
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((item - mean) ** 2 for item in rets) / len(rets)
    return var ** 0.5
