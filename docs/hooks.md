# Hook Integration

The runtime scripts are agent-agnostic. Integrations are thin wrappers that:

- find the current project root
- optionally bootstrap `.project_cognition/`
- run `codex_pre_hook.py` at session start
- run `codex_post_hook.py` at session stop
- pass `PROJECT_COGNITION_AGENT` so user profile paths stay isolated

The wrappers also sync per-project runtime scripts from the local bootstrap runtime before calling project hooks. Existing project folders can move to the latest governance pipeline without creating project-level `AGENTS.md`.

The global runtime at `~/.project_cognition` is only a script/schema source. It must not be treated as a project root when the current directory has no project cognition state.

Automatic bootstrap is disabled by default. Set `PROJECT_COGNITION_AUTO_BOOTSTRAP=1` for Codex or `HERMES_PROJECT_COGNITION_AUTO_BOOTSTRAP=1` for Hermes only when hooks should create `.project_cognition/` in a new project. Otherwise initialize existing projects with `bootstrap_existing_project.py`.

## Hook Types

Codex uses two hooks:

- `SessionStart`: injects compact project context and compact global user profile.
- `Stop`: ingests the completed transcript and runs the local governance pipeline.

Hermes uses equivalent plugin hooks:

- `pre_llm_call`: injects compact project context and compact Hermes user profile.
- `post_llm_call`: stores the completed turn and runs the same local governance pipeline.

Hermes also has a gateway event hook system under `~/.hermes/hooks/`. The bundled gateway hook in `integrations/hermes/gateway_hook/project_cognition/` registers lifecycle events:

- `session:start`
- `agent:start`
- `agent:end`
- `session:end`
- `session:reset`

The gateway hook is a lifecycle bridge. It logs gateway events so Hermes does not report "no hooks", but compact context injection belongs to the `pre_llm_call` plugin hook because gateway event hooks cannot mutate the LLM request. To avoid duplicate ingestion when the plugin hook is active, gateway post-turn ingestion is disabled by default. Enable it explicitly with `HERMES_PROJECT_COGNITION_GATEWAY_RUN_POST_HOOK=1`.

## Timeouts

Default timeouts are intentionally separate:

- Codex `SessionStart`: `30s`, configurable with `PROJECT_COGNITION_CODEX_SESSION_START_TIMEOUT`.
- Codex `Stop`: `90s`, configurable with `PROJECT_COGNITION_CODEX_STOP_TIMEOUT`.
- Hermes `pre_llm_call`: `30s`, configurable with `HERMES_PROJECT_COGNITION_PRE_TIMEOUT`.
- Hermes `post_llm_call`: `90s`, configurable with `HERMES_PROJECT_COGNITION_POST_TIMEOUT`.
- Hermes gateway optional post hook: `90s`, configurable with `HERMES_PROJECT_COGNITION_GATEWAY_POST_TIMEOUT`.

## Pre Hook

The pre hook should stay compact. It reads `WORLD_STATE_COMPACT.md` plus a compact global user profile. Raw evidence, logs, history directories, generated indexes, and proposals are not bulk-injected.

For task-specific context selection, use `select_context.py` explicitly. It writes a manifest under `logs/context_injections/` and does not mutate core state.

## Post Hook

The post hook is local-only by default. It ingests the current transcript, writes assistant output to logs, normalizes tool calls into `raw/tool_evidence.jsonl`, runs a versioned state upgrade, and runs the local governance pipeline. It does not call an LLM or bulk-inject raw history.

Current post-hook pipeline:

```text
ingest_session
  -> upgrade_state
  -> update_scoring_weights      # shadow-only by default
  -> extract_candidates
  -> score_candidates
  -> detect_conflicts
  -> cluster_candidates
  -> cluster_conflicts
  -> auto_governance_gate        # policy-backed, hash-tracked
  -> build_world_state
  -> build_user_profile          # proposal-first by default
  -> index_segments
  -> drift_report
```

Important side-effect boundaries:

- `update_scoring_weights.py` writes a shadow report by default. It mutates weights only with `--apply`.
- `build_user_profile.py` writes a local report by default. It mutates global `USER_PROFILE.md` only with `--apply-profile`.
- `auto_governance_gate.py` reads `rules/governance_policy.json` and writes policy metadata to `governance_gate.json`.
- `resolve_conflict.py --action coexist-by-condition` preserves both conflict sides and blocks them from core state.
- `select_context.py` is not part of the default post hook; it is task-specific and manifest-only.

## Evidence Lookup

`index_segments.py` is a record-level lookup index despite the historical name. It does not split user utterances or tool evidence into authoritative chunks.

`build_vector_index.py` follows the same rule: vector retrieval may embed/rank full records and return source IDs, not chunk-derived facts. `lookup_evidence.py` and `vector_lookup.py` return source IDs plus short previews only. A preview is not a fact source; any claim must still be grounded by reading the full source record.

`lookup_evidence.py`, `vector_lookup.py`, and `review_conflict_cluster.py` are explicit on-demand tools. They are not injected into context and do not update `WORLD_STATE` unless the normal governance/update pipeline is used.

## Recommended Profile Paths

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

Do not generate project-level `AGENTS.md`. Keep user-level instructions global and project cognition in `.project_cognition/`.
