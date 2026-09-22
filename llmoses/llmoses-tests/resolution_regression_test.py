"""Causal draw history and real representation activity regressions."""
import random
import unittest
from m2_test_support import BuilderFixture, envelope, tree


def knob(child,index,default=0,disallowed=()):
    return ['mkKnob',child,['mkLSK',['mkDiscKnob',['mkMultip',3],['mkDiscSpec',default],
            ['mkDiscSpec',default],[['mkDiscSpec',d] for d in disallowed]]],index]


class CausalHistory(unittest.TestCase):
    def test_ancestor_history_and_build_reset_tokens(self):
        with BuilderFixture() as f:
            sb=f.sb; pairs=[[0,1],[1,0]];labels=['X1','X2']
            sb._responses[3]=envelope(3,policy={'rules':[{'when':{'ancestor_drew':['X1','X2']},
                'adjust':[{'pair':['X2','X1'],'weight':4}]}]})
            sb.begin_build(tree('AND'))
            before=random.getstate()
            first=sb.begin_combo_draw(pairs,labels,'AND',[],'exemplar_node',[])
            self.assertEqual(sb._combo_bufs[first]['detail']['fired_rules'],[])
            self.assertEqual(before,random.getstate())
            sb.end_combo_draw(first,[0])
            second=sb.begin_combo_draw(pairs,labels,'OR',[3],'appended_child',[])
            self.assertEqual(sb._combo_bufs[second]['detail']['fired_rules'],[0])
            self.assertEqual(sb._combo_bufs[second]['state']['depth'],1)
            self.assertAlmostEqual(sb._combo_bufs[second]['D'][1],.8)
            sb.end_combo_draw(second,[1])
            self.assertFalse(sb._combo_bufs)
            self.assertEqual([d['site_seq'] for d in sb._draws],[1,2])
            sb.begin_build(tree('AND'))
            third=sb.begin_combo_draw(pairs,labels,'OR',[3],'appended_child',[])
            self.assertEqual(sb._combo_bufs[third]['detail']['fired_rules'],[])
            sb.end_combo_draw(third,[0])

    def test_without_replacement_zero_remaining_fallback(self):
        with BuilderFixture() as f:
            sb=f.sb
            sb._responses[3]=envelope(3,policy={'base':[{'pair':['X2','X1'],'weight':0}]})
            sb.begin_build(tree('AND'))
            token=sb.begin_combo_draw([[0,1],[1,0]],['X1','X2'],'AND',[])
            a=sb.weighted_combo_pick(token,0,1,[])
            b=sb.weighted_combo_pick(token,0,1,[a])
            self.assertEqual((a,b),(0,1))
            self.assertTrue(sb._combo_bufs[token]['pick_records'][-1]['zero_mass_fallback'])
            sb.end_combo_draw(token,[a,b])
            self.assertFalse(sb._combo_bufs)

    def test_absent_ancestors_and_pruned_effective_settings(self):
        with BuilderFixture() as f:
            nested=knob(tree('AND',[knob(tree('X1'),1)]),0)
            self.assertEqual(f.sb._active_settings(nested,[0,1]),{})
            self.assertEqual(f.sb._active_settings(nested,[1,2]),{0:1,1:2})
            pruned=knob(tree('X1'),0,default=0,disallowed=(1,))
            self.assertEqual(f.sb._active_settings(pruned,[1]),{0:2})
            default=knob(tree('X1'),0,default=1,disallowed=(0,))
            default[2][1][2]=["mkDiscSpec",2]  # current differs from default
            self.assertEqual(f.sb._active_settings(default,[0]),{0:1})


if __name__=='__main__':
    unittest.main()
