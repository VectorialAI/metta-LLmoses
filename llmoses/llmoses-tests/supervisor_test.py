#!/usr/bin/env python3
"""Host-only supervision tests."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SUPERVISOR = os.path.join(ROOT, "utilities", "supervisor.py")
fail = 0


def check(label, ok, detail=""):
    global fail
    print("  %s: %s%s" % ("PASS" if ok else "FAIL", label,
                           (" " + detail) if detail else ""))
    if not ok: fail = 1


def run(*args):
    return subprocess.run([sys.executable, SUPERVISOR] + list(args), text=True,
                          capture_output=True)


def ready(directory):
    os.makedirs(os.path.join(directory, "ready"), exist_ok=True)
    open(os.path.join(directory, "ready", "run-1-step-1"), "w").close()


with tempfile.TemporaryDirectory() as root:
    wedged = os.path.join(root, "wedged"); ready(wedged)
    proc = run("--session", "w=" + wedged, "--stall-s", "0", "--once")
    abort = json.load(open(os.path.join(wedged, "CONTROL", "abort")))
    check("stalled ready aborts wedged agent", proc.returncode == 1 and
          abort.get("reason") == "agent_wedged")
    done = os.path.join(root, "done")
    os.makedirs(os.path.join(done, "state", "run-1"))
    with open(os.path.join(done, "state", "run-1", "terminal.json"), "w") as fh:
        json.dump({"run_verdict": "ok"}, fh)
    proc = run("--session", "d=" + done, "--once")
    status = json.load(open(os.path.join(done, "CONTROL", "supervisor.json")))
    check("terminal ok completes and writes observable heartbeat", proc.returncode == 0 and
          status.get("counter", 0) >= 1 and status["sessions"]["d"]["verdict"] == "ok")
    dead = os.path.join(root, "dead"); ready(dead)
    child = subprocess.Popen(["sleep", "0"]); child.wait()
    proc = run("--session", "a=%s:%d" % (dead, child.pid), "--stall-s", "600", "--once")
    abort = json.load(open(os.path.join(dead, "CONTROL", "abort")))
    check("dead agent with outstanding work aborts", proc.returncode == 1 and
          abort.get("reason") == "agent_dead")

    live = os.path.join(root, "live"); os.makedirs(os.path.join(live, "ready"))
    proc = run("--session", "l=" + live, "--poll-s", "0.01", "--max-wall-s", "0")
    abort = json.load(open(os.path.join(live, "CONTROL", "abort")))
    check("wall-clock backstop expiry aborts the unfinished session and exits 1",
          proc.returncode == 1 and abort.get("reason") == "supervisor_backstop"
          and json.loads(proc.stdout)["l"]["verdict"] == "aborted", proc.stdout)

print("\nSUPERVISOR TEST: %s" % ("PASS" if not fail else "FAIL"))
sys.exit(fail)
