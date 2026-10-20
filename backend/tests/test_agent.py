import unittest

from app.agent.loop import apply_execution
from app.agent.policy import decide_order, quarter_kelly
from app.agent.risk import MAX_DRAWDOWN
from app.agent.schema import ReflexDecision
from app.agent.state_engine import FutureLeak, build_snapshot


def _book(**kwargs):
    base = dict(
        symbol="BTC",
        decision_ts=1_000,
        bids=[(100.0, 3.0, 900)],
        asks=[(100.4, 1.0, 900)],
        mids=[(100.0, 700), (100.2, 800), (99.9, 900)],
        inventory=0,
        equity=10_000,
        peak_equity=10_000,
        day_start_equity=10_000,
        position_notional=0,
    )
    base.update(kwargs)
    return build_snapshot(**base)


class StateTests(unittest.TestCase):
    def test_snapshot_is_causal(self):
        snap = _book()
        self.assertAlmostEqual(snap.mid, 100.2)
        self.assertGreater(snap.imbalance, 0)

    def test_future_timestamp_is_rejected(self):
        with self.assertRaises(FutureLeak):
            _book(bids=[(100.0, 1.0, 1_001)])

    def test_drawdown_uses_peak(self):
        snap = _book(equity=8_000, peak_equity=10_000)
        self.assertAlmostEqual(snap.drawdown, 0.2)
        self.assertGreaterEqual(snap.drawdown, MAX_DRAWDOWN)


class PolicyTests(unittest.TestCase):
    def test_quarter_kelly_caps(self):
        self.assertEqual(quarter_kelly(0.4), 0)
        self.assertLessEqual(quarter_kelly(0.9), 0.10)

    def test_weak_setup_does_not_fire(self):
        decision = ReflexDecision(
            regime="trending",
            direction="long",
            direction_confidence=0.9,
            toxic_flow=0.1,
            setup_quality=1,
            risk_state="safe",
            probability=0.9,
            action="buy",
            backend="test",
        )
        self.assertFalse(decide_order(decision).fire)

    def test_crisis_escalates(self):
        decision = ReflexDecision(
            regime="crisis",
            direction="long",
            direction_confidence=0.95,
            toxic_flow=0.2,
            setup_quality=3,
            risk_state="safe",
            probability=0.95,
            action="buy",
            backend="test",
        )
        order = decide_order(decision)
        self.assertTrue(order.escalated)
        self.assertFalse(order.fire)

    def test_passing_gate_fires(self):
        decision = ReflexDecision(
            regime="trending",
            direction="long",
            direction_confidence=0.91,
            toxic_flow=0.1,
            setup_quality=3,
            risk_state="safe",
            probability=0.9,
            action="buy",
            backend="test",
        )
        order = decide_order(decision)
        self.assertTrue(order.fire)
        self.assertIn("exchange", order.reason)

    def test_missing_exchange_keys_wait(self):
        import os
        os.environ.pop("BINANCE_API_KEY", None)
        os.environ.pop("BINANCE_API_SECRET", None)
        os.environ.pop("STOCK_BROKER_API_BASE", None)
        os.environ.pop("STOCK_BROKER_API_KEY", None)
        os.environ.pop("STOCK_BROKER_API_SECRET", None)
        decision = ReflexDecision(
            regime="trending",
            direction="long",
            direction_confidence=0.91,
            toxic_flow=0.1,
            setup_quality=3,
            risk_state="safe",
            probability=0.9,
            action="buy",
            backend="test",
        )
        result = apply_execution(decide_order(decision), "600519.SS", 1000, "cn")
        self.assertTrue(result["waiting"])
        self.assertFalse(result["executed"])


if __name__ == "__main__":
    unittest.main()
