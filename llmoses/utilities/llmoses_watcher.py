#!/usr/bin/env python3
"""Consume four-call ready markers using a live estimator or deterministic fixture."""
import argparse
import json
import os
import signal
import sys
import time

import call_paths
import protocol_version
import responder_control as rc
import response_template
import utility_schema

MOCK_MODE = os.environ.get("LLMOSES_MOCK_UTILITY_MODE", "neutral")
CONTEXT_STRATEGY = os.environ.get("LLMOSES_CONTEXT_STRATEGY", "full_history")
POLL_S = float(os.environ.get("LLMOSES_WATCH_POLL_S", "0.1"))
_stop = False


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _request_stop(*unused):
    global _stop
    _stop = True


def _mock_utility(mode, state, config, gen=None):
    slots = response_template.build_slots(state, config)
    if mode == "neutral":
        return response_template.assemble(slots, {}, decline=True)
    if mode not in ("identity", "prefer_worst", "pair_policy"):
        raise ValueError(f"unsupported mock mode {mode!r}")
    values = {key: (0.0 if spec["domain"] == "offset" else 1.0)
              for key, spec in slots.items() if spec["kind"] != "policy"}
    if "policy" in slots:
        values["policy"] = {}
    if mode == "prefer_worst" and state["call"] == 1 and state["rows"]:
        worst = min(state["rows"], key=lambda row: sum(row.get("scores", {}).values()))["row"]
        values[f"row:{worst}"] = slots[f"row:{worst}"]["maximum"]
    if mode == "prefer_worst" and state["call"] in (2, 4) and state["candidates"]:
        worst = min(state["candidates"], key=lambda m: m["cscore"]["penalized_score"])["program_id"]
        for key, spec in slots.items():
            if spec["domain"] == "offset":
                values[key] = spec["maximum"] if spec["identity"]["program_id"] == worst else spec["minimum"]
    if mode == "pair_policy" and state["call"] == 3 and state["pairs"]:
        values["policy"] = {"base": [{"pair": state["pairs"][0],
                                       "weight": config["experiment"]["utility_max"]}], "rules": []}
    return response_template.assemble(slots, values)


def _history(run_dir, seq, step):
    root = os.path.join(run_dir, "traces", f"run-{seq}")
    rows = []
    if not os.path.isdir(root):
        return rows
    for name in os.listdir(root):
        if not name.startswith("step-") or not name.endswith(".json"):
            continue
        previous = name[5:-5]
        if call_paths.key(seq, previous) < call_paths.key(seq, step):
            rows.append((call_paths.key(seq, previous), _load_json(os.path.join(root, name))))
    return [doc for unused, doc in sorted(rows)]


def _handle_step(run_dir, seq, step, dirs=None):
    paths = call_paths.paths(run_dir, seq, step)
    state, config = _load_json(paths["state"]), _load_json(paths["run_config"])
    trace = {}
    if MOCK_MODE == "live":
        import live_estimator
        try:
            live_estimator.check_timeout_invariant(config["handshake"]["response_timeout_s"])
            doc, trace = live_estimator.estimate(state, config, step, history=_history(run_dir, seq, step))
        except (live_estimator.TimeoutInvariantError, ValueError) as exc:
            doc = utility_schema.neutral(state, 503, {"error_class": "configuration", "detail": str(exc)})
    else:
        doc = _mock_utility(MOCK_MODE, state, config)
    clean, report = utility_schema.ingest(doc, state, config["experiment"])
    if clean is None:
        clean = utility_schema.neutral(state, 500, {"error_class": "schema", "detail": str(report)})
    if report["dropped"]:
        clean.setdefault("outcome", {})["salvage"] = {
            "requested": report["requested"], "survived": report["survived"]}
    clean.setdefault("outcome", {})["protocol_version"] = protocol_version.compute()
    trace.update({"schema_version": "agent-trace-v2", "record_type": "AgentTrace",
                  "run_seq": int(seq), "generation": state["generation"], "call": state["call"],
                  "input_state": state, "parsed_utility_response": clean,
                  "ingest_report": report, "context_strategy": CONTEXT_STRATEGY})
    # Trace and utility are durable before the response marker is published.
    with rc.response_write_guard(run_dir, "watcher"):
        rc.write_json_atomic(paths["utilities"], clean, fsync=True)
        rc.write_json_atomic(paths["trace"], trace, fsync=True)
    return paths["utilities"], paths["trace"]


def _scan_and_process(run_dir, dirs=None, consumed_dir=None):
    consumed_dir = consumed_dir or os.path.join(run_dir, "ready", ".consumed")
    os.makedirs(consumed_dir, exist_ok=True)
    if os.path.exists(rc.control_path(run_dir, "pause")):
        return 0
    processed = 0
    for seq, step, ready in call_paths.ready_entries(run_dir):
        if not rc.owns(run_dir, "watcher"):
            raise rc.OwnershipConflict("watcher no longer owns this run")
        if rc.abort_requested(run_dir):
            raise SystemExit(4)
        paths = call_paths.paths(run_dir, seq, step)
        if not os.path.exists(paths["response"]):
            _handle_step(run_dir, seq, step)
            with rc.response_write_guard(run_dir, "watcher"):
                rc.write_json_atomic(paths["response"], {"step": step}, fsync=True)
        if os.path.exists(ready):
            os.replace(ready, os.path.join(consumed_dir, os.path.basename(ready)))
        processed += 1
    return processed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    args = parser.parse_args()
    run_dir = os.path.abspath(args.run_dir)
    if MOCK_MODE not in ("neutral", "identity", "prefer_worst", "pair_policy", "live"):
        parser.error("legacy mock modes were retired; use neutral/identity/prefer_worst/pair_policy/live")
    version = protocol_version.check_pin()
    rc.claim(run_dir, f"watcher:{MOCK_MODE}", "watcher", version, CONTEXT_STRATEGY)
    heartbeat = rc.Heartbeat(run_dir, "watcher").start()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    try:
        while not _stop and not os.path.exists(rc.control_path(run_dir, "stop")):
            if rc.abort_requested(run_dir):
                return 4
            _scan_and_process(run_dir)
            time.sleep(POLL_S)
        _scan_and_process(run_dir)
        return 0
    finally:
        heartbeat.stop()
        if rc.owns(run_dir, "watcher"):
            rc.release(run_dir)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (rc.OwnershipConflict, protocol_version.ProtocolPinError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(5)
