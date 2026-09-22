"""M2 four-call state emission, per-call transport, and policy application."""
import functools
import hashlib
import itertools
import json
import math
import os
import random
import sys
import time

import atom_evidence
import call_paths
import checkpointing
import conditional_policy
import lever_config
import lever_policy as policy
import responder_control as rc
import runspace
import utility_schema
from boundary import (_num, _flat, unwrap_atom, cons_to_list, expr_to_str,
                      cr_or_none as _cr_or_none, present_atom as _present_atom,
                      demeid as _demeid)

_VERSION = "2.0-four-call"
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_LLMOSES_DIR = os.path.dirname(_THIS_DIR)
_RS = runspace.bootstrap(_LLMOSES_DIR, _VERSION)
_RUN_ID, _RUN_DIR = _RS.run_id, _RS.run_dir
_STATE_DIR, _ACTION_DIR = _RS.state_dir, _RS.action_dir
_READY_DIR, _RESPONSE_DIR, _NFH = _RS.ready_dir, _RS.response_dir, _RS.native_log
_CONTROL_DIR = os.path.join(_RUN_DIR, "CONTROL")
_AWAIT_ENABLED = os.environ.get("LLMOSES_AWAIT_RESPONSE", "0") == "1"
_EXPECT_SPEC = os.environ.get("LLMOSES_EXPECT_RESPONSE_GENS", "all")
_RESP_POLL_S = float(os.environ.get("LLMOSES_RESPONSE_POLL_S", "0.05"))
_RESP_TIMEOUT_S = float(os.environ.get("LLMOSES_RESPONSE_TIMEOUT_S", "300"))
_HB_STALL_S = float(os.environ.get("LLMOSES_HEARTBEAT_STALL_S", "120"))
_HB_READ_EVERY_S = 0.5
_FSYNC = os.environ.get("LLMOSES_FSYNC", "0") == "1"
_RNG_SEED = os.environ.get("LLMOSES_RNG_SEED")
if _RNG_SEED is not None:
    random.seed(_RNG_SEED)
_exit_fn = os._exit
_ID_SAMPLE_CAP = 10
_EVAL_COUNT_INDEX = 8
_HC_MAX_EVALS_DEFAULT = 10000
_KIND_BY_TAG = {"LSK": "boolean", "SSK": "strategy"}
_CSCORE_FIELDS = ("raw_score", "complexity", "complexity_penalty", "uniformity_penalty", "penalized_score")
_run_seq = 0
_cur_state_dir, _cur_action_dir = _STATE_DIR, _ACTION_DIR
_gen, _pending_deme_evals, _depth, _pending_run_params = {}, {}, {}, {}
_explored_ids, _versions_seen = set(), set()
_atom_alphabet, _atom_alphabet_map, _atom_cumulative = None, {}, {}
_pending_selection, _pending_merge, _problem_spec = None, None, None
_capture_failures, _quality, _confab, _context_stats = {}, {}, {}, {}
_total_evals, _logging_degraded = 0, 0
_aborted, _abort_record = False, None
_current_gen, _current_call, _await_gen = None, 0, None
_config, _run_config = None, None
_responses, _call_states, _call_status, _site_records = {}, {}, {}, {}
_row_weights, _sel_buf, _retained, _generation_start_members = [], [], set(), []
_combo_bufs, _draws, _candidate_pairs = {}, [], {}
_construction_history, _previous_draws = [], []
_needs_initial_rescore = False
_build_seq = 0
_build_tree = None
_site_seq = 0
_next_token = 0
_known_ids, _native_by_design = set(), []
_continuation, _checkpoint_request = None, None
_previous_outcome, _native_evolution = {}, None

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


def begin_gen(gen):
    _gen[_num(gen)] = _blank(_num(gen))
    return 0


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
    pid = _pid(raw)
    if pid not in _depth:
        parent = (_pending_selection or {}).get("program_id")
        _depth[pid] = _depth.get(parent, 0) + 1 if parent else 0
    _gs(gen)["members"].append({
        "program_id": _pid(raw),        # identity off the full tree
        "tree_str": tree_str,           # lossless clean AST (replaces expr + tree)
        "tree_ast": expr,               # nested preOrder list — clause walker input (stripped on emit)
        "cscore": cscore_fields,
        "complexity": cscore_fields["complexity"],
        "bscore": bscore_values if bscore_values else None,
    })
    return 0


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


_EXPECT = _parse_gen_spec(_EXPECT_SPEC)

def _experiment():
    global _config
    if _config is None:
        _config = lever_config.load()
    return _config


def new_run():
    global _run_seq, _cur_state_dir, _cur_action_dir, _config, _run_config
    global _pending_selection, _pending_merge, _problem_spec, _atom_alphabet
    global _current_gen, _current_call, _await_gen, _total_evals, _logging_degraded
    global _aborted, _abort_record, _continuation, _previous_outcome, _next_token
    global _row_weights, _generation_start_members, _build_seq, _site_seq, _build_tree
    global _needs_initial_rescore
    _config = lever_config.load()
    _run_seq = max(_run_seq + 1, _max_existing_run_seq() + 1)
    _cur_state_dir = os.path.join(_STATE_DIR, f"run-{_run_seq}")
    _cur_action_dir = os.path.join(_ACTION_DIR, f"run-{_run_seq}")
    for path in (_cur_state_dir, _cur_action_dir):
        os.makedirs(path, exist_ok=True)
    for value in (_gen, _pending_deme_evals, _depth, _pending_run_params,
                  _atom_alphabet_map, _atom_cumulative, _capture_failures,
                  _quality, _confab, _context_stats, _responses, _call_states,
                  _call_status, _site_records, _combo_bufs, _candidate_pairs):
        value.clear()
    for value in (_explored_ids, _versions_seen, _known_ids, _retained,
                  _native_by_design, _draws, _sel_buf, _construction_history, _previous_draws):
        value.clear()
    _pending_selection = _pending_merge = _problem_spec = _atom_alphabet = None
    _current_gen, _current_call, _await_gen = None, 0, None
    _total_evals = _logging_degraded = _next_token = _build_seq = _site_seq = 0
    _build_tree = None
    _aborted, _abort_record, _continuation = False, None, None
    _needs_initial_rescore = any(w != 1.0 for w in _row_weights)
    _row_weights, _generation_start_members, _previous_outcome = [], [], {}
    _run_config = None
    return _run_seq


def _effective_problem_type():
    # Resolve the run-parameter override at every site, including Call 1. Using
    # it only for config emission made strategy game scores look like rows.
    return (_present_atom(_pending_run_params.get("problem_type"))
            or (_problem_spec or {}).get("problem_type"))


def _build_run_parameters():
    cfg = _experiment()
    params = {k: _num(v) for k, v in _pending_run_params.items() if k != "complexity_ratio"}
    params["complexity_coef"] = complexity_coef(_pending_run_params.get("complexity_ratio", 3.5))
    params["selection_temperature"] = cfg["selection_temperature"]
    return params


def emit_run_config():
    global _atom_alphabet, _atom_alphabet_map, _run_config
    ptype = _effective_problem_type()
    if ptype != "boolean" and any(s["b"] for s in _experiment()["levers"].values()):
        _abort_run("unsupported_guided_problem", problem_type=ptype)
    _atom_alphabet, _atom_alphabet_map = atom_evidence.build_atom_alphabet(_problem_spec, ptype)
    _run_config = {"schema_version": _VERSION, "record_type": "run_config",
                   "run_seq": _run_seq, "problem_spec": _problem_spec,
                   "atom_alphabet": _atom_alphabet, "run_parameters": _build_run_parameters(),
                   "experiment": _experiment(),
                   "active_levers": [n for n, s in _config["levers"].items() if s["b"] > 0],
                   "rng_seed": _RNG_SEED, "handshake": _handshake_block(),
                   "baseline": "upstream plus declared retention redesign and overlay fixes"}
    _write_json(os.path.join(_cur_state_dir, "run_config.json"), _run_config, durable=True)
    runspace.ensure_context_docs(_LLMOSES_DIR, _RUN_ID, _RUN_DIR, run_seq=_run_seq,
        problem_type=ptype, problem_spec=_problem_spec,
        active_levers=_run_config["active_levers"], experiment=_config)
    _log_event("effective_config", experiment=_config, parameters=_build_run_parameters())
    return 0


def _handshake_block():
    return {"await_enabled": _AWAIT_ENABLED, "expect_response_gens": _EXPECT_SPEC,
            "response_timeout_s": _RESP_TIMEOUT_S, "poll_s": _RESP_POLL_S,
            "heartbeat_stall_s": _HB_STALL_S, "per_call": True}


def _member_out(member):
    pid = member["program_id"]
    out = {k: v for k, v in member.items() if k != "tree_ast"}
    out.update(explored=pid in _explored_ids, lineage_depth=_depth.get(pid, 0),
               max_lineage_depth=max(_depth.values(), default=0),
               unweighted_score=sum(member.get("bscore") or []),
               active_pairs=_candidate_pairs.get(pid, []))
    return out


def _terminal_doc(members, verdict, abort=None):
    return {"schema_version": _VERSION, "run_seq": _run_seq, "record_type": "terminal",
            "generation": _current_gen, "total_evaluations": _total_evals,
            "metapopulation": {"size": len(members), "members": [_member_out(m) for m in members],
                              "best_penalized_score": _best_penalized(members)},
            "run_verdict": verdict, "quality_flags": _quality_flags(), "abort": abort,
            "stop_reason": "empty_population" if not members else "generation_or_target_limit",
            "confabulation": _confab_block(), "logging_degraded": _logging_degraded,
            "protocol_versions_seen": sorted(_versions_seen),
            "context_instrumentation": _context_stats,
            "response_window": {"spec": _EXPECT_SPEC, "native_calls": _native_by_design},
            "handshake": _handshake_block(), "experiment": _experiment(),
            "run_parameters": _build_run_parameters(), "problem_spec": _problem_spec}


def flush_terminal(gen):
    doc = _terminal_doc(_gs(gen)["members"], _compute_verdict())
    _log_event("run_verdict", verdict=doc["run_verdict"], quality_flags=doc["quality_flags"])
    _write_json(os.path.join(_cur_state_dir, "terminal.json"), doc, durable=True)
    _flush_native_log(durable=True)
    return 0


def _abort_run(reason, **detail):
    global _aborted, _abort_record
    _aborted = True
    _abort_record = {"reason": reason, "detail": detail, "run_seq": _run_seq,
                     "generation": _current_gen, "call": _current_call}
    _log_event("run_aborted", **_abort_record)
    try:
        _write_json(_control_path("abort"), _abort_record, durable=True)
        members = _gs(_current_gen)["members"] if _current_gen is not None else []
        _write_json(os.path.join(_cur_state_dir, "terminal.json"),
                    _terminal_doc(members, "aborted", _abort_record), durable=True)
        sys.stderr.write(f"[LLMOSES abort] {reason}: {json.dumps(detail, default=str)}\n")
    finally:
        _flush_native_log(durable=True)
        sys.stdout.flush()
        sys.stderr.flush()
        _exit_fn(3)
    raise RuntimeError("abort exit hook returned")


def _check_abort_channel():
    if os.path.exists(_control_path("abort")):
        _abort_run("abort_requested", request=_read_json_quiet(_control_path("abort")))


def enter_gen(g):
    global _current_gen, _current_call, _generation_start_members
    g = int(_num(g))
    _check_abort_channel()
    if _current_gen is not None and (g != _current_gen + 1 or _current_call != 4):
        _abort_run("generation_fence", previous_generation=_current_gen, next_generation=g)
    if _combo_bufs:
        _abort_run("unreleased_sampler_tokens", tokens=list(_combo_bufs))
    _current_gen, _current_call = g, 0
    _responses.clear()
    _call_states.clear()
    _call_status.clear()
    _site_records.clear()
    _previous_draws[:] = _draws
    _construction_history.clear()
    _draws.clear()
    _generation_start_members = []
    _known_ids.clear()
    return 0


def checkpoint_native(continuation):
    global _continuation
    # mkM2... constructors are data, not evaluable calls. The bridge preserves
    # the atom's nested list shape; llmContinue pattern-matches it on restore.
    _continuation = continuation
    return 0


_CHECKPOINT_GLOBALS = (
    "_run_seq", "_gen", "_pending_deme_evals", "_depth", "_pending_run_params",
    "_explored_ids", "_versions_seen", "_atom_alphabet", "_atom_alphabet_map",
    "_atom_cumulative", "_pending_selection", "_pending_merge", "_problem_spec",
    "_capture_failures", "_quality", "_confab", "_context_stats", "_total_evals",
    "_logging_degraded", "_current_gen", "_current_call", "_await_gen", "_config",
    "_run_config", "_responses", "_call_states", "_call_status", "_site_records",
    "_row_weights", "_needs_initial_rescore", "_sel_buf", "_retained", "_generation_start_members",
    "_combo_bufs", "_draws", "_candidate_pairs", "_next_token",
    "_construction_history", "_previous_draws", "_build_seq", "_build_tree", "_site_seq",
    "_known_ids", "_native_by_design", "_previous_outcome", "_native_evolution")


def _save_checkpoint(request):
    state = {name: globals()[name] for name in _CHECKPOINT_GLOBALS}
    context = checkpointing.context_snapshot(_RUN_DIR, _run_seq)
    path = os.path.join(_RUN_DIR, "checkpoints", f"run-{_run_seq}", "latest.json")
    checkpointing.save(path, state, _continuation, request, context)
    _flush_native_log(durable=True)
    return path


def restore_checkpoint():
    global _cur_state_dir, _cur_action_dir, _continuation, _current_call
    path = os.environ.get("LLMOSES_RESUME_CHECKPOINT")
    if not path:
        raise ValueError("LLMOSES_RESUME_CHECKPOINT is required")
    state, continuation, doc = checkpointing.restore(path)
    for name in _CHECKPOINT_GLOBALS:
        globals()[name] = state[name]
    _cur_state_dir = os.path.join(_STATE_DIR, f"run-{_run_seq}")
    _cur_action_dir = os.path.join(_ACTION_DIR, f"run-{_run_seq}")
    _continuation = continuation
    checkpointing.restore_context(_RUN_DIR, doc["agent_context"])
    request = doc["request"]
    _current_call = request["call"] - 1
    pause = _read_json_quiet(_control_path("pause"))
    if pause:
        fence = {k: request[k] for k in ("run_seq", "generation", "call")}
        if any(pause.get(k) != v for k, v in fence.items()):
            _abort_run("checkpoint_pause_fence", expected=fence, pause=pause)
        # Rejoin the persisted pause. Do not checkpoint/log a second pause just
        # because its waiting process was restarted.
        _wait_for_resume(fence)
        paths = call_paths.paths(_RUN_DIR, _run_seq, f"{_current_gen}-call-{request['call']}")
        for key in ("response", "utilities"):
            if os.path.exists(paths[key]):
                os.unlink(paths[key])
    _call(request["call"], payload=request)
    if request["call"] == 4:
        apply_retention(_pending_run_params["min_pool_size"],
                        _pending_run_params["complexity_temperature"], _current_gen)
    return continuation


def _pause(reason, request):
    path = _save_checkpoint(request)
    if os.path.exists(_control_path("pause_requested")):
        os.unlink(_control_path("pause_requested"))
    fence = {k: request[k] for k in ("run_seq", "generation", "call")}
    pause = {**fence, "reason": reason, "checkpoint": path}
    _write_json(_control_path("pause"), pause, durable=True)
    _log_event("run_paused", **pause)
    _wait_for_resume(fence)


def _wait_for_resume(fence):
    while True:
        _check_abort_channel()
        resume = _read_json_quiet(_control_path("resume"))
        if resume is not None and all(resume.get(k) == v for k, v in fence.items()):
            os.unlink(_control_path("resume"))
            os.unlink(_control_path("pause"))
            _log_event("run_resumed", **fence)
            return
        time.sleep(_RESP_POLL_S)


def _payload(call):
    members = [_member_out(m) for m in _gs(_current_gen)["members"]]
    state = {"schema_version": _VERSION, "run_seq": _run_seq, "generation": _current_gen,
             "call": call, "problem_type": _effective_problem_type(),
             "metapopulation": {"size": len(members), "members": members},
             "capture_status": {"ok": True, "failed_sections": []},
             "previous_outcome": _previous_outcome,
             "total_evaluations": _total_evals + (sum(d.get("evaluations") or 0 for d in
                _gs(_current_gen)["demes"].values()) if call == 4 else 0)}
    if call == 1:
        # Row weighting is Boolean-only. Strategy seeds and evaluated members
        # can have different game-score vector lengths; they are not shared rows.
        size = (len(members[0].get("bscore") or [])
                if members and state["problem_type"] == "boolean" else 0)
        state["rows"] = [{"row": i, "scores": {m["program_id"]: m["bscore"][i] for m in members}}
                         for i in range(size)]
    elif call in (2, 4):
        state["candidates"] = members
        if call == 2:
            state["row_weights"] = list(_row_weights)
        else:
            state["drawn_pairs"] = list(_draws)
            state["demes"] = (list(_gs(_current_gen)["demes"].values())
                              if "demes" in _emitted_sections() else {"gated": None})
            if "atom_evidence" in _emitted_sections():
                try:
                    evidence, lossless, rollup = atom_evidence.build_atom_evidence(
                        _gs(_current_gen)["members"], _current_gen, _effective_problem_type(),
                        _best_penalized(_gs(_current_gen)["members"]), _atom_alphabet_map,
                        _atom_cumulative, _VERSION, _run_seq)
                    state["atom_evidence"], state["atom_lossless"] = evidence, lossless
                    # Depth bands and score summaries are operator roll-ups
                    # (reversal #21): they go to the native log, never to the agent.
                    _log_event("atom_evidence_rollup", **rollup)
                except Exception as exc:
                    _bump(_capture_failures, "atom_evidence")
                    state["capture_status"] = {"ok": False, "failed_sections": ["atom_evidence"]}
                    state["atom_evidence"] = state["atom_lossless"] = {"error": str(exc)}
            else:
                state["atom_evidence"], state["atom_lossless"] = {"gated": None}, {"gated": None}
    else:
        state["selection"] = _pending_selection
        state["alphabet"] = _atom_alphabet
        labels = [a["label"] for a in (_atom_alphabet or {}).get("atoms", [])]
        state["pairs"] = [list(p) for p in itertools.permutations(labels, 2)]
        state["condition_vocabulary"] = conditional_policy.vocabulary(_experiment()["context_radius"])
        state["previous_draws"] = list(_previous_draws)
    return state


_EMITTABLE_SECTIONS = ("atom_evidence", "demes")


def _emitted_sections():
    """Optional Call 4 sections. A name outside the known set is a config
    error, not a gate: silently emitting `gated: null` for a typo would look
    identical to a deliberate ablation (P3)."""
    raw = os.environ.get("LLMOSES_EMIT_SECTIONS", ",".join(_EMITTABLE_SECTIONS))
    names = {n.strip() for n in raw.split(",") if n.strip()}
    unknown = names - set(_EMITTABLE_SECTIONS)
    if unknown:
        _abort_run("unknown_emit_section", unknown=sorted(unknown), allowed=list(_EMITTABLE_SECTIONS))
    return names


def _call(call, payload=None):
    global _current_call, _await_gen, _checkpoint_request, _generation_start_members
    if call != _current_call + 1:
        _abort_run("call_fence", requested=call, previous=_current_call)
    _current_call, _await_gen = call, _current_gen
    request = payload or _payload(call)
    _checkpoint_request = request
    _call_states[call] = request
    if call == 1:
        _generation_start_members = list(_gs(_current_gen)["members"])
    _known_ids.update(m["program_id"] for m in _gs(_current_gen)["members"])
    lever = policy.CALL_LEVERS[call]
    spec = _experiment()["levers"][lever]
    reason = ("b_zero" if spec["b"] == 0 else "outside_window" if not _EXPECT(_current_gen)
              else "await_disabled" if not _AWAIT_ENABLED else None)
    if reason:
        _responses[call] = None
        _call_status[call] = reason
        _native_by_design.append({"generation": _current_gen, "call": call, "reason": reason})
        _log_event("call_skipped", generation=_current_gen, call=call, reason=reason)
        return 0
    step = f"{_current_gen}-call-{call}"
    paths = call_paths.paths(_RUN_DIR, _run_seq, step)
    _write_json(paths["state"], request)
    _write_json(paths["action"],
                {k: v for k, v in request.items() if k in
                 ("run_seq", "generation", "call", "rows", "candidates", "pairs", "condition_vocabulary")})
    _save_checkpoint(request)
    ready, sentinel = paths["ready"], paths["response"]
    while True:
        if not os.path.exists(sentinel):
            _write_json(ready, {"run_seq": _run_seq, "generation": _current_gen, "call": call})
        deadline, hb = time.monotonic() + _RESP_TIMEOUT_S, _HeartbeatWatch()
        while not os.path.exists(sentinel):
            _check_abort_channel()
            now = time.monotonic()
            hb.observe(now)
            pause_request = _read_json_quiet(_control_path("pause_requested"))
            if now >= deadline or hb.stalled(now) or pause_request:
                reason = ((pause_request or {}).get("reason") or
                          ("response_timeout" if now >= deadline else "responder_dead"))
                _pause(reason, request)
                deadline, hb = time.monotonic() + _RESP_TIMEOUT_S, _HeartbeatWatch()
                _write_json(ready, {"run_seq": _run_seq, "generation": _current_gen, "call": call})
            time.sleep(_RESP_POLL_S)
        utility_path = paths["utilities"]
        raw = _read_json_quiet(utility_path)
        doc, report = utility_schema.ingest(raw, request, _experiment())
        trace = _read_json_quiet(paths["trace"]) or {}
        rejected = [entry["key"][len("member:"):] for entry in trace.get("dropped_keys", [])
                    if isinstance(entry, dict) and isinstance(entry.get("key"), str)
                    and entry["key"].startswith("member:")]
        ids = _id_buckets(raw or {}, request, rejected)
        if doc is not None and report["dropped"]:
            previous = doc.setdefault("outcome", {}).get("salvage", {})
            doc["outcome"]["salvage"] = {
                "requested": previous.get("requested", report["requested"]),
                "survived": report["survived"]}
        _record_confab(_current_gen, ids, doc is not None and not report["dropped"],
                       (doc or {}).get("outcome", {}), (doc or {}).get("pass", True))
        _log_event("utility_ingest", generation=_current_gen, call=call, report=report, ids=ids)
        if doc is not None and doc["status"] in (503, 504):
            # Infrastructure failure never silently contaminates an experimental arm.
            _pause((doc.get("outcome") or {}).get("error_class", "provider_failure"), request)
            os.unlink(sentinel)
            if os.path.exists(ready):
                os.unlink(ready)
            continue
        if doc is None or doc["status"] in (422, 500):
            _responses[call] = None
            _call_status[call] = "semantic_degradation"
            _bump(_quality, "semantic_degradation")
            _log_event("call_degraded", generation=_current_gen, call=call,
                       reason=_call_status[call], divergence=0.0)
        else:
            _responses[call] = None if doc["pass"] else doc
            _call_status[call] = "declined" if doc["pass"] else "applied"
        return 0


def _id_buckets(doc, state, rejected_ids=()):
    field = utility_schema.FIELDS[state["call"]]
    if state["call"] not in (2, 4):
        return {}
    entries = doc.get(field, []) if isinstance(doc.get(field, []), list) else []
    ids = [e["program_id"] for e in entries if isinstance(e, dict) and isinstance(e.get("program_id"), str)]
    ids.extend(rejected_ids)
    if not ids:
        return {}
    offered = {m["program_id"] for m in state.get("candidates", [])}
    unknown = [p for p in ids if p not in _known_ids]
    unoffered = [p for p in ids if p in _known_ids and p not in offered]
    return {field: {"unknown": len(unknown), "unoffered": len(unoffered), "total": len(ids),
                    "sample": unknown[:_ID_SAMPLE_CAP], "unoffered_sample": unoffered[:_ID_SAMPLE_CAP]}}


def _surface(call):
    spec = _experiment()["levers"][policy.CALL_LEVERS[call]]
    response = _responses.get(call)
    if not response:
        return 0.0, 1.0, {}
    return spec["b"], response.get(utility_schema.TEMPERATURES[call], spec["T_base"]), response


def _site(call, prior, realized, coverage=0.0, preference=None, adjustment=None, **extra):
    name = policy.CALL_LEVERS[call]
    preference = prior if preference is None else preference
    b = _surface(call)[0]
    mixed = [(1 - b) * p + b * a for p, a in zip(prior, preference)]
    record = {"generation": _current_gen, "call": call, "lever": name,
              "fired": bool(_surface(call)[0]), "reason": _call_status.get(call, "not_reached"),
              "P": prior, "adjustment": adjustment, "A": preference, "D0": mixed,
              "D": realized, "tv_agent": policy.divergence(prior, preference)["tv"],
              "tv_realized": policy.divergence(prior, realized)["tv"], "coverage": coverage,
              **policy.divergence(prior, realized), **extra}
    _site_records.setdefault(call, []).append(record)
    _log_event("lever_site", **record)


def call_rows():
    return _call(1)


def install_row_weights():
    global _row_weights, _needs_initial_rescore
    old_weights = list(_row_weights)
    count = len(_call_states[1].get("rows", []))
    prior = [1.0 / count] * count if count else []
    b, temp, response = _surface(1)
    utilities = {e["row"]: e["weight"] for e in response.get("row_weights", [])}
    preference = policy.normalize([utilities.get(i, 1.0) for i in range(count)], prior)
    realized = policy.mix(prior, preference, b, temp)
    _row_weights = [count * d for d in realized] if b else [1.0] * count
    _site(1, prior, realized, len(utilities) / count if count else 0,
          preference=preference, adjustment=[utilities.get(i, 1.0) for i in range(count)],
          realized_weights=_row_weights,
          zero_mass_fallback=bool(count) and not any(utilities.get(i, 1.0) for i in range(count)))
    changed = _needs_initial_rescore or (old_weights != _row_weights and
               (any(w != 1.0 for w in old_weights) or any(w != 1.0 for w in _row_weights)))
    _needs_initial_rescore = False
    return int(changed)


def weighted_sum(bscore, native_sum):
    values = [_num(v) for v in cons_to_list(bscore)]
    if not _row_weights or all(w == 1 for w in _row_weights):
        return _num(native_sum)
    if len(values) != len(_row_weights):
        _abort_run("row_weight_shape", rows=len(values), weights=len(_row_weights))
    return sum(w * value for w, value in zip(_row_weights, values))


def complexity_coef(ratio):
    cfg = _experiment()
    if "complexity_coef" in cfg:
        return cfg["complexity_coef"]
    r = float(_num(ratio))
    if not math.isfinite(r):
        raise ValueError("legacy complexity ratio must be finite")
    return min(1.0, max(0.0, 1.0 / r)) if r > 0 else 1.0


def selection_temperature():
    return _experiment()["selection_temperature"]


def call_exemplar():
    return _call(2)


def begin_selection(n):
    _sel_buf.clear()
    return 0


def add_selection_candidate(index, prob, tree, score):
    _sel_buf.append({"index": int(_num(index)), "weight": float(_num(prob)),
                     "pid": _pid(expr_to_str(tree)), "score": float(_num(score))})
    return 0


def select_index():
    weights = [m["weight"] for m in _sel_buf]
    prior = policy.normalize(weights)
    b, temp, response = _surface(2)
    by_id = {e["program_id"]: e["offset"] for e in response.get("exemplar_utilities", [])}
    utilities = {i: by_id[m["pid"]] for i, m in enumerate(_sel_buf) if m["pid"] in by_id}
    preference = (policy.offset_preference([m["score"] for m in _sel_buf], utilities,
                  _experiment()["selection_temperature"] / 100.0) if any(utilities.values()) else prior)
    realized = policy.mix(prior, preference, b, temp)
    index = policy.roulette(realized if b else weights)
    _site(2, prior, realized, len(utilities) / len(prior) if prior else 0,
          chosen_program_id=_sel_buf[index]["pid"], program_ids=[m["pid"] for m in _sel_buf], preference=preference,
          adjustment=[utilities.get(i, 0.0) for i in range(len(prior))])
    return _sel_buf[index]["index"]


def selection_single(tree):
    pid = _pid(expr_to_str(tree))
    offsets = {e["program_id"]: e["offset"] for e in _surface(2)[2].get("exemplar_utilities", [])}
    _site(2, [1.0], [1.0], float(pid in offsets), adjustment=[offsets.get(pid, 0.0)],
          chosen_program_id=pid, program_ids=[pid], guard="single_member")
    return 0


def call_retention(minimum, comp_temp, generation):
    global _previous_outcome
    _call(4)
    return apply_retention(minimum, comp_temp, generation)


def apply_retention(minimum, comp_temp, generation):
    global _previous_outcome
    members = _gs(_current_gen)["members"]
    scores = [m["cscore"]["penalized_score"] for m in members]
    cfg = _experiment()["retention"]
    prior = policy.softmax(scores, cfg["tau"])
    old = {m["program_id"] for m in _generation_start_members}
    entrants = sum(m["program_id"] not in old for m in members)
    k, budget = policy.retention_budget(prior, scores, len(old), entrants,
        int(_num(minimum)), float(_num(comp_temp)) * 0.30, cfg, int(_num(generation)))
    b, temp, response = _surface(4)
    by_id = {e["program_id"]: e["offset"] for e in response.get("retention_utilities", [])}
    utilities = {i: by_id[m["program_id"]] for i, m in enumerate(members) if m["program_id"] in by_id}
    preference = policy.offset_preference(scores, utilities, cfg["tau"]) if any(utilities.values()) else prior
    realized = policy.mix(prior, preference, b, temp)
    pi, adjustment = policy.inclusion_probabilities(realized, k, cfg["constraint"])
    native_pi, _ = policy.inclusion_probabilities(prior, k, cfg["constraint"])
    chosen = policy.madow(pi, k)
    _retained.clear()
    _retained.update(members[i]["program_id"] for i in chosen)
    _previous_outcome = {"survivors": sorted(_retained),
                         "culled": [m["program_id"] for m in members if m["program_id"] not in _retained]}
    _site(4, prior, realized, len(utilities) / len(prior) if prior else 0,
          preference=preference, adjustment=[utilities.get(i, 0.0) for i in range(len(prior))],
          program_ids=[m["program_id"] for m in members],
          inclusion_probabilities=pi, native_inclusion_probabilities=native_pi,
          mean_inclusion_difference=sum(abs(a - p) for a, p in zip(pi, native_pi)) / len(pi) if pi else 0,
          budget=budget, inclusion_adjustment=adjustment, survivors=sorted(_retained))
    _log_event("overflow_valve", generation=_current_gen, fired=False, reason="subsumed_by_K")
    return 0


def retain_member(tree):
    return int(_pid(expr_to_str(tree)) in _retained)


def flush_gen(gen):
    global _total_evals
    s = _gs(gen)
    if _pending_selection:
        _explored_ids.add(_pending_selection["program_id"])
    for did in s["deme_order"]:
        _total_evals += s["demes"][did].get("evaluations") or 0
    for call in policy.CALL_LEVERS:
        if call not in _site_records:
            _log_event("lever_site", generation=_current_gen, call=call,
                       lever=policy.CALL_LEVERS[call], fired=False, reason="no_draw_site",
                       P=[], adjustment=[], A=[], D0=[], D=[], coverage=0.0,
                       tv_agent=0.0, tv_realized=0.0, tv=0.0, js=0.0)
    doc = {"schema_version": _VERSION, "run_seq": _run_seq, "generation": _current_gen,
           "metapopulation": {"members": [_member_out(m) for m in s["members"]]},
           "demes": list(s["demes"].values()), "total_evaluations": _total_evals,
           "merge_summary": {**(_pending_merge or {}), "resize_cull": _previous_outcome},
           "selection": _pending_selection, "drawn_pairs": list(_draws),
           "call_status": _call_status}
    _write_json(os.path.join(_cur_state_dir, f"step-{_current_gen}.json"), doc)
    _log_event("generation_complete", generation=_current_gen,
               total_evaluations=_total_evals, call_status=_call_status)
    return 0


def call_atom():
    return _call(3)


def _items(value):
    return cons_to_list(value)


def begin_build(tree):
    global _build_seq, _build_tree
    if _combo_bufs:
        _abort_run("interleaved_representation_build", tokens=list(_combo_bufs))
    _build_seq += 1
    _build_tree = tree
    _construction_history.clear()
    return 0


def _literal(tree):
    if not isinstance(tree, list) or not tree:
        return None
    if tree[0] == "mkKnob":
        return _literal(tree[1])
    if tree[0] != "mkTree" or len(tree) != 3:
        return None
    op = unwrap_atom(tree[1])
    children = _items(tree[2])
    if op == "NOT" and len(children) == 1:
        literal = _literal(children[0])
        if literal:
            return {"atom": literal["atom"], "polarity": "-" if literal["polarity"] == "+" else "+"}
    if not children and str(op) in _atom_alphabet_map:
        return {"atom": str(op), "polarity": "+"}
    return None


def begin_combo_draw(combos, labels, op=None, node_path=None,
                     site_kind="exemplar_node", local_children=None):
    global _next_token, _site_seq
    combinations = [[int(_num(i)) for i in _items(c)] for c in _items(combos)]
    labels = [str(a) for a in _items(labels)]
    pairs = [[labels[i] for i in pair] for pair in combinations]
    path = [int(_num(x)) for x in _items(node_path)]
    _next_token += 1
    _site_seq += 1
    token = _next_token
    ancestors = [h for h in _construction_history
                 if len(h["path"]) < len(path) and path[:len(h["path"])] == h["path"]]
    local = [lit for child in _items(local_children) if (lit := _literal(child))]
    state = {"op": str(op), "depth": len(path), "site_kind": str(site_kind),
             "local_literals": local,
             "ancestor_drew": [p for h in ancestors for p in h["drawn_pairs"]],
             "already_drawn": [p for h in _construction_history for p in h["drawn_pairs"]]}
    prior = policy.normalize([1.0] * len(pairs))
    b, temperature, response = _surface(3)
    preference, detail = conditional_policy.evaluate(response.get("policy", {}), pairs, prior, state)
    realized = policy.mix(prior, preference, b, temperature)
    _combo_bufs[token] = {"pairs": pairs, "combinations": combinations, "labels": labels,
                         "P": prior, "A": preference, "D": realized, "b": b,
                         "path": path, "site_seq": _site_seq, "build_seq": _build_seq,
                         "state": state, "detail": detail, "pick_records": []}
    return token


def combo_guided(token):
    return int(_combo_bufs[int(_num(token))]["b"] > 0)


def weighted_combo_pick(token, lower, upper, picked):
    buffer = _combo_bufs[int(_num(token))]
    taken = {int(_num(i)) for i in _items(picked)}
    eligible = [i for i in range(int(_num(lower)), int(_num(upper)) + 1) if i not in taken]
    weights = [buffer["D"][i] for i in eligible]
    zero = not any(weights)
    if zero:
        weights = [1.0] * len(eligible)
    index = eligible[policy.roulette(weights)]
    buffer["pick_records"].append({"remaining": eligible,
                                   "conditional_D": policy.normalize(weights),
                                   "chosen": index, "zero_mass_fallback": zero})
    return index


def end_combo_draw(token, picked):
    buffer = _combo_bufs.pop(int(_num(token)))
    indices = [int(_num(i)) for i in _items(picked)]
    if len(indices) != len(set(indices)) or any(i < 0 or i >= len(buffer["pairs"]) for i in indices):
        _abort_run("invalid_pair_draw", site_seq=buffer["site_seq"])
    # Preserve the native selector tuple; never infer chronological order from it.
    pairs = [buffer["pairs"][i] for i in indices]
    record = {"site_seq": buffer["site_seq"], "build_seq": buffer["build_seq"],
              "path": buffer["path"], "op": buffer["state"]["op"],
              "depth": buffer["state"]["depth"], "site_kind": buffer["state"]["site_kind"],
              "local_literals": buffer["state"]["local_literals"],
              "labels": buffer["labels"], "drawn_pairs": pairs, "knobs": []}
    _construction_history.append(record)
    _draws.append(record)
    detail = buffer["detail"]
    _site(3, buffer["P"], buffer["D"], detail["coverage"],
          preference=buffer["A"], adjustment=detail["factors"],
          site_seq=buffer["site_seq"], build_seq=buffer["build_seq"],
          # Diagnostic causal position; site identity remains the sequence ID.
          path=buffer["path"],
          causal_state=buffer["state"], pair_universe=buffer["pairs"], fired_rules=detail["fired_rules"],
          zero_mass_fallback=detail["zero_mass_fallback"], drawn_pairs=pairs,
          picks=buffer["pick_records"])
    return 0


def register_pair_knobs(tree, causal_path):
    path = [int(_num(i)) for i in _items(causal_path)]
    sites = [d for d in _draws if d["build_seq"] == _build_seq and d["path"] == path]
    if not sites:
        return 0  # arity-one sites do not draw pairs
    site = sites[-1]
    labels = [a["label"] for a in (_atom_alphabet or {}).get("atoms", [])]
    if not isinstance(tree, list) or tree[0] != "mkTree":
        return 0
    for child in _items(tree[2]):
        if not isinstance(child, list) or len(child) != 4 or child[0] != "mkKnob":
            continue
        subtree = child[1]
        if isinstance(subtree, list) and subtree and subtree[0] == "mkNullVex":
            children = _items(subtree[1])
            subtree = children[0] if len(children) == 1 else None
        if not isinstance(subtree, list) or len(subtree) != 3 or subtree[0] != "mkTree":
            continue
        literals = [_literal(t) for t in _items(subtree[2])]
        if len(literals) != 2 or any(t is None for t in literals):
            continue
        actual = {(t["atom"], t["polarity"]) for t in literals}
        for a, b in site["drawn_pairs"]:
            # getArgs uses the feature set's index order, not alphabet order.
            label_order = site.get("labels", labels)
            expected = {(a, "-" if label_order.index(a) < label_order.index(b) else "+"), (b, "+")}
            if actual == expected:
                site["knobs"].append({"index": int(_num(child[3])), "pair": [a, b],
                                      "build_seq": _build_seq, "site_seq": site["site_seq"]})
    return 0


def _active_settings(tree, settings):
    """Mirror native effective→actual mapping and skip absent ancestor subtrees."""
    active = {}
    def visit(node):
        if not isinstance(node, list) or not node:
            return
        tag = node[0]
        if tag == "mkKnob":
            subtree, knob, index = node[1:]
            index = int(_num(index))
            effective = int(_num(settings[index]))
            disc = knob[1]
            multiplicity = int(_num(unwrap_atom(disc[1])))
            default = int(_num(unwrap_atom(disc[3])))
            disallowed = {int(_num(unwrap_atom(d))) for d in _items(disc[4])}
            if not disallowed:
                actual = effective
            elif effective == 0 or multiplicity - len(disallowed - {default}) <= 1:
                actual = default
            else:
                options = [v for v in range(multiplicity) if v != default and v not in disallowed]
                actual = options[effective - 1]
            if actual == 0:
                return
            active[index] = actual
            if isinstance(subtree, list) and subtree[0] == "mkNullVex":
                for child in _items(subtree[1]):
                    visit(child)
            else:
                visit(subtree)
        elif tag == "mkTree":
            for child in _items(node[2]):
                visit(child)
        # Bare null vertices are absent, unless an active knob above unwraps them.
    visit(tree)
    return active


def tag_candidate(tree, rep, inst, deme_id):
    if not isinstance(inst, list) or inst[0] != "mkInst":
        return 0
    settings = _items(inst[1])
    rep_tree = rep[2] if isinstance(rep, list) and len(rep) > 2 else None
    rep_key = expr_to_str(rep_tree)
    build_ids = {d["build_seq"] for d in _draws if d.get("representation") == rep_key}
    active = _active_settings(rep_tree, settings) if build_ids else {}
    tags = []
    for draw in _draws:
        if draw["build_seq"] not in build_ids:
            continue
        for knob in draw["knobs"]:
            if knob["index"] in active:
                tags.append({**knob, "setting": active[knob["index"]],
                             "deme_id": _demeid(deme_id)})
    _candidate_pairs[_pid(expr_to_str(tree))] = tags
    return 0


def finish_build(tree):
    key = expr_to_str(tree)
    for draw in _draws:
        if draw["build_seq"] == _build_seq:
            draw["representation"] = key
    return 0



def current_generation():
    return _current_gen


def clear_members(generation):
    _gs(generation)["members"].clear()
    return 0


def _bridge_guard(function):
    """Do not let a Python failure become an unevaluated atom in MeTTa."""
    @functools.wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            _abort_run("bridge_failure", function=function.__name__, error=repr(exc))
    return guarded


# Every py-call entry uses the same failure boundary. Ingest handles semantic
# failures before this boundary; only broken runtime/config invariants abort.
for _entrypoint in (
    "new_run", "begin_gen", "add_member", "add_knob", "set_deme", "begin_merge",
    "add_merged_member", "set_merge_count", "add_cull_candidate", "set_selection",
    "set_deme_evals", "set_problem_spec", "get_total_evals", "get_hill_climb_max_evals",
    "set_run_param", "set_problem_spec_strategy", "emit_run_config", "flush_terminal",
    "enter_gen", "checkpoint_native", "restore_checkpoint", "call_rows",
    "install_row_weights", "weighted_sum", "complexity_coef", "selection_temperature",
    "call_exemplar", "begin_selection", "add_selection_candidate", "select_index",
    "selection_single", "call_retention", "retain_member", "flush_gen", "call_atom",
    "begin_build", "begin_combo_draw", "combo_guided", "weighted_combo_pick",
    "end_combo_draw", "register_pair_knobs", "tag_candidate", "finish_build",
    "current_generation", "clear_members"):
    globals()[_entrypoint] = _bridge_guard(globals()[_entrypoint])
