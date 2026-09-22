"""Four-lever policy arithmetic. No I/O, implicit RNG draws, or provider calls."""

import math
import random

CALL_LEVERS = {1: "rowweight", 2: "exemplar", 3: "atom", 4: "retention"}


def normalize(weights, fallback=None):
    total = math.fsum(weights)
    if total > 0:
        return [w / total for w in weights]
    if fallback is not None:
        return list(fallback)
    return [1.0 / len(weights)] * len(weights) if weights else []


def softmax(scores, temperature):
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    finite = [s for s in scores if math.isfinite(s)]
    if not finite:
        return normalize([1.0] * len(scores))
    best = max(finite)
    return normalize([math.exp((s - best) / temperature)
                      if math.isfinite(s) else 0.0 for s in scores])


def offset_preference(scores, offsets, native_temperature):
    """Bounded score-space edits to MOSES's prior; omitted offsets are zero."""
    adjusted = [score + offsets.get(i, 0.0) for i, score in enumerate(scores)]
    return softmax(adjusted, native_temperature)


def mix(prior, preference, b, temperature=1.0):
    # A true off gate: no rounding, no sharpening, no random-number consumption.
    if b == 0:
        return list(prior)
    mixed = [(1.0 - b) * p + b * a for p, a in zip(prior, preference)]
    if temperature == 1.0:
        return mixed
    logs = [math.log(x) / temperature if x > 0 else -math.inf for x in mixed]
    high = max(logs, default=-math.inf)
    return normalize([math.exp(v - high) if math.isfinite(v) else 0.0
                      for v in logs], prior)


def divergence(prior, realized):
    mid = [(p + d) / 2 for p, d in zip(prior, realized)]
    js = sum(x * math.log(x / m) / 2
             for vector in (prior, realized) for x, m in zip(vector, mid) if x > 0)
    return {"tv": 0.5 * sum(abs(p - d) for p, d in zip(prior, realized)),
            "js": js}


def roulette(weights, rng=random):
    # Keep native sum/order and one random.random call, including b=0.
    target = rng.random() * sum(weights)
    for i, weight in enumerate(weights):
        target -= weight
        if target <= 0:
            return i
    return len(weights) - 1


def retention_budget(prior, scores, n0, entrants, minimum, band, config,
                     generation):
    n = len(prior)
    cap = config["c_max"]
    if config.get("anneal_cap"):
        cap = min(cap, int(config["cap_coef"] * (generation + 250)
                          * (1 + 2 * math.exp(-generation / 500))))
    ceiling = max(0, min(n, cap, n0 + math.floor(config["rho"] * entrants)))
    requested_floor = max(math.ceil(config["floor_coef"] * n0), minimum)
    floor = min(requested_floor, ceiling)
    mode = config["mode"]
    if mode == "growth":
        target = ceiling
    elif mode == "band":
        target = max(minimum, sum(s >= max(scores) - band for s in scores)) if n else 0
    elif mode == "ess":
        target = math.floor(1.0 / math.fsum(p * p for p in prior)) if n else 0
    else:
        target = config["target"]
    k = min(ceiling, max(floor, target))
    return k, {"target": target, "floor": requested_floor, "ceiling": ceiling,
               "floor_shortfall": max(0, requested_floor - ceiling), "K": k,
               "mode": mode, "N0": n0, "entrants": entrants}


def inclusion_probabilities(distribution, k, method="power"):
    """First-order pi in [0,1], sum(pi)=K, with deterministic adjustment."""
    n = len(distribution)
    if not 0 <= k <= n:
        raise ValueError("retention K is outside the feasible pool")
    if k == 0 or k == n:
        return [float(k == n)] * n, {"method": method, "alpha": 1.0}
    q = normalize(distribution)
    if method == "power":
        def powered(alpha):
            if alpha == 0:
                return [1.0 / n] * n
            return normalize([p ** alpha for p in q])
        lo, hi = 0.0, 1.0
        support = sum(p > 0 for p in q)
        if max(q) * k <= 1:
            lo = 1.0
        elif support >= k:
            for _ in range(80):
                mid = (lo + hi) / 2
                if max(powered(mid)) * k <= 1:
                    lo = mid
                else:
                    hi = mid
        pi = [k * p for p in powered(lo)]
        return pi, {"method": method, "alpha": lo,
                    "support_shortfall": max(0, k - support)}
    if method != "clamp":
        raise ValueError("sum constraint must be power or clamp")
    pi, active, remaining = [0.0] * n, list(range(n)), float(k)
    while active:
        weights = normalize([q[i] for i in active])
        saturated = [i for i, p in zip(active, weights) if remaining * p >= 1]
        if not saturated:
            for i, p in zip(active, weights):
                pi[i] = remaining * p
            break
        for i in saturated:
            pi[i] = 1.0
        remaining -= len(saturated)
        saturated = set(saturated)
        active = [i for i in active if i not in saturated]
    return pi, {"method": method, "clamped": sum(p == 1 for p in pi)}


def madow(pi, k, rng=random):
    """Randomized-order systematic pi-ps sampling, exactly K distinct indices."""
    if k == 0:
        return []
    if k == len(pi):
        return list(range(k))
    order = list(range(len(pi)))
    rng.shuffle(order)
    offset = rng.random()
    chosen, cumulative, point = [], 0.0, offset
    for position, i in enumerate(order):
        # The total is mathematically K. Pin the endpoint against roundoff.
        cumulative = float(k) if position == len(order) - 1 else cumulative + pi[i]
        if len(chosen) < k and point < cumulative:
            chosen.append(i)
            point = offset + len(chosen)
    if len(chosen) != k or len(set(chosen)) != k:
        raise ArithmeticError("systematic retention draw violated exact K")
    return sorted(chosen)
