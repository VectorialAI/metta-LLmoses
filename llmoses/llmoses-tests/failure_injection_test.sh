#!/usr/bin/env bash
# ===========================================================================
# M2 failure-injection test (PLAN-m2-hardening.md §8.C).
#
# M1 verified that success paths succeed. This suite injects each failure in
# the plan's table into a REAL PeTTa run (3-generation parity-3 driver) and
# asserts the run behaves correctly — abort with the right reason and a
# terminal.json verdict, or continue with the right quality flags:
#
#   R1  invalid credential      classified auth, no retry, 503, run aborted
#   R2  network unreachable     classified network, no retry at our layer, abort
#   R3  malformed output        one retry, both attempts logged, 500, abort
#   R4  fabricated program_id   run continues, counted, verdict degraded (W-26)
#   R5  supervisor killed       heartbeat stalls -> abort supervisor_dead,
#                               distinguishable from response_timeout (W-3)
#   R6  response never written  abort response_timeout, NOT native continuation
#   R7  deliberate 204          run continues, verdict ok, not a failure
#   R8  agent session wedged    supervisor detects, triggers abort (W-27)
#   R6b responder never declares abort anyway — expectation comes from the run
#                               config, not from CONTROL/responder (R1)
#   R9/R10 interlock windows    frontloaded / backloaded LLMOSES_EXPECT_RESPONSE_GENS
#                               run to completion; out-of-window generations are
#                               native by design and recorded (R1)
#   R4-durability               after os._exit the audit log holds the run_aborted
#                               row and the row explaining it (revision R4)
#
# Every assertion reverse-checks: on the pre-hardening tree every row fails
# (the runs complete rc=0 with no verdict; see reverse_check.sh).
#
# Needs the PeTTa runtime; run inside the project container from the repo root:
#   docker run --rm -v "$(pwd):/workspace/metta-moses" -w /workspace/metta-moses \
#     metta-llmoses bash llmoses/llmoses-tests/failure_injection_test.sh
# Exit 0 = PASS, 1 = FAIL, 2 = setup error.
# ===========================================================================
set -u

REPO="${REPO:-$PWD}"
cd "$REPO" || { echo "ERROR: cannot cd to repo root '$REPO'" >&2; exit 2; }

RUN_SH="$(command -v run.sh 2>/dev/null || true)"
[[ -z "$RUN_SH" && -x /opt/PeTTa/run.sh ]] && RUN_SH=/opt/PeTTa/run.sh
[[ -z "$RUN_SH" ]] && RUN_SH="$(find / -name run.sh -type f -path '*PeTTa*' 2>/dev/null | head -n1 || true)"
[[ -n "$RUN_SH" && -x "$RUN_SH" ]] || { echo "ERROR: could not locate PeTTa run.sh" >&2; exit 2; }

UTIL="$REPO/llmoses/utilities"
WATCHER="$UTIL/llmoses_watcher.py"
SUPERVISOR="$UTIL/supervisor.py"
[[ -f "$WATCHER" ]] || { echo "ERROR: watcher not found at $WATCHER" >&2; exit 2; }
export PYTHONPATH="$UTIL:${PYTHONPATH:-}"

DRIVER_REL="llmoses/llmoses-tests/_failure_injection_$$.metta"
cat > "$REPO/$DRIVER_REL" <<'METTA'
;; AUTO-GENERATED failure-injection driver (deleted on exit).
!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
!(println! (fi-result (booleanStateParity3Short)))
METTA

STUBS="$(mktemp -d)"
RUN_DIRS=("$STUBS")
BG_PIDS=()
cleanup() {
  local p d
  for p in "${BG_PIDS[@]}"; do kill "$p" 2>/dev/null; done
  rm -f "$REPO/$DRIVER_REL"
  for d in "${RUN_DIRS[@]}"; do rm -rf "$d"; done
}
trap cleanup EXIT

fail=0
pass() { echo "  PASS: $1"; }
bad()  { echo "  FAIL: $1"; fail=1; }

new_rundir() {
  CUR_RUNDIR="$(mktemp -d)" || { echo "ERROR: mktemp failed" >&2; exit 2; }
  RUN_DIRS+=("$CUR_RUNDIR")
}

# Provider stubs (LLMOSES_LIVE_CMD): read the prompt on stdin, fail with a
# characteristic stderr signature (probe Part E) or print garbage.
cat > "$STUBS/auth.py" <<'PY'
import sys; sys.stdin.read()
sys.stderr.write("warning: plugin cache stale\n" * 20)
sys.stderr.write("ERROR: 401 Unauthorized: {\"error\":{\"code\":\"invalid_api_key\"}}\n")
sys.exit(1)
PY
cat > "$STUBS/network.py" <<'PY'
import sys; sys.stdin.read()
sys.stderr.write("warning: plugin cache stale\n" * 20)
for i in range(1, 6):
    sys.stderr.write(f"Reconnecting... {i}/5\n")
sys.stderr.write("ERROR: stream disconnected before completion: error sending request for url (https://api/codex/responses)\n")
sys.exit(1)
PY
cat > "$STUBS/malformed.py" <<'PY'
import sys; sys.stdin.read()
print("I would rather not emit JSON today.")
PY

# Common MOSES-side environment for a live/mock run.
run_driver() {
  # run_driver <rundir> <apply-levers> [ENV=VAL ...]
  local rundir="$1" apply="$2"; shift 2
  env \
    LLMOSES_RUN_DIR="$rundir" \
    LLMOSES_AWAIT_RESPONSE=1 \
    LLMOSES_RESPONSE_TIMEOUT_S=30 \
    LLMOSES_RESPONSE_POLL_S=0.05 \
    LLMOSES_APPLY_LEVERS="$apply" \
    LLMOSES_LEVER_WEIGHT_EXEMPLAR_SELECTION=1 \
    LLMOSES_LEVER_WEIGHT_CULLING=1 \
    LLMOSES_LEVER_WEIGHT_COMPARATOR=1 \
    LLMOSES_LEVER_WEIGHT_COMPLEXITY_RATIO=1 \
    LLMOSES_LEVER_WEIGHT_ATOM_PRIOR=1 \
    "$@" \
    "$RUN_SH" "$DRIVER_REL" > "$rundir/run.log" 2>&1
}

start_watcher() {
  # start_watcher <mode> <rundir> [ENV=VAL ...]
  local mode="$1" rundir="$2"; shift 2
  env LLMOSES_MOCK_UTILITY_MODE="$mode" "$@" \
    python3 "$WATCHER" "$rundir" > "$rundir/watcher.log" 2>&1 &
  WPID=$!
  BG_PIDS+=("$WPID")
  sleep 0.6
}

stop_watcher() {
  if [[ -n "${WPID:-}" ]]; then
    sleep 0.5; kill "$WPID" 2>/dev/null; wait "$WPID" 2>/dev/null; WPID=""
  fi
}

# terminal_field <rundir> <python-expr over t (terminal.json dict)>
terminal_field() {
  RUNDIR="$1" EXPR="$2" python3 - <<'PY'
import json, os, sys
p = os.path.join(os.environ["RUNDIR"], "state", "run-1", "terminal.json")
try:
    t = json.load(open(p, encoding="utf-8"))
except Exception as e:
    print(f"<no terminal: {e}>"); sys.exit(0)
try:
    print(eval(os.environ["EXPR"]))
except Exception as e:
    print(f"<error: {e}>")
PY
}

# trace_field <rundir> <gen> <python-expr over d (trace dict)>
trace_field() {
  RUNDIR="$1" GEN="$2" EXPR="$3" python3 - <<'PY'
import json, os, sys
p = os.path.join(os.environ["RUNDIR"], "traces", "run-1", f"step-{os.environ['GEN']}.json")
try:
    d = json.load(open(p, encoding="utf-8"))
except Exception as e:
    print(f"<no trace: {e}>"); sys.exit(0)
try:
    print(eval(os.environ["EXPR"]))
except Exception as e:
    print(f"<error: {e}>")
PY
}

# util_field <rundir> <gen> <python-expr over u (utility doc)>
util_field() {
  RUNDIR="$1" GEN="$2" EXPR="$3" python3 - <<'PY'
import json, os, sys
p = os.path.join(os.environ["RUNDIR"], "utilities", "run-1", f"step-{os.environ['GEN']}.json")
try:
    u = json.load(open(p, encoding="utf-8"))
except Exception as e:
    print(f"<no utility: {e}>"); sys.exit(0)
try:
    print(eval(os.environ["EXPR"]))
except Exception as e:
    print(f"<error: {e}>")
PY
}

# abort_log_ok <rundir> <preceding-event>: after os._exit the audit log must
# hold the run_aborted row AND the row that explains it (R4 durability).
abort_log_ok() {
  RUNDIR="$1" PREV="$2" python3 - <<'PY'
import json, os
rows = []
try:
    for line in open(os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl"), encoding="utf-8"):
        if line.strip():
            rows.append(json.loads(line).get("event"))
except (FileNotFoundError, ValueError) as e:
    print(f"unreadable: {e}"); raise SystemExit(0)
prev = os.environ["PREV"]
ok = "run_aborted" in rows and prev in rows and rows.index(prev) < rows.index("run_aborted") \
     and rows[-1] == "run_aborted"
print("ok" if ok else f"rows_tail={rows[-4:]}")
PY
}

log_count() { # log_count <rundir> <event>
  RUNDIR="$1" EV="$2" python3 - <<'PY'
import json, os
n = 0
try:
    for line in open(os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl"), encoding="utf-8"):
        if line.strip() and json.loads(line).get("event") == os.environ["EV"]:
            n += 1
except FileNotFoundError:
    pass
print(n)
PY
}

declare_fake_responder() { # declare_fake_responder <rundir>
  mkdir -p "$1/CONTROL"
  cat > "$1/CONTROL/responder" <<'JSON'
{"mode": "agent:never-answers", "owner": {"kind": "agent", "pid": 424242, "host": "elsewhere"},
 "protocol_version": "llmoses-p1+injection", "context_strategy": "full_history", "released": false}
JSON
}

# --- provider-classification rows share one shape ---------------------------
provider_row() {
  # provider_row <label> <stub> <expected_class> <expected_status> <expected_attempts>
  local label="$1" stub="$2" klass="$3" status="$4" attempts="$5" rundir rc
  echo
  echo "=== $label ==="
  new_rundir; rundir="$CUR_RUNDIR"
  start_watcher live "$rundir" \
    LLMOSES_LIVE_CMD="python3 $STUBS/$stub" \
    LLMOSES_LIVE_RETRIES=1 LLMOSES_LIVE_TIMEOUT_S=5 LLMOSES_LIVE_BACKOFF_S=0
  run_driver "$rundir" "exemplar_selection,culling,comparator,complexity_ratio,atom_prior"; rc=$?
  stop_watcher
  echo "  run rc=$rc"
  [[ "$rc" -eq 3 ]] && pass "$label: run aborted (rc=3)" || bad "$label: rc=$rc (expected 3)"
  local v; v="$(terminal_field "$rundir" 't["run_verdict"]')"
  [[ "$v" == "aborted" ]] && pass "$label: terminal run_verdict aborted" || bad "$label: verdict=$v"
  v="$(terminal_field "$rundir" 't["abort"]["reason"] + "/" + str(t["abort"]["detail"].get("error_class"))')"
  [[ "$v" == "responder_failure/$klass" ]] && pass "$label: abort reason responder_failure, class $klass" \
                                           || bad "$label: abort=$v"
  v="$(util_field "$rundir" 1 'str(u.get("status")) + "/" + str((u.get("outcome") or {}).get("attempts"))')"
  [[ "$v" == "$status/$attempts" ]] && pass "$label: response status $status after $attempts attempt(s)" \
                                    || bad "$label: status/attempts=$v (expected $status/$attempts)"
  v="$(trace_field "$rundir" 1 'str(len(d.get("attempt_errors") or [])) + "/" + str(d["attempt_errors"][0].get("class"))')"
  [[ "$v" == "$attempts/$klass" ]] && pass "$label: trace logs $attempts classified attempt(s)" \
                                   || bad "$label: trace attempts=$v"
  v="$(terminal_field "$rundir" 't["capture_failures"].get("responder_'"$status"'")')"
  [[ "$v" == "1" ]] && pass "$label: capture_failures.responder_$status == 1" || bad "$label: capture_failures=$v"
  v="$(abort_log_ok "$rundir" responder_failure)"
  [[ "$v" == "ok" ]] && pass "$label: audit log durable across os._exit (responder_failure then run_aborted, last row)" || bad "$label: abort log $v"
  if [[ "$attempts" -gt 1 ]]; then
    v="$(trace_field "$rundir" 1 'len(d.get("raw_provider_outputs") or [])')"
    [[ "$v" == "$attempts" ]] && pass "$label: both raw attempts recorded" || bad "$label: raw outputs=$v"
  fi
}

provider_row "R1 invalid credential" auth.py auth 503 1
provider_row "R2 network unreachable" network.py network 503 1
provider_row "R3 malformed provider output" malformed.py malformed 500 2

# --- R4 fabricated program_id ------------------------------------------------
echo
echo "=== R4 fabricated program_id (W-26) ==="
new_rundir; R4="$CUR_RUNDIR"
start_watcher fabricate_ids "$R4"
run_driver "$R4" "exemplar_selection,culling,comparator"; rc=$?
stop_watcher
echo "  run rc=$rc"
[[ "$rc" -eq 0 ]] && pass "R4: run continues (rc=0)" || bad "R4: rc=$rc (expected 0)"
v="$(terminal_field "$R4" 't["run_verdict"]')"
[[ "$v" == "degraded" ]] && pass "R4: terminal run_verdict degraded" || bad "R4: verdict=$v"
v="$(terminal_field "$R4" 't["quality_flags"].get("unknown_program_ids", 0) >= 4')"
[[ "$v" == "True" ]] && pass "R4: unknown_program_ids quality flag counted (>= 2 per generation)" || bad "R4: flags=$(terminal_field "$R4" 't["quality_flags"]')"
v="$(terminal_field "$R4" 'sorted(t["confabulation"]["unknown_program_ids"]) == ["comparator_bias", "culling_utilities", "exemplar_utilities"] and t["confabulation"]["unknown_program_ids"]["exemplar_utilities"]["rate"] > 0 and len(t["confabulation"]["unknown_program_ids"]["exemplar_utilities"]["sample"]) >= 2')"
[[ "$v" == "True" ]] && pass "R4: confabulation stats per channel with rate + sample" || bad "R4: confabulation=$(terminal_field "$R4" 't["confabulation"]["unknown_program_ids"]')"
v="$(terminal_field "$R4" 'all(t["confabulation"]["unoffered_program_ids"][ch]["unoffered"] == 0 for ch in t["confabulation"]["unoffered_program_ids"]) and not t["quality_flags"].get("unoffered_program_ids")')"
[[ "$v" == "True" ]] && pass "R4: fabricated ids land in bucket A only (unoffered bucket B empty for offered-set mock)" || bad "R4: unoffered=$(terminal_field "$R4" 't["confabulation"]["unoffered_program_ids"]')"
n="$(log_count "$R4" bias_applied)"
[[ "$n" -ge 1 ]] && pass "R4: real ids still applied ($n bias_applied rows)" || bad "R4: no bias_applied rows"

# --- R5 supervisor killed mid-run ----------------------------------------------
echo
echo "=== R5 supervisor killed mid-run (W-3) ==="
new_rundir; R5="$CUR_RUNDIR"
start_watcher neutral "$R5" LLMOSES_HEARTBEAT_S=0.2
t0=$(date +%s)
run_driver "$R5" "" LLMOSES_RESPONSE_TIMEOUT_S=60 LLMOSES_HEARTBEAT_STALL_S=3 &
DPID=$!
BG_PIDS+=("$DPID")
# Let the responder answer generation 1, then kill it hard (no release).
for _ in $(seq 1 600); do [[ -f "$R5/response/run-1-step-1" ]] && break; sleep 0.1; done
kill -9 "$WPID" 2>/dev/null; wait "$WPID" 2>/dev/null; WPID=""
wait "$DPID"; rc=$?; wall=$(( $(date +%s) - t0 ))
echo "  run rc=$rc wall=${wall}s"
[[ "$rc" -eq 3 ]] && pass "R5: run aborted (rc=3)" || bad "R5: rc=$rc (expected 3)"
v="$(terminal_field "$R5" 't["abort"]["reason"]')"
[[ "$v" == "supervisor_dead" ]] && pass "R5: abort reason supervisor_dead" || bad "R5: abort reason=$v"
[[ "$wall" -lt 40 ]] && pass "R5: aborted well before the 60s backstop (wall ${wall}s)" || bad "R5: wall ${wall}s"
v="$(terminal_field "$R5" 'str(t["capture_failures"].get("supervisor_dead")) + "/" + str(t["capture_failures"].get("response_timeout"))')"
[[ "$v" == "1/None" ]] && pass "R5: counted as supervisor_dead, not response_timeout" || bad "R5: capture_failures=$v"

# --- R6 response never written ---------------------------------------------------
echo
echo "=== R6 response never written (declared responder, §1.3) ==="
new_rundir; R6="$CUR_RUNDIR"
declare_fake_responder "$R6"
t0=$(date +%s)
run_driver "$R6" "" LLMOSES_RESPONSE_TIMEOUT_S=3; rc=$?; wall=$(( $(date +%s) - t0 ))
echo "  run rc=$rc wall=${wall}s"
[[ "$rc" -eq 3 ]] && pass "R6: run aborted (rc=3), not silent native continuation" || bad "R6: rc=$rc (expected 3)"
v="$(terminal_field "$R6" 't["run_verdict"] + "/" + t["abort"]["reason"]')"
[[ "$v" == "aborted/response_timeout" ]] && pass "R6: verdict aborted, reason response_timeout" || bad "R6: $v"
gens=$(find "$R6/state" -name 'step-*.json' | wc -l | tr -d ' ')
[[ "$gens" -eq 1 ]] && pass "R6: stopped after the first unanswered generation" || bad "R6: $gens generations emitted"
[[ -f "$R6/CONTROL/abort" ]] && pass "R6: CONTROL/abort written for the supervisor" || bad "R6: no CONTROL/abort"
v="$(abort_log_ok "$R6" response_timeout)"
[[ "$v" == "ok" ]] && pass "R6: audit log durable across os._exit (response_timeout then run_aborted, last row)" || bad "R6: abort log $v"

# --- R6b responder never declares itself (R1) ---------------------------------------
echo
echo "=== R6b responder never declares (no CONTROL/responder), estimate expected -> abort ==="
new_rundir; R6B="$CUR_RUNDIR"
run_driver "$R6B" "" LLMOSES_RESPONSE_TIMEOUT_S=3; rc=$?
echo "  run rc=$rc"
[[ "$rc" -eq 3 ]] && pass "R6b: run aborted (rc=3) although no responder ever declared" || bad "R6b: rc=$rc (expected 3)"
v="$(terminal_field "$R6B" 't["run_verdict"] + "/" + t["abort"]["reason"] + "/" + str(t["abort"]["detail"].get("responder_declared"))')"
[[ "$v" == "aborted/response_timeout/False" ]] && pass "R6b: verdict aborted, reason response_timeout, responder_declared false" || bad "R6b: $v"
[[ ! -f "$R6B/CONTROL/responder" ]] && pass "R6b: expectation came from run config, not from CONTROL/responder" || bad "R6b: unexpected responder file"

# --- R9/R10 interlock windows (R1) ----------------------------------------------------
echo
echo "=== R9 frontloaded window 1-2 (watcher present) -> gen 3 native by design, verdict ok ==="
new_rundir; R9="$CUR_RUNDIR"
start_watcher neutral "$R9"
run_driver "$R9" "" LLMOSES_EXPECT_RESPONSE_GENS=1-2; rc=$?
stop_watcher
echo "  run rc=$rc"
[[ "$rc" -eq 0 ]] && pass "R9: run completes (rc=0)" || bad "R9: rc=$rc"
v="$(terminal_field "$R9" 't["run_verdict"] + "/" + t["response_window"]["spec"] + "/" + str(t["response_window"]["native_generations"]) + "/" + str(len([r for r in [1] if True]))')"
[[ "$v" == "ok/1-2/[3]/1" ]] && pass "R9: verdict ok, window 1-2 recorded, generation 3 native by design" || bad "R9: $v"
n="$(log_count "$R9" await_skipped)"; m="$(log_count "$R9" utility_ingest)"
[[ "$n" -eq 1 && "$m" -eq 2 ]] && pass "R9: 2 ingests inside the window, 1 skip outside" || bad "R9: ingests=$m skips=$n"

echo
echo "=== R10 backloaded window 3- (no watcher until gen 3 would block) -> gens 1-2 native by design ==="
new_rundir; R10="$CUR_RUNDIR"
start_watcher neutral "$R10"
run_driver "$R10" "" LLMOSES_EXPECT_RESPONSE_GENS=3-; rc=$?
stop_watcher
echo "  run rc=$rc"
[[ "$rc" -eq 0 ]] && pass "R10: run completes (rc=0)" || bad "R10: rc=$rc"
v="$(terminal_field "$R10" 't["run_verdict"] + "/" + str(t["response_window"]["native_generations"]) + "/" + str(t["quality_flags"])')"
[[ "$v" == "ok/[1, 2]/{}" ]] && pass "R10: verdict ok, gens 1-2 native by design, no quality flags" || bad "R10: $v"

# --- R7 deliberate 204 abstention -------------------------------------------------
echo
echo "=== R7 deliberate 204 abstention ==="
new_rundir; R7="$CUR_RUNDIR"
start_watcher neutral "$R7"
run_driver "$R7" "exemplar_selection,culling,comparator,complexity_ratio,atom_prior"; rc=$?
stop_watcher
echo "  run rc=$rc"
[[ "$rc" -eq 0 ]] && pass "R7: run completes (rc=0)" || bad "R7: rc=$rc"
v="$(terminal_field "$R7" 't["run_verdict"] + "/" + str(t["quality_flags"]) + "/" + str(t["capture_failures"])')"
[[ "$v" == "ok/{}/{}" ]] && pass "R7: verdict ok, no quality flags, no capture failures" || bad "R7: $v"
v="$(util_field "$R7" 1 'u.get("status")')"
[[ "$v" == "204" ]] && pass "R7: responses carry status 204" || bad "R7: status=$v"
v="$(terminal_field "$R7" 't["confabulation"]["declines"] >= 2 and t["confabulation"]["responses"] == t["confabulation"]["declines"]')"
[[ "$v" == "True" ]] && pass "R7: abstentions counted as declines, not failures" || bad "R7: confabulation=$(terminal_field "$R7" 't["confabulation"]')"
v="$(terminal_field "$R7" 'str(t.get("protocol_version"))[:10] + "/" + str(t.get("context_strategy"))')"
[[ "$v" == "llmoses-p1/per_generation" ]] && pass "R7: terminal surfaces protocol_version + context_strategy (W-28/W-22)" || bad "R7: $v"

# --- R8 agent session wedged ------------------------------------------------------
echo
echo "=== R8 agent session wedged (W-27 supervisor) ==="
if [[ -f "$SUPERVISOR" ]]; then
  new_rundir; R8="$CUR_RUNDIR"
  # A "wedged" agent: claims the run and keeps heart-beating, never answers.
  python3 - "$R8" <<'PY' > "$R8/agent.log" 2>&1 &
import sys, time
import responder_control as rc
rundir = sys.argv[1]
rc.claim(rundir, mode="agent:wedged", kind="agent", protocol_version="llmoses-p1+wedged",
         context_strategy="full_history")
rc.Heartbeat(rundir, "agent", interval_s=0.2).start()
time.sleep(600)
PY
  APID=$!; BG_PIDS+=("$APID")
  sleep 0.6
  python3 "$SUPERVISOR" --session "wedged=$R8" --stall-s 3 --poll-s 0.5 --max-wall-s 60 \
    > "$R8/supervisor.log" 2>&1 &
  SPID=$!; BG_PIDS+=("$SPID")
  t0=$(date +%s)
  run_driver "$R8" "" LLMOSES_RESPONSE_TIMEOUT_S=60 LLMOSES_HEARTBEAT_STALL_S=60; rc=$?
  wall=$(( $(date +%s) - t0 ))
  wait "$SPID"; src=$?
  kill "$APID" 2>/dev/null; wait "$APID" 2>/dev/null
  echo "  run rc=$rc wall=${wall}s supervisor rc=$src"
  [[ "$rc" -eq 3 ]] && pass "R8: run aborted (rc=3)" || bad "R8: rc=$rc (expected 3)"
  [[ "$wall" -lt 40 ]] && pass "R8: aborted long before the 60s backstop (wall ${wall}s)" || bad "R8: wall ${wall}s"
  v="$(terminal_field "$R8" 't["abort"]["reason"] + "/" + str(t["abort"]["detail"].get("requested_reason")) + "/" + str(t["abort"]["source"])')"
  [[ "$v" == "abort_requested/agent_wedged/supervisor" ]] && pass "R8: abort requested by the supervisor for a wedged agent" || bad "R8: abort=$v"
  [[ "$src" -eq 1 ]] && pass "R8: supervisor exits 1 (a session aborted)" || bad "R8: supervisor rc=$src"
  grep -q '"agent_wedged"' "$R8/CONTROL/abort" && pass "R8: CONTROL/abort carries reason agent_wedged" || bad "R8: CONTROL/abort=$(cat "$R8/CONTROL/abort" 2>/dev/null)"
  [[ -f "$R8/CONTROL/supervisor.json" ]] && pass "R8: supervisor is observable (CONTROL/supervisor.json)" || bad "R8: no supervisor status file"
else
  bad "R8: supervisor.py missing"
fi

echo
if [[ $fail -eq 0 ]]; then
  echo "FAILURE INJECTION TEST: PASS"
  exit 0
else
  echo "FAILURE INJECTION TEST: FAIL"
  exit 1
fi
