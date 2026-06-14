"""LLMOSES state/action JSON semantic invariant checks.

Validates coherence between fields emitted by state_builder.py. Intended for
use after schema validation in the strategy/regression state test harnesses, or
post-hoc on archived runs under llmoses/outputs/runs/.

Caveats (by design):
  - action.exemplar_candidates[].neighborhood_size is memoized from the last
    expansion of that program (_nbh_by_pid), not recomputed every generation.
    Deme-level neighborhood_size is validated strictly; candidate-level only
    when non-null and the program is the exemplar on a deme in the same step.
  - set_candidate_neighborhood is referenced in MeTTa but not implemented in
    state_builder.py — no per-member pre-flush neighborhood checks.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class Violation:
    check_id: str
    step: int | str  # generation number or "terminal" / "run"
    detail: str

    def format(self) -> str:
        return f"FAIL_INVARIANT: {self.check_id} step-{self.step}: {self.detail}"


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _approx(a: float, b: float, eps: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= eps


def _sum_bscore(bs: list | None) -> float | None:
    if not bs:
        return None
    if not all(_is_num(v) for v in bs):
        return None
    return float(sum(bs))


def _deme_gen_evals(deme: dict) -> int | None:
    """Per-generation eval count for one deme (matches flush_gen evals_gen arm)."""
    ev = deme.get("evaluations")
    if ev is None:
        ev = deme.get("hill_climb_evaluations")
    if _is_num(ev):
        return int(ev)
    inst = deme.get("instances_evaluated")
    if _is_num(inst):
        return int(inst)
    return None


def _knob_neighborhood(knobs: list) -> int:
    total = 0
    for k in knobs:
        m = k.get("multiplicity")
        if _is_num(m):
            total += max(int(m) - 1, 0)
    return total


# ---------------------------------------------------------------------------
# Linear contin tree parser: (+ offset (* coeff feature) ...)
# ---------------------------------------------------------------------------

def _tokenize_sexpr(s: str) -> list[str]:
    s = s.strip()
    if not s:
        return []
    tokens: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c in "()":
            tokens.append(c)
            i += 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < len(s) and s[j] not in "() \t\n\r":
                j += 1
            tokens.append(s[i:j])
            i = j
    return tokens


def _parse_sexpr_tokens(tokens: list[str], pos: int = 0) -> tuple[Any, int]:
    if pos >= len(tokens):
        raise ValueError("unexpected end of s-expression")
    tok = tokens[pos]
    if tok == "(":
        items: list[Any] = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != ")":
            item, pos = _parse_sexpr_tokens(tokens, pos)
            items.append(item)
        if pos >= len(tokens) or tokens[pos] != ")":
            raise ValueError("unclosed s-expression")
        return items, pos + 1
    if tok == ")":
        raise ValueError("unexpected )")
    # numeric literal or symbol
    try:
        if "." in tok or "e" in tok.lower():
            return float(tok), pos + 1
        return int(tok), pos + 1
    except ValueError:
        return tok, pos + 1


def parse_linear_contin_means(tree_str: str) -> list[float]:
    """Extract [offset, coeff1, coeff2, ...] from a linear contin tree_str.

    Matches continMeansFor / build-contin linear template:
      (+ offset (* c1 X1) (* c2 X2) ...)
    Bare (+) or non-+ root yields [0] or offset-only list.
    """
    tokens = _tokenize_sexpr(tree_str)
    if not tokens:
        return [0.0]
    expr, _ = _parse_sexpr_tokens(tokens, 0)
    if not isinstance(expr, list) or not expr:
        return [0.0]
    if expr[0] != "+":
        return [0.0]

    offset = 0.0
    coeffs: list[float] = []

    for child in expr[1:]:
        if _is_num(child):
            offset = float(child)
        elif isinstance(child, list) and len(child) == 3 and child[0] == "*":
            c, feat = child[1], child[2]
            if _is_num(c):
                coeffs.append(float(c))
            elif isinstance(feat, str):
                coeffs.append(1.0 if _is_num(c) is False and c == feat else 0.0)
        elif isinstance(child, list) and child and child[0] == "*":
            if len(child) >= 2 and _is_num(child[1]):
                coeffs.append(float(child[1]))

    return [offset] + coeffs


def _member_by_id(members: list, program_id: str | None) -> dict | None:
    if not program_id:
        return None
    for m in members:
        if m.get("program_id") == program_id:
            return m
    return None


def _problem_type(state: dict) -> str | None:
    rp = state.get("run_parameters") or {}
    p = rp.get("problem_type")
    if p:
        return str(p)
    ps = state.get("problem_spec") or {}
    return ps.get("problem_type")


def _check_step(
    state: dict,
    action: dict,
    step: int,
    eps: float,
) -> list[Violation]:
    violations: list[Violation] = []
    ptype = _problem_type(state)
    members = (state.get("metapopulation") or {}).get("members") or []
    ratio = (state.get("run_parameters") or {}).get("complexity_ratio")

    for m in members:
        pid = m.get("program_id", "?")
        cs = m.get("cscore") or {}
        raw = cs.get("raw_score")
        cpx = cs.get("complexity")
        cpx_pen = cs.get("complexity_penalty")
        uni_pen = cs.get("uniformity_penalty")
        pen = cs.get("penalized_score")

        if all(_is_num(x) for x in (raw, cpx_pen, uni_pen, pen)):
            expected_pen = float(raw) - float(cpx_pen) - float(uni_pen)
            if not _approx(float(pen), expected_pen, eps):
                violations.append(Violation(
                    "cscore_coherence", step,
                    f"member {pid}: penalized {pen} != raw({raw}) - cpx_pen({cpx_pen}) - uni_pen({uni_pen})",
                ))

        if ptype == "boolean" and _is_num(uni_pen) and float(uni_pen) != 0.0:
            violations.append(Violation(
                "boolean_uniformity_zero", step,
                f"member {pid}: uniformity_penalty={uni_pen}, expected 0.0",
            ))

        if (
            ratio is not None
            and _is_num(ratio)
            and float(ratio) != 0
            and _is_num(uni_pen)
            and float(uni_pen) == 0.0
            and all(_is_num(x) for x in (raw, pen, cpx))
        ):
            expected_ratio_pen = float(raw) - float(cpx) / float(ratio)
            if not _approx(float(pen), expected_ratio_pen, eps):
                violations.append(Violation(
                    "ratio_penalized", step,
                    f"member {pid}: penalized {pen} != raw({raw}) - complexity({cpx})/ratio({ratio})",
                ))

        bs = m.get("bscore")
        if bs and _is_num(raw):
            bsum = _sum_bscore(bs)
            if bsum is not None and not _approx(bsum, float(raw), eps):
                violations.append(Violation(
                    "bscore_sum_raw", step,
                    f"member {pid}: sum(bscore)={bsum} != raw_score={raw}",
                ))

    for deme in state.get("demes") or []:
        did = deme.get("deme_id", "?")
        knobs = deme.get("knobs") or []
        expected_nbh = _knob_neighborhood(knobs)
        actual_nbh = deme.get("neighborhood_size")
        if actual_nbh is not None and int(actual_nbh) != expected_nbh:
            violations.append(Violation(
                "deme_neighborhood", step,
                f"deme {did}: neighborhood_size={actual_nbh} != sum(mult-1)={expected_nbh}",
            ))

        if ptype == "regression":
            contin_knobs = deme.get("contin_knobs")
            if contin_knobs:
                exemplar_id = deme.get("exemplar_program_id")
                member = _member_by_id(members, exemplar_id)
                if member and member.get("tree_str"):
                    try:
                        expected_means = parse_linear_contin_means(member["tree_str"])
                    except (ValueError, TypeError) as e:
                        violations.append(Violation(
                            "contin_means_match", step,
                            f"deme {did}: failed to parse tree_str: {e}",
                        ))
                        continue
                    for grp in contin_knobs:
                        g = grp.get("group")
                        if g is None or g >= len(expected_means):
                            continue
                        mean = grp.get("mean")
                        if _is_num(mean) and not _approx(float(mean), expected_means[g], eps):
                            violations.append(Violation(
                                "contin_means_match", step,
                                f"deme {did} group {g}: mean={mean} != tree constant {expected_means[g]}",
                            ))

    sel_status = action.get("selection_status")
    selected_id = action.get("selected_program_id")
    if sel_status == "ok" and selected_id:
        cand_ids = {c.get("program_id") for c in (action.get("exemplar_candidates") or [])}
        if selected_id not in cand_ids:
            violations.append(Violation(
                "selection_in_candidates", step,
                f"selected_program_id {selected_id} not in exemplar_candidates {sorted(cand_ids)}",
            ))
        post = (state.get("moses_native_events") or {}).get("post_selection") or {}
        chosen = post.get("chosen_program_id")
        if chosen and chosen != selected_id:
            violations.append(Violation(
                "selection_in_candidates", step,
                f"action selected {selected_id} != post_selection chosen {chosen}",
            ))

    return violations


def _check_eval_deltas(steps: list[tuple[int, dict]], eps: float) -> list[Violation]:
    violations: list[Violation] = []
    prev_total: int | None = None
    for gen, state in steps:
        total = state.get("total_evaluations")
        if not _is_num(total):
            continue
        total_i = int(total)
        deme_sum = 0
        any_eval = False
        for deme in state.get("demes") or []:
            ev = _deme_gen_evals(deme)
            if ev is not None:
                deme_sum += ev
                any_eval = True
        if prev_total is not None and any_eval:
            delta = total_i - prev_total
            if delta != deme_sum:
                violations.append(Violation(
                    "eval_step_delta", gen,
                    f"total_evaluations delta {delta} != sum(deme evals) {deme_sum} "
                    f"(prev={prev_total}, cur={total_i})",
                ))
        prev_total = total_i
    return violations


def _check_run_level(
    steps: list[tuple[int, dict, dict]],
    terminal: dict | None,
    *,
    require_evolution: bool,
) -> list[Violation]:
    violations: list[Violation] = []

    if terminal and steps:
        last_gen, last_state, _ = steps[-1]
        t_eval = terminal.get("total_evaluations")
        s_eval = last_state.get("total_evaluations")
        if _is_num(t_eval) and _is_num(s_eval) and int(t_eval) != int(s_eval):
            violations.append(Violation(
                "terminal_eval_total", "terminal",
                f"terminal.total_evaluations={t_eval} != last step {last_gen} total={s_eval}",
            ))

    if require_evolution and steps:
        saw_change = False
        for gen, state, _ in steps:
            ld = state.get("lineage_diff") or {}
            if ld.get("new_programs"):
                saw_change = True
                break
            ms = state.get("merge_summary") or {}
            entrants = (ms.get("resize_cull") or {}).get("new_entrants") or []
            if entrants:
                saw_change = True
                break
        if not saw_change:
            violations.append(Violation(
                "lineage_evolution", "run",
                "require_evolution set but no step had new_programs or merge new_entrants",
            ))

        if len(steps) >= 2:
            _, first_state, _ = steps[0]
            _, last_state, _ = steps[-1]
            ids_first = {m.get("program_id") for m in (first_state.get("metapopulation") or {}).get("members") or []}
            ids_last = {m.get("program_id") for m in (last_state.get("metapopulation") or {}).get("members") or []}
            if ids_first == ids_last:
                violations.append(Violation(
                    "cross_gen_change", "run",
                    "member program_id set unchanged between first and final step",
                ))

    return violations


def _load_steps(state_dir: Path, action_dir: Path) -> list[tuple[int, dict, dict]]:
    steps: list[tuple[int, dict, dict]] = []
    for sp in sorted(state_dir.glob("step-*.json"), key=lambda p: int(re.search(r"(\d+)", p.name).group(1))):  # type: ignore[union-attr]
        m = re.search(r"step-(\d+)", sp.name)
        if not m:
            continue
        gen = int(m.group(1))
        ap = action_dir / sp.name
        if not ap.exists():
            raise FileNotFoundError(f"missing paired action file {ap}")
        with sp.open(encoding="utf-8") as fh:
            state = json.load(fh)
        with ap.open(encoding="utf-8") as fh:
            action = json.load(fh)
        steps.append((gen, state, action))
    return steps


def validate_run(
    state_dir: Path | str,
    action_dir: Path | str,
    *,
    require_evolution: bool = False,
    eps: float = 1e-5,
) -> list[Violation]:
    """Validate semantic invariants for one archived case directory pair."""
    state_dir = Path(state_dir)
    action_dir = Path(action_dir)
    if not state_dir.is_dir():
        return [Violation("run", "run", f"missing state dir {state_dir}")]
    if not action_dir.is_dir():
        return [Violation("run", "run", f"missing action dir {action_dir}")]

    violations: list[Violation] = []
    try:
        steps = _load_steps(state_dir, action_dir)
    except FileNotFoundError as e:
        return [Violation("run", "run", str(e))]

    if not steps:
        return [Violation("run", "run", f"no step-*.json in {state_dir}")]

    for gen, state, action in steps:
        violations.extend(_check_step(state, action, gen, eps))

    step_pairs = [(g, s) for g, s, _ in steps]
    violations.extend(_check_eval_deltas(step_pairs, eps))

    terminal_path = state_dir / "terminal.json"
    terminal = None
    if terminal_path.exists():
        with terminal_path.open(encoding="utf-8") as fh:
            terminal = json.load(fh)

    violations.extend(_check_run_level(steps, terminal, require_evolution=require_evolution))
    return violations


def validate_runs_root(
    runs_root: Path | str,
    *,
    require_evolution: bool = False,
    eps: float = 1e-5,
) -> dict[str, list[Violation]]:
    """Scan runs_root/*/state/<case> and validate every archived case found."""
    runs_root = Path(runs_root)
    results: dict[str, list[Violation]] = {}
    if not runs_root.is_dir():
        return {"": [Violation("run", "run", f"runs root not found: {runs_root}")]}

    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        state_root = run_dir / "state"
        action_root = run_dir / "action"
        if not state_root.is_dir():
            continue
        for case_dir in sorted(state_root.iterdir()):
            if not case_dir.is_dir():
                continue
            # skip ephemeral run-* dirs if present
            if case_dir.name.startswith("run-"):
                continue
            action_case = action_root / case_dir.name
            key = f"{run_dir.name}/{case_dir.name}"
            results[key] = validate_run(
                case_dir, action_case,
                require_evolution=require_evolution,
                eps=eps,
            )
    return results


def violations_to_report(violations: list[Violation]) -> dict[str, Any]:
    return {
        "passed": len(violations) == 0,
        "violation_count": len(violations),
        "violations": [asdict(v) for v in violations],
    }
