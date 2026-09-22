"""Every way a lever can silently not fire must leave a visible, attributable mark.

The audit's recurring failure class was capability quietly disabled: a
schema gap read as "off", an env typo read as an ablation, a native
fallback read as an agent decision. These tests pin that each such path
either aborts or writes a reason the operator can read back.
"""
import json
import os
from pathlib import Path
import re
import threading
import time
import unittest
from m2_test_support import BuilderFixture, Aborted, ROOT, envelope, tree
import call_paths
import responder_control as rc

LLMOSES = ROOT / 'llmoses'


class GatesAreVisible(unittest.TestCase):
    def test_ablated_sections_say_gated_and_default_sections_are_present(self):
        with BuilderFixture(env={'LLMOSES_EMIT_SECTIONS': ''}) as f:
            f.sb._current_call = 3
            state = f.sb._payload(4)
            for key in ('demes', 'atom_evidence', 'atom_lossless'):
                self.assertEqual(state[key], {'gated': None}, key)
        with BuilderFixture() as f:
            f.sb._current_call = 3
            state = f.sb._payload(4)
            for key in ('demes', 'atom_evidence', 'atom_lossless'):
                self.assertNotIn('gated', state[key] if isinstance(state[key], dict) else {}, key)

    def test_unknown_section_name_aborts_instead_of_gating(self):
        with BuilderFixture(env={'LLMOSES_EMIT_SECTIONS': 'atom_evidenc,demes'}) as f:
            f.sb._current_call = 3
            with self.assertRaises(Aborted):
                f.sb._payload(4)
            aborted = f.events('run_aborted')[-1]
            self.assertEqual(aborted['reason'], 'unknown_emit_section')
            self.assertEqual(aborted['detail']['unknown'], ['atom_evidenc'])

    def test_guided_levers_on_a_non_boolean_problem_abort(self):
        with BuilderFixture(b=0) as f:
            sb = f.sb
            sb.set_run_param('problem_type', 'strategy')
            sb.emit_run_config()  # native strategy: fine
            sb._config['levers']['exemplar']['b'] = 0.5
            with self.assertRaises(Aborted):
                sb.emit_run_config()
            self.assertEqual(f.events('run_aborted')[-1]['reason'], 'unsupported_guided_problem')

    def test_native_strategy_does_not_treat_game_scores_as_shared_rows(self):
        for domain_source in ('matching', 'run_parameter', 'problem_spec'):
            with self.subTest(domain_source=domain_source), \
                    BuilderFixture(b=0, run_params={'problem_type': 'strategy'}) as f:
                sb = f.sb
                if domain_source == 'run_parameter':
                    # Preserve the original regression: the explicit run type
                    # must win even if a Boolean spec was installed earlier.
                    sb.set_problem_spec(['X1', 'X2', 'X3'])
                elif domain_source == 'problem_spec':
                    sb._pending_run_params.pop('problem_type')
                sb.clear_members(1)
                for label, scores in (('playwin', [1, 0, -1, 1, 0]),
                                      ('playblock', [-1000])):
                    total = sum(scores)
                    sb.add_member(1, label, tree(label), [total, 1, 0, 0, total],
                                  ['mkBScore', scores])
                sb.call_rows()
                sb.install_row_weights()
                self.assertEqual(sb._call_states[1]['problem_type'], 'strategy')
                self.assertEqual(sb._call_states[1]['rows'], [])
                self.assertEqual(sb._row_weights, [])
                self.assertEqual(sb._call_status[1], 'b_zero')
                self.assertEqual(sb.weighted_sum(['mkBScore', [1, 0, -1, 1, 0]], 1), 1)
                self.assertEqual(f.events('run_aborted'), [])


class SkippedCallsAreAttributed(unittest.TestCase):
    def check_skip(self, f, reason):
        sb = f.sb
        sb.call_rows()
        self.assertEqual(sb._call_status[1], reason)
        self.assertEqual(call_paths.ready_entries(f.run), [])
        skipped = f.events('call_skipped')
        self.assertEqual([(e['call'], e['reason']) for e in skipped], [(1, reason)])
        terminal = sb._terminal_doc(sb._gs(1)['members'], 'ok')
        self.assertEqual(terminal['response_window']['native_calls'],
                         [{'generation': 1, 'call': 1, 'reason': reason}])
        return terminal

    def test_outside_window_is_named_and_windowed(self):
        with BuilderFixture(env={'LLMOSES_EXPECT_RESPONSE_GENS': '2-3'}) as f:
            terminal = self.check_skip(f, 'outside_window')
            self.assertEqual(terminal['response_window']['spec'], '2-3')
            self.assertEqual(terminal['handshake']['expect_response_gens'], '2-3')
        for spec, inside in (('1', True), ('2', False), ('-1', True), ('3-', False), ('none', False), ('all', True)):
            with self.subTest(spec=spec), BuilderFixture(env={'LLMOSES_EXPECT_RESPONSE_GENS': spec}) as f:
                self.assertEqual(f.sb._EXPECT(1), inside)

    def test_await_disabled_is_named(self):
        with BuilderFixture(env={'LLMOSES_AWAIT_RESPONSE': '0'}) as f:
            terminal = self.check_skip(f, 'await_disabled')
            self.assertFalse(terminal['handshake']['await_enabled'])

    def test_b_zero_is_named_and_run_config_lists_no_active_levers(self):
        with BuilderFixture(b=0) as f:
            self.check_skip(f, 'b_zero')
            self.assertEqual(f.sb._run_config['active_levers'], [])

    def test_unreached_sites_are_logged_per_lever_at_generation_end(self):
        with BuilderFixture() as f:
            sb = f.advance_to(2)  # call 1 ran and recorded its site
            sb.flush_gen(1)
            sites = f.events('lever_site')
            missing = {(e['call'], e['lever']) for e in sites if e['reason'] == 'no_draw_site'}
            self.assertEqual(missing, {(2, 'exemplar'), (3, 'atom'), (4, 'retention')})
            self.assertEqual([e['call'] for e in sites if e['reason'] != 'no_draw_site'], [1])
            step = json.loads((Path(f.run) / 'state/run-1/step-1.json').read_text())
            self.assertEqual(step['call_status'], {'1': 'declined'})


class FencesAbort(unittest.TestCase):
    def test_generation_fence_requires_call_four_and_consecutive_generations(self):
        with BuilderFixture() as f:
            with self.assertRaises(Aborted):
                f.sb.enter_gen(2)
            self.assertEqual(f.events('run_aborted')[-1]['reason'], 'generation_fence')
        with BuilderFixture() as f:
            f.sb._current_call = 4
            f.sb.enter_gen(2)
            self.assertEqual((f.sb._current_gen, f.sb._current_call), (2, 0))
            f.sb._current_call = 4
            with self.assertRaises(Aborted):
                f.sb.enter_gen(4)
            self.assertEqual(f.events('run_aborted')[-1]['detail'],
                             {'previous_generation': 2, 'next_generation': 4})

    def test_unreleased_sampler_tokens_abort_at_generation_and_build_boundaries(self):
        with BuilderFixture() as f:
            sb = f.sb
            sb.begin_build(tree('AND'))
            token = sb.begin_combo_draw([[0, 1], [1, 0]], ['X1', 'X2'], 'AND', [])
            with self.assertRaises(Aborted):
                sb.begin_build(tree('OR'))
            aborted = f.events('run_aborted')[-1]
            self.assertEqual((aborted['reason'], aborted['detail']['tokens']),
                             ('interleaved_representation_build', [token]))
        with BuilderFixture() as f:
            sb = f.sb
            sb.begin_build(tree('AND'))
            token = sb.begin_combo_draw([[0, 1], [1, 0]], ['X1', 'X2'], 'AND', [])
            sb._current_call = 4
            with self.assertRaises(Aborted):
                sb.enter_gen(2)
            aborted = f.events('run_aborted')[-1]
            self.assertEqual((aborted['reason'], aborted['detail']['tokens']), ('unreleased_sampler_tokens', [token]))
        # a durable abort record is honoured on the next fence check (abort_requested)
        with BuilderFixture() as f:
            with self.assertRaises(Aborted):
                f.sb._abort_run('injected')
            f.sb._current_call = 4
            with self.assertRaises(Aborted):
                f.sb.enter_gen(2)
            self.assertEqual(f.events('run_aborted')[-1]['reason'], 'abort_requested')

    def test_invalid_pair_draw_aborts(self):
        with BuilderFixture() as f:
            sb = f.sb
            sb.begin_build(tree('AND'))
            token = sb.begin_combo_draw([[0, 1], [1, 0]], ['X1', 'X2'], 'AND', [])
            with self.assertRaises(Aborted):
                sb.end_combo_draw(token, [0, 0])
            self.assertEqual(f.events('run_aborted')[-1]['reason'], 'invalid_pair_draw')


class TimeoutsPauseNotProceed(unittest.TestCase):
    def test_response_timeout_pauses_with_checkpoint_and_resumes_on_exact_fence(self):
        with BuilderFixture(env={'LLMOSES_RESPONSE_TIMEOUT_S': '0.05', 'LLMOSES_RESPONSE_POLL_S': '0.005'}) as f:
            sb = f.sb
            errors, seen = [], {}

            def operator():
                try:
                    deadline = time.monotonic() + 4
                    pause_path = Path(f.run) / 'CONTROL/pause'
                    while not pause_path.exists() and time.monotonic() < deadline:
                        time.sleep(.005)
                    pause = rc.read_json(pause_path)
                    if pause is None:
                        raise AssertionError('timeout did not pause')
                    seen.update(pause)
                    if not Path(pause['checkpoint']).exists():
                        raise AssertionError('pause without durable checkpoint')
                    rc.write_json_atomic(Path(f.run) / 'CONTROL/resume', {'run_seq': 1, 'generation': 1, 'call': 1})
                    while pause_path.exists() and time.monotonic() < deadline:
                        time.sleep(.005)
                    f.answer(1, envelope(1, row_weights=[{'row': 0, 'weight': 2}, {'row': 1, 'weight': 1}]))
                except BaseException as exc:
                    errors.append(exc)
                    rc.request_abort(f.run, 'fixture_failure', 'test', str(exc))

            thread = threading.Thread(target=operator, daemon=True)
            thread.start()
            sb.call_rows()
            thread.join(4)
            self.assertFalse(thread.is_alive())
            if errors:
                raise errors[0]
            self.assertEqual(seen['reason'], 'response_timeout')
            self.assertEqual(sb._call_status[1], 'applied')
            self.assertEqual([e['event'] for e in f.events() if e['event'] in ('run_paused', 'run_resumed')],
                             ['run_paused', 'run_resumed'])
            # a paused call never counts as a degraded or skipped one
            self.assertEqual(f.events('call_skipped'), [])
            self.assertEqual(f.events('call_degraded'), [])


class RetiredIdentifiersStayRetired(unittest.TestCase):
    """Source sweep: retired controls and fields must not resurface anywhere an
    agent or operator reads. Allowlist only where the identifier exists to
    reject or to feed the operator log."""
    RETIRED = ('LLMOSES_APPLY_LEVERS', 'LLMOSES_LEVER_WEIGHT_', 'LLMOSES_UTILITY_POLICY', 'LLMOSES_LAMBDA',
               'LLMOSES_ATOM_LOSSLESS', 'depth_bucket', 'parent_operator', 'mean_penalized', 'n_best_tier',
               'utility_score', 'node_mask', 'path_mask', 'contextual_axes')
    ALLOW = {'utilities/lever_config.py': {'LLMOSES_APPLY_LEVERS', 'LLMOSES_LEVER_WEIGHT_',
                                           'LLMOSES_UTILITY_POLICY', 'LLMOSES_LAMBDA'},
             'utilities/atom_evidence.py': {'depth_bucket', 'mean_penalized', 'n_best_tier'}}
    SURFACES = ('skills/*.md', 'agent-configs/**/*.md', 'utilities/*.py', 'utilities/context_doc_templates/*.md',
                'configs/*.json', 'wrapper/*.metta', 'scoring/*.metta', 'metapopulation/*.metta',
                'deme/*.metta', 'representation/*.metta', 'run_m2.sh', 'readme.md')

    def test_no_retired_identifier_in_agent_or_operator_surfaces(self):
        offenders = []
        for pattern in self.SURFACES:
            for path in sorted(LLMOSES.glob(pattern)):
                rel = path.relative_to(LLMOSES).as_posix()
                text = path.read_text(encoding='utf-8', errors='replace')
                for identifier in self.RETIRED:
                    if identifier in self.ALLOW.get(rel, set()):
                        continue
                    for number, line in enumerate(text.splitlines(), 1):
                        if identifier in line and not re.search(r'retired|removed|never|no longer|not ', line, re.I):
                            offenders.append(f'{rel}:{number}: {identifier}')
        self.assertEqual(offenders, [])

    def test_atom_evidence_allowlist_feeds_only_the_rollup(self):
        text = (LLMOSES / 'utilities/atom_evidence.py').read_text()
        # the evidence and lossless dict literals must not name the retired fields
        evidence = text[text.index('evidence = {'):text.index('rollup = {')]
        for identifier in ('depth_bucket', 'score', 'parent_operator', 'mean_penalized'):
            self.assertNotIn(f'"{identifier}"', evidence)
        self.assertNotIn('LLMOSES_ATOM_LOSSLESS', text)
        self.assertNotIn('os.environ', text)


if __name__ == '__main__':
    unittest.main()
