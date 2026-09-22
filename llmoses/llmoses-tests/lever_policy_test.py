"""Mutative arithmetic, deterministic K, and first-order inclusion guarantees."""
import math
import random
import unittest
from m2_test_support import config
import lever_policy as lp
import conditional_policy as cp


class LeverMath(unittest.TestCase):
    def test_offsets_preserve_prior_odds_for_unadjusted_members(self):
        scores = [-2., -1., 0.]
        prior = lp.softmax(scores, .7)
        adjusted = lp.offset_preference(scores, {0: .5}, .7)
        self.assertAlmostEqual(adjusted[1] / adjusted[2], prior[1] / prior[2])
        self.assertAlmostEqual(adjusted[0] / adjusted[2], prior[0] / prior[2] * math.exp(.5 / .7))
        self.assertEqual(lp.offset_preference(scores, {}, .7), prior)
        self.assertGreater(lp.divergence(prior, adjusted)['tv'], 0)

    def test_mix_then_sharpen_and_off_gate(self):
        p, a = [.8, .2], [.2, .8]
        self.assertEqual(lp.mix(p, a, 0, .25), p)
        raw = [.65, .35]
        expected = lp.normalize([v*v for v in raw])
        for got, want in zip(lp.mix(p, a, .25, .5), expected):
            self.assertAlmostEqual(got, want)

    def test_infeasible_floor_and_k_modes_do_not_consume_rng(self):
        cfg = config()['retention']
        cfg.update(c_max=2, mode='growth')
        before = random.getstate()
        k, detail = lp.retention_budget([.5, .3, .2], [0, -1, -2], 4, 1, 5, 1, cfg, 1)
        self.assertEqual((k, detail['floor_shortfall']), (2, 3))
        self.assertEqual(before, random.getstate())
        for mode in ('ess', 'band', 'fixed', 'growth'):
            cfg.update(mode=mode, c_max=100, floor_coef=0)
            k, _ = lp.retention_budget([.5, .3, .2], [0, -1, -2], 1, 2, 0, .1, cfg, 1)
            self.assertTrue(0 <= k <= 3)

    def test_madow_exact_size_and_inclusion_marginals(self):
        for method in ('power', 'clamp'):
            pi, _ = lp.inclusion_probabilities([.7, .15, .1, .05], 2, method)
            self.assertAlmostEqual(sum(pi), 2)
            self.assertTrue(all(0 <= v <= 1 for v in pi))
            rng, counts = random.Random(823), [0]*4
            for _ in range(12000):
                selected = lp.madow(pi, 2, rng)
                self.assertEqual(len(set(selected)), 2)
                for index in selected:
                    counts[index] += 1
            for n, expected in zip(counts, pi):
                self.assertLess(abs(n / 12000 - expected), .025)
        rng = random.Random(9)
        saved = rng.getstate()
        self.assertEqual(lp.madow([1., 1.], 2, rng), [0, 1])
        self.assertEqual(saved, rng.getstate())

    def test_madow_shuffle_reaches_pairs_fixed_order_cannot(self):
        # Uniform pi, K=2, n=4: fixed-order systematic sampling only ever
        # yields {0,2} or {1,3}. The shuffle is what makes the second-order
        # inclusion match pi_i * pi_j for i != j.
        pi = [0.5, 0.5, 0.5, 0.5]
        rng, pairs = random.Random(17), set()
        for _ in range(800):
            pairs.add(tuple(lp.madow(pi, 2, rng)))
        self.assertGreaterEqual(len(pairs), 5)
        self.assertIn((0, 1), pairs)
        self.assertIn((2, 3), pairs)

    def test_madow_second_order_and_order_independence(self):
        # pi = 1 is a certainty regardless of its position in the pool; the
        # remaining unit of mass is split, so the two half-members never
        # appear together (second-order inclusion 0) and each appears ~50%.
        for certain in (0, 2):
            pi = [.5, .5, .5]
            pi[certain] = 1.
            rng, together, singles = random.Random(31), 0, [0, 0, 0]
            for _ in range(6000):
                chosen = lp.madow(pi, 2, rng)
                self.assertIn(certain, chosen)
                others = [i for i in chosen if i != certain]
                together += len(others) == 2
                for i in others:
                    singles[i] += 1
            self.assertEqual(together, 0)
            for i in range(3):
                if i != certain:
                    self.assertLess(abs(singles[i] / 6000 - .5), .03)
        # K = n is deterministic and consumes no randomness
        rng = random.Random(5)
        saved = rng.getstate()
        self.assertEqual(lp.madow([.2, .3, .5], 3, rng), [0, 1, 2])
        self.assertEqual(saved, rng.getstate())
        self.assertEqual(lp.madow([.2, .3, .5], 0, rng), [])

    def test_conditional_factors_are_multiplicative_and_causal(self):
        pairs = [['X1','X2'], ['X2','X1']]
        raw = {'base': [{'pair': pairs[0], 'weight': 2}], 'rules': [
            {'when': {'ancestor_drew': pairs[1], 'op': 'OR'},
             'adjust': [{'pair': pairs[0], 'weight': .5}]}]}
        policy, _ = cp.validate(raw, {'X1','X2'}, config())
        local = {'op':'OR', 'depth':1, 'site_kind':'appended_child', 'local_literals':[],
                 'ancestor_drew':[], 'already_drawn':[]}
        before, detail = cp.evaluate(policy, pairs, [.5,.5], local)
        self.assertAlmostEqual(before[0], 2/3)
        self.assertEqual(detail['fired_rules'], [])
        local['ancestor_drew'] = [pairs[1]]
        after, detail = cp.evaluate(policy, pairs, [.5,.5], local)
        self.assertEqual(after, [.5,.5])
        self.assertEqual(detail['fired_rules'], [0])
        for radius in (0,1):
            cfg=config(); cfg['context_radius']=radius
            with self.assertRaises(ValueError): cp.validate(raw, {'X1','X2'}, cfg)
        cfg=config(); cfg['rule_budget']=0
        with self.assertRaises(ValueError): cp.validate(raw, {'X1','X2'}, cfg)


if __name__ == '__main__':
    unittest.main()
