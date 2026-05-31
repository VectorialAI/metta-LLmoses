#!/usr/bin/env python3
"""LLMOSES shadow-agent watcher (MVP, v0).

Emulates the real coding-agent topology: an independent process that observes
state appearing on disk and writes its own output files. It is NOT called by
MOSES and does NOT publish back to MOSES — fully filesystem-mediated.

Trigger contract: it watches <run>/ready/ for per-step sentinels dropped by the
emitter as the LAST action of each generation. Sentinel names are
``run-<seq>-step-<g>`` — the run-sequence prefix keeps the flat ready/ dir
collision-free even when multiple runMoses calls fire within the same process.
A sentinel's presence proves that state/run-<seq>/step-<g>.txt and
action/run-<seq>/step-<g>.txt are both complete, so there are no partial reads.

Stop/drain contract: on a stop signal (a <run>/CONTROL/stop flag file, or
SIGTERM) the watcher does a FINAL pass that processes every remaining sentinel
before exiting. Nothing emitted before stop is ever lost. The demo script
touches the stop flag only AFTER the MeTTa process returns (so the last
sentinel is guaranteed on disk), then waits on this process.

MVP handler: ``head -10`` of state-<g> and action-<g>, echoed into
utilities/run-<seq>/step-<g>.txt and traces/run-<seq>/step-<g>.txt with an
explicit STUB banner. Swapping this handler for a real provider call is the
only change needed to go from MVP to a live agent.

Directory layout produced:
  <run>/utilities/run-<seq>/step-<g>.txt  — stub utility estimate
  <run>/traces/run-<seq>/step-<g>.txt     — stub trace / receipt
  <run>/ready/.consumed/run-<seq>-step-<g> — moved-on-success marker
"""
import argparse
import os
import signal
import sys
import time

HEAD_N = 10

# TODO: consider replacing the 100 ms polling loop with an OS-native file-event
# mechanism such as inotify (Linux) or kqueue/FSEvents (macOS) — e.g. via the
# watchdog library — to reduce latency and CPU overhead on high-generation runs.
POLL_S = float(os.environ.get("LLMOSES_WATCH_POLL_S", "0.1"))

_stop = False


def _request_stop(*_):
    global _stop
    _stop = True


def _head(path, n=HEAD_N):
    """Return up to n lines from path; surface missing/empty files gracefully."""
    if not os.path.exists(path):
        return [f"<missing: {os.path.basename(path)}>"]
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= n:
                break
            out.append(line.rstrip("\n"))
    return out or ["<empty>"]


def _parse_sentinel(name):
    """Parse a sentinel filename ``run-<seq>-step-<g>`` into (seq, gen) strings.

    Returns (seq, gen) or (None, None) if the name does not match the expected
    format. The compound name encodes the per-run sequence so that the flat
    ready/ directory is collision-free even when multiple runMoses calls fire
    within the same MeTTa process.
    """
    if not name.startswith("run-"):
        return None, None
    rest = name[len("run-"):]
    sep = rest.find("-step-")
    if sep == -1:
        return None, None
    seq = rest[:sep]
    gen = rest[sep + len("-step-"):]
    if not seq or not gen:
        return None, None
    return seq, gen


def _handle_step(run_dir, seq, gen, dirs):
    """MVP stub handler: acknowledge receipt of state-<g> + action-<g>.

    Reads from the per-run subdirectories that mirror the emitter's layout:
      state/run-<seq>/step-<g>.txt
      action/run-<seq>/step-<g>.txt
    Writes into:
      utilities/run-<seq>/step-<g>.txt
      traces/run-<seq>/step-<g>.txt
    """
    state_p  = os.path.join(dirs["state"],  f"run-{seq}", f"step-{gen}.txt")
    action_p = os.path.join(dirs["action"], f"run-{seq}", f"step-{gen}.txt")
    state_head  = _head(state_p)
    action_head = _head(action_p)
    ts = int(time.time() * 1000)

    util_dir = os.path.join(dirs["utilities"], f"run-{seq}")
    os.makedirs(util_dir, exist_ok=True)
    util_p = os.path.join(util_dir, f"step-{gen}.txt")
    with open(util_p, "w", encoding="utf-8") as fh:
        fh.write(
            f"STUB_UTILITY_v0 run {seq} step {gen} ts {ts}"
            " (NOT a real utility estimate)\n"
        )
        fh.write(f"-- received state-{gen} (head {HEAD_N}) --\n")
        fh.write("\n".join(state_head) + "\n")
        fh.write(f"-- received action-{gen} (head {HEAD_N}) --\n")
        fh.write("\n".join(action_head) + "\n")

    trace_dir = os.path.join(dirs["traces"], f"run-{seq}")
    os.makedirs(trace_dir, exist_ok=True)
    trace_p = os.path.join(trace_dir, f"step-{gen}.txt")
    with open(trace_p, "w", encoding="utf-8") as fh:
        fh.write(f"STUB_TRACE_v0 run {seq} step {gen} ts {ts}\n")
        fh.write(
            f"observed ready/run-{seq}-step-{gen}; "
            f"read {len(state_head)} state line(s), "
            f"{len(action_head)} action line(s); wrote utilities + traces.\n"
        )

    return util_p, trace_p


def _scan_and_process(run_dir, dirs, consumed_dir):
    """Process every unconsumed ready/ sentinel once. Returns count processed."""
    ready_dir = dirs["ready"]
    if not os.path.isdir(ready_dir):
        return 0
    processed = 0
    for entry in sorted(os.scandir(ready_dir), key=lambda e: e.name):
        if not entry.is_file() or not entry.name.startswith("run-"):
            continue
        seq, gen = _parse_sentinel(entry.name)
        if seq is None:
            continue
        try:
            _handle_step(run_dir, seq, gen, dirs)
            # Move the marker out of ready/ — drain == "ready/ is empty".
            os.replace(entry.path, os.path.join(consumed_dir, entry.name))
            processed += 1
        except Exception as e:  # never let one bad step kill the watcher
            sys.stderr.write(f"[watcher] sentinel {entry.name} failed: {e}\n")
    return processed


def main():
    ap = argparse.ArgumentParser(
        description="LLMOSES shadow-agent watcher — watches ready/ sentinels "
                    "and writes stub utilities + traces."
    )
    ap.add_argument("run_dir", help="Path to the run root directory.")
    args = ap.parse_args()
    run_dir = os.path.abspath(args.run_dir)

    dirs = {
        "state":     os.path.join(run_dir, "state"),
        "action":    os.path.join(run_dir, "action"),
        "ready":     os.path.join(run_dir, "ready"),
        "utilities": os.path.join(run_dir, "utilities"),
        "traces":    os.path.join(run_dir, "traces"),
    }
    for k in ("utilities", "traces"):
        os.makedirs(dirs[k], exist_ok=True)
    consumed_dir = os.path.join(dirs["ready"], ".consumed")
    os.makedirs(consumed_dir, exist_ok=True)
    stop_flag = os.path.join(run_dir, "CONTROL", "stop")
    os.makedirs(os.path.dirname(stop_flag), exist_ok=True)

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT,  _request_stop)

    sys.stderr.write(f"[watcher] watching {dirs['ready']} (poll {POLL_S}s)\n")
    total = 0
    while not _stop and not os.path.exists(stop_flag):
        total += _scan_and_process(run_dir, dirs, consumed_dir)
        time.sleep(POLL_S)

    # Final drain: guarantee every sentinel on disk at stop time is handled.
    total += _scan_and_process(run_dir, dirs, consumed_dir)
    sys.stderr.write(f"[watcher] drained; processed {total} step(s); exiting.\n")


if __name__ == "__main__":
    main()
