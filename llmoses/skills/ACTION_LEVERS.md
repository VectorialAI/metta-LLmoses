# Action Levers

Only score levers that are present in the current ActionVector or explicitly supported by `run_config.json.active_levers`.

Exemplar selection:

- Prefer candidates with strong penalized score and plausible room for useful local search.
- Preserve structural diversity when top scores are close.
- Be cautious about repeatedly selecting already explored candidates unless the trend supports deeper local search.

Culling and retention:

- Retain high-quality, diverse, and non-dominated candidates.
- Avoid premature culling of candidates with useful atoms, complementary structure, or promising raw score.
- Penalize candidates whose complexity rises without score improvement.

Complexity ratio:

- `increase` means reward complexity by reducing the effective complexity penalty.
- `decrease` means penalize complexity by increasing pressure against complex programs.
- `maintain` means leave complexity pressure unchanged.
- Trends in per-member `complexity` and `cscore.penalized_score` across recent steps may indicate if complexity increases are benegicial.

Comparator ordering:

- If exposed, bias ordering toward score, diversity, novelty, lower complexity, or other documented comparator dimensions.
- Do not invent comparator dimensions absent from the current state/config.

Pair or cooccurrence guidance:

- Prefer explicit `pair_sampling_candidates` when available.
- If not available, `atom_evidence` can still guide which atoms or cooccurrences look useful.
- For boolean domains, watch polarity and repeated or contradictory literals.
- For strategy domains, treat move cooccurrence as sequence or policy structure evidence, not boolean literal logic.
