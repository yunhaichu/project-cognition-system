# Conditional Conflicts

Some conflicts should not be resolved by choosing one side and superseding the other. A default rule and a scoped exception can coexist when the condition is explicit.

Example:

```text
Default: WORLD_STATE must not be updated automatically.
Exception: WORLD_STATE may be updated when the user explicitly requests it.
```

Use:

```bash
python .project_cognition/scripts/resolve_conflict.py \
  --conflict-id conflict_xxx \
  --action coexist-by-condition \
  --condition only_when_user_explicitly_requests \
  --reason "Default prohibition and explicit override coexist by condition."
```

This records:

```text
resolution = resolved
resolution_type = coexist_by_condition
chosen_side = ""
condition = only_when_user_explicitly_requests
blocks_world_state = true
```

Both cognition items are preserved. Neither side is superseded. Both sides receive a `conditional_conflict_block` marker and are kept out of `WORLD_STATE.md` and `WORLD_STATE_COMPACT.md` until a later mechanism renders the condition explicitly.

The scoring layer preserves the conditional block. The governance gate treats `conditional_conflict_block` as a constitutional block, so accepted stable-source items cannot bypass it. Drift reporting does not count a resolved conditional conflict as unresolved high-severity drift.
