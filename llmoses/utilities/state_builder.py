"""Build structured LLMOSES state/action JSON from MeTTa extractor values.

Values arrive through py-call as native Python numbers, strings, nested lists,
or Cons spines. This module owns the per-run/per-generation accumulator state and
the public py-call entry points; the value-unwrap primitives (boundary.py), the
run-directory bootstrap (runspace.py), and the atom-evidence walker
(atom_evidence.py) live alongside it and are imported here.
"""
import json
import math
import random
import time
import hashlib
import os
import sys

import atom_evidence
import runspace
from boundary import (
    _num, _flat, unwrap_atom, cons_to_list, expr_to_str,
    cr_or_none as _cr_or_none, present_atom as _present_atom,
    demeid as _demeid,
)

_VERSION = "0.5-mvp"

# Per problem_type: which action-space levers are live (agent should not score inactive dims).
_ACTIVE_LEVERS = {
    "boolean": ["exemplar_selection", "culling", "atom_evidence",
                "complexity_ratio", "comparator_hook"],
    "strategy": ["exemplar_selection", "culling", "atom_evidence",
                 "complexity_ratio", "comparator_hook"],
}

# --- Phase II lever switches (two independent planes, env-driven) ------------
# Outbound: which emission sections the agent gets to see (default: all).
# Inbound: which UtilityResponse components are applied to policy (default:
# NONE — pure shadow). Per-lever mixing weight lambda in [0,1]; the unified
# formula everywhere is  w' = w_native * (lam*u_hat + (1-lam)), so lam=0 is
# exactly native and lam=1 with 0/1 utilities is explicit control.
_EMIT_LEVER_NAMES = ("exemplar_selection", "culling", "atom_evidence",
                     "complexity_ratio", "comparator_hook")
_APPLY_LEVER_NAMES = ("exemplar_selection", "culling", "comparator",
                      "complexity_ratio", "atom_prior")


def _csv_env(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return set(default)
    return {tok.strip() for tok in raw.split(",") if tok.strip()}


def _lever_weight_env(name):
    raw = os.environ.get(f"LLMOSES_LEVER_WEIGHT_{name.upper()}")
    try:
        lam = float(raw) if raw is not None else 1.0
    except (TypeError, ValueError):
        lam = 1.0
    return min(max(lam, 0.0), 1.0)


_EMIT_LEVERS = _csv_env("LLMOSES_EMIT_LEVERS", _EMIT_LEVER_NAMES)
_APPLY_LEVERS = _csv_env("LLMOSES_APPLY_LEVERS", ())
_LEVER_WEIGHTS = {n: _lever_weight_env(n) for n in _APPLY_LEVER_NAMES}

# --- run-directory bootstrap (paths, native log, run_meta) ------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))      # .../llmoses/utilities
_LLMOSES_DIR = os.path.dirname(_THIS_DIR)                   # .../llmoses

_RS = runspace.bootstrap(_LLMOSES_DIR, _VERSION)
_RUN_ID = _RS.run_id
_RUN_DIR = _RS.run_dir
_STATE_DIR = _RS.state_dir
_ACTION_DIR = _RS.action_dir
_READY_DIR = _RS.ready_dir
_RESPONSE_DIR = _RS.response_dir
_NFH = _RS.native_log

# --- per-run + per-gen accumulator state -----------------------------------
_run_seq = 0
_cur_state_dir = _STATE_DIR
_cur_action_dir = _ACTION_DIR
_gen = {}                 # gen -> accumulating record
_pending_selection = None  # buffered {id, tree} from set_selection, consumed by flush_gen
_pending_merge = None      # buffered post-merge metapop ids from sbEmitAllMerged, consumed by flush_gen
_pending_deme_evals = {}   # deme_id -> currentNInstances (from expandDemeHelper)
_depth = {}               # program_id -> lineage depth (reset per run)
_total_evals = 0           # cumulative true fitness calls across all gens in the current run
_explored_ids = set()      # program_ids selected in a prior gen (reset per run; "explored" flag)
_problem_spec = None       # {input_labels, arity}; set once per run by set_problem_spec
_last_complexity_ratio = None  # derived cratio from flush_gen; reused by flush_terminal
_pending_run_params = {}   # name -> raw value; persists across gens, reset by new_run
_atom_alphabet = None      # {problem_type, prefix, atoms:[{index,key,label}]}; static, run_config
_atom_alphabet_map = {}    # label -> {index, key}; walker lookup, derived from _atom_alphabet
_atom_cumulative = {}      # key -> {appearances_total, first_seen_gen, last_seen_gen} (run-scoped)
_capture_failures = {}     # kind -> count; reset by new_run. Unifies flush-section
                           # degradations and response_timeouts as one validity signal.
_pending_utilities = None  # parsed UtilityResponse (latest ingested); None = native
_utility_gen = None        # generation whose response filled _pending_utilities
_effective_cratio = None   # complexity-ratio lever accumulator (persists across gens)
_cratio_applied_for = None  # last response gen whose ratio delta was consumed
_comparator_overrides = 0  # comparator-lever override count since last flush_gen
_sel_buf = None            # streamed selection candidates (begin_selection..select_index)
_cull_buf = None           # streamed cull candidates (begin_cull..cull_index)
_combo_buf = None          # streamed sampler combos (begin_combo_draw..weighted pick)

# --- Phase II return leg (blocking watcher handshake) -----------------------
# OFF by default so existing watcher-less smoke tests are byte-for-byte unchanged;
# Phase II runs opt in with LLMOSES_AWAIT_RESPONSE=1 and a live watcher.
_AWAIT_ENABLED = os.environ.get("LLMOSES_AWAIT_RESPONSE", "0") == "1"
_RESP_POLL_S = float(os.environ.get("LLMOSES_RESPONSE_POLL_S", "0.05"))
_RESP_TIMEOUT_S = float(os.environ.get("LLMOSES_RESPONSE_TIMEOUT_S", "30"))

# Boltzmann selection constants; mirror exemplar-selection.metta COMPXY_TEMP / INV_TEMP.
_COMPXY_TEMP = 6.0
_INV_TEMP = 100.0 / _COMPXY_TEMP


# ===========================================================================
# Problem-type resolution (reads run-scoped _problem_spec; uses marshal prims)
# ===========================================================================
def _effective_problem_type(raw_problem_type=None):
    """Resolve the canonical problem-type string from the buffered run param,
    falling back to _problem_spec. Returns None if genuinely unknown."""
    p = _present_atom(raw_problem_type)
    if p is not None:
        return p
    if isinstance(_problem_spec, dict):
        p = _present_atom(_problem_spec.get("problem_type"))
        if p is not None:
            return p
        if "input_labels" in _problem_spec:
            return "boolean"
    return None


def _build_run_parameters(cratio_override=None):
    """Assemble run_parameters dict from buffered _pending_run_params."""
    rp = _pending_run_params
    ptype = _effective_problem_type(rp.get("problem_type"))
    cratio = cratio_override if cratio_override is not None else _cr_or_none(rp.get("complexity_ratio"))
    if cratio is None:
        cratio = _last_complexity_ratio
    hc_max = get_hill_climb_max_evals()
    hill_climb_max_evals = rp.get("hill_climb_max_evaluations")
    if hill_climb_max_evals is not None:
        hc_max = _num(hill_climb_max_evals) or hc_max
    return {
        "problem_type": ptype,
        "complexity_ratio": cratio,
        "n_eval": _num(rp.get("n_eval")),
        "hill_climb_max_evaluations": hc_max,
        "max_cands_per_deme": _num(rp.get("max_cands_per_deme")),
        "min_pool_size": _num(rp.get("min_pool_size")),
        "complexity_temperature": _num(rp.get("complexity_temperature")),
        "n_to_keep": _num(rp.get("n_to_keep")),
        "cap_coef": _num(rp.get("cap_coef")),
        "n_deme": _num(rp.get("n_deme")),
        "optimizer": _flat(rp.get("optimizer")),
    }


def _boltzmann(pen_scores):
    """Reproduce normalizeProbs + the sum in selectExemplar.
    w_i = exp((s_i - best) * INV_TEMP) / sum(w), aligned to input order.
    Returns a parallel list of floats (or None for non-finite inputs)."""
    finite_scores = [score for score in pen_scores
                     if isinstance(score, (int, float)) and not math.isinf(score)]
    if not finite_scores:
        return [None] * len(pen_scores)
    best = max(finite_scores)
    weights = [0.0 if (not isinstance(score, (int, float)) or math.isinf(score))
               else math.exp((score - best) * _INV_TEMP)
               for score in pen_scores]
    total = sum(weights)
    return [0.0] * len(weights) if total <= 0 else [w / total for w in weights]


def _pid(expr_str):
    return "p" + hashlib.sha1(expr_str.encode("utf-8")).hexdigest()[:10]


def _blank(gen):
    return {"generation": gen, "members": [], "demes": {}, "deme_order": []}


def _knob_kind(m):
    """Problem-agnostic: boolean LSK=3, strategy SSK=2, else 'other'
    (continuous coefficient knobs land in 'other' rather than being mislabeled)."""
    return "boolean" if m == 3 else "strategy" if m == 2 else "other"


def _dslot(s, did):
    return s["demes"].setdefault(did, {"knobs": [], "deme_tree": None,
                                       "instances": None, "evaluations": None})


def _gs(gen):
    g = _num(gen)
    if g not in _gen:
        _gen[g] = _blank(g)
    return _gen[g]


def _member_out(m):
    """Emit-shape of a member: drop the internal tree_ast (walker input only),
    tag the explored flag."""
    return {k: v for k, v in m.items() if k != "tree_ast"} | {
        "explored": m["program_id"] in _explored_ids}


def _best_penalized(members):
    """Max finite penalized_score across members, or None when none are numeric."""
    pens = [m["cscore"]["penalized_score"] for m in members
            if isinstance(m["cscore"]["penalized_score"], (int, float))]
    return max(pens) if pens else None


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


def _max_existing_run_seq():
    seqs = []
    for root in (_STATE_DIR, _ACTION_DIR):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            if not name.startswith("run-"):
                continue
            raw = name[4:].split("-", 1)[0]
            try:
                seqs.append(int(raw))
            except ValueError:
                pass
    return max(seqs) if seqs else 0


def new_run():
    """Open a fresh per-run subdir. Call once at the top of each runMoses."""
    global _run_seq, _cur_state_dir, _cur_action_dir, _pending_selection, _pending_merge
    global _pending_deme_evals, _depth, _total_evals, _explored_ids, _problem_spec
    global _last_complexity_ratio, _pending_run_params
    global _atom_alphabet, _atom_alphabet_map, _atom_cumulative, _capture_failures
    global _pending_utilities, _utility_gen, _effective_cratio, _cratio_applied_for
    global _comparator_overrides, _sel_buf, _cull_buf, _combo_buf
    _run_seq = max(_run_seq + 1, _max_existing_run_seq() + 1)
    _cur_state_dir = os.path.join(_STATE_DIR, f"run-{_run_seq}")
    _cur_action_dir = os.path.join(_ACTION_DIR, f"run-{_run_seq}")
    os.makedirs(_cur_state_dir, exist_ok=True)
    os.makedirs(_cur_action_dir, exist_ok=True)
    _pending_selection = None
    _pending_merge = None
    _pending_deme_evals = {}
    _depth = {}
    _total_evals = 0
    _explored_ids = set()
    _problem_spec = None
    _last_complexity_ratio = None
    _pending_run_params = {}
    _atom_alphabet = None
    _atom_alphabet_map = {}
    _atom_cumulative = {}
    _capture_failures = {}
    _pending_utilities = None
    _utility_gen = None
    _effective_cratio = None
    _cratio_applied_for = None
    _comparator_overrides = 0
    _sel_buf = None
    _cull_buf = None
    _combo_buf = None
    runspace.ensure_context_docs(_LLMOSES_DIR, _RUN_ID, _RUN_DIR, run_seq=_run_seq)
    return _run_seq


def begin_gen(gen):
    _gen[_num(gen)] = _blank(_num(gen))
    return 0


# cscore crosses as a flat list from `cscoreFields (memberCscore $x)`
# (state-builder.metta sbEmitMembers). Field order confirmed against cscoreFields
# (extractors.metta:7) -> (getScore getComp getCompPen getUniPen getPenScore):
_CSCORE_FIELDS = ("raw_score", "complexity", "complexity_penalty",
                  "uniformity_penalty", "penalized_score")


def add_member(gen, expr, tree, cscore, bscore):
    """One member. expr = preOrder (lossless clean AST for resolved trees;
    emitted as tree_str). tree = raw mkTree, used to derive the
    collision-resistant program_id (not emitted currently)
    cscore = flat list in _CSCORE_FIELDS order; bscore = ['mkBScore', spine]|spine|Nil."""
    tree_str = expr_to_str(expr)        # preOrder — lossless for resolved members
    raw = expr_to_str(tree)             # full raw tree -> identity only
    # dict(zip) truncates a long list and the pad fills a short one, so this is
    # behavior-identical to the old index-and-pad over cs[0..4].
    cscore_values = [_num(v) for v in (cscore if isinstance(cscore, list) else [cscore])]
    cscore_values += [None] * (len(_CSCORE_FIELDS) - len(cscore_values))
    cscore_fields = dict(zip(_CSCORE_FIELDS, cscore_values))
    bscore_values = [_num(v) for v in cons_to_list(bscore)]
    _gs(gen)["members"].append({
        "program_id": _pid(raw),        # identity off the full tree
        "tree_str": tree_str,           # lossless clean AST (replaces expr + tree)
        "tree_ast": expr,               # nested preOrder list — clause walker input (stripped on emit)
        "cscore": cscore_fields,
        "complexity": cscore_fields["complexity"],
        "bscore": bscore_values if bscore_values else None,
    })
    return 0


_KIND_BY_TAG = {"LSK": "boolean", "SSK": "strategy"}


def add_knob(gen, deme_id, loc, multip, default, tag=None):
    """One call per deme knob, keyed by deme_id for multi-deme support."""
    s = _gs(gen); did = _demeid(deme_id); d = _dslot(s, did)
    # multip crosses wrapped as (mkMultip n) -> ['mkMultip', n]; loc as a native
    # NodeId (knobMultip / knobLoc, extractors.metta). unwrap_atom peels the
    # ['tag', payload] shell; a bare value passes through.
    multiplicity = _num(unwrap_atom(multip))
    location = unwrap_atom(loc)
    kind = _KIND_BY_TAG.get(_flat(tag)) or _knob_kind(multiplicity)   # tag wins; multiplicity is fallback only
    d["knobs"].append({
        "knob_id": location if isinstance(location, (int, float)) else _flat(location),
        "multiplicity": multiplicity, "kind": kind, "default_setting": _num(default),
    })
    return 0


def set_deme(gen, deme_id, deme_tree, instances):
    s = _gs(gen); did = _demeid(deme_id); d = _dslot(s, did)
    if did not in s["deme_order"]: s["deme_order"].append(did)
    d["deme_tree"] = expr_to_str(deme_tree)
    d["instances"] = _num(instances)
    d["evaluations"] = _pending_deme_evals.pop(did, None)
    return 0


def begin_merge():
    """post_deme_close Tier A: open a fresh merge buffer before walking $updatedMetaPop."""
    global _pending_merge
    _pending_merge = {"post_ids": [], "counts": {}, "cull_candidates": []}
    return 0


def add_merged_member(tree):
    """Append one post-merge member's program_id (hashed from its full raw tree).
    Uses the identical _pid(expr_to_str(tree)) scheme as add_member so the ids
    align with the candidate set built during the same generation."""
    if _pending_merge is not None:
        _pending_merge["post_ids"].append(_pid(expr_to_str(tree)))
    return 0


def set_merge_count(name, value):
    """Accumulate a named merge-pipeline count into _pending_merge["counts"]."""
    if _pending_merge is not None:
        k = _flat(name); c = _pending_merge["counts"]
        c[k] = (c.get(k) or 0) + (_num(value) or 0)
    return 0


def add_cull_candidate(expr, tree, bscore, raw, cpx, pen):
    """A merge survivor (mkExemplar from removeDominated) entering the resize cull,
    fed one-per-call from sbEmitCullCands (state-builder.metta:110).
    Boundary shapes: expr = preOrder nested-list AST; tree = full raw mkTree
    (hashed for program_id, same scheme as add_member); bscore = ['mkBScore', spine]."""
    if _pending_merge is None:
        return 0
    _pending_merge["cull_candidates"].append({
        "program_id":      _pid(expr_to_str(tree)),
        "tree_str":        expr_to_str(expr),
        "bscore":          [_num(v) for v in cons_to_list(bscore)],
        "raw_score":       _num(raw),
        "complexity":      _num(cpx),
        "penalized_score": _num(pen),
    })
    return 0


def set_selection(tree):
    """post_selection hook: record the exemplar selectExemplar chose THIS gen.
    Buffered (expandDeme lacks $genIndex); flush_gen consumes + validates it.
    A MISMATCH signals a real defect (stale buffer / multi-or-zero selection /
    non-canonical id)."""
    global _pending_selection
    ts = expr_to_str(tree)
    _pending_selection = {"program_id": _pid(ts), "tree": ts}
    return 0


# Boundary shape 
#   `state` is the hill-climbing optimizer state tuple returned by optimizeDemes
#   and passed in from expandDemeHelper:
#     0:alreadyXover 1:lastChance 2:_ 3:prevCenter 4:prevStart 5:prevSize
#     6:bestSscore 7:bestScore 8:currentNInstances 9:d 10:i
#   Index 8 (currentNInstances) is the deme's running fitness-eval count, in one
#   of two marshalled forms:
#     * a bare Number                  e.g.  240
#     * an unreduced sum expr (+ a b)  e.g.  ['+', 180, 60]   
_EVAL_COUNT_INDEX = 8  # currentNInstances; see note above


def set_deme_evals(deme_id, state):
    """Record one deme's fitness-call count. Keyed by deme_id because the
    expandDemeHelper caller passes no generation index; flush_gen reconciles it."""
    try:
        eval_field = state[_EVAL_COUNT_INDEX]
        is_sum_expr = (isinstance(eval_field, (list, tuple))
                       and len(eval_field) >= 3 and eval_field[0] == "+")
        evaluations = (_num(eval_field[1]) + _num(eval_field[2]) if is_sum_expr
                       else _num(eval_field))
    except Exception:
        evaluations = None
    _pending_deme_evals[_demeid(deme_id)] = evaluations
    return 0


def set_problem_spec(labels, arity=None):
    """Input feature space — the domain the pair-sampling / FS / operator-inclusion
    action spaces are defined over. From getArgLabels (mkITable ...)."""
    global _problem_spec
    # labels crosses as a Cons spine of symbol strings from getArgLabels
    # (sbSetProblemSpec, state-builder.metta:17) -> ['Cons','X1',['Cons','X2','Nil']].
    # Fall back to a bare/native list if it did not arrive as a spine.
    raw_labels = cons_to_list(labels)
    if not raw_labels:
        raw_labels = list(labels) if isinstance(labels, list) else [labels]
    feature_labels = [_flat(label) for label in raw_labels]
    _problem_spec = {
        "problem_type": "boolean",
        "input_labels": feature_labels,
        "arity": (_num(arity) if arity is not None else len(feature_labels)),
    }
    return 0


def get_total_evals():
    """Return cumulative true fitness calls in the current run (reset by new_run)."""
    return _total_evals


_HC_MAX_EVALS_DEFAULT = 10000


def get_hill_climb_max_evals():
    """Per-deme hill-climbing fitness-eval cap for this run (fixed at init).
    Defaults to 10000 (OpenCog Classic default) when not explicitly set."""
    v = _pending_run_params.get("hill_climb_max_evaluations")
    if v is not None:
        n = _num(v)
        if n is not None:
            return int(n)
    return _HC_MAX_EVALS_DEFAULT


def set_run_param(name, value):
    """Buffer one named run parameter. Persists until overwritten or new_run;
    NOT cleared by flush_gen, so flush_terminal sees the same values without re-set."""
    _pending_run_params[_flat(name)] = value
    return 0


def emit_run_config():
    """Write run_config.json preamble (static config) before evolution starts.
    Resolves the static atom_alphabet here (and builds the walker's label map)."""
    global _atom_alphabet, _atom_alphabet_map
    ptype = _effective_problem_type(_pending_run_params.get("problem_type"))
    _atom_alphabet, _atom_alphabet_map = atom_evidence.build_atom_alphabet(_problem_spec, ptype)
    doc = {
        "schema_version": _VERSION,
        "run_seq": _run_seq,
        "record_type": "run_config",
        "timestamp_ms": int(time.time() * 1000),
        "problem_spec": _problem_spec,
        "atom_alphabet": _atom_alphabet,
        "run_parameters": _build_run_parameters(),
        "active_levers": [l for l in _ACTIVE_LEVERS.get(ptype, [])
                          if l in _EMIT_LEVERS],
        "comparator_hook_available": True,
        # Phase II switch state: runs are self-describing about which lever
        # data went out and which utility components were applied back in.
        "lever_switches": {
            "emit": sorted(_EMIT_LEVERS & set(_EMIT_LEVER_NAMES)),
            "apply": sorted(_APPLY_LEVERS & set(_APPLY_LEVER_NAMES)),
            "weights": {n: _LEVER_WEIGHTS[n]
                        for n in sorted(_APPLY_LEVERS & set(_APPLY_LEVER_NAMES))},
        },
    }
    _write_json(os.path.join(_cur_state_dir, "run_config.json"), doc)
    runspace.ensure_context_docs(_LLMOSES_DIR, _RUN_ID, _RUN_DIR, run_seq=_run_seq,
                                 problem_type=ptype, problem_spec=_problem_spec,
                                 active_levers=doc["active_levers"])
    return 0


def set_problem_spec_strategy(moves, n_games, opponent_policy, complexity_ratio):
    """Strategy analog of set_problem_spec. Moves arrive as a marshalled flat list
    of symbols (bare MeTTa tuple, not a Cons spine), from sbSetProblemSpecStrategy"""
    global _problem_spec
    move_list = moves if isinstance(moves, list) else [moves]
    _problem_spec = {
        "problem_type": "strategy",
        "moves": [_flat(move) for move in move_list],
        "n_games": _num(n_games),
        "opponent_policy": _flat(opponent_policy),
        "complexity_ratio": _num(complexity_ratio),
    }
    return 0


def flush_terminal(gen):
    """Final post-merge metapopulation -> terminal.json."""
    g = _num(gen)
    s = _gs(g)
    members = s["members"]
    best = _best_penalized(members)
    members_out = [_member_out(m) for m in members]
    doc = {
        "schema_version": _VERSION, "run_seq": _run_seq, "record_type": "terminal",
        "timestamp_ms": int(time.time() * 1000),
        "total_hill_climb_evaluations": _total_evals,
        "total_evaluations": _total_evals,
        "metapopulation": {"size": len(members_out),
                           "best_penalized_score": best, "members": members_out},
        "problem_spec": _problem_spec,
        "run_parameters": _build_run_parameters(),
        # Run total, per-kind (incl. response_timeout): nonzero == partly-blind run.
        "capture_failures": dict(_capture_failures),
    }
    _write_json(os.path.join(_cur_state_dir, "terminal.json"), doc)
    return 0


def await_response(g):
    """Phase II foothold: block until the watcher signals a response for gen g,
    then hand control back to MOSES. v0 reads nothing into the reduction — the
    response is consumed Python-side and discarded; the run proceeds natively
    regardless of content. Isolates round-trip plumbing from consumption.

    Gated by LLMOSES_AWAIT_RESPONSE (default off) so non-Phase-II runs are
    unaffected. §5.1.7 inverted: the run is now coupled to the responder, BUT a
    broken/absent responder must degrade to native, never deadlock. Block <=
    timeout, then proceed. Always returns 0 — shape-identical to every sb* hook.
    """
    if not _AWAIT_ENABLED:
        return 0
    g = _num(g)
    sentinel = os.path.join(_RESPONSE_DIR, f"run-{_run_seq}-step-{g}")
    deadline = time.monotonic() + _RESP_TIMEOUT_S
    try:
        while not os.path.exists(sentinel):
            if time.monotonic() >= deadline:
                _capture_failures["response_timeout"] = \
                    _capture_failures.get("response_timeout", 0) + 1
                _NFH.write(json.dumps({
                    "run_seq": _run_seq, "generation": g,
                    "event": "response_timeout", "ts_ms": int(time.time() * 1000),
                }) + "\n")
                sys.stderr.write(f"[await_response] timeout run {_run_seq} step {g}; "
                                 "proceeding natively\n")
                return 0
            time.sleep(_RESP_POLL_S)
        # Response present — ingest the UtilityResponse payload into module
        # state (Phase II consumption; supersedes the v0 discard).
        _ingest_utilities(g)
    except Exception as e:                       # never raise into the Prolog goal
        sys.stderr.write(f"[await_response] error run {_run_seq} step {g}: {e}\n")
    return 0


def flush_gen(gen):
    """Flush dynamic per-step state; static config lives in run_config.json."""
    global _pending_selection, _pending_merge, _pending_deme_evals, _depth
    global _total_evals, _explored_ids, _last_complexity_ratio
    g = _num(gen)
    ptype = _effective_problem_type(_pending_run_params.get("problem_type"))
    s = _gs(g)
    members = s["members"]

    best = _best_penalized(members)
    cur_ids = {m["program_id"] for m in members}
    probs = _boltzmann([m["cscore"]["penalized_score"] for m in members])

    selected_id, selection_status = None, "no_selection"
    sel = _pending_selection
    _pending_selection = None
    if sel is not None:
        if sel["program_id"] in cur_ids:
            selected_id, selection_status = sel["program_id"], "ok"
        else:
            selected_id, selection_status = "MISMATCH", "mismatch"

    post_ids, counts, cull_cands = set(), {}, []
    if _pending_merge is not None:
        post_ids   = set(_pending_merge["post_ids"])
        counts     = _pending_merge["counts"]
        cull_cands = _pending_merge.get("cull_candidates", [])
        _pending_merge = None

    ts = int(time.time() * 1000)

    # Flush-layer fail-flags: each section's assembly runs under _section so a
    # malformed section degrades to a placeholder (carrying capture_status:"failed"
    # when it's a dict) instead of taking down the run. Generalizes the long-standing
    # atom_evidence try/except. failed_sections drives the per-gen capture_status
    # summary; _capture_failures is the run-scoped, per-kind validity counter.
    failed_sections = []

    def _section(name, build_fn, placeholder):
        try:
            return build_fn()
        except Exception as e:  # capture failure must never fail the run
            _capture_failures[name] = _capture_failures.get(name, 0) + 1
            failed_sections.append(name)
            sys.stderr.write(f"[flush_gen] section '{name}' failed run {_run_seq} "
                             f"gen {g}: {e}\n")
            if isinstance(placeholder, dict):
                return {**placeholder, "capture_status": "failed"}
            return placeholder

    lineage_diff = _section("lineage_diff", lambda: {
        "seed_exemplar_id": selected_id,
        "new_programs": sorted(post_ids - cur_ids),
        "culled": sorted(cur_ids - post_ids),
    }, {"seed_exemplar_id": selected_id, "new_programs": [], "culled": []})

    def _build_demes():
        demes_l, evals_l = [], 0
        for deme_id in s["deme_order"]:
            deme = s["demes"][deme_id]
            knob_breakdown = {"boolean": 0, "strategy": 0, "other": 0}
            for knob in deme["knobs"]:
                knob_breakdown[knob["kind"]] = knob_breakdown.get(knob["kind"], 0) + 1
            neighborhood_size = sum(max(_num(knob["multiplicity"]) - 1, 0)
                                    for knob in deme["knobs"]
                                    if isinstance(knob["multiplicity"], (int, float)))
            deme_evaluations = (deme["evaluations"] if deme["evaluations"] is not None
                                else (_num(deme["instances"]) or 0))
            evals_l += deme_evaluations or 0
            demes_l.append({
                "deme_id": deme_id, "exemplar_program_id": selected_id,
                "exemplar_expr": deme["deme_tree"],
                "knobs": deme["knobs"], "knob_count": len(deme["knobs"]),
                "knob_type_breakdown": knob_breakdown,
                "neighborhood_size": neighborhood_size,
                "instances_evaluated": deme["instances"],
                "hill_climb_evaluations": deme["evaluations"],
            })
        return demes_l, evals_l
    demes, evals_gen = _section("demes", _build_demes, ([], 0))
    _total_evals += evals_gen

    def _build_merge_summary():
        pool_ids = cur_ids | {c["program_id"] for c in cull_cands}
        return {
            "candidates_produced":     counts.get("candidates_produced"),
            "duplicates_dropped":      counts.get("duplicates_dropped"),
            "dominated_count_removed": counts.get("dominated_removed"),
            "resize_cull": {
                "incumbents":   sorted(cur_ids),
                "new_entrants": cull_cands,
                "survivors":    sorted(post_ids),
                "culled":       sorted(pool_ids - post_ids),
            },
        }
    merge_summary = _section("merge_summary", _build_merge_summary, {})

    seed_depth = _depth.get(selected_id, 0)
    for pid in lineage_diff["new_programs"]:
        _depth.setdefault(pid, seed_depth + 1)
    for m in members:
        _depth.setdefault(m["program_id"], 0)

    def _build_cratio():
        c = _cr_or_none(_pending_run_params.get("complexity_ratio"))
        if c is None:
            for m in members:
                cpx, cpen = m["complexity"], m["cscore"]["complexity_penalty"]
                if isinstance(cpx, (int, float)) and isinstance(cpen, (int, float)) and cpen:
                    c = cpx / cpen
                    break
        return c
    cratio = _section("complexity_ratio", _build_cratio, None)
    _last_complexity_ratio = cratio

    members_out = [_member_out(m) for m in members]

    def _build_post_selection():
        if selection_status == "no_selection":
            return None
        rank = None
        if selected_id not in (None, "MISMATCH"):
            rank = next((i for i, m in enumerate(members)
                         if m["program_id"] == selected_id), None)
        return {
            "event_type": "post_selection", "generation": g, "timestamp_ms": ts,
            "chosen_program_id": selected_id,
            "native_boltzmann_probability": (probs[rank]
                                             if rank is not None and rank < len(probs) else None),
            "selected_position": rank, "llm_utility": None,
            "selection_status": selection_status,
        }
    post_selection_evt = _section("post_selection", _build_post_selection,
                                  {"event_type": "post_selection", "generation": g})

    # Atom evidence is best-effort emission metadata; malformed trees must not
    # interrupt search or generation output. Routed through _section so its
    # failures land in the same per-kind counter as every other section.
    # Emit-gated: with the lever off the walker never runs.
    if "atom_evidence" in _EMIT_LEVERS:
        atom_evidence_block, atom_lossless = _section(
            "atom_evidence",
            lambda: atom_evidence.build_atom_evidence(
                members, g, ptype, best, _atom_alphabet_map, _atom_cumulative,
                _VERSION, _run_seq),
            ({"atom_appearances": [], "realized_cooccurrences": [],
              "atom_cumulative": {},
              "degenerate_summary": {"contradiction_dropped": 0,
                                     "repeats_collapsed": 0}},
             None))
    else:
        atom_evidence_block = {"atom_appearances": [], "realized_cooccurrences": [],
                               "atom_cumulative": {},
                               "degenerate_summary": {"contradiction_dropped": 0,
                                                      "repeats_collapsed": 0},
                               "emit_disabled": True}
        atom_lossless = None

    state_doc = {
        "schema_version": _VERSION, "run_seq": _run_seq, "generation": g,
        "problem_type": ptype,
        "timestamp_ms": ts,
        "hill_climb_evaluations_this_generation": evals_gen,
        "total_hill_climb_evaluations": _total_evals,
        "total_evaluations": _total_evals,
        "metapopulation": {
            "size": len(members_out), "best_penalized_score": best, "members": members_out,
        },
        "demes": demes,
        "merge_summary": merge_summary,
        "lineage_diff": lineage_diff,
        "moses_native_events": {"post_selection": post_selection_evt},
        "atom_evidence": atom_evidence_block,
        # Contract: ready/ now means "written + self-describing completeness".
        # Consumers must read this rather than assume the step is fully captured.
        "capture_status": {"failed_sections": failed_sections,
                           "ok": not failed_sections},
    }

    action_doc = {
        "schema_version": _VERSION, "run_seq": _run_seq, "generation": g,
        "problem_type": ptype,
        # Each action component is emit-gated by LLMOSES_EMIT_LEVERS; a gated
        # section emits its empty shape so consumers see stable keys.
        "exemplar_candidates": ([
            {"program_id": m["program_id"], "tree_str": m["tree_str"],
             "penalized_score": m["cscore"]["penalized_score"],
             "complexity": m["complexity"],
             "raw_score": m["cscore"]["raw_score"],
             "lineage_depth": _depth.get(m["program_id"])}
            for m in members
        ] if "exemplar_selection" in _EMIT_LEVERS else []),
        "culling_candidates": ((cull_cands if cull_cands else [])
                               if "culling" in _EMIT_LEVERS else []),
        "complexity_ratio": ({
            "current_value": cratio,
            "options": ([cratio] if cratio is not None else []),
        } if "complexity_ratio" in _EMIT_LEVERS
            else {"current_value": None, "options": []}),
    }

    _write_json(os.path.join(_cur_state_dir, f"step-{g}.json"), state_doc)
    _write_json(os.path.join(_cur_action_dir, f"step-{g}.json"), action_doc)
    if atom_lossless is not None:
        _write_json(os.path.join(_cur_state_dir, f"atom_lossless-{g}.json"), atom_lossless)
    global _comparator_overrides
    _NFH.write(json.dumps({
        "run_seq": _run_seq, "generation": g, "size": len(members),
        "best_penalized_score": best,
        "capture_failures": len(failed_sections),  # live tail-able blind-spot signal
        "comparator_overrides": _comparator_overrides,  # lever-3 decisions this gen
        "ts_ms": int(time.time() * 1000),
    }) + "\n")
    _comparator_overrides = 0

    if selection_status == "ok":
        _explored_ids.add(selected_id)

    ready = os.path.join(_READY_DIR, f"run-{_run_seq}-step-{g}")
    with open(ready, "w", encoding="utf-8") as fh:
        fh.write(f"{int(time.time()*1000)}\n")
    return 0


# ===========================================================================
# Phase II utility guidance: ingestion + policy application
#
# The watcher's UtilityResponse for generation G is ingested at the end of
# gen G (await_response) and applied to the meta-loop's draws during gen G+1.
# Every application site uses the one mixing formula
#     w' = w_native * (lam * u_hat + (1 - lam)),   u_hat = u ** (1/T)
# so lam=0 reproduces native behavior exactly and lam=1 with 0/1 utilities
# hands the utility explicit control. Every function here is called from a
# Prolog goal and must never raise: errors degrade to native + a log row.
# ===========================================================================
def _log_event(event, **fields):
    """One JSONL audit row in moses_native_log.jsonl; never raises."""
    try:
        row = {"run_seq": _run_seq, "event": event, "ts_ms": int(time.time() * 1000)}
        row.update(fields)
        _NFH.write(json.dumps(row) + "\n")
    except Exception:
        pass


def _clamp01(x):
    try:
        return min(max(float(x), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


def _sharpen(u, temp):
    """sampling_temperature: u ** (1/T). T<=0/None/1 leave u unchanged."""
    u = max(float(u), 0.0)
    if temp and temp > 0 and temp != 1.0:
        try:
            return u ** (1.0 / temp)
        except (OverflowError, ZeroDivisionError):
            return u
    return u


def _mix(native_w, u_hat, lam):
    return native_w * (lam * u_hat + (1.0 - lam))


def _lever_on(name, data_key=None):
    """Lever applies iff switched on, lambda > 0, and a response is buffered
    (pass=true clears the buffer, so it reads as native everywhere)."""
    if _pending_utilities is None or name not in _APPLY_LEVERS:
        return False
    if _LEVER_WEIGHTS.get(name, 0.0) <= 0.0:
        return False
    if data_key is not None and not _pending_utilities.get(data_key):
        return False
    return True


def _roulette(weights):
    """Native rouletteSelect semantics: r*sum, walk subtracting. Returns the
    positional index into weights, or None when the total mass is zero."""
    total = sum(weights)
    if total <= 0:
        return None
    adjusted = total * random.random()
    for i, w in enumerate(weights):
        adjusted -= w
        if adjusted <= 0:
            return i
    return len(weights) - 1


def _ingest_utilities(g):
    """Parse utilities/run-N/step-G.json (written by the watcher BEFORE the
    response sentinel) into normalized per-lever lookups."""
    global _pending_utilities, _utility_gen
    path = os.path.join(_RUN_DIR, "utilities", f"run-{_run_seq}", f"step-{g}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict):
            raise ValueError("UtilityResponse is not a JSON object")
    except Exception as e:
        _log_event("utility_ingest_error", generation=g, error=str(e)[:200])
        return
    if doc.get("pass", True):
        _pending_utilities, _utility_gen = None, g
        _log_event("utility_ingest", generation=g, decline=True)
        return

    exemplar = {}
    for e in doc.get("exemplar_utilities") or []:
        if isinstance(e, dict) and e.get("program_id") is not None:
            exemplar[str(e["program_id"])] = _clamp01(e.get("utility"))
    retention = {}
    retention_default = None
    for e in doc.get("culling_utilities") or []:
        if not isinstance(e, dict) or e.get("program_id") is None:
            continue
        r = e.get("retention_utility", e.get("retain_utility"))
        if r is None and e.get("cull_utility") is not None:
            r = 1.0 - _clamp01(e.get("cull_utility"))
        if r is None:
            continue
        # program_id "*" = default retention for candidates the agent has not
        # seen (programs born after the response) — without it, fresh
        # candidates are structurally exempt from culling guidance.
        if str(e["program_id"]) == "*":
            retention_default = _clamp01(r)
        else:
            retention[str(e["program_id"])] = _clamp01(r)
    atom_prior = {}
    for e in doc.get("atom_utility_prior") or []:
        if isinstance(e, dict) and e.get("atom") is not None:
            atom_prior[str(e["atom"])] = _clamp01(e.get("utility"))
    levers = doc.get("feature_utility_levers") or {}
    aggregate_fn = levers.get("aggregate_fn") if isinstance(levers, dict) else None
    if aggregate_fn not in ("product", "mean", "geometric_mean", "softmax"):
        aggregate_fn = "product"
    comparator_rank = {}
    cb = doc.get("comparator_bias")
    if isinstance(cb, dict):
        for rank, pid in enumerate(cb.get("program_id_ordering") or []):
            comparator_rank.setdefault(str(pid), rank)
    delta = doc.get("complexity_ratio_delta")
    if not (isinstance(delta, dict) and delta.get("direction") in
            ("increase", "decrease", "maintain")):
        delta = None
    temp = doc.get("sampling_temperature")
    try:
        temp = float(temp) if temp is not None and float(temp) > 0 else None
    except (TypeError, ValueError):
        temp = None

    _pending_utilities = {
        "exemplar": exemplar, "retention": retention,
        "retention_default": retention_default, "atom_prior": atom_prior,
        "aggregate_fn": aggregate_fn, "comparator_rank": comparator_rank,
        "complexity_ratio_delta": delta, "sampling_temperature": temp,
    }
    _utility_gen = g
    _log_event("utility_ingest", generation=g, decline=False,
               exemplar=len(exemplar), retention=len(retention),
               atoms=len(atom_prior), comparator=len(comparator_rank),
               ratio_delta=(delta or {}).get("direction"), temperature=temp)


def utility_summary(g):
    """sbLogUtilities probe: prove the buffered estimates are reachable from
    the MeTTa loop. Prints a one-liner; returns the exemplar-utility count."""
    g = _num(g)
    try:
        if _pending_utilities is None:
            print(f"[utility] gen {g}: buffer empty (native)", flush=True)
            return 0
        p = _pending_utilities
        delta = p["complexity_ratio_delta"]
        print(f"[utility] gen {g}: from-step {_utility_gen} "
              f"exemplar={len(p['exemplar'])} retention={len(p['retention'])} "
              f"atoms={len(p['atom_prior'])} comparator={len(p['comparator_rank'])} "
              f"ratio={(delta or {}).get('direction')} "
              f"temp={p['sampling_temperature']}", flush=True)
        return len(p["exemplar"])
    except Exception as e:
        sys.stderr.write(f"[utility_summary] error: {e}\n")
        return 0


# --- Lever 1: exemplar selection ---------------------------------------------
# The exemplar-selection fork streams (index, native Boltzmann numerator, tree)
# per member, then select_index() draws. Lever off => same roulette over the
# same native numerators with the same process-wide RNG the native selector
# used (py-call random.random), so the off path is distribution-identical.
def begin_selection(n):
    global _sel_buf
    _sel_buf = {"n": _num(n), "cands": []}
    return 0


def add_selection_candidate(i, prob, tree):
    try:
        _sel_buf["cands"].append({
            "i": int(_num(i)), "prob": max(_num(prob) or 0.0, 0.0),
            "pid": _pid(expr_to_str(tree)),
        })
    except Exception as e:
        sys.stderr.write(f"[add_selection_candidate] error: {e}\n")
    return 0


def select_index():
    """Biased (or native) roulette over the streamed candidates. Returns the
    metapop index of the chosen exemplar; always a valid int."""
    try:
        cands = (_sel_buf or {}).get("cands") or []
        if not cands:
            return 0
        native = [c["prob"] for c in cands]
        weights, degraded = native, None
        if _lever_on("exemplar_selection", "exemplar"):
            lam = _LEVER_WEIGHTS["exemplar_selection"]
            temp = _pending_utilities["sampling_temperature"]
            util = _pending_utilities["exemplar"]
            # missing program_id => neutral (u_hat=1 keeps the native weight)
            weights = [_mix(n, _sharpen(util[c["pid"]], temp), lam)
                       if c["pid"] in util else n
                       for n, c in zip(native, cands)]
            if sum(weights) <= 0:
                weights, degraded = native, "all_zero_bias"
            idx = _roulette(weights)
            if idx is None:
                idx = 0
            _log_event("bias_applied", lever="exemplar_selection",
                       response_gen=_utility_gen, lam=lam, degraded=degraded,
                       native_probs=[round(w, 6) for w in native],
                       biased_probs=[round(w, 6) for w in weights],
                       chosen_index=cands[idx]["i"], chosen_pid=cands[idx]["pid"])
            return cands[idx]["i"]
        idx = _roulette(weights)
        return cands[idx]["i"] if idx is not None else 0
    except Exception as e:
        sys.stderr.write(f"[select_index] error: {e}\n")
        return 0


# --- Lever 2a: resize culling -------------------------------------------------
# The metapopulation fork streams the removable tail [offset-1, popSize-1]
# (exactly the native randint(offset, popSize)-1 range), then cull_index()
# picks one to remove. Native weight is uniform 1; cull weight uses
# u = 1 - retention, and members WITHOUT a retention entry stay native.
def begin_cull(offset, pop_size):
    global _cull_buf
    _cull_buf = {"offset": _num(offset), "pop_size": _num(pop_size), "cands": []}
    return 0


def add_cull_member(i, tree):
    try:
        _cull_buf["cands"].append({"i": int(_num(i)),
                                   "pid": _pid(expr_to_str(tree))})
    except Exception as e:
        sys.stderr.write(f"[add_cull_member] error: {e}\n")
    return 0


def _retention_of(pid):
    """Retention for pid, honoring the '*' wildcard default; None = no guidance."""
    ret = _pending_utilities["retention"]
    return ret.get(pid, _pending_utilities.get("retention_default"))


def _culling_lever_on():
    """The culling lever has data when any explicit retention entry OR the '*'
    wildcard default is present."""
    return (_lever_on("culling") and
            (_pending_utilities.get("retention") or
             _pending_utilities.get("retention_default") is not None))


def cull_index():
    try:
        cands = (_cull_buf or {}).get("cands") or []
        if not cands:  # degenerate; mirror native lower bound
            return max(int((_cull_buf or {}).get("offset", 1)) - 1, 0)
        if _culling_lever_on():
            lam = _LEVER_WEIGHTS["culling"]
            temp = _pending_utilities["sampling_temperature"]
            weights = [_mix(1.0, _sharpen(1.0 - r, temp), lam)
                       if (r := _retention_of(c["pid"])) is not None else 1.0
                       for c in cands]
            degraded = None
            if sum(weights) <= 0:
                weights, degraded = [1.0] * len(cands), "all_zero_bias"
            idx = _roulette(weights)
            if idx is None:
                idx = 0
            _log_event("bias_applied", lever="culling",
                       response_gen=_utility_gen, lam=lam, degraded=degraded,
                       removable=[c["pid"] for c in cands],
                       weights=[round(w, 6) for w in weights],
                       culled_index=cands[idx]["i"], culled_pid=cands[idx]["pid"])
            return cands[idx]["i"]
        return cands[random.randint(0, len(cands) - 1)]["i"]
    except Exception as e:
        sys.stderr.write(f"[cull_index] error: {e}\n")
        return max(int((_cull_buf or {}).get("offset", 1)) - 1, 0)


# --- Lever 2b: dominated-candidate escape --------------------------------------
def dominated_escape(tree):
    """Bernoulli gate on removeDominated: p(keep) = lam * u_hat(retention).
    Returns 1 to KEEP the dominated candidate, 0 for the native removal."""
    try:
        if not _culling_lever_on():
            return 0
        pid = _pid(expr_to_str(tree))
        r = _retention_of(pid)
        if r is None:
            return 0
        lam = _LEVER_WEIGHTS["culling"]
        temp = _pending_utilities["sampling_temperature"]
        p_keep = _clamp01(lam * _sharpen(r, temp))
        keep = random.random() < p_keep
        if keep:
            _log_event("bias_applied", lever="dominated_escape",
                       response_gen=_utility_gen, pid=pid,
                       p_keep=round(p_keep, 4))
        return 1 if keep else 0
    except Exception as e:
        sys.stderr.write(f"[dominated_escape] error: {e}\n")
        return 0


# --- Lever 3: comparator ordering ----------------------------------------------
def comparator_resort_active():
    """1 when the comparator lever should re-sort the current metapopulation.
    Merge inserts always involve a candidate born AFTER the response (its id
    cannot appear in program_id_ordering), so the ordering is applied by
    re-sorting the KNOWN population at the top of each generation instead."""
    try:
        return 1 if _lever_on("comparator", "comparator_rank") else 0
    except Exception:
        return 0


def compare_exemplars(tree1, tree2):
    """comparator lever: -1/0/1 when the response's program_id_ordering covers
    BOTH exemplars (lower rank = better = Greater); 2 = 'use the native
    comparison' (lever off, missing ids, or any error). The native comparison
    itself stays MeTTa-side in the fork, so the off path is exactly native."""
    global _comparator_overrides
    try:
        if not _lever_on("comparator", "comparator_rank"):
            return 2
        rank = _pending_utilities["comparator_rank"]
        pid1, pid2 = _pid(expr_to_str(tree1)), _pid(expr_to_str(tree2))
        if pid1 not in rank or pid2 not in rank:
            return 2
        _comparator_overrides += 1
        if rank[pid1] == rank[pid2]:
            return 0
        return 1 if rank[pid1] < rank[pid2] else -1
    except Exception as e:
        sys.stderr.write(f"[compare_exemplars] error: {e}\n")
        return 2


# --- Lever 5: atom-prior weighted combination sampling ---------------------------
def _aggregate_prior(u_hats, fn):
    """Width-generic combo weight from per-atom sharpened priors."""
    if not u_hats:
        return 1.0
    if fn == "mean":
        return sum(u_hats) / len(u_hats)
    if fn == "geometric_mean":
        prod = 1.0
        for u in u_hats:
            prod *= u
        return prod ** (1.0 / len(u_hats)) if prod > 0 else 0.0
    if fn == "softmax":  # exp-weighted mean of the atom priors
        exps = [math.exp(min(u, 50.0)) for u in u_hats]
        return sum(u * e for u, e in zip(u_hats, exps)) / sum(exps)
    prod = 1.0           # default: product — a combo is only as strong as its
    for u in u_hats:     # weakest atom
        prod *= u
    return prod


def begin_combo_draw(combos, labels):
    """Gate + setup for one sampler node draw. combos = enumerated index
    combinations (pairs/triplets) into labels. Returns 1 when the atom_prior
    lever applies (the fork then draws through weighted_combo_pick); 0 keeps
    the native lazyRandomSelector untouched."""
    global _combo_buf
    try:
        if not _lever_on("atom_prior", "atom_prior"):
            _combo_buf = None
            return 0
        label_list = [_flat(l) for l in (labels if isinstance(labels, list) else [labels])]
        combo_list = []
        for c in (combos if isinstance(combos, list) else []):
            idxs = [int(_num(v)) for v in (c if isinstance(c, list) else [c])]
            combo_list.append(idxs)
        prior = _pending_utilities["atom_prior"]
        temp = _pending_utilities["sampling_temperature"]
        fn = _pending_utilities["aggregate_fn"]
        lam = _LEVER_WEIGHTS["atom_prior"]
        weights, names = [], []
        for idxs in combo_list:
            atoms = [label_list[i] if 0 <= i < len(label_list) else None for i in idxs]
            # missing atom in the prior => neutral factor 1.0
            u_hats = [_sharpen(prior[a], temp) if a in prior else 1.0 for a in atoms]
            weights.append(_mix(1.0, _aggregate_prior(u_hats, fn), lam))
            names.append(atoms)
        _combo_buf = {"weights": weights, "names": names}
        _log_event("bias_applied", lever="atom_prior", response_gen=_utility_gen,
                   lam=lam, aggregate_fn=fn, n_combos=len(weights),
                   nonzero=sum(1 for w in weights if w > 0))
        return 1
    except Exception as e:
        sys.stderr.write(f"[begin_combo_draw] error: {e}\n")
        _combo_buf = None
        return 0


def weighted_combo_pick(lower, upper, picked):
    """One without-replacement weighted draw over combo indices [lower, upper]
    excluding picked. All-zero remaining mass degrades to uniform (logged)."""
    try:
        lo, hi = int(_num(lower)), int(_num(upper))
        taken = {int(_num(p)) for p in (picked if isinstance(picked, list) else
                                        ([picked] if picked is not None else []))}
        remaining = [i for i in range(lo, hi + 1) if i not in taken]
        if not remaining:
            return lo
        buf = _combo_buf or {}
        weights = [(buf.get("weights") or [])[i]
                   if i < len(buf.get("weights") or []) else 1.0
                   for i in remaining]
        pos = _roulette(weights)
        if pos is None:  # zero mass left: deliberate diversity cut exhausted
            pos = random.randint(0, len(remaining) - 1)
            _log_event("bias_degraded", lever="atom_prior",
                       reason="zero_mass_pool", remaining=len(remaining))
            _log_event("combo_pick", lever="atom_prior", degraded=True,
                       index=remaining[pos],
                       atoms=(buf.get("names") or [[]])[remaining[pos]]
                       if remaining[pos] < len(buf.get("names") or []) else None)
            return remaining[pos]
        _log_event("combo_pick", lever="atom_prior", degraded=False,
                   index=remaining[pos],
                   atoms=(buf.get("names") or [[]])[remaining[pos]]
                   if remaining[pos] < len(buf.get("names") or []) else None)
        return remaining[pos]
    except Exception as e:
        sys.stderr.write(f"[weighted_combo_pick] error: {e}\n")
        return int(_num(lower)) if lower is not None else 0


# --- Lever 4: complexity ratio ---------------------------------------------------
def current_complexity_ratio(g):
    """Called once per generation from runMosesLoop. Returns 0 when the context
    should stay as-is; otherwise the new effective ratio (the loop rebuilds the
    scoring context with it, and the rebuilt context persists via recursion).
    Each response's delta is consumed exactly once."""
    global _effective_cratio, _cratio_applied_for
    try:
        if not _lever_on("complexity_ratio", "complexity_ratio_delta"):
            return 0
        if _utility_gen is None or _cratio_applied_for == _utility_gen:
            return 0
        delta = _pending_utilities["complexity_ratio_delta"]
        _cratio_applied_for = _utility_gen          # consume even on maintain
        direction = delta.get("direction")
        mag = _num(delta.get("magnitude")) or 0.0
        if direction == "maintain" or mag <= 0:
            return 0
        base = _effective_cratio
        if base is None:
            base = _cr_or_none(_pending_run_params.get("complexity_ratio"))
        if base is None:
            base = _last_complexity_ratio
        if base is None:
            _log_event("bias_degraded", lever="complexity_ratio",
                       reason="no_base_ratio", generation=_num(g))
            return 0
        lam = _LEVER_WEIGHTS["complexity_ratio"]
        new = base + lam * mag * (1.0 if direction == "increase" else -1.0)
        new = max(new, 0.01)                        # ratio<=0 disables penalties
        _effective_cratio = new
        _log_event("bias_applied", lever="complexity_ratio", generation=_num(g),
                   response_gen=_utility_gen, lam=lam, direction=direction,
                   magnitude=mag, old=round(base, 6), new=round(new, 6))
        return float(new)
    except Exception as e:
        sys.stderr.write(f"[current_complexity_ratio] error: {e}\n")
        return 0
