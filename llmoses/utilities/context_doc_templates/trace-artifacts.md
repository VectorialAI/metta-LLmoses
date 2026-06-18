# Trace Artifacts

This file is generated and may be deleted with its run directory. Use
`llmoses/skills/AGENT_TRACE.md` for the canonical AgentTrace guide.

Trace files are written under `traces/run-N/` as `step-G.json`.

Each file is an AgentTrace transcript and audit artifact for the matching
UtilityResponse. It should include available prompt/context manifests, read-file
lists, raw model responses, parsed UtilityResponse JSON, explicit audit
reasoning, provider metadata, and parse/error diagnostics.

Do not require or attempt to reconstruct hidden model chain-of-thought. Store
only transcript material and explicit reasoning or audit notes available to the
harness.
