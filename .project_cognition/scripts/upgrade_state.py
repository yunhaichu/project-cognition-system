#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

from common import (
    COGNITION_ROOT,
    CONFIDENCE_TABLE,
    INDEX_DIR,
    INDEX_MANIFEST,
    SEGMENT_INDEX,
    STATE_SCHEMA_VERSION,
    STATE_VERSION,
    USER_UTTERANCES,
    VECTOR_INDEX,
    VECTOR_MANIFEST,
    canonical_object,
    classify_user_utterance_intent,
    normalize_predicate,
    now_iso,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl,
)


DERIVED_INDEX_FILES = [SEGMENT_INDEX, INDEX_MANIFEST, VECTOR_INDEX, VECTOR_MANIFEST]
UPGRADE_RULES = [
    "backfill_user_utterance_intent",
    "backfill_candidate_utterance_intents",
    "block_non_direct_user_material_from_core",
    "normalize_legacy_read_world_state_predicate",
    "backfill_structured_object_key",
    "invalidate_derived_indexes_after_state_upgrade",
]


def safe_timestamp() -> str:
    return now_iso().replace(":", "").replace("-", "").replace("Z", "Z")


def source_refs(item: dict[str, Any]) -> list[str]:
    refs = [str(value) for value in item.get("evidence", []) if value]
    structured = item.get("structured", {})
    if isinstance(structured, dict):
        refs.extend(str(value) for value in structured.get("source_refs", []) if value)
    return list(dict.fromkeys(refs))


def existing_version() -> str:
    data = read_json(STATE_VERSION, {})
    return str(data.get("state_schema_version", "")) if isinstance(data, dict) else ""


def needs_read_predicate_fix(item: dict[str, Any]) -> bool:
    structured = item.get("structured", {})
    if not isinstance(structured, dict):
        return False
    if structured.get("predicate") != "render":
        return False
    text = "\n".join(
        [
            str(item.get("claim", "")),
            str(structured.get("object", "")),
            str(structured.get("confidence_reason", "")),
        ]
    )
    if not re.search(r"(读|读取|先读|read)", text, re.IGNORECASE):
        return False
    return normalize_predicate(None, text) == "read_source"


def backfill_user_utterance_intents(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    changed = 0
    updated: list[dict[str, Any]] = []
    for record in records:
        row = dict(record)
        expected = classify_user_utterance_intent(str(row.get("text", "")))
        if row.get("utterance_intent") != expected:
            row["utterance_intent"] = expected
            changed += 1
        updated.append(row)
    return updated, changed


def upgrade_confidence_items(
    items: list[dict[str, Any]], utterance_intents: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counters = {
        "candidate_utterance_intents_backfilled": 0,
        "non_direct_user_core_blocked": 0,
        "legacy_read_predicates_normalized": 0,
        "object_keys_backfilled": 0,
    }
    updated: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        structured = dict(row.get("structured", {})) if isinstance(row.get("structured"), dict) else {}
        refs = source_refs(row)
        intents = sorted({utterance_intents[ref] for ref in refs if ref in utterance_intents})
        if intents and row.get("utterance_intents") != intents:
            row["utterance_intents"] = intents
            counters["candidate_utterance_intents_backfilled"] += 1

        if intents and "direct_user_intent" not in intents and row.get("include_in_world_state"):
            row["include_in_world_state"] = False
            row["requires_governance_gate_for_world_state"] = True
            row["requires_review_for_world_state"] = True
            signals = set(row.get("score_signals", []))
            signals.add("non_direct_user_material_blocked")
            row["score_signals"] = sorted(signals)
            counters["non_direct_user_core_blocked"] += 1

        if needs_read_predicate_fix(row):
            structured["predicate"] = "read_source"
            counters["legacy_read_predicates_normalized"] += 1

        object_value = str(structured.get("object", ""))
        object_key = canonical_object(object_value)
        if structured and structured.get("object_key") != object_key:
            structured["object_key"] = object_key
            counters["object_keys_backfilled"] += 1

        if structured:
            row["structured"] = structured
        updated.append(row)
    return updated, counters


def backup_files(paths: list[Path], timestamp: str) -> dict[str, Any]:
    backup_root = COGNITION_ROOT / "backups" / "state_upgrade" / timestamp
    copied: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        relative = path.relative_to(COGNITION_ROOT)
        destination = backup_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied.append(str(relative))
    return {"backup_root": str(backup_root), "copied": copied}


def archive_index_files(timestamp: str) -> dict[str, Any]:
    existing = [path for path in DERIVED_INDEX_FILES if path.exists()]
    if not existing:
        return {"archive_root": "", "archived": []}
    archive_root = COGNITION_ROOT / "logs" / "migrations" / f"index_archive_{timestamp}"
    archived: list[str] = []
    for path in existing:
        relative = path.relative_to(COGNITION_ROOT)
        destination = archive_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        archived.append(str(relative))
    return {"archive_root": str(archive_root), "archived": archived}


def analyze_or_repair(repair: bool, force_index_refresh: bool) -> dict[str, Any]:
    timestamp = safe_timestamp()
    from_version = existing_version()
    utterances = read_jsonl(USER_UTTERANCES)
    upgraded_utterances, utterance_changes = backfill_user_utterance_intents(utterances)
    utterance_intents = {str(row.get("id", "")): str(row.get("utterance_intent", "")) for row in upgraded_utterances if row.get("id")}

    table = read_json(CONFIDENCE_TABLE, {"items": []})
    items = table.get("items", []) if isinstance(table, dict) else []
    upgraded_items, item_counters = upgrade_confidence_items([row for row in items if isinstance(row, dict)], utterance_intents)

    active_index_files = [path for path in DERIVED_INDEX_FILES if path.exists()]
    needs_index_refresh = bool(active_index_files) and (
        force_index_refresh
        or utterance_changes > 0
        or any(value > 0 for value in item_counters.values())
        or from_version != STATE_SCHEMA_VERSION
    )
    changed = utterance_changes > 0 or any(value > 0 for value in item_counters.values()) or from_version != STATE_SCHEMA_VERSION
    changed = changed or needs_index_refresh

    backup: dict[str, Any] = {"backup_root": "", "copied": []}
    index_archive: dict[str, Any] = {"archive_root": "", "archived": []}
    migration_log = ""
    if repair and changed:
        backup_targets = [USER_UTTERANCES, CONFIDENCE_TABLE, STATE_VERSION]
        backup = backup_files(backup_targets, timestamp)
        if utterance_changes:
            write_jsonl(USER_UTTERANCES, upgraded_utterances)
        if any(value > 0 for value in item_counters.values()):
            write_json(CONFIDENCE_TABLE, {"items": upgraded_items})
        if needs_index_refresh:
            index_archive = archive_index_files(timestamp)
            INDEX_DIR.mkdir(parents=True, exist_ok=True)
        version_payload = {
            "state_schema_version": STATE_SCHEMA_VERSION,
            "upgraded_at": now_iso(),
            "from_version": from_version,
            "upgrade_rules": UPGRADE_RULES,
            "local_only": True,
            "llm_used": False,
        }
        write_json(STATE_VERSION, version_payload)
        migration_summary = {
            "target_root": str(COGNITION_ROOT.parent),
            "timestamp": now_iso(),
            "from_version": from_version,
            "to_version": STATE_SCHEMA_VERSION,
            "changes": {
                "user_utterance_intents_backfilled": utterance_changes,
                **item_counters,
                "index_files_invalidated": len(index_archive.get("archived", [])),
            },
            "backup": backup,
            "index_archive": index_archive,
            "local_only": True,
        }
        migration_path = COGNITION_ROOT / "logs" / "migrations" / f"state_upgrade_{timestamp}.json"
        write_json(migration_path, migration_summary)
        migration_log = str(migration_path)
    elif repair and from_version != STATE_SCHEMA_VERSION:
        write_json(
            STATE_VERSION,
            {
                "state_schema_version": STATE_SCHEMA_VERSION,
                "upgraded_at": now_iso(),
                "from_version": from_version,
                "upgrade_rules": UPGRADE_RULES,
                "local_only": True,
                "llm_used": False,
            },
        )

    return {
        "target_root": str(COGNITION_ROOT.parent),
        "from_version": from_version,
        "to_version": STATE_SCHEMA_VERSION,
        "repair": repair,
        "needs_upgrade": changed,
        "changes": {
            "user_utterance_intents_backfilled": utterance_changes,
            **item_counters,
            "active_index_files": len(active_index_files),
            "index_refresh_needed": needs_index_refresh,
        },
        "backup": backup,
        "index_archive": index_archive,
        "migration_log": migration_log,
        "local_only": True,
        "llm_used": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Versioned Project Cognition state upgrade. Preserves raw evidence, repairs metadata, and invalidates derived indexes."
    )
    parser.add_argument("--repair", action="store_true", help="Apply the upgrade. Without this flag, only report pending changes.")
    parser.add_argument(
        "--force-index-refresh",
        action="store_true",
        help="Archive active derived indexes even when no metadata upgrade is pending.",
    )
    args = parser.parse_args()
    result = analyze_or_repair(repair=args.repair, force_index_refresh=args.force_index_refresh)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
