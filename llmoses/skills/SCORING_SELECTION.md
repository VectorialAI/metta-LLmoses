# Scoring And Selection

MOSES scoring is multi-field. Do not rank candidates from one number unless the run exposes only one meaningful field.

Common fields:

- `raw_score`: problem-level fitness before complexity penalties.
- `complexity`: structural size or complexity measure (under `cscore`).
- `complexity_penalty`: penalty derived from complexity pressure.
- `penalized_score`: score after penalties; often the best single ranking signal.
- `bscore`: vector-valued behavior or table score, when present.

`uniformity_penalty` is not emitted in Phase I (always 0.0, a no-op per D-014); do not expect it as a ranking field.

Selection signals:

- `moses_native_events.post_selection` records what native MOSES selected this generation.
- `lineage_diff.selected_program_id` links selection to candidate identity when available.
- `explored` marks programs already selected in prior generations.
- `lineage_depth` helps distinguish fresh structures from repeatedly expanded descendants.

Use score and complexity together. Rising complexity with flat score usually favors stronger complexity pressure; rising score with useful structural novelty can justify preserving or rewarding complexity.
