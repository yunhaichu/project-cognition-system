#!/usr/bin/env python3
from __future__ import annotations

from project_cognition_common import (
    emit_additional_context,
    emit_empty,
    ensure_project_script,
    find_or_bootstrap_project_root,
    log_event,
    now_iso,
    read_hook_input,
    resolve_cwd,
    run_project_script,
)


MAX_CONTEXT_CHARS = 1600
CONTEXT_MINIMALISM_NOTICE = (
    "Context Minimal Mode: use current command + global protocol + compact project state. "
    "Do not rely on thread history; read specific original sources only when needed."
)


def run_pre_hook(project_root):
    attempts = [
        ["--format", "markdown", "--profile-mode", "ultra", "--world-mode", "compact", "--max-chars", str(MAX_CONTEXT_CHARS)],
        ["--format", "markdown", "--profile-mode", "compact", "--max-chars", str(MAX_CONTEXT_CHARS)],
        ["--format", "markdown", "--max-chars", str(MAX_CONTEXT_CHARS)],
    ]
    completed = None
    for args in attempts:
        completed = run_project_script(project_root, "codex_pre_hook.py", args, 10)
        if completed.returncode == 0 and completed.stdout.strip():
            return completed, args
    return completed, attempts[-1]


def main() -> int:
    payload = read_hook_input()
    cwd = resolve_cwd(payload)
    project_root, bootstrap_event = find_or_bootstrap_project_root(cwd, allow_bootstrap=True)
    event = {
        "hook": "SessionStart",
        "timestamp": now_iso(),
        "cwd": str(cwd),
        "project_root": str(project_root) if project_root else "",
    }
    if bootstrap_event:
        event["bootstrap"] = bootstrap_event

    if not project_root:
        event["status"] = "no_project_cognition" if not bootstrap_event else "bootstrap_failed"
        log_event(event)
        emit_empty()
        return 0

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

    completed, used_args = run_pre_hook(project_root)
    event["pre_hook_args"] = used_args
    event["returncode"] = completed.returncode
    event["stderr"] = completed.stderr[-2000:]
    if completed.returncode == 0 and completed.stdout.strip():
        context = CONTEXT_MINIMALISM_NOTICE + "\n\n" + completed.stdout.strip()
        if len(context) > MAX_CONTEXT_CHARS:
            suffix = "\n\n[TRUNCATED: project cognition context exceeded hook limit]\n"
            context = context[: max(0, MAX_CONTEXT_CHARS - len(suffix))] + suffix
        emit_additional_context(context)
        event["status"] = "bootstrapped_ok" if bootstrap_event else "ok"
    else:
        emit_additional_context(f"Project Cognition: failed to load WORLD_STATE.md for {project_root}. Check hook log.")
        event["status"] = "error"
    log_event(event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

