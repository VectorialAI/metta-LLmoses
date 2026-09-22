"""Supervision must pause infrastructure failures and ignore older terminals."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from m2_test_support import config
import responder_control as rc
import supervisor as sup


class Supervisor(unittest.TestCase):
    def session(self,run,agent=None,moses=None):
        return {'run_dir':run,'agent_pid':agent,'moses_pid':moses}

    def ready(self,run):
        rc.write_json_atomic(Path(run)/'ready/run-1-step-1-call-2',{})

    def test_wedge_and_agent_death_request_pause(self):
        with tempfile.TemporaryDirectory(prefix='llmoses-supervisor-test-') as run:
            self.ready(run)
            view=sup._status(self.session(run),{},1.,0)
            self.assertEqual(view['state'],'pausing')
            self.assertEqual(rc.read_json(Path(run)/'CONTROL/pause_requested')['reason'],'agent_wedged')
            self.assertFalse((Path(run)/'CONTROL/abort').exists())
            with patch.object(rc,'pid_alive',return_value=False):
                view=sup._status(self.session(run,agent=123),{},1.,600)
            self.assertEqual(view['reason'],'agent_dead')

    def test_pause_is_not_terminal_and_newer_run_overrides_old_terminal(self):
        with tempfile.TemporaryDirectory(prefix='llmoses-supervisor-test-') as run:
            rc.write_json_atomic(Path(run)/'state/run-1/terminal.json',{'run_verdict':'ok'})
            (Path(run)/'state/run-2').mkdir()
            rc.write_json_atomic(Path(run)/'CONTROL/pause',{'reason':'auth'})
            view=sup._status(self.session(run),{},1.,600)
            self.assertEqual((view['state'],view['verdict']),('paused',None))
            rc.write_json_atomic(Path(run)/'state/run-2/terminal.json',{'run_verdict':'degraded'})
            view=sup._status(self.session(run),{},1.,600)
            self.assertEqual((view['state'],view['verdict']),('done','degraded'))

    def test_abort_is_first_writer_wins(self):
        with tempfile.TemporaryDirectory(prefix='llmoses-abort-test-') as run:
            rc.request_abort(run,'first','test')
            rc.request_abort(run,'second','test')
            self.assertEqual(rc.read_json(Path(run)/'CONTROL/abort')['reason'],'first')


if __name__=='__main__':
    unittest.main()
