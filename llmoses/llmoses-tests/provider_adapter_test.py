#!/usr/bin/env python3
"""Offline provider classification and bounded-estimator failure tests."""
import json
import os
import shlex
import stat
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "utilities"))
import live_estimator as le  # noqa: E402
import provider_adapter as pa  # noqa: E402
import response_template as rt  # noqa: E402

fail = 0
RUN_CONFIG = {"atom_alphabet": {"problem_type": "boolean", "prefix": "feature",
              "atoms": [{"index": i, "key": "feature:X%d" % (i + 1),
                         "label": "X%d" % (i + 1)} for i in range(3)]}}
STATE = {"metapopulation": {"members": [
    {"program_id": "p1", "cscore": {"penalized_score": -0.5}},
    {"program_id": "p2", "cscore": {"penalized_score": -1.2}}]},
    "merge_summary": {"resize_cull": {"survivors": ["p1", "p2"], "new_entrants": []}},
    "atom_evidence": {"atom_appearances": []}}


def check(label, ok, detail=""):
    global fail
    print("  %s: %s%s" % ("PASS" if ok else "FAIL", label,
                           (" " + detail) if detail else ""))
    if not ok: fail = 1


def full_values():
    values = {}
    for key, spec in rt.build_slots(STATE, RUN_CONFIG).items():
        if spec["kind"] == "aggregate_fn": values[key] = "mean"
        elif key == "ratio:direction": values[key] = "maintain"
        elif spec["kind"] == "temperature": values[key] = 1.0
        else: values[key] = .5
    return values


def stub(td, name, body):
    path = os.path.join(td, name)
    with open(path, "w") as fh: fh.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def estimate(script, env=None, state=STATE):
    old = os.environ.copy()
    try:
        os.environ.update({"LLMOSES_LIVE_CMD": "%s %s" % (shlex.quote(sys.executable), shlex.quote(script)),
                           "LLMOSES_LIVE_RETRIES": "1", "LLMOSES_LIVE_BACKOFF_S": "0",
                           "LLMOSES_LIVE_TIMEOUT_S": "10", "VALUES": json.dumps(full_values())})
        if env: os.environ.update(env)
        return le.estimate(state, RUN_CONFIG, "1")
    finally:
        os.environ.clear(); os.environ.update(old)


for text, klass, retryable in (
        ("401 Unauthorized invalid_api_key", "auth", False),
        ("Reconnecting... 5/5 stream disconnected before completion", "network", False),
        ("You exceeded your current quota 429", "quota", False),
        ("429 Too Many Requests rate limit", "rate_limit", True),
        ("gibberish", "provider_error", False)):
    err = pa.classify("warning " * 700 + text, 1)
    check("classify %s including tail signatures" % klass,
          err.error_class == klass and err.retryable is retryable, err.error_class)

with tempfile.TemporaryDirectory() as td:
    auth = stub(td, "auth.py", "import sys\nsys.stderr.write('401 Unauthorized invalid_api_key')\nsys.exit(1)\n")
    doc, trace = estimate(auth)
    check("auth is terminal 503 after one attempt", doc["status"] == 503 and
          doc["outcome"]["error_class"] == "auth" and doc["outcome"]["attempts"] == 1 and
          len(trace["attempt_errors"]) == 1)
    network = stub(td, "network.py", "import sys\nsys.stderr.write('Reconnecting... 5/5 stream disconnected before completion')\nsys.exit(1)\n")
    doc, unused = estimate(network)
    check("network is non-retryable", doc["status"] == 503 and doc["outcome"]["attempts"] == 1)
    rate = stub(td, "rate.py", """import os, sys
p = os.environ['COUNT']
try: n = int(open(p).read())
except IOError: n = 0
open(p, 'w').write(str(n + 1))
if n == 0: sys.stderr.write('429 Too Many Requests rate limit'); sys.exit(1)
print(os.environ['VALUES'])
""")
    count = os.path.join(td, "count")
    doc, unused = estimate(rate, {"COUNT": count})
    check("rate limit retries once then guides", doc["status"] == 200 and
          doc["outcome"]["attempts"] == 2 and doc["outcome"]["retried"] is True)
    timeout = stub(td, "timeout.py", "import time\ntime.sleep(3)\n")
    doc, unused = estimate(timeout, {"LLMOSES_LIVE_TIMEOUT_S": "1"})
    check("timeout retries once and returns 504", doc["status"] == 504 and doc["outcome"]["attempts"] == 2)
    malformed = stub(td, "malformed.py", "print('nope')\n")
    doc, unused = estimate(malformed)
    check("malformed output returns 500 after two attempts", doc["status"] == 500 and doc["outcome"]["attempts"] == 2)
    empty = stub(td, "empty.py", "print('{}')\n")
    doc, unused = estimate(empty)
    check("empty object is deliberate 204", doc["status"] == 204)
    schema = stub(td, "schema.py", """import json, os
schema = json.load(open(os.environ['LLMOSES_OUTPUT_SCHEMA_PATH']))
assert schema['type'] == 'object' and schema['additionalProperties'] is False
print(os.environ['VALUES'])
""")
    doc, unused = estimate(schema)
    check("provider receives closed output schema", doc["status"] == 200)
    marker = os.path.join(td, "called")
    no_call = stub(td, "nocall.py", "import os\nopen(os.environ['MARKER'], 'w').close()\nprint('{}')\n")
    bad_state = dict(STATE); bad_state["capture_status"] = {"ok": False}
    doc, unused = estimate(no_call, {"MARKER": marker}, bad_state)
    check("bad capture returns 422 without provider call", doc["status"] == 422 and not os.path.exists(marker))

old = os.environ.copy()
try:
    os.environ.update({"LLMOSES_LIVE_TIMEOUT_S": "10", "LLMOSES_LIVE_RETRIES": "1",
                       "LLMOSES_LIVE_BACKOFF_S": "0"})
    check("timeout invariant accepts 30", le.check_timeout_invariant(30) == 20)
    for boundary in (20, 15):
        try: le.check_timeout_invariant(boundary)
        except le.TimeoutInvariantError: continue
        check("timeout invariant rejects %s" % boundary, False)
finally:
    os.environ.clear(); os.environ.update(old)

print("\nPROVIDER ADAPTER TEST: %s" % ("PASS" if not fail else "FAIL"))
sys.exit(fail)
