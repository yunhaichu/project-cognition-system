# USER_PROFILE Updates

`build_user_profile.py` is proposal-first by default. Running it without flags writes a local report only:

```bash
python .project_cognition/scripts/build_user_profile.py
```

Default output goes to:

```text
.project_cognition/proposals/user_profile_update_report.json
```

It does not write the global profile file.

To explicitly apply the generated profile:

```bash
python .project_cognition/scripts/build_user_profile.py --apply-profile
```

## Why this is stricter than project WORLD_STATE

A wrong project state entry affects one repository. A wrong `USER_PROFILE.md` entry can affect every project run by the same agent. For that reason, global profile mutation requires an explicit command.

## Report contents

The report includes:

```text
generated_candidates
rejected_candidates
rejected_reason_counts
would_change
applied
mutates_global_profile
profile_preview
```

Project-only claims, single weak expressions, low-confidence candidates, conflicted candidates, rejected/superseded candidates, and implementation-review details are rejected.

The post hook still calls `build_user_profile.py`, but because default mode is proposal-first, the hook does not mutate global `USER_PROFILE.md`.
