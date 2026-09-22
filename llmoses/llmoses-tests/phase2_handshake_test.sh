#!/usr/bin/env bash
# Protocol-2 offline replacement. Native integration: m2_runtime_test.sh.
set -euo pipefail
exec bash "$(dirname "$0")/offline_suite.sh"
