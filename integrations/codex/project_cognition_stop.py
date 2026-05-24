#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from project_cognition_common import (
    emit_empty,
    ensure_project_script,
    find_or_bootstrap_project_root,
    hook_value,
    log_event,
    now_iso,
    read_hook_input,
    resolve_cwd,
    run_project_script,
)


def main() -> int:
    payload = read_hook_input()
    cwd = resolve_cwd(payload)
    project_root, bootstrap_event = find_or_bootstrap_project_root(cwd, allow_bootstrap=True)
    transcript_path = hook_value(payload, "transcript_path")
    session_id = hook_value(payload, "session_id", "turn_id") or f"codex_stop_{now_iso().replace(':', '').replace('-', '')}"
    event = {
        "hook": "Stop",
        "timestamp": now_iso(),
        "cwd": str(cwd),
        "project_root": str(project_root) if project_root else "",
        "transcript_path": transcript_path,
        "session_id": session_id,
    }
    if bootstrap_event:
        event["bootstrap"] = bootstrap_event

    if not project_root:
        event["status"] = "no_project_cognition" if not bootstrap_event else "bootstrap_failed"
        log_event(event)
        emit_empty()
        return 0

    args = ["--session-id", session_id]
    if transcript_path and Path(transcript_path).exists():
        args.extend(["--session-jsonl", transcript_path])
    else:
        args.append("--skip-ingest")

    try:
        completed = run_project_script(project_root, "codex_post_hook.py", args, 45)
        event["returncode"] = completed.returncode
        event["stdout"] = completed.stdout[-4000:]
        event["stderr"] = completed.stderr[-4000:]
        event["status"] = "bootstrapped_ok" if bootstrap_event and completed.returncode == 0 else ("ok" if completed.returncode == 0 else "error")
    except Exception as exc:
        event["status"] = "exception"
        event["error"] = repr(exc)

    try:
        copied = ensure_project_script(project_root, "build_user_profile.py")
        profile_completed = run_project_script(project_root, "build_user_profile.py", [], 15)
        event["user_profile"] = {
            "runtime_copied": copied,
            "returncode": profile_completed.returncode,
            "stdout": profile_completed.stdout[-2000:],
            "stderr": profile_completed.stderr[-2000:],
        }
    except Exception as exc:
        event["user_profile"] = {"status": "error", "error": repr(exc)}

    log_event(event)
    emit_empty()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

