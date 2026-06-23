# State Artifacts

This file is generated and may be deleted with its run directory. Use it as a
local guide only; JSON artifacts are ground truth.

Problem: {problem_summary}

State files are written under `state/run-N/`.

- `run_config.json` contains static run parameters, problem spec, atom alphabet,
  active levers, and comparator availability.
- `step-G.json` is the MosesState for generation `G`.
- `terminal.json` may appear at the end of a run for final post-merge state.
- `atom_lossless-G.json` may appear when lossless atom/cooccurrence emission is
  enabled.

Common `step-G.json` sections:

- `metapopulation`: candidate programs and scores; each member's `tree_str` is the
  canonical tree shape, referenced elsewhere by `program_id`.
- `demes`: per-deme `exemplar_program_id`, knobs, instance counts, and evaluation counts.
- `merge_summary`: merge counts and `resize_cull` (an `incumbent_count` plus `program_id`
  lists for `new_entrants`, `survivors`, and `culled`; ids resolve in `metapopulation` or
  `action.culling_candidates`).
- `lineage_diff`: selected, new, retained, and removed program ids.
- `moses_native_events`: selected native MOSES events for this generation.
- `score_vs_complexity_trend`: score and complexity direction over recent steps.
- `atom_evidence`: atom appearances and realized cooccurrences.

`step` means generation. Do not wait for renamed generation files; the current
compatibility contract is `step-G.json`.
