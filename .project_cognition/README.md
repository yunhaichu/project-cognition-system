# Project Cognition Runtime

This directory is the local runtime state for Project Cognition System.

Generated or private evidence belongs under `raw/`, `logs/`, `distilled/`, and `proposals/`. Do not publish real project evidence without review.

Key runtime files:

- `raw/user_utterances.jsonl`: highest-weight user evidence.
- `raw/tool_evidence.jsonl`: normalized tool evidence, linked back to full logs.
- `logs/outputs/`: assistant final outputs; audit only, not core cognition.
- `distilled/confidence_table.json`: scored candidates with structured fields.
- `raw/conflicts.jsonl`: detected conflicts; use `scripts/resolve_conflict.py` for review.

`WORLD_STATE.md` combines short bootstrap doctrine with accepted structured cognition. The compact file remains short and is the default hook payload.

Compact structured cognition is intentionally narrow: accepted project-scope must/must_not rows with confidence 95 or higher, capped at 3 rows.

Structured cognition includes a normalized predicate and an `object_key` for local equivalent-object matching. Real transcript dogfood must be passed explicitly to eval scripts; hooks should not scan historical transcripts by default.
