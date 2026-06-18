"""Generate run-local context docs for LLMOSES output directories.

The canonical estimator docs live in llmoses/skills/. This module writes small
orientation files into ignored output directories so a shadow agent can inspect
a run in place without needing repository-wide context.
"""
import json
import os
import time

_SCHEMA_VERSION = "0.1"


def _ts_ms():
    return int(time.time() * 1000)


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")
    os.replace(tmp, path)


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _problem_summary(problem_type, problem_spec):
    if not problem_spec:
        return "Problem spec has not been emitted yet."
    if problem_type in ("logical", "boolean"):
        labels = problem_spec.get("input_labels") or []
        return "Logical problem over inputs: " + ", ".join(str(x) for x in labels)
    if problem_type == "strategy":
        moves = problem_spec.get("moves") or []
        return "Strategy problem over moves: " + ", ".join(str(x) for x in moves)
    return "Problem type: " + str(problem_type or problem_spec.get("problem_type") or "unknown")


def ensure_output_context(llmoses_dir, run_id, run_dir, run_seq=None,
                          problem_type=None, problem_spec=None,
                          active_levers=None):
    """Write output-root and run-local guide docs for the current run."""
    outputs_dir = os.path.join(llmoses_dir, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    _write_text(os.path.join(outputs_dir, "moses-explanation.md"),
                _moses_explanation())
    _write_json(os.path.join(outputs_dir, "CURRENT_RUN.json"), {
        "schema_version": _SCHEMA_VERSION,
        "run_id": run_id,
        "run_dir": run_dir,
        "run_seq": run_seq,
        "problem_type": problem_type,
        "problem_spec": problem_spec,
        "active_levers": active_levers or [],
        "updated_ts_ms": _ts_ms(),
        "guide_files": {
            "root": os.path.join(outputs_dir, "moses-explanation.md"),
            "run": os.path.join(run_dir, "run-instructions.md"),
            "state": os.path.join(run_dir, "state", "state-artifacts.md"),
            "action": os.path.join(run_dir, "action", "action-artifacts.md"),
            "ready": os.path.join(run_dir, "ready", "ready-artifacts.md"),
            "utilities": os.path.join(run_dir, "utilities", "utility-artifacts.md"),
            "traces": os.path.join(run_dir, "traces", "trace-artifacts.md"),
        },
    })
    ensure_run_context(run_dir, run_id, run_seq, problem_type,
                       problem_spec, active_levers or [])


def ensure_run_context(run_dir, run_id, run_seq=None, problem_type=None,
                       problem_spec=None, active_levers=None):
    active_levers = active_levers or []
    for name in ("state", "action", "ready", "utilities", "traces"):
        os.makedirs(os.path.join(run_dir, name), exist_ok=True)
    _write_text(os.path.join(run_dir, "run-instructions.md"),
                _run_instructions(run_id, run_seq, problem_type,
                                  problem_spec, active_levers))
    _write_text(os.path.join(run_dir, "state", "state-artifacts.md"),
                _state_artifacts(problem_type, problem_spec))
    _write_text(os.path.join(run_dir, "action", "action-artifacts.md"),
                _action_artifacts(active_levers))
    _write_text(os.path.join(run_dir, "ready", "ready-artifacts.md"),
                _ready_artifacts())
    _write_text(os.path.join(run_dir, "utilities", "utility-artifacts.md"),
                _utility_artifacts())
    _write_text(os.path.join(run_dir, "traces", "trace-artifacts.md"),
                _trace_artifacts())


def _moses_explanation():
    return """# MOSES Explanation

This file is generated under `llmoses/outputs/` and is safe to delete with the
rest of the generated outputs. The canonical estimator docs live in
`llmoses/skills/`.

MOSES searches over program trees. Each generation selects an exemplar from the
metapopulation, expands one or more demes around that exemplar, scores generated
candidates, and merges useful candidates back into the metapopulation.

LLMOSES runs in shadow mode. It emits state and action artifacts at generation
boundaries so an estimator can score possible intervention levers without
mutating MOSES state.

The useful loop for an estimator is:

1. Read the current run pointer from `CURRENT_RUN.json`.
2. Open the run directory and read `run-instructions.md`.
3. Use `state/run-*/run_config.json` for static run context.
4. Use matching `state/run-*/step-G.json` and `action/run-*/step-G.json` files as ground truth.
5. Treat `ready/run-N-step-G` as the completion marker for generation `G`.

The checked-in source docs under `llmoses/skills/` give deeper estimator context.
"""


def _run_instructions(run_id, run_seq, problem_type, problem_spec, active_levers):
    lever_text = ", ".join(active_levers) if active_levers else "not emitted yet"
    return f"""# Run Instructions

This file is generated inside a run directory and is disposable. It exists so an
estimator can orient itself locally; the canonical estimator docs remain in
`llmoses/skills/` and are not copied into runs.

Run id: `{run_id}`
Current run sequence: `{run_seq if run_seq is not None else "not emitted yet"}`
Problem: {_problem_summary(problem_type, problem_spec)}
Active levers: {lever_text}

Read order for a utility-estimation step:

1. `run_meta.json`
2. `state/run-*/run_config.json`
3. Matching `state/run-*/step-G.json`
4. Matching `action/run-*/step-G.json`
5. Recent prior `step-*.json` files when trend context is useful
6. `moses_native_log.jsonl` for native event breadcrumbs

Use the JSON artifacts as ground truth. These markdown files only describe how
to navigate and interpret the artifacts.

Write two output artifacts for each processed ready sentinel:

- `utilities/run-N/step-G.json`: machine-consumable UtilityResponse.
- `traces/run-N/step-G.json`: AgentTrace transcript and audit artifact.

The UtilityResponse contains only:

- `pass`
- `sampling_temperature`
- `exemplar_utilities`
- `pair_utilities`
- `culling_utilities`
- `complexity_ratio_delta`
- `comparator_bias`

Put prompt/context manifests, raw model responses, read-file lists, explicit
audit reasoning, provider metadata, and parse/error diagnostics in AgentTrace.
Do not rely on hidden model chain-of-thought; traces should contain only
transcript material and explicit audit text available to the harness.

Complexity-ratio direction: `increase` rewards complexity, `decrease` penalizes
complexity, and `maintain` leaves pressure unchanged.
"""


def _state_artifacts(problem_type, problem_spec):
    return f"""# State Artifacts

This file is generated and may be deleted with its run directory. Use it as a
local guide only; JSON artifacts are ground truth.

Problem: {_problem_summary(problem_type, problem_spec)}

State files are written under `state/run-N/`.

- `run_config.json` contains static run parameters, problem spec, atom alphabet,
  active levers, and comparator availability.
- `step-G.json` is the MosesState for generation `G`.
- `terminal.json` may appear at the end of a run for final post-merge state.
- `atom_lossless-G.json` may appear when lossless atom/cooccurrence emission is
  enabled.

Common `step-G.json` sections:

- `metapopulation`: candidate programs and scores.
- `demes`: per-deme knobs, instance counts, and evaluation counts.
- `merge_summary`: merge counts and culling context.
- `lineage_diff`: selected, new, retained, and removed program ids.
- `moses_native_events`: selected native MOSES events for this generation.
- `score_vs_complexity_trend`: score and complexity direction over recent steps.
- `atom_evidence`: atom appearances and realized cooccurrences.

`step` means generation. Do not wait for renamed generation files; the current
compatibility contract is `step-G.json`.
"""


def _action_artifacts(active_levers):
    lever_text = ", ".join(active_levers) if active_levers else "not emitted yet"
    return f"""# Action Artifacts

This file is generated and may be deleted with its run directory. Use
`llmoses/skills/ACTION_LEVERS.md` for the canonical action-lever guide.

Action files are written under `action/run-N/` as `step-G.json`.

Active levers from config: {lever_text}

Current or planned action components:

- `exemplar_candidates`: candidate programs available for exemplar preference.
- `culling_candidates`: candidates exposed for retention or removal preference.
- `complexity_ratio`: current value and complexity-pressure context.
- `pair_sampling_candidates`: optional explicit pair or cooccurrence guidance.
- Comparator ordering: available only when exposed by config or action files.

Only estimate utilities for components that are actually present or explicitly
exposed. If a component is absent, return an empty array or null for that part
of the UtilityResponse.
"""


def _ready_artifacts():
    return """# Ready Artifacts

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
"""


def _utility_artifacts():
    return """# Utility Artifacts

This file is generated and may be deleted with its run directory. Use
`llmoses/skills/UTILITY_RESPONSE.md` for the canonical UtilityResponse guide.

Utility files are written under `utilities/run-N/` as `step-G.json`.

Each file is a machine-consumable UtilityResponse. It should contain only the
action utility fields needed by a downstream controller:

- `pass`
- `sampling_temperature`
- `exemplar_utilities`
- `pair_utilities`
- `culling_utilities`
- `complexity_ratio_delta`
- `comparator_bias`

Do not put prompt text, raw provider output, natural-language reasoning, or
conversation transcripts in utility files. Those belong in the matching
AgentTrace file under `traces/run-N/step-G.json`.
"""


def _trace_artifacts():
    return """# Trace Artifacts

This file is generated and may be deleted with its run directory. Use
`llmoses/skills/AGENT_TRACE.md` for the canonical AgentTrace guide.

Trace files are written under `traces/run-N/` as `step-G.json`.

Each file is an AgentTrace transcript and audit artifact for the matching
UtilityResponse. It should include available prompt/context manifests, read-file
lists, raw model responses, parsed UtilityResponse JSON, explicit audit
reasoning, provider metadata, and parse/error diagnostics.

Do not require or attempt to reconstruct hidden model chain-of-thought. Store
only transcript material and explicit reasoning or audit notes available to the
harness.
"""
