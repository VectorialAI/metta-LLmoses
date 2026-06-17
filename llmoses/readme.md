# LLMOSES

LLMOSES is a shadow wrapper layer for metta-moses that emits MOSES state and action information without changing the root MOSES files in place. The wrapper imports LLMOSES versions of selected modules, captures run configuration and per-generation evolutionary state, and writes structured JSON plus readiness markers for downstream agent or analysis workflows.

## Tree Overview

- `wrapper/`: MeTTa extractors and state-builder entrypoints that bridge MOSES values into Python.
- `utilities/`: Python JSON emitters, the watcher stub, and helper shims used by the wrapper.
- `deme/`, `representation/`, `scoring/`, `feature-selection/`, `moses/`, `optimization/`: shadow MOSES files imported instead of base files where LLMOSES hooks or fixes are needed.
- `llmoses-tests/`: demo, state-capture, smoke, and pressure test entrypoints.
- `outputs/`: generated logs, run metadata, state/action JSON, and ready sentinels.

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
