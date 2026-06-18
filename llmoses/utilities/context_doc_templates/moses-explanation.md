# MOSES Explanation

This file is generated under `llmoses/outputs/` and is safe to delete with the
rest of the generated outputs. The canonical estimator docs live in
`llmoses/skills/`.

MOSES searches over program trees. Each generation selects an exemplar from the
metapopulation, expands one or more demes around that exemplar, scores generated
candidates, and merges useful candidates back into the metapopulation.

LLMOSES runs in shadow mode. It emits state and action artifacts at generation
boundaries so an estimator can score possible intervention levers without
mutating MOSES state.

The useful loop for an estimator is:

1. Read the current run pointer from `CURRENT_RUN.json`.
2. Open the run directory and read `run-instructions.md`.
3. Use `state/run-*/run_config.json` for static run context.
4. Use matching `state/run-*/step-G.json` and `action/run-*/step-G.json` files as ground truth.
5. Treat `ready/run-N-step-G` as the completion marker for generation `G`.

The checked-in source docs under `llmoses/skills/` give deeper estimator context.
