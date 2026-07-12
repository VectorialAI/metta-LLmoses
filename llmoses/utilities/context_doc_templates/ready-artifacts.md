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

Each `state/run-N/step-G.json` carries a top-level `capture_status`
(`{"failed_sections": [...], "ok": <bool>}`). The sentinel asserts the files are
written and self-describe their completeness — read `capture_status` rather than
assume the step is fully captured.

## Phase II return leg

After writing `utilities/` and `traces/`, the watcher drops `response/run-N-step-G`
**last**, then moves the ready sentinel into `ready/.consumed/`. When
`LLMOSES_AWAIT_RESPONSE=1`, MOSES blocks at end-of-generation-G waiting for that
response sentinel (up to `LLMOSES_RESPONSE_TIMEOUT_S` seconds), then resumes; on
timeout it proceeds natively and records a `response_timeout`. With the flag unset
(default) the await is a no-op.
