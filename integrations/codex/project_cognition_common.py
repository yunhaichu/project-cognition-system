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
LOG_MAX_BYTES = int(os.environ.get("PROJECT_COGNITION_HOOK_LOG_MAX_BYTES", str(1024 * 1024)))
LOG_BACKUPS = int(os.environ.get("PROJECT_COGNITION_HOOK_LOG_BACKUPS", "3"))
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
RUNTIME_SCRIPT_NAMES = [
    "common.py",
    "ingest_session.py",
    "extract_candidates.py",
    "score_candidates.py",
    "detect_conflicts.py",
    "cluster_candidates.py",
    "cluster_conflicts.py",
    "auto_governance_gate.py",
    "build_world_state.py",
    "build_user_profile.py",
    "index_segments.py",
    "lookup_evidence.py",
    "drift_report.py",
    "upgrade_state.py",
    "migrate_legacy_state.py",
    "review_conflict_cluster.py",
    "codex_pre_hook.py",
    "codex_post_hook.py",
    "update_scoring_weights.py",
    "validate_state.py",
    "resolve_conflict.py",
    "propose_update.py",
    "review_update.py",
]
RUNTIME_SCHEMA_NAMES = [
    "agent_interpretation.schema.json",
    "cognition_candidate.schema.json",
    "confidence_table.schema.json",
    "conflict.schema.json",
    "decision.schema.json",
    "proposed_update.schema.json",
    "tool_evidence.schema.json",
    "user_utterance.schema.json",
    "world_state.schema.json",
    "state_version.schema.json",
]


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
        if not is_unsafe_bootstrap_target(candidate) and has_complete_cognition(candidate):
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
        if is_unsafe_bootstrap_target(candidate):
            continue
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


def truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def rotate_log_if_needed() -> None:
    if LOG_MAX_BYTES <= 0 or LOG_BACKUPS <= 0 or not LOG_FILE.exists():
        return
    try:
        if LOG_FILE.stat().st_size <= LOG_MAX_BYTES:
            return
        for index in range(LOG_BACKUPS - 1, 0, -1):
            source = LOG_FILE.with_name(f"{LOG_FILE.name}.{index}")
            destination = LOG_FILE.with_name(f"{LOG_FILE.name}.{index + 1}")
            if source.exists():
                if destination.exists():
                    destination.unlink()
                source.rename(destination)
        first_backup = LOG_FILE.with_name(f"{LOG_FILE.name}.1")
        if first_backup.exists():
            first_backup.unlink()
        LOG_FILE.rename(first_backup)
    except OSError:
        pass


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
        rotate_log_if_needed()
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


def files_differ(source: Path, destination: Path) -> bool:
    if not destination.exists():
        return True
    try:
        return source.read_bytes() != destination.read_bytes()
    except OSError:
        return True


def ensure_project_script(project_root: Path, script_name: str) -> bool:
    source = BOOTSTRAP_SCRIPT.parent / script_name
    destination = project_root / ".project_cognition" / "scripts" / script_name
    if destination.exists() and not files_differ(source, destination):
        return False
    if not source.exists():
        raise FileNotFoundError(f"Project cognition runtime script not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def runtime_schema_names() -> list[str]:
    source_dir = BOOTSTRAP_SCRIPT.parent.parent / "schemas"
    if source_dir.exists():
        return sorted(path.name for path in source_dir.glob("*.schema.json"))
    return RUNTIME_SCHEMA_NAMES


def ensure_project_schema(project_root: Path, schema_name: str) -> bool:
    source = BOOTSTRAP_SCRIPT.parent.parent / "schemas" / schema_name
    destination = project_root / ".project_cognition" / "schemas" / schema_name
    if destination.exists() and not files_differ(source, destination):
        return False
    if not source.exists():
        raise FileNotFoundError(f"Project cognition runtime schema not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def ensure_project_runtime(project_root: Path, script_names: list[str] | None = None) -> dict[str, Any]:
    copied: list[str] = []
    missing: list[str] = []
    for script_name in script_names or RUNTIME_SCRIPT_NAMES:
        try:
            if ensure_project_script(project_root, script_name):
                copied.append(script_name)
        except FileNotFoundError:
            missing.append(script_name)
    copied_schemas: list[str] = []
    missing_schemas: list[str] = []
    for schema_name in runtime_schema_names():
        try:
            if ensure_project_schema(project_root, schema_name):
                copied_schemas.append(schema_name)
        except FileNotFoundError:
            missing_schemas.append(schema_name)
    return {
        "copied": copied,
        "missing": missing,
        "copied_schemas": copied_schemas,
        "missing_schemas": missing_schemas,
    }


def summarize_mapping(value: Any, keys: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in keys if key in value}


def summarize_post_hook_stdout(stdout: str) -> dict[str, Any]:
    raw = stdout.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_stdout_chars": len(stdout), "stdout_tail": truncate_text(stdout, 1000)}
    if not isinstance(data, dict):
        return {"raw_stdout_chars": len(stdout), "stdout_type": type(data).__name__}

    summary: dict[str, Any] = summarize_mapping(
        data,
        ["hook", "timestamp", "session_id", "ingested", "local_only", "step_count", "step_scripts"],
    )
    summary["raw_stdout_chars"] = len(stdout)
    summary["world_state"] = summarize_mapping(
        data.get("world_state"),
        ["included_count", "structured_count", "compact_structured_count", "characters", "compact_characters"],
    )
    summary["state_upgrade"] = summarize_mapping(
        data.get("state_upgrade"),
        ["needs_upgrade", "from_version", "to_version", "repair", "local_only", "llm_used"],
    )
    summary["user_profile"] = summarize_mapping(
        data.get("user_profile"),
        ["changed", "generated_candidates", "min_confidence"],
    )
    summary["conflicts"] = summarize_mapping(data.get("conflicts"), ["new_conflicts", "total_conflicts"])
    summary["conflict_clusters"] = summarize_mapping(
        data.get("conflict_clusters"),
        ["total_conflicts", "cluster_count"],
    )
    summary["evidence_index"] = summarize_mapping(
        data.get("evidence_index"),
        ["segment_count", "source_types", "source_file_count", "skipped", "skip_reason", "local_only"],
    )
    summary["drift"] = summarize_mapping(
        data.get("drift"),
        [
            "ok",
            "compact_characters",
            "max_compact_chars",
            "unresolved_high_severity_conflicts",
            "max_high_severity_conflicts",
            "conflict_cluster_count",
            "dangling_reference_errors",
            "stale_revived_items",
            "assistant_only_core_items",
            "candidate_core_items",
            "evidence_mix",
            "warnings",
            "hard_failures",
        ],
    )
    return summary


def emit_additional_context(text: str) -> None:
    json.dump({"hookSpecificOutput": {"additionalContext": text}}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def emit_empty() -> None:
    json.dump({"hookSpecificOutput": {}}, sys.stdout)
    sys.stdout.write("\n")
