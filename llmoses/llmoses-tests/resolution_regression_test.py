#!/usr/bin/env python3
"""Utility-estimation resolution regression test (no PeTTa needed).

Replays pinned UtilityResponse fixtures through state_builder._ingest_utilities
and asserts, per fixture, exactly which estimations survive, which are
rejected, and that every rejection is REPORTED in the utility_ingest audit row
(`ignored` map + schema diagnostics). This pins the resolution audit of the
milestone-1 simulated run (llmoses/outputs/runs/20260618-000924, 53 handshakes):
exemplar and culling estimations flow at 100% (retain_utility legacy alias),
while pair_utilities (superseded by D-027/D-033 atom priors + synergy) and
pre-D-030 bare-string ratio deltas are dropped — visibly, never silently.

Run from the repo root:  python3 llmoses/llmoses-tests/resolution_regression_test.py
Exit 0 = PASS, 1 = FAIL.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FIXTURES = os.path.join(REPO, "llmoses", "llmoses-tests", "fixtures",
                        "m1-sim-utilities")

RUN_DIR = tempfile.mkdtemp(prefix="llmoses-resolution-")
os.environ["LLMOSES_RUN_DIR"] = RUN_DIR
os.environ.pop("LLMOSES_APPLY_LEVERS", None)
sys.path.insert(0, os.path.join(REPO, "llmoses", "utilities"))
import state_builder as sb  # noqa: E402  (env must be set first)

fail = 0


def check(label, cond, detail=""):
    global fail
    if cond:
        print(f"  PASS: {label}")
    else:
        print(f"  FAIL: {label} {detail}")
        fail = 1


def last_ingest_row():
    rows = []
    with open(os.path.join(RUN_DIR, "moses_native_log.jsonl"),
              encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                if row.get("event") == "utility_ingest":
                    rows.append(row)
    return rows[-1] if rows else {}


def ingest(doc_or_name, gen=1):
    """Place a UtilityResponse where _ingest_utilities looks and ingest it."""
    util_dir = os.path.join(RUN_DIR, "utilities", f"run-{sb._run_seq}")
    os.makedirs(util_dir, exist_ok=True)
    dst = os.path.join(util_dir, f"step-{gen}.json")
    if isinstance(doc_or_name, str):
        shutil.copy(os.path.join(FIXTURES, doc_or_name), dst)
    else:
        with open(dst, "w", encoding="utf-8") as fh:
            json.dump(doc_or_name, fh)
    sb._pending_utilities = None
    sb._ingest_utilities(gen)
    return sb._pending_utilities, last_ingest_row()


# (fixture, expected survivors, expected ignored map). Counts pinned from the
# milestone-1 sim; if a contract change alters any of these, this test is the
# tripwire that makes the resolution regression visible.
M1_CASES = [
    ("run-1-step-1.json",
     {"exemplar": 1, "retention": 78},
     {"pair_utilities": 0, "complexity_ratio_delta": "invalid_shape"}),
    ("run-1-step-8.json",
     {"exemplar": 279, "retention": 47},
     {"pair_utilities": 30, "complexity_ratio_delta": "invalid_shape"}),
    ("run-3-step-2.json",
     {"exemplar": 16, "retention": 9},
     {"pair_utilities": 6, "complexity_ratio_delta": "invalid_shape"}),
    ("run-5-step-3.json",
     {"exemplar": 114, "retention": 34},
     {"pair_utilities": 30, "complexity_ratio_delta": "invalid_shape"}),
    ("run-8-step-4.json",
     {"exemplar": 1, "retention": 6},
     {"pair_utilities": 1, "complexity_ratio_delta": "invalid_shape"}),
]

print("=== milestone-1 sim fixtures: survivors pinned, drops reported ===")
for name, want, want_ignored in M1_CASES:
    pending, row = ingest(name)
    check(f"{name} ingested non-decline", pending is not None)
    if pending is None:
        continue
    check(f"{name} exemplar {want['exemplar']}/{want['exemplar']}",
          len(pending["exemplar"]) == want["exemplar"],
          f"got {len(pending['exemplar'])}")
    check(f"{name} retention {want['retention']}/{want['retention']} "
          f"(retain_utility alias)",
          len(pending["retention"]) == want["retention"],
          f"got {len(pending['retention'])}")
    check(f"{name} no atom prior / synergy / comparator / ratio parsed",
          not pending["atom_prior"] and not pending["atom_prior_ctx"]
          and not pending["synergy"] and not pending["comparator_rank"]
          and pending["complexity_ratio_delta"] is None)
    check(f"{name} drops reported in ignored map",
          row.get("ignored") == want_ignored,
          f"got {row.get('ignored')}")
    check(f"{name} flagged schema-invalid (pre-contract shape)",
          row.get("schema_ok") is False and row.get("schema_errors"))

print("=== decline fixture ===")
pending, row = ingest("run-7-step-2.json")
check("run-7-step-2 pass=true clears the buffer",
      pending is None and row.get("decline") is True)
check("run-7-step-2 legacy fields still reported on decline",
      (row.get("ignored") or {}).get("pair_utilities") == 5,
      f"got {row.get('ignored')}")

print("=== current-contract document parses fully and validates ===")
modern = {
    "pass": False,
    "sampling_temperature": 1.0,
    "exemplar_utilities": [{"program_id": "p1", "utility": 0.9}],
    "atom_utility_prior": [
        {"atom": "X1", "utility": 0.2},
        {"atom": "X1", "utility": 0.9,
         "context": {"parent_operator": "OR", "depth_bucket": "mid"}},
        {"atom": "X2", "utility": 0.7, "context": {"polarity": "-"}},
    ],
    "combination_synergy": [{"atoms": ["X1", "X2"], "utility": 0.8}],
    "feature_utility_levers": {
        "aggregate_fn": "mean",
        "lever_weights": {"parent_operator": 1.0, "tree_depth": 0.5,
                          "polarity": 1.0, "combination_synergy": 1.0}},
    "culling_utilities": [{"program_id": "p1", "retention_utility": 1.0},
                          {"program_id": "*", "retention_utility": 0.5}],
    "complexity_ratio_delta": {"direction": "decrease", "magnitude": 0.5},
    "comparator_bias": {"program_id_ordering": ["p1", "p2"]},
}
pending, row = ingest(modern)
check("modern doc schema_ok", row.get("schema_ok") is True,
      f"errors={row.get('schema_errors')}")
check("modern doc nothing ignored", row.get("ignored") is None,
      f"got {row.get('ignored')}")
check("modern doc parsed: 1 global + 2 contextual atoms, 1 synergy, "
      "ratio object, ordering, wildcard retention",
      pending is not None
      and len(pending["atom_prior"]) == 1
      and len(pending["atom_prior_ctx"]) == 2
      and len(pending["synergy"]) == 1
      and pending["lever_weights"].get("parent_operator") == 1.0
      and pending["complexity_ratio_delta"] == {"direction": "decrease",
                                                "magnitude": 0.5}
      and len(pending["comparator_rank"]) == 2
      and pending["retention_default"] == 0.5)

print("=== unknown fields are reported, never silent ===")
odd = dict(modern)
odd["totally_new_field"] = [1, 2, 3]
pending, row = ingest(odd)
check("unknown top-level field lands in ignored map",
      (row.get("ignored") or {}).get("totally_new_field") == 3,
      f"got {row.get('ignored')}")
check("unknown top-level field fails schema (constrained-output gate)",
      row.get("schema_ok") is False)

shutil.rmtree(RUN_DIR, ignore_errors=True)
print()
print("RESOLUTION REGRESSION TEST: " + ("PASS" if fail == 0 else "FAIL"))
sys.exit(fail)
