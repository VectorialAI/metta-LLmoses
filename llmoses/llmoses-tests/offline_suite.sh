#!/usr/bin/env bash
# Offline Python suite: every protocol-2 unit test that does not need PeTTa or Docker.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m unittest \
  agent_tools_test \
  atom_evidence_test \
  config_context_test \
  hardening_unit_test \
  lever_policy_test \
  lever_wiring_test \
  live_estimator_test \
  overlay_imports_test \
  provider_adapter_test \
  resolution_regression_test \
  response_template_test \
  runtime_verifier_test \
  scoring_test \
  silent_failure_test \
  supervisor_test
