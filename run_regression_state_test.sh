#!/usr/bin/env bash
# ============================================================================
# run_regression_state_test.sh — regression (contin) MOSES + LLMOSES
# state/action test harness.
#
# Directory contract intentionally matches llmoses/utilities/state_builder.py:
#   LLMOSES_RUN_ID=<timestamp>
#   -> llmoses/outputs/runs/<timestamp>/{state,action,ready}
# Logs are kept separately under:
#   llmoses/outputs/logs
#
# Usage:
#   ./run_regression_state_test.sh list
#   ./run_regression_state_test.sh metta decoder-unit
#   ./run_regression_state_test.sh metta all
#   ./run_regression_state_test.sh state exact-fit
#   ./run_regression_state_test.sh state all
#   ./run_regression_state_test.sh all
# ============================================================================
set -euo pipefail

TRACE="summary"
HEAD_N=80
KEEP_DRIVER=0
TEST_REL="llmoses/llmoses-tests/regression_test.metta"
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

# Unit tier first (regression-only arithmetic: decoder, numeric eval, bscore,
# knob build, transform dispatch), then end-to-end smoke + pressure cases.
METTA_CASES=(
  decoder-unit
  numeric-eval-unit
  bscore-unit
  knob-build-unit
  transform-dispatch-unit
  expand-single
  expand-multideme
  run-single
  exact-fit-termination
  linear-recovery
  multi-feature
  fractional-refinement
  sampling-pressure
  empty-seed
  merge-cull-pressure
  multigen-multideme
  sr-demo
  cp-demo
  ann-cp-demo
)

STATE_CASES=(
  single
  multigen-multideme
  empty-seed
  exact-fit
  merge-cull-pressure
)

metta_func() {
  case "$1" in
    decoder-unit) echo "continDecoderUnitTest" ;;
    numeric-eval-unit) echo "numericEvalUnitTest" ;;
    bscore-unit) echo "regressionBscoreUnitTest" ;;
    knob-build-unit) echo "continKnobBuildTest" ;;
    transform-dispatch-unit) echo "transformDispatchTest" ;;
    expand-single) echo "regressionExpandSingleDemeTest" ;;
    expand-multideme) echo "regressionExpandMultiDemeTest" ;;
    run-single) echo "regressionRunSingleGenerationTest" ;;
    exact-fit-termination) echo "regressionExactFitTerminationTest" ;;
    linear-recovery) echo "regressionLinearRecoveryTest" ;;
    multi-feature) echo "regressionMultiFeatureTest" ;;
    fractional-refinement) echo "regressionFractionalRefinementTest" ;;
    sampling-pressure) echo "regressionSamplingPressureTest" ;;
    empty-seed) echo "regressionEmptySeedTest" ;;
    merge-cull-pressure) echo "regressionMergeCullPressureTest" ;;
    multigen-multideme) echo "regressionMultigenMultidemeTest" ;;
    sr-demo) echo "regressionSrDemoTest" ;;
    cp-demo) echo "regressionCpDemoTest" ;;
    ann-cp-demo) echo "regressionAnnCpDemoTest" ;;
    *) return 1 ;;
  esac
}

state_func() {
  case "$1" in
    single)               echo "regressionStateSingle" ;;
    multigen-multideme)   echo "regressionStateMultigenMultideme" ;;
    empty-seed)           echo "regressionStateEmptySeed" ;;
    exact-fit)            echo "regressionStateExactFit" ;;
    merge-cull-pressure)  echo "regressionStateMergeCullPressure" ;;
    *) return 1 ;;
  esac
}

state_expected_gens() {
  case "$1" in
    single|exact-fit) echo 1 ;;
    multigen-multideme) echo 3 ;;
    empty-seed|merge-cull-pressure) echo 2 ;;
    *) return 1 ;;
  esac
}

state_expected_demes() {
  case "$1" in
    single|exact-fit) echo 1 ;;
    multigen-multideme|empty-seed|merge-cull-pressure) echo 2 ;;
    *) return 1 ;;
  esac
}

# Regression fixtures used by the state cases are all over the 1-feature
# lineTable: arity 1, (arity+1) coefficient groups of continDepth (4) trit
# knobs each -> 8 trit knobs per deme.
EXPECTED_ARITY=1
EXPECTED_COEFF_DEPTH=4

make_driver_name() {
  local kind="$1" case_name="$2"
  echo "llmoses/llmoses-tests/_regression_${kind}_${case_name}_${RUN_ID}.metta"
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
        grep -iE "(regression-state|regression-metta|result-size|error[: ]|Type error|assertEq|FAILED|PASS|FAIL|New best score|Merging Deme|Merging Regression Deme|Metapop size|RegressionHillClimbing|Terminating because)" "$tmp" || true
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
  cat <<EOF
Output root:      $OUTPUT_ROOT
Logs:             $LOGDIR
State run dir:    $RUN_DIR
Run ID:           $RUN_ID
Test file:        $TEST_REL

MeTTa unit cases:
EOF
  for c in "${METTA_CASES[@]}"; do echo "  metta $c"; done
  echo "  metta all"
  echo
  echo "State/action JSON cases:"
  for c in "${STATE_CASES[@]}"; do echo "  state $c"; done
  echo "  state all"
  echo
  echo "Combined:"
  echo "  all"
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
;; AUTO-GENERATED regression MeTTa unit driver.
!(import! &self $TEST_REL)
!(println! "================ regression-metta run: $case_name begin ================")
!(println! (regression-metta-result $case_name ($fn)))
!(println! "================ regression-metta run: $case_name end ==================")
EOF

  echo "Running MeTTa regression case: $case_name"
  run_traced "regression-metta-${case_name}" -- "$RUN_SH" "$driver_rel" || rc=$?
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
  python3 - "$RUN_DIR" "$case_name" "$expected_gens" "$expected_demes" "$EXPECTED_ARITY" "$EXPECTED_COEFF_DEPTH" <<'PY'
import json, sys
from pathlib import Path
run_dir = Path(sys.argv[1])
case = sys.argv[2]
expected_gens = int(sys.argv[3])
expected_demes = int(sys.argv[4])
expected_arity = int(sys.argv[5])
expected_coeff_depth = int(sys.argv[6])
state_dir = run_dir / "state" / case
action_dir = run_dir / "action" / case
ready_dir = run_dir / "ready" / case

def fail(msg):
    print(f"FAIL_SCHEMA: {msg}", file=sys.stderr)
    sys.exit(1)

if not state_dir.is_dir(): fail(f"missing archived state dir {state_dir}")
if not action_dir.is_dir(): fail(f"missing archived action dir {action_dir}")
if not ready_dir.is_dir(): fail(f"missing archived ready dir {ready_dir}")

expected_groups = expected_arity + 1
expected_trit_knobs = expected_groups * expected_coeff_depth

steps = []
for g in range(1, expected_gens + 1):
    sp = state_dir / f"step-{g}.json"
    ap = action_dir / f"step-{g}.json"
    if not sp.exists(): fail(f"missing {sp}")
    if not ap.exists(): fail(f"missing {ap}")
    with sp.open() as fh: s = json.load(fh)
    with ap.open() as fh: a = json.load(fh)
    steps.append(s)
    if s.get("generation") != g: fail(f"state generation mismatch in step-{g}")
    if a.get("generation") != g: fail(f"action generation mismatch in step-{g}")

    # --- problem spec ---
    ps = s.get("problem_spec", {})
    if ps.get("problem_type") != "regression": fail(f"problem_spec not regression in step-{g}")
    if not ps.get("input_labels"): fail(f"missing input_labels in step-{g}")
    if ps.get("arity") != expected_arity: fail(f"arity != {expected_arity} in step-{g}: {ps.get('arity')}")
    if ps.get("template") != "linear_combination": fail(f"template not linear_combination in step-{g}")
    if ps.get("coeff_depth") != expected_coeff_depth: fail(f"coeff_depth != {expected_coeff_depth} in step-{g}")
    if ps.get("step_size") is None: fail(f"missing step_size in problem_spec step-{g}")
    rp = s.get("run_parameters", {})
    if rp.get("problem_type") != "regression": fail(f"run_parameters.problem_type not regression in step-{g}")
    if rp.get("complexity_ratio") is None: fail(f"missing run_parameters complexity_ratio in step-{g}")

    # --- demes: contin knobs only ---
    demes = s.get("demes", [])
    if len(demes) < expected_demes: fail(f"expected at least {expected_demes} demes in step-{g}, got {len(demes)}")
    for d in demes:
        kb = d.get("knob_type_breakdown", {})
        if kb.get("logical", 0) != 0: fail(f"logical knobs present in regression deme step-{g}: {kb}")
        if kb.get("strategy", 0) != 0: fail(f"strategy knobs present in regression deme step-{g}: {kb}")
        if d.get("sampled_pair_count") is not None: fail(f"sampled_pair_count should be null for regression step-{g}")
        knobs = d.get("knobs", [])
        if len(knobs) != expected_trit_knobs:
            fail(f"expected {expected_trit_knobs} trit knobs in step-{g}, got {len(knobs)}")
        for k in knobs:
            if k.get("kind") != "contin": fail(f"non-contin knob in regression deme step-{g}: {k}")
            if k.get("multiplicity") != 3: fail(f"contin knob multiplicity not 3 in step-{g}: {k}")
            if not isinstance(k.get("contin"), dict): fail(f"contin knob missing metadata in step-{g}: {k}")
        ck = d.get("contin_knobs")
        if not isinstance(ck, list) or len(ck) != expected_groups:
            fail(f"expected {expected_groups} contin knob groups in step-{g}, got {ck if not isinstance(ck, list) else len(ck)}")
        for grp in ck:
            for key in ("group", "mean", "step_size", "expansion", "depth", "trit_knob_ids"):
                if key not in grp: fail(f"contin_knobs group missing {key} in step-{g}: {grp}")
            if len(grp["trit_knob_ids"]) != grp["depth"]:
                fail(f"trit_knob_ids length != depth in step-{g}: {grp}")

    # --- members: bscore row count and non-positive entries; cscore populated ---
    members = s.get("metapopulation", {}).get("members", [])
    if not members: fail(f"no metapopulation members in step-{g}")
    row_count = None
    for m in members:
        bs = m.get("bscore")
        if bs:
            if row_count is None:
                row_count = len(bs)
            elif len(bs) != row_count:
                fail(f"inconsistent bscore lengths in step-{g}")
            if any(isinstance(v, (int, float)) and v > 0 for v in bs):
                fail(f"positive bscore entry in regression step-{g}: {bs}")
        cs = m.get("cscore", {})
        for key in ("raw_score", "complexity", "penalized_score"):
            if cs.get(key) is None: fail(f"member cscore missing {key} in step-{g}")
    if row_count is None: fail(f"no member carried a bscore in step-{g}")

    # --- merge summary / post_selection / action doc ---
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
    if not any(c.get("neighborhood_size") is not None for c in cands):
        fail(f"no candidate neighborhood_size emitted in step-{g}")
    if a.get("problem_type") != "regression": fail(f"action problem_type not regression in step-{g}")

terminal = state_dir / "terminal.json"
if not terminal.exists(): fail(f"missing terminal {terminal}")
with terminal.open() as fh: t = json.load(fh)
if t.get("record_type") != "terminal": fail("terminal record_type mismatch")
if t.get("problem_spec", {}).get("problem_type") != "regression": fail("terminal problem_spec not regression")
if t.get("run_parameters", {}).get("problem_type") != "regression": fail("terminal run_parameters not regression")
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

  validate_case_json "$case_name" "$expected_gens" "$expected_demes"

  local require_evolution=0
  case "$case_name" in
    multigen-multideme|merge-cull-pressure) require_evolution=1 ;;
  esac
  local inv_args=()
  [[ "$require_evolution" -eq 1 ]] && inv_args+=(--require-evolution)
  python3 "$REPO/scripts/validate_llmoses_state.py" \
    --run-dir "$state_case" --action-dir "$action_case" \
    "${inv_args[@]}" || return 1

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
;; AUTO-GENERATED regression state/action driver.
!(import! &self $TEST_REL)
!(println! "================ regression-state run: $case_name begin ================")
!(println! (regression-state-result-size $case_name ($fn)))
!(println! "================ regression-state run: $case_name end ==================")
EOF

  reset_native_emission
  echo "Running state regression case: $case_name"
  echo "Using LLMOSES_RUN_ID=$RUN_ID"
  echo "Native run dir: $RUN_DIR"
  run_traced "regression-state-${case_name}" -- "$RUN_SH" "$driver_rel" || rc=$?
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
