#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
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
        cognition_root / "index",
    ]:
        directory.mkdir(parents=True, exist_ok=True)
        for child in directory.glob("*.json*"):
            child.unlink()
    for path in [
        cognition_root / "distilled" / "candidate_clusters.json",
        cognition_root / "distilled" / "conflict_clusters.json",
        cognition_root / "distilled" / "governance_gate.json",
    ]:
        if path.exists():
            path.unlink()
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
        "candidate_clusters": run_script(project_root, "cluster_candidates.py"),
        "conflict_clusters": run_script(project_root, "cluster_conflicts.py"),
        "governance_gate": run_script(project_root, "auto_governance_gate.py"),
        "world_state": run_script(project_root, "build_world_state.py"),
        "unresolved": run_script(project_root, "resolve_conflict.py", ["--list-unresolved"]),
    }


def run_cognition_pipeline(project_root: Path) -> dict[str, Any]:
    return {
        "extract": run_script(project_root, "extract_candidates.py"),
        "score": run_script(project_root, "score_candidates.py"),
        "conflicts": run_script(project_root, "detect_conflicts.py"),
        "candidate_clusters": run_script(project_root, "cluster_candidates.py"),
        "conflict_clusters": run_script(project_root, "cluster_conflicts.py"),
        "governance_gate": run_script(project_root, "auto_governance_gate.py"),
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
        "candidates_without_gate_do_not_enter_world_state": all(
            not row.get("include_in_world_state") for row in items if row.get("status") == "candidate"
        ),
        "tool_only_candidate_requires_governance_gate": bool(tool_items)
        and all(row.get("requires_governance_gate_for_world_state") and not row.get("include_in_world_state") for row in tool_items),
        "governance_gate_created": steps["governance_gate"]["item_count"] == len(items)
        and (cognition_root / "distilled" / "governance_gate.json").exists(),
        "governance_gate_controls_world_state": sorted(steps["world_state"]["included_cognition_ids"])
        == sorted(steps["governance_gate"]["allowed_item_ids"]),
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
    stale_related_ids = {
        item["id"]
        for item in items
        if "临时错误说法" in json.dumps(item, ensure_ascii=False) and item.get("status") != "superseded"
    }
    conflicts = read_jsonl(conflicts_path)
    for conflict in conflicts:
        if conflict.get("resolution") != "unresolved":
            continue
        pair = {conflict.get("item_a"), conflict.get("item_b")}
        if accepted_rule["id"] in pair and pair & stale_related_ids:
            action = "choose-a" if conflict["item_a"] == accepted_rule["id"] else "choose-b"
            run_script(
                project_root,
                "resolve_conflict.py",
                ["--conflict-id", conflict["id"], "--action", action, "--reason", "E2E resolves all stale extracted variants."],
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
        "e2e_governed_rule_enters_compact": final_result.get("compact_structured_count", 0) >= 1
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


def check_evidence_lookup(project_root: Path) -> dict[str, bool]:
    run_script(
        project_root,
        "ingest_session.py",
        ["--input", str(CASE_FILE), "--session-id", "lookup_eval", "--source", "eval"],
    )
    world_before = (project_root / ".project_cognition" / "WORLD_STATE.md").read_text(encoding="utf-8")
    table_before = (project_root / ".project_cognition" / "distilled" / "confidence_table.json").read_text(encoding="utf-8")
    index_result = run_script(project_root, "index_segments.py")
    index_rows = read_jsonl(project_root / ".project_cognition" / "index" / "segments.jsonl")
    utterance = read_jsonl(project_root / ".project_cognition" / "raw" / "user_utterances.jsonl")[0]
    exact = run_script(project_root, "lookup_evidence.py", ["--source-id", utterance["id"], "--limit", "3"])
    query = run_script(project_root, "lookup_evidence.py", ["--query", "assistant 输出 核心事实", "--limit", "3"])
    world_after = (project_root / ".project_cognition" / "WORLD_STATE.md").read_text(encoding="utf-8")
    table_after = (project_root / ".project_cognition" / "distilled" / "confidence_table.json").read_text(encoding="utf-8")
    return {
        "source_id_exact_lookup_pass": exact.get("matches", [{}])[0].get("source_id") == utterance["id"],
        "lookup_returns_source_refs": index_result.get("segment_count", 0) >= 2
        and bool(query.get("matches"))
        and all(row.get("source_id") and row.get("source_type") and row.get("matched_text") for row in query.get("matches", [])),
        "retrieval_does_not_bypass_governance": world_before == world_after and table_before == table_after,
        "retrieval_index_does_not_split_records": bool(index_rows)
        and all(row.get("record_level") is True and row.get("chunked") is False and row.get("segment_index") == 0 for row in index_rows)
        and len({row.get("source_id") for row in index_rows}) == len(index_rows),
        "lookup_preview_not_authoritative": bool(query.get("matches"))
        and all(row.get("matched_text_is_preview") is True and row.get("record_level") is True for row in query.get("matches", [])),
    }


def check_vector_lookup(project_root: Path) -> dict[str, bool]:
    run_script(
        project_root,
        "ingest_session.py",
        ["--input", str(CASE_FILE), "--session-id", "vector_lookup_eval", "--source", "eval"],
    )
    world_before = (project_root / ".project_cognition" / "WORLD_STATE.md").read_text(encoding="utf-8")
    table_before = (project_root / ".project_cognition" / "distilled" / "confidence_table.json").read_text(encoding="utf-8")
    run_script(project_root, "index_segments.py")
    vector_result = run_script(project_root, "build_vector_index.py")
    vector_rows = read_jsonl(project_root / ".project_cognition" / "index" / "vector_records.jsonl")
    utterance = read_jsonl(project_root / ".project_cognition" / "raw" / "user_utterances.jsonl")[0]
    exact = run_script(project_root, "vector_lookup.py", ["--source-id", utterance["id"], "--limit", "3"])
    query = run_script(project_root, "vector_lookup.py", ["--query", "assistant 输出 核心事实", "--limit", "3"])
    world_after = (project_root / ".project_cognition" / "WORLD_STATE.md").read_text(encoding="utf-8")
    table_after = (project_root / ".project_cognition" / "distilled" / "confidence_table.json").read_text(encoding="utf-8")
    return {
        "vector_index_builds": vector_result.get("record_count", 0) >= 2
        and vector_result.get("indexing_mode") == "record_level_no_split",
        "vector_index_does_not_split_records": bool(vector_rows)
        and all(row.get("record_level") is True and row.get("chunked") is False and row.get("segment_index") == 0 for row in vector_rows)
        and len({row.get("source_id") for row in vector_rows}) == len(vector_rows),
        "vector_source_id_exact_lookup_pass": exact.get("matches", [{}])[0].get("source_id") == utterance["id"],
        "vector_lookup_returns_source_refs": bool(query.get("matches"))
        and all(row.get("source_id") and row.get("source_type") and row.get("path") for row in query.get("matches", [])),
        "vector_lookup_does_not_bypass_governance": world_before == world_after and table_before == table_after,
        "vector_preview_not_authoritative": bool(query.get("matches"))
        and all(
            row.get("matched_text_is_preview") is True
            and row.get("matched_text_is_authoritative") is False
            and row.get("record_level") is True
            for row in query.get("matches", [])
        ),
    }


def check_index_cache(project_root: Path) -> dict[str, bool]:
    run_script(
        project_root,
        "ingest_session.py",
        ["--input", str(CASE_FILE), "--session-id", "index_cache_eval", "--source", "eval"],
    )
    first = run_script(project_root, "index_segments.py")
    second = run_script(project_root, "index_segments.py")
    return {
        "first_index_builds": first.get("skipped") is False and first.get("segment_count", 0) >= 2,
        "unchanged_index_skips": second.get("skipped") is True and second.get("skip_reason") == "inputs_unchanged",
        "index_summary_hides_fingerprint": "source_fingerprint" not in second and second.get("source_file_count", 0) >= 2,
    }


def load_codex_common_module() -> Any:
    module_path = REPO_ROOT / "integrations" / "codex" / "project_cognition_common.py"
    spec = importlib.util.spec_from_file_location("eval_project_cognition_common", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_hook_runtime_hygiene(project_root: Path) -> dict[str, bool]:
    common_module = load_codex_common_module()
    common_module.BOOTSTRAP_SCRIPT = REPO_ROOT / ".project_cognition" / "scripts" / "bootstrap_existing_project.py"

    target = project_root.parent / "runtime_target"
    shutil.copytree(project_root / ".project_cognition", target / ".project_cognition")
    for path in (target / ".project_cognition" / "schemas").glob("*.schema.json"):
        path.unlink()
    runtime_sync = common_module.ensure_project_runtime(target)

    noisy_output = json.dumps(
        {
            "hook": "codex_post",
            "session_id": "eval",
            "ingested": False,
            "local_only": True,
            "step_count": 1,
            "step_scripts": ["cluster_conflicts.py"],
            "conflict_clusters": {
                "total_conflicts": 2,
                "cluster_count": 1,
                "clusters": [{"id": "cluster_x", "large": "x" * 5000}],
            },
            "evidence_index": {
                "segment_count": 3,
                "source_types": {"user_utterance": 1, "tool_evidence": 2},
                "source_file_count": 2,
                "source_fingerprint": {"files": [{"path": "raw/user_utterances.jsonl"}]},
                "skipped": True,
                "skip_reason": "inputs_unchanged",
                "local_only": True,
            },
            "drift": {"ok": True, "compact_characters": 300, "hard_failures": []},
        },
        ensure_ascii=False,
    )
    summary = common_module.summarize_post_hook_stdout(noisy_output)
    schema_names = {path.name for path in (target / ".project_cognition" / "schemas").glob("*.schema.json")}
    return {
        "runtime_sync_copies_schemas": "tool_evidence.schema.json" in schema_names
        and bool(runtime_sync.get("copied_schemas")),
        "post_hook_summary_omits_cluster_members": "clusters" not in summary.get("conflict_clusters", {}),
        "post_hook_summary_omits_fingerprint": "source_fingerprint" not in summary.get("evidence_index", {}),
        "post_hook_summary_keeps_metrics": summary.get("evidence_index", {}).get("skipped") is True
        and summary.get("raw_stdout_chars", 0) == len(noisy_output),
    }


def check_legacy_state_migration(project_root: Path) -> dict[str, bool]:
    cognition_root = project_root / ".project_cognition"
    utterance = {
        "id": "utt_migrate_valid",
        "session_id": "legacy_migration",
        "timestamp": "2026-05-25T00:00:00Z",
        "text": "用户原话必须最高权重，Agent 输出不能进入核心记忆，只能进入日志。",
        "source": "eval",
        "importance_score": 95,
        "signals": {
            "long_form": False,
            "repeated": False,
            "explicit_preference": True,
            "explicit_rejection": True,
            "strong_emphasis": True,
        },
        "linked_topics": ["user_utterance", "memory"],
        "notes": "",
    }
    valid = item(
        "cog_migrate_valid",
        claim="用户原话必须最高权重。",
        source_type="user_utterance",
        modality="must",
        scope="project",
        subject="user_utterance",
        predicate="score_evidence",
        object_value="user utterance",
        status="accepted",
        confidence=96,
    )
    valid["evidence"] = ["utt_migrate_valid"]
    valid["structured"]["source_refs"] = ["utt_migrate_valid"]
    legacy_orphan = item(
        "cog_legacy_orphan",
        claim="旧版本错误派生产物：Agent 输出可以进入核心记忆。",
        source_type="agent_interpretation",
        modality="may",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
        status="accepted",
        confidence=95,
    )
    legacy_orphan["evidence"] = ["interp_missing_old"]
    legacy_orphan["structured"]["source_refs"] = ["interp_missing_old"]
    legacy_orphan["include_in_world_state"] = True
    legacy_conflict = {
        "id": "conflict_legacy_orphan",
        "timestamp": "2026-05-25T00:01:00Z",
        "type": "old_vs_new",
        "item_a": "cog_migrate_valid",
        "item_b": "cog_legacy_orphan",
        "description": "Legacy derived conflict should be rebuilt.",
        "severity": 90,
        "resolution": "unresolved",
        "chosen_side": "",
        "reason": "",
    }
    write_jsonl(cognition_root / "raw" / "user_utterances.jsonl", [utterance])
    write_json(cognition_root / "distilled" / "confidence_table.json", {"items": [valid, legacy_orphan]})
    write_jsonl(cognition_root / "raw" / "conflicts.jsonl", [legacy_conflict])
    (cognition_root / "WORLD_STATE.md").write_text("旧版本错误派生产物 should not survive migration.\n", encoding="utf-8")
    (cognition_root / "WORLD_STATE_COMPACT.md").write_text("旧版本错误派生产物\n", encoding="utf-8")

    report = run_script(project_root, "migrate_legacy_state.py")
    repaired = run_script(project_root, "migrate_legacy_state.py", ["--repair"])
    final_table = read_json(cognition_root / "distilled" / "confidence_table.json").get("items", [])
    final_ids = {row.get("id") for row in final_table}
    quarantine = read_json(cognition_root / "distilled" / "legacy_quarantined_candidates.json")
    backup_root = Path(repaired.get("backup", {}).get("backup_root", ""))
    validation = run_script(project_root, "validate_state.py")
    final_world = (cognition_root / "WORLD_STATE.md").read_text(encoding="utf-8")
    return {
        "legacy_report_detects_orphan": report.get("needs_repair") is True and bool(report.get("orphaned_items")),
        "legacy_repair_backs_up_derived": backup_root.exists() and (backup_root / "WORLD_STATE.md").exists(),
        "legacy_repair_quarantines_orphan": "cog_legacy_orphan" in json.dumps(quarantine, ensure_ascii=False),
        "legacy_repair_keeps_raw_evidence": read_jsonl(cognition_root / "raw" / "user_utterances.jsonl")[0].get("id") == "utt_migrate_valid",
        "legacy_orphan_not_core_after_repair": "cog_legacy_orphan" not in final_ids and "旧版本错误派生产物" not in final_world,
        "legacy_repair_validates_state": validation.get("ok") is True,
    }


def check_conflict_cluster_integrity(project_root: Path) -> dict[str, bool]:
    a = item(
        "cluster_user_a",
        claim="Assistant output must not enter core memory.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
    )
    b = item(
        "cluster_agent_b",
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
    c = item(
        "cluster_user_c",
        claim="Assistant final answer must not enter core memory.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final answer",
    )
    d = item(
        "cluster_agent_d",
        claim="Assistant output may enter core facts.",
        source_type="agent_interpretation",
        modality="may",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant output",
        confidence=74,
        status="candidate",
    )
    set_items(project_root, [a, b, c, d])
    conflict_result = run_script(project_root, "detect_conflicts.py")
    cluster_result = run_script(project_root, "cluster_conflicts.py")
    clusters = cluster_result.get("clusters", [])
    return {
        "conflict_cluster_integrity": conflict_result.get("new_conflicts", 0) >= 2
        and cluster_result.get("cluster_count") == 1
        and clusters[0].get("member_count") == conflict_result.get("new_conflicts")
        and len(clusters[0].get("cognition_ids", [])) == 4,
    }


def check_conflict_cluster_review(project_root: Path) -> dict[str, bool]:
    user_rule = item(
        "review_user_rule",
        claim="Assistant output must not enter core memory.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
        confidence=98,
    )
    agent_rule = item(
        "review_agent_rule",
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
    set_items(project_root, [user_rule, agent_rule])
    run_script(project_root, "detect_conflicts.py")
    clusters = run_script(project_root, "cluster_conflicts.py")
    cluster_id = clusters["clusters"][0]["id"]
    listed = run_script(project_root, "review_conflict_cluster.py", ["--list"])
    inspected = run_script(project_root, "review_conflict_cluster.py", ["--cluster-id", cluster_id, "--inspect"])
    applied = run_script(
        project_root,
        "review_conflict_cluster.py",
        ["--cluster-id", cluster_id, "--action", "apply-suggested", "--reason", "Eval applies explicit suggested side."],
    )
    rows = {row["id"]: row for row in read_json(project_root / ".project_cognition" / "distilled" / "confidence_table.json").get("items", [])}
    apply_ok = (
        listed.get("cluster_count") == 1
        and inspected.get("suggested_count") == 1
        and applied.get("reviewed_count") == 1
        and applied.get("skipped_count") == 0
        and rows["review_agent_rule"].get("status") == "superseded"
        and not rows["review_agent_rule"].get("include_in_world_state")
    )

    equal_a = item(
        "review_equal_a",
        claim="WORLD_STATE must be updated automatically.",
        source_type="user_utterance",
        modality="must",
        scope="project",
        subject="world_state",
        predicate="update_world_state",
        object_value="world state",
        confidence=96,
    )
    equal_b = item(
        "review_equal_b",
        claim="WORLD_STATE must not be updated automatically.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="world_state",
        predicate="update_world_state",
        object_value="WORLD_STATE.md",
        confidence=96,
    )
    set_items(project_root, [equal_a, equal_b])
    run_script(project_root, "detect_conflicts.py")
    clusters = run_script(project_root, "cluster_conflicts.py")
    cluster_id = clusters["clusters"][0]["id"]
    skipped = run_script(
        project_root,
        "review_conflict_cluster.py",
        ["--cluster-id", cluster_id, "--action", "apply-suggested", "--reason", "Eval should skip missing suggestions."],
    )
    conflicts_after_skip = read_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl")
    skip_ok = skipped.get("reviewed_count") == 0 and skipped.get("skipped_count") == 1 and conflicts_after_skip[0].get("resolution") == "unresolved"

    deferred = run_script(
        project_root,
        "review_conflict_cluster.py",
        ["--cluster-id", cluster_id, "--action", "defer", "--reason", "Eval defers unresolved cluster."],
    )
    rows = {row["id"]: row for row in read_json(project_root / ".project_cognition" / "distilled" / "confidence_table.json").get("items", [])}
    conflicts_after_defer = read_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl")
    defer_ok = (
        deferred.get("reviewed_count") == 1
        and conflicts_after_defer[0].get("resolution") == "deferred"
        and not rows["review_equal_a"].get("include_in_world_state")
        and not rows["review_equal_b"].get("include_in_world_state")
    )
    return {
        "cluster_review_lists_clusters": listed.get("cluster_count") == 1 and bool(inspected.get("items")),
        "cluster_review_applies_suggested": apply_ok,
        "cluster_review_skips_missing_suggestions": skip_ok,
        "cluster_review_defers_cluster": defer_ok,
    }


def check_candidate_clustering(project_root: Path) -> dict[str, bool]:
    user_anchor = item(
        "cand_user_anchor",
        claim="Assistant final output must not enter core memory.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
        confidence=99,
    )
    user_reworded = item(
        "cand_user_reworded",
        claim="Agent output is not allowed to become a core fact.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="agent output",
        confidence=96,
    )
    agent_duplicate = item(
        "cand_agent_duplicate",
        claim="Assistant answer should not enter core memory.",
        source_type="agent_interpretation",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant answer",
        confidence=74,
        status="candidate",
    )
    global_scope = item(
        "cand_user_global_scope",
        claim="Global user profile may mention assistant output logging.",
        source_type="user_utterance",
        modality="must_not",
        scope="user_global",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
        confidence=95,
    )
    set_items(project_root, [user_anchor, user_reworded, agent_duplicate, global_scope])
    world_before = (project_root / ".project_cognition" / "WORLD_STATE.md").read_text(encoding="utf-8")
    table_before = (project_root / ".project_cognition" / "distilled" / "confidence_table.json").read_text(encoding="utf-8")
    result = run_script(project_root, "cluster_candidates.py")
    world_after = (project_root / ".project_cognition" / "WORLD_STATE.md").read_text(encoding="utf-8")
    table_after = (project_root / ".project_cognition" / "distilled" / "confidence_table.json").read_text(encoding="utf-8")
    clusters = result.get("clusters", [])
    cluster = clusters[0] if clusters else {}
    candidate_ids = set(cluster.get("candidate_ids", []))
    duplicate_ids = set(cluster.get("duplicate_candidate_ids", []))
    return {
        "candidate_cluster_integrity": result.get("cluster_count") == 1
        and cluster.get("member_count") == 3
        and cluster.get("representative_id") == "cand_user_anchor"
        and cluster.get("merge_mode") == "none_no_state_mutation"
        and cluster.get("updates_world_state") is False,
        "same_claim_different_words_clustered": {"cand_user_anchor", "cand_user_reworded", "cand_agent_duplicate"} <= candidate_ids,
        "different_scope_not_merged": "cand_user_global_scope" not in candidate_ids,
        "user_evidence_not_merged_into_agent_only": cluster.get("governance_action") == "prefer_user_anchor_block_weaker_duplicates"
        and "cand_agent_duplicate" in duplicate_ids
        and cluster.get("representative_id") == "cand_user_anchor",
        "candidate_cluster_does_not_update_state": world_before == world_after and table_before == table_after,
    }


def check_auto_governance_gate(project_root: Path) -> dict[str, bool]:
    user_anchor = item(
        "gate_user_anchor",
        claim="Assistant final output must not enter core memory.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
        confidence=99,
        status="candidate",
    )
    user_anchor["evidence_types"] = ["user_utterance"]
    user_anchor["score_signals"] = ["user_explicit_rejection", "user_strong_emphasis"]

    user_duplicate = item(
        "gate_user_duplicate",
        claim="Agent output cannot become a core fact.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="agent output",
        confidence=98,
        status="candidate",
    )
    user_duplicate["evidence_types"] = ["user_utterance"]
    user_duplicate["score_signals"] = ["user_explicit_rejection"]

    agent_duplicate = item(
        "gate_agent_duplicate",
        claim="Assistant answer should not enter core memory.",
        source_type="agent_interpretation",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant answer",
        confidence=74,
        status="candidate",
    )
    agent_duplicate["evidence"] = ["interp_gate_agent"]
    agent_duplicate["structured"]["source_refs"] = ["interp_gate_agent"]
    agent_duplicate["evidence_types"] = ["agent_interpretation"]
    agent_duplicate["score_signals"] = ["agent_interpretation"]

    low_confidence = item(
        "gate_low_confidence",
        claim="Low confidence candidate must stay out.",
        source_type="user_utterance",
        modality="must",
        scope="project",
        subject="world_state",
        predicate="render",
        object_value="low confidence rule",
        confidence=80,
        status="candidate",
    )
    low_confidence["evidence_types"] = ["user_utterance"]

    conflict_a = item(
        "gate_conflict_a",
        claim="WORLD_STATE must update automatically.",
        source_type="user_utterance",
        modality="must",
        scope="project",
        subject="world_state",
        predicate="update_world_state",
        object_value="world state",
        confidence=99,
        status="candidate",
    )
    conflict_a["evidence_types"] = ["user_utterance"]
    conflict_b = item(
        "gate_conflict_b",
        claim="WORLD_STATE must not update automatically.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="world_state",
        predicate="update_world_state",
        object_value="world state",
        confidence=99,
        status="candidate",
    )
    conflict_b["evidence_types"] = ["user_utterance"]
    conflict = {
        "id": "gate_conflict",
        "timestamp": "2026-05-26T00:00:00Z",
        "type": "user_vs_user",
        "item_a": "gate_conflict_a",
        "item_b": "gate_conflict_b",
        "description": "Eval unresolved conflict.",
        "severity": 90,
        "resolution": "unresolved",
        "chosen_side": "",
        "reason": "",
    }

    set_items(project_root, [user_anchor, user_duplicate, agent_duplicate, low_confidence, conflict_a, conflict_b])
    write_jsonl(project_root / ".project_cognition" / "raw" / "conflicts.jsonl", [conflict])
    world_before = (project_root / ".project_cognition" / "WORLD_STATE.md").read_text(encoding="utf-8")
    table_before = (project_root / ".project_cognition" / "distilled" / "confidence_table.json").read_text(encoding="utf-8")
    raw_before = (project_root / ".project_cognition" / "raw" / "conflicts.jsonl").read_text(encoding="utf-8")
    run_script(project_root, "cluster_candidates.py")
    gate = run_script(project_root, "auto_governance_gate.py")
    build = run_script(project_root, "build_world_state.py")
    world_after = (project_root / ".project_cognition" / "WORLD_STATE.md").read_text(encoding="utf-8")
    table_after = (project_root / ".project_cognition" / "distilled" / "confidence_table.json").read_text(encoding="utf-8")
    raw_after = (project_root / ".project_cognition" / "raw" / "conflicts.jsonl").read_text(encoding="utf-8")
    allowed = set(gate.get("allowed_item_ids", []))
    decisions = {row.get("id"): row for row in gate.get("decisions", [])}
    return {
        "gate_allows_user_anchor": "gate_user_anchor" in allowed,
        "gate_blocks_duplicate_candidates": "gate_user_duplicate" not in allowed
        and "blocked_as_duplicate_candidate" in decisions["gate_user_duplicate"].get("reasons", []),
        "gate_blocks_agent_only_duplicate": "gate_agent_duplicate" not in allowed
        and "agent_only_evidence" in decisions["gate_agent_duplicate"].get("reasons", []),
        "gate_blocks_low_confidence": "gate_low_confidence" not in allowed
        and any(reason.startswith("confidence_below_") for reason in decisions["gate_low_confidence"].get("reasons", [])),
        "gate_blocks_unresolved_conflict": not ({"gate_conflict_a", "gate_conflict_b"} & allowed),
        "gate_does_not_mutate_evidence_or_table": table_before == table_after and raw_before == raw_after,
        "build_world_state_uses_gate": build.get("included_cognition_ids") == ["gate_user_anchor"]
        and "assistant final output" in world_after.lower()
        and world_before != world_after,
    }


def check_governance_gate_budget(project_root: Path) -> dict[str, bool]:
    high = item(
        "budget_high",
        claim="Highest priority user rule should enter the gate budget.",
        source_type="user_utterance",
        modality="must_not",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final output",
        confidence=99,
        status="candidate",
    )
    mid = item(
        "budget_mid",
        claim="Second priority user rule should enter the gate budget.",
        source_type="user_utterance",
        modality="must",
        scope="project",
        subject="history_context",
        predicate="read_source",
        object_value="specified source records",
        confidence=98,
        status="candidate",
    )
    low = item(
        "budget_low",
        claim="Lower priority user rule should stay in distilled when the gate budget is full.",
        source_type="user_utterance",
        modality="should",
        scope="project",
        subject="world_state",
        predicate="render",
        object_value="secondary implementation detail",
        confidence=95,
        status="candidate",
    )
    for row in [high, mid, low]:
        row["evidence_types"] = ["user_utterance"]
        row["score_signals"] = ["user_explicit_preference"]
    set_items(project_root, [high, mid, low])
    gate = run_script(
        project_root,
        "auto_governance_gate.py",
        ["--max-allowed", "2", "--max-per-category", "0", "--max-per-predicate", "0", "--max-per-slot", "0"],
    )
    build = run_script(project_root, "build_world_state.py")
    allowed = set(gate.get("allowed_item_ids", []))
    low_decision = next(row for row in gate.get("decisions", []) if row.get("id") == "budget_low")
    budget = gate.get("admission_budget", {})
    budget_blocked = budget.get("budget_blocked_ids", {}).get("max_allowed", [])
    return {
        "gate_budget_keeps_top_priority": allowed == {"budget_high", "budget_mid"},
        "gate_budget_blocks_lower_priority": "budget_low" in budget_blocked
        and "blocked_by_gate_budget_max_allowed" in low_decision.get("reasons", []),
        "world_state_uses_budgeted_gate": set(build.get("included_cognition_ids", [])) == {"budget_high", "budget_mid"},
        "budget_metrics_reported": budget.get("max_allowed") == 2 and budget.get("kept_count") == 2,
    }


def check_compound_sentence_extraction(project_root: Path) -> dict[str, bool]:
    utterance = {
        "id": "utt_compound",
        "session_id": "compound_eval",
        "timestamp": "2026-05-24T18:00:00Z",
        "text": "assistant 输出可以进日志，但不能进入核心记忆；更新 WORLD_STATE 必须经过审查；需要按具体证据读取原文，不得注入全部历史上下文。",
        "source": "eval",
        "importance_score": 95,
        "signals": {
            "long_form": False,
            "repeated": False,
            "explicit_preference": True,
            "explicit_rejection": True,
            "strong_emphasis": True,
        },
        "linked_topics": ["memory", "world_state", "review_flow"],
        "notes": "",
    }
    write_jsonl(project_root / ".project_cognition" / "raw" / "user_utterances.jsonl", [utterance])
    run_script(project_root, "extract_candidates.py")
    items = read_json(project_root / ".project_cognition" / "distilled" / "confidence_table.json").get("items", [])
    predicates = {row.get("structured", {}).get("predicate") for row in items}
    object_keys = {row.get("structured", {}).get("object_key") for row in items}
    return {
        "compound_sentence_splits_multiple_claims": {"store_log", "enter_core_memory", "require_review", "read_source", "inject_context"}
        <= predicates
        and {"assistant_output", "world_state", "history_context"} <= object_keys,
    }


def check_drift_report(project_root: Path) -> dict[str, bool]:
    run_minimal_pipeline(project_root)
    run_script(project_root, "cluster_candidates.py")
    run_script(project_root, "cluster_conflicts.py")
    ok_report = run_script(project_root, "drift_report.py")

    stale = item(
        "stale_revived",
        claim="Superseded rule should not re-enter world state.",
        source_type="user_utterance",
        modality="must",
        scope="project",
        subject="world_state",
        predicate="render",
        object_value="stale rule",
        status="superseded",
    )
    stale["evidence"] = []
    stale["structured"]["source_refs"] = []
    stale["include_in_world_state"] = True
    set_items(project_root, [stale])
    stale_status = run_script_status(project_root, "drift_report.py")
    stale_report = json.loads(stale_status.stdout)

    assistant_only = item(
        "assistant_only_core",
        claim="Agent-only interpretation should not become core.",
        source_type="agent_interpretation",
        modality="must",
        scope="project",
        subject="assistant_output",
        predicate="enter_core_memory",
        object_value="assistant final answer",
        status="candidate",
        confidence=74,
    )
    assistant_only["evidence"] = []
    assistant_only["structured"]["source_refs"] = []
    assistant_only["include_in_world_state"] = True
    set_items(project_root, [assistant_only])
    assistant_status = run_script_status(project_root, "drift_report.py")
    assistant_report = json.loads(assistant_status.stdout)

    candidate_core = item(
        "candidate_core",
        claim="Ungoverned candidate should not become core.",
        source_type="user_utterance",
        modality="must",
        scope="project",
        subject="world_state",
        predicate="render",
        object_value="candidate core",
        status="candidate",
        confidence=99,
    )
    candidate_core["include_in_world_state"] = True
    set_items(project_root, [candidate_core])
    candidate_status = run_script_status(project_root, "drift_report.py")
    candidate_report = json.loads(candidate_status.stdout)
    return {
        "drift_report_blocks_stale_revival": ok_report.get("ok") is True
        and stale_status.returncode != 0
        and "stale_rule_revived" in stale_report.get("hard_failures", []),
        "assistant_only_still_never_core": assistant_status.returncode != 0
        and "assistant_only_entered_core" in assistant_report.get("hard_failures", []),
        "ungoverned_candidate_still_never_core": candidate_status.returncode != 0
        and "ungoverned_candidate_entered_core" in candidate_report.get("hard_failures", []),
        "candidate_cluster_metrics_reported": ok_report.get("candidate_cluster_file_exists") is True
        and "candidate_cluster_count" in ok_report
        and "duplicate_candidate_ratio" in ok_report,
        "governance_gate_metrics_reported": ok_report.get("governance_gate_file_exists") is True
        and "governance_allowed_count" in ok_report
        and "governance_blocked_count" in ok_report
        and "governance_blocked_reason_counts" in ok_report,
    }


def check_post_hook_sidecar_pipeline(project_root: Path) -> dict[str, bool]:
    result = run_script(
        project_root,
        "codex_post_hook.py",
        ["--session-jsonl", str(CASE_FILE), "--session-id", "post_hook_sidecar", "--source", "eval"],
    )
    scripts = list(result.get("step_scripts", []))
    cognition_root = project_root / ".project_cognition"
    return {
        "post_hook_runs_sidecars": all(
            script in scripts
            for script in ["cluster_candidates.py", "cluster_conflicts.py", "auto_governance_gate.py", "index_segments.py", "drift_report.py"]
        ),
        "post_hook_reports_sidecars": bool(result.get("conflict_clusters"))
        and bool(result.get("candidate_clusters"))
        and bool(result.get("governance_gate"))
        and bool(result.get("evidence_index"))
        and bool(result.get("drift"))
        and result.get("drift", {}).get("ok") is True,
        "post_hook_writes_sidecar_outputs": (cognition_root / "index" / "segments.jsonl").exists()
        and (cognition_root / "distilled" / "candidate_clusters.json").exists()
        and (cognition_root / "distilled" / "conflict_clusters.json").exists()
        and (cognition_root / "distilled" / "governance_gate.json").exists(),
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
        ("evidence_lookup", check_evidence_lookup),
        ("vector_lookup", check_vector_lookup),
        ("index_cache", check_index_cache),
        ("hook_runtime_hygiene", check_hook_runtime_hygiene),
        ("legacy_state_migration", check_legacy_state_migration),
        ("conflict_clustering", check_conflict_cluster_integrity),
        ("conflict_cluster_review", check_conflict_cluster_review),
        ("candidate_clustering", check_candidate_clustering),
        ("auto_governance_gate", check_auto_governance_gate),
        ("governance_gate_budget", check_governance_gate_budget),
        ("compound_sentence_extraction", check_compound_sentence_extraction),
        ("drift_report", check_drift_report),
        ("post_hook_sidecar_pipeline", check_post_hook_sidecar_pipeline),
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
