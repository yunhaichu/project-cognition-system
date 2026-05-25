#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import COGNITION_ROOT, append_jsonl, now_iso


SCRIPT_DIR = Path(__file__).resolve().parent


def run_step(name: str, args: list[str]) -> dict[str, Any]:
    command = [sys.executable, str(SCRIPT_DIR / name), *args]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(command, cwd=COGNITION_ROOT.parent, env=env, text=True, capture_output=True, check=False)
    output = completed.stdout.strip()
    parsed: Any = None
    if output:
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            parsed = output
    return {
        "script": name,
        "argv": args,
        "returncode": completed.returncode,
        "stdout": parsed,
        "stderr": completed.stderr.strip(),
    }


def require_success(step: dict[str, Any]) -> None:
    if step["returncode"] != 0:
        print(json.dumps(step, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(step["returncode"])


def run_post_hook(session_jsonl: str | None, session_id: str, source: str, skip_ingest: bool, allow_llm: bool) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    if allow_llm:
        raise SystemExit(
            "LLM-assisted cognition distillation is intentionally disabled in this MVP. "
            "Use local rule scripts by default; add an explicit reviewed implementation before enabling model calls."
        )
    if session_jsonl and not skip_ingest:
        steps.append(run_step("ingest_session.py", ["--input", session_jsonl, "--session-id", session_id, "--source", source]))
        require_success(steps[-1])

    for script_name in [
        "update_scoring_weights.py",
        "extract_candidates.py",
        "score_candidates.py",
        "detect_conflicts.py",
        "cluster_conflicts.py",
        "build_world_state.py",
        "build_user_profile.py",
        "index_segments.py",
        "drift_report.py",
    ]:
        steps.append(run_step(script_name, []))
        require_success(steps[-1])

    summary = {
        "hook": "codex_post",
        "timestamp": now_iso(),
        "session_id": session_id,
        "session_jsonl": session_jsonl,
        "ingested": bool(session_jsonl and not skip_ingest),
        "local_only": True,
        "steps": steps,
    }
    append_jsonl(COGNITION_ROOT / "logs" / "sessions" / "codex_hook_runs.jsonl", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Codex post-conversation hook: ingest session material, score cognition, detect conflicts, and rebuild WORLD_STATE.md."
    )
    parser.add_argument(
        "--session-jsonl",
        default=os.environ.get("PROJECT_COGNITION_SESSION_JSONL"),
        help="Simple session JSONL to ingest. Also read from PROJECT_COGNITION_SESSION_JSONL.",
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("CODEX_SESSION_ID") or f"codex_{now_iso().replace(':', '').replace('-', '')}",
        help="Session id. Default uses CODEX_SESSION_ID or a timestamp.",
    )
    parser.add_argument("--source", default="codex_hook", help="Source label for ingested user utterances. Default: codex_hook.")
    parser.add_argument("--skip-ingest", action="store_true", help="Run extract/score/conflict/build without importing a session file.")
    parser.add_argument(
        "--allow-llm",
        action="store_true",
        help="Reserved. Currently rejected to prevent hidden token spend in post-hook cognition updates.",
    )
    args = parser.parse_args()

    if args.session_jsonl and not Path(args.session_jsonl).exists():
        raise SystemExit(f"Session JSONL not found: {args.session_jsonl}")

    summary = run_post_hook(args.session_jsonl, args.session_id, args.source, args.skip_ingest, args.allow_llm)
    step_by_script = {step["script"]: step for step in summary["steps"]}
    compact = {
        "hook": summary["hook"],
        "timestamp": summary["timestamp"],
        "session_id": summary["session_id"],
        "ingested": summary["ingested"],
        "local_only": summary["local_only"],
        "step_count": len(summary["steps"]),
        "step_scripts": [step["script"] for step in summary["steps"]],
        "world_state": step_by_script.get("build_world_state.py", {}).get("stdout"),
        "user_profile": step_by_script.get("build_user_profile.py", {}).get("stdout"),
        "conflicts": step_by_script.get("detect_conflicts.py", {}).get("stdout"),
        "conflict_clusters": step_by_script.get("cluster_conflicts.py", {}).get("stdout"),
        "evidence_index": step_by_script.get("index_segments.py", {}).get("stdout"),
        "drift": step_by_script.get("drift_report.py", {}).get("stdout"),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
