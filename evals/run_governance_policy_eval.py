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


def make_project_copy(temp_dir: str) -> Path:
    project_root = Path(temp_dir) / "project"
    shutil.copytree(REPO_ROOT / ".project_cognition", project_root / ".project_cognition", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in [
        project_root / ".project_cognition" / "raw" / "conflicts.jsonl",
        project_root / ".project_cognition" / "raw" / "feedback_events.jsonl",
        project_root / ".project_cognition" / "raw" / "rule_change_log.jsonl",
        project_root / ".project_cognition" / "proposals" / "rule_change_proposals.jsonl",
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


def item(item_id: str, object_value: str, confidence: int = 98) -> dict[str, Any]:
    return {
        "id": item_id,
        "claim": f"Policy eval item {item_id}.",
        "category": "constraint",
        "confidence": confidence,
        "evidence": [],
        "conflicts": [],
        "last_verified": "2026-06-08T00:00:00Z",
        "stability": "stable",
        "include_in_world_state": False,
        "source_type": "manual_initialization",
        "status": "accepted",
        "topics": [],
        "structured": {
            "subject": "policy_eval",
            "predicate": "requires",
            "object": object_value,
            "object_key": object_value,
            "scope": "project",
            "modality": "must",
            "valid_from": "2026-06-08T00:00:00Z",
            "valid_until": None,
            "source_refs": [],
            "confidence_reason": "Policy eval fixture.",
            "supersedes": [],
        },
    }


def check_governance_policy(project_root: Path) -> dict[str, bool]:
    cognition_root = project_root / ".project_cognition"
    table_path = cognition_root / "distilled" / "confidence_table.json"
    write_json(table_path, {"items": [item("policy_high", "policy_high"), item("policy_low", "policy_low", 95)]})
    default_policy_validation = run_script(project_root, "validate_governance_policy.py")
    default_gate = run_script(project_root, "auto_governance_gate.py")
    policy = json.loads((cognition_root / "rules" / "governance_policy.json").read_text(encoding="utf-8"))
    policy["version"] = 2
    policy["admission_budget"]["max_allowed"] = 1
    policy["admission_budget"]["max_per_category"] = 0
    policy["admission_budget"]["max_per_predicate"] = 0
    policy["admission_budget"]["max_per_slot"] = 0
    custom_policy_path = cognition_root / "rules" / "eval_policy.json"
    write_json(custom_policy_path, policy)
    custom_policy_validation = run_script(project_root, "validate_governance_policy.py", ["--policy", ".project_cognition/rules/eval_policy.json"])
    custom_gate = run_script(project_root, "auto_governance_gate.py", ["--policy", ".project_cognition/rules/eval_policy.json"])
    override_gate = run_script(project_root, "auto_governance_gate.py", ["--policy", ".project_cognition/rules/eval_policy.json", "--max-allowed", "2"])
    return {
        "default_policy_validates": default_policy_validation.get("ok") is True and default_policy_validation.get("policy_version") == 1,
        "custom_policy_validates": custom_policy_validation.get("ok") is True and custom_policy_validation.get("policy_version") == 2,
        "default_policy_metadata_present": default_gate.get("policy_version") == 1
        and bool(default_gate.get("policy_hash"))
        and default_gate.get("policy_path") == ".project_cognition/rules/governance_policy.json",
        "default_policy_allows_both": default_gate.get("allowed_count") == 2,
        "custom_policy_hash_changes": custom_gate.get("policy_version") == 2
        and custom_gate.get("policy_hash") != default_gate.get("policy_hash")
        and custom_gate.get("policy_path") == ".project_cognition/rules/eval_policy.json",
        "custom_policy_budget_changes_gate": custom_gate.get("allowed_count") == 1
        and custom_gate.get("admission_budget", {}).get("max_allowed") == 1,
        "cli_override_still_works": override_gate.get("allowed_count") == 2
        and override_gate.get("admission_budget", {}).get("max_allowed") == 2,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pcs_policy_eval_") as temp_dir:
        project_root = make_project_copy(temp_dir)
        checks = check_governance_policy(project_root)
    result = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
