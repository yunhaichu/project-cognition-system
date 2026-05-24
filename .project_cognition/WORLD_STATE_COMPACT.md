# WORLD_STATE_COMPACT.md

Project: low-drift, auditable project cognition for AI agents; not RAG, not memory.md, not history stuffing.
Goal: avoid drift while keeping default context tiny.
Evidence: user utterances and real tool results outrank agent interpretations; agent final output is a log.
Context: do not load raw/logs/history by default; look up exact sources only when needed.
Flow: local scripts rebuild world state through extraction, scoring, conflict detection, proposals, and review.

