#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from common import CONFLICTS, confidence_table_items, now_iso, read_jsonl, save_confidence_table, write_jsonl


def unresolved_conflicts() -> list[dict[str, Any]]:
    return [
        conflict
        for conflict in read_jsonl(CONFLICTS)
        if conflict.get("resolution") in {"unresolved", "deferred"} and int(conflict.get("severity", 0)) >= 60
    ]


def update_items_for_choice(items: list[dict[str, Any]], chosen_id: str, losing_id: str) -> list[dict[str, Any]]:
    for item in items:
        if item.get("id") == losing_id:
            item["status"] = "superseded"
            item["include_in_world_state"] = False
            item["superseded_by"] = chosen_id
        elif item.get("id") == chosen_id:
            item.setdefault("structured", {})
            item["structured"].setdefault("supersedes", [])
            if losing_id not in item["structured"]["supersedes"]:
                item["structured"]["supersedes"].append(losing_id)
            if int(item.get("confidence", 0)) >= 90 and item.get("status") != "rejected":
                item["include_in_world_state"] = True
    return items


def defer_items(items: list[dict[str, Any]], conflict: dict[str, Any]) -> list[dict[str, Any]]:
    blocked = {conflict.get("item_a"), conflict.get("item_b")}
    for item in items:
        if item.get("id") in blocked:
            item["include_in_world_state"] = False
    return items


def conditionally_block_items(items: list[dict[str, Any]], conflict: dict[str, Any], condition: str) -> list[dict[str, Any]]:
    blocked = {str(conflict.get("item_a", "")), str(conflict.get("item_b", ""))}
    for item in items:
        if str(item.get("id", "")) in blocked:
            item["include_in_world_state"] = False
            item["conditional_conflict_block"] = {
                "conflict_id": conflict.get("id", ""),
                "condition": condition,
                "blocks_world_state": True,
            }
    return items


def resolve(conflict_id: str, action: str, reason: str, condition: str = "") -> dict[str, Any]:
    conflicts = read_jsonl(CONFLICTS)
    matched: dict[str, Any] | None = None
    for conflict in conflicts:
        if conflict.get("id") == conflict_id:
            matched = conflict
            break
    if matched is None:
        raise SystemExit(f"Conflict not found: {conflict_id}")

    items = confidence_table_items()
    chosen = ""
    losing = ""
    resolution_type = "standard"
    blocks_world_state = False
    if action == "choose-a":
        chosen = str(matched.get("item_a", ""))
        losing = str(matched.get("item_b", ""))
        matched["resolution"] = "resolved"
        matched["chosen_side"] = chosen
        matched["reason"] = reason
        items = update_items_for_choice(items, chosen, losing)
    elif action == "choose-b":
        chosen = str(matched.get("item_b", ""))
        losing = str(matched.get("item_a", ""))
        matched["resolution"] = "resolved"
        matched["chosen_side"] = chosen
        matched["reason"] = reason
        items = update_items_for_choice(items, chosen, losing)
    elif action == "defer":
        matched["resolution"] = "deferred"
        matched["reason"] = reason
        matched["chosen_side"] = ""
        items = defer_items(items, matched)
        resolution_type = "deferred"
        blocks_world_state = True
    elif action == "coexist-by-condition":
        if not condition:
            raise SystemExit("--condition is required for coexist-by-condition.")
        matched["resolution"] = "resolved"
        matched["resolution_type"] = "coexist_by_condition"
        matched["condition"] = condition
        matched["blocks_world_state"] = True
        matched["chosen_side"] = ""
        matched["reason"] = reason
        items = conditionally_block_items(items, matched, condition)
        resolution_type = "coexist_by_condition"
        blocks_world_state = True
    else:
        matched["resolution"] = "resolved"
        matched["reason"] = reason
        matched.setdefault("chosen_side", "")

    matched["resolved_at"] = now_iso()
    item_by_id = {item.get("id"): item for item in items}
    blocked_ids = [str(matched.get("item_a", "")), str(matched.get("item_b", ""))]
    matched["audit_summary"] = {
        "action": action,
        "chosen": chosen,
        "loser": losing,
        "supersedes": item_by_id.get(chosen, {}).get("structured", {}).get("supersedes", []) if chosen else [],
        "condition": condition,
        "resolution_type": resolution_type,
        "blocks_world_state": blocks_world_state,
        "blocked_status": {
            item_id: {
                "status": item_by_id.get(item_id, {}).get("status"),
                "include_in_world_state": bool(item_by_id.get(item_id, {}).get("include_in_world_state")),
                "superseded_by": item_by_id.get(item_id, {}).get("superseded_by", ""),
                "conditional_conflict_block": item_by_id.get(item_id, {}).get("conditional_conflict_block", {}),
            }
            for item_id in blocked_ids
            if item_id
        },
    }
    write_jsonl(CONFLICTS, conflicts)
    save_confidence_table(items)
    return matched


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve or defer a recorded cognition conflict without silently overwriting evidence.")
    parser.add_argument("--list-unresolved", action="store_true", help="List unresolved or deferred high-severity conflicts.")
    parser.add_argument("--conflict-id", help="Conflict id to resolve.")
    parser.add_argument("--action", choices=["choose-a", "choose-b", "defer", "mark-resolved", "coexist-by-condition"], help="Conflict resolution action.")
    parser.add_argument("--reason", default="", help="Resolution reason.")
    parser.add_argument("--condition", default="", help="Condition required for coexist-by-condition, for example only_when_user_explicitly_requests.")
    args = parser.parse_args()

    if args.list_unresolved:
        print(json.dumps(unresolved_conflicts(), ensure_ascii=False, indent=2))
        return
    if not args.conflict_id or not args.action:
        raise SystemExit("--conflict-id and --action are required unless --list-unresolved is used.")
    if args.action != "mark-resolved" and not args.reason:
        raise SystemExit("--reason is required for choose-a, choose-b, defer, and coexist-by-condition.")
    if args.action == "coexist-by-condition" and not args.condition:
        raise SystemExit("--condition is required for coexist-by-condition.")

    reviewed = resolve(args.conflict_id, args.action, args.reason, args.condition)
    print(json.dumps(reviewed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
