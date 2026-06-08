#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


COGNITION_ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_EVENTS = COGNITION_ROOT / "raw" / "feedback_events.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_no}: {exc}") from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key, "unknown") or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def build_report() -> dict[str, Any]:
    rows = read_jsonl(FEEDBACK_EVENTS)
    negative_rows = [row for row in rows if row.get("outcome") == "negative"]
    correction_rows = [row for row in rows if row.get("event_family") == "correction" or row.get("event_name") == "user_correction"]
    deterministic_rows = [row for row in rows if row.get("source_type") == "deterministic_tool"]
    drift_rows = [row for row in rows if row.get("event_family") == "drift"]
    false_accept_rows = [row for row in rows if row.get("event_family") == "gate" and row.get("event_name") == "false_accept"]
    false_reject_rows = [row for row in rows if row.get("event_family") == "gate" and row.get("event_name") == "false_reject"]
    high_severity_negative_rows = [row for row in negative_rows if int(row.get("severity", 0)) >= 75]
    return {
        "feedback_count": len(rows),
        "by_family": count_by(rows, "event_family"),
        "by_outcome": count_by(rows, "outcome"),
        "by_source_type": count_by(rows, "source_type"),
        "negative_feedback_count": len(negative_rows),
        "high_severity_negative_count": len(high_severity_negative_rows),
        "user_correction_count": len(correction_rows),
        "deterministic_tool_feedback_count": len(deterministic_rows),
        "drift_feedback_count": len(drift_rows),
        "gate_false_accept_count": len(false_accept_rows),
        "gate_false_reject_count": len(false_reject_rows),
        "local_only": True,
        "mutates_state": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report feedback-event metrics without mutating cognition state.")
    parser.parse_args()
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
