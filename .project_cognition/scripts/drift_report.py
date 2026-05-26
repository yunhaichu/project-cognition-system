#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from common import CANDIDATE_CLUSTERS, CONFLICT_CLUSTERS, CONFLICTS, WORLD_STATE_COMPACT, confidence_table_items, read_json, read_jsonl
from validate_state import validate_state


def assistant_only_core_items(items: list[dict[str, Any]]) -> list[str]:
    offenders: list[str] = []
    for item in items:
        if not item.get("include_in_world_state"):
            continue
        source_type = str(item.get("source_type", ""))
        evidence_types = set(item.get("evidence_types", []))
        if source_type == "assistant_output":
            offenders.append(str(item.get("id", "")))
        elif source_type == "agent_interpretation" and not (evidence_types & {"user_utterance", "tool_evidence"}):
            offenders.append(str(item.get("id", "")))
    return sorted(filter(None, offenders))


def stale_revived_items(items: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(item.get("id", ""))
        for item in items
        if item.get("status") in {"superseded", "rejected"} and item.get("include_in_world_state")
    )


def candidate_core_items(items: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(item.get("id", ""))
        for item in items
        if item.get("include_in_world_state")
        and item.get("status") != "accepted"
        and item.get("source_type") not in {"manual_initialization", "bootstrap_rule"}
    )


def evidence_mix(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"user_utterance": 0, "tool_evidence": 0, "agent_interpretation": 0, "assistant_output": 0, "other": 0}
    for item in items:
        source_type = str(item.get("source_type", ""))
        if source_type in counts:
            counts[source_type] += 1
        else:
            counts["other"] += 1
    return counts


def load_cluster_count() -> tuple[int, bool]:
    if not CONFLICT_CLUSTERS.exists():
        return 0, False
    data = read_json(CONFLICT_CLUSTERS, {})
    return int(data.get("cluster_count", 0)), True


def load_candidate_cluster_metrics() -> tuple[int, int, float, bool]:
    if not CANDIDATE_CLUSTERS.exists():
        return 0, 0, 0.0, False
    data = read_json(CANDIDATE_CLUSTERS, {})
    return (
        int(data.get("cluster_count", 0)),
        int(data.get("duplicate_candidate_count", 0)),
        float(data.get("duplicate_ratio", 0.0)),
        True,
    )


def build_report(
    *,
    max_compact_chars: int,
    max_high_severity_conflicts: int,
) -> dict[str, Any]:
    items = confidence_table_items()
    conflicts = read_jsonl(CONFLICTS)
    compact_text = WORLD_STATE_COMPACT.read_text(encoding="utf-8") if WORLD_STATE_COMPACT.exists() else ""
    validation = validate_state(WORLD_STATE_COMPACT.parents[1])
    high_unresolved = [
        conflict
        for conflict in conflicts
        if conflict.get("resolution") in {"unresolved", "deferred"} and int(conflict.get("severity", 0)) >= 75
    ]
    cluster_count, cluster_file_exists = load_cluster_count()
    candidate_cluster_count, duplicate_candidate_count, duplicate_candidate_ratio, candidate_cluster_file_exists = load_candidate_cluster_metrics()
    stale_revived = stale_revived_items(items)
    assistant_only_core = assistant_only_core_items(items)
    candidate_core = candidate_core_items(items)
    hard_failures: list[str] = []
    warnings: list[str] = []

    if len(compact_text) > max_compact_chars:
        hard_failures.append("compact_characters_exceeded")
    if validation.get("errors"):
        hard_failures.append("dangling_or_invalid_references")
    if stale_revived:
        hard_failures.append("stale_rule_revived")
    if assistant_only_core:
        hard_failures.append("assistant_only_entered_core")
    if candidate_core:
        hard_failures.append("unreviewed_candidate_entered_core")
    if len(high_unresolved) > max_high_severity_conflicts:
        warnings.append("conflict_budget_exceeded")
    if duplicate_candidate_ratio >= 0.5 and duplicate_candidate_count >= 20:
        warnings.append("candidate_duplicate_noise_high")

    return {
        "compact_characters": len(compact_text),
        "max_compact_chars": max_compact_chars,
        "unresolved_high_severity_conflicts": len(high_unresolved),
        "max_high_severity_conflicts": max_high_severity_conflicts,
        "conflict_cluster_count": cluster_count,
        "conflict_cluster_file_exists": cluster_file_exists,
        "candidate_cluster_count": candidate_cluster_count,
        "candidate_cluster_file_exists": candidate_cluster_file_exists,
        "duplicate_candidate_count": duplicate_candidate_count,
        "duplicate_candidate_ratio": duplicate_candidate_ratio,
        "dangling_reference_errors": len(validation.get("errors", [])),
        "stale_revived_items": stale_revived,
        "assistant_only_core_items": assistant_only_core,
        "candidate_core_items": candidate_core,
        "evidence_mix": evidence_mix(items),
        "warnings": warnings,
        "hard_failures": hard_failures,
        "ok": not hard_failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report context-drift risk budgets for Project Cognition state.")
    parser.add_argument("--max-compact-chars", type=int, default=1600, help="Hard budget for WORLD_STATE_COMPACT.md.")
    parser.add_argument(
        "--max-high-severity-conflicts",
        type=int,
        default=100,
        help="Warning budget for unresolved/deferred conflicts with severity >= 75.",
    )
    parser.add_argument("--fail-on-conflict-budget", action="store_true", help="Treat conflict budget warning as a hard failure.")
    args = parser.parse_args()
    report = build_report(
        max_compact_chars=args.max_compact_chars,
        max_high_severity_conflicts=args.max_high_severity_conflicts,
    )
    if args.fail_on_conflict_budget and "conflict_budget_exceeded" in report["warnings"]:
        report["hard_failures"].append("conflict_budget_exceeded")
        report["ok"] = False
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
