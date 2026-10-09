# LLMOSES

LLMOSES is a shadow wrapper layer for metta-moses. It captures MOSES state and action information without changing the root MOSES files in place. Milestone 2 adds four response calls per generation: row weighting, exemplar selection, a conditional atom-pair policy, and retention. The responder's adjustments are mixed with the native distributions according to the experiment configuration.

## Tree Overview

- `wrapper/`: MeTTa extractors and state-builder entrypoints that bridge MOSES values into Python.
- `utilities/`: Python state emitters, response handling, and responder tools.
- `skills/`: the checked-in response contract and agent guidance.
- `agent-configs/`: session instructions for supported agent runners.
- `configs/m2-closure.json`: the baseline M2 experiment configuration, with guidance weights set to zero.
- `run_m2.sh`: a launcher for an M2 driver using a locally supplied Docker image and Petta runtime.
- `deme/`, `representation/`, `scoring/`, `feature-selection/`, `moses/`, `optimization/`: shadow MOSES files imported instead of base files where LLMOSES hooks or fixes are needed.
- `outputs/`: ignored generated logs, run metadata, state/action JSON, ready sentinels, and run-local guide files.

## Runtime status

The Docker image, Makefile, root demo and smoke scripts, and LLMOSES test harness are local-only development artifacts. They are deliberately ignored and are not part of this repository's tracked source. The checked-in `run_m2.sh` requires a locally available image and an in-repository driver.

The MeTTa source runs with the Petta runtime. A maintained, portable quickstart package will be added separately. See `skills/ACTION_LEVERS.md` for the M2 controls and `skills/RUN_DIRECTORY.md` for the response lifecycle.

`run_m2.sh` takes `CONFIG RUNDIR DRIVER [MODE]`; all three paths must be inside the repository. The caller chooses the run directory. A conventional location is:

```text
llmoses/outputs/runs/<run-id>/{state,action,ready}
```

M2 request and response artifacts are written beneath that directory, including:

```text
state/  action/  ready/  utilities/  traces/  response/  checkpoints/
```

Generated runs and logs are local artifacts and are not committed. The canonical agent guidance stays in `llmoses/skills/`.
