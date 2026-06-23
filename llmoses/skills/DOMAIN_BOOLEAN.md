# Boolean Domain

Boolean runs search logical program trees over input atoms. The static atom vocabulary appears in `run_config.json.atom_alphabet`, and realized use appears in `state/run-*/step-G.json.atom_evidence`.

Interpretation notes:

- Atom labels may include polarity, such as positive or negated forms.
- Cooccurrence evidence can indicate useful building blocks, redundant clauses, or contradictions.
- Repeated or contradictory atom use may be collapsed or counted in `degenerate_summary`.
- Feature-selection runs can make atom evidence especially important because useful features may appear before a full program becomes top scoring.

Prefer candidate structures that improve score while using compact, coherent atom combinations. Avoid overvaluing complexity when added literals do not improve the trend.
