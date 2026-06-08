# Rule Change Lifecycle

Rule changes are governed separately from cognition updates. Feedback can be collected automatically and rule changes can be proposed automatically, but rule changes do not take effect until they are simulated and explicitly applied.

Current apply scope covers `scoring_weight_update`. Simulation also now performs a baseline/proposed comparison in temporary project copies and checks forbidden transitions before a proposal can be applied.

## Files

```text
.project_cognition/proposals/rule_change_proposals.jsonl
.project_cognition/raw/rule_change_log.jsonl
.project_cognition/distilled/rule_change_simulation_<id>.json
```

## Commands

Create a proposal from the current scoring-weight shadow report:

```bash
python .project_cognition/scripts/propose_rule_change.py \
  --reason "Use reviewed feedback to adjust scoring weights" \
  --evidence fb_xxx
```

Simulate the proposal without mutating the target:

```bash
python .project_cognition/scripts/simulate_rule_change.py --proposal-id rule_prop_xxx
```

Run the forbidden-transition detector self-check:

```bash
python .project_cognition/scripts/simulate_rule_change.py --self-check
```

Apply only after simulation succeeds:

```bash
python .project_cognition/scripts/apply_rule_change.py --proposal-id rule_prop_xxx
```

## Forbidden transitions

Simulation blocks changes that cause or expose these failure classes:

```text
assistant_or_agent_only_entered_core
quoted_or_external_user_material_entered_core
stale_item_entered_core
unresolved_conflict_side_entered_world_state
compact_characters_exceeded
validation_errors_increased
drift_report_hard_failures_present
```

## Invariants

- unsimulated proposals cannot be applied.
- proposals with hard failures cannot be applied.
- simulation runs baseline and proposed scoring/gate/build pipelines in temporary project copies.
- simulation does not mutate `scoring_weights.json`.
- apply is explicit and writes `rule_change_log.jsonl`.
- validation checks rule-change proposal evidence and rule-change log proposal references.

The v0.5 loop is now:

```text
feedback event -> feedback report -> rule change proposal -> simulation -> forbidden-transition check -> explicit apply -> rule change log
```
