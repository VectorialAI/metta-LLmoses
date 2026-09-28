#!/usr/bin/env bash
# Shared, bounded capture for the Boolean and strategy smoke-test runners.
# The complete child trace is written directly to its final log.  Only periodic
# progress and a bounded post-run summary are sent to the caller's terminal.

llmoses_capture_file_size() {
  local path="$1" size
  if size="$(stat -c %s "$path" 2>/dev/null)"; then
    printf '%s' "$size"
  elif size="$(stat -f %z "$path" 2>/dev/null)"; then
    printf '%s' "$size"
  else
    printf 'unknown'
  fi
}

llmoses_capture_emit_progress() {
  local log="$1" started_at="$2" progress_re="$3" window="$4"
  local now elapsed bytes marker
  now="$(date +%s)"
  elapsed=$((now - started_at))
  bytes="$(llmoses_capture_file_size "$log")"
  marker="$(tail -n "$window" "$log" 2>/dev/null | grep -iE "$progress_re" | tail -n 1 || true)"
  if [[ -n "$marker" ]]; then
    printf '[PeTTa progress] elapsed=%ss log_bytes=%s latest=%s\n' \
      "$elapsed" "$bytes" "${marker:0:500}"
  else
    printf '[PeTTa progress] elapsed=%ss log_bytes=%s latest=(no marker yet)\n' \
      "$elapsed" "$bytes"
  fi
}

llmoses_capture_emit_summary() {
  local log="$1" trace="$2" line_limit="$3" progress_re="$4"
  local total bytes match_limit
  total="$(wc -l < "$log")"
  bytes="$(llmoses_capture_file_size "$log")"
  match_limit="${LLMOSES_SUMMARY_MATCHES:-$line_limit}"
  [[ "$match_limit" =~ ^[1-9][0-9]*$ ]] || {
    echo "ERROR: LLMOSES_SUMMARY_MATCHES must be a positive integer" >&2
    return 2
  }

  case "$trace" in
    partial)
      echo "--- first $line_limit lines ---"
      head -n "$line_limit" "$log" || true
      if (( total > line_limit )); then
        echo "... $((total - line_limit)) more lines (${total} total)"
      fi
      ;;
    summary)
      echo "--- last $match_limit status lines ---"
      grep -iE "$progress_re" "$log" | tail -n "$match_limit" || true
      echo "--- last $line_limit lines ---"
      tail -n "$line_limit" "$log" || true
      ;;
    full)
      # "full" retains the complete trace in the log, but terminal output is
      # intentionally bounded to prevent Docker/terminal pipe backpressure.
      echo "--- first $line_limit lines (full trace retained in log) ---"
      head -n "$line_limit" "$log" || true
      if (( total > line_limit * 2 )); then
        echo "... $((total - line_limit * 2)) middle lines omitted from terminal ..."
      fi
      echo "--- last $line_limit lines ---"
      tail -n "$line_limit" "$log" || true
      ;;
    *)
      echo "ERROR: unknown trace mode '$trace'" >&2
      return 2
      ;;
  esac
  echo "--- end (${total} lines, ${bytes} bytes) ---"
}

_llmoses_capture_exec() (
  local log="$1" repo="$2" run_id="$3" run_dir="$4" progress_re="$5"
  shift 5
  [[ "${1:-}" == "--" ]] && shift

  local heartbeat="${LLMOSES_HEARTBEAT_S:-30}"
  local window="${LLMOSES_PROGRESS_WINDOW:-400}"
  [[ "$heartbeat" =~ ^[1-9][0-9]*$ ]] || {
    echo "ERROR: LLMOSES_HEARTBEAT_S must be a positive integer" >&2
    exit 2
  }
  [[ "$window" =~ ^[1-9][0-9]*$ ]] || {
    echo "ERROR: LLMOSES_PROGRESS_WINDOW must be a positive integer" >&2
    exit 2
  }

  : > "$log" || exit 2
  local child_pid monitor_pid grouped=0 rc=0 started_at
  started_at="$(date +%s)"

  if command -v setsid >/dev/null 2>&1; then
    (cd "$repo" && exec setsid env \
      LLMOSES_RUN_ID="$run_id" LLMOSES_RUN_DIR="$run_dir" "$@") \
      >> "$log" 2>&1 &
    child_pid=$!
    grouped=1
  else
    (cd "$repo" && exec env \
      LLMOSES_RUN_ID="$run_id" LLMOSES_RUN_DIR="$run_dir" "$@") \
      >> "$log" 2>&1 &
    child_pid=$!
  fi

  terminate_child() {
    local signal="$1"
    if (( grouped )); then
      kill -"$signal" -- "-$child_pid" 2>/dev/null || true
    else
      kill -"$signal" "$child_pid" 2>/dev/null || true
    fi
  }
  cleanup_live_child() {
    if kill -0 "$child_pid" 2>/dev/null; then
      terminate_child TERM
    fi
    if [[ -n "${monitor_pid:-}" ]]; then
      kill "$monitor_pid" 2>/dev/null || true
    fi
  }
  trap 'cleanup_live_child; exit 130' INT
  trap 'cleanup_live_child; exit 143' TERM
  trap 'cleanup_live_child; exit 129' HUP
  trap 'cleanup_live_child' EXIT

  (
    local slept
    while kill -0 "$child_pid" 2>/dev/null; do
      slept=0
      while (( slept < heartbeat )); do
        sleep 1
        kill -0 "$child_pid" 2>/dev/null || exit 0
        slept=$((slept + 1))
      done
      llmoses_capture_emit_progress "$log" "$started_at" "$progress_re" "$window"
    done
  ) &
  monitor_pid=$!

  if wait "$child_pid"; then
    rc=0
  else
    rc=$?
  fi
  kill "$monitor_pid" 2>/dev/null || true
  wait "$monitor_pid" 2>/dev/null || true
  monitor_pid=""

  trap - INT TERM HUP EXIT
  exit "$rc"
)

llmoses_capture_run() {
  local log="$1" repo="$2" run_id="$3" run_dir="$4"
  local trace="$5" line_limit="$6" progress_re="$7"
  shift 7
  [[ "${1:-}" == "--" ]] && shift

  local rc=0
  _llmoses_capture_exec "$log" "$repo" "$run_id" "$run_dir" \
    "$progress_re" -- "$@" || rc=$?
  llmoses_capture_emit_summary "$log" "$trace" "$line_limit" "$progress_re" || {
    local summary_rc=$?
    (( rc == 0 )) && rc=$summary_rc
  }
  return "$rc"
}
