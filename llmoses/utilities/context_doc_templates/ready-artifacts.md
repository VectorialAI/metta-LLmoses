# Ready Artifacts

This file is generated and may be deleted with its run directory.

Ready sentinels are written under `ready/` and named `run-N-step-G`.

The sentinel is written after the matching state and action JSON files, so it is
the safe trigger for an external watcher or estimator. A watcher may move
processed sentinels into `ready/.consumed/`.

For `run-N-step-G`, read:

- `state/run-N/step-G.json`
- `action/run-N/step-G.json`

The watcher or live agent should write both:

- `utilities/run-N/step-G.json`
- `traces/run-N/step-G.json`

Only after both files are written should a watcher move the sentinel into
`ready/.consumed/`.
