# Hook Integration

The runtime scripts are agent-agnostic. Integrations are thin wrappers that:

- find the current project root
- optionally bootstrap `.project_cognition/`
- run `codex_pre_hook.py` at session start
- run `codex_post_hook.py` at session stop
- pass `PROJECT_COGNITION_AGENT` so user profile paths stay isolated

The post hook is local-only by default. It ingests the current transcript, writes assistant output to logs, normalizes tool calls into `raw/tool_evidence.jsonl`, runs rule-based extraction/scoring/conflict detection, and rebuilds compact state. It does not call an LLM or bulk-inject raw history.

Recommended profile paths:

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

Do not generate project-level `AGENTS.md`. Keep user-level instructions global and keep project cognition in `.project_cognition/`.
