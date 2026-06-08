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


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_project_copy(temp_dir: str) -> Path:
    project_root = Path(temp_dir) / "project"
    shutil.copytree(
        REPO_ROOT / ".project_cognition",
        project_root / ".project_cognition",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    feedback_path = project_root / ".project_cognition" / "distilled" / "scoring_feedback.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text("", encoding="utf-8")
    shadow_path = project_root / ".project_cognition" / "distilled" / "scoring_weight_shadow_report.json"
    if shadow_path.exists():
        shadow_path.unlink()
    return project_root


def run_script(project_root: Path, script_name: str, args: list[str] | None = None) -> Any:
    command = [sys.executable, str(project_root / ".project_cognition" / "scripts" / script_name), *(args or [])]
    completed = subprocess.run(command, cwd=project_root, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{script_name} failed with code {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    stdout = completed.stdout.strip()
    if not stdout:
        return None
    return json.loads(stdout)


def check_scoring_shadow(project_root: Path) -> dict[str, bool]:
    cognition_root = project_root / ".project_cognition"
    weights_path = cognition_root / "distilled" / "scoring_weights.json"
    feedback_path = cognition_root / "distilled" / "scoring_feedback.jsonl"
    shadow_path = cognition_root / "distilled" / "scoring_weight_shadow_report.json"
    feedback_rows = [
        {
            "id": "feedback_accept_preference",
            "timestamp": "2026-06-08T00:00:00Z",
            "proposal_id": "prop_accept_preference",
            "action": "accept",
            "proposal_confidence": 96,
            "category": "constraint",
            "should_update_world_state": True,
            "signals": ["user_explicit_preference", "user_strong_emphasis"],
            "note": "Eval accept feedback.",
            "applied_to_weights": False,
        },
        {
            "id": "feedback_reject_agent",
            "timestamp": "2026-06-08T00:01:00Z",
            "proposal_id": "prop_reject_agent",
            "action": "reject",
            "proposal_confidence": 90,
            "category": "risk",
            "should_update_world_state": False,
            "signals": ["agent_interpretation"],
            "note": "Eval reject feedback.",
            "applied_to_weights": False,
        },
    ]
    write_jsonl(feedback_path, feedback_rows)
    before_weights_text = weights_path.read_text(encoding="utf-8")
    before_feedback_text = feedback_path.read_text(encoding="utf-8")
    before_weights = read_json(weights_path)

    shadow = run_script(project_root, "update_scoring_weights.py")
    after_shadow_weights_text = weights_path.read_text(encoding="utf-8")
    after_shadow_feedback_text = feedback_path.read_text(encoding="utf-8")
    shadow_file = read_json(shadow_path)

    applied = run_script(project_root, "update_scoring_weights.py", ["--apply"])
    after_weights = read_json(weights_path)
    after_feedback = read_jsonl(feedback_path)

    return {
        "default_mode_is_shadow": shadow.get("mode") == "shadow" and shadow.get("writes_weights") is False and shadow.get("writes_feedback") is False,
        "shadow_does_not_mutate_weights_or_feedback": before_weights_text == after_shadow_weights_text and before_feedback_text == after_shadow_feedback_text,
        "shadow_report_written": shadow_file.get("mode") == "shadow" and shadow_file.get("would_apply") == 2 and shadow_file.get("changed_signal_count") == 3,
        "apply_mutates_weights": applied.get("mode") == "apply"
        and after_weights.get("signal_weights", {}).get("user_explicit_preference")
        > before_weights.get("signal_weights", {}).get("user_explicit_preference")
        and after_weights.get("signal_weights", {}).get("agent_interpretation")
        < before_weights.get("signal_weights", {}).get("agent_interpretation"),
        "apply_marks_feedback_rows": bool(after_feedback) and all(row.get("applied_to_weights") is True for row in after_feedback),
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pcs_scoring_eval_") as temp_dir:
        project_root = make_project_copy(temp_dir)
        checks = check_scoring_shadow(project_root)
    result = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
