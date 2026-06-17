#!/usr/bin/env bash
# ============================================================================
# run_boolean_smoke_test.sh — boolean LLMOSES smoke + pressure regression
#
# Targeted fixture / pressure runs — NOT classic demo problems.
# For classic demos use: ./run_moses_demo.sh demo <key>
#
# Usage:
#   ./run_boolean_smoke_test.sh list
#   ./run_boolean_smoke_test.sh metta run-single
#   ./run_boolean_smoke_test.sh metta parity3
#   ./run_boolean_smoke_test.sh metta expand-example 4
#   ./run_boolean_smoke_test.sh state single
#   ./run_boolean_smoke_test.sh all
# ============================================================================
set -euo pipefail

TRACE="summary"
HEAD_N=80
KEEP_DRIVER=0
STATE_TEST_REL="llmoses/llmoses-tests/boolean_state_test.metta"
PRESSURE_TEST_REL="llmoses/llmoses-tests/boolean_pressure_test.metta"
EXPAND_CI_REL="llmoses/llmoses-tests/expand-demes-test.metta"
SIMILARITY_REL="llmoses/llmoses-tests/similarity-scorers-test.metta"
FS_SMD_REL="llmoses/llmoses-tests/feature-selection-smoke-test.metta"
FS_PORT_REL="feature-selection/tests/smd-test.metta"
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
RUN_SH="$(command -v run.sh 2>/dev/null || true)"
[[ -z "$RUN_SH" ]] && RUN_SH="$(find / -name run.sh -type f -path '*PeTTa*' 2>/dev/null | head -n1 || true)"
[[ -n "$RUN_SH" && -f "$RUN_SH" ]] || { echo "ERROR: could not locate PeTTa run.sh" >&2; exit 2; }

STAMP="${RUN_ID_OVERRIDE:-$(date +%Y%m%d-%H%M%S)}"
RUN_ID="$STAMP"
OUTPUT_ROOT="$REPO/llmoses/outputs"
RUN_DIR="$OUTPUT_ROOT/runs/$RUN_ID"
LOGDIR="${LOGDIR_OVERRIDE:-$OUTPUT_ROOT/logs}"
DRIVER_DIR="$REPO/llmoses/llmoses-tests"
mkdir -p "$LOGDIR" "$RUN_DIR" "$DRIVER_DIR"

# metta cases: name tier import_mode
# import_mode: state | pressure | file:<rel> | expand-ci | expand-example
METTA_CASES=(
  "run-single:smoke:state"
  "run-multigen:smoke:state"
  "merge-cull-pressure:pressure:state"
  "expand-ci:smoke:expand-ci"
  "similarity-scorers:smoke:file:llmoses/llmoses-tests/similarity-scorers-test.metta"
  "fs-smd:pressure:file:llmoses/llmoses-tests/feature-selection-smoke-test.metta"
  "fs-port:pressure:file:feature-selection/tests/smd-test.metta"
  "parity3:pressure:pressure"
  "crep-smd:pressure:pressure"
)

STATE_CASES=(
  "single:smoke:state"
  "multigen-multideme:smoke:state"
  "merge-cull-smoke:smoke:state"
  "merge-cull-pressure:pressure:state"
  "parity3-short:pressure:pressure"
)

metta_tier() { IFS=: read -r _ tier _ <<< "$(case_entry "$1" metta)"; echo "$tier"; }
state_tier() { IFS=: read -r _ tier _ <<< "$(case_entry "$1" state)"; echo "$tier"; }

case_entry() {
  local name="$1" kind="$2" entry
  for entry in $( [[ "$kind" == metta ]] && printf '%s\n' "${METTA_CASES[@]}" || printf '%s\n' "${STATE_CASES[@]}" ); do
    IFS=: read -r cname _ _ <<< "$entry"
    [[ "$cname" == "$name" ]] && { echo "$entry"; return 0; }
  done
  return 1
}

metta_func() {
  case "$1" in
    run-single)           echo "booleanRunSingleGenerationTest" ;;
    run-multigen)         echo "booleanRunMultiGenerationTest" ;;
    merge-cull-pressure)  echo "booleanMergeCullPressureTest" ;;
    parity3)              echo "booleanPressureParity3" ;;
    crep-smd)             echo "booleanPressureCrepSmd" ;;
    *) return 1 ;;
  esac
}

metta_import_mode() {
  local name="$1" entry
  entry="$(case_entry "$name" metta)" || return 1
  IFS=: read -r _ _ mode rest <<< "$entry"
  if [[ "$mode" == file ]]; then echo "file:$rest"; else echo "$mode"; fi
}

state_func() {
  case "$1" in
    single)               echo "booleanStateSingle" ;;
    multigen-multideme)   echo "booleanStateMultigenMultideme" ;;
    merge-cull-smoke)     echo "booleanStateMergeCullSmoke" ;;
    merge-cull-pressure)  echo "booleanStateMergeCullPressure" ;;
    parity3-short)      echo "booleanStateParity3Short" ;;
    *) return 1 ;;
  esac
}

state_import_mode() {
  local name="$1" entry
  entry="$(case_entry "$name" state)" || return 1
  IFS=: read -r _ _ mode <<< "$entry"
  echo "$mode"
}

state_expected_gens() {
  case "$1" in
    single) echo 1 ;;
    multigen-multideme|parity3-short) echo 3 ;;
    merge-cull-smoke|merge-cull-pressure) echo 2 ;;
    *) return 1 ;;
  esac
}

state_expected_demes() {
  case "$1" in
    single) echo 1 ;;
    # These fixtures validate state/action emission, not feature-set diversity:
    # the XOR cases have one usable feature-set, and parity3-short uses
    # feature selection None, which builds one all-input representation.
    multigen-multideme|merge-cull-smoke|merge-cull-pressure|parity3-short) echo 1 ;;
    *) return 1 ;;
  esac
}

make_driver_name() {
  local kind="$1" case_name="$2"
  echo "llmoses/llmoses-tests/_boolean_${kind}_${case_name}_${RUN_ID}.metta"
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
        grep -iE "(boolean-metta|boolean-state|boolean-pressure|result-size|error[: ]|Type error|assertEq|FAILED|PASS|FAIL|Generation|SMD_REP)" "$tmp" || true
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
  echo
  echo "MeTTa cases:"
  local entry cname tier mode
  for entry in "${METTA_CASES[@]}"; do
    IFS=: read -r cname tier mode rest <<< "$entry"
    if [[ "$mode" == file ]]; then
      echo "  metta $cname [$tier]  (imports $rest)"
    elif [[ "$mode" == "expand-ci" ]]; then
      echo "  metta $cname [$tier]  (runs $EXPAND_CI_REL)"
    else
      echo "  metta $cname [$tier]"
    fi
  done
  echo "  metta expand-example <N> [pressure]  (commented runMoses from expand-demes-test)"
  echo "  metta all"
  echo
  echo "State/action JSON cases:"
  for entry in "${STATE_CASES[@]}"; do
    IFS=: read -r cname tier _ <<< "$entry"
    echo "  state $cname [$tier]"
  done
  echo "  state all"
  echo
  echo "Combined:  all"
  echo
  echo "Classic MOSES demos:  ./run_moses_demo.sh demo pa"
}

case_in_array() {
  local needle="$1" kind="$2" entry cname
  for entry in $( [[ "$kind" == metta ]] && printf '%s\n' "${METTA_CASES[@]}" || printf '%s\n' "${STATE_CASES[@]}" ); do
    IFS=: read -r cname _ _ <<< "$entry"
    [[ "$cname" == "$needle" ]] && return 0
  done
  return 1
}

read -r -d '' PYGEN <<'PYEOF' || true
import re, sys
SRC, MODE = sys.argv[1], sys.argv[2]
WHICH = int(sys.argv[3]) if len(sys.argv) > 3 else 0
lines = open(SRC).read().splitlines()
text = "\n".join(lines)

def code_only(line):
    out, instr = [], False
    for c in line:
        if c == '"': instr = not instr; out.append(c)
        elif c == ';' and not instr: break
        else: out.append(c)
    return "".join(out)

def decomment(line):
    return re.sub(r'^(\s*);{1,2} ?', r'\1', line)

def top_level_forms(text):
    buf, depth, started = [], 0, False
    for ln in text.splitlines(keepends=True):
        co = code_only(ln); st = ln.lstrip()
        if not started:
            if st == "" or st.startswith(";"): continue
            started, buf = True, [ln]; depth = co.count("(") - co.count(")")
        else:
            buf.append(ln); depth += co.count("(") - co.count(")")
        if started and depth <= 0:
            raw = "".join(buf); head = raw.lstrip()
            kind = ("import" if head.startswith("!(import!") else
                    "def" if head.startswith("(= ") else "other")
            yield kind, raw
            buf, started, depth = [], False, 0

imports = [r.rstrip("\n") for k, r in top_level_forms(text) if k == "import"]
defs = [r for k, r in top_level_forms(text) if k == "def"]

def commented_examples(lines):
    out, i, n = [], 0, len(lines)
    while i < n:
        raw = lines[i]; de = decomment(raw).lstrip()
        if raw.lstrip().startswith(";") and (de.startswith("!(runMoses") or de.startswith("!(let*")):
            block, depth, j = [], 0, i
            while j < n and lines[j].lstrip().startswith(";"):
                d = decomment(lines[j]); block.append(d)
                depth += code_only(d).count("(") - code_only(d).count(")")
                j += 1
                if depth <= 0 and len(block) > 1: break
            out.append((i+1, "\n".join(block))); i = j
        else:
            i += 1
    return out

examples = commented_examples(lines)
if MODE == "list":
    for idx, (ln, blk) in enumerate(examples, 1):
        gen = re.search(r'runMoses\s+(\d+)', blk)
        g = gen.group(1) if gen else "?"
        print(f"  expand-example {idx}: src line {ln:>3} | maxGen={g}")
    sys.exit(0)
if WHICH < 1 or WHICH > len(examples):
    sys.stderr.write(f"example index out of range (have 1..{len(examples)})\n"); sys.exit(3)
ln, blk = examples[WHICH-1]
print("; AUTO-GENERATED expand-example driver")
print("\n".join(imports)); print(); print("\n".join(defs)); print()
print('!(println! "================ expand-example: begin ================")')
print(blk)
print('!(println! "================ expand-example: end ==================")')
PYEOF

example_count() {
  python3 -c "$PYGEN" "$REPO/$EXPAND_CI_REL" list 2>/dev/null | grep -c 'expand-example' || echo 0
}

run_metta_case() {
  local case_name="$1" driver_rel driver rc=0 mode fn test_rel result_wrapper

  if [[ "$case_name" == expand-example ]]; then
    local N="${2:-}"
    [[ -n "$N" && "$N" =~ ^[1-9][0-9]*$ ]] || { echo "usage: $0 metta expand-example <N>" >&2; return 2; }
    driver_rel="llmoses/llmoses-tests/_boolean_metta_expand-example_${N}_${RUN_ID}.metta"
    driver="$REPO/$driver_rel"
    python3 -c "$PYGEN" "$REPO/$EXPAND_CI_REL" build "$N" >"$driver" || return $?
    echo "Running boolean MeTTa expand-example $N [pressure]"
    run_traced "boolean-metta-expand-example-${N}" -- "$RUN_SH" "$driver_rel" || rc=$?
    cleanup_driver "$driver"
    return "$rc"
  fi

  case_in_array "$case_name" metta || { echo "ERROR: unknown metta case '$case_name'" >&2; return 2; }
  mode="$(metta_import_mode "$case_name")"

  if [[ "$mode" == expand-ci ]]; then
    echo "Running boolean MeTTa expand-ci [smoke]"
    run_traced "boolean-metta-expand-ci" -- "$RUN_SH" "$EXPAND_CI_REL" || rc=$?
    return "$rc"
  fi

  if [[ "$mode" == file:* ]]; then
    test_rel="${mode#file:}"
    echo "Running boolean MeTTa $case_name [$(metta_tier "$case_name")] (file: $test_rel)"
    run_traced "boolean-metta-${case_name}" -- "$RUN_SH" "$test_rel" || rc=$?
    return "$rc"
  fi

  fn="$(metta_func "$case_name")" || return 2
  if [[ "$mode" == pressure ]]; then
    test_rel="$PRESSURE_TEST_REL"
    result_wrapper="boolean-pressure-result"
  else
    test_rel="$STATE_TEST_REL"
    result_wrapper="boolean-metta-result"
  fi

  driver_rel="$(make_driver_name metta "$case_name")"
  driver="$REPO/$driver_rel"
  cat > "$driver" <<EOF
;; AUTO-GENERATED boolean MeTTa driver.
!(import! &self $test_rel)
!(println! "================ boolean-metta run: $case_name begin ================")
!(println! ($result_wrapper $case_name ($fn)))
!(println! "================ boolean-metta run: $case_name end ==================")
EOF
  echo "Running boolean MeTTa $case_name [$(metta_tier "$case_name")]"
  run_traced "boolean-metta-${case_name}" -- "$RUN_SH" "$driver_rel" || rc=$?
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

run_config_path = state_dir / "run_config.json"
if not run_config_path.exists():
    fail(f"missing run_config.json in {state_dir}")
with run_config_path.open() as fh:
    rc = json.load(fh)
if rc.get("record_type") != "run_config":
    fail("run_config record_type mismatch")
ps = rc.get("problem_spec", {})
if ps.get("problem_type") != "boolean":
    fail("run_config problem_spec not boolean")
if not ps.get("input_labels"):
    fail("missing boolean input_labels in run_config")
alphabet = rc.get("atom_alphabet", {})
if alphabet.get("prefix") != "feature":
    fail("run_config atom_alphabet prefix not feature")
if not alphabet.get("atoms"):
    fail("missing atom_alphabet atoms in run_config")
rp = rc.get("run_parameters", {})
if rp.get("problem_type") != "boolean":
    fail("run_config run_parameters.problem_type not boolean")
levers = rc.get("active_levers", [])
for need in ("exemplar_selection", "culling", "atom_evidence", "complexity_ratio", "comparator_hook"):
    if need not in levers:
        fail(f"missing active_lever {need} in run_config")

for g in range(1, expected_gens + 1):
    sp = state_dir / f"step-{g}.json"
    ap = action_dir / f"step-{g}.json"
    if not sp.exists(): fail(f"missing {sp}")
    if not ap.exists(): fail(f"missing {ap}")
    with sp.open() as fh: s = json.load(fh)
    with ap.open() as fh: a = json.load(fh)
    if s.get("problem_type") != "boolean": fail(f"state problem_type not boolean in step-{g}")
    if a.get("problem_type") != "boolean": fail(f"action problem_type not boolean in step-{g}")
    for static_key in ("problem_spec", "run_parameters", "active_levers", "comparator_hook_available"):
        if static_key in s:
            fail(f"static key {static_key} must not appear in per-step state step-{g}")
    if s.get("score_vs_complexity_trend") is None:
        fail(f"missing score_vs_complexity_trend in state step-{g}")
    ae = s.get("atom_evidence")
    if not isinstance(ae, dict):
        fail(f"missing atom_evidence in state step-{g}")
    for key in ("atom_appearances", "realized_cooccurrences", "atom_cumulative", "degenerate_summary"):
        if key not in ae:
            fail(f"missing atom_evidence.{key} in state step-{g}")
    demes = s.get("demes", [])
    if len(demes) < expected_demes:
        fail(f"expected at least {expected_demes} demes in step-{g}, got {len(demes)}")
    saw_logical = False
    for d in demes:
        kb = d.get("knob_type_breakdown", {})
        if kb.get("strategy", 0) != 0:
            fail(f"strategy knobs present in boolean deme step-{g}")
        for k in d.get("knobs", []):
            if k.get("kind") == "logical":
                saw_logical = True
    if not saw_logical:
        fail(f"no logical knobs found in step-{g}")
    if not a.get("exemplar_candidates"):
        fail(f"no action exemplar_candidates in step-{g}")

terminal = state_dir / "terminal.json"
if not terminal.exists(): fail(f"missing terminal {terminal}")
ready_files = list(ready_dir.glob("run-*-step-*"))
if len(ready_files) < expected_gens:
    fail(f"expected at least {expected_gens} ready sentinels, got {len(ready_files)}")
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

  [[ -d "$state_run" && -d "$action_run" ]] || { echo "FAIL_ARCHIVE: native dirs absent" >&2; return 1; }
  rm -rf "$state_case" "$action_case" "$ready_case"
  mkdir -p "$state_case" "$action_case" "$ready_case"
  cp -a "$state_run"/. "$state_case"/
  cp -a "$action_run"/. "$action_case"/
  find "$RUN_DIR/ready" -maxdepth 1 -type f -name 'run-*-step-*' -exec cp -a {} "$ready_case"/ \; 2>/dev/null || true
  validate_case_json "$case_name" "$expected_gens" "$expected_demes" || return $?
  rm -rf "$state_run" "$action_run"
  find "$RUN_DIR/ready" -maxdepth 1 -type f -name 'run-*-step-*' -delete 2>/dev/null || true
}

run_state_case() {
  local case_name="$1" fn driver_rel driver rc=0 expected_gens expected_demes mode test_rel wrapper
  case_in_array "$case_name" state || { echo "ERROR: unknown state case '$case_name'" >&2; return 2; }
  fn="$(state_func "$case_name")" || return 2
  mode="$(state_import_mode "$case_name")"
  expected_gens="$(state_expected_gens "$case_name")"
  expected_demes="$(state_expected_demes "$case_name")"
  if [[ "$mode" == pressure ]]; then
    test_rel="$PRESSURE_TEST_REL"
    wrapper="boolean-pressure-state-size"
  else
    test_rel="$STATE_TEST_REL"
    wrapper="boolean-state-result-size"
  fi
  driver_rel="$(make_driver_name state "$case_name")"
  driver="$REPO/$driver_rel"
  cat > "$driver" <<EOF
;; AUTO-GENERATED boolean state/action driver.
!(import! &self $test_rel)
!(println! "================ boolean-state run: $case_name begin ================")
!(println! ($wrapper $case_name ($fn)))
!(println! "================ boolean-state run: $case_name end ==================")
EOF
  reset_native_emission
  echo "Running boolean state $case_name [$(state_tier "$case_name")] (LLMOSES_RUN_ID=$RUN_ID)"
  run_traced "boolean-state-${case_name}" -- "$RUN_SH" "$driver_rel" || rc=$?
  cleanup_driver "$driver"
  [[ "$rc" -eq 0 ]] || return "$rc"
  archive_state_case "$case_name" "$expected_gens" "$expected_demes"
}

run_metta_all() {
  local overall=0 entry cname
  for entry in "${METTA_CASES[@]}"; do
    IFS=: read -r cname _ _ <<< "$entry"
    echo; echo "======== metta $cname ========"
    run_metta_case "$cname" || overall=$?
  done
  return "$overall"
}

run_state_all() {
  local overall=0 entry cname
  for entry in "${STATE_CASES[@]}"; do
    IFS=: read -r cname _ _ <<< "$entry"
    echo; echo "======== state $cname ========"
    run_state_case "$cname" || overall=$?
  done
  return "$overall"
}

cmd="${1:-list}"
shift || true
case "$cmd" in
  list) list_cases ;;
  metta)
    [[ $# -ge 1 ]] || { echo "usage: $0 metta <case|expand-example N|all>" >&2; exit 2; }
    if [[ "$1" == "all" ]]; then run_metta_all
    elif [[ "$1" == "expand-example" ]]; then
      [[ $# -ge 2 ]] || { echo "usage: $0 metta expand-example <N>" >&2; exit 2; }
      run_metta_case expand-example "$2"
    else run_metta_case "$1"
    fi ;;
  state)
    [[ $# -ge 1 ]] || { echo "usage: $0 state <case|all>" >&2; exit 2; }
    if [[ "$1" == "all" ]]; then run_state_all; else run_state_case "$1"; fi ;;
  all) run_metta_all || exit $?; run_state_all ;;
  *) echo "usage: $0 [OPTIONS] {list|metta <case|expand-example N|all>|state <case|all>|all}" >&2; exit 2 ;;
esac
