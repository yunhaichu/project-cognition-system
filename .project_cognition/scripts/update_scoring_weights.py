#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from common import SCORING_FEEDBACK, SCORING_WEIGHTS, now_iso, read_json, read_jsonl, write_json


DEFAULT_WEIGHTS: dict[str, Any] = {
    "version": 1,
    "updated_at": now_iso(),
    "base_confidence": 60,
    "point_multiplier": 5.0,
    "min_world_confidence": 90,
    "signal_weights": {
        "user_long_form": 5.0,
        "user_repeated": 5.0,
        "user_explicit_preference": 4.0,
        "user_explicit_rejection": 4.0,
        "user_strong_emphasis": 3.0,
        "user_long_term": 5.0,
        "user_profile_or_project_scope": 4.0,
        "agent_interpretation": 1.0,
        "assistant_output": 0.5,
        "unresolved_conflict": -5.0,
        "single_weak_non_user_evidence": -2.0,
        "missing_evidence": -5.0,
    },
    "bounds": {
        "min_signal_weight": -12.0,
        "max_signal_weight": 12.0,
        "learning_rate": 0.25,
    },
}


def load_weights() -> dict[str, Any]:
    data = read_json(SCORING_WEIGHTS, DEFAULT_WEIGHTS)
    merged = json.loads(json.dumps(DEFAULT_WEIGHTS))
    merged.update({key: value for key, value in data.items() if key not in {"signal_weights", "bounds"}})
    merged["signal_weights"].update(data.get("signal_weights", {}))
    merged["bounds"].update(data.get("bounds", {}))
    return merged


def feedback_delta(action: str) -> float:
    if action == "accept":
        return 1.0
    if action == "reject":
        return -1.0
    return 0.0


def update_weights(dry_run: bool = False) -> dict[str, Any]:
    weights = load_weights()
    feedback_rows = read_jsonl(SCORING_FEEDBACK)
    signal_weights = dict(weights.get("signal_weights", {}))
    learning_rate = float(weights.get("bounds", {}).get("learning_rate", 0.25))
    min_weight = float(weights.get("bounds", {}).get("min_signal_weight", -12.0))
    max_weight = float(weights.get("bounds", {}).get("max_signal_weight", 12.0))

    applied = 0
    for row in feedback_rows:
        if row.get("applied_to_weights"):
            continue
        action = str(row.get("action", ""))
        delta = feedback_delta(action)
        if delta == 0:
            row["applied_to_weights"] = True
            applied += 1
            continue
        confidence = int(row.get("proposal_confidence", 50))
        strength = max(0.5, min(1.5, confidence / 90))
        for signal in row.get("signals", []):
            if signal not in signal_weights:
                continue
            current = float(signal_weights[signal])
            adjusted = current + delta * learning_rate * strength
            signal_weights[signal] = round(max(min_weight, min(max_weight, adjusted)), 3)
        row["applied_to_weights"] = True
        row["applied_at"] = now_iso()
        applied += 1

    weights["signal_weights"] = signal_weights
    weights["updated_at"] = now_iso()
    weights["feedback_seen"] = len(feedback_rows)
    weights["feedback_applied_total"] = int(weights.get("feedback_applied_total", 0)) + applied

    if not dry_run:
        write_json(SCORING_WEIGHTS, weights)
        if feedback_rows:
            from common import write_jsonl

            write_jsonl(SCORING_FEEDBACK, feedback_rows)
    return {"weights": weights, "applied": applied, "feedback_total": len(feedback_rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Update scoring weights from proposal review feedback.")
    parser.add_argument("--dry-run", action="store_true", help="Compute updates without writing files.")
    args = parser.parse_args()
    result = update_weights(args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
