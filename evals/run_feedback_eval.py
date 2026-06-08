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


def make_project_copy(temp_dir: str) -> Path:
    project_root = Path(temp_dir) / "project"
    shutil.copytree(
        REPO_ROOT / ".project_cognition",
        project_root / ".project_cognition",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for path in [
        project_root / ".project_cognition" / "raw" / "user_utterances.jsonl",
        project_root / ".project_cognition" / "raw" / "tool_evidence.jsonl",
        project_root / ".project_cognition" / "raw" / "feedback_events.jsonl",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
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


def run_script_status(project_root: Path, script_name: str, args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(project_root / ".project_cognition" / "scripts" / script_name), *(args or [])]
    return subprocess.run(command, cwd=project_root, text=True, capture_output=True, check=False)


def check_feedback_layer(project_root: Path) -> dict[str, bool]:
    cognition_root = project_root / ".project_cognition"
    utterance = {
        "id": "utt_feedback_anchor",
        "session_id": "feedback_eval",
        "timestamp": "2026-06-08T00:00:00Z",
        "text": "用户纠正：这条规则不应进入核心状态。",
        "source": "eval",
        "utterance_intent": "direct_user_intent",
        "importance_score": 95,
        "signals": {
            "long_form": False,
            "repeated": False,
            "explicit_preference": True,
            "explicit_rejection": True,
            "strong_emphasis": True,
        },
        "linked_topics": ["feedback"],
        "notes": "",
    }
    tool_log = {
        "id": "tool_feedback_anchor",
        "session_id": "feedback_eval",
        "timestamp": "2026-06-08T00:01:00Z",
        "name": "pytest",
        "content": "1 failed",
    }
    tool_evidence = {
        "id": "tool_ev_feedback_anchor",
        "session_id": "feedback_eval",
        "timestamp": "2026-06-08T00:01:00Z",
        "tool_name": "pytest",
        "source_log_id": "tool_feedback_anchor",
        "source": "tool",
        "evidence_kind": "test_result",
        "deterministic": True,
        "outcome": "failed",
        "content_summary": "1 failed",
        "linked_topics": ["feedback"],
        "notes": "",
    }
    write_jsonl(cognition_root / "raw" / "user_utterances.jsonl", [utterance])
    write_jsonl(cognition_root / "logs" / "tool_calls" / "feedback_eval.jsonl", [tool_log])
    write_jsonl(cognition_root / "raw" / "tool_evidence.jsonl", [tool_evidence])

    first = run_script(
        project_root,
        "record_feedback.py",
        [
            "--session-id",
            "feedback_eval",
            "--event-family",
            "correction",
            "--event-name",
            "user_correction",
            "--target-type",
            "rule",
            "--target-id",
            "feedback_rule_no_core",
            "--outcome",
            "negative",
            "--severity",
            "90",
            "--source-type",
            "user_utterance",
            "--source-ref",
            "utt_feedback_anchor",
            "--confidence",
            "98",
            "--notes",
            "Eval correction feedback.",
        ],
    )
    second = run_script(
        project_root,
        "record_feedback.py",
        [
            "--session-id",
            "feedback_eval",
            "--event-family",
            "test",
            "--event-name",
            "test_failed_after_plan",
            "--target-type",
            "test",
            "--target-id",
            "pytest",
            "--outcome",
            "negative",
            "--severity",
            "80",
            "--source-type",
            "deterministic_tool",
            "--source-ref",
            "tool_ev_feedback_anchor",
            "--confidence",
            "100",
        ],
    )
    validation = run_script(project_root, "validate_state.py")
    report = run_script(project_root, "feedback_report.py")

    broken = dict(second)
    broken["id"] = "fb_broken"
    broken["source_refs"] = ["tool_ev_missing"]
    write_jsonl(cognition_root / "raw" / "feedback_events.jsonl", [first, broken])
    invalid = run_script_status(project_root, "validate_state.py")
    before_world = (cognition_root / "WORLD_STATE.md").read_text(encoding="utf-8")
    before_table = (cognition_root / "distilled" / "confidence_table.json").read_text(encoding="utf-8")
    run_script(project_root, "feedback_report.py")
    after_world = (cognition_root / "WORLD_STATE.md").read_text(encoding="utf-8")
    after_table = (cognition_root / "distilled" / "confidence_table.json").read_text(encoding="utf-8")
    return {
        "feedback_events_recorded": first.get("id", "").startswith("fb_") and second.get("id", "").startswith("fb_"),
        "feedback_state_validates": validation.get("ok") is True,
        "feedback_report_counts": report.get("feedback_count") == 2
        and report.get("negative_feedback_count") == 2
        and report.get("user_correction_count") == 1
        and report.get("deterministic_tool_feedback_count") == 1,
        "feedback_report_does_not_mutate_state": before_world == after_world and before_table == after_table,
        "dangling_feedback_source_ref_detected": invalid.returncode != 0 and "tool_ev_missing" in invalid.stdout,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pcs_feedback_eval_") as temp_dir:
        project_root = make_project_copy(temp_dir)
        checks = check_feedback_layer(project_root)
    result = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
