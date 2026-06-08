#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common import COGNITION_ROOT, append_jsonl, make_id, now_iso, read_jsonl, write_jsonl
from drift_report import build_report as build_drift_report
from update_scoring_weights import update_weights
from validate_state import validate_state


PROJECT_ROOT = COGNITION_ROOT.parent
RULE_CHANGE_PROPOSALS = COGNITION_ROOT / "proposals" / "rule_change_proposals.jsonl"
RULE_CHANGE_LOG = COGNITION_ROOT / "raw" / "rule_change_log.jsonl"


def sha256_file(path: Path) -> str:
    if not path.exists():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def target_abs(target_path: str) -> Path:
    target = Path(target_path)
    if target.is_absolute():
        raise SystemExit("target_path must be relative to the project root.")
    if not target_path.startswith(".project_cognition/"):
        raise SystemExit("target_path must stay under .project_cognition/.")
    return PROJECT_ROOT / target


def load_proposals() -> list[dict[str, Any]]:
    return read_jsonl(RULE_CHANGE_PROPOSALS)


def save_proposals(proposals: list[dict[str, Any]]) -> None:
    write_jsonl(RULE_CHANGE_PROPOSALS, proposals)


def find_proposal(proposals: list[dict[str, Any]], proposal_id: str) -> dict[str, Any]:
    for proposal in proposals:
        if proposal.get("id") == proposal_id:
            return proposal
    raise SystemExit(f"Rule change proposal not found: {proposal_id}")


def apply(proposal_id: str) -> dict[str, Any]:
    proposals = load_proposals()
    proposal = find_proposal(proposals, proposal_id)
    if proposal.get("status") not in {"simulated", "accepted"}:
        raise SystemExit("Rule change must be simulated before apply.")
    hard_failures = list(proposal.get("hard_failures", []))
    if hard_failures:
        raise SystemExit(f"Refusing to apply rule change with hard failures: {', '.join(hard_failures)}")
    if proposal.get("change_type") != "scoring_weight_update":
        raise SystemExit("Only scoring_weight_update can be applied in this phase.")
    target_path = str(proposal.get("target_path"))
    target = target_abs(target_path)
    before_hash = sha256_file(target)
    update_result = update_weights(apply=True, write_shadow=True)
    after_hash = sha256_file(target)
    validation = validate_state(PROJECT_ROOT)
    drift = build_drift_report(max_compact_chars=1600, max_high_severity_conflicts=100)
    if not validation.get("ok"):
        raise SystemExit("Validation failed after applying rule change.")
    if not drift.get("ok"):
        raise SystemExit("Drift report failed after applying rule change.")
    timestamp = now_iso()
    log = {
        "id": make_id("rule_change", f"{proposal_id}:{timestamp}", timestamp),
        "timestamp": timestamp,
        "proposal_id": proposal_id,
        "change_type": proposal.get("change_type"),
        "target_path": target_path,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "changed_fields": update_result.get("changed_signals", {}),
        "simulation_report_id": str(proposal.get("simulation_report_id", "")),
        "eval_passed": validation.get("ok") is True,
        "drift_report_ok": drift.get("ok") is True,
        "applied_by": "explicit_cli",
        "rollback_ref": before_hash,
    }
    append_jsonl(RULE_CHANGE_LOG, log)
    proposal["status"] = "applied"
    proposal["applied_at"] = timestamp
    save_proposals(proposals)
    return {"proposal": proposal, "log": log, "update_result": update_result}


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a simulated rule-change proposal.")
    parser.add_argument("--proposal-id", required=True)
    args = parser.parse_args()
    print(json.dumps(apply(args.proposal_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
