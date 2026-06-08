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


def seed_empty_profile_candidates(project_root: Path) -> None:
    confidence_path = project_root / ".project_cognition" / "distilled" / "confidence_table.json"
    write_json(confidence_path, {"items": []})


def read_report(project_root: Path) -> dict[str, Any]:
    report_path = project_root / ".project_cognition" / "proposals" / "user_profile_update_report.json"
    return json.loads(report_path.read_text(encoding="utf-8"))


def check_user_profile(project_root: Path, profile_path: Path) -> dict[str, bool]:
    seed_empty_profile_candidates(project_root)
    env = dict(os.environ)
    env["PROJECT_COGNITION_USER_PROFILE"] = str(profile_path)

    default_result = run_script(project_root, "build_user_profile.py", env=env)
    default_report_path = project_root / ".project_cognition" / "proposals" / "user_profile_update_report.json"
    default_report = read_report(project_root)
    after_default_exists = profile_path.exists()

    apply_result = run_script(project_root, "build_user_profile.py", ["--apply-profile"], env=env)
    apply_report = read_report(project_root)
    profile_content = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""

    return {
        "default_runs_as_proposal": default_result.get("applied") is False
        and default_result.get("mutates_global_profile") is False
        and default_report_path.exists()
        and default_report.get("mutates_global_profile") is False,
        "default_does_not_write_global_profile": not after_default_exists,
        "explicit_apply_writes_global_profile": profile_path.exists()
        and apply_result.get("applied") is True
        and apply_report.get("mutates_global_profile") is True,
        "profile_has_expected_header": "# USER_PROFILE.md" in profile_content,
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
