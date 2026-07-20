"""Slot-based UtilityResponse construction (stdlib-only; no pip in-container).

The inversion that makes constrained generation deterministic: the WRAPPER
enumerates the legal estimation universe for a generation — every program id,
atom label, evidence bucket, and combination set, all read from the emitted
state and run_config, all real — and the agent supplies nothing but VALUES
for those slots. A response assembled through this module cannot reference an
id that does not exist; `utility_schema.validate_utility_response` remains as
an invariant check (assemble() runs it and raises on failure), not a filter.

Three consumers:

  * the live-agent harness — build_slots() per generation; render the slots
    (with their provenance meta) into the prompt; hand the provider
    json_schema() as the structured-output/tool schema (additionalProperties
    false + closed enums = the model physically cannot invent a slot); pass
    the returned values to assemble() and write the doc.
  * mocks / scripted estimators — fill slots programmatically (the values
    are the only degrees of freedom, exactly like the live agent).
  * tests — llmoses/llmoses-tests/response_template_test.py pins the slot
    enumeration, assembly validity, and schema export.

Slot keys (stable, human-readable):
  exemplar:<pid>            utility in [0,1]
  cull:<pid>  cull:*        retention utility in [0,1] ('*' = newborn default)
  atom:<label>              global per-atom prior in [0,1]
  atomctx:<label>|<k>=<v>   single-axis contextual prior (observed buckets
                            only; k in polarity/parent_operator/depth_bucket)
  syn:<a>&<b>[&<c>]         combination synergy, labels sorted, in [0,1]
  rank:<pid>                comparator rank value (lower = better); the
                            assembler sorts rank slots into program_id_ordering
  lever:<axis>              feature_utility_levers.lever_weights axis in [0,1]
  aggregate_fn              enum: product | mean | geometric_mean | softmax
  ratio:direction           enum: increase | decrease | maintain
  ratio:magnitude           number >= 0 (emitted only with ratio:direction)
  sampling_temperature      number > 0 (omit = null)

Omitted slots mean "no opinion": the entry is simply not emitted, which the
mixing formula already treats as neutral. Unknown keys raise — by design.
"""

import itertools
import math

import utility_schema

_CTX_AXES = ("polarity", "parent_operator", "depth_bucket")


def _survivor_ids(state):
    """Ordered real program ids: post-merge members joined with resize_cull
    new entrants, restricted to survivors (mirrors the watcher's scoring
    join; ids only, plus penalized score meta where present)."""
    scores, order = {}, []
    for m in (state.get("metapopulation") or {}).get("members") or []:
        pid = m.get("program_id")
        if pid is None:
            continue
        if pid not in scores:
            order.append(pid)
        scores[pid] = (m.get("cscore") or {}).get("penalized_score")
    rc = (state.get("merge_summary") or {}).get("resize_cull") or {}
    for e in rc.get("new_entrants") or []:
        if isinstance(e, dict) and e.get("program_id") is not None:
            pid = e["program_id"]
            if pid not in scores:
                order.append(pid)
            scores[pid] = e.get("penalized_score")
    survivors = rc.get("survivors") or order
    kept = [pid for pid in order if pid in set(survivors)]
    return [(pid, scores.get(pid)) for pid in (kept or order)]


def _alphabet(run_config):
    block = (run_config or {}).get("atom_alphabet") or {}
    labels = [a.get("label") for a in block.get("atoms") or []
              if a.get("label") is not None]
    width = 3 if block.get("problem_type") == "strategy" else 2
    return block, labels, width


def build_slots(state, run_config):
    """Enumerate the legal estimation universe for one generation. Returns
    {slot_key: {"kind", "domain", "meta"}} — meta carries provenance the
    prompt can render (scores, evidence counts) but never affects validity."""
    slots = {}
    for pid, pen in _survivor_ids(state):
        meta = {"penalized_score": pen}
        slots[f"exemplar:{pid}"] = {"kind": "exemplar", "domain": "unit",
                                    "meta": meta}
        slots[f"cull:{pid}"] = {"kind": "culling", "domain": "unit",
                                "meta": meta}
        slots[f"rank:{pid}"] = {"kind": "comparator", "domain": "number",
                                "meta": meta}
    slots["cull:*"] = {"kind": "culling", "domain": "unit",
                       "meta": {"newborn_default": True}}

    _, labels, width = _alphabet(run_config)
    for label in labels:
        slots[f"atom:{label}"] = {"kind": "atom_prior", "domain": "unit",
                                  "meta": {}}
    # Contextual slots: only OBSERVED evidence buckets, marginalized to the
    # single axes the response context vocabulary names. Real by
    # construction — a bucket exists iff the walker saw that atom there.
    # Evidence rows carry prefixed alphabet KEYS ('feature:X1'); slots and
    # the response contract use bare labels — map through the alphabet.
    block, _, _ = _alphabet(run_config)
    key_to_label = {a.get("key"): a.get("label")
                    for a in block.get("atoms") or []}
    seen = {}
    for row in (state.get("atom_evidence") or {}).get("atom_appearances") or []:
        atom = key_to_label.get(row.get("atom"), row.get("atom"))
        if atom not in labels:
            continue
        for axis in _CTX_AXES:
            val = row.get(axis)
            if val in (None, ""):
                continue
            key = (atom, axis, str(val))
            seen[key] = seen.get(key, 0) + (row.get("count") or 0)
    for (atom, axis, val), count in sorted(seen.items()):
        slots[f"atomctx:{atom}|{axis}={val}"] = {
            "kind": "atom_prior_ctx", "domain": "unit",
            "meta": {"observed_count": count}}

    for combo in itertools.combinations(labels, width):
        slots["syn:" + "&".join(sorted(combo))] = {
            "kind": "synergy", "domain": "unit", "meta": {}}

    for axis in utility_schema.LEVER_WEIGHT_AXES:
        slots[f"lever:{axis}"] = {"kind": "lever_weight", "domain": "unit",
                                  "meta": {}}
    slots["aggregate_fn"] = {"kind": "aggregate_fn", "domain": "enum",
                             "enum": list(utility_schema.AGGREGATE_FNS),
                             "meta": {}}
    slots["ratio:direction"] = {"kind": "ratio", "domain": "enum",
                                "enum": list(utility_schema.RATIO_DIRECTIONS),
                                "meta": {}}
    slots["ratio:magnitude"] = {"kind": "ratio", "domain": "nonneg",
                                "meta": {}}
    slots["sampling_temperature"] = {"kind": "temperature", "domain": "pos",
                                     "meta": {}}
    return slots


def json_schema(slots):
    """Per-generation JSON Schema over the VALUES payload — the provider-side
    constrained-decoding artifact (Anthropic tool input_schema, OpenAI
    structured outputs, a Pydantic model, or any grammar decoder consume it
    unchanged). additionalProperties false + closed enums: the model cannot
    reference anything the wrapper did not enumerate."""
    props = {}
    for key, spec in slots.items():
        if spec["domain"] == "unit":
            props[key] = {"type": "number", "minimum": 0.0, "maximum": 1.0}
        elif spec["domain"] == "nonneg":
            props[key] = {"type": "number", "minimum": 0.0}
        elif spec["domain"] == "pos":
            props[key] = {"type": "number", "exclusiveMinimum": 0.0}
        elif spec["domain"] == "number":
            props[key] = {"type": "number"}
        elif spec["domain"] == "enum":
            props[key] = {"enum": list(spec["enum"])}
    return {"type": "object", "properties": props,
            "additionalProperties": False}


def _num(key, v, lo=None, lo_open=False, hi=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)) \
            or not math.isfinite(v):
        raise ValueError(f"{key}: value must be a finite number")
    if lo is not None and (v <= lo if lo_open else v < lo):
        raise ValueError(f"{key}: value out of domain")
    if hi is not None and v > hi:
        raise ValueError(f"{key}: value out of domain")
    return float(v)


def _unit(key, v):
    return _num(key, v, 0.0, hi=1.0)


def assemble(slots, values, run_config=None, decline=False):
    """Deterministically build a contract-valid UtilityResponse from slot
    values. Unknown keys, out-of-domain values, and enum violations raise
    (nothing is coerced or dropped — the caller's generation layer should
    have made them impossible). The finished document is asserted against
    validate_utility_response before it is returned."""
    doc = {"pass": bool(decline), "sampling_temperature": None,
           "exemplar_utilities": [], "atom_utility_prior": [],
           "combination_synergy": [], "feature_utility_levers": None,
           "culling_utilities": [], "complexity_ratio_delta": None,
           "comparator_bias": None}
    ranks, lever_weights, aggregate_fn = [], {}, None
    ratio_dir, ratio_mag = None, None
    for key in sorted(values):
        if key not in slots:
            raise KeyError(f"unknown slot: {key!r}")
        spec, v = slots[key], values[key]
        kind = spec["kind"]
        if kind == "exemplar":
            doc["exemplar_utilities"].append(
                {"program_id": key.split(":", 1)[1],
                 "utility": _unit(key, v)})
        elif kind == "culling":
            doc["culling_utilities"].append(
                {"program_id": key.split(":", 1)[1],
                 "retention_utility": _unit(key, v)})
        elif kind == "comparator":
            ranks.append((_num(key, v), key.split(":", 1)[1]))
        elif kind == "atom_prior":
            doc["atom_utility_prior"].append(
                {"atom": key.split(":", 1)[1], "utility": _unit(key, v)})
        elif kind == "atom_prior_ctx":
            body = key.split(":", 1)[1]
            atom, cond = body.split("|", 1)
            axis, val = cond.split("=", 1)
            doc["atom_utility_prior"].append(
                {"atom": atom, "utility": _unit(key, v),
                 "context": {axis: val}})
        elif kind == "synergy":
            doc["combination_synergy"].append(
                {"atoms": key.split(":", 1)[1].split("&"),
                 "utility": _unit(key, v)})
        elif kind == "lever_weight":
            lever_weights[key.split(":", 1)[1]] = _unit(key, v)
        elif kind == "aggregate_fn":
            if v not in spec["enum"]:
                raise ValueError(f"{key}: must be one of {spec['enum']}")
            aggregate_fn = v
        elif kind == "ratio":
            if key == "ratio:direction":
                if v not in spec["enum"]:
                    raise ValueError(f"{key}: must be one of {spec['enum']}")
                ratio_dir = v
            else:
                ratio_mag = _num(key, v, 0.0)
        elif kind == "temperature":
            doc["sampling_temperature"] = _num(key, v, 0.0, lo_open=True)
    if ranks:
        doc["comparator_bias"] = {
            "program_id_ordering": [pid for _, pid in sorted(ranks)]}
    if lever_weights or aggregate_fn:
        doc["feature_utility_levers"] = {
            "aggregate_fn": aggregate_fn or "product",
            "lever_weights": lever_weights}
    if ratio_dir is not None:
        doc["complexity_ratio_delta"] = {"direction": ratio_dir,
                                         "magnitude": ratio_mag or 0.0}
    elif ratio_mag is not None:
        raise ValueError("ratio:magnitude supplied without ratio:direction")

    alphabet = (run_config or {}).get("atom_alphabet")
    ok, errs = utility_schema.validate_utility_response(doc, alphabet)
    if not ok:
        # Structurally unreachable when slots came from build_slots; if it
        # fires, the template and the contract have diverged — fail loudly.
        raise AssertionError(f"assembled response failed validation: {errs}")
    return doc
