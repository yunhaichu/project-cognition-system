#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from common import (
    SEGMENT_INDEX,
    VECTOR_INDEX,
    VECTOR_MANIFEST,
    now_iso,
    read_json,
    read_jsonl,
    stable_id,
    trim_text,
    write_json,
    write_jsonl,
)
from index_segments import build_index


DEFAULT_DIMENSIONS = 4096
MODEL_NAME = "local_hashing_record_vector_v1"
NO_SPLIT_POLICY = "Vector retrieval may rank or embed whole evidence records, but must not split records into authoritative memory chunks."


def token_terms(text: str) -> list[str]:
    lowered = str(text).lower()
    values: list[str] = re.findall(r"[a-z0-9_.-]{2,}", lowered)
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", str(text)):
        if len(run) <= 8:
            values.append(run)
        values.extend(run[index : index + 2] for index in range(0, max(0, len(run) - 1)))
    return [value for value in values if value]


def hash_dimension(term: str, dimensions: int) -> int:
    digest = hashlib.sha1(term.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % dimensions


def vectorize_text(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> dict[str, float]:
    counts: dict[int, int] = {}
    for term in token_terms(text):
        index = hash_dimension(term, dimensions)
        counts[index] = counts.get(index, 0) + 1
    if not counts:
        return {}
    weighted = {index: 1.0 + math.log(count) for index, count in counts.items()}
    norm = math.sqrt(sum(value * value for value in weighted.values()))
    if norm <= 0:
        return {}
    return {str(index): round(value / norm, 6) for index, value in sorted(weighted.items())}


def validate_record_level_segments(segments: list[dict[str, Any]]) -> None:
    for row in segments:
        if row.get("record_level") is not True or row.get("chunked") is not False or row.get("segment_index") != 0:
            raise SystemExit(
                "Vector index refuses non-record-level evidence. Rebuild with index_segments.py in record_level_no_split mode."
            )


def source_fingerprint(dimensions: int, include_tool_logs: bool) -> dict[str, Any]:
    if not SEGMENT_INDEX.exists():
        return {
            "model": MODEL_NAME,
            "dimensions": dimensions,
            "segment_index": None,
            "include_tool_logs": include_tool_logs,
        }
    stat = SEGMENT_INDEX.stat()
    return {
        "model": MODEL_NAME,
        "dimensions": dimensions,
        "segment_index": {
            "path": str(SEGMENT_INDEX),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        },
        "include_tool_logs": include_tool_logs,
    }


def public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    result = dict(manifest)
    result.pop("source_fingerprint", None)
    return result


def build_vector_index(
    *,
    dimensions: int = DEFAULT_DIMENSIONS,
    include_tool_logs: bool = True,
    force: bool = False,
    auto_build_segments: bool = True,
) -> dict[str, Any]:
    if dimensions <= 0:
        raise SystemExit("--dimensions must be positive.")
    if auto_build_segments and not SEGMENT_INDEX.exists():
        build_index(include_tool_logs=include_tool_logs)
    if not SEGMENT_INDEX.exists():
        raise SystemExit(f"Record index not found: {SEGMENT_INDEX}. Run index_segments.py first.")

    fingerprint = source_fingerprint(dimensions=dimensions, include_tool_logs=include_tool_logs)
    existing = read_json(VECTOR_MANIFEST, {})
    if (
        not force
        and VECTOR_INDEX.exists()
        and existing.get("source_fingerprint") == fingerprint
    ):
        skipped = dict(existing)
        skipped["skipped"] = True
        skipped["skip_reason"] = "inputs_unchanged"
        return public_manifest(skipped)

    segments = read_jsonl(SEGMENT_INDEX)
    validate_record_level_segments(segments)
    records: list[dict[str, Any]] = []
    source_types: dict[str, int] = {}
    for segment in segments:
        text = str(segment.get("text", ""))
        vector = vectorize_text(text, dimensions=dimensions)
        if not vector:
            continue
        source_type = str(segment.get("source_type", ""))
        source_types[source_type] = source_types.get(source_type, 0) + 1
        records.append(
            {
                "id": stable_id("vec", str(segment.get("id", "")), MODEL_NAME, str(dimensions)),
                "segment_id": segment.get("id", ""),
                "source_id": segment.get("source_id", ""),
                "source_type": source_type,
                "session_id": segment.get("session_id", ""),
                "timestamp": segment.get("timestamp", ""),
                "path": segment.get("path", ""),
                "record_level": True,
                "chunked": False,
                "segment_index": 0,
                "record_characters": int(segment.get("record_characters", len(text))),
                "text_preview": trim_text(text, 500),
                "text_preview_is_authoritative": False,
                "vector_model": MODEL_NAME,
                "dimensions": dimensions,
                "vector": vector,
                "topics": segment.get("topics", []),
            }
        )

    write_jsonl(VECTOR_INDEX, records)
    manifest = {
        "generated_at": now_iso(),
        "record_count": len(records),
        "source_types": source_types,
        "index": str(VECTOR_INDEX),
        "source_index": str(SEGMENT_INDEX),
        "vector_model": MODEL_NAME,
        "dimensions": dimensions,
        "indexing_mode": "record_level_no_split",
        "local_only": True,
        "skipped": False,
        "source_fingerprint": fingerprint,
        "no_split_policy": NO_SPLIT_POLICY,
        "note": "Read-only vector sidecar. It ranks whole evidence records and does not update WORLD_STATE.",
    }
    write_json(VECTOR_MANIFEST, manifest)
    return public_manifest(manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local record-level vector index for evidence lookup.")
    parser.add_argument("--dimensions", type=int, default=DEFAULT_DIMENSIONS, help="Hash vector dimensions.")
    parser.add_argument("--skip-tool-logs", action="store_true", help="When auto-building the record index, skip logs/tool_calls/*.jsonl.")
    parser.add_argument("--no-build", action="store_true", help="Do not auto-build the record index if it is missing.")
    parser.add_argument("--force", action="store_true", help="Rebuild even when source index inputs are unchanged.")
    args = parser.parse_args()
    result = build_vector_index(
        dimensions=args.dimensions,
        include_tool_logs=not args.skip_tool_logs,
        force=args.force,
        auto_build_segments=not args.no_build,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
