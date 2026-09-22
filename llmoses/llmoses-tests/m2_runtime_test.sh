#!/usr/bin/env bash
# Prepared integration battery; run only after the implementation/testing handoff.
set -euo pipefail
if [[ $# != 1 ]]; then echo "usage: $0 NEW_OUTPUT_DIRECTORY" >&2; exit 2; fi
REPO=$(cd "$(dirname "$0")/../.." && pwd)
mkdir "$1"
OUT=$(cd "$1" && pwd)
case "$OUT" in "$REPO"/*) ;; *) echo "output must be inside repository" >&2; exit 2;; esac
python3 - "$REPO" "$OUT" <<'PY'
import json,sys
from pathlib import Path
repo,out=map(Path,sys.argv[1:])
source=json.loads((repo/'llmoses/configs/m2-closure.json').read_text())
def write(name, mutate):
    cfg=json.loads(json.dumps(source))
    mutate(cfg)
    (out/(name+'.json')).write_text(json.dumps(cfg))
def all_on(cfg, atom=1.0):
    for name, spec in cfg['levers'].items():
        spec['b'] = atom if name == 'atom' else 1.0
    cfg['retention'].update(mode='fixed', target=3, floor_coef=0, c_max=20)
write('off', lambda cfg: cfg['retention'].update(mode='fixed', target=3, floor_coef=0, c_max=20))
write('neutral', lambda cfg: all_on(cfg, atom=1.0))
write('guided', lambda cfg: all_on(cfg, atom=1.0))
write('identity', lambda cfg: all_on(cfg, atom=0.0))
write('pair_policy', lambda cfg: all_on(cfg, atom=1.0))
(out/'driver.metta').write_text(
    '!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)\n'
    '!(println! (booleanStateParity3Short))\n')
merge_lines=(repo/'llmoses/llmoses-tests/m2_merge_regression.metta').read_text().splitlines()
(out/'merge.metta').write_text(
    '!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)\n'+
    '\n'.join(line for line in merge_lines if not line.startswith('!(import!')))
(out/'trace.metta').write_text('''!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
!(sbNewRun)
!(py-call (state_builder.set_problem_spec (X1 X2)))
!(sbSetRunParam problem_type boolean)
!(sbEmitRunConfig)
!(py-call (state_builder.begin_build (mkTree (mkNode AND) ())))
!(println! (buildLogical (mkTree (mkNode AND) ()) AND () (X1 X2)))
''')
(out/'trace2.metta').write_text('''!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
!(sbNewRun)
!(py-call (state_builder.set_problem_spec (X1 X2)))
!(sbSetRunParam problem_type boolean)
!(sbEmitRunConfig)
!(py-call (state_builder.begin_build (mkTree (mkNode AND) (cons (mkTree (mkNode X1) ()) (cons (mkTree (mkNode X2) ()) ())))))
!(println! (buildLogical (mkTree (mkNode AND) (cons (mkTree (mkNode X1) ()) (cons (mkTree (mkNode X2) ()) ()))) AND () (X1 X2)))
''')
(out/'resume.metta').write_text(
    '!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)\n'
    '!(println! (sbResume))\n')
(out/'pause_controller.py').write_text(r'''#!/usr/bin/env python3
"""Answer calls until generation 2 call 1, then pause and abort."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'llmoses' / 'utilities'))
import call_paths
import responder_control as rc

run = Path(sys.argv[2])
deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    for seq, step, ready in call_paths.ready_entries(str(run)):
        # Ready filenames yield strings; response fences require integers.
        seq, gen, call = call_paths.key(seq, step)
        paths = call_paths.paths(str(run), seq, step)
        if gen >= 2 and call == 1:
            rc.write_json_atomic(run / 'CONTROL' / 'pause_requested',
                                 {'reason': 'operator_stop'})
            pause = run / 'CONTROL' / 'pause'
            while not pause.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not pause.exists():
                raise SystemExit('pause was never persisted')
            rc.request_abort(str(run), 'abort_requested', 'runtime-battery')
            raise SystemExit(0)
        if not Path(paths['response']).exists():
            rc.write_json_atomic(paths['utilities'], {
                'run_seq': seq, 'generation': gen, 'call': call,
                'pass': True, 'status': 204, 'outcome': {}})
            rc.write_json_atomic(paths['response'], {})
    time.sleep(0.05)
raise SystemExit('controller timed out before generation 2')
''')
PY
export LLMOSES_RNG_SEED=101
bash "$REPO/llmoses/run_m2.sh" "$OUT/off.json" "$OUT/off" "$OUT/driver.metta" external
bash "$REPO/llmoses/run_m2.sh" "$OUT/neutral.json" "$OUT/neutral" "$OUT/driver.metta" neutral
bash "$REPO/llmoses/run_m2.sh" "$OUT/guided.json" "$OUT/guided" "$OUT/driver.metta" prefer_worst
bash "$REPO/llmoses/run_m2.sh" "$OUT/identity.json" "$OUT/identity" "$OUT/driver.metta" identity
bash "$REPO/llmoses/run_m2.sh" "$OUT/pair_policy.json" "$OUT/pair_policy" "$OUT/driver.metta" pair_policy
bash "$REPO/llmoses/run_m2.sh" "$OUT/off.json" "$OUT/merge" "$OUT/merge.metta" external
bash "$REPO/llmoses/run_m2.sh" "$OUT/off.json" "$OUT/trace" "$OUT/trace.metta" external
bash "$REPO/llmoses/run_m2.sh" "$OUT/off.json" "$OUT/trace2" "$OUT/trace2.metta" external
bash "$REPO/llmoses/run_m2.sh" "$OUT/identity.json" "$OUT/full" "$OUT/driver.metta" identity
mkdir -p "$OUT/paused"
CONTROLLER=
cleanup_controller() {
  if [[ -n "$CONTROLLER" ]]; then
    kill "$CONTROLLER" 2>/dev/null || true
    wait "$CONTROLLER" 2>/dev/null || true
  fi
}
trap cleanup_controller EXIT
python3 "$OUT/pause_controller.py" "$REPO" "$OUT/paused" &
CONTROLLER=$!
printf 'controller_pid=%s\n' "$CONTROLLER" > "$OUT/paused/controller-resources.txt"
set +e
bash "$REPO/llmoses/run_m2.sh" "$OUT/identity.json" "$OUT/paused" "$OUT/driver.metta" external
PAUSED_RC=$?
set -e
CONTROLLER_RC=0
wait "$CONTROLLER" || CONTROLLER_RC=$?
CONTROLLER=
if [[ "$CONTROLLER_RC" != 0 ]]; then
  echo "pause controller exited $CONTROLLER_RC" >&2
  exit "$CONTROLLER_RC"
fi
if [[ "$PAUSED_RC" != 3 ]]; then
  echo "paused arm exited $PAUSED_RC, expected abort 3" >&2
  exit 1
fi
PAUSE=$(python3 - "$REPO" "$OUT/paused/CONTROL/pause" <<'PY'
import json,sys
from pathlib import Path
checkpoint=Path(json.loads(Path(sys.argv[2]).read_text())['checkpoint'])
# The pause record was written inside Docker; run_m2.sh accepts host paths.
print(Path(sys.argv[1])/checkpoint.relative_to('/workspace/metta-moses'))
PY
)
python3 - "$OUT/paused" <<'PY'
import json,sys
from pathlib import Path
run=Path(sys.argv[1])
pause=json.loads((run/'CONTROL'/'pause').read_text())
(run/'CONTROL'/'abort').unlink()
(run/'CONTROL'/'resume').write_text(json.dumps({k: pause[k] for k in ('run_seq','generation','call')}))
PY
LLMOSES_RESUME_CHECKPOINT="$PAUSE" bash "$REPO/llmoses/run_m2.sh" \
  "$OUT/identity.json" "$OUT/paused" "$OUT/resume.metta" identity
python3 "$REPO/llmoses/llmoses-tests/live_agent_verify.py" \
  "$OUT/off" "$OUT/neutral" "$OUT/guided" \
  --identity "$OUT/identity" \
  --pair-policy "$OUT/pair_policy" \
  --trace "$OUT/trace" --trace2 "$OUT/trace2" \
  --resume "$OUT/paused" "$OUT/full" \
  --merge "$OUT/merge"
