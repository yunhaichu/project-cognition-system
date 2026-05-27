#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PREFIXES = ("utt_", "interp_", "tool_ev_", "ev_")
COGNITION_PREFIXES = ("cog_",)
CONFLICT_PREFIXES = ("conflict_",)


class ValidationError(ValueError):
    pass


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[Any]:
    if not path.exists():
        return []
    rows: list[Any] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValidationError(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return rows


def type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def validate_value(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(type_matches(value, item) for item in expected_types):
            errors.append(f"{path}: expected type {'/'.join(expected_types)}, got {type(value).__name__}")
            return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']}, got {value!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: expected >= {schema['minimum']}, got {value}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: expected <= {schema['maximum']}, got {value}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: missing required field")
        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in value:
                errors.extend(validate_value(value[key], child_schema, f"{path}.{key}"))

    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(validate_value(item, schema["items"], f"{path}[{index}]"))
    return errors


def load_schema(root: Path, name: str) -> dict[str, Any]:
    return read_json(root / ".project_cognition" / "schemas" / name)


def validate_json_file(path: Path, schema: dict[str, Any], label: str) -> tuple[int, list[str]]:
    if not path.exists():
        return 0, []
    value = read_json(path)
    return 1, validate_value(value, schema, label)


def validate_jsonl_file(path: Path, schema: dict[str, Any], label: str) -> tuple[int, list[str]]:
    if not path.exists():
        return 0, []
    rows = read_jsonl(path)
    errors: list[str] = []
    for index, row in enumerate(rows, 1):
        errors.extend(validate_value(row, schema, f"{label}:{index}"))
    return len(rows), errors


def validate_confidence_table(root: Path) -> tuple[int, list[str]]:
    table_path = root / ".project_cognition" / "distilled" / "confidence_table.json"
    if not table_path.exists():
        return 0, []
    table_schema = load_schema(root, "confidence_table.schema.json")
    item_schema = load_schema(root, "cognition_candidate.schema.json")
    table = read_json(table_path)
    errors = validate_value(table, table_schema, "distilled/confidence_table.json")
    rows = table.get("items", []) if isinstance(table, dict) else []
    if isinstance(rows, list):
        for index, item in enumerate(rows):
            errors.extend(validate_value(item, item_schema, f"distilled/confidence_table.json.items[{index}]"))
    return len(rows), errors


def ids_by_record(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("id", "")) for row in rows if row.get("id")}


def reference_like(value: str, prefixes: tuple[str, ...]) -> bool:
    return any(value.startswith(prefix) for prefix in prefixes)


def validate_reference(value: str, valid_ids: set[str], label: str, kind: str, prefixes: tuple[str, ...] | None = None) -> list[str]:
    if not value:
        return []
    if value in valid_ids:
        return []
    if prefixes is None or reference_like(value, prefixes):
        return [f"{label}: unknown {kind} reference {value!r}"]
    return []


def validate_references(values: list[Any], valid_ids: set[str], label: str, kind: str, prefixes: tuple[str, ...] | None = None) -> list[str]:
    errors: list[str] = []
    for index, value in enumerate(values):
        errors.extend(validate_reference(str(value), valid_ids, f"{label}[{index}]", kind, prefixes))
    return errors


def read_all_tool_logs(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    log_dir = root / ".project_cognition" / "logs" / "tool_calls"
    if not log_dir.exists():
        return rows
    for path in sorted(log_dir.glob("*.jsonl")):
        rows.extend(read_jsonl(path))
    return rows


def validate_cross_references(root: Path) -> tuple[int, list[str]]:
    cognition_root = root / ".project_cognition"
    utterances = read_jsonl(cognition_root / "raw" / "user_utterances.jsonl")
    interpretations = read_jsonl(cognition_root / "raw" / "agent_interpretations.jsonl")
    tool_evidence = read_jsonl(cognition_root / "raw" / "tool_evidence.jsonl")
    decisions = read_jsonl(cognition_root / "raw" / "decisions.jsonl")
    conflicts = read_jsonl(cognition_root / "raw" / "conflicts.jsonl")
    proposals = read_jsonl(cognition_root / "proposals" / "proposed_updates.jsonl")
    confidence_table = read_json(cognition_root / "distilled" / "confidence_table.json") if (cognition_root / "distilled" / "confidence_table.json").exists() else {"items": []}
    cognition_items = confidence_table.get("items", []) if isinstance(confidence_table, dict) else []

    utterance_ids = ids_by_record(utterances)
    interpretation_ids = ids_by_record(interpretations)
    tool_evidence_ids = ids_by_record(tool_evidence)
    evidence_ids = utterance_ids | interpretation_ids | tool_evidence_ids
    cognition_ids = ids_by_record(cognition_items)
    conflict_ids = ids_by_record(conflicts)
    tool_log_ids = ids_by_record(read_all_tool_logs(root))

    errors: list[str] = []

    for index, row in enumerate(interpretations, 1):
        errors.extend(
            validate_references(
                row.get("based_on_utterance_ids", []),
                utterance_ids,
                f"raw/agent_interpretations.jsonl:{index}.based_on_utterance_ids",
                "user utterance",
                ("utt_",),
            )
        )

    for index, row in enumerate(tool_evidence, 1):
        source_log_id = str(row.get("source_log_id", ""))
        if source_log_id and source_log_id not in tool_log_ids:
            errors.append(f"raw/tool_evidence.jsonl:{index}.source_log_id: unknown tool log reference {source_log_id!r}")

    for index, row in enumerate(decisions, 1):
        errors.extend(
            validate_references(
                row.get("evidence_utterance_ids", []),
                utterance_ids,
                f"raw/decisions.jsonl:{index}.evidence_utterance_ids",
                "user utterance",
                ("utt_",),
            )
        )

    for index, row in enumerate(conflicts, 1):
        label = f"raw/conflicts.jsonl:{index}"
        item_a = str(row.get("item_a", ""))
        item_b = str(row.get("item_b", ""))
        chosen_side = str(row.get("chosen_side", ""))
        errors.extend(validate_reference(item_a, cognition_ids, f"{label}.item_a", "cognition item", COGNITION_PREFIXES))
        errors.extend(validate_reference(item_b, cognition_ids, f"{label}.item_b", "cognition item", COGNITION_PREFIXES))
        if chosen_side and chosen_side not in {item_a, item_b}:
            errors.append(f"{label}.chosen_side: expected item_a or item_b, got {chosen_side!r}")
        audit = row.get("audit_summary", {})
        if isinstance(audit, dict):
            for key in ["chosen", "loser"]:
                errors.extend(validate_reference(str(audit.get(key, "")), cognition_ids, f"{label}.audit_summary.{key}", "cognition item", COGNITION_PREFIXES))
            errors.extend(
                validate_references(
                    audit.get("supersedes", []),
                    cognition_ids,
                    f"{label}.audit_summary.supersedes",
                    "cognition item",
                    COGNITION_PREFIXES,
                )
            )

    for index, row in enumerate(cognition_items):
        label = f"distilled/confidence_table.json.items[{index}]"
        errors.extend(validate_references(row.get("evidence", []), evidence_ids, f"{label}.evidence", "evidence", EVIDENCE_PREFIXES))
        errors.extend(validate_references(row.get("conflicts", []), conflict_ids, f"{label}.conflicts", "conflict", CONFLICT_PREFIXES))
        superseded_by = str(row.get("superseded_by", ""))
        errors.extend(validate_reference(superseded_by, cognition_ids, f"{label}.superseded_by", "cognition item", COGNITION_PREFIXES))
        structured = row.get("structured", {})
        if isinstance(structured, dict):
            errors.extend(
                validate_references(
                    structured.get("source_refs", []),
                    evidence_ids,
                    f"{label}.structured.source_refs",
                    "evidence",
                    EVIDENCE_PREFIXES,
                )
            )
            errors.extend(
                validate_references(
                    structured.get("supersedes", []),
                    cognition_ids,
                    f"{label}.structured.supersedes",
                    "cognition item",
                    COGNITION_PREFIXES,
                )
            )

    for index, row in enumerate(proposals, 1):
        label = f"proposals/proposed_updates.jsonl:{index}"
        errors.extend(validate_references(row.get("evidence", []), evidence_ids, f"{label}.evidence", "evidence", EVIDENCE_PREFIXES))
        errors.extend(validate_references(row.get("conflicts", []), conflict_ids, f"{label}.conflicts", "conflict", CONFLICT_PREFIXES))
        structured = row.get("structured", {})
        if isinstance(structured, dict):
            errors.extend(
                validate_references(
                    structured.get("source_refs", []),
                    evidence_ids,
                    f"{label}.structured.source_refs",
                    "evidence",
                    EVIDENCE_PREFIXES,
                )
            )
            errors.extend(
                validate_references(
                    structured.get("supersedes", []),
                    cognition_ids,
                    f"{label}.structured.supersedes",
                    "cognition item",
                    COGNITION_PREFIXES,
                )
            )

    checked = (
        len(interpretations)
        + len(tool_evidence)
        + len(decisions)
        + len(conflicts)
        + len(cognition_items)
        + len(proposals)
    )
    return checked, errors


def validate_state(root: Path) -> dict[str, Any]:
    targets = [
        ("raw/user_utterances.jsonl", "user_utterance.schema.json", "jsonl"),
        ("raw/agent_interpretations.jsonl", "agent_interpretation.schema.json", "jsonl"),
        ("raw/tool_evidence.jsonl", "tool_evidence.schema.json", "jsonl"),
        ("raw/decisions.jsonl", "decision.schema.json", "jsonl"),
        ("raw/conflicts.jsonl", "conflict.schema.json", "jsonl"),
        ("proposals/proposed_updates.jsonl", "proposed_update.schema.json", "jsonl"),
        ("distilled/state_version.json", "state_version.schema.json", "json"),
    ]
    summary: dict[str, Any] = {
        "target_root": str(root),
        "validated": {},
        "errors": [],
    }
    for relative_path, schema_name, kind in targets:
        path = root / ".project_cognition" / relative_path
        schema = load_schema(root, schema_name)
        if kind == "jsonl":
            count, errors = validate_jsonl_file(path, schema, relative_path)
        else:
            count, errors = validate_json_file(path, schema, relative_path)
        summary["validated"][relative_path] = {"records": count, "errors": len(errors)}
        summary["errors"].extend(errors)

    count, errors = validate_confidence_table(root)
    summary["validated"]["distilled/confidence_table.json"] = {"records": count, "errors": len(errors)}
    summary["errors"].extend(errors)

    count, errors = validate_cross_references(root)
    summary["validated"]["cross_references"] = {"records": count, "errors": len(errors)}
    summary["errors"].extend(errors)
    summary["ok"] = not summary["errors"]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Project Cognition JSON/JSONL state using the bundled schema subset.")
    parser.add_argument("--target-root", default=".", help="Project root containing .project_cognition. Default: current directory.")
    args = parser.parse_args()

    root = Path(args.target_root).resolve()
    if not (root / ".project_cognition").exists():
        raise SystemExit(f"No .project_cognition directory under {root}")
    result = validate_state(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
