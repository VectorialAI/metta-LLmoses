# LLMOSES

LLMOSES is a shadow wrapper layer for metta-moses that emits MOSES state and action information without changing the root MOSES files in place. The wrapper imports LLMOSES versions of selected modules, captures run configuration and per-generation evolutionary state, and writes structured JSON plus readiness markers for downstream agent or analysis workflows.

## Tree Overview

- `wrapper/`: MeTTa extractors and state-builder entrypoints that bridge MOSES values into Python.
- `utilities/`: Python JSON emitters, the watcher stub, and helper shims used by the wrapper.
- `skills/`: checked-in context docs for the shadow-mode utility estimator.
- `deme/`, `representation/`, `scoring/`, `feature-selection/`, `moses/`, `optimization/`: shadow MOSES files imported instead of base files where LLMOSES hooks or fixes are needed.
- `outputs/`: ignored generated logs, run metadata, state/action JSON, ready sentinels, and run-local guide files.

## Runtime status

The Docker image, Makefile, demo scripts, and LLMOSES test harness are local-only development artifacts. They are deliberately ignored and are not part of this repository's tracked source.

The MeTTa source can be run with the Petta runtime. A maintained, portable quickstart package will be added separately.

State/action output is written under:

```text
llmoses/outputs/runs/<run-id>/{state,action,ready}
```

Demo logs are written under:

```text
llmoses/outputs/logs/
```

The latest run is recorded in `llmoses/outputs/CURRENT_RUN.json`. Runtime guide files are generated under `llmoses/outputs/` and each run directory; they are local artifacts and are not committed.

Deleting a run removes only `llmoses/outputs/runs/<run-id>`. The canonical estimator docs stay in `llmoses/skills/`; run-local Markdown files are regenerated guide artifacts.
