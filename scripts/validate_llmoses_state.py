#!/usr/bin/env python3
"""Validate LLMOSES state/action JSON semantic invariants.

Single archived case:
  python3 scripts/validate_llmoses_state.py \\
    --run-dir llmoses/outputs/runs/<id>/state/<case> \\
    --action-dir llmoses/outputs/runs/<id>/action/<case>

Batch scan:
  python3 scripts/validate_llmoses_state.py \\
    --runs-root llmoses/outputs/runs --all-cases
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow import when invoked from repo root without installing a package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from llmoses.utilities.state_invariants import (  # noqa: E402
    validate_run,
    validate_runs_root,
    violations_to_report,
)


def _emit(violations, *, as_json: bool, label: str) -> int:
    if as_json:
        report = violations_to_report(violations)
        report["label"] = label
        print(json.dumps(report, indent=2))
    elif violations:
        for v in violations:
            print(v.format(), file=sys.stderr)
    else:
        print(f"PASS_INVARIANT: {label}")
    return 1 if violations else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LLMOSES state/action invariant validator")
    p.add_argument("--run-dir", type=Path, help="Archived state case directory")
    p.add_argument("--action-dir", type=Path, help="Archived action case directory")
    p.add_argument("--runs-root", type=Path, help="Scan all runs under this root")
    p.add_argument("--all-cases", action="store_true",
                   help="With --runs-root, validate every state/<case> archive")
    p.add_argument("--require-evolution", action="store_true",
                   help="Require lineage/merge activity across the run")
    p.add_argument("--eps", type=float, default=1e-5, help="Float comparison tolerance")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON report")
    args = p.parse_args(argv)

    if args.runs_root:
        if not args.all_cases:
            p.error("--runs-root requires --all-cases")
        results = validate_runs_root(
            args.runs_root,
            require_evolution=args.require_evolution,
            eps=args.eps,
        )
        if not results:
            print("PASS_INVARIANT: no archived cases found", file=sys.stderr)
            return 0
        rc = 0
        if args.json:
            payload = {
                k: violations_to_report(v) for k, v in results.items()
            }
            payload["passed"] = all(not v for v in results.values())
            print(json.dumps(payload, indent=2))
            return 0 if payload["passed"] else 1
        for label, violations in results.items():
            if violations:
                rc = 1
                for v in violations:
                    print(f"[{label}] {v.format()}", file=sys.stderr)
            else:
                print(f"PASS_INVARIANT: {label}")
        return rc

    if not args.run_dir or not args.action_dir:
        p.error("either (--run-dir and --action-dir) or (--runs-root --all-cases) required")

    violations = validate_run(
        args.run_dir,
        args.action_dir,
        require_evolution=args.require_evolution,
        eps=args.eps,
    )
    label = f"{args.run_dir.name}"
    return _emit(violations, as_json=args.json, label=label)


if __name__ == "__main__":
    raise SystemExit(main())
