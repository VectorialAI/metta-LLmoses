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

State and action files for the same `run-*/step-G` are consumed together and joined by `program_id`. Each program's `tree_str` (preorder s-expression) is emitted exactly once across the pair, never duplicated.

Important MosesState sections:

- `metapopulation`: current members, scores, complexity, explored flag, and best penalized score. Each member's `tree_str` is the canonical tree shape for incumbents and survivors — `action.exemplar_candidates` references these members by `program_id` rather than repeating it. `complexity` lives under `cscore`; `uniformity_penalty` is omitted (always 0.0 in Phase I, per D-014).
- `demes`: per-deme `exemplar_program_id` (the seeding member — resolve its tree shape from the metapopulation), knobs, instances, and evaluation counts. The raw representation tree is not emitted.
- `merge_summary`: merge counts plus `resize_cull`, a membership partition — `incumbent_count` (the metapopulation) and `program_id` lists for `new_entrants`, `survivors`, and `culled`. Every id resolves to a full record in `metapopulation.members` or `action.culling_candidates`.
- `lineage_diff`: new, removed, retained, and selected ids across generations.
- `moses_native_events.post_selection`: native exemplar selection event.
- `score_vs_complexity_trend`: recent score and complexity direction.
- `atom_evidence`: atom appearances and realized cooccurrences derived from candidate trees.

Important ActionVector sections:

- `exemplar_candidates`: candidates that could be preferred for future selection; carry `program_id`, scores, complexity, and `lineage_depth`. Resolve `tree_str` from `metapopulation.members` by `program_id`.
- `culling_candidates`: new entrants exposed around retention or removal. These are not in the metapopulation, so each carries its own `tree_str`, `bscore`, scores, and `lineage_depth` here.
- `complexity_ratio`: current value and available direction context.
- `pair_sampling_candidates`: future or optional pair guidance if emitted by a run.
