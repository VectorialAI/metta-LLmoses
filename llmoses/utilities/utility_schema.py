"""Closed call-specific response contracts; clamp at ingest, salvage entries."""
import copy
import conditional_policy
import math
from lever_policy import CALL_LEVERS

STATUS_CODES = (200, 204, 422, 500, 503, 504)
CONTINUE_STATUSES = (200, 204, 422, 500)
CONTEXT_STRATEGIES = ("full_history", "rolling_summary", "per_generation", "retrieval")
OUTCOME_KEYS = ("attempts", "retried", "salvage", "coverage", "error_class",
                "detail", "protocol_version", "context")
ENVELOPE = {"run_seq", "generation", "call", "pass", "status", "outcome"}
FIELDS = {1: "row_weights", 2: "exemplar_utilities", 3: "policy", 4: "retention_utilities"}
TEMPERATURES = {1: "T_rowweight", 2: "T_exemplar", 3: "T_atom", 4: "T_retention"}


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def default_status(doc):
    return 204 if doc.get("pass") else 200


def response_field(call, config):
    return FIELDS[call]


def neutral(state, status=204, outcome=None):
    return {"run_seq": state["run_seq"], "generation": state["generation"],
            "call": state["call"], "pass": True, "status": status, "outcome": outcome or {}}


def _outcome_errors(outcome):
    if not isinstance(outcome, dict) or set(outcome) - set(OUTCOME_KEYS):
        return ["outcome: invalid object or unknown fields"]
    errors = []
    for key in ("detail", "error_class", "protocol_version"):
        if key in outcome and not isinstance(outcome[key], str):
            errors.append(f"outcome.{key}: must be a string")
    if "attempts" in outcome and (type(outcome["attempts"]) is not int or outcome["attempts"] < 1):
        errors.append("outcome.attempts: must be a positive integer")
    if "retried" in outcome and not isinstance(outcome["retried"], bool):
        errors.append("outcome.retried: must be boolean")
    for key in ("salvage", "coverage"):
        if key not in outcome:
            continue
        value = outcome[key]
        allowed = {"requested", "survived"} if key == "salvage" else {"mode", "requested", "supplied"}
        if not isinstance(value, dict) or set(value) - allowed:
            errors.append(f"outcome.{key}: invalid object")
            continue
        for field, number in value.items():
            if field == "mode":
                if number not in ("full", "sparse"):
                    errors.append("outcome.coverage.mode: must be full or sparse")
            elif type(number) is not int or number < 0:
                errors.append(f"outcome.{key}.{field}: must be nonnegative integer")
    if "context" in outcome:
        ctx = outcome["context"]
        if not isinstance(ctx, dict) or set(ctx) - {"strategy", "chars", "compressed", "dropped", "tokens"}:
            errors.append("outcome.context: invalid object")
        else:
            if "strategy" in ctx and ctx["strategy"] not in CONTEXT_STRATEGIES:
                errors.append("outcome.context.strategy: unsupported")
            for key in ("chars", "tokens"):
                if key in ctx and (type(ctx[key]) is not int or ctx[key] < 0):
                    errors.append(f"outcome.context.{key}: must be nonnegative integer")
            if "compressed" in ctx and not isinstance(ctx["compressed"], bool):
                errors.append("outcome.context.compressed: must be boolean")
            if "dropped" in ctx and not isinstance(ctx["dropped"], list):
                errors.append("outcome.context.dropped: must be a list")
    return errors


def _entry(entry, field, state):
    if not isinstance(entry, dict):
        raise ValueError("entry must be an object")
    if field == "row_weights":
        if set(entry) != {"row", "weight"} or type(entry["row"]) is not int:
            raise ValueError("row entry requires integer row and weight")
        key, value_key = entry["row"], "weight"
        if key not in {r["row"] for r in state.get("rows", [])}:
            raise ValueError("row was not offered")
    elif field in ("exemplar_utilities", "retention_utilities"):
        if set(entry) != {"program_id", "offset"} or not isinstance(entry["program_id"], str):
            raise ValueError("member entry requires program_id and offset")
        key, value_key = entry["program_id"], "offset"
        if key not in {m["program_id"] for m in state.get("candidates", [])}:
            raise ValueError("program_id was not offered")
    if not _is_num(entry.get(value_key)):
        raise ValueError(f"{value_key} must be finite")
    return key, value_key


def ingest(doc, state, config):
    """Envelope/mode violations reject the call; malformed entries are salvaged."""
    report = {"errors": [], "dropped": [], "clamped": [], "requested": 0, "survived": 0}
    if not isinstance(doc, dict):
        report["errors"].append("response must be an object")
        return None, report
    call = state["call"]
    field, temp = response_field(call, config), TEMPERATURES[call]
    errors = report["errors"]
    if set(doc) - (ENVELOPE | {field, temp}):
        errors.append("unknown fields or content for inactive call/mode")
    for key in ("run_seq", "generation", "call"):
        if type(doc.get(key)) is not int or doc[key] != state[key]:
            errors.append(f"{key}: response fence mismatch")
    if not isinstance(doc.get("pass"), bool):
        errors.append("pass must be boolean")
    status = doc.get("status")
    if type(status) is not int or status not in STATUS_CODES:
        errors.append("unsupported status")
    elif (status == 200) == doc.get("pass"):
        errors.append("status and pass disagree")
    errors.extend(_outcome_errors(doc.get("outcome", {})))
    spec = config["levers"][CALL_LEVERS[call]]
    if temp in doc and (not spec["T_commandable"] or not _is_num(doc[temp])):
        errors.append(f"{temp}: not commandable or nonfinite")
    if doc.get("pass") and (doc.get(field) or temp in doc):
        errors.append("decline must not contain guidance")
    if call != 3 and field in doc and not isinstance(doc[field], list):
        errors.append(f"{field} must be a list")
    if errors:
        return None, report
    clean = copy.deepcopy(doc)
    if temp in clean:
        low, high = spec["T_bounds"]
        clipped = min(high, max(low, clean[temp]))
        if clipped != clean[temp]:
            report["clamped"].append(temp)
        clean[temp] = clipped
    if call == 3:
        try:
            alphabet = {a["label"] for a in state["alphabet"]["atoms"]}
            clean["policy"], clamped = conditional_policy.validate(doc.get("policy", {}), alphabet, config)
            report["clamped"].extend(clamped)
            report["requested"] = report["survived"] = len(clean["policy"]["base"]) + sum(len(r["adjust"]) for r in clean["policy"]["rules"])
            if doc["pass"]:
                clean.pop("policy", None)
            return clean, report
        except (KeyError, TypeError, ValueError) as exc:
            report["errors"].append(str(exc))
            return None, report
    seen, entries = set(), []
    for i, entry in enumerate(doc.get(field, [])):
        report["requested"] += 1
        try:
            identity, value_key = _entry(entry, field, state)
            if identity in seen:
                raise ValueError("duplicate identity")
            seen.add(identity)
            entry = dict(entry)
            bound = spec["delta_max"] if call in (2, 4) else config["utility_max"]
            low = -bound if call in (2, 4) else 0.0
            clipped = min(bound, max(low, entry[value_key]))
            if clipped != entry[value_key]:
                report["clamped"].append(f"{field}[{i}].{value_key}")
            entry[value_key] = clipped
            entries.append(entry)
        except ValueError as exc:
            report["dropped"].append({"field": field, "index": i, "reason": str(exc)})
    if field in clean:
        clean[field] = entries
    report["survived"] = len(entries)
    return clean, report


def validate_utility_response(doc, atom_alphabet=None, *, state=None, run_config=None):
    if state is None or run_config is None:
        return False, ["call state and experiment config are required"]
    clean, report = ingest(doc, state, run_config.get("experiment", run_config))
    errors = report["errors"] + [d["reason"] for d in report["dropped"]]
    return clean is not None and not errors, errors


def salvage_utility_response(doc, atom_alphabet=None, *, state=None, run_config=None):
    if state is None or run_config is None:
        return None, {"errors": ["call state and config required"], "dropped": []}
    return ingest(doc, state, run_config.get("experiment", run_config))


def has_guidance(doc):
    return not doc.get("pass", True) and any(doc.get(k) for k in
        ("row_weights", "exemplar_utilities", "retention_utilities", "policy", *TEMPERATURES.values()))
