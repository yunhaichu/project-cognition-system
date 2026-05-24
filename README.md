# Project Cognition System

A lightweight, local-first cognition governance system for long-running AI coding agents.

This project is not a generic RAG pipeline, not a growing `memory.md`, and not a tool for stuffing all chat history into every prompt. Its goal is to keep an agent aligned to a stable project view after context truncation, session compaction, or lost conversation history, while keeping default context very small.

## Core Idea

Traditional memory systems answer "can the agent remember more?"

Project Cognition System asks different questions:

- Is this memory reliable?
- Is it user evidence, tool evidence, agent interpretation, or agent output?
- Should it enter the core project state at all?
- Is there a conflict with older high-confidence cognition?
- Can the agent recover the exact original source when needed?
- Can the default injected context stay tiny?

The system separates evidence, interpretation, strategy, user profile, and logs. It generates a short `WORLD_STATE.md` and an even shorter `WORLD_STATE_COMPACT.md` for hook injection.

## Principles

- User utterances have the highest evidence weight.
- Agent final answers are outputs, not facts.
- Agent reasoning and tool use are useful for audit, not automatic truth.
- Raw material may grow, but default context must stay small.
- Low-confidence cognition must not enter core project state.
- Conflicts are recorded, not silently overwritten.
- Core state is rebuilt by local rule-based scripts, not hidden LLM summarization.
- Project cognition is per project; user profile is global and agent-specific.

## Directory Layout

```text
.project_cognition/
  WORLD_STATE.md
  WORLD_STATE_COMPACT.md
  raw/
  distilled/
  proposals/
  logs/
  scripts/
  schemas/
examples/
docs/
integrations/
```

## Quick Start

Run the sample flow:

```bash
python .project_cognition/scripts/ingest_session.py \
  --input examples/sample_session.jsonl \
  --session-id sample_demo

python .project_cognition/scripts/extract_candidates.py
python .project_cognition/scripts/score_candidates.py
python .project_cognition/scripts/detect_conflicts.py
python .project_cognition/scripts/build_world_state.py
python .project_cognition/scripts/codex_pre_hook.py \
  --format markdown \
  --profile-mode ultra \
  --world-mode compact \
  --max-chars 1600
```

Or run the local post-hook wrapper:

```bash
python .project_cognition/scripts/codex_post_hook.py \
  --session-jsonl examples/sample_session.jsonl \
  --session-id sample_demo
```

## Hook Model

At session start:

1. Read the agent-specific global `USER_PROFILE.md`.
2. Read the current project's `WORLD_STATE_COMPACT.md`.
3. Inject only the compact state, not raw history.

At session stop:

1. Ingest the current session if a transcript is available.
2. Store user messages as raw evidence.
3. Store assistant outputs as logs.
4. Extract candidates with local rules.
5. Score candidates.
6. Detect conflicts.
7. Rebuild `WORLD_STATE.md` and `WORLD_STATE_COMPACT.md`.

## User Profile Boundary

Project state belongs in each project's `.project_cognition/`.

User profile is global and agent-specific:

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

Do not put user profile into project folders. Do not create project-level `AGENTS.md` as part of this system.

## Existing Project Bootstrap

```bash
python .project_cognition/scripts/bootstrap_existing_project.py \
  --target-root /path/to/existing/project \
  --history /path/to/history.jsonl
```

The bootstrap script creates `.project_cognition/` in the target project and imports history as evidence. It does not create project-level `AGENTS.md`.

## Privacy

This repository ships with empty raw/log files and sanitized examples. Real `raw/`, `logs/`, `distilled/`, and `proposals/` content may contain private conversation history, tool output, paths, or user preferences. Review before publishing.

## License

This project is released under the PolyForm Noncommercial License 1.0.0.

Commercial use is not permitted without separate written permission. This means the project is source-available for noncommercial use, but it is not OSI-approved open source.

## Status

MVP. Python standard library only.
