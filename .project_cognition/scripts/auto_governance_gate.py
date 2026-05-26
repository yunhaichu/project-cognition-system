#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from common import CANDIDATE_CLUSTERS, CONFLICTS, GOVERNANCE_GATE, confidence_table_items, normalize_text, now_iso, read_json, read_jsonl, write_json


ALLOWED_ACCEPTED_SOURCES = {"manual_initialization", "bootstrap_rule", "proposed_update"}
DETERMINISTIC_TOOL_KINDS = {"test_result", "git_result", "filesystem_result"}
SOURCE_PRIORITY = {
    "user_utterance": 0,
    "tool_evidence": 1,
    "proposed_update": 2,
    "manual_initialization": 3,
    "bootstrap_rule": 4,
    "agent_interpretation": 8,
    "assistant_output": 9,
}
PREDICATE_PRIORITY = {
    "enter_core_memory": 0,
    "inject_context": 1,
    "read_source": 2,
    "update_world_state": 3,
    "require_review": 4,
    "score_evidence": 5,
    "resolve_conflict": 6,
    "store_log": 7,
    "override": 8,
}
MODALITY_PRIORITY = {
    "must": 0,
    "must_not": 0,
    "is": 1,
    "is_not": 1,
    "requires": 2,
    "should": 3,
    "may": 5,
    "unknown": 9,
}


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
    utterance_intents = set(str(value) for value in item.get("utterance_intents", []))
    return {
        "has_user_evidence": "user_utterance" in evidence_types or source_type == "user_utterance",
        "has_direct_user_evidence": not utterance_intents or "direct_user_intent" in utterance_intents,
        "has_non_direct_user_evidence": bool(utterance_intents - {"direct_user_intent"}),
        "has_tool_evidence": "tool_evidence" in evidence_types or source_type == "tool_evidence",
        "has_agent_evidence": "agent_interpretation" in evidence_types or source_type == "agent_interpretation",
        "has_assistant_output": source_type == "assistant_output",
        "has_deterministic_tool_evidence": bool(score_signals & {"tool_test_result", "tool_git_result", "tool_filesystem_result", "tool_deterministic"}),
    }


def structured(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("structured", {})
    return value if isinstance(value, dict) else {}


def source_rank(item: dict[str, Any], flags: dict[str, bool]) -> int:
    if flags["has_user_evidence"]:
        return SOURCE_PRIORITY["user_utterance"]
    if flags["has_tool_evidence"]:
        return SOURCE_PRIORITY["tool_evidence"]
    return SOURCE_PRIORITY.get(str(item.get("source_type", "")), 7)


def governance_slot(item: dict[str, Any]) -> str:
    row = structured(item)
    return "|".join(
        [
            str(row.get("scope") or "project"),
            str(item.get("category") or "uncategorized"),
            str(row.get("subject") or "unknown"),
            str(row.get("predicate") or "states"),
            str(row.get("object_key") or row.get("object") or "unknown"),
            str(row.get("modality") or "unknown"),
        ]
    )


def category_key(item: dict[str, Any]) -> str:
    return str(item.get("category") or "uncategorized")


def predicate_key(item: dict[str, Any]) -> str:
    return str(structured(item).get("predicate") or "states")


def item_priority_score(item: dict[str, Any], flags: dict[str, bool]) -> int:
    row = structured(item)
    score = int(item.get("confidence", 0)) * 10
    rank = source_rank(item, flags)
    score += max(0, 90 - rank * 12)
    if item.get("status") == "accepted":
        score += 45
    if str(item.get("source_type", "")) in ALLOWED_ACCEPTED_SOURCES:
        score += 30
    if flags["has_user_evidence"]:
        score += 80
    if flags["has_deterministic_tool_evidence"]:
        score += 55
    if str(row.get("scope") or "project") == "project":
        score += 18
    predicate = str(row.get("predicate") or "states")
    score += max(0, 35 - PREDICATE_PRIORITY.get(predicate, 12) * 3)
    modality = str(row.get("modality") or "unknown")
    score += max(0, 25 - MODALITY_PRIORITY.get(modality, 9) * 3)
    score += min(len(item.get("evidence", [])), 4) * 6
    object_key = str(row.get("object_key") or "")
    if object_key in {"unknown", ""}:
        score -= 40
    if predicate == "states":
        score -= 8
    claim = normalize_text(str(item.get("claim", "")))
    if len(claim) < 20:
        score -= 10
    return score


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
    if flags["has_user_evidence"] and flags["has_non_direct_user_evidence"] and not flags["has_direct_user_evidence"]:
        allowed = False
        reasons.append("quoted_or_external_user_material_not_core")
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
        "priority_score": item_priority_score(item, flags),
        "governance_slot": governance_slot(item),
        "category": category_key(item),
        "predicate": predicate_key(item),
        "confidence": confidence,
        "status": status,
        "source_type": source_type,
        "evidence_types": sorted(str(value) for value in item.get("evidence_types", [])),
    }


def apply_admission_budget(
    decisions: list[dict[str, Any]],
    items_by_id: dict[str, dict[str, Any]],
    *,
    max_allowed: int,
    max_per_category: int,
    max_per_predicate: int,
    max_per_slot: int,
) -> dict[str, Any]:
    allowed_rows = [row for row in decisions if row.get("allowed")]
    ranked = sorted(
        allowed_rows,
        key=lambda row: (
            -int(row.get("priority_score", 0)),
            -int(row.get("confidence", 0)),
            str(row.get("id", "")),
        ),
    )
    category_counts: dict[str, int] = {}
    predicate_counts: dict[str, int] = {}
    slot_counts: dict[str, int] = {}
    kept: set[str] = set()
    budget_blocked: dict[str, list[str]] = {
        "max_allowed": [],
        "max_per_category": [],
        "max_per_predicate": [],
        "max_per_slot": [],
    }
    positive_reasons = {
        "accepted_stable_source",
        "deterministic_tool_evidence_auto_allowed",
        "governance_gate_allowed",
        "user_evidence_auto_allowed",
    }

    for row in ranked:
        item_id = str(row.get("id", ""))
        category = str(row.get("category") or category_key(items_by_id.get(item_id, {})))
        predicate = str(row.get("predicate") or predicate_key(items_by_id.get(item_id, {})))
        slot = str(row.get("governance_slot") or item_id)
        block_reasons: list[str] = []
        if max_allowed > 0 and len(kept) >= max_allowed:
            block_reasons.append("max_allowed")
        if max_per_category > 0 and category_counts.get(category, 0) >= max_per_category:
            block_reasons.append("max_per_category")
        if max_per_predicate > 0 and predicate_counts.get(predicate, 0) >= max_per_predicate:
            block_reasons.append("max_per_predicate")
        if max_per_slot > 0 and slot_counts.get(slot, 0) >= max_per_slot:
            block_reasons.append("max_per_slot")

        if block_reasons:
            row["allowed"] = False
            row["reasons"] = [reason for reason in row.get("reasons", []) if reason not in positive_reasons]
            for reason in block_reasons:
                budget_blocked[reason].append(item_id)
                row.setdefault("reasons", []).append(f"blocked_by_gate_budget_{reason}")
            row["reasons"] = sorted(set(row.get("reasons", [])))
            continue

        kept.add(item_id)
        category_counts[category] = category_counts.get(category, 0) + 1
        predicate_counts[predicate] = predicate_counts.get(predicate, 0) + 1
        slot_counts[slot] = slot_counts.get(slot, 0) + 1

    return {
        "kept_count": len(kept),
        "category_counts": dict(sorted(category_counts.items())),
        "predicate_counts": dict(sorted(predicate_counts.items())),
        "budget_blocked_ids": {key: sorted(value) for key, value in budget_blocked.items()},
    }


def build_gate(
    *,
    min_confidence: int = 90,
    min_confidence_user: int = 95,
    min_confidence_tool: int = 95,
    min_conflict_severity: int = 60,
    max_allowed: int = 80,
    max_per_category: int = 24,
    max_per_predicate: int = 24,
    max_per_slot: int = 1,
) -> dict[str, Any]:
    blocked_by_conflict = unresolved_blocked_ids(min_conflict_severity)
    blocked_duplicates = duplicate_blocked_ids()
    items = confidence_table_items()
    items_by_id = {str(item.get("id", "")): item for item in items}
    decisions = [
        decision_for_item(
            item,
            min_confidence=min_confidence,
            min_confidence_user=min_confidence_user,
            min_confidence_tool=min_confidence_tool,
            blocked_by_conflict=blocked_by_conflict,
            blocked_duplicates=blocked_duplicates,
        )
        for item in items
    ]
    budget = apply_admission_budget(
        decisions,
        items_by_id,
        max_allowed=max_allowed,
        max_per_category=max_per_category,
        max_per_predicate=max_per_predicate,
        max_per_slot=max_per_slot,
    )
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
        "admission_budget": {
            "max_allowed": max_allowed,
            "max_per_category": max_per_category,
            "max_per_predicate": max_per_predicate,
            "max_per_slot": max_per_slot,
            **budget,
        },
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
    parser.add_argument("--max-allowed", type=int, default=80, help="Maximum items allowed into WORLD_STATE before lower-priority items are kept in distilled only. Use 0 for unlimited.")
    parser.add_argument("--max-per-category", type=int, default=24, help="Maximum allowed items per cognition category. Use 0 for unlimited.")
    parser.add_argument("--max-per-predicate", type=int, default=24, help="Maximum allowed items per structured predicate. Use 0 for unlimited.")
    parser.add_argument("--max-per-slot", type=int, default=1, help="Maximum allowed items per structured governance slot. Use 0 for unlimited.")
    args = parser.parse_args()
    result = build_gate(
        min_confidence=args.min_confidence,
        min_confidence_user=args.min_confidence_user,
        min_confidence_tool=args.min_confidence_tool,
        min_conflict_severity=args.min_conflict_severity,
        max_allowed=args.max_allowed,
        max_per_category=args.max_per_category,
        max_per_predicate=args.max_per_predicate,
        max_per_slot=args.max_per_slot,
    )
    write_json(GOVERNANCE_GATE, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
