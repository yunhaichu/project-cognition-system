# Security And Privacy

The runtime may store sensitive data:

- original user messages
- assistant outputs
- tool output
- normalized tool evidence in `raw/tool_evidence.jsonl`
- local file paths
- project decisions
- personal preferences

Before publishing, sanitize and remove real `raw/`, `logs/`, `distilled/`, and `proposals/` content. The default `.gitignore` blocks common private runtime outputs.

The system is designed so assistant outputs are logged but not promoted into core cognition. Tool evidence is higher weight than agent interpretation, but tool-only candidates must pass deterministic-evidence and conflict-safety checks in the automated governance gate before `WORLD_STATE.md` inclusion.
