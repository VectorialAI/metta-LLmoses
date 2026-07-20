# UtilityResponse

Write exactly one valid JSON object to `utilities/run-N/step-G.json`. Do not wrap it in Markdown.

UtilityResponse is the machine-consumable action utility output. It should not contain prompt text, raw model responses, natural-language reasoning, or transcript material. Those belong in `traces/run-N/step-G.json`.

Required top-level fields (no others are read; unknown fields fail source validation and are reported in the ingest `ignored` map):

```json
{
  "pass": true,
  "sampling_temperature": null,
  "exemplar_utilities": [],
  "atom_utility_prior": [],
  "combination_synergy": [],
  "feature_utility_levers": null,
  "culling_utilities": [],
  "complexity_ratio_delta": null,
  "comparator_bias": null
}
```

`pass` should be `true` when no intervention is justified, evidence is insufficient, or all exposed levers should stay neutral. `pass: true` clears the wrapper's utility buffer — every lever runs natively that generation.

Use empty arrays or `null` for components that are not exposed in the current files. Do not fabricate candidate ids — and prefer the construction path that makes fabrication impossible:

## Producing this document (slot template — the recommended path)

`llmoses/utilities/response_template.py` inverts generation: `build_slots(state, run_config)` enumerates every legal estimation target for the generation — real program ids (plus the `cull:*` newborn default), alphabet atoms, observed evidence buckets, enumerated combination sets, lever axes, and the enum/scalar knobs — and you supply nothing but a value per slot. `json_schema(slots)` exports a closed per-generation JSON Schema (`additionalProperties: false`, closed enums) for provider-side constrained decoding; `assemble(slots, values, run_config)` deterministically builds this document (rank slots sort into `program_id_ordering`; omitted slots emit nothing, which the mixing formula treats as neutral) and asserts it through the validator. A document built this way cannot reference an id that does not exist.

Validation is two-tier (`utility_schema.validate_utility_response(doc, atom_alphabet)`): shape always (closed key set, closed vocabularies, unit intervals, finiteness, duplicate rejection — one entry per program id, per (atom, context) pair, per unordered synergy set); run context when the alphabet is supplied (atom labels must exist, synergy sets must be exactly the problem width). Writers that do not use the template must validate before writing; an invalid document is salvaged component-by-component at the writer gate (valid entries kept, drops reported in trace `parse_diagnostics`), degrading to a neutral decline only when nothing survives.

## Application semantics (Phase II)

The response to generation `G` is ingested when MOSES unblocks at the end of `G` and applied to generation `G+1`'s draws. Only levers listed in the run's `LLMOSES_APPLY_LEVERS` are applied; `run_config.json.lever_switches` records the active set and per-lever weights. Every applied draw uses one mixing formula:

```
w' = w_native * (lambda * u^(1/T) + (1 - lambda))
```

where `lambda` is the per-lever weight (0 = native, 1 = full utility control with 0/1 utilities), and `T` is `sampling_temperature` (sharpens toward the max as T -> 0; null/1 = unchanged). Utilities are clamped to [0, 1]. Candidates whose `program_id` is absent from a component are treated as neutral. All-zero effective weight pools degrade to native with a `bias_degraded` audit row.

## Utility records

- Exemplar utilities: `{program_id, utility}`. Reweights the native Boltzmann selection numerators.
- Atom utility prior: `{atom, utility}` over `run_config.json.atom_alphabet.labels`, optionally with a `context` object (below). The wrapper maps atoms to combinations at the sampler draw site (width 2 boolean / 3 strategy); a combination's weight aggregates its atoms' sharpened priors per `feature_utility_levers.aggregate_fn` (`product` | `mean` | `geometric_mean` | `softmax`; default `product` — a combination is only as strong as its weakest atom). Zero-utility atoms deliberately remove combinations from the draw pool.
- Combination synergy: `{atoms: [..], utility}` — an unordered atom set (width 2 boolean / 3 strategy) with a non-separable utility: "these atoms together", which no symmetric aggregate of individual priors can express. Applied as a multiplier on the matching combination's aggregated weight, gated by `feature_utility_levers.lever_weights.combination_synergy`.
- Culling utilities: `{program_id, retention_utility}` (or `cull_utility` = 1 − retention). Applied at two sites: the resize cull draw (cull weight ∝ 1 − retention) and the dominated-candidate escape gate (p(keep) = lambda · retention). The special entry `{"program_id": "*", "retention_utility": r}` sets the default for candidates born after this response — without it, fresh candidates are exempt from culling guidance.
- Complexity ratio: `{direction: increase|decrease|maintain, magnitude}`. Applied once per response as ratio += lambda · magnitude (increase rewards complexity, decrease penalizes it); the rebuilt scoring context persists into later generations. A bare direction string is NOT accepted — always the object.
- Comparator bias: `{program_id_ordering: [...]}`, best first. Applied by re-sorting the known population at the top of the next generation; a pair is reordered only when BOTH ids appear in the ordering (merge-time inserts of newborn candidates always fall back to the native score comparison). Supply a complete ordering over the current population for a total override.

## Contextual atom priors (`context` + `lever_weights`)

An `atom_utility_prior` entry may carry a `context` object restricting when it applies, in the SAME vocabulary the state's `atom_evidence.atom_appearances` buckets use:

```json
{"atom": "X1", "utility": 0.2,
 "context": {"parent_operator": "OR", "depth_bucket": "mid", "polarity": "-"}}
```

Recognized context keys and values:

- `polarity`: `"+"` | `"-"` — the atom's polarity in the drawn combination. Boolean pairs only ever realize two of the four sign patterns at the draw site (the sampler emits `(NOT first, second)` for ascending index pairs and a positive pair otherwise); full polarity control is a knob-stage setting resolved later by hill climbing and is out of scope for this lever.
- `clause_type` / `parent_operator`: `"AND"` | `"OR"` | `"PRIORITIZED-OR"` — the clause the drawn combination will inhabit (under alternating canonicalization these coincide, exactly as in `atom_evidence`).
- `depth_bucket`: `"shallow"` | `"mid"` | `"deep"` — depth band of the clause the combination will create (same banding as `atom_evidence`: 0 shallow, 1–2 mid, 3+ deep).
- `exemplar_id`: a `program_id` — applies only while building the representation seeded by that exemplar (a real axis only when n_deme > 1).

A contextual entry applies only when every key it names matches the live draw context, weighted by `feature_utility_levers.lever_weights`:

```json
"feature_utility_levers": {
  "aggregate_fn": "product",
  "lever_weights": {"polarity": 0, "clause_type": 0, "parent_operator": 0,
                    "tree_depth": 0, "selected_exemplar": 0,
                    "combination_synergy": 0, "novelty": 0}
}
```

Each weight is in [0, 1]. A matching contextual entry blends into the atom's effective utility as `u = (1-w)*u + w*u_ctx`, where `w` is the product of the lever weights of the axes the entry conditions on (`polarity`, `clause_type`, `parent_operator` → those axes; `depth_bucket` → `tree_depth`; `exemplar_id` → `selected_exemplar`). Entries apply in response order. **All-zero or absent `lever_weights` means the global (context-free) prior alone applies — the default.** Entries whose named axes multiply to zero can never apply; ingest prunes them (reported in the `utility_ingest` row's `inert` map) so the draw site stays on the untouched native path. If you supply contextual entries or synergy, set the matching axes non-zero or the entries are inert by construction. `novelty` has no wrapper-side application: fold novelty/diversity pressure into the priors you emit (`atom_cumulative` is in the state for exactly this).

Put all reasons, audit notes, parse diagnostics, prompt/context manifests, and raw provider responses in the matching AgentTrace file under `traces/`.
