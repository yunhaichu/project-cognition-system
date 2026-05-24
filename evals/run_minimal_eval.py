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
CASE_FILE = REPO_ROOT / "evals" / "cases" / "minimal_governance_session.jsonl"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reset_state(project_root: Path) -> None:
    cognition_root = project_root / ".project_cognition"
    for path in [
        cognition_root / "raw" / "user_utterances.jsonl",
        cognition_root / "raw" / "agent_interpretations.jsonl",
        cognition_root / "raw" / "tool_evidence.jsonl",
        cognition_root / "raw" / "decisions.jsonl",
        cognition_root / "raw" / "conflicts.jsonl",
        cognition_root / "proposals" / "proposed_updates.jsonl",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for directory in [
        cognition_root / "raw" / "sessions",
        cognition_root / "logs" / "sessions",
        cognition_root / "logs" / "tool_calls",
        cognition_root / "logs" / "outputs",
        cognition_root / "logs" / "file_changes",
    ]:
        directory.mkdir(parents=True, exist_ok=True)
        for child in directory.glob("*.json*"):
            child.unlink()
    write_json(cognition_root / "distilled" / "confidence_table.json", {"items": []})
    scoring_feedback = cognition_root / "distilled" / "scoring_feedback.jsonl"
    if scoring_feedback.exists():
        scoring_feedback.unlink()


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
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return stdout


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_eval() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pcs_eval_") as temp_dir:
        project_root = Path(temp_dir) / "project"
        shutil.copytree(
            REPO_ROOT / ".project_cognition",
            project_root / ".project_cognition",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        reset_state(project_root)

        steps = {
            "ingest": run_script(
                project_root,
                "ingest_session.py",
                ["--input", str(CASE_FILE), "--session-id", "eval_minimal", "--source", "eval"],
            ),
            "extract": run_script(project_root, "extract_candidates.py"),
            "score": run_script(project_root, "score_candidates.py"),
            "conflicts": run_script(project_root, "detect_conflicts.py"),
            "world_state": run_script(project_root, "build_world_state.py"),
            "unresolved": run_script(project_root, "resolve_conflict.py", ["--list-unresolved"]),
        }

        cognition_root = project_root / ".project_cognition"
        table = read_json(cognition_root / "distilled" / "confidence_table.json")
        items = table.get("items", [])
        tool_evidence = read_jsonl(cognition_root / "raw" / "tool_evidence.jsonl")
        assistant_outputs = read_jsonl(cognition_root / "logs" / "outputs" / "eval_minimal.jsonl")
        compact_chars = len((cognition_root / "WORLD_STATE_COMPACT.md").read_text(encoding="utf-8"))
        tool_items = [item for item in items if item.get("source_type") == "tool_evidence"]

        checks = {
            "user_utterance_ingested": steps["ingest"]["counts"]["user"] == 1,
            "assistant_output_is_log": len(assistant_outputs) == 1,
            "tool_evidence_ingested": len(tool_evidence) == 1 and tool_evidence[0].get("evidence_kind") == "test_result",
            "candidates_have_structured_fields": bool(items) and all("structured" in item for item in items),
            "tool_only_candidate_requires_review_for_world_state": bool(tool_items)
            and all(not item.get("include_in_world_state") for item in tool_items),
            "compact_state_under_1600_chars": compact_chars <= 1600,
        }
        return {
            "case": str(CASE_FILE.relative_to(REPO_ROOT)),
            "steps": steps,
            "checks": checks,
            "passed": all(checks.values()),
        }


def main() -> None:
    result = run_eval()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
