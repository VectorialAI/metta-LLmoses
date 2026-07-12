# Run Directory

The estimator receives one run directory, usually under `llmoses/outputs/runs/<run-id>/`.

Run directories are generated artifacts and may be deleted. Canonical estimator
docs live in `llmoses/skills/`; Markdown files inside a run are regenerated
orientation guides, not the source of truth.

Current compatibility layout:

```text
<run-id>/
  run_meta.json
  moses_native_log.jsonl
  run-instructions.md
  state/
    state-artifacts.md
    run-1/
      run_config.json
      step-1.json
      step-2.json
  action/
    action-artifacts.md
    run-1/
      step-1.json
      step-2.json
  ready/
    ready-artifacts.md
    run-1-step-1
  utilities/
    run-1/
      step-1.json
  traces/
    run-1/
      step-1.json
  response/
    run-1-step-1
```

`step-G.json` means generation `G`. The ready sentinel is written after the matching state and action JSON files, so its presence means both files are present. With flush-layer fail-flags, each `step-G.json` also carries a top-level `capture_status` (`{"failed_sections": [...], "ok": <bool>}`): the sentinel now asserts "written and self-describing its own completeness," so a consumer must read `capture_status` rather than assume the step is fully captured. A run total (per-kind, incl. `response_timeout`) lands in `state/run-N/terminal.json` under `capture_failures`; a nonzero total means the run was partly blind.

After a watcher or live agent consumes `ready/run-N-step-G`, it writes the machine-consumable UtilityResponse to `utilities/run-N/step-G.json` and the AgentTrace transcript/audit artifact to `traces/run-N/step-G.json`.

## Phase II return leg (blocking handshake)

`response/` is the return channel. After the watcher finishes `utilities/` + `traces/` for a step, it drops `response/run-N-step-G` **last** (symmetric to the emitter writing `ready/` last). When `LLMOSES_AWAIT_RESPONSE=1`, MOSES blocks at the end of generation `G` waiting for that sentinel, up to `LLMOSES_RESPONSE_TIMEOUT_S` seconds (default 30; poll interval `LLMOSES_RESPONSE_POLL_S`, default 0.05). On response it resumes; on timeout / missing watcher it logs a `response_timeout` row to `moses_native_log.jsonl`, counts it, and proceeds natively — a broken responder degrades to native, never deadlocks. With the flag unset (default), the await is a no-op and runs behave exactly as before.

`llmoses/outputs/CURRENT_RUN.json` points to the most recent run directory. `llmoses/outputs/moses-explanation.md` gives run-independent MOSES context.
