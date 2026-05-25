"""Project Cognition plugin for Hermes Agent.

Matches the current Codex hook strategy:
- resolve the current project from cwd, not from a global cognition folder;
- bootstrap a minimal per-project .project_cognition only for directories that
  look like real project roots;
- inject only compact project state, at most once per session/project by default;
- store each completed turn as evidence and run the local per-project
  codex_post_hook.py pipeline by default, without calling an LLM.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("hermes_plugins.project_cognition")

_STATE_DIR = Path.home() / ".hermes" / "state" / "project-cognition"
_LOG_FILE = _STATE_DIR / "hook-runs.jsonl"
_LOG_MAX_BYTES = int(os.environ.get("HERMES_PROJECT_COGNITION_LOG_MAX_BYTES", str(1024 * 1024)))
_LOG_BACKUPS = int(os.environ.get("HERMES_PROJECT_COGNITION_LOG_BACKUPS", "3"))
_BOOTSTRAP_SCRIPT = Path(
    os.environ.get(
        "PROJECT_COGNITION_BOOTSTRAP_SCRIPT",
        str(Path.home() / ".project_cognition" / "scripts" / "bootstrap_existing_project.py"),
    )
).expanduser()
_HERMES_USER_PROFILE = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser() / "USER_PROFILE.md"

_MAX_CONTEXT_CHARS = int(os.environ.get("HERMES_PROJECT_COGNITION_MAX_CONTEXT_CHARS", "1600"))
_INJECT_MODE = os.environ.get("HERMES_PROJECT_COGNITION_INJECT_MODE", "once").lower()
_RUN_POST_HOOK = os.environ.get("HERMES_PROJECT_COGNITION_RUN_POST_HOOK", "1").lower() in {"1", "true", "yes", "on"}
_PRE_HOOK_TIMEOUT = int(os.environ.get("HERMES_PROJECT_COGNITION_PRE_TIMEOUT", "30"))
_POST_HOOK_TIMEOUT = int(os.environ.get("HERMES_PROJECT_COGNITION_POST_TIMEOUT", "90"))
_PROFILE_TIMEOUT = int(os.environ.get("HERMES_PROJECT_COGNITION_PROFILE_TIMEOUT", "15"))

_PROJECT_MARKER_FILES = {
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
_PROJECT_MARKER_SUFFIXES = {".xcodeproj", ".xcworkspace"}
_RUNTIME_SCRIPT_NAMES = [
    "common.py",
    "ingest_session.py",
    "extract_candidates.py",
    "score_candidates.py",
    "detect_conflicts.py",
    "cluster_conflicts.py",
    "build_world_state.py",
    "build_user_profile.py",
    "index_segments.py",
    "lookup_evidence.py",
    "drift_report.py",
    "review_conflict_cluster.py",
    "codex_pre_hook.py",
    "codex_post_hook.py",
    "update_scoring_weights.py",
    "validate_state.py",
    "resolve_conflict.py",
    "propose_update.py",
    "review_update.py",
]
_RUNTIME_SCHEMA_NAMES = [
    "agent_interpretation.schema.json",
    "cognition_candidate.schema.json",
    "confidence_table.schema.json",
    "conflict.schema.json",
    "decision.schema.json",
    "proposed_update.schema.json",
    "tool_evidence.schema.json",
    "user_utterance.schema.json",
    "world_state.schema.json",
]

_CONTEXT_MINIMALISM_NOTICE = (
    "Context Minimal Mode: use current command + global protocol + compact project state. "
    "Do not rely on thread history; read specific original sources only when needed."
)

_INJECTED_KEYS: set[str] = set()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def _short_hash(text: str, length: int = 10) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def _safe_id(value: str | None, fallback: str = "default") -> str:
    raw = value or fallback
    safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(raw)).strip("_")
    return safe[:120] or fallback


def _hook_value(kwargs: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = kwargs.get(key)
        if isinstance(value, str) and value:
            return value
    payload = kwargs.get("payload")
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _resolve_cwd(kwargs: dict[str, Any]) -> Path:
    cwd = _hook_value(kwargs, "cwd", "current_working_directory", "project_root", "working_directory", "workspace")
    if cwd:
        return Path(cwd).expanduser().resolve()
    pwd = os.environ.get("PWD")
    if pwd:
        return Path(pwd).expanduser().resolve()
    return Path.cwd().resolve()


def _candidate_dirs(start: Path) -> list[Path]:
    current = start if start.is_dir() else start.parent
    return [current, *current.parents]


def _has_complete_cognition(candidate: Path) -> bool:
    cognition_root = candidate / ".project_cognition"
    return (
        (cognition_root / "WORLD_STATE.md").exists()
        and (cognition_root / "scripts" / "codex_pre_hook.py").exists()
        and (cognition_root / "scripts" / "codex_post_hook.py").exists()
    )


def _is_unsafe_bootstrap_target(candidate: Path) -> bool:
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


def _looks_like_project_root(candidate: Path) -> bool:
    if _is_unsafe_bootstrap_target(candidate):
        return False
    for marker in _PROJECT_MARKER_FILES:
        if (candidate / marker).exists():
            return True
    try:
        return any(child.suffix in _PROJECT_MARKER_SUFFIXES for child in candidate.iterdir())
    except OSError:
        return False


def _find_project_root(start: Path) -> Path | None:
    for candidate in _candidate_dirs(start):
        if _has_complete_cognition(candidate):
            return candidate
    return None


def _find_bootstrap_target(start: Path) -> Path | None:
    for candidate in _candidate_dirs(start):
        if _has_complete_cognition(candidate):
            return None
        if _looks_like_project_root(candidate):
            return candidate
    return None


def _bootstrap_project(target_root: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    if not _BOOTSTRAP_SCRIPT.exists():
        raise FileNotFoundError(f"Project cognition bootstrap script not found: {_BOOTSTRAP_SCRIPT}")
    env = _project_cognition_env()
    return subprocess.run(
        [
            sys.executable,
            str(_BOOTSTRAP_SCRIPT),
            "--target-root",
            str(target_root),
            "--no-create-agents",
        ],
        cwd=target_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _find_or_bootstrap_project_root(start: Path, allow_bootstrap: bool = True) -> tuple[Path | None, dict[str, Any] | None]:
    existing = _find_project_root(start)
    if existing or not allow_bootstrap:
        return existing, None

    target = _find_bootstrap_target(start)
    if not target:
        return None, None

    completed = _bootstrap_project(target)
    event = {
        "target_root": str(target),
        "returncode": completed.returncode,
        "stdout": _truncate_text(completed.stdout, 1000),
        "stderr": _truncate_text(completed.stderr, 1000),
    }
    if completed.returncode == 0 and _has_complete_cognition(target):
        event["status"] = "created"
        return target, event
    event["status"] = "error"
    return None, event


def _rotate_log_if_needed() -> None:
    if _LOG_MAX_BYTES <= 0 or _LOG_BACKUPS <= 0 or not _LOG_FILE.exists():
        return
    try:
        if _LOG_FILE.stat().st_size <= _LOG_MAX_BYTES:
            return
        for index in range(_LOG_BACKUPS - 1, 0, -1):
            source = _LOG_FILE.with_name(f"{_LOG_FILE.name}.{index}")
            destination = _LOG_FILE.with_name(f"{_LOG_FILE.name}.{index + 1}")
            if source.exists():
                if destination.exists():
                    destination.unlink()
                source.rename(destination)
        first_backup = _LOG_FILE.with_name(f"{_LOG_FILE.name}.1")
        if first_backup.exists():
            first_backup.unlink()
        _LOG_FILE.rename(first_backup)
    except OSError:
        pass


def _run_project_script(project_root: Path, script_name: str, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    script = project_root / ".project_cognition" / "scripts" / script_name
    env = _project_cognition_env()
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _project_cognition_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PROJECT_COGNITION_AGENT"] = "hermes"
    env["PROJECT_COGNITION_USER_PROFILE"] = str(_HERMES_USER_PROFILE)
    return env


def _files_differ(source: Path, destination: Path) -> bool:
    if not destination.exists():
        return True
    try:
        return source.read_bytes() != destination.read_bytes()
    except OSError:
        return True


def _ensure_project_script(project_root: Path, script_name: str) -> bool:
    source = _BOOTSTRAP_SCRIPT.parent / script_name
    destination = project_root / ".project_cognition" / "scripts" / script_name
    if destination.exists() and not _files_differ(source, destination):
        return False
    if not source.exists():
        raise FileNotFoundError(f"Project cognition runtime script not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _runtime_schema_names() -> list[str]:
    source_dir = _BOOTSTRAP_SCRIPT.parent.parent / "schemas"
    if source_dir.exists():
        return sorted(path.name for path in source_dir.glob("*.schema.json"))
    return _RUNTIME_SCHEMA_NAMES


def _ensure_project_schema(project_root: Path, schema_name: str) -> bool:
    source = _BOOTSTRAP_SCRIPT.parent.parent / "schemas" / schema_name
    destination = project_root / ".project_cognition" / "schemas" / schema_name
    if destination.exists() and not _files_differ(source, destination):
        return False
    if not source.exists():
        raise FileNotFoundError(f"Project cognition runtime schema not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _ensure_project_runtime(project_root: Path, script_names: list[str] | None = None) -> dict[str, Any]:
    copied: list[str] = []
    missing: list[str] = []
    for script_name in script_names or _RUNTIME_SCRIPT_NAMES:
        try:
            if _ensure_project_script(project_root, script_name):
                copied.append(script_name)
        except FileNotFoundError:
            missing.append(script_name)
    copied_schemas: list[str] = []
    missing_schemas: list[str] = []
    for schema_name in _runtime_schema_names():
        try:
            if _ensure_project_schema(project_root, schema_name):
                copied_schemas.append(schema_name)
        except FileNotFoundError:
            missing_schemas.append(schema_name)
    return {
        "copied": copied,
        "missing": missing,
        "copied_schemas": copied_schemas,
        "missing_schemas": missing_schemas,
    }


def _log_event(event: dict[str, Any]) -> None:
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed()
        with _LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass


def _summarize_mapping(value: Any, keys: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in keys if key in value}


def _summarize_post_hook_stdout(stdout: str) -> dict[str, Any]:
    raw = stdout.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_stdout_chars": len(stdout), "stdout_tail": _truncate_text(stdout, 1000)}
    if not isinstance(data, dict):
        return {"raw_stdout_chars": len(stdout), "stdout_type": type(data).__name__}

    summary: dict[str, Any] = _summarize_mapping(
        data,
        ["hook", "timestamp", "session_id", "ingested", "local_only", "step_count", "step_scripts"],
    )
    summary["raw_stdout_chars"] = len(stdout)
    summary["world_state"] = _summarize_mapping(
        data.get("world_state"),
        ["included_count", "structured_count", "compact_structured_count", "characters", "compact_characters"],
    )
    summary["user_profile"] = _summarize_mapping(data.get("user_profile"), ["changed", "generated_candidates", "min_confidence"])
    summary["conflicts"] = _summarize_mapping(data.get("conflicts"), ["new_conflicts", "total_conflicts"])
    summary["conflict_clusters"] = _summarize_mapping(data.get("conflict_clusters"), ["total_conflicts", "cluster_count"])
    summary["evidence_index"] = _summarize_mapping(
        data.get("evidence_index"),
        ["segment_count", "source_types", "source_file_count", "skipped", "skip_reason", "local_only"],
    )
    summary["drift"] = _summarize_mapping(
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
            "evidence_mix",
            "warnings",
            "hard_failures",
        ],
    )
    return summary


def _cap_context(content: str) -> str:
    if len(content) <= _MAX_CONTEXT_CHARS:
        return content
    suffix = "\n\n[TRUNCATED: project cognition context exceeded Hermes hook limit]\n"
    return content[: max(0, _MAX_CONTEXT_CHARS - len(suffix))] + suffix


def _run_pre_hook(project_root: Path) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    attempts = [
        ["--format", "markdown", "--profile-mode", "ultra", "--world-mode", "compact", "--max-chars", str(_MAX_CONTEXT_CHARS)],
        ["--format", "markdown", "--profile-mode", "compact", "--max-chars", str(_MAX_CONTEXT_CHARS)],
        ["--format", "markdown", "--max-chars", str(_MAX_CONTEXT_CHARS)],
    ]
    completed: subprocess.CompletedProcess[str] | None = None
    for args in attempts:
        completed = _run_project_script(project_root, "codex_pre_hook.py", args, _PRE_HOOK_TIMEOUT)
        if completed.returncode == 0 and completed.stdout.strip():
            return completed, args
    assert completed is not None
    return completed, attempts[-1]


def _strip_injected_context(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"(?s)^\s*\[PROJECT_STATE\].*?</PROJECT_STATE>\s*", "", text)
    cleaned = re.sub(
        r"(?s)<!-- PROJECT_COGNITION_USER_PROFILE_BEGIN -->.*?<!-- PROJECT_COGNITION_USER_PROFILE_END -->\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?s)<!-- PROJECT_COGNITION_WORLD_STATE_BEGIN -->.*?<!-- PROJECT_COGNITION_WORLD_STATE_END -->\s*",
        "",
        cleaned,
    )
    return cleaned.strip()


def _save_turn_jsonl(project_root: Path, session_id: str | None, turn_id: str | None, user_message: str, assistant_response: str) -> Path:
    session_key = _safe_id(session_id, "hermes")
    timestamp = _now_iso()
    turn_key = _safe_id(turn_id, f"{timestamp}_{_short_hash(user_message + assistant_response, 8)}")
    turn_dir = project_root / ".project_cognition" / "logs" / "sessions" / "hermes_turns" / session_key
    turn_dir.mkdir(parents=True, exist_ok=True)
    turn_file = turn_dir / f"{turn_key}.jsonl"
    records = [
        {"role": "user", "content": _strip_injected_context(user_message), "timestamp": timestamp},
        {"role": "assistant", "content": assistant_response, "timestamp": timestamp},
    ]
    with turn_file.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return turn_file


def pre_llm_call_hook(session_id: str = None, user_message: str = None, **kwargs):
    """Inject compact project cognition context into the current user turn."""
    if _INJECT_MODE in {"0", "off", "none", "disabled"}:
        return None

    cwd = _resolve_cwd(kwargs)
    project_root, bootstrap_event = _find_or_bootstrap_project_root(cwd, allow_bootstrap=True)
    event: dict[str, Any] = {
        "hook": "pre_llm_call",
        "timestamp": _now_iso(),
        "cwd": str(cwd),
        "project_root": str(project_root) if project_root else "",
        "session_id": session_id or "",
    }
    if bootstrap_event:
        event["bootstrap"] = bootstrap_event

    if not project_root:
        event["status"] = "no_project_cognition" if not bootstrap_event else "bootstrap_failed"
        _log_event(event)
        return None

    try:
        runtime_sync = _ensure_project_runtime(project_root)
        profile_completed = _run_project_script(project_root, "build_user_profile.py", [], _PROFILE_TIMEOUT)
        event["user_profile"] = {
            "runtime_sync": runtime_sync,
            "returncode": profile_completed.returncode,
            "stdout": _truncate_text(profile_completed.stdout, 1000),
            "stderr": _truncate_text(profile_completed.stderr, 1000),
        }
    except Exception as exc:
        event["user_profile"] = {"status": "error", "error": repr(exc)}

    inject_key = f"{_safe_id(session_id)}::{project_root}"
    if _INJECT_MODE in {"once", "first", "session"} and inject_key in _INJECTED_KEYS:
        event["status"] = "already_injected"
        _log_event(event)
        return None

    completed, used_args = _run_pre_hook(project_root)
    event["pre_hook_args"] = used_args
    event["returncode"] = completed.returncode
    event["stderr"] = _truncate_text(completed.stderr, 1000)
    if completed.returncode != 0 or not completed.stdout.strip():
        event["status"] = "error"
        _log_event(event)
        return None

    context = _cap_context(_CONTEXT_MINIMALISM_NOTICE + "\n\n" + completed.stdout.strip())
    _INJECTED_KEYS.add(inject_key)
    event["status"] = "bootstrapped_ok" if bootstrap_event else "ok"
    event["context_chars"] = len(context)
    _log_event(event)
    return {"context": context}


def post_llm_call_hook(
    session_id: str = None,
    turn_id: str = None,
    user_message: str = None,
    assistant_response: str = None,
    agent_response: str = None,
    **kwargs,
):
    """Store the completed turn and run the local per-project post hook."""
    response = assistant_response or agent_response
    if not user_message or not response:
        return None

    cwd = _resolve_cwd(kwargs)
    project_root, bootstrap_event = _find_or_bootstrap_project_root(cwd, allow_bootstrap=True)
    event: dict[str, Any] = {
        "hook": "post_llm_call",
        "timestamp": _now_iso(),
        "cwd": str(cwd),
        "project_root": str(project_root) if project_root else "",
        "session_id": session_id or "",
        "turn_id": turn_id or "",
        "run_post_hook": _RUN_POST_HOOK,
    }
    if bootstrap_event:
        event["bootstrap"] = bootstrap_event

    if not project_root:
        event["status"] = "no_project_cognition" if not bootstrap_event else "bootstrap_failed"
        _log_event(event)
        return None

    turn_file = _save_turn_jsonl(project_root, session_id, turn_id, user_message, response)
    event["turn_file"] = str(turn_file)

    if _RUN_POST_HOOK:
        event["runtime_sync"] = _ensure_project_runtime(project_root)
        args = [
            "--session-jsonl",
            str(turn_file),
            "--session-id",
            f"hermes_{_safe_id(session_id, 'session')}",
            "--source",
            "hermes_hook",
        ]
        completed = _run_project_script(project_root, "codex_post_hook.py", args, _POST_HOOK_TIMEOUT)
        event["returncode"] = completed.returncode
        event["post_hook"] = _summarize_post_hook_stdout(completed.stdout)
        if completed.returncode != 0:
            event["stdout_tail"] = _truncate_text(completed.stdout, 1000)
        event["stderr"] = _truncate_text(completed.stderr, 2000)
        event["status"] = "bootstrapped_ok" if bootstrap_event and completed.returncode == 0 else ("ok" if completed.returncode == 0 else "error")
    else:
        event["status"] = "captured_only"

    try:
        profile_completed = _run_project_script(project_root, "build_user_profile.py", [], _PROFILE_TIMEOUT)
        event["user_profile"] = {
            "returncode": profile_completed.returncode,
            "stdout": _truncate_text(profile_completed.stdout, 1000),
            "stderr": _truncate_text(profile_completed.stderr, 1000),
        }
    except Exception as exc:
        event["user_profile"] = {"status": "error", "error": repr(exc)}

    _log_event(event)
    return None


def register(ctx):
    ctx.register_hook("pre_llm_call", pre_llm_call_hook)
    ctx.register_hook("post_llm_call", post_llm_call_hook)
    logger.info(
        "Project Cognition plugin loaded: per-project compact mode, "
        "max_context=%s, inject_mode=%s, run_post_hook=%s, pre_timeout=%s, post_timeout=%s, bootstrap_script=%s",
        _MAX_CONTEXT_CHARS,
        _INJECT_MODE,
        _RUN_POST_HOOK,
        _PRE_HOOK_TIMEOUT,
        _POST_HOOK_TIMEOUT,
        _BOOTSTRAP_SCRIPT,
    )
