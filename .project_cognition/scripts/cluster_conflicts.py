#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from common import CONFLICT_CLUSTERS, CONFLICTS, confidence_table_items, now_iso, read_jsonl, stable_id, write_json


NEGATIVE_MODALITIES = {"must_not", "is_not"}
POSITIVE_MODALITIES = {"must", "should", "may", "is"}


def polarity(item: dict[str, Any]) -> str:
    modality = str(item.get("structured", {}).get("modality", ""))
    if modality in NEGATIVE_MODALITIES:
        return "negative"
    if modality in POSITIVE_MODALITIES:
        return "positive"
    return "neutral"


def topic_from_description(description: str) -> str:
    match = re.search(r"topic '([^']+)'", description)
    if match:
        return match.group(1)
    return "unknown"


def cluster_key(conflict: dict[str, Any], item_by_id: dict[str, dict[str, Any]]) -> str:
    items = [item_by_id.get(str(conflict.get("item_a", "")), {}), item_by_id.get(str(conflict.get("item_b", "")), {})]
    structured = [item.get("structured", {}) for item in items]
    object_keys = sorted({str(row.get("object_key") or "unknown") for row in structured})
    predicates = sorted({str(row.get("predicate") or "states") for row in structured})
    scopes = sorted({str(row.get("scope") or "project") for row in structured})
    polarities = sorted({polarity(item) for item in items})
    topic = topic_from_description(str(conflict.get("description", "")))
    return "|".join(
        [
            ",".join(object_keys),
            ",".join(predicates),
            ",".join(scopes),
            ",".join(polarities),
            topic,
            str(conflict.get("type", "old_vs_new")),
        ]
    )


def priority(max_severity: int, count: int) -> str:
    if max_severity >= 90 or count >= 20:
        return "critical"
    if max_severity >= 75 or count >= 5:
        return "high"
    return "medium"


def build_clusters(min_severity: int = 0, include_deferred: bool = True) -> dict[str, Any]:
    item_by_id = {item["id"]: item for item in confidence_table_items()}
    allowed_resolutions = {"unresolved", "deferred"} if include_deferred else {"unresolved"}
    conflicts = [
        conflict
        for conflict in read_jsonl(CONFLICTS)
        if conflict.get("resolution") in allowed_resolutions and int(conflict.get("severity", 0)) >= min_severity
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for conflict in conflicts:
        grouped.setdefault(cluster_key(conflict, item_by_id), []).append(conflict)

    clusters: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        rows.sort(key=lambda row: (-int(row.get("severity", 0)), str(row.get("id", ""))))
        cognition_ids = sorted({str(row.get("item_a", "")) for row in rows} | {str(row.get("item_b", "")) for row in rows})
        max_severity = max(int(row.get("severity", 0)) for row in rows)
        clusters.append(
            {
                "id": stable_id("cluster", key),
                "key": key,
                "representative_conflict_id": rows[0].get("id", ""),
                "member_count": len(rows),
                "max_severity": max_severity,
                "review_priority": priority(max_severity, len(rows)),
                "conflict_ids": [row.get("id", "") for row in rows],
                "cognition_ids": cognition_ids,
                "topic": topic_from_description(str(rows[0].get("description", ""))),
                "resolution_states": sorted({str(row.get("resolution", "")) for row in rows}),
            }
        )
    clusters.sort(key=lambda row: ({"critical": 0, "high": 1, "medium": 2}.get(row["review_priority"], 3), -row["max_severity"], -row["member_count"]))
    return {
        "generated_at": now_iso(),
        "total_conflicts": len(conflicts),
        "cluster_count": len(clusters),
        "clusters": clusters,
        "note": "Conflict clusters are review aids only; they do not resolve conflicts.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster unresolved cognition conflicts for review triage.")
    parser.add_argument("--min-severity", type=int, default=0, help="Only cluster conflicts at or above this severity.")
    parser.add_argument("--unresolved-only", action="store_true", help="Exclude deferred conflicts from the review queue.")
    args = parser.parse_args()
    result = build_clusters(min_severity=args.min_severity, include_deferred=not args.unresolved_only)
    write_json(CONFLICT_CLUSTERS, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
