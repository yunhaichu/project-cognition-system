# Feedback Layer

The feedback layer records evidence about how PCS behaved after it made or used a cognition decision. It is not another memory store and it does not directly update `WORLD_STATE.md`.

Feedback events are written to:

```text
.project_cognition/raw/feedback_events.jsonl
```

A feedback event can describe a user correction, deterministic tool result, drift incident, retrieval result, gate false accept, gate false reject, or other local governance outcome. `event_family` is intentionally controlled, while `event_name` remains open so new feedback types can be added without changing the schema for every new metric.

The default tools are:

```bash
python .project_cognition/scripts/record_feedback.py \
  --event-family correction \
  --event-name user_correction \
  --target-type cognition \
  --target-id cog_xxx \
  --outcome negative \
  --severity 90 \
  --source-type user_utterance \
  --source-ref utt_xxx

python .project_cognition/scripts/feedback_report.py
```

`feedback_report.py` is read-only. It reports aggregate feedback metrics and must not mutate raw evidence, `confidence_table.json`, `WORLD_STATE.md`, or governance-gate output.

Initial metrics include total feedback events, events by family, events by outcome, negative feedback count, high-severity negative count, user correction count, deterministic tool feedback count, drift feedback count, gate false accept count, and gate false reject count.

Feedback is input to later rule-change proposals. It is not itself permission to change scoring weights, governance policy, object canonicalization, predicate rules, or bootstrap doctrine.
