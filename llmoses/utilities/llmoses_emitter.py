"""LLMOSES state emitter — Python-owned file I/O (v0.2).

Adds three things to the v0 text emitter, all pure file I/O (no spawning, no
threads) so the in-loop MeTTa path stays in proven-safe territory:

  1. moses_native_log.jsonl  — append-only audit of what MOSES did natively this
     generation, one JSON object per line. Each record carries run_seq so that
     records from different runMoses calls within the same process are
     distinguishable. This is the shadow-mode ground truth the LLM's utilities
     get compared against later. (Honest scope: the action TAKEN — which exemplar
     selectExemplar chose — is still UNCAPTURED_v0; this records the native
     STATE TRANSITION, which is what we can observe today.)

  2. ready/run-<seq>-step-<g> — a per-step sentinel written as the LAST action
     of emit_gen, after all channels for generation g are on disk. The watcher
     triggers on this marker, never on the data files, so a trigger provably
     means state-<g> AND action-<g> are complete. The compound name encodes the
     run sequence number so the flat ready/ dir is collision-free even when
     multiple runMoses calls fire within the same process.

  3. run_meta.json — written once at import: run id, mode, emitter version,
     start timestamp.

Per-run step-file discrimination (from v0.1): new_run() is called once at the
top of every runMoses invocation (via emitNewRun in expand-deme.metta). It
increments _run_seq and redirects _current_state_dir / _current_action_dir to
state/run-<N>/ and action/run-<N>/ so that generation 1 of run A and
generation 1 of run B never share a file.

The watcher (llmoses_watcher.py, separate process) owns utilities/ and traces/.
The emitter never touches them — it only records native state and signals
readiness via the ready/ sentinels.
"""
import os
import json
import time

_VERSION = "0.2"

# --- path resolution -------------------------------------------------------
# Combined human log. Override with LLMOSES_STATE_LOG (kept from v0 emitter).
_OVERRIDE = os.environ.get("LLMOSES_STATE_LOG")
if _OVERRIDE:
    _LOG_PATH = os.path.abspath(_OVERRIDE)
    _LLMOSES_DIR = os.path.dirname(os.path.dirname(_LOG_PATH))
else:
    _THIS_DIR = os.path.dirname(os.path.abspath(__file__))      # .../llmoses/utilities
    _LLMOSES_DIR = os.path.dirname(_THIS_DIR)                   # .../llmoses
    _LOG_PATH = os.path.join(_LLMOSES_DIR, "outputs", "states", "llmoses-state.log")

os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
_FH = open(_LOG_PATH, "a", buffering=1, encoding="utf-8")

# Per-run root. Override the full dir with LLMOSES_RUN_DIR, or just the id
# with LLMOSES_RUN_ID. The same env vars must be exported to the watcher
# process so it watches the same directory tree.
_RUN_DIR = os.environ.get("LLMOSES_RUN_DIR")
if not _RUN_DIR:
    _RUN_ID = os.environ.get("LLMOSES_RUN_ID") or time.strftime("%Y%m%d-%H%M%S")
    _RUN_DIR = os.path.join(_LLMOSES_DIR, "outputs", "runs", _RUN_ID)
else:
    _RUN_ID = os.path.basename(os.path.normpath(_RUN_DIR))

_STATE_DIR  = os.path.join(_RUN_DIR, "state")
_ACTION_DIR = os.path.join(_RUN_DIR, "action")
_READY_DIR  = os.path.join(_RUN_DIR, "ready")
for _d in (_STATE_DIR, _ACTION_DIR, _READY_DIR):
    os.makedirs(_d, exist_ok=True)

# Native audit log — one JSON line per generation, run_seq field included.
_NATIVE_LOG = os.path.join(_RUN_DIR, "moses_native_log.jsonl")
_NFH = open(_NATIVE_LOG, "a", buffering=1, encoding="utf-8")

# run_meta.json — written once at import, best-effort (never crashes the run).
try:
    with open(os.path.join(_RUN_DIR, "run_meta.json"), "w", encoding="utf-8") as _m:
        json.dump(
            {
                "run_id": _RUN_ID,
                "mode": "shadow",
                "emitter_version": _VERSION,
                "start_ts_ms": int(time.time() * 1000),
            },
            _m,
        )
except Exception:
    pass

# Per-run sequence counter. Starts at 0 (no run open yet). Incremented by
# new_run() which is called once at the top of every runMoses invocation so
# that multiple calls within the same process each land in their own sub-dir.
_run_seq = 0
_current_state_dir  = _STATE_DIR
_current_action_dir = _ACTION_DIR


# --- helpers ---------------------------------------------------------------
def _scalar(x):
    """Render whatever MeTTa marshalled as a flat token; never raise.

    We don't trust the type: a Number may arrive as int/float, but a wrapped
    atom or string could arrive as something else. Coerce loosely and, on
    failure, fall back to repr so the log SHOWS us the raw marshalled value
    rather than crashing the run.
    """
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return f"{x:g}"
    try:
        s = str(x).strip()
        return s if s else "<empty>"
    except Exception as e:  # pragma: no cover - defensive only
        return f"<unrepr:{type(x).__name__}:{e}>"


def _num(x):
    """Best-effort numeric coercion for JSON records; falls back to string."""
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return x
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        try:
            return float(str(x).strip())
        except (TypeError, ValueError):
            return _scalar(x)


def _write_combined(line):
    _FH.write(line + "\n")


def _write_step(directory, gen, line):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"step-{_scalar(gen)}.txt")
    with open(path, "a", buffering=1, encoding="utf-8") as fh:
        fh.write(line + "\n")
    return path


def _mark_ready(gen):
    """Last action of a generation: drop the ready/ sentinel.

    The sentinel name is ``run-<seq>-step-<g>`` — the run-sequence prefix
    prevents collisions between multiple runMoses calls in the same process,
    since they all share the flat ready/ directory.  A sentinel's presence on
    disk proves that state-<g> and action-<g> for this run sequence are both
    fully written.
    """
    g   = _scalar(gen)
    seq = str(_run_seq)
    path = os.path.join(_READY_DIR, f"run-{seq}-step-{g}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"{int(time.time() * 1000)}\n")
    return path


# --- public API ------------------------------------------------------------
def log_path():
    """Canary: returns the combined-log path. Called at import time from MeTTa."""
    return _LOG_PATH


def run_dir():
    return _RUN_DIR


def new_run():
    """Open a fresh per-run subdirectory for step files.

    Must be called exactly once at the start of every runMoses invocation
    (via emitNewRun in expand-deme.metta). Subsequent emit_gen calls within
    that invocation write into run-N/state/ and run-N/action/ so that
    generation 1 of run A and generation 1 of run B never collide.
    Returns the sequence number (1-based) for the new run.
    """
    global _run_seq, _current_state_dir, _current_action_dir
    _run_seq += 1
    _current_state_dir  = os.path.join(_STATE_DIR,  f"run-{_run_seq}")
    _current_action_dir = os.path.join(_ACTION_DIR, f"run-{_run_seq}")
    os.makedirs(_current_state_dir,  exist_ok=True)
    os.makedirs(_current_action_dir, exist_ok=True)
    _write_combined(f"NEW_RUN seq {_run_seq}")
    return _run_seq


def emit_state(gen_index, remaining):
    """Back-compat shim for the original two-number signature (no sentinel)."""
    g = _scalar(gen_index)
    r = _scalar(remaining)
    line = f"LLMOSES_STATE gen {g} remaining {r}"
    _write_combined(line)
    _write_step(_current_state_dir, g, line)
    return 0


def emit_gen(gen_index, remaining, pop_size, best_score, deme_size):
    """Single MeTTa entry point; writes state + action + JSONL, then sentinel.

    Argument order matches the five-scalar MeTTa call in state-emitter.metta
    and must not change:
      gen_index  : ascending 1-based generation number
      remaining  : the loop's native descending counter ($maxGen)
      pop_size   : OS.length of the metapopulation going into this generation
      best_score : penalized score of the current top exemplar
      deme_size  : number of scored instances in the optimized deme this gen
    """
    g     = _scalar(gen_index)
    rem   = _scalar(remaining)
    pop   = _scalar(pop_size)
    best  = _scalar(best_score)
    dsize = _scalar(deme_size)

    # Channel 1 — METAPOP: the outer-loop population snapshot for this gen.
    metapop_line = (
        f"METAPOP gen {g} remaining {rem} pop_size {pop} best_penalized_score {best}"
    )
    # Channel 2 — DEME: the inner-loop neighborhood that was just optimized.
    deme_line = f"DEME gen {g} optimized_instances {dsize}"
    # Channel 3 — ACTION: in Phase I shadow mode, the action SPACE available this
    # gen. The action actually TAKEN (which exemplar selectExemplar chose) lives
    # inside expandDeme and needs a trace hook (v8 D-012) — deferred past v0.
    action_line = (
        f"ACTION gen {g} candidate_exemplars {pop} action_taken UNCAPTURED_v0"
    )

    # Human-readable combined log — all channels interleaved, easy to tail -f.
    _write_combined(metapop_line)
    _write_combined(deme_line)
    _write_combined(action_line)

    # Discrete per-step text files (state = metapop + deme; action separate).
    _write_step(_current_state_dir,  g, metapop_line)
    _write_step(_current_state_dir,  g, deme_line)
    _write_step(_current_action_dir, g, action_line)

    # Native audit log — one JSON line per generation, run_seq included so
    # records from different runMoses calls in the same process are distinct.
    _NFH.write(json.dumps({
        "run_seq":                    _run_seq,
        "generation":                 _num(gen_index),
        "remaining":                  _num(remaining),
        "pop_size":                   _num(pop_size),
        "best_penalized_score":       _num(best_score),
        "deme_optimized_instances":   _num(deme_size),
        "action_taken":               None,   # UNCAPTURED_v0: needs expandDeme hook
        "ts_ms":                      int(time.time() * 1000),
    }) + "\n")

    # MUST be last: signals that state-<g> and action-<g> are both complete.
    _mark_ready(g)
    return 0
