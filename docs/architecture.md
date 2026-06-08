# Architecture

Project Cognition System separates project understanding into local, auditable layers. The goal is not larger memory; the goal is governed admission, feedback, rule evolution, and bounded task context.

## Layers

1. Raw fact layer: user utterances, normalized tool evidence, feedback events, conflicts, decisions, and rule-change logs.
2. Agent interpretation layer: what the agent believed, with confidence and possible misreadings.
3. Strategy layer: current route, phase, rejected routes, and temporary decisions.
4. Rule layer: governance policy, scoring weights, bootstrap doctrine, and rule-change proposals.
5. User profile layer: slow-changing cross-project preferences, stored globally per agent and updated proposal-first.
6. Log layer: assistant outputs, tool calls, session material, and context-injection manifests for audit only.

Only high-confidence, stable, non-conflicted, admitted cognition should enter `WORLD_STATE.md`.

## Core Data Flow

```text
session transcript
  -> raw evidence
  -> versioned state upgrade
  -> cognition candidates
  -> scoring
  -> conflict detection
  -> candidate/conflict clustering
  -> automated governance gate
  -> WORLD_STATE.md / WORLD_STATE_COMPACT.md
```

The v0.5 governance loop adds feedback and rule evolution:

```text
feedback event
  -> feedback report
  -> scoring shadow report
  -> rule change proposal
  -> baseline/proposed simulation
  -> forbidden-transition check
  -> explicit apply
  -> rule_change_log
```

## Evidence Layers

Tool calls are split into audit logs and formal evidence:

- `logs/tool_calls/<session>.jsonl` stores full tool-call output for audit.
- `raw/tool_evidence.jsonl` stores normalized records with `evidence_kind`, `deterministic`, `outcome`, `source_log_id`, and bounded `content_summary`.

Supported tool evidence kinds are `test_result`, `git_result`, `filesystem_result`, `web_result`, and `command_output`. Deterministic test, git, and filesystem results score above agent interpretation. Web results and generic command output are weaker. Tool-only candidates remain outside `WORLD_STATE.md` unless the automated governance gate verifies deterministic evidence strength and conflict safety.

`raw/feedback_events.jsonl` records outcomes such as user correction, drift incident, test result, retrieval outcome, gate false accept, and gate false reject. Feedback events do not mutate `WORLD_STATE.md`, `confidence_table.json`, or the governance gate. They are input to reports and later rule-change proposals.

The retrieval sidecar is record-level. It may score or vectorize whole user utterance, tool evidence, or tool-call records, but it must not split those records into authoritative memory chunks. Lookup results are triage previews only; stable evidence remains the full raw record addressed by `source_id` and `path`.

## Structured Cognition

Candidates keep a human-readable `claim` and a small structured object:

```json
{
  "subject": "project_cognition_system",
  "predicate": "requires",
  "object": "do not bulk-inject history",
  "object_key": "bulk_history_injection",
  "scope": "project",
  "modality": "must_not",
  "valid_from": "2026-06-08T00:00:00Z",
  "valid_until": null,
  "source_refs": ["utt_xxx"],
  "confidence_reason": "Extracted by local rule from user_utterance.",
  "supersedes": []
}
```

The structured fields give conflict detection, governance gating, and rule simulation a stable handle without turning the MVP into a database.

`predicate` is normalized to a small local enum. Specific predicates include `enter_core_memory`, `store_log`, `create`, `render`, `override`, `require_review`, `inject_context`, `call_llm`, `read_source`, `update_world_state`, `score_evidence`, `resolve_conflict`, and `test_passed`. The fallback predicates `states`, `requires`, `observed`, and `infers` are kept for compatibility and low-confidence extraction.

`object_key` is a local canonical key for equivalent objects. For example, `assistant final answer`, `agent output`, and `最终输出` can resolve to the same conflict object without model calls. Golden fixtures under `evals/golden/` protect predicate and object normalization.

## Candidate Denoise

`cluster_candidates.py` groups active candidates by `scope / subject / predicate / object_key / modality` and writes `distilled/candidate_clusters.json`. It chooses deterministic representatives using evidence authority, accepted status, confidence, and evidence count.

Candidate clustering is automatic governance denoise only. It does not merge evidence, edit `confidence_table.json`, or update `WORLD_STATE.md`. Weaker duplicates are kept out of core suggestions.

## Governance Gate

`auto_governance_gate.py` is the default admission layer for `WORLD_STATE.md` and compact state. It reads:

- `distilled/confidence_table.json`
- `raw/conflicts.jsonl`
- `distilled/candidate_clusters.json`
- `rules/governance_policy.json`

It writes `distilled/governance_gate.json` and does not edit raw evidence, proposals, conflicts, or the confidence table.

The governance policy owns thresholds, admission budgets, accepted source lists, source/predicate/modality priorities, and constitutional blocks. Gate output includes:

```text
policy_version
policy_hash
policy_path
```

The gate allows only candidates that pass local evidence and policy rules, including high-confidence user evidence, accepted stable sources, and deterministic high-confidence tool evidence. It blocks stale or rejected items, unresolved high-severity conflict sides, candidate-cluster duplicates, assistant-output claims, agent-only claims, quoted/external material, conditional conflict blocks, missing-evidence claims, and low-confidence claims.

## Conflict Lifecycle

`detect_conflicts.py` records potential contradictions and blocks unresolved high-severity items. `resolve_conflict.py` supports:

- `choose-a` or `choose-b`: choose one side and supersede the loser.
- `defer`: keep both sides out of `WORLD_STATE.md` until more evidence exists.
- `mark-resolved`: record external resolution.
- `coexist-by-condition`: preserve both sides under an explicit condition.

Conditional coexistence is for default rules with scoped exceptions, such as:

```text
Default: WORLD_STATE must not be updated automatically.
Exception: WORLD_STATE may be updated when the user explicitly requests it.
```

Conditional conflicts resolve the conflict record, preserve both items, add `conditional_conflict_block`, and keep both sides out of core state until a future conditional rendering mechanism can represent the condition safely.

Resolved conflicts include an `audit_summary` with action, chosen side, loser, condition, supersedes, and blocked status. Human judgment is not part of the default path; it is used only when explicitly requested.

## Rule Change Lifecycle

Rule changes are governed separately from cognition updates. Current apply support covers scoring-weight updates.

Key files:

```text
.project_cognition/proposals/rule_change_proposals.jsonl
.project_cognition/raw/rule_change_log.jsonl
.project_cognition/distilled/scoring_weight_shadow_report.json
.project_cognition/distilled/rule_change_simulation_<id>.json
```

Default scoring-weight update is shadow-only:

```bash
python .project_cognition/scripts/update_scoring_weights.py
```

Apply requires explicit command:

```bash
python .project_cognition/scripts/update_scoring_weights.py --apply
```

Lifecycle path:

```bash
python .project_cognition/scripts/propose_rule_change.py --reason "..." --evidence fb_xxx
python .project_cognition/scripts/simulate_rule_change.py --proposal-id rule_prop_xxx
python .project_cognition/scripts/apply_rule_change.py --proposal-id rule_prop_xxx
```

Simulation runs baseline and proposed pipelines in temporary project copies. It compares score changes, inclusion flags, governance-gate decisions, `WORLD_STATE` IDs, compact character delta, validation error delta, and drift state.

Forbidden transitions block apply:

```text
assistant_or_agent_only_entered_core
quoted_or_external_user_material_entered_core
stale_item_entered_core
unresolved_conflict_side_entered_world_state
compact_characters_exceeded
validation_errors_increased
drift_report_hard_failures_present
```

## Context Selection

Core-state admission and task-context injection are separate.

`auto_governance_gate.py` decides what is admitted. `select_context.py` decides which admitted cognition items are relevant enough for a specific task. It writes a read-only manifest under:

```text
.project_cognition/logs/context_injections/<session_id>.json
```

The manifest records included cognition IDs, exclusion reasons, prompt fingerprint, ruleset hash, gate policy hash, source manifest, and `mutates_state=false`. It may write manifests only; it must not mutate raw evidence, confidence table, governance gate, `WORLD_STATE.md`, or compact state.

## User Profile

`USER_PROFILE.md` is global per agent:

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

`build_user_profile.py` is proposal-first by default. It writes:

```text
.project_cognition/proposals/user_profile_update_report.json
```

It writes the global profile only with:

```bash
python .project_cognition/scripts/build_user_profile.py --apply-profile
```

This is stricter than project `WORLD_STATE` because an incorrect global profile can affect every project.

## World State Rendering

`WORLD_STATE.md` has two layers:

- bootstrap doctrine: fixed, short guardrails that keep the MVP stable and compact.
- accepted structured cognition: governed cognition objects rendered as bounded bullets.

`WORLD_STATE_COMPACT.md` remains doctrine-heavy by design. It can include a small high-priority structured cognition summary, but eligibility is strict: governance-admitted, high-confidence, project-scope, `must/must_not`, and capped.

## Why Not Just Memory?

Large memory stores introduce failure modes:

- unreliable memories
- irrelevant retrieval
- context overflow from retrieved memories
- conflicts between old and new facts
- agent summaries replacing user evidence
- untracked rule drift

This system treats memory as governed evidence and context as a selected output of policy, not as trusted raw recall.

## Validation And CI

Validation scripts:

```bash
python .project_cognition/scripts/validate_state.py
python .project_cognition/scripts/validate_governance_policy.py
```

Primary evals:

```bash
python evals/run_minimal_eval.py
python evals/run_feedback_eval.py
python evals/run_scoring_weight_eval.py
python evals/run_rule_change_eval.py
python evals/run_forbidden_transition_eval.py
python evals/run_governance_policy_eval.py
python evals/run_conditional_conflict_eval.py
python evals/run_context_selection_eval.py
python evals/run_user_profile_eval.py
```

GitHub Actions runs compilation, state validation, policy validation, indexing, clustering, governance gate, drift report, feedback report, all evals, sanitized package build, and whitespace check. These checks use sanitized fixtures and do not scan real history directories.
