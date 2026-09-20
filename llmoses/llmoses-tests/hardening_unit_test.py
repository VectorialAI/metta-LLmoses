#!/usr/bin/env python3
"""M2 hardening unit test — MOSES-side failure behaviour (no PeTTa, no docker).

Drives state_builder through the same hooks the MeTTa loop calls
(new_run / begin_gen / add_member / flush_gen / await_response / enter_gen /
select_index) with a scripted responder and asserts the PLAN-m2-hardening.md
failure semantics:

  W-1/W-2   stale-on-timeout is impossible (buffer cleared, fence asserted)
  W-1b      an unreadable response never leaves old guidance live
  W-2       re-ingest is a no-op, older-gen ingest is rejected, fence
            violations are FATAL (abort), not fallbacks
  W-5/W-15  non-200/204 statuses (and status/pass contradictions) abort the
            run and reach capture_failures
  W-26      fabricated program ids are counted per channel (rate + sample),
            the run continues, verdict `degraded`; '*' is exempt
  W-19      terminal.json carries run_verdict ok / degraded / aborted
  W-20      CONTROL/abort ends the run (poll loop and generation boundary)
  R1/§1.3   an expected estimate that never arrives aborts whether or not
            a responder ever declared itself; generations outside the
            configured window (LLMOSES_EXPECT_RESPONSE_GENS) run native by
            design without blocking and are recorded in terminal.json
  R2        unknown (fabricated) vs unoffered (existed, culled at merge) ids
            are separate per-channel rates
  R3/R4     covered by agent_tools_test.py / failure_injection_test.sh
  W-3       a static heartbeat counter aborts with reason supervisor_dead,
            distinguishable from response_timeout; an advancing one waits
  W-17      section failures log their exception; audit-log failures are
            counted as logging_degraded in terminal.json
  W-18/W-14 salvage / retry / coverage outcomes feed the degraded verdict
  W-23      consecutive lost generations abort (guidance_lost_cascade)
  W-28/W-22 protocol versions and context strategy surface in terminal.json

Reverse-check: every assertion here fails on the pre-hardening tree
(a7b64f1): the hooks it relies on (enter_gen, _exit_fn, status handling,
CONTROL/ channel) do not exist there and the pre-change code silently
continues natively in every scenario.

Run from anywhere:  python3 llmoses/llmoses-tests/hardening_unit_test.py
Exit 0 = PASS, 1 = FAIL.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_DIR = tempfile.mkdtemp(prefix="llmoses-hardening-")
os.environ["LLMOSES_RUN_DIR"] = RUN_DIR
os.environ["LLMOSES_AWAIT_RESPONSE"] = "1"
os.environ["LLMOSES_RESPONSE_TIMEOUT_S"] = "0.6"
os.environ["LLMOSES_RESPONSE_POLL_S"] = "0.02"
os.environ["LLMOSES_HEARTBEAT_STALL_S"] = "0.4"
os.environ["LLMOSES_APPLY_LEVERS"] = "exemplar_selection,culling,comparator"
os.environ["LLMOSES_LEVER_WEIGHT_EXEMPLAR_SELECTION"] = "1"
os.environ["LLMOSES_LEVER_WEIGHT_CULLING"] = "1"
os.environ["LLMOSES_LEVER_WEIGHT_COMPARATOR"] = "1"
# atom_evidence off: string trees are not walkable and would pollute
# capture_failures (the W-17 check turns it on deliberately).
os.environ["LLMOSES_EMIT_LEVERS"] = "exemplar_selection,culling,complexity_ratio,comparator_hook"
os.environ["LLMOSES_MAX_CONSECUTIVE_LOST"] = "2"
sys.path.insert(0, os.path.join(REPO, "llmoses", "utilities"))
import state_builder as sb  # noqa: E402

fail = 0


def check(label, cond, detail=""):
    global fail
    if cond:
        print(f"  PASS: {label}")
    else:
        print(f"  FAIL: {label} {detail}")
        fail = 1


class AbortSignal(BaseException):
    """Stands in for os._exit: BaseException so the hooks' `except
    Exception` guards do not swallow it, exactly like SystemExit."""

    def __init__(self, code):
        self.code = code
        super().__init__(f"abort exit {code}")


def _raise_abort(code):
    raise AbortSignal(code)


try:
    sb._exit_fn = _raise_abort
    sb._HB_READ_EVERY_S = 0.05
except Exception:
    pass

CONTROL = os.path.join(RUN_DIR, "CONTROL")
MEMBERS = ["A", "B", "C", "D"]


def pid_of(expr):
    return sb._pid(expr)


def rows(event=None):
    out = []
    with open(os.path.join(RUN_DIR, "moses_native_log.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                if event is None or row.get("event") == event:
                    out.append(row)
    return out


def rows_since(n, event=None):
    return [r for r in rows()[n:] if event is None or r.get("event") == event]


def log_len():
    return len(rows())


def fresh_run():
    """Clean CONTROL/ and open a new run (module state reset by new_run)."""
    shutil.rmtree(CONTROL, ignore_errors=True)
    seq = sb.new_run()
    try:
        sb._aborted = False
    except Exception:
        pass
    return seq


def gen(g, members=MEMBERS):
    """Emit one generation the way sbEmitGeneration does (members + flush)."""
    sb.begin_gen(g)
    for i, m in enumerate(members):
        score = -0.1 * (i + 1)
        sb.add_member(g, m, m, [score, 1, 0.0, 0.0, score], None)
    sb.flush_gen(g)


def write_response(g, doc, seq=None):
    seq = seq or sb._run_seq
    d = os.path.join(RUN_DIR, "utilities", f"run-{seq}")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"step-{g}.json")
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(doc, str):
            fh.write(doc)
        else:
            json.dump(doc, fh)
    os.makedirs(os.path.join(RUN_DIR, "response"), exist_ok=True)
    with open(os.path.join(RUN_DIR, "response", f"run-{seq}-step-{g}"), "w") as fh:
        fh.write("1\n")


def response(exemplar=None, culling=None, ordering=None, decline=False,
             status=None, outcome=None):
    doc = {"pass": bool(decline), "sampling_temperature": None,
           "exemplar_utilities": exemplar or [],
           "atom_utility_prior": [], "combination_synergy": [],
           "feature_utility_levers": None, "culling_utilities": culling or [],
           "complexity_ratio_delta": None,
           "comparator_bias": ({"program_id_ordering": ordering}
                               if ordering else None)}
    if status is not None:
        doc["status"] = status
    if outcome is not None:
        doc["outcome"] = outcome
    return doc


def force(target):
    return [{"program_id": pid_of(m), "utility": 1.0 if m == target else 0.0}
            for m in MEMBERS]


def draw(g):
    """One exemplar draw at generation g (enter_gen + roulette)."""
    enter_gen(g)
    sb.begin_selection(len(MEMBERS))
    for i, m in enumerate(MEMBERS):
        sb.add_selection_candidate(i, 0.25, m)
    return sb.select_index()


def terminal(seq=None):
    seq = seq or sb._run_seq
    path = os.path.join(RUN_DIR, "state", f"run-{seq}", "terminal.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def control(name, doc):
    os.makedirs(CONTROL, exist_ok=True)
    with open(os.path.join(CONTROL, name), "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def declare_responder():
    control("responder", {"mode": "test", "owner": {"kind": "test", "pid": 1},
                          "protocol_version": "llmoses-p1+test",
                          "context_strategy": "full_history",
                          "released": False})


def expect_abort(fn, label):
    try:
        fn()
    except AbortSignal as e:
        return e.code
    except BaseException as e:  # noqa: BLE001
        check(f"{label}: raised {type(e).__name__} instead of abort", False, repr(e))
        return None
    return None


# ---------------------------------------------------------------------------

SCENARIOS = []


def scenario(fn):
    SCENARIOS.append(fn)
    return fn


def enter_gen(g):
    """Pre-hardening trees have no enter_gen; degrade to a no-op so every
    check still runs (and fails) there instead of crashing the file."""
    hook = getattr(sb, "enter_gen", None)
    return hook(g) if hook else 0


@scenario
def scenario_1():
    print("=== W-19: clean run is verdict ok; 200 guidance applied one generation later ===")
    fresh_run()
    gen(1)
    write_response(1, response(exemplar=force("D"), status=200))
    sb.await_response(1)
    n0 = log_len()
    idx = draw(2)
    bias = rows_since(n0, "bias_applied")
    check("guidance for gen 1 is applied at gen 2 with response_gen 1",
          len(bias) == 1 and bias[0].get("response_gen") == 1 and idx == 3,
          f"idx={idx} rows={bias}")
    gen(2)
    write_response(2, response(exemplar=force("A"), status=200))
    sb.await_response(2)
    sb.begin_gen(3)
    sb.flush_terminal(3)
    t = terminal()
    check("terminal.json run_verdict ok with no quality flags",
          t.get("run_verdict") == "ok" and not t.get("quality_flags"),
          f"verdict={t.get('run_verdict')} flags={t.get('quality_flags')}")
    check("terminal.json carries handshake + confabulation blocks",
          isinstance(t.get("handshake"), dict) and isinstance(t.get("confabulation"), dict))

    # ---------------------------------------------------------------------------

@scenario
def scenario_2():
    print("=== R1/W-1: expected estimate missing, NO responder ever declared -> abort (no stale guidance) ===")
    fresh_run()
    gen(1)
    write_response(1, response(exemplar=force("D")))
    sb.await_response(1)
    draw(2)
    gen(2)
    n0 = log_len()
    code = expect_abort(lambda: sb.await_response(2), "undeclared timeout")
    to = rows_since(n0, "response_timeout")
    check("timeout with no responder declared ABORTS (rc 3) — the crashing-before-claim case",
          code == 3 and len(to) == 1 and to[0].get("responder_declared") is False,
          f"code={code} rows={to}")
    t = terminal()
    check("terminal verdict aborted / response_timeout, responder_declared false recorded",
          t.get("run_verdict") == "aborted"
          and (t.get("abort") or {}).get("reason") == "response_timeout"
          and (t.get("abort") or {}).get("detail", {}).get("responder_declared") is False,
          json.dumps(t.get("abort"))[:200])
    check("buffer cleared before exit — gen-1 guidance cannot outlive the failed await (W-1)",
          sb._pending_utilities is None)
    check("capture_failures counts the timeout",
          sb._capture_failures.get("response_timeout") == 1, str(sb._capture_failures))

    # ---------------------------------------------------------------------------

@scenario
def scenario_3():
    print("=== R1/§1.3: response never written WITH a declared responder -> abort (unchanged) ===")
    fresh_run()
    declare_responder()
    gen(1)
    code = expect_abort(lambda: sb.await_response(1), "declared timeout")
    check("await_response exits non-zero", code == 3, f"code={code}")
    t = terminal()
    check("terminal.json run_verdict aborted, reason response_timeout",
          t.get("run_verdict") == "aborted"
          and (t.get("abort") or {}).get("reason") == "response_timeout",
          json.dumps(t.get("abort"))[:200])
    ab = json.load(open(os.path.join(CONTROL, "abort"), encoding="utf-8"))
    check("CONTROL/abort written by moses", ab.get("source") == "moses"
          and ab.get("reason") == "response_timeout", str(ab))
    check("capture_failures records the abort",
          sb._capture_failures.get("abort:response_timeout") == 1
          and sb._capture_failures.get("response_timeout") == 1,
          str(sb._capture_failures))

    # ---------------------------------------------------------------------------

@scenario
def scenario_4():
    print("=== W-20: CONTROL/abort ends the run in the poll loop and at the generation boundary ===")
    fresh_run()
    gen(1)
    control("abort", {"reason": "operator", "source": "agent", "detail": "unsalvageable"})
    code = expect_abort(lambda: sb.await_response(1), "abort in poll")
    t = terminal()
    check("abort during await: exit 3, verdict aborted, reason abort_requested",
          code == 3 and t.get("run_verdict") == "aborted"
          and (t.get("abort") or {}).get("reason") == "abort_requested"
          and (t.get("abort") or {}).get("detail", {}).get("requested_reason") == "operator",
          f"code={code} abort={t.get('abort')}")
    fresh_run()
    control("abort", {"reason": "supervisor-says-stop", "source": "supervisor"})
    code = expect_abort(lambda: sb.enter_gen(1), "abort at boundary")
    check("abort at enter_gen: exit 3", code == 3, f"code={code}")

    # ---------------------------------------------------------------------------

@scenario
def scenario_5():
    print("=== W-3: heartbeat static -> supervisor_dead (not response_timeout); advancing -> waits ===")
    os.environ["LLMOSES_RESPONSE_TIMEOUT_S"] = "3"
    sb._RESP_TIMEOUT_S = 3.0
    fresh_run()
    declare_responder()
    control("heartbeat", {"counter": 7, "ts_ms": 0})
    gen(1)
    t0 = time.monotonic()
    code = expect_abort(lambda: sb.await_response(1), "static heartbeat")
    dt = time.monotonic() - t0
    t = terminal()
    check("static counter aborts with reason supervisor_dead before the timeout",
          code == 3 and (t.get("abort") or {}).get("reason") == "supervisor_dead" and dt < 2.5,
          f"code={code} reason={(t.get('abort') or {}).get('reason')} dt={dt:.2f}")
    check("supervisor_dead is counted separately from response_timeout",
          sb._capture_failures.get("supervisor_dead") == 1
          and not sb._capture_failures.get("response_timeout"), str(sb._capture_failures))

    fresh_run()
    declare_responder()
    stop = threading.Event()


    def beat():
        c = 0
        while not stop.is_set():
            c += 1
            control("heartbeat", {"counter": c})
            time.sleep(0.05)


    th = threading.Thread(target=beat, daemon=True)
    th.start()
    gen(1)
    t0 = time.monotonic()
    code = expect_abort(lambda: sb.await_response(1), "advancing heartbeat")
    dt = time.monotonic() - t0
    stop.set()
    th.join(1)
    t = terminal()
    check("advancing counter waits for the backstop, then aborts as response_timeout",
          code == 3 and (t.get("abort") or {}).get("reason") == "response_timeout" and dt >= 2.9,
          f"code={code} reason={(t.get('abort') or {}).get('reason')} dt={dt:.2f}")
    os.environ["LLMOSES_RESPONSE_TIMEOUT_S"] = "0.6"
    sb._RESP_TIMEOUT_S = 0.6

    # ---------------------------------------------------------------------------

@scenario
def scenario_6():
    print("=== W-5/W-15: status taxonomy decides continue vs abort ===")
    fresh_run()
    gen(1)
    write_response(1, response(decline=True, status=204))
    code = expect_abort(lambda: sb.await_response(1), "204")
    check("204 deliberate abstention continues", code is None and sb._pending_utilities is None)
    gen(2)
    write_response(2, response(decline=True, status=503,
                               outcome={"attempts": 1, "retried": False,
                                        "error_class": "auth", "detail": "401"}))
    code = expect_abort(lambda: sb.await_response(2), "503")
    t = terminal()
    check("503 aborts with reason responder_failure and the error class",
          code == 3 and (t.get("abort") or {}).get("reason") == "responder_failure"
          and (t.get("abort") or {}).get("detail", {}).get("error_class") == "auth",
          json.dumps(t.get("abort"))[:300])
    check("failure reaches capture_failures as responder_503",
          sb._capture_failures.get("responder_503") == 1
          and t.get("capture_failures", {}).get("responder_503") == 1,
          str(sb._capture_failures))
    for st in (422, 500, 504):
        fresh_run()
        gen(1)
        write_response(1, response(decline=True, status=st))
        code = expect_abort(lambda: sb.await_response(1), str(st))
        check(f"{st} aborts", code == 3
              and sb._capture_failures.get(f"responder_{st}") == 1, f"code={code}")
    fresh_run()
    gen(1)
    write_response(1, response(exemplar=force("A"), decline=True, status=200))
    code = expect_abort(lambda: sb.await_response(1), "200/pass mismatch")
    check("status 200 with pass=true is a contract break -> abort", code == 3)
    fresh_run()
    gen(1)
    write_response(1, response(decline=True, status=299))
    code = expect_abort(lambda: sb.await_response(1), "unknown status")
    check("unknown status code reads as 500 -> abort", code == 3
          and sb._capture_failures.get("responder_500") == 1, str(sb._capture_failures))

    # ---------------------------------------------------------------------------

@scenario
def scenario_7():
    print("=== W-1b: unreadable response clears the buffer and aborts ===")
    fresh_run()
    gen(1)
    write_response(1, response(exemplar=force("D")))
    sb.await_response(1)
    draw(2)
    gen(2)
    write_response(2, "{not json")
    code = expect_abort(lambda: sb.await_response(2), "garbage")
    check("unreadable response -> abort responder_failure/unreadable_response, buffer None",
          code == 3 and sb._pending_utilities is None
          and (terminal().get("abort") or {}).get("detail", {}).get("error_class")
          == "unreadable_response",
          f"code={code} buffer={sb._pending_utilities is not None}")
    check("utility_ingest_error counted", sb._capture_failures.get("utility_ingest_error") == 1)

    # ---------------------------------------------------------------------------

@scenario
def scenario_8():
    print("=== W-2: idempotent re-ingest, stale rejection, fatal fence ===")
    fresh_run()
    gen(1)
    write_response(1, response(exemplar=force("D")))
    sb.await_response(1)
    n0 = log_len()
    sb._ingest_utilities(1)
    sk = rows_since(n0, "utility_ingest_skipped")
    check("re-ingest of the same (run, gen) is a no-op",
          len(sk) == 1 and sk[0].get("reason") == "duplicate"
          and not rows_since(n0, "utility_ingest"), str(sk))
    write_response(0, response(exemplar=force("A")))
    n0 = log_len()
    sb._ingest_utilities(0)
    sk = rows_since(n0, "utility_ingest_skipped")
    check("ingest of a generation older than the fence is rejected",
          len(sk) == 1 and sk[0].get("reason") == "stale"
          and sb._pending_utilities["exemplar"][pid_of("D")] == 1.0, str(sk))
    n0 = log_len()
    code = expect_abort(lambda: sb.await_response(1), "await re-entry")
    check("await_response re-entry for the same gen is idempotent",
          code is None and len(rows_since(n0, "await_reentry")) == 1)
    code = expect_abort(lambda: sb.enter_gen(4), "fence at enter_gen")
    check("enter_gen with offset != 1 is FATAL (generation_fence)",
          code == 3 and (terminal().get("abort") or {}).get("reason") == "generation_fence",
          f"code={code}")
    fresh_run()
    gen(1)
    write_response(1, response(exemplar=force("D")))
    sb.await_response(1)
    sb._await_gen = 3            # simulate a broken meta-loop: buffer two behind


    def lever_only():
        sb.begin_selection(len(MEMBERS))
        for i, m in enumerate(MEMBERS):
            sb.add_selection_candidate(i, 0.25, m)
        return sb.select_index()


    code = expect_abort(lever_only, "fence at lever")
    check("_lever_on with a buffer not exactly one generation behind aborts",
          code == 3 and (terminal().get("abort") or {}).get("detail", {}).get("where",
                                                                              "").startswith("_lever_on"),
          f"code={code} abort={terminal().get('abort')}")

    # ---------------------------------------------------------------------------

@scenario
def scenario_9():
    print("=== W-26: fabricated program ids are counted, inert, and degrade the verdict ===")
    fresh_run()
    gen(1)
    fake = [{"program_id": "pfake000001", "utility": 1.0},
            {"program_id": "pfake000002", "utility": 1.0}]
    write_response(1, response(exemplar=force("D") + fake,
                               culling=[{"program_id": "*", "retention_utility": 1.0},
                                        {"program_id": pid_of("A"), "retention_utility": 0.5}],
                               ordering=["pfake000003", pid_of("A"), pid_of("B")]))
    n0 = log_len()
    sb.await_response(1)
    ing = rows_since(n0, "utility_ingest")
    u = (ing[0].get("unknown_ids") or {}) if ing else {}
    check("utility_ingest row carries per-channel unknown-id rates",
          u.get("exemplar_utilities", {}).get("unknown") == 2
          and u.get("exemplar_utilities", {}).get("total") == 6
          and abs(u.get("exemplar_utilities", {}).get("rate", 0) - 2 / 6) < 1e-6
          and u.get("comparator_bias", {}).get("unknown") == 1
          and u.get("culling_utilities", {}).get("unknown") == 0
          and u.get("culling_utilities", {}).get("total") == 1,   # '*' is exempt
          json.dumps(u))
    check("sample lists the fabricated ids",
          sorted(u.get("exemplar_utilities", {}).get("sample", [])) == ["pfake000001", "pfake000002"])
    idx = draw(2)
    check("run continues; fabricated ids stay inert (real utility-1 target still chosen)",
          idx == 3, f"idx={idx}")
    sb.begin_gen(3)
    sb.flush_terminal(3)
    t = terminal()
    check("terminal verdict degraded with unknown_program_ids flag",
          t.get("run_verdict") == "degraded"
          and t.get("quality_flags", {}).get("unknown_program_ids") == 3,
          f"{t.get('run_verdict')} {t.get('quality_flags')}")
    cf = t.get("confabulation", {}).get("unknown_program_ids", {})
    check("confabulation block aggregates per channel with rate",
          cf.get("exemplar_utilities", {}).get("rate") is not None
          and cf.get("comparator_bias", {}).get("unknown") == 1, json.dumps(cf)[:300])

    # ---------------------------------------------------------------------------

@scenario
def scenario_10():
    print("=== W-23: consecutive generations of nothing-but-fabricated guidance abort ===")
    fresh_run()
    gen(1)
    write_response(1, response(exemplar=[{"program_id": "pfake1", "utility": 1.0}]))
    code = expect_abort(lambda: sb.await_response(1), "lost 1")
    check("first lost generation continues (counted)", code is None
          and sb._lost_streak == 1)
    draw(2)
    gen(2)
    write_response(2, response(exemplar=[{"program_id": "pfake2", "utility": 1.0}]))
    code = expect_abort(lambda: sb.await_response(2), "lost 2")
    check("second consecutive lost generation aborts (guidance_lost_cascade)",
          code == 3 and (terminal().get("abort") or {}).get("reason") == "guidance_lost_cascade",
          f"code={code}")

    # ---------------------------------------------------------------------------

@scenario
def scenario_11():
    print("=== W-18/W-14/W-22/W-28: outcome accounting feeds the verdict and terminal ===")
    fresh_run()
    gen(1)
    write_response(1, response(exemplar=force("D"), status=200, outcome={
        "attempts": 2, "retried": True,
        "salvage": {"requested": 5, "survived": 3},
        "coverage": {"mode": "full", "requested": 10, "supplied": 8},
        "protocol_version": "llmoses-p1+aaaaaaaaaaaa",
        "context": {"strategy": "rolling_summary", "chars": 1234,
                    "compressed": True, "dropped": [1]}}))
    sb.await_response(1)
    draw(2)
    gen(2)
    write_response(2, response(exemplar=force("A"), status=200, outcome={
        "attempts": 1, "retried": False,
        "protocol_version": "llmoses-p1+bbbbbbbbbbbb",
        "context": {"strategy": "rolling_summary", "chars": 999,
                    "compressed": False, "dropped": []}}))
    sb.await_response(2)
    sb.begin_gen(3)
    sb.flush_terminal(3)
    t = terminal()
    q = t.get("quality_flags", {})
    check("retries / salvage drops / partial coverage are quality flags -> degraded",
          t.get("run_verdict") == "degraded" and q.get("retries") == 1
          and q.get("salvage_drops") == 2 and q.get("partial_coverage") == 1, str(q))
    check("two protocol versions in one run flag protocol_drift and are listed",
          q.get("protocol_drift") == 2
          and t.get("protocol_versions_seen") == ["llmoses-p1+aaaaaaaaaaaa",
                                                  "llmoses-p1+bbbbbbbbbbbb"],
          str(t.get("protocol_versions_seen")))
    ci = t.get("context_instrumentation") or {}
    check("context instrumentation aggregated (strategy, max chars, compressions, dropped)",
          ci.get("strategies") == ["rolling_summary"] and ci.get("max_chars") == 1234
          and ci.get("compressions") == 1 and ci.get("dropped_total") == 1
          and ci.get("generations") == 2, str(ci))

    # ---------------------------------------------------------------------------

@scenario
def scenario_12():
    print("=== W-17: section failures log their exception; audit-log failures are counted ===")
    fresh_run()
    sb._EMIT_LEVERS.add("atom_evidence")
    real_walker = sb.atom_evidence.build_atom_evidence


    def boom(*a, **k):
        raise RuntimeError("walker exploded on purpose")


    sb.atom_evidence.build_atom_evidence = boom
    n0 = log_len()
    gen(1)
    sb.atom_evidence.build_atom_evidence = real_walker
    sb._EMIT_LEVERS.discard("atom_evidence")
    sf = rows_since(n0, "section_failed")
    check("section_failed row carries the section name and repr(e)",
          len(sf) == 1 and sf[0].get("section") == "atom_evidence"
          and "walker exploded on purpose" in sf[0].get("error", ""), str(sf))
    check("capture_failures counts the section", sb._capture_failures.get("atom_evidence") == 1)


    class BrokenLog:
        def write(self, *_):
            raise OSError("disk gone")

        def flush(self):
            pass


    real_nfh = sb._NFH
    sb._NFH = BrokenLog()
    sb._log_event("probe")
    sb._NFH = real_nfh
    check("a failed audit write increments logging_degraded", sb._logging_degraded >= 1)
    write_response(1, response(decline=True))
    sb.await_response(1)
    sb.begin_gen(2)
    sb.flush_terminal(2)
    t = terminal()
    check("terminal.json surfaces logging_degraded and the section failure -> degraded",
          t.get("logging_degraded", 0) >= 1 and t.get("run_verdict") == "degraded"
          and t.get("quality_flags", {}).get("capture_failures.atom_evidence") == 1,
          f"{t.get('logging_degraded')} {t.get('run_verdict')} {t.get('quality_flags')}")

    # ---------------------------------------------------------------------------

@scenario
def scenario_13():
    print("=== run_config: handshake block for the responder-side timeout invariant (W-16) ===")
    fresh_run()
    sb.emit_run_config()
    rc_doc = json.load(open(os.path.join(RUN_DIR, "state", f"run-{sb._run_seq}",
                                         "run_config.json"), encoding="utf-8"))
    hs = rc_doc.get("handshake") or {}
    check("run_config.handshake records response_timeout_s / poll_s / heartbeat_stall_s",
          hs.get("await_enabled") is True and hs.get("response_timeout_s") == 0.6
          and hs.get("heartbeat_stall_s") == 0.4, str(hs))


@scenario
def scenario_unknown_atoms():
    print("=== W-23: out-of-alphabet atom guidance is not usable (lost), counted as unknown_atoms ===")
    fresh_run()
    sb.set_problem_spec(["X1", "X2", "X3"])
    sb.emit_run_config()
    gen(1)
    doc = response(status=200)
    doc["atom_utility_prior"] = [{"atom": "NOT_AN_ATOM", "utility": 1.0}]
    doc["combination_synergy"] = [{"atoms": ["X1", "NOPE"], "utility": 1.0}]
    write_response(1, doc)
    code = expect_abort(lambda: sb.await_response(1), "unknown atoms 1")
    check("first all-unknown-atom generation continues but counts as lost",
          code is None and sb._lost_streak == 1
          and sb._confab.get("unknown_atoms") == 2, f"lost={sb._lost_streak} confab={sb._confab}")
    draw(2)
    gen(2)
    doc2 = response(status=200)
    doc2["atom_utility_prior"] = [{"atom": "STILL_NOT", "utility": 1.0}]
    write_response(2, doc2)
    code = expect_abort(lambda: sb.await_response(2), "unknown atoms 2")
    check("second consecutive all-unknown-atom generation aborts (guidance_lost_cascade)",
          code == 3 and (terminal().get("abort") or {}).get("reason") == "guidance_lost_cascade",
          f"code={code}")
    check("terminal confabulation reports unknown_atoms",
          terminal().get("confabulation", {}).get("unknown_atoms") == 3
          and terminal().get("quality_flags", {}).get("unknown_atoms") == 3,
          str(terminal().get("confabulation", {}).get("unknown_atoms")))
    fresh_run()
    sb.set_problem_spec(["X1", "X2", "X3"])
    sb.emit_run_config()
    gen(1)
    doc = response(status=200)
    doc["atom_utility_prior"] = [{"atom": "X1", "utility": 1.0},
                                 {"atom": "NOT_AN_ATOM", "utility": 1.0}]
    write_response(1, doc)
    sb.await_response(1)
    check("a response with one real atom is usable (streak reset) but still flags unknown_atoms",
          sb._lost_streak == 0 and sb._quality.get("unknown_atoms") == 1)


@scenario
def scenario_window():
    print("=== R1: expected-generation window — outside it native by design, no blocking ===")
    saved_spec, saved_pred = sb._EXPECT_SPEC, sb._EXPECT
    try:
        # backloaded: only generation 3 expects an estimate
        sb._EXPECT_SPEC, sb._EXPECT = "3-", sb._parse_gen_spec("3-")
        fresh_run()
        gen(1)
        t0 = time.monotonic()
        code = expect_abort(lambda: sb.await_response(1), "outside window")
        dt = time.monotonic() - t0
        check("gen 1 outside the window: no block, no abort, await_skipped row",
              code is None and dt < 0.3 and len(rows("await_skipped")) >= 1, f"code={code} dt={dt:.2f}")
        draw(2)
        gen(2)
        code = expect_abort(lambda: sb.await_response(2), "outside window 2")
        check("gen 2 outside the window: still native, fence advanced", code is None and sb._await_gen == 2)
        draw(3)
        gen(3)
        code = expect_abort(lambda: sb.await_response(3), "inside window, missing")
        check("gen 3 inside the window with no response ABORTS", code == 3)
        t = terminal()
        w = t.get("response_window") or {}
        check("terminal records window spec and native-by-design generations",
              w.get("spec") == "3-" and w.get("native_generations") == [1, 2], str(w))
        # frontloaded: gens 1-1 expected, later ones native; run completes ok
        sb._EXPECT_SPEC, sb._EXPECT = "1-1", sb._parse_gen_spec("1-1")
        fresh_run()
        gen(1)
        write_response(1, response(exemplar=force("D")))
        sb.await_response(1)
        idx = draw(2)
        gen(2)
        code = expect_abort(lambda: sb.await_response(2), "frontload gen 2")
        draw(3)
        sb.begin_gen(3)
        sb.flush_terminal(3)
        t = terminal()
        check("frontloaded window: gen 1 guidance applied, gen 2 native by design, verdict ok",
              idx == 3 and code is None and t.get("run_verdict") == "ok"
              and (t.get("response_window") or {}).get("native_generations") == [2]
              and not t.get("quality_flags"),
              f"idx={idx} code={code} verdict={t.get('run_verdict')} flags={t.get('quality_flags')}")
        check("spec parser: lists, ranges, open ranges, none, all",
              sb._parse_gen_spec("1-3,5")(2) and sb._parse_gen_spec("1-3,5")(5)
              and not sb._parse_gen_spec("1-3,5")(4) and sb._parse_gen_spec("-2")(1)
              and not sb._parse_gen_spec("-2")(3) and sb._parse_gen_spec("4-")(9)
              and not sb._parse_gen_spec("none")(1) and sb._parse_gen_spec("all")(77))
    finally:
        sb._EXPECT_SPEC, sb._EXPECT = saved_spec, saved_pred


@scenario
def scenario_unoffered():
    print("=== R2: fabricated (A) vs unoffered-but-existed (B) ids are separate buckets ===")
    fresh_run()
    sb.begin_gen(1)
    for i, m in enumerate(MEMBERS):
        score = -0.1 * (i + 1)
        sb.add_member(1, m, m, [score, 1, 0.0, 0.0, score], None)
    # merge: A, B, C survive; D is culled -> existed in gen 1, not offered
    sb.begin_merge()
    for m in ("A", "B", "C"):
        sb.add_merged_member(m)
    sb.flush_gen(1)
    write_response(1, response(
        exemplar=[{"program_id": pid_of("A"), "utility": 1.0},
                  {"program_id": pid_of("D"), "utility": 1.0},
                  {"program_id": "pfake000009", "utility": 1.0}],
        culling=[{"program_id": pid_of("D"), "retention_utility": 0.5},
                 {"program_id": pid_of("C"), "retention_utility": 0.5},
                 {"program_id": "*", "retention_utility": 1.0}],
        ordering=[pid_of("D"), pid_of("B")]))
    n0 = log_len()
    sb.await_response(1)
    ing = rows_since(n0, "utility_ingest")
    u = (ing[0].get("unknown_ids") or {}) if ing else {}
    cu = u.get("culling_utilities", {})
    check("culling channel: D unoffered, C offered, '*' exempt",
          cu.get("unoffered") == 1 and cu.get("unknown") == 0 and cu.get("total") == 2, json.dumps(cu))
    ex = u.get("exemplar_utilities", {})
    check("exemplar channel: 1 unknown (fabricated), 1 unoffered (culled D), offered A in neither",
          ex.get("unknown") == 1 and ex.get("unoffered") == 1 and ex.get("total") == 3
          and ex.get("sample") == ["pfake000009"] and ex.get("unoffered_sample") == [pid_of("D")],
          json.dumps(ex))
    cb = u.get("comparator_bias", {})
    check("comparator channel: D unoffered, B offered", cb.get("unoffered") == 1 and cb.get("unknown") == 0, json.dumps(cb))
    sb.begin_gen(2)
    sb.flush_terminal(2)
    t = terminal()
    cf = t.get("confabulation", {})
    check("terminal carries both rates and both feed the degraded verdict",
          t.get("run_verdict") == "degraded"
          and t.get("quality_flags", {}).get("unknown_program_ids") == 1
          and t.get("quality_flags", {}).get("unoffered_program_ids") == 3
          and cf.get("unknown_program_ids", {}).get("exemplar_utilities", {}).get("rate") is not None
          and cf.get("unoffered_program_ids", {}).get("comparator_bias", {}).get("unoffered") == 1,
          f"{t.get('quality_flags')} {json.dumps(cf.get('unoffered_program_ids'))[:200]}")


@scenario
def scenario_schema_streak():
    print("=== W-23: consecutive schema failures abort even when guidance salvaged through ===")
    saved = sb._MAX_SCHEMA_STREAK
    sb._MAX_SCHEMA_STREAK = 3
    try:
        fresh_run()
        code = None
        for g in (1, 2):
            gen(g)
            doc = response(exemplar=force("D"), status=200)
            doc["totally_new_field"] = [1]        # schema-invalid, guidance intact
            write_response(g, doc)
            code = expect_abort(lambda: sb.await_response(g), f"schema fail {g}")
            draw(g + 1)
        check("two consecutive schema failures continue (streak 2), guidance still applied",
              code is None and sb._schema_fail_streak == 2
              and sb._pending_utilities is not None, f"code={code} streak={sb._schema_fail_streak}")
        gen(3)
        write_response(3, response(exemplar=force("A"), status=200))   # valid: resets
        sb.await_response(3)
        check("a valid response resets the streak", sb._schema_fail_streak == 0)
        draw(4)
        for g in (4, 5, 6):
            gen(g)
            doc = response(exemplar=force("D"), status=200)
            doc["totally_new_field"] = [1]
            write_response(g, doc)
            code = expect_abort(lambda: sb.await_response(g), f"schema fail {g}")
            if code is not None:
                break
            draw(g + 1)
        check("third consecutive schema failure aborts (schema_failure_cascade)",
              code == 3 and g == 6
              and (terminal().get("abort") or {}).get("reason") == "schema_failure_cascade",
              f"code={code} g={g}")
        check("confabulation counts every schema failure",
              terminal().get("confabulation", {}).get("schema_failures") == 5)
    finally:
        sb._MAX_SCHEMA_STREAK = saved


for _fn in SCENARIOS:
    try:
        _fn()
    except BaseException as _e:  # noqa: BLE001 - report, then keep going
        check(f"{_fn.__name__} completed without crashing", False,
              f"{type(_e).__name__}: {_e}")
        try:
            sb._aborted = False
        except Exception:
            pass

shutil.rmtree(RUN_DIR, ignore_errors=True)
print()
print("HARDENING UNIT TEST: " + ("PASS" if fail == 0 else "FAIL"))
sys.exit(fail)
