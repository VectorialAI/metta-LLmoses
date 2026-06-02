"""LLMOSES state builder — list-marshalling accumulator (v0.4).

Receives extractor outputs across py-call. The marshalling was PROBED, not
assumed: MeTTaLog hands Python native values recursively —
  bare Number          -> int / float
  (mkX $payload)       -> ['mkX', <payload>]            (atom: [name, payload])
  (Cons h t) / Nil     -> ['Cons', h, t] / 'Nil'        (list spine)
  preOrder expr        -> nested list, e.g. ['OR', ['NOT', 'A']]
  cscoreFields         -> flat [raw, cpxy, cpen, upen, pen]
So everything crosses in ONE py-call per value; Python unwraps. No MeTTa-side
unwrap helpers, no streaming accumulator required for Phase I sizes.

I/O design is copied verbatim from the proven llmoses_emitter.py: per-run
subdirs via new_run(), ready/ sentinels written LAST, append-only JSONL native
log, run_meta.json, permissive coercion that surfaces bad marshalling as a
visible value rather than crashing the run.

Lives in llmoses/utilities/ (on PYTHONPATH), imported from MeTTa as
  !(import! &self "state_builder.py")
"""
import os
import json
import time
import hashlib

_VERSION = "0.4-mvp"

# --- path resolution (same contract as llmoses_emitter.py) -----------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))      # .../llmoses/utilities
_LLMOSES_DIR = os.path.dirname(_THIS_DIR)                   # .../llmoses

_RUN_DIR = os.environ.get("LLMOSES_RUN_DIR")
if not _RUN_DIR:
    _RUN_ID = os.environ.get("LLMOSES_RUN_ID") or time.strftime("%Y%m%d-%H%M%S")
    _RUN_DIR = os.path.join(_LLMOSES_DIR, "outputs", "runs", _RUN_ID)
else:
    _RUN_ID = os.path.basename(os.path.normpath(_RUN_DIR))

_STATE_DIR = os.path.join(_RUN_DIR, "state")
_ACTION_DIR = os.path.join(_RUN_DIR, "action")
_READY_DIR = os.path.join(_RUN_DIR, "ready")
for _d in (_STATE_DIR, _ACTION_DIR, _READY_DIR):
    os.makedirs(_d, exist_ok=True)

_NATIVE_LOG = os.path.join(_RUN_DIR, "moses_native_log.jsonl")
_NFH = open(_NATIVE_LOG, "a", buffering=1, encoding="utf-8")

try:
    with open(os.path.join(_RUN_DIR, "run_meta.json"), "w", encoding="utf-8") as _m:
        json.dump({"run_id": _RUN_ID, "mode": "shadow",
                   "builder_version": _VERSION, "start_ts_ms": int(time.time() * 1000)}, _m)
except Exception:
    pass

# --- per-run + per-gen accumulator state -----------------------------------
_run_seq = 0
_cur_state_dir = _STATE_DIR
_cur_action_dir = _ACTION_DIR
_gen = {}                 # gen -> accumulating record
_prev_member_ids = set()  # cross-generation lineage diff
_pending_selection = None  # buffered {id, tree} from set_selection, consumed by flush_gen


# ===========================================================================
# Marshalling unwrap helpers — matched to the PROBED shapes (see module docstring)
# ===========================================================================
def _is_nil(x):
    return x == "Nil" or x == ["Nil"]


def unwrap_atom(x):
    """['mkMultip', 3] -> 3 ; ['mkDemeId', '1'] -> '1' ; bare value -> unchanged.
    Only unwraps the shallow [name, payload] atom shape; leaves anything else."""
    if isinstance(x, list) and len(x) == 2 and isinstance(x[0], str):
        return x[1]
    return x


def cons_to_list(x):
    """Flatten a Cons spine to a flat Python list.
       ['Cons', 1.0, ['Cons', 0.0, 'Nil']] -> [1.0, 0.0]
       'Nil' -> []
    Also accepts a wrapped list atom like ['mkBScore', <spine>] and unwraps first."""
    # unwrap a single-payload wrapper (e.g. mkBScore) if present
    if isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and x[0] != "Cons":
        x = x[1]
    out = []
    cur = x
    while isinstance(cur, list) and len(cur) == 3 and cur[0] == "Cons":
        out.append(cur[1])
        cur = cur[2]
    return out


def expr_to_str(x):
    """Render a marshalled preOrder expression (nested list) to an s-expression
    string for stable hashing/display. Scalars pass through as str."""
    if isinstance(x, list):
        if not x:
            return "()"
        return "(" + " ".join(expr_to_str(e) for e in x) + ")"
    return str(x)


def _num(x):
    """Best-effort numeric coercion; falls back to a flat string. Never raises."""
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
            return _flat(x)


def _flat(x):
    try:
        return str(x).strip()
    except Exception:
        return "<unrepr>"


def _cr_or_none(x):
    """Coerce complexity_ratio to float/int or None.
    The boolean context emits () (marshalled as '()' or [] or empty string);
    treat any of those as absent → JSON null. Real numeric values pass through _num."""
    if x is None:
        return None
    s = str(x).strip()
    if s in ("", "()", "Nil"):
        return None
    if isinstance(x, list) and len(x) == 0:
        return None
    return _num(x)


def _pid(expr_str):
    return "p" + hashlib.sha1(expr_str.encode("utf-8")).hexdigest()[:10]


def _blank(gen):
    return {"generation": gen, "members": [], "knobs": [],
            "deme_id": None, "deme_tree": None, "deme_instances": None}


def _gs(gen):
    g = _num(gen)
    if g not in _gen:
        _gen[g] = _blank(g)
    return _gen[g]


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp, path)


# ===========================================================================
# Public API — MeTTa entry points (all receive list-marshalled values)
# ===========================================================================
def sb_run_dir():
    return _RUN_DIR


def new_run():
    """Open a fresh per-run subdir. Call once at the top of each runMoses."""
    global _run_seq, _cur_state_dir, _cur_action_dir, _prev_member_ids, _pending_selection
    _run_seq += 1
    _cur_state_dir = os.path.join(_STATE_DIR, f"run-{_run_seq}")
    _cur_action_dir = os.path.join(_ACTION_DIR, f"run-{_run_seq}")
    os.makedirs(_cur_state_dir, exist_ok=True)
    os.makedirs(_cur_action_dir, exist_ok=True)
    _prev_member_ids = set()
    _pending_selection = None
    return _run_seq


def begin_gen(gen):
    _gen[_num(gen)] = _blank(_num(gen))
    return 0


def add_member(gen, expr, tree, cscore, bscore):
    """One call per metapopulation member.
      expr   : marshalled preOrder expression — SHORT display form (nested list).
               NB preOrder currently collapses children, so this is for
               human/agent readability only.
      tree   : marshalled RAW tree (full mkTree structure). Used for program_id
               because it is collision-resistant: two distinct programs cannot
               share a raw tree, whereas preOrder can flatten distinct programs
               to the same short form. Identity off the full tree; display off
               the (possibly lossy) preOrder.
      cscore : flat [raw, cpxy, cpen, upen, pen]
      bscore : ['mkBScore', <Cons spine>]  (or bare spine / Nil)
    """
    es = expr_to_str(expr)          # short display
    ts = expr_to_str(tree)          # full raw tree -> stable identity
    cs = [_num(v) for v in (cscore if isinstance(cscore, list) else [cscore])]
    # pad/truncate defensively to 5 fields so a bad marshal is visible, not fatal
    while len(cs) < 5:
        cs.append(None)
    bs = [_num(v) for v in cons_to_list(bscore)]
    _gs(gen)["members"].append({
        "program_id": _pid(ts),     # hash the FULL tree, not the lossy display
        "expr": es,
        "tree": ts,                 # full structural rendering (audit / debug)
        "cscore": {
            "raw_score": cs[0], "complexity": cs[1], "complexity_penalty": cs[2],
            "uniformity_penalty": cs[3], "penalized_score": cs[4],
        },
        "complexity": cs[1],
        "bscore": bs if bs else None,
    })
    return 0


def add_knob(gen, loc, multip, default):
    """One call per deme knob. loc=['mkNodeId',[..]], multip=['mkMultip',n], default=n."""
    m = _num(unwrap_atom(multip))
    _gs(gen)["knobs"].append({
        "knob_id": _flat(unwrap_atom(loc)) if not isinstance(unwrap_atom(loc), (int, float)) else unwrap_atom(loc),
        "multiplicity": m,
        "default_setting": _num(default),
    })
    return 0


def set_deme_meta(gen, deme_id, deme_tree, instances):
    s = _gs(gen)
    s["deme_id"] = _flat(unwrap_atom(deme_id))
    s["deme_tree"] = expr_to_str(deme_tree)
    s["deme_instances"] = _num(instances)
    return 0


def set_selection(tree):
    """post_selection hook: record the exemplar selectExemplar chose THIS gen.
    Called from inside expandDeme with the FULL raw tree — same value the member
    loop hashes — so the program_id matches a candidate's id.
    Buffered (expandDeme lacks $genIndex); flush_gen consumes + validates it.
    A MISMATCH signals a real defect (stale buffer / multi-or-zero selection /
    non-canonical id)."""
    global _pending_selection
    ts = expr_to_str(tree)
    _pending_selection = {"program_id": _pid(ts), "tree": ts}
    return 0


def flush_gen(gen, problem_type, complexity_ratio, max_gen, n_eval,
              max_cands_per_deme, min_pool_size, complexity_temperature,
              n_to_keep, cap_coef, n_deme, optimizer):
    """Assemble + write state/step-G.json and action/step-G.json, append JSONL,
    then drop the ready/ sentinel (LAST)."""
    global _prev_member_ids, _pending_selection
    g = _num(gen)
    s = _gs(g)
    members = s["members"]

    pens = [m["cscore"]["penalized_score"] for m in members
            if isinstance(m["cscore"]["penalized_score"], (int, float))]
    best = max(pens) if pens else None

    cur_ids = {m["program_id"] for m in members}
    new_ids = sorted(cur_ids - _prev_member_ids)
    culled_ids = sorted(_prev_member_ids - cur_ids)
    id_to_expr = {m["program_id"]: m["expr"] for m in members}

    # consume + VALIDATE buffered selection (must be one of this gen's candidates)
    selected_id = None
    selection_status = "no_selection"
    sel = _pending_selection
    _pending_selection = None
    if sel is not None:
        if sel["program_id"] in cur_ids:
            selected_id = sel["program_id"]; selection_status = "ok"
        else:
            selected_id = "MISMATCH"; selection_status = "mismatch"

    knobs = s["knobs"]
    neighborhood = sum(max(_num(k["multiplicity"]) - 1, 0)
                       for k in knobs if isinstance(k["multiplicity"], (int, float)))

    run_parameters = {
        "problem_type": _flat(problem_type),
        "complexity_ratio": _cr_or_none(complexity_ratio), "max_gen": _num(max_gen),
        "n_eval": _num(n_eval), "max_cands_per_deme": _num(max_cands_per_deme),
        "min_pool_size": _num(min_pool_size),
        "complexity_temperature": _num(complexity_temperature),
        "n_to_keep": _num(n_to_keep), "cap_coef": _num(cap_coef),
        "n_deme": _num(n_deme), "optimizer": _flat(optimizer),
    }

    state_doc = {
        "schema_version": _VERSION, "run_seq": _run_seq, "generation": g,
        "metapopulation": {
            "size": len(members), "best_penalized_score": best, "members": members,
        },
        "current_deme": {
            "deme_id": s["deme_id"], "exemplar_expr": s["deme_tree"],
            "knobs": knobs, "knob_count": len(knobs),
            "neighborhood_size": neighborhood,
            "instances_evaluated": s["deme_instances"],
        },
        "lineage": {
            "new_members": [{"program_id": pid, "expr": id_to_expr.get(pid)} for pid in new_ids],
            "culled_program_ids": culled_ids,
        },
        "run_parameters": run_parameters,
    }

    action_doc = {
        "schema_version": _VERSION, "run_seq": _run_seq, "generation": g,
        "problem_type": _flat(problem_type),
        "exemplar_candidates": [
            {"program_id": m["program_id"], "program_expr": m["expr"],
             "penalized_score": m["cscore"]["penalized_score"],
             "cscore": m["cscore"], "complexity": m["complexity"]}
            for m in members
        ],
        "selected_program_id": selected_id,
        "selection_status": selection_status,
        "selection_detail": (
            None if selection_status in ("ok", "no_selection")
            else {"buffered_id": sel["program_id"], "buffered_tree": sel["tree"],
                  "candidate_ids": sorted(cur_ids)}
        ),
        "complexity_ratio": {"current_value": _cr_or_none(complexity_ratio)},
    }

    _write_json(os.path.join(_cur_state_dir, f"step-{g}.json"), state_doc)
    _write_json(os.path.join(_cur_action_dir, f"step-{g}.json"), action_doc)

    _NFH.write(json.dumps({
        "run_seq": _run_seq, "generation": g, "size": len(members),
        "best_penalized_score": best, "knob_count": len(knobs),
        "ts_ms": int(time.time() * 1000),
    }) + "\n")

    _prev_member_ids = cur_ids

    # MUST be last: ready sentinel (compound name avoids cross-run collision).
    ready = os.path.join(_READY_DIR, f"run-{_run_seq}-step-{g}")
    with open(ready, "w", encoding="utf-8") as fh:
        fh.write(f"{int(time.time()*1000)}\n")
    return 0
