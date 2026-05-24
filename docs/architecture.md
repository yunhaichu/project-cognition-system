# Architecture

Project Cognition System separates project understanding into layers:

1. Raw fact layer: user utterances, normalized tool evidence, real files, test results.
2. Agent interpretation layer: what the agent believed, with confidence and possible misreadings.
3. Strategy layer: current route, current phase, rejected routes, temporary decisions.
4. User profile layer: slow-changing cross-project preferences, stored globally per agent.
5. Log layer: assistant outputs, tool calls, and session material for audit only.

Only high-confidence, stable, non-conflicted cognition should enter `WORLD_STATE.md`.

## Evidence Layers

Tool calls are split into audit logs and formal evidence:

- `logs/tool_calls/<session>.jsonl` stores the full tool call output for audit.
- `raw/tool_evidence.jsonl` stores a normalized record with `evidence_kind`, `deterministic`, `outcome`, `source_log_id`, and a bounded `content_summary`.

Supported tool evidence kinds are `test_result`, `git_result`, `filesystem_result`, `web_result`, and `command_output`. Tool evidence can raise confidence above agent interpretation, but tool-only candidates remain below automatic `WORLD_STATE.md` inclusion unless accepted through review.

## Structured Cognition

Candidates keep a human-readable `claim`, but also carry a minimal structured object:

```json
{
  "subject": "project_cognition_system",
  "predicate": "requires",
  "object": "do not bulk-inject history",
  "scope": "project",
  "modality": "must_not",
  "valid_from": "2026-05-24T00:00:00Z",
  "valid_until": null,
  "source_refs": ["utt_xxx"],
  "confidence_reason": "Extracted by local rule from user_utterance.",
  "supersedes": []
}
```

The structured fields are intentionally small. They give conflict detection and review a stable handle without turning the MVP into a database or semantic platform.

## Conflict Lifecycle

`detect_conflicts.py` records potential contradictions and blocks unresolved high-severity items. `resolve_conflict.py` adds the review path:

- `choose-a` or `choose-b`: mark one side as chosen and supersede the losing cognition.
- `defer`: keep both sides out of `WORLD_STATE.md` until more evidence exists.
- `mark-resolved`: record that a conflict was resolved externally.

After resolution, rerun `score_candidates.py` and `build_world_state.py`.

## Why Not Just Memory?

Large memory stores introduce new failure modes:

- unreliable memories
- irrelevant retrieval
- context overflow from retrieved memories
- conflicts between old and new facts
- agent-generated summaries replacing user evidence

This system treats memory as governed evidence, not as trusted context.

## Compact Context

Hooks should inject `WORLD_STATE_COMPACT.md` plus a compact user profile. Raw evidence should be read only through targeted lookup when a task requires it.

## Eval

`evals/run_minimal_eval.py` runs the pipeline in a temporary project copy and checks the core governance invariants: user evidence goes to raw, assistant output stays in logs, tool output becomes formal evidence, candidates are structured, tool-only candidates require review, and compact state remains small.
