"""Protocol-2 runtime boundaries: four calls, off gates, pause and durable abort."""
import json
import os
from pathlib import Path
import random
import threading
import time
import unittest
from unittest.mock import patch
from m2_test_support import BuilderFixture, Aborted, envelope, tree
import call_paths
import checkpointing
import responder_control as rc
from boundary import cons_to_list


class Hardening(unittest.TestCase):
    def test_four_call_fence_and_semantic_failure_is_local(self):
        with BuilderFixture() as f:
            sb=f.sb
            f.answer(1)
            sb.call_rows(); sb.install_row_weights()
            wrong=envelope(2, generation=9)
            f.answer(2, wrong)
            sb.call_exemplar()
            self.assertEqual(sb._call_status[2], 'semantic_degradation')
            f.answer(3, envelope(3, policy={'base':[], 'rules':[]}))
            sb.call_atom()
            self.assertEqual(sb._call_status[3], 'applied')
            f.answer(4)
            sb.call_retention(1, 1, 1)
            self.assertEqual(sb._current_call, 4)
            self.assertEqual(len(sb._retained), 1)
            with self.assertRaises(Aborted): sb.call_atom()
            self.assertEqual(rc.read_json(Path(f.run)/'CONTROL/abort')['reason'], 'call_fence')

    def test_off_gate_skips_transport_and_temperature(self):
        with BuilderFixture() as f:
            sb=f.sb
            for spec in sb._config['levers'].values():
                spec.update(b=0, T_base=.25)
            before=random.getstate()
            sb.call_rows(); sb.install_row_weights(); sb.call_exemplar()
            sb.call_atom(); sb.call_retention(1,1,1)
            self.assertEqual(before, random.getstate())  # singleton retention
            self.assertEqual(sb._row_weights, [1,1])
            self.assertEqual(call_paths.ready_entries(f.run), [])
            self.assertEqual(set(sb._call_status.values()), {'b_zero'})
            sb.selection_single(tree('X1'))
            for event in f.events('lever_site'):
                self.assertEqual(event['P'], event['D'])
                self.assertIn('adjustment', event)
                self.assertEqual(event['tv_realized'], 0)

    def test_native_exemplar_rng_one_draw_and_identity_offsets(self):
        with BuilderFixture() as f:
            sb=f.sb
            sb._config['levers']['exemplar']['b']=0
            sb.begin_selection(2)
            sb.add_selection_candidate(0, 1., tree('X1'), 0)
            sb.add_selection_candidate(1, .5, tree('X2'), -1)
            saved=random.getstate()
            probe=random.Random(); probe.setstate(saved); probe.random()
            sb.select_index()
            self.assertEqual(random.getstate(), probe.getstate())
            sb._config['levers']['exemplar']['b']=1
            sb._responses[2]=envelope(2, exemplar_utilities=[
                {'program_id':m['pid'], 'offset':0} for m in sb._sel_buf])
            sb.select_index()
            event=f.events('lever_site')[-1]
            self.assertEqual(event['P'], event['A'])

    def test_row_rescore_changes_arithmetic_not_evaluation_count(self):
        with BuilderFixture() as f:
            sb=f.sb
            f.answer(1,envelope(1,row_weights=[{'row':0,'weight':3}, {'row':1,'weight':1}]))
            sb.call_rows()
            self.assertEqual(sb.install_row_weights(),1)
            self.assertEqual(sb._row_weights,[1.5,.5])
            self.assertEqual(sb.weighted_sum(['mkBScore',['Cons',-1,['Cons',0,'Nil']]], -1),-1.5)
            self.assertEqual(sb.get_total_evals(),0)
            self.assertEqual(sb._payload(2)['candidates'][0]['unweighted_score'],-1)

    def test_native_flat_bscores_and_explicit_spines_preserve_rows(self):
        forms=([-1,0], ['mkBScore',[-1,0]],
               ['mkBScore',['cons',-1,['cons',0,[]]]],
               ['mkBScore',['Cons',-1,['Cons',0,'Nil']]])
        for bscore in forms:
            with self.subTest(bscore=bscore), BuilderFixture() as f:
                sb=f.sb
                sb.clear_members(1)
                sb.add_member(1,'X1',tree('X1'),[-1,1,0,0,-1],bscore)
                pid=sb._gs(1)['members'][0]['program_id']
                self.assertEqual(sb._payload(1)['rows'],[
                    {'row':0,'scores':{pid:-1}}, {'row':1,'scores':{pid:0}}])
                f.answer(1,envelope(1,row_weights=[{'row':0,'weight':3},{'row':1,'weight':1}]))
                sb.call_rows(); sb.install_row_weights()
                self.assertEqual(sb.weighted_sum(bscore,-1),-1.5)
                self.assertEqual(sb._payload(2)['candidates'][0]['bscore'],[-1,0])
                sb.begin_merge()
                sb.add_cull_candidate('X1',tree('X1'),bscore,-1,1,-1)
                self.assertEqual(sb._pending_merge['cull_candidates'][0]['bscore'],[-1,0])
        self.assertEqual(cons_to_list(['X1','X2']),['X1','X2'])
        self.assertEqual(cons_to_list(['mkBScore',[]]),[])
        self.assertEqual(cons_to_list('Nil'),[])

    def test_infrastructure_pause_preserves_rng_and_exact_resume_fence(self):
        with BuilderFixture() as f:
            sb=f.sb
            f.answer(1, {'run_seq':1,'generation':1,'call':1,'pass':True,'status':503,
                         'outcome':{'error_class':'auth'}})
            observed=[]
            errors=[]
            def repair():
                try:
                    deadline=time.monotonic()+4
                    pause_path=Path(f.run)/'CONTROL/pause'
                    while not pause_path.exists() and time.monotonic()<deadline: time.sleep(.005)
                    pause=rc.read_json(pause_path)
                    if pause is None: raise AssertionError('pause not persisted')
                    observed.append(json.loads(Path(pause['checkpoint']).read_text()))
                    # A stale fence must leave the call paused.
                    rc.write_json_atomic(Path(f.run)/'CONTROL/resume', {'run_seq':1,'generation':2,'call':1})
                    time.sleep(.03)
                    if not pause_path.exists(): raise AssertionError('stale resume accepted')
                    rc.write_json_atomic(Path(f.run)/'CONTROL/resume', {'run_seq':1,'generation':1,'call':1})
                    paths=call_paths.paths(f.run,1,'1-call-1')
                    while (pause_path.exists() or Path(paths['response']).exists()) and time.monotonic()<deadline:
                        time.sleep(.005)
                    f.answer(1)
                except BaseException as exc:
                    errors.append(exc)
                    rc.request_abort(f.run,"fixture_failure","test",str(exc))
            saved=random.getstate()
            thread=threading.Thread(target=repair, daemon=True); thread.start()
            sb.call_rows(); thread.join(4)
            self.assertFalse(thread.is_alive())
            if errors: raise errors[0]
            self.assertEqual(sb._call_status[1],'declined')
            self.assertEqual(checkpointing.decode(observed[0]['rng_state']),saved)
            self.assertEqual(random.getstate(),saved)
            self.assertEqual([x['event'] for x in f.events() if x['event'] in ('run_paused','run_resumed')],
                             ['run_paused','run_resumed'])

    def test_checkpoint_roundtrip_and_context(self):
        with BuilderFixture() as f:
            sb=f.sb
            path=Path(f.run)/'context/run-1/summary.md';path.parent.mkdir(parents=True);path.write_text('remember X1')
            sb._row_weights=[1.5,.5]
            state=sb._payload(1)
            checkpoint=sb._save_checkpoint(state)
            expected=random.getstate();random.random()
            evolution, continuation, doc=checkpointing.restore(checkpoint)
            self.assertEqual(evolution['_row_weights'],[1.5,.5])
            self.assertEqual(continuation,['mkM2Rows',['test-frame']])
            self.assertEqual(random.getstate(),expected)
            path.write_text('changed')
            checkpointing.restore_context(f.run,doc['agent_context'])
            self.assertEqual(path.read_text(),'remember X1')
            with self.assertRaises(ValueError):
                checkpointing.restore_context(f.run,{'artifacts':[{'path':'../escape','text':'bad'}]})

    def test_cold_restore_rejoins_one_persisted_pause(self):
        with BuilderFixture() as f:
            sb=f.sb
            request=sb._payload(1)
            sb._current_call=1
            # Stop the waiting process after it has persisted its checkpoint.
            with patch.object(sb,'_wait_for_resume',side_effect=Aborted(3)):
                with self.assertRaises(Aborted): sb._pause('operator_stop',request)
            pause=rc.read_json(Path(f.run)/'CONTROL/pause')
            fence={k:request[k] for k in ('run_seq','generation','call')}
            rc.write_json_atomic(Path(f.run)/'CONTROL/resume',fence)
            with patch.dict(os.environ,{'LLMOSES_RESUME_CHECKPOINT':pause['checkpoint']}), \
                    patch.object(sb,'_call',return_value=0) as pending_call:
                continuation=sb.restore_checkpoint()
            pending_call.assert_called_once_with(1,payload=request)
            self.assertEqual(continuation,['mkM2Rows',['test-frame']])
            self.assertEqual([e['event'] for e in f.events()
                              if e['event'] in ('run_paused','run_resumed')],
                             ['run_paused','run_resumed'])
            self.assertFalse((Path(f.run)/'CONTROL/pause').exists())
            self.assertFalse((Path(f.run)/'CONTROL/resume').exists())

    def test_offered_unknown_and_known_but_unoffered_buckets(self):
        with BuilderFixture() as f:
            f.sb._known_ids.update({'p1','p2'})
            result=f.sb._id_buckets(envelope(2,exemplar_utilities=[
                {'program_id':p,'offset':1} for p in ('p1','p2','ghost')]),
                {'call':2,'candidates':[{'program_id':'p1'}]})['exemplar_utilities']
            self.assertEqual((result['unknown'],result['unoffered'],result['total']),(1,1,3))

    def test_abort_writes_durable_terminal_and_survives_logging_failure(self):
        with BuilderFixture() as f:
            f.sb._NFH.close()
            with self.assertRaises(Aborted): f.sb._abort_run('injected')
            terminal=rc.read_json(Path(f.run)/'state/run-1/terminal.json')
            self.assertEqual(terminal['run_verdict'],'aborted')
            self.assertGreater(terminal['logging_degraded'],0)


if __name__=='__main__':
    unittest.main()
