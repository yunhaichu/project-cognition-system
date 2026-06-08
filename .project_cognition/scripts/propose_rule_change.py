#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common import COGNITION_ROOT, append_jsonl, make_id, now_iso, parse_csv_values, read_jsonl
from update_scoring_weights import update_weights


PROJECT_ROOT = COGNITION_ROOT.parent
RULE_CHANGE_PROPOSALS = COGNITION_ROOT / "proposals" / "rule_change_proposals.jsonl"
DEFAULT_SCORING_TARGET = ".project_cognition/distilled/scoring_weights.json"


def sha256_file(path: Path) -> str:
    if not path.exists():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def target_abs(target_path: str) -> Path:
    target = Path(target_path)
    if target.is_absolute():
        raise SystemExit("target_path must be relative to the project root.")
    if not target_path.startswith(".project_cognition/"):
        raise SystemExit("target_path must stay under .project_cognition/.")
    return PROJECT_ROOT / target


def latest_shadow_summary(change_type: str, refresh_shadow: bool) -> dict[str, Any]:
    if change_type != "scoring_weight_update":
        return {}
    if refresh_shadow:
        return update_weights(apply=False, write_shadow=True)
    shadow_path = COGNITION_ROOT / "distilled" / "scoring_weight_shadow_report.json"
    if not shadow_path.exists():
        return update_weights(apply=False, write_shadow=True)
    return json.loads(shadow_path.read_text(encoding="utf-8"))


def create_proposal(args: argparse.Namespace) -> dict[str, Any]:
    timestamp = now_iso()
    evidence = parse_csv_values(args.evidence)
    target_path = args.target_path or DEFAULT_SCORING_TARGET
    shadow = latest_shadow_summary(args.change_type, not args.no_refresh_shadow)
    before_hash = sha256_file(target_abs(target_path))
    proposed_after_hash = sha256_json(
        {
            "change_type": args.change_type,
            "target_path": target_path,
            "changed_signals": shadow.get("changed_signals", {}),
            "would_apply": shadow.get("would_apply", 0),
        }
    )
    changed_count = int(shadow.get("changed_signal_count", 0))
    would_apply = int(shadow.get("would_apply", 0))
    patch_summary = args.patch_summary or f"Scoring weight shadow update: {changed_count} signal changes; {would_apply} feedback rows would apply."
    proposal = {
        "id": make_id("rule_prop", f"{args.change_type}:{target_path}:{timestamp}", timestamp),
        "timestamp": timestamp,
        "change_type": args.change_type,
        "target_path": target_path,
        "reason": args.reason,
        "evidence": evidence,
        "before_hash": before_hash,
        "proposed_after_hash": proposed_after_hash,
        "patch_summary": patch_summary,
        "risk_level": args.risk_level,
        "status": "pending",
        "requires_explicit_apply": True,
        "simulation_report_id": "",
        "simulation_report_path": "",
        "hard_failures": [],
        "warnings": [],
    }
    append_jsonl(RULE_CHANGE_PROPOSALS, proposal)
    return proposal


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a rule-change proposal without applying it.")
    parser.add_argument("--change-type", default="scoring_weight_update", choices=["scoring_weight_update", "governance_policy_update", "predicate_rule_update", "object_canonicalization_update", "bootstrap_doctrine_update", "context_selection_policy_update"])
    parser.add_argument("--target-path", help="Relative path under .project_cognition/. Defaults to scoring_weights.json for scoring updates.")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--evidence", action="append", help="Feedback event ids or labels. Can be repeated or comma-separated.")
    parser.add_argument("--risk-level", default="medium", choices=["low", "medium", "high", "constitutional"])
    parser.add_argument("--patch-summary", help="Optional human-readable change summary.")
    parser.add_argument("--no-refresh-shadow", action="store_true", help="Use the existing shadow report if present.")
    args = parser.parse_args()
    if args.change_type != "scoring_weight_update":
        raise SystemExit("Only scoring_weight_update is implemented in this phase.")
    proposal = create_proposal(args)
    print(json.dumps(proposal, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
