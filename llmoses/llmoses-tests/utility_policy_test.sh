#!/usr/bin/env bash
# ===========================================================================
# Phase II utility-policy functionality test.
#
# Proves the mock UtilityResponse levers are ingested and applied end to end:
#
#   Phase 1  - INGEST: utility rows are consumed and visible in-loop.
#   Phase 2  - EXEMPLAR: exemplar-selection utilities control the chosen seed.
#   Phase 3  - CULL: culling utilities avoid protected retention targets.
#   Phase 4  - DOMUNIT: dominated-candidate escape is gated by culling.
#   Phase 5  - COMPARATOR: comparator ordering re-sorts the metapopulation.
#   Phase 6  - RATIO: complexity-ratio deltas persist and affect scoring.
#   Phase 7  - ATOM: atom priors constrain non-degraded combination picks.
#   Phase 8  - CTXOP: parent_operator-conditioned priors partition draw pools
#              by the clause operator at the draw site (D-033).
#   Phase 9  - CTXDEPTH: depth_bucket-conditioned priors partition draw pools
#              by the depth band of the clause being created (D-033).
#   Phase 10 - CTXPOL: polarity-conditioned priors steer picks to the
#              order-encoded negated combinations (D-033).
#   Phase 11 - SYNERGY: combination_synergy alone (no per-atom prior)
#              constrains non-degraded picks to the chosen atom set (D-033).
#   Phase 12 - OFFSWITCH: disabled, zero-weight, and neutral responses stay
#              native — including contextual and synergy responses, and the
#              inner-axis converse (entries present, lever_weights all absent).
#
# This needs the PeTTa runtime (run.sh) + PYTHONPATH for llmoses/utilities, so
# run it inside the project container. From the repo root:
#
#   docker run --rm -v "$(pwd):/workspace/metta-moses" -w /workspace/metta-moses \
#     metta-llmoses bash llmoses/llmoses-tests/utility_policy_test.sh
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

# Throwaway drivers for the standard 3-generation run, resize-cull run, and
# dominated-escape unit probe. They are deleted on exit.
DRIVER_STD_REL="llmoses/llmoses-tests/_utility_policy_std_$$.metta"
DRIVER_CULL_REL="llmoses/llmoses-tests/_utility_policy_cull_$$.metta"
DRIVER_DOM_REL="llmoses/llmoses-tests/_utility_policy_domunit_$$.metta"

cat > "$REPO/$DRIVER_STD_REL" <<'METTA'
;; AUTO-GENERATED utility-policy standard driver (deleted on exit).
!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
!(println! (upt-result (booleanStateParity3Short)))
METTA

cat > "$REPO/$DRIVER_CULL_REL" <<'METTA'
;; AUTO-GENERATED utility-policy culling driver (deleted on exit).
!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
(= (upCullRun)
   (let* (($result (runMoses 4 (parity3TargetCscore) 6 (parity3MetaPop)
                              0 3 (parity3Context) hillClimbing
                              100 10 2 1 2 0.002 1000))
          ($size (eval (OS.length $result))))
     $size))
!(println! (upt-cull (upCullRun)))
METTA

cat > "$REPO/$DRIVER_DOM_REL" <<'METTA'
;; AUTO-GENERATED utility-policy dominated-escape driver (deleted on exit).
!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
(= (mkTestEx $sym $b1 $b2)
   (mkExemplar (mkTree (mkNode $sym) Nil) (mkDemeId "t")
               (mkCscore 0 1 0.0 0.0 0)
               (mkBScore (Cons $b1 (Cons $b2 Nil)))))
(= (domEscapeProbe)
   (let* (($_r (sbNewRun))
          ($_a (sbAwaitResponse 0))
          ($a (mkTestEx AAA 0 0))
          ($b (mkTestEx BBB -1 -1))
          ($out (removeDominated (Cons $b (Cons $a Nil))))
          ($n (eval (List.length $out))))
     $n))
!(println! (dom-unit-kept (domEscapeProbe)))
METTA

WPID=""
RUN_DIRS=()
cleanup() {
  [[ -n "$WPID" ]] && kill "$WPID" 2>/dev/null
  rm -f "$REPO/$DRIVER_STD_REL" "$REPO/$DRIVER_CULL_REL" "$REPO/$DRIVER_DOM_REL"
  local d
  for d in "${RUN_DIRS[@]}"; do
    rm -rf "$d"
  done
}
trap cleanup EXIT

fail=0
pass() { echo "  PASS: $1"; }
bad()  { echo "  FAIL: $1"; fail=1; }

count_files() { find "$1" -type f "${@:2}" 2>/dev/null | wc -l | tr -d ' '; }
count_grep()  { local n; n="$(grep -c "$1" "$2" 2>/dev/null)"; echo "${n:-0}"; }

# Sets CUR_RUNDIR in the parent shell (a $(new_rundir) substitution would run
# in a subshell and the RUN_DIRS cleanup registration would be lost).
new_rundir() {
  CUR_RUNDIR="$(mktemp -d)" || { echo "ERROR: mktemp failed" >&2; exit 2; }
  RUN_DIRS+=("$CUR_RUNDIR")
}

start_watcher() {
  local mode="$1"
  local rundir="$2"
  LLMOSES_MOCK_UTILITY_MODE="$mode" python3 "$WATCHER" "$rundir" > "$rundir/watcher.log" 2>&1 &
  WPID=$!
  sleep 0.5
}

stop_watcher() {
  if [[ -n "$WPID" ]]; then
    sleep 0.7
    kill "$WPID" 2>/dev/null
    wait "$WPID" 2>/dev/null
    WPID=""
  fi
}

run_driver() {
  local rundir="$1"
  local driver_rel="$2"
  local apply="$3"
  shift 3
  local t0 rc wall
  t0=$(date +%s)
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
    "$RUN_SH" "$driver_rel" > "$rundir/run.log" 2>&1
  rc=$?
  wall=$(( $(date +%s) - t0 ))
  echo "  run rc=$rc wall=${wall}s"
  return "$rc"
}

assert_run_ok() {
  local label="$1"
  local rc="$2"
  [[ "$rc" -eq 0 ]] && pass "$label run completed" || bad "$label run rc=$rc (expected 0)"
}

seed_domunit_response() {
  local rundir="$1"
  mkdir -p "$rundir/utilities/run-1" "$rundir/response"
  cat > "$rundir/utilities/run-1/step-0.json" <<'JSON'
{"pass": false, "sampling_temperature": null, "culling_utilities": [{"program_id": "*", "retention_utility": 1.0}]}
JSON
  printf 'ok\n' > "$rundir/response/run-1-step-0"
}

check_offswitch_run() {
  local label="$1"
  local mode="$2"
  local apply="$3"
  shift 3
  local rundir rc out pyrc

  echo
  echo "=== Phase 12${label}: OFFSWITCH mode=${mode} apply='${apply}' ==="
  new_rundir; rundir="$CUR_RUNDIR"
  start_watcher "$mode" "$rundir"
  run_driver "$rundir" "$DRIVER_STD_REL" "$apply" "$@"; rc=$?
  stop_watcher
  assert_run_ok "OFFSWITCH ${label}" "$rc"

  out="$(RUNDIR="$rundir" python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl")
bias = 0
ingest = 0
try:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") == "bias_applied":
                bias += 1
            if row.get("event") == "utility_ingest":
                ingest += 1
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if bias != 0:
    print(f"bias_applied={bias}")
    sys.exit(1)
if ingest < 2:
    print(f"utility_ingest={ingest}")
    sys.exit(1)
print(f"bias_applied=0 utility_ingest={ingest}")
PY
)"
  pyrc=$?
  [[ "$pyrc" -eq 0 ]] && pass "OFFSWITCH ${label} no bias_applied rows and >=2 ingests" \
                       || bad "OFFSWITCH ${label} no bias_applied rows and >=2 ingests: $out"
}

# ---------------------------------------------------------------------------
echo "=== Phase 1: INGEST mode=ingest_probe apply='' ==="
new_rundir; T_INGEST="$CUR_RUNDIR"
start_watcher ingest_probe "$T_INGEST"
run_driver "$T_INGEST" "$DRIVER_STD_REL" ""; rc=$?
stop_watcher
assert_run_ok "INGEST" "$rc"

out="$(RUNDIR="$T_INGEST" python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl")
count = 0
try:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") == "utility_ingest" and row.get("decline") is False:
                count += 1
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if count < 2:
    print(f"non_decline_utility_ingest={count}")
    sys.exit(1)
print(f"non_decline_utility_ingest={count}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "INGEST wrote >=2 non-decline utility_ingest rows" \
                     || bad "INGEST wrote >=2 non-decline utility_ingest rows: $out"

out="$(RUNDIR="$T_INGEST" python3 - <<'PY'
import os, sys
path = os.path.join(os.environ["RUNDIR"], "run.log")
try:
    text = open(path, encoding="utf-8").read()
except FileNotFoundError:
    print("run.log missing")
    sys.exit(1)
needles = [
    "[utility] gen 2: from-step 1",
    "(UtilityBuffer gen 2",
    "[utility] gen 1: buffer empty (native)",
]
missing = [n for n in needles if n not in text]
if missing:
    print("missing " + ", ".join(missing))
    sys.exit(1)
print("utility buffer log lines present")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "INGEST run.log shows gen-1 empty and gen-2 buffered utility" \
                     || bad "INGEST run.log shows gen-1 empty and gen-2 buffered utility: $out"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 2: EXEMPLAR mode=force_worst apply=exemplar_selection ==="
new_rundir; T_EXEMPLAR="$CUR_RUNDIR"
start_watcher force_worst "$T_EXEMPLAR"
run_driver "$T_EXEMPLAR" "$DRIVER_STD_REL" "exemplar_selection"; rc=$?
stop_watcher
assert_run_ok "EXEMPLAR" "$rc"

out="$(RUNDIR="$T_EXEMPLAR" python3 - <<'PY'
import glob, json, os, re, sys

rd = os.environ["RUNDIR"]

def gen_of(path):
    m = re.search(r"step-(\d+)\.json$", path)
    return int(m.group(1)) if m else -1

checked = 0
errors = []
for state_path in sorted(glob.glob(os.path.join(rd, "state", "run-1", "step-*.json")), key=gen_of):
    g = gen_of(state_path)
    if g < 2:
        continue
    util_path = os.path.join(rd, "utilities", "run-1", f"step-{g - 1}.json")
    if not os.path.exists(util_path):
        continue
    util = json.load(open(util_path, encoding="utf-8"))
    if util.get("pass") is not False:
        continue
    targets = [str(e.get("program_id")) for e in util.get("exemplar_utilities") or []
               if float(e.get("utility", -1.0)) == 1.0]
    if len(targets) != 1:
        errors.append(f"step {g}: target_count={len(targets)}")
        continue
    state = json.load(open(state_path, encoding="utf-8"))
    post = (state.get("moses_native_events") or {}).get("post_selection") or {}
    if post.get("selection_status") != "ok" or post.get("chosen_program_id") != targets[0]:
        errors.append(f"step {g}: selected={post.get('chosen_program_id')} status={post.get('selection_status')} target={targets[0]}")
    checked += 1
if errors:
    print("; ".join(errors[:3]))
    sys.exit(1)
if checked < 1:
    print("checked=0")
    sys.exit(1)
print(f"checked={checked}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "EXEMPLAR selected the utility-1.0 program for checked steps" \
                     || bad "EXEMPLAR selected the utility-1.0 program for checked steps: $out"

out="$(RUNDIR="$T_EXEMPLAR" python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl")
hits = 0
rows = 0
try:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") != "bias_applied" or row.get("lever") != "exemplar_selection":
                continue
            rows += 1
            native = row.get("native_probs") or []
            if not native:
                continue
            native_best = max(range(len(native)), key=lambda i: native[i])
            if native_best != row.get("chosen_index"):
                hits += 1
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if hits < 1:
    print(f"rows={rows} native_override_hits={hits}")
    sys.exit(1)
print(f"rows={rows} native_override_hits={hits}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "EXEMPLAR overrode at least one native-best selection" \
                     || bad "EXEMPLAR overrode at least one native-best selection: $out"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 3: CULL mode=cull_targets apply=culling ==="
new_rundir; T_CULL="$CUR_RUNDIR"
start_watcher cull_targets "$T_CULL"
run_driver "$T_CULL" "$DRIVER_CULL_REL" "culling"; rc=$?
stop_watcher
assert_run_ok "CULL" "$rc"

out="$(RUNDIR="$T_CULL" python3 - <<'PY'
import json, os, sys

rd = os.environ["RUNDIR"]
log_path = os.path.join(rd, "moses_native_log.jsonl")
checked = 0
errors = []

def step_name(value):
    try:
        n = int(float(value))
        return str(n)
    except (TypeError, ValueError):
        return str(value)

try:
    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") != "bias_applied" or row.get("lever") != "culling":
                continue
            if row.get("degraded"):
                continue
            util_path = os.path.join(rd, "utilities", "run-1",
                                     f"step-{step_name(row.get('response_gen'))}.json")
            if not os.path.exists(util_path):
                errors.append(f"missing {util_path}")
                continue
            util = json.load(open(util_path, encoding="utf-8"))
            protected = {str(e.get("program_id")) for e in util.get("culling_utilities") or []
                         if float(e.get("retention_utility", -1.0)) == 1.0}
            if str(row.get("culled_pid")) in protected:
                errors.append(f"protected culled pid={row.get('culled_pid')} response_gen={row.get('response_gen')}")
            checked += 1
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if errors:
    print("; ".join(errors[:3]))
    sys.exit(1)
if checked < 1:
    print("checked=0")
    sys.exit(1)
print(f"checked={checked}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "CULL never culled a utility-protected program" \
                     || bad "CULL never culled a utility-protected program: $out"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 4a: DOMUNIT apply=culling ==="
new_rundir; T_DOM_ON="$CUR_RUNDIR"
seed_domunit_response "$T_DOM_ON"
run_driver "$T_DOM_ON" "$DRIVER_DOM_REL" "culling"; rc=$?
assert_run_ok "DOMUNIT culling-on" "$rc"

out="$(RUNDIR="$T_DOM_ON" python3 - <<'PY'
import os, sys
path = os.path.join(os.environ["RUNDIR"], "run.log")
try:
    text = open(path, encoding="utf-8").read()
except FileNotFoundError:
    print("run.log missing")
    sys.exit(1)
if "(dom-unit-kept 2)" not in text:
    print("missing (dom-unit-kept 2)")
    sys.exit(1)
print("dom-unit-kept 2 present")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "DOMUNIT culling-on kept both exemplars" \
                     || bad "DOMUNIT culling-on kept both exemplars: $out"

out="$(RUNDIR="$T_DOM_ON" python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl")
count = 0
try:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") == "bias_applied" and row.get("lever") == "dominated_escape":
                count += 1
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if count < 1:
    print(f"dominated_escape_bias={count}")
    sys.exit(1)
print(f"dominated_escape_bias={count}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "DOMUNIT culling-on logged dominated_escape bias" \
                     || bad "DOMUNIT culling-on logged dominated_escape bias: $out"

echo
echo "=== Phase 4b: DOMUNIT apply='' ==="
new_rundir; T_DOM_OFF="$CUR_RUNDIR"
seed_domunit_response "$T_DOM_OFF"
run_driver "$T_DOM_OFF" "$DRIVER_DOM_REL" ""; rc=$?
assert_run_ok "DOMUNIT culling-off" "$rc"

out="$(RUNDIR="$T_DOM_OFF" python3 - <<'PY'
import os, sys
path = os.path.join(os.environ["RUNDIR"], "run.log")
try:
    text = open(path, encoding="utf-8").read()
except FileNotFoundError:
    print("run.log missing")
    sys.exit(1)
if "(dom-unit-kept 1)" not in text:
    print("missing (dom-unit-kept 1)")
    sys.exit(1)
print("dom-unit-kept 1 present")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "DOMUNIT culling-off kept one exemplar natively" \
                     || bad "DOMUNIT culling-off kept one exemplar natively: $out"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 5: COMPARATOR mode=reverse_order apply=comparator ==="
new_rundir; T_COMPARATOR="$CUR_RUNDIR"
start_watcher reverse_order "$T_COMPARATOR"
run_driver "$T_COMPARATOR" "$DRIVER_CULL_REL" "comparator"; rc=$?
stop_watcher
assert_run_ok "COMPARATOR" "$rc"

out="$(RUNDIR="$T_COMPARATOR" python3 - <<'PY'
import glob, json, os, re, sys

rd = os.environ["RUNDIR"]

def gen_of(path):
    m = re.search(r"step-(\d+)\.json$", path)
    return int(m.group(1)) if m else -1

checked = 0
errors = []
for state_path in sorted(glob.glob(os.path.join(rd, "state", "run-1", "step-*.json")), key=gen_of):
    g = gen_of(state_path)
    if g < 2:
        continue
    util_path = os.path.join(rd, "utilities", "run-1", f"step-{g - 1}.json")
    if not os.path.exists(util_path):
        continue
    util = json.load(open(util_path, encoding="utf-8"))
    ordering = ((util.get("comparator_bias") or {}).get("program_id_ordering") or [])
    if not ordering:
        continue
    state = json.load(open(state_path, encoding="utf-8"))
    members = [m.get("program_id") for m in (state.get("metapopulation") or {}).get("members") or []]
    ordering = [str(pid) for pid in ordering]
    if members != ordering:
        errors.append(f"step {g}: members={members} ordering={ordering}")
    checked += 1
if errors:
    print("; ".join(errors[:2]))
    sys.exit(1)
if checked < 1:
    print("checked=0")
    sys.exit(1)
print(f"checked={checked}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "COMPARATOR state member order matched utility ordering" \
                     || bad "COMPARATOR state member order matched utility ordering: $out"

out="$(RUNDIR="$T_COMPARATOR" python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl")
total = 0
try:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            total += int(row.get("comparator_overrides") or 0)
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if total <= 0:
    print(f"comparator_overrides={total}")
    sys.exit(1)
print(f"comparator_overrides={total}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "COMPARATOR logged comparator_overrides > 0" \
                     || bad "COMPARATOR logged comparator_overrides > 0: $out"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 6: RATIO mode=ratio_increase apply=complexity_ratio ==="
new_rundir; T_RATIO="$CUR_RUNDIR"
start_watcher ratio_increase "$T_RATIO"
run_driver "$T_RATIO" "$DRIVER_STD_REL" "complexity_ratio"; rc=$?
stop_watcher
assert_run_ok "RATIO" "$rc"

out="$(RUNDIR="$T_RATIO" python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl")
rows = []
try:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") == "bias_applied" and row.get("lever") == "complexity_ratio":
                rows.append(row)
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if len(rows) < 2:
    print(f"complexity_ratio_rows={len(rows)}")
    sys.exit(1)
news = [float(r["new"]) for r in rows]
if any(news[i] <= news[i - 1] for i in range(1, len(news))):
    print(f"not strictly increasing new={news}")
    sys.exit(1)
bad_delta = [r for r in rows if abs((float(r["new"]) - float(r["old"])) - 1.0) > 1e-9]
if bad_delta:
    print(f"bad_delta={bad_delta[0]}")
    sys.exit(1)
print(f"complexity_ratio_rows={len(rows)} new={news}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "RATIO logged >=2 +1.0 strictly increasing ratio changes" \
                     || bad "RATIO logged >=2 +1.0 strictly increasing ratio changes: $out"

out="$(RUNDIR="$T_RATIO" python3 - <<'PY'
import glob, json, os, re, sys

rd = os.environ["RUNDIR"]
found = None

def gen_of(path):
    m = re.search(r"step-(\d+)\.json$", path)
    return int(m.group(1)) if m else -1

for state_path in sorted(glob.glob(os.path.join(rd, "state", "run-1", "step-*.json")), key=gen_of):
    state = json.load(open(state_path, encoding="utf-8"))
    for m in (state.get("metapopulation") or {}).get("members") or []:
        c = m.get("complexity")
        p = (m.get("cscore") or {}).get("complexity_penalty")
        if isinstance(c, (int, float)) and isinstance(p, (int, float)) and p:
            ratio = c / p
            if ratio > 2.001:
                found = (os.path.basename(state_path), m.get("program_id"), ratio)
                break
    if found:
        break
if not found:
    print("no member ratio > 2.001")
    sys.exit(1)
print(f"found={found[0]} pid={found[1]} ratio={found[2]:.6f}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "RATIO produced a state member with complexity/penalty > 2.001" \
                     || bad "RATIO produced a state member with complexity/penalty > 2.001: $out"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 7: ATOM mode=atom_pair apply=atom_prior ==="
new_rundir; T_ATOM="$CUR_RUNDIR"
start_watcher atom_pair "$T_ATOM"
run_driver "$T_ATOM" "$DRIVER_STD_REL" "atom_prior"; rc=$?
stop_watcher
assert_run_ok "ATOM" "$rc"

out="$(RUNDIR="$T_ATOM" python3 - <<'PY'
import json, os, sys

rd = os.environ["RUNDIR"]
util_path = os.path.join(rd, "utilities", "run-1", "step-1.json")
try:
    util = json.load(open(util_path, encoding="utf-8"))
except FileNotFoundError:
    print("step-1 utility missing")
    sys.exit(1)
allowed = {str(e.get("atom")) for e in util.get("atom_utility_prior") or []
           if float(e.get("utility", -1.0)) == 1.0}
if not allowed:
    print("allowed atom set empty")
    sys.exit(1)

bias_rows = 0
combo_rows = 0
errors = []
log_path = os.path.join(rd, "moses_native_log.jsonl")
try:
    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") == "bias_applied" and row.get("lever") == "atom_prior":
                bias_rows += 1
            if row.get("event") == "combo_pick":
                combo_rows += 1
                if row.get("degraded") is False:
                    atoms = row.get("atoms")
                    if not isinstance(atoms, list):
                        errors.append(f"missing atoms for combo index={row.get('index')}")
                    elif not {str(a) for a in atoms}.issubset(allowed):
                        errors.append(f"atoms={atoms} allowed={sorted(allowed)}")
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if bias_rows < 1:
    print("atom_prior bias rows missing")
    sys.exit(1)
if combo_rows < 1:
    print("combo_pick rows missing")
    sys.exit(1)
if errors:
    print("; ".join(errors[:3]))
    sys.exit(1)
print(f"bias_rows={bias_rows} combo_rows={combo_rows} allowed={sorted(allowed)}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "ATOM constrained non-degraded combo picks to utility-1.0 atoms" \
                     || bad "ATOM constrained non-degraded combo picks to utility-1.0 atoms: $out"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 8: CTXOP mode=ctx_parent_op apply=atom_prior ==="
new_rundir; T_CTXOP="$CUR_RUNDIR"
start_watcher ctx_parent_op "$T_CTXOP"
run_driver "$T_CTXOP" "$DRIVER_STD_REL" "atom_prior"; rc=$?
stop_watcher
assert_run_ok "CTXOP" "$rc"

out="$(RUNDIR="$T_CTXOP" python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl")
or_full = and_empty = 0
errors = []
try:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") != "bias_applied" or row.get("lever") != "atom_prior":
                continue
            clause, nz, n = row.get("clause_type"), row.get("nonzero"), row.get("n_combos")
            if clause == "OR":
                if nz == n:
                    or_full += 1
                else:
                    errors.append(f"OR draw nonzero={nz}/{n}")
            elif clause == "AND":
                if nz == 0:
                    and_empty += 1
                else:
                    errors.append(f"AND draw nonzero={nz}/{n}")
            else:
                errors.append(f"unexpected clause_type={clause}")
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if errors:
    print("; ".join(errors[:3]))
    sys.exit(1)
if or_full < 1 or and_empty < 1:
    print(f"or_full={or_full} and_empty={and_empty}")
    sys.exit(1)
print(f"or_full={or_full} and_empty={and_empty}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "CTXOP pools full under OR clauses, empty under AND clauses" \
                     || bad "CTXOP pools full under OR clauses, empty under AND clauses: $out"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 9: CTXDEPTH mode=ctx_depth apply=atom_prior ==="
new_rundir; T_CTXDEPTH="$CUR_RUNDIR"
start_watcher ctx_depth "$T_CTXDEPTH"
run_driver "$T_CTXDEPTH" "$DRIVER_STD_REL" "atom_prior"; rc=$?
stop_watcher
assert_run_ok "CTXDEPTH" "$rc"

out="$(RUNDIR="$T_CTXDEPTH" python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl")
mid_full = other_empty = 0
errors = []
try:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") != "bias_applied" or row.get("lever") != "atom_prior":
                continue
            bucket, nz, n = row.get("depth_bucket"), row.get("nonzero"), row.get("n_combos")
            if bucket == "mid":
                if nz == n:
                    mid_full += 1
                else:
                    errors.append(f"mid draw nonzero={nz}/{n}")
            else:
                if nz == 0:
                    other_empty += 1
                else:
                    errors.append(f"{bucket} draw nonzero={nz}/{n}")
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if errors:
    print("; ".join(errors[:3]))
    sys.exit(1)
if mid_full < 1:
    print(f"mid_full={mid_full}")
    sys.exit(1)
print(f"mid_full={mid_full} other_empty={other_empty}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "CTXDEPTH mid-band pools full; non-mid draws (if any) empty" \
                     || bad "CTXDEPTH mid-band pools full; non-mid draws (if any) empty: $out"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 10: CTXPOL mode=ctx_polarity apply=atom_prior ==="
new_rundir; T_CTXPOL="$CUR_RUNDIR"
start_watcher ctx_polarity "$T_CTXPOL"
run_driver "$T_CTXPOL" "$DRIVER_STD_REL" "atom_prior"; rc=$?
stop_watcher
assert_run_ok "CTXPOL" "$rc"

out="$(RUNDIR="$T_CTXPOL" python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["RUNDIR"], "moses_native_log.jsonl")
picks = 0
errors = []
try:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") != "combo_pick" or row.get("degraded") is not False:
                continue
            picks += 1
            lits = row.get("literals")
            if not isinstance(lits, list) or not any(
                    isinstance(l, str) and l.startswith("-") for l in lits):
                errors.append(f"literals={lits}")
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if errors:
    print("; ".join(errors[:3]))
    sys.exit(1)
if picks < 1:
    print("no non-degraded picks")
    sys.exit(1)
print(f"non_degraded_picks={picks} all contain a negated literal")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "CTXPOL non-degraded picks all carry a negated literal" \
                     || bad "CTXPOL non-degraded picks all carry a negated literal: $out"

# ---------------------------------------------------------------------------
echo
echo "=== Phase 11: SYNERGY mode=synergy_pair apply=atom_prior ==="
new_rundir; T_SYNERGY="$CUR_RUNDIR"
start_watcher synergy_pair "$T_SYNERGY"
run_driver "$T_SYNERGY" "$DRIVER_STD_REL" "atom_prior"; rc=$?
stop_watcher
assert_run_ok "SYNERGY" "$rc"

out="$(RUNDIR="$T_SYNERGY" python3 - <<'PY'
import json, os, sys

rd = os.environ["RUNDIR"]
util_path = os.path.join(rd, "utilities", "run-1", "step-1.json")
try:
    util = json.load(open(util_path, encoding="utf-8"))
except FileNotFoundError:
    print("step-1 utility missing")
    sys.exit(1)
allowed = set()
for e in util.get("combination_synergy") or []:
    if float(e.get("utility", -1.0)) == 1.0:
        allowed.update(str(a) for a in e.get("atoms") or [])
if not allowed:
    print("allowed synergy atom set empty")
    sys.exit(1)
if util.get("atom_utility_prior"):
    print("atom_utility_prior unexpectedly non-empty")
    sys.exit(1)

bias_syn = picks = 0
errors = []
log_path = os.path.join(rd, "moses_native_log.jsonl")
try:
    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if (row.get("event") == "bias_applied"
                    and row.get("lever") == "atom_prior"
                    and row.get("synergy")):
                bias_syn += 1
            if row.get("event") == "combo_pick" and row.get("degraded") is False:
                picks += 1
                atoms = row.get("atoms")
                if not isinstance(atoms, list) or \
                        not {str(a) for a in atoms}.issubset(allowed):
                    errors.append(f"atoms={atoms} allowed={sorted(allowed)}")
except FileNotFoundError:
    print("native log missing")
    sys.exit(1)
if errors:
    print("; ".join(errors[:3]))
    sys.exit(1)
if bias_syn < 1 or picks < 1:
    print(f"bias_synergy_rows={bias_syn} non_degraded_picks={picks}")
    sys.exit(1)
print(f"bias_synergy_rows={bias_syn} non_degraded_picks={picks} allowed={sorted(allowed)}")
PY
)"
pyrc=$?
[[ "$pyrc" -eq 0 ]] && pass "SYNERGY alone constrained non-degraded picks to the chosen atom set" \
                     || bad "SYNERGY alone constrained non-degraded picks to the chosen atom set: $out"

# ---------------------------------------------------------------------------
check_offswitch_run "a" force_worst ""
check_offswitch_run "b" force_worst "exemplar_selection" LLMOSES_LEVER_WEIGHT_EXEMPLAR_SELECTION=0
check_offswitch_run "c" neutral "exemplar_selection,culling,comparator,complexity_ratio,atom_prior"
check_offswitch_run "d" ctx_parent_op ""
check_offswitch_run "e" synergy_pair "atom_prior" LLMOSES_LEVER_WEIGHT_ATOM_PRIOR=0
# 12f: the INNER-axis converse — lever enabled, outer lambda 1, contextual +
# synergy entries present, but every response lever_weights axis absent.
# Ingest must prune the inert entries and the draw gate must stay native.
check_offswitch_run "f" ctx_zero_weights "atom_prior"

echo
if [[ $fail -eq 0 ]]; then
  echo "UTILITY POLICY TEST: PASS"
  exit 0
else
  echo "UTILITY POLICY TEST: FAIL"
  exit 1
fi
