"""Complexity coefficient: direct `coef` in [0,1] is primary; `ratio` is a legacy alias.

Reversal #20: `coef = 1/ratio` is undefined at ratio = 0 and exceeds 1 on
(0, 1). Both clamp to the coefficient ceiling, 1.0, which is the balanced
point by design (penalty and fitness carry equal total weight). This is NOT
"maximum penalty" -- the primary range never extends past balanced -- and
it deliberately does not reproduce native's `ratio <= 0 -> 0.0` off switch.
The off switch is direct `coef = 0`.
"""
import math
import unittest
from m2_test_support import BuilderFixture, Aborted


class ComplexityCoefficient(unittest.TestCase):
    def test_legacy_ratio_preserves_native_default(self):
        with BuilderFixture() as f:
            # spec section 9: coef 0.2857 == ratio 3.5, the native default
            self.assertAlmostEqual(f.sb.complexity_coef(3.5), 1 / 3.5, places=12)
            self.assertAlmostEqual(f.sb.complexity_coef(3.5), 0.285714, places=6)
            self.assertAlmostEqual(f.sb.complexity_coef(2), 0.5)
            self.assertEqual(f.sb.complexity_coef(1), 1.0)

    def test_legacy_ratio_edges_clamp_to_the_balanced_ceiling(self):
        with BuilderFixture() as f:
            # undefined (1/0) and reversed (1/negative): ceiling, not native's 0.0
            for ratio in (0, -1, -3.5):
                self.assertEqual(f.sb.complexity_coef(ratio), 1.0, ratio)
            # (0, 1) would exceed 1: clamped to the same ceiling
            for ratio in (0.5, 0.999):
                self.assertEqual(f.sb.complexity_coef(ratio), 1.0, ratio)
            # non-finite ratio is a config invariant break, surfaced through the bridge
            with self.assertRaises(Aborted):
                f.sb.complexity_coef(math.inf)

    def test_direct_coef_zero_is_the_off_switch(self):
        with BuilderFixture() as f:
            f.sb._config['complexity_coef'] = 0.0
            # cscore.metta: complexity_penalty = complexity * coef -> 0, penalized == raw
            self.assertEqual(f.sb.complexity_coef(3.5), 0.0)
            self.assertEqual(f.sb.complexity_coef(0), 0.0)

    def test_direct_coef_wins_over_conflicting_legacy_ratio(self):
        with BuilderFixture() as f:
            f.sb._config['complexity_coef'] = 0.4
            for ratio in (3.5, 0, -1, 1e9):
                self.assertEqual(f.sb.complexity_coef(ratio), 0.4, ratio)

    def test_run_parameters_echo_the_effective_coef_not_the_ratio(self):
        with BuilderFixture() as f:
            params = f.sb._build_run_parameters()
            self.assertNotIn('complexity_ratio', params)
            self.assertAlmostEqual(params['complexity_coef'], 1 / 3.5)
        with BuilderFixture(run_params={'complexity_ratio': 0}) as f:
            self.assertEqual(f.sb._build_run_parameters()['complexity_coef'], 1.0)
        with BuilderFixture() as f:
            f.sb._config['complexity_coef'] = 0.25
            self.assertEqual(f.sb._build_run_parameters()['complexity_coef'], 0.25)


if __name__ == '__main__':
    unittest.main()
