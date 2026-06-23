"""Golden-master harness for the state-builder py-call boundary.

Drives a synthetic 2-generation run plus a terminal snapshot through the public
API exactly as the .metta wrapper would (native numbers/strings, nested-list
preOrder ASTs, Cons spines, wrapped atoms), then collects every emitted JSON
artifact with volatile timestamps normalized. Used to prove a refactor preserves
emission byte-for-byte.
"""
import importlib
import json
import os
import sys


def cons(*xs):
    """Build a Cons spine terminated by Nil: cons(1.0, 0.0) -> ['Cons',1.0,['Cons',0.0,'Nil']]."""
    spine = "Nil"
    for x in reversed(xs):
        spine = ["Cons", x, spine]
    return spine


def drive(sb):
    """Exercise every emission path. Returns nothing; writes into the run dir."""
    sb.new_run()

    # problem spec: labels as a Cons spine of symbol strings (set_problem_spec path)
    sb.set_problem_spec(cons("X1", "X2", "X3"), 3)

    # buffer run parameters (mirrors sbSetRunParams), incl. an absent-style cratio
    params = {
        "problem_type": "boolean", "complexity_ratio": "3.5", "max_gen": "2",
        "n_eval": "100", "max_cands_per_deme": "50", "min_pool_size": "5",
        "complexity_temperature": "6.0", "n_to_keep": "10", "cap_coef": "2",
        "n_deme": "1", "optimizer": "hill-climbing",
        "hill_climb_max_evaluations": 10000,
    }
    for k, v in params.items():
        sb.set_run_param(k, v)
    sb.emit_run_config()

    # Two members per gen; trees are preOrder nested lists over the alphabet.
    trees = {
        0: [["AND", "X1", ["NOT", "X2"]], ["OR", "X2", "X3"]],
        1: [["AND", "X1", "X3"], ["OR", ["NOT", "X1"], "X2"], ["AND", "X2", "X2"]],
    }
    cscores = {
        0: [[0.80, 5.0, 1.0, 0.0, 0.79], [0.60, 3.0, 0.5, 0.0, 0.595]],
        1: [[0.90, 4.0, 0.8, 0.0, 0.892], [0.70, 6.0, 1.2, 0.0, 0.688],
            [0.50, 2.0, 0.4, 0.0, 0.496]],
    }
    for g in (0, 1):
        sb.begin_gen(g)
        for tree, cs in zip(trees[g], cscores[g]):
            # expr == tree here (resolved member); bscore as mkBScore-wrapped spine
            sb.add_member(g, tree, tree, cs, ["mkBScore", cons(1.0, 0.0, 1.0)])
        # select the first member of the gen (its raw tree hashes to a real id)
        sb.set_selection(trees[g][0])
        # one deme with two knobs (LSK + SSK), keyed by a wrapped demeId
        deme_id = ["mkDemeId", str(g + 1)]
        sb.add_knob(g, deme_id, ["mkNodeId", 10 + g], ["mkMultip", 3], 0, "LSK")
        sb.add_knob(g, deme_id, ["mkNodeId", 20 + g], ["mkMultip", 2], 1, "SSK")
        sb.set_deme(g, deme_id, trees[g][0], 7)
        # merge buffer: post-merge ids, counts, a cull candidate
        sb.begin_merge()
        for tree in trees[g]:
            sb.add_merged_member(tree)
        # introduce one brand-new post-merge program (drives lineage_diff.new_programs)
        new_tree = ["OR", "X3", ["NOT", "X1"]]
        sb.add_merged_member(new_tree)
        sb.set_merge_count("candidates_produced", 4)
        sb.set_merge_count("duplicates_dropped", 1)
        sb.set_merge_count("dominated_removed", 1)
        sb.add_cull_candidate(new_tree, new_tree, ["mkBScore", cons(0.0, 1.0)],
                              0.55, 3.0, 0.544)
        sb.flush_gen(g)

    # terminal snapshot reuses the last gen's members
    sb.begin_gen(2)
    for tree, cs in zip(trees[1], cscores[1]):
        sb.add_member(2, tree, tree, cs, "Nil")
    sb.flush_terminal(2)


_VOLATILE_KEYS = {"timestamp_ms", "ts_ms", "start_ts_ms", "updated_ts_ms"}


def _scrub(obj):
    """Recursively replace volatile timestamp values with a constant."""
    if isinstance(obj, dict):
        return {k: ("<TS>" if k in _VOLATILE_KEYS else _scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def collect(run_dir):
    """Map every .json/.jsonl artifact under run_dir -> scrubbed content."""
    out = {}
    for root, _dirs, files in os.walk(run_dir):
        for fn in sorted(files):
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, run_dir)
            if fn.endswith(".json"):
                with open(path, encoding="utf-8") as fh:
                    out[rel] = _scrub(json.load(fh))
            elif fn.endswith(".jsonl"):
                rows = [_scrub(json.loads(ln)) for ln in open(path, encoding="utf-8") if ln.strip()]
                out[rel] = rows
    return out


def main(run_dir, pkg_dir, out_json):
    sys.path.insert(0, pkg_dir)
    os.environ["LLMOSES_RUN_DIR"] = run_dir
    sb = importlib.import_module("state_builder")
    drive(sb)
    snapshot = collect(run_dir)
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, sort_keys=True)
    print(f"captured {len(snapshot)} artifacts -> {out_json}")
    for rel in sorted(snapshot):
        print("  ", rel)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
