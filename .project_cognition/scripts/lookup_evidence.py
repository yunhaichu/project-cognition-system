#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from common import SEGMENT_INDEX, normalize_text, read_jsonl, trim_text
from index_segments import build_index


def terms(text: str) -> set[str]:
    lowered = str(text).lower()
    values = {token for token in re.findall(r"[a-z0-9_.-]{2,}", lowered)}
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", str(text)):
        if len(run) <= 8:
            values.add(run)
        for index in range(0, max(0, len(run) - 1)):
            values.add(run[index : index + 2])
    return {value for value in values if value}


def score_segment(segment: dict[str, Any], query: str, query_terms: set[str], source_id: str = "") -> int:
    if source_id and source_id in {segment.get("source_id"), segment.get("id")}:
        return 100
    if not query:
        return 0
    text = str(segment.get("text", ""))
    normalized_query = normalize_text(query)
    normalized_text = normalize_text(text)
    score = 0
    if normalized_query and normalized_query in normalized_text:
        score += 60
    segment_terms = terms(text)
    overlap = query_terms & segment_terms
    if query_terms:
        score += int(35 * (len(overlap) / len(query_terms)))
    if any(term in str(segment.get("source_id", "")).lower() for term in query_terms):
        score += 15
    return min(100, score)


def load_segments(auto_build: bool) -> list[dict[str, Any]]:
    if not SEGMENT_INDEX.exists():
        if not auto_build:
            raise SystemExit(f"Segment index not found: {SEGMENT_INDEX}. Run index_segments.py first.")
        build_index()
    return read_jsonl(SEGMENT_INDEX)


def lookup(query: str = "", source_id: str = "", limit: int = 5, auto_build: bool = True) -> dict[str, Any]:
    segments = load_segments(auto_build=auto_build)
    query_terms = terms(query)
    matches: list[dict[str, Any]] = []
    for segment in segments:
        score = score_segment(segment, query, query_terms, source_id=source_id)
        if score <= 0:
            continue
        matches.append(
            {
                "segment_id": segment.get("id", ""),
                "source_id": segment.get("source_id", ""),
                "source_type": segment.get("source_type", ""),
                "session_id": segment.get("session_id", ""),
                "timestamp": segment.get("timestamp", ""),
                "path": segment.get("path", ""),
                "score": score,
                "matched_text": trim_text(str(segment.get("text", "")), 500),
                "topics": segment.get("topics", []),
            }
        )
    matches.sort(key=lambda item: (-int(item["score"]), str(item["source_id"]), str(item["segment_id"])))
    return {
        "query": query,
        "source_id": source_id,
        "match_count": len(matches),
        "matches": matches[:limit],
        "note": "Lookup returns grounded source snippets only. It does not update WORLD_STATE.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Look up exact source evidence from the local segment index.")
    parser.add_argument("--query", default="", help="Keyword or phrase to look up.")
    parser.add_argument("--source-id", default="", help="Exact source id or segment id to retrieve.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum matches to print.")
    parser.add_argument("--no-build", action="store_true", help="Do not auto-build the segment index if it is missing.")
    args = parser.parse_args()
    if not args.query and not args.source_id:
        raise SystemExit("Provide --query or --source-id.")
    result = lookup(query=args.query, source_id=args.source_id, limit=args.limit, auto_build=not args.no_build)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
