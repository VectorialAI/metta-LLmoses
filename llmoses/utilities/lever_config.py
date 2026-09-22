"""Experiment-owned M2 configuration, validated before the first generation."""

import json
import math
import os

from lever_policy import CALL_LEVERS


def _number(value, name, lo, hi=math.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name} must be finite in [{lo}, {hi}]")
    return value


def load(path=None):
    retired = [key for key in os.environ if key == "LLMOSES_APPLY_LEVERS"
               or key.startswith("LLMOSES_LEVER_WEIGHT_")
               or key in ("LLMOSES_UTILITY_POLICY", "LLMOSES_LAMBDA")]
    if retired:
        raise ValueError(f"retired experiment controls {sorted(retired)}; use LLMOSES_CONFIG")
    path = path or os.environ.get("LLMOSES_CONFIG")
    source = {}
    if path:
        with open(path, encoding="utf-8") as fh:
            source = json.load(fh)
    if not isinstance(source, dict):
        raise ValueError("LLMOSES_CONFIG must contain an object")
    allowed = {"selection_temperature", "utility_max", "context_radius", "rule_budget", "levers",
               "retention", "complexity_coef", "context_docs"}
    if set(source) - allowed:
        raise ValueError(f"unknown experiment controls: {sorted(set(source) - allowed)}")
    selection = source.get("selection_temperature")
    if selection is None and "LLMOSES_SELECTION_TEMPERATURE" in os.environ:
        selection = float(os.environ["LLMOSES_SELECTION_TEMPERATURE"])
    if selection is None:
        raise ValueError("LLMOSES requires an explicit selection_temperature "
                         "in LLMOSES_CONFIG or LLMOSES_SELECTION_TEMPERATURE")
    result = {"selection_temperature": _number(selection, "selection_temperature", 1e-12),
              "utility_max": _number(source.get("utility_max", 4.0), "utility_max", 1.000000001),
              "context_radius": source.get("context_radius", 3),
              "rule_budget": source.get("rule_budget", 16), "levers": {}}
    for key, upper in (("context_radius", 3), ("rule_budget", math.inf)):
        if type(result[key]) is not int:
            raise ValueError(f"{key} must be an integer")
        _number(result[key], key, 0, upper)
    declared = source.get("levers", {})
    if not isinstance(declared, dict) or set(declared) - set(CALL_LEVERS.values()):
        raise ValueError("levers must name rowweight, exemplar, atom, or retention")
    for name in CALL_LEVERS.values():
        spec = declared.get(name, {})
        allowed_lever = {"b", "T_base", "T_commandable", "T_bounds"}
        if name in ("exemplar", "retention"):
            allowed_lever.add("delta_max")
        if not isinstance(spec, dict) or set(spec) - allowed_lever:
            raise ValueError(f"invalid controls for {name}")
        bounds = spec.get("T_bounds", [0.25, 4.0])
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f"{name}.T_bounds must be [min, max]")
        low = _number(bounds[0], f"{name}.T_min", 1e-12)
        high = _number(bounds[1], f"{name}.T_max", low)
        commandable = spec.get("T_commandable", False)
        if not isinstance(commandable, bool):
            raise ValueError(f"{name}.T_commandable must be boolean")
        result["levers"][name] = {
            "b": _number(spec.get("b", 0.0), f"{name}.b", 0, 1),
            "T_base": _number(spec.get("T_base", 1.0), f"{name}.T_base", low, high),
            "T_commandable": commandable, "T_bounds": [low, high]}
        if name in ("exemplar", "retention"):
            result["levers"][name]["delta_max"] = _number(
                spec.get("delta_max", 1.0), f"{name}.delta_max", 0)
    retention = {"mode": "growth", "tau": 1.0, "rho": 1.0, "floor_coef": 1.0,
                 "c_max": 1000, "constraint": "power", "anneal_cap": False,
                 "cap_coef": 1.0, "target": 20}
    supplied = source.get("retention", {})
    if not isinstance(supplied, dict) or set(supplied) - set(retention):
        raise ValueError("invalid retention controls")
    retention.update(supplied)
    if retention["mode"] not in ("growth", "band", "ess", "fixed"):
        raise ValueError("invalid K mode")
    if retention["constraint"] not in ("power", "clamp"):
        raise ValueError("invalid pi constraint")
    for key in ("tau", "cap_coef"):
        _number(retention[key], key, 1e-12)
    for key in ("rho", "floor_coef"):
        _number(retention[key], key, 0, 1)
    for key in ("c_max", "target"):
        _number(retention[key], key, 1)
        if not isinstance(retention[key], int):
            raise ValueError(f"{key} must be an integer")
    if not isinstance(retention["anneal_cap"], bool):
        raise ValueError("anneal_cap must be boolean")
    result["retention"] = retention
    if "complexity_coef" in source:
        value = _number(source["complexity_coef"], "complexity_coef", -math.inf)
        result["complexity_coef"] = min(1.0, max(0.0, value))
    result["context_docs"] = source.get("context_docs", {})
    return result
