# UtilityResponse

Write exactly one valid JSON object to `utilities/run-N/step-G.json`. Do not wrap it in Markdown.

UtilityResponse is the machine-consumable action utility output. It should not contain prompt text, raw model responses, natural-language reasoning, or transcript material. Those belong in `traces/run-N/step-G.json`.

Required top-level fields:

```json
{
  "pass": true,
  "sampling_temperature": null,
  "exemplar_utilities": [],
  "pair_utilities": [],
  "culling_utilities": [],
  "complexity_ratio_delta": null,
  "comparator_bias": null
}
```

`pass` should be `true` when no intervention is justified, evidence is insufficient, or all exposed levers should stay neutral.

Use empty arrays or `null` for components that are not exposed in the current files. Do not fabricate candidate ids.

Recommended utility records:

- Exemplar utilities: include `program_id` and `utility`.
- Pair utilities: include the pair or atom keys available in the artifact and `utility`.
- Culling utilities: include `program_id` and `retain_utility` or `cull_utility`.
- Complexity ratio: use `increase`, `decrease`, or `maintain` when a directional field is expected.
- Comparator bias: include only documented comparator dimensions.

Put all reasons, audit notes, parse diagnostics, prompt/context manifests, and raw provider responses in the matching AgentTrace file under `traces/`.
