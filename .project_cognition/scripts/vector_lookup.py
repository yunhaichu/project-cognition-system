#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from build_vector_index import DEFAULT_DIMENSIONS, build_vector_index, vectorize_text
from common import VECTOR_INDEX, read_jsonl, trim_text


def dot_product(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def load_records(auto_build: bool) -> list[dict[str, Any]]:
    if not VECTOR_INDEX.exists():
        if not auto_build:
            raise SystemExit(f"Vector index not found: {VECTOR_INDEX}. Run build_vector_index.py first.")
        build_vector_index()
    return read_jsonl(VECTOR_INDEX)


def result_row(record: dict[str, Any], score: int) -> dict[str, Any]:
    return {
        "vector_id": record.get("id", ""),
        "segment_id": record.get("segment_id", ""),
        "source_id": record.get("source_id", ""),
        "source_type": record.get("source_type", ""),
        "session_id": record.get("session_id", ""),
        "timestamp": record.get("timestamp", ""),
        "path": record.get("path", ""),
        "score": score,
        "matched_text": trim_text(str(record.get("text_preview", "")), 500),
        "matched_text_is_preview": True,
        "matched_text_is_authoritative": False,
        "record_level": bool(record.get("record_level", False)),
        "chunked": bool(record.get("chunked", True)),
        "record_characters": int(record.get("record_characters", 0)),
        "vector_model": record.get("vector_model", ""),
        "topics": record.get("topics", []),
    }


def lookup(query: str = "", source_id: str = "", limit: int = 5, auto_build: bool = True) -> dict[str, Any]:
    records = load_records(auto_build=auto_build)
    dimensions = int(records[0].get("dimensions", DEFAULT_DIMENSIONS)) if records else DEFAULT_DIMENSIONS
    query_vector = vectorize_text(query, dimensions=dimensions)
    matches: list[dict[str, Any]] = []
    for record in records:
        score = 0
        if source_id and source_id in {record.get("source_id"), record.get("segment_id"), record.get("id")}:
            score = 100
        elif query_vector:
            vector = {str(key): float(value) for key, value in dict(record.get("vector", {})).items()}
            score = int(round(dot_product(query_vector, vector) * 100))
        if score <= 0:
            continue
        matches.append(result_row(record, score))
    matches.sort(key=lambda item: (-int(item["score"]), str(item["source_id"]), str(item["vector_id"])))
    return {
        "query": query,
        "source_id": source_id,
        "match_count": len(matches),
        "matches": matches[:limit],
        "note": "Vector lookup returns source ids plus non-authoritative previews from whole evidence records. Read the full source record by source_id before using it as evidence. It does not update WORLD_STATE.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Look up source evidence using the local record-level vector index.")
    parser.add_argument("--query", default="", help="Keyword or phrase to look up.")
    parser.add_argument("--source-id", default="", help="Exact source id, segment id, or vector id to retrieve.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum matches to print.")
    parser.add_argument("--no-build", action="store_true", help="Do not auto-build the vector index if it is missing.")
    args = parser.parse_args()
    if not args.query and not args.source_id:
        raise SystemExit("Provide --query or --source-id.")
    result = lookup(query=args.query, source_id=args.source_id, limit=args.limit, auto_build=not args.no_build)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
