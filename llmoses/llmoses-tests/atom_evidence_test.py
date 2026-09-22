"""Call 4 atom evidence: raw facts with their bounds, retired roll-ups gone (reversal #21)."""
import os
import unittest
from unittest.mock import patch
from m2_test_support import BuilderFixture, tree
import atom_evidence as ae

RETIRED_ROW_KEYS = {'depth_bucket', 'depth_buckets', 'score', 'parent_operator'}
ALPHABET = {'input_labels': ['X1', 'X2', 'X3']}


def _members():
    return [
        {'program_id': 'pa', 'cscore': {'penalized_score': -1.0},
         'tree_ast': ['AND', 'X1', ['NOT', 'X2'], ['OR', 'X2', 'X3']]},
        {'program_id': 'pb', 'cscore': {'penalized_score': -2.0},
         'tree_ast': ['OR', 'X1', 'X1', ['NOT', 'X1']]},
        {'program_id': 'pc', 'cscore': {'penalized_score': -3.0}, 'tree_ast': None},
    ]


class AtomEvidence(unittest.TestCase):
    def build(self, env=None):
        _, alpha = ae.build_atom_alphabet(ALPHABET, 'boolean')
        with patch.dict(os.environ, env or {}, clear=True):
            return ae.build_atom_evidence(_members(), 1, 'boolean', -1.0, alpha, {}, '2.0', 1)

    def test_state_document_carries_no_retired_rollups(self):
        evidence, lossless, _ = self.build()
        self.assertEqual(set(evidence), {'n_programs_total', 'atom_appearances', 'realized_cooccurrences',
                                         'atom_cumulative', 'degenerate_summary'})
        for row in evidence['atom_appearances'] + evidence['realized_cooccurrences']:
            self.assertFalse(RETIRED_ROW_KEYS & set(row), row)
        for row in lossless['atom_appearances'] + lossless['realized_cooccurrences']:
            self.assertFalse(RETIRED_ROW_KEYS & set(row), row)
        self.assertEqual(evidence['n_programs_total'], 2)

    def test_lossless_is_populated_by_default_with_raw_depth_and_bounds(self):
        evidence, lossless, rollup = self.build()
        self.assertNotIn('LLMOSES_ATOM_LOSSLESS', os.environ)
        self.assertIsNotNone(lossless)
        self.assertEqual(lossless['programs'], {'pa': {'tree_max_depth': 1, 'node_count': 7},
                                                'pb': {'tree_max_depth': 0, 'node_count': 5}})
        by_ref = {(e['score_ref'], e['node_ref']): e for e in lossless['atom_appearances']}
        self.assertEqual(by_ref[('pa', '0.0')]['depth'], 0)
        self.assertEqual(by_ref[('pa', '0.1')]['polarity'], '-')
        self.assertEqual((by_ref[('pa', '0.2.0')]['depth'], by_ref[('pa', '0.2.0')]['clause_type']), (1, 'OR'))
        # Raw events are pre-normalization: the repeated and contradicted X1 in pb all survive.
        self.assertEqual(sum(e['score_ref'] == 'pb' for e in lossless['atom_appearances']), 3)
        self.assertEqual(sum(e['depth'] == 1 for e in lossless['realized_cooccurrences']), 1)
        # Roll-ups still exist, but only in the operator-facing record.
        self.assertTrue(all('depth_buckets' in r and 'score' in r for r in rollup['atom_appearances']))
        self.assertEqual(rollup['generation'], 1)

    def test_aggregates_are_counts_with_totals(self):
        evidence, _, _ = self.build()
        x1_and = [r for r in evidence['atom_appearances'] if (r['atom'], r['clause_type']) == ('feature:X1', 'AND')]
        self.assertEqual(x1_and, [{'atom': 'feature:X1', 'polarity': '+', 'clause_type': 'AND',
                                   'count': 1, 'n_programs': 1, 'clause_adjacent': 1}])
        self.assertEqual(evidence['degenerate_summary'], {'contradiction_dropped': 1, 'repeats_collapsed': 1})
        keys = {(r['key'], r['clause_type']) for r in evidence['realized_cooccurrences']}
        self.assertEqual(keys, {('+X1&-X2', 'AND'), ('+X2&+X3', 'OR')})
        self.assertEqual(evidence['atom_cumulative']['feature:X1']['appearances_total'], 3)

    def test_payload_emits_lossless_and_logs_rollup(self):
        with BuilderFixture() as f:
            sb = f.sb
            sb.add_member(1, ['OR', 'X2', ['NOT', 'X3']], tree('OR', [tree('X2'), tree('NOT', [tree('X3')])]),
                          [-1, 1, 0, 0, -1], ['mkBScore', [-1, 0]])
            sb._current_call = 3
            state = sb._payload(4)
            self.assertNotIn('gated', state['atom_lossless'])
            self.assertTrue(state['atom_lossless']['atom_appearances'])
            self.assertEqual(set(state['atom_lossless']['programs']),
                             {m['program_id'] for m in sb._gs(1)['members']})
            for row in state['atom_evidence']['atom_appearances']:
                self.assertFalse(RETIRED_ROW_KEYS & set(row))
            rollups = f.events('atom_evidence_rollup')
            self.assertEqual(len(rollups), 1)
            self.assertTrue(rollups[0]['atom_appearances'][0]['depth_buckets'])


if __name__ == '__main__':
    unittest.main()
