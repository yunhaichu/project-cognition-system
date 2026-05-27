from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
STATE_DIR = HERMES_HOME / "state" / "project-cognition"
EVENT_LOG = STATE_DIR / "gateway-hook-runs.jsonl"
MAX_LOG_FIELD_CHARS = int(os.environ.get("HERMES_PROJECT_COGNITION_GATEWAY_LOG_FIELD_CHARS", "1000"))
RUN_POST_HOOK = os.environ.get("HERMES_PROJECT_COGNITION_GATEWAY_RUN_POST_HOOK", "0").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
POST_TIMEOUT = int(os.environ.get("HERMES_PROJECT_COGNITION_GATEWAY_POST_TIMEOUT", "90"))

PROJECT_MARKER_FILES = {
    ".project_cognition",
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "README.md",
}
PROJECT_MARKER_SUFFIXES = {".xcodeproj", ".xcworkspace"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _short(value: Any, limit: int = MAX_LOG_FIELD_CHARS) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 32)] + "\n[truncated by gateway hook]"


def _safe_id(value: Any, fallback: str = "hermes_gateway") -> str:
    text = str(value or fallback)
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    return text[:96] or fallback


def _candidate_cwds(context: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    for key in ("cwd", "working_dir", "project_root"):
        value = context.get(key)
        if value:
            candidates.append(Path(str(value)).expanduser())
    for name in ("MESSAGING_CWD", "HERMES_PROJECT_ROOT", "PWD"):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value).expanduser())
    candidates.append(Path.cwd())
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _is_unsafe_project_root(path: Path) -> bool:
    resolved = path.resolve()
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


def _looks_like_project(path: Path) -> bool:
    if _is_unsafe_project_root(path):
        return False
    if not path.is_dir():
        return False
    for marker in PROJECT_MARKER_FILES:
        if (path / marker).exists():
            return True
    try:
        return any(child.suffix in PROJECT_MARKER_SUFFIXES for child in path.iterdir())
    except OSError:
        return False


def _find_project_root(context: dict[str, Any]) -> Path | None:
    for start in _candidate_cwds(context):
        current = start if start.is_dir() else start.parent
        for candidate in [current, *current.parents]:
            if not _is_unsafe_project_root(candidate) and (candidate / ".project_cognition").is_dir():
                return candidate
        for candidate in [current, *current.parents]:
            if _looks_like_project(candidate):
                return candidate
    return None


def _run_project_script(project_root: Path, script_name: str, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    script = project_root / ".project_cognition" / "scripts" / script_name
    if not script.exists():
        raise FileNotFoundError(str(script))
    env = os.environ.copy()
    env.setdefault("PROJECT_COGNITION_AGENT", "hermes")
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(project_root),
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _save_gateway_turn(project_root: Path, context: dict[str, Any]) -> Path:
    session_id = _safe_id(context.get("session_id"), "gateway_session")
    timestamp = _now_iso()
    turn_file = (
        project_root
        / ".project_cognition"
        / "logs"
        / "sessions"
        / "hermes_gateway_turns"
        / session_id
        / f"{timestamp.replace(':', '').replace('-', '')}.jsonl"
    )
    _write_jsonl(
        turn_file,
        [
            {
                "role": "user",
                "content": _short(context.get("message")),
                "timestamp": timestamp,
            },
            {
                "role": "assistant",
                "content": _short(context.get("response")),
                "timestamp": timestamp,
            },
        ],
    )
    return turn_file


def _log(event: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def handle(event_type: str, context: dict[str, Any] | None = None) -> None:
    context = context or {}
    project_root = _find_project_root(context)
    event: dict[str, Any] = {
        "event_type": event_type,
        "timestamp": _now_iso(),
        "session_id": context.get("session_id", ""),
        "project_root": str(project_root) if project_root else "",
        "status": "observed",
        "gateway_post_enabled": RUN_POST_HOOK,
    }

    if context.get("platform"):
        event["platform"] = context.get("platform")

    if not project_root or not (project_root / ".project_cognition").is_dir():
        event["status"] = "no_project_cognition"
        _log(event)
        return

    if event_type == "agent:end" and RUN_POST_HOOK:
        try:
            turn_file = _save_gateway_turn(project_root, context)
            completed = _run_project_script(
                project_root,
                "codex_post_hook.py",
                [
                    "--session-jsonl",
                    str(turn_file),
                    "--session-id",
                    _safe_id(context.get("session_id"), "hermes_gateway"),
                    "--source",
                    "hermes_gateway_hook",
                ],
                POST_TIMEOUT,
            )
            event["status"] = "post_hook_ok" if completed.returncode == 0 else "post_hook_error"
            event["turn_file"] = str(turn_file)
            event["returncode"] = completed.returncode
            event["stdout"] = _short(completed.stdout, 2000)
            event["stderr"] = _short(completed.stderr, 2000)
        except Exception as exc:
            event["status"] = "exception"
            event["error"] = repr(exc)

    _log(event)
