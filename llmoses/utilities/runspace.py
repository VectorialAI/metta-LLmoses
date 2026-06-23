"""Run-directory bootstrap and shadow-agent guide-doc generation.

Keeps filesystem/run-environment concerns out of the builder. `bootstrap()`
resolves the run directory, creates the output subtree, opens the append-only
native event log, and writes run_meta.json. `ensure_context_docs()` generates the
run-local Markdown guides best-effort: a guide-doc failure must never block state
emission, but unlike a bare `pass` it records the traceback to a sidecar so the
failure is observable (and recoverable out-of-band via manage_outputs).
"""
import json
import os
import time
import traceback
from collections import namedtuple

try:
    import context_docs
except Exception:  # pragma: no cover - guide docs must not block state emission
    context_docs = None

RunSpace = namedtuple(
    "RunSpace",
    ["run_id", "run_dir", "state_dir", "action_dir", "ready_dir", "native_log"],
)

_CTX_ERR_LOG = "context_docs_errors.log"


def bootstrap(llmoses_dir, version):
    """Resolve the run dir, create state/action/ready, open the native log, and
    write run_meta.json. Called once at module import so the run dir exists before
    the first py-call. Returns a RunSpace with the open native-log handle."""
    run_dir = os.environ.get("LLMOSES_RUN_DIR")
    if not run_dir:
        run_id = os.environ.get("LLMOSES_RUN_ID") or time.strftime("%Y%m%d-%H%M%S")
        run_dir = os.path.join(llmoses_dir, "outputs", "runs", run_id)
    else:
        run_id = os.path.basename(os.path.normpath(run_dir))

    state_dir = os.path.join(run_dir, "state")
    action_dir = os.path.join(run_dir, "action")
    ready_dir = os.path.join(run_dir, "ready")
    for d in (state_dir, action_dir, ready_dir):
        os.makedirs(d, exist_ok=True)

    native_log = open(os.path.join(run_dir, "moses_native_log.jsonl"),
                      "a", buffering=1, encoding="utf-8")

    try:
        with open(os.path.join(run_dir, "run_meta.json"), "w", encoding="utf-8") as m:
            json.dump({"run_id": run_id, "mode": "shadow",
                       "builder_version": version,
                       "start_ts_ms": int(time.time() * 1000)}, m)
    except Exception:
        pass

    return RunSpace(run_id, run_dir, state_dir, action_dir, ready_dir, native_log)


def ensure_context_docs(llmoses_dir, run_id, run_dir, run_seq=None,
                        problem_type=None, problem_spec=None, active_levers=None):
    """Best-effort run-local guide generation. Non-fatal, but records failures to
    a per-run sidecar instead of swallowing them silently."""
    if context_docs is None:
        return
    try:
        context_docs.ensure_output_context(
            llmoses_dir, run_id, run_dir,
            run_seq=run_seq, problem_type=problem_type,
            problem_spec=problem_spec, active_levers=active_levers,
        )
    except Exception:
        _record_ctx_failure(run_dir)


def _record_ctx_failure(run_dir):
    """Append a timestamped traceback to the run-local context-doc error log."""
    try:
        path = os.path.join(run_dir, _CTX_ERR_LOG)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"--- {int(time.time() * 1000)} ---\n")
            fh.write(traceback.format_exc())
            fh.write("\n")
    except Exception:
        pass
