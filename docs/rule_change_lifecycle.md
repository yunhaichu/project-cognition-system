# Rule Change Lifecycle

Rule changes are governed separately from cognition updates. Feedback can be collected automatically and rule changes can be proposed automatically, but rule changes do not take effect until they are simulated and explicitly applied.

Current scope covers `scoring_weight_update`.

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

Apply only after simulation succeeds:

```bash
python .project_cognition/scripts/apply_rule_change.py --proposal-id rule_prop_xxx
```

## Invariants

- unsimulated proposals cannot be applied.
- proposals with hard failures cannot be applied.
- simulation does not mutate `scoring_weights.json`.
- apply is explicit and writes `rule_change_log.jsonl`.
- validation checks rule-change proposal evidence and rule-change log proposal references.

This is the first step toward the fuller v0.5 loop:

```text
feedback event -> feedback report -> rule change proposal -> simulation -> explicit apply -> rule change log
```
