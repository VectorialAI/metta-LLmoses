#!/usr/bin/env bash
# ============================================================================
# run_moses_demo.sh — classic MOSES demo problems (watch + state emission)
#
# Boolean demos via runClassicDemo / runDemoProblem; tic-tac-toe strategy via
# runClassicStrategyDemo (examples/tic-tac-toe/).
# LLMOSES state/action JSON is emitted under:
#   llmoses/outputs/runs/<LLMOSES_RUN_ID>/{state,action,ready}
#
# For boolean/strategy smoke + pressure regression, use:
#   ./run_boolean_smoke_test.sh
#   ./run_strategy_smoke_test.sh
#
# Usage:
#   ./run_moses_demo.sh [OPTIONS] list
#   ./run_moses_demo.sh [OPTIONS] demo pa
#   ./run_moses_demo.sh [OPTIONS] demo dj|maj|mux|cp|ann-cp|ttt|sr|all
#
# Options:
#   --trace full|partial|summary   (default: full)
#   --head N                       (default: 50)
#   --no-log
#   --log-dir DIR
# ============================================================================
set -euo pipefail

TRACE="full"
HEAD_N=50
DO_LOG=1
LOGDIR_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --trace)
            TRACE="${2:-}"
            [[ "$TRACE" == full || "$TRACE" == partial || "$TRACE" == summary ]] || { echo "ERROR: --trace full|partial|summary" >&2; exit 2; }
            shift 2 ;;
        --head)
            HEAD_N="${2:-}"
            [[ "$HEAD_N" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: --head must be positive integer" >&2; exit 2; }
            shift 2 ;;
        --no-log) DO_LOG=0; shift ;;
        --log-dir) LOGDIR_OVERRIDE="${2:-}"; shift 2 ;;
        --) shift; break ;;
        -*) echo "ERROR: unknown option '$1'" >&2; exit 2 ;;
        *) break ;;
    esac
done

REPO="${REPO:-$PWD}"
DEMOS_REL="llmoses/llmoses-tests/demos_test.metta"
DEMOS="$REPO/$DEMOS_REL"
STRATEGY_DEMOS_REL="llmoses/llmoses-tests/strategy_demos_test.metta"
STRATEGY_DEMOS="$REPO/$STRATEGY_DEMOS_REL"
REGRESSION_TEST_REL="llmoses/llmoses-tests/regression_test.metta"
REGRESSION_TEST="$REPO/$REGRESSION_TEST_REL"

[[ -f "$DEMOS" ]] || { echo "ERROR: missing $DEMOS_REL under REPO=$REPO" >&2; exit 2; }

RUN_SH="$(command -v run.sh 2>/dev/null || true)"
[[ -z "$RUN_SH" ]] && RUN_SH="$(find / -name run.sh -type f -path '*PeTTa*' 2>/dev/null | head -n1 || true)"
[[ -n "$RUN_SH" && -f "$RUN_SH" ]] || { echo "ERROR: could not locate PeTTa run.sh" >&2; exit 2; }

LOGDIR="${LOGDIR_OVERRIDE:-$REPO/llmoses/outputs/logs}"
mkdir -p "$LOGDIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
run_traced() {
    local stem="$1"; shift
    [[ "${1:-}" == "--" ]] && shift
    local log=""
    [[ $DO_LOG -eq 1 && -n "$stem" ]] && log="$LOGDIR/${stem}.log"
    local rid="${LLMOSES_RUN_ID:-$STAMP}"
    if [[ "$TRACE" == "full" ]]; then
        local rc=0
        if [[ -n "$log" ]]; then
            (cd "$REPO" && LLMOSES_RUN_ID="$rid" "$@") 2>&1 | tee "$log" || rc=${PIPESTATUS[0]}
        else
            (cd "$REPO" && LLMOSES_RUN_ID="$rid" "$@") 2>&1 || rc=$?
        fi
        [[ -n "$log" ]] && echo "Saved: $log"
        return "$rc"
    fi
    local tmp rc=0
    tmp="$(mktemp)"
    (cd "$REPO" && LLMOSES_RUN_ID="$rid" "$@") >"$tmp" 2>&1 || rc=$?
    local total
    total="$(wc -l < "$tmp")"
    case "$TRACE" in
        partial)
            head -n "$HEAD_N" "$tmp" || true
            (( total > HEAD_N )) && echo "... $((total - HEAD_N)) more lines (${total} total)"
            ;;
        summary)
            grep -iE "(MOSES demo:|StrategyDemo|BestPossibleScore|FinalResult|FinalStrategyResult|error[: ]|Type error|Generation)" "$tmp" || true
            echo "--- last $HEAD_N lines ---"
            tail -n "$HEAD_N" "$tmp" || true
            echo "--- end ($total lines total) ---"
            ;;
    esac
    [[ -n "$log" ]] && cp "$tmp" "$log" && echo "Saved: $log"
    rm -f "$tmp"
    return "$rc"
}

DEMO_KEYS=(pa dj maj mux cp ann-cp ttt ttt-mm)

is_strategy_demo() {
    case "$1" in ttt|tictactoe|ttt-mm) return 0 ;; *) return 1 ;; esac
}

demo_key_to_metta() {
    case "$1" in
        pa) echo pa ;; dj) echo dj ;; maj) echo maj ;; mux) echo mux ;;
        cp) echo cp ;; ann-cp) echo annCp ;;
        ttt|tictactoe) echo ttt ;;
        ttt-mm) echo ttt-mm ;;
        *) return 1 ;;
    esac
}

list_demos() {
    cat <<EOF
Classic MOSES demo keys (via $DEMOS_REL):
  pa       3-bit parity
  dj       3-input disjunction
  maj      3-bit majority
  mux      3-bit mux
  cp       combo-program recovery (parity4 stand-in)
  ann-cp   ANN combo (parity4 stand-in until ANN scorer ported)
  ttt      tic-tac-toe strategy vs random-player (examples/tic-tac-toe/)
  ttt-mm   tic-tac-toe strategy vs minimax-player
  sr       simple regression (regression_test.metta)
  all      every key above

Run:
  $0 demo pa
  $0 demo all

State output:
  $REPO/llmoses/outputs/runs/<run-id>/{state,action,ready}

Other harnesses:
  ./run_boolean_smoke_test.sh list
  ./run_strategy_smoke_test.sh list
EOF
}

run_demo() {
    local KEY="$1" METTA_KEY driver_rel driver rc=0 rid="${LLMOSES_RUN_ID:-$STAMP}"

    if [[ "$KEY" == "tictactoe" ]]; then KEY="ttt"; fi

    if [[ "$KEY" == "sr" ]]; then
        [[ -f "$REGRESSION_TEST" ]] || { echo "ERROR: missing $REGRESSION_TEST_REL" >&2; return 2; }
        driver_rel="llmoses/llmoses-tests/_moses_demo_sr_${STAMP}.metta"
        driver="$REPO/$driver_rel"
        cat > "$driver" <<EOF
!(import! &self $REGRESSION_TEST_REL)
!(println! "================ MOSES demo: sr begin ================")
!(println! (regression-metta-result sr-demo (regressionSrDemoTest)))
!(println! "================ MOSES demo: sr end ==================")
EOF
        echo "Running classic demo: sr"
        echo "LLMOSES state: $REPO/llmoses/outputs/runs/$rid/{state,action,ready}"
        run_traced "demo-sr-${STAMP}" -- "$RUN_SH" "$driver_rel" || rc=$?
        rm -f "$driver"
        return "$rc"
    fi

    if is_strategy_demo "$KEY"; then
        [[ -f "$STRATEGY_DEMOS" ]] || { echo "ERROR: missing $STRATEGY_DEMOS_REL" >&2; return 2; }
        METTA_KEY="$(demo_key_to_metta "$KEY")" || { echo "ERROR: unknown demo key '$KEY'" >&2; return 2; }
        driver_rel="llmoses/llmoses-tests/_moses_demo_${KEY}_${STAMP}.metta"
        driver="$REPO/$driver_rel"
        cat > "$driver" <<EOF
!(import! &self $STRATEGY_DEMOS_REL)
!(println! "================ MOSES demo: $KEY begin ================")
!(println! (runClassicStrategyDemo $METTA_KEY))
!(println! "================ MOSES demo: $KEY end ==================")
EOF
        echo "Running strategy demo: $KEY (tic-tac-toe)"
        echo "LLMOSES state: $REPO/llmoses/outputs/runs/$rid/{state,action,ready}"
        run_traced "demo-${KEY}-${STAMP}" -- "$RUN_SH" "$driver_rel" || rc=$?
        rm -f "$driver"
        return "$rc"
    fi

    METTA_KEY="$(demo_key_to_metta "$KEY")" || { echo "ERROR: unknown demo key '$KEY'" >&2; return 2; }
    driver_rel="llmoses/llmoses-tests/_moses_demo_${KEY}_${STAMP}.metta"
    driver="$REPO/$driver_rel"
    cat > "$driver" <<EOF
!(import! &self $DEMOS_REL)
!(println! "================ MOSES demo: $KEY begin ================")
!(println! (runClassicDemo $METTA_KEY))
!(println! "================ MOSES demo: $KEY end ==================")
EOF
    echo "Running classic demo: $KEY"
    echo "LLMOSES state: $REPO/llmoses/outputs/runs/$rid/{state,action,ready}"
    run_traced "demo-${KEY}-${STAMP}" -- "$RUN_SH" "$driver_rel" || rc=$?
    rm -f "$driver"
    return "$rc"
}

run_demo_all() {
    local overall=0 k
    for k in "${DEMO_KEYS[@]}"; do
        echo; echo "======== demo $k ========"
        run_demo "$k" || overall=$?
    done
    echo; echo "======== demo sr ========"
    run_demo sr || overall=$?
    return "$overall"
}

cmd="${1:-list}"
shift || true
case "$cmd" in
    list) list_demos ;;
    demo)
        [[ $# -ge 1 ]] || { echo "usage: $0 demo <pa|dj|maj|mux|cp|ann-cp|ttt|ttt-mm|sr|all>" >&2; exit 2; }
        if [[ "$1" == "all" ]]; then run_demo_all
        else
            overall=0
            for KEY in "$@"; do run_demo "$KEY" || overall=$?; done
            (( overall == 0 )) || exit "$overall"
        fi ;;
    *)
        echo "usage: $0 [OPTIONS] {list|demo <key|all>}" >&2
        exit 2 ;;
esac
