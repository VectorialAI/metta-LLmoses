#!/usr/bin/env bash
# ============================================================================
# run_moses_demo.sh — watch a REAL end-to-end MOSES run, not just unit asserts.
#
# The CI suite only checks `assertEqual` invariants (e.g. "returned >= 1
# candidate"). This script instead executes a full evolutionary cycle —
# deme construction -> knob building -> instance scoring -> hill-climbing ->
# merge -> next generation -> top candidates — and prints what comes out, so
# you can see the behavior your LLMOSES action-vector layer will be biasing.
#
# It does NOT hand-author any MeTTa. Every form it runs is copied verbatim from
# deme/tests/expand-demes-test.metta:
#   * MODE `live`      : runs that test file as-is but non-silent, surfacing the
#                        optimizeDemes/runMoses output the file already prints.
#   * MODE `example N` : rebuilds a driver = (all imports + all fixture defs from
#                        the test file) + the maintainers' Nth commented-out
#                        `runMoses` example, de-commented. Loads identically to
#                        the test (same imports/defs the green suite uses) plus
#                        one extra evolutionary run.
#
# Usage:
#   ./run_moses_demo.sh [OPTIONS] list
#   ./run_moses_demo.sh [OPTIONS] live
#   ./run_moses_demo.sh [OPTIONS] example 4           # single example
#   ./run_moses_demo.sh [OPTIONS] example 4 5 6       # several examples
#   ./run_moses_demo.sh [OPTIONS] example all         # every example
#
# Options:
#   --trace full|partial|summary
#     full     (default) stream all output; save full log
#     partial  show first --head N lines, then "… M more lines"; save full log
#     summary  show run markers + any error/assertion lines + tail --head lines;
#              save full log. Good for quick sanity checks on slow runs.
#   --head N   lines to show in partial (first N) and summary (tail N)
#              default: 50
#   --no-log   do not write a log file
#   --log-dir DIR
#              override log directory (default: <REPO>/moses_demo_logs)
#
# Environment:
#   REPO=<path>  metta-moses repo root (default: $PWD)
# ============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
TRACE="full"
HEAD_N=50
DO_LOG=1
LOGDIR_OVERRIDE=""

# ---------------------------------------------------------------------------
# Flag parsing  (flags must precede the subcommand)
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --trace)
            TRACE="${2:-}"
            if [[ "$TRACE" != full && "$TRACE" != partial && "$TRACE" != summary ]]; then
                echo "ERROR: --trace must be full, partial, or summary" >&2; exit 2
            fi
            shift 2 ;;
        --head)
            HEAD_N="${2:-}"
            if ! [[ "$HEAD_N" =~ ^[1-9][0-9]*$ ]]; then
                echo "ERROR: --head must be a positive integer" >&2; exit 2
            fi
            shift 2 ;;
        --no-log)   DO_LOG=0; shift ;;
        --log-dir)  LOGDIR_OVERRIDE="${2:-}"; shift 2 ;;
        --)         shift; break ;;
        -*)         echo "ERROR: unknown option '$1'" >&2; exit 2 ;;
        *)          break ;;
    esac
done

# ---------------------------------------------------------------------------
# Repo / entry-point validation
# ---------------------------------------------------------------------------
REPO="${REPO:-$PWD}"
ENTRY_REL="deme/tests/expand-demes-test.metta"
ENTRY="$REPO/$ENTRY_REL"

if [[ ! -f "$ENTRY" ]]; then
    echo "ERROR: can't find $ENTRY_REL under REPO=$REPO" >&2
    echo "Run from the metta-moses repo root, or set REPO=/path/to/metta-moses." >&2
    exit 2
fi

# Locate PeTTa's run.sh (on PATH in the container image; otherwise search).
RUN_SH="$(command -v run.sh 2>/dev/null || true)"
if [[ -z "$RUN_SH" ]]; then
    RUN_SH="$(find / -name run.sh -type f -path '*PeTTa*' 2>/dev/null | head -n1 || true)"
fi
if [[ -z "$RUN_SH" ]] || [[ ! -f "$RUN_SH" ]]; then
    echo "ERROR: could not find PeTTa's run.sh on PATH or under a *PeTTa* dir." >&2
    exit 2
fi

LOGDIR="${LOGDIR_OVERRIDE:-$REPO/moses_demo_logs}"
mkdir -p "$LOGDIR"
STAMP="$(date +%Y%m%d-%H%M%S)"

# ---------------------------------------------------------------------------
# run_traced <log-stem> -- <cmd> [args...]
#
# Runs <cmd> from $REPO, applies --trace filtering, optionally saves full log.
# Returns the command's exit code.
# ---------------------------------------------------------------------------
run_traced() {
    local stem="$1"; shift
    [[ "${1:-}" == "--" ]] && shift

    local log=""
    if [[ $DO_LOG -eq 1 && -n "$stem" ]]; then
        log="$LOGDIR/${stem}.log"
    fi

    if [[ "$TRACE" == "full" ]]; then
        # Stream directly — no buffering delay for long runs.
        local exit_code=0
        if [[ -n "$log" ]]; then
            (cd "$REPO" && "$@") 2>&1 | tee "$log" || exit_code=${PIPESTATUS[0]}
        else
            (cd "$REPO" && "$@") 2>&1 || exit_code=$?
        fi
        [[ -n "$log" ]] && echo "Saved: $log"
        return "$exit_code"
    fi

    # partial / summary: buffer first, then display filtered output.
    local tmp exit_code=0
    tmp="$(mktemp)"
    (cd "$REPO" && "$@") > "$tmp" 2>&1 || exit_code=$?
    local total
    total="$(wc -l < "$tmp")"

    case "$TRACE" in
        partial)
            head -n "$HEAD_N" "$tmp" || true
            if (( total > HEAD_N )); then
                echo "... $((total - HEAD_N)) more lines (${total} total)"
            fi
            ;;
        summary)
            # Run markers, Prolog/MeTTa errors, assertion lines, candidate output.
            grep -iE "(MOSES run:|error[: ]|Type error|assertEq|Candidate|PASSED|FAILED)" "$tmp" || true
            printf -- "--- last %d lines ---\n" "$HEAD_N"
            tail -n "$HEAD_N" "$tmp" || true
            printf -- "--- end (%d lines total) ---\n" "$total"
            ;;
    esac

    if [[ -n "$log" ]]; then
        cp "$tmp" "$log"
        echo "Saved: $log"
    fi
    rm -f "$tmp"
    return "$exit_code"
}

# ---------------------------------------------------------------------------
# Python extractor/generator (copies forms verbatim from the test file — no
# hand-authored MeTTa).
# ---------------------------------------------------------------------------
read -r -d '' PYGEN <<'PYEOF' || true
import re, sys
SRC = sys.argv[1]
MODE = sys.argv[2]                # "list" | "build"
WHICH = int(sys.argv[3]) if len(sys.argv) > 3 else 0
lines = open(SRC).read().splitlines()
text  = "\n".join(lines)

def code_only(line):
    out, instr = [], False
    for c in line:
        if c == '"': instr = not instr; out.append(c)
        elif c == ';' and not instr: break
        else: out.append(c)
    return "".join(out)

def decomment(line):
    return re.sub(r'^(\s*);{1,2} ?', r'\1', line)

# --- segment top-level forms (paren-balanced, comment/string aware) ---
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
                    "def"    if head.startswith("(= ")       else
                    "bang"   if head.startswith("!(")         else "other")
            yield kind, raw
            buf, started, depth = [], False, 0

imports = [r.rstrip("\n") for k, r in top_level_forms(text) if k == "import"]
defs    = [r for k, r in top_level_forms(text) if k == "def"]

# --- find the maintainers' commented runnable examples ---
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
        first = blk.splitlines()[0].strip()
        gen = re.search(r'runMoses\s+(\d+)', blk)
        fix = "metaPop2" if "metaPop2" in blk else "metaPop" if "metaPop" in blk else ""
        fix = "emptyStrategyMetaPop" if "emptyStrategyMetaPop" in blk else fix
        tbl = ("xortable" if "xortable" in blk else "bigtable" if "bigtable" in blk else
               "OR-table" if "True (Cons False (Cons True" in blk else
               "tic-tac-toe" if "random-player" in blk else "")
        g = gen.group(1) if gen else "?"
        print(f"  example {idx}: src line {ln:>3} | maxGen={g:>2} | start={fix or '-'} | data={tbl or '-'}")
    sys.exit(0)

# MODE == build
if WHICH < 1 or WHICH > len(examples):
    sys.stderr.write(f"example index out of range (have 1..{len(examples)})\n"); sys.exit(3)
ln, blk = examples[WHICH-1]

print("; AUTO-GENERATED demo driver — DO NOT EDIT.")
print(f"; Imports + fixtures copied verbatim from {SRC}.")
print(f"; Runnable example below copied verbatim from src line {ln} (comment markers stripped).")
print()
print("\n".join(imports))
print()
print("\n".join(defs))
print()
print('!(println! "================ MOSES run: begin ================")')
print(blk)
print('!(println! "================ MOSES run: end ==================")')
PYEOF

# ---------------------------------------------------------------------------
# Count available examples (for "example all")
# ---------------------------------------------------------------------------
example_count() {
    python3 -c "$PYGEN" "$ENTRY" list 2>/dev/null | grep -c 'example [0-9]' || echo 0
}

# ---------------------------------------------------------------------------
# Run a single numbered example; caller handles multi-example looping.
# ---------------------------------------------------------------------------
run_example() {
    local N="$1"
    local DRIVER_REL="deme/tests/_moses_demo_driver_${STAMP}_${N}.metta"
    local DRIVER="$REPO/$DRIVER_REL"

    if ! python3 -c "$PYGEN" "$ENTRY" build "$N" > "$DRIVER"; then
        local rc=$?
        rm -f "$DRIVER"
        (( rc == 3 )) && echo "ERROR: example $N is out of range. Use 'list' to see valid indices." >&2
        return "$rc"
    fi

    echo "Generated driver: $DRIVER_REL"
    echo "Running MOSES example #${N}.  Trace: $TRACE  |  head: $HEAD_N"
    echo "(Maintainers' commented examples — runnable but not CI-covered;"
    echo " may be slow or surface WIP behavior.)"
    echo "----------------------------------------------------------------"

    local exit_code=0
    run_traced "example-${N}-${STAMP}" -- "$RUN_SH" "$DRIVER_REL" || exit_code=$?

    rm -f "$DRIVER"
    echo "----------------------------------------------------------------"
    return "$exit_code"
}

# ---------------------------------------------------------------------------
# Subcommand dispatch
# ---------------------------------------------------------------------------
cmd="${1:-}"
shift || true

case "$cmd" in
    list)
        echo "Maintainers' runnable examples in $ENTRY_REL:"
        python3 -c "$PYGEN" "$ENTRY" list
        echo
        echo "Run one with:    $0 example <N>"
        echo "Run several:     $0 example <N1> <N2> ..."
        echo "Run all:         $0 example all"
        echo "Live test run:   $0 live"
        echo "Quiet mode:      $0 --trace summary example <N>"
        echo "First 30 lines:  $0 --trace partial --head 30 example <N>"
        ;;

    live)
        echo "Running entry-point test NON-silent (shows built-in optimizeDemes/"
        echo "runMoses output).  Trace: $TRACE  |  head: $HEAD_N"
        echo "----------------------------------------------------------------"
        run_traced "live-${STAMP}" -- "$RUN_SH" "$ENTRY_REL"
        echo "----------------------------------------------------------------"
        ;;

    example)
        if [[ $# -eq 0 ]]; then
            echo "usage: $0 [OPTIONS] example <N|all|N1 N2 ...>" >&2; exit 2
        fi

        if [[ "$1" == "all" ]]; then
            COUNT="$(example_count)"
            if (( COUNT == 0 )); then
                echo "No runnable examples found in $ENTRY_REL." >&2; exit 1
            fi
            echo "Running all $COUNT examples.  Trace: $TRACE  |  head: $HEAD_N"
            overall=0
            for i in $(seq 1 "$COUNT"); do
                echo
                echo "======== example $i / $COUNT ========"
                run_example "$i" || { overall=$?; echo "  (example $i exited $overall — continuing)"; }
            done
            (( overall == 0 )) || exit "$overall"
        else
            for N in "$@"; do
                if ! [[ "$N" =~ ^[1-9][0-9]*$ ]]; then
                    echo "ERROR: example index must be a positive integer, got '$N'" >&2; exit 2
                fi
            done
            overall=0
            multi=$(( $# > 1 ))
            for N in "$@"; do
                (( multi )) && { echo; echo "======== example $N ========"; }
                run_example "$N" || { overall=$?; (( multi )) && echo "  (example $N exited $overall — continuing)"; }
            done
            (( overall == 0 )) || exit "$overall"
        fi
        ;;

    *)
        cat <<EOF
usage:
  $0 [OPTIONS] list                    list runnable examples
  $0 [OPTIONS] live                    run entry-point test, non-silent
  $0 [OPTIONS] example <N>             run example N end-to-end
  $0 [OPTIONS] example <N1> <N2> ...   run several examples
  $0 [OPTIONS] example all             run every example

Options:
  --trace full|partial|summary   output verbosity  (default: full)
    full     stream everything; save full log
    partial  show first --head N lines, then line count; save full log
    summary  show markers + errors + tail --head lines; save full log
  --head N   lines to show in partial/summary  (default: 50)
  --no-log   skip writing a log file
  --log-dir DIR  override log directory (default: <REPO>/moses_demo_logs)

Examples:
  $0 list
  $0 example 4
  $0 --trace summary example 4 5
  $0 --trace partial --head 30 --no-log example all
  REPO=/workspace/metta-moses $0 example 4
EOF
        exit 2
        ;;
esac
