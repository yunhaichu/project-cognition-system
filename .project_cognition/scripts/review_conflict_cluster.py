#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from cluster_conflicts import build_clusters
from common import CONFLICT_CLUSTERS, CONFLICTS, confidence_table_items, read_json, read_jsonl, write_json
from resolve_conflict import resolve


def refresh_clusters() -> dict[str, Any]:
    result = build_clusters()
    write_json(CONFLICT_CLUSTERS, result)
    return result


def load_clusters(auto_build: bool = True) -> dict[str, Any]:
    if not CONFLICT_CLUSTERS.exists():
        if not auto_build:
            raise SystemExit(f"Conflict cluster file not found: {CONFLICT_CLUSTERS}. Run cluster_conflicts.py first.")
        return refresh_clusters()
    return read_json(CONFLICT_CLUSTERS, {"clusters": []})


def cluster_by_id(cluster_id: str, auto_build: bool = True) -> dict[str, Any]:
    data = load_clusters(auto_build=auto_build)
    for cluster in data.get("clusters", []):
        if cluster.get("id") == cluster_id:
            return cluster
    raise SystemExit(f"Conflict cluster not found: {cluster_id}")


def active_conflicts_by_id() -> dict[str, dict[str, Any]]:
    return {str(conflict.get("id", "")): conflict for conflict in read_jsonl(CONFLICTS)}


def items_by_id() -> dict[str, dict[str, Any]]:
    return {str(item.get("id", "")): item for item in confidence_table_items()}


def summarize_item(item: dict[str, Any]) -> dict[str, Any]:
    structured = item.get("structured", {}) if isinstance(item.get("structured"), dict) else {}
    return {
        "id": item.get("id", ""),
        "status": item.get("status", ""),
        "source_type": item.get("source_type", ""),
        "confidence": item.get("confidence", 0),
        "include_in_world_state": bool(item.get("include_in_world_state")),
        "claim": item.get("claim", ""),
        "subject": structured.get("subject", ""),
        "predicate": structured.get("predicate", ""),
        "object_key": structured.get("object_key", ""),
        "scope": structured.get("scope", ""),
        "modality": structured.get("modality", ""),
    }


def inspect_cluster(cluster_id: str) -> dict[str, Any]:
    cluster = cluster_by_id(cluster_id)
    conflicts = active_conflicts_by_id()
    items = items_by_id()
    rows = [conflicts[conflict_id] for conflict_id in cluster.get("conflict_ids", []) if conflict_id in conflicts]
    cognition_ids = sorted({str(row.get("item_a", "")) for row in rows} | {str(row.get("item_b", "")) for row in rows})
    return {
        "cluster": cluster,
        "conflicts": rows,
        "items": [summarize_item(items[item_id]) for item_id in cognition_ids if item_id in items],
        "suggested_count": sum(1 for row in rows if row.get("chosen_side")),
        "missing_suggestion_count": sum(1 for row in rows if not row.get("chosen_side")),
    }


def action_for_conflict(conflict: dict[str, Any], action: str, chosen_item_id: str = "") -> tuple[str, str]:
    item_a = str(conflict.get("item_a", ""))
    item_b = str(conflict.get("item_b", ""))
    if action == "defer":
        return "defer", ""
    if action == "mark-resolved":
        return "mark-resolved", ""
    if action == "choose-item":
        if chosen_item_id == item_a:
            return "choose-a", ""
        if chosen_item_id == item_b:
            return "choose-b", ""
        return "", "chosen_item_not_in_conflict"
    if action == "apply-suggested":
        chosen = str(conflict.get("chosen_side", ""))
        if chosen == item_a:
            return "choose-a", ""
        if chosen == item_b:
            return "choose-b", ""
        return "", "missing_chosen_side"
    return "", "unknown_action"


def review_cluster(
    cluster_id: str,
    *,
    action: str,
    reason: str,
    chosen_item_id: str = "",
    dry_run: bool = False,
    refresh: bool = True,
) -> dict[str, Any]:
    cluster = cluster_by_id(cluster_id)
    conflicts = active_conflicts_by_id()
    reviewed: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for conflict_id in cluster.get("conflict_ids", []):
        conflict = conflicts.get(conflict_id)
        if not conflict:
            skipped.append({"conflict_id": str(conflict_id), "reason": "missing_conflict"})
            continue
        if conflict.get("resolution") not in {"unresolved", "deferred"}:
            skipped.append({"conflict_id": str(conflict_id), "reason": "already_resolved"})
            continue
        conflict_action, skip_reason = action_for_conflict(conflict, action, chosen_item_id)
        if not conflict_action:
            skipped.append({"conflict_id": str(conflict_id), "reason": skip_reason})
            continue
        if dry_run:
            reviewed.append({"conflict_id": str(conflict_id), "action": conflict_action, "dry_run": True})
            continue
        reviewed_conflict = resolve(str(conflict_id), conflict_action, reason)
        reviewed.append(
            {
                "conflict_id": str(conflict_id),
                "action": conflict_action,
                "chosen": reviewed_conflict.get("audit_summary", {}).get("chosen", ""),
                "loser": reviewed_conflict.get("audit_summary", {}).get("loser", ""),
                "supersedes": reviewed_conflict.get("audit_summary", {}).get("supersedes", []),
            }
        )

    refreshed = refresh_clusters() if refresh and not dry_run else None
    return {
        "cluster_id": cluster_id,
        "action": action,
        "dry_run": dry_run,
        "reviewed_count": len(reviewed),
        "skipped_count": len(skipped),
        "reviewed": reviewed,
        "skipped": skipped,
        "remaining_cluster_count": refreshed.get("cluster_count") if refreshed else None,
        "note": "Cluster review applies explicit review actions only; clustering itself never chooses truth.",
    }


def list_clusters() -> dict[str, Any]:
    data = load_clusters(auto_build=True)
    return {
        "generated_at": data.get("generated_at", ""),
        "cluster_count": data.get("cluster_count", 0),
        "clusters": data.get("clusters", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Review clustered cognition conflicts without letting clustering decide truth.")
    parser.add_argument("--list", action="store_true", help="List current conflict clusters. This is the default with no cluster id.")
    parser.add_argument("--cluster-id", help="Cluster id to inspect or review.")
    parser.add_argument("--inspect", action="store_true", help="Print cluster conflicts and item summaries.")
    parser.add_argument(
        "--action",
        choices=["apply-suggested", "choose-item", "defer", "mark-resolved"],
        help="Review action to apply to conflicts in the cluster.",
    )
    parser.add_argument("--chosen-item-id", default="", help="Cognition item id required for --action choose-item.")
    parser.add_argument("--reason", default="", help="Human review reason required for mutating actions except dry runs.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be reviewed without modifying state.")
    parser.add_argument("--no-refresh", action="store_true", help="Do not rebuild conflict_clusters.json after review.")
    args = parser.parse_args()

    if args.list or not args.cluster_id:
        print(json.dumps(list_clusters(), ensure_ascii=False, indent=2))
        return
    if args.inspect and not args.action:
        print(json.dumps(inspect_cluster(args.cluster_id), ensure_ascii=False, indent=2))
        return
    if not args.action:
        raise SystemExit("--action is required unless --list or --inspect is used.")
    if args.action == "choose-item" and not args.chosen_item_id:
        raise SystemExit("--chosen-item-id is required for --action choose-item.")
    if not args.dry_run and args.action in {"apply-suggested", "choose-item", "defer"} and not args.reason:
        raise SystemExit("--reason is required for mutating review actions.")

    result = review_cluster(
        args.cluster_id,
        action=args.action,
        reason=args.reason,
        chosen_item_id=args.chosen_item_id,
        dry_run=args.dry_run,
        refresh=not args.no_refresh,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
