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
    classify_user_utterance_intent,
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
    "user_direct_intent": 2.0,
    "user_mixed_request_with_quote": -4.0,
    "user_quoted_evaluation": -8.0,
    "user_external_commentary": -8.0,
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


def has_conditional_world_state_block(item: dict[str, Any]) -> bool:
    block = item.get("conditional_conflict_block", {})
    return isinstance(block, dict) and bool(block.get("blocks_world_state"))


def apply_conditional_world_state_block(item: dict[str, Any]) -> dict[str, Any]:
    if has_conditional_world_state_block(item):
        item["include_in_world_state"] = False
        item["requires_governance_gate_for_world_state"] = True
        item["requires_review_for_world_state"] = True
        signals = set(str(value) for value in item.get("score_signals", []))
        signals.add("conditional_conflict_block")
        item["score_signals"] = sorted(signals)
    return item


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
        return apply_conditional_world_state_block(item)
    if item.get("source_type") == "manual_initialization" and int(item.get("confidence", 0)) >= 90:
        item["include_in_world_state"] = not any(conflict in unresolved_conflicts for conflict in item.get("conflicts", []))
        return apply_conditional_world_state_block(item)
    if item.get("source_type") == "proposed_update" and item.get("status") == "accepted":
        confidence = int(item.get("confidence", 0))
        item["include_in_world_state"] = confidence >= 90 and not any(conflict in unresolved_conflicts for conflict in item.get("conflicts", []))
        return apply_conditional_world_state_block(item)

    signal_weights = weights["signal_weights"]
    points = 0.0
    matched_signals: list[str] = []
    has_user_evidence = False
    has_agent_evidence = False
    has_tool_evidence = False
    evidence_types: set[str] = set()
    utterance_intents: set[str] = set()

    for evidence_id in item.get("evidence", []):
        utterance = utterances.get(evidence_id)
        if utterance:
            has_user_evidence = True
            evidence_types.add("user_utterance")
            intent = str(utterance.get("utterance_intent") or classify_user_utterance_intent(str(utterance.get("text", ""))))
            utterance_intents.add(intent)
            intent_signal = f"user_{intent}"
            if intent_signal in signal_weights:
                points += signal_weights[intent_signal]
                matched_signals.append(intent_signal)
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
            evidence_types.add("agent_interpretation")
            points += signal_weights["agent_interpretation"]
            matched_signals.append("agent_interpretation")
        tool_record = tool_evidence.get(evidence_id)
        if tool_record:
            has_tool_evidence = True
            evidence_types.add("tool_evidence")
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
            elif kind == "web_result":
                points += signal_weights["tool_web_result"]
                matched_signals.append("tool_web_result")
            elif kind == "command_output":
                points += signal_weights["tool_command_output"]
                matched_signals.append("tool_command_output")
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
    non_direct_intents = utterance_intents - {"direct_user_intent"}
    if has_user_evidence and non_direct_intents and "direct_user_intent" not in utterance_intents and item.get("status") != "accepted":
        confidence = min(84, confidence)
    non_direct_user_material = bool(has_user_evidence and utterance_intents and "direct_user_intent" not in utterance_intents)

    item["confidence"] = confidence
    item["evidence_types"] = sorted(evidence_types)
    if utterance_intents:
        item["utterance_intents"] = sorted(utterance_intents)
    accepted_for_world_state = item.get("status") == "accepted" and (has_user_evidence or has_tool_evidence) and not non_direct_user_material
    requires_governance_gate = bool(
        (has_tool_evidence and not has_user_evidence and item.get("status") != "accepted")
        or non_direct_user_material
        or (confidence >= int(weights["min_world_confidence"]) and not accepted_for_world_state)
    )
    item["requires_governance_gate_for_world_state"] = requires_governance_gate
    item["requires_review_for_world_state"] = requires_governance_gate
    item["include_in_world_state"] = (
        accepted_for_world_state
        and confidence >= 90
        and not any(conflict in unresolved_conflicts for conflict in item.get("conflicts", []))
    )
    if confidence < 50:
        item["include_in_world_state"] = False
    if non_direct_user_material:
        item["include_in_world_state"] = False
        matched_signals.append("non_direct_user_material_blocked")
    if item.get("status") not in {"accepted", "rejected"}:
        item["status"] = "candidate"
    item["score_signals"] = sorted(set(matched_signals))
    return apply_conditional_world_state_block(item)


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
        item = apply_conditional_world_state_block(item)
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
