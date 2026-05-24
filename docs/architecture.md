# Architecture

Project Cognition System separates project understanding into layers:

1. Raw fact layer: user utterances, real files, tool results, test results.
2. Agent interpretation layer: what the agent believed, with confidence and possible misreadings.
3. Strategy layer: current route, current phase, rejected routes, temporary decisions.
4. User profile layer: slow-changing cross-project preferences, stored globally per agent.
5. Log layer: assistant outputs, tool calls, and session material for audit only.

Only high-confidence, stable, non-conflicted cognition should enter `WORLD_STATE.md`.

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

