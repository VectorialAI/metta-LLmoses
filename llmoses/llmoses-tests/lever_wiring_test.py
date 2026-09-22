"""Lever arithmetic as wired through state_builder, pinned to decided values.

Every case here exercises the real ingest -> surface -> mix -> site path, not
lever_policy in isolation, so a wiring regression (wrong temperature unit,
wrong normalization order, unclamped input) is caught even when the pure
arithmetic is right.
"""
import math
import random
import unittest
from m2_test_support import BuilderFixture, Aborted, envelope, tree


def _knob(child, index, default=0, disallowed=()):
    return ['mkKnob', child, ['mkLSK', ['mkDiscKnob', ['mkMultip', 3], ['mkDiscSpec', default],
            ['mkDiscSpec', default], [['mkDiscSpec', d] for d in disallowed]]], index]


class Lever4RowWeights(unittest.TestCase):
    """Reversal #19: normalize the agent's multipliers, mix with uniform, rescale by n."""

    def install(self, f, b, weights, T=None):
        f.sb._config['levers']['rowweight'].update(b=b, T_commandable=True)
        doc = envelope(1, row_weights=[{'row': i, 'weight': w} for i, w in enumerate(weights)])
        if T is not None:
            doc['T_rowweight'] = T
        f.answer(1, doc)
        f.sb.call_rows()
        f.sb.install_row_weights()
        return list(f.sb._row_weights)

    def test_fractional_b_is_a_convex_combination_of_mean_one_vectors(self):
        with BuilderFixture() as f:
            self.assertEqual(self.install(f, 0.5, [3, 1]), [1.25, 0.75])
        with BuilderFixture() as f:
            # the literal spec form (raw mix then normalize) would give [1.6, 0.4] here
            got = self.install(f, 0.5, [3, 1])
            self.assertNotEqual([round(w, 6) for w in got], [1.6, 0.4])

    def test_scale_invariance_to_agent_input_magnitude(self):
        with BuilderFixture() as f:
            a = self.install(f, 0.5, [3, 1])
        with BuilderFixture() as f:
            b = self.install(f, 0.5, [1.5, 0.5])
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y)

    def test_row_temperature_sharpens_after_mixing(self):
        with BuilderFixture() as f:
            got = self.install(f, 0.5, [3, 1], T=0.5)
            # D0 = [.625, .375]; D = normalize(D0^2) = [25/34, 9/34]; w = 2*D
            self.assertAlmostEqual(got[0], 25 / 17)
            self.assertAlmostEqual(got[1], 9 / 17)
            event = f.events('lever_site')[-1]
            self.assertAlmostEqual(event['D0'][0], .625)
            self.assertAlmostEqual(event['A'][0], .75)

    def test_weights_always_sum_to_n(self):
        for b, weights, T in ((1.0, [4, 0], None), (0.3, [0.2, 3.9], 2.0), (0.9, [1, 1], 0.25)):
            with self.subTest(b=b, weights=weights, T=T), BuilderFixture() as f:
                got = self.install(f, b, weights, T)
                self.assertAlmostEqual(sum(got), 2)
                self.assertTrue(all(w >= 0 for w in got))

    def test_b_one_reproduces_the_raw_mix_and_ingest_clamps_utility_max(self):
        with BuilderFixture() as f:
            self.assertEqual(self.install(f, 1.0, [3, 1]), [1.5, 0.5])
        with BuilderFixture() as f:
            # utility_max is 4: a 12 arrives as 4, so [4, 1] -> [1.6, 0.4]
            got = self.install(f, 1.0, [12, 1])
            self.assertAlmostEqual(got[0], 1.6)
            self.assertIn('row_weights[0].weight', f.events('utility_ingest')[-1]['report']['clamped'])

    def test_row_weight_shape_mismatch_aborts_instead_of_truncating(self):
        with BuilderFixture() as f:
            self.install(f, 0.5, [3, 1])
            with self.assertRaises(Aborted):
                f.sb.weighted_sum(['mkBScore', [-1, 0, 1]], 0)
            aborted = f.events('run_aborted')[-1]
            self.assertEqual(aborted['reason'], 'row_weight_shape')
            self.assertEqual(aborted['detail'], {'rows': 3, 'weights': 2})


class Lever1ExemplarTemperature(unittest.TestCase):
    """Offsets are in lattice (score) units and pass through native temperature."""

    def select(self, f, selection_temperature, offsets, scores=(0.0, -1.0, -2.0)):
        sb = f.sb
        sb._config['selection_temperature'] = selection_temperature
        sb._config['levers']['exemplar'].update(b=1.0)
        # Offsets are only accepted for offered candidates, so the selection
        # pool must be the emitted metapopulation.
        sb.clear_members(1)
        for i, s in enumerate(scores):
            sb.add_member(1, f'X{i + 1}', tree(f'X{i + 1}'), [s, 1, 0, 0, s], ['mkBScore', [s, 0]])
        f.advance_to(2)
        sb.begin_selection(len(scores))
        inv_temp = 100.0 / selection_temperature
        best = max(scores)
        pids = []
        for i, s in enumerate(scores):
            sb.add_selection_candidate(i, math.exp((s - best) * inv_temp), tree(f'X{i + 1}'), s)
            pids.append(sb._sel_buf[-1]['pid'])
        self.assertEqual(pids, [m['program_id'] for m in sb._gs(1)['members']])
        f.answer(2, envelope(2, exemplar_utilities=[
            {'program_id': pids[i], 'offset': o} for i, o in offsets.items()]))
        sb.call_exemplar()
        sb.select_index()
        return f.events('lever_site')[-1]

    def test_prior_is_reproduced_at_native_temperature_over_100(self):
        for temperature in (100.0, 50.0, 25.0):
            with self.subTest(T=temperature), BuilderFixture() as f:
                event = self.select(f, temperature, {0: 0.0})
                # all-zero offsets: A is the prior, not a re-softmax at a different unit
                for p, a in zip(event['P'], event['A']):
                    self.assertAlmostEqual(p, a)
                self.assertEqual(event['tv_agent'], 0)

    def test_offset_odds_ratio_is_exp_delta_times_100_over_T(self):
        for temperature, delta in ((100.0, 0.5), (50.0, 0.5), (25.0, 1.0)):
            with self.subTest(T=temperature, delta=delta), BuilderFixture() as f:
                event = self.select(f, temperature, {0: delta})
                P, A = event['P'], event['A']
                self.assertAlmostEqual((A[0] / A[1]) / (P[0] / P[1]), math.exp(delta * 100.0 / temperature))
                # unadjusted members keep their native odds against each other
                self.assertAlmostEqual(A[1] / A[2], P[1] / P[2])
                self.assertEqual(event['adjustment'], [delta, 0.0, 0.0])

    def test_offsets_are_clamped_to_delta_max_at_ingest(self):
        with BuilderFixture() as f:
            f.sb._config['levers']['exemplar']['delta_max'] = 1.0
            event = self.select(f, 100.0, {2: 7.0})
            self.assertEqual(event['adjustment'], [0.0, 0.0, 1.0])
            self.assertIn('exemplar_utilities[0].offset', f.events('utility_ingest')[-1]['report']['clamped'])
            self.assertGreater(event['tv_realized'], 0)


class Lever2RetentionMultiMember(unittest.TestCase):
    """Directional inclusion probabilities, K modes, and exact-K sampling on a real pool."""

    def pool(self, f, scores):
        sb = f.sb
        sb.clear_members(1)
        for i, s in enumerate(scores):
            label = f'X{(i % 3) + 1}'
            sb.add_member(1, ['AND', label, 'X%d' % ((i + 1) % 3 + 1)] if i else label,
                          tree('AND', [tree(label), tree('X%d' % ((i + 1) % 3 + 1)), tree(str(i))]),
                          [s, 1, 0, 0, s], ['mkBScore', [s, 0]])
        return [m['program_id'] for m in sb._gs(1)['members']]

    def retain(self, f, scores, offsets, retention=None, b=1.0, minimum=1, comp_temp=1.0):
        sb = f.sb
        sb._config['levers']['retention'].update(b=b)
        sb._config['retention'].update(retention or {})
        pids = self.pool(f, scores)
        sb._responses[4] = envelope(4, retention_utilities=[
            {'program_id': pids[i], 'offset': o} for i, o in offsets.items()]) if offsets else None
        sb._call_status[4] = 'applied' if offsets else 'declined'
        sb.apply_retention(minimum, comp_temp, 1)
        return pids, f.events('lever_site')[-1]

    def test_positive_offset_raises_inclusion_probability_directionally(self):
        with BuilderFixture() as f:
            pids, event = self.retain(f, [0.0, -1.0, -2.0], {2: 1.0}, {'c_max': 2})
            pi, native = event['inclusion_probabilities'], event['native_inclusion_probabilities']
            self.assertAlmostEqual(sum(pi), 2)
            self.assertAlmostEqual(sum(native), 2)
            self.assertGreater(pi[2], native[2])
            self.assertLess(pi[0] + pi[1], native[0] + native[1])
            self.assertGreater(event['mean_inclusion_difference'], 0)
            self.assertEqual(len(event['survivors']), 2)
            self.assertEqual(event['budget']['K'], 2)

    def test_identity_offsets_reproduce_native_inclusion(self):
        with BuilderFixture() as f:
            _, event = self.retain(f, [0.0, -1.0, -2.0], {0: 0.0, 1: 0.0}, {'c_max': 2})
            self.assertEqual(event['inclusion_probabilities'], event['native_inclusion_probabilities'])
            self.assertEqual(event['tv_realized'], 0)

    def test_k_modes_on_a_real_pool(self):
        scores = [0.0, -0.1, -2.0, -3.0]
        with BuilderFixture() as f:
            _, event = self.retain(f, scores, {}, {'mode': 'band'}, comp_temp=1.0)
            # band = 0.30 * comp_temp: two members within 0.3 of the best
            self.assertEqual(event['budget']['target'], 2)
            self.assertEqual(event['budget']['mode'], 'band')
        with BuilderFixture() as f:
            _, event = self.retain(f, scores, {}, {'mode': 'ess', 'tau': 1.0})
            prior = event['P']
            self.assertEqual(event['budget']['target'], math.floor(1 / math.fsum(p * p for p in prior)))
        with BuilderFixture() as f:
            _, event = self.retain(f, scores, {}, {'mode': 'fixed', 'target': 3})
            self.assertEqual((event['budget']['target'], event['budget']['K']), (3, 3))
        with BuilderFixture() as f:
            _, event = self.retain(f, scores, {}, {'mode': 'growth', 'c_max': 1000})
            # no generation-start members recorded: ceiling = floor(rho * entrants) = n
            self.assertEqual(event['budget']['K'], 4)

    def test_min_pool_floor_binds_and_off_gate_keeps_rng(self):
        with BuilderFixture() as f:
            _, event = self.retain(f, [0.0, -5.0, -9.0], {}, {'mode': 'fixed', 'target': 1}, minimum=2)
            self.assertEqual(event['budget']['K'], 2)
        with BuilderFixture() as f:
            before = random.getstate()
            pids, event = self.retain(f, [0.0, -1.0], {}, {'c_max': 1000}, b=0)
            # everyone retained (K = n) -> no draw at all
            self.assertEqual(before, random.getstate())
            self.assertEqual(sorted(event['survivors']), sorted(pids))


class Lever5PairPolicy(unittest.TestCase):
    """Ordered-pair polarity, end-to-end knob tagging, and rule compounding."""

    def test_register_pair_knobs_uses_native_polarity_convention(self):
        with BuilderFixture() as f:
            sb = f.sb
            labels = ['X1', 'X2']
            sb.begin_build(tree('AND'))
            token = sb.begin_combo_draw([[0, 1], [1, 0]], labels, 'AND', [], 'exemplar_node', [])
            sb.end_combo_draw(token, [0])  # drew ordered pair [X1, X2]
            neg_first = _knob(tree('AND', [tree('NOT', [tree('X1')]), tree('X2')]), 0)
            both_pos = _knob(tree('AND', [tree('X1'), tree('X2')]), 1)
            sb.register_pair_knobs(tree('AND', [neg_first, both_pos]), [])
            knobs = sb._draws[-1]['knobs']
            # getArgs negates the lower-indexed atom when a < b: [X1, X2] is (-X1, +X2)
            self.assertEqual([(k['index'], k['pair']) for k in knobs], [(0, ['X1', 'X2'])])
            token = sb.begin_combo_draw([[0, 1], [1, 0]], labels, 'AND', [3], 'appended_child', [])
            sb.end_combo_draw(token, [1])  # drew [X2, X1]
            sb.register_pair_knobs(tree('AND', [neg_first, both_pos]), [3])
            self.assertEqual([(k['index'], k['pair']) for k in sb._draws[-1]['knobs']], [(1, ['X2', 'X1'])])
            # a path with no draw site registers nothing (arity-one site)
            self.assertEqual(sb.register_pair_knobs(tree('AND', [both_pos]), [7]), 0)

    def test_tag_candidate_attaches_active_pairs_to_the_member(self):
        with BuilderFixture() as f:
            sb = f.sb
            sb.begin_build(tree('AND'))
            token = sb.begin_combo_draw([[0, 1], [1, 0]], ['X1', 'X2'], 'AND', [], 'exemplar_node', [])
            sb.end_combo_draw(token, [0])
            knob = _knob(tree('AND', [tree('NOT', [tree('X1')]), tree('X2')]), 0)
            rep_tree = tree('AND', [knob])
            sb.register_pair_knobs(rep_tree, [])
            sb.finish_build(rep_tree)
            rep = ['mkRep', 'unused', rep_tree]
            sb.tag_candidate(tree('X3'), rep, ['mkInst', [1]], 'd0')
            tags = sb._candidate_pairs[sb._pid(sb.expr_to_str(tree('X3')))]
            self.assertEqual([(t['pair'], t['setting'], t['index']) for t in tags], [(['X1', 'X2'], 1, 0)])
            # knob off in this instance: no active pair for the sibling candidate
            sb.tag_candidate(tree('X2'), rep, ['mkInst', [0]], 'd0')
            self.assertEqual(sb._candidate_pairs[sb._pid(sb.expr_to_str(tree('X2')))], [])
            # emitted on the member as active_pairs
            sb.add_member(1, 'X3', tree('X3'), [0, 1, 0, 0, 0], ['mkBScore', [0, 0]])
            emitted = [m for m in sb._payload(1)['metapopulation']['members'] if m['tree_str'] == 'X3'][0]
            self.assertEqual(emitted['active_pairs'][0]['pair'], ['X1', 'X2'])

    def test_two_fired_rules_compound_multiplicatively_with_base(self):
        with BuilderFixture() as f:
            sb = f.sb
            sb._responses[3] = envelope(3, policy={
                'base': [{'pair': ['X1', 'X2'], 'weight': 2}],
                'rules': [{'when': {'op': 'OR'}, 'adjust': [{'pair': ['X1', 'X2'], 'weight': 0.5}]},
                          {'when': {'depth': {'min': 1}}, 'adjust': [{'pair': ['X1', 'X2'], 'weight': 4}]},
                          {'when': {'op': 'AND'}, 'adjust': [{'pair': ['X1', 'X2'], 'weight': 0.1}]}]})
            sb._call_status[3] = 'applied'
            sb.begin_build(tree('OR'))
            token = sb.begin_combo_draw([[0, 1], [1, 0]], ['X1', 'X2'], 'OR', [2], 'appended_child', [])
            buf = sb._combo_bufs[token]
            self.assertEqual(buf['detail']['fired_rules'], [0, 1])
            # factor on [X1,X2] = 2 * 0.5 * 4 = 4; on [X2,X1] = 1 -> D = [4/5, 1/5]
            self.assertAlmostEqual(buf['D'][0], 0.8)
            self.assertAlmostEqual(buf['D'][1], 0.2)
            self.assertEqual(buf['detail']['factors'][0], [2, 0.5, 4])
            sb.end_combo_draw(token, [0])
            self.assertEqual(f.events('lever_site')[-1]['fired_rules'], [0, 1])


if __name__ == '__main__':
    unittest.main()
