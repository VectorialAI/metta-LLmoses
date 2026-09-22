# LLMOSES M2 closure staging

This overlay implements four sequential calls per generation on the rebased
MOSES tree. The staging branch is `codex/m2-closure`; preservation commit
`77df0fdf` retains the earlier hardening work. Implementation is under review;
the user requested a pause before all testing and runtime verification.

Read [implementation handoff](../docs/m2-closure/IMPLEMENTATION.md),
[lever contracts](skills/ACTION_LEVERS.md), [responses](skills/UTILITY_RESPONSE.md),
and [run lifecycle](skills/RUN_DIRECTORY.md). Revised plan §0 supersedes earlier
absolute utilities and masks. No comparator or complexity-ratio agent lever remains.

The experiment JSON is [configs/m2-closure.json](configs/m2-closure.json).
It explicitly sets selection temperature and defaults every b to zero. Copy it
for a guided arm and choose b per lever; declare all arm controls in that file.
Native source files are untouched. All required overlay imports must be used
exactly once; general-helpers, bscore and demo-problems are additive shims.

Prepared commands for the testing phase (not executed during implementation):

```sh
python3 -m unittest discover -s llmoses/llmoses-tests -p '*_test.py'
bash llmoses/llmoses-tests/m2_runtime_test.sh OUTPUT_DIRECTORY
```

Use `llmoses/run_m2.sh CONFIG RUNDIR DRIVER [MODE]` for a Boolean runtime driver.
MODE is neutral, identity, prefer_worst, pair_policy, live, or external (default).
Live mode invokes a configured provider; external leaves responder ownership to
agent_tools. The runner does not silently enable retired environment controls.
Infrastructure failures pause and retain the run's checkpoint. No runner has
been executed in this implementation phase.
