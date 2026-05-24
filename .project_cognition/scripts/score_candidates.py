#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from common import (
    AGENT_INTERPRETATIONS,
    CONFLICTS,
    SCORING_WEIGHTS,
    TOOL_EVIDENCE,
    USER_UTTERANCES,
    LONG_TERM_RE,
    confidence_table_items,
    read_json,
    read_jsonl,
    save_confidence_table,
)


DEFAULT_SIGNAL_WEIGHTS = {
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
    "tool_deterministic": 3.0,
    "agent_interpretation": 1.0,
    "assistant_output": 0.5,
    "unresolved_conflict": -5.0,
    "single_weak_non_user_evidence": -2.0,
    "missing_evidence": -5.0,
}


def load_scoring_weights() -> dict[str, Any]:
    data = read_json(SCORING_WEIGHTS, {})
    signal_weights = dict(DEFAULT_SIGNAL_WEIGHTS)
    signal_weights.update(data.get("signal_weights", {}))
    return {
        "base_confidence": float(data.get("base_confidence", 60)),
        "point_multiplier": float(data.get("point_multiplier", 5.0)),
        "min_world_confidence": int(data.get("min_world_confidence", 90)),
        "signal_weights": signal_weights,
    }


def evidence_indexes() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], set[str]]:
    utterances = {record["id"]: record for record in read_jsonl(USER_UTTERANCES)}
    interpretations = {record["id"]: record for record in read_jsonl(AGENT_INTERPRETATIONS)}
    tool_evidence = {record["id"]: record for record in read_jsonl(TOOL_EVIDENCE)}
    unresolved_conflicts = {
        record["id"]
        for record in read_jsonl(CONFLICTS)
        if record.get("resolution") in {"unresolved", "deferred"} and int(record.get("severity", 0)) >= 60
    }
    return utterances, interpretations, tool_evidence, unresolved_conflicts


def score_item(
    item: dict[str, Any],
    utterances: dict[str, dict[str, Any]],
    interpretations: dict[str, dict[str, Any]],
    tool_evidence: dict[str, dict[str, Any]],
    unresolved_conflicts: set[str],
    weights: dict[str, Any],
) -> dict[str, Any]:
    if item.get("status") in {"rejected", "superseded"}:
        item["include_in_world_state"] = False
        return item
    if item.get("source_type") == "bootstrap_rule" and item.get("status") == "accepted":
        confidence = int(item.get("confidence", 0))
        item["include_in_world_state"] = confidence >= 90 and not any(conflict in unresolved_conflicts for conflict in item.get("conflicts", []))
        return item
    if item.get("source_type") == "manual_initialization" and int(item.get("confidence", 0)) >= 90:
        item["include_in_world_state"] = not any(conflict in unresolved_conflicts for conflict in item.get("conflicts", []))
        return item
    if item.get("source_type") == "proposed_update" and item.get("status") == "accepted":
        confidence = int(item.get("confidence", 0))
        item["include_in_world_state"] = confidence >= 90 and not any(conflict in unresolved_conflicts for conflict in item.get("conflicts", []))
        return item

    signal_weights = weights["signal_weights"]
    points = 0.0
    matched_signals: list[str] = []
    has_user_evidence = False
    has_agent_evidence = False
    has_tool_evidence = False

    for evidence_id in item.get("evidence", []):
        utterance = utterances.get(evidence_id)
        if utterance:
            has_user_evidence = True
            signals = utterance.get("signals", {})
            if signals.get("long_form"):
                points += signal_weights["user_long_form"]
                matched_signals.append("user_long_form")
            if signals.get("repeated"):
                points += signal_weights["user_repeated"]
                matched_signals.append("user_repeated")
            if signals.get("explicit_preference"):
                points += signal_weights["user_explicit_preference"]
                matched_signals.append("user_explicit_preference")
            if signals.get("explicit_rejection"):
                points += signal_weights["user_explicit_rejection"]
                matched_signals.append("user_explicit_rejection")
            if signals.get("strong_emphasis"):
                points += signal_weights["user_strong_emphasis"]
                matched_signals.append("user_strong_emphasis")
            if LONG_TERM_RE.search(str(utterance.get("text", ""))):
                points += signal_weights["user_long_term"]
                matched_signals.append("user_long_term")
            if re.search(r"(用户画像|AGENTS\.md|每个项目|项目文件夹)", str(utterance.get("text", ""))):
                points += signal_weights["user_profile_or_project_scope"]
                matched_signals.append("user_profile_or_project_scope")
        if evidence_id in interpretations:
            has_agent_evidence = True
            points += signal_weights["agent_interpretation"]
            matched_signals.append("agent_interpretation")
        tool_record = tool_evidence.get(evidence_id)
        if tool_record:
            has_tool_evidence = True
            kind = str(tool_record.get("evidence_kind", "command_output"))
            points += signal_weights["tool_evidence"]
            matched_signals.append("tool_evidence")
            if kind == "test_result":
                points += signal_weights["tool_test_result"]
                matched_signals.append("tool_test_result")
            elif kind == "git_result":
                points += signal_weights["tool_git_result"]
                matched_signals.append("tool_git_result")
            elif kind == "filesystem_result":
                points += signal_weights["tool_filesystem_result"]
                matched_signals.append("tool_filesystem_result")
            if tool_record.get("deterministic"):
                points += signal_weights["tool_deterministic"]
                matched_signals.append("tool_deterministic")

    if item.get("source_type") == "assistant_output":
        points += signal_weights["assistant_output"]
        matched_signals.append("assistant_output")
    if any(conflict in unresolved_conflicts for conflict in item.get("conflicts", [])):
        points += signal_weights["unresolved_conflict"]
        matched_signals.append("unresolved_conflict")
    if len(item.get("evidence", [])) == 1 and not has_user_evidence and not has_agent_evidence and not has_tool_evidence:
        points += signal_weights["single_weak_non_user_evidence"]
        matched_signals.append("single_weak_non_user_evidence")
    if not item.get("evidence"):
        points += signal_weights["missing_evidence"]
        matched_signals.append("missing_evidence")

    if not has_user_evidence and has_agent_evidence and not has_tool_evidence:
        confidence = min(74, int(weights["base_confidence"] + points * weights["point_multiplier"]))
    else:
        confidence = int(weights["base_confidence"] + points * weights["point_multiplier"])
    confidence = max(0, min(100, confidence))
    if has_tool_evidence and not has_user_evidence and item.get("status") != "accepted":
        confidence = min(89, confidence)

    item["confidence"] = confidence
    item["score_signals"] = sorted(set(matched_signals))
    item["include_in_world_state"] = confidence >= 90 and not any(conflict in unresolved_conflicts for conflict in item.get("conflicts", []))
    if confidence < 50:
        item["include_in_world_state"] = False
    if item.get("status") not in {"accepted", "rejected"}:
        item["status"] = "candidate"
    return item


def main() -> None:
    parser = argparse.ArgumentParser(description="Score cognition candidates using simple evidence-weight rules.")
    weights = load_scoring_weights()
    parser.add_argument("--min-world-confidence", type=int, default=weights["min_world_confidence"], help="Minimum confidence for WORLD_STATE inclusion.")
    args = parser.parse_args()

    utterances, interpretations, tool_evidence, unresolved_conflicts = evidence_indexes()
    scored = [score_item(item, utterances, interpretations, tool_evidence, unresolved_conflicts, weights) for item in confidence_table_items()]
    for item in scored:
        if int(item.get("confidence", 0)) < args.min_world_confidence:
            item["include_in_world_state"] = False
        if re.search(r"无证据|没有证据", str(item.get("claim", ""))):
            item["include_in_world_state"] = False
    save_confidence_table(scored)

    summary = {
        "total": len(scored),
        "include_in_world_state": sum(1 for item in scored if item.get("include_in_world_state")),
        "min_world_confidence": args.min_world_confidence,
        "weights_file": str(SCORING_WEIGHTS),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
