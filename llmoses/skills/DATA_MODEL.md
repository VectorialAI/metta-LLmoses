# Data Model

Treat JSON artifacts as ground truth. Markdown files explain conventions, but they are not authoritative state.

Primary files:

- `run_meta.json`: run id, mode, builder version, and start timestamp.
- `state/run-*/run_config.json`: static problem specification, atom alphabet, run parameters, active levers, and comparator availability.
- `state/run-*/step-G.json`: MosesState for generation `G`.
- `action/run-*/step-G.json`: ActionVector for generation `G`.
- `moses_native_log.jsonl`: append-only native event summary.
- `state/run-*/terminal.json`: final post-merge state when emitted.
- `state/run-*/atom_lossless-G.json`: optional detailed atom/cooccurrence record when lossless atom emission is enabled.

Important MosesState sections:

- `metapopulation`: current members, scores, complexity, explored flag, and best penalized score.
- `demes`: per-deme tree, knobs, instances, and evaluation counts.
- `merge_summary`: merge counts and culling candidates.
- `lineage_diff`: new, removed, retained, and selected ids across generations.
- `moses_native_events.post_selection`: native exemplar selection event.
- `score_vs_complexity_trend`: recent score and complexity direction.
- `atom_evidence`: atom appearances and realized cooccurrences derived from candidate trees.

Important ActionVector sections:

- `exemplar_candidates`: candidates that could be preferred for future selection.
- `culling_candidates`: candidates exposed around retention or removal.
- `complexity_ratio`: current value and available direction context.
- `pair_sampling_candidates`: future or optional pair guidance if emitted by a run.
