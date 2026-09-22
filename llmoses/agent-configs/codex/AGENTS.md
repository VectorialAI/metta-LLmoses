# LLMOSES responder session (Codex CLI)

Act as the sole responder for this run directory. Read the estimation semantics
in `llmoses/skills/*.md` (especially `ROLE.md`, `ACTION_LEVERS.md`,
`SCORING_SELECTION.md`, and the domain skill) before estimating. The skills,
not this file, define UtilityResponse field shapes.

1. Claim the run before reading a ready marker:
   `python3 llmoses/utilities/agent_tools.py claim RUNDIR --mode agent:codex --session SESSION`.
   The printed `session` token is your identity for every later tool call
   (each call is a new process, so a pid cannot identify you): export it as
   `LLMOSES_RESPONDER_SESSION` or pass `--session` to `respond`, `abstain`,
   `heartbeat` and `release`. Record it and the printed protocol version /
   `LLMOSES_PROTOCOL_PIN` in run notes.
   The token is a coordination handle that keeps concurrent sub-processes
   from doubling, dropping or crossing responses; it is minted per run and
   is NOT a security control (anything with filesystem access can read it).
2. Start liveness immediately and keep it in the background:
   `python3 llmoses/utilities/agent_tools.py heartbeat RUNDIR --watch-pid $$ &`.
   The sandbox must have write access to the entire run directory.
3. Loop on `wait`. For each ready event, read its state and action, then obtain the legal
   slots. Do not read the operator-only run_config or run-instructions parameters. Obtain context with `history`, using
   `LLMOSES_CONTEXT_STRATEGY` (default `full_history`). Reason from those
   artifacts, preserving a concise auditable rationale.
4. Run `slots`, write a JSON values object (structured `policy` at Call 3), then call `respond` with the
   rationale and `--history FILE` (the saved `history` output you reasoned
   over, so context instrumentation is measured rather than asserted). It writes utilities, trace, response
   sentinel, and consumes ready in the required order. If `respond` rejects an
   unknown or invalid slot, correct the values and retry; never invent ids or
   bypass the slot mechanism.
5. Use `abstain` only for a deliberate native decision. Never leave a
   call unanswered. Use status 422 if `capture_status.ok` is false; 204
   only for deliberate abstention. If the run is unsalvageable, invoke `abort`
   with a clear reason rather than allowing silent continuation.
6. Stop the loop only when `wait` exits 10 (terminal), then `release` the
   responder claim. Treat abort/ownership/pin exits as run failures to report.

Transient provider failures may retry within the declared timeout budget;
persistent infrastructure failures require checkpointed pause and operator
resume. `wait` exit 13 means paused; repair the cause, then request resume.
Keep explicit rationale in AgentTrace. This is a single responder session;
do not use sub-agents. The current `gen` argument is G-call-C, not just G.
