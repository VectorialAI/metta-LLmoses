"""Per-call agent CLI, response ordering, and responder ownership regressions."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from m2_test_support import ROOT, config, state
import call_paths
import protocol_version
import responder_control as rc


class AgentTools(unittest.TestCase):
    def cli(self,*args):
        result=subprocess.run([sys.executable,str(ROOT/'llmoses/utilities/agent_tools.py'),*map(str,args)],
                              text=True,capture_output=True,timeout=5)
        return result,json.loads(result.stdout)

    def request(self,run,step,call):
        paths=call_paths.paths(run,1,step)
        rc.write_json_atomic(paths['state'],state(call))
        rc.write_json_atomic(paths['action'],{})
        rc.write_json_atomic(paths['run_config'],{'experiment':config()})
        rc.write_json_atomic(paths['ready'],{})
        return paths

    def test_structured_policy_response_and_stale_duplicate(self):
        with tempfile.TemporaryDirectory(prefix='llmoses-agent-test-') as run:
            paths=self.request(run,'1-call-3',3)
            proc,claim=self.cli('claim',run)
            self.assertEqual(proc.returncode,0)
            token=claim['session']
            proc,ready=self.cli('wait',run,'--timeout',0)
            self.assertEqual(ready['gen'],'1-call-3')
            values=Path(run)/'values.json';values.write_text('{"policy":{"base":[],"rules":[]}}')
            proc,result=self.cli('respond',run,1,'1-call-3','--values',values,'--session',token)
            self.assertEqual(proc.returncode,0,proc.stderr+proc.stdout)
            self.assertEqual(result['status'],200)
            for key in ('utilities','trace','response'): self.assertTrue(Path(paths[key]).exists())
            self.assertFalse(Path(paths['ready']).exists())
            trace=rc.read_json(paths['trace'])
            self.assertEqual((trace['generation'],trace['call']),(1,3))
            self.assertEqual(trace['input_state']['call'],3)
            proc,_=self.cli('respond',run,1,'1-call-3','--values',values,'--session',token)
            self.assertEqual(proc.returncode,3)
            self.request(run,'1-call-4',4)
            proc,result=self.cli('abstain',run,1,'1-call-4','--reason','identity','--session',token)
            self.assertEqual(proc.returncode,0)
            self.assertEqual(result['status'],204)

    def test_numerical_call_order_and_latest_run_terminal(self):
        with tempfile.TemporaryDirectory(prefix='llmoses-order-test-') as run:
            for step in ('10-call-1','2-call-4','2-call-1'):
                paths=call_paths.paths(run,1,step);rc.write_json_atomic(paths['ready'],{})
            self.assertEqual([row[1] for row in call_paths.ready_entries(run)],
                             ['2-call-1','2-call-4','10-call-1'])
            rc.write_json_atomic(Path(run)/'state/run-1/terminal.json',{'run_verdict':'ok'})
            (Path(run)/'state/run-2').mkdir()
            self.assertIsNone(call_paths.latest_terminal(run))

    def test_claim_is_exclusive_and_old_session_cannot_mutate(self):
        with tempfile.TemporaryDirectory(prefix='llmoses-claim-test-') as run:
            def claim():
                try: return rc.claim(run,'agent:test','agent')['owner']['session']
                except rc.OwnershipConflict: return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                tokens=list(pool.map(lambda _:claim(),range(2)))
            self.assertEqual(sum(t is not None for t in tokens),1)
            old=next(t for t in tokens if t)
            new=rc.claim(run,'agent:test','agent',takeover=True)['owner']['session']
            self.assertNotEqual(old,new)
            self.assertFalse(rc.owns(run,'agent',old))
            with self.assertRaises(rc.OwnershipConflict): rc.release(run,session=old)
            self.assertTrue(rc.owns(run,'agent',new))
            rc.release(run,session=new)

    def test_history_excludes_future_and_includes_responses(self):
        with tempfile.TemporaryDirectory(prefix='llmoses-history-test-') as run:
            for call in (1,2,3):
                paths=self.request(run,f'1-call-{call}',call)
                rc.write_json_atomic(paths['trace'],{'parsed_utility_response':{'call':call},'audit_reasoning':['why']})
            proc,hist=self.cli('history',run,1,'--strategy','full_history','--budget',100000,'--gen','1-call-2')
            self.assertEqual(proc.returncode,0)
            self.assertEqual(hist['included'],['1-call-1','1-call-2'])
            self.assertEqual(hist['payload']['history'][0]['trace']['audit_reasoning'],['why'])
            proc,_=self.cli('summarize',run,1,'--text','remember')
            self.assertEqual(proc.returncode,0)
            self.assertIn('remember',(Path(run)/'context/run-1/summary.md').read_text())


if __name__=='__main__':
    unittest.main()
