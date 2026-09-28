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
#   ./run_strategy_smoke_test.sh state smoke
#   ./run_strategy_smoke_test.sh state merge-cull-pressure
#   ./run_strategy_smoke_test.sh state pressure
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
VERIFY_PY="$REPO/llmoses/llmoses-tests/live_agent_verify.py"
CAPTURE_SH="$REPO/llmoses/llmoses-tests/run_capture.sh"
source "$CAPTURE_SH"
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
  lineage-smoke
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
    single|multigen-multideme|empty-seed|merge-cull-smoke|lineage-smoke)
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
    lineage-smoke)        echo "strategyStateLineageSmoke" ;;
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
    lineage-smoke|deep-lineage) echo 5 ;;
    *) return 1 ;;
  esac
}

state_expected_demes() {
  case "$1" in
    single) echo 1 ;;
    multigen-multideme|empty-seed|merge-cull-smoke|lineage-smoke|merge-cull-pressure|deep-lineage) echo 2 ;;
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

# Protocol 2 refuses to start without an explicit experiment config
# (selection_temperature is required). Default to the closure config, in which
# every lever is off, so native smoke runs need no extra setup.
export LLMOSES_CONFIG="${LLMOSES_CONFIG:-$REPO/llmoses/configs/m2-closure.json}"

run_traced() {
  local stem="$1"
  shift
  [[ "${1:-}" == "--" ]] && shift
  local log="$LOGDIR/${stem}-${RUN_ID}.log"
  # Protocol-2 state and native logs belong to one case. Off runs deliberately
  # emit no agent action JSON or ready sentinels; retain artifacts in place.
  local case_run_dir="$RUN_DIR/$stem"
  mkdir "$case_run_dir" || return 2
  local progress_re="strategy-state|strategy-metta|result-size|error[: ]|Type error|assertEq|FAILED|PASS|FAIL|Generation|New best score|Merging Deme|Metapop size"
  local rc=0
  llmoses_capture_run "$log" "$REPO" "$RUN_ID" "$case_run_dir" \
    "$TRACE" "$HEAD_N" "$progress_re" -- "$@" || rc=$?
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
  echo "Protocol-2 state cases (native, no agent actions):"
  for c in "${STATE_CASES[@]}"; do
    echo "  state $c [$(strategy_state_tier "$c")]"
  done
  echo "  state smoke"
  echo "  state pressure"
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

verify_state_artifacts() {
  local case_name="$1" expected_gens="$2" expected_demes="$3"
  local case_run_dir="$RUN_DIR/strategy-state-${case_name}"
  local lineage_args=()
  [[ "$case_name" == "lineage-smoke" || "$case_name" == "deep-lineage" ]] && \
    lineage_args+=(--require-lineage)
  python3 "$VERIFY_PY" --smoke "$case_run_dir" --problem-type strategy \
    --expect-gens "$expected_gens" --expect-demes "$expected_demes" "${lineage_args[@]}"
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
;; AUTO-GENERATED strategy protocol-2 state driver.
!(import! &self $TEST_REL)
!(println! "================ strategy-state run: $case_name begin ================")
!(println! (strategy-state-result-size $case_name ($fn)))
!(println! "================ strategy-state run: $case_name end ==================")
EOF

  echo "Running state strategy case: $case_name"
  echo "Using LLMOSES_RUN_ID=$RUN_ID"
  echo "Native run dir: $RUN_DIR/strategy-state-${case_name}"
  run_traced "strategy-state-${case_name}" -- "$RUN_SH" "$driver_rel" || rc=$?
  cleanup_driver "$driver"
  if [[ "$rc" -ne 0 ]]; then
    echo "FAIL_DRIVER: PeTTa exited with $rc for state case $case_name" >&2
    return "$rc"
  fi
  verify_state_artifacts "$case_name" "$expected_gens" "$expected_demes"
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

run_state_tier() {
  local tier="$1" overall=0 c
  for c in "${STATE_CASES[@]}"; do
    [[ "$(strategy_state_tier "$c")" == "$tier" ]] || continue
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
    [[ $# -ge 1 ]] || { echo "usage: $0 state <case|smoke|pressure|all>" >&2; exit 2; }
    case "$1" in
      all) run_state_all ;;
      smoke|pressure) run_state_tier "$1" ;;
      *) run_state_case "$1" ;;
    esac ;;
  all)
    run_metta_all || exit $?
    run_state_all ;;
  *)
    echo "usage: $0 [OPTIONS] {list|metta <case|all>|state <case|smoke|pressure|all>|all}" >&2
    exit 2 ;;
esac
