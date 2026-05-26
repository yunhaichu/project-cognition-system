#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from common import CANDIDATE_CLUSTERS, CONFLICTS, GOVERNANCE_GATE, confidence_table_items, now_iso, read_json, read_jsonl, write_json


ALLOWED_ACCEPTED_SOURCES = {"manual_initialization", "bootstrap_rule", "proposed_update"}
DETERMINISTIC_TOOL_KINDS = {"test_result", "git_result", "filesystem_result"}


def unresolved_blocked_ids(min_severity: int) -> set[str]:
    blocked: set[str] = set()
    for conflict in read_jsonl(CONFLICTS):
        if conflict.get("resolution") in {"unresolved", "deferred"} and int(conflict.get("severity", 0)) >= min_severity:
            blocked.add(str(conflict.get("item_a", "")))
            blocked.add(str(conflict.get("item_b", "")))
    return {value for value in blocked if value}


def duplicate_blocked_ids() -> set[str]:
    if not CANDIDATE_CLUSTERS.exists():
        return set()
    data = read_json(CANDIDATE_CLUSTERS, {})
    blocked: set[str] = set()
    for cluster in data.get("clusters", []):
        blocked.update(str(value) for value in cluster.get("blocked_from_core_suggestions", []))
    return {value for value in blocked if value}


def evidence_flags(item: dict[str, Any]) -> dict[str, bool]:
    evidence_types = set(str(value) for value in item.get("evidence_types", []))
    source_type = str(item.get("source_type", ""))
    score_signals = set(str(value) for value in item.get("score_signals", []))
    return {
        "has_user_evidence": "user_utterance" in evidence_types or source_type == "user_utterance",
        "has_tool_evidence": "tool_evidence" in evidence_types or source_type == "tool_evidence",
        "has_agent_evidence": "agent_interpretation" in evidence_types or source_type == "agent_interpretation",
        "has_assistant_output": source_type == "assistant_output",
        "has_deterministic_tool_evidence": bool(score_signals & {"tool_test_result", "tool_git_result", "tool_filesystem_result", "tool_deterministic"}),
    }


def decision_for_item(
    item: dict[str, Any],
    *,
    min_confidence: int,
    min_confidence_user: int,
    min_confidence_tool: int,
    blocked_by_conflict: set[str],
    blocked_duplicates: set[str],
) -> dict[str, Any]:
    item_id = str(item.get("id", ""))
    confidence = int(item.get("confidence", 0))
    source_type = str(item.get("source_type", ""))
    status = str(item.get("status", ""))
    flags = evidence_flags(item)
    reasons: list[str] = []
    allowed = True

    if status in {"rejected", "superseded"}:
        allowed = False
        reasons.append(f"status_{status}")
    if item_id in blocked_by_conflict:
        allowed = False
        reasons.append("blocked_by_unresolved_conflict")
    if item_id in blocked_duplicates:
        allowed = False
        reasons.append("blocked_as_duplicate_candidate")
    if flags["has_assistant_output"]:
        allowed = False
        reasons.append("assistant_output_log_only")
    if flags["has_agent_evidence"] and not flags["has_user_evidence"] and not flags["has_tool_evidence"]:
        allowed = False
        reasons.append("agent_only_evidence")
    if not item.get("evidence") and source_type not in {"manual_initialization", "bootstrap_rule"}:
        allowed = False
        reasons.append("missing_evidence")

    threshold = min_confidence
    if flags["has_user_evidence"]:
        threshold = min_confidence_user
    elif flags["has_tool_evidence"]:
        threshold = min_confidence_tool
    if confidence < threshold:
        allowed = False
        reasons.append(f"confidence_below_{threshold}")

    if source_type in ALLOWED_ACCEPTED_SOURCES and status == "accepted" and confidence >= min_confidence:
        if not (item_id in blocked_by_conflict or item_id in blocked_duplicates):
            allowed = True
            reasons = [reason for reason in reasons if not reason.startswith("confidence_below_") and reason != "missing_evidence"]
            reasons.append("accepted_stable_source")
    elif flags["has_user_evidence"] and confidence >= min_confidence_user:
        reasons.append("user_evidence_auto_allowed" if allowed else "user_evidence_present")
    elif flags["has_tool_evidence"] and flags["has_deterministic_tool_evidence"] and confidence >= min_confidence_tool:
        reasons.append("deterministic_tool_evidence_auto_allowed" if allowed else "deterministic_tool_evidence_present")
    elif flags["has_tool_evidence"]:
        allowed = False
        reasons.append("tool_evidence_needs_user_anchor_or_deterministic_signal")

    if allowed and not reasons:
        reasons.append("governance_gate_allowed")

    return {
        "id": item_id,
        "allowed": bool(allowed),
        "reasons": sorted(set(reasons)),
        "confidence": confidence,
        "status": status,
        "source_type": source_type,
        "evidence_types": sorted(str(value) for value in item.get("evidence_types", [])),
    }


def build_gate(
    *,
    min_confidence: int = 90,
    min_confidence_user: int = 95,
    min_confidence_tool: int = 95,
    min_conflict_severity: int = 60,
) -> dict[str, Any]:
    blocked_by_conflict = unresolved_blocked_ids(min_conflict_severity)
    blocked_duplicates = duplicate_blocked_ids()
    decisions = [
        decision_for_item(
            item,
            min_confidence=min_confidence,
            min_confidence_user=min_confidence_user,
            min_confidence_tool=min_confidence_tool,
            blocked_by_conflict=blocked_by_conflict,
            blocked_duplicates=blocked_duplicates,
        )
        for item in confidence_table_items()
    ]
    allowed_ids = sorted(row["id"] for row in decisions if row.get("allowed"))
    blocked_rows = [row for row in decisions if not row.get("allowed")]
    blocked_reason_counts: dict[str, int] = {}
    for row in blocked_rows:
        for reason in row.get("reasons", []):
            blocked_reason_counts[reason] = blocked_reason_counts.get(reason, 0) + 1
    return {
        "generated_at": now_iso(),
        "item_count": len(decisions),
        "allowed_count": len(allowed_ids),
        "blocked_count": len(blocked_rows),
        "allowed_item_ids": allowed_ids,
        "blocked_by_conflict_ids": sorted(blocked_by_conflict),
        "blocked_duplicate_ids": sorted(blocked_duplicates),
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        "decisions": decisions,
        "thresholds": {
            "min_confidence": min_confidence,
            "min_confidence_user": min_confidence_user,
            "min_confidence_tool": min_confidence_tool,
            "min_conflict_severity": min_conflict_severity,
        },
        "note": "Automated governance gate only; no human review is required or performed. The gate does not edit raw evidence or confidence_table.json.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build automated governance admission decisions for WORLD_STATE inclusion.")
    parser.add_argument("--min-confidence", type=int, default=90, help="Minimum confidence for accepted stable sources.")
    parser.add_argument("--min-confidence-user", type=int, default=95, help="Minimum confidence for user-evidence candidates.")
    parser.add_argument("--min-confidence-tool", type=int, default=95, help="Minimum confidence for deterministic tool-evidence candidates.")
    parser.add_argument("--min-conflict-severity", type=int, default=60, help="Conflict severity that blocks both sides.")
    args = parser.parse_args()
    result = build_gate(
        min_confidence=args.min_confidence,
        min_confidence_user=args.min_confidence_user,
        min_confidence_tool=args.min_confidence_tool,
        min_conflict_severity=args.min_conflict_severity,
    )
    write_json(GOVERNANCE_GATE, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
