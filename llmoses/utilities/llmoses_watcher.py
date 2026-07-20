#!/usr/bin/env python3
"""Watch LLMOSES ready sentinels and write shadow-agent artifacts.

The watcher is a separate process. It reads <run>/ready/run-<seq>-step-<g>
markers after the emitter has finished state/action files, writes utility and
trace JSON under run-local directories, and drains remaining sentinels before
exit on stop.
"""
import argparse
import itertools
import json
import os
import signal
import sys
import time

import atom_evidence
import utility_schema

HEAD_N = 10

# TODO: consider replacing the 100 ms polling loop with an OS-native file-event
# mechanism such as inotify (Linux) or kqueue/FSEvents (macOS), e.g. via the
# watchdog library, to reduce latency and CPU overhead on high-generation runs.
POLL_S = float(os.environ.get("LLMOSES_WATCH_POLL_S", "0.1"))

# Deterministic mock estimator modes for Phase II lever validation. "neutral"
# (default) preserves the original stub byte-for-byte: pass=true, no guidance.
# Every other mode emits pass=false with exactly one lever's worth of
# deterministic utilities, derived from the step's own state/action JSON, so
# tests can assert the meta-loop obeyed them. Modes: ingest_probe, force_worst,
# cull_targets, retain_all, reverse_order, ratio_increase, atom_pair,
# ctx_parent_op, ctx_depth, ctx_polarity, ctx_zero_weights, synergy_pair,
# evidence_pair, live. Any error while building a mock/live response falls back to
# neutral — the handshake must never break.
MOCK_MODE = os.environ.get("LLMOSES_MOCK_UTILITY_MODE", "neutral")

_NEUTRAL_DOC = {
    "pass": True,
    "sampling_temperature": None,
    "exemplar_utilities": [],
    "atom_utility_prior": [],
    "combination_synergy": [],
    "feature_utility_levers": None,
    "culling_utilities": [],
    "complexity_ratio_delta": None,
    "comparator_bias": None,
}


def _alphabet_labels(run_config):
    alphabet = run_config.get("atom_alphabet") or {}
    labels = [a.get("label") for a in alphabet.get("atoms") or []
              if a.get("label") is not None]
    width = 3 if alphabet.get("problem_type") == "strategy" else 2
    return labels, width


def _load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _survivor_scores(state):
    """{program_id: penalized_score} over the post-merge population, joining
    pre-merge members with merge_summary.resize_cull.new_entrants (which carry
    scores) and restricting to resize_cull.survivors."""
    scores = {}
    for m in state.get("metapopulation", {}).get("members", []):
        pen = (m.get("cscore") or {}).get("penalized_score")
        if m.get("program_id") is not None and pen is not None:
            scores[m["program_id"]] = pen
    rc = (state.get("merge_summary") or {}).get("resize_cull") or {}
    for e in rc.get("new_entrants") or []:
        if isinstance(e, dict) and e.get("program_id") is not None \
                and e.get("penalized_score") is not None:
            scores[e["program_id"]] = e["penalized_score"]
    survivors = rc.get("survivors") or list(scores)
    return {pid: scores[pid] for pid in survivors if pid in scores}


def _mock_utility(mode, state, run_config, gen):
    """Build one deterministic non-neutral UtilityResponse for the given mode."""
    doc = dict(_NEUTRAL_DOC)
    doc["pass"] = False
    doc["sampling_temperature"] = 1.0
    surv = _survivor_scores(state)
    if mode == "ingest_probe":
        u = round(int(gen) / 100.0, 4)
        doc["exemplar_utilities"] = [{"program_id": p, "utility": u} for p in surv]
        doc["culling_utilities"] = [{"program_id": p, "retention_utility": 1.0}
                                    for p in surv]
        labels = [a.get("label") for a in
                  (run_config.get("atom_alphabet") or {}).get("atoms") or []]
        doc["atom_utility_prior"] = [{"atom": l, "utility": 0.5}
                                     for l in labels if l is not None]
        doc["complexity_ratio_delta"] = {"direction": "maintain", "magnitude": 0.0}
    elif mode == "force_worst":
        if not surv:
            raise ValueError("no scored survivors")
        target = min(surv, key=lambda p: surv[p])
        doc["exemplar_utilities"] = [
            {"program_id": p, "utility": 1.0 if p == target else 0.0}
            for p in surv]
    elif mode == "cull_targets":
        ordered = sorted(surv, key=lambda p: surv[p])       # worst first
        targets = set(ordered[:2])
        doc["culling_utilities"] = (
            [{"program_id": p, "retention_utility": 0.0 if p in targets else 1.0}
             for p in surv]
            # '*' = default for candidates born after this response: protected.
            + [{"program_id": "*", "retention_utility": 1.0}])
    elif mode == "retain_all":
        doc["culling_utilities"] = (
            [{"program_id": p, "retention_utility": 1.0} for p in surv]
            + [{"program_id": "*", "retention_utility": 1.0}])
    elif mode == "reverse_order":
        doc["comparator_bias"] = {
            "program_id_ordering": sorted(surv, key=lambda p: surv[p])}  # worst first
    elif mode == "ratio_increase":
        doc["complexity_ratio_delta"] = {"direction": "increase", "magnitude": 1.0}
    elif mode == "atom_pair":
        labels, width = _alphabet_labels(run_config)
        chosen = set(labels[:width])
        doc["atom_utility_prior"] = [
            {"atom": l, "utility": 1.0 if l in chosen else 0.0} for l in labels]
        doc["feature_utility_levers"] = {"aggregate_fn": "product",
                                         "lever_weights": {}}
    elif mode == "ctx_parent_op":
        # Global 0 everywhere, 1 under OR clauses: draws under AND must have a
        # zero pool (all degraded), draws under OR a full one (D-033).
        labels, _ = _alphabet_labels(run_config)
        doc["atom_utility_prior"] = (
            [{"atom": l, "utility": 0.0} for l in labels]
            + [{"atom": l, "utility": 1.0,
                "context": {"parent_operator": "OR"}} for l in labels])
        doc["feature_utility_levers"] = {"aggregate_fn": "product",
                                         "lever_weights": {"parent_operator": 1.0}}
    elif mode == "ctx_depth":
        # Same partition keyed on the depth band of the clause being created.
        labels, _ = _alphabet_labels(run_config)
        doc["atom_utility_prior"] = (
            [{"atom": l, "utility": 0.0} for l in labels]
            + [{"atom": l, "utility": 1.0,
                "context": {"depth_bucket": "mid"}} for l in labels])
        doc["feature_utility_levers"] = {"aggregate_fn": "product",
                                         "lever_weights": {"tree_depth": 1.0}}
    elif mode == "ctx_polarity":
        # Only negated positions score (order-encoded at the boolean draw:
        # ascending index pairs carry NOT on the first literal). mean, not
        # product: every pair has at most one negated slot.
        labels, _ = _alphabet_labels(run_config)
        doc["atom_utility_prior"] = (
            [{"atom": l, "utility": 0.0} for l in labels]
            + [{"atom": l, "utility": 1.0,
                "context": {"polarity": "-"}} for l in labels])
        doc["feature_utility_levers"] = {"aggregate_fn": "mean",
                                         "lever_weights": {"polarity": 1.0}}
    elif mode == "ctx_zero_weights":
        # Contextual + synergy entries present but every lever_weights axis
        # absent: all entries are inert, ingest prunes them, and the draw
        # gate must stay 0 — the native-selector off-switch converse for the
        # INNER axis plane (the outer plane converses are 12a-12e).
        labels, width = _alphabet_labels(run_config)
        chosen = set(labels[:width])
        doc["atom_utility_prior"] = [
            {"atom": l, "utility": 1.0, "context": {"parent_operator": "OR"}}
            for l in labels]
        doc["combination_synergy"] = [
            {"atoms": list(c), "utility": 1.0 if set(c) == chosen else 0.0}
            for c in itertools.combinations(labels, width)]
        doc["feature_utility_levers"] = {"aggregate_fn": "product",
                                         "lever_weights": {}}
    elif mode == "synergy_pair":
        # One atom set together = 1, every other combination = 0; no per-atom
        # prior at all — only the non-separable channel carries signal.
        labels, width = _alphabet_labels(run_config)
        chosen = set(labels[:width])
        doc["combination_synergy"] = [
            {"atoms": list(c), "utility": 1.0 if set(c) == chosen else 0.0}
            for c in itertools.combinations(labels, width)]
        doc["feature_utility_levers"] = {
            "aggregate_fn": "product",
            "lever_weights": {"combination_synergy": 1.0}}
    elif mode == "evidence_pair":
        # Same synergy-only channel, but choose the most frequent realized
        # cooccurrence in the current state evidence instead of the prefix.
        # Atom identities resolve through the canonical alphabet resolver
        # (an identity outside the alphabet raises -> loud mock failure).
        labels, width = _alphabet_labels(run_config)
        label_set = set(labels)
        resolve = atom_evidence.atom_label_resolver(
            run_config.get("atom_alphabet"))
        best = None
        for e in (state.get("atom_evidence") or {}).get("realized_cooccurrences") or []:
            members = []
            for m in e.get("members") or []:
                raw = m.get("atom") if isinstance(m, dict) else m
                members.append(resolve(raw))
            members = tuple(sorted(str(m) for m in members if m is not None))
            if e.get("width") != width or len(members) != width:
                continue
            if not set(members).issubset(label_set):
                continue
            count = int(e.get("count") or 0)
            if best is None or count > best[0] or \
                    (count == best[0] and members < best[1]):
                best = (count, members)
        source = "evidence" if best is not None else "positional_fallback"
        count = best[0] if best is not None else 0
        chosen = set(best[1] if best is not None else labels[:width])
        doc["combination_synergy"] = [
            {"atoms": list(c), "utility": 1.0 if set(c) == chosen else 0.0}
            for c in itertools.combinations(labels, width)]
        doc["feature_utility_levers"] = {
            "aggregate_fn": "product",
            "lever_weights": {"combination_synergy": 1.0}}
        sys.stderr.write(f"[watcher] evidence_pair gen={gen} "
                         f"chosen={sorted(chosen)} count={count} "
                         f"source={source}\n")
    else:
        raise ValueError(f"unknown mock mode {mode!r}")
    return doc

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


def _write_json(path, doc):
    """Atomically write one JSON document."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _parse_sentinel(name):
    """Parse ``run-<seq>-step-<g>`` into (seq, gen) strings."""
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
    """Stub handler: acknowledge receipt of state-<g> + action-<g>.

    Reads from the per-run subdirectories that mirror the emitter's layout:
      state/run-<seq>/step-<g>.json
      action/run-<seq>/step-<g>.json
    Writes into:
      utilities/run-<seq>/step-<g>.json  (UtilityResponse)
      traces/run-<seq>/step-<g>.json     (AgentTrace)
    """
    state_p  = os.path.join(dirs["state"],  f"run-{seq}", f"step-{gen}.json")
    action_p = os.path.join(dirs["action"], f"run-{seq}", f"step-{gen}.json")
    state_head  = _head(state_p)
    action_head = _head(action_p)
    ts = int(time.time() * 1000)

    util_dir = os.path.join(dirs["utilities"], f"run-{seq}")
    os.makedirs(util_dir, exist_ok=True)
    util_p = os.path.join(util_dir, f"step-{gen}.json")
    utility_doc = dict(_NEUTRAL_DOC)
    run_config = None
    trace_extras = {}
    if MOCK_MODE != "neutral":
        try:
            state = _load_json(state_p)
            run_config = _load_json(os.path.join(dirs["state"], f"run-{seq}",
                                                 "run_config.json"))
            if MOCK_MODE == "live":
                import live_estimator
                utility_doc, trace_extras = live_estimator.estimate(
                    state, run_config, gen)
            else:
                utility_doc = _mock_utility(MOCK_MODE, state, run_config, gen)
        except Exception as e:  # mock failure must never break the handshake
            sys.stderr.write(f"[watcher] mock mode {MOCK_MODE!r} failed for "
                             f"run-{seq}-step-{gen}: {e}; emitting neutral\n")
            utility_doc = dict(_NEUTRAL_DOC)
    # Constrained-output gate: never write a response that violates the
    # UtilityResponse contract. A live agent retries here first; when the
    # retry budget is spent (or for a mock, which has no retry), the invalid
    # document is SALVAGED component-by-component — one bad entry must not
    # cost a generation of otherwise-good guidance — and only a document
    # with nothing salvageable degrades to the neutral decline. Loud either
    # way: an invalid mock is a defect and the policy phase that expected
    # its bias will fail its assertions.
    parse_diagnostics = []
    _alpha = (run_config or {}).get("atom_alphabet")
    schema_ok, schema_errors = utility_schema.validate_utility_response(
        utility_doc, _alpha)
    if not schema_ok:
        salvaged, salvage_report = utility_schema.salvage_utility_response(
            utility_doc, _alpha)
        parse_diagnostics = [f"schema: {e}" for e in schema_errors] + \
            [f"salvage: {f}: dropped={r['dropped']} ({r['first_error']})"
             for f, r in sorted(salvage_report.items())]
        if salvaged is not None and utility_schema.has_guidance(salvaged):
            sys.stderr.write(
                f"[watcher] SCHEMA INVALID (mock mode {MOCK_MODE!r}) for "
                f"run-{seq}-step-{gen}: {schema_errors[:5]}; salvaged with "
                f"drops {salvage_report}\n")
            utility_doc = salvaged
        else:
            sys.stderr.write(
                f"[watcher] SCHEMA INVALID (mock mode {MOCK_MODE!r}) for "
                f"run-{seq}-step-{gen}: {schema_errors[:5]}; nothing "
                f"salvageable, emitting neutral\n")
            utility_doc = dict(_NEUTRAL_DOC)
    raw_outputs = trace_extras.get("raw_provider_outputs") or []
    raw_model_response = (raw_outputs[-1] if raw_outputs
                          else json.dumps(utility_doc, sort_keys=True))
    _write_json(util_p, utility_doc)

    trace_dir = os.path.join(dirs["traces"], f"run-{seq}")
    os.makedirs(trace_dir, exist_ok=True)
    trace_p = os.path.join(trace_dir, f"step-{gen}.json")
    trace_doc = {
        "schema_version": "agent-trace-v0",
        "record_type": "AgentTrace",
        "stub": MOCK_MODE != "live",
        "mock_mode": MOCK_MODE,
        "run_seq": seq,
        "generation": gen,
        "timestamp_ms": ts,
        "ready_sentinel": f"ready/run-{seq}-step-{gen}",
        "input_artifacts": {
            "state_path": state_p,
            "action_path": action_p,
            "run_config_path": os.path.join(dirs["state"], f"run-{seq}",
                                            "run_config.json"),
            "native_log_path": os.path.join(run_dir, "moses_native_log.jsonl"),
        },
        "read_files": [state_p, action_p],
        "prompt_context_manifest": [
            "stub watcher read state/action JSON heads only",
        ],
        "provider": None,
        "raw_model_response": raw_model_response,
        "parsed_utility_response": utility_doc,
        "audit_reasoning": [
            "stub watcher observed ready sentinel but did not call a provider",
        ],
        "parse_diagnostics": parse_diagnostics,
        "debug_heads": {
            "state_head": state_head,
            "action_head": action_head,
        },
        "summary": (
            f"observed ready/run-{seq}-step-{gen}; "
            f"read {len(state_head)} state line(s), "
            f"{len(action_head)} action line(s); wrote utilities + traces."
        ),
    }
    trace_doc.update(trace_extras)
    _write_json(trace_p, trace_doc)

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
            # Phase II return leg: drop the response sentinel LAST (symmetric to the
            # emitter writing ready/ last), so its presence means utilities + traces
            # for this step are fully written. MOSES blocks on this in await_response.
            resp = os.path.join(dirs["response"], f"run-{seq}-step-{gen}")
            with open(resp, "w", encoding="utf-8") as fh:
                fh.write(f"{int(time.time() * 1000)}\n")
            # Move the marker out of ready/ — drain == "ready/ is empty".
            os.replace(entry.path, os.path.join(consumed_dir, entry.name))
            processed += 1
        except Exception as e:  # never let one bad step kill the watcher
            sys.stderr.write(f"[watcher] sentinel {entry.name} failed: {e}\n")
    return processed


def main():
    ap = argparse.ArgumentParser(
        description="LLMOSES shadow-agent watcher: watches ready/ sentinels "
                    "and writes stub UtilityResponse + AgentTrace JSON."
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
        "response":  os.path.join(run_dir, "response"),  # Phase II return leg
    }
    for k in ("utilities", "traces", "response"):
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
