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


def make_project_copy(temp_dir: str) -> Path:
    project_root = Path(temp_dir) / "project"
    shutil.copytree(REPO_ROOT / ".project_cognition", project_root / ".project_cognition", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    context_dir = project_root / ".project_cognition" / "logs" / "context_injections"
    context_dir.mkdir(parents=True, exist_ok=True)
    for child in context_dir.glob("*.json"):
        child.unlink()
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


def item(item_id: str, claim: str, *, scope: str = "project", status: str = "accepted", conditional: bool = False) -> dict[str, Any]:
    row = {
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
        "status": status,
        "structured": {
            "subject": "context_selection",
            "predicate": "requires",
            "object": claim,
            "object_key": item_id,
            "scope": scope,
            "modality": "must",
            "valid_from": "2026-06-08T00:00:00Z",
            "valid_until": None,
            "source_refs": [],
            "confidence_reason": "Context selection eval fixture.",
            "supersedes": [],
        },
    }
    if conditional:
        row["conditional_conflict_block"] = {"conflict_id": "conflict_context_eval", "condition": "only_when_explicit", "blocks_world_state": True}
    return row


def check_context_selection(project_root: Path) -> dict[str, bool]:
    cognition_root = project_root / ".project_cognition"
    confidence_path = cognition_root / "distilled" / "confidence_table.json"
    gate_path = cognition_root / "distilled" / "governance_gate.json"
    world_path = cognition_root / "WORLD_STATE.md"
    compact_path = cognition_root / "WORLD_STATE_COMPACT.md"
    raw_path = cognition_root / "raw" / "conflicts.jsonl"
    write_json(
        confidence_path,
        {
            "items": [
                item("ctx_relevant", "governance policy context selection must inject task relevant rules"),
                item("ctx_irrelevant", "database migration notes should not match this task"),
                item("ctx_conditional", "governance policy conditional conflict blocked item", conditional=True),
                item("ctx_not_admitted", "governance policy not admitted item"),
            ]
        },
    )
    write_json(
        gate_path,
        {
            "allowed_item_ids": ["ctx_relevant", "ctx_irrelevant", "ctx_conditional"],
            "policy_hash": "policy_eval_hash",
            "policy_version": 1,
            "policy_path": ".project_cognition/rules/governance_policy.json",
        },
    )
    before_world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""
    before_compact = compact_path.read_text(encoding="utf-8") if compact_path.exists() else ""
    before_confidence = confidence_path.read_text(encoding="utf-8")
    before_gate = gate_path.read_text(encoding="utf-8")
    before_raw = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
    result = run_script(project_root, "select_context.py", ["--session-id", "ctx_eval", "--task", "governance policy", "--max-chars", "900"])
    manifest_path = cognition_root / result["manifest_path"]
    manifest = read_json(manifest_path)
    after_world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""
    after_compact = compact_path.read_text(encoding="utf-8") if compact_path.exists() else ""
    after_confidence = confidence_path.read_text(encoding="utf-8")
    after_gate = gate_path.read_text(encoding="utf-8")
    after_raw = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
    return {
        "context_includes_relevant_item": "ctx_relevant" in result.get("context", "") and manifest.get("included_cognition_ids") == ["ctx_relevant"],
        "context_excludes_irrelevant_and_unadmitted": manifest.get("excluded_reason_counts", {}).get("not_task_relevant") == 1
        and manifest.get("excluded_reason_counts", {}).get("not_admitted") == 1,
        "context_excludes_conditional_block": manifest.get("excluded_reason_counts", {}).get("conditional_conflict_block") == 1,
        "manifest_written": manifest_path.exists() and manifest.get("session_id") == "ctx_eval" and manifest.get("mutates_state") is False,
        "manifest_has_hashes": bool(manifest.get("prompt_fingerprint")) and bool(manifest.get("ruleset_hash")) and manifest.get("gate_policy_hash") == "policy_eval_hash",
        "select_context_does_not_mutate_core_state": before_world == after_world
        and before_compact == after_compact
        and before_confidence == after_confidence
        and before_gate == after_gate
        and before_raw == after_raw,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pcs_context_eval_") as temp_dir:
        project_root = make_project_copy(temp_dir)
        checks = check_context_selection(project_root)
    result = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
