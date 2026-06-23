"""Atom evidence: clause-walking over resolved post-merge candidate trees.

This keeps sampling evidence out of the MeTTa knob-building hot path. The builder
owns the run-scoped state (problem spec, alphabet map, cumulative counter) and
passes it in; everything here is otherwise a pure function of the candidate ASTs.

Two entry points:
  build_atom_alphabet(problem_spec, ptype) -> (alphabet_block, alpha_map)
  build_atom_evidence(members, g, ptype, gen_best, alpha_map, cumulative,
                      version, run_seq) -> (evidence_block, lossless_block_or_None)
"""
import os

from boundary import _flat

# One problem_type-keyed config drives THREE coupled choices so they can't
# desync: the clause-op set, the ordered flag (which governs both dedupe rule
# and key canonicalization), and whether contradictions are meaningful.
#   logical  : AND/OR commutative -> set-dedupe, sorted keys, contradictions real
#   strategy : PRIORITIZED-OR ordered -> order-preserving dedupe, preserved keys,
#              no contradiction concept (no negation in the move algebra)
_PROBLEM_CONFIG = {
    "logical":  {"ops": {"AND", "OR"},        "ordered": False, "contradiction": True},
    "strategy": {"ops": {"PRIORITIZED-OR"},   "ordered": True,  "contradiction": False},
}
_DEFAULT_CONFIG = {"ops": {"AND", "OR"}, "ordered": False, "contradiction": True}

# Lossless debug: when LLMOSES_ATOM_LOSSLESS is truthy, also write the raw
# per-event appearance/cooccurrence lists to a SEPARATE side-file per gen.
_ATOM_LOSSLESS = os.environ.get("LLMOSES_ATOM_LOSSLESS", "").strip().lower() in (
    "1", "true", "yes", "on")


def build_atom_alphabet(problem_spec, ptype):
    """Resolve the static action-space alphabet from problem_spec.
    Strategy -> moves (prefix 'move'); logical/default -> input_labels (prefix
    'feature'). Returns (alphabet_block, alpha_map) where alpha_map is
    label -> {index, key} for the walker. Returns (None, {}) when no spec."""
    if not isinstance(problem_spec, dict):
        return None, {}
    if ptype == "strategy":
        labels = problem_spec.get("moves") or []
        prefix = "move"
    else:
        labels = problem_spec.get("input_labels") or []
        prefix = "feature"
    atoms, alpha_map = [], {}
    for i, lbl in enumerate(labels):
        label = _flat(lbl)
        key = f"{prefix}:{label}"
        atoms.append({"index": i, "key": key, "label": label})
        alpha_map[label] = {"index": i, "key": key}
    return {"problem_type": ptype, "prefix": prefix, "atoms": atoms}, alpha_map


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
    distinct hosts sitting at the generation's best_penalized_score."""
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
    lossless raw lists). See build_atom_evidence for accumulator shapes."""
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


def build_atom_evidence(members, g, ptype, gen_best, alpha_map, cumulative,
                        version, run_seq):
    """Drive the normalize -> aggregate pass over the retained metapop members
    for generation g, update the run-scoped cumulative accumulator (mutated in
    place), and finalize rollup records. Returns (evidence_block, lossless|None)."""
    cfg = _PROBLEM_CONFIG.get(ptype, _DEFAULT_CONFIG)
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
        rec = cumulative.get(key)
        if rec is None:
            cumulative[key] = {"appearances_total": cnt,
                               "first_seen_gen": g, "last_seen_gen": g}
        else:
            rec["appearances_total"] += cnt
            rec["last_seen_gen"] = g

    evidence = {
        "atom_appearances": appearances,
        "realized_cooccurrences": cooccurrences,
        "atom_cumulative": {k: dict(v) for k, v in cumulative.items()},
        "degenerate_summary": acc["degen"],
    }
    lossless = None
    if _ATOM_LOSSLESS:
        lossless = {"schema_version": version, "run_seq": run_seq, "generation": g,
                    "atom_appearances": acc["raw_app"],
                    "realized_cooccurrences": acc["raw_co"]}
    return evidence, lossless
