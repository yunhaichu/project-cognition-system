#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common import COGNITION_ROOT, now_iso, read_jsonl, write_json, write_jsonl
from update_scoring_weights import update_weights
from validate_state import validate_state


PROJECT_ROOT = COGNITION_ROOT.parent
RULE_CHANGE_PROPOSALS = COGNITION_ROOT / "proposals" / "rule_change_proposals.jsonl"
SIMULATION_DIR = COGNITION_ROOT / "distilled"


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


def simulate(proposal_id: str) -> dict[str, Any]:
    proposals = load_proposals()
    proposal = find_proposal(proposals, proposal_id)
    timestamp = now_iso()
    hard_failures: list[str] = []
    warnings: list[str] = []
    if proposal.get("change_type") != "scoring_weight_update":
        hard_failures.append("unsupported_change_type")
        shadow = {}
    else:
        shadow = update_weights(apply=False, write_shadow=True)
        if int(shadow.get("would_apply", 0)) == 0:
            warnings.append("no_pending_scoring_feedback")
        if int(shadow.get("changed_signal_count", 0)) == 0 and int(shadow.get("would_apply", 0)) > 0:
            warnings.append("feedback_would_apply_without_signal_changes")
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
        "validation_ok": validation.get("ok") is True,
        "validation_error_count": len(validation.get("errors", [])),
        "hard_failures": hard_failures,
        "warnings": warnings,
        "writes_target": False,
    }
    report_path = SIMULATION_DIR / f"rule_change_simulation_{report['id']}.json"
    write_json(report_path, report)
    proposal["status"] = "simulated"
    proposal["simulation_report_id"] = report["id"]
    proposal["simulation_report_path"] = str(report_path.relative_to(COGNITION_ROOT))
    proposal["hard_failures"] = hard_failures
    proposal["warnings"] = warnings
    proposal["simulated_at"] = timestamp
    save_proposals(proposals)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a rule-change proposal without applying it.")
    parser.add_argument("--proposal-id", required=True)
    args = parser.parse_args()
    print(json.dumps(simulate(args.proposal_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
