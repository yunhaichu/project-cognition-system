# Project Cognition Runtime

This directory is the local runtime state for Project Cognition System.

Generated or private evidence belongs under `raw/`, `logs/`, `distilled/`, and `proposals/`. Do not publish real project evidence without review.

Key runtime files:

- `raw/user_utterances.jsonl`: highest-weight user evidence.
- `raw/tool_evidence.jsonl`: normalized tool evidence, linked back to full logs.
- `raw/feedback_events.jsonl`: local feedback events for governance analysis.
- `raw/conflicts.jsonl`: detected conflicts; use `scripts/resolve_conflict.py` for explicit resolution.
- `raw/rule_change_log.jsonl`: applied rule-change audit log.
- `logs/outputs/`: assistant final outputs; audit only, not core cognition.
- `logs/context_injections/`: task-specific context-selection manifests.
- `distilled/confidence_table.json`: scored candidates with structured fields.
- `distilled/governance_gate.json`: generated gate decisions with policy hash metadata.
- `distilled/scoring_weight_shadow_report.json`: generated scoring-weight change preview.
- `proposals/rule_change_proposals.jsonl`: rule-change proposals requiring simulation and explicit apply.
- `proposals/user_profile_update_report.json`: proposal-first global user-profile update report.
- `rules/governance_policy.json`: local governance gate policy.

`WORLD_STATE.md` combines short bootstrap doctrine with accepted structured cognition. `WORLD_STATE_COMPACT.md` remains short and is the default hook payload.

Compact structured cognition is intentionally narrow: admitted project-scope `must` / `must_not` rows with high confidence and strict caps.

Structured cognition includes a normalized predicate and an `object_key` for local equivalent-object matching. Real transcript dogfood must be passed explicitly to eval scripts; hooks should not scan historical transcripts by default.

Conflict resolution writes an audit summary. Conditional conflict resolution can preserve both sides under a condition and keep both out of core state.

Rule changes are not silent. Feedback may be collected automatically and scoring changes may be proposed automatically, but rule changes must go through proposal, simulation, forbidden-transition checking, explicit apply, and logging.

Global `USER_PROFILE.md` is proposal-first. `build_user_profile.py` writes a local report by default and writes the global profile only with `--apply-profile`.

Run these validators before packaging or release:

```bash
python .project_cognition/scripts/validate_state.py
python .project_cognition/scripts/validate_governance_policy.py
```

CI should run validation, governance gate generation, feedback report, all evals, sanitized package build, and whitespace checks against sanitized fixtures only.
