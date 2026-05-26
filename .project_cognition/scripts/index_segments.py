#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import (
    COGNITION_ROOT,
    INDEX_MANIFEST,
    SEGMENT_INDEX,
    TOOL_EVIDENCE,
    USER_UTTERANCES,
    now_iso,
    read_json,
    read_jsonl,
    stable_id,
    trim_text,
    write_json,
    write_jsonl,
)


DEFAULT_MAX_CHARS = 900


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(COGNITION_ROOT.parent))
    except ValueError:
        return str(path)


def record_text(text: str) -> str:
    return "\n".join(str(text).strip().splitlines())


def segment_record(
    *,
    source_id: str,
    source_type: str,
    text: str,
    path: Path,
    session_id: str = "",
    timestamp: str = "",
    topics: list[str] | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[dict[str, Any]]:
    full_text = record_text(text)
    if not full_text:
        return []
    return [
        {
            "id": stable_id("seg", source_type, source_id, "record"),
            "source_id": source_id,
            "source_type": source_type,
            "session_id": session_id,
            "timestamp": timestamp,
            "path": relative(path),
            "segment_index": 0,
            "text": full_text,
            "snippet": trim_text(full_text, 320),
            "topics": topics or [],
            "record_level": True,
            "chunked": False,
            "record_characters": len(full_text),
        }
    ]


def user_segments(max_chars: int) -> list[dict[str, Any]]:
    path = USER_UTTERANCES
    rows: list[dict[str, Any]] = []
    for record in read_jsonl(path):
        rows.extend(
            segment_record(
                source_id=str(record.get("id", "")),
                source_type="user_utterance",
                text=str(record.get("text", "")),
                path=path,
                session_id=str(record.get("session_id", "")),
                timestamp=str(record.get("timestamp", "")),
                topics=list(record.get("linked_topics", [])),
                max_chars=max_chars,
            )
        )
    return rows


def tool_evidence_segments(max_chars: int) -> list[dict[str, Any]]:
    path = TOOL_EVIDENCE
    rows: list[dict[str, Any]] = []
    for record in read_jsonl(path):
        text = str(record.get("content_summary", ""))
        rows.extend(
            segment_record(
                source_id=str(record.get("id", "")),
                source_type="tool_evidence",
                text=text,
                path=path,
                session_id=str(record.get("session_id", "")),
                timestamp=str(record.get("timestamp", "")),
                topics=list(record.get("linked_topics", [])),
                max_chars=max_chars,
            )
        )
    return rows


def tool_call_segments(max_chars: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    log_dir = COGNITION_ROOT / "logs" / "tool_calls"
    if not log_dir.exists():
        return rows
    for path in sorted(log_dir.glob("*.jsonl")):
        for record in read_jsonl(path):
            rows.extend(
                segment_record(
                    source_id=str(record.get("id", "")),
                    source_type="tool_call",
                    text=str(record.get("content", "")),
                    path=path,
                    session_id=str(record.get("session_id", "")),
                    timestamp=str(record.get("timestamp", "")),
                    topics=[],
                    max_chars=max_chars,
                )
            )
    return rows


def input_paths(include_tool_logs: bool) -> list[Path]:
    paths = [USER_UTTERANCES, TOOL_EVIDENCE]
    log_dir = COGNITION_ROOT / "logs" / "tool_calls"
    if include_tool_logs and log_dir.exists():
        paths.extend(sorted(log_dir.glob("*.jsonl")))
    return [path for path in paths if path.exists()]


def source_fingerprint(max_chars: int, include_tool_logs: bool) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in input_paths(include_tool_logs):
        stat = path.stat()
        files.append(
            {
                "path": relative(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return {
        "indexing_mode": "record_level_no_split",
        "include_tool_logs": include_tool_logs,
        "files": files,
    }


def public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    result = dict(manifest)
    fingerprint = result.pop("source_fingerprint", {})
    files = fingerprint.get("files", []) if isinstance(fingerprint, dict) else []
    result["source_file_count"] = len(files)
    return result


def dedupe_records(segments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    duplicates = 0
    for segment in segments:
        source_id = str(segment.get("source_id", ""))
        key = (str(segment.get("source_type", "")), source_id or str(segment.get("id", "")))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(segment)
    return unique, duplicates


def build_index(max_chars: int = DEFAULT_MAX_CHARS, include_tool_logs: bool = True, force: bool = False) -> dict[str, Any]:
    fingerprint = source_fingerprint(max_chars=max_chars, include_tool_logs=include_tool_logs)
    existing = read_json(INDEX_MANIFEST, {})
    if (
        not force
        and SEGMENT_INDEX.exists()
        and existing.get("source_fingerprint") == fingerprint
    ):
        skipped = dict(existing)
        skipped["skipped"] = True
        skipped["skip_reason"] = "inputs_unchanged"
        return public_manifest(skipped)

    segments = [*user_segments(max_chars), *tool_evidence_segments(max_chars)]
    if include_tool_logs:
        segments.extend(tool_call_segments(max_chars))
    segments, duplicate_records = dedupe_records(segments)

    write_jsonl(SEGMENT_INDEX, segments)
    source_types: dict[str, int] = {}
    for segment in segments:
        source_types[segment["source_type"]] = source_types.get(segment["source_type"], 0) + 1
    manifest = {
        "generated_at": now_iso(),
        "segment_count": len(segments),
        "source_types": source_types,
        "index": str(SEGMENT_INDEX),
        "indexing_mode": "record_level_no_split",
        "local_only": True,
        "skipped": False,
        "duplicate_records_dropped": duplicate_records,
        "source_fingerprint": fingerprint,
        "no_split_policy": "Retrieval may rank or embed whole evidence records, but must not split records into authoritative memory chunks.",
        "note": "Read-only record-level evidence lookup sidecar. It does not split evidence and does not update WORLD_STATE.",
    }
    write_json(INDEX_MANIFEST, manifest)
    return public_manifest(manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local record-level evidence lookup index for on-demand lookup.")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="Deprecated compatibility flag. Evidence is indexed as whole records.")
    parser.add_argument("--skip-tool-logs", action="store_true", help="Index raw tool evidence but skip logs/tool_calls/*.jsonl.")
    parser.add_argument("--force", action="store_true", help="Rebuild the index even when indexed source files are unchanged.")
    args = parser.parse_args()
    result = build_index(max_chars=args.max_chars, include_tool_logs=not args.skip_tool_logs, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
