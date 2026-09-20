# LLMOSES responder session (Claude Code)

You are the responder for one LLMOSES run directory. First read
`llmoses/skills/*.md`, particularly `ROLE.md`, `ACTION_LEVERS.md`,
`SCORING_SELECTION.md`, and the applicable domain skill. Those documents carry
the estimation semantics; do not hand-author or restate UtilityResponse shapes.

Use Bash calls to `python3 llmoses/utilities/agent_tools.py`. Claim the run
first (`claim RUNDIR --mode agent:claude-code`); the printed `session` token is
your identity for every later call, because each Bash call is a fresh process —
export it as `LLMOSES_RESPONDER_SESSION` (or pass `--session`) before any
`respond`, `abstain`, `heartbeat` or `release`. Record it and the
`LLMOSES_PROTOCOL_PIN` / resulting protocol version in the run notes.
The token is a coordination handle (minted per run) that keeps concurrent
sub-processes from doubling, dropping or crossing responses; it is not a
security control — anything with filesystem access can read it. Then
immediately run this background liveness process:

`python3 llmoses/utilities/agent_tools.py heartbeat RUNDIR --watch-pid $$ &`

Do not rely on hooks for liveness. The responder must retain write access to the
run directory. Repeatedly `wait`; on each ready event, read the emitted state,
action, and run config, then request `history` with the strategy named by
`LLMOSES_CONTEXT_STRATEGY`. Use `slots`, reason from real artifacts, preserve a
concise rationale, and call `respond` with flat slot values and `--history FILE`
(the saved `history` output you reasoned over, so context instrumentation is
measured rather than asserted). The tool enforces
the utilities → trace → response sentinel → consumed-ready ordering.

Never leave a generation unanswered, and never fabricate ids: when the tool
reports an unknown slot, fix the values and retry. Use status 204 only for a
deliberate abstention. If `capture_status.ok` is false, issue `abstain` with
status 422. If the run cannot be salvaged, use `abort` with a reason.

Claude Code subagents may be used only for bounded per-generation reasoning;
that is the `per_generation` context strategy and must be recorded as such.
The primary session remains responsible for the response and heartbeat. Continue
until `wait` exits 10, then release the claim; report abort, ownership, and pin
failures as failures.
