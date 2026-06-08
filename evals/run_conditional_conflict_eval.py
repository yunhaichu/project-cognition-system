#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records), encoding="utf-8")


def make_project_copy(temp_dir: str) -> Path:
    project_root = Path(temp_dir) / "project"
    shutil.copytree(REPO_ROOT / ".project_cognition", project_root / ".project_cognition", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    cognition_root = project_root / ".project_cognition"
    for path in [
        cognition_root / "raw" / "conflicts.jsonl",
        cognition_root / "raw" / "feedback_events.jsonl",
        cognition_root / "raw" / "rule_change_log.jsonl",
        cognition_root / "proposals" / "rule_change_proposals.jsonl",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return project_root


def run_script(project_root: Path, script_name: str, args: list[str] | None = None) -> Any:
    command = [sys.executable, str(project_root / ".project_cognition" / "scripts" / script_name), *(args or [])]
    completed = subprocess.run(command, cwd=project_root, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{script_name} failed with code {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    stdout = completed.stdout.strip()
    if not stdout:
        return None
    return json.loads(stdout)


def item(
    item_id: str,
    *,
    claim: str,
    modality: str,
    object_value: str = "WORLD_STATE.md automatic update",
) -> dict[str, Any]:
    return {
        "id": item_id,
        "claim": claim,
        "category": "constraint",
        "confidence": 96,
        "evidence": [],
        "conflicts": [],
        "last_verified": "2026-06-08T00:00:00Z",
        "stability": "stable",
        "include_in_world_state": True,
        "source_type": "manual_initialization",
        "status": "accepted",
        "topics": [],
        "structured": {
            "subject": "world_state",
            "predicate": "update_world_state",
            "object": object_value,
            "object_key": "world_state",
            "scope": "project",
            "modality": modality,
            "valid_from": "2026-06-08T00:00:00Z",
            "valid_until": None,
            "source_refs": [],
            "confidence_reason": "Conditional conflict eval fixture.",
            "supersedes": [],
        },
    }


def check_conditional_conflict(project_root: Path) -> dict[str, bool]:
    cognition_root = project_root / ".project_cognition"
    table_path = cognition_root / "distilled" / "confidence_table.json"
    write_json(
        table_path,
        {
            "items": [
                item("conditional_default_block", claim="WORLD_STATE must not be updated automatically.", modality="must_not"),
                item("conditional_explicit_allow", claim="WORLD_STATE may be updated when the user explicitly requests it.", modality="must"),
            ]
        },
    )
    write_jsonl(cognition_root / "raw" / "conflicts.jsonl", [])

    detect = run_script(project_root, "detect_conflicts.py")
    conflicts = read_jsonl(cognition_root / "raw" / "conflicts.jsonl")
    conflict = conflicts[0]
    resolved = run_script(
        project_root,
        "resolve_conflict.py",
        [
            "--conflict-id",
            conflict["id"],
            "--action",
            "coexist-by-condition",
            "--condition",
            "only_when_user_explicitly_requests",
            "--reason",
            "Default prohibition and explicit user override coexist by condition.",
        ],
    )
    after_resolve_items = {row["id"]: row for row in read_json(table_path).get("items", [])}
    score = run_script(project_root, "score_candidates.py")
    gate = run_script(project_root, "auto_governance_gate.py")
    world = run_script(project_root, "build_world_state.py")
    drift = run_script(project_root, "drift_report.py")
    validation = run_script(project_root, "validate_state.py")
    final_items = {row["id"]: row for row in read_json(table_path).get("items", [])}
    final_conflict = read_jsonl(cognition_root / "raw" / "conflicts.jsonl")[0]
    compact = (cognition_root / "WORLD_STATE_COMPACT.md").read_text(encoding="utf-8")
    decisions = {row.get("id"): row for row in gate.get("decisions", [])}
    blocked_ids = {"conditional_default_block", "conditional_explicit_allow"}
    return {
        "conflict_detected": detect.get("new_conflicts") == 1 and final_conflict.get("id") == conflict.get("id"),
        "conditional_resolution_recorded": resolved.get("resolution") == "resolved"
        and resolved.get("resolution_type") == "coexist_by_condition"
        and resolved.get("condition") == "only_when_user_explicitly_requests"
        and resolved.get("chosen_side") == "",
        "condition_preserves_both_items": {row.get("status") for row in after_resolve_items.values()} == {"accepted"},
        "condition_blocks_world_state_after_resolve": all(
            after_resolve_items[item_id].get("include_in_world_state") is False
            and after_resolve_items[item_id].get("conditional_conflict_block", {}).get("blocks_world_state") is True
            for item_id in blocked_ids
        ),
        "score_preserves_conditional_block": score.get("include_in_world_state") == 0
        and all(final_items[item_id].get("include_in_world_state") is False for item_id in blocked_ids),
        "gate_blocks_conditionally_blocked_items": not (blocked_ids & set(gate.get("allowed_item_ids", [])))
        and all("conditional_conflict_block" in decisions[item_id].get("reasons", []) for item_id in blocked_ids),
        "world_state_does_not_include_condition_sides": not (blocked_ids & set(world.get("included_cognition_ids", [])))
        and "WORLD_STATE may be updated when the user explicitly requests it" not in compact,
        "resolved_conditional_conflict_not_drift_warning": drift.get("ok") is True and drift.get("unresolved_high_severity_conflicts") == 0,
        "conditional_state_validates": validation.get("ok") is True,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pcs_conditional_conflict_eval_") as temp_dir:
        project_root = make_project_copy(temp_dir)
        checks = check_conditional_conflict(project_root)
    result = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
