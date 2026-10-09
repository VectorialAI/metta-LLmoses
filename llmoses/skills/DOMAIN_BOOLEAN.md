# Boolean Domain

Boolean runs search logical program trees over input atoms. The static atom vocabulary appears in `run_config.json.atom_alphabet`. Realized use appears in `state/run-*/step-G-call-4.json` in two blocks:

- `atom_evidence` — counts with their totals. `atom_appearances` aggregates by `(atom, polarity, clause_type)` with `count`, `n_programs`, and `clause_adjacent`; `realized_cooccurrences` aggregates clause co-membership the same way; `n_programs_total` is the total the counts were drawn from; `atom_cumulative` accumulates appearances across generations; `degenerate_summary` tallies collapsed repeats and dropped contradictions.
- `atom_lossless` — the raw walk, always populated. One event per clause member with exact `depth`, `clause_type`, `node_ref`, and `score_ref` (the host program's id), and one event per multi-member clause. `programs[program_id]` gives each tree's `tree_max_depth` and `node_count` so depth can be normalized against the tree it came from.

Interpretation notes:

- Atom labels may include polarity, such as positive or negated forms.
- Cooccurrence evidence can indicate useful building blocks, redundant clauses, or contradictions.
- Repeated or contradictory atom use may be collapsed or counted in `degenerate_summary`.
- Depth is emitted raw with its bound; no depth band or score summary is emitted. Join `score_ref` to `candidates` if score correlations matter.
- Feature-selection runs can make atom evidence especially important because useful features may appear before a full program becomes top scoring.

Prefer candidate structures that improve score while using compact, coherent atom combinations. Avoid overvaluing complexity when added literals do not improve the trend.
