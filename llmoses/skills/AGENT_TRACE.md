# AgentTrace

Write exactly one valid JSON object to `traces/run-N/step-G.json` for each processed ready sentinel.

AgentTrace is the per-step transcript and audit artifact. It is the canonical location for reasoning, diagnostics, and provider interaction records. It should include transcript material and explicit audit reasoning available to the harness, not hidden model chain-of-thought.

Recommended top-level fields:

```json
{
  "schema_version": "agent-trace-v0",
  "record_type": "AgentTrace",
  "run_seq": "1",
  "generation": "1",
  "timestamp_ms": 0,
  "ready_sentinel": "ready/run-1-step-1",
  "input_artifacts": {
    "state_path": "state/run-1/step-1.json",
    "action_path": "action/run-1/step-1.json",
    "run_config_path": "state/run-1/run_config.json",
    "native_log_path": "moses_native_log.jsonl"
  },
  "read_files": [],
  "prompt_context_manifest": [],
  "provider": null,
  "raw_model_response": "",
  "parsed_utility_response": {},
  "audit_reasoning": [],
  "parse_diagnostics": []
}
```

For a stub or failed provider call, still write AgentTrace with whatever input paths, diagnostics, and parsed fallback UtilityResponse are available.
