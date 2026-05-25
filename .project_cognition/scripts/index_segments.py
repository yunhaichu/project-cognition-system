#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import (
    COGNITION_ROOT,
    INDEX_MANIFEST,
    SEGMENT_INDEX,
    TOOL_EVIDENCE,
    USER_UTTERANCES,
    now_iso,
    read_jsonl,
    stable_id,
    trim_text,
    write_json,
    write_jsonl,
)


DEFAULT_MAX_CHARS = 900
DEFAULT_OVERLAP = 120


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(COGNITION_ROOT.parent))
    except ValueError:
        return str(path)


def split_text(text: str, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP) -> list[str]:
    collapsed = re.sub(r"\s+", " ", str(text)).strip()
    if not collapsed:
        return []
    if len(collapsed) <= max_chars:
        return [collapsed]

    chunks: list[str] = []
    start = 0
    while start < len(collapsed):
        end = min(len(collapsed), start + max_chars)
        if end < len(collapsed):
            boundary = max(
                collapsed.rfind("。", start, end),
                collapsed.rfind(".", start, end),
                collapsed.rfind("；", start, end),
                collapsed.rfind(";", start, end),
                collapsed.rfind(" ", start, end),
            )
            if boundary > start + max_chars // 2:
                end = boundary + 1
        chunks.append(collapsed[start:end].strip())
        if end >= len(collapsed):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


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
    segments: list[dict[str, Any]] = []
    for index, chunk in enumerate(split_text(text, max_chars=max_chars)):
        segments.append(
            {
                "id": stable_id("seg", source_type, source_id, str(index), chunk),
                "source_id": source_id,
                "source_type": source_type,
                "session_id": session_id,
                "timestamp": timestamp,
                "path": relative(path),
                "segment_index": index,
                "text": chunk,
                "snippet": trim_text(chunk, 320),
                "topics": topics or [],
            }
        )
    return segments


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


def build_index(max_chars: int = DEFAULT_MAX_CHARS, include_tool_logs: bool = True) -> dict[str, Any]:
    segments = [*user_segments(max_chars), *tool_evidence_segments(max_chars)]
    if include_tool_logs:
        segments.extend(tool_call_segments(max_chars))

    write_jsonl(SEGMENT_INDEX, segments)
    source_types: dict[str, int] = {}
    for segment in segments:
        source_types[segment["source_type"]] = source_types.get(segment["source_type"], 0) + 1
    manifest = {
        "generated_at": now_iso(),
        "segment_count": len(segments),
        "source_types": source_types,
        "index": str(SEGMENT_INDEX),
        "local_only": True,
        "note": "Read-only evidence lookup sidecar. It does not update WORLD_STATE.",
    }
    write_json(INDEX_MANIFEST, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local evidence segment index for on-demand lookup.")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="Maximum characters per segment.")
    parser.add_argument("--skip-tool-logs", action="store_true", help="Index raw tool evidence but skip logs/tool_calls/*.jsonl.")
    args = parser.parse_args()
    result = build_index(max_chars=args.max_chars, include_tool_logs=not args.skip_tool_logs)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
