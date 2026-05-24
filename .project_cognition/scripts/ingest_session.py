#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import (
    AGENT_INTERPRETATIONS,
    COGNITION_ROOT,
    TOOL_EVIDENCE,
    USER_UTTERANCES,
    append_jsonl,
    classify_tool_evidence,
    detect_signals,
    detect_topics,
    importance_from_signals,
    make_id,
    now_iso,
    read_jsonl,
    write_json,
)


def message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            for key in ["text", "input_text", "output_text"]:
                value = item.get(key)
                if isinstance(value, str):
                    parts.append(value)
                    break
    return "\n".join(part for part in parts if part)


def looks_like_synthetic_user_text(text: str) -> bool:
    stripped = text.lstrip()
    synthetic_prefixes = (
        "<permissions instructions>",
        "<app-context>",
        "<skills_instructions>",
        "<plugins_instructions>",
        "<environment_context>",
        "## Memory\n",
        "# Codex",
    )
    return stripped.startswith(synthetic_prefixes)


def normalize_codex_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    has_event_user_messages = any(
        record.get("type") == "event_msg" and record.get("payload", {}).get("type") == "user_message"
        for record in records
    )
    normalized: list[dict[str, Any]] = []
    for record in records:
        if "role" in record:
            normalized.append(record)
            continue

        timestamp = str(record.get("timestamp") or now_iso())
        record_type = record.get("type")
        payload = record.get("payload", {})

        if record_type == "event_msg" and payload.get("type") == "user_message":
            content = str(payload.get("message") or "")
            if content and not looks_like_synthetic_user_text(content):
                normalized.append({"role": "user", "content": content, "timestamp": timestamp})
            continue

        if record_type != "response_item" or not isinstance(payload, dict):
            continue

        if payload.get("type") == "message":
            role = str(payload.get("role", "")).lower()
            if role not in {"user", "assistant"}:
                continue
            if role == "user" and has_event_user_messages:
                continue
            content = message_content(payload.get("content"))
            if not content:
                continue
            if role == "user" and looks_like_synthetic_user_text(content):
                continue
            normalized.append({"role": role, "content": content, "timestamp": timestamp})
        elif payload.get("type") in {"function_call_output", "custom_tool_call"}:
            content = str(payload.get("output") or payload.get("input") or "")
            if content:
                normalized.append(
                    {
                        "role": "tool",
                        "name": str(payload.get("name") or payload.get("type") or "tool"),
                        "content": content[:20000],
                        "timestamp": timestamp,
                    }
                )
    return normalized


def load_records(input_path: Path, input_format: str) -> list[dict[str, Any]]:
    if input_format == "text" or (input_format == "auto" and input_path.suffix.lower() != ".jsonl"):
        return [{"role": "user", "content": input_path.read_text(encoding="utf-8"), "timestamp": now_iso()}]

    records: list[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL input at line {line_no}: {exc}") from exc
    return normalize_codex_records(records)


def ingest_user(
    record: dict[str, Any],
    session_id: str,
    existing_texts: list[str],
    existing_keys: set[tuple[str, str, str]],
    source: str,
) -> tuple[dict[str, Any], bool]:
    text = str(record.get("content", ""))
    timestamp = str(record.get("timestamp") or now_iso())
    signals = detect_signals(text, existing_texts)
    dedupe_key = (session_id, timestamp, text)
    utterance = {
        "id": make_id("utt", f"{session_id}:{text}", timestamp),
        "session_id": session_id,
        "timestamp": timestamp,
        "text": text,
        "source": source,
        "importance_score": importance_from_signals(text, signals),
        "signals": signals,
        "linked_topics": detect_topics(text),
        "notes": "",
    }
    if dedupe_key in existing_keys:
        return utterance, False
    append_jsonl(USER_UTTERANCES, utterance)
    existing_keys.add(dedupe_key)
    return utterance, True


def ingest_assistant(record: dict[str, Any], session_id: str, existing_ids: set[str]) -> tuple[dict[str, Any], bool]:
    content = str(record.get("content", ""))
    timestamp = str(record.get("timestamp") or now_iso())
    output = {
        "id": make_id("out", content, timestamp),
        "session_id": session_id,
        "timestamp": timestamp,
        "content": content,
        "note": "Assistant final output is stored as a log, not core cognition.",
    }
    if output["id"] in existing_ids:
        return output, False
    append_jsonl(COGNITION_ROOT / "logs" / "outputs" / f"{session_id}.jsonl", output)
    existing_ids.add(output["id"])
    return output, True


def tool_evidence_from_call(tool_call: dict[str, Any]) -> dict[str, Any]:
    classification = classify_tool_evidence(str(tool_call.get("name", "")), str(tool_call.get("content", "")))
    content = str(tool_call.get("content", ""))
    return {
        "id": make_id("tool_ev", f"{tool_call.get('name', '')}:{content}", str(tool_call.get("timestamp") or now_iso())),
        "session_id": tool_call["session_id"],
        "timestamp": tool_call["timestamp"],
        "tool_name": tool_call["name"],
        "source_log_id": tool_call["id"],
        "source": "tool",
        "content_summary": content[:1200],
        "linked_topics": detect_topics(content),
        "notes": "",
        **classification,
    }


def ingest_tool(
    record: dict[str, Any],
    session_id: str,
    existing_ids: set[str],
    existing_evidence_ids: set[str],
) -> tuple[dict[str, Any], bool, bool]:
    content = str(record.get("content", ""))
    timestamp = str(record.get("timestamp") or now_iso())
    tool_call = {
        "id": make_id("tool", f"{record.get('name', '')}:{content}", timestamp),
        "session_id": session_id,
        "timestamp": timestamp,
        "name": str(record.get("name") or "tool"),
        "content": content,
    }
    wrote_log = False
    if tool_call["id"] not in existing_ids:
        append_jsonl(COGNITION_ROOT / "logs" / "tool_calls" / f"{session_id}.jsonl", tool_call)
        existing_ids.add(tool_call["id"])
        wrote_log = True

    evidence = tool_evidence_from_call(tool_call)
    wrote_evidence = False
    if evidence["id"] not in existing_evidence_ids:
        append_jsonl(TOOL_EVIDENCE, evidence)
        existing_evidence_ids.add(evidence["id"])
        wrote_evidence = True
    return tool_call, wrote_log, wrote_evidence


def ingest_records(records: list[dict[str, Any]], session_id: str, source: str, input_path: Path) -> dict[str, Any]:
    existing_user_records = read_jsonl(USER_UTTERANCES)
    existing_texts = [record.get("text", "") for record in existing_user_records]
    existing_user_keys = {
        (str(record.get("session_id", "")), str(record.get("timestamp", "")), str(record.get("text", "")))
        for record in existing_user_records
    }
    output_path = COGNITION_ROOT / "logs" / "outputs" / f"{session_id}.jsonl"
    tool_path = COGNITION_ROOT / "logs" / "tool_calls" / f"{session_id}.jsonl"
    existing_output_ids = {record.get("id", "") for record in read_jsonl(output_path)}
    existing_tool_ids = {record.get("id", "") for record in read_jsonl(tool_path)}
    existing_tool_evidence_ids = {record.get("id", "") for record in read_jsonl(TOOL_EVIDENCE)}
    counts = {"user": 0, "assistant": 0, "tool": 0, "tool_evidence": 0, "ignored": 0, "duplicates": 0}
    first_timestamp = records[0].get("timestamp") if records else now_iso()
    last_timestamp = records[-1].get("timestamp") if records else now_iso()

    for record in records:
        role = str(record.get("role", "")).lower()
        if role == "user":
            utterance, written = ingest_user(record, session_id, existing_texts, existing_user_keys, source)
            if written:
                existing_texts.append(utterance["text"])
                counts["user"] += 1
            else:
                counts["duplicates"] += 1
        elif role == "assistant":
            _, written = ingest_assistant(record, session_id, existing_output_ids)
            counts["assistant" if written else "duplicates"] += 1
        elif role == "tool":
            _, wrote_log, wrote_evidence = ingest_tool(record, session_id, existing_tool_ids, existing_tool_evidence_ids)
            counts["tool" if wrote_log else "duplicates"] += 1
            if wrote_evidence:
                counts["tool_evidence"] += 1
        else:
            counts["ignored"] += 1

    metadata = {
        "session_id": session_id,
        "input": str(input_path),
        "source": source,
        "ingested_at": now_iso(),
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "counts": counts,
        "agent_interpretations_file": str(AGENT_INTERPRETATIONS.relative_to(COGNITION_ROOT)),
    }
    write_json(COGNITION_ROOT / "logs" / "sessions" / f"{session_id}.json", metadata)
    write_json(COGNITION_ROOT / "raw" / "sessions" / f"{session_id}.json", metadata)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a simple session JSONL or text file into project cognition raw/log layers.")
    parser.add_argument("--input", required=True, help="Path to a simple JSONL session file or plain text file.")
    parser.add_argument("--session-id", required=True, help="Stable session id for this import.")
    parser.add_argument("--source", default="chat", help="Source label for user utterances. Default: chat.")
    parser.add_argument("--format", choices=["auto", "jsonl", "text"], default="auto", help="Input format. Default: auto.")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    records = load_records(input_path, args.format)
    metadata = ingest_records(records, args.session_id, args.source, input_path)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
