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


def make_project_copy(temp_dir: str) -> Path:
    project_root = Path(temp_dir) / "project"
    shutil.copytree(REPO_ROOT / ".project_cognition", project_root / ".project_cognition", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return project_root


def run_script(project_root: Path, script_name: str, args: list[str] | None = None) -> Any:
    command = [sys.executable, str(project_root / ".project_cognition" / "scripts" / script_name), *(args or [])]
    completed = subprocess.run(command, cwd=project_root, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{script_name} failed with code {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    return json.loads(completed.stdout)


def check_forbidden_detector(project_root: Path) -> dict[str, bool]:
    result = run_script(project_root, "simulate_rule_change.py", ["--self-check", "--max-compact-chars", "1600"])
    failures = set(result.get("hard_failures", []))
    return {
        "self_check_passes": result.get("passed") is True,
        "blocks_agent_only": "assistant_or_agent_only_entered_core" in failures,
        "blocks_quoted_material": "quoted_or_external_user_material_entered_core" in failures,
        "blocks_stale_item": "stale_item_entered_core" in failures,
        "blocks_conflict_side": "unresolved_conflict_side_entered_world_state" in failures,
        "blocks_compact_overflow": "compact_characters_exceeded" in failures,
        "blocks_validation_increase": "validation_errors_increased" in failures,
        "blocks_drift_failure": "drift_report_hard_failures_present" in failures,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pcs_forbidden_eval_") as temp_dir:
        project_root = make_project_copy(temp_dir)
        checks = check_forbidden_detector(project_root)
    result = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
