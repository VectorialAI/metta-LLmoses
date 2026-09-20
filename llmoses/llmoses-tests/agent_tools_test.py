#!/usr/bin/env python3
"""Host-only smoke and contract tests for agent_tools.py."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOOLS = os.path.join(ROOT, "utilities", "agent_tools.py")
sys.path.insert(0, os.path.join(ROOT, "utilities"))
import response_template as rt  # noqa: E402
import utility_schema as us  # noqa: E402

fail = 0
RUN_CONFIG = {"atom_alphabet": {"problem_type": "boolean", "prefix": "feature",
              "atoms": [{"index": i, "key": "feature:X%d" % (i + 1),
                         "label": "X%d" % (i + 1)} for i in range(3)]}}
STATE = {"metapopulation": {"members": [
    {"program_id": "p1", "cscore": {"penalized_score": -0.5}},
    {"program_id": "p2", "cscore": {"penalized_score": -1.2}}]},
    "merge_summary": {"resize_cull": {"survivors": ["p1", "p2"],
                      "new_entrants": []}},
    "atom_evidence": {"atom_appearances": [{"atom": "X1", "polarity": "-",
                       "parent_operator": "AND", "depth_bucket": "mid", "count": 4}]}}


def check(label, ok, detail=""):
    global fail
    print("  %s: %s%s" % ("PASS" if ok else "FAIL", label,
                           (" " + detail) if detail else ""))
    if not ok:
        fail = 1


def cli(*args, **kwargs):
    proc = subprocess.run([sys.executable, TOOLS] + list(args), text=True,
                          capture_output=True, **kwargs)
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        doc = {}
    return proc, doc


def step(run, gen, ready=True):
    for kind, doc in (("state", STATE), ("action", {"generation": gen})):
        directory = os.path.join(run, kind, "run-1")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "step-%s.json" % gen), "w") as fh:
            json.dump(doc, fh)
    with open(os.path.join(run, "state", "run-1", "run_config.json"), "w") as fh:
        json.dump(RUN_CONFIG, fh)
    if ready:
        os.makedirs(os.path.join(run, "ready"), exist_ok=True)
        open(os.path.join(run, "ready", "run-1-step-%s" % gen), "w").close()


with tempfile.TemporaryDirectory() as run:
    step(run, 3)
    first, rec = cli("claim", run, "--session", "first")
    second, unused = cli("claim", run, "--session", "second")
    takeover, unused = cli("claim", run, "--session", "second", "--takeover")
    check("claim conflict exits 5 and takeover works", second.returncode == 5 and
          takeover.returncode == 0, second.stdout)
    # Ownership is a SESSION token, not the pid of the (short-lived) claim CLI.
    auto, rec = cli("claim", run, "--takeover")
    session = rec.get("session")
    check("claim without --session mints a token", auto.returncode == 0 and bool(session))
    os.environ["LLMOSES_RESPONDER_SESSION"] = session
    slots = rt.build_slots(STATE, RUN_CONFIG)
    values = {"exemplar:p1": .8, "atom:X1": .7}
    vals = os.path.join(run, "values.json")
    with open(vals, "w") as fh: json.dump(values, fh)
    wrong, unused = cli("respond", run, "1", "3", "--values", vals, "--session", "nope")
    check("respond from a session that does not hold the claim exits 5 and writes nothing",
          wrong.returncode == 5 and
          not os.path.exists(os.path.join(run, "utilities", "run-1", "step-3.json")))
    proc, doc = cli("respond", run, "1", "3", "--values", vals,
                    "--rationale", "score and evidence")
    up = os.path.join(run, "utilities", "run-1", "step-3.json")
    tp = os.path.join(run, "traces", "run-1", "step-3.json")
    rp = os.path.join(run, "response", "run-1-step-3")
    utility = json.load(open(up))
    valid, errors = us.validate_utility_response(utility, RUN_CONFIG["atom_alphabet"])
    trace = json.load(open(tp))
    check("respond writes response sequence and a valid documented outcome",
          proc.returncode == 0 and os.path.exists(rp) and
          os.path.exists(os.path.join(run, "ready", ".consumed", "run-1-step-3")) and
          valid and utility.get("status") == 200 and
          "protocol_version" in utility.get("outcome", {}) and
          utility["outcome"].get("context") and trace.get("authored_by") == "agent" and
          trace.get("audit_reasoning") == ["score and evidence"], str(errors))
    step(run, 4)
    bad = os.path.join(run, "bad.json")
    with open(bad, "w") as fh: json.dump({"fake:slot": 1}, fh)
    proc, unused = cli("respond", run, "1", "4", "--values", bad)
    check("unknown slot exits 3 and writes no artifacts", proc.returncode == 3 and
          not os.path.exists(os.path.join(run, "utilities", "run-1", "step-4.json")) and
          not os.path.exists(os.path.join(run, "traces", "run-1", "step-4.json")) and
          not os.path.exists(os.path.join(run, "response", "run-1-step-4")))
    step(run, 5)
    empty = os.path.join(run, "empty.json")
    with open(empty, "w") as fh: json.dump({}, fh)
    proc, unused = cli("respond", run, "1", "5", "--values", empty)
    check("empty values deliberately decline with 204", proc.returncode == 0 and
          json.load(open(os.path.join(run, "utilities", "run-1", "step-5.json"))).get("status") == 204)
    step(run, 6)
    proc, unused = cli("abstain", run, "1", "6", "--reason", "bad capture",
                       "--status", "422")
    abstained = json.load(open(os.path.join(run, "utilities", "run-1", "step-6.json")))
    check("abstain writes 422 input outcome", proc.returncode == 0 and
          abstained.get("pass") is True and abstained.get("status") == 422 and
          abstained.get("outcome", {}).get("error_class") == "input")
    # Unreadable input (no state/run_config for this step): abstain must NOT
    # claim a healthy 204 — it reports 422 input-unusable.
    proc, unused = cli("abstain", run, "1", "99", "--reason", "cannot read step")
    fb = json.load(open(os.path.join(run, "utilities", "run-1", "step-99.json")))
    check("abstain over unreadable input forces status 422 / error_class input",
          proc.returncode == 0 and fb.get("status") == 422
          and fb.get("outcome", {}).get("error_class") == "input", json.dumps(fb.get("outcome"))[:200])
    # W-22 binding: the history result travels into the response outcome.
    step(run, 8)
    hist_path = os.path.join(run, "hist.json")
    with open(hist_path, "w") as fh:
        json.dump({"strategy": "retrieval", "chars": 4321, "compressed": True, "dropped": [1, 2]}, fh)
    proc, unused = cli("respond", run, "1", "8", "--values", vals, "--history", hist_path)
    ctx = json.load(open(os.path.join(run, "utilities", "run-1", "step-8.json")))["outcome"]["context"]
    check("--history binds strategy/chars/compressed/dropped into outcome.context",
          proc.returncode == 0 and ctx == {"strategy": "retrieval", "chars": 4321,
                                           "compressed": True, "dropped": [1, 2]}, str(ctx))
    # Set a new ready marker and exercise wait, terminal, abort independently.
    step(run, 7)
    proc, event = cli("wait", run, "--timeout", "0.1")
    check("wait reports lowest unconsumed ready", proc.returncode == 0 and event.get("event") == "ready")
    os.remove(os.path.join(run, "ready", "run-1-step-4"))
    os.remove(os.path.join(run, "ready", "run-1-step-7"))
    with open(os.path.join(run, "state", "run-1", "terminal.json"), "w") as fh:
        json.dump({"run_verdict": "ok"}, fh)
    proc, event = cli("wait", run, "--timeout", "0.1")
    check("wait reports terminal with exit 10", proc.returncode == 10 and event.get("event") == "terminal")
    os.remove(os.path.join(run, "state", "run-1", "terminal.json"))
    proc, abort = cli("abort", run, "--reason", "test")
    proc, event = cli("wait", run, "--timeout", "0.1")
    check("abort channel and wait exit 11", proc.returncode == 11 and event.get("event") == "abort" and abort.get("source") == "agent")
    os.remove(os.path.join(run, "CONTROL", "abort"))
    for gen in (1, 2): step(run, gen, ready=False)
    proc, hist = cli("history", run, "1", "--strategy", "full_history", "--budget", "250")
    check("full history drops oldest under budget", hist.get("compressed") and 1 in hist.get("dropped", []))
    proc, hist = cli("history", run, "1", "--strategy", "per_generation", "--budget", "1", "--gen", "3")
    check("per generation never compresses", hist.get("compressed") is False)
    proc, hist = cli("history", run, "1", "--strategy", "retrieval", "--budget", "1000", "--gen", "3", "--query", "X1")
    check("retrieval returns digest context", hist.get("strategy") == "retrieval" and hist.get("payload"))
    cli("summarize", run, "1", "--text", "trend X1 improving")
    proc, hist = cli("history", run, "1", "--strategy", "rolling_summary", "--budget", "100")
    check("rolling summary round trips", "trend X1" in hist.get("payload", {}).get("summary", ""))
    proc, beat = cli("heartbeat", run, "--once")
    check("heartbeat once writes a counter", proc.returncode == 0 and beat.get("counter", 0) >= 1)
    # R3: a token minted for ANOTHER run must not claim or respond here.
    with tempfile.TemporaryDirectory() as other:
        step(other, 1)
        # The env token belongs to `run`; the other run's claim must not see it.
        saved = os.environ.pop("LLMOSES_RESPONDER_SESSION")
        oproc, orec = cli("claim", other, "--takeover")
        os.environ["LLMOSES_RESPONDER_SESSION"] = saved
        stale = orec.get("session")
        check("tokens are minted per run (run identity prefix differs)",
              oproc.returncode == 0 and stale and stale.rsplit(".", 1)[0] != session.rsplit(".", 1)[0])
        sclaim, unused = cli("claim", run, "--session", stale, "--takeover")
        sresp, unused = cli("respond", run, "1", "3", "--values", vals, "--session", stale)
        check("stale token from a prior run is rejected by claim and respond",
              sclaim.returncode == 5 and sresp.returncode == 5,
              f"claim={sclaim.returncode} respond={sresp.returncode} {sclaim.stdout[:120]}")
    # A2: an existing-but-unreadable responder record is HELD (fail safe).
    with tempfile.TemporaryDirectory() as broken:
        os.makedirs(os.path.join(broken, "CONTROL"))
        open(os.path.join(broken, "CONTROL", "responder"), "w").close()
        saved = os.environ.pop("LLMOSES_RESPONDER_SESSION")
        bproc, unused = cli("claim", broken)
        tproc, unused = cli("claim", broken, "--takeover")
        os.environ["LLMOSES_RESPONDER_SESSION"] = saved
        check("unreadable responder record refuses a claim (5) unless --takeover",
              bproc.returncode == 5 and tproc.returncode == 0, bproc.stdout[:160])
    # R3: concurrent re-claim of a RELEASED record — exactly one claimant may
    # win. Acquisition is serialised under flock, so the regression is a
    # start-together race of several contenders (plus a takeover variant,
    # where the LAST one to run wins but never two at once).
    import multiprocessing as mp
    sys.path.insert(0, os.path.join(ROOT, "utilities"))
    import responder_control as rc_mod

    def contender(rundir, label, barrier, queue, takeover):
        os.environ.pop("LLMOSES_RESPONDER_SESSION", None)
        try:
            barrier.wait(timeout=10)
        except Exception:
            pass
        try:
            rec = rc_mod.claim(rundir, "agent:" + label, "agent", session=label,
                               takeover=takeover)
            queue.put((label, "ok", rec["owner"]["session"]))
        except Exception as exc:  # noqa: BLE001
            queue.put((label, type(exc).__name__, None))

    def race(takeover, n=4):
        with tempfile.TemporaryDirectory() as raced:
            os.makedirs(os.path.join(raced, "CONTROL"))
            with open(os.path.join(raced, "CONTROL", "responder"), "w") as fh:
                json.dump({"mode": "agent:old", "run_id": os.path.basename(raced),
                           "owner": {"kind": "agent", "pid": 1, "host": "old",
                                     "session": "old.tok", "label": "old"},
                           "released": True}, fh)
            ctx = mp.get_context("fork")
            barrier, queue = ctx.Barrier(n), ctx.Queue()
            labels = ["c%d" % i for i in range(n)]
            procs = [ctx.Process(target=contender, args=(raced, lbl, barrier, queue, takeover))
                     for lbl in labels]
            for pr in procs:
                pr.start()
            for pr in procs:
                pr.join(20)
            outcomes = sorted(queue.get(timeout=5) for _ in procs)
            final = rc_mod.read_json(rc_mod.control_path(raced, "responder")) or {}
            return outcomes, (final.get("owner") or {})

    outcomes, owner = race(False)
    winners = [(lbl, tok) for lbl, res, tok in outcomes if res == "ok"]
    check("4 concurrent re-claims of a released record: exactly one winner, record matches it",
          len(winners) == 1 and owner.get("label") == winners[0][0]
          and owner.get("session") == winners[0][1],
          f"outcomes={[(l, r) for l, r, _ in outcomes]} final={owner.get('label')}")
    outcomes, owner = race(True)
    winners = [(lbl, tok) for lbl, res, tok in outcomes if res == "ok"]
    check("concurrent takeovers serialise: final record matches exactly one claimant's minted token",
          len(winners) >= 1 and owner.get("session") in [tok for _, tok in winners]
          and len({tok for _, tok in winners}) == len(winners),
          f"outcomes={[(l, r) for l, r, _ in outcomes]} final={owner.get('label')}")
    denied, unused = cli("release", run, "--session", "nope")
    proc, rel = cli("release", run)
    check("release requires the owning session", denied.returncode == 5 and
          proc.returncode == 0 and rel.get("released") is True)
    os.environ.pop("LLMOSES_RESPONDER_SESSION", None)

print("\nAGENT TOOLS TEST: %s" % ("PASS" if not fail else "FAIL"))
sys.exit(fail)
