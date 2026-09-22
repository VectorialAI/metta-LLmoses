#!/usr/bin/env bash
# Influence is an explicit JSON parameter; implicit five-lever sweeps are retired.
set -euo pipefail
if [[ $# != 3 ]]; then echo "usage: $0 CONFIG RUNDIR DRIVER" >&2; exit 2; fi
exec bash "$(dirname "$0")/../run_m2.sh" "$1" "$2" "$3" pair_policy
