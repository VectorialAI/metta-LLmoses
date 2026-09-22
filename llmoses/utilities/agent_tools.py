#!/usr/bin/env python3
"""Command-line tools for an agent acting as an LLMOSES responder.

All success and operational-error output is one JSON object, making the tools
safe to drive from a coding-agent loop.  The response writer deliberately uses
the same utilities/trace/response ordering as ``llmoses_watcher.py``.
"""

import argparse
import json
import os
import re
import signal
import sys
import time

import call_paths
import protocol_version
import responder_control as rc
import response_template
import utility_schema


EXIT_INVALID = 3
EXIT_OWNERSHIP = 5
EXIT_PIN = 6
EXIT_TERMINAL = 10
EXIT_ABORT = 11
EXIT_TIMEOUT = 12


def _print(doc):
    print(json.dumps(doc, sort_keys=True, separators=(",", ":")))


def _json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


_paths = call_paths.paths
_generation_key = call_paths.key
_ready_entries = call_paths.ready_entries


def _terminals(run_dir):
    latest = call_paths.latest_terminal(run_dir)
    return [latest] if latest else []


def _read_values(value_path):
    if value_path == "-":
        text = sys.stdin.read()
    else:
        with open(value_path, encoding="utf-8") as fh:
            text = fh.read()
    values = json.loads(text)
    if not isinstance(values, dict):
        raise ValueError("values must be a JSON object")
    return values


def _text_arg(value):
    if value and value.startswith("@"):
        with open(value[1:], encoding="utf-8") as fh:
            return fh.read()
    return value or ""


def _outcome(args, slot_count, supplied):
    strategy = getattr(args, "context_strategy", None) or os.environ.get(
        "LLMOSES_CONTEXT_STRATEGY", "full_history")
    dropped = []
    if getattr(args, "dropped", None):
        for item in args.dropped.split(","):
            if item:
                dropped.append(item)
    attempts = int(getattr(args, "attempts", 1))
    mode = getattr(args, "coverage_mode", "sparse")
    chars = int(getattr(args, "context_chars", 0) or 0)
    compressed = bool(getattr(args, "compressed", False))
    # W-22: `--history FILE` binds the exact `history` result the agent used
    # into the response, so instrumentation is measured, not asserted.
    hist_path = getattr(args, "history", None)
    if hist_path:
        with open(hist_path, encoding="utf-8") as fh:
            hist = json.load(fh)
        strategy = hist.get("strategy") or strategy
        chars = int(hist.get("chars") or chars or 0)
        compressed = bool(hist.get("compressed", compressed))
        dropped = list(hist.get("dropped") or dropped)
    if not chars:
        # W-22 instrumentation must not be voluntary: without an explicit
        # figure, account for every file the agent declares it read.
        for path in (getattr(args, "read_files", None) or []):
            try:
                chars += os.path.getsize(path)
            except OSError:
                pass
    return {
        "attempts": attempts,
        "retried": attempts > 1,
        "coverage": {"mode": mode,
                     "requested": slot_count,
                     "supplied": supplied},
        "protocol_version": protocol_version.compute(),
        "context": {"strategy": strategy,
                    "chars": chars,
                    "compressed": compressed,
                    "dropped": dropped},
    }


def _trace_doc(run_dir, seq, gen, paths, doc, outcome, rationale, read_files):
    now = int(time.time() * 1000)
    strategy = (outcome.get("context") or {}).get("strategy")
    return {
        "schema_version": "agent-trace-v2",
        "record_type": "AgentTrace",
        "authored_by": "agent",
        "stub": False,
        "run_seq": int(seq),
        "generation": call_paths.parse_step(gen)[0],
        "call": call_paths.parse_step(gen)[1],
        "input_state": rc.read_json(paths["state"]),
        "timestamp_ms": now,
        "ready_sentinel": "ready/run-%s-step-%s" % (seq, gen),
        "input_artifacts": {
            "state_path": paths["state"], "action_path": paths["action"],
            "run_config_path": paths["run_config"],
            "native_log_path": os.path.join(os.path.abspath(run_dir),
                                             "moses_native_log.jsonl"),
        },
        "read_files": read_files,
        "prompt_context_manifest": [],
        "provider": "agent",
        "raw_model_response": "{}",
        "parsed_utility_response": doc,
        "audit_reasoning": [rationale] if rationale else [],
        "parse_diagnostics": [],
        "status": doc.get("status"),
        "outcome": outcome,
        "protocol_version": outcome.get("protocol_version"),
        "context_strategy": strategy,
        "summary": "agent authored response for run-%s step-%s" % (seq, gen),
    }


def _write_response(run_dir, seq, gen, doc, outcome, rationale, read_files,
                    values):
    paths = _paths(run_dir, seq, gen)
    trace = _trace_doc(run_dir, seq, gen, paths, doc, outcome, rationale,
                       read_files)
    trace["raw_model_response"] = json.dumps(values, sort_keys=True)
    if os.path.exists(rc.control_path(run_dir, "pause")):
        raise ValueError("run is paused; resume before responding")
    if not os.path.isfile(paths["ready"]) or os.path.exists(paths["response"]):
        raise ValueError("call is not outstanding (stale or duplicate response)")
    rc.write_json_atomic(paths["utilities"], doc, fsync=True)
    rc.write_json_atomic(paths["trace"], trace, fsync=True)
    rc.write_json_atomic(paths["response"], {"step": gen}, fsync=True)
    consumed = os.path.join(os.path.abspath(run_dir), "ready", ".consumed")
    os.makedirs(consumed, exist_ok=True)
    try:
        os.replace(paths["ready"], os.path.join(consumed,
                                                  os.path.basename(paths["ready"])))
    except FileNotFoundError:
        pass
    return paths


def command_claim(args):
    try:
        version = protocol_version.check_pin()
    except protocol_version.ProtocolPinError as exc:
        _print({"error": str(exc)})
        return EXIT_PIN
    try:
        # --takeover forces; otherwise defer to LLMOSES_RESPONDER_TAKEOVER.
        record = rc.claim(args.rundir, args.mode, "agent", version,
                          args.context_strategy or os.environ.get(
                              "LLMOSES_CONTEXT_STRATEGY", "full_history"),
                          args.session, True if args.takeover else None)
    except rc.OwnershipConflict as exc:
        _print({"error": str(exc)})
        return EXIT_OWNERSHIP
    # The session token IS the agent's identity for every later tool call
    # (respond/abstain/release): pass it as --session or export it as
    # LLMOSES_RESPONDER_SESSION. A pid would not survive across CLI calls.
    record = dict(record)
    record["session"] = (record.get("owner") or {}).get("session")
    _print(record)
    return 0


def command_release(args):
    try:
        _print(rc.release(args.rundir, session=args.session, force=args.force)
               or {"released": False})
    except rc.OwnershipConflict as exc:
        _print({"error": str(exc)})
        return EXIT_OWNERSHIP
    return 0


def command_heartbeat(args):
    alive = (lambda: rc.pid_alive(args.watch_pid)) if args.watch_pid else None
    heartbeat = rc.Heartbeat(args.rundir, "agent", args.interval,
                             session=rc._session_from_env(args.session))
    if args.once:
        heartbeat.beat(force=True)
        _print(rc.read_json(rc.control_path(args.rundir, "heartbeat")) or {})
        return 0
    stop = [False]
    def stop_loop(signum, frame):
        stop[0] = True
    signal.signal(signal.SIGINT, stop_loop)
    signal.signal(signal.SIGTERM, stop_loop)
    while not stop[0] and (alive is None or alive()):
        heartbeat.beat(force=True)
        time.sleep(max(0.01, float(args.interval)))
    _print(rc.read_json(rc.control_path(args.rundir, "heartbeat")) or {})
    return 0


def command_wait(args):
    deadline = time.monotonic() + float(args.timeout)
    while True:
        pause = rc.read_json(rc.control_path(args.rundir, "pause"))
        if pause:
            _print({"event": "paused", **pause})
            return 13
        ready = _ready_entries(args.rundir)
        if ready:
            seq, gen, unused = ready[0]
            paths = _paths(args.rundir, seq, gen)
            _print({"event": "ready", "seq": seq, "gen": gen,
                    "state_path": paths["state"], "action_path": paths["action"],
                    "slots_command": "slots RUNDIR SEQ G-call-C"})
            return 0
        terminals = _terminals(args.rundir)
        if terminals:
            seq, path, verdict = terminals[0]
            _print({"event": "terminal", "seq": seq, "gen": None,
                    "state_path": None, "action_path": None,
                    "run_config_path": os.path.join(args.rundir, "state",
                                                     "run-%s" % seq,
                                                     "run_config.json"),
                    "terminal_path": path, "verdict": verdict})
            return EXIT_TERMINAL
        if rc.abort_requested(args.rundir):
            _print({"event": "abort", "seq": None, "gen": None,
                    "state_path": None, "action_path": None,
                    "run_config_path": None})
            return EXIT_ABORT
        if time.monotonic() >= deadline:
            _print({"event": "timeout", "seq": None, "gen": None,
                    "state_path": None, "action_path": None,
                    "run_config_path": None})
            return EXIT_TIMEOUT
        time.sleep(max(0.01, float(args.poll)))


def command_slots(args):
    paths = _paths(args.rundir, args.seq, args.gen)
    slots = response_template.build_slots(_json(paths["state"]),
                                          _json(paths["run_config"]))
    schema = response_template.json_schema(slots)
    if args.schema_out:
        rc.write_json_atomic(os.path.abspath(args.schema_out), schema)
    if args.table:
        for key in sorted(slots):
            spec = slots[key]
            print("%s | %s | %s" % (key, spec["domain"],
                                     json.dumps(spec.get("meta", {}), sort_keys=True)))
    else:
        _print({"slot_count": len(slots), "slots": slots, "schema": schema})
    return 0


def _assembled(args, abstain=False):
    paths = _paths(args.rundir, args.seq, args.gen)
    state, config = _json(paths["state"]), _json(paths["run_config"])
    slots = response_template.build_slots(state, config)
    values = {} if abstain else _read_values(args.values)
    outcome = _outcome(args, len(slots), len(values))
    if abstain:
        status = int(args.status)
        outcome["detail"] = _text_arg(args.reason)
        if status in (422, 500):
            outcome["error_class"] = "input" if status == 422 else "responder_failure"
        doc = response_template.assemble(slots, {}, config, decline=True,
                                         status=status, outcome=outcome)
    else:
        doc = response_template.assemble(slots, values, config,
                                         decline=not bool(values),
                                         status=204 if not values else None,
                                         outcome=outcome)
    return paths, slots, values, outcome, doc


def command_respond(args):
    try:
        paths, slots, values, outcome, doc = _assembled(args)
    except (KeyError, ValueError, AssertionError, json.JSONDecodeError) as exc:
        text = str(exc)
        key = None
        match = re.search(r"unknown slot: ['\"]?([^'\"]+)", text)
        if match:
            key = match.group(1)
        else:
            try:
                paths = _paths(args.rundir, args.seq, args.gen)
                slots = response_template.build_slots(_json(paths["state"]),
                                                      _json(paths["run_config"]))
                values = _read_values(args.values)
                for candidate in sorted(values):
                    try:
                        response_template.assemble(slots, {candidate: values[candidate]},
                                                   _json(paths["run_config"]))
                    except (KeyError, ValueError, AssertionError):
                        key = candidate
                        break
            except Exception:
                pass
        _print({"error": text, "unknown_or_bad_key": key})
        return EXIT_INVALID
    if not rc.owns(args.rundir, "agent", session=args.session):
        _print({"error": "this session does not hold the agent responder claim "
                         "(claim first; pass --session or set "
                         "LLMOSES_RESPONDER_SESSION)"})
        return EXIT_OWNERSHIP
    with rc.response_write_guard(args.rundir, "agent", args.session):
        result = _write_response(args.rundir, args.seq, args.gen, doc, outcome,
                                 _text_arg(args.rationale), args.read_files, values)
    _print({"written": result, "status": doc["status"],
            "slot_count": len(slots), "supplied": len(values)})
    return 0


def command_abstain(args):
    try:
        paths, slots, values, outcome, doc = _assembled(args, abstain=True)
    except Exception as exc:
        # A capture failure can itself make slot enumeration impossible.  The
        # failure still needs an answer so MOSES can make its status decision
        # — and that answer is 422 (input unusable), never a healthy 204: a
        # deliberate abstention cannot be claimed over input we could not
        # read. An explicitly requested 500 (own failure) is kept.
        values, slots = {}, {}
        status = 500 if int(args.status) == 500 else 422
        outcome = {"attempts": 1, "retried": False,
                   "coverage": {"mode": "sparse", "requested": 0, "supplied": 0},
                   "protocol_version": protocol_version.compute(),
                   "context": {"strategy": "full_history", "chars": 0,
                               "compressed": False, "dropped": []},
                   "detail": f"{_text_arg(args.reason)} [input unusable: {exc!r}]"[:500],
                   "error_class": "input" if status == 422 else "responder_failure"}
        generation, call = call_paths.parse_step(args.gen)
        doc = utility_schema.neutral({"run_seq": int(args.seq),
            "generation": generation, "call": call}, status, outcome)
    if not rc.owns(args.rundir, "agent", session=args.session):
        _print({"error": "this session does not hold the agent responder claim "
                         "(claim first; pass --session or set "
                         "LLMOSES_RESPONDER_SESSION)"})
        return EXIT_OWNERSHIP
    with rc.response_write_guard(args.rundir, "agent", args.session):
        result = _write_response(args.rundir, args.seq, args.gen, doc, outcome,
                                 _text_arg(args.rationale), [], values)
    _print({"written": result, "status": doc["status"],
            "slot_count": len(slots), "supplied": 0})
    return 0


def command_trace(args):
    paths = _paths(args.rundir, args.seq, args.gen)
    trace = rc.read_json(paths["trace"])
    if trace is None:
        generation, call = call_paths.parse_step(args.gen)
        trace = {"schema_version": "agent-trace-v2", "record_type": "AgentTrace",
                 "authored_by": "agent", "stub": False, "run_seq": int(args.seq),
                 "generation": generation, "call": call, "timestamp_ms": int(time.time() * 1000),
                 "audit_reasoning": []}
    trace.setdefault("audit_reasoning", []).append(_text_arg(args.note))
    rc.write_json_atomic(paths["trace"], trace)
    _print({"written": paths["trace"]})
    return 0


def _states(run_dir, seq):
    directory = os.path.join(run_dir, "state", "run-%s" % seq)
    rows = []
    try:
        names = os.listdir(directory)
    except OSError:
        return rows
    for name in names:
        match = re.match(r"^step-([1-9][0-9]*-call-[1-4])\.json$", name)
        if match:
            rows.append((match.group(1), _json(os.path.join(directory, name))))
    return sorted(rows, key=lambda row: _generation_key(seq, row[0]))


def _compact(doc):
    return json.dumps(doc, separators=(",", ":"), sort_keys=True)


def _digest(gen, state):
    members = (state.get("metapopulation") or {}).get("members") or []
    ids = [row.get("program_id") for row in members if row.get("program_id")]
    scores = [(row.get("cscore") or {}).get("penalized_score") for row in members]
    scores = [score for score in scores if isinstance(score, (int, float))]
    labels = []
    for row in ((state.get("atom_evidence") or {}).get("atom_appearances") or []):
        atom = row.get("atom")
        if atom is not None:
            labels.append(str(atom))
    return {"gen": int(gen) if str(gen).isdigit() else gen,
            "size": len(_compact(state)), "best_score": max(scores) if scores else None,
            "member_ids": ids, "atom_labels": sorted(set(labels))}


def _summary_path(run_dir, seq):
    return os.path.join(os.path.abspath(run_dir), "context", f"run-{int(seq)}", "summary.md")


def command_history(args):
    rows = _states(args.rundir, args.seq)
    current = str(args.gen) if args.gen is not None else (rows[-1][0] if rows else None)
    if current:
        rows = [(step, state) for step, state in rows
                if _generation_key(args.seq, step) <= _generation_key(args.seq, current)]
    # Keep states, replies, and rationale together; never leak a future call.
    records = [(step, {"input_state": state,
                "trace": rc.read_json(_paths(args.rundir, args.seq, step)["trace"])})
               for step, state in rows]
    budget = max(0, int(args.budget))
    selected, summary = list(records), ""
    if args.strategy in ("per_generation", "rolling_summary"):
        selected = [(step, doc) for step, doc in records if step == current]
    if args.strategy == "rolling_summary":
        path = _summary_path(args.rundir, args.seq)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                summary = fh.read()
        # Declared, logged summary truncation; the current request stays intact.
        summary = summary[-budget:] if budget else ""
    if args.strategy == "retrieval":
        query = set(re.findall(r"\w+", (args.query or "").lower()))
        selected.sort(key=lambda item: (item[0] == current,
            len(set(re.findall(r"\w+", _compact(item[1]).lower())) & query),
            _generation_key(args.seq, item[0])), reverse=True)
    elif args.strategy == "full_history":
        selected.reverse()
    chosen = []
    for item in selected:
        trial = chosen + [item]
        if item[0] == current or len(_compact([doc for _, doc in trial])) + len(summary) <= budget:
            chosen.append(item)
    chosen.sort(key=lambda item: _generation_key(args.seq, item[0]))
    included = [step for step, _ in chosen]
    dropped = [step for step, _ in records if step not in included]
    payload = {"history": [doc for _, doc in chosen], "summary": summary}
    result = {"strategy": args.strategy, "budget": budget, "chars": len(_compact(payload)),
              "compressed": bool(dropped) or args.strategy == "rolling_summary",
              "dropped": dropped, "included": included, "payload": payload,
              "over_budget": len(_compact(payload)) > budget}
    _print(result)
    return 0


def command_summarize(args):
    path = _summary_path(args.rundir, args.seq)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("[%d] %s\n" % (int(time.time() * 1000), _text_arg(args.text)))
        fh.flush()
        os.fsync(fh.fileno())
    _print({"written": path})
    return 0


def command_resume(args):
    pause = rc.read_json(rc.control_path(args.rundir, "pause"))
    if not pause:
        raise ValueError("no paused call to resume")
    request = {key: pause[key] for key in ("run_seq", "generation", "call")}
    rc.write_json_atomic(rc.control_path(args.rundir, "resume"), request, fsync=True)
    _print({"resume_requested": request, "checkpoint": pause.get("checkpoint")})
    return 0


def command_abort(args):
    _print(rc.request_abort(args.rundir, args.reason, "agent", args.detail))
    return 0


def command_status(args):
    outstanding = [os.path.basename(row[2]) for row in _ready_entries(args.rundir)]
    terminal = {seq: verdict for seq, unused, verdict in _terminals(args.rundir)}
    _print({"responder": rc.responder(args.rundir),
            "heartbeat": rc.read_json(rc.control_path(args.rundir, "heartbeat")),
            "abort": rc.read_json(rc.control_path(args.rundir, "abort")),
            "pause": rc.read_json(rc.control_path(args.rundir, "pause")),
            "outstanding_ready": outstanding, "terminal": terminal,
            "protocol_version": protocol_version.compute()})
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("claim")
    p.add_argument("rundir")
    p.add_argument("--mode", default="agent:agent")
    p.add_argument("--context-strategy")
    p.add_argument("--session")
    p.add_argument("--takeover", action="store_true")
    p.set_defaults(func=command_claim)
    p = sub.add_parser("release")
    p.add_argument("rundir")
    p.add_argument("--session")
    p.add_argument("--force", action="store_true",
                   help="operator override: release a claim you do not hold")
    p.set_defaults(func=command_release)
    p = sub.add_parser("heartbeat")
    p.add_argument("rundir")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--watch-pid", type=int)
    p.add_argument("--once", action="store_true")
    p.add_argument("--session")
    p.set_defaults(func=command_heartbeat)
    p = sub.add_parser("wait")
    p.add_argument("rundir")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--poll", type=float, default=.2)
    p.set_defaults(func=command_wait)
    p = sub.add_parser("slots")
    p.add_argument("rundir")
    p.add_argument("seq")
    p.add_argument("gen")
    p.add_argument("--table", action="store_true")
    p.add_argument("--schema-out")
    p.set_defaults(func=command_slots)
    p = sub.add_parser("respond")
    p.add_argument("rundir")
    p.add_argument("seq")
    p.add_argument("gen")
    p.add_argument("--values", required=True)
    p.add_argument("--rationale")
    p.add_argument("--attempts", type=int, default=1)
    p.add_argument("--coverage-mode", choices=("sparse", "full"), default="sparse")
    p.add_argument("--context-strategy")
    p.add_argument("--context-chars", type=int, default=0)
    p.add_argument("--compressed", action="store_true")
    p.add_argument("--dropped")
    p.add_argument("--read-files", nargs="*", default=[])
    p.add_argument("--history", help="JSON file holding the `history` result "
                   "used for this estimate (binds W-22 context instrumentation)")
    p.add_argument("--session", help="agent session token from claim "
                   "(or LLMOSES_RESPONDER_SESSION)")
    p.set_defaults(func=command_respond)
    p = sub.add_parser("abstain")
    p.add_argument("rundir")
    p.add_argument("seq")
    p.add_argument("gen")
    p.add_argument("--reason", required=True)
    p.add_argument("--status", choices=("204", "422", "500"), default="204")
    p.add_argument("--rationale")
    p.add_argument("--session")
    p.set_defaults(func=command_abstain)
    p = sub.add_parser("trace")
    p.add_argument("rundir")
    p.add_argument("seq")
    p.add_argument("gen")
    p.add_argument("--note", required=True)
    p.set_defaults(func=command_trace)
    p = sub.add_parser("abort")
    p.add_argument("rundir")
    p.add_argument("--reason", required=True)
    p.add_argument("--detail")
    p.set_defaults(func=command_abort)
    p = sub.add_parser("history")
    p.add_argument("rundir")
    p.add_argument("seq")
    p.add_argument("--strategy", choices=utility_schema.CONTEXT_STRATEGIES, required=True)
    p.add_argument("--budget", type=int, required=True)
    p.add_argument("--gen")
    p.add_argument("--query")
    p.set_defaults(func=command_history)
    p = sub.add_parser("summarize")
    p.add_argument("rundir")
    p.add_argument("seq")
    p.add_argument("--text", required=True)
    p.set_defaults(func=command_summarize)
    p = sub.add_parser("resume")
    p.add_argument("rundir")
    p.set_defaults(func=command_resume)
    p = sub.add_parser("status")
    p.add_argument("rundir")
    p.set_defaults(func=command_status)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return 0
    except rc.OwnershipConflict as exc:
        _print({"error": str(exc)})
        return EXIT_OWNERSHIP
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _print({"error": str(exc)})
        return EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
