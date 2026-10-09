"""Causal ordered-pair policy grammar and evaluation (no construction ownership)."""

import math

from lever_policy import normalize

SITE_KINDS = ("exemplar_node", "appended_child", "literal_wrap", "sampled_subtree")
LOCAL_KEYS = ("op", "depth", "site_kind", "local_literals")


def vocabulary(radius):
    return ([] if radius == 0 else list(LOCAL_KEYS)
            + (["ancestor_drew"] if radius >= 2 else [])
            + (["already_drawn"] if radius >= 3 else []))


def _pair(pair, alphabet):
    if not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(a, str) for a in pair):
        raise ValueError("pair must be an ordered list of two labels")
    if pair[0] == pair[1] or any(a not in alphabet for a in pair):
        raise ValueError("pair requires distinct atoms in the alphabet")
    return tuple(pair)


def _weights(entries, alphabet, maximum, clamped, where):
    if not isinstance(entries, list):
        raise ValueError(f"{where}: must be a list")
    seen, result = set(), []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"pair", "weight"}:
            raise ValueError(f"{where}: entry requires pair and weight")
        pair = _pair(entry["pair"], alphabet)
        if pair in seen:
            raise ValueError(f"{where}: duplicate ordered pair")
        seen.add(pair)
        value = entry["weight"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{where}: weight must be finite")
        clipped = min(maximum, max(0.0, value))
        if clipped != value:
            clamped.append(f"{where}[{i}]")
        result.append({"pair": list(pair), "weight": clipped})
    return result


def validate(policy, alphabet, config):
    if not isinstance(policy, dict) or set(policy) - {"base", "rules"}:
        raise ValueError("policy permits only base and rules")
    clamped = []
    result = {"base": _weights(policy.get("base", []), alphabet, config["utility_max"], clamped, "base"),
              "rules": []}
    rules = policy.get("rules", [])
    if not isinstance(rules, list) or len(rules) > config["rule_budget"]:
        raise ValueError("rules exceeds rule_budget or is not a list")
    if rules and config["context_radius"] == 0:
        raise ValueError("context_radius=0 accepts base weights only")
    allowed = set(vocabulary(config["context_radius"]))
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict) or set(rule) != {"when", "adjust"}:
            raise ValueError("rule requires when and adjust")
        when = rule["when"]
        if not isinstance(when, dict) or not when or set(when) - allowed:
            raise ValueError("when contains disabled/noncausal keys or is empty")
        if "op" in when and when["op"] not in ("AND", "OR"):
            raise ValueError("op must be AND or OR")
        if "site_kind" in when and when["site_kind"] not in SITE_KINDS:
            raise ValueError("invalid site_kind")
        if "depth" in when:
            depth = when["depth"]
            if not isinstance(depth, dict) or not depth or set(depth) - {"min", "max"}:
                raise ValueError("depth requires min and/or max")
            if any(type(x) is not int or x < 0 for x in depth.values()):
                raise ValueError("depth bounds must be nonnegative integers")
            if depth.get("min", 0) > depth.get("max", math.inf):
                raise ValueError("depth interval is empty")
        if "local_literals" in when:
            literals = when["local_literals"]
            if not isinstance(literals, list) or not literals:
                raise ValueError("local_literals requires a nonempty conjunction")
            for literal in literals:
                if not isinstance(literal, dict) or set(literal) != {"atom", "polarity"}:
                    raise ValueError("literal requires atom and polarity")
                if literal["atom"] not in alphabet or literal["polarity"] not in ("+", "-"):
                    raise ValueError("literal is outside the alphabet/polarity vocabulary")
        for key in ("ancestor_drew", "already_drawn"):
            if key in when:
                _pair(when[key], alphabet)
        result["rules"].append({"when": dict(when), "adjust": _weights(
            rule["adjust"], alphabet, config["utility_max"], clamped, f"rules[{i}].adjust")})
    return result, clamped


def matches(when, state):
    for key, value in when.items():
        if key == "depth":
            if not value.get("min", 0) <= state["depth"] <= value.get("max", math.inf):
                return False
        elif key == "local_literals":
            actual = {(x["atom"], x["polarity"]) for x in state[key]}
            if any((x["atom"], x["polarity"]) not in actual for x in value):
                return False
        elif key in ("ancestor_drew", "already_drawn"):
            if tuple(value) not in {tuple(pair) for pair in state[key]}:
                return False
        elif state[key] != value:
            return False
    return True


def evaluate(policy, pairs, prior, state):
    fired = [i for i, rule in enumerate(policy.get("rules", [])) if matches(rule["when"], state)]
    factors = [policy.get("base", [])] + [policy["rules"][i]["adjust"] for i in fired]
    maps = [{tuple(e["pair"]): e["weight"] for e in entries} for entries in factors]
    logs, applied = [], []
    for pair, p in zip(pairs, prior):
        values = [m.get(tuple(pair), 1.0) for m in maps]
        logs.append(math.log(p) + sum(math.log(v) for v in values)
                    if p > 0 and all(v > 0 for v in values) else -math.inf)
        applied.append(values)
    high = max(logs, default=-math.inf)
    preference = normalize([math.exp(v - high) if math.isfinite(v) else 0.0 for v in logs], prior)
    coverage = sum(any(tuple(pair) in m for m in maps) for pair in pairs) / len(pairs) if pairs else 0
    return preference, {"factors": applied, "fired_rules": fired, "coverage": coverage,
                         "zero_mass_fallback": high == -math.inf}


def json_schema(alphabet, config):
    pair = {"type": "array", "items": {"type": "string", "enum": sorted(alphabet)}, "minItems": 2, "maxItems": 2}
    weight = {"type": "object", "additionalProperties": False, "required": ["pair", "weight"],
              "properties": {"pair": pair, "weight": {"type": "number", "minimum": 0, "maximum": config["utility_max"]}}}
    conditions = {
        "op": {"enum": ["AND", "OR"]}, "site_kind": {"enum": list(SITE_KINDS)},
        "depth": {"type": "object", "additionalProperties": False, "minProperties": 1,
                  "properties": {k: {"type": "integer", "minimum": 0} for k in ("min", "max")}},
        "local_literals": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False, "required": ["atom", "polarity"],
            "properties": {"atom": {"enum": sorted(alphabet)}, "polarity": {"enum": ["+", "-"]}}}},
        "ancestor_drew": pair, "already_drawn": pair}
    when = {"type": "object", "additionalProperties": False, "minProperties": 1,
            "properties": {k: conditions[k] for k in vocabulary(config["context_radius"])}}
    return {"type": "object", "additionalProperties": False, "properties": {
        "base": {"type": "array", "items": weight},
        "rules": {"type": "array", "maxItems": config["rule_budget"] if config["context_radius"] else 0,
                  "items": {"type": "object", "additionalProperties": False, "required": ["when", "adjust"],
                            "properties": {"when": when, "adjust": {"type": "array", "items": weight}}}}}}
