"""Generate run-local context docs for LLMOSES output directories.

The canonical estimator docs live in llmoses/skills/. This module writes small
orientation files into ignored output directories so a shadow agent can inspect
a run in place without needing repository-wide context. The generated Markdown
bodies live in context_doc_templates/.
"""
import json
import os
import time

_SCHEMA_VERSION = "0.1"
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_DIR = os.path.join(_THIS_DIR, "context_doc_templates")

_MOSES_EXPLANATION = "moses-explanation.md"
_RUN_INSTRUCTIONS = "run-instructions.md"
_STATE_ARTIFACTS = "state-artifacts.md"
_ACTION_ARTIFACTS = "action-artifacts.md"
_READY_ARTIFACTS = "ready-artifacts.md"
_UTILITY_ARTIFACTS = "utility-artifacts.md"
_TRACE_ARTIFACTS = "trace-artifacts.md"


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


def _template_text(name):
    path = os.path.join(_TEMPLATE_DIR, name)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _render_template(name, **values):
    return _template_text(name).format_map(values)


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
    return _template_text(_MOSES_EXPLANATION)


def _run_instructions(run_id, run_seq, problem_type, problem_spec, active_levers):
    lever_text = ", ".join(active_levers) if active_levers else "not emitted yet"
    return _render_template(
        _RUN_INSTRUCTIONS,
        run_id=run_id,
        run_seq_text=run_seq if run_seq is not None else "not emitted yet",
        problem_summary=_problem_summary(problem_type, problem_spec),
        lever_text=lever_text,
    )


def _state_artifacts(problem_type, problem_spec):
    return _render_template(
        _STATE_ARTIFACTS,
        problem_summary=_problem_summary(problem_type, problem_spec),
    )


def _action_artifacts(active_levers):
    lever_text = ", ".join(active_levers) if active_levers else "not emitted yet"
    return _render_template(_ACTION_ARTIFACTS, lever_text=lever_text)


def _ready_artifacts():
    return _template_text(_READY_ARTIFACTS)


def _utility_artifacts():
    return _template_text(_UTILITY_ARTIFACTS)


def _trace_artifacts():
    return _template_text(_TRACE_ARTIFACTS)
