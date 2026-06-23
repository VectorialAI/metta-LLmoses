# MOSES Overview

MOSES is an evolutionary search loop over program trees. A run keeps a metapopulation of candidate programs, selects an exemplar, expands one or more demes around that exemplar, scores generated candidates, then merges survivors back into the metapopulation.

The LLMOSES wrapper runs in shadow mode. It records the state and exposed action space at generation boundaries, but it does not currently feed estimator choices back into MOSES.

Core concepts:

- Metapopulation: the current global pool of candidate programs.
- Exemplar: the selected program used as the center for local expansion.
- Deme: a local neighborhood search around an exemplar.
- Knobs: editable program locations exposed during neighborhood generation.
- Score: problem fitness, usually reported as raw score plus complexity and penalty fields.
- Merge: the step that combines new candidates with the metapopulation and removes dominated or excess entries.
- Ready sentinel: the filesystem marker that a state/action pair for a generation is complete.

The estimator should prefer changes that plausibly improve later fitness, retain structurally useful diversity, and avoid unnecessary complexity unless score trends justify it.
