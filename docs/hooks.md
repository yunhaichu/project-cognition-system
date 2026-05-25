# Hook Integration

The runtime scripts are agent-agnostic. Integrations are thin wrappers that:

- find the current project root
- optionally bootstrap `.project_cognition/`
- run `codex_pre_hook.py` at session start
- run `codex_post_hook.py` at session stop
- pass `PROJECT_COGNITION_AGENT` so user profile paths stay isolated

The wrappers also sync the per-project runtime scripts from the local bootstrap runtime before calling project hooks. This keeps existing project folders on the latest governance pipeline without creating project-level `AGENTS.md`.

The post hook is local-only by default. It ingests the current transcript, writes assistant output to logs, normalizes tool calls into `raw/tool_evidence.jsonl`, runs rule-based extraction/scoring/conflict detection, clusters unresolved conflicts, rebuilds compact state, refreshes the read-only evidence index, and runs drift-budget checks. It does not call an LLM or bulk-inject raw history.

Current post-hook pipeline:

```text
ingest_session
  -> update_scoring_weights
  -> extract_candidates
  -> score_candidates
  -> detect_conflicts
  -> cluster_conflicts
  -> build_world_state
  -> build_user_profile
  -> index_segments
  -> drift_report
```

`lookup_evidence.py` and `review_conflict_cluster.py` are explicit, on-demand tools. They are not injected into context and do not update `WORLD_STATE` unless the normal review/update pipeline is used.

Recommended profile paths:

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

Do not generate project-level `AGENTS.md`. Keep user-level instructions global and keep project cognition in `.project_cognition/`.
