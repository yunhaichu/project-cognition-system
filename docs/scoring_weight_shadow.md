# Scoring Weight Shadow Updates

`update_scoring_weights.py` is safe by default. Running it without flags now produces a shadow report instead of mutating `scoring_weights.json` or marking feedback rows as applied.

Default mode:

```bash
python .project_cognition/scripts/update_scoring_weights.py
```

This writes a generated report to:

```text
.project_cognition/distilled/scoring_weight_shadow_report.json
```

The report includes feedback totals, pending feedback count, proposed signal-weight changes, ignored signals, zero-delta feedback, and bounds hits.

Explicit apply mode:

```bash
python .project_cognition/scripts/update_scoring_weights.py --apply
```

Only `--apply` mutates:

```text
.project_cognition/distilled/scoring_weights.json
.project_cognition/distilled/scoring_feedback.jsonl
```

This keeps rule evolution procedural. Feedback may be collected automatically, and scoring changes may be proposed automatically, but scoring-weight changes do not take effect without an explicit apply command.
