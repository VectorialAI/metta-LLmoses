#!/usr/bin/env bash
# ===========================================================================
# Phase II blocking-handshake functionality test.
#
# Proves the ready/response round-trip is wired correctly, end to end:
#
#   Phase 1 — responder SUPPRESSED (no watcher), short timeout:
#             every generation blocks for the response, times out, and the run
#             proceeds natively. We must EXIT ON TIMEOUT, never deadlock.
#
#   Phase 2 — responder ENABLED (the watcher writes the mock response), normal
#             timeout: every generation's ready sentinel is answered, so the run
#             COMPLETES ACROSS MULTIPLE GENERATIONS with no timeouts.
#
# This needs the PeTTa runtime (run.sh) + PYTHONPATH for llmoses/utilities, so
# run it inside the project container. From the repo root:
#
#   docker run --rm -v "$(pwd):/workspace/metta-moses" metta-llmoses \
#     bash llmoses/llmoses-tests/phase2_handshake_test.sh
#
# Exit 0 = PASS, 1 = FAIL, 2 = setup error.
# ===========================================================================
set -u

REPO="${REPO:-$PWD}"
cd "$REPO" || { echo "ERROR: cannot cd to repo root '$REPO'" >&2; exit 2; }

# Locate the PeTTa runner the same way the smoke tests do.
RUN_SH="$(command -v run.sh 2>/dev/null || true)"
[[ -z "$RUN_SH" && -x /opt/PeTTa/run.sh ]] && RUN_SH=/opt/PeTTa/run.sh
[[ -z "$RUN_SH" ]] && RUN_SH="$(find / -name run.sh -type f -path '*PeTTa*' 2>/dev/null | head -n1 || true)"
[[ -n "$RUN_SH" && -x "$RUN_SH" ]] || { echo "ERROR: could not locate PeTTa run.sh" >&2; exit 2; }

WATCHER="$REPO/llmoses/utilities/llmoses_watcher.py"
[[ -f "$WATCHER" ]] || { echo "ERROR: watcher not found at $WATCHER" >&2; exit 2; }

# A throwaway driver that runs the short 3-generation parity-3 evolution.
DRIVER_REL="llmoses/llmoses-tests/_phase2_handshake_$$.metta"
cat > "$REPO/$DRIVER_REL" <<'METTA'
;; AUTO-GENERATED Phase II handshake driver (deleted on exit).
!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
!(println! (phase2-handshake-result (booleanStateParity3Short)))
METTA

T1=""; T2=""; WPID=""
cleanup() {
  [[ -n "$WPID" ]] && kill "$WPID" 2>/dev/null
  rm -f "$REPO/$DRIVER_REL"
  rm -rf "$T1" "$T2"
}
trap cleanup EXIT

fail=0
pass() { echo "  PASS: $1"; }
bad()  { echo "  FAIL: $1"; fail=1; }

count_files() { find "$1" -type f "${@:2}" 2>/dev/null | wc -l | tr -d ' '; }
count_grep()  { local n; n="$(grep -c "$1" "$2" 2>/dev/null)"; echo "${n:-0}"; }

TIMEOUT_SHORT="${LLMOSES_TEST_TIMEOUT_SHORT:-10}"   # Phase 1 deadman timeout (s)
TIMEOUT_NORMAL="${LLMOSES_TEST_TIMEOUT_NORMAL:-30}" # Phase 2 normal timeout (s)

# ---------------------------------------------------------------------------
echo "=== Phase 1: responder SUPPRESSED, ${TIMEOUT_SHORT}s timeout -> exit on timeout ==="
T1="$(mktemp -d)"
t0=$(date +%s)
LLMOSES_RUN_DIR="$T1" LLMOSES_AWAIT_RESPONSE=1 \
  LLMOSES_RESPONSE_TIMEOUT_S="$TIMEOUT_SHORT" LLMOSES_RESPONSE_POLL_S=0.05 \
  "$RUN_SH" "$DRIVER_REL" > "$T1/run.log" 2>&1
rc=$?; wall=$(( $(date +%s) - t0 ))
echo "  run rc=$rc wall=${wall}s"

[[ $rc -eq 0 ]] && pass "run completed (no deadlock)" || bad "run rc=$rc (expected 0)"
timeouts=$(count_grep response_timeout "$T1/moses_native_log.jsonl")
[[ "$timeouts" -ge 1 ]] && pass "exited via timeout ($timeouts response_timeout row(s))" \
                        || bad "no response_timeout rows logged"
[[ "$wall" -ge "$TIMEOUT_SHORT" ]] && pass "blocked >= one full ${TIMEOUT_SHORT}s timeout (wall ${wall}s)" \
                                   || bad "wall ${wall}s < ${TIMEOUT_SHORT}s (did it actually block?)"
nresp=$(count_files "$T1/response")
[[ "$nresp" -eq 0 ]] && pass "no response sentinels (responder suppressed)" \
                     || bad "unexpected response sentinels: $nresp"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 2: responder ENABLED (watcher), ${TIMEOUT_NORMAL}s timeout -> completes multi-gen ==="
T2="$(mktemp -d)"
python3 "$WATCHER" "$T2" > "$T2/watcher.log" 2>&1 &
WPID=$!
sleep 0.5
t0=$(date +%s)
LLMOSES_RUN_DIR="$T2" LLMOSES_AWAIT_RESPONSE=1 \
  LLMOSES_RESPONSE_TIMEOUT_S="$TIMEOUT_NORMAL" LLMOSES_RESPONSE_POLL_S=0.05 \
  "$RUN_SH" "$DRIVER_REL" > "$T2/run.log" 2>&1
rc=$?; wall=$(( $(date +%s) - t0 ))
sleep 0.6; kill "$WPID" 2>/dev/null; WPID=""
echo "  run rc=$rc wall=${wall}s"

[[ $rc -eq 0 ]] && pass "run completed" || bad "run rc=$rc (expected 0)"
gens=$(count_files "$T2/state" -name 'step-*.json')
[[ "$gens" -ge 2 ]] && pass "completed across $gens generations (>= 2)" \
                    || bad "only $gens generation(s) emitted (expected >= 2)"
resp=$(count_files "$T2/response")
[[ "$resp" -ge 2 ]] && pass "$resp response sentinels written (round-trip)" \
                    || bad "only $resp response sentinels (expected >= 2)"
consumed=$(count_files "$T2/ready/.consumed" -name 'run-*')
[[ "$consumed" -ge 2 ]] && pass "$consumed ready sentinels consumed" \
                        || bad "only $consumed ready sentinels consumed (expected >= 2)"
to2=$(count_grep response_timeout "$T2/moses_native_log.jsonl")
[[ "$to2" -eq 0 ]] && pass "no timeouts (mock responder kept up)" \
                   || bad "$to2 unexpected response_timeout row(s)"

echo
if [[ $fail -eq 0 ]]; then
  echo "PHASE II HANDSHAKE TEST: PASS"
  exit 0
else
  echo "PHASE II HANDSHAKE TEST: FAIL"
  exit 1
fi
