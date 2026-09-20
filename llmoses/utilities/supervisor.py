#!/usr/bin/env python3
"""Small observable supervisor for one or more LLMOSES responder sessions."""

import argparse
import json
import os
import re
import sys
import time

import responder_control as rc

_READY_RE = re.compile(r"^run-([^-]+)-step-([^-]+)$")


def _number(value):
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _ready(run_dir):
    directory = os.path.join(run_dir, "ready")
    rows = []
    try:
        names = os.listdir(directory)
    except OSError:
        return rows
    for name in names:
        match = _READY_RE.match(name)
        if match and os.path.isfile(os.path.join(directory, name)):
            rows.append((match.group(1), match.group(2), name))
    return sorted(rows, key=lambda row: (_number(row[0]), _number(row[1])))


def _terminal(run_dir):
    root = os.path.join(run_dir, "state")
    found = []
    try:
        runs = os.listdir(root)
    except OSError:
        return None
    for name in runs:
        path = os.path.join(root, name, "terminal.json")
        doc = rc.read_json(path) if name.startswith("run-") else None
        if doc and doc.get("run_verdict"):
            found.append((_number(name[4:]), doc["run_verdict"]))
    # A driver may run several runMoses in one directory; the LATEST run's
    # terminal is the session's verdict (an earlier run finishing is not
    # "done" while a later run is still emitting).
    return sorted(found)[-1][1] if found else None


def parse_session(value):
    name, sep, rest = value.partition("=")
    if not sep or not name or not rest:
        raise argparse.ArgumentTypeError("session must be NAME=RUNDIR[:AGENT_PID[:MOSES_PID]]")
    fields = rest.split(":")
    if len(fields) > 3 or not fields[0]:
        raise argparse.ArgumentTypeError("invalid session specification")
    try:
        agent = int(fields[1]) if len(fields) > 1 and fields[1] else None
        moses = int(fields[2]) if len(fields) > 2 and fields[2] else None
    except ValueError as exc:
        raise argparse.ArgumentTypeError("PIDs must be integers") from exc
    return name, {"run_dir": fields[0], "agent_pid": agent, "moses_pid": moses,
                  "state": "running", "verdict": None, "reason": None}


def _status(session, first_seen, now, stall_s):
    run_dir = session["run_dir"]
    verdict = _terminal(run_dir)
    outstanding = _ready(run_dir)
    name = outstanding[0][2] if outstanding else None
    if name:
        first_seen.setdefault(name, now)
        age = now - first_seen[name]
    else:
        first_seen.clear()
        age = None
    agent_alive = (rc.pid_alive(session["agent_pid"])
                   if session["agent_pid"] is not None else None)
    moses_alive = (rc.pid_alive(session["moses_pid"])
                   if session["moses_pid"] is not None else None)
    reason = None
    if verdict:
        state = "done"
    elif rc.abort_requested(run_dir):
        state, verdict = "done", "aborted"
        reason = (rc.read_json(rc.control_path(run_dir, "abort")) or {}).get("reason")
    elif name and (stall_s <= 0 or age > stall_s):
        detail = "ready sentinel %s outstanding for %.3fs" % (name, age)
        rc.request_abort(run_dir, "agent_wedged", "supervisor", detail)
        state, verdict, reason = "done", "aborted", "agent_wedged"
    elif name and agent_alive is False:
        rc.request_abort(run_dir, "agent_dead", "supervisor",
                         "agent pid %s is not alive" % session["agent_pid"])
        state, verdict, reason = "done", "aborted", "agent_dead"
    elif moses_alive is False:
        state, verdict, reason = "done", "aborted", "moses_dead"
    else:
        state = "running"
    return {"state": state, "verdict": verdict, "reason": reason,
            "outstanding_ready": [row[2] for row in outstanding],
            "oldest_ready_age_s": age, "agent_alive": agent_alive,
            "moses_alive": moses_alive}


def run(sessions, stall_s, poll_s, once=False, max_wall_s=None):
    first_seen = {name: {} for name in sessions}
    counter, started = 0, time.monotonic()
    final = {}
    while True:
        counter += 1
        now = time.monotonic()
        views = {}
        for name, session in sessions.items():
            view = _status(session, first_seen[name], now, stall_s)
            session.update({key: view[key] for key in ("state", "verdict", "reason")})
            views[name] = view
        payload = {"counter": counter, "ts_ms": int(time.time() * 1000),
                   "supervisor_pid": os.getpid(), "stall_s": stall_s,
                   "sessions": views}
        for session in sessions.values():
            rc.write_json_atomic(rc.control_path(session["run_dir"], "supervisor.json"),
                                 payload)
        final = views
        if once or all(view["state"] == "done" for view in views.values()):
            break
        if max_wall_s is not None and now - started >= max_wall_s:
            # Backstop expiry must never look like successful supervision:
            # every session still running is aborted, loudly, before exit.
            for name, session in sessions.items():
                if views[name]["state"] != "done":
                    rc.request_abort(session["run_dir"], "supervisor_backstop",
                                     "supervisor",
                                     "supervisor wall-clock backstop %.1fs expired"
                                     % max_wall_s)
                    views[name].update({"state": "done", "verdict": "aborted",
                                        "reason": "supervisor_backstop"})
                    session.update({"state": "done", "verdict": "aborted",
                                    "reason": "supervisor_backstop"})
            payload["sessions"] = views
            for session in sessions.values():
                rc.write_json_atomic(rc.control_path(session["run_dir"],
                                                     "supervisor.json"), payload)
            final = views
            break
        time.sleep(max(0.01, poll_s))
    return final


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", action="append", required=True, type=parse_session)
    parser.add_argument("--stall-s", type=float, default=600.0)
    parser.add_argument("--poll-s", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-wall-s", type=float)
    args = parser.parse_args(argv)
    sessions = dict(args.session)
    if len(sessions) != len(args.session):
        parser.error("session names must be unique")
    views = run(sessions, args.stall_s, args.poll_s, args.once, args.max_wall_s)
    print(json.dumps({name: {"verdict": view["verdict"], "reason": view["reason"]}
                      for name, view in views.items()}, sort_keys=True))
    return 1 if any(view["verdict"] == "aborted" for view in views.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
