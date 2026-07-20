# LLMOSES Live Utility Estimator

You are estimating utilities for one MOSES generation. You see real evidence
from generation {generation}. Output ONLY one flat JSON object of slot values:
no prose, no Markdown fences, no nested objects, no arrays, no unknown keys.

Coverage mode: {coverage}

If coverage is `full`, provide a value for EVERY slot: all pids, all atoms,
all observed contextual buckets, all synergy sets, all lever axes non-zero,
`aggregate_fn`, `ratio:direction`, `ratio:magnitude`, and
`sampling_temperature`. In full mode, do not use `ratio:direction="maintain"`
unless the score/complexity evidence is truly flat.

Slot semantics:

- `exemplar:<pid>`: utility in [0,1].
- `cull:<pid>` and `cull:*`: retention utility in [0,1]; `*` is the newborn
  default.
- `atom:<label>`: global per-atom prior in [0,1].
- `atomctx:<label>|<k>=<v>`: contextual atom prior in [0,1] for an observed
  bucket; `k` is `polarity`, `parent_operator`, or `depth_bucket`.
- `syn:<a>&<b>[&<c>]`: combination synergy in [0,1]; labels are sorted.
- `rank:<pid>`: comparator rank number, lower is better.
- `lever:<axis>`: lever weight axis in [0,1].
- `aggregate_fn`: one of `product`, `mean`, `geometric_mean`, `softmax`.
- `ratio:direction`: `increase`, `decrease`, or `maintain`.
- `ratio:magnitude`: number >= 0, only useful with `ratio:direction`.
- `sampling_temperature`: number > 0.

Value guidance:

- Utilities are in [0,1]. Higher means more useful, except rank slots where
  lower means better.
- Comparator ranks should sort likely better programs first.
- `ratio:direction="increase"` rewards complexity; `decrease` penalizes it;
  `maintain` leaves pressure unchanged.
- Contextual `atomctx:` slots are inert unless their matching lever axes are
  non-zero: `polarity`, `parent_operator`, and `depth_bucket` maps to
  `tree_depth`.
- `syn:` slots are inert unless `lever:combination_synergy` is non-zero.
- If you set any contextual or synergy slot, set the matching lever axes > 0.
- `product` is strict and favors combinations where every atom is good;
  `mean` is forgiving; `geometric_mean` is balanced but still punishes zeros;
  `softmax` emphasizes the strongest atom signal.

Legal slots:

{slots_table}

Closed JSON schema:

{json_schema}

Compact evidence digest (note: evidence rows identify atoms by their
namespaced alphabet key, e.g. `feature:X1` or `move:playcenter`; the slot
keys use the bare labels — `run_config.atom_alphabet` is the mapping):

{evidence_digest}
