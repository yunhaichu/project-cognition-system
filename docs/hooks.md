# Hook Integration

The runtime scripts are agent-agnostic. Integrations are thin wrappers that:

- find the current project root
- optionally bootstrap `.project_cognition/`
- run `codex_pre_hook.py` at session start
- run `codex_post_hook.py` at session stop
- pass `PROJECT_COGNITION_AGENT` so user profile paths stay isolated

The wrappers also sync the per-project runtime scripts from the local bootstrap runtime before calling project hooks. This keeps existing project folders on the latest governance pipeline without creating project-level `AGENTS.md`.

Codex uses two hooks:

- `SessionStart`: injects only compact project context and refreshes the agent-specific user profile.
- `Stop`: ingests the completed transcript and runs the local governance pipeline.

Hermes uses the equivalent two hooks:

- `pre_llm_call`: injects only compact project context and refreshes the Hermes user profile.
- `post_llm_call`: stores the completed turn and runs the same local governance pipeline.

Hermes also has a separate gateway event hook system under `~/.hermes/hooks/`. The bundled gateway hook in `integrations/hermes/gateway_hook/project_cognition/` registers visible lifecycle events:

- `session:start`
- `agent:start`
- `agent:end`
- `session:end`
- `session:reset`

This gateway hook is intentionally a lifecycle bridge. It logs gateway events so Hermes does not report "no hooks", but compact context injection still belongs to the `pre_llm_call` plugin hook because gateway event hooks cannot mutate the LLM request. To avoid duplicate ingestion when the plugin hook is active, gateway post-turn ingestion is disabled by default. It can be enabled explicitly with `HERMES_PROJECT_COGNITION_GATEWAY_RUN_POST_HOOK=1`.

Default timeouts are intentionally separate:

- Codex `SessionStart`: `30s`, configurable with `PROJECT_COGNITION_CODEX_SESSION_START_TIMEOUT`.
- Codex `Stop`: `90s`, configurable with `PROJECT_COGNITION_CODEX_STOP_TIMEOUT`.
- Hermes `pre_llm_call`: `30s`, configurable with `HERMES_PROJECT_COGNITION_PRE_TIMEOUT`.
- Hermes `post_llm_call`: `90s`, configurable with `HERMES_PROJECT_COGNITION_POST_TIMEOUT`.
- Hermes gateway optional post hook: `90s`, configurable with `HERMES_PROJECT_COGNITION_GATEWAY_POST_TIMEOUT`.

The post hook is local-only by default. It ingests the current transcript, writes assistant output to logs, normalizes tool calls into `raw/tool_evidence.jsonl`, runs rule-based extraction/scoring/conflict detection, clusters unresolved conflicts, rebuilds compact state, refreshes the read-only evidence index, and runs drift-budget checks. It does not call an LLM or bulk-inject raw history.

Current post-hook pipeline:

```text
ingest_session
  -> update_scoring_weights
  -> extract_candidates
  -> score_candidates
  -> detect_conflicts
  -> cluster_candidates
  -> cluster_conflicts
  -> auto_governance_gate
  -> build_world_state
  -> build_user_profile
  -> index_segments
  -> drift_report
```

`index_segments.py` is a record-level lookup index despite the historical name: it does not split user utterances or tool evidence into authoritative chunks. `build_vector_index.py` follows the same rule: vector retrieval may embed/rank full records and return source ids, not chunk-derived facts. `lookup_evidence.py` and `vector_lookup.py` return source ids plus short previews only; the preview is not a fact source, and any claim must still be grounded by reading the full source record by `source_id`. `lookup_evidence.py`, `vector_lookup.py`, and `review_conflict_cluster.py` are explicit, on-demand tools. They are not injected into context and do not update `WORLD_STATE` unless the normal governance/update pipeline is used.

Recommended profile paths:

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

Do not generate project-level `AGENTS.md`. Keep user-level instructions global and keep project cognition in `.project_cognition/`.
