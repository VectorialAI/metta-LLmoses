"""Canonical per-call artifact identities shared by both responder paths."""
import os
import re
import json

READY_RE = re.compile(r"^run-([1-9][0-9]*)-step-([1-9][0-9]*)-call-([1-4])$")


def parse_step(step):
    match = re.fullmatch(r"([1-9][0-9]*)-call-([1-4])", str(step))
    if not match:
        raise ValueError("step must be G-call-C (C is 1..4)")
    return int(match[1]), int(match[2])


def paths(run_dir, seq, step):
    parse_step(step)
    seq = int(seq)
    if seq < 1:
        raise ValueError("run sequence must be positive")
    base, run = os.path.abspath(run_dir), f"run-{seq}"
    name = f"step-{step}.json"
    result = {section: os.path.join(base, directory, run, name)
              for section, directory in (("state", "state"), ("action", "action"),
                  ("utilities", "utilities"), ("trace", "traces"))}
    result.update(run_config=os.path.join(base, "state", run, "run_config.json"),
                  ready=os.path.join(base, "ready", f"{run}-step-{step}"),
                  response=os.path.join(base, "response", f"{run}-step-{step}"))
    return result


def key(seq, step):
    generation, call = parse_step(step)
    return int(seq), generation, call


def ready_entries(run_dir):
    root = os.path.join(run_dir, "ready")
    if not os.path.isdir(root):
        return []
    rows = []
    for name in os.listdir(root):
        match = READY_RE.fullmatch(name)
        if match and os.path.isfile(os.path.join(root, name)):
            rows.append((match[1], f"{match[2]}-call-{match[3]}", os.path.join(root, name)))
    return sorted(rows, key=lambda row: key(row[0], row[1]))


def latest_terminal(run_dir):
    root = os.path.join(run_dir, "state")
    if not os.path.isdir(root):
        return None
    runs = [int(n[4:]) for n in os.listdir(root) if re.fullmatch(r"run-[1-9][0-9]*", n)]
    if not runs:
        return None
    seq = max(runs)
    path = os.path.join(root, f"run-{seq}", "terminal.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return str(seq), path, doc.get("run_verdict")
    except (OSError, ValueError):
        return None
