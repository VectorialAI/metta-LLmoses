# Run Directory

The estimator receives one run directory, usually under `llmoses/outputs/runs/<run-id>/`.

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
  traces/
```

`step-G.json` means generation `G`. The ready sentinel is written after the matching state and action JSON files, so its presence means both files are complete.

`llmoses/outputs/CURRENT_RUN.json` points to the most recent run directory. `llmoses/outputs/moses-explanation.md` gives run-independent MOSES context.
