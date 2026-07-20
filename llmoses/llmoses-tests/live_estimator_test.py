#!/usr/bin/env python3
"""Offline live_estimator tests (no Codex, no PeTTa).

Exit 0 = PASS, 1 = FAIL.
"""

import json
import os
import shlex
import stat
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "utilities"))
import live_estimator as le           # noqa: E402
import response_template as rt        # noqa: E402
import utility_schema as us           # noqa: E402

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
        {"program_id": "p2", "cscore": {"penalized_score": -1.2}},
    ]},
    "merge_summary": {"resize_cull": {
        "survivors": ["p1", "p2", "p3"],
        "new_entrants": [{"program_id": "p3", "penalized_score": -0.25}]}},
    "atom_evidence": {
        "atom_appearances": [
            {"atom": "X1", "polarity": "-", "parent_operator": "AND",
             "depth_bucket": "mid", "count": 4},
            {"atom": "X2", "polarity": "+", "parent_operator": "OR",
             "depth_bucket": "shallow", "count": 2},
        ],
        "realized_cooccurrences": [
            {"width": 2, "members": ["feature:X1", "feature:X2"],
             "count": 3, "mean_score": -0.4},
        ],
    },
}


def full_values():
    slots = rt.build_slots(STATE, RUN_CONFIG)
    values = {}
    rank = 0
    for key in sorted(slots):
        kind = slots[key]["kind"]
        if kind == "exemplar":
            values[key] = {"exemplar:p2": 0.95, "exemplar:p3": 0.7}.get(key, 0.2)
        elif kind == "culling":
            values[key] = 1.0 if key in ("cull:p2", "cull:*") else 0.4
        elif kind == "comparator":
            order = {"rank:p2": 0.0, "rank:p3": 1.0, "rank:p1": 2.0}
            values[key] = order.get(key, float(rank))
            rank += 1
        elif kind == "atom_prior":
            values[key] = 0.6
        elif kind == "atom_prior_ctx":
            values[key] = 0.8
        elif kind == "synergy":
            values[key] = 0.55
        elif kind == "lever_weight":
            values[key] = 0.5
        elif kind == "aggregate_fn":
            values[key] = "mean"
        elif kind == "ratio":
            values[key] = "increase" if key == "ratio:direction" else 0.25
        elif kind == "temperature":
            values[key] = 1.2
    return values


def write_stub(td, name, body):
    path = os.path.join(td, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def run_with_stub(script, extra_env=None):
    old = os.environ.copy()
    try:
        os.environ.update({
            "LLMOSES_LIVE_CMD": f"{shlex.quote(sys.executable)} {shlex.quote(script)}",
            "LLMOSES_LIVE_RETRIES": "1",
            "LLMOSES_LIVE_TIMEOUT_S": "10",
        })
        if extra_env:
            os.environ.update(extra_env)
        return le.estimate(STATE, RUN_CONFIG, "7")
    finally:
        os.environ.clear()
        os.environ.update(old)


print("=== valid full-coverage values ===")
with tempfile.TemporaryDirectory() as td:
    vals = json.dumps(full_values(), sort_keys=True)
    stub = write_stub(td, "valid.py",
                      "import os\nprint(os.environ['STUB_VALUES'])\n")
    doc, trace = run_with_stub(stub, {"STUB_VALUES": vals,
                                      "LLMOSES_LIVE_COVERAGE": "full"})
    ok, errs = us.validate_utility_response(doc, RUN_CONFIG["atom_alphabet"])
    check("assembled document validates with run-context tier", ok, str(errs))
    check("contextual entries are present",
          any(e.get("context") for e in doc["atom_utility_prior"]))
    check("comparator ordering matches rank sort",
          doc["comparator_bias"]["program_id_ordering"] == ["p2", "p3", "p1"],
          str(doc.get("comparator_bias")))
    check("trace records first prompt and provider output",
          bool(trace.get("prompt")) and len(trace.get("raw_provider_outputs") or []) == 1)

print("=== retry after garbage ===")
with tempfile.TemporaryDirectory() as td:
    count = os.path.join(td, "count.txt")
    stub = write_stub(td, "retry.py", """
import os
path = os.environ["COUNT_FILE"]
try:
    n = int(open(path, encoding="utf-8").read())
except FileNotFoundError:
    n = 0
open(path, "w", encoding="utf-8").write(str(n + 1))
print("not json" if n == 0 else os.environ["STUB_VALUES"])
""")
    doc, trace = run_with_stub(stub, {"COUNT_FILE": count,
                                      "STUB_VALUES": json.dumps(full_values())})
    check("retry returns non-decline guidance", doc.get("pass") is False)
    check("trace records both raw attempts",
          len(trace.get("raw_provider_outputs") or []) == 2)
    check("trace records first attempt error",
          len(trace.get("attempt_errors") or []) == 1
          and "no JSON object" in trace["attempt_errors"][0]["error"])

print("=== final value-level salvage ===")
with tempfile.TemporaryDirectory() as td:
    vals = {"exemplar:p1": 0.9, "atom:X1": 1.5, "atom:X2": 0.4,
            "rank:p1": 0.0, "rank:p2": 1.0, "unknown:slot": 0.5}
    stub = write_stub(td, "bad_values.py",
                      "import os\nprint(os.environ['STUB_VALUES'])\n")
    doc, trace = run_with_stub(stub, {"STUB_VALUES": json.dumps(vals)})
    ok, errs = us.validate_utility_response(doc, RUN_CONFIG["atom_alphabet"])
    dropped = sorted(d["key"] for d in trace.get("dropped_keys") or [])
    check("salvaged document validates", ok, str(errs))
    check("salvage preserves valid entries",
          doc["exemplar_utilities"] == [{"program_id": "p1", "utility": 0.9}]
          and any(e["atom"] == "X2" for e in doc["atom_utility_prior"]))
    check("salvage drops exactly unknown and out-of-range slots",
          dropped == ["atom:X1", "unknown:slot"], str(dropped))

print("=== non-json declines neutrally ===")
with tempfile.TemporaryDirectory() as td:
    stub = write_stub(td, "nonjson.py", "print('still not json')\n")
    doc, trace = run_with_stub(stub)
    ok, errs = us.validate_utility_response(doc, RUN_CONFIG["atom_alphabet"])
    check("neutral decline returned without exception",
          ok and doc.get("pass") is True, str(errs))
    check("non-json attempts are recorded",
          len(trace.get("attempt_errors") or []) == 2
          and len(trace.get("raw_provider_outputs") or []) == 2)

print()
if fail == 0:
    print("LIVE ESTIMATOR TEST: PASS")
    sys.exit(0)
print("LIVE ESTIMATOR TEST: FAIL")
sys.exit(1)
