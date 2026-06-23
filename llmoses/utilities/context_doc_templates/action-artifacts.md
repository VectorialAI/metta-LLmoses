# Action Artifacts

This file is generated and may be deleted with its run directory. Use
`llmoses/skills/ACTION_LEVERS.md` for the canonical action-lever guide.

Action files are written under `action/run-N/` as `step-G.json`.

Active levers from config: {lever_text}

Current or planned action components:

- `exemplar_candidates`: candidate programs available for exemplar preference.
- `culling_candidates`: candidates exposed for retention or removal preference.
- `complexity_ratio`: current value and complexity-pressure context.
- `pair_sampling_candidates`: optional explicit pair or cooccurrence guidance.
- Comparator ordering: available only when exposed by config or action files.

Only estimate utilities for components that are actually present or explicitly
exposed. If a component is absent, return an empty array or null for that part
of the UtilityResponse.
