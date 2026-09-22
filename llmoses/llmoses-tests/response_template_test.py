"""Closed schemas, fence checks, salvage and structured Call-3 slots."""
import unittest
from m2_test_support import config, state, envelope
import response_template as rt
import utility_schema as us


class ResponseContracts(unittest.TestCase):
    def test_member_offsets_clamp_and_salvage(self):
        doc = envelope(exemplar_utilities=[{'program_id': 'p1', 'offset': 9},
            {'program_id': 'made-up', 'offset': .2}, {'program_id': 'p2', 'offset': float('nan')}])
        clean, report = us.ingest(doc, state(), config())
        self.assertEqual(clean['exemplar_utilities'], [{'program_id': 'p1', 'offset': 1}])
        self.assertEqual(len(report['dropped']), 2)
        self.assertEqual(len(report['clamped']), 1)

    def test_closed_envelope_even_on_decline(self):
        for extra in ({'comparator_bias': None}, {'masks': []}, {'culling_utilities': []},
                      {'generation': 2}, {'call': 4}, {'run_seq': True},
                      {'outcome': {'detail': None}}, {'pass': False}):
            with self.subTest(extra=extra):
                doc = {**us.neutral(state()), **extra}
                self.assertIsNone(us.ingest(doc, state(), config())[0])

    def test_temperature_is_owned_and_clamped(self):
        cfg = config()
        doc = envelope(T_exemplar=9)
        self.assertIsNone(us.ingest(doc, state(), cfg)[0])
        cfg['levers']['exemplar']['T_commandable'] = True
        clean, report = us.ingest(doc, state(), cfg)
        self.assertEqual(clean['T_exemplar'], 4)
        self.assertTrue(report['clamped'])
        self.assertTrue(us.has_guidance(clean))

    def test_policy_slot_and_no_paths(self):
        slots = rt.build_slots(state(3), {'experiment': config()})
        self.assertEqual(set(slots), {'policy'})
        policy = {'base': [{'pair': ['X1', 'X3'], 'weight': 2}],
                  'rules': [{'when': {'op': 'OR'}, 'adjust': []}]}
        self.assertEqual(rt.assemble(slots, {'policy': policy})['policy'], policy)
        for key in ('path', 'descendants', 'final_depth', 'knob_state'):
            with self.assertRaises(ValueError):
                rt.assemble(slots, {'policy': {'rules': [{'when': {key: 1}, 'adjust': []}]}})

    def test_numeric_slots_and_neutral(self):
        for call, slot, val, field in ((1, 'row:0', 2, 'row_weights'),
                (2, 'member:p1', -.5, 'exemplar_utilities'),
                (4, 'member:p2', .5, 'retention_utilities')):
            slots = rt.build_slots(state(call), config())
            self.assertIn(field, rt.assemble(slots, {slot: val}))
            self.assertEqual(rt.assemble(slots, {}, decline=True)['status'], 204)
            for bad in (True, float('inf'), None):
                with self.assertRaises(ValueError):
                    rt.assemble(slots, {slot: bad})


if __name__ == '__main__':
    unittest.main()
