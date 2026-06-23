# Derived metrics (reconstruct, don't pre-bake)

The emitter ships **raw per-member numbers** and leaves summarization to you. Any
quantity that is a pure function of fields already in the step/terminal JSON is
your job to compute when you need it — write a throwaway script, cache the result,
and discard it as your context fills. Nothing below is emitted; all of it is
reconstructable from `metapopulation.members[*]` across `state/run-*/step-*.json`.

Each member carries `cscore.penalized_score`, `cscore.raw_score`, `complexity`,
`cscore.complexity_penalty`, and `program_id`. That is enough for the summaries an
estimator usually wants.

## score-vs-complexity trend (was previously emitted; now yours)

```python
import json, glob, os
from statistics import mean

def members(step_path):
    d = json.load(open(step_path))
    return d["metapopulation"]["members"], d["generation"]

def pearson(xs, ys):
    pts = [(x, y) for x, y in zip(xs, ys)
           if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    n = len(pts)
    if n < 2: return None
    mx, my = mean(p[0] for p in pts), mean(p[1] for p in pts)
    num = sum((x-mx)*(y-my) for x, y in pts)
    dx = sum((x-mx)**2 for x, _ in pts); dy = sum((y-my)**2 for _, y in pts)
    return None if dx <= 0 or dy <= 0 else num/(dx*dy)**0.5

def summarize(step_path):
    ms, g = members(step_path)
    pens = [m["cscore"]["penalized_score"] for m in ms if isinstance(m["cscore"]["penalized_score"], (int, float))]
    cpxs = [m["complexity"] for m in ms if isinstance(m["complexity"], (int, float))]
    return {
        "generation": g,
        "best_penalized_score": max(pens) if pens else None,
        "mean_complexity": mean(cpxs) if cpxs else None,
        "correlation": pearson(cpxs, pens),   # complexity vs penalized score, this gen
    }

# gen-over-gen deltas: sort step files, diff consecutive summaries
steps = sorted(glob.glob("state/run-*/step-*.json"),
               key=lambda p: int(os.path.basename(p).split("-")[1].split(".")[0]))
rows = [summarize(p) for p in steps]
for prev, cur in zip(rows, rows[1:]):
    cur["delta_best"] = (cur["best_penalized_score"] - prev["best_penalized_score"]
                         if None not in (cur["best_penalized_score"], prev["best_penalized_score"]) else None)
    cur["delta_mean_complexity"] = (cur["mean_complexity"] - prev["mean_complexity"]
                                    if None not in (cur["mean_complexity"], prev["mean_complexity"]) else None)
```

Interpret `delta_best` / `delta_mean_complexity` directly (sign + magnitude) — you
do not need the old categorical label string; the numbers carry the same signal
and don't pre-commit to a bucketing the emitter chose for you.

## best penalized score

`max(m["cscore"]["penalized_score"] ...)`. This one *is* still emitted as
`metapopulation.best_penalized_score` because it is a single scalar, costs nothing,
and is needed in many places — but the reconstruction is trivial if you ever want
it over a window of generations.

## why this lives here, not in the emitter

Pre-baking summaries spends tokens on every step whether or not you use them, and
freezes one definition (which correlation? which delta convention?) into the wire
format. Shipping raw numbers + an exemplar lets you compute exactly what the
current decision needs and compress on your own terms.
