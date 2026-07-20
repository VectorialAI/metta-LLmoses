#!/usr/bin/env python3
"""Audit live-agent demo artifacts.

Usage: live_agent_verify.py <rundir> [<rundir>...]
Exit 0 when all hard checks pass, 1 otherwise.
"""

import collections
import json
import os
import sys


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def jsonl(path):
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        yield {"event": "json_decode_error", "raw": line[:200]}
    except FileNotFoundError:
        return


def walk_json(root):
    if not os.path.isdir(root):
        return
    for dirpath, _, names in os.walk(root):
        for name in sorted(names):
            if name.endswith(".json"):
                yield os.path.join(dirpath, name)


def survivor_ids(state):
    scores, order = {}, []
    for m in (state.get("metapopulation") or {}).get("members") or []:
        pid = m.get("program_id")
        if pid is None:
            continue
        if pid not in scores:
            order.append(pid)
        scores[pid] = True
    rc = (state.get("merge_summary") or {}).get("resize_cull") or {}
    for e in rc.get("new_entrants") or []:
        if isinstance(e, dict) and e.get("program_id") is not None:
            pid = e["program_id"]
            if pid not in scores:
                order.append(pid)
            scores[pid] = True
    survivors = set(rc.get("survivors") or order)
    kept = [pid for pid in order if pid in survivors]
    return set(kept or order)


def labels_and_width(run_config):
    alphabet = (run_config or {}).get("atom_alphabet") or {}
    labels = {a.get("label") for a in alphabet.get("atoms") or []
              if a.get("label") is not None}
    width = 3 if alphabet.get("problem_type") == "strategy" else 2
    return labels, width


def num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def utility_docs(rundir):
    root = os.path.join(rundir, "utilities")
    for path in walk_json(root) or []:
        rel = os.path.relpath(path, root)
        parts = rel.split(os.sep)
        if len(parts) != 2 or not parts[0].startswith("run-"):
            continue
        seq = parts[0][4:]
        gen = parts[1][5:-5] if parts[1].startswith("step-") else None
        if gen is None:
            continue
        try:
            yield seq, gen, path, read_json(path)
        except Exception as e:
            yield seq, gen, path, {"_read_error": str(e)}


def state_and_config(rundir, seq, gen):
    base = os.path.join(rundir, "state", f"run-{seq}")
    return (read_json(os.path.join(base, f"step-{gen}.json")),
            read_json(os.path.join(base, "run_config.json")))


def response_reference_failures(rundir):
    failures = []
    component_presence = collections.defaultdict(bool)
    apply_levers = set()
    for seq, gen, path, doc in utility_docs(rundir):
        if "_read_error" in doc:
            failures.append(f"{path}: cannot read JSON: {doc['_read_error']}")
            continue
        try:
            state, run_config = state_and_config(rundir, seq, gen)
        except Exception as e:
            failures.append(f"{path}: missing corresponding state/config: {e}")
            continue
        pids = survivor_ids(state)
        labels, width = labels_and_width(run_config)
        apply_levers.update(((run_config.get("lever_switches") or {})
                             .get("apply") or []))
        for e in doc.get("exemplar_utilities") or []:
            component_presence["exemplar_selection"] = True
            if e.get("program_id") not in pids:
                failures.append(f"{path}: exemplar pid {e.get('program_id')!r} not in state")
        for e in doc.get("culling_utilities") or []:
            component_presence["culling"] = True
            pid = e.get("program_id")
            if pid != "*" and pid not in pids:
                failures.append(f"{path}: culling pid {pid!r} not in state")
        cb = doc.get("comparator_bias") or {}
        for pid in cb.get("program_id_ordering") or []:
            component_presence["comparator"] = True
            if pid not in pids:
                failures.append(f"{path}: comparator pid {pid!r} not in state")
        for e in doc.get("atom_utility_prior") or []:
            component_presence["atom_prior"] = True
            if e.get("atom") not in labels:
                failures.append(f"{path}: atom {e.get('atom')!r} not in alphabet")
        for e in doc.get("combination_synergy") or []:
            component_presence["atom_prior"] = True
            atoms = e.get("atoms") or []
            if len(atoms) != width:
                failures.append(f"{path}: synergy width {len(atoms)} != {width}")
            for atom in atoms:
                if atom not in labels:
                    failures.append(f"{path}: synergy atom {atom!r} not in alphabet")
    return failures, component_presence, apply_levers


def polarity_pattern(literals):
    if not isinstance(literals, list):
        return None
    out = []
    for i, lit in enumerate(literals):
        s = str(lit)
        sign = "-" if s.startswith("-") else "+"
        out.append(f"{sign}{chr(ord('X') + i)}")
    return ",".join(out) if out else None


def trace_diagnostics(rundir):
    attempts = drops = salvage = traces = 0
    for path in walk_json(os.path.join(rundir, "traces")) or []:
        try:
            doc = read_json(path)
        except Exception:
            continue
        traces += 1
        attempts += len(doc.get("attempt_errors") or [])
        drops += len(doc.get("dropped_keys") or [])
        for msg in doc.get("parse_diagnostics") or []:
            if "salvage:" in str(msg):
                salvage += 1
    return {"traces": traces, "attempt_errors": attempts,
            "dropped_keys": drops, "watcher_salvage": salvage}


def audit_rundir(rundir):
    rows = list(jsonl(os.path.join(rundir, "moses_native_log.jsonl")))
    hard = []
    for row in rows:
        if row.get("event") == "utility_ingest":
            gen = num(row.get("generation"))
            if row.get("schema_ok") is False:
                hard.append(f"utility_ingest gen {gen}: schema_ok false")
            if row.get("decline") is True and gen is not None and gen > 1:
                hard.append(f"utility_ingest gen {gen}: decline true after gen 1")

    ref_failures, components, apply_levers = response_reference_failures(rundir)
    hard.extend(ref_failures)

    bias_counts = collections.Counter(row.get("lever") for row in rows
                                      if row.get("event") == "bias_applied")
    cull_required = "cull" in os.path.abspath(rundir).lower()
    if "exemplar_selection" in apply_levers and components["exemplar_selection"] \
            and bias_counts["exemplar_selection"] == 0:
        hard.append("no exemplar_selection bias_applied rows despite nonzero component")
    if cull_required and "culling" in apply_levers and components["culling"] \
            and bias_counts["culling"] == 0:
        hard.append("no culling bias_applied rows despite nonzero culling component")
    if "atom_prior" in apply_levers and components["atom_prior"] \
            and bias_counts["atom_prior"] == 0:
        hard.append("no atom_prior bias_applied rows despite nonzero component")

    comparator_overrides = sum(int(row.get("comparator_overrides") or 0)
                               for row in rows)
    cratio = [f"gen {row.get('generation')} resp {row.get('response_gen')}: "
              f"{row.get('old')}->{row.get('new')} {row.get('direction')}"
              for row in rows
              if row.get("event") == "bias_applied"
              and row.get("lever") == "complexity_ratio"]
    atom_prior_split = collections.Counter(
        (bool(row.get("contextual")), bool(row.get("synergy")))
        for row in rows
        if row.get("event") == "bias_applied" and row.get("lever") == "atom_prior")
    combo_degraded = collections.Counter(str(row.get("degraded")) for row in rows
                                         if row.get("event") == "combo_pick")
    patterns = collections.Counter()
    widths = collections.Counter()
    move_labels = collections.Counter()
    for row in rows:
        if row.get("event") != "combo_pick":
            continue
        pat = polarity_pattern(row.get("literals"))
        if pat:
            patterns[pat] += 1
        atoms = row.get("atoms") or []
        widths[len(atoms)] += 1
        for atom in atoms:
            move_labels[str(atom)] += 1
    inert = [(row.get("generation"), row.get("inert")) for row in rows
             if row.get("event") == "utility_ingest" and row.get("inert")]
    ingests = [
        f"gen {row.get('generation')}: exemplar={row.get('exemplar', 0)} "
        f"retention={row.get('retention', 0)} atoms={row.get('atoms', 0)} "
        f"ctx={row.get('atoms_ctx', 0)} synergy={row.get('synergy', 0)} "
        f"comparator={row.get('comparator', 0)} ratio={row.get('ratio_delta')} "
        f"decline={row.get('decline')}"
        for row in rows if row.get("event") == "utility_ingest"
    ]
    report = {
        "bias_counts": dict(sorted((k, v) for k, v in bias_counts.items()
                                   if k is not None)),
        "comparator_overrides": comparator_overrides,
        "complexity_ratio": cratio,
        "atom_prior_split": {str(k): v for k, v in atom_prior_split.items()},
        "combo_degraded": dict(combo_degraded),
        "polarity_patterns": dict(patterns),
        "pick_widths": dict(widths),
        "move_labels": dict(move_labels),
        "inert": inert,
        "trace_diagnostics": trace_diagnostics(rundir),
        "ingests": ingests,
        "apply_levers": sorted(apply_levers),
    }
    return hard, report


def main(argv):
    if len(argv) < 2:
        print("usage: live_agent_verify.py <rundir> [<rundir>...]", file=sys.stderr)
        return 2
    all_hard = []
    for rundir in argv[1:]:
        hard, report = audit_rundir(rundir)
        print(f"=== {rundir} ===")
        print(f"apply_levers: {report['apply_levers']}")
        print(f"bias_applied counts: {report['bias_counts']}")
        print(f"comparator_overrides total: {report['comparator_overrides']}")
        print(f"complexity_ratio old->new: {report['complexity_ratio']}")
        print(f"atom_prior contextual/synergy split: {report['atom_prior_split']}")
        print(f"combo_pick degraded counts: {report['combo_degraded']}")
        print(f"literal polarity patterns: {report['polarity_patterns']}")
        print(f"strategy pick widths: {report['pick_widths']}")
        print(f"strategy move labels: {report['move_labels']}")
        print(f"inert map occurrences: {report['inert']}")
        if report["inert"]:
            print("FLAG: coverage mode should have no inert map occurrences")
        print(f"retry/salvage diagnostics: {report['trace_diagnostics']}")
        print("per-generation ingest component counts:")
        for line in report["ingests"]:
            print(f"  {line}")
        if hard:
            print("HARD FAILS:")
            for item in hard:
                print(f"  {item}")
            all_hard.extend(f"{rundir}: {item}" for item in hard)
        else:
            print("HARD FAILS: none")
    if all_hard:
        print(f"ALL VERDICT: FAIL ({len(all_hard)} hard failure(s))")
        return 1
    print("ALL VERDICT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
