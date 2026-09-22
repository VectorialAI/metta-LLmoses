"""Offline live-estimator semantics and explicit context truncation."""
import json
import os
import unittest
from unittest.mock import patch
from m2_test_support import config, state
import live_estimator as le
import provider_adapter as pa


class LiveEstimator(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'LLMOSES_LIVE_RETRIES':'1','LLMOSES_LIVE_BACKOFF_S':'0',
              'LLMOSES_LIVE_TIMEOUT_S':'1','LLMOSES_CONTEXT_STRATEGY':'full_history'},clear=True)
        self.env.start(); self.addCleanup(self.env.stop)

    def test_transient_retry_success_and_persistent_pause_status(self):
        with patch.object(pa,'invoke',side_effect=[pa.ProviderError('network','offline'),'{"member:p1":0.5}']) as invoke:
            doc,trace=le.estimate(state(),{'experiment':config()})
        self.assertEqual(doc['status'],200)
        self.assertEqual(doc['outcome']['attempts'],2)
        self.assertTrue(doc['outcome']['retried'])
        self.assertEqual(invoke.call_count,2)
        with patch.object(pa,'invoke',side_effect=pa.ProviderError('auth','denied')) as invoke:
            doc,_=le.estimate(state(),config())
        self.assertEqual(doc['status'],503); self.assertEqual(invoke.call_count,1)

    def test_semantic_failure_no_retry_and_partial_salvage(self):
        with patch.object(pa,'invoke',return_value='garbage') as invoke:
            doc,_=le.estimate(state(),config())
        self.assertEqual(doc['status'],500); self.assertEqual(invoke.call_count,1)
        with patch.object(pa,'invoke',return_value='{"member:p1":0.3,"invented":5}'):
            doc,trace=le.estimate(state(),config())
        self.assertEqual(doc['status'],200)
        self.assertEqual(doc['outcome']['salvage'],{'requested':2,'survived':1})
        self.assertEqual(trace['dropped_keys'][0]['key'],'invented')

    def test_bad_capture_never_invokes_provider(self):
        st=state(); st['capture_status']['ok']=False
        with patch.object(pa,'invoke') as invoke: doc,_=le.estimate(st,config())
        self.assertEqual(doc['status'],422); invoke.assert_not_called()

    def test_context_retains_state_reply_and_rationale(self):
        old={'input_state':state(1),'parsed_utility_response':{'row_weights':[]},'audit_reasoning':['reason']}
        with patch.object(pa,'invoke',return_value='{}') as invoke:
            doc,trace=le.estimate(state(),config(),history=[old])
        prompt=invoke.call_args.args[0]
        self.assertIn('row_weights',prompt); self.assertIn('reason',prompt)
        self.assertEqual(doc['outcome']['context']['chars'],len(prompt))
        self.assertNotIn('"b":',prompt)
        with patch.dict(os.environ,{'LLMOSES_CONTEXT_MAX_CHARS':'1','LLMOSES_CONTEXT_TRUNCATION':'none'}):
            with patch.object(pa,'invoke') as invoke: doc,_=le.estimate(state(),config(),history=[old])
            self.assertEqual(doc['status'],503); invoke.assert_not_called()
        with patch.dict(os.environ,{'LLMOSES_CONTEXT_MAX_CHARS':'1','LLMOSES_CONTEXT_TRUNCATION':'oldest'}):
            with patch.object(pa,'invoke',return_value='{}'): doc,_=le.estimate(state(),config(),history=[old])
            self.assertEqual(doc['outcome']['context']['dropped'],['1-call-1'])

    def test_timeout_budget(self):
        self.assertEqual(le.check_timeout_invariant(3),2)
        with self.assertRaises(le.TimeoutInvariantError): le.check_timeout_invariant(2)


if __name__=='__main__':
    unittest.main()
