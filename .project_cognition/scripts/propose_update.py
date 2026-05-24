#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from common import (
    PROPOSALS_JSONL,
    PROPOSALS_MD,
    append_jsonl,
    bool_from_yes_no,
    canonical_object,
    category_choices,
    make_id,
    normalize_predicate,
    now_iso,
    parse_csv_values,
    predicate_choices,
    read_jsonl,
    write_text,
)


def render_markdown(proposals: list[dict[str, Any]]) -> str:
    if not proposals:
        return "# Proposed Cognition Updates\n\nNo pending proposals.\n"
    lines = ["# Proposed Cognition Updates", ""]
    for index, proposal in enumerate(proposals, 1):
        lines.extend(
            [
                f"## Candidate {index}",
                f"- Proposal ID: {proposal['id']}",
                f"- Claim: {proposal['claim']}",
                f"- Category: {proposal['category']}",
                f"- Evidence: {', '.join(proposal.get('evidence', [])) or 'none'}",
                f"- Confidence: {proposal['confidence']}",
                f"- Reason: {proposal['reason']}",
                f"- Conflicts: {', '.join(proposal.get('conflicts', [])) or 'none'}",
                f"- Suggested action: {proposal['suggested_action']}",
                f"- Should update WORLD_STATE.md: {'yes' if proposal.get('should_update_world_state') else 'no'}",
                f"- Structured: {json.dumps(proposal.get('structured', {}), ensure_ascii=False, sort_keys=True)}",
                f"- Status: {proposal['status']}",
                "",
            ]
        )
    return "\n".join(lines)


def create_proposal(args: argparse.Namespace) -> dict[str, Any]:
    timestamp = now_iso()
    evidence = parse_csv_values(args.evidence)
    conflicts = parse_csv_values(args.conflicts)
    supersedes = parse_csv_values(args.supersedes)
    structured = {
        "subject": args.subject or args.category,
        "predicate": normalize_predicate(args.predicate, args.claim),
        "object": args.object or args.claim,
        "object_key": canonical_object(args.object or args.claim),
        "scope": args.scope,
        "modality": args.modality,
        "valid_from": args.valid_from or timestamp,
        "valid_until": args.valid_until,
        "source_refs": evidence,
        "confidence_reason": args.reason,
        "supersedes": supersedes,
    }
    proposal = {
        "id": make_id("prop", args.claim, timestamp),
        "timestamp": timestamp,
        "claim": args.claim,
        "category": args.category,
        "evidence": evidence,
        "confidence": args.confidence,
        "reason": args.reason,
        "conflicts": conflicts,
        "suggested_action": args.suggested_action,
        "should_update_world_state": bool_from_yes_no(args.should_update_world_state),
        "status": "pending",
        "structured": structured,
    }
    append_jsonl(PROPOSALS_JSONL, proposal)
    proposals = read_jsonl(PROPOSALS_JSONL)
    write_text(PROPOSALS_MD, render_markdown(proposals))
    return proposal


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a proposed cognition update without directly editing WORLD_STATE.md.")
    parser.add_argument("--claim", required=True, help="Candidate cognition claim.")
    parser.add_argument("--category", required=True, choices=category_choices(), help="Cognition category.")
    parser.add_argument("--evidence", action="append", help="Evidence ids or labels. Can be repeated or comma-separated.")
    parser.add_argument("--confidence", required=True, type=int, choices=range(0, 101), metavar="[0-100]", help="Confidence score.")
    parser.add_argument("--reason", required=True, help="Why this update is proposed.")
    parser.add_argument("--conflicts", action="append", help="Known conflict ids. Can be repeated or comma-separated.")
    parser.add_argument("--suggested-action", choices=["accept", "reject", "defer"], default="defer", help="Suggested review action.")
    parser.add_argument("--should-update-world-state", choices=["yes", "no"], default="no", help="Whether this should enter WORLD_STATE.md if accepted.")
    parser.add_argument("--subject", help="Structured subject for this cognition.")
    parser.add_argument("--predicate", choices=predicate_choices(), help="Structured predicate for this cognition.")
    parser.add_argument("--object", help="Structured object for this cognition.")
    parser.add_argument("--scope", default="project", help="Structured scope. Default: project.")
    parser.add_argument("--modality", default="unknown", choices=["must", "should", "may", "must_not", "is", "is_not", "unknown"], help="Structured modality.")
    parser.add_argument("--valid-from", help="Optional validity start timestamp.")
    parser.add_argument("--valid-until", help="Optional validity end timestamp.")
    parser.add_argument("--supersedes", action="append", help="Cognition ids superseded by this proposal. Can be repeated or comma-separated.")
    args = parser.parse_args()

    proposal = create_proposal(args)
    print(json.dumps(proposal, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
