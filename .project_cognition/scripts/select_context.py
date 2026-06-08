#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from common import COGNITION_ROOT, CONFIDENCE_TABLE, GOVERNANCE_GATE, WORLD_STATE, WORLD_STATE_COMPACT, now_iso, read_json, write_json


CONTEXT_LOG_DIR = COGNITION_ROOT / "logs" / "context_injections"
DEFAULT_MAX_CHARS = 1600


def sha256_text(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def sha256_json(value: Any, length: int = 16) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True), length)


def safe_session_id(session_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id.strip())
    return cleaned or "context_session"


def terms(text: str) -> set[str]:
    lowered = text.lower()
    values = {token for token in re.findall(r"[a-z0-9_.-]{3,}", lowered)}
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,12}", text):
        values.add(chunk)
    return values


def structured(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("structured", {})
    return value if isinstance(value, dict) else {}


def item_text(item: dict[str, Any]) -> str:
    row = structured(item)
    return " ".join(
        [
            str(item.get("claim", "")),
            str(item.get("category", "")),
            str(row.get("subject", "")),
            str(row.get("predicate", "")),
            str(row.get("object", "")),
            str(row.get("object_key", "")),
            str(row.get("scope", "")),
            str(row.get("modality", "")),
        ]
    )


def item_scope(item: dict[str, Any]) -> str:
    return str(structured(item).get("scope") or "project")


def load_items() -> list[dict[str, Any]]:
    return list(read_json(CONFIDENCE_TABLE, {"items": []}).get("items", []))


def admitted_ids(items: list[dict[str, Any]], gate: dict[str, Any]) -> set[str]:
    allowed = gate.get("allowed_item_ids", [])
    if isinstance(allowed, list) and allowed:
        return {str(value) for value in allowed}
    return {str(item.get("id", "")) for item in items if item.get("include_in_world_state")}


def exclusion_reason(item: dict[str, Any], allowed_ids: set[str], task_terms: set[str]) -> str:
    item_id = str(item.get("id", ""))
    if item.get("status") in {"rejected", "superseded"}:
        return "stale"
    if item.get("conditional_conflict_block", {}).get("blocks_world_state"):
        return "conditional_conflict_block"
    if item_id not in allowed_ids:
        return "not_admitted"
    if item_scope(item) not in {"project", "user", "global", ""}:
        return "not_project_scope"
    if task_terms and not (task_terms & terms(item_text(item))):
        return "not_task_relevant"
    return ""


def relevance_score(item: dict[str, Any], task_terms: set[str]) -> int:
    confidence = int(item.get("confidence", 0))
    row = structured(item)
    overlap = len(task_terms & terms(item_text(item))) if task_terms else 1
    predicate_bonus = 8 if row.get("predicate") in {"requires", "must", "update_world_state", "enter_core_memory", "inject_context"} else 0
    category_bonus = 6 if item.get("category") in {"constraint", "project_principle", "user_principle"} else 0
    return overlap * 100 + confidence + predicate_bonus + category_bonus


def render_line(item: dict[str, Any]) -> str:
    claim = re.sub(r"\s+", " ", str(item.get("claim", "")).strip())
    if len(claim) > 220:
        claim = claim[:217] + "..."
    row = structured(item)
    predicate = row.get("predicate") or "states"
    modality = row.get("modality") or "unknown"
    return f"- [{item.get('id')}] ({item.get('category')}/{predicate}/{modality}) {claim}"


def build_context(task: str, max_chars: int) -> tuple[str, dict[str, Any]]:
    items = load_items()
    gate = read_json(GOVERNANCE_GATE, {})
    allowed = admitted_ids(items, gate)
    task_terms = terms(task)
    excluded_reason_counts: dict[str, int] = {}
    eligible: list[tuple[int, dict[str, Any]]] = []
    excluded_ids: dict[str, str] = {}

    for item in items:
        item_id = str(item.get("id", ""))
        reason = exclusion_reason(item, allowed, task_terms)
        if reason:
            excluded_reason_counts[reason] = excluded_reason_counts.get(reason, 0) + 1
            excluded_ids[item_id] = reason
            continue
        eligible.append((relevance_score(item, task_terms), item))

    eligible.sort(key=lambda row: (-row[0], -int(row[1].get("confidence", 0)), str(row[1].get("id", ""))))
    lines = ["# SELECTED_CONTEXT", "", f"Task: {task.strip() or '(unspecified)'}", ""]
    included: list[str] = []
    for _, item in eligible:
        line = render_line(item)
        proposed = "\n".join([*lines, line, ""])
        if len(proposed) > max_chars:
            excluded_reason_counts["over_budget"] = excluded_reason_counts.get("over_budget", 0) + 1
            excluded_ids[str(item.get("id", ""))] = "over_budget"
            continue
        lines.append(line)
        included.append(str(item.get("id", "")))
    if not included:
        lines.append("- No admitted task-relevant cognition selected.")
    context = "\n".join(lines).strip() + "\n"
    manifest = {
        "id": f"ctx_{sha256_json([task, included, now_iso()])}",
        "timestamp": now_iso(),
        "task": task,
        "max_chars": max_chars,
        "included_cognition_ids": included,
        "excluded_reason_counts": dict(sorted(excluded_reason_counts.items())),
        "excluded_ids": excluded_ids,
        "prompt_fingerprint": sha256_text(context),
        "ruleset_hash": sha256_json({"gate_policy_hash": gate.get("policy_hash", ""), "allowed_item_ids": sorted(allowed)}),
        "gate_policy_hash": str(gate.get("policy_hash", "")),
        "source_manifest": {
            "confidence_table": str(CONFIDENCE_TABLE.relative_to(COGNITION_ROOT)),
            "governance_gate": str(GOVERNANCE_GATE.relative_to(COGNITION_ROOT)),
            "world_state": str(WORLD_STATE.relative_to(COGNITION_ROOT)),
            "world_state_compact": str(WORLD_STATE_COMPACT.relative_to(COGNITION_ROOT)),
            "candidate_count": len(items),
            "admitted_count": len(allowed),
            "eligible_count": len(eligible),
        },
        "output_characters": len(context),
        "mutates_state": False,
    }
    return context, manifest


def select_context(session_id: str, task: str, max_chars: int) -> dict[str, Any]:
    context, manifest = build_context(task, max_chars)
    manifest["session_id"] = session_id
    path = CONTEXT_LOG_DIR / f"{safe_session_id(session_id)}.json"
    write_json(path, manifest)
    return {"context": context, "manifest": manifest, "manifest_path": str(path.relative_to(COGNITION_ROOT))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Select task-relevant admitted context and write a read-only injection manifest.")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task", default="")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    args = parser.parse_args()
    result = select_context(args.session_id, args.task, args.max_chars)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
