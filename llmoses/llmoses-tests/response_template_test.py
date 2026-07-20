#!/usr/bin/env python3
"""Slot-template + salvage test (no PeTTa; runs on host and in-container).

Pins the deterministic-generation contract:
  * build_slots enumerates ONLY the real universe (pids from state, atoms
    from the alphabet, contextual slots from observed evidence buckets,
    synergy sets from the enumerated combinations);
  * assemble() from slot values always yields a contract-valid document,
    and rejects unknown slots / out-of-domain values with exceptions;
  * json_schema() closes the payload (additionalProperties false, enums);
  * salvage_utility_response keeps valid components of an invalid document
    and degrades to a valid decline only when nothing survives.

Exit 0 = PASS, 1 = FAIL.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "utilities"))
import response_template as rt          # noqa: E402
import utility_schema as us             # noqa: E402

fail = 0


def check(label, ok, detail=""):
    global fail
    if ok:
        print(f"  PASS: {label}")
    else:
        print(f"  FAIL: {label} {detail}")
        fail = 1


RUN_CONFIG = {"atom_alphabet": {
    "problem_type": "boolean", "prefix": "feature",
    "atoms": [{"index": i, "key": f"feature:X{i+1}", "label": f"X{i+1}"}
              for i in range(3)]}}

STATE = {
    "metapopulation": {"members": [
        {"program_id": "p1", "cscore": {"penalized_score": -0.5}},
        {"program_id": "p2", "cscore": {"penalized_score": -1.0}},
    ]},
    "merge_summary": {"resize_cull": {
        "survivors": ["p1", "p2", "p3"],
        "new_entrants": [{"program_id": "p3", "penalized_score": -0.25}]}},
    "atom_evidence": {"atom_appearances": [
        # Evidence rows carry prefixed alphabet KEYS, exactly as emitted —
        # the template must map key -> bare label (the prefix trap).
        {"atom": "feature:X1", "polarity": "-", "clause_type": "AND",
         "parent_operator": "AND", "depth_bucket": "mid", "count": 4},
        {"atom": "feature:X3", "polarity": "+", "clause_type": "OR",
         "parent_operator": "OR", "depth_bucket": "mid", "count": 1},
    ]},
}

print("=== slot enumeration: everything real, nothing else ===")
slots = rt.build_slots(STATE, RUN_CONFIG)
pids = {k.split(":", 1)[1] for k in slots if k.startswith("exemplar:")}
check("pids are exactly the survivors incl. new entrant",
      pids == {"p1", "p2", "p3"}, f"got {sorted(pids)}")
check("newborn wildcard slot present", "cull:*" in slots)
atoms = {k.split(":", 1)[1] for k in slots if k.startswith("atom:")}
check("global atom slots are exactly the alphabet",
      atoms == {"X1", "X2", "X3"}, f"got {sorted(atoms)}")
ctx = sorted(k for k in slots if k.startswith("atomctx:"))
check("contextual slots come only from observed buckets",
      ctx == ["atomctx:X1|depth_bucket=mid", "atomctx:X1|parent_operator=AND",
              "atomctx:X1|polarity=-", "atomctx:X3|depth_bucket=mid",
              "atomctx:X3|parent_operator=OR", "atomctx:X3|polarity=+"],
      f"got {ctx}")
syn = sorted(k for k in slots if k.startswith("syn:"))
check("synergy slots enumerate all width-2 sets",
      syn == ["syn:X1&X2", "syn:X1&X3", "syn:X2&X3"], f"got {syn}")

print("=== atom identity resolution: strict, canonical, no passthrough ===")
import atom_evidence as ae                                    # noqa: E402
resolve = ae.atom_label_resolver(RUN_CONFIG["atom_alphabet"])
check("resolver maps alphabet key to bare label",
      resolve("feature:X2") == "X2")
check("resolver accepts an exact bare label",
      resolve("X2") == "X2")
try:
    resolve("feature:GHOST")
    check("resolver raises on unknown identity", False, "no exception")
except KeyError:
    check("resolver raises on unknown identity", True)
bad_state = {"atom_evidence": {"atom_appearances": [
    {"atom": "bogus:Z9", "polarity": "+", "parent_operator": "OR",
     "depth_bucket": "mid", "count": 1}]}}
try:
    rt.build_slots(bad_state, RUN_CONFIG)
    check("build_slots raises on out-of-alphabet evidence identity",
          False, "no exception")
except KeyError:
    check("build_slots raises on out-of-alphabet evidence identity", True)

print("=== assembly: valid by construction ===")
values = {"exemplar:p1": 1.0, "exemplar:p2": 0.0,
          "cull:p3": 1.0, "cull:*": 1.0,
          "atom:X1": 0.9, "atomctx:X1|parent_operator=AND": 1.0,
          "syn:X1&X3": 1.0, "syn:X1&X2": 0.0,
          "rank:p2": 0.0, "rank:p1": 1.0, "rank:p3": 2.0,
          "lever:parent_operator": 1.0, "lever:combination_synergy": 1.0,
          "aggregate_fn": "product",
          "ratio:direction": "increase", "ratio:magnitude": 0.5,
          "sampling_temperature": 1.0}
doc = rt.assemble(slots, values, RUN_CONFIG)
ok, errs = us.validate_utility_response(doc,
                                        RUN_CONFIG["atom_alphabet"])
check("assembled document is contract-valid (context tier)", ok, str(errs[:2]))
check("comparator ordering sorted by rank value",
      doc["comparator_bias"]["program_id_ordering"] == ["p2", "p1", "p3"],
      str(doc["comparator_bias"]))
check("contextual entry carries the single-axis context",
      any(e.get("context") == {"parent_operator": "AND"}
          for e in doc["atom_utility_prior"]))
check("omitted slots emit nothing (sparse = neutral)",
      len(doc["exemplar_utilities"]) == 2 and len(doc["culling_utilities"]) == 2)

decline = rt.assemble(slots, {}, RUN_CONFIG, decline=True)
check("decline assembly is a valid pass=true document",
      decline["pass"] is True and
      us.validate_utility_response(decline)[0])

print("=== adversarial fills raise, never coerce ===")
for label, bad in [
        ("unknown slot key", {"exemplar:ghost": 1.0}),
        ("out-of-domain unit value", {"atom:X1": 1.5}),
        ("non-finite value", {"atom:X1": float("inf")}),
        ("bad enum", {"ratio:direction": "explode"}),
        ("magnitude without direction", {"ratio:magnitude": 1.0}),
        ("zero temperature", {"sampling_temperature": 0.0})]:
    try:
        rt.assemble(slots, bad, RUN_CONFIG)
        check(f"assemble rejects {label}", False, "no exception")
    except (KeyError, ValueError):
        check(f"assemble rejects {label}", True)

print("=== schema export: closed world ===")
schema = rt.json_schema(slots)
check("additionalProperties is false",
      schema.get("additionalProperties") is False)
check("every slot has a property and nothing extra",
      set(schema["properties"]) == set(slots))
check("enums are closed",
      schema["properties"]["ratio:direction"]["enum"] ==
      list(us.RATIO_DIRECTIONS))

print("=== salvage: keep the good, account for the bad ===")
broken = dict(doc)
broken["exemplar_utilities"] = (
    doc["exemplar_utilities"]
    + [{"program_id": "p1", "utility": 0.3},          # duplicate pid
       {"program_id": "px", "utility": 7.0}])         # out-of-range
broken["complexity_ratio_delta"] = "increase"          # pre-D-030 shape
broken["pair_utilities"] = [{"pair": "X1&X2"}]         # unknown field
salvaged, report = us.salvage_utility_response(
    broken, RUN_CONFIG["atom_alphabet"])
ok, errs = us.validate_utility_response(salvaged,
                                        RUN_CONFIG["atom_alphabet"])
check("salvaged document is contract-valid", ok, str(errs[:2]))
check("valid exemplar entries kept",
      [e["program_id"] for e in salvaged["exemplar_utilities"]] == ["p1", "p2"])
check("bad exemplar entries dropped and reported",
      report.get("exemplar_utilities", {}).get("dropped") == 2)
check("bare-string ratio dropped and reported",
      salvaged["complexity_ratio_delta"] is None
      and "complexity_ratio_delta" in report)
check("unknown field reported",
      "pair_utilities" in report)
check("untouched components survive salvage",
      salvaged["comparator_bias"] == doc["comparator_bias"]
      and salvaged["combination_synergy"] == doc["combination_synergy"])

hopeless, report2 = us.salvage_utility_response({"weird": 1}, None)
check("nothing salvageable yields a valid guidance-free document",
      us.validate_utility_response(hopeless)[0]
      and not us.has_guidance(hopeless))
check("non-object input yields None",
      us.salvage_utility_response("nope", None)[0] is None)

print()
if fail == 0:
    print("RESPONSE TEMPLATE TEST: PASS")
    sys.exit(0)
print("RESPONSE TEMPLATE TEST: FAIL")
sys.exit(1)
