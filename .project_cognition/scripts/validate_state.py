#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[1]


class ValidationError(ValueError):
    pass


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[Any]:
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


def validate_state(root: Path) -> dict[str, Any]:
    targets = [
        ("raw/user_utterances.jsonl", "user_utterance.schema.json", "jsonl"),
        ("raw/agent_interpretations.jsonl", "agent_interpretation.schema.json", "jsonl"),
        ("raw/tool_evidence.jsonl", "tool_evidence.schema.json", "jsonl"),
        ("raw/decisions.jsonl", "decision.schema.json", "jsonl"),
        ("raw/conflicts.jsonl", "conflict.schema.json", "jsonl"),
        ("proposals/proposed_updates.jsonl", "proposed_update.schema.json", "jsonl"),
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
