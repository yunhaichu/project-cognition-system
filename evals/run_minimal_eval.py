#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = REPO_ROOT / "evals" / "cases" / "minimal_governance_session.jsonl"
DOGFOOD_FILE = REPO_ROOT / "evals" / "cases" / "dogfood_self_update.jsonl"
LONG_DOGFOOD_FILE = REPO_ROOT / "evals" / "cases" / "dogfood_long_development.jsonl"
GOLDEN_FILE = REPO_ROOT / "evals" / "golden" / "minimal_invariants.json"
PREDICATE_FIXTURES_FILE = REPO_ROOT / "evals" / "golden" / "predicate_fixtures.json"
OBJECT_FIXTURES_FILE = REPO_ROOT / "evals" / "golden" / "object_fixtures.json"
MULTI_TRANSCRIPT_FILES = [
    REPO_ROOT / "evals" / "cases" / "multi_transcript" / "session1_establish_rule.jsonl",
    REPO_ROOT / "evals" / "cases" / "multi_transcript" / "session2_conflicting_rule.jsonl",
    REPO_ROOT / "evals" / "cases" / "multi_transcript" / "session3_deferred_conflict_a.jsonl",
    REPO_ROOT / "evals" / "cases" / "multi_transcript" / "session4_deferred_conflict_b.jsonl",
]
sys.path.insert(0, str(REPO_ROOT / ".project_cognition" / "scripts"))
from common import canonical_object, normalize_predicate  # noqa: E402
PREDICATES = {
    "states",
    "requires",
    "observed",
    "infers",
    "enter_core_memory",
    "store_log",
    "create",
    "render",
    "override",
    "require_review",
    "inject_context",
    "call_llm",
    "read_source",
    "update_world_state",
    "score_evidence",
    "resolve_conflict",
    "test_passed",
}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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


def make_project_copy(temp_dir: str) -> Path:
    project_root = Path(temp_dir) / "project"
    shutil.copytree(
        REPO_ROOT / ".project_cognition",
        project_root / ".project_cognition",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    reset_state(project_root)
    return project_root


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


def run_script_status(project_root: Path, script_name: str, args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(project_root / ".project_cognition" / "scripts" / script_name), *(args or [])]
    return subprocess.run(command, cwd=project_root, text=True, capture_output=True, check=False)


def item(
    item_id: str,
    *,
    claim: str,
    source_type: str,
    modality: str,
    scope: str,
    subject: str,
    predicate: str,
    object_value: str,
    confidence: int = 95,
    category: str = "constraint",
    status: str = "accepted",
) -> dict[str, Any]:
    return {
        "id": item_id,
        "claim": claim,
        "category": category,
        "confidence": confidence,
        "evidence": [f"ev_{item_id}"],
        "conflicts": [],
        "last_verified": "2026-05-24T00:00:00Z",
        "stability": "stable",
        "include_in_world_state": confidence >= 90,
        "source_type": source_type,
        "status": status,
        "topics": [],
        "structured": {
            "subject": subject,
            "predicate": predicate,
            "object": object_value,
            "object_key": canonical_object(object_value),
            "scope": scope,
            "modality": modality,
            "valid_from": "2026-05-24T00:00:00Z",
            "valid_until": None,
            "source_refs": [f"ev_{item_id}"],
            "confidence_reason": "Eval fixture.",
            "supersedes": [],
        },
    }


def set_items(project_root: Path, items: list[dict[str, Any]]) -> None:
    write_json(project_root / ".project_cognition" / "distilled" / "confidence_table.json", {"items": items})
    write_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl", [])


def run_minimal_pipeline(project_root: Path) -> dict[str, Any]:
    return {
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


def run_cognition_pipeline(project_root: Path) -> dict[str, Any]:
    return {
        "extract": run_script(project_root, "extract_candidates.py"),
        "score": run_script(project_root, "score_candidates.py"),
        "conflicts": run_script(project_root, "detect_conflicts.py"),
        "world_state": run_script(project_root, "build_world_state.py"),
    }


def proposal_review(project_root: Path, claim: str, evidence: list[str]) -> dict[str, Any]:
    proposal = run_script(
        project_root,
        "propose_update.py",
        [
            "--claim",
            claim,
            "--category",
            "constraint",
            "--confidence",
            "98",
            "--reason",
            "E2E multi-transcript review fixture.",
            "--suggested-action",
            "accept",
            "--should-update-world-state",
            "yes",
            "--subject",
            "assistant_output",
            "--predicate",
            "enter_core_memory",
            "--object",
            "assistant final output",
            "--scope",
            "project",
            "--modality",
            "must_not",
            *sum([["--evidence", item] for item in evidence], []),
        ],
    )
    return run_script(
        project_root,
        "review_update.py",
        ["--proposal-id", proposal["id"], "--action", "accept", "--note", "Accepted by E2E multi-transcript eval."],
    )


def find_item(items: list[dict[str, Any]], *needles: str) -> dict[str, Any]:
    lowered_needles = [needle.lower() for needle in needles]
    for item in items:
        haystack = json.dumps(item, ensure_ascii=False).lower()
        if all(needle in haystack for needle in lowered_needles):
            return item
    raise AssertionError(f"Item not found for needles: {needles}")


def find_conflict(conflicts: list[dict[str, Any]], *item_ids: str) -> dict[str, Any]:
    wanted = set(item_ids)
    for conflict in conflicts:
        if {conflict.get("item_a"), conflict.get("item_b")} == wanted:
            return conflict
    raise AssertionError(f"Conflict not found for items: {item_ids}")


def check_minimal_pipeline(project_root: Path, steps: dict[str, Any]) -> dict[str, bool]:
    cognition_root = project_root / ".project_cognition"
    table = read_json(cognition_root / "distilled" / "confidence_table.json")
    items = table.get("items", [])
    tool_evidence = read_jsonl(cognition_root / "raw" / "tool_evidence.jsonl")
    assistant_outputs = read_jsonl(cognition_root / "logs" / "outputs" / "eval_minimal.jsonl")
    compact_chars = len((cognition_root / "WORLD_STATE_COMPACT.md").read_text(encoding="utf-8"))
    tool_items = [row for row in items if row.get("source_type") == "tool_evidence"]
    return {
        "user_utterance_ingested": steps["ingest"]["counts"]["user"] == 1,
        "assistant_output_is_log": len(assistant_outputs) == 1,
        "tool_evidence_ingested": len(tool_evidence) == 1 and tool_evidence[0].get("evidence_kind") == "test_result",
        "tool_evidence_scored_explicitly": bool(tool_items)
        and all("tool_evidence" in row.get("score_signals", []) for row in tool_items),
        "predicate_normalized": bool(items)
        and all(row.get("structured", {}).get("predicate") in PREDICATES for row in items)
        and any(row.get("structured", {}).get("predicate") != "states" for row in items),
        "predicate_fixtures_pass": all(
            normalize_predicate(None, row["text"]) == row["expected"] for row in read_json(PREDICATE_FIXTURES_FILE)
        ),
        "object_fixtures_pass": all(
            canonical_object(row["text"]) == row["expected"] for row in read_json(OBJECT_FIXTURES_FILE)
        ),
        "object_keys_canonicalized": bool(items) and all(row.get("structured", {}).get("object_key") for row in items),
        "candidates_have_structured_fields": bool(items) and all("structured" in row for row in items),
        "tool_only_candidate_requires_review_for_world_state": bool(tool_items)
        and all(row.get("requires_review_for_world_state") and not row.get("include_in_world_state") for row in tool_items),
        "compact_state_under_1600_chars": compact_chars <= 1600,
    }


def check_user_overrides_agent(project_root: Path) -> dict[str, bool]:
    user = item(
        "user_rule",
        claim="用户要求 assistant 输出只能进入日志，不能进入核心事实。",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
    )
    agent = item(
        "agent_bad",
        claim="Agent 推断 assistant 输出可以进入核心事实。",
        source_type="agent_interpretation",
        modality="may",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
        confidence=74,
        status="candidate",
    )
    set_items(project_root, [user, agent])
    result = run_script(project_root, "detect_conflicts.py")
    conflicts = read_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl")
    return {
        "conflict_detected": result["new_conflicts"] == 1,
        "user_side_preferred": bool(conflicts) and conflicts[0].get("chosen_side") == "user_rule",
    }


def check_tool_overrides_agent(project_root: Path) -> dict[str, bool]:
    tool = item(
        "tool_failed_tests",
        claim="工具结果显示测试失败。",
        source_type="tool_evidence",
        modality="is_not",
        scope="test",
        subject="test_result",
        predicate="test_passed",
        object_value="pytest suite",
        confidence=89,
        status="candidate",
    )
    agent = item(
        "agent_tests_pass",
        claim="Agent 推断测试已经通过。",
        source_type="agent_interpretation",
        modality="is",
        scope="test",
        subject="test_result",
        predicate="test_passed",
        object_value="pytest suite",
        confidence=74,
        status="candidate",
    )
    set_items(project_root, [tool, agent])
    result = run_script(project_root, "detect_conflicts.py")
    conflicts = read_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl")
    return {
        "conflict_detected": result["new_conflicts"] == 1,
        "tool_side_preferred": bool(conflicts) and conflicts[0].get("chosen_side") == "tool_failed_tests",
    }


def check_scope_separation(project_root: Path) -> dict[str, bool]:
    project_rule = item(
        "project_no_agents",
        claim="项目目录不得创建 AGENTS.md。",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="AGENTS.md",
        predicate="create",
        object_value="AGENTS.md",
    )
    global_rule = item(
        "global_agents",
        claim="用户级全局目录可以保留 AGENTS.md。",
        source_type="user_utterance",
        modality="may",
        scope="user_global",
        subject="AGENTS.md",
        predicate="create",
        object_value="AGENTS.md",
    )
    set_items(project_root, [project_rule, global_rule])
    result = run_script(project_root, "detect_conflicts.py")
    return {"different_scope_not_conflict": result["new_conflicts"] == 0}


def check_resolve_supersedes_loser(project_root: Path) -> dict[str, bool]:
    old_rule = item(
        "old_rule",
        claim="旧规则：可以把 assistant 输出进入核心记忆。",
        source_type="agent_interpretation",
        modality="may",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
        confidence=74,
        status="candidate",
    )
    new_rule = item(
        "new_rule",
        claim="新规则：assistant 输出只能进入日志。",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
    )
    set_items(project_root, [old_rule, new_rule])
    run_script(project_root, "detect_conflicts.py")
    conflicts = read_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl")
    if not conflicts:
        return {"conflict_detected": False, "loser_superseded": False, "winner_kept": False}
    run_script(
        project_root,
        "resolve_conflict.py",
        ["--conflict-id", conflicts[0]["id"], "--action", "choose-b", "--reason", "User rule supersedes older agent inference."],
    )
    run_script(project_root, "build_world_state.py")
    items = {row["id"]: row for row in read_json(project_root / ".project_cognition" / "distilled" / "confidence_table.json").get("items", [])}
    return {
        "conflict_detected": True,
        "loser_superseded": items["old_rule"].get("status") == "superseded" and not items["old_rule"].get("include_in_world_state"),
        "winner_kept": items["new_rule"].get("include_in_world_state")
        and "old_rule" in items["new_rule"].get("structured", {}).get("supersedes", []),
    }


def check_world_state_structured_layer(project_root: Path) -> dict[str, bool]:
    accepted = item(
        "accepted_structured",
        claim="Accepted structured cognition should render into WORLD_STATE.",
        source_type="proposed_update",
        modality="must",
        scope="project",
        subject="world_state",
        predicate="render",
        object_value="accepted structured cognition layer",
    )
    set_items(project_root, [accepted])
    result = run_script(project_root, "build_world_state.py")
    world_state = (project_root / ".project_cognition" / "WORLD_STATE.md").read_text(encoding="utf-8")
    return {
        "structured_count_reported": result.get("structured_count") == 1,
        "structured_layer_rendered": "accepted structured cognition layer" in world_state,
    }


def check_compact_structured_summary(project_root: Path) -> dict[str, bool]:
    accepted = item(
        "compact_rule",
        claim="Compact world state should include only top priority accepted project rules.",
        source_type="proposed_update",
        modality="must",
        scope="project",
        subject="compact_world_state",
        predicate="render",
        object_value="top priority accepted project rules",
        confidence=98,
    )
    low_priority = item(
        "low_priority_rule",
        claim="Low confidence structured cognition should not enter compact state.",
        source_type="proposed_update",
        modality="must",
        scope="project",
        subject="compact_world_state",
        predicate="render",
        object_value="low confidence rule",
        confidence=90,
    )
    out_of_scope = item(
        "global_rule",
        claim="Global user profile rule should not enter project compact state.",
        source_type="proposed_update",
        modality="must",
        scope="user_global",
        subject="compact_world_state",
        predicate="render",
        object_value="global profile rule",
        confidence=98,
    )
    set_items(project_root, [accepted, low_priority, out_of_scope])
    result = run_script(project_root, "build_world_state.py")
    compact = (project_root / ".project_cognition" / "WORLD_STATE_COMPACT.md").read_text(encoding="utf-8")
    return {
        "compact_structured_count_reported": result.get("compact_structured_count") == 1,
        "compact_structured_rendered": "top priority accepted project rules" in compact
        and "low confidence rule" not in compact
        and "global profile rule" not in compact,
        "compact_stays_small": len(compact) <= 1600,
    }


def check_negative_compact_filters(project_root: Path) -> dict[str, bool]:
    low_confidence = item(
        "low_confidence_accepted",
        claim="Low confidence accepted cognition must not enter compact.",
        source_type="proposed_update",
        modality="must",
        scope="project",
        subject="compact_world_state",
        predicate="render",
        object_value="low confidence accepted cognition",
        confidence=94,
    )
    user_global = item(
        "user_global_accepted",
        claim="Global user profile cognition must not enter project compact.",
        source_type="proposed_update",
        modality="must",
        scope="user_global",
        subject="compact_world_state",
        predicate="render",
        object_value="global user profile cognition",
        confidence=99,
    )
    set_items(project_root, [low_confidence, user_global])
    run_script(project_root, "build_world_state.py")
    compact = (project_root / ".project_cognition" / "WORLD_STATE_COMPACT.md").read_text(encoding="utf-8")
    return {
        "low_confidence_accepted_excluded": "low confidence accepted cognition" not in compact,
        "user_global_excluded": "global user profile cognition" not in compact,
    }


def check_negative_memory_filters(project_root: Path) -> dict[str, bool]:
    assistant_only = item(
        "assistant_only",
        claim="Assistant says its final answer should become core memory.",
        source_type="agent_interpretation",
        modality="must",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final answer",
        confidence=74,
        status="candidate",
    )
    user_rule = item(
        "user_rule",
        claim="User says web search output cannot override user utterances.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="web_result",
        predicate="override",
        object_value="user utterance",
        confidence=95,
    )
    web_result = item(
        "web_result",
        claim="A web result says memory can override user utterances.",
        source_type="tool_evidence",
        modality="may",
        scope="project",
        subject="web_result",
        predicate="override",
        object_value="user utterance",
        confidence=89,
        status="candidate",
    )
    set_items(project_root, [assistant_only, user_rule, web_result])
    run_script(project_root, "detect_conflicts.py")
    rows = {row["id"]: row for row in read_json(project_root / ".project_cognition" / "distilled" / "confidence_table.json").get("items", [])}
    conflicts = read_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl")
    return {
        "assistant_only_not_core": not rows["assistant_only"].get("include_in_world_state"),
        "web_result_does_not_override_user": bool(conflicts)
        and conflicts[0].get("chosen_side") == "user_rule"
        and not rows["web_result"].get("include_in_world_state"),
    }


def check_deferred_conflict_blocks(project_root: Path) -> dict[str, bool]:
    a = item(
        "rule_a",
        claim="Rule A says assistant output must not enter core memory.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
    )
    b = item(
        "rule_b",
        claim="Rule B says assistant output may enter core memory.",
        source_type="user_utterance",
        modality="may",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant output",
    )
    set_items(project_root, [a, b])
    run_script(project_root, "detect_conflicts.py")
    conflict = read_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl")[0]
    run_script(project_root, "resolve_conflict.py", ["--conflict-id", conflict["id"], "--action", "defer", "--reason", "Eval defer."])
    run_script(project_root, "score_candidates.py")
    rows = {row["id"]: row for row in read_json(project_root / ".project_cognition" / "distilled" / "confidence_table.json").get("items", [])}
    return {
        "deferred_conflict_blocks_both_sides": not rows["rule_a"].get("include_in_world_state")
        and not rows["rule_b"].get("include_in_world_state")
    }


def check_object_key_conflict(project_root: Path) -> dict[str, bool]:
    a = item(
        "assistant_final_output_no_core",
        claim="Final assistant answer must not enter core facts.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final answer",
    )
    b = item(
        "assistant_output_core",
        claim="Agent output may enter core memory.",
        source_type="agent_interpretation",
        modality="may",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="agent output",
        confidence=74,
        status="candidate",
    )
    set_items(project_root, [a, b])
    result = run_script(project_root, "detect_conflicts.py")
    return {"equivalent_objects_conflict": result["new_conflicts"] == 1}


def check_resolve_audit_summary(project_root: Path) -> dict[str, bool]:
    winner = item(
        "audit_winner",
        claim="Assistant output must not enter core memory.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
    )
    loser = item(
        "audit_loser",
        claim="Agent output may enter core memory.",
        source_type="agent_interpretation",
        modality="may",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="agent output",
        confidence=74,
        status="candidate",
    )
    set_items(project_root, [winner, loser])
    run_script(project_root, "detect_conflicts.py")
    conflict = read_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl")[0]
    reviewed = run_script(
        project_root,
        "resolve_conflict.py",
        ["--conflict-id", conflict["id"], "--action", "choose-a", "--reason", "Audit summary eval."],
    )
    audit = reviewed.get("audit_summary", {})
    blocked = audit.get("blocked_status", {})
    return {
        "audit_chosen_loser_present": audit.get("chosen") == "audit_winner" and audit.get("loser") == "audit_loser",
        "audit_supersedes_present": "audit_loser" in audit.get("supersedes", []),
        "audit_blocked_status_present": blocked.get("audit_loser", {}).get("status") == "superseded"
        and blocked.get("audit_loser", {}).get("include_in_world_state") is False,
    }


def check_multi_session_evolution(project_root: Path) -> dict[str, bool]:
    current_rule = item(
        "session1_current_rule",
        claim="Session 1: assistant output must not enter core memory.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
        confidence=98,
    )
    stale_rule = item(
        "session2_stale_rule",
        claim="Session 2: agent output may enter core memory.",
        source_type="agent_interpretation",
        modality="may",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="agent output",
        confidence=74,
        status="candidate",
    )
    set_items(project_root, [current_rule, stale_rule])
    run_script(project_root, "detect_conflicts.py")
    conflict = read_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl")[0]
    run_script(
        project_root,
        "resolve_conflict.py",
        ["--conflict-id", conflict["id"], "--action", "choose-a", "--reason", "Multi-session user rule wins."],
    )

    deferred_a = item(
        "session3_deferred_a",
        claim="Session 3: WORLD_STATE must be updated automatically.",
        source_type="user_utterance",
        modality="must",
        scope="project",
        subject="world_state",
        predicate="update_world_state",
        object_value="world state",
        confidence=96,
    )
    deferred_b = item(
        "session3_deferred_b",
        claim="Session 3: WORLD_STATE must not be updated automatically.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="world_state",
        predicate="update_world_state",
        object_value="WORLD_STATE.md",
        confidence=96,
    )
    existing = read_json(project_root / ".project_cognition" / "distilled" / "confidence_table.json").get("items", [])
    set_items(project_root, [*existing, deferred_a, deferred_b])
    run_script(project_root, "detect_conflicts.py")
    conflicts = read_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl")
    deferred_conflict = next(row for row in conflicts if {row["item_a"], row["item_b"]} == {"session3_deferred_a", "session3_deferred_b"})
    run_script(project_root, "resolve_conflict.py", ["--conflict-id", deferred_conflict["id"], "--action", "defer", "--reason", "Keep blocked."])
    result = run_script(project_root, "build_world_state.py")
    rows = {row["id"]: row for row in read_json(project_root / ".project_cognition" / "distilled" / "confidence_table.json").get("items", [])}
    compact = (project_root / ".project_cognition" / "WORLD_STATE_COMPACT.md").read_text(encoding="utf-8")
    return {
        "old_rule_not_revived": rows["session2_stale_rule"].get("status") == "superseded"
        and not rows["session2_stale_rule"].get("include_in_world_state"),
        "deferred_not_leak": not rows["session3_deferred_a"].get("include_in_world_state")
        and not rows["session3_deferred_b"].get("include_in_world_state"),
        "compact_uses_current_rule": result.get("compact_structured_count", 0) >= 1
        and "assistant final output" in compact.lower()
        and "WORLD_STATE must be updated automatically" not in compact,
    }


def check_e2e_multi_transcript(project_root: Path) -> dict[str, bool]:
    for index, transcript in enumerate(MULTI_TRANSCRIPT_FILES, 1):
        run_script(
            project_root,
            "ingest_session.py",
            ["--input", str(transcript), "--session-id", f"e2e_multi_{index}", "--source", "eval_multi_transcript"],
        )
        run_cognition_pipeline(project_root)
        if index == 1:
            items = read_json(project_root / ".project_cognition" / "distilled" / "confidence_table.json").get("items", [])
            source_item = find_item(items, "assistant final output", "core memory")
            proposal_review(
                project_root,
                "Assistant final output must not enter core memory.",
                list(source_item.get("evidence", [])),
            )
            run_cognition_pipeline(project_root)

    table_path = project_root / ".project_cognition" / "distilled" / "confidence_table.json"
    conflicts_path = project_root / ".project_cognition" / "raw" / "conflicts.jsonl"
    items = read_json(table_path).get("items", [])
    accepted_rule = find_item(items, "assistant final output must not enter core memory")
    stale_rule = find_item(items, "临时错误说法", "assistant final output")
    conflicts = read_jsonl(conflicts_path)
    first_conflict = find_conflict(conflicts, accepted_rule["id"], stale_rule["id"])
    choose_action = "choose-a" if first_conflict["item_a"] == accepted_rule["id"] else "choose-b"
    run_script(
        project_root,
        "resolve_conflict.py",
        ["--conflict-id", first_conflict["id"], "--action", choose_action, "--reason", "E2E multi-transcript accepted rule wins."],
    )

    items = read_json(table_path).get("items", [])
    world_state_yes = find_item(items, "待裁决规则 A", "WORLD_STATE")
    world_state_no = find_item(items, "待裁决规则 B", "WORLD_STATE")
    run_cognition_pipeline(project_root)
    conflicts = read_jsonl(conflicts_path)
    deferred_conflict = find_conflict(conflicts, world_state_yes["id"], world_state_no["id"])
    run_script(
        project_root,
        "resolve_conflict.py",
        ["--conflict-id", deferred_conflict["id"], "--action", "defer", "--reason", "E2E multi-transcript keeps unresolved world-state update conflict blocked."],
    )
    final_result = run_script(project_root, "build_world_state.py")
    final_items = {row["id"]: row for row in read_json(table_path).get("items", [])}
    compact = (project_root / ".project_cognition" / "WORLD_STATE_COMPACT.md").read_text(encoding="utf-8")
    assistant_outputs = [
        row
        for output_file in (project_root / ".project_cognition" / "logs" / "outputs").glob("e2e_multi_*.jsonl")
        for row in read_jsonl(output_file)
    ]
    return {
        "e2e_transcripts_ingested": len(read_jsonl(project_root / ".project_cognition" / "raw" / "user_utterances.jsonl")) >= 4,
        "e2e_reviewed_rule_enters_compact": final_result.get("compact_structured_count", 0) >= 1
        and "assistant final output" in compact.lower(),
        "e2e_stale_rule_superseded": final_items[stale_rule["id"]].get("status") == "superseded"
        and not final_items[stale_rule["id"]].get("include_in_world_state"),
        "e2e_deferred_conflict_blocked": not final_items[world_state_yes["id"]].get("include_in_world_state")
        and not final_items[world_state_no["id"]].get("include_in_world_state"),
        "e2e_assistant_outputs_logged_only": len(assistant_outputs) == 4,
    }


def check_cross_reference_validation(project_root: Path) -> dict[str, bool]:
    cognition_root = project_root / ".project_cognition"
    utterance = {
        "id": "utt_valid",
        "session_id": "ref_session",
        "timestamp": "2026-05-24T17:00:00Z",
        "text": "User evidence anchors the reviewed rule.",
        "source": "eval",
        "importance_score": 90,
        "signals": {
            "long_form": False,
            "repeated": False,
            "explicit_preference": True,
            "explicit_rejection": False,
            "strong_emphasis": False,
        },
        "linked_topics": ["validation"],
        "notes": "",
    }
    interpretation = {
        "id": "interp_valid",
        "session_id": "ref_session",
        "timestamp": "2026-05-24T17:01:00Z",
        "based_on_utterance_ids": ["utt_valid"],
        "agent_understanding": "The user wants references to remain auditable.",
        "inferred_goals": [],
        "inferred_constraints": [],
        "risks": [],
        "confidence": 70,
        "possible_misreadings": [],
        "status": "candidate",
    }
    tool_log = {
        "id": "tool_valid",
        "session_id": "ref_session",
        "timestamp": "2026-05-24T17:02:00Z",
        "name": "pytest",
        "content": "1 passed",
    }
    tool_evidence = {
        "id": "tool_ev_valid",
        "session_id": "ref_session",
        "timestamp": "2026-05-24T17:02:00Z",
        "tool_name": "pytest",
        "source_log_id": "tool_valid",
        "source": "tool",
        "evidence_kind": "test_result",
        "deterministic": True,
        "outcome": "passed",
        "content_summary": "1 passed",
        "linked_topics": ["validation"],
        "notes": "",
    }
    item_a = item(
        "cog_valid_a",
        claim="Validated cognition references user and tool evidence.",
        source_type="user_utterance",
        modality="must",
        scope="project",
        subject="validator",
        predicate="requires",
        object_value="cross references",
    )
    item_a["evidence"] = ["utt_valid", "tool_ev_valid"]
    item_a["structured"]["source_refs"] = ["utt_valid", "tool_ev_valid"]
    item_a["structured"]["supersedes"] = ["cog_valid_b"]
    item_b = item(
        "cog_valid_b",
        claim="Older cognition is superseded by validated cognition.",
        source_type="agent_interpretation",
        modality="should",
        scope="project",
        subject="validator",
        predicate="requires",
        object_value="cross references",
        status="superseded",
        confidence=65,
    )
    item_b["evidence"] = ["interp_valid"]
    item_b["structured"]["source_refs"] = ["interp_valid"]
    item_b["include_in_world_state"] = False
    item_b["superseded_by"] = "cog_valid_a"
    conflict = {
        "id": "conflict_valid",
        "timestamp": "2026-05-24T17:03:00Z",
        "type": "user_vs_agent",
        "item_a": "cog_valid_a",
        "item_b": "cog_valid_b",
        "description": "Reference validation fixture conflict.",
        "severity": 80,
        "resolution": "resolved",
        "chosen_side": "cog_valid_a",
        "reason": "Fixture chooses user-backed item.",
        "resolved_at": "2026-05-24T17:04:00Z",
        "audit_summary": {
            "action": "choose-a",
            "chosen": "cog_valid_a",
            "loser": "cog_valid_b",
            "supersedes": ["cog_valid_b"],
            "blocked_status": {},
        },
    }
    proposal = {
        "id": "prop_valid",
        "timestamp": "2026-05-24T17:05:00Z",
        "claim": "Cross-reference validation should keep evidence auditable.",
        "category": "constraint",
        "evidence": ["utt_valid", "tool_ev_valid"],
        "confidence": 95,
        "reason": "Fixture proposal.",
        "conflicts": ["conflict_valid"],
        "suggested_action": "accept",
        "should_update_world_state": True,
        "status": "pending",
        "structured": {
            "subject": "validator",
            "predicate": "requires",
            "object": "cross references",
            "object_key": "cross_references",
            "scope": "project",
            "modality": "must",
            "valid_from": "2026-05-24T17:05:00Z",
            "valid_until": None,
            "source_refs": ["utt_valid", "tool_ev_valid"],
            "confidence_reason": "Fixture proposal.",
            "supersedes": ["cog_valid_b"],
        },
    }

    write_jsonl(cognition_root / "raw" / "user_utterances.jsonl", [utterance])
    write_jsonl(cognition_root / "raw" / "agent_interpretations.jsonl", [interpretation])
    write_jsonl(cognition_root / "logs" / "tool_calls" / "ref_session.jsonl", [tool_log])
    write_jsonl(cognition_root / "raw" / "tool_evidence.jsonl", [tool_evidence])
    write_json(cognition_root / "distilled" / "confidence_table.json", {"items": [item_a, item_b]})
    write_jsonl(cognition_root / "raw" / "conflicts.jsonl", [conflict])
    write_jsonl(cognition_root / "proposals" / "proposed_updates.jsonl", [proposal])

    valid_result = run_script(project_root, "validate_state.py")

    broken_conflict = dict(conflict)
    broken_conflict["item_b"] = "cog_missing"
    write_jsonl(cognition_root / "raw" / "conflicts.jsonl", [broken_conflict])
    dangling_conflict = run_script_status(project_root, "validate_state.py")

    write_jsonl(cognition_root / "raw" / "conflicts.jsonl", [conflict])
    broken_proposal = dict(proposal)
    broken_proposal["evidence"] = ["tool_ev_missing"]
    broken_proposal["structured"] = dict(proposal["structured"])
    broken_proposal["structured"]["source_refs"] = ["tool_ev_missing"]
    write_jsonl(cognition_root / "proposals" / "proposed_updates.jsonl", [broken_proposal])
    dangling_evidence = run_script_status(project_root, "validate_state.py")

    return {
        "valid_references_pass": bool(valid_result.get("ok")),
        "dangling_conflict_detected": dangling_conflict.returncode != 0 and "cog_missing" in dangling_conflict.stdout,
        "dangling_evidence_detected": dangling_evidence.returncode != 0 and "tool_ev_missing" in dangling_evidence.stdout,
    }


def check_dogfood_self_update(project_root: Path) -> dict[str, bool]:
    steps = {
        "ingest": run_script(
            project_root,
            "ingest_session.py",
            ["--input", str(DOGFOOD_FILE), "--session-id", "dogfood_self_update", "--source", "eval"],
        ),
        "extract": run_script(project_root, "extract_candidates.py"),
        "score": run_script(project_root, "score_candidates.py"),
        "conflicts": run_script(project_root, "detect_conflicts.py"),
        "world_state": run_script(project_root, "build_world_state.py"),
    }
    cognition_root = project_root / ".project_cognition"
    table_text = json.dumps(read_json(cognition_root / "distilled" / "confidence_table.json"), ensure_ascii=False)
    assistant_outputs = read_jsonl(cognition_root / "logs" / "outputs" / "dogfood_self_update.jsonl")
    tool_evidence = read_jsonl(cognition_root / "raw" / "tool_evidence.jsonl")
    return {
        "self_update_terms_extracted": all(term in table_text for term in ["tool evidence scoring", "structured conflict", "eval scenarios"]),
        "assistant_output_still_log": steps["ingest"]["counts"]["assistant"] == 1 and len(assistant_outputs) == 1,
        "tool_git_evidence_ingested": any(row.get("evidence_kind") == "git_result" for row in tool_evidence),
    }


def check_long_dogfood_transcript(project_root: Path) -> dict[str, bool]:
    steps = {
        "ingest": run_script(
            project_root,
            "ingest_session.py",
            ["--input", str(LONG_DOGFOOD_FILE), "--session-id", "long_dogfood", "--source", "eval"],
        ),
        "extract": run_script(project_root, "extract_candidates.py"),
        "score": run_script(project_root, "score_candidates.py"),
        "conflicts": run_script(project_root, "detect_conflicts.py"),
        "world_state": run_script(project_root, "build_world_state.py"),
    }
    cognition_root = project_root / ".project_cognition"
    table_text = json.dumps(read_json(cognition_root / "distilled" / "confidence_table.json"), ensure_ascii=False)
    assistant_outputs = read_jsonl(cognition_root / "logs" / "outputs" / "long_dogfood.jsonl")
    tool_evidence = read_jsonl(cognition_root / "raw" / "tool_evidence.jsonl")
    return {
        "long_dogfood_terms_extracted": all(
            term in table_text for term in ["object fixture", "multi-session regression", "resolve audit summary"]
        ),
        "long_dogfood_assistant_logged": steps["ingest"]["counts"]["assistant"] == len(assistant_outputs) == 2,
        "long_dogfood_tool_evidence": any(row.get("evidence_kind") == "git_result" for row in tool_evidence)
        and any(row.get("evidence_kind") == "test_result" for row in tool_evidence),
    }


def check_transcript_dogfood(project_root: Path, transcript: Path) -> dict[str, bool]:
    steps = {
        "ingest": run_script(
            project_root,
            "ingest_session.py",
            ["--input", str(transcript), "--session-id", "external_dogfood", "--source", "dogfood_transcript"],
        ),
        "extract": run_script(project_root, "extract_candidates.py"),
        "score": run_script(project_root, "score_candidates.py"),
        "conflicts": run_script(project_root, "detect_conflicts.py"),
        "world_state": run_script(project_root, "build_world_state.py"),
    }
    cognition_root = project_root / ".project_cognition"
    assistant_outputs = read_jsonl(cognition_root / "logs" / "outputs" / "external_dogfood.jsonl")
    table = read_json(cognition_root / "distilled" / "confidence_table.json").get("items", [])
    return {
        "transcript_user_ingested": steps["ingest"]["counts"]["user"] > 0,
        "transcript_assistant_output_logged": steps["ingest"]["counts"]["assistant"] == len(assistant_outputs),
        "transcript_candidates_structured": bool(table) and all("structured" in row for row in table),
    }


def check_golden_invariants(result: dict[str, Any]) -> dict[str, bool]:
    golden = read_json(GOLDEN_FILE)
    checks = result["checks"]
    scenarios = result["scenario_checks"]
    required_checks = golden.get("required_checks", [])
    required_scenarios = golden.get("required_scenarios", {})
    compact_chars = int(result["pipeline_steps"]["world_state"].get("compact_characters", 10**9))
    rows: dict[str, bool] = {
        "golden_required_checks_present": all(checks.get(name) is True for name in required_checks),
        "golden_required_scenarios_present": all(
            scenarios.get(scenario, {}).get(name) is True
            for scenario, names in required_scenarios.items()
            for name in names
        ),
        "golden_compact_budget_kept": compact_chars <= int(golden.get("max_compact_chars", 1600)),
    }
    return rows


def run_eval(dogfood_transcript: Path | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pcs_eval_") as temp_dir:
        project_root = make_project_copy(temp_dir)
        steps = run_minimal_pipeline(project_root)
        checks = check_minimal_pipeline(project_root, steps)

    scenario_checks: dict[str, dict[str, bool]] = {}
    for name, check_fn in [
        ("user_overrides_agent", check_user_overrides_agent),
        ("tool_overrides_agent", check_tool_overrides_agent),
        ("scope_separation", check_scope_separation),
        ("resolve_supersedes_loser", check_resolve_supersedes_loser),
        ("world_state_structured_layer", check_world_state_structured_layer),
        ("compact_structured_summary", check_compact_structured_summary),
        ("negative_compact_filters", check_negative_compact_filters),
        ("negative_memory_filters", check_negative_memory_filters),
        ("deferred_conflict_blocks", check_deferred_conflict_blocks),
        ("object_key_conflict", check_object_key_conflict),
        ("resolve_audit_summary", check_resolve_audit_summary),
        ("multi_session_evolution", check_multi_session_evolution),
        ("e2e_multi_transcript", check_e2e_multi_transcript),
        ("cross_reference_validation", check_cross_reference_validation),
        ("dogfood_self_update", check_dogfood_self_update),
        ("long_dogfood_transcript", check_long_dogfood_transcript),
    ]:
        with tempfile.TemporaryDirectory(prefix=f"pcs_eval_{name}_") as temp_dir:
            project_root = make_project_copy(temp_dir)
            scenario_checks[name] = check_fn(project_root)

    if dogfood_transcript:
        with tempfile.TemporaryDirectory(prefix="pcs_eval_transcript_dogfood_") as temp_dir:
            project_root = make_project_copy(temp_dir)
            scenario_checks["external_transcript_dogfood"] = check_transcript_dogfood(project_root, dogfood_transcript)

    result = {
        "case": str(CASE_FILE.relative_to(REPO_ROOT)),
        "golden": str(GOLDEN_FILE.relative_to(REPO_ROOT)),
        "pipeline_steps": steps,
        "checks": checks,
        "scenario_checks": scenario_checks,
    }
    result["golden_checks"] = check_golden_invariants(result)
    all_checks = [*checks.values(), *result["golden_checks"].values()]
    for scenario in scenario_checks.values():
        all_checks.extend(scenario.values())
    result["passed"] = all(all_checks)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Project Cognition governance evals in temporary project copies.")
    parser.add_argument("--dogfood-transcript", help="Optional explicit Codex/Hermes transcript JSONL to dogfood. No history directories are scanned.")
    args = parser.parse_args()
    transcript_arg = Path(args.dogfood_transcript) if args.dogfood_transcript else None
    env_transcript = os.environ.get("PROJECT_COGNITION_DOGFOOD_TRANSCRIPT")
    dogfood_transcript = transcript_arg or (Path(env_transcript) if env_transcript else None)
    if dogfood_transcript:
        dogfood_transcript = dogfood_transcript.expanduser().resolve()
    if dogfood_transcript and not dogfood_transcript.exists():
        raise SystemExit(f"Dogfood transcript not found: {dogfood_transcript}")
    result = run_eval(dogfood_transcript)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
