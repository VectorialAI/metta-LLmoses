#!/usr/bin/env python3
"""Verify protocol-2 runtime artifacts; this module makes no provider calls.

Arms (each is a run directory produced by llmoses/run_m2.sh):
  positional   off / neutral / guided arms: artifacts well-formed, off == neutral,
               guided offsets move the prior in the direction of the offsets
  --identity   b > 0 with zero offsets: sites fire, A == P, trajectory == off (P8)
  --pair-policy  base weight on one ordered pair raises its realized mass
  --trace      empty exemplar: draw sites and causal depth as documented
  --trace2     non-empty exemplar: sequential site identity and depth invariants
  --resume PAUSED FULL   pause/stop/cold-resume trajectory equals the uninterrupted run
  --merge      merge/regression driver log free of assertion failures
  --smoke RUN --expect-gens N --expect-demes M   native (await-disabled) MeTTa run
               --problem-type strategy selects strategy state/knob contracts
"""
import argparse
import json
import re
from pathlib import Path

SKIP_REASONS = {'b_zero', 'await_disabled', 'outside_window'}
SITE_KINDS = {'exemplar_node', 'appended_child', 'literal_wrap', 'sampled_subtree'}
SITE_KEYS = ('P', 'adjustment', 'A', 'D0', 'D', 'tv_agent', 'tv_realized', 'coverage')


def read(path):
    return json.loads(path.read_text())


def events(run):
    return [json.loads(line) for line in (run / 'moses_native_log.jsonl').read_text().splitlines()]


def sites(run, call=None):
    rows = [e for e in events(run) if e['event'] == 'lever_site']
    return rows if call is None else [e for e in rows if e['call'] == call]


def trajectory(terminal):
    members = terminal['metapopulation']['members']
    return (sorted((m['program_id'], m['cscore']['penalized_score']) for m in members),
            terminal['total_evaluations'])


def directional(site):
    """Exponential tilting / convex reweighting raises the expectation of the
    adjustment under A relative to P: sum adj_i (A_i - P_i) > 0 unless the
    adjustment is constant."""
    adj, P, A = site['adjustment'], site['P'], site['A']
    if not adj or max(adj) == min(adj):
        return None
    return sum(a * (x - p) for a, x, p in zip(adj, A, P))


def verify(run, require_guidance=False):
    terminal = read(run / 'state/run-1/terminal.json')
    assert terminal['run_verdict'] == 'ok', terminal
    states = sorted((run / 'state/run-1').glob('step-*-call-*.json'))
    for path in states:
        state = read(path)
        assert state['capture_status']['ok'], path
        utility = read(run / 'utilities/run-1' / path.name)
        assert tuple(utility[k] for k in ('run_seq', 'generation', 'call')) == \
            tuple(state[k] for k in ('run_seq', 'generation', 'call'))
        if state['call'] == 2 and any(w != 1 for w in state['row_weights']):
            for member in state['candidates']:
                weighted = sum(w * b for w, b in zip(state['row_weights'], member['bscore']))
                assert abs(weighted - member['cscore']['raw_score']) < 1e-9, member
        if state['call'] == 4:
            for block in ('atom_evidence', 'atom_lossless'):
                assert isinstance(state[block], dict) and 'gated' not in state[block], (path, block)
            for row in state['atom_evidence']['atom_appearances']:
                assert not {'depth_bucket', 'score', 'parent_operator'} & set(row), row
            assert state['atom_lossless']['programs'], path
    all_sites = sites(run)
    assert all_sites, 'no lever sites observed'
    for site in all_sites:
        assert all(k in site for k in SITE_KEYS), site
        if site['call'] == 4 and 'budget' in site:
            k = site['budget']['K']
            assert len(site['survivors']) == k, site
            assert abs(sum(site['inclusion_probabilities']) - k) < 1e-9, site
    if require_guidance:
        fired = [s for s in all_sites if s['fired'] and s['call'] in (1, 2, 4)]
        assert fired, 'guided arm never fired a lever'
        moved = [directional(s) for s in fired]
        assert any(m is not None for m in moved), 'guided arm never sent a non-constant adjustment'
        for site, m in zip(fired, moved):
            if m is not None:
                assert m > 1e-12, ('adjustment did not move the prior in its own direction', site)
                worst = max(range(len(site['adjustment'])), key=site['adjustment'].__getitem__)
                assert site['A'][worst] > site['P'][worst], ('favoured member lost mass', site)
        assert any(s['tv_realized'] > 1e-9 for s in fired), 'guidance never reached the realized distribution'
    return terminal, events(run)


def verify_identity(identity, off):
    terminal, _ = verify(identity)
    fired = [s for s in sites(identity) if s['fired']]
    assert fired, 'identity arm never fired a lever (b must be > 0)'
    for site in fired:
        if site['call'] == 3:
            assert all(all(v == 1.0 for v in factors) for factors in site['adjustment']), site
        else:
            neutral_value = 1.0 if site['call'] == 1 else 0.0
            assert all(a == neutral_value for a in site['adjustment']), site
        assert all(abs(a - p) < 1e-12 for a, p in zip(site['A'], site['P'])), site
        assert site['tv_agent'] < 1e-12 and site['tv_realized'] < 1e-12, site
    assert trajectory(terminal) == trajectory(read(off / 'state/run-1/terminal.json')), \
        'identity offsets changed the trajectory: P8 violated'


def verify_pair_policy(run):
    verify(run)
    draws = [s for s in sites(run, 3) if s['fired']]
    assert draws, 'pair_policy arm produced no fired draw sites'
    moved = 0
    for site in draws:
        universe = site['pair_universe']
        first = universe.index(['X1', 'X2']) if ['X1', 'X2'] in universe else None
        assert site['coverage'] > 0, site
        if first is not None:
            assert site['D'][first] > site['P'][first] + 1e-12, ('weighted pair lost mass', site)
            moved += 1
        assert site['picks'], site
    assert moved, 'no draw site offered the weighted pair'


def verify_trace(run):
    draws = sites(run, 3)
    # Empty exemplar: inserted mkNullVex knobs do not recurse; appended child
    # does draw, despite sharing the upstream probe path with the root.
    assert [d['causal_state']['site_kind'] for d in draws] == ['exemplar_node', 'appended_child'], draws
    assert [d['causal_state']['depth'] for d in draws] == [0, 1], draws
    assert len({d['site_seq'] for d in draws}) == 2
    assert all(d['P'] == d['D'] for d in draws)


def verify_trace2(run):
    draws = sites(run, 3)
    assert draws, 'non-empty exemplar produced no draw sites'
    seqs = [d['site_seq'] for d in draws]
    assert seqs == list(range(1, len(seqs) + 1)), ('site identity must be sequential', seqs)
    for d in draws:
        assert d['causal_state']['site_kind'] in SITE_KINDS, d
        assert d['causal_state']['depth'] == len(d['path']), d
        assert d['P'] == d['D'], d
        assert len(d['drawn_pairs']) >= 1, d
    kinds = {d['causal_state']['site_kind'] for d in draws}
    assert 'exemplar_node' in kinds, kinds
    assert not any(e['event'] == 'run_aborted' for e in events(run)), 'trace run aborted'


def verify_resume(paused, full):
    log = events(paused)
    names = [e['event'] for e in log]
    assert 'run_paused' in names and 'run_aborted' in names and 'run_resumed' in names, names
    assert names.count('run_paused') == names.count('run_resumed') == 1, names
    assert names.count('run_aborted') == 1, names
    paused_event = next(e for e in log if e['event'] == 'run_paused')
    assert paused_event['reason'] == 'operator_stop', paused_event
    assert paused_event['generation'] >= 2, ('stop must land after at least one full generation', paused_event)
    aborted = next(e for e in log if e['event'] == 'run_aborted')
    assert aborted['reason'] == 'abort_requested', aborted
    assert names.index('run_paused') < names.index('run_aborted') < names.index('run_resumed'), \
        'resume must follow the pause and stop'
    terminal = read(paused / 'state/run-1/terminal.json')
    assert terminal['run_verdict'] == 'ok', terminal
    full_terminal = read(full / 'state/run-1/terminal.json')
    assert full_terminal['run_verdict'] == 'ok', full_terminal
    assert terminal['generation'] == full_terminal['generation'], (terminal, full_terminal)
    assert trajectory(terminal) == trajectory(full_terminal), \
        'cold checkpoint replay diverged from the uninterrupted run'
    completed = [e['generation'] for e in log if e['event'] == 'generation_complete']
    full_completed = [e['generation'] for e in events(full) if e['event'] == 'generation_complete']
    assert full_completed and full_completed == list(range(1, full_completed[-1] + 1)), full_completed
    assert completed == full_completed, ('generations replayed or skipped', completed, full_completed)
    after_resume = [e['generation'] for e in log[names.index('run_resumed') + 1:]
                    if e['event'] == 'generation_complete']
    assert after_resume == list(range(paused_event['generation'], full_completed[-1] + 1)) and after_resume, \
        ('continuation did not complete the remaining generations', after_resume)


def verify_smoke(run, expect_gens, expect_demes, problem_type='boolean'):
    state_dir = run / 'state/run-1'
    terminal = read(state_dir / 'terminal.json')
    assert terminal['run_verdict'] == 'ok', terminal
    config = read(state_dir / 'run_config.json')
    assert config['record_type'] == 'run_config', config
    problem = config['problem_spec']
    assert problem['problem_type'] == problem_type, problem
    assert config['run_parameters']['problem_type'] == problem_type, config['run_parameters']
    assert terminal['problem_spec']['problem_type'] == problem_type, terminal
    prefix = {'boolean': 'feature', 'strategy': 'move'}[problem_type]
    assert config['atom_alphabet']['prefix'] == prefix and config['atom_alphabet']['atoms'], config
    if problem_type == 'strategy':
        assert problem['moves'] and problem['n_games'] > 0, problem
        assert problem['opponent_policy'] not in (None, '', 'None'), problem
    assert 'complexity_coef' in config['run_parameters'] and 'complexity_ratio' not in config['run_parameters']
    assert config['active_levers'] == [], ('native smoke run must not activate a lever', config['active_levers'])
    for g in range(1, expect_gens + 1):
        step = read(state_dir / f'step-{g}.json')
        assert step['generation'] == g, step
        assert step['metapopulation']['members'], f'empty metapopulation in step-{g}'
        demes = step['demes']
        assert len(demes) >= expect_demes, (g, len(demes))
        knobs = [k for d in demes for k in d.get('knobs', [])]
        kinds = {k['kind'] for k in knobs}
        assert kinds == {problem_type}, (g, kinds)
        if problem_type == 'strategy':
            assert all(k['multiplicity'] == 2 for k in knobs), (g, knobs)
        assert set(step['call_status']) == {'1', '2', '3', '4'}, (g, step['call_status'])
        assert set(step['call_status'].values()) <= SKIP_REASONS, (g, step['call_status'])
    log = events(run)
    assert not any(e['event'] == 'run_aborted' for e in log)
    completed = [e['generation'] for e in log if e['event'] == 'generation_complete']
    assert completed == list(range(1, expect_gens + 1)), completed
    for site in (e for e in log if e['event'] == 'lever_site'):
        assert site['P'] == site['D'], ('native run realized a non-native distribution', site)
    assert not list((run / 'ready').glob('run-*-step-*')) if (run / 'ready').exists() else True, \
        'native run must not publish ready sentinels'
    print(f'PASS_SCHEMA: {run.name} ({expect_gens} generations, {len(completed)} completed)')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('runs', nargs='*', type=Path)
    parser.add_argument('--identity', type=Path)
    parser.add_argument('--pair-policy', type=Path)
    parser.add_argument('--trace', type=Path)
    parser.add_argument('--trace2', type=Path)
    parser.add_argument('--resume', nargs=2, type=Path, metavar=('PAUSED', 'FULL'))
    parser.add_argument('--merge', type=Path)
    parser.add_argument('--smoke', type=Path)
    parser.add_argument('--expect-gens', type=int, default=1)
    parser.add_argument('--expect-demes', type=int, default=1)
    parser.add_argument('--problem-type', choices=('boolean', 'strategy'), default='boolean')
    args = parser.parse_args()
    if args.smoke:
        verify_smoke(args.smoke, args.expect_gens, args.expect_demes, args.problem_type)
        return
    results = [verify(run, run.name == 'guided') for run in args.runs]
    by_name = {run.name: result for run, result in zip(args.runs, results)}
    if 'off' in by_name and 'neutral' in by_name:
        # Same redesigned retention baseline. Neutral responses consume no RNG.
        left, right = (by_name[k][0] for k in ('off', 'neutral'))
        assert left['metapopulation'] == right['metapopulation'], 'neutral arm differs from off'
        assert left['total_evaluations'] == right['total_evaluations']
    if 'off' in by_name and 'guided' in by_name:
        assert trajectory(by_name['guided'][0]) != trajectory(by_name['off'][0]), \
            'guided arm reproduced the off trajectory exactly: levers had no effect'
    if args.identity:
        off = next((run for run in args.runs if run.name == 'off'), None)
        assert off is not None, '--identity requires the off arm'
        verify_identity(args.identity, off)
    if args.pair_policy:
        verify_pair_policy(args.pair_policy)
    if args.trace:
        verify_trace(args.trace)
    if args.trace2:
        verify_trace2(args.trace2)
    if args.resume:
        verify_resume(*args.resume)
    if args.merge:
        text = re.sub(r'\x1b\[[0-9;]*m', '', (args.merge / 'driver.log').read_text())
        # Verbose PeTTa prints source definitions containing Error/FAIL. Check
        # runtime assertion diagnostics and an executed, standalone PASS line.
        assert '❌' not in text and 'Assertion failed' not in text, text[-2000:]
        assert not re.search(r'^\s*ERROR:', text, re.M), text[-2000:]
        assert re.search(r'^\s*"?m2-merge-regression: PASS"?\s*$', text, re.M), text[-2000:]
    print('M2 runtime artifacts: PASS')


if __name__ == '__main__':
    main()
