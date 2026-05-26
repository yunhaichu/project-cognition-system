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

Supported tool evidence kinds are `test_result`, `git_result`, `filesystem_result`, `web_result`, and `command_output`. The scoring layer indexes `tool_evidence` directly. Deterministic test, git, and filesystem results score above agent interpretation. Web results and generic command output are weaker. Tool-only candidates remain below automatic `WORLD_STATE.md` inclusion unless accepted through review.

The retrieval sidecar is record-level. It may score or vectorize whole user utterance, tool evidence, or tool-call records, but it must not split those records into authoritative memory chunks. Lookup results can show short previews for triage, yet the stable evidence remains the full raw record addressed by `source_id` and `path`.

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

`predicate` is normalized to a small local enum. Specific predicates include `enter_core_memory`, `store_log`, `create`, `render`, `override`, `require_review`, `inject_context`, `call_llm`, `read_source`, `update_world_state`, `score_evidence`, `resolve_conflict`, and `test_passed`. The fallback predicates `states`, `requires`, `observed`, and `infers` are kept for compatibility and low-confidence extraction.

Structured objects also include `object_key`, a local canonical key for equivalent objects. For example, `assistant final answer`, `agent output`, and `最终输出` can all resolve to the same conflict object without model calls.

Object fixtures live in `evals/golden/object_fixtures.json`, so object canonicalization can grow without silently merging or splitting important concepts.

Conflict detection compares structured fields before falling back to keyword topics. Opposite modality for the same `subject / predicate / object / scope` is a conflict. Different scopes are kept separate, so a project-level prohibition does not automatically conflict with a global-user-level allowance.

## Conflict Lifecycle

`detect_conflicts.py` records potential contradictions and blocks unresolved high-severity items. `resolve_conflict.py` adds the review path:

- `choose-a` or `choose-b`: mark one side as chosen and supersede the losing cognition.
- `defer`: keep both sides out of `WORLD_STATE.md` until more evidence exists.
- `mark-resolved`: record that a conflict was resolved externally.

After resolution, rerun `score_candidates.py` and `build_world_state.py`.

Resolved conflicts include an `audit_summary` with chosen side, loser, supersedes, and blocked status for both sides. This keeps human review inspectable without reading the full confidence table.

## World State Rendering

`WORLD_STATE.md` has two layers:

- bootstrap doctrine: fixed, short guardrails that keep the MVP stable and compact.
- accepted structured cognition: reviewed cognition objects rendered as bounded bullets.

The compact file remains doctrine-heavy by design. Full state can expose accepted structured cognition without pushing raw evidence or logs into the prompt.

`WORLD_STATE_COMPACT.md` may include a tiny high-priority structured cognition summary. Eligibility is deliberately strict: `accepted`, confidence at least 95, `scope=project`, and `modality=must/must_not`, capped at 3 rows.

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

It also checks five drift scenarios: user evidence overriding agent inference, tool evidence overriding agent inference, same rule with different scope not conflicting, conflict resolution superseding the loser, and accepted structured cognition rendering into `WORLD_STATE.md`.

Golden invariants live in `evals/golden/minimal_invariants.json`. They assert behavior such as required checks, scenario coverage, and compact character budget without freezing the exact Markdown prose.

Predicate fixtures live in `evals/golden/predicate_fixtures.json`. They test compound Chinese/English sentences so regex ordering regressions are visible.

The regression suite includes negative and multi-session cases:

- assistant-only claims do not enter core memory
- web results do not outrank user utterances
- low-confidence accepted cognition and `user_global` cognition do not enter project compact state
- deferred conflicts keep both sides blocked
- superseded rules do not revive in later sessions
- compact state keeps only the current high-priority project rule
- sequential multi-transcript ingestion keeps reviewed rules, supersedes stale rules, and preserves assistant output as logs
- cross-reference validation rejects dangling cognition, conflict, proposal, and evidence references

The eval suite also includes a dogfood case in `evals/cases/dogfood_self_update.jsonl`, where this project records its own tool evidence scoring, structured conflict, and eval scenario work as candidate cognition without allowing assistant output into core memory.

For real-session dogfood, pass exactly one transcript path:

```bash
python evals/run_minimal_eval.py --dogfood-transcript path/to/session.jsonl
```

The eval intentionally does not discover or bulk-read historical transcripts.

Real transcript dogfood summaries may be committed only after redaction. The repository includes one summary at `evals/dogfood/real_codex_transcript_summary_2026-05-24.json`; the raw transcript and local source path are not committed.

## Validation And CI

`validate_state.py` validates the bundled JSON/JSONL state files with a small standard-library schema subset:

```bash
python .project_cognition/scripts/validate_state.py
```

It also checks cross-file references: conflict sides must point to cognition items, proposal conflict ids must exist, source refs must resolve to user/agent/tool evidence, supersedes links must point to cognition items, and tool evidence must point back to its tool log.

GitHub Actions runs Python compilation, schema validation, governance evals, and whitespace checks. These checks only use sanitized fixtures and do not scan real history directories. The workflow is committed at `.github/workflows/ci.yml`, with a copy at `docs/ci/github-actions.yml`.
