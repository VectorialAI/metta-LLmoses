# Probe — `codex exec` streaming and error signatures

**Purpose.** The idle-timeout design (replacing the wall-clock
`LLMOSES_LIVE_TIMEOUT_S` with a progress-based liveness signal) depends on
whether `codex exec` emits output *during* execution or only at exit. This probe
answers that empirically, and opportunistically collects error signatures for the
W-13 classifier.

**Constraints:** read-only with respect to the repo. Creates one temp directory
per run and deletes it. Does not modify `live_estimator.py`. Total provider spend
is roughly 3–4 short calls.

---

## Questions this probe must answer

1. **Does output arrive incrementally, or all at once at exit?** This is the
   go/no-go for idle timeouts.
2. **What is the silent window while the model is reasoning?** This is the
   crux. If reasoning is silent and only the final message streams, then a
   healthy reasoning agent is indistinguishable from a wedged one for the whole
   reasoning duration, and the idle threshold must exceed the longest expected
   reasoning window — which may make it useless.
3. **Which stream carries progress** — stdout, stderr, or neither.
4. **Is output block-buffered through a pipe?** Critical and easy to miss: many
   CLIs line-buffer to a TTY but block-buffer to a pipe. `subprocess` uses pipes,
   so a probe run in a terminal would give a false positive. Part C tests the pty
   workaround if the pipe path is buffered.
5. **Is there a structured event / JSON mode, and does it report token usage?**
   A token cap is a better loop guard than a time cap.
6. **What do failures look like** — exit codes and stderr format.

---

## Part A/B/C — streaming harness

Save as `probe_codex_streaming.py`, run from anywhere.

```python
#!/usr/bin/env python3
"""Probe codex exec streaming behaviour. Read-only; no repo files touched."""
import os
import pty
import subprocess
import sys
import tempfile
import threading
import time

# High reasoning effort, small answer: maximises the SILENT REASONING window,
# which is the case the idle-timeout design has to survive.
PROMPT = (
    "Reason carefully and at length before answering. Do not skip steps.\n"
    "Question: in a 12-element set, how many distinct 3-element subsets\n"
    "contain at least one member of {a,b} and at least one member of {c,d},\n"
    "where a,b,c,d are four distinct elements? Show full reasoning, then\n"
    "give the final integer on its own line.\n"
)


def _reader(fd, label, events, t0, lock):
    while True:
        try:
            data = os.read(fd, 4096)
        except OSError:          # EIO on pty master when the child exits
            break
        if not data:
            break
        with lock:
            events.append({
                "t": round(time.monotonic() - t0, 3),
                "stream": label,
                "bytes": len(data),
                "head": data[:120].decode("utf-8", "replace").replace("\n", "\\n"),
            })


def run_pipe(cmd, prompt):
    events, lock = [], threading.Lock()
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, bufsize=0)
    ts = [threading.Thread(target=_reader,
                           args=(p.stdout.fileno(), "stdout", events, t0, lock)),
          threading.Thread(target=_reader,
                           args=(p.stderr.fileno(), "stderr", events, t0, lock))]
    for t in ts:
        t.daemon = True
        t.start()
    try:
        p.stdin.write(prompt.encode())
        p.stdin.close()
    except BrokenPipeError:
        pass
    rc = p.wait()
    for t in ts:
        t.join(timeout=5)
    return rc, events, round(time.monotonic() - t0, 3)


def run_pty(cmd, prompt):
    """Same, but give the child a pseudo-terminal so TTY-detecting CLIs
    line-buffer. Only meaningful if the pipe path showed block buffering."""
    events, lock = [], threading.Lock()
    t0 = time.monotonic()
    master, slave = pty.openpty()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=slave, stderr=slave,
                         bufsize=0, close_fds=True)
    os.close(slave)
    th = threading.Thread(target=_reader,
                          args=(master, "pty", events, t0, lock))
    th.daemon = True
    th.start()
    try:
        p.stdin.write(prompt.encode())
        p.stdin.close()
    except BrokenPipeError:
        pass
    rc = p.wait()
    th.join(timeout=5)
    try:
        os.close(master)
    except OSError:
        pass
    return rc, events, round(time.monotonic() - t0, 3)


def report(label, rc, events, total):
    print(f"\n=== {label} ===")
    print(f"exit={rc}  total_wall_s={total}  chunks={len(events)}")
    if not events:
        print("NO OUTPUT OBSERVED BEFORE EXIT")
        return
    events.sort(key=lambda e: e["t"])
    print(f"first_byte_at_s={events[0]['t']}  "
          f"(SILENT WINDOW = {events[0]['t']}s)")
    gaps, prev = [], 0.0
    for e in events:
        gaps.append(round(e["t"] - prev, 3))
        prev = e["t"]
    print(f"max_inter_chunk_gap_s={max(gaps)}")
    print("timeline (t, stream, bytes, head):")
    for e in events[:60]:
        print(f"  {e['t']:>8}  {e['stream']:<6} {e['bytes']:>6}  {e['head'][:90]}")
    if len(events) > 60:
        print(f"  ... {len(events) - 60} more chunks")


def main():
    model = os.environ.get("PROBE_MODEL", "gpt-5.5")
    effort = os.environ.get("PROBE_EFFORT", "high")

    with tempfile.TemporaryDirectory(prefix="probe-codex-") as td:
        out_path = os.path.join(td, "last-message.txt")
        cmd = ["codex", "exec", "-m", model,
               "-c", f"model_reasoning_effort={effort}",
               "--sandbox", "read-only", "--skip-git-repo-check",
               "--output-last-message", out_path, "-"]
        print("CMD:", " ".join(cmd))

        rc, ev, total = run_pipe(cmd, PROMPT)
        report("A: pipe (how subprocess actually sees it)", rc, ev, total)

        if not ev or (ev and ev[0]["t"] > total * 0.8):
            print("\n>>> pipe path looks block-buffered; testing pty fallback")
            rc2, ev2, total2 = run_pty(cmd, PROMPT)
            report("C: pty (TTY-detection workaround)", rc2, ev2, total2)


if __name__ == "__main__":
    main()
```

---

## Part D — capability surface

```bash
codex exec --help 2>&1 | tee codex-exec-help.txt
codex --version
```

Report specifically whether any of these exist:

- a JSON / structured event output mode (`--json`, `--event-format`, or similar)
- token usage reporting or a token cap flag
- a streaming flag, or a flag that suppresses/enables progress output

---

## Part E — error signatures (opportunistic)

For each case, record **exit code** and the **first 500 chars of stderr**.

1. **Auth failure** — run the Part A command with an invalid credential in the
   environment (e.g. an obviously bogus `OPENAI_API_KEY` / whatever `codex`
   reads). Safe and cheap.
2. **Network failure** — same command with networking disabled, or with a bogus
   proxy env var set.
3. **Quota / rate limit** — not reproducible on demand. Instead: grep any
   existing logs or shell history for previously observed quota or 429 stderr
   text and paste whatever exists.

If a class cannot be characterised, say so explicitly rather than guessing — the
classifier defaults unknown to **non-retryable + abort**, so an uncharacterised
class fails safe.

---

## What to report back

- Part A: `first_byte_at_s`, `max_inter_chunk_gap_s`, `total_wall_s`, and whether
  chunks arrived throughout or clustered at the end
- Which stream carried progress
- Part C result, if it ran
- Part D: the capability list above
- Part E: exit code + stderr head per reproducible class

---

## Interpretation

| Observation | Consequence for the design |
|---|---|
| Chunks arrive throughout, `max_gap` small (< ~30 s) | **Idle timeout is viable.** Set the threshold at ~3–5× observed max gap. This is the good case: it gives real reasoning-vs-wedged discrimination. |
| Chunks arrive only after a long silent window, then stream | Idle timeout works **only after first byte**. The silent window becomes a separate, longer "time to first byte" bound. Two thresholds, not one. |
| No output at all until exit (pipe), but pty streams | Buffering, not absence. Use the pty path in `_run_provider`. Adds moderate complexity; worth it. |
| No output until exit on both | **Idle timeout unavailable.** Fall back to: token cap (if Part D found one) as the loop guard, plus a generous absolute ceiling. The W-3 heartbeat then cannot reflect the innermost component, so it degrades to "watcher alive" only — and MOSES keeps a real deadline after all. This is the outcome that most changes the plan. |
| Structured event mode exists | Prefer it over raw-stream timing for everything above, and revisit loop detection (repeated identical tool calls become observable). |

The fourth row is the one to watch: it would reinstate a MOSES-side wall-clock
deadline, which the current plan proposes to delete.
