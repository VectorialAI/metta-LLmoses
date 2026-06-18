#!/usr/bin/env python3
"""Manage generated LLMOSES output runs.

This script only operates on generated run directories under
llmoses/outputs/runs/. Canonical estimator docs live in llmoses/skills/ and are
never copied or deleted by this utility.
"""
import argparse
import glob
import json
import os
import shutil
import sys

import context_docs

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_LLMOSES_DIR = os.path.dirname(_THIS_DIR)
_OUTPUTS_DIR = os.path.join(_LLMOSES_DIR, "outputs")
_RUNS_DIR = os.path.join(_OUTPUTS_DIR, "runs")
_CURRENT_RUN = os.path.join(_OUTPUTS_DIR, "CURRENT_RUN.json")


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _run_dirs():
    if not os.path.isdir(_RUNS_DIR):
        return []
    return [
        entry.path for entry in os.scandir(_RUNS_DIR)
        if entry.is_dir() and not entry.name.startswith(".")
    ]


def _run_start_ts(run_dir):
    meta = _read_json(os.path.join(run_dir, "run_meta.json")) or {}
    ts = meta.get("start_ts_ms")
    if isinstance(ts, (int, float)):
        return ts
    try:
        return os.path.getmtime(run_dir) * 1000
    except OSError:
        return 0


def _sorted_runs_newest_first():
    return sorted(_run_dirs(),
                  key=lambda p: (_run_start_ts(p), os.path.basename(p)),
                  reverse=True)


def _current_doc():
    return _read_json(_CURRENT_RUN)


def _resolve_current_path(doc):
    if not doc:
        return None
    run_dir = doc.get("run_dir")
    if run_dir:
        if os.path.isabs(run_dir):
            return os.path.realpath(run_dir)
        repo_root = os.path.dirname(_LLMOSES_DIR)
        candidates = [
            os.path.join(repo_root, run_dir),
            os.path.join(os.getcwd(), run_dir),
            os.path.join(_LLMOSES_DIR, run_dir),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return os.path.realpath(candidate)
        return os.path.realpath(candidates[0])
    run_id = doc.get("run_id")
    if run_id:
        return os.path.realpath(os.path.join(_RUNS_DIR, run_id))
    return None


def _current_status(doc=None):
    doc = _current_doc() if doc is None else doc
    if not doc:
        return "missing", None, None
    run_id = doc.get("run_id")
    current_path = _resolve_current_path(doc)
    if current_path and os.path.isdir(current_path):
        return "ok", run_id, current_path
    return "stale", run_id, current_path


def _run_config_for(run_dir):
    configs = glob.glob(os.path.join(run_dir, "state", "run-*", "run_config.json"))
    best = None
    best_seq = -1
    for path in configs:
        doc = _read_json(path) or {}
        seq = doc.get("run_seq")
        if not isinstance(seq, int):
            seq = -1
        if best is None or seq > best_seq or (seq == best_seq and path > best[0]):
            best = (path, doc)
            best_seq = seq
    return best[1] if best else {}


def _refresh_current():
    runs = _sorted_runs_newest_first()
    if not runs:
        try:
            os.remove(_CURRENT_RUN)
        except FileNotFoundError:
            pass
        return None

    run_dir = runs[0]
    config = _run_config_for(run_dir)
    problem_spec = config.get("problem_spec")
    run_params = config.get("run_parameters") or {}
    problem_type = (
        (problem_spec or {}).get("problem_type")
        or run_params.get("problem_type")
        or config.get("problem_type")
    )
    context_docs.ensure_output_context(
        _LLMOSES_DIR,
        os.path.basename(run_dir),
        os.path.realpath(run_dir),
        run_seq=config.get("run_seq"),
        problem_type=problem_type,
        problem_spec=problem_spec,
        active_levers=config.get("active_levers") or [],
    )
    return run_dir


def _run_path_for_delete(run_id):
    if not run_id or run_id in (".", ".."):
        raise ValueError("run id must name one direct child of llmoses/outputs/runs")
    if os.path.basename(run_id) != run_id:
        raise ValueError("run id must not contain path separators")

    runs_root = os.path.realpath(_RUNS_DIR)
    candidate = os.path.realpath(os.path.join(_RUNS_DIR, run_id))
    if os.path.dirname(candidate) != runs_root:
        raise ValueError("resolved run path is outside llmoses/outputs/runs")
    if not os.path.isdir(candidate):
        raise FileNotFoundError(f"run not found: {run_id}")
    return candidate


def cmd_list(_args):
    os.makedirs(_RUNS_DIR, exist_ok=True)
    doc = _current_doc()
    status, current_id, current_path = _current_status(doc)
    if current_id:
        print(f"CURRENT_RUN.json: {current_id} ({status})")
    else:
        print(f"CURRENT_RUN.json: ({status})")
    if status == "stale" and current_path:
        print(f"  stale path: {current_path}")

    runs = _sorted_runs_newest_first()
    print(f"runs: {len(runs)}")
    for idx, run_dir in enumerate(runs):
        run_id = os.path.basename(run_dir)
        flags = []
        if idx == 0:
            flags.append("latest")
        if current_path and os.path.realpath(run_dir) == current_path:
            flags.append("current")
        elif current_id and run_id == current_id:
            flags.append("current-id")
        suffix = f" [{' '.join(flags)}]" if flags else ""
        print(f"  {run_id}{suffix}")
    return 0


def cmd_refresh_current(_args):
    refreshed = _refresh_current()
    if refreshed is None:
        print("No runs remain; CURRENT_RUN.json removed.")
    else:
        print(f"CURRENT_RUN.json -> {os.path.basename(refreshed)}")
    return 0


def cmd_delete(args):
    if not args.yes:
        print("Refusing to delete without --yes.", file=sys.stderr)
        return 2
    try:
        target = _run_path_for_delete(args.run_id)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    doc = _current_doc()
    status, current_id, current_path = _current_status(doc)
    shutil.rmtree(target)
    print(f"Deleted run: {args.run_id}")

    deleted_current = (
        (current_path and os.path.realpath(target) == current_path)
        or (current_id == args.run_id)
        or status == "stale"
    )
    if deleted_current:
        refreshed = _refresh_current()
        if refreshed is None:
            print("No runs remain; CURRENT_RUN.json removed.")
        else:
            print(f"CURRENT_RUN.json -> {os.path.basename(refreshed)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="List, delete, and refresh generated LLMOSES run outputs."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    list_ap = sub.add_parser("list", help="list generated runs")
    list_ap.set_defaults(func=cmd_list)

    delete_ap = sub.add_parser("delete", help="delete one generated run")
    delete_ap.add_argument("run_id", help="run id under llmoses/outputs/runs")
    delete_ap.add_argument("--yes", action="store_true",
                           help="required confirmation for deletion")
    delete_ap.set_defaults(func=cmd_delete)

    refresh_ap = sub.add_parser("refresh-current",
                                help="point CURRENT_RUN.json at newest run")
    refresh_ap.set_defaults(func=cmd_refresh_current)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
