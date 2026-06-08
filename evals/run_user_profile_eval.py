#!/usr/bin/env python3
from __future__ import annotations

import json
import os
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
    return project_root


def run_script(project_root: Path, script_name: str, args: list[str] | None = None, env: dict[str, str] | None = None) -> Any:
    command = [sys.executable, str(project_root / ".project_cognition" / "scripts" / script_name), *(args or [])]
    completed = subprocess.run(command, cwd=project_root, env=env, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{script_name} failed with code {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    stdout = completed.stdout.strip()
    if not stdout:
        return None
    return json.loads(stdout)


def profile_item(item_id: str, claim: str, *, confidence: int = 98, stability: str = "stable", evidence: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": item_id,
        "claim": claim,
        "category": "user_principle",
        "confidence": confidence,
        "evidence": evidence if evidence is not None else [f"utt_{item_id}"],
        "conflicts": [],
        "last_verified": "2026-06-08T00:00:00Z",
        "stability": stability,
        "include_in_world_state": False,
        "source_type": "manual_initialization",
        "status": "accepted",
    }


def seed_profile_candidates(project_root: Path) -> None:
    confidence_path = project_root / ".project_cognition" / "distilled" / "confidence_table.json"
    write_json(
        confidence_path,
        {
            "items": [
                profile_item("profile_direct_practical", "用户要求回答直接务实，避免无关寒暄。", evidence=["utt_profile_direct", "utt_profile_repeat"]),
                profile_item("profile_project_only", "用户要求当前项目 WORLD_STATE 直接记录阶段进度。"),
                profile_item("profile_weak_single", "用户原话权重应在单次弱表达时直接写入画像。", stability="evolving", evidence=["utt_weak_once"]),
            ]
        },
    )


def read_report(project_root: Path) -> dict[str, Any]:
    report_path = project_root / ".project_cognition" / "proposals" / "user_profile_update_report.json"
    return json.loads(report_path.read_text(encoding="utf-8"))


def rejected_ids(report: dict[str, Any]) -> set[str]:
    return {str(row.get("item_id", "")) for row in report.get("rejected_candidates", [])}


def check_user_profile(project_root: Path, profile_path: Path) -> dict[str, bool]:
    seed_profile_candidates(project_root)
    env = dict(os.environ)
    env["PROJECT_COGNITION_USER_PROFILE"] = str(profile_path)
    default_result = run_script(project_root, "build_user_profile.py", env=env)
    default_report = read_report(project_root)
    run_script(project_root, "codex_post_hook.py", ["--skip-ingest", "--session-id", "profile_eval"], env=env)
    after_post_hook_exists = profile_path.exists()

    seed_profile_candidates(project_root)
    apply_result = run_script(project_root, "build_user_profile.py", ["--apply-profile"], env=env)
    profile_content = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    apply_report = read_report(project_root)
    return {
        "default_does_not_write_global_profile": default_result.get("applied") is False
        and default_result.get("mutates_global_profile") is False
        and default_result.get("would_change") is True
        and not profile_path.exists(),
        "default_writes_local_report": default_report.get("generated_candidate_count") == 1
        and {"profile_project_only", "profile_weak_single"} <= rejected_ids(default_report),
        "post_hook_default_does_not_write_global_profile": not after_post_hook_exists,
        "explicit_apply_writes_profile": apply_result.get("applied") is True and profile_path.exists(),
        "profile_includes_valid_candidate": "用户要求回答直接务实，避免无关寒暄。" in profile_content,
        "profile_excludes_project_only_candidate": "WORLD_STATE 直接记录阶段进度" not in profile_content,
        "profile_excludes_single_weak_expression": "单次弱表达时直接写入画像" not in profile_content,
        "apply_report_marks_global_mutation": apply_report.get("mutates_global_profile") is True and apply_report.get("applied") is True,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pcs_user_profile_eval_") as temp_dir:
        root = Path(temp_dir)
        project_root = make_project_copy(temp_dir)
        profile_path = root / "USER_PROFILE.md"
        checks = check_user_profile(project_root, profile_path)
    result = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
