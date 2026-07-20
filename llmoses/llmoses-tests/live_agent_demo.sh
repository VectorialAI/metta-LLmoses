#!/usr/bin/env bash
# Host-side live-agent demo runner. PeTTa runs in Docker; the watcher and
# Codex/live estimator run on the host.
set -u

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <demo> <outdir>" >&2
  echo "demo must be one of: bool-std, bool-cull, strategy" >&2
  exit 2
fi

DEMO="$1"
OUTDIR_IN="$2"
REPO="${REPO:-$PWD}"
cd "$REPO" || { echo "ERROR: cannot cd to repo root '$REPO'" >&2; exit 2; }
REPO="$(pwd)"
WATCHER="$REPO/llmoses/utilities/llmoses_watcher.py"
[[ -f "$WATCHER" ]] || { echo "ERROR: watcher not found at $WATCHER" >&2; exit 2; }

case "$OUTDIR_IN" in
  /*) OUTDIR="$OUTDIR_IN" ;;
  *) OUTDIR="$REPO/$OUTDIR_IN" ;;
esac
mkdir -p "$OUTDIR" || { echo "ERROR: cannot create outdir '$OUTDIR'" >&2; exit 2; }
OUTDIR="$(cd "$OUTDIR" && pwd)"
case "$OUTDIR" in
  "$REPO"|"$REPO"/*) ;;
  *) echo "ERROR: outdir must be under repo root so Docker can see it" >&2; exit 2 ;;
esac

RUNDIR="$OUTDIR/run"
CONTAINER_RUNDIR="/workspace/metta-moses${RUNDIR#$REPO}"
mkdir -p "$RUNDIR" || { echo "ERROR: cannot create rundir '$RUNDIR'" >&2; exit 2; }

DRIVER_REL="llmoses/llmoses-tests/_live_agent_demo_${DEMO}_$$.metta"
case "$DEMO" in
  bool-std)
    cat > "$REPO/$DRIVER_REL" <<'METTA'
;; AUTO-GENERATED live-agent demo driver (deleted on exit).
!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
!(println! (upt-result (booleanStateParity3Short)))
METTA
    ;;
  bool-cull)
    cat > "$REPO/$DRIVER_REL" <<'METTA'
;; AUTO-GENERATED live-agent resize-cull demo driver (deleted on exit).
!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
(= (upCullRun)
   (let* (($result (runMoses 4 (parity3TargetCscore) 6 (parity3MetaPop)
                              0 3 (parity3Context) hillClimbing
                              100 10 2 1 2 0.002 1000))
          ($size (eval (OS.length $result))))
     $size))
!(println! (upt-cull (upCullRun)))
METTA
    ;;
  strategy)
    cat > "$REPO/$DRIVER_REL" <<'METTA'
;; AUTO-GENERATED live-agent strategy demo driver (deleted on exit).
!(import! &self llmoses/llmoses-tests/strategy_test.metta)
!(println! (lad-result (strategyRunMultiGenerationMultiDemeTest)))
METTA
    ;;
  *)
    echo "ERROR: unknown demo '$DEMO' (expected bool-std, bool-cull, strategy)" >&2
    exit 2
    ;;
esac

WPID=""
cleanup() {
  if [[ -n "$WPID" ]]; then
    kill "$WPID" 2>/dev/null
    wait "$WPID" 2>/dev/null
    WPID=""
  fi
  rm -f "$REPO/$DRIVER_REL"
}
trap cleanup EXIT

echo "Starting host watcher; log: $OUTDIR/watcher.log"
LLMOSES_MOCK_UTILITY_MODE=live \
LLMOSES_LIVE_COVERAGE=full \
python3 "$WATCHER" "$RUNDIR" > "$OUTDIR/watcher.log" 2>&1 &
WPID=$!
sleep 0.5

echo "Running Docker demo '$DEMO'"
docker run --rm \
  -v "$REPO:/workspace/metta-moses" \
  -w /workspace/metta-moses \
  metta-llmoses \
  env \
    LLMOSES_RUN_DIR="$CONTAINER_RUNDIR" \
    LLMOSES_AWAIT_RESPONSE=1 \
    LLMOSES_RESPONSE_TIMEOUT_S=900 \
    LLMOSES_RESPONSE_POLL_S=0.5 \
    LLMOSES_APPLY_LEVERS=exemplar_selection,culling,comparator,complexity_ratio,atom_prior \
    LLMOSES_LEVER_WEIGHT_EXEMPLAR_SELECTION=1 \
    LLMOSES_LEVER_WEIGHT_CULLING=1 \
    LLMOSES_LEVER_WEIGHT_COMPARATOR=1 \
    LLMOSES_LEVER_WEIGHT_COMPLEXITY_RATIO=1 \
    LLMOSES_LEVER_WEIGHT_ATOM_PRIOR=1 \
    LLMOSES_RNG_SEED=101 \
    /opt/PeTTa/run.sh "$DRIVER_REL" > "$OUTDIR/driver.log" 2>&1
RC=$?

if [[ -n "$WPID" ]]; then
  sleep 0.7
  kill "$WPID" 2>/dev/null
  wait "$WPID" 2>/dev/null
  WPID=""
fi

echo "driver rc=$RC"
echo "artifacts:"
echo "  run: $RUNDIR"
echo "  watcher log: $OUTDIR/watcher.log"
echo "  driver log: $OUTDIR/driver.log"
exit "$RC"
