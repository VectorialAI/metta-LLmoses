# AgentTrace

Write `traces/run-N/step-G-call-C.json` with the same fence as the response.
Record available input_state, input artifact paths, declared read files,
prompt/context manifest, raw provider outputs, parsed_utility_response,
status/outcome, attempts, diagnostics, context strategy/load/truncation,
protocol version and concise audit_reasoning. Do not reconstruct hidden
chain-of-thought. Tokens are recorded only when actually measured.

Keep previous states, replies and rationale together in context. Checkpointing
persists trace contents and run-local summaries, not just their filenames.
Provider failures and retries belong in the trace even if the call later works.
