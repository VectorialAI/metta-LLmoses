#!/usr/bin/env bash
# ===========================================================================
# Reverse-check runner (PLAN-m2-hardening.md §8.C): every new M2 test must
# FAIL against the pre-hardening tree, or it is testing nothing.
#
# Creates a detached git worktree at BASE_REF (default a7b64f1, the last
# pre-hardening commit), copies ONLY the new test files into it, runs them
# there, and reports. A test that PASSES on the base tree is flagged.
#
# Usage (from the repo root, host):
#   bash llmoses/llmoses-tests/reverse_check.sh [BASE_REF] [--docker]
# --docker also runs failure_injection_test.sh on the base tree inside the
# metta-llmoses container (slow: several minutes).
# Exit 0 = every new suite fails on the base tree (reverse-check holds).
# ===========================================================================
set -u
REPO="${REPO:-$PWD}"
cd "$REPO" || exit 2
BASE_REF="a7b64f1"
DOCKER=0
for a in "$@"; do
  case "$a" in
    --docker) DOCKER=1 ;;
    *) BASE_REF="$a" ;;
  esac
done

HOST_TESTS=(hardening_unit_test.py provider_adapter_test.py agent_tools_test.py supervisor_test.py)
# GNU timeout is not stock on macOS; run bare when absent.
TIMEOUT=""
command -v timeout >/dev/null 2>&1 && TIMEOUT="timeout 300"
WT="$(mktemp -d)/base"
git worktree add --detach "$WT" "$BASE_REF" >/dev/null 2>&1 || { echo "ERROR: cannot create worktree at $BASE_REF" >&2; exit 2; }
cleanup() { git worktree remove --force "$WT" >/dev/null 2>&1; rm -rf "$(dirname "$WT")"; }
trap cleanup EXIT
echo "base tree: $WT @ $(git -C "$WT" rev-parse --short HEAD)"

# The new responder-side modules are copied as well, so a suite fails on the
# base tree because the MOSES-side / contract behaviour is absent — not merely
# because a module file is missing.
NEW_MODULES=(responder_control.py provider_adapter.py protocol_version.py agent_tools.py supervisor.py)
for m in "${NEW_MODULES[@]}"; do
  [[ -f "llmoses/utilities/$m" ]] && cp "llmoses/utilities/$m" "$WT/llmoses/utilities/$m"
done

bad=0
for t in "${HOST_TESTS[@]}"; do
  src="llmoses/llmoses-tests/$t"
  [[ -f "$src" ]] || { echo "  SKIP: $t (not present)"; continue; }
  cp "$src" "$WT/llmoses/llmoses-tests/$t"
  out="$(cd "$WT" && $TIMEOUT python3 "llmoses/llmoses-tests/$t" 2>&1)"; rc=$?
  npass=$(printf '%s\n' "$out" | grep -c "PASS:")
  nfail=$(printf '%s\n' "$out" | grep -c "FAIL:")
  if [[ $rc -ne 0 ]]; then
    echo "  REVERSE-CHECK OK: $t fails on base (rc=$rc, $nfail FAIL / $npass PASS lines)"
  else
    echo "  REVERSE-CHECK BROKEN: $t PASSES on base (rc=0) — it tests nothing new"
    bad=1
  fi
done

if [[ $DOCKER -eq 1 ]]; then
  cp llmoses/llmoses-tests/failure_injection_test.sh "$WT/llmoses/llmoses-tests/"
  out="$(docker run --rm -v "$WT:/workspace/metta-moses" -w /workspace/metta-moses metta-llmoses \
          bash llmoses/llmoses-tests/failure_injection_test.sh 2>&1)"; rc=$?
  npass=$(printf '%s\n' "$out" | grep -c "PASS:")
  nfail=$(printf '%s\n' "$out" | grep -c "FAIL:")
  printf '%s\n' "$out" | grep -E "^=== |PASS:|FAIL:" | sed 's/^/    /'
  if [[ $rc -ne 0 ]]; then
    echo "  REVERSE-CHECK OK: failure_injection_test.sh fails on base (rc=$rc, $nfail FAIL / $npass PASS)"
  else
    echo "  REVERSE-CHECK BROKEN: failure_injection_test.sh PASSES on base"
    bad=1
  fi
fi

if [[ $bad -eq 0 ]]; then echo "REVERSE CHECK: OK"; else echo "REVERSE CHECK: BROKEN"; fi
exit $bad
