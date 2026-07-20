# Utility Artifacts

This file is generated and may be deleted with its run directory. Use
`llmoses/skills/UTILITY_RESPONSE.md` for the canonical UtilityResponse guide.

Utility files are written under `utilities/run-N/` as `step-G.json`.

Each file is a machine-consumable UtilityResponse. It should contain exactly
the action utility fields needed by a downstream controller:

- `pass`
- `sampling_temperature`
- `exemplar_utilities`
- `atom_utility_prior` (entries may carry a `context` object — polarity,
  clause_type, parent_operator, depth_bucket, exemplar_id — in the same
  vocabulary as the state's `atom_evidence` buckets)
- `combination_synergy` (unordered atom sets with a non-separable utility)
- `feature_utility_levers` (`aggregate_fn` + per-axis `lever_weights`;
  all-zero/absent weights mean the global prior alone applies)
- `culling_utilities`
- `complexity_ratio_delta` (always the `{direction, magnitude}` object,
  never a bare direction string)
- `comparator_bias`

Do not put prompt text, raw provider output, natural-language reasoning, or
conversation transcripts in utility files. Those belong in the matching
AgentTrace file under `traces/run-N/step-G.json`.
