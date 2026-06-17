"""LLMOSES state builder — list-marshalling accumulator (v0.4).

Receives extractor outputs across py-call. MeTTaLog hands Python native values
recursively —
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
import math
import os
import json
import time
import hashlib

_VERSION = "0.5-mvp"

# Per problem_type: which action-space levers are live (agent should not score inactive dims).
_ACTIVE_LEVERS = {
    "boolean": ["exemplar_selection", "culling", "pair_sampling",
                "complexity_ratio", "comparator_hook"],
    "strategy": ["exemplar_selection", "culling", "pair_sampling",
                 "complexity_ratio", "comparator_hook"],
}

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
_pending_selection = None  # buffered {id, tree} from set_selection, consumed by flush_gen
_pending_merge = None      # buffered post-merge metapop ids from sbEmitAllMerged, consumed by flush_gen
_pending_deme_evals = {}   # deme_id -> currentNInstances (from expandDemeHelper)
_depth = {}               # program_id -> lineage depth (reset per run)
_total_evals = 0           # cumulative true fitness calls across all gens in the current run
_explored_ids = set()      # program_ids selected in a prior gen (reset per run; "explored" flag)
_problem_spec = None       # {input_labels, arity} — set once per run by set_problem_spec
_last_complexity_ratio = None  # derived cratio from flush_gen; reused by flush_terminal
_pending_run_params = {}   # name -> raw value; persists across gens, reset by new_run
_score_complexity_history = []  # per-gen trajectory for score_vs_complexity_trend
_atom_alphabet = None      # {problem_type, prefix, atoms:[{index,key,label}]} — static, run_config
_atom_alphabet_map = {}    # label -> {index, key} — walker lookup, derived from _atom_alphabet
_atom_cumulative = {}      # key -> {appearances_total, first_seen_gen, last_seen_gen} (run-scoped)

# Boltzmann selection constants — mirror exemplar-selection.metta COMPXY_TEMP / INV_TEMP
_COMPXY_TEMP = 6.0
_INV_TEMP = 100.0 / _COMPXY_TEMP


# ===========================================================================
# Marshalling unwrap helpers — matched to the marshalled shapes above.
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


def _demeid(x):
    """mkDemeId payload: dotted pair ($nExpansion . $idx) -> 'exp.idx'; bare
    numeric string (nDeme<=1) passes through; anything else -> _flat."""
    p = unwrap_atom(x)
    if isinstance(p, list) and len(p) == 3 and str(p[1]).strip() == ".":
        return f"{_flat(p[0])}.{_flat(p[2])}"
    return _flat(p)


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


_ABSENT_ATOMS = {"", "None", "()", "Nil"}

def _present_atom(x):
    s = _flat(x)
    return None if s in _ABSENT_ATOMS else s

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


def _pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys)
             if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    n = len(pairs)
    if n < 2:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    num = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    dx = sum((p[0] - mx) ** 2 for p in pairs)
    dy = sum((p[1] - my) ** 2 for p in pairs)
    if dx <= 0 or dy <= 0:
        return None
    return num / (dx * dy) ** 0.5


def _trend_label(delta_score, delta_complexity):
    if delta_score is None or delta_complexity is None:
        return None
    if abs(delta_score) < 1e-9 and abs(delta_complexity) < 1e-9:
        return "stable"
    if delta_score > 0 and delta_complexity > 0:
        return "score_up_complexity_up"
    if delta_score > 0 and delta_complexity < 0:
        return "score_up_complexity_down"
    if delta_score < 0 and delta_complexity > 0:
        return "score_down_complexity_up"
    if delta_score < 0 and delta_complexity < 0:
        return "score_down_complexity_down"
    if delta_score > 0:
        return "score_up_complexity_flat"
    if delta_score < 0:
        return "score_down_complexity_flat"
    return "complexity_shift"


def _compute_score_vs_complexity_trend(members, g):
    pens, cpxs = [], []
    for m in members:
        ps = m["cscore"]["penalized_score"]
        cx = m["complexity"]
        if isinstance(ps, (int, float)) and isinstance(cx, (int, float)):
            pens.append(ps)
            cpxs.append(cx)
    corr = _pearson(cpxs, pens)
    best = max(pens) if pens else None
    mean_cpx = (sum(cpxs) / len(cpxs)) if cpxs else None
    _score_complexity_history.append({
        "generation": g, "best_penalized_score": best,
        "mean_complexity": mean_cpx, "correlation": corr,
    })
    out = {"correlation_this_generation": corr}
    if len(_score_complexity_history) >= 2:
        prev = _score_complexity_history[-2]
        ds = ((best or 0) - (prev["best_penalized_score"] or 0)
              if best is not None and prev["best_penalized_score"] is not None else None)
        dc = ((mean_cpx or 0) - (prev["mean_complexity"] or 0)
              if mean_cpx is not None and prev["mean_complexity"] is not None else None)
        out["gen_over_gen"] = {
            "delta_best_penalized_score": ds,
            "delta_mean_complexity": dc,
            "label": _trend_label(ds, dc),
        }
    return out


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
    finite = [s for s in pen_scores if isinstance(s, (int, float)) and not math.isinf(s)]
    if not finite:
        return [None] * len(pen_scores)
    best = max(finite)
    w = [0.0 if (not isinstance(s, (int, float)) or math.isinf(s))
         else math.exp((s - best) * _INV_TEMP)
         for s in pen_scores]
    tot = sum(w)
    return [0.0] * len(w) if tot <= 0 else [x / tot for x in w]


def _pid(expr_str):
    return "p" + hashlib.sha1(expr_str.encode("utf-8")).hexdigest()[:10]


def _blank(gen):
    return {"generation": gen, "members": [], "demes": {}, "deme_order": []}


def _knob_kind(m):
    """Problem-agnostic: boolean LSK=3, strategy SSK=2, else 'other'
    (continuous coefficient knobs land in 'other' rather than being mislabeled)."""
    return "logical" if m == 3 else "strategy" if m == 2 else "other"


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


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp, path)


# ===========================================================================
# Atom evidence: clause-walking over the resolved post-merge candidate trees.
# This keeps sampling evidence out of the MeTTa knob-building hot path.
# ===========================================================================

# One problem_type-keyed config drives THREE coupled choices so they can't
# desync: the clause-op set, the ordered flag (which governs both dedupe rule
# and key canonicalization), and whether contradictions are meaningful.
#   boolean  : AND/OR commutative -> set-dedupe, sorted keys, contradictions real
#   strategy : PRIORITIZED-OR ordered -> order-preserving dedupe, preserved keys,
#              no contradiction concept (no negation in the move algebra)
_PROBLEM_CONFIG = {
    "boolean":  {"ops": {"AND", "OR"},        "ordered": False, "contradiction": True},
    "strategy": {"ops": {"PRIORITIZED-OR"},   "ordered": True,  "contradiction": False},
}
_DEFAULT_CONFIG = {"ops": {"AND", "OR"}, "ordered": False, "contradiction": True}

# Lossless debug: when LLMOSES_ATOM_LOSSLESS is truthy, also write the raw
# per-event appearance/cooccurrence lists to a SEPARATE side-file per gen
# (atom_lossless-<g>.json), so aggregated-vs-raw can be diffed during validation
# without bloating the main state doc. Default off.
_ATOM_LOSSLESS = os.environ.get("LLMOSES_ATOM_LOSSLESS", "").strip().lower() in (
    "1", "true", "yes", "on")


def _build_atom_alphabet():
    """Resolve the static action-space alphabet from _problem_spec.
    Strategy -> moves (prefix 'move'); boolean/default -> input_labels (prefix
    'feature'). Returns the indexed, label-keyed block emitted in run_config and
    also (re)builds _atom_alphabet_map (label -> {index, key}) for the walker."""
    global _atom_alphabet_map
    _atom_alphabet_map = {}
    if not isinstance(_problem_spec, dict):
        return None
    ptype = _problem_spec.get("problem_type")
    if ptype == "strategy":
        labels = _problem_spec.get("moves") or []
        prefix = "move"
    else:
        labels = _problem_spec.get("input_labels") or []
        prefix = "feature"
    atoms = []
    for i, lbl in enumerate(labels):
        label = _flat(lbl)
        key = f"{prefix}:{label}"
        atoms.append({"index": i, "key": key, "label": label})
        _atom_alphabet_map[label] = {"index": i, "key": key}
    return {"problem_type": ptype, "prefix": prefix, "atoms": atoms}


# --- node classifiers over the marshalled preOrder AST ---------------------
def _is_clause_op(node, ops):
    """node is a non-empty list whose head is a clause-op symbol in `ops`."""
    return isinstance(node, list) and len(node) >= 1 and node[0] in ops


def _is_not_wrapper(node):
    """Unary NOT wrapper: ['NOT', <child>]."""
    return isinstance(node, list) and len(node) == 2 and node[0] == "NOT"


def _is_alphabet_atom(x, alpha_map):
    """Scalar string present in the resolved alphabet."""
    return isinstance(x, str) and x in alpha_map


def _peel_modifier(node):
    """Peel a unary NOT for polarity. ['NOT', c] -> ('-', c) ; else ('+', node)."""
    if _is_not_wrapper(node):
        return "-", node[1]
    return "+", node


def _depth_bucket(d):
    """Collapse exact clause depth into bounded bands (the agent levers on bands,
    and raw depth shatters the keyspace). 0 -> shallow, 1-2 -> mid, 3+ -> deep."""
    if d <= 0:
        return "shallow"
    if d <= 2:
        return "mid"
    return "deep"


def _canonical_members(members, ordered):
    """Order a clause's distinct members for keying. Unordered (boolean) -> sort
    by (atom_index, polarity); ordered (strategy) -> preserve source order."""
    if ordered:
        return list(members)
    return sorted(members, key=lambda m: (m["atom_index"], m["polarity"]))


def _coocc_key(members):
    """Join key from already-ordered members: '+X1&-X2' (label-based)."""
    return "&".join(f"{m['polarity']}{m['atom_label']}" for m in members)


def _score_summary(scores, gen_best, eps=1e-9):
    """Summarize a bucket's host-program penalized scores. n_best_tier counts
    distinct hosts sitting at the generation's best_penalized_score (the "is this
    in the current optima" signal)."""
    vals = [s for s in scores if isinstance(s, (int, float))]
    if not vals:
        return {"mean_penalized": None, "best_penalized": None, "n_best_tier": 0}
    n_best = (sum(1 for s in vals if abs(s - gen_best) <= eps)
              if isinstance(gen_best, (int, float)) else 0)
    return {"mean_penalized": round(sum(vals) / len(vals), 6),
            "best_penalized": max(vals), "n_best_tier": n_best}


def _normalize_clause(raw_members, cfg, degen):
    """Per-clause normalization (runs after raw member collection, before any
    counting). Returns (distinct_members, degenerate_bool).
      - dedupe identical (atom, polarity), tallying repeats_collapsed;
      - boolean only: flag contradiction (an atom present with both polarities),
        tally contradiction_dropped, mark the clause degenerate.
    Order-preserving for both (boolean re-canonicalizes at key time anyway)."""
    distinct, seen = [], set()
    for m in raw_members:
        sig = (m["atom_index"], m["polarity"])
        if sig in seen:
            continue
        seen.add(sig)
        distinct.append(m)
    degen["repeats_collapsed"] += len(raw_members) - len(distinct)
    degenerate = False
    if cfg["contradiction"]:
        pols = {}
        for m in distinct:
            pols.setdefault(m["atom_index"], set()).add(m["polarity"])
        if any(len(v) > 1 for v in pols.values()):
            degenerate = True
            degen["contradiction_dropped"] += 1
    return distinct, degenerate


def _walk_member(tree_ast, cfg, alpha_map, pid, pen, acc):
    """Walk one candidate AST, feeding the appearance/cooccurrence/degenerate
    accumulators directly (no intermediate per-event lists, except the optional
    lossless raw lists). See _build_atom_evidence for accumulator shapes."""
    ops, ordered = cfg["ops"], cfg["ordered"]
    app, co, degen = acc["app"], acc["co"], acc["degen"]

    def visit_clause(node, depth, node_ref):
        op = node[0]
        raw_members, has_nested = [], False
        for ci, child in enumerate(node[1:]):
            child_ref = f"{node_ref}.{ci}"
            polarity, peeled = _peel_modifier(child)
            if _is_clause_op(peeled, ops):
                has_nested = True
                visit_clause(peeled, depth + 1, child_ref)
            elif _is_alphabet_atom(peeled, alpha_map):
                info = alpha_map[peeled]
                raw_members.append({"atom_index": info["index"], "atom_label": peeled,
                                    "atom_key": info["key"], "polarity": polarity,
                                    "node_ref": child_ref})
        bucket = _depth_bucket(depth)

        # Lossless raw events: pre-normalization, mirrors the un-aggregated walk.
        if _ATOM_LOSSLESS:
            for m in raw_members:
                acc["raw_app"].append({
                    "atom_index": m["atom_index"], "atom_label": m["atom_label"],
                    "polarity": m["polarity"], "score_ref": pid,
                    "clause_type": op, "parent_operator": op,
                    "depth": depth, "node_ref": m["node_ref"],
                    "clause_adjacent": has_nested})
            if len(raw_members) >= 2:
                ordered_raw = _canonical_members(raw_members, ordered)
                acc["raw_co"].append({
                    "members": [{"atom": m["atom_key"], "polarity": m["polarity"]}
                                for m in ordered_raw],
                    "key": _coocc_key(ordered_raw), "score_ref": pid,
                    "clause_type": op, "parent_operator": op,
                    "depth": depth, "node_ref": node_ref,
                    "clause_adjacent": has_nested})

        distinct, degenerate = _normalize_clause(raw_members, cfg, degen)

        # Appearances: deduped distinct members stay honest even in a degenerate
        # clause (each atom genuinely appeared). Aggregate into bucket records.
        for m in distinct:
            ak = (m["atom_key"], m["polarity"], op, op, bucket)
            b = app.get(ak)
            if b is None:
                b = app[ak] = {"atom": m["atom_key"], "polarity": m["polarity"],
                               "clause_type": op, "parent_operator": op,
                               "depth_bucket": bucket, "count": 0,
                               "programs": {}, "clause_adjacent": 0}
            b["count"] += 1
            b["programs"][pid] = pen
            if has_nested:
                b["clause_adjacent"] += 1

        # Cooccurrences: only non-degenerate clauses with >=2 distinct members.
        if not degenerate and len(distinct) >= 2:
            ordered_m = _canonical_members(distinct, ordered)
            canon = _coocc_key(ordered_m)
            ck = (canon, op)
            c = co.get(ck)
            if c is None:
                c = co[ck] = {
                    "key": canon,
                    "members": [{"atom": m["atom_key"], "polarity": m["polarity"]}
                                for m in ordered_m],
                    "width": len(ordered_m), "ordered": ordered, "clause_type": op,
                    "count": 0, "programs": {}, "depth_buckets": {}}
            c["count"] += 1
            c["programs"][pid] = pen
            c["depth_buckets"][bucket] = c["depth_buckets"].get(bucket, 0) + 1

    if _is_clause_op(tree_ast, ops):
        visit_clause(tree_ast, 0, "0")


def _build_atom_evidence(members, g, ptype, gen_best):
    """Drive the normalize -> aggregate pass over the retained metapop members
    for generation g, update the run-scoped cumulative accumulator, and finalize
    rollup records. Returns (atom_evidence_block, lossless_block_or_None)."""
    cfg = _PROBLEM_CONFIG.get(ptype, _DEFAULT_CONFIG)
    alpha_map = _atom_alphabet_map
    acc = {"app": {}, "co": {},
           "degen": {"contradiction_dropped": 0, "repeats_collapsed": 0},
           "raw_app": [], "raw_co": []}
    for m in members:
        ast = m.get("tree_ast")
        if ast is None:
            continue
        pen = m.get("cscore", {}).get("penalized_score")
        _walk_member(ast, cfg, alpha_map, m["program_id"], pen, acc)

    # Finalize appearance buckets (drop per-program score duplication: emit
    # n_programs cardinality + a score summary, never one record per host).
    appearances = []
    for b in acc["app"].values():
        progs = b["programs"]
        appearances.append({
            "atom": b["atom"], "polarity": b["polarity"],
            "clause_type": b["clause_type"], "parent_operator": b["parent_operator"],
            "depth_bucket": b["depth_bucket"],
            "count": b["count"], "n_programs": len(progs),
            "clause_adjacent": b["clause_adjacent"],
            "score": _score_summary(list(progs.values()), gen_best),
        })
    appearances.sort(key=lambda r: (r["atom"], r["polarity"], r["clause_type"],
                                    r["depth_bucket"]))

    cooccurrences = []
    for c in acc["co"].values():
        progs = c["programs"]
        cooccurrences.append({
            "key": c["key"], "members": c["members"], "width": c["width"],
            "ordered": c["ordered"], "clause_type": c["clause_type"],
            "count": c["count"], "n_programs": len(progs),
            "depth_buckets": c["depth_buckets"],
            "score": _score_summary(list(progs.values()), gen_best),
        })
    cooccurrences.sort(key=lambda r: (r["key"], r["clause_type"]))

    # Cumulative accumulator: per-alphabet-key totals across generations, fed
    # from the (post-dedupe) aggregated appearance counts.
    counts_this_gen = {}
    for b in acc["app"].values():
        counts_this_gen[b["atom"]] = counts_this_gen.get(b["atom"], 0) + b["count"]
    for key, cnt in counts_this_gen.items():
        rec = _atom_cumulative.get(key)
        if rec is None:
            _atom_cumulative[key] = {"appearances_total": cnt,
                                     "first_seen_gen": g, "last_seen_gen": g}
        else:
            rec["appearances_total"] += cnt
            rec["last_seen_gen"] = g

    evidence = {
        "atom_appearances": appearances,
        "realized_cooccurrences": cooccurrences,
        "atom_cumulative": {k: dict(v) for k, v in _atom_cumulative.items()},
        "degenerate_summary": acc["degen"],
    }
    lossless = None
    if _ATOM_LOSSLESS:
        lossless = {"schema_version": _VERSION, "run_seq": _run_seq, "generation": g,
                    "atom_appearances": acc["raw_app"],
                    "realized_cooccurrences": acc["raw_co"]}
    return evidence, lossless


# ===========================================================================
# Public API — MeTTa entry points (all receive list-marshalled values)
# ===========================================================================
def sb_run_dir():
    return _RUN_DIR


def new_run():
    """Open a fresh per-run subdir. Call once at the top of each runMoses."""
    global _run_seq, _cur_state_dir, _cur_action_dir, _pending_selection, _pending_merge
    global _pending_deme_evals, _depth, _total_evals, _explored_ids, _problem_spec
    global _last_complexity_ratio, _pending_run_params, _score_complexity_history
    global _atom_alphabet, _atom_alphabet_map, _atom_cumulative
    _run_seq += 1
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
    _score_complexity_history = []
    _atom_alphabet = None
    _atom_alphabet_map = {}
    _atom_cumulative = {}
    return _run_seq


def begin_gen(gen):
    _gen[_num(gen)] = _blank(_num(gen))
    return 0


def add_member(gen, expr, tree, cscore, bscore):
    """One member. expr = preOrder (lossless clean AST for resolved trees;
    emitted as tree_str). tree = raw mkTree, used ONLY to derive the
    collision-resistant program_id — not emitted (bloat, no info gain).
    cscore = flat [raw, cpxy, cpen, upen, pen]. bscore = ['mkBScore', spine]|spine|Nil."""
    tree_str = expr_to_str(expr)        # preOrder — lossless for resolved members
    raw = expr_to_str(tree)             # full raw tree -> identity only
    cs = [_num(v) for v in (cscore if isinstance(cscore, list) else [cscore])]
    while len(cs) < 5:
        cs.append(None)
    bs = [_num(v) for v in cons_to_list(bscore)]
    _gs(gen)["members"].append({
        "program_id": _pid(raw),        # identity off the full tree
        "tree_str": tree_str,           # lossless clean AST (replaces expr + tree)
        "tree_ast": expr,               # nested preOrder list — clause walker input (stripped on emit)
        "cscore": {
            "raw_score": cs[0], "complexity": cs[1], "complexity_penalty": cs[2],
            "uniformity_penalty": cs[3], "penalized_score": cs[4],
        },
        "complexity": cs[1],
        "bscore": bs if bs else None,
    })
    return 0


_KIND_BY_TAG = {"LSK": "logical", "SSK": "strategy"}

def add_knob(gen, deme_id, loc, multip, default, tag=None):
    """One call per deme knob, keyed by deme_id for multi-deme support."""
    s = _gs(gen); did = _demeid(deme_id); d = _dslot(s, did)
    m = _num(unwrap_atom(multip)); lz = unwrap_atom(loc)
    kind = _KIND_BY_TAG.get(_flat(tag)) or _knob_kind(m)   # tag wins; multiplicity is fallback only
    d["knobs"].append({
        "knob_id": lz if isinstance(lz, (int, float)) else _flat(lz),
        "multiplicity": m, "kind": kind, "default_setting": _num(default),
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
    """A merge survivor (mkExemplar from removeDominated) entering the resize cull.
    raw/cpx/pen are scalars extracted by named cscore accessors in MeTTa, so
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


def set_deme_evals(deme_id, state):
    """Per-deme fitness-call count, keyed by deme_id (expandDemeHelper has no gen)."""
    try:
        e = state[8]
        evals = (_num(e[1]) + _num(e[2])
                 if isinstance(e, (list, tuple)) and len(e) >= 3 and e[0] == "+"
                 else _num(e))
    except Exception:
        evals = None
    _pending_deme_evals[_demeid(deme_id)] = evals
    return 0


def set_problem_spec(labels, arity=None):
    """Input feature space — the domain the pair-sampling / FS / operator-inclusion
    action spaces are defined over. From getArgLabels (mkITable ...).
    Called once at run start; persists into every state_doc for that run."""
    global _problem_spec
    raw = cons_to_list(labels)
    if not raw:
        raw = list(labels) if isinstance(labels, list) else [labels]
    lbls = [_flat(x) for x in raw]
    _problem_spec = {
        "problem_type": "boolean",
        "input_labels": lbls,
        "arity": (_num(arity) if arity is not None else len(lbls)),
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
    global _atom_alphabet
    ptype = _effective_problem_type(_pending_run_params.get("problem_type"))
    _atom_alphabet = _build_atom_alphabet()
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
    return 0


def set_problem_spec_strategy(moves, n_games, opponent_policy, complexity_ratio):
    """Strategy analog of set_problem_spec. Moves arrive as a marshalled flat list
    of symbols (bare MeTTa tuple, not a Cons spine)."""
    global _problem_spec
    mv = moves if isinstance(moves, list) else [moves]
    _problem_spec = {
        "problem_type": "strategy",
        "moves": [_flat(m) for m in mv],
        "n_games": _num(n_games),
        "opponent_policy": _flat(opponent_policy),
        "complexity_ratio": _num(complexity_ratio),
    }
    return 0


def flush_terminal(gen):
    """Final post-merge metapopulation -> terminal.json. Offline/experiment use;
    no ready/ sentinel (not an agent step)."""
    g = _num(gen)
    rp = _pending_run_params
    problem_type           = rp.get("problem_type")
    complexity_ratio       = rp.get("complexity_ratio")
    n_eval                 = rp.get("n_eval")
    hill_climb_max_evals   = rp.get("hill_climb_max_evaluations")
    max_cands_per_deme     = rp.get("max_cands_per_deme")
    min_pool_size          = rp.get("min_pool_size")
    complexity_temperature = rp.get("complexity_temperature")
    n_to_keep              = rp.get("n_to_keep")
    cap_coef               = rp.get("cap_coef")
    n_deme                 = rp.get("n_deme")
    optimizer              = rp.get("optimizer")
    ptype = _effective_problem_type(problem_type)
    s = _gs(g)
    members = s["members"]
    pens = [m["cscore"]["penalized_score"] for m in members
            if isinstance(m["cscore"]["penalized_score"], (int, float))]
    best = max(pens) if pens else None
    hc_max = get_hill_climb_max_evals()
    if hill_climb_max_evals is not None:
        hc_max = _num(hill_climb_max_evals) or hc_max
    members_out = [_member_out(m) for m in members]
    doc = {
        "schema_version": _VERSION, "run_seq": _run_seq, "record_type": "terminal",
        "timestamp_ms": int(time.time() * 1000),
        "total_hill_climb_evaluations": _total_evals,
        "total_evaluations": _total_evals,
        "metapopulation": {"size": len(members_out),
                           "best_penalized_score": best, "members": members_out},
        "problem_spec": _problem_spec,
        "run_parameters": {
            "problem_type": ptype,
            "complexity_ratio": (_cr_or_none(complexity_ratio)
                                 if _cr_or_none(complexity_ratio) is not None
                                 else _last_complexity_ratio),
            "n_eval": _num(n_eval),
            "hill_climb_max_evaluations": hc_max,
            "max_cands_per_deme": _num(max_cands_per_deme), "min_pool_size": _num(min_pool_size),
            "complexity_temperature": _num(complexity_temperature), "n_to_keep": _num(n_to_keep),
            "cap_coef": _num(cap_coef), "n_deme": _num(n_deme), "optimizer": _flat(optimizer),
        },
    }
    _write_json(os.path.join(_cur_state_dir, "terminal.json"), doc)
    return 0


def flush_gen(gen):
    """v0.5: per-step state is dynamic-only; static config lives in run_config.json."""
    global _pending_selection, _pending_merge, _pending_deme_evals, _depth
    global _total_evals, _explored_ids, _last_complexity_ratio
    g = _num(gen)
    ptype = _effective_problem_type(_pending_run_params.get("problem_type"))
    s = _gs(g)
    members = s["members"]

    pens = [m["cscore"]["penalized_score"] for m in members
            if isinstance(m["cscore"]["penalized_score"], (int, float))]
    best = max(pens) if pens else None
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
    for i, did in enumerate(s["deme_order"]):
        d = s["demes"][did]
        kb = {"logical": 0, "strategy": 0, "other": 0}
        for k in d["knobs"]:
            kb[k["kind"]] = kb.get(k["kind"], 0) + 1
        nbh = sum(max(_num(k["multiplicity"]) - 1, 0) for k in d["knobs"]
                  if isinstance(k["multiplicity"], (int, float)))
        ev = d["evaluations"] if d["evaluations"] is not None else (_num(d["instances"]) or 0)
        evals_gen += ev or 0
        demes.append({
            "deme_id": did, "exemplar_program_id": selected_id,
            "exemplar_expr": d["deme_tree"],
            "knobs": d["knobs"], "knob_count": len(d["knobs"]),
            "knob_type_breakdown": kb,
            "neighborhood_size": nbh,
            "instances_evaluated": d["instances"],
            "hill_climb_evaluations": d["evaluations"],
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

    score_vs_complexity_trend = _compute_score_vs_complexity_trend(members, g)

    # Atom evidence is best-effort emission metadata; malformed trees must not
    # interrupt search or generation output. The aggregation adds no new failure
    # surface on the search path (settled-side only), but stays wrapped anyway.
    try:
        atom_evidence, atom_lossless = _build_atom_evidence(members, g, ptype, best)
    except Exception:  # pragma: no cover - defensive only
        atom_evidence = {"atom_appearances": [], "realized_cooccurrences": [],
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
        "score_vs_complexity_trend": score_vs_complexity_trend,
        "atom_evidence": atom_evidence,
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
