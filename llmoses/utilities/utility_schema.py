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

RESPONSE_KEYS = ("pass", "sampling_temperature", "exemplar_utilities",
                 "atom_utility_prior", "combination_synergy",
                 "feature_utility_levers", "culling_utilities",
                 "complexity_ratio_delta", "comparator_bias")
AGGREGATE_FNS = ("product", "mean", "geometric_mean", "softmax")
LEVER_WEIGHT_AXES = ("polarity", "clause_type", "parent_operator",
                     "tree_depth", "selected_exemplar", "combination_synergy",
                     "novelty")
# context key -> closed vocabulary (None = any non-empty string)
CONTEXT_KEYS = {"polarity": ("+", "-"),
                "clause_type": None, "parent_operator": None,
                "depth_bucket": ("shallow", "mid", "deep"),
                "exemplar_id": None}
RATIO_DIRECTIONS = ("increase", "decrease", "maintain")


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


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


def validate_utility_response(doc):
    """Return (ok, errors). errors is a list of human-readable strings; the
    document is valid iff it is empty."""
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
