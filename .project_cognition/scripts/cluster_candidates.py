#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from build_vector_index import vectorize_text
from common import CANDIDATE_CLUSTERS, confidence_table_items, now_iso, stable_id, write_json


ACTIVE_STATUSES = {"candidate", "accepted", "manual_initialization", "bootstrap_rule", ""}
AUTHORITY_ORDER = {
    "user_utterance": 0,
    "tool_evidence": 1,
    "manual_initialization": 2,
    "bootstrap_rule": 3,
    "agent_interpretation": 4,
    "assistant_output": 5,
}


def structured(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("structured", {})
    return value if isinstance(value, dict) else {}


def source_authority(item: dict[str, Any]) -> int:
    source_type = str(item.get("source_type", ""))
    evidence_types = set(str(value) for value in item.get("evidence_types", []))
    if "user_utterance" in evidence_types:
        return AUTHORITY_ORDER["user_utterance"]
    if "tool_evidence" in evidence_types:
        return AUTHORITY_ORDER["tool_evidence"]
    return AUTHORITY_ORDER.get(source_type, 9)


def active_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in confidence_table_items():
        if str(item.get("status", "")) not in ACTIVE_STATUSES:
            continue
        if not str(item.get("id", "")):
            continue
        items.append(item)
    return items


def cluster_key(item: dict[str, Any]) -> str:
    row = structured(item)
    return "|".join(
        [
            str(row.get("scope") or "project"),
            str(row.get("subject") or "unknown"),
            str(row.get("predicate") or "states"),
            str(row.get("object_key") or row.get("object") or "unknown"),
            str(row.get("modality") or "unknown"),
        ]
    )


def weak_cluster_key(key: str) -> bool:
    scope, subject, predicate, object_key, modality = (key.split("|") + ["", "", "", "", ""])[:5]
    if subject == "unknown" and predicate == "states" and object_key == "unknown":
        return True
    if predicate == "states" and object_key in {"unknown", ""}:
        return True
    if object_key in {"unknown", ""} and modality == "unknown":
        return True
    return False


def claim_similarity(left: str, right: str) -> float:
    left_vector = vectorize_text(left, dimensions=1024)
    right_vector = vectorize_text(right, dimensions=1024)
    if not left_vector or not right_vector:
        return 0.0
    if len(left_vector) > len(right_vector):
        left_vector, right_vector = right_vector, left_vector
    return sum(value * right_vector.get(key, 0.0) for key, value in left_vector.items())


def representative(items: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(
        items,
        key=lambda item: (
            source_authority(item),
            0 if item.get("status") == "accepted" else 1,
            -int(item.get("confidence", 0)),
            -len(item.get("evidence", [])),
            str(item.get("id", "")),
        ),
    )[0]


def pairwise_max_similarity(items: list[dict[str, Any]]) -> float:
    if len(items) < 2:
        return 1.0
    best = 0.0
    claims = [str(item.get("claim", "")) for item in items]
    for left_index, left in enumerate(claims):
        for right in claims[left_index + 1 :]:
            best = max(best, claim_similarity(left, right))
    return round(best, 4)


def governance_action(items: list[dict[str, Any]], rep: dict[str, Any]) -> str:
    if len(items) < 2:
        return "single"
    authorities = {source_authority(item) for item in items}
    if source_authority(rep) == AUTHORITY_ORDER["user_utterance"] and any(
        source_authority(item) >= AUTHORITY_ORDER["agent_interpretation"] for item in items if item.get("id") != rep.get("id")
    ):
        return "prefer_user_anchor_block_weaker_duplicates"
    if len(authorities) == 1:
        return "dedupe_same_authority_candidates"
    return "cluster_only_mixed_authority"


def build_clusters(min_members: int = 2) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in active_items():
        key = cluster_key(item)
        if weak_cluster_key(key):
            continue
        grouped.setdefault(key, []).append(item)

    clusters: list[dict[str, Any]] = []
    duplicate_candidate_ids: set[str] = set()
    for key, rows in grouped.items():
        if len(rows) < min_members:
            continue
        rows.sort(key=lambda item: (source_authority(item), -int(item.get("confidence", 0)), str(item.get("id", ""))))
        rep = representative(rows)
        rep_id = str(rep.get("id", ""))
        duplicate_ids = [str(item.get("id", "")) for item in rows if item.get("id") != rep_id]
        duplicate_candidate_ids.update(duplicate_ids)
        source_types = sorted({str(item.get("source_type", "")) for item in rows if item.get("source_type")})
        evidence_types = sorted({str(value) for item in rows for value in item.get("evidence_types", [])})
        statuses = sorted({str(item.get("status", "")) for item in rows})
        confidences = [int(item.get("confidence", 0)) for item in rows]
        row_struct = structured(rep)
        action = governance_action(rows, rep)
        clusters.append(
            {
                "id": stable_id("candidate_cluster", key),
                "key": key,
                "scope": str(row_struct.get("scope") or "project"),
                "subject": str(row_struct.get("subject") or "unknown"),
                "predicate": str(row_struct.get("predicate") or "states"),
                "object_key": str(row_struct.get("object_key") or row_struct.get("object") or "unknown"),
                "modality": str(row_struct.get("modality") or "unknown"),
                "member_count": len(rows),
                "candidate_ids": [str(item.get("id", "")) for item in rows],
                "representative_id": rep_id,
                "duplicate_candidate_ids": duplicate_ids,
                "blocked_from_core_suggestions": duplicate_ids,
                "max_confidence": max(confidences) if confidences else 0,
                "min_confidence": min(confidences) if confidences else 0,
                "source_types": source_types,
                "evidence_types": evidence_types,
                "statuses": statuses,
                "claim_similarity_max": pairwise_max_similarity(rows),
                "governance_action": action,
                "merge_mode": "none_no_state_mutation",
                "updates_world_state": False,
            }
        )

    clusters.sort(key=lambda row: (-row["member_count"], -row["max_confidence"], row["key"]))
    active_count = len(active_items())
    return {
        "generated_at": now_iso(),
        "candidate_count": active_count,
        "cluster_count": len(clusters),
        "duplicate_candidate_count": len(duplicate_candidate_ids),
        "duplicate_ratio": round(len(duplicate_candidate_ids) / active_count, 4) if active_count else 0,
        "clusters": clusters,
        "note": "Candidate clusters are automatic governance denoise signals only; they do not merge candidates or update WORLD_STATE.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster duplicate or near-duplicate cognition candidates for automatic governance denoise.")
    parser.add_argument("--min-members", type=int, default=2, help="Minimum candidate count required for a cluster.")
    args = parser.parse_args()
    if args.min_members < 2:
        raise SystemExit("--min-members must be at least 2.")
    result = build_clusters(min_members=args.min_members)
    write_json(CANDIDATE_CLUSTERS, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
