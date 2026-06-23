"""Build structured LLMOSES state/action JSON from MeTTa extractor values.

Values arrive through py-call as native Python numbers, strings, nested lists,
or Cons spines. This module owns the per-run/per-generation accumulator state and
the public py-call entry points; the value-unwrap primitives (boundary.py), the
run-directory bootstrap (runspace.py), and the atom-evidence walker
(atom_evidence.py) live alongside it and are imported here.
"""
import json
import math
import time
import hashlib
import os

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

# --- run-directory bootstrap (paths, native log, run_meta) ------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))      # .../llmoses/utilities
_LLMOSES_DIR = os.path.dirname(_THIS_DIR)                   # .../llmoses

_RS = runspace.bootstrap(_LLMOSES_DIR, _VERSION)
_RUN_ID = _RS.run_id
_RUN_DIR = _RS.run_dir
_STATE_DIR = _RS.state_dir
_ACTION_DIR = _RS.action_dir
_READY_DIR = _RS.ready_dir
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
    """Open a fresh per-run subdir. Call once at the top of each runMoses.

    Demo harnesses may invoke several PeTTa processes with one LLMOSES_RUN_ID.
    Each process imports this module with _run_seq reset to 0, so consult the
    existing output directories before choosing the next run-N slot.
    """
    global _run_seq, _cur_state_dir, _cur_action_dir, _pending_selection, _pending_merge
    global _pending_deme_evals, _depth, _total_evals, _explored_ids, _problem_spec
    global _last_complexity_ratio, _pending_run_params
    global _atom_alphabet, _atom_alphabet_map, _atom_cumulative
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
    emitted as tree_str). tree = raw mkTree, used ONLY to derive the
    collision-resistant program_id — not emitted (bloat, no info gain).
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
    """Accumulate a named merge-pipeline count into _pending_merge["counts"].
    Additive so nDeme>1 recurses correctly through mergeDemes."""
    if _pending_merge is not None:
        k = _flat(name); c = _pending_merge["counts"]
        c[k] = (c.get(k) or 0) + (_num(value) or 0)
    return 0


def add_cull_candidate(expr, tree, bscore, raw, cpx, pen):
    """A merge survivor (mkExemplar from removeDominated) entering the resize cull,
    fed one-per-call from sbEmitCullCands (state-builder.metta:110).
    Boundary shapes: expr = preOrder nested-list AST; tree = full raw mkTree
    (hashed for program_id, same scheme as add_member); bscore = ['mkBScore', spine].
    raw/cpx/pen are scalars pre-extracted by named cscore accessors in MeTTa, so
    there is no field-alignment ambiguity from the raw mkCscore atom."""
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
    Called from inside expandDeme with the FULL raw tree — same value the member
    loop hashes — so the program_id matches a candidate's id.
    Buffered (expandDeme lacks $genIndex); flush_gen consumes + validates it.
    A MISMATCH signals a real defect (stale buffer / multi-or-zero selection /
    non-canonical id)."""
    global _pending_selection
    ts = expr_to_str(tree)
    _pending_selection = {"program_id": _pid(ts), "tree": ts}
    return 0


# Boundary shape — confirmed against the producer.
#   `state` is the hill-climbing optimizer state tuple returned by optimizeDemes
#   and passed in from expandDemeHelper (deme/expand-deme.metta:81-82). Its fields
#   (hill-climbing-helpers.metta:235):
#     0:alreadyXover 1:lastChance 2:_ 3:prevCenter 4:prevStart 5:prevSize
#     6:bestSscore 7:bestScore 8:currentNInstances 9:d 10:i
#   Index 8 (currentNInstances) is the deme's running fitness-eval count, in one
#   of two marshalled forms:
#     * a bare Number                  e.g.  240
#     * an unreduced sum expr (+ a b)  e.g.  ['+', 180, 60]   (running total not
#                                            yet evaluated when the state crossed)
#   For the summed form, '+' is the operator symbol and [1]/[2] its two operands,
#   totaled here into one per-deme count.
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
    action spaces are defined over. From getArgLabels (mkITable ...).
    Called once at run start; persists into every state_doc for that run."""
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
        "active_levers": _ACTIVE_LEVERS.get(ptype, []),
        "comparator_hook_available": True,
    }
    _write_json(os.path.join(_cur_state_dir, "run_config.json"), doc)
    runspace.ensure_context_docs(_LLMOSES_DIR, _RUN_ID, _RUN_DIR, run_seq=_run_seq,
                                 problem_type=ptype, problem_spec=_problem_spec,
                                 active_levers=doc["active_levers"])
    return 0


def set_problem_spec_strategy(moves, n_games, opponent_policy, complexity_ratio):
    """Strategy analog of set_problem_spec. Moves arrive as a marshalled flat list
    of symbols (bare MeTTa tuple, not a Cons spine), from sbSetProblemSpecStrategy
    (state-builder.metta:147)."""
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
    """Final post-merge metapopulation -> terminal.json. Offline/experiment use;
    no ready/ sentinel (not an agent step)."""
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
    }
    _write_json(os.path.join(_cur_state_dir, "terminal.json"), doc)
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

    lineage_diff = {
        "seed_exemplar_id": selected_id,
        "new_programs": sorted(post_ids - cur_ids),
        "culled": sorted(cur_ids - post_ids),
    }

    demes, evals_gen = [], 0
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
        evals_gen += deme_evaluations or 0
        demes.append({
            "deme_id": deme_id, "exemplar_program_id": selected_id,
            "exemplar_expr": deme["deme_tree"],
            "knobs": deme["knobs"], "knob_count": len(deme["knobs"]),
            "knob_type_breakdown": knob_breakdown,
            "neighborhood_size": neighborhood_size,
            "instances_evaluated": deme["instances"],
            "hill_climb_evaluations": deme["evaluations"],
        })
    _total_evals += evals_gen

    pool_ids = cur_ids | {c["program_id"] for c in cull_cands}
    merge_summary = {
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

    seed_depth = _depth.get(selected_id, 0)
    for pid in lineage_diff["new_programs"]:
        _depth.setdefault(pid, seed_depth + 1)
    for m in members:
        _depth.setdefault(m["program_id"], 0)

    cratio = _cr_or_none(_pending_run_params.get("complexity_ratio"))
    if cratio is None:
        for m in members:
            cpx, cpen = m["complexity"], m["cscore"]["complexity_penalty"]
            if isinstance(cpx, (int, float)) and isinstance(cpen, (int, float)) and cpen:
                cratio = cpx / cpen
                break
    _last_complexity_ratio = cratio

    members_out = [_member_out(m) for m in members]

    post_selection_evt = None
    if selection_status != "no_selection":
        rank = None
        if selected_id not in (None, "MISMATCH"):
            rank = next((i for i, m in enumerate(members)
                         if m["program_id"] == selected_id), None)
        post_selection_evt = {
            "event_type": "post_selection", "generation": g, "timestamp_ms": ts,
            "chosen_program_id": selected_id,
            "native_boltzmann_probability": (probs[rank]
                                              if rank is not None and rank < len(probs) else None),
            "selected_position": rank, "llm_utility": None,
            "selection_status": selection_status,
        }

    # Atom evidence is best-effort emission metadata; malformed trees must not
    # interrupt search or generation output. Settled-side only, but stays wrapped.
    try:
        atom_evidence_block, atom_lossless = atom_evidence.build_atom_evidence(
            members, g, ptype, best, _atom_alphabet_map, _atom_cumulative,
            _VERSION, _run_seq)
    except Exception:  # pragma: no cover - defensive only
        atom_evidence_block = {"atom_appearances": [], "realized_cooccurrences": [],
                               "atom_cumulative": {},
                               "degenerate_summary": {"contradiction_dropped": 0,
                                                      "repeats_collapsed": 0}}
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
    }

    action_doc = {
        "schema_version": _VERSION, "run_seq": _run_seq, "generation": g,
        "problem_type": ptype,
        "exemplar_candidates": [
            {"program_id": m["program_id"], "tree_str": m["tree_str"],
             "penalized_score": m["cscore"]["penalized_score"],
             "complexity": m["complexity"],
             "raw_score": m["cscore"]["raw_score"],
             "lineage_depth": _depth.get(m["program_id"])}
            for m in members
        ],
        "culling_candidates": cull_cands if cull_cands else [],
        "complexity_ratio": {
            "current_value": cratio,
            "options": ([cratio] if cratio is not None else []),
        },
    }

    _write_json(os.path.join(_cur_state_dir, f"step-{g}.json"), state_doc)
    _write_json(os.path.join(_cur_action_dir, f"step-{g}.json"), action_doc)
    if atom_lossless is not None:
        _write_json(os.path.join(_cur_state_dir, f"atom_lossless-{g}.json"), atom_lossless)
    _NFH.write(json.dumps({
        "run_seq": _run_seq, "generation": g, "size": len(members),
        "best_penalized_score": best,
        "ts_ms": int(time.time() * 1000),
    }) + "\n")

    if selection_status == "ok":
        _explored_ids.add(selected_id)

    ready = os.path.join(_READY_DIR, f"run-{_run_seq}-step-{g}")
    with open(ready, "w", encoding="utf-8") as fh:
        fh.write(f"{int(time.time()*1000)}\n")
    return 0
