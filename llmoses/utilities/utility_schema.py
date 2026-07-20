"""Strict UtilityResponse validation (stdlib-only; the container has no pip).

Single executable source of truth for the UtilityResponse contract described
in llmoses/skills/UTILITY_RESPONSE.md. Consumers:

  * llmoses_watcher.py — every mock UtilityResponse is validated before it is
    written; an invalid mock is a defect, reported loudly and degraded to the
    neutral stub so the handshake never breaks.
  * a live agent harness — the constrained-decoding / retry gate: reject the
    provider output and re-ask rather than write a malformed response. This
    is where pre-D-030 shapes (bare-string ratio deltas, pair_utilities) get
    caught at the source instead of dropping at ingest.
  * state_builder._ingest_utilities — diagnostic mode only: validation errors
    are logged in the utility_ingest audit row, never enforced (a malformed
    response degrades to whatever normalizes, and the run proceeds natively
    where it does not — the run must never deadlock on a bad responder).
"""

import math

RESPONSE_KEYS = ("pass", "sampling_temperature", "exemplar_utilities",
                 "atom_utility_prior", "combination_synergy",
                 "feature_utility_levers", "culling_utilities",
                 "complexity_ratio_delta", "comparator_bias")
AGGREGATE_FNS = ("product", "mean", "geometric_mean", "softmax")
LEVER_WEIGHT_AXES = ("polarity", "clause_type", "parent_operator",
                     "tree_depth", "selected_exemplar", "combination_synergy",
                     "novelty")
CLAUSE_OPS = ("AND", "OR", "PRIORITIZED-OR")
# context key -> closed vocabulary (None = any non-empty string)
CONTEXT_KEYS = {"polarity": ("+", "-"),
                "clause_type": CLAUSE_OPS, "parent_operator": CLAUSE_OPS,
                "depth_bucket": ("shallow", "mid", "deep"),
                "exemplar_id": None}
RATIO_DIRECTIONS = ("increase", "decrease", "maintain")


def _is_num(x):
    return (isinstance(x, (int, float)) and not isinstance(x, bool)
            and math.isfinite(x))


def _is_unit(x):
    return _is_num(x) and 0.0 <= float(x) <= 1.0


def _check_entries(errs, doc, field, checker):
    val = doc.get(field)
    if not isinstance(val, list):
        errs.append(f"{field}: must be a list")
        return
    for i, e in enumerate(val):
        if not isinstance(e, dict):
            errs.append(f"{field}[{i}]: must be an object")
            continue
        checker(errs, f"{field}[{i}]", e)


def _check_exemplar(errs, at, e):
    if set(e) != {"program_id", "utility"}:
        errs.append(f"{at}: keys must be exactly program_id, utility")
    if not isinstance(e.get("program_id"), str):
        errs.append(f"{at}.program_id: must be a string")
    if not _is_unit(e.get("utility")):
        errs.append(f"{at}.utility: must be a number in [0, 1]")


def _check_atom_prior(errs, at, e):
    if not set(e) <= {"atom", "utility", "context"} or not {"atom", "utility"} <= set(e):
        errs.append(f"{at}: keys must be atom, utility and optionally context")
    if not isinstance(e.get("atom"), str):
        errs.append(f"{at}.atom: must be a string")
    if not _is_unit(e.get("utility")):
        errs.append(f"{at}.utility: must be a number in [0, 1]")
    ctx = e.get("context")
    if ctx is None:
        return
    if not isinstance(ctx, dict) or not ctx:
        errs.append(f"{at}.context: must be a non-empty object when present")
        return
    for k, v in ctx.items():
        if k not in CONTEXT_KEYS:
            errs.append(f"{at}.context.{k}: unknown context key")
        elif CONTEXT_KEYS[k] is not None and v not in CONTEXT_KEYS[k]:
            errs.append(f"{at}.context.{k}: must be one of {CONTEXT_KEYS[k]}")
        elif CONTEXT_KEYS[k] is None and (not isinstance(v, str) or not v):
            errs.append(f"{at}.context.{k}: must be a non-empty string")


def _check_synergy(errs, at, e):
    if set(e) != {"atoms", "utility"}:
        errs.append(f"{at}: keys must be exactly atoms, utility")
    atoms = e.get("atoms")
    if (not isinstance(atoms, list) or not 2 <= len(atoms) <= 3
            or not all(isinstance(a, str) for a in atoms)):
        errs.append(f"{at}.atoms: must be a list of 2-3 atom label strings")
    if not _is_unit(e.get("utility")):
        errs.append(f"{at}.utility: must be a number in [0, 1]")


def _check_culling(errs, at, e):
    keys = set(e)
    if not isinstance(e.get("program_id"), str):
        errs.append(f"{at}.program_id: must be a string ('*' = newborn default)")
    if "retain_utility" in keys:
        errs.append(f"{at}: retain_utility is a pre-contract alias; "
                    "use retention_utility")
        return
    util_keys = keys & {"retention_utility", "cull_utility"}
    if len(util_keys) != 1 or keys - {"program_id", "retention_utility",
                                      "cull_utility"}:
        errs.append(f"{at}: keys must be program_id plus exactly one of "
                    "retention_utility, cull_utility")
        return
    if not _is_unit(e.get(next(iter(util_keys)))):
        errs.append(f"{at}.{next(iter(util_keys))}: must be a number in [0, 1]")


def _check_duplicates(errs, doc):
    """Entries that would silently collapse at ingest (dict construction,
    last value wins) are contract violations at the source."""
    seen = set()
    for i, e in enumerate(doc.get("atom_utility_prior") or []):
        if not isinstance(e, dict):
            continue
        ctx = e.get("context")
        sig = (e.get("atom"),
               frozenset(ctx.items()) if isinstance(ctx, dict) else None)
        if sig in seen:
            errs.append(f"atom_utility_prior[{i}]: duplicate entry for atom "
                        f"{e.get('atom')!r} with identical context")
        seen.add(sig)
    seen = set()
    for i, e in enumerate(doc.get("combination_synergy") or []):
        if not isinstance(e, dict) or not isinstance(e.get("atoms"), list):
            continue
        atoms = [a for a in e["atoms"] if isinstance(a, str)]
        if len(set(atoms)) != len(atoms):
            errs.append(f"combination_synergy[{i}].atoms: atoms must be "
                        "distinct (sets are unordered)")
            continue
        sig = frozenset(atoms)
        if sig in seen:
            errs.append(f"combination_synergy[{i}]: duplicate atom set "
                        f"{sorted(sig)}")
        seen.add(sig)
    for field in ("exemplar_utilities", "culling_utilities"):
        seen = set()
        for i, e in enumerate(doc.get(field) or []):
            if not isinstance(e, dict):
                continue
            pid = e.get("program_id")
            if pid in seen:
                errs.append(f"{field}[{i}]: duplicate program_id {pid!r}")
            seen.add(pid)


def _check_alphabet(errs, doc, atom_alphabet):
    """Run-context checks (optional): atom labels must exist in the run's
    alphabet and synergy sets must be exactly the problem width — a response
    that validates but can never match a draw-site label is the silent-drop
    failure mode this gate exists to prevent."""
    labels = {a.get("label") for a in atom_alphabet.get("atoms") or []}
    width = 3 if atom_alphabet.get("problem_type") == "strategy" else 2
    for i, e in enumerate(doc.get("atom_utility_prior") or []):
        if isinstance(e, dict) and isinstance(e.get("atom"), str) \
                and e["atom"] not in labels:
            errs.append(f"atom_utility_prior[{i}].atom: {e['atom']!r} is not "
                        "in the run's atom_alphabet")
    for i, e in enumerate(doc.get("combination_synergy") or []):
        if not isinstance(e, dict) or not isinstance(e.get("atoms"), list):
            continue
        atoms = e["atoms"]
        if len(atoms) != width:
            errs.append(f"combination_synergy[{i}].atoms: width must be "
                        f"exactly {width} for this problem type")
        for a in atoms:
            if isinstance(a, str) and a not in labels:
                errs.append(f"combination_synergy[{i}].atoms: {a!r} is not "
                            "in the run's atom_alphabet")


_LIST_FIELDS = ("exemplar_utilities", "atom_utility_prior",
                "combination_synergy", "culling_utilities")
_VALUE_FIELDS = ("sampling_temperature", "feature_utility_levers",
                 "complexity_ratio_delta", "comparator_bias")


def _empty_doc(decline):
    return {"pass": bool(decline), "sampling_temperature": None,
            "exemplar_utilities": [], "atom_utility_prior": [],
            "combination_synergy": [], "feature_utility_levers": None,
            "culling_utilities": [], "complexity_ratio_delta": None,
            "comparator_bias": None}


def salvage_utility_response(doc, atom_alphabet=None):
    """Component-level salvage of an invalid UtilityResponse: keep every
    entry/field that validates in isolation (duplicate semantics preserved by
    accumulating accepted entries into each probe), drop and report the rest.
    Returns (salvaged_doc, report) where report maps field -> {"dropped": n,
    "first_error": str}; salvaged_doc is always contract-valid, or None when
    doc is not an object at all.

    This is the post-retry fallback for a response WRITER (watcher today, the
    live-agent harness after its retry budget): one bad entry must not cost a
    generation of otherwise-good guidance. It is deliberately NOT used at
    ingest — what reaches MOSES is fully valid or accounted for here."""
    if not isinstance(doc, dict):
        return None, {"document": {"dropped": 1,
                                   "first_error": "not a JSON object"}}
    decline = doc.get("pass") is True
    out = _empty_doc(decline)
    report = {}
    if decline:
        return out, report
    for k in doc:
        if k not in RESPONSE_KEYS:
            report[k] = {"dropped": 1, "first_error": "unknown top-level field"}
    for field in _LIST_FIELDS:
        val = doc.get(field)
        if not isinstance(val, list):
            if val not in (None, []):
                report[field] = {"dropped": 1, "first_error": "must be a list"}
            continue
        kept, dropped, first_err = [], 0, None
        for e in val:
            probe = _empty_doc(False)
            probe[field] = kept + [e]
            ok, errs = validate_utility_response(probe, atom_alphabet)
            if ok:
                kept.append(e)
            else:
                dropped += 1
                first_err = first_err or (errs[0] if errs else "invalid")
        out[field] = kept
        if dropped:
            report[field] = {"dropped": dropped, "first_error": first_err}
    for field in _VALUE_FIELDS:
        val = doc.get(field)
        if val is None:
            continue
        probe = _empty_doc(False)
        probe[field] = val
        ok, errs = validate_utility_response(probe, atom_alphabet)
        if ok:
            out[field] = val
        else:
            report[field] = {"dropped": 1,
                             "first_error": errs[0] if errs else "invalid"}
    ok, errs = validate_utility_response(out, atom_alphabet)
    if not ok:  # structurally unreachable; fail closed to a valid decline
        return _empty_doc(True), {"document": {"dropped": 1,
                                               "first_error": str(errs[:1])}}
    return out, report


def has_guidance(doc):
    """True when a non-decline document carries at least one estimation."""
    if not isinstance(doc, dict) or doc.get("pass") is True:
        return False
    return any(doc.get(f) for f in _LIST_FIELDS) or any(
        doc.get(f) is not None for f in ("complexity_ratio_delta",
                                         "comparator_bias"))


def validate_utility_response(doc, atom_alphabet=None):
    """Return (ok, errors). errors is a list of human-readable strings; the
    document is valid iff it is empty. atom_alphabet (optional) is the
    run_config.json atom_alphabet block; when supplied, atom labels and
    synergy widths are checked against the live run — the form a live agent's
    retry gate must use."""
    if not isinstance(doc, dict):
        return False, ["UtilityResponse must be a JSON object"]
    errs = []
    for k in RESPONSE_KEYS:
        if k not in doc:
            errs.append(f"missing required field: {k}")
    for k in doc:
        if k not in RESPONSE_KEYS:
            errs.append(f"unknown top-level field: {k}")
    if errs:
        return False, errs

    if not isinstance(doc["pass"], bool):
        errs.append("pass: must be a boolean")
    temp = doc["sampling_temperature"]
    if temp is not None and not (_is_num(temp) and float(temp) > 0):
        errs.append("sampling_temperature: must be null or a number > 0")

    _check_entries(errs, doc, "exemplar_utilities", _check_exemplar)
    _check_entries(errs, doc, "atom_utility_prior", _check_atom_prior)
    _check_entries(errs, doc, "combination_synergy", _check_synergy)
    _check_entries(errs, doc, "culling_utilities", _check_culling)
    _check_duplicates(errs, doc)
    if atom_alphabet is not None and isinstance(atom_alphabet, dict):
        _check_alphabet(errs, doc, atom_alphabet)

    levers = doc["feature_utility_levers"]
    if levers is not None:
        if not isinstance(levers, dict):
            errs.append("feature_utility_levers: must be null or an object")
        else:
            if set(levers) - {"aggregate_fn", "lever_weights"}:
                errs.append("feature_utility_levers: keys must be "
                            "aggregate_fn and/or lever_weights")
            fn = levers.get("aggregate_fn")
            if fn is not None and fn not in AGGREGATE_FNS:
                errs.append(f"feature_utility_levers.aggregate_fn: must be "
                            f"one of {AGGREGATE_FNS}")
            lw = levers.get("lever_weights")
            if lw is not None:
                if not isinstance(lw, dict):
                    errs.append("feature_utility_levers.lever_weights: "
                                "must be an object")
                else:
                    for k, v in lw.items():
                        if k not in LEVER_WEIGHT_AXES:
                            errs.append(f"lever_weights.{k}: unknown axis")
                        elif not _is_unit(v):
                            errs.append(f"lever_weights.{k}: must be a "
                                        "number in [0, 1]")

    delta = doc["complexity_ratio_delta"]
    if delta is not None:
        if not isinstance(delta, dict):
            errs.append("complexity_ratio_delta: must be null or "
                        "{direction, magnitude} — a bare direction string "
                        "is a pre-D-030 shape and is not accepted")
        else:
            if set(delta) != {"direction", "magnitude"}:
                errs.append("complexity_ratio_delta: keys must be exactly "
                            "direction, magnitude")
            if delta.get("direction") not in RATIO_DIRECTIONS:
                errs.append(f"complexity_ratio_delta.direction: must be one "
                            f"of {RATIO_DIRECTIONS}")
            mag = delta.get("magnitude")
            if not (_is_num(mag) and float(mag) >= 0):
                errs.append("complexity_ratio_delta.magnitude: must be a "
                            "number >= 0")

    cb = doc["comparator_bias"]
    if cb is not None:
        if not isinstance(cb, dict) or set(cb) != {"program_id_ordering"}:
            errs.append("comparator_bias: must be null or "
                        "{program_id_ordering: [...]}")
        elif (not isinstance(cb["program_id_ordering"], list) or
              not all(isinstance(p, str) for p in cb["program_id_ordering"])):
            errs.append("comparator_bias.program_id_ordering: must be a "
                        "list of program_id strings")

    return not errs, errs
