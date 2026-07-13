# UtilityResponse

Write exactly one valid JSON object to `utilities/run-N/step-G.json`. Do not wrap it in Markdown.

UtilityResponse is the machine-consumable action utility output. It should not contain prompt text, raw model responses, natural-language reasoning, or transcript material. Those belong in `traces/run-N/step-G.json`.

Required top-level fields:

```json
{
  "pass": true,
  "sampling_temperature": null,
  "exemplar_utilities": [],
  "atom_utility_prior": [],
  "feature_utility_levers": null,
  "culling_utilities": [],
  "complexity_ratio_delta": null,
  "comparator_bias": null
}
```

`pass` should be `true` when no intervention is justified, evidence is insufficient, or all exposed levers should stay neutral. `pass: true` clears the wrapper's utility buffer — every lever runs natively that generation.

Use empty arrays or `null` for components that are not exposed in the current files. Do not fabricate candidate ids.

## Application semantics (Phase II)

The response to generation `G` is ingested when MOSES unblocks at the end of `G` and applied to generation `G+1`'s draws. Only levers listed in the run's `LLMOSES_APPLY_LEVERS` are applied; `run_config.json.lever_switches` records the active set and per-lever weights. Every applied draw uses one mixing formula:

```
w' = w_native * (lambda * u^(1/T) + (1 - lambda))
```

where `lambda` is the per-lever weight (0 = native, 1 = full utility control with 0/1 utilities), and `T` is `sampling_temperature` (sharpens toward the max as T -> 0; null/1 = unchanged). Utilities are clamped to [0, 1]. Candidates whose `program_id` is absent from a component are treated as neutral. All-zero effective weight pools degrade to native with a `bias_degraded` audit row.

## Utility records

- Exemplar utilities: `{program_id, utility}`. Reweights the native Boltzmann selection numerators.
- Atom utility prior: `{atom, utility}` over `run_config.json.atom_alphabet.labels`. The wrapper maps atoms to combinations at the sampler draw site (width 2 boolean / 3 strategy); a combination's weight aggregates its atoms' sharpened priors per `feature_utility_levers.aggregate_fn` (`product` | `mean` | `geometric_mean` | `softmax`; default `product` — a combination is only as strong as its weakest atom). Zero-utility atoms deliberately remove combinations from the draw pool.
- Culling utilities: `{program_id, retention_utility}` (or `cull_utility` = 1 − retention). Applied at two sites: the resize cull draw (cull weight ∝ 1 − retention) and the dominated-candidate escape gate (p(keep) = lambda · retention). The special entry `{"program_id": "*", "retention_utility": r}` sets the default for candidates born after this response — without it, fresh candidates are exempt from culling guidance.
- Complexity ratio: `{direction: increase|decrease|maintain, magnitude}`. Applied once per response as ratio += lambda · magnitude (increase rewards complexity, decrease penalizes it); the rebuilt scoring context persists into later generations.
- Comparator bias: `{program_id_ordering: [...]}`, best first. Applied by re-sorting the known population at the top of the next generation; a pair is reordered only when BOTH ids appear in the ordering (merge-time inserts of newborn candidates always fall back to the native score comparison). Supply a complete ordering over the current population for a total override.

Put all reasons, audit notes, parse diagnostics, prompt/context manifests, and raw provider responses in the matching AgentTrace file under `traces/`.
