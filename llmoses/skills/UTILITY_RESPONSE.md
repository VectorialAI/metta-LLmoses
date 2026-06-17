# UtilityResponse

Return exactly one valid JSON object. Do not wrap it in Markdown.

Required top-level fields:

```json
{
  "pass": true,
  "sampling_temperature": null,
  "exemplar_utilities": [],
  "pair_utilities": [],
  "culling_utilities": [],
  "complexity_ratio_delta": null,
  "comparator_bias": null,
  "reasoning_trace": [],
  "trace_summary": ""
}
```

`pass` should be `true` when no intervention is justified, evidence is insufficient, or all exposed levers should stay neutral.

Use empty arrays or `null` for components that are not exposed in the current files. Do not fabricate candidate ids.

Recommended utility records:

- Exemplar utilities: include `program_id`, `utility`, and a short `reason`.
- Pair utilities: include the pair or atom keys available in the artifact, `utility`, and `reason`.
- Culling utilities: include `program_id`, `retain_utility` or `cull_utility`, and `reason`.
- Complexity ratio: use `increase`, `decrease`, or `maintain` when a directional field is expected.
- Comparator bias: include only documented comparator dimensions.

Keep `reasoning_trace` concise. It should support auditability, not narrate every token of analysis.
