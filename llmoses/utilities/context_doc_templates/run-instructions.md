# Run Instructions

This file is generated inside a run directory and is disposable. It exists so an
estimator can orient itself locally; the canonical estimator docs remain in
`llmoses/skills/` and are not copied into runs.

Run id: `{run_id}`
Current run sequence: `{run_seq_text}`
Problem: {problem_summary}
Active levers: {lever_text}

Read order for a utility-estimation step:

1. `run_meta.json`
2. `state/run-*/run_config.json`
3. Matching `state/run-*/step-G.json`
4. Matching `action/run-*/step-G.json`
5. Recent prior `step-*.json` files when trend context is useful
6. `moses_native_log.jsonl` for native event breadcrumbs

Use the JSON artifacts as ground truth. These markdown files only describe how
to navigate and interpret the artifacts.

Write two output artifacts for each processed ready sentinel:

- `utilities/run-N/step-G.json`: machine-consumable UtilityResponse.
- `traces/run-N/step-G.json`: AgentTrace transcript and audit artifact.

The UtilityResponse contains only:

- `pass`
- `sampling_temperature`
- `exemplar_utilities`
- `pair_utilities`
- `culling_utilities`
- `complexity_ratio_delta`
- `comparator_bias`

Put prompt/context manifests, raw model responses, read-file lists, explicit
audit reasoning, provider metadata, and parse/error diagnostics in AgentTrace.
Do not rely on hidden model chain-of-thought; traces should contain only
transcript material and explicit audit text available to the harness.

Complexity-ratio direction: `increase` rewards complexity, `decrease` penalizes
complexity, and `maintain` leaves pressure unchanged.
