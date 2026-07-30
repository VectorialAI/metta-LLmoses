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
```

`step-G.json` means generation `G`. The ready sentinel is written after the matching state and action JSON files, so its presence means both files are complete.

After a watcher or live agent consumes `ready/run-N-step-G`, it writes the machine-consumable UtilityResponse to `utilities/run-N/step-G.json` and the AgentTrace transcript/audit artifact to `traces/run-N/step-G.json`.

`llmoses/outputs/CURRENT_RUN.json` points to the most recent run directory. `llmoses/outputs/moses-explanation.md` gives run-independent MOSES context.
