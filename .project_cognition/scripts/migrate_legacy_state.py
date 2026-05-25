#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import now_iso, read_json, read_jsonl, write_json, write_jsonl


DERIVED_FILES = [
    "WORLD_STATE.md",
    "WORLD_STATE_COMPACT.md",
    "distilled/confidence_table.json",
    "distilled/conflict_clusters.json",
    "distilled/scoring_weights.json",
    "distilled/scoring_feedback.jsonl",
    "raw/conflicts.jsonl",
    "index/segments.jsonl",
    "index/manifest.json",
]

REBUILD_SCRIPTS = [
    "update_scoring_weights.py",
    "extract_candidates.py",
    "score_candidates.py",
    "detect_conflicts.py",
    "cluster_conflicts.py",
    "build_world_state.py",
    "build_user_profile.py",
    "index_segments.py",
    "drift_report.py",
]

EVIDENCE_PREFIXES = ("utt_", "interp_", "tool_ev_")
SAFE_SOURCE_TYPES = {"bootstrap_rule", "manual_initialization", "user_utterance", "tool_evidence", "proposed_update"}


def cognition_root(target_root: Path) -> Path:
    return target_root / ".project_cognition"


def safe_timestamp() -> str:
    return now_iso().replace(":", "").replace("-", "").replace("Z", "Z")


def target_path(target_root: Path, relative: str) -> Path:
    return cognition_root(target_root) / relative


def evidence_ids(target_root: Path) -> set[str]:
    root = cognition_root(target_root)
    ids: set[str] = set()
    for relative in [
        "raw/user_utterances.jsonl",
        "raw/agent_interpretations.jsonl",
        "raw/tool_evidence.jsonl",
    ]:
        for record in read_jsonl(root / relative):
            if record.get("id"):
                ids.add(str(record["id"]))
    return ids


def load_items(target_root: Path) -> list[dict[str, Any]]:
    table = read_json(target_path(target_root, "distilled/confidence_table.json"), {"items": []})
    rows = table.get("items", []) if isinstance(table, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def source_refs(item: dict[str, Any]) -> list[str]:
    refs = [str(value) for value in item.get("evidence", []) if value]
    structured = item.get("structured", {})
    if isinstance(structured, dict):
        refs.extend(str(value) for value in structured.get("source_refs", []) if value)
    return list(dict.fromkeys(refs))


def missing_evidence_refs(item: dict[str, Any], valid_evidence_ids: set[str]) -> list[str]:
    missing: list[str] = []
    for ref in source_refs(item):
        if ref in valid_evidence_ids:
            continue
        if ref.startswith(EVIDENCE_PREFIXES):
            missing.append(ref)
    return missing


def item_is_preservable(item: dict[str, Any], valid_evidence_ids: set[str], preserve_reviewed: bool) -> bool:
    source_type = str(item.get("source_type", ""))
    status = str(item.get("status", "candidate"))
    if source_type in {"bootstrap_rule", "manual_initialization"} and status in {"accepted", "candidate"}:
        return True
    if not preserve_reviewed:
        return False
    if status != "accepted":
        return False
    if source_type not in SAFE_SOURCE_TYPES:
        return False
    if source_type not in {"bootstrap_rule", "manual_initialization"} and not source_refs(item):
        return False
    return not missing_evidence_refs(item, valid_evidence_ids)


def analyze(target_root: Path, preserve_reviewed: bool = True) -> dict[str, Any]:
    root = cognition_root(target_root)
    valid_ids = evidence_ids(target_root)
    items = load_items(target_root)
    orphaned = []
    preservable = []
    quarantined = []
    unsafe_core = []
    for item in items:
        missing = missing_evidence_refs(item, valid_ids)
        row = {
            "id": item.get("id", ""),
            "source_type": item.get("source_type", ""),
            "status": item.get("status", ""),
            "include_in_world_state": bool(item.get("include_in_world_state")),
            "missing_evidence": missing,
        }
        if missing:
            orphaned.append(row)
        if item_is_preservable(item, valid_ids, preserve_reviewed):
            preservable.append(row)
        else:
            quarantined.append(row)
            if item.get("include_in_world_state"):
                unsafe_core.append(row)

    derived = {}
    for relative in DERIVED_FILES:
        path = target_path(target_root, relative)
        derived[relative] = {
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
        }

    missing_schemas = []
    schema_dir = root / "schemas"
    for name in [
        "agent_interpretation.schema.json",
        "cognition_candidate.schema.json",
        "confidence_table.schema.json",
        "conflict.schema.json",
        "decision.schema.json",
        "proposed_update.schema.json",
        "tool_evidence.schema.json",
        "user_utterance.schema.json",
        "world_state.schema.json",
    ]:
        if not (schema_dir / name).exists():
            missing_schemas.append(name)

    return {
        "target_root": str(target_root),
        "cognition_root": str(root),
        "raw_evidence_ids": len(valid_ids),
        "confidence_items": len(items),
        "preservable_items": len(preservable),
        "quarantine_items": len(quarantined),
        "orphaned_items": orphaned,
        "unsafe_core_items": unsafe_core,
        "missing_schemas": missing_schemas,
        "derived_files": derived,
        "needs_repair": bool(orphaned or missing_schemas or unsafe_core),
        "repair_rule": "Preserve raw evidence/logs; backup and rebuild generated cognition state with current scripts.",
    }


def copy_if_exists(source: Path, backup_root: Path, relative: str) -> bool:
    if not source.exists():
        return False
    destination = backup_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return True


def backup_derived(target_root: Path, timestamp: str) -> dict[str, Any]:
    backup_root = cognition_root(target_root) / "backups" / "legacy_migration" / timestamp
    copied: list[str] = []
    for relative in DERIVED_FILES:
        if copy_if_exists(target_path(target_root, relative), backup_root, relative):
            copied.append(relative)
    return {"backup_root": str(backup_root), "copied": copied}


def reset_derived_state(target_root: Path, preserved_items: list[dict[str, Any]], quarantined_items: list[dict[str, Any]]) -> None:
    root = cognition_root(target_root)
    write_json(root / "distilled" / "confidence_table.json", {"items": preserved_items})
    write_json(root / "distilled" / "legacy_quarantined_candidates.json", {"items": quarantined_items, "quarantined_at": now_iso()})
    write_jsonl(root / "raw" / "conflicts.jsonl", [])
    for relative in [
        "distilled/conflict_clusters.json",
        "distilled/scoring_weights.json",
        "distilled/scoring_feedback.jsonl",
        "index/segments.jsonl",
        "index/manifest.json",
    ]:
        path = target_path(target_root, relative)
        if path.exists():
            path.unlink()


def run_target_script(target_root: Path, script_name: str, args: list[str] | None = None) -> dict[str, Any]:
    command = [sys.executable, str(cognition_root(target_root) / "scripts" / script_name), *(args or [])]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(command, cwd=target_root, env=env, text=True, capture_output=True, check=False)
    stdout = completed.stdout.strip()
    parsed: Any = stdout
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            pass
    result = {
        "script": script_name,
        "argv": args or [],
        "returncode": completed.returncode,
        "stdout": parsed,
        "stderr": completed.stderr.strip(),
    }
    if completed.returncode != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def repair(target_root: Path, preserve_reviewed: bool = True, rebuild: bool = True) -> dict[str, Any]:
    before = analyze(target_root, preserve_reviewed=preserve_reviewed)
    valid_ids = evidence_ids(target_root)
    items = load_items(target_root)
    preserved = [item for item in items if item_is_preservable(item, valid_ids, preserve_reviewed)]
    quarantined = [item for item in items if item not in preserved]
    timestamp = safe_timestamp()
    backup = backup_derived(target_root, timestamp)
    reset_derived_state(target_root, preserved, quarantined)
    steps = []
    if rebuild:
        for script_name in REBUILD_SCRIPTS:
            steps.append(run_target_script(target_root, script_name, []))
    after = analyze(target_root, preserve_reviewed=preserve_reviewed)
    summary = {
        "target_root": str(target_root),
        "repaired_at": now_iso(),
        "backup": backup,
        "preserved_count": len(preserved),
        "quarantined_count": len(quarantined),
        "before": before,
        "after": after,
        "rebuild_steps": steps,
    }
    migration_log = cognition_root(target_root) / "logs" / "migrations" / f"legacy_migration_{timestamp}.json"
    write_json(migration_log, summary)
    summary["migration_log"] = str(migration_log)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Report or repair legacy Project Cognition derived state.")
    parser.add_argument("--target-root", default=".", help="Project root containing .project_cognition. Default: current directory.")
    parser.add_argument("--repair", action="store_true", help="Backup generated state, quarantine unsafe derived items, and rebuild with current scripts.")
    parser.add_argument("--no-rebuild", action="store_true", help="With --repair, only reset/quarantine derived state; do not run rebuild scripts.")
    parser.add_argument(
        "--drop-reviewed",
        action="store_true",
        help="Do not preserve accepted user/tool/manual cognition items even when their evidence still exists.",
    )
    args = parser.parse_args()
    target_root = Path(args.target_root).expanduser().resolve()
    if not cognition_root(target_root).is_dir():
        raise SystemExit(f"No .project_cognition directory under {target_root}")

    preserve_reviewed = not args.drop_reviewed
    if args.repair:
        result = repair(target_root, preserve_reviewed=preserve_reviewed, rebuild=not args.no_rebuild)
    else:
        result = analyze(target_root, preserve_reviewed=preserve_reviewed)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
