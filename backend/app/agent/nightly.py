"""Nightly calibration note. Brier score is computed only from logged outcomes."""

from __future__ import annotations

import json
from pathlib import Path

JOURNAL = Path(__file__).resolve().parents[3] / "data" / "agent_journal.jsonl"


def brier_score(rows: list[dict]) -> float | None:
    pairs = []
    for row in rows:
        outcome = row.get("outcome")
        probability = (row.get("decision") or {}).get("probability")
        if outcome in (0, 1) and isinstance(probability, (int, float)):
            pairs.append((float(probability), int(outcome)))
    if not pairs:
        return None
    return sum((prob - outcome) ** 2 for prob, outcome in pairs) / len(pairs)


def review() -> dict:
    rows = []
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    fired = sum(1 for row in rows if (row.get("order") or {}).get("fire"))
    held = len(rows) - fired
    return {
        "ticks": len(rows),
        "fired": fired,
        "held": held,
        "brier": brier_score(rows),
        "note": "No schema rewrite is shipped automatically. Outcomes are absent until the operator labels them.",
    }
