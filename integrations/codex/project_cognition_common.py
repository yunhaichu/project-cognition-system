#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_DIR = Path.home() / "codex-hooks" / "state" / "project-cognition"
LOG_FILE = STATE_DIR / "hook-runs.jsonl"
BOOTSTRAP_SCRIPT = Path(
    os.environ.get(
        "PROJECT_COGNITION_BOOTSTRAP_SCRIPT",
        str(Path.home() / ".project_cognition" / "scripts" / "bootstrap_existing_project.py"),
    )
).expanduser()
CODEX_USER_PROFILE = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser() / "USER_PROFILE.md"

PROJECT_MARKER_FILES = {
    ".git",
    "README.md",
    "README.txt",
    "pyproject.toml",
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "Cargo.toml",
    "go.mod",
    "Package.swift",
    "Makefile",
}
PROJECT_MARKER_SUFFIXES = {".xcodeproj", ".xcworkspace"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_hook_input() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {"raw_stdin": raw[:2000]}


def hook_value(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    nested = payload.get("payload")
    if isinstance(nested, dict):
        for key in keys:
            value = nested.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def resolve_cwd(payload: dict[str, Any]) -> Path:
    cwd = hook_value(payload, "cwd", "current_working_directory", "project_root")
    return Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()


def iter_candidate_dirs(start: Path) -> list[Path]:
    current = start if start.is_dir() else start.parent
    return [current, *current.parents]


def has_complete_cognition(candidate: Path) -> bool:
    cognition_root = candidate / ".project_cognition"
    return (
        (cognition_root / "WORLD_STATE.md").exists()
        and (cognition_root / "scripts" / "codex_pre_hook.py").exists()
        and (cognition_root / "scripts" / "codex_post_hook.py").exists()
    )


def find_project_root(start: Path) -> Path | None:
    for candidate in iter_candidate_dirs(start):
        if has_complete_cognition(candidate):
            return candidate
    return None


def is_unsafe_bootstrap_target(candidate: Path) -> bool:
    resolved = candidate.resolve()
    home = Path.home().resolve()
    unsafe = {
        Path("/").resolve(),
        home,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "Library",
        home / ".codex",
        home / ".hermes",
        home / ".config",
        home / "codex-hooks",
    }
    if resolved in unsafe:
        return True
    try:
        parts = resolved.relative_to(home).parts
    except ValueError:
        return False
    return any(part.startswith(".") for part in parts)


def looks_like_project_root(candidate: Path) -> bool:
    if is_unsafe_bootstrap_target(candidate):
        return False
    for marker in PROJECT_MARKER_FILES:
        if (candidate / marker).exists():
            return True
    try:
        return any(child.suffix in PROJECT_MARKER_SUFFIXES for child in candidate.iterdir())
    except OSError:
        return False


def find_bootstrap_target(start: Path) -> Path | None:
    for candidate in iter_candidate_dirs(start):
        if has_complete_cognition(candidate):
            return None
        if looks_like_project_root(candidate):
            return candidate
    return None


def project_cognition_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PROJECT_COGNITION_AGENT"] = "codex"
    env["PROJECT_COGNITION_USER_PROFILE"] = str(CODEX_USER_PROFILE)
    return env


def bootstrap_project(target_root: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    if not BOOTSTRAP_SCRIPT.exists():
        raise FileNotFoundError(f"Project cognition bootstrap script not found: {BOOTSTRAP_SCRIPT}")
    return subprocess.run(
        [sys.executable, str(BOOTSTRAP_SCRIPT), "--target-root", str(target_root), "--no-create-agents"],
        cwd=target_root,
        env=project_cognition_env(),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def find_or_bootstrap_project_root(start: Path, allow_bootstrap: bool = True) -> tuple[Path | None, dict[str, Any] | None]:
    existing = find_project_root(start)
    if existing or not allow_bootstrap:
        return existing, None
    target = find_bootstrap_target(start)
    if not target:
        return None, None
    completed = bootstrap_project(target)
    event: dict[str, Any] = {
        "target_root": str(target),
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }
    if completed.returncode == 0 and has_complete_cognition(target):
        event["status"] = "created"
        return target, event
    event["status"] = "error"
    return None, event


def log_event(event: dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass


def run_project_script(project_root: Path, script_name: str, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    script = project_root / ".project_cognition" / "scripts" / script_name
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=project_root,
        env=project_cognition_env(),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def ensure_project_script(project_root: Path, script_name: str) -> bool:
    source = BOOTSTRAP_SCRIPT.parent / script_name
    destination = project_root / ".project_cognition" / "scripts" / script_name
    if destination.exists():
        return False
    if not source.exists():
        raise FileNotFoundError(f"Project cognition runtime script not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def emit_additional_context(text: str) -> None:
    json.dump({"hookSpecificOutput": {"additionalContext": text}}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def emit_empty() -> None:
    json.dump({"hookSpecificOutput": {}}, sys.stdout)
    sys.stdout.write("\n")

