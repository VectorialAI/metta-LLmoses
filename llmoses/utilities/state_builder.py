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
import utility_schema
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

# The embedding runtime seeds Python's RNG deterministically, so bias-path
# draws repeat run to run unless a seed is forced (sweep/experiment reps).
_RNG_SEED = os.environ.get("LLMOSES_RNG_SEED")
if _RNG_SEED:
    random.seed(_RNG_SEED)

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

# --- M2 hardening state (PLAN-m2-hardening.md) --------------------------------
# W-2 generation fence: the buffer is valid for exactly one generation.
#   _await_gen   = the generation MOSES most recently asked a response for
#                  (set at the top of await_response, timeout or not);
#   _current_gen = the generation whose draws are in progress (enter_gen);
#   _ingest_key  = (run_seq, gen) of the last ingest (re-ingest is a no-op).
# Invariant while any lever is consulted: _utility_gen == _await_gen, and at
# the top of generation G: _await_gen == G-1. A violation is FATAL (abort),
# never a fallback — an offset other than 1 means the meta-loop is broken.
_await_gen = None
_current_gen = None
_ingest_key = None
_quality = {}              # W-19 experiment-quality counters (nonzero => degraded)
_confab = {}               # W-23 confabulation statistics (run-scoped)
_lost_streak = 0           # W-23 consecutive non-decline responses that yielded nothing
_versions_seen = set()     # W-28 responder protocol versions observed in responses
_context_stats = {}        # W-22 context-strategy instrumentation (aggregated)
_logging_degraded = 0      # W-17 audit-log writes that failed (surfaced in terminal)
_aborted = False           # W-20 set once _abort_run has fired
_abort_record = None
_exit_fn = os._exit        # test hook: replaced by a BaseException raiser in tests
_ABORT_EXIT_CODE = 3       # the driver reads a non-zero exit as "not a run"

# --- Phase II return leg (blocking watcher handshake) -----------------------
# OFF by default so existing watcher-less smoke tests are byte-for-byte unchanged;
# Phase II runs opt in with LLMOSES_AWAIT_RESPONSE=1 and a live watcher.
_AWAIT_ENABLED = os.environ.get("LLMOSES_AWAIT_RESPONSE", "0") == "1"
_RESP_POLL_S = float(os.environ.get("LLMOSES_RESPONSE_POLL_S", "0.05"))
_RESP_TIMEOUT_S = float(os.environ.get("LLMOSES_RESPONSE_TIMEOUT_S", "30"))
# R1: the RUN CONFIGURATION declares which generations expect an estimate —
# never the responder (a responder that crashes before declaring itself must
# not be able to turn a failed run into a clean native one). With
# LLMOSES_AWAIT_RESPONSE=1, LLMOSES_EXPECT_RESPONSE_GENS is a generation
# predicate: "all" (default), "none", or a comma list of ints / inclusive
# ranges ("1-3,5", "4-", "-2") for frontloaded / backloaded interlock
# ablations. Inside the window a missing response ABORTS; outside it MOSES
# does not block at all — native by design, recorded, never degradation.
_EXPECT_SPEC = os.environ.get("LLMOSES_EXPECT_RESPONSE_GENS", "all").strip() or "all"


def _parse_gen_spec(spec):
    """Return predicate(gen) -> bool for an expected-generation spec."""
    spec = (spec or "all").strip().lower()
    if spec == "all":
        return lambda g: True
    if spec == "none":
        return lambda g: False
    ranges = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:
            lo, hi = tok.split("-", 1)
            lo = int(lo) if lo.strip() else None
            hi = int(hi) if hi.strip() else None
        else:
            lo = hi = int(tok)
        ranges.append((lo, hi))
    if not ranges:
        raise ValueError(f"empty expected-generation spec {spec!r}")

    def expected(g):
        try:
            g = int(g)
        except (TypeError, ValueError):
            return True
        return any((lo is None or g >= lo) and (hi is None or g <= hi)
                   for lo, hi in ranges)
    return expected


try:
    _EXPECT = _parse_gen_spec(_EXPECT_SPEC)
except ValueError as _e:
    sys.stderr.write(f"[state_builder] bad LLMOSES_EXPECT_RESPONSE_GENS "
                     f"{_EXPECT_SPEC!r}: {_e}; expecting every generation\n")
    _EXPECT_SPEC, _EXPECT = "all", (lambda g: True)
_native_by_design = []     # generations skipped because they were outside the window
# W-3 heartbeat reader: a declared responder whose CONTROL/heartbeat counter
# has not advanced for this many seconds of MOSES's OWN monotonic clock is
# dead (clock-domain free: only "did the counter change" is compared).
_HB_STALL_S = float(os.environ.get("LLMOSES_HEARTBEAT_STALL_S", "120"))
_HB_READ_EVERY_S = 0.5
# W-23 fatal threshold: consecutive non-decline responses that yielded no
# applicable guidance (schema failure / fabricated ids) abort the run.
_MAX_LOST_STREAK = int(os.environ.get("LLMOSES_MAX_CONSECUTIVE_LOST", "2"))
# W-23 fatal threshold (plan §3): consecutive schema-invalid responses abort
# the run even when something salvaged through — with constrained generation
# (--output-schema, slot template) a schema failure should be near-impossible,
# so a run of them means the responder is broken, not unlucky.
_MAX_SCHEMA_STREAK = int(os.environ.get("LLMOSES_MAX_CONSECUTIVE_SCHEMA_FAILURES", "3"))
_schema_fail_streak = 0
# W-10 durability: fsync every atomic JSON write (default off).
_FSYNC = os.environ.get("LLMOSES_FSYNC", "0") == "1"
_CONTROL_DIR = os.path.join(_RUN_DIR, "CONTROL")
_ID_SAMPLE_CAP = 10

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


def _write_json(path, doc, durable=False):
    """Atomic JSON write (tmp + os.replace). durable=True (or LLMOSES_FSYNC=1)
    also fsyncs the temp file before the rename and the directory after it,
    so the document survives a process that exits with os._exit right
    after (R4: the abort path must not lose its own evidence)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        if _FSYNC or durable:
            fh.flush()
            os.fsync(fh.fileno())
    os.replace(tmp, path)
    if _FSYNC or durable:
        try:
            dfd = os.open(os.path.dirname(path), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass


def _flush_native_log(durable=False):
    """Push every buffered audit row to the OS (and to disk when durable)."""
    try:
        _NFH.flush()
        if durable:
            os.fsync(_NFH.fileno())
    except Exception as e:
        sys.stderr.write(f"[log] flush failed: {e!r}\n")


def _read_json_quiet(path):
    """Parse a small JSON file; None when absent/unreadable (never raises)."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


def _control_path(name):
    return os.path.join(_CONTROL_DIR, name)


def _responder_declared():
    """W-24: the responder ownership record (CONTROL/responder), or None.
    A released record (owner exited cleanly) counts as not declared."""
    doc = _read_json_quiet(_control_path("responder"))
    if doc is None or doc.get("released"):
        return None
    return doc


def _bump(counter, key, n=1):
    counter[key] = counter.get(key, 0) + n


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
    global _await_gen, _current_gen, _ingest_key, _quality, _confab, _lost_streak
    global _versions_seen, _context_stats, _aborted, _abort_record
    global _gen, _logging_degraded, _native_by_design, _schema_fail_streak
    _run_seq = max(_run_seq + 1, _max_existing_run_seq() + 1)
    _aborted = False
    _abort_record = None
    _gen = {}                # a run's terminal/abort record must never show a prior run's members
    _logging_degraded = 0
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
    _await_gen = None
    _current_gen = None
    _ingest_key = None
    _quality = {}
    _confab = {}
    _lost_streak = 0
    _versions_seen = set()
    _context_stats = {}
    _native_by_design = []
    _schema_fail_streak = 0
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
            "rng_seed": _RNG_SEED,
        },
        # W-16: the responder reads the MOSES-side deadline from here to
        # assert LIVE_TIMEOUT_S * (RETRIES+1) < RESPONSE_TIMEOUT_S before its
        # first provider call (the two processes do not share an environment).
        "handshake": _handshake_block(),
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


def _handshake_block():
    return {"await_enabled": _AWAIT_ENABLED,
            "expect_response_gens": _EXPECT_SPEC,
            "response_timeout_s": _RESP_TIMEOUT_S,
            "poll_s": _RESP_POLL_S,
            "heartbeat_stall_s": _HB_STALL_S,
            "max_consecutive_lost": _MAX_LOST_STREAK,
            "max_consecutive_schema_failures": _MAX_SCHEMA_STREAK,
            "fsync": _FSYNC}


def _compute_verdict():
    """W-19 run_verdict. `aborted` = exited non-zero (not a run). `degraded`
    = completed and mechanically correct but carrying experiment-quality
    caveats (any nonzero quality flag). `ok` otherwise. Computed identically
    for every run; there is no demo/experiment split."""
    if _aborted:
        return "aborted"
    if any(v for v in _quality_flags().values()):
        return "degraded"
    return "ok"


def _quality_flags():
    """Nonzero experiment-quality counters (W-19). Sources: W-26 unknown ids,
    W-18 salvage drops, W-14 retries that succeeded, W-23 coverage/schema,
    W-17 logging, W-1 legacy timeouts, flush-section capture failures, and
    W-28 protocol drift (more than one responder version in one run)."""
    flags = dict((k, v) for k, v in _quality.items() if v)
    for k, v in _capture_failures.items():
        if v:
            flags[f"capture_failures.{k}"] = v
    if _logging_degraded:
        flags["logging_degraded"] = _logging_degraded
    # W-28 drift: more than one version stamped on responses, or responses
    # stamped with a version other than the one the responder declared.
    declared = (_responder_declared() or {}).get("protocol_version")
    versions = set(_versions_seen)
    if declared and versions:
        versions.add(declared)
    if len(versions) > 1:
        flags["protocol_drift"] = len(versions)
    return flags


def _confab_block():
    """W-23 confabulation statistics as a per-run record."""
    out = {"unknown_program_ids": {}, "schema_failures": 0,
           "unknown_atoms": 0, "salvage_drops": 0, "lost_generations": 0,
           "coverage": {"requested": 0, "supplied": 0, "partial_generations": 0},
           "responses": 0, "declines": 0}
    out["unoffered_program_ids"] = {}
    for k, v in _confab.items():
        if k in ("unknown_program_ids", "unoffered_program_ids"):
            field = "unknown" if k == "unknown_program_ids" else "unoffered"
            for ch, st in v.items():
                total = st.get("total", 0)
                out[k][ch] = {
                    field: st.get(field, 0), "total": total,
                    "rate": (round(st.get(field, 0) / total, 6)
                             if total else None),
                    "sample": list(st.get("sample", []))[:_ID_SAMPLE_CAP]}
        else:
            out[k] = v
    return out


def _terminal_doc(members, verdict, abort=None):
    best = _best_penalized(members)
    members_out = [_member_out(m) for m in members]
    responder = _responder_declared() or _read_json_quiet(_control_path("responder"))
    return {
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
        # --- M2 hardening (W-19 and friends) ---------------------------------
        "run_verdict": verdict,
        "quality_flags": _quality_flags(),
        "confabulation": _confab_block(),
        "logging_degraded": _logging_degraded,
        "abort": abort,
        "handshake": _handshake_block(),
        "responder": responder,
        # W-28: the responder-declared protocol identifier (None = undeclared
        # responder); versions_seen lists every identifier stamped on a
        # response this run — more than one is undeclared drift.
        "protocol_version": ((responder or {}).get("protocol_version")
                             if responder else None),
        "protocol_versions_seen": sorted(_versions_seen),
        # W-22: context strategy as recorded by the responder, plus the
        # per-generation instrumentation aggregate.
        "context_strategy": ((responder or {}).get("context_strategy")
                             if responder else None),
        "context_instrumentation": dict(_context_stats) or None,
        "generations_awaited": _await_gen,
        # R1: the expected-response window and the generations that ran
        # native BY DESIGN (outside it) — reported as such, not as degradation.
        "response_window": {"spec": _EXPECT_SPEC,
                            "await_enabled": _AWAIT_ENABLED,
                            "native_generations": list(_native_by_design)},
    }


def flush_terminal(gen):
    """Final post-merge metapopulation -> terminal.json (with run_verdict)."""
    g = _num(gen)
    s = _gs(g)
    doc = _terminal_doc(s["members"], _compute_verdict())
    _write_json(os.path.join(_cur_state_dir, "terminal.json"), doc)
    _log_event("run_verdict", verdict=doc["run_verdict"],
               quality_flags=doc["quality_flags"] or None)
    return 0


def _abort_run(reason, **detail):
    """W-20 / §1.3: end the run NOW and record why. Writes CONTROL/abort (if
    the responder did not already), a terminal.json with run_verdict
    'aborted', a run_aborted audit row, then exits the process non-zero so
    the driver sees a failed run. MOSES never proceeds without an estimate it
    was supposed to receive. Never returns (the test hook raises instead)."""
    global _aborted, _abort_record
    if _aborted:
        return
    _aborted = True
    record = {"reason": reason, "source": detail.pop("source", "moses"),
              "run_seq": _run_seq, "generation": _await_gen,
              "current_gen": _current_gen, "ts_ms": int(time.time() * 1000),
              "detail": detail}
    _abort_record = record
    _bump(_capture_failures, f"abort:{reason}")
    _log_event("run_aborted", reason=reason, detail=detail)
    try:
        if not os.path.exists(_control_path("abort")):
            _write_json(_control_path("abort"), record, durable=True)
    except Exception as e:
        sys.stderr.write(f"[abort] could not write CONTROL/abort: {e}\n")
    try:
        gens = [k for k in _gen if isinstance(k, (int, float))]
        members = _gs(max(gens))["members"] if gens else []
        _write_json(os.path.join(_cur_state_dir, "terminal.json"),
                    _terminal_doc(members, "aborted", abort=record),
                    durable=True)
    except Exception as e:
        sys.stderr.write(f"[abort] could not write terminal.json: {e}\n")
    # R4: os._exit skips every Python-level flush, so the audit log (the
    # run_aborted row and everything before it) is pushed to disk HERE.
    _flush_native_log(durable=True)
    sys.stderr.write(f"[abort] run {_run_seq} aborted: {reason} {detail}\n")
    try:
        sys.stderr.flush()
        sys.stdout.flush()
    except Exception:
        pass
    _exit_fn(_ABORT_EXIT_CODE)


def _check_abort_channel():
    """W-20: a CONTROL/abort written by the responder/supervisor ends the run."""
    doc = _read_json_quiet(_control_path("abort"))
    if doc is None and os.path.exists(_control_path("abort")):
        doc = {"reason": "abort_requested", "detail": "unreadable abort document"}
    if doc is not None:
        _abort_run("abort_requested", source=str(doc.get("source") or "responder"),
                   requested_reason=doc.get("reason"),
                   requested_detail=doc.get("detail"))


def enter_gen(g):
    """Top of generation g (before any draw). W-2: assert the response fence
    is exactly one generation behind; W-20: honour a pending abort. Called
    from runMosesLoop via sbEnterGen; returns 0 like every sb* hook."""
    global _current_gen
    g = _num(g)
    _current_gen = g
    try:
        _check_abort_channel()
        if _AWAIT_ENABLED and _await_gen is not None and _await_gen != g - 1:
            _abort_run("generation_fence", where="enter_gen", generation=g,
                       await_gen=_await_gen, utility_gen=_utility_gen)
        if _pending_utilities is not None and _utility_gen != g - 1:
            _abort_run("generation_fence", where="enter_gen", generation=g,
                       await_gen=_await_gen, utility_gen=_utility_gen)
    except Exception as e:
        sys.stderr.write(f"[enter_gen] error gen {g}: {e}\n")
    return 0


class _HeartbeatWatch:
    """W-3 reader: tracks CONTROL/heartbeat's monotonic counter against
    MOSES's own monotonic clock. stalled() is True only when a heartbeat has
    been seen and its counter has not advanced for _HB_STALL_S seconds."""

    def __init__(self):
        self.counter = None
        self.changed_at = None
        self.next_read = 0.0
        self.seen = False

    def observe(self, now):
        if now < self.next_read:
            return
        self.next_read = now + _HB_READ_EVERY_S
        doc = _read_json_quiet(_control_path("heartbeat"))
        if doc is None:
            return
        counter = doc.get("counter")
        if counter != self.counter:
            self.counter, self.changed_at, self.seen = counter, now, True

    def stalled(self, now):
        return self.seen and (now - self.changed_at) >= _HB_STALL_S


def await_response(g):
    """Phase II return leg: block until the responder signals a response for
    gen g, ingest it, then hand control back to MOSES.

    Gated by LLMOSES_AWAIT_RESPONSE (default off) so non-Phase-II runs are
    unaffected. Failure policy (plan §1.3, revision R1): the run
    configuration says which generations EXPECT an estimate
    (LLMOSES_EXPECT_RESPONSE_GENS, default all). Inside that window a
    missing response is a failed run no matter who was supposed to answer —
    timeout, dead supervisor (W-3 heartbeat stall) and CONTROL/abort (W-20)
    all exit non-zero with run_verdict 'aborted'. Outside the window MOSES
    does not block: the generation is native by design and recorded in
    terminal.json's response_window. Always returns 0 — shape-identical to
    every sb* hook."""
    global _await_gen, _pending_utilities
    if not _AWAIT_ENABLED:
        return 0
    g = _num(g)
    try:
        if _await_gen is not None and g <= _await_gen:
            if g == _await_gen:      # hook re-entry: idempotent, logged
                _log_event("await_reentry", generation=g)
                return 0
            _abort_run("generation_fence", where="await_response",
                       generation=g, await_gen=_await_gen)
        _await_gen = g
        if not _EXPECT(g):
            # Outside the declared window: native by design. Nothing may
            # carry over into the next generation (the fence still holds:
            # _await_gen advanced, buffer empty).
            _pending_utilities = None
            _native_by_design.append(g)
            _log_event("await_skipped", generation=g, expected=False,
                       window=_EXPECT_SPEC)
            return 0
        sentinel = os.path.join(_RESPONSE_DIR, f"run-{_run_seq}-step-{g}")
        start = time.monotonic()
        deadline = start + _RESP_TIMEOUT_S
        hb = _HeartbeatWatch()
        while not os.path.exists(sentinel):
            now = time.monotonic()
            _check_abort_channel()
            hb.observe(now)
            if hb.stalled(now):
                # A heartbeat file exists only because a responder wrote it;
                # a static counter means that responder is dead.
                _bump(_capture_failures, "supervisor_dead")
                _log_event("supervisor_dead", generation=g,
                           heartbeat_counter=hb.counter,
                           stalled_s=round(now - hb.changed_at, 3))
                _abort_run("supervisor_dead", generation=g,
                           heartbeat_counter=hb.counter,
                           stalled_s=round(now - hb.changed_at, 3))
            if now >= deadline:
                declared = _responder_declared()
                _bump(_capture_failures, "response_timeout")
                _log_event("response_timeout", generation=g,
                           timeout_s=_RESP_TIMEOUT_S,
                           responder_declared=declared is not None,
                           heartbeat_seen=hb.seen)
                # R1: an expected estimate did not arrive. Whether a
                # responder ever declared itself is irrelevant — the more
                # broken the responder, the more important this abort is.
                _pending_utilities = None
                _abort_run("response_timeout", generation=g,
                           timeout_s=_RESP_TIMEOUT_S,
                           responder=(declared or {}).get("owner"),
                           responder_declared=declared is not None,
                           heartbeat_seen=hb.seen)
                return 0
            time.sleep(_RESP_POLL_S)
        # Response present — ingest the UtilityResponse payload into module
        # state (Phase II consumption).
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
            # W-17: the WHY lands in the run directory, not only on stderr.
            _log_event("section_failed", generation=g, section=name,
                       error=repr(e)[:500])
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
    # W-26: every program id that existed in generation g — pre-merge members,
    # resize-cull entrants, and post-merge survivors — is the universe a
    # responder may legitimately reference for g. Kept on the gen record
    # (reset only by begin_gen/new_run) so ingest validates without a disk read.
    s["known_ids"] = cur_ids | post_ids | {c["program_id"] for c in cull_cands}
    # R2: what the responder was OFFERED as slots — the survivor set
    # (response_template._survivor_ids: members ∪ entrants restricted to
    # resize_cull.survivors; the whole pool when no survivors list exists).
    s["offered_ids"] = set(post_ids) if post_ids else set(s["known_ids"])

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

    # W-9: the ready sentinel is edge-triggered, write-once, existence-only.
    # Nothing reads its content; liveness lives in CONTROL/heartbeat instead.
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
    """One JSONL audit row in moses_native_log.jsonl; never raises. A failed
    write must not kill the run, but it must not be silent either (W-17):
    the run-scoped logging_degraded counter is surfaced in terminal.json."""
    global _logging_degraded
    try:
        row = {"run_seq": _run_seq, "event": event, "ts_ms": int(time.time() * 1000)}
        row.update(fields)
        _NFH.write(json.dumps(row) + "\n")
    except Exception as e:
        _logging_degraded += 1
        try:
            sys.stderr.write(f"[log_event] audit write failed ({event}): {e!r}\n")
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
    (pass=true clears the buffer, so it reads as native everywhere).

    W-2 fence: a buffered response is consulted only while it is exactly one
    generation behind — it was ingested for the generation MOSES most
    recently awaited. Any other offset is a broken meta-loop, so it aborts."""
    if _pending_utilities is None:
        return False
    if _utility_gen != _await_gen:
        _abort_run("generation_fence", where=f"_lever_on:{name}",
                   utility_gen=_utility_gen, await_gen=_await_gen,
                   current_gen=_current_gen)
        return False
    if name not in _APPLY_LEVERS:
        return False
    if _LEVER_WEIGHTS.get(name, 0.0) <= 0.0:
        return False
    if data_key is not None and not _pending_utilities.get(data_key):
        return False
    return True


def _roulette(weights):
    """Native rouletteSelect semantics: r*sum, walk subtracting. Returns the
    positional index into weights, or None when the total mass is zero.
    Zero-weight entries are never selectable — without the skip, a draw of
    exactly 0.0 would land on a leading zero-weight entry, violating the
    lambda=1 'zero eliminates the option' guarantee."""
    total = sum(weights)
    if total <= 0:
        return None
    adjusted = total * random.random()
    last_positive = None
    for i, w in enumerate(weights):
        if w <= 0:
            continue
        last_positive = i
        adjusted -= w
        if adjusted <= 0:
            return i
    return last_positive


# Contextual-prior vocabulary: context keys on atom_utility_prior entries map
# to feature_utility_levers.lever_weights axes (D-033). Mirrors the
# atom_evidence bucket vocabulary so the agent reads and writes one language.
_CTX_KEY_AXIS = {
    "polarity": "polarity", "clause_type": "clause_type",
    "parent_operator": "parent_operator", "depth_bucket": "tree_depth",
    "exemplar_id": "selected_exemplar",
}
_LEVER_WEIGHT_AXES = ("polarity", "clause_type", "parent_operator", "tree_depth",
                      "selected_exemplar", "combination_synergy", "novelty")
_RESPONSE_KEYS = ("pass", "sampling_temperature", "exemplar_utilities",
                  "atom_utility_prior", "combination_synergy",
                  "feature_utility_levers", "culling_utilities",
                  "complexity_ratio_delta", "comparator_bias",
                  "status", "outcome")     # W-5 additive metadata


def _unknown_ids(doc, known, offered=None):
    """W-26 (R2 split): per id-bearing channel, two buckets over the ids the
    responder supplied — A `unknown` (existed nowhere in generation G:
    hallucination) and B `unoffered` (existed in G — e.g. shown pre-merge —
    but was not in the offered slot set: protocol adherence). Ids in the
    offered set are simply correct. Rates over total_ids_supplied, sample
    capped. '*' is the legitimate newborn-default sentinel on the culling
    channel. Behaviour is unchanged — such entries stay inert at lookup;
    this only makes them visible."""
    channels = {
        "exemplar_utilities": [e.get("program_id") for e in
                               (doc.get("exemplar_utilities") or [])
                               if isinstance(e, dict)],
        "culling_utilities": [e.get("program_id") for e in
                              (doc.get("culling_utilities") or [])
                              if isinstance(e, dict)
                              and str(e.get("program_id")) != "*"],
        "comparator_bias": list(((doc.get("comparator_bias") or {})
                                 .get("program_id_ordering") or [])
                                if isinstance(doc.get("comparator_bias"), dict)
                                else []),
    }
    out = {}
    for ch, ids in channels.items():
        ids = [str(i) for i in ids if i is not None]
        if not ids:
            continue
        unknown = [i for i in ids if i not in known]
        unoffered = ([i for i in ids if i in known and i not in offered]
                     if offered is not None else [])
        out[ch] = {"unknown": len(unknown), "unoffered": len(unoffered),
                   "total": len(ids),
                   "rate": round(len(unknown) / len(ids), 6),
                   "unoffered_rate": round(len(unoffered) / len(ids), 6),
                   "sample": unknown[:_ID_SAMPLE_CAP],
                   "unoffered_sample": unoffered[:_ID_SAMPLE_CAP]}
    return out


def _record_confab(g, unknown_ids, schema_ok, outcome, decline):
    """W-23: fold one response's observations into the run-scoped stats."""
    _bump(_confab, "responses")
    if decline:
        _bump(_confab, "declines")
    if not schema_ok:
        _bump(_confab, "schema_failures")
        _bump(_quality, "schema_failures")
    per = _confab.setdefault("unknown_program_ids", {})
    per_b = _confab.setdefault("unoffered_program_ids", {})
    for ch, st in unknown_ids.items():
        agg = per.setdefault(ch, {"unknown": 0, "total": 0, "sample": []})
        agg["unknown"] += st["unknown"]
        agg["total"] += st["total"]
        for i in st["sample"]:
            if len(agg["sample"]) < _ID_SAMPLE_CAP and i not in agg["sample"]:
                agg["sample"].append(i)
        if st["unknown"]:
            _bump(_quality, "unknown_program_ids", st["unknown"])
        agg_b = per_b.setdefault(ch, {"unoffered": 0, "total": 0, "sample": []})
        agg_b["unoffered"] += st.get("unoffered", 0)
        agg_b["total"] += st["total"]
        for i in st.get("unoffered_sample", []):
            if len(agg_b["sample"]) < _ID_SAMPLE_CAP and i not in agg_b["sample"]:
                agg_b["sample"].append(i)
        if st.get("unoffered"):
            _bump(_quality, "unoffered_program_ids", st["unoffered"])
    if isinstance(outcome, dict):
        attempts = outcome.get("attempts")
        if outcome.get("retried") or (isinstance(attempts, int) and attempts > 1):
            _bump(_quality, "retries",
                  max(1, (attempts or 2) - 1))
        sal = outcome.get("salvage")
        if isinstance(sal, dict):
            dropped = max(0, (sal.get("requested") or 0) - (sal.get("survived") or 0))
            if dropped:
                _bump(_quality, "salvage_drops", dropped)
                _bump(_confab, "salvage_drops", dropped)
        cov = outcome.get("coverage")
        if isinstance(cov, dict):
            c = _confab.setdefault("coverage", {"requested": 0, "supplied": 0,
                                                "partial_generations": 0})
            req, sup = cov.get("requested"), cov.get("supplied")
            if isinstance(req, int):
                c["requested"] += req
            if isinstance(sup, int):
                c["supplied"] += sup
            if (cov.get("mode") == "full" and isinstance(req, int)
                    and isinstance(sup, int) and sup < req):
                c["partial_generations"] += 1
                _bump(_quality, "partial_coverage")
        pv = outcome.get("protocol_version")
        if isinstance(pv, str) and pv:
            _versions_seen.add(pv)
        ctx = outcome.get("context")
        if isinstance(ctx, dict):
            cs = _context_stats
            cs.setdefault("strategies", [])
            if ctx.get("strategy") and ctx["strategy"] not in cs["strategies"]:
                cs["strategies"].append(ctx["strategy"])
            chars = ctx.get("chars")
            if isinstance(chars, int):
                cs["max_chars"] = max(cs.get("max_chars", 0), chars)
                cs["total_chars"] = cs.get("total_chars", 0) + chars
            cs["generations"] = cs.get("generations", 0) + 1
            if ctx.get("compressed"):
                cs["compressions"] = cs.get("compressions", 0) + 1
            if ctx.get("dropped"):
                cs["dropped_total"] = cs.get("dropped_total", 0) + len(ctx["dropped"])


def _ingest_utilities(g):
    """Parse utilities/run-N/step-G.json (written by the responder BEFORE the
    response sentinel) into normalized per-lever lookups. Anything supplied
    but not usable is reported in the utility_ingest row's `ignored` map —
    an estimation must never drop silently.

    W-2 fence: re-ingest of the same (run, gen) is a no-op; a generation older
    than the fence is rejected; an unreadable response clears the buffer and,
    like every non-200/204 status (W-5, plan §1.3), aborts the run."""
    global _pending_utilities, _utility_gen, _ingest_key, _lost_streak
    global _schema_fail_streak
    key = (_run_seq, g)
    if _ingest_key == key:
        _log_event("utility_ingest_skipped", generation=g, reason="duplicate")
        return
    if _utility_gen is not None and g < _utility_gen:
        _log_event("utility_ingest_skipped", generation=g, reason="stale",
                   utility_gen=_utility_gen)
        return
    path = os.path.join(_RUN_DIR, "utilities", f"run-{_run_seq}", f"step-{g}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict):
            raise ValueError("UtilityResponse is not a JSON object")
    except Exception as e:
        # W-1b: never leave the previous generation's guidance live.
        _pending_utilities, _utility_gen, _ingest_key = None, g, key
        _bump(_capture_failures, "utility_ingest_error")
        _log_event("utility_ingest_error", generation=g, error=str(e)[:200])
        _abort_run("responder_failure", generation=g, status=500,
                   error_class="unreadable_response", detail=str(e)[:200])
        return
    ignored = {}
    for k in doc:
        if k not in _RESPONSE_KEYS:
            v = doc[k]
            ignored[k] = len(v) if isinstance(v, (list, dict)) else "present"
    # Diagnostic schema check: logged and counted (W-23), never a filter —
    # ingest still normalizes what it can.
    schema_ok, schema_errors = utility_schema.validate_utility_response(
        doc, _atom_alphabet)
    status = utility_schema.effective_status(doc)
    outcome = doc.get("outcome") if isinstance(doc.get("outcome"), dict) else None
    known = _gs(g).get("known_ids") if g in _gen else None
    offered = _gs(g).get("offered_ids") if g in _gen else None
    unknown_ids = (_unknown_ids(doc, known, offered)
                   if known is not None else {})
    decline = bool(doc.get("pass", True))
    _record_confab(g, unknown_ids, schema_ok, outcome, decline)
    _schema_fail_streak = 0 if schema_ok else _schema_fail_streak + 1
    if not schema_ok and _MAX_SCHEMA_STREAK > 0 \
            and _schema_fail_streak >= _MAX_SCHEMA_STREAK:
        _pending_utilities, _utility_gen, _ingest_key = None, g, key
        _log_event("schema_failure_cascade", generation=g,
                   streak=_schema_fail_streak, schema_errors=schema_errors[:3])
        _abort_run("schema_failure_cascade", generation=g,
                   streak=_schema_fail_streak, schema_errors=schema_errors[:3])
        return
    if status not in utility_schema.CONTINUE_STATUSES or \
            (status == 200) == decline:
        # W-5/W-15/§1.3: the responder reported a failure (or a status that
        # contradicts `pass`, which is a contract break and reads the same).
        # Guidance that should have existed did not; that contaminates every
        # later generation, so the run is not the experiment it claims to be.
        _pending_utilities, _utility_gen, _ingest_key = None, g, key
        _bump(_capture_failures, f"responder_{status}")
        _log_event("responder_failure", generation=g, status=status,
                   pass_flag=decline,
                   error_class=(outcome or {}).get("error_class"),
                   detail=str((outcome or {}).get("detail"))[:200],
                   schema_ok=schema_ok)
        _abort_run("responder_failure", generation=g, status=status,
                   error_class=(outcome or {}).get("error_class"),
                   detail=str((outcome or {}).get("detail"))[:200])
        return
    if decline:
        _pending_utilities, _utility_gen, _ingest_key = None, g, key
        _lost_streak = 0
        _log_event("utility_ingest", generation=g, decline=True, status=status,
                   ignored=ignored or None, schema_ok=schema_ok,
                   schema_errors=schema_errors[:3] or None,
                   unknown_ids=unknown_ids or None,
                   outcome=outcome or None)
        return

    exemplar = {}
    for e in doc.get("exemplar_utilities") or []:
        if isinstance(e, dict) and e.get("program_id") is not None:
            exemplar[str(e["program_id"])] = _clamp01(e.get("utility"))
        else:
            ignored["exemplar_utilities"] = \
                ignored.get("exemplar_utilities", 0) + 1
    retention = {}
    retention_default = None
    for e in doc.get("culling_utilities") or []:
        if not isinstance(e, dict) or e.get("program_id") is None:
            ignored["culling_utilities"] = ignored.get("culling_utilities", 0) + 1
            continue
        r = e.get("retention_utility", e.get("retain_utility"))
        if r is None and e.get("cull_utility") is not None:
            r = 1.0 - _clamp01(e.get("cull_utility"))
        if r is None:
            ignored["culling_utilities"] = ignored.get("culling_utilities", 0) + 1
            continue
        # program_id "*" = default retention for candidates the agent has not
        # seen (programs born after the response) — without it, fresh
        # candidates are structurally exempt from culling guidance.
        if str(e["program_id"]) == "*":
            retention_default = _clamp01(r)
        else:
            retention[str(e["program_id"])] = _clamp01(r)
    atom_prior = {}
    atom_prior_ctx = []   # contextual entries, response order preserved (D-033)
    for e in doc.get("atom_utility_prior") or []:
        if not (isinstance(e, dict) and e.get("atom") is not None):
            continue
        ctx = e.get("context")
        if isinstance(ctx, dict) and ctx:
            keys = {k: str(v) for k, v in ctx.items()
                    if k in _CTX_KEY_AXIS and v is not None}
            if keys:
                atom_prior_ctx.append({"atom": str(e["atom"]),
                                       "utility": _clamp01(e.get("utility")),
                                       "context": keys})
            else:
                ignored["atom_utility_prior.context"] = \
                    ignored.get("atom_utility_prior.context", 0) + 1
            continue
        atom_prior[str(e["atom"])] = _clamp01(e.get("utility"))
    synergy = []
    for e in doc.get("combination_synergy") or []:
        if isinstance(e, dict) and isinstance(e.get("atoms"), list) and e["atoms"]:
            synergy.append({"atoms": frozenset(str(a) for a in e["atoms"]),
                            "utility": _clamp01(e.get("utility"))})
    # W-23 "usable": did this response carry ANY guidance MOSES can apply?
    # Judged on what was SUPPLIED (before inert-entry pruning — a responder
    # may deliberately emit inert entries) and, for id channels, on ids that
    # actually existed in generation g (a channel made only of fabricated
    # ids contributes nothing). Consulted for the lost-generation cascade.
    def _known_hits(channel, supplied_n):
        """Ids that can actually match a draw: offered ones (an unoffered id
        was culled at merge and is as inert as a fabricated one)."""
        st = unknown_ids.get(channel)
        if st is None:
            return supplied_n
        return st["total"] - st["unknown"] - st.get("unoffered", 0)
    # Atom channels: an atom outside the run's alphabet (or a synergy set of
    # the wrong width / unknown labels) can never match a draw site — it is
    # the atom analogue of a fabricated program id (W-23 "unknown atoms").
    labels = set(_atom_alphabet_map) if _atom_alphabet_map else None
    if labels is not None:
        known_atoms = ([a for a in atom_prior if a in labels]
                       + [e for e in atom_prior_ctx if e["atom"] in labels])
        known_syn = [e for e in synergy if e["atoms"] <= labels]
        unknown_atoms = ((len(atom_prior) - sum(1 for a in atom_prior if a in labels))
                         + sum(1 for e in atom_prior_ctx if e["atom"] not in labels)
                         + (len(synergy) - len(known_syn)))
    else:
        known_atoms, known_syn, unknown_atoms = (list(atom_prior) + atom_prior_ctx,
                                                 list(synergy), 0)
    if unknown_atoms:
        _bump(_confab, "unknown_atoms", unknown_atoms)
        _bump(_quality, "unknown_atoms", unknown_atoms)
    supplied_usable = bool(
        _known_hits("exemplar_utilities", len(exemplar)) > 0
        or _known_hits("culling_utilities", len(retention)) > 0
        or retention_default is not None
        or known_atoms or known_syn)
    levers = doc.get("feature_utility_levers") or {}
    aggregate_fn = levers.get("aggregate_fn") if isinstance(levers, dict) else None
    if aggregate_fn not in ("product", "mean", "geometric_mean", "softmax"):
        aggregate_fn = "product"
    lever_weights = {}
    lw = levers.get("lever_weights") if isinstance(levers, dict) else None
    if isinstance(lw, dict):
        for k, v in lw.items():
            if k in _LEVER_WEIGHT_AXES:
                lever_weights[k] = _clamp01(v)
            else:
                ignored[f"lever_weights.{k}"] = "unknown_axis"
    # Inert-entry pruning: a contextual entry whose named axes multiply to a
    # zero blend weight, or synergy under a zero combination_synergy axis,
    # can never affect a draw. Prune here so begin_combo_draw's gate stays 0
    # and the native selector path (and its RNG consumption) is untouched —
    # the all-zero lever_weights => v1-byte-identical guarantee is a gate
    # property, not just a weight property.
    inert = {}
    kept_ctx = []
    for e in atom_prior_ctx:
        w = 1.0
        for k in e["context"]:
            w *= lever_weights.get(_CTX_KEY_AXIS[k], 0.0)
        if w > 0.0:
            kept_ctx.append(e)
    if len(kept_ctx) != len(atom_prior_ctx):
        inert["atom_prior_ctx"] = len(atom_prior_ctx) - len(kept_ctx)
        atom_prior_ctx = kept_ctx
    if synergy and lever_weights.get("combination_synergy", 0.0) <= 0.0:
        inert["combination_synergy"] = len(synergy)
        synergy = []
    comparator_rank = {}
    cb = doc.get("comparator_bias")
    if isinstance(cb, dict):
        for rank, pid in enumerate(cb.get("program_id_ordering") or []):
            comparator_rank.setdefault(str(pid), rank)
    elif cb is not None:
        ignored["comparator_bias"] = "invalid_shape"
    delta = doc.get("complexity_ratio_delta")
    if not (isinstance(delta, dict) and delta.get("direction") in
            ("increase", "decrease", "maintain")):
        if delta is not None:
            # Pre-D-030 bare strings land here: rejected by design — the agent
            # must constrained-generate the {direction, magnitude} object.
            ignored["complexity_ratio_delta"] = "invalid_shape"
        delta = None
    temp = doc.get("sampling_temperature")
    try:
        temp = float(temp) if temp is not None and float(temp) > 0 else None
    except (TypeError, ValueError):
        temp = None

    _pending_utilities = {
        "exemplar": exemplar, "retention": retention,
        "retention_default": retention_default, "atom_prior": atom_prior,
        "atom_prior_ctx": atom_prior_ctx, "synergy": synergy,
        "lever_weights": lever_weights,
        "aggregate_fn": aggregate_fn, "comparator_rank": comparator_rank,
        "complexity_ratio_delta": delta, "sampling_temperature": temp,
    }
    _utility_gen = g
    _ingest_key = key
    # W-23 fatal threshold: a non-decline response that yields NOTHING
    # applicable (every id fabricated, schema failure dropped everything) is
    # a lost generation; consecutive lost generations abort the run.
    usable = bool(supplied_usable
                  or _known_hits("comparator_bias", len(comparator_rank)) > 0
                  or delta is not None)
    if usable:
        _lost_streak = 0
    else:
        _lost_streak += 1
        _bump(_confab, "lost_generations")
        _bump(_quality, "lost_generations")
    _log_event("utility_ingest", generation=g, decline=False, status=status,
               exemplar=len(exemplar), retention=len(retention),
               atoms=len(atom_prior), atoms_ctx=len(atom_prior_ctx),
               synergy=len(synergy),
               lever_weights=({k: v for k, v in lever_weights.items() if v > 0}
                              or None),
               comparator=len(comparator_rank),
               ratio_delta=(delta or {}).get("direction"), temperature=temp,
               ignored=ignored or None, inert=inert or None,
               schema_ok=schema_ok,
               schema_errors=schema_errors[:3] or None,
               unknown_ids=unknown_ids or None,
               usable=usable, lost_streak=_lost_streak,
               outcome=outcome or None)
    if _lost_streak >= _MAX_LOST_STREAK > 0:
        _abort_run("guidance_lost_cascade", generation=g,
                   lost_streak=_lost_streak, schema_ok=schema_ok,
                   unknown_ids=unknown_ids or None)


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


def begin_combo_draw(combos, labels, op=None, path=None):
    """Gate + setup for one sampler node draw. combos = enumerated index
    combinations (pairs/triplets) into labels; op = the exemplar node's
    operator; path = the node id (its tree path — root is (0), a child of the
    root is (n), deeper nodes concatenate). Returns 1 when the atom_prior
    lever applies (the fork then draws through weighted_combo_pick); 0 keeps
    the native lazyRandomSelector untouched.

    D-033 contextual application: each atom's effective utility starts from
    the global prior (missing => neutral 1.0) and blends matching contextual
    entries, weighted by the product of the lever_weights of the axes the
    entry conditions on — all-zero lever_weights reproduces the global-only
    v1 behavior exactly. The aggregated combo weight is then multiplied by
    the combination_synergy factor (the non-separable channel)."""
    global _combo_buf
    try:
        p = _pending_utilities
        if not (_lever_on("atom_prior") and
                (p["atom_prior"] or p["atom_prior_ctx"] or p["synergy"])):
            _combo_buf = None
            return 0
        label_list = [_flat(l) for l in (labels if isinstance(labels, list) else [labels])]
        combo_list = []
        for c in (combos if isinstance(combos, list) else []):
            idxs = [int(_num(v)) for v in (c if isinstance(c, list) else [c])]
            combo_list.append(idxs)
        prior = p["atom_prior"]
        prior_ctx = p["atom_prior_ctx"]
        synergy = p["synergy"]
        lw = p["lever_weights"]
        temp = p["sampling_temperature"]
        fn = p["aggregate_fn"]
        lam = _LEVER_WEIGHTS["atom_prior"]

        # Live draw context. The drawn perm becomes a clause under the SWAPPED
        # operator (getArgs builds ($swapedOp ...)); under alternating AND/OR
        # canonicalization clause_type and parent_operator coincide, exactly
        # as atom_evidence records them. Depth: the node id is its tree path
        # (root (0) is depth 0; elsewhere depth = path length); the new clause
        # sits one below the node, bucketed with atom_evidence's bands.
        op_s = _flat(op) if op is not None else None
        clause_op = {"AND": "OR", "OR": "AND"}.get(op_s, op_s)
        path_l = [int(_num(v)) for v in (path if isinstance(path, list)
                                         else ([] if path in (None, ()) else [path]))]
        node_depth = 0 if path_l == [0] else len(path_l)
        depth_bucket = (atom_evidence._depth_bucket(node_depth + 1)
                        if path_l else None)
        exemplar_id = (_pending_selection or {}).get("program_id")
        draw_ctx = {"clause_type": clause_op, "parent_operator": clause_op,
                    "depth_bucket": depth_bucket, "exemplar_id": exemplar_id}

        def u_eff(atom, pol):
            """Blend global + matching contextual priors; None = no entry
            touched this atom (stay neutral, unsharpened)."""
            touched = atom in prior
            u = prior[atom] if touched else 1.0
            for e in prior_ctx:
                if e["atom"] != atom:
                    continue
                w, match = 1.0, True
                for k, v in e["context"].items():
                    cur = pol if k == "polarity" else draw_ctx.get(k)
                    if cur is None or str(cur) != v:
                        match = False
                        break
                    w *= lw.get(_CTX_KEY_AXIS[k], 0.0)
                if not match or w <= 0.0:
                    continue
                if not touched:
                    touched, u = True, 1.0
                u = (1.0 - w) * u + w * e["utility"]
            return u if touched else None

        syn_w = lw.get("combination_synergy", 0.0)
        syn_map = ({e["atoms"]: e["utility"] for e in synergy}
                   if syn_w > 0.0 else {})

        weights, names, literals = [], [], []
        for idxs in combo_list:
            atoms = [label_list[i] if 0 <= i < len(label_list) else None for i in idxs]
            # Boolean pair polarity is order-encoded at the draw: getArgs emits
            # (NOT first, second) for ascending index pairs, a positive pair
            # otherwise. Strategy triplets carry no NOT at the draw.
            if len(idxs) == 2 and idxs[0] < idxs[1]:
                pols = ["-", "+"]
            else:
                pols = ["+"] * len(idxs)
            u_hats = []
            for a, pol in zip(atoms, pols):
                u = u_eff(a, pol)
                u_hats.append(_sharpen(u, temp) if u is not None else 1.0)
            w = _mix(1.0, _aggregate_prior(u_hats, fn), lam)
            if syn_map:
                key = frozenset(a for a in atoms if a is not None)
                if key in syn_map:
                    lam_s = lam * syn_w
                    w *= lam_s * _sharpen(syn_map[key], temp) + (1.0 - lam_s)
            weights.append(w)
            names.append(atoms)
            literals.append([f"{pol}{a}" for a, pol in zip(atoms, pols)])
        _combo_buf = {"weights": weights, "names": names, "literals": literals}
        _log_event("bias_applied", lever="atom_prior", response_gen=_utility_gen,
                   lam=lam, aggregate_fn=fn, n_combos=len(weights),
                   nonzero=sum(1 for w in weights if w > 0),
                   clause_type=clause_op, depth_bucket=depth_bucket,
                   exemplar_id=exemplar_id,
                   contextual=bool(prior_ctx), synergy=bool(syn_map))
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
        def _row(field):
            vals = buf.get(field) or []
            return vals[remaining[pos]] if remaining[pos] < len(vals) else None
        pos = _roulette(weights)
        if pos is None:  # zero mass left: deliberate diversity cut exhausted
            pos = random.randint(0, len(remaining) - 1)
            _log_event("bias_degraded", lever="atom_prior",
                       reason="zero_mass_pool", remaining=len(remaining))
            _log_event("combo_pick", lever="atom_prior", degraded=True,
                       index=remaining[pos], atoms=_row("names"),
                       literals=_row("literals"))
            return remaining[pos]
        _log_event("combo_pick", lever="atom_prior", degraded=False,
                   index=remaining[pos], atoms=_row("names"),
                   literals=_row("literals"))
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
