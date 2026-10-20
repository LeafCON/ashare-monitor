"""Order gate. Quality, confidence, and risk are enforced here, not in the model."""

from __future__ import annotations

from .risk import MAX_POSITION_FRACTION, kill_switch_on
from .schema import PolicyOrder, ReflexDecision

MIN_QUALITY = 2
MIN_CONFIDENCE = 0.80
ESCALATE_BELOW = 0.60


def quarter_kelly(probability: float, payoff: float = 1.0) -> float:
    """Quarter of the Kelly fraction for a binary payoff. Zero when the edge is not positive."""
    if payoff <= 0:
        return 0.0
    full = probability - (1 - probability) / payoff
    if full <= 0:
        return 0.0
    return min(0.25 * full, MAX_POSITION_FRACTION)


def decide_order(decision: ReflexDecision) -> PolicyOrder:
    if kill_switch_on():
        return PolicyOrder(fire=False, action="hold", reason="kill switch is on")
    if decision.regime == "crisis" or decision.direction_confidence < ESCALATE_BELOW:
        return PolicyOrder(fire=False, action="hold", reason="escalated for a deep re-read", escalated=True)
    if decision.risk_state != "safe":
        return PolicyOrder(fire=False, action="hold", reason=f"risk_state={decision.risk_state}")
    if decision.setup_quality < MIN_QUALITY:
        return PolicyOrder(fire=False, action="hold", reason="setup_quality below 2")
    if decision.direction == "neutral" or decision.direction_confidence <= MIN_CONFIDENCE:
        return PolicyOrder(fire=False, action="hold", reason="direction confidence is not above 0.80")
    if decision.action == "hold":
        return PolicyOrder(fire=False, action="hold", reason="reflex action is hold")
    size = quarter_kelly(decision.probability if decision.action == "buy" else 1 - decision.probability)
    if size <= 0:
        return PolicyOrder(fire=False, action="hold", reason="kelly size is zero")
    return PolicyOrder(fire=True, action=decision.action, size_fraction=size, reason="gates passed; submitting to the exchange")
