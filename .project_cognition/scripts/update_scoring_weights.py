#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from common import SCORING_FEEDBACK, SCORING_WEIGHTS, now_iso, read_json, read_jsonl, write_json


SCORING_WEIGHT_SHADOW_REPORT = SCORING_WEIGHTS.parent / "scoring_weight_shadow_report.json"

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
        "tool_evidence": 4.0,
        "tool_test_result": 4.0,
        "tool_git_result": 3.0,
        "tool_filesystem_result": 3.0,
        "tool_web_result": 1.0,
        "tool_command_output": 0.5,
        "tool_deterministic": 3.0,
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


def deep_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def load_weights() -> dict[str, Any]:
    data = read_json(SCORING_WEIGHTS, DEFAULT_WEIGHTS)
    merged = deep_copy(DEFAULT_WEIGHTS)
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


def plan_update(weights: dict[str, Any], feedback_rows: list[dict[str, Any]]) -> dict[str, Any]:
    planned_weights = deep_copy(weights)
    planned_feedback = deep_copy(feedback_rows)
    signal_weights = dict(planned_weights.get("signal_weights", {}))
    before_signal_weights = dict(signal_weights)
    bounds = planned_weights.get("bounds", {})
    learning_rate = float(bounds.get("learning_rate", 0.25))
    min_weight = float(bounds.get("min_signal_weight", -12.0))
    max_weight = float(bounds.get("max_signal_weight", 12.0))

    would_apply = 0
    ignored_signals: dict[str, int] = {}
    zero_delta_feedback_ids: list[str] = []
    bounds_hit: list[dict[str, Any]] = []
    pending_feedback_ids: list[str] = []

    for row in planned_feedback:
        if row.get("applied_to_weights"):
            continue
        feedback_id = str(row.get("id", ""))
        if feedback_id:
            pending_feedback_ids.append(feedback_id)
        action = str(row.get("action", ""))
        delta = feedback_delta(action)
        if delta == 0:
            if feedback_id:
                zero_delta_feedback_ids.append(feedback_id)
            row["applied_to_weights"] = True
            row["applied_at"] = now_iso()
            would_apply += 1
            continue
        confidence = int(row.get("proposal_confidence", 50))
        strength = max(0.5, min(1.5, confidence / 90))
        touched = False
        for signal in row.get("signals", []):
            if signal not in signal_weights:
                ignored_signals[str(signal)] = ignored_signals.get(str(signal), 0) + 1
                continue
            current = float(signal_weights[signal])
            raw_adjusted = current + delta * learning_rate * strength
            adjusted = round(max(min_weight, min(max_weight, raw_adjusted)), 3)
            if adjusted in {min_weight, max_weight} and adjusted != round(raw_adjusted, 3):
                bounds_hit.append({"feedback_id": feedback_id, "signal": signal, "raw_adjusted": round(raw_adjusted, 3), "bounded": adjusted})
            signal_weights[signal] = adjusted
            touched = True
        row["applied_to_weights"] = True
        row["applied_at"] = now_iso()
        if touched:
            would_apply += 1

    changed_signals: dict[str, dict[str, float]] = {}
    for signal, before in sorted(before_signal_weights.items()):
        after = float(signal_weights.get(signal, before))
        if float(before) != after:
            changed_signals[signal] = {"before": float(before), "after": after, "delta": round(after - float(before), 3)}

    planned_weights["signal_weights"] = signal_weights
    planned_weights["updated_at"] = now_iso()
    planned_weights["feedback_seen"] = len(feedback_rows)
    planned_weights["feedback_applied_total"] = int(planned_weights.get("feedback_applied_total", 0)) + would_apply

    return {
        "planned_weights": planned_weights,
        "planned_feedback": planned_feedback,
        "would_apply": would_apply,
        "pending_feedback_ids": pending_feedback_ids,
        "changed_signals": changed_signals,
        "ignored_signals": dict(sorted(ignored_signals.items())),
        "zero_delta_feedback_ids": zero_delta_feedback_ids,
        "bounds_hit": bounds_hit,
    }


def update_weights(*, apply: bool = False, write_shadow: bool = True) -> dict[str, Any]:
    weights = load_weights()
    feedback_rows = read_jsonl(SCORING_FEEDBACK)
    plan = plan_update(weights, feedback_rows)
    shadow_report = {
        "generated_at": now_iso(),
        "mode": "apply" if apply else "shadow",
        "writes_weights": bool(apply),
        "writes_feedback": bool(apply),
        "writes_shadow_report": bool(write_shadow),
        "weights_file": str(SCORING_WEIGHTS),
        "feedback_file": str(SCORING_FEEDBACK),
        "shadow_report_file": str(SCORING_WEIGHT_SHADOW_REPORT),
        "feedback_total": len(feedback_rows),
        "pending_feedback_count": len(plan["pending_feedback_ids"]),
        "would_apply": int(plan["would_apply"]),
        "changed_signal_count": len(plan["changed_signals"]),
        "changed_signals": plan["changed_signals"],
        "ignored_signals": plan["ignored_signals"],
        "zero_delta_feedback_ids": plan["zero_delta_feedback_ids"],
        "bounds_hit": plan["bounds_hit"],
        "note": "Default mode is shadow-only. Use --apply to mutate scoring_weights.json and mark feedback rows applied.",
    }

    if apply:
        write_json(SCORING_WEIGHTS, plan["planned_weights"])
        if feedback_rows:
            from common import write_jsonl

            write_jsonl(SCORING_FEEDBACK, plan["planned_feedback"])
    if write_shadow:
        write_json(SCORING_WEIGHT_SHADOW_REPORT, shadow_report)
    return shadow_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan or apply scoring weight updates from proposal review feedback.")
    parser.add_argument("--apply", action="store_true", help="Actually write scoring_weights.json and mark feedback rows applied. Default is shadow-only.")
    parser.add_argument("--dry-run", action="store_true", help="Deprecated compatibility flag. Dry-run is now the default unless --apply is set.")
    parser.add_argument("--no-write-shadow", action="store_true", help="Do not write distilled/scoring_weight_shadow_report.json.")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("--apply and --dry-run cannot be used together.")
    result = update_weights(apply=args.apply, write_shadow=not args.no_write_shadow)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
