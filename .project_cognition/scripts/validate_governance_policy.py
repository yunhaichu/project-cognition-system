#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from auto_governance_gate import GOVERNANCE_POLICY, merge_policy, policy_hash, resolve_policy_path
from validate_state import load_schema, validate_json_file


PROJECT_ROOT = GOVERNANCE_POLICY.parents[1]


def validate_policy(path: Path) -> dict[str, object]:
    schema = load_schema(PROJECT_ROOT, "governance_policy.schema.json")
    count, errors = validate_json_file(path, schema, "rules/governance_policy.json")
    policy = merge_policy(json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})
    return {
        "policy_path": str(path),
        "records": count,
        "errors": errors,
        "error_count": len(errors),
        "policy_version": int(policy.get("version", 0)),
        "policy_hash": policy_hash(policy),
        "ok": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate governance policy schema and report its hash.")
    parser.add_argument("--policy", help="Policy path. Defaults to .project_cognition/rules/governance_policy.json.")
    args = parser.parse_args()
    path = resolve_policy_path(args.policy)
    result = validate_policy(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
