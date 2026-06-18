# LLMOSES

LLMOSES is a shadow wrapper layer for metta-moses that emits MOSES state and action information without changing the root MOSES files in place. The wrapper imports LLMOSES versions of selected modules, captures run configuration and per-generation evolutionary state, and writes structured JSON plus readiness markers for downstream agent or analysis workflows.

## Tree Overview

- `wrapper/`: MeTTa extractors and state-builder entrypoints that bridge MOSES values into Python.
- `utilities/`: Python JSON emitters, the watcher stub, and helper shims used by the wrapper.
- `skills/`: checked-in context docs for the shadow-mode utility estimator.
- `deme/`, `representation/`, `scoring/`, `feature-selection/`, `moses/`, `optimization/`: shadow MOSES files imported instead of base files where LLMOSES hooks or fixes are needed.
- `llmoses-tests/`: demo, state-capture, smoke, and pressure test entrypoints.
- `outputs/`: ignored generated logs, run metadata, state/action JSON, ready sentinels, and run-local guide files.

## Quickstart

Run these commands from the repository root after Docker Desktop is running:

```sh
make build
make shell
./run_moses_demo.sh list
./run_moses_demo.sh demo pa
```

Use the full demo sweep when you want to run every demo key exposed by the harness:

```sh
./run_moses_demo.sh demo all
```

State/action output is written under:

```text
llmoses/outputs/runs/<run-id>/{state,action,ready}
```

Demo logs are written under:

```text
llmoses/outputs/logs/
```

The latest run is recorded in `llmoses/outputs/CURRENT_RUN.json`. Runtime guide files are generated under `llmoses/outputs/` and each run directory; they are local artifacts and are not committed.

Generated runs can be listed and removed without affecting the checked-in estimator docs:

```sh
make runs-list
make run-delete RUN_ID=<run-id>
make runs-refresh-current
```

Deleting a run removes only `llmoses/outputs/runs/<run-id>`. The canonical estimator docs stay in `llmoses/skills/`; run-local Markdown files are regenerated guide artifacts.
