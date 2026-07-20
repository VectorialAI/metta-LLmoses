#!/usr/bin/env bash
# Demonstrate atom-combination utility estimates as a lambda dial.
set -u
if [[ $# -ne 4 ]]; then echo "usage: $0 <mode> <lambda-list> <reps> <outdir>" >&2; exit 2; fi
MODE="$1"; LAMBDAS="$2"; REPS="$3"; OUTDIR="$4"
SEED_BASE="${LLMOSES_SWEEP_SEED_BASE:-41000}"
REPO="${REPO:-$PWD}"
cd "$REPO" || { echo "ERROR: cannot cd to repo root '$REPO'" >&2; exit 2; }
RUN_SH="$(command -v run.sh 2>/dev/null || true)"
[[ -z "$RUN_SH" && -x /opt/PeTTa/run.sh ]] && RUN_SH=/opt/PeTTa/run.sh
[[ -z "$RUN_SH" ]] && RUN_SH="$(find / -name run.sh -type f -path '*PeTTa*' 2>/dev/null | head -n1 || true)"
[[ -n "$RUN_SH" && -x "$RUN_SH" ]] || { echo "ERROR: could not locate PeTTa run.sh" >&2; exit 2; }
WATCHER="$REPO/llmoses/utilities/llmoses_watcher.py"; [[ -f "$WATCHER" ]] || { echo "ERROR: watcher not found at $WATCHER" >&2; exit 2; }
mkdir -p "$OUTDIR" || { echo "ERROR: cannot create outdir '$OUTDIR'" >&2; exit 2; }
BLOCKS_CSV="$OUTDIR/blocks.csv"
REPORT="$OUTDIR/report.txt"
printf '%s\n' 'mode,lambda,rep,response_gen,clause_type,depth_bucket,n_combos,nonzero,contextual,synergy,first_pick_atoms,first_pick_degraded,first_pick_in_chosen,picks_total,picks_nondegraded,picks_in_chosen_nondegraded,degraded_picks,utility_ingest_schema_ok,utility_ingest_schema_bad,bias_degraded_rows,bias_applied_rows,combo_pick_rows' > "$BLOCKS_CSV"
DRIVER_STD_REL="llmoses/llmoses-tests/_lambda_sweep_std_$$.metta"
cat > "$REPO/$DRIVER_STD_REL" <<'METTA'
;; AUTO-GENERATED lambda-sweep standard driver (deleted on exit).
!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
!(println! (upt-result (booleanStateParity3Short)))
METTA
# LLMOSES_SWEEP_DRIVER=cull runs the longer resize-cull loop instead: its
# retained programs grow multi-literal clauses, so realized_cooccurrences
# evidence exists for the evidence_pair mock to read (std-scale runs did not
# reliably yield usable width-2 evidence in stored samples).
DRIVER_CULL_REL="llmoses/llmoses-tests/_lambda_sweep_cull_$$.metta"
cat > "$REPO/$DRIVER_CULL_REL" <<'METTA'
;; AUTO-GENERATED lambda-sweep culling driver (deleted on exit).
!(import! &self llmoses/llmoses-tests/boolean_pressure_test.metta)
(= (upCullRun)
   (let* (($result (runMoses 4 (parity3TargetCscore) 6 (parity3MetaPop)
                              0 3 (parity3Context) hillClimbing
                              100 10 2 1 2 0.002 1000))
          ($size (eval (OS.length $result))))
     $size))
!(println! (upt-cull (upCullRun)))
METTA
DRIVER_REL="$DRIVER_STD_REL"
[[ "${LLMOSES_SWEEP_DRIVER:-std}" == "cull" ]] && DRIVER_REL="$DRIVER_CULL_REL"
WPID=""
RUN_DIRS=()
cleanup() {
  [[ -n "$WPID" ]] && kill "$WPID" 2>/dev/null
  rm -f "$REPO/$DRIVER_STD_REL" "$REPO/$DRIVER_CULL_REL"
  local d
  for d in "${RUN_DIRS[@]}"; do
    rm -rf "$d"
  done
}
trap cleanup EXIT
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
  local lambda="$2"
  local seed="$3"
  local t0 rc wall
  t0=$(date +%s)
  env \
    LLMOSES_RUN_DIR="$rundir" \
    LLMOSES_AWAIT_RESPONSE=1 \
    LLMOSES_RESPONSE_TIMEOUT_S=30 \
    LLMOSES_RESPONSE_POLL_S=0.05 \
    LLMOSES_APPLY_LEVERS=atom_prior \
    LLMOSES_LEVER_WEIGHT_ATOM_PRIOR="$lambda" \
    LLMOSES_RNG_SEED="$seed" \
    "$RUN_SH" "$DRIVER_REL" > "$rundir/run.log" 2>&1
  rc=$?
  wall=$(( $(date +%s) - t0 ))
  echo "  run rc=$rc wall=${wall}s"
  return "$rc"
}
lambda_path_token() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'
}
extract_blocks() {
  local rundir="$1"
  local lambda="$2"
  local rep="$3"
  MODE="$MODE" LAMBDA="$lambda" REP="$rep" RUNDIR="$rundir" OUT_CSV="$BLOCKS_CSV" python3 - <<'PY'
import csv, json, os
from decimal import Decimal, InvalidOperation
FIELDS = ("mode,lambda,rep,response_gen,clause_type,depth_bucket,n_combos,"
          "nonzero,contextual,synergy,first_pick_atoms,first_pick_degraded,"
          "first_pick_in_chosen,picks_total,picks_nondegraded,"
          "picks_in_chosen_nondegraded,degraded_picks,utility_ingest_schema_ok,"
          "utility_ingest_schema_bad,bias_degraded_rows,bias_applied_rows,"
          "combo_pick_rows").split(",")
def lambda_zero(s):
    try: return Decimal(str(s)) == 0
    except InvalidOperation: return False
def b(v):
    return "true" if bool(v) else "false"
def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
def chosen_of(rundir, gen):
    """(prior_atoms, synergy_sets) scored 1.0 in the response file. Synergy
    stays a set of unordered sets — a union would falsely accept cross-set
    combinations when more than one set is scored 1.0."""
    prior, sets_ = set(), set()
    if gen in (None, ""):
        return prior, sets_
    path = os.path.join(rundir, "utilities", "run-1", f"step-{int(gen)}.json")
    try:
        doc = read_json(path)
    except (FileNotFoundError, ValueError, TypeError):
        return prior, sets_
    for e in doc.get("atom_utility_prior") or []:
        try:
            if float(e.get("utility")) == 1.0 and e.get("atom") is not None:
                prior.add(str(e["atom"]))
        except (TypeError, ValueError):
            pass
    for e in doc.get("combination_synergy") or []:
        try:
            is_one = float(e.get("utility")) == 1.0
        except (TypeError, ValueError):
            is_one = False
        if is_one:
            sets_.add(frozenset(str(a) for a in (e.get("atoms") or [])))
    return prior, sets_
def pick_atoms(pick):
    atoms = pick.get("atoms") if isinstance(pick, dict) else None
    return sorted(str(a) for a in atoms) if isinstance(atoms, list) else []
def in_chosen(pick, prior, sets_):
    atoms = set(pick_atoms(pick))
    if not atoms:
        return False
    if prior and atoms.issubset(prior):
        return True
    return frozenset(atoms) in sets_
def block_row(block, picks, counts):
    prior, sets_ = chosen_of(os.environ["RUNDIR"], block.get("response_gen"))
    first = picks[0] if picks else None
    nondeg = [p for p in picks if p.get("degraded") is False]
    return {
        "mode": os.environ["MODE"],
        "lambda": os.environ["LAMBDA"],
        "rep": os.environ["REP"],
        "response_gen": block.get("response_gen", ""),
        "clause_type": block.get("clause_type", ""),
        "depth_bucket": block.get("depth_bucket", ""),
        "n_combos": block.get("n_combos", 0),
        "nonzero": block.get("nonzero", 0),
        "contextual": b(block.get("contextual")),
        "synergy": b(block.get("synergy")),
        "first_pick_atoms": "|".join(pick_atoms(first)) if first else "",
        "first_pick_degraded": b(first.get("degraded")) if first else "",
        "first_pick_in_chosen": b(in_chosen(first, prior, sets_)) if first else "",
        "picks_total": len(picks),
        "picks_nondegraded": len(nondeg),
        "picks_in_chosen_nondegraded": sum(1 for p in nondeg
                                           if in_chosen(p, prior, sets_)),
        "degraded_picks": sum(1 for p in picks if p.get("degraded") is True),
        **counts,
    }
def sentinel(counts):
    row = {f: "" for f in FIELDS}
    row.update({"mode": os.environ["MODE"], "lambda": os.environ["LAMBDA"],
                "rep": os.environ["REP"], "n_combos": 0, "nonzero": 0,
                "picks_total": 0, "picks_nondegraded": 0,
                "picks_in_chosen_nondegraded": 0, "degraded_picks": 0,
                **counts})
    return row
def extract_rows(rundir):
    counts = {"utility_ingest_schema_ok": 0, "utility_ingest_schema_bad": 0,
              "bias_degraded_rows": 0, "bias_applied_rows": 0,
              "combo_pick_rows": 0}
    blocks, cur, picks = [], None, []
    path = os.path.join(rundir, "moses_native_log.jsonl")
    try:
        fh = open(path, encoding="utf-8")
    except FileNotFoundError:
        return [sentinel(counts)]
    with fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            ev = row.get("event")
            if ev == "utility_ingest":
                if cur is not None:
                    blocks.append((cur, picks))
                    cur, picks = None, []
                if row.get("schema_ok") is True:
                    counts["utility_ingest_schema_ok"] += 1
                else:
                    counts["utility_ingest_schema_bad"] += 1
                continue
            if ev == "bias_degraded":
                counts["bias_degraded_rows"] += 1
            if ev == "bias_applied":
                counts["bias_applied_rows"] += 1
                if cur is not None:
                    blocks.append((cur, picks))
                if row.get("lever") == "atom_prior":
                    cur, picks = row, []
                else:
                    cur, picks = None, []
                continue
            if ev == "combo_pick":
                counts["combo_pick_rows"] += 1
                if cur is not None:
                    picks.append(row)
    if cur is not None:
        blocks.append((cur, picks))
    rows = [block_row(block, picks, counts) for block, picks in blocks]
    return [sentinel(counts)] if lambda_zero(os.environ["LAMBDA"]) or not rows else rows
rows = extract_rows(os.environ["RUNDIR"])
with open(os.environ["OUT_CSV"], "a", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=FIELDS)
    writer.writerows(rows)
PY
}
for lambda in $LAMBDAS; do
  rep=1
  while [[ "$rep" -le "$REPS" ]]; do
    echo "=== mode=$MODE lambda=$lambda rep=$rep/$REPS ==="
    new_rundir; rundir="$CUR_RUNDIR"
    start_watcher "$MODE" "$rundir"
    # Matched-seed assignment: rep N gets the same seed at every lambda.
    # Note this pairs seeds, not random variates — the native (lambda=0)
    # and weighted paths consume the RNG differently, and trajectories
    # diverge after the first differing pick.
    run_driver "$rundir" "$lambda" "$((SEED_BASE + rep))"; rc=$?
    stop_watcher
    extract_blocks "$rundir" "$lambda" "$rep"
    if [[ "$rep" -eq 1 ]]; then
      token="$(lambda_path_token "$lambda")"
      sample="$OUTDIR/sample-rundir-lambda-$token"
      rm -rf "$sample"
      mv "$rundir" "$sample"
    else
      rm -rf "$rundir"
    fi
    if [[ "$rc" -ne 0 ]]; then
      echo "ERROR: driver failed for lambda=$lambda rep=$rep" >&2
      exit 1
    fi
    rep=$((rep + 1))
  done
done
MODE="$MODE" LAMBDAS="$LAMBDAS" REPS="$REPS" OUTDIR="$OUTDIR" python3 - "$BLOCKS_CSV" <<'PY' | tee "$REPORT"
import csv, json, math, os, sys
from decimal import Decimal, InvalidOperation
blocks_csv = sys.argv[1]
mode = os.environ["MODE"]
lambdas = os.environ["LAMBDAS"].split()
reps = int(os.environ["REPS"])
outdir = os.environ["OUTDIR"]
def dec(s):
    try: return Decimal(str(s))
    except InvalidOperation: return Decimal("NaN")
def num(row, key):
    try: return int(row.get(key) or 0)
    except ValueError: return 0
def is_true(v):
    return str(v).lower() == "true"
def wilson(k, n):
    if n <= 0:
        return None
    z = 1.959963984540054
    phat = k / n
    den = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / den
    half = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n) / den
    return center - half, center + half
def fmt_share(k, n):
    if n <= 0:
        return "n/a"
    ci = wilson(k, n)
    return f"{k / n:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]"
def expected(lam):
    try: return 1.0 / (1.0 + 2.0 * (1.0 - float(lam)))
    except ValueError: return float("nan")
with open(blocks_csv, newline="", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
violations = []
run_rows = {}
for r in rows:
    run_rows.setdefault((r["lambda"], r["rep"]), r)
for lam in lambdas:
    for rep in range(1, reps + 1):
        if (lam, str(rep)) not in run_rows:
            violations.append(f"missing CSV rows for lambda={lam} rep={rep}")
print("REPORT")
print("lambda,n_blocks,first_pick_share_95ci,nondeg_picks_share,degraded_pick_rate,excluded_first_frac,expected_first_pick_share")
headline = {}
for lam in sorted(lambdas, key=dec):
    br = [r for r in rows if r["lambda"] == lam and num(r, "n_combos") == 6]
    first = [r for r in br if r.get("first_pick_degraded") == "false"]
    first_ok = sum(1 for r in first if is_true(r.get("first_pick_in_chosen")))
    first_n = len(first)
    pick_ok = sum(num(r, "picks_in_chosen_nondegraded") for r in br)
    pick_n = sum(num(r, "picks_nondegraded") for r in br)
    deg = sum(num(r, "degraded_picks") for r in br)
    total = sum(num(r, "picks_total") for r in br)
    headline[lam] = (first_ok / first_n) if first_n else None
    nondeg_share = "n/a" if pick_n == 0 else f"{pick_ok / pick_n:.3f}"
    deg_rate = "n/a" if total == 0 else f"{deg / total:.3f}"
    excl = ((len(br) - first_n) / len(br)) if br else 0.0
    if br and excl > 0.25:
        violations.append(f"lambda={lam}: {excl:.2f} of blocks excluded by a "
                          "degraded first pick (cap 0.25)")
    # Intermediate cells must not just be monotone: the measured share must
    # contain the theoretical first-pick share in its 95% Wilson interval.
    if 0 < dec(lam) < 1 and first_n:
        lo, hi = wilson(first_ok, first_n)
        exp = expected(lam)
        if not (lo <= exp <= hi):
            violations.append(f"lambda={lam}: expected first-pick share "
                              f"{exp:.3f} outside Wilson CI [{lo:.3f}, {hi:.3f}]")
    print(f"{lam},{len(br)},{fmt_share(first_ok, first_n)},{nondeg_share},{deg_rate},{excl:.3f},{expected(lam):.3f}")
# Every run at every lambda must have a live handshake: >=2 schema-ok
# ingests. Without this, a rep whose watcher died (sentinel row, zero
# counts) could silently prop up a passing cell.
for (lam, rep), r in sorted(run_rows.items(), key=lambda kv: (dec(kv[0][0]), int(kv[0][1]))):
    if num(r, "utility_ingest_schema_ok") < 2:
        violations.append(f"lambda={lam} rep={rep} had utility_ingest_schema_ok={num(r, 'utility_ingest_schema_ok')} (< 2)")
for lam in lambdas:
    if dec(lam) == 0:
        for rep in range(1, reps + 1):
            r = run_rows.get((lam, str(rep)))
            if not r:
                continue
            if num(r, "bias_applied_rows") != 0 or num(r, "combo_pick_rows") != 0:
                violations.append(f"lambda=0 rep={rep} had bias_applied={num(r, 'bias_applied_rows')} combo_pick={num(r, 'combo_pick_rows')}")
    if dec(lam) == 1:
        br = [r for r in rows if r["lambda"] == lam and num(r, "n_combos") == 6
              and r.get("first_pick_degraded") == "false"]
        if not br or any(not is_true(r.get("first_pick_in_chosen")) for r in br):
            violations.append(f"lambda=1 first-pick share was not 1.0 over non-degraded 6-combo blocks")
prev = None
for lam in sorted((l for l in lambdas if dec(l) > 0), key=dec):
    share = headline.get(lam)
    if share is None:
        violations.append(f"lambda={lam} had no non-degraded 6-combo first picks")
        continue
    if prev is not None and share < prev[1]:
        violations.append(f"headline share decreased from lambda={prev[0]} to lambda={lam}")
    prev = (lam, share)
for (lam, rep), r in sorted(run_rows.items(), key=lambda kv: (dec(kv[0][0]), int(kv[0][1]))):
    if num(r, "utility_ingest_schema_bad") != 0:
        violations.append(f"lambda={lam} rep={rep} had schema_bad={num(r, 'utility_ingest_schema_bad')}")
if mode == "evidence_pair":
    print()
    print("EVIDENCE CHAIN")
    def labels_width(run_config):
        alphabet = run_config.get("atom_alphabet") or {}
        labels = [a.get("label") for a in alphabet.get("atoms") or []
                  if a.get("label") is not None]
        return labels, 3 if alphabet.get("problem_type") == "strategy" else 2
    def members_of(e, key_to_label):
        out = []
        for m in e.get("members") or []:
            raw = m.get("atom") if isinstance(m, dict) else m
            out.append(key_to_label.get(raw, raw))
        return tuple(sorted(str(m) for m in out if m is not None))
    def evidence_winner(state, run_config):
        labels, width = labels_width(run_config)
        key_to_label = {a.get("key"): a.get("label")
                        for a in (run_config.get("atom_alphabet") or {}).get("atoms") or []}
        label_set, best = set(labels), None
        for e in (state.get("atom_evidence") or {}).get("realized_cooccurrences") or []:
            members = members_of(e, key_to_label)
            if e.get("width") != width or len(members) != width or not set(members).issubset(label_set):
                continue
            count = int(e.get("count") or 0)
            if best is None or count > best[0] or (count == best[0] and members < best[1]):
                best = (count, members, e)
        return best
    def log_rows(sample):
        path = os.path.join(sample, "moses_native_log.jsonl")
        try:
            with open(path, encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]
        except FileNotFoundError:
            return []
    def first_for(rows, pred):
        return next((r for r in rows if pred(r)), None)
    for lam in sorted(lambdas, key=dec):
        token = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in lam)
        sample = os.path.join(outdir, f"sample-rundir-lambda-{token}")
        rc_path = os.path.join(sample, "state", "run-1", "run_config.json")
        if not os.path.exists(rc_path):
            continue
        run_config = json.load(open(rc_path, encoding="utf-8"))
        lrows = log_rows(sample)
        print(f"sample lambda={lam} path={sample}")
        util_dir = os.path.join(sample, "utilities", "run-1")
        for name in sorted(os.listdir(util_dir), key=lambda n: int(n[5:-5]) if n.startswith("step-") else -1):
            if not name.startswith("step-") or not name.endswith(".json"):
                continue
            gen = int(name[5:-5])
            state_path = os.path.join(sample, "state", "run-1", name)
            if not os.path.exists(state_path):
                continue
            state = json.load(open(state_path, encoding="utf-8"))
            util = json.load(open(os.path.join(util_dir, name), encoding="utf-8"))
            win = evidence_winner(state, run_config)
            syn = [e for e in util.get("combination_synergy") or []
                   if float(e.get("utility", -1.0)) == 1.0]
            ingest = first_for(lrows, lambda r, g=gen: r.get("event") == "utility_ingest" and r.get("generation") == g)
            bias = first_for(lrows, lambda r, g=gen: r.get("event") == "bias_applied" and r.get("response_gen") == g)
            pick = None
            if bias is not None:
                seen = False
                for row in lrows:
                    if row is bias:
                        seen = True
                        continue
                    if seen and row.get("event") == "combo_pick":
                        pick = row
                        break
                    if seen and row.get("event") in ("bias_applied", "utility_ingest"):
                        break
            wtxt = None if win is None else {"members": list(win[1]), "count": win[0],
                                             "clause_type": win[2].get("clause_type")}
            print(f"  gen={gen} evidence={json.dumps(wtxt, sort_keys=True)} synergy_1={json.dumps(syn[:1], sort_keys=True)} ingest={json.dumps(ingest, sort_keys=True)} bias={json.dumps(bias, sort_keys=True)} first_pick={json.dumps(pick, sort_keys=True)}")
print()
if violations:
    for v in violations:
        print(f"VERDICT FAIL: {v}")
    sys.exit(1)
# The verdict names only the proofs this invocation actually exercised —
# an endpoint that was not in the lambda list is reported as such, never
# claimed.
proofs = []
if any(dec(l) == 0 for l in lambdas):
    proofs.append("lambda=0 native proof")
if any(dec(l) == 1 for l in lambdas):
    proofs.append("lambda=1 hard constraint")
if any(0 < dec(l) < 1 for l in lambdas):
    proofs.append("intermediate cells monotone and theory-contained")
proofs.append("ingest and schema_ok checks")
missing = [e for e, present in (("lambda=0", any(dec(l) == 0 for l in lambdas)),
                                ("lambda=1", any(dec(l) == 1 for l in lambdas)))
           if not present]
suffix = f" (endpoints not exercised: {', '.join(missing)})" if missing else ""
print(f"VERDICT PASS: {', '.join(proofs)} passed{suffix}")
PY
rc=${PIPESTATUS[0]}
exit "$rc"
