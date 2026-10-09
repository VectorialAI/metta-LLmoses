# Run directories and responder lifecycle

Use a dedicated LLMOSES_RUN_DIR. Several runMoses calls may share the directory;
run-N namespaces increase monotonically. Calls use the fence (N,G,C), C=1..4.

- state/action/run-N/step-G-call-C.json: complete request, written before ready.
- ready/run-N-step-G-call-C: outstanding request marker.
- utilities/traces/run-N/step-G-call-C.json: response and transcript.
- response/run-N-step-G-call-C: published last, after durable response files.
- ready/.consumed/: consumed markers.
- state/run-N/step-G.json: generation summary; terminal.json: final verdict.
- checkpoints/run-N/latest.json: RNG, evolution/continuation and agent context.
- context/run-N/summary.md: persistent agent summary; traces contain exchanges.
- moses_native_log.jsonl: site distributions, decisions, quality and lifecycle.
- CONTROL/: responder claim, heartbeat, pause_requested, pause, resume, abort.

LLMOSES_CONFIG points to experiment JSON. selection_temperature is explicit
(required, alternatively LLMOSES_SELECTION_TEMPERATURE). LLMOSES_AWAIT_RESPONSE=1
activates waiting; expected generations are selected by
LLMOSES_EXPECT_RESPONSE_GENS (all, none, integer/range list). b=0 calls skip the
responder and bypass sharpening. Await-disabled and out-of-window calls are
recorded as native by design.

Claim one responder; retain the returned session token for every agent tool
mutation. Wait returns seq and gen; gen is the composite string G-call-C. Use it
unchanged in slots/respond/abstain/trace/history. Numeric ordering includes call.
An older run's terminal is not completion of a later active run.

The response timeout is per call (default 300s); heartbeat stall default 120s.
Timeout, dead responder, persistent infrastructure failure or supervisor stall
pause instead of silently running a guided arm natively. Resume only after
repairing the cause: `agent_tools.py resume RUNDIR` publishes the exact pause
fence. A stale resume cannot unlock another call. Abort is an explicit operator
choice and writes a durable terminal before a nonzero exit.

Cold recovery uses the same code/protocol and native runtime. Set
LLMOSES_RESUME_CHECKPOINT to latest.json and import the original driver definitions
before invoking `(sbResume)` instead of `(runMoses ...)`. Use the same run directory
and responder settings, then issue resume for a persisted pause. The checkpoint
restores Python RNG, native continuation atoms and saved context. Runtime replay
and cache behavior must be verified in the deferred testing phase.

Live watcher context defaults to full history. LLMOSES_CONTEXT_MAX_CHARS=0 means
no truncation. A positive limit requires LLMOSES_CONTEXT_TRUNCATION=oldest to
discard prior exchanges; otherwise overflow is a configuration failure and
pauses. Current input is never truncated. Agent tools also support
rolling_summary and retrieval with explicit budgets and dropped-call records.
Context artifacts and provider outputs are persisted for replay.
