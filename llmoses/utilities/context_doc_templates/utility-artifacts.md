# Utility Artifacts

This file is generated and may be deleted with its run directory. Use
`llmoses/skills/UTILITY_RESPONSE.md` for the canonical UtilityResponse guide.

Utility files are written under `utilities/run-N/` as `step-G.json`.

Each file is a machine-consumable UtilityResponse. It should contain only the
action utility fields needed by a downstream controller:

- `pass`
- `sampling_temperature`
- `exemplar_utilities`
- `pair_utilities`
- `culling_utilities`
- `complexity_ratio_delta`
- `comparator_bias`

Do not put prompt text, raw provider output, natural-language reasoning, or
conversation transcripts in utility files. Those belong in the matching
AgentTrace file under `traces/run-N/step-G.json`.
