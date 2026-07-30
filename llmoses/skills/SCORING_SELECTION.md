# Scoring And Selection

MOSES scoring is multi-field. Do not rank candidates from one number unless the run exposes only one meaningful field.

Common fields:

- `raw_score`: problem-level fitness before complexity penalties.
- `complexity`: structural size or complexity measure.
- `complexity_penalty`: penalty derived from complexity pressure.
- `uniformity_penalty`: additional penalty where present.
- `penalized_score`: score after penalties; often the best single ranking signal.
- `bscore`: vector-valued behavior or table score, when present.

Selection signals:

- `moses_native_events.post_selection` records what native MOSES selected this generation.
- `lineage_diff.selected_program_id` links selection to candidate identity when available.
- `explored` marks programs already selected in prior generations.
- `lineage_depth` helps distinguish fresh structures from repeatedly expanded descendants.

Use score and complexity together. Rising complexity with flat score usually favors stronger complexity pressure; rising score with useful structural novelty can justify preserving or rewarding complexity.
