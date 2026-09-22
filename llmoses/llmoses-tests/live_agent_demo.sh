#!/usr/bin/env bash
# Explicit protocol-2 live demo: CONFIG RUNDIR DRIVER.
set -euo pipefail
if [[ $# != 3 ]]; then echo "usage: $0 CONFIG RUNDIR DRIVER" >&2; exit 2; fi
exec bash "$(dirname "$0")/../run_m2.sh" "$1" "$2" "$3" live
