"""Artifact-only regressions for the native smoke and cold-resume verifiers."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from live_agent_verify import verify_resume, verify_smoke


class RuntimeVerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='llmoses-verifier-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, path, doc):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))

    def log(self, run, rows):
        run.mkdir(parents=True, exist_ok=True)
        (run / 'moses_native_log.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in rows))

    def smoke_run(self, problem_type):
        run = self.root / problem_type
        state = run / 'state/run-1'
        problem = {'problem_type': problem_type}
        if problem_type == 'strategy':
            problem.update(moves=['playwin'], n_games=5, opponent_policy='random')
        self.write(state / 'run_config.json', {
            'record_type': 'run_config', 'problem_spec': problem,
            'run_parameters': {'problem_type': problem_type, 'complexity_coef': 0.25},
            'atom_alphabet': {'prefix': 'move' if problem_type == 'strategy' else 'feature',
                              'atoms': [{'label': 'playwin' if problem_type == 'strategy' else 'X1'}]},
            'active_levers': []})
        self.write(state / 'terminal.json', {'run_verdict': 'ok', 'problem_spec': problem})
        self.write(state / 'step-1.json', {
            'generation': 1, 'metapopulation': {'members': [{'program_id': 'p1'}]},
            'demes': [{'knobs': [{'kind': problem_type, 'multiplicity': 2}]}],
            'call_status': {str(i): 'b_zero' for i in range(1, 5)}})
        self.log(run, [{'event': 'generation_complete', 'generation': 1},
                       {'event': 'lever_site', 'P': [], 'D': []}])
        return run

    def test_strategy_smoke_accepts_native_run_without_action_json(self):
        run = self.smoke_run('strategy')
        self.assertFalse((run / 'action').exists())
        with contextlib.redirect_stdout(io.StringIO()):
            verify_smoke(run, 1, 1, problem_type='strategy')

    def test_strategy_smoke_rejects_wrong_knob_multiplicity(self):
        run = self.smoke_run('strategy')
        path = run / 'state/run-1/step-1.json'
        step = json.loads(path.read_text())
        step['demes'][0]['knobs'][0]['multiplicity'] = 3
        self.write(path, step)
        with self.assertRaises(AssertionError):
            verify_smoke(run, 1, 1, problem_type='strategy')

    def test_smoke_rejects_missing_call_status(self):
        run = self.smoke_run('boolean')
        path = run / 'state/run-1/step-1.json'
        step = json.loads(path.read_text())
        del step['call_status']['4']
        self.write(path, step)
        with self.assertRaises(AssertionError):
            verify_smoke(run, 1, 1)

    def resume_runs(self, remaining):
        paused, full = self.root / 'paused', self.root / 'full'
        terminal = {'run_verdict': 'ok', 'generation': 3, 'total_evaluations': 12,
                    'metapopulation': {'members': [
                        {'program_id': 'p1', 'cscore': {'penalized_score': -1}}]}}
        for run in (paused, full):
            self.write(run / 'state/run-1/terminal.json', terminal)
        complete = lambda g: {'event': 'generation_complete', 'generation': g}
        self.log(full, [complete(g) for g in (1, 2, 3)])
        self.log(paused, [complete(1),
                         {'event': 'run_paused', 'generation': 2, 'reason': 'operator_stop'},
                         {'event': 'run_aborted', 'reason': 'abort_requested'},
                         {'event': 'run_resumed', 'generation': 2},
                         *[complete(g) for g in remaining]])
        return paused, full

    def test_resume_requires_every_generation_even_with_matching_terminal(self):
        paused, full = self.resume_runs([3])
        with self.assertRaisesRegex(AssertionError, 'generations replayed or skipped'):
            verify_resume(paused, full)

    def test_resume_requires_completion_after_the_resume_event(self):
        paused, full = self.resume_runs([2, 3])
        path = paused / 'moses_native_log.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.log(paused, [rows[0], *rows[4:], *rows[1:4]])
        with self.assertRaisesRegex(AssertionError, 'continuation did not complete'):
            verify_resume(paused, full)

    def test_resume_accepts_full_continuation_with_matching_trajectory(self):
        verify_resume(*self.resume_runs([2, 3]))


if __name__ == '__main__':
    unittest.main()
