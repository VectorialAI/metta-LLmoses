"""Real per-call slots: the agent supplies values, never invents identities."""
import json
import conditional_policy
import math
import utility_schema
from lever_policy import CALL_LEVERS


class Slots(dict):
    def __init__(self, state, config):
        super().__init__()
        self.state, self.config = state, config


def build_slots(state, run_config):
    config = run_config.get("experiment", run_config)
    slots = Slots(state, config)
    call = state["call"]
    field = utility_schema.response_field(call, config)
    if call == 1:
        entries = [(f"row:{r['row']}", {"row": r["row"]}, "weight", r) for r in state["rows"]]
    elif call in (2, 4):
        entries = [(f"member:{m['program_id']}", {"program_id": m["program_id"]}, "offset", m)
                   for m in state["candidates"]]
    else:
        alphabet = {a["label"] for a in state["alphabet"]["atoms"]}
        slots["policy"] = {"kind": "policy", "domain": "policy", "meta": {},
                           "schema": conditional_policy.json_schema(alphabet, config)}
        entries = []
    for key, identity, value_key, meta in entries:
        slots[key] = {"kind": field, "domain": "offset" if call in (2, 4) else "multiplier",
                      "minimum": -config["levers"][CALL_LEVERS[call]]["delta_max"] if call in (2, 4) else 0.0,
                      "maximum": config["levers"][CALL_LEVERS[call]]["delta_max"] if call in (2, 4) else config["utility_max"], "identity": identity,
                      "value_key": value_key, "meta": meta}
    spec = config["levers"][CALL_LEVERS[call]]
    if spec["T_commandable"]:
        slots[utility_schema.TEMPERATURES[call]] = {
            "kind": "temperature", "domain": "temperature",
            "minimum": spec["T_bounds"][0], "maximum": spec["T_bounds"][1], "meta": {}}
    return slots


def json_schema(slots):
    return {"type": "object", "additionalProperties": False,
            "properties": {key: spec["schema"] if spec["kind"] == "policy" else
                           {"type": "number", "minimum": spec["minimum"],
                            "maximum": spec["maximum"]} for key, spec in slots.items()}}


def assemble(slots, values, run_config=None, decline=False, status=None, outcome=None):
    if not isinstance(values, dict) or set(values) - set(slots):
        raise ValueError("unknown slots or non-object values")
    doc = utility_schema.neutral(slots.state, status or (204 if decline else 200), outcome)
    doc["pass"] = bool(decline)
    if decline and values:
        raise ValueError("decline cannot contain values")
    for key, value in values.items():
        spec = slots[key]
        if spec["kind"] == "policy":
            doc["policy"] = value
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key}: value must be finite")
        if spec["kind"] == "temperature":
            doc[key] = value
        else:
            doc.setdefault(spec["kind"], []).append({**spec["identity"], spec["value_key"]: value})
    clean, report = utility_schema.ingest(doc, slots.state, slots.config)
    if clean is None or report["dropped"]:
        raise ValueError(str(report))
    return clean
