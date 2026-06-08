#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import append_jsonl, make_id, now_iso, parse_csv_values


COGNITION_ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_EVENTS = COGNITION_ROOT / "raw" / "feedback_events.jsonl"


def create_event(args: argparse.Namespace) -> dict[str, Any]:
    timestamp = args.timestamp or now_iso()
    refs = parse_csv_values(args.source_ref)
    event = {
        "id": make_id("fb", "|".join([args.event_family, args.event_name, args.target_type, args.target_id, timestamp]), timestamp),
        "timestamp": timestamp,
        "session_id": args.session_id or "",
        "task_id": args.task_id or "",
        "event_family": args.event_family,
        "event_name": args.event_name,
        "target_type": args.target_type,
        "target_id": args.target_id,
        "outcome": args.outcome,
        "severity": args.severity,
        "source_type": args.source_type,
        "source_refs": refs,
        "confidence": args.confidence,
        "notes": args.notes,
    }
    append_jsonl(FEEDBACK_EVENTS, event)
    return event


def main() -> None:
    parser = argparse.ArgumentParser(description="Append a feedback event without mutating cognition state.")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--timestamp")
    parser.add_argument("--event-family", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--target-type", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--outcome", required=True, choices=["positive", "negative", "neutral", "unknown"])
    parser.add_argument("--severity", type=int, default=0, choices=range(0, 101), metavar="[0-100]")
    parser.add_argument("--source-type", required=True)
    parser.add_argument("--source-ref", action="append")
    parser.add_argument("--confidence", type=int, default=100, choices=range(0, 101), metavar="[0-100]")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    print(json.dumps(create_event(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
