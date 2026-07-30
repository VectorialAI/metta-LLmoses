#!/usr/bin/env bash
# ============================================================================
# run_strategy_smoke_test.sh — strategy LLMOSES smoke + pressure regression
#
# Targeted tic-tac-toe fixture runs (NOT classic boolean demos).
# For classic demos use: ./run_moses_demo.sh demo <key>
#
# Usage:
#   ./run_strategy_smoke_test.sh list
#   ./run_strategy_smoke_test.sh metta expand-single
#   ./run_strategy_smoke_test.sh metta all
#   ./run_strategy_smoke_test.sh state merge-cull-pressure
#   ./run_strategy_smoke_test.sh state all
#   ./run_strategy_smoke_test.sh all
# ============================================================================
set -euo pipefail

TRACE="summary"
HEAD_N=80
KEEP_DRIVER=0
TEST_REL="llmoses/llmoses-tests/strategy_test.metta"
RUN_ID_OVERRIDE=""
LOGDIR_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --trace)
      TRACE="${2:-}"
      [[ "$TRACE" == "full" || "$TRACE" == "summary" || "$TRACE" == "partial" ]] || { echo "ERROR: --trace full|summary|partial" >&2; exit 2; }
      shift 2 ;;
    --head)
      HEAD_N="${2:-}"
      [[ "$HEAD_N" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: --head must be positive integer" >&2; exit 2; }
      shift 2 ;;
    --keep-driver) KEEP_DRIVER=1; shift ;;
    --test-file)
      TEST_REL="${2:-}"
      shift 2 ;;
    --run-id)
      RUN_ID_OVERRIDE="${2:-}"
      shift 2 ;;
    --log-dir)
      LOGDIR_OVERRIDE="${2:-}"
      shift 2 ;;
    --) shift; break ;;
    -*) echo "ERROR: unknown option '$1'" >&2; exit 2 ;;
    *) break ;;
  esac
done

REPO="${REPO:-$PWD}"
TEST_FILE="$REPO/$TEST_REL"
[[ -f "$TEST_FILE" ]] || { echo "ERROR: missing $TEST_REL under REPO=$REPO" >&2; exit 2; }

RUN_SH="$(command -v run.sh 2>/dev/null || true)"
if [[ -z "$RUN_SH" ]]; then
  RUN_SH="$(find / -name run.sh -type f -path '*PeTTa*' 2>/dev/null | head -n1 || true)"
fi
[[ -n "$RUN_SH" && -f "$RUN_SH" ]] || { echo "ERROR: could not locate PeTTa run.sh" >&2; exit 2; }

STAMP="${RUN_ID_OVERRIDE:-$(date +%Y%m%d-%H%M%S)}"
RUN_ID="$STAMP"
OUTPUT_ROOT="$REPO/llmoses/outputs"
RUNS_ROOT="$OUTPUT_ROOT/runs"
RUN_DIR="$RUNS_ROOT/$RUN_ID"
LOGDIR="${LOGDIR_OVERRIDE:-$OUTPUT_ROOT/logs}"
DRIVER_DIR="$REPO/llmoses/llmoses-tests"
mkdir -p "$LOGDIR" "$RUN_DIR" "$DRIVER_DIR"

METTA_CASES=(
  expand-single
  expand-multideme
  run-single
  max-candidate-cap
  game-context-scoring
  multigen-multideme
  empty-seed
  merge-cull-pressure
)

STATE_CASES=(
  single
  multigen-multideme
  empty-seed
  merge-cull-smoke
  merge-cull-pressure
  deep-lineage
)

strategy_metta_tier() {
  case "$1" in
    expand-single|expand-multideme|run-single|game-context-scoring|empty-seed)
      echo smoke ;;
    max-candidate-cap|multigen-multideme|merge-cull-pressure)
      echo pressure ;;
    *) return 1 ;;
  esac
}

strategy_state_tier() {
  case "$1" in
    single|multigen-multideme|empty-seed|merge-cull-smoke)
      echo smoke ;;
    merge-cull-pressure|deep-lineage)
      echo pressure ;;
    *) return 1 ;;
  esac
}

metta_func() {
  case "$1" in
    expand-single) echo "strategyExpandSingleDemeTest" ;;
    expand-multideme) echo "strategyExpandMultiDemeTest" ;;
    run-single) echo "strategyRunSingleGenerationTest" ;;
    max-candidate-cap) echo "strategyRunMaxCandidateCapTest" ;;
    game-context-scoring) echo "strategyGameContextScoringTest" ;;
    multigen-multideme) echo "strategyRunMultiGenerationMultiDemeTest" ;;
    empty-seed) echo "strategyRunEmptySeedTest" ;;
    merge-cull-pressure) echo "strategyMergeCullPressureTest" ;;
    *) return 1 ;;
  esac
}

state_func() {
  case "$1" in
    single)               echo "strategyStateSingle" ;;
    multigen-multideme)   echo "strategyStateMultigenMultideme" ;;
    empty-seed)           echo "strategyStateEmptySeed" ;;
    merge-cull-smoke)     echo "strategyStateMergeCullSmoke" ;;
    merge-cull-pressure)  echo "strategyStateMergeCullPressure" ;;
    deep-lineage)         echo "strategyStateDeepLineage" ;;
    *) return 1 ;;
  esac
}

state_expected_gens() {
  case "$1" in
    single) echo 1 ;;
    multigen-multideme) echo 3 ;;
    empty-seed|merge-cull-smoke|merge-cull-pressure) echo 2 ;;
    deep-lineage) echo 5 ;;
    *) return 1 ;;
  esac
}

state_expected_demes() {
  case "$1" in
    single) echo 1 ;;
    multigen-multideme|empty-seed|merge-cull-smoke|merge-cull-pressure|deep-lineage) echo 2 ;;
    *) return 1 ;;
  esac
}

make_driver_name() {
  local kind="$1" case_name="$2"
  echo "llmoses/llmoses-tests/_strategy_${kind}_${case_name}_${RUN_ID}.metta"
}

cleanup_driver() {
  local driver="$1"
  [[ "$KEEP_DRIVER" -eq 0 ]] && rm -f "$driver"
}

run_traced() {
  local stem="$1"
  shift
  [[ "${1:-}" == "--" ]] && shift
  local log="$LOGDIR/${stem}-${RUN_ID}.log"
  local rc=0
  if [[ "$TRACE" == "full" ]]; then
    (cd "$REPO" && LLMOSES_RUN_ID="$RUN_ID" "$@") 2>&1 | tee "$log" || rc=${PIPESTATUS[0]}
  else
    local tmp
    tmp="$(mktemp)"
    (cd "$REPO" && LLMOSES_RUN_ID="$RUN_ID" "$@") >"$tmp" 2>&1 || rc=$?
    case "$TRACE" in
      partial)
        head -n "$HEAD_N" "$tmp" || true
        local total
        total="$(wc -l < "$tmp")"
        (( total > HEAD_N )) && echo "... $((total - HEAD_N)) more lines (${total} total)"
        ;;
      summary)
        grep -iE "(strategy-state|strategy-metta|result-size|error[: ]|Type error|assertEq|FAILED|PASS|FAIL|New best score|Merging Deme|Metapop size)" "$tmp" || true
        echo "--- last $HEAD_N lines ---"
        tail -n "$HEAD_N" "$tmp" || true
        echo "--- end ($(wc -l < "$tmp") lines total) ---"
        ;;
    esac
    cp "$tmp" "$log"
    rm -f "$tmp"
  fi
  echo "Saved: $log"
  return "$rc"
}

list_cases() {
  echo "Output root:      $OUTPUT_ROOT"
  echo "Logs:             $LOGDIR"
  echo "State run dir:    $RUN_DIR"
  echo "Run ID:           $RUN_ID"
  echo "Test file:        $TEST_REL"
  echo
  echo "MeTTa unit cases:"
  local c
  for c in "${METTA_CASES[@]}"; do
    echo "  metta $c [$(strategy_metta_tier "$c")]"
  done
  echo "  metta all"
  echo
  echo "State/action JSON cases:"
  for c in "${STATE_CASES[@]}"; do
    echo "  state $c [$(strategy_state_tier "$c")]"
  done
  echo "  state all"
  echo
  echo "Combined:  all"
  echo
  echo "Classic MOSES demos:  ./run_moses_demo.sh demo pa"
}

case_in_array() {
  local needle="$1"; shift
  local x
  for x in "$@"; do [[ "$x" == "$needle" ]] && return 0; done
  return 1
}

run_metta_case() {
  local case_name="$1" fn driver_rel driver rc=0
  fn="$(metta_func "$case_name")" || { echo "ERROR: unknown metta case '$case_name'" >&2; return 2; }
  driver_rel="$(make_driver_name metta "$case_name")"
  driver="$REPO/$driver_rel"

  cat > "$driver" <<EOF
;; AUTO-GENERATED strategy MeTTa unit driver.
!(import! &self $TEST_REL)
!(println! "================ strategy-metta run: $case_name begin ================")
!(println! (strategy-metta-result $case_name ($fn)))
!(println! "================ strategy-metta run: $case_name end ==================")
EOF

  echo "Running MeTTa strategy case: $case_name"
  run_traced "strategy-metta-${case_name}" -- "$RUN_SH" "$driver_rel" || rc=$?
  cleanup_driver "$driver"
  return "$rc"
}

reset_native_emission() {
  mkdir -p "$RUN_DIR/state" "$RUN_DIR/action" "$RUN_DIR/ready"
  find "$RUN_DIR/state"  -maxdepth 1 -type d -name 'run-*' -exec rm -rf {} + 2>/dev/null || true
  find "$RUN_DIR/action" -maxdepth 1 -type d -name 'run-*' -exec rm -rf {} + 2>/dev/null || true
  find "$RUN_DIR/ready"  -maxdepth 1 -type f -name 'run-*-step-*' -delete 2>/dev/null || true
}

validate_case_json() {
  local case_name="$1" expected_gens="$2" expected_demes="$3"
  python3 - "$RUN_DIR" "$case_name" "$expected_gens" "$expected_demes" <<'PY'
import json, sys
from pathlib import Path
run_dir = Path(sys.argv[1])
case = sys.argv[2]
expected_gens = int(sys.argv[3])
expected_demes = int(sys.argv[4])
state_dir = run_dir / "state" / case
action_dir = run_dir / "action" / case
ready_dir = run_dir / "ready" / case

def fail(msg):
    print(f"FAIL_SCHEMA: {msg}", file=sys.stderr)
    sys.exit(1)

if not state_dir.is_dir(): fail(f"missing archived state dir {state_dir}")
if not action_dir.is_dir(): fail(f"missing archived action dir {action_dir}")
if not ready_dir.is_dir(): fail(f"missing archived ready dir {ready_dir}")

steps = []
actions = []
run_config_path = state_dir / "run_config.json"
if not run_config_path.exists():
    fail(f"missing run_config.json in {state_dir}")
with run_config_path.open() as fh:
    rc = json.load(fh)
if rc.get("record_type") != "run_config":
    fail("run_config record_type mismatch")
ps = rc.get("problem_spec", {})
if ps.get("problem_type") != "strategy":
    fail("run_config problem_spec not strategy")
if not ps.get("moves"):
    fail("missing strategy moves in run_config")
if ps.get("n_games") is None:
    fail("missing n_games in run_config problem_spec")
if ps.get("opponent_policy") in (None, "", "None"):
    fail("missing opponent_policy in run_config")
if ps.get("complexity_ratio") is None:
    fail("missing problem_spec complexity_ratio in run_config")
alphabet = rc.get("atom_alphabet", {})
if alphabet.get("prefix") != "move":
    fail("run_config atom_alphabet prefix not move")
if not alphabet.get("atoms"):
    fail("missing atom_alphabet atoms in run_config")
rp = rc.get("run_parameters", {})
if rp.get("problem_type") != "strategy":
    fail("run_config run_parameters.problem_type not strategy")
if rp.get("complexity_ratio") is None:
    fail("missing run_parameters complexity_ratio in run_config")
levers = rc.get("active_levers", [])
for need in ("exemplar_selection", "culling", "atom_evidence", "complexity_ratio", "comparator_hook"):
    if need not in levers:
        fail(f"missing active_lever {need} in run_config")
if rc.get("comparator_hook_available") is not True:
    fail("run_config comparator_hook_available not true")

for g in range(1, expected_gens + 1):
    sp = state_dir / f"step-{g}.json"
    ap = action_dir / f"step-{g}.json"
    if not sp.exists(): fail(f"missing {sp}")
    if not ap.exists(): fail(f"missing {ap}")
    with sp.open() as fh: s = json.load(fh)
    with ap.open() as fh: a = json.load(fh)
    steps.append(s)
    actions.append(a)
    if s.get("generation") != g: fail(f"state generation mismatch in step-{g}")
    if a.get("generation") != g: fail(f"action generation mismatch in step-{g}")
    if s.get("problem_type") != "strategy": fail(f"state problem_type not strategy in step-{g}")
    if a.get("problem_type") != "strategy": fail(f"action problem_type not strategy in step-{g}")
    for static_key in ("problem_spec", "run_parameters", "active_levers", "comparator_hook_available"):
        if static_key in s:
            fail(f"static key {static_key} must not appear in per-step state step-{g}")
    if "active_levers" in a:
        fail(f"active_levers must not appear in per-step action step-{g}")
    for removed in ("selected_program_id", "selection_status", "selection_detail"):
        if removed in a:
            fail(f"realized selection field {removed} must not appear in action step-{g}")
    if s.get("score_vs_complexity_trend") is None:
        fail(f"missing score_vs_complexity_trend in state step-{g}")
    ae = s.get("atom_evidence")
    if not isinstance(ae, dict):
        fail(f"missing atom_evidence in state step-{g}")
    for key in ("atom_appearances", "realized_cooccurrences", "atom_cumulative", "degenerate_summary"):
        if key not in ae:
            fail(f"missing atom_evidence.{key} in state step-{g}")
    demes = s.get("demes", [])
    if len(demes) < expected_demes: fail(f"expected at least {expected_demes} demes in step-{g}, got {len(demes)}")
    saw_strategy_knob = False
    for d in demes:
        if "operator_inclusion_set" in d:
            fail(f"operator_inclusion_set must not appear in deme step-{g}")
        kb = d.get("knob_type_breakdown", {})
        if kb.get("logical", 0) != 0: fail(f"logical knobs present in strategy deme step-{g}: {kb}")
        for k in d.get("knobs", []):
            if k.get("kind") == "strategy":
                saw_strategy_knob = True
                if k.get("multiplicity") != 2: fail(f"strategy knob multiplicity not 2 in step-{g}: {k}")
    if not saw_strategy_knob: fail(f"no SSK/strategy knobs found in step-{g}")
    ms = s.get("merge_summary")
    if not isinstance(ms, dict): fail(f"missing merge_summary in step-{g}")
    rz = ms.get("resize_cull")
    if not isinstance(rz, dict): fail(f"missing merge_summary.resize_cull in step-{g}")
    for key in ("incumbents", "survivors", "culled", "new_entrants"):
        if key not in rz: fail(f"missing resize_cull.{key} in step-{g}")
    post = s.get("moses_native_events", {}).get("post_selection")
    if post is None: fail(f"missing post_selection in step-{g}")
    if post.get("selection_status") not in ("ok", "no_selection"):
        fail(f"bad selection_status in step-{g}: {post.get('selection_status')}")
    cands = a.get("exemplar_candidates", [])
    if not cands: fail(f"no action exemplar_candidates in step-{g}")
    if "culling_candidates" not in a:
        fail(f"missing culling_candidates in action step-{g}")
    cr = a.get("complexity_ratio", {})
    if not cr.get("options"):
        fail(f"missing complexity_ratio.options in action step-{g}")

terminal = state_dir / "terminal.json"
if not terminal.exists(): fail(f"missing terminal {terminal}")
with terminal.open() as fh: t = json.load(fh)
if t.get("record_type") != "terminal": fail("terminal record_type mismatch")
if t.get("problem_spec", {}).get("problem_type") != "strategy": fail("terminal problem_spec not strategy")
if t.get("run_parameters", {}).get("problem_type") != "strategy": fail("terminal run_parameters not strategy")
ready_files = list(ready_dir.glob("run-*-step-*"))
if len(ready_files) < expected_gens: fail(f"expected at least {expected_gens} ready sentinels, got {len(ready_files)}")
print(f"PASS_SCHEMA: {case} ({expected_gens} steps, {len(ready_files)} ready sentinels)")
PY
}

archive_state_case() {
  local case_name="$1" expected_gens="$2" expected_demes="$3"
  local state_run action_run
  state_run="$(find "$RUN_DIR/state" -maxdepth 1 -type d -name 'run-*' | sort | tail -n1)"
  action_run="$(find "$RUN_DIR/action" -maxdepth 1 -type d -name 'run-*' | sort | tail -n1)"
  local state_case="$RUN_DIR/state/$case_name"
  local action_case="$RUN_DIR/action/$case_name"
  local ready_case="$RUN_DIR/ready/$case_name"

  if [[ ! -d "$state_run" || ! -d "$action_run" ]]; then
    echo "FAIL_ARCHIVE: native dirs absent; state=$state_run action=$action_run" >&2
    echo "Run dir probe:" >&2
    find "$RUN_DIR" -maxdepth 3 -print 2>/dev/null | sort >&2 || true
    return 1
  fi
  if ! compgen -G "$state_run/*.json" >/dev/null; then
    echo "FAIL_ARCHIVE: native state dir contains no JSON: $state_run" >&2
    find "$RUN_DIR" -maxdepth 3 -print 2>/dev/null | sort >&2 || true
    return 1
  fi
  if ! compgen -G "$action_run/*.json" >/dev/null; then
    echo "FAIL_ARCHIVE: native action dir contains no JSON: $action_run" >&2
    find "$RUN_DIR" -maxdepth 3 -print 2>/dev/null | sort >&2 || true
    return 1
  fi

  rm -rf "$state_case" "$action_case" "$ready_case"
  mkdir -p "$state_case" "$action_case" "$ready_case"
  cp -a "$state_run"/. "$state_case"/
  cp -a "$action_run"/. "$action_case"/
  find "$RUN_DIR/ready" -maxdepth 1 -type f -name 'run-*-step-*' -exec cp -a {} "$ready_case"/ \; 2>/dev/null || true

  validate_case_json "$case_name" "$expected_gens" "$expected_demes" || return $?

  rm -rf "$state_run" "$action_run"
  find "$RUN_DIR/ready" -maxdepth 1 -type f -name 'run-*-step-*' -delete 2>/dev/null || true
  echo "Archived state:  $state_case"
  echo "Archived action: $action_case"
  echo "Archived ready:  $ready_case"
}

run_state_case() {
  local case_name="$1" fn driver_rel driver rc=0 expected_gens expected_demes
  case_in_array "$case_name" "${STATE_CASES[@]}" || { echo "ERROR: unknown state case '$case_name'" >&2; return 2; }
  fn="$(state_func "$case_name")" || { echo "ERROR: unknown state case '$case_name'" >&2; return 2; }
  expected_gens="$(state_expected_gens "$case_name")"
  expected_demes="$(state_expected_demes "$case_name")"
  driver_rel="$(make_driver_name state "$case_name")"
  driver="$REPO/$driver_rel"
  cat > "$driver" <<EOF
;; AUTO-GENERATED strategy state/action driver.
!(import! &self $TEST_REL)
!(println! "================ strategy-state run: $case_name begin ================")
!(println! (strategy-state-result-size $case_name ($fn)))
!(println! "================ strategy-state run: $case_name end ==================")
EOF

  reset_native_emission
  echo "Running state strategy case: $case_name"
  echo "Using LLMOSES_RUN_ID=$RUN_ID"
  echo "Native run dir: $RUN_DIR"
  run_traced "strategy-state-${case_name}" -- "$RUN_SH" "$driver_rel" || rc=$?
  cleanup_driver "$driver"
  if [[ "$rc" -ne 0 ]]; then
    echo "FAIL_DRIVER: PeTTa exited with $rc for state case $case_name" >&2
    return "$rc"
  fi
  archive_state_case "$case_name" "$expected_gens" "$expected_demes"
}

run_metta_all() {
  local overall=0 c
  for c in "${METTA_CASES[@]}"; do
    echo
    echo "======== metta $c ========"
    run_metta_case "$c" || overall=$?
  done
  return "$overall"
}

run_state_all() {
  local overall=0 c
  for c in "${STATE_CASES[@]}"; do
    echo
    echo "======== state $c ========"
    run_state_case "$c" || overall=$?
  done
  return "$overall"
}

cmd="${1:-list}"
shift || true
case "$cmd" in
  list)
    list_cases ;;
  metta)
    [[ $# -ge 1 ]] || { echo "usage: $0 metta <case|all>" >&2; exit 2; }
    if [[ "$1" == "all" ]]; then run_metta_all; else run_metta_case "$1"; fi ;;
  state)
    [[ $# -ge 1 ]] || { echo "usage: $0 state <case|all>" >&2; exit 2; }
    if [[ "$1" == "all" ]]; then run_state_all; else run_state_case "$1"; fi ;;
  all)
    run_metta_all || exit $?
    run_state_all ;;
  *)
    echo "usage: $0 [OPTIONS] {list|metta <case|all>|state <case|all>|all}" >&2
    exit 2 ;;
esac
