#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from common import (
    DECISIONS,
    PROPOSALS_JSONL,
    PROPOSALS_MD,
    SCORING_FEEDBACK,
    append_jsonl,
    category_choices,
    confidence_table_items,
    now_iso,
    read_jsonl,
    save_confidence_table,
    stable_id,
    write_jsonl,
    write_text,
)
from propose_update import render_markdown


def infer_feedback_signals(proposal: dict[str, Any]) -> list[str]:
    text = " ".join([proposal.get("claim", ""), proposal.get("reason", ""), " ".join(proposal.get("evidence", []))])
    signals: set[str] = set()
    if len(text) >= 120:
        signals.add("user_long_form")
    if any(token in text for token in ["明确", "偏好", "希望", "要求", "优先", "权重"]):
        signals.add("user_explicit_preference")
    if any(token in text for token in ["不要", "不得", "不能", "禁止", "不应", "不是"]):
        signals.add("user_explicit_rejection")
    if any(token in text for token in ["必须", "最高", "最低", "核心", "只能", "极致"]):
        signals.add("user_strong_emphasis")
    if any(token in text for token in ["每次", "默认", "长期", "稳定", "以后", "永远"]):
        signals.add("user_long_term")
    if any(token in text for token in ["用户画像", "AGENTS.md", "每个项目", "项目文件夹"]):
        signals.add("user_profile_or_project_scope")
    if not proposal.get("evidence"):
        signals.add("missing_evidence")
    if proposal.get("conflicts"):
        signals.add("unresolved_conflict")
    if proposal.get("source_type") == "assistant_output":
        signals.add("assistant_output")
    return sorted(signals)


def record_scoring_feedback(proposal: dict[str, Any], action: str, note: str) -> None:
    append_jsonl(
        SCORING_FEEDBACK,
        {
            "id": stable_id("feedback", proposal.get("id", ""), action),
            "timestamp": now_iso(),
            "proposal_id": proposal.get("id"),
            "action": action,
            "proposal_confidence": proposal.get("confidence", 0),
            "category": proposal.get("category"),
            "should_update_world_state": proposal.get("should_update_world_state"),
            "signals": infer_feedback_signals(proposal),
            "note": note,
            "applied_to_weights": False,
        },
    )


def proposal_to_cognition(proposal: dict[str, Any]) -> dict[str, Any]:
    confidence = int(proposal.get("confidence", 0))
    return {
        "id": stable_id("cog", proposal["category"], proposal["claim"]),
        "claim": proposal["claim"],
        "category": proposal["category"],
        "confidence": confidence,
        "evidence": proposal.get("evidence", []),
        "conflicts": proposal.get("conflicts", []),
        "last_verified": now_iso(),
        "stability": "stable" if confidence >= 90 and proposal["category"] != "strategy" else "temporary" if proposal["category"] == "strategy" else "evolving",
        "include_in_world_state": bool(proposal.get("should_update_world_state")) and confidence >= 90 and not proposal.get("conflicts"),
        "source_type": "proposed_update",
        "status": "accepted",
    }


def accept_proposal(proposal: dict[str, Any]) -> None:
    if proposal["category"] == "decision":
        decision = {
            "id": stable_id("decision", proposal["claim"]),
            "timestamp": now_iso(),
            "decision": proposal["claim"],
            "reason": proposal.get("reason", ""),
            "evidence_utterance_ids": proposal.get("evidence", []),
            "confidence": proposal.get("confidence", 0),
            "reversible": True,
            "status": "active",
        }
        append_jsonl(DECISIONS, decision)
        return

    items = confidence_table_items()
    cognition = proposal_to_cognition(proposal)
    replaced = False
    for index, item in enumerate(items):
        if item.get("id") == cognition["id"]:
            items[index] = cognition
            replaced = True
            break
    if not replaced:
        items.append(cognition)
    save_confidence_table(items)


def review(proposal_id: str, action: str, note: str) -> dict[str, Any]:
    proposals = read_jsonl(PROPOSALS_JSONL)
    if not proposals:
        raise SystemExit("No proposals found.")
    matched: dict[str, Any] | None = None
    for proposal in proposals:
        if proposal.get("id") == proposal_id:
            matched = proposal
            break
    if not matched:
        raise SystemExit(f"Proposal not found: {proposal_id}")

    if action == "accept":
        accept_proposal(matched)
        matched["status"] = "accepted"
    elif action == "reject":
        matched["status"] = "rejected"
    else:
        matched["status"] = "deferred"
    matched["reviewed_at"] = now_iso()
    matched["review_note"] = note
    record_scoring_feedback(matched, action, note)

    write_jsonl(PROPOSALS_JSONL, proposals)
    write_text(PROPOSALS_MD, render_markdown(proposals))
    return matched


def main() -> None:
    parser = argparse.ArgumentParser(description="Review a proposed cognition update and optionally merge it into distilled state.")
    parser.add_argument("--proposal-id", help="Proposal id to review.")
    parser.add_argument("--action", choices=["accept", "reject", "defer"], help="Review action.")
    parser.add_argument("--note", default="", help="Optional review note.")
    parser.add_argument("--list", action="store_true", help="List proposals and exit.")
    args = parser.parse_args()

    if args.list:
        print(json.dumps(read_jsonl(PROPOSALS_JSONL), ensure_ascii=False, indent=2))
        return
    if not args.proposal_id or not args.action:
        raise SystemExit("--proposal-id and --action are required unless --list is used.")

    reviewed = review(args.proposal_id, args.action, args.note)
    print(json.dumps(reviewed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
