"""Shared offline fixtures for protocol 2. Importing this module runs no tests."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
UTIL = ROOT / 'llmoses' / 'utilities'
sys.path.insert(0, str(UTIL))
import lever_config
import call_paths
import responder_control as rc


def config(b=1.0):
    with patch.dict(os.environ, {}, clear=True):
        cfg = lever_config.load(str(ROOT / 'llmoses/configs/m2-closure.json'))
    for spec in cfg['levers'].values():
        spec['b'] = b
    return cfg


def state(call=2):
    members = [{'program_id': 'p1', 'tree_str': '(AND X1 X2)',
                'cscore': {'penalized_score': -1.0}, 'bscore': [-1, 0]},
               {'program_id': 'p2', 'tree_str': '(OR X1 X2)',
                'cscore': {'penalized_score': -2.0}, 'bscore': [0, -1]}]
    return {'run_seq': 1, 'generation': 1, 'call': call,
            'capture_status': {'ok': True, 'failed_sections': []},
            'rows': [{'row': 0}, {'row': 1}], 'candidates': members,
            'metapopulation': {'members': members},
            'alphabet': {'atoms': [{'label': s} for s in ('X1', 'X2', 'X3')]},
            'pairs': [['X1', 'X2'], ['X2', 'X1']]}


def envelope(call=2, **values):
    return {'run_seq': 1, 'generation': 1, 'call': call,
            'pass': False, 'status': 200, 'outcome': {}, **values}


def tree(label, children=None):
    return ['mkTree', ['mkNode', label], children or []]


class Aborted(BaseException):
    pass


class BuilderFixture:
    """One state_builder module bound to a throwaway run directory.

    env         extra/overriding environment for the builder import
    b           lever strength installed on every lever (default fully on)
    run_params  overrides for the run parameters set before emit_run_config
    """
    def __init__(self, env=None, b=1.0, run_params=None):
        self.extra_env = dict(env or {})
        self.b = b
        self.run_params = dict(run_params or {})

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='llmoses-m2-test-')
        self.run = self.tmp.name
        self.cfg = config(self.b)
        path = Path(self.run) / 'experiment.json'
        path.write_text(json.dumps(self.cfg))
        environment = {'LLMOSES_RUN_DIR': self.run, 'LLMOSES_CONFIG': str(path),
                       'LLMOSES_AWAIT_RESPONSE': '1', 'LLMOSES_RNG_SEED': '321'}
        environment.update(self.extra_env)
        self.env = patch.dict(os.environ, environment, clear=True)
        self.env.start()
        spec = importlib.util.spec_from_file_location('m2_fixture_builder', UTIL / 'state_builder.py')
        self.sb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sb)
        self.sb._exit_fn = lambda code: (_ for _ in ()).throw(Aborted(code))
        self.sb.new_run()
        params = {'problem_type': 'boolean', 'min_pool_size': 1,
                  'complexity_temperature': 1, 'complexity_ratio': 3.5}
        params.update(self.run_params)
        if params['problem_type'] == 'strategy':
            self.sb.set_problem_spec_strategy(['playwin', 'playblock'], 5,
                                             'random', params['complexity_ratio'])
        else:
            self.sb.set_problem_spec(['X1', 'X2', 'X3'])
        for key, value in params.items():
            self.sb.set_run_param(key, value)
        with patch.object(self.sb.runspace, 'ensure_context_docs'):
            self.sb.emit_run_config()
        self.sb.enter_gen(1)
        self.sb.begin_gen(1)
        self.sb.add_member(1, ['AND', 'X1'], tree('AND', [tree('X1')]),
                           [-1, 1, 0, 0, -1], ['mkBScore', [-1, 0]])
        self.sb.checkpoint_native(['mkM2Rows', ['test-frame']])
        return self

    def answer(self, call, doc=None):
        paths = call_paths.paths(self.run, 1, f'1-call-{call}')
        if doc is None:
            doc = {'run_seq': 1, 'generation': 1, 'call': call,
                   'pass': True, 'status': 204, 'outcome': {}}
        rc.write_json_atomic(paths['utilities'], doc)
        rc.write_json_atomic(paths['response'], {})
        return paths

    def advance_to(self, call, answers=None):
        """Drive the generation through calls 1..call-1 with neutral (pass)
        responses, or the per-call docs in `answers`, so the fence sits at
        call-1 and the next `_call(call)` is legal. Returns self.sb."""
        answers = answers or {}
        drivers = {1: lambda: (self.sb.call_rows(), self.sb.install_row_weights()),
                   2: self.sb.call_exemplar, 3: self.sb.call_atom}
        for step in range(1, call):
            self.answer(step, answers.get(step))
            drivers[step]()
        return self.sb

    def events(self, name=None):
        self.sb._NFH.flush()
        rows = [json.loads(line) for line in (Path(self.run) / 'moses_native_log.jsonl').read_text().splitlines()]
        return [row for row in rows if name is None or row['event'] == name]

    def __exit__(self, *unused):
        self.sb._NFH.close()
        self.env.stop()
        self.tmp.cleanup()
