# Governance Policy

`auto_governance_gate.py` now loads its thresholds, admission budgets, and priority maps from a local policy file:

```text
.project_cognition/rules/governance_policy.json
```

The default policy preserves the previous gate behavior. CLI flags still override policy values for eval and debugging.

## Policy contents

The policy owns:

```text
thresholds.min_confidence
thresholds.min_confidence_user
thresholds.min_confidence_tool
thresholds.min_conflict_severity
admission_budget.max_allowed
admission_budget.max_per_category
admission_budget.max_per_predicate
admission_budget.max_per_slot
priority.source
priority.predicate
priority.modality
allowed_accepted_sources
constitutional_blocks
```

## Gate metadata

Every generated `distilled/governance_gate.json` now includes:

```text
policy_version
policy_hash
policy_path
```

This makes gate decisions traceable to the exact policy used to produce them.

## Change control

The policy is still a rule file. Policy changes should go through the rule-change lifecycle rather than being edited silently.
