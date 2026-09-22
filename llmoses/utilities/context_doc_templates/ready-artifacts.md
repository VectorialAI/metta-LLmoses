# Ready artifacts

ready/run-N-step-G-call-C is published after state and action. Responders write
utilities/traces durably before response/run-N-step-G-call-C, then consume ready.
Read capture_status. Timeouts pause with a checkpoint; no silent native fallback.
