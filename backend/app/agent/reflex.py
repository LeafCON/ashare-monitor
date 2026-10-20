"""Reflex backends.

Jev is used only when JEV_API_KEY is set. Otherwise the process loads
HuggingFaceTB/SmolLM2-135M-Instruct if transformers is installed.
If that model is not on disk, a local calibrated scorer returns the same schema.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

from .risk import risk_state
from .schema import MarketSnapshot, ReflexDecision

HF_MODEL_ID = os.getenv("HF_REFLEX_MODEL", "Qwen/Qwen2.5-0.5B-Instruct-GGUF")
LLAMA_URL = os.getenv("LLAMA_SERVER_URL", "http://127.0.0.1:8091").rstrip("/")
JEV_URL = os.getenv("JEV_API_URL", "https://jevtypesafeai.com/api/v1/decide")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class LocalCalibratedReflex:
    """Numeric scorer. It does not see charts and it does not place orders."""

    backend = "local_calibrated"

    def judge(self, snapshot: MarketSnapshot) -> ReflexDecision:
        started = time.perf_counter()
        state = risk_state(snapshot)
        if snapshot.realized_vol > 0.02 or snapshot.spread_bps > 50:
            regime = "high_vol"
        elif snapshot.drawdown > 0.10:
            regime = "crisis"
        elif abs(snapshot.imbalance) < 0.15 and snapshot.realized_vol < 0.005:
            regime = "mean_reverting"
        else:
            regime = "trending"
        probability = _clamp(0.5 + 0.25 * snapshot.imbalance - snapshot.realized_vol)
        if regime == "crisis" or state == "reduce":
            direction, confidence, quality, action = "neutral", 0.4, 0, "hold"
        elif probability >= 0.62 and snapshot.imbalance > 0.2:
            direction, confidence, quality, action = "long", min(0.9, probability + 0.2), 2, "buy"
        elif probability <= 0.38 and snapshot.imbalance < -0.2:
            direction, confidence, quality, action = "short", min(0.9, 1 - probability), 2, "sell"
        else:
            direction, confidence, quality, action = "neutral", 0.55, 1, "hold"
        toxic = _clamp(snapshot.spread_bps / 100 + max(0, -snapshot.imbalance) * 0.3)
        return ReflexDecision(
            regime=regime,
            direction=direction,
            direction_confidence=confidence,
            toxic_flow=toxic,
            setup_quality=quality,
            risk_state=state,  # type: ignore[arg-type]
            probability=probability,
            action=action,
            backend=self.backend,
            latency_ms=(time.perf_counter() - started) * 1000,
        )


class JevReflex:
    backend = "jev"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def judge(self, snapshot: MarketSnapshot) -> ReflexDecision:
        started = time.perf_counter()
        payload = json.dumps({"state": snapshot.model_dump(), "schema": "trading_gate_v1"}).encode()
        request = urllib.request.Request(
            JEV_URL,
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = json.loads(response.read().decode())
        decision = ReflexDecision.model_validate(body)
        decision.backend = self.backend
        decision.latency_ms = (time.perf_counter() - started) * 1000
        decision.risk_state = risk_state(snapshot)  # type: ignore[assignment]
        return decision


class HuggingFaceReflex:
    """Local SmolLM2. Used only when the weights are already installed."""

    backend = "huggingface:" + HF_MODEL_ID

    def __init__(self) -> None:
        from transformers import pipeline

        self.pipe = pipeline("text-generation", model=HF_MODEL_ID, device_map="auto")

    def judge(self, snapshot: MarketSnapshot) -> ReflexDecision:
        started = time.perf_counter()
        prompt = (
            "Return one JSON object with regime, direction, direction_confidence, "
            "toxic_flow, setup_quality, probability, action. State: "
            + snapshot.model_dump_json()
        )
        text = self.pipe(prompt, max_new_tokens=120, do_sample=False)[0]["generated_text"]
        start = text.rfind("{")
        end = text.rfind("}")
        raw = json.loads(text[start : end + 1]) if start >= 0 and end > start else {}
        raw["risk_state"] = risk_state(snapshot)
        raw["backend"] = self.backend
        raw["latency_ms"] = (time.perf_counter() - started) * 1000
        return ReflexDecision.model_validate(raw)


class LlamaServerReflex:
    """Local GGUF server. The weights are Qwen2.5-0.5B-Instruct Q4_K_M."""

    backend = "huggingface:" + HF_MODEL_ID

    def judge(self, snapshot: MarketSnapshot) -> ReflexDecision:
        started = time.perf_counter()
        prompt = (
            "Reply with one JSON object only. Keys: regime (trending|mean_reverting|high_vol|crisis), "
            "direction (long|short|neutral), direction_confidence (0-1), toxic_flow (0-1), "
            "setup_quality (0-3 integer), probability (0-1), action (buy|sell|hold). State: "
            + snapshot.model_dump_json()
        )
        payload = json.dumps({
            "messages": [
                {"role": "system", "content": "You are a trading gate. Output one JSON object and nothing else."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 160,
        }).encode()
        request = urllib.request.Request(
            LLAMA_URL + "/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _local_open(request, 60) as response:
            body = json.loads(response.read().decode())
        text = body["choices"][0]["message"]["content"]
        start = text.find("{")
        end = text.rfind("}")
        raw = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
        raw["risk_state"] = risk_state(snapshot)
        raw.setdefault("regime", "mean_reverting")
        raw.setdefault("direction", "neutral")
        raw.setdefault("direction_confidence", 0.5)
        raw.setdefault("toxic_flow", 0.0)
        raw.setdefault("setup_quality", 0)
        raw.setdefault("probability", 0.5)
        raw.setdefault("action", "hold")
        raw["backend"] = self.backend
        raw["latency_ms"] = (time.perf_counter() - started) * 1000
        return ReflexDecision.model_validate(raw)


def _local_open(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def llama_server_up() -> bool:
    try:
        with _local_open(urllib.request.Request(LLAMA_URL + "/health"), 2) as response:
            return response.status == 200
    except Exception:
        return False


def load_reflex():
    if llama_server_up():
        return LlamaServerReflex()
    key = os.getenv("JEV_API_KEY", "").strip()
    if key:
        return JevReflex(key)
    if os.getenv("AGENT_HF", "").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            return HuggingFaceReflex()
        except Exception:
            pass
    return LocalCalibratedReflex()
