# Context Selection

Core-state admission and task-context injection are separate decisions.

`auto_governance_gate.py` decides what is allowed into governed state. `select_context.py` decides which admitted cognition items are relevant enough to inject for a specific task.

## Command

```bash
python .project_cognition/scripts/select_context.py \
  --session-id codex_20260608 \
  --task "governance policy" \
  --max-chars 1600
```

The script prints the selected context and writes a manifest to:

```text
.project_cognition/logs/context_injections/<session_id>.json
```

## Manifest

The manifest records:

```text
session_id
task
max_chars
included_cognition_ids
excluded_reason_counts
prompt_fingerprint
ruleset_hash
gate_policy_hash
source_manifest
output_characters
mutates_state = false
```

## Invariants

`select_context.py` must not mutate:

```text
.project_cognition/WORLD_STATE.md
.project_cognition/WORLD_STATE_COMPACT.md
.project_cognition/distilled/confidence_table.json
.project_cognition/distilled/governance_gate.json
.project_cognition/raw/*.jsonl
```

It may only write context-injection manifests under `logs/context_injections/`.

This lets later feedback determine whether a drift incident happened because the cognition was not admitted, not selected, over budget, blocked by a conditional conflict, or selected but ignored by the agent.
