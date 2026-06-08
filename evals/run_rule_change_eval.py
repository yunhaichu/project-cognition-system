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
    shutil.copytree(REPO_ROOT / ".project_cognition", project_root / ".project_cognition", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in [
        project_root / ".project_cognition" / "raw" / "feedback_events.jsonl",
        project_root / ".project_cognition" / "raw" / "rule_change_log.jsonl",
        project_root / ".project_cognition" / "proposals" / "rule_change_proposals.jsonl",
        project_root / ".project_cognition" / "distilled" / "scoring_feedback.jsonl",
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


def run_script_status(project_root: Path, script_name: str, args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(project_root / ".project_cognition" / "scripts" / script_name), *(args or [])]
    return subprocess.run(command, cwd=project_root, text=True, capture_output=True, check=False)


def seed_feedback(project_root: Path) -> None:
    cognition_root = project_root / ".project_cognition"
    write_jsonl(
        cognition_root / "raw" / "feedback_events.jsonl",
        [
            {
                "id": "fb_rule_weight_eval",
                "timestamp": "2026-06-08T00:00:00Z",
                "session_id": "rule_change_eval",
                "task_id": "",
                "event_family": "rule",
                "event_name": "scoring_weight_feedback",
                "target_type": "rule",
                "target_id": "scoring_weights",
                "outcome": "positive",
                "severity": 30,
                "source_type": "manual_review",
                "source_refs": [],
                "confidence": 95,
                "notes": "Eval feedback event anchoring the rule proposal.",
            }
        ],
    )
    write_jsonl(
        cognition_root / "distilled" / "scoring_feedback.jsonl",
        [
            {
                "id": "feedback_accept_rule_lifecycle",
                "timestamp": "2026-06-08T00:01:00Z",
                "proposal_id": "prop_rule_lifecycle",
                "action": "accept",
                "proposal_confidence": 96,
                "category": "constraint",
                "should_update_world_state": True,
                "signals": ["user_explicit_preference"],
                "note": "Eval accepted scoring feedback.",
                "applied_to_weights": False,
            }
        ],
    )


def check_rule_change_lifecycle(project_root: Path) -> dict[str, bool]:
    cognition_root = project_root / ".project_cognition"
    weights_path = cognition_root / "distilled" / "scoring_weights.json"
    seed_feedback(project_root)
    before_weights = weights_path.read_text(encoding="utf-8")
    proposal = run_script(project_root, "propose_rule_change.py", ["--reason", "Eval rule-change lifecycle.", "--evidence", "fb_rule_weight_eval"])
    unsimulated_apply = run_script_status(project_root, "apply_rule_change.py", ["--proposal-id", proposal["id"]])
    after_unsimulated = weights_path.read_text(encoding="utf-8")
    simulation = run_script(project_root, "simulate_rule_change.py", ["--proposal-id", proposal["id"]])
    after_simulation = weights_path.read_text(encoding="utf-8")
    applied = run_script(project_root, "apply_rule_change.py", ["--proposal-id", proposal["id"]])
    after_weights = weights_path.read_text(encoding="utf-8")
    proposals = read_jsonl(cognition_root / "proposals" / "rule_change_proposals.jsonl")
    logs = read_jsonl(cognition_root / "raw" / "rule_change_log.jsonl")
    validation = run_script(project_root, "validate_state.py")
    report_path = cognition_root / str(proposals[0].get("simulation_report_path", ""))
    report_exists = report_path.exists() and bool(read_json(report_path).get("id"))
    return {
        "proposal_created_pending": proposal.get("status") == "pending" and proposal.get("requires_explicit_apply") is True,
        "unsimulated_apply_refused": unsimulated_apply.returncode != 0 and before_weights == after_unsimulated,
        "simulation_records_report": simulation.get("proposal_id") == proposal.get("id") and simulation.get("hard_failures") == [] and report_exists,
        "simulation_does_not_mutate_weights": before_weights == after_simulation,
        "apply_mutates_weights_and_logs": before_weights != after_weights and bool(logs) and logs[0].get("proposal_id") == proposal.get("id"),
        "proposal_marked_applied": proposals[0].get("status") == "applied" and bool(proposals[0].get("applied_at")),
        "applied_feedback_marked": applied.get("update_result", {}).get("mode") == "apply",
        "rule_change_state_validates": validation.get("ok") is True,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pcs_rule_change_eval_") as temp_dir:
        project_root = make_project_copy(temp_dir)
        checks = check_rule_change_lifecycle(project_root)
    result = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
