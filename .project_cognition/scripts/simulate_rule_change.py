#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from common import COGNITION_ROOT, now_iso, read_json, read_jsonl, write_json, write_jsonl
from update_scoring_weights import update_weights
from validate_state import validate_state


PROJECT_ROOT = COGNITION_ROOT.parent
RULE_CHANGE_PROPOSALS = COGNITION_ROOT / "proposals" / "rule_change_proposals.jsonl"
SIMULATION_DIR = COGNITION_ROOT / "distilled"
DEFAULT_MAX_COMPACT_CHARS = 1600


def sha256_json(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def load_proposals() -> list[dict[str, Any]]:
    return read_jsonl(RULE_CHANGE_PROPOSALS)


def save_proposals(proposals: list[dict[str, Any]]) -> None:
    write_jsonl(RULE_CHANGE_PROPOSALS, proposals)


def find_proposal(proposals: list[dict[str, Any]], proposal_id: str) -> dict[str, Any]:
    for proposal in proposals:
        if proposal.get("id") == proposal_id:
            return proposal
    raise SystemExit(f"Rule change proposal not found: {proposal_id}")


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


def make_project_copy(temp_dir: str) -> Path:
    project_root = Path(temp_dir) / "project"
    shutil.copytree(
        PROJECT_ROOT / ".project_cognition",
        project_root / ".project_cognition",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return project_root


def read_confidence_items(cognition_root: Path) -> list[dict[str, Any]]:
    table_path = cognition_root / "distilled" / "confidence_table.json"
    if not table_path.exists():
        return []
    return list(read_json(table_path, {"items": []}).get("items", []))


def item_is_agent_only(item: dict[str, Any]) -> bool:
    source_type = str(item.get("source_type", ""))
    evidence_types = set(str(value) for value in item.get("evidence_types", []))
    if source_type == "assistant_output":
        return True
    return source_type == "agent_interpretation" and not (evidence_types & {"user_utterance", "tool_evidence"})


def item_is_non_direct_user_material(item: dict[str, Any]) -> bool:
    intents = set(str(value) for value in item.get("utterance_intents", []))
    return bool(intents) and "direct_user_intent" not in intents


def item_is_stale(item: dict[str, Any]) -> bool:
    return str(item.get("status", "")) in {"rejected", "superseded"}


def read_gate_allowed(cognition_root: Path) -> set[str]:
    gate_path = cognition_root / "distilled" / "governance_gate.json"
    if not gate_path.exists():
        return set()
    return {str(value) for value in read_json(gate_path, {}).get("allowed_item_ids", [])}


def unresolved_blocked_conflict_ids(cognition_root: Path, min_severity: int = 60) -> set[str]:
    blocked: set[str] = set()
    for conflict in read_jsonl(cognition_root / "raw" / "conflicts.jsonl"):
        if conflict.get("resolution") in {"unresolved", "deferred"} and int(conflict.get("severity", 0)) >= min_severity:
            blocked.add(str(conflict.get("item_a", "")))
            blocked.add(str(conflict.get("item_b", "")))
    return {value for value in blocked if value}


def snapshot_project(project_root: Path, *, apply_scoring_weights: bool) -> dict[str, Any]:
    cognition_root = project_root / ".project_cognition"
    if apply_scoring_weights:
        run_script(project_root, "update_scoring_weights.py", ["--apply"])
    run_script(project_root, "score_candidates.py")
    run_script(project_root, "detect_conflicts.py")
    run_script(project_root, "cluster_candidates.py")
    run_script(project_root, "cluster_conflicts.py")
    gate = run_script(project_root, "auto_governance_gate.py")
    world = run_script(project_root, "build_world_state.py")
    validation = run_script(project_root, "validate_state.py")
    drift = run_script(project_root, "drift_report.py")
    items = read_confidence_items(cognition_root)
    items_by_id = {str(item.get("id", "")): item for item in items}
    include_ids = {str(item.get("id", "")) for item in items if item.get("include_in_world_state")}
    world_ids = {str(value) for value in world.get("included_cognition_ids", [])}
    gate_ids = read_gate_allowed(cognition_root)
    scores = {item_id: int(item.get("confidence", 0)) for item_id, item in items_by_id.items()}
    compact_path = cognition_root / "WORLD_STATE_COMPACT.md"
    compact_text = compact_path.read_text(encoding="utf-8") if compact_path.exists() else ""
    return {
        "items_by_id": items_by_id,
        "include_ids": include_ids,
        "gate_allowed_ids": gate_ids,
        "world_state_ids": world_ids,
        "scores": scores,
        "compact_characters": len(compact_text),
        "validation_error_count": len(validation.get("errors", [])),
        "drift_ok": drift.get("ok") is True,
        "drift_hard_failures": list(drift.get("hard_failures", [])),
        "blocked_conflict_ids": unresolved_blocked_conflict_ids(cognition_root),
        "gate": gate,
        "world": world,
    }


def state_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": len(snapshot.get("items_by_id", {})),
        "include_count": len(snapshot.get("include_ids", set())),
        "gate_allowed_count": len(snapshot.get("gate_allowed_ids", set())),
        "world_state_count": len(snapshot.get("world_state_ids", set())),
        "compact_characters": int(snapshot.get("compact_characters", 0)),
        "validation_error_count": int(snapshot.get("validation_error_count", 0)),
        "drift_ok": bool(snapshot.get("drift_ok")),
    }


def compare_snapshots(baseline: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    baseline_scores = baseline.get("scores", {})
    proposed_scores = proposed.get("scores", {})
    score_changes = {}
    for item_id in sorted(set(baseline_scores) | set(proposed_scores)):
        before = baseline_scores.get(item_id)
        after = proposed_scores.get(item_id)
        if before != after:
            score_changes[item_id] = {"before": before, "after": after}
    def transitions(key: str) -> dict[str, list[str]]:
        before = set(baseline.get(key, set()))
        after = set(proposed.get(key, set()))
        return {"entered": sorted(after - before), "exited": sorted(before - after)}
    return {
        "score_changes": score_changes,
        "include_transitions": transitions("include_ids"),
        "gate_decision_transitions": transitions("gate_allowed_ids"),
        "world_state_transitions": transitions("world_state_ids"),
        "compact_character_delta": int(proposed.get("compact_characters", 0)) - int(baseline.get("compact_characters", 0)),
        "validation_error_delta": int(proposed.get("validation_error_count", 0)) - int(baseline.get("validation_error_count", 0)),
    }


def detect_forbidden_transitions(baseline: dict[str, Any], proposed: dict[str, Any], *, max_compact_chars: int) -> list[str]:
    failures: list[str] = []
    baseline_core = set(baseline.get("world_state_ids", set())) | set(baseline.get("include_ids", set())) | set(baseline.get("gate_allowed_ids", set()))
    proposed_core = set(proposed.get("world_state_ids", set())) | set(proposed.get("include_ids", set())) | set(proposed.get("gate_allowed_ids", set()))
    entered_core = proposed_core - baseline_core
    items_by_id = proposed.get("items_by_id", {})
    if any(item_is_agent_only(items_by_id.get(item_id, {})) for item_id in entered_core):
        failures.append("assistant_or_agent_only_entered_core")
    if any(item_is_non_direct_user_material(items_by_id.get(item_id, {})) for item_id in entered_core):
        failures.append("quoted_or_external_user_material_entered_core")
    if any(item_is_stale(items_by_id.get(item_id, {})) for item_id in proposed_core):
        failures.append("stale_item_entered_core")
    if set(proposed.get("blocked_conflict_ids", set())) & set(proposed.get("world_state_ids", set())):
        failures.append("unresolved_conflict_side_entered_world_state")
    if int(proposed.get("compact_characters", 0)) > max_compact_chars:
        failures.append("compact_characters_exceeded")
    if int(proposed.get("validation_error_count", 0)) > int(baseline.get("validation_error_count", 0)):
        failures.append("validation_errors_increased")
    if proposed.get("drift_hard_failures"):
        failures.append("drift_report_hard_failures_present")
    return sorted(set(failures))


def synthetic_self_check(max_compact_chars: int) -> dict[str, Any]:
    baseline = {
        "items_by_id": {
            "safe": {"id": "safe", "source_type": "user_utterance", "status": "accepted"},
            "agent_only": {"id": "agent_only", "source_type": "agent_interpretation", "evidence_types": [], "status": "candidate"},
            "quoted": {"id": "quoted", "source_type": "user_utterance", "utterance_intents": ["quoted_evaluation"], "status": "candidate"},
            "stale": {"id": "stale", "source_type": "user_utterance", "status": "superseded"},
        },
        "include_ids": {"safe"},
        "gate_allowed_ids": {"safe"},
        "world_state_ids": {"safe"},
        "blocked_conflict_ids": set(),
        "compact_characters": 100,
        "validation_error_count": 0,
        "drift_hard_failures": [],
    }
    proposed = {
        "items_by_id": baseline["items_by_id"],
        "include_ids": {"safe", "agent_only", "quoted", "stale"},
        "gate_allowed_ids": {"safe", "agent_only", "quoted", "stale"},
        "world_state_ids": {"safe", "agent_only", "quoted", "stale", "conflict_side"},
        "blocked_conflict_ids": {"conflict_side"},
        "compact_characters": max_compact_chars + 1,
        "validation_error_count": 1,
        "drift_hard_failures": ["assistant_only_entered_core"],
    }
    failures = detect_forbidden_transitions(baseline, proposed, max_compact_chars=max_compact_chars)
    expected = {
        "assistant_or_agent_only_entered_core",
        "quoted_or_external_user_material_entered_core",
        "stale_item_entered_core",
        "unresolved_conflict_side_entered_world_state",
        "compact_characters_exceeded",
        "validation_errors_increased",
        "drift_report_hard_failures_present",
    }
    return {"hard_failures": failures, "expected_failures_present": expected <= set(failures), "passed": expected <= set(failures)}


def simulate(proposal_id: str, *, max_compact_chars: int = DEFAULT_MAX_COMPACT_CHARS) -> dict[str, Any]:
    proposals = load_proposals()
    proposal = find_proposal(proposals, proposal_id)
    timestamp = now_iso()
    hard_failures: list[str] = []
    warnings: list[str] = []
    if proposal.get("change_type") != "scoring_weight_update":
        hard_failures.append("unsupported_change_type")
        shadow = {}
        baseline_summary = {}
        proposed_summary = {}
        diff = {}
    else:
        shadow = update_weights(apply=False, write_shadow=True)
        if int(shadow.get("would_apply", 0)) == 0:
            warnings.append("no_pending_scoring_feedback")
        if int(shadow.get("changed_signal_count", 0)) == 0 and int(shadow.get("would_apply", 0)) > 0:
            warnings.append("feedback_would_apply_without_signal_changes")
        with tempfile.TemporaryDirectory(prefix="pcs_rule_baseline_") as baseline_dir, tempfile.TemporaryDirectory(prefix="pcs_rule_proposed_") as proposed_dir:
            baseline_project = make_project_copy(baseline_dir)
            proposed_project = make_project_copy(proposed_dir)
            baseline = snapshot_project(baseline_project, apply_scoring_weights=False)
            proposed = snapshot_project(proposed_project, apply_scoring_weights=True)
        diff = compare_snapshots(baseline, proposed)
        hard_failures.extend(detect_forbidden_transitions(baseline, proposed, max_compact_chars=max_compact_chars))
        baseline_summary = state_summary(baseline)
        proposed_summary = state_summary(proposed)
    validation = validate_state(PROJECT_ROOT)
    if validation.get("errors"):
        hard_failures.append("validation_errors_present")
    report = {
        "id": f"sim_{sha256_json([proposal_id, timestamp])[:12]}",
        "timestamp": timestamp,
        "proposal_id": proposal_id,
        "change_type": proposal.get("change_type"),
        "target_path": proposal.get("target_path"),
        "shadow_report": shadow,
        "baseline_summary": baseline_summary,
        "proposed_summary": proposed_summary,
        "diff": diff,
        "validation_ok": validation.get("ok") is True,
        "validation_error_count": len(validation.get("errors", [])),
        "max_compact_chars": max_compact_chars,
        "hard_failures": sorted(set(hard_failures)),
        "warnings": sorted(set(warnings)),
        "writes_target": False,
    }
    report_path = SIMULATION_DIR / f"rule_change_simulation_{report['id']}.json"
    write_json(report_path, report)
    proposal["status"] = "simulated"
    proposal["simulation_report_id"] = report["id"]
    proposal["simulation_report_path"] = str(report_path.relative_to(COGNITION_ROOT))
    proposal["hard_failures"] = report["hard_failures"]
    proposal["warnings"] = report["warnings"]
    proposal["simulated_at"] = timestamp
    save_proposals(proposals)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a rule-change proposal without applying it.")
    parser.add_argument("--proposal-id")
    parser.add_argument("--max-compact-chars", type=int, default=DEFAULT_MAX_COMPACT_CHARS)
    parser.add_argument("--self-check", action="store_true", help="Run synthetic forbidden-transition detector self-check.")
    args = parser.parse_args()
    if args.self_check:
        result = synthetic_self_check(args.max_compact_chars)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["passed"]:
            raise SystemExit(1)
        return
    if not args.proposal_id:
        raise SystemExit("--proposal-id is required unless --self-check is used.")
    print(json.dumps(simulate(args.proposal_id, max_compact_chars=args.max_compact_chars), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
