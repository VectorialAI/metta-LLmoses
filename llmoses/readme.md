# LLMOSES

LLMOSES is a shadow wrapper layer for metta-moses that emits MOSES state and action information without changing the root MOSES files in place. The wrapper imports LLMOSES versions of selected modules, captures run configuration and per-generation evolutionary state, and writes structured JSON plus readiness markers for downstream agent or analysis workflows.

## Tree Overview

- `wrapper/`: MeTTa extractors and state-builder entrypoints that bridge MOSES values into Python.
- `utilities/`: Python JSON emitters, the watcher stub, and helper shims used by the wrapper.
- `skills/`: checked-in context docs for the shadow-mode utility estimator.
- `deme/`, `representation/`, `scoring/`, `feature-selection/`, `moses/`, `optimization/`: shadow MOSES files imported instead of base files where LLMOSES hooks or fixes are needed.
- `llmoses-tests/`: centralized demo, state-capture, smoke, and pressure test entrypoints. This is an intentional harness layout exception to the repo's per-folder `tests/` convention.
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

## Milestone II: Utility-Guided Search

M1 only observes. M2 adds a blocking handshake: MOSES pauses each generation for
a `UtilityResponse` (schema in `llmoses/skills/UTILITY_RESPONSE.md`) and can
apply it across five levers — exemplar selection, culling, comparator re-sort,
complexity ratio, and atom-prior weighted sampling (global, context-conditioned,
and combination-synergy) — before resuming. The estimator is pluggable behind
one env var; the mechanism is identical whether the response comes from a
deterministic mock, a live LLM call, or (later) a supervising agent.

### Switch planes

Two independent env-driven planes, recorded in every run's `run_config.json`
under `lever_switches`:

- `LLMOSES_EMIT_LEVERS` — comma-separated list of outbound state sections the
  estimator gets to see. Default: all sections.
- `LLMOSES_APPLY_LEVERS` — comma-separated list of `UtilityResponse` components
  actually applied to MOSES's policy. **Default: empty — pure shadow.** Nothing
  is applied unless you opt in, even with a live agent running.
- `LLMOSES_LEVER_WEIGHT_<NAME>` (e.g. `LLMOSES_LEVER_WEIGHT_ATOM_PRIOR`) — per-lever
  mixing weight λ in `[0,1]`, default `1.0` for any lever in the apply set. One
  formula everywhere: `w' = w_native · (λ·û + (1−λ))` — λ=0 is exactly native
  behavior, λ=1 with 0/1 utilities is explicit control.
- `LLMOSES_RNG_SEED` — the embedding runtime seeds Python's RNG deterministically,
  so fixed inputs repeat byte-for-byte unless you force a seed. Set this per
  replication for any experiment that treats runs as independent samples.

### Estimator modes

`LLMOSES_MOCK_UTILITY_MODE` on the watcher (`llmoses/utilities/llmoses_watcher.py`)
selects the responder:

- `neutral` (default), `ingest_probe`, `force_worst`, `cull_targets`, `retain_all`,
  `reverse_order`, `ratio_increase`, `atom_pair`, `ctx_parent_op`, `ctx_depth`,
  `ctx_polarity`, `ctx_zero_weights`, `synergy_pair`, `evidence_pair` — deterministic
  fixtures for per-lever control testing; see `llmoses/llmoses-tests/utility_policy_test.sh`.
- `live` — routes through `llmoses/utilities/live_estimator.py`: builds the
  per-generation slot enumeration (`response_template.build_slots`), renders
  `llmoses/skills/ESTIMATOR_PROMPT.md`, calls a real provider (`codex exec` by
  default), retries once on error with the failure appended, falls back to
  value-level salvage, then a neutral decline. Configured by:
  - `LLMOSES_LIVE_MODEL` (default `gpt-5.5`), `LLMOSES_LIVE_EFFORT` (default `medium`)
  - `LLMOSES_LIVE_TIMEOUT_S` (default `240`, per attempt), `LLMOSES_LIVE_RETRIES` (default `2`)
  - `LLMOSES_LIVE_COVERAGE=full` asks the model to value every enumerated slot
    (used by the demos below); default `sparse`
  - `LLMOSES_LIVE_CMD` overrides the provider command (the offline-test seam)

Every document, mock or live, is validated by
`llmoses/utilities/utility_schema.py::validate_utility_response` before it
reaches MOSES; invalid output is salvaged component-by-component and degrades to
a neutral decline only when nothing survives.

### Running the live-agent demo

Host-side (the watcher and provider CLI run on the host; PeTTa runs in Docker —
the file-handshake makes this split free):

```sh
llmoses/llmoses-tests/live_agent_demo.sh bool-std /path/to/outdir
llmoses/llmoses-tests/live_agent_demo.sh bool-cull /path/to/outdir
llmoses/llmoses-tests/live_agent_demo.sh strategy /path/to/outdir
```

Each run applies all five levers at λ=1 with coverage=full and writes a full
run directory (state/action/utilities/traces) plus a `run/` subtree under the
given outdir. Audit with:

```sh
python3 llmoses/llmoses-tests/live_agent_verify.py /path/to/outdir/run
```

which hard-fails on schema violations, unexpected declines, unknown ids, or
missing lever coverage, and reports per-lever application counts.

### Running the lambda-dial demo

Deterministic-mock demonstration of the λ mixing formula, independent of any
live provider:

```sh
llmoses/llmoses-tests/lambda_sweep_demo.sh atom_pair "0.25,0.5,0.75,1.0" 15 /path/to/outdir
llmoses/llmoses-tests/lambda_sweep_demo.sh synergy_pair "0.25,0.5,0.75,1.0" 10 /path/to/outdir
```

`LLMOSES_SWEEP_DRIVER=std|cull` selects the driver (`cull` retains multi-literal
programs so `evidence_pair` has real co-occurrence evidence to read).
`LLMOSES_SWEEP_SEED_BASE` seeds each rep. The script exits non-zero if the
measured first-pick share at any intermediate λ falls outside its theoretical
95% Wilson interval, or if the λ=0/λ=1 endpoints aren't exact.

### Tests

```sh
docker run --rm -v "$PWD:/workspace/metta-moses" -w /workspace/metta-moses metta-llmoses \
  bash llmoses/llmoses-tests/phase2_handshake_test.sh
docker run --rm -v "$PWD:/workspace/metta-moses" -w /workspace/metta-moses metta-llmoses \
  bash llmoses/llmoses-tests/utility_policy_test.sh
docker run --rm -v "$PWD:/workspace/metta-moses" -w /workspace/metta-moses metta-llmoses \
  python3 llmoses/llmoses-tests/resolution_regression_test.py   # also runs bare on host
python3 llmoses/llmoses-tests/response_template_test.py         # host, no PeTTa
python3 llmoses/llmoses-tests/live_estimator_test.py             # host, stubbed provider
```

### Output locations

```text
llmoses/outputs/live-demo/<demo>/       live-agent demo runs (gitignored)
llmoses/outputs/lambda-sweep/           lambda-dial demo runs (gitignored)
```

Both are runtime artifacts under the same `llmoses/outputs/*` gitignore rule as
Milestone I output; nothing here is committed.

### Known gap

Guided-vs-baseline experiments (design doc §8.2.4 — convergence, quality,
overhead, ablation, per-lever λ default tuning) have not been run. The
mechanism above is implemented and validated per-lever; it has not yet been
used to produce a guided-vs-baseline result.
