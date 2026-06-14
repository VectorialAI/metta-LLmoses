"""Unit tests for llmoses.utilities.state_invariants."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llmoses.utilities.state_invariants import (
    Violation,
    parse_linear_contin_means,
    validate_run,
)


def _member(pid: str, raw: float, cpx: float, cpx_pen: float, uni_pen: float, pen: float, bscore=None):
    return {
        "program_id": pid,
        "tree_str": "(+ 1 (* 2 X))",
        "complexity": cpx,
        "cscore": {
            "raw_score": raw,
            "complexity": cpx,
            "complexity_penalty": cpx_pen,
            "uniformity_penalty": uni_pen,
            "penalized_score": pen,
        },
        "bscore": bscore,
    }


def _coherent_member(pid: str = "p1", raw: float = -10.0, cpx: float = 3.0, ratio: float = 3.5,
                   bscore=None):
    """Build a member whose cscore fields satisfy both coherence checks."""
    cpx_pen = cpx / ratio
    pen = raw - cpx_pen
    return _member(pid, raw, cpx, cpx_pen, 0.0, pen, bscore=bscore)


def _minimal_state(step: int, members, demes=None, total_eval=10, ptype="regression", ratio=3.5):
    return {
        "generation": step,
        "total_evaluations": total_eval,
        "run_parameters": {"problem_type": ptype, "complexity_ratio": ratio},
        "problem_spec": {"problem_type": ptype},
        "metapopulation": {"members": members},
        "demes": demes or [],
        "lineage_diff": {"new_programs": ["new1"], "culled": []},
        "merge_summary": {"resize_cull": {"new_entrants": [{"program_id": "new1"}]}},
        "moses_native_events": {
            "post_selection": {
                "chosen_program_id": "p1",
                "selection_status": "ok",
            }
        },
    }


def _minimal_action(step: int, selected="p1", cands=None):
    cands = cands or [{"program_id": "p1", "neighborhood_size": 2}]
    return {
        "generation": step,
        "selection_status": "ok",
        "selected_program_id": selected,
        "exemplar_candidates": cands,
    }


class TestParseLinearContinMeans(unittest.TestCase):
    def test_offset_and_coeff(self):
        self.assertEqual(parse_linear_contin_means("(+ 1 (* 2 X))"), [1.0, 2.0])

    def test_multi_feature(self):
        tree = "(+ 0 (* 1 X1) (* 1 X2))"
        self.assertEqual(parse_linear_contin_means(tree), [0.0, 1.0, 1.0])

    def test_bare_plus(self):
        self.assertEqual(parse_linear_contin_means("(+)"), [0.0])


class TestValidateRunPass(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name) / "state"
        self.action_dir = Path(self.tmp.name) / "action"
        self.state_dir.mkdir()
        self.action_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, gen: int, state: dict, action: dict):
        (self.state_dir / f"step-{gen}.json").write_text(json.dumps(state))
        (self.action_dir / f"step-{gen}.json").write_text(json.dumps(action))

    def test_coherent_cscore_and_bscore(self):
        m = _coherent_member(bscore=[-1, -4, -9, 4])  # sums to -10
        self._write(1, _minimal_state(1, [m]), _minimal_action(1))
        v = validate_run(self.state_dir, self.action_dir)
        self.assertEqual(v, [])

    def test_deme_neighborhood(self):
        deme = {
            "deme_id": "0",
            "exemplar_program_id": "p1",
            "neighborhood_size": 4,
            "knobs": [
                {"multiplicity": 3, "kind": "contin", "contin": {"group": 0, "mean": 1.0, "depth": 2}},
                {"multiplicity": 3, "kind": "contin", "contin": {"group": 0, "mean": 1.0, "depth": 2}},
            ],
            "contin_knobs": [{"group": 0, "mean": 1.0, "depth": 2, "trit_knob_ids": [0, 1]}],
            "instances_evaluated": 5,
            "evaluations": 5,
        }
        m = _coherent_member()
        self._write(1, _minimal_state(1, [m], demes=[deme]), _minimal_action(1))
        v = validate_run(self.state_dir, self.action_dir)
        self.assertEqual(v, [])

    def test_eval_step_delta(self):
        m = _coherent_member(raw=0, cpx=1)
        d = {"deme_id": "0", "neighborhood_size": 0, "knobs": [],
             "instances_evaluated": 3, "evaluations": 3}
        self._write(1, _minimal_state(1, [m], demes=[d], total_eval=3), _minimal_action(1))
        self._write(2, _minimal_state(2, [m], demes=[d], total_eval=6), _minimal_action(2))
        v = validate_run(self.state_dir, self.action_dir)
        self.assertEqual(v, [])


class TestValidateRunFail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name) / "state"
        self.action_dir = Path(self.tmp.name) / "action"
        self.state_dir.mkdir()
        self.action_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, gen: int, state: dict, action: dict):
        (self.state_dir / f"step-{gen}.json").write_text(json.dumps(state))
        (self.action_dir / f"step-{gen}.json").write_text(json.dumps(action))

    def test_bscore_sum_mismatch(self):
        m = _member("p1", raw=-10.0, cpx=3.0, cpx_pen=0.857, uni_pen=0.0, pen=-10.857,
                    bscore=[-1, -1, -1, -1])
        self._write(1, _minimal_state(1, [m]), _minimal_action(1))
        v = validate_run(self.state_dir, self.action_dir)
        self.assertTrue(any(x.check_id == "bscore_sum_raw" for x in v))

    def test_cscore_incoherent(self):
        m = _member("p1", raw=-10.0, cpx=3.0, cpx_pen=0.857, uni_pen=0.0, pen=0.0)
        self._write(1, _minimal_state(1, [m]), _minimal_action(1))
        v = validate_run(self.state_dir, self.action_dir)
        self.assertTrue(any(x.check_id == "cscore_coherence" for x in v))

    def test_boolean_uniformity(self):
        m = _member("p1", raw=1.0, cpx=1.0, cpx_pen=0.1, uni_pen=0.5, pen=0.4)
        self._write(1, _minimal_state(1, [m], ptype="boolean", ratio=None), _minimal_action(1))
        v = validate_run(self.state_dir, self.action_dir)
        self.assertTrue(any(x.check_id == "boolean_uniformity_zero" for x in v))

    def test_selection_not_in_candidates(self):
        m = _member("p1", raw=0, cpx=1, cpx_pen=0.1, uni_pen=0, pen=-0.1)
        self._write(1, _minimal_state(1, [m]), _minimal_action(1, selected="missing",
                     cands=[{"program_id": "p1"}]))
        v = validate_run(self.state_dir, self.action_dir)
        self.assertTrue(any(x.check_id == "selection_in_candidates" for x in v))

    def test_deme_neighborhood_mismatch(self):
        deme = {"deme_id": "0", "neighborhood_size": 99, "knobs": [{"multiplicity": 3}]}
        m = _member("p1", raw=0, cpx=1, cpx_pen=0.1, uni_pen=0, pen=-0.1)
        self._write(1, _minimal_state(1, [m], demes=[deme]), _minimal_action(1))
        v = validate_run(self.state_dir, self.action_dir)
        self.assertTrue(any(x.check_id == "deme_neighborhood" for x in v))

    def test_require_evolution_fails(self):
        m = _member("p1", raw=0, cpx=1, cpx_pen=0.1, uni_pen=0, pen=-0.1)
        state = _minimal_state(1, [m])
        state["lineage_diff"] = {"new_programs": [], "culled": []}
        state["merge_summary"] = {"resize_cull": {"new_entrants": []}}
        self._write(1, state, _minimal_action(1))
        v = validate_run(self.state_dir, self.action_dir, require_evolution=True)
        self.assertTrue(any(x.check_id == "lineage_evolution" for x in v))

    def test_contin_means_mismatch(self):
        deme = {
            "deme_id": "0",
            "exemplar_program_id": "p1",
            "neighborhood_size": 2,
            "knobs": [{"multiplicity": 3, "kind": "contin",
                       "contin": {"group": 0, "mean": 99.0, "depth": 1}}],
            "contin_knobs": [{"group": 0, "mean": 99.0, "depth": 1, "trit_knob_ids": [0]}],
        }
        m = _member("p1", raw=0, cpx=1, cpx_pen=0.1, uni_pen=0, pen=-0.1)
        self._write(1, _minimal_state(1, [m], demes=[deme]), _minimal_action(1))
        v = validate_run(self.state_dir, self.action_dir)
        self.assertTrue(any(x.check_id == "contin_means_match" for x in v))


class TestViolationFormat(unittest.TestCase):
    def test_format(self):
        v = Violation("bscore_sum_raw", 1, "detail here")
        self.assertEqual(v.format(), "FAIL_INVARIANT: bscore_sum_raw step-1: detail here")


if __name__ == "__main__":
    unittest.main()
