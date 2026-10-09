#!/usr/bin/env bash
# Run a protocol-2 driver. No runtime or provider is started merely by installing this file.
set -euo pipefail
if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "usage: $0 CONFIG RUNDIR DRIVER [external|neutral|identity|prefer_worst|pair_policy|live]" >&2
  exit 2
fi
REPO=$(cd "$(dirname "$0")/.." && pwd)
CONFIG=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
mkdir -p "$2"
RUNDIR=$(cd "$2" && pwd)
DRIVER=$(cd "$(dirname "$3")" && pwd)/$(basename "$3")
MODE=${4:-external}
case "$MODE" in external|neutral|identity|prefer_worst|pair_policy|live) ;; *) echo "unknown responder mode" >&2; exit 2;; esac
for path in "$CONFIG" "$RUNDIR" "$DRIVER"; do
  case "$path" in "$REPO"/*) ;; *) echo "config, run directory and driver must be inside the repository" >&2; exit 2;; esac
done
CONTAINER_ROOT=/workspace/metta-moses
WPID=
CONTAINER_NAME="llmoses-m2-$(date +%s)-$$"
cleanup() {
  if [[ -n "$WPID" ]]; then
    kill "$WPID" 2>/dev/null || true
    wait "$WPID" 2>/dev/null || true
  fi
  # Stop only this runner's uniquely named container, if still alive.
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT
printf 'container=%s\n' "$CONTAINER_NAME" > "$RUNDIR/runner-resources.txt"
if [[ "$MODE" != external ]]; then
  LLMOSES_MOCK_UTILITY_MODE="$MODE" python3 "$REPO/llmoses/utilities/llmoses_watcher.py" "$RUNDIR" > "$RUNDIR/watcher.log" 2>&1 &
  WPID=$!
  printf 'watcher_pid=%s\n' "$WPID" >> "$RUNDIR/runner-resources.txt"
fi
RESUME_ARGS=()
if [[ -n ${LLMOSES_RESUME_CHECKPOINT:-} ]]; then
  case "$LLMOSES_RESUME_CHECKPOINT" in "$REPO"/*) ;; *) echo "checkpoint must be an absolute path inside repository" >&2; exit 2;; esac
  RESUME_ARGS=(-e "LLMOSES_RESUME_CHECKPOINT=$CONTAINER_ROOT${LLMOSES_RESUME_CHECKPOINT#$REPO}")
fi
docker run --rm --name "$CONTAINER_NAME" -v "$REPO:$CONTAINER_ROOT" -w "$CONTAINER_ROOT" \
  -e "LLMOSES_CONFIG=$CONTAINER_ROOT${CONFIG#$REPO}" \
  -e "LLMOSES_RUN_DIR=$CONTAINER_ROOT${RUNDIR#$REPO}" \
  -e LLMOSES_AWAIT_RESPONSE=1 \
  -e "LLMOSES_EXPECT_RESPONSE_GENS=${LLMOSES_EXPECT_RESPONSE_GENS:-all}" \
  -e "LLMOSES_RESPONSE_TIMEOUT_S=${LLMOSES_RESPONSE_TIMEOUT_S:-300}" \
  -e "LLMOSES_HEARTBEAT_STALL_S=${LLMOSES_HEARTBEAT_STALL_S:-120}" \
  -e "LLMOSES_RNG_SEED=${LLMOSES_RNG_SEED:-101}" \
  "${RESUME_ARGS[@]}" "${LLMOSES_DOCKER_IMAGE:-metta-llmoses}" \
  /opt/PeTTa/run.sh "${DRIVER#$REPO/}" > "$RUNDIR/driver.log" 2>&1
